"""
Ultima 7 palette handler.

Provides :class:`U7Palette` for loading palettes from ``PALETTES.FLX``
or standalone ``.pal`` files.

``PALETTES.FLX`` is a standard Flex archive containing 12 palettes.
Each palette is 768 bytes: 256 RGB triplets with values 0–63 (VGA 6-bit
range).  Palette 0 is the main daytime palette used by most graphics.

Special colour indices:

* **255** — always transparent
* **224–254** — colour-cycling / translucent effects (engine-managed)

Example::

    from titan.u7.palette import U7Palette

    # Load all palettes from PALETTES.FLX (palette 0 is the default)
    pal = U7Palette.from_file("PALETTES.FLX")  # uses palette 0
    swatch = pal.to_pil_image()
    swatch.save("palette_0.png")

    # Load a specific palette index
    pal3 = U7Palette.from_file("PALETTES.FLX", palette_index=3)
"""

from __future__ import annotations

__all__ = ["U7Palette"]

from PIL import Image

PALETTE_SIZE = 768  # 256 * 3


class U7Palette:
    """
    Ultima 7 palette reader.

    Loads palettes from ``PALETTES.FLX`` (Flex archive) or standalone
    768-byte ``.pal`` files.  Values are scaled from VGA 6-bit (0–63)
    to 8-bit (0–255).
    """

    def __init__(self) -> None:
        self.colors: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
        self.transparent_index: int = 255
        self.palette_index: int = 0

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str, *,
                  palette_index: int = 0) -> U7Palette:
        """Load a palette from ``PALETTES.FLX`` or a raw ``.pal`` file.

        If *filepath* is a Flex archive, extract record *palette_index*
        and parse the 768-byte palette data within.  Otherwise treat
        the file as raw palette bytes.
        """
        with open(filepath, "rb") as f:
            data = f.read()

        # Detect Flex archive by the magic at offset 0x50.
        if len(data) >= 0x58 and data[0x50:0x54] == b'\x00\x1a\xff\xff':
            return cls._from_flex(data, palette_index)

        # Standalone raw palette (768 or 772 bytes with optional header).
        return cls.from_raw_bytes(data, palette_index=palette_index)

    @classmethod
    def _from_flex(cls, data: bytes, palette_index: int) -> U7Palette:
        """Extract palette record from an in-memory Flex archive."""
        import struct

        count = struct.unpack_from("<I", data, 0x54)[0]
        if palette_index < 0 or palette_index >= count:
            raise ValueError(
                f"Palette index {palette_index} out of range "
                f"(archive has {count} records)")

        tbl_off = 0x80 + palette_index * 8
        rec_off = struct.unpack_from("<I", data, tbl_off)[0]
        rec_len = struct.unpack_from("<I", data, tbl_off + 4)[0]

        if rec_off == 0 or rec_len == 0:
            raise ValueError(f"Palette record {palette_index} is empty")

        raw = data[rec_off:rec_off + rec_len]
        return cls.from_raw_bytes(raw, palette_index=palette_index)

    @classmethod
    def from_raw_bytes(cls, data: bytes, *,
                       palette_index: int = 0) -> U7Palette:
        """Parse palette from raw bytes (768 bytes of RGB triplets).

        If data has a 4-byte header (772 bytes) like U8 palettes, skip it.
        """
        pal = cls()
        pal.palette_index = palette_index

        if len(data) >= 772 and len(data) < PALETTE_SIZE * 2:
            # Skip 4-byte header (U8-style PAL files have this).
            raw = data[4:4 + PALETTE_SIZE]
        elif len(data) >= PALETTE_SIZE:
            raw = data[:PALETTE_SIZE]
        else:
            raise ValueError(
                f"Palette data too small: {len(data)} bytes "
                f"(need at least {PALETTE_SIZE})")

        # Detect whether palette stores 6-bit VGA values (0-63) or full
        # 8-bit values (0-255).  Only check indices 0-254; index 255 is
        # always transparent and often contains garbage values that would
        # defeat the detection (e.g. raw 250, 64, 1 in U7 PALETTES.FLX).
        needs_scale = all(raw[j] <= 63 for j in range(255 * 3))

        for i in range(256):
            r = raw[i * 3]
            g = raw[i * 3 + 1]
            b = raw[i * 3 + 2]
            if needs_scale and i != 255:
                pal.colors[i] = (
                    (r * 255) // 63,
                    (g * 255) // 63,
                    (b * 255) // 63,
                )
            else:
                pal.colors[i] = (r, g, b)

        return pal

    # ------------------------------------------------------------------
    # Flex enumeration helper
    # ------------------------------------------------------------------

    @classmethod
    def palette_count(cls, filepath: str) -> int:
        """Return the number of palettes in a ``PALETTES.FLX`` archive."""
        import struct
        with open(filepath, "rb") as f:
            data = f.read(0x58)
        if len(data) < 0x58 or data[0x50:0x54] != b'\x00\x1a\xff\xff':
            return 1  # standalone PAL file
        return struct.unpack_from("<I", data, 0x54)[0]

    # ------------------------------------------------------------------
    # Output helpers (match U8Palette API)
    # ------------------------------------------------------------------

    def to_flat_rgb(self) -> bytes:
        """Return 768 bytes of flat RGB data (for PIL ``putpalette``)."""
        flat = bytearray(PALETTE_SIZE)
        for i, (r, g, b) in enumerate(self.colors):
            flat[i * 3] = r
            flat[i * 3 + 1] = g
            flat[i * 3 + 2] = b
        return bytes(flat)

    def to_pil_image(self, swatch_size: int = 16) -> Image.Image:
        """Create a 16×16 grid swatch image of the palette."""
        img = Image.new("RGB", (16 * swatch_size, 16 * swatch_size))
        px = img.load()
        for idx in range(256):
            row, col = divmod(idx, 16)
            r, g, b = self.colors[idx]
            for py in range(swatch_size):
                for ppx in range(swatch_size):
                    px[col * swatch_size + ppx,
                       row * swatch_size + py] = (r, g, b)
        return img

    def to_text(self) -> str:
        """Return a plain-text listing of all 256 colour entries."""
        lines = [f"# Palette {self.palette_index} — 256 entries (R G B, 0-255)"]
        for i, (r, g, b) in enumerate(self.colors):
            lines.append(f"{i:3d}: {r:3d} {g:3d} {b:3d}")
        return "\n".join(lines)

    @staticmethod
    def default_palette() -> U7Palette:
        """Generate a fallback greyscale palette."""
        pal = U7Palette()
        for i in range(256):
            pal.colors[i] = (i, i, i)
        return pal
