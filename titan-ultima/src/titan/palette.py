"""
Ultima 8 palette reader (.pal files).

Provides the :class:`U8Palette` class for loading, manipulating, and
rendering Ultima 8 VGA 6-bit palettes.

Example::

    from titan.palette import U8Palette

    pal = U8Palette.from_file("U8PAL.PAL")
    swatch = pal.to_pil_image()
    swatch.save("palette.png")
"""

from __future__ import annotations

__all__ = ["U8Palette"]

from PIL import Image


class U8Palette:
    """
    Ultima 8 palette reader (.pal files).

    Binary layout::

        Offset 0x00, 4 bytes : Unknown header (often 00 00 00 01)
        Offset 0x04, 768 bytes: 256 RGB triplets, each 0–63 (VGA 6-bit range)

    Palette index 0 is typically transparent.
    Values are scaled from 0–63 to 0–255 via: ``out = (val * 255) // 63``.
    """

    HEADER_SIZE: int = 4
    PALETTE_DATA_SIZE: int = 768  # 256 * 3
    TOTAL_SIZE: int = HEADER_SIZE + PALETTE_DATA_SIZE

    def __init__(self) -> None:
        # 256 RGB tuples, 0-255 range
        self.colors: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
        self.transparent_index: int = 0  # Index treated as transparent

    @classmethod
    def from_file(cls, filepath: str) -> U8Palette:
        """Load a U8PAL.PAL file."""
        pal = cls()
        with open(filepath, "rb") as f:
            data = f.read()

        if len(data) < cls.TOTAL_SIZE:
            raise ValueError(f"Palette file too small: {len(data)} bytes "
                             f"(need {cls.TOTAL_SIZE})")

        # Skip 4-byte header, read 768 bytes of RGB data
        raw = data[cls.HEADER_SIZE:cls.HEADER_SIZE + cls.PALETTE_DATA_SIZE]
        for i in range(256):
            r = raw[i * 3]
            g = raw[i * 3 + 1]
            b = raw[i * 3 + 2]
            # Scale from VGA 6-bit (0-63) to 8-bit (0-255)
            pal.colors[i] = (
                (r * 255) // 63,
                (g * 255) // 63,
                (b * 255) // 63,
            )

        return pal

    @classmethod
    def from_raw_bytes(cls, data: bytes) -> U8Palette:
        """Load palette from raw bytes (with 4-byte header)."""
        pal = cls()
        if len(data) < cls.TOTAL_SIZE:
            raise ValueError(f"Palette data too small: {len(data)} bytes")
        raw = data[cls.HEADER_SIZE:cls.HEADER_SIZE + cls.PALETTE_DATA_SIZE]
        for i in range(256):
            r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
            pal.colors[i] = ((r * 255) // 63, (g * 255) // 63, (b * 255) // 63)
        return pal

    def to_flat_rgb(self) -> bytes:
        """Return 768 bytes of flat RGB data (for PIL ``putpalette``)."""
        flat = bytearray(768)
        for i, (r, g, b) in enumerate(self.colors):
            flat[i * 3] = r
            flat[i * 3 + 1] = g
            flat[i * 3 + 2] = b
        return bytes(flat)

    def to_pil_image(self, swatch_size: int = 16) -> Image.Image:
        """Create a 16x16 grid swatch image of the palette."""
        img = Image.new("RGB", (16 * swatch_size, 16 * swatch_size))
        pixels = img.load()
        for idx in range(256):
            row, col = divmod(idx, 16)
            r, g, b = self.colors[idx]
            for py in range(swatch_size):
                for px in range(swatch_size):
                    pixels[col * swatch_size + px, row * swatch_size + py] = (r, g, b)
        return img

    @staticmethod
    def default_palette() -> U8Palette:
        """Generate a fallback greyscale palette."""
        pal = U8Palette()
        for i in range(256):
            pal.colors[i] = (i, i, i)
        return pal
