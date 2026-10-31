"""Native GUMPAGE.DAT storage rectangles, indexed by gump shape minus one."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class U8GumpItemArea:
    """Signed native rectangle; right and bottom are exclusive, in gump origin coordinates."""

    shape: int
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class U8GumpAreas:
    """Complete captured GUMPAGE bytes; empty entries retain their native indices."""

    raw_data: bytes
    areas: tuple[U8GumpItemArea, ...]

    @classmethod
    def from_file(cls, path: Path) -> U8GumpAreas:
        """Read the selected gump graphics owner's GUMPAGE.DAT."""
        return cls.from_bytes(path.read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> U8GumpAreas:
        """Reject partial records instead of silently discarding the trailing bytes."""
        if not data or len(data) % 8:
            raise ValueError("GUMPAGE.DAT: expected complete 8-byte rectangles")
        return cls(
            bytes(data),
            tuple(
                U8GumpItemArea(index + 1, *values)
                for index, values in enumerate(struct.iter_unpack("<4h", data))
            ),
        )

    def get_area(self, shape: int) -> U8GumpItemArea:
        """Resolve one-based gump shape IDs, preserving empty and signed rectangles."""
        if not 1 <= shape <= len(self.areas):
            raise ValueError(
                f"GUMPAGE.DAT: no storage rectangle for gump shape {shape}"
            )
        return self.areas[shape - 1]
