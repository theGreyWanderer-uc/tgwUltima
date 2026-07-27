"""
Color palette reader for Ultima 9: Ascension's ``static/ankh.pal``.

Used to color 8-bit (paletted) texture frames -- see the ``palette``
parameter on :func:`titan.u9.texture.decode_frame`. Format confirmed
directly against the real file: exactly 1024 bytes = 256 entries * 4
bytes each (R, G, B, unused) -- the 4th byte was 0 in every entry
checked.

The reference Blender importer has a commented-out, never-finished
``readPalette()``/``readColor8_alpha()`` pair that reads this same file
in **B, G, R, A** order and forces alpha to 1.0 -- that byte order
turned out to be wrong for this file. It was cross-checked here
against real data instead: the same "default" placeholder texture
appears in both ``bitmap16.flx`` (16-bit, independently confirmed
correct -- a magenta/pink zebra-stripe pattern) and ``bitmapsh.flx``
(8-bit, paletted). Decoding the 8-bit copy through this palette in
**R, G, B** order reproduces a matching magenta/pink color family;
decoding it in B, G, R order instead produces a mismatched
blue-dominant result. R, G, B is what's implemented here.

Without a palette, 8-bit textures fall back to flat grayscale (see
:mod:`titan.u9.texture`) -- real, but visually flatter than intended;
passing this palette recovers the real, colorful result (confirmed:
sampling 200 entries from each of ``bitmap16.flx``/``bitmapC.flx``/
``bitmapsh.flx``, palette lookup never raised an index error, i.e.
every observed raw byte value is a valid 0-255 palette index).

Example::

    from titan.u9.palette import U9Palette
    from titan.u9.texture import decode_frame

    palette = U9Palette.from_file("static/ankh.pal")
    frame = decode_frame(entry_data, palette=palette)
"""

from __future__ import annotations

__all__ = ["U9Palette", "U9PaletteError"]

import os

PALETTE_ENTRY_COUNT = 256
ENTRY_SIZE = 4
EXPECTED_SIZE = PALETTE_ENTRY_COUNT * ENTRY_SIZE


class U9PaletteError(Exception):
    """Raised when palette data is too small to hold 256 entries."""


class U9Palette:
    """256-entry RGB color table, decoded from ``static/ankh.pal``."""

    def __init__(self, data: bytes) -> None:
        if len(data) < EXPECTED_SIZE:
            raise U9PaletteError(f"palette data too small: {len(data)} bytes (need {EXPECTED_SIZE})")
        self.colors: tuple[tuple[int, int, int], ...] = tuple(
            (data[i * ENTRY_SIZE], data[i * ENTRY_SIZE + 1], data[i * ENTRY_SIZE + 2])
            for i in range(PALETTE_ENTRY_COUNT)
        )

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Palette:
        with open(filepath, "rb") as f:
            return cls(f.read())

    def color_for(self, index: int) -> tuple[int, int, int]:
        return self.colors[index]

    def __len__(self) -> int:
        return len(self.colors)
