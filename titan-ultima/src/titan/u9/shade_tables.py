"""Lossless readers for Ultima IX ``static/shade.tbl`` and ``static/shadegry.tbl``.

**Neither file is loaded by the retail game.** Retail 1.19F keeps a file-name
pointer for each (``0x007868B4`` and ``0x007868B8``) but nothing reads either
pointer and neither name appears anywhere else in ``u9.exe``. Both are
authoring-tool outputs shipped in ``static/``. Titan reads them as historical
data and does not use them for rendering.

Both are raw arrays of ``ankh.pal`` indices with no header:

``shade.tbl`` (8,192 bytes)
    32 light levels of 256 entries. ``output = table[level * 256 + index]``.
    Levels 0-15 and columns 0-9 and 246-255 hold one filler index (the
    palette's closest colour to magenta); levels 16-31 hold the shaded colour
    for each index, darkest first.

``shadegry.tbl`` (320 bytes)
    Four 16-step colour ramps (blue, beige, green, grey; darkest first),
    followed by a 256-entry red-tint translation of every palette index.

The layouts come from the authoring tool's builder and are confirmed on the
shipped bytes: each ramp resolves through ``ankh.pal`` to the builder's
endpoint colours, and every filler cell holds the same index.
"""

from __future__ import annotations

__all__ = [
    "EDITOR_COLOR_TABLE_SIZE",
    "RAMP_LENGTH",
    "RAMP_NAMES",
    "SHADE_FILLER_COLUMNS",
    "SHADE_LEVEL_COUNT",
    "SHADE_LIT_LEVELS",
    "SHADE_TABLE_SIZE",
    "U9EditorColorTable",
    "U9ShadeTable",
    "U9ShadeTableError",
]

import os
from pathlib import Path

PALETTE_SIZE = 256
SHADE_LEVEL_COUNT = 32
SHADE_TABLE_SIZE = SHADE_LEVEL_COUNT * PALETTE_SIZE
SHADE_LIT_LEVELS = range(16, SHADE_LEVEL_COUNT)
SHADE_FILLER_COLUMNS = (*range(0, 10), *range(246, PALETTE_SIZE))

RAMP_NAMES = ("blue", "beige", "green", "grey")
RAMP_LENGTH = 16
_RED_TINT_OFFSET = len(RAMP_NAMES) * RAMP_LENGTH
EDITOR_COLOR_TABLE_SIZE = _RED_TINT_OFFSET + PALETTE_SIZE


class U9ShadeTableError(Exception):
    """Raised when a shade table does not have its fixed size."""


def _read(path: str | os.PathLike[str]) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as error:
        raise U9ShadeTableError(str(error)) from error


class U9ShadeTable:
    """``static/shade.tbl``: 32 light levels of palette-index translation."""

    def __init__(self, data: bytes) -> None:
        if len(data) != SHADE_TABLE_SIZE:
            raise U9ShadeTableError(
                f"shade.tbl must be exactly {SHADE_TABLE_SIZE} bytes; found {len(data)}"
            )
        self._data = bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> U9ShadeTable:
        return cls(data)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> U9ShadeTable:
        return cls(_read(path))

    def to_bytes(self) -> bytes:
        return self._data

    def level(self, level: int) -> bytes:
        """The 256 output indices of one light level."""
        if not 0 <= level < SHADE_LEVEL_COUNT:
            raise IndexError(f"level {level} outside 0..{SHADE_LEVEL_COUNT - 1}")
        return self._data[level * PALETTE_SIZE : (level + 1) * PALETTE_SIZE]

    def shade(self, level: int, index: int) -> int:
        """The output palette index for ``index`` at ``level``."""
        if not 0 <= index < PALETTE_SIZE:
            raise IndexError(f"palette index {index} outside 0..255")
        return self.level(level)[index]

    @property
    def filler_index(self) -> int:
        """The index stored in the first cell, which the builder uses as filler."""
        return self._data[0]

    def is_filler_cell(self, level: int, index: int) -> bool:
        """True where the builder writes filler rather than a shaded colour."""
        return level not in SHADE_LIT_LEVELS or index in SHADE_FILLER_COLUMNS

    def filler_anomalies(self) -> tuple[tuple[int, int, int], ...]:
        """``(level, index, value)`` for filler cells not holding the filler."""
        filler = self.filler_index
        return tuple(
            (level, index, self.shade(level, index))
            for level in range(SHADE_LEVEL_COUNT)
            for index in range(PALETTE_SIZE)
            if self.is_filler_cell(level, index) and self.shade(level, index) != filler
        )


class U9EditorColorTable:
    """``static/shadegry.tbl``: four colour ramps and a red-tint translation."""

    def __init__(self, data: bytes) -> None:
        if len(data) != EDITOR_COLOR_TABLE_SIZE:
            raise U9ShadeTableError(
                f"shadegry.tbl must be exactly {EDITOR_COLOR_TABLE_SIZE} bytes; "
                f"found {len(data)}"
            )
        self._data = bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> U9EditorColorTable:
        return cls(data)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> U9EditorColorTable:
        return cls(_read(path))

    def to_bytes(self) -> bytes:
        return self._data

    def ramp(self, name: str) -> bytes:
        """One 16-step ramp by name, darkest first."""
        try:
            position = RAMP_NAMES.index(name)
        except ValueError:
            raise KeyError(
                f"unknown ramp {name!r}; expected one of {RAMP_NAMES}"
            ) from None
        start = position * RAMP_LENGTH
        return self._data[start : start + RAMP_LENGTH]

    @property
    def red_tint(self) -> bytes:
        """The red-tinted output index for each of the 256 palette indices."""
        return self._data[_RED_TINT_OFFSET:]
