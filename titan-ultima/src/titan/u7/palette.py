"""
Ultima 7 palette handler.

Provides :class:`U7Palette` for loading palettes from ``PALETTES.FLX``
or standalone ``.pal`` files.

``PALETTES.FLX`` is a standard Flex archive containing 12 palettes.
Each palette is 768 bytes: 256 RGB triplets with values 0–63 (VGA 6-bit
range).  Palette 0 is the main daytime palette used by most graphics.
Real archives commonly declare more table slots than they populate
(e.g. Black Gate's ``PALETTES.FLX`` declares 16 slots but only fills 12);
use :meth:`U7Palette.enumerate_slots` to see slot occupancy without
raising, and expect :class:`PaletteRecordEmptyError` from
:meth:`U7Palette.from_file`/:meth:`~U7Palette.from_raw_bytes` when asking
for a specific empty slot by index.

Special colour indices:

* **255** — reserved/context-dependent transparency.  RLE sprites treat
  it as transparent; flat (non-RLE) terrain tiles render it as an opaque
  colour like any other index.  Index 255's stored RGB bytes are also
  commonly garbage in real archives and are preserved as-is rather than
  scaled or interpreted.
* **224–254** — colour-cycling / translucent effects (engine-managed)

Example::

    from titan.u7.palette import U7Palette

    # Load all palettes from PALETTES.FLX (palette 0 is the default)
    pal = U7Palette.from_file("PALETTES.FLX")  # uses palette 0
    swatch = pal.to_pil_image()
    swatch.save("palette_0.png")

    # Load a specific palette index
    pal3 = U7Palette.from_file("PALETTES.FLX", palette_index=3)

    # Enumerate slot occupancy without raising on empty/invalid slots
    for slot in U7Palette.enumerate_slots("PALETTES.FLX"):
        print(slot.index, slot.is_empty, slot.is_valid)
"""

from __future__ import annotations

__all__ = [
    "U7Palette",
    "PaletteSlot",
    "PaletteRecordEmptyError",
    "PaletteRecordInvalidError",
]

import struct
from dataclasses import dataclass
from typing import Literal, Optional

from PIL import Image

PALETTE_SIZE = 768  # 256 * 3

# Flex archive header layout (see titan.u7.flex.U7FlexArchive for the full
# format).  Duplicated here (rather than imported) because this module only
# needs the handful of fields required to locate palette records.
_FLEX_MAGIC = b"\x00\x1a\xff\xff"
_FLEX_MAGIC_OFFSET = 0x50
_FLEX_COUNT_OFFSET = 0x54
_FLEX_TABLE_OFFSET = 0x80
_FLEX_TABLE_ENTRY_SIZE = 8

PaletteEncoding = Literal["auto", "6bit", "8bit"]


def _slot_bounds_error(
    index: int, offset: int, length: int, data_len: int,
    occupied: list[tuple[int, int, int]],
) -> Optional[str]:
    """Return an error message if slot *index* is truncated or overlaps a
    previously validated slot in *occupied* (list of ``(start, end, index)``
    for already-accepted populated slots), else ``None``."""
    if offset + length > data_len:
        return (
            f"Record {index} truncated: offset 0x{offset:x} + length "
            f"{length} exceeds archive size {data_len}"
        )
    for start, end, other in occupied:
        if offset < end and start < offset + length:
            return f"Record {index} overlaps record {other}"
    return None


class PaletteRecordEmptyError(ValueError):
    """Raised when a specifically requested Flex palette slot has no data.

    Subclasses :class:`ValueError` so existing ``except ValueError`` call
    sites keep working unchanged.
    """


class PaletteRecordInvalidError(ValueError):
    """Raised for malformed, truncated, or out-of-bounds palette records
    or Flex record tables — as opposed to :class:`PaletteRecordEmptyError`,
    which means the slot is simply unused.

    Subclasses :class:`ValueError` so existing ``except ValueError`` call
    sites keep working unchanged.
    """


