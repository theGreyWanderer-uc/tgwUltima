"""Read the serialized object-reference table in U9 ``processes.dat``."""

from __future__ import annotations

__all__ = [
    "OBJECT_REFERENCE_DATA_OFFSET",
    "U9ObjectReferenceEntry",
    "U9ObjectReferenceTable",
    # Compatibility exports retained for callers using the earlier names.
    "HANDLE_DATA_OFFSET",
    "U9ItemHandleEntry",
    "U9ItemHandleTable",
    "U9ProcessDataError",
]

import os
import struct
from dataclasses import dataclass

OBJECT_REFERENCE_DATA_OFFSET = 0x27F74
OBJECT_REFERENCE_VERSION = 1
CAMERA_VERSION = 2
OBJECT_REFERENCE_RECORD = struct.Struct("<iii")
MIN_OBJECT_REFERENCE_COUNT = 2
MAX_OBJECT_REFERENCE_COUNT = 0x10000

# Deprecated compatibility constants. New code should use the format-oriented
# names above; values and serialized behavior are unchanged.
HANDLE_DATA_OFFSET = OBJECT_REFERENCE_DATA_OFFSET
HANDLE_VERSION = OBJECT_REFERENCE_VERSION
HANDLE_RECORD = OBJECT_REFERENCE_RECORD
MIN_HANDLE_COUNT = MIN_OBJECT_REFERENCE_COUNT
MAX_HANDLE_COUNT = MAX_OBJECT_REFERENCE_COUNT


class U9ProcessDataError(Exception):
    """Raised when a deterministic process-data section is malformed."""


@dataclass(frozen=True, init=False)
class U9ObjectReferenceEntry:
    """One serialized reference from a process to a fixed or runtime object."""

    index: int
    link_or_reference_count: int
    map_number: int
    encoded_object_offset: int

    def __init__(
        self,
        index: int,
        link_or_reference_count: int | None = None,
        map_number: int | None = None,
        encoded_object_offset: int | None = None,
        *,
        usage_count: int | None = None,
        encoded_item_offset: int | None = None,
    ) -> None:
        """Create an entry, accepting the earlier keyword names as aliases."""
        if link_or_reference_count is None:
            link_or_reference_count = usage_count
        elif usage_count is not None and usage_count != link_or_reference_count:
            raise TypeError("conflicting reference-count values")
        if encoded_object_offset is None:
            encoded_object_offset = encoded_item_offset
        elif (
            encoded_item_offset is not None
            and encoded_item_offset != encoded_object_offset
        ):
            raise TypeError("conflicting encoded-offset values")
        if link_or_reference_count is None:
            raise TypeError("missing link_or_reference_count")
        if map_number is None:
            raise TypeError("missing map_number")
        if encoded_object_offset is None:
            raise TypeError("missing encoded_object_offset")
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "link_or_reference_count", link_or_reference_count)
        object.__setattr__(self, "map_number", map_number)
        object.__setattr__(self, "encoded_object_offset", encoded_object_offset)

    @property
    def reference_count(self) -> int:
        """Live-reference count; free entries reuse this field as the next link."""
        return self.link_or_reference_count

    @property
    def next_free_index(self) -> int:
        """Next free table index when this entry is unallocated."""
        return self.link_or_reference_count

    @property
    def is_free(self) -> bool:
        return self.map_number == -1

    @property
    def is_live(self) -> bool:
        return self.map_number >= 0 and self.encoded_object_offset != 0

    @property
    def is_fixed(self) -> bool:
        return self.is_live and self.encoded_object_offset < 0

    @property
    def object_offset(self) -> int:
        """Absolute heap offset of the referenced object slot."""
        return abs(self.encoded_object_offset)

    # Compatibility properties retained for callers using the earlier field
    # vocabulary. They intentionally mirror the generalized properties.
    @property
    def usage_count(self) -> int:
        return self.link_or_reference_count

    @property
    def encoded_item_offset(self) -> int:
        return self.encoded_object_offset

    @property
    def item_offset(self) -> int:
        return self.object_offset


