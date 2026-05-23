"""
Ultima 7 shape name table from TEXT.FLX.

TEXT.FLX is a Flex archive where record N contains the null-terminated display
name for shape N (e.g. record 522 → "locked chest"). Records for unnamed or
unused shapes are empty.

Example::

    from titan.u7.names import U7ShapeNames

    names = U7ShapeNames.from_file("STATIC/TEXT.FLX")
    print(names.get(522))               # "locked chest"
    print(names.find_shapes("chest"))   # [521, 522, ...]
"""

from __future__ import annotations

__all__ = ["U7ShapeNames"]

import os
from pathlib import Path
from typing import Optional

from titan.u7.flex import U7FlexArchive


class U7ShapeNames:
    """Shape display names loaded from TEXT.FLX."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str) -> "U7ShapeNames":
        """Load TEXT.FLX from an explicit path."""
        flex = U7FlexArchive.from_file(path)
        names: list[str] = []
        for i in range(len(flex.records)):
            rec = flex.get_record(i)
            if rec:
                text = rec.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()
            else:
                text = ""
            names.append(text)
        return cls(names)

    @classmethod
    def from_static_dir(cls, static_dir: str) -> Optional["U7ShapeNames"]:
        """Try to load TEXT.FLX from a STATIC directory. Returns None if absent."""
        for name in ("TEXT.FLX", "text.flx"):
            path = Path(static_dir) / name
            if path.exists():
                return cls.from_file(str(path))
        return None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, shape_num: int) -> str:
        """Return the display name for shape_num, or empty string if unknown."""
        if 0 <= shape_num < len(self._names):
            return self._names[shape_num]
        return ""

    def label(self, shape_num: int) -> str:
        """Return '522 (locked chest)' style label, or just '522' if unnamed."""
        name = self.get(shape_num)
        if name:
            return f"{shape_num} ({name})"
        return str(shape_num)

    def find_shapes(self, pattern: str) -> list[int]:
        """Return shape numbers whose name contains pattern (case-insensitive)."""
        lower = pattern.lower()
        return [i for i, n in enumerate(self._names) if lower in n.lower()]

    def __len__(self) -> int:
        return len(self._names)
