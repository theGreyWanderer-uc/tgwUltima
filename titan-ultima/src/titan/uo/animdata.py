"""Ultima Online static-art animation metadata support."""

from __future__ import annotations

__all__ = ["UOAnimData", "UOAnimDataEntry"]

from dataclasses import dataclass
from pathlib import Path

_ENTRIES_PER_GROUP = 8
_FRAME_COUNT = 64
_ENTRY_SIZE = 68
_GROUP_SIZE = 4 + (_ENTRIES_PER_GROUP * _ENTRY_SIZE)


@dataclass(frozen=True)
class UOAnimDataEntry:
    """One animdata.mul static-art animation entry."""

    tile_id: int
    frame_offsets: tuple[int, ...]
    unknown: int
    frame_count: int
    frame_interval: int
    frame_start: int

    @property
    def active_offsets(self) -> tuple[int, ...]:
        end = min(self.frame_count, len(self.frame_offsets))
        return self.frame_offsets[:end]


class UOAnimData:
    """Parsed animdata.mul metadata."""

    def __init__(self, entries: dict[int, UOAnimDataEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_file(cls, path: str | Path) -> UOAnimData:
        data = Path(path).read_bytes()
        entries: dict[int, UOAnimDataEntry] = {}
        groups = len(data) // _GROUP_SIZE
        pos = 0
        tile_id = 0

        for _group in range(groups):
            pos += 4
            for _ in range(_ENTRIES_PER_GROUP):
                raw_offsets = data[pos : pos + _FRAME_COUNT]
                pos += _FRAME_COUNT
                frame_offsets = tuple(
                    value - 256 if value >= 128 else value for value in raw_offsets
                )
                unknown = data[pos]
                frame_count = data[pos + 1]
                frame_interval = data[pos + 2]
                frame_start = data[pos + 3]
                pos += 4

                if frame_count > 0:
                    entries[tile_id] = UOAnimDataEntry(
                        tile_id,
                        frame_offsets,
                        unknown,
                        frame_count,
                        frame_interval,
                        frame_start,
                    )
                tile_id += 1

        return cls(entries)