@dataclass
class PaletteSlot:
    """One entry in a Flex record table, inspected without decoding colors.

    ``index`` always reflects the real Flex slot number — callers must
    never compact/renumber slots when reporting or iterating them.
    """

    index: int
    offset: int
    length: int
    is_empty: bool
    is_valid: bool = True
    error: Optional[str] = None


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

        # Lossless/provenance metadata (see PaletteEncoding docstring below).
        self.raw_record: bytes = b""
        self.encoding: Literal["6bit", "8bit"] = "8bit"
        self.flex_index: Optional[int] = None
        self.source: str = ""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str, *,
                   palette_index: int = 0,
                   encoding: PaletteEncoding = "auto") -> U7Palette:
        """Load a palette from ``PALETTES.FLX`` or a raw ``.pal`` file.

        If *filepath* is a Flex archive, extract record *palette_index*
        and parse the 768-byte palette data within.  Otherwise treat
        the file as raw palette bytes.

        *encoding* controls 6-bit/8-bit component interpretation: ``"auto"``
        (default) detects it from the byte values, exactly as before.
        Pass ``"6bit"``/``"8bit"`` to force the interpretation instead of
        guessing — useful for standalone files where the heuristic is
        ambiguous (e.g. a palette that happens to be uniformly dark).
        """
        with open(filepath, "rb") as f:
            data = f.read()

        if len(data) >= 0x58 and data[_FLEX_MAGIC_OFFSET:_FLEX_MAGIC_OFFSET + 4] == _FLEX_MAGIC:
            pal = cls._from_flex(data, palette_index, encoding=encoding)
        else:
            pal = cls.from_raw_bytes(data, palette_index=palette_index, encoding=encoding)

        pal.source = str(filepath)
        return pal

    @classmethod
    def enumerate_slots(cls, filepath: str) -> list[PaletteSlot]:
        """Return every Flex table slot's ``(index, offset, length,
        is_empty, is_valid, error)`` without decoding any colors.

        For a standalone (non-Flex) file, returns a single implicit slot
        0 describing whether the file is large enough to be a palette.

        This never raises for empty or malformed *individual* slots —
        those are reported via ``is_empty``/``is_valid``/``error`` so a
        caller can enumerate a whole archive in one pass.  It does raise
        :class:`PaletteRecordInvalidError` if the record table itself is
        truncated (the file is too small to even contain the declared
        table), since there is nothing meaningful to enumerate then.
        """
        with open(filepath, "rb") as f:
            data = f.read()

        if len(data) < 0x58 or data[_FLEX_MAGIC_OFFSET:_FLEX_MAGIC_OFFSET + 4] != _FLEX_MAGIC:
            is_valid = len(data) >= PALETTE_SIZE
            error = None if is_valid else f"File too small: {len(data)} bytes"
            return [PaletteSlot(0, 0, len(data), is_empty=False, is_valid=is_valid, error=error)]

        count = struct.unpack_from("<I", data, _FLEX_COUNT_OFFSET)[0]
        table_end = _FLEX_TABLE_OFFSET + count * _FLEX_TABLE_ENTRY_SIZE
        if table_end > len(data):
            raise PaletteRecordInvalidError(
                f"Flex record table truncated: declares {count} slot(s) "
                f"(needs {table_end} bytes) but archive is only {len(data)} bytes"
            )

        slots: list[PaletteSlot] = []
        occupied: list[tuple[int, int, int]] = []  # (start, end, index) of valid populated slots
        for i in range(count):
            tbl_off = _FLEX_TABLE_OFFSET + i * _FLEX_TABLE_ENTRY_SIZE
            off, length = struct.unpack_from("<II", data, tbl_off)
            is_empty = off == 0 or length == 0
            error = None if is_empty else _slot_bounds_error(i, off, length, len(data), occupied)

            if not is_empty and error is None:
                occupied.append((off, off + length, i))

            slots.append(PaletteSlot(i, off, length, is_empty=is_empty, is_valid=error is None, error=error))

        return slots

    @classmethod
    def _from_flex(cls, data: bytes, palette_index: int, *,
                    encoding: PaletteEncoding = "auto") -> U7Palette:
        """Extract palette record from an in-memory Flex archive."""
        count = struct.unpack_from("<I", data, _FLEX_COUNT_OFFSET)[0]
        table_end = _FLEX_TABLE_OFFSET + count * _FLEX_TABLE_ENTRY_SIZE
        if table_end > len(data):
            raise PaletteRecordInvalidError(
                f"Flex record table truncated: declares {count} slot(s) "
                f"(needs {table_end} bytes) but archive is only {len(data)} bytes"
            )
        if palette_index < 0 or palette_index >= count:
            raise PaletteRecordInvalidError(
                f"Palette index {palette_index} out of range "
                f"(archive has {count} records)")

        tbl_off = _FLEX_TABLE_OFFSET + palette_index * _FLEX_TABLE_ENTRY_SIZE
        rec_off = struct.unpack_from("<I", data, tbl_off)[0]
        rec_len = struct.unpack_from("<I", data, tbl_off + 4)[0]

        if rec_off == 0 or rec_len == 0:
            raise PaletteRecordEmptyError(f"Palette record {palette_index} is empty")
        if rec_off + rec_len > len(data):
            raise PaletteRecordInvalidError(
                f"Palette record {palette_index} is truncated: offset "
                f"0x{rec_off:x} + length {rec_len} exceeds archive size {len(data)}"
            )

        raw = data[rec_off:rec_off + rec_len]
        pal = cls.from_raw_bytes(raw, palette_index=palette_index, encoding=encoding)
        pal.flex_index = palette_index
        return pal

    @classmethod
    def from_raw_bytes(cls, data: bytes, *,
                        palette_index: int = 0,
                        encoding: PaletteEncoding = "auto") -> U7Palette:
        """Parse palette from raw bytes (768 bytes of RGB triplets).

        If data has a 4-byte header (772 bytes) like U8 palettes, skip it.
        For interleaved "double" palettes (>=1536 bytes), use
        :meth:`from_double_bytes` instead — this method always treats its
        input as a single 768-colour table.
        """
        if encoding not in ("auto", "6bit", "8bit"):
            raise ValueError(
                f"Unknown encoding {encoding!r}; expected 'auto', '6bit', or '8bit'")

        pal = cls()
        pal.palette_index = palette_index
        pal.raw_record = bytes(data)

        if len(data) >= 772 and len(data) < PALETTE_SIZE * 2:
            # Skip 4-byte header (U8-style PAL files have this).
            payload = data[4:4 + PALETTE_SIZE]
        elif len(data) >= PALETTE_SIZE:
            payload = data[:PALETTE_SIZE]
        else:
            raise PaletteRecordInvalidError(
                f"Palette data too small: {len(data)} bytes "
                f"(need at least {PALETTE_SIZE})")

        # Detect whether palette stores 6-bit VGA values (0-63) or full
        # 8-bit values (0-255).  Only check indices 0-254; index 255 is
        # reserved/context-dependent and often contains garbage values that
        # would defeat the detection (e.g. raw 250, 64, 1 in U7 PALETTES.FLX).
        if encoding == "auto":
            needs_scale = all(payload[j] <= 63 for j in range(255 * 3))
        else:
            needs_scale = encoding == "6bit"
        pal.encoding = "6bit" if needs_scale else "8bit"

        for i in range(256):
            r = payload[i * 3]
            g = payload[i * 3 + 1]
            b = payload[i * 3 + 2]
            if needs_scale and i != 255:
                pal.colors[i] = (
                    (r * 255) // 63,
                    (g * 255) // 63,
                    (b * 255) // 63,
                )
            else:
                pal.colors[i] = (r, g, b)

        return pal

    @classmethod
    def from_double_bytes(cls, data: bytes, *,
                           encoding: PaletteEncoding = "auto"
                           ) -> tuple[U7Palette, U7Palette]:
        """Parse an interleaved "double" palette (>=1536 bytes), as used
        by Exult's ``Palette::set_loaded`` (see ``palette.cc``): even
        bytes form the primary 768-byte palette, odd bytes form a second
        768-byte palette (``pal2``, typically all-black in practice).

        Returns ``(primary, secondary)``.
        """
        if len(data) < PALETTE_SIZE * 2:
            raise PaletteRecordInvalidError(
                f"Double-palette data too small: {len(data)} bytes "
                f"(need at least {PALETTE_SIZE * 2})")

        primary_bytes = data[0:PALETTE_SIZE * 2:2]
        secondary_bytes = data[1:PALETTE_SIZE * 2:2]

        primary = cls.from_raw_bytes(primary_bytes, encoding=encoding)
        secondary = cls.from_raw_bytes(secondary_bytes, encoding=encoding)
        primary.raw_record = bytes(data)
        secondary.raw_record = bytes(data)
        return primary, secondary

    # ------------------------------------------------------------------
    # Flex enumeration helper
    # ------------------------------------------------------------------

    @classmethod
    def palette_count(cls, filepath: str) -> int:
        """Return the number of declared slots in a ``PALETTES.FLX``
        archive (including empty ones — see :meth:`enumerate_slots` to
        distinguish populated from empty/invalid slots)."""
        with open(filepath, "rb") as f:
            data = f.read(0x58)
        if len(data) < 0x58 or data[_FLEX_MAGIC_OFFSET:_FLEX_MAGIC_OFFSET + 4] != _FLEX_MAGIC:
            return 1  # standalone PAL file
        return struct.unpack_from("<I", data, _FLEX_COUNT_OFFSET)[0]

    # ------------------------------------------------------------------
    # Colour cycling
    # ------------------------------------------------------------------

    def at_cycle_phase(self, elapsed_ms: int, rot_speed_ms: Optional[int] = None) -> U7Palette:
        """Return a copy of this palette with Exult's six palette-cycling
        ranges rotated forward by ``elapsed_ms // rot_speed_ms`` steps,
        reproducing ``Game_window::rotatecolours()``'s per-tick rotation
        (see :mod:`titan.u7.palette_cycle`)."""
        from titan.u7.palette_cycle import DEFAULT_CYCLE_MS, apply_all_cycles

        steps = elapsed_ms // (rot_speed_ms or DEFAULT_CYCLE_MS)

        cycled = U7Palette()
        cycled.colors = apply_all_cycles(self.colors, steps=steps)
        cycled.transparent_index = self.transparent_index
        cycled.palette_index = self.palette_index
        cycled.raw_record = self.raw_record
        cycled.encoding = self.encoding
        cycled.flex_index = self.flex_index
        cycled.source = self.source
        return cycled

    # ------------------------------------------------------------------
    # Output helpers (match U8Palette API)
    # ------------------------------------------------------------------

    def to_raw_bytes(self) -> bytes:
        """Return the exact original record bytes as read from disk,
        unchanged — round-tripping an unmodified palette this way
        reproduces the source record byte-for-byte.  Contrast with
        :meth:`to_flat_rgb`, which returns the *expanded* 8-bit form used
        for rendering."""
        return self.raw_record

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