@dataclass(frozen=True)
class U9ObjectReferenceTable:
    """Serialized object-reference entries plus their free-index chain."""

    version: int
    count: int
    free_head: int
    entries: tuple[U9ObjectReferenceEntry, ...]
    offset: int = OBJECT_REFERENCE_DATA_OFFSET

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9ObjectReferenceTable:
        with open(filepath, "rb") as file:
            return cls.from_bytes(file.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> U9ObjectReferenceTable:
        if len(data) < OBJECT_REFERENCE_DATA_OFFSET + 12:
            raise U9ProcessDataError(
                "process data is too short for the object-reference table at "
                f"0x{OBJECT_REFERENCE_DATA_OFFSET:X}"
            )
        main_version, state_version = struct.unpack_from("<II", data, 0)
        if (main_version, state_version) != (8, 2):
            raise U9ProcessDataError(
                f"unsupported process versions {main_version}/{state_version}; expected 8/2"
            )
        version, count, free_head = struct.unpack_from(
            "<III", data, OBJECT_REFERENCE_DATA_OFFSET
        )
        if version != OBJECT_REFERENCE_VERSION:
            raise U9ProcessDataError(
                f"unsupported object-reference version {version}; "
                f"expected {OBJECT_REFERENCE_VERSION}"
            )
        if not MIN_OBJECT_REFERENCE_COUNT <= count <= MAX_OBJECT_REFERENCE_COUNT:
            raise U9ProcessDataError(f"implausible object-reference count {count}")
        table_end = (
            OBJECT_REFERENCE_DATA_OFFSET + 12 + count * OBJECT_REFERENCE_RECORD.size
        )
        if table_end + 4 > len(data):
            raise U9ProcessDataError(
                "truncated object-reference table: needs "
                f"{table_end + 4} bytes, got {len(data)}"
            )
        (camera_version,) = struct.unpack_from("<I", data, table_end)
        if camera_version != CAMERA_VERSION:
            raise U9ProcessDataError(
                "object-reference table does not end at camera version "
                f"{CAMERA_VERSION} "
                f"(found {camera_version})"
            )
        entries = tuple(
            U9ObjectReferenceEntry(
                index,
                *OBJECT_REFERENCE_RECORD.unpack_from(
                    data, OBJECT_REFERENCE_DATA_OFFSET + 12 + index * 12
                ),
            )
            for index in range(count)
        )
        invalid_maps = [entry.index for entry in entries if entry.map_number < -1]
        if invalid_maps:
            raise U9ProcessDataError(
                f"{len(invalid_maps)} object-reference entries have map numbers below -1"
            )
        if free_head >= count:
            raise U9ProcessDataError(
                f"object-reference free head {free_head} is outside 0..{count - 1}"
            )
        return cls(version, count, free_head, entries)

    @property
    def end_offset(self) -> int:
        return self.offset + 12 + self.count * OBJECT_REFERENCE_RECORD.size

    @property
    def live_entries(self) -> tuple[U9ObjectReferenceEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_live)

    @property
    def fixed_entries(self) -> tuple[U9ObjectReferenceEntry, ...]:
        return tuple(entry for entry in self.live_entries if entry.is_fixed)

    @property
    def nonfixed_entries(self) -> tuple[U9ObjectReferenceEntry, ...]:
        return tuple(entry for entry in self.live_entries if not entry.is_fixed)

    def walk_free_chain(self) -> tuple[int, ...]:
        """Return free indices, excluding reserved entry zero, or raise on damage."""
        chain: list[int] = []
        seen: set[int] = set()
        current = self.free_head
        while current:
            if current < 0 or current >= self.count:
                raise U9ProcessDataError(f"free chain leaves table at entry {current}")
            if current in seen:
                raise U9ProcessDataError(f"free chain cycles at entry {current}")
            entry = self.entries[current]
            if not entry.is_free:
                raise U9ProcessDataError(f"free chain enters live entry {current}")
            seen.add(current)
            chain.append(current)
            current = entry.next_free_index
        expected = {entry.index for entry in self.entries[1:] if entry.is_free}
        if seen != expected:
            raise U9ProcessDataError(
                f"free chain covers {len(seen)} of {len(expected)} free entries"
            )
        return tuple(chain)


# Deprecated compatibility aliases. Keeping identity, rather than subclasses,
# preserves ``isinstance`` behavior and existing imports without duplicating
# the parser implementation.
U9ItemHandleEntry = U9ObjectReferenceEntry
U9ItemHandleTable = U9ObjectReferenceTable
