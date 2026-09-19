"""Deterministic reader for the ItemHandle section of U9 ``processes.dat``."""

from __future__ import annotations

__all__ = [
    "HANDLE_DATA_OFFSET",
    "U9ItemHandleEntry",
    "U9ItemHandleTable",
    "U9ProcessDataError",
]

import os
import struct
from dataclasses import dataclass

HANDLE_DATA_OFFSET = 0x27F74
HANDLE_VERSION = 1
CAMERA_VERSION = 2
HANDLE_RECORD = struct.Struct("<iii")
MIN_HANDLE_COUNT = 2
MAX_HANDLE_COUNT = 0x10000


class U9ProcessDataError(Exception):
    """Raised when the deterministic ItemHandle section is malformed."""


@dataclass(frozen=True)
class U9ItemHandleEntry:
    index: int
    usage_count: int
    map_number: int
    encoded_item_offset: int

    @property
    def is_free(self) -> bool:
        return self.map_number == -1

    @property
    def is_live(self) -> bool:
        return self.map_number >= 0 and self.encoded_item_offset != 0

    @property
    def is_fixed(self) -> bool:
        return self.is_live and self.encoded_item_offset < 0

    @property
    def item_offset(self) -> int:
        return abs(self.encoded_item_offset)


@dataclass(frozen=True)
class U9ItemHandleTable:
    version: int
    count: int
    free_head: int
    entries: tuple[U9ItemHandleEntry, ...]
    offset: int = HANDLE_DATA_OFFSET

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9ItemHandleTable:
        with open(filepath, "rb") as file:
            return cls.from_bytes(file.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> U9ItemHandleTable:
        if len(data) < HANDLE_DATA_OFFSET + 12:
            raise U9ProcessDataError(
                f"process data is too short for ItemHandle header at 0x{HANDLE_DATA_OFFSET:X}"
            )
        main_version, state_version = struct.unpack_from("<II", data, 0)
        if (main_version, state_version) != (8, 2):
            raise U9ProcessDataError(
                f"unsupported process versions {main_version}/{state_version}; expected 8/2"
            )
        version, count, free_head = struct.unpack_from("<III", data, HANDLE_DATA_OFFSET)
        if version != HANDLE_VERSION:
            raise U9ProcessDataError(
                f"unsupported ItemHandle version {version}; expected {HANDLE_VERSION}"
            )
        if not MIN_HANDLE_COUNT <= count <= MAX_HANDLE_COUNT:
            raise U9ProcessDataError(f"implausible ItemHandle count {count}")
        table_end = HANDLE_DATA_OFFSET + 12 + count * HANDLE_RECORD.size
        if table_end + 4 > len(data):
            raise U9ProcessDataError(
                f"truncated ItemHandle table: needs {table_end + 4} bytes, got {len(data)}"
            )
        (camera_version,) = struct.unpack_from("<I", data, table_end)
        if camera_version != CAMERA_VERSION:
            raise U9ProcessDataError(
                f"ItemHandle table does not end at camera version {CAMERA_VERSION} "
                f"(found {camera_version})"
            )
        entries = tuple(
            U9ItemHandleEntry(index, *HANDLE_RECORD.unpack_from(data, HANDLE_DATA_OFFSET + 12 + index * 12))
            for index in range(count)
        )
        invalid_maps = [entry.index for entry in entries if entry.map_number < -1]
        if invalid_maps:
            raise U9ProcessDataError(
                f"{len(invalid_maps)} ItemHandle entries have map numbers below -1"
            )
        if free_head >= count:
            raise U9ProcessDataError(
                f"ItemHandle free head {free_head} is outside 0..{count - 1}"
            )
        return cls(version, count, free_head, entries)

    @property
    def end_offset(self) -> int:
        return self.offset + 12 + self.count * HANDLE_RECORD.size

    @property
    def live_entries(self) -> tuple[U9ItemHandleEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_live)

    @property
    def fixed_entries(self) -> tuple[U9ItemHandleEntry, ...]:
        return tuple(entry for entry in self.live_entries if entry.is_fixed)

    @property
    def nonfixed_entries(self) -> tuple[U9ItemHandleEntry, ...]:
        return tuple(entry for entry in self.live_entries if not entry.is_fixed)

    def walk_free_chain(self) -> tuple[int, ...]:
        """Return free indices, excluding reserved handle zero, or raise on damage."""
        chain: list[int] = []
        seen: set[int] = set()
        current = self.free_head
        while current:
            if current < 0 or current >= self.count:
                raise U9ProcessDataError(f"free chain leaves table at handle {current}")
            if current in seen:
                raise U9ProcessDataError(f"free chain cycles at handle {current}")
            entry = self.entries[current]
            if not entry.is_free:
                raise U9ProcessDataError(f"free chain enters live handle {current}")
            seen.add(current)
            chain.append(current)
            current = entry.usage_count
        expected = {entry.index for entry in self.entries[1:] if entry.is_free}
        if seen != expected:
            raise U9ProcessDataError(
                f"free chain covers {len(seen)} of {len(expected)} free handles"
            )
        return tuple(chain)