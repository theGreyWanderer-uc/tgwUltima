"""Decode U8 ITEMCACH.DAT's item arrays and complete native cache metadata.

References: decoded ITEM/ITEMDATA.H/C, ITEMCACH.H/C and ITEM.C; Pentagram
world/World.cpp and docs/u8mapfmt.txt. Native DOS int/unsigned are 16 bits.
Item slots are references, not compact records; free slots retain stale data.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from titan.u8.state_io import parse_u8_state_flex, read_u8_state_bytes

__all__ = [
    "U8ItemCache",
    "U8CachedItem",
    "U8CacheMetadata",
    "U8CacheRegion",
    "U8ItemChain",
    "U8ItemCacheError",
]

ITEM_SLOT_COUNT = 9216
NPC_SLOT_COUNT = 256
ITEM_ARRAY_SIZE = 147456
CACHE_METADATA_SIZE = 16410
REGION_SIDE = 64
ITEM_ARRAY_FIELDS = (
    ("x", 0x00000, "H"),
    ("y", 0x04800, "H"),
    ("z", 0x09000, "B"),
    ("shape", 0x0B400, "H"),
    ("frame_low", 0x0FC00, "B"),
    ("status", 0x12000, "H"),
    ("quality", 0x16800, "H"),
    ("npc_num", 0x1B000, "B"),
    ("map_num_raw", 0x1D400, "B"),
    ("next_item", 0x1F800, "H"),
)
ITEM_STATUS_NAMES = {
    0x0001: "in_display_list",
    0x0002: "disposable",
    0x0004: "owned",
    0x0008: "contained",
    0x0010: "invisible",
    0x0020: "flipped",
    0x0040: "in_npc_list",
    0x0080: "fast_only",
    0x0100: "gump_open",
    0x0200: "equipped",
    0x0400: "bouncing",
    0x0800: "ethereal",
    0x1000: "hanging",
    0x2000: "fast_area",
    0x4000: "low_friction",
    0x8000: "has_item_relative_gump",
}


class U8ItemCacheError(ValueError):
    """ITEMCACH.DAT's container or required item/cache blocks are malformed."""


@dataclass(frozen=True)
class U8CachedItem:
    """Raw slot fields; contained X is a parent ID and Y stores gump coordinates."""

    item_id: int
    x: int
    y: int
    z: int
    shape: int
    frame_low: int
    status: int
    quality: int
    npc_num: int
    map_num_raw: int
    next_item: int

    @property
    def container_id(self) -> int | None:
        return self.x if self.status & 0x0008 else None

    @property
    def location_kind(self) -> str:
        """Stored location context; raw coordinates are not resolved through parents."""
        if self.status & 0x0008:
            return "contained"
        if self.status & 0x0800:
            return "ethereal"
        return "inactive_z" if self.z >= 251 else "world_stored"

    def status_names(self) -> list[str]:
        return [name for bit, name in ITEM_STATUS_NAMES.items() if self.status & bit]


@dataclass(frozen=True)
class U8CacheRegion:
    """One native [rx][ry] cache region; count is preserved, not recomputed."""

    rx: int
    ry: int
    head: int
    item_count: int


@dataclass(frozen=True)
class U8CacheMetadata:
    """Native record 1, including signed map/counts and all 4096 region cells."""

    map_in: int
    min_sum: int
    max_sum: int
    min_diff: int
    max_diff: int
    regions: tuple[U8CacheRegion, ...]
    free_count: int
    free_npc_count: int
    first_free: int
    first_free_npc: int
    last_free: int
    last_free_npc: int
    ethereal_top: int
    ethereal_count: int
    trailing_bytes: bytes


@dataclass(frozen=True)
class U8ItemChain:
    """A bounded next-item walk; bad links become diagnostics instead of looping."""

    head: int
    item_ids: tuple[int, ...]
    issues: tuple[str, ...]


class U8ItemCache:
    """All 9216 native slots with free-list membership and exact original bytes."""

    def __init__(
        self,
        data: bytes,
        items: tuple[U8CachedItem, ...],
        metadata: U8CacheMetadata,
        array_tail: bytes,
    ) -> None:
        self._data = data
        self.items = items
        self.metadata = metadata
        self.array_tail = array_tail
        self.free_items = self.trace_chain(metadata.first_free)
        self.free_npcs = self.trace_chain(metadata.first_free_npc)
        self.ethereal_items = self.trace_chain(metadata.ethereal_top)
        self._free_item_ids = frozenset(self.free_items.item_ids)
        self._free_npc_ids = frozenset(self.free_npcs.item_ids)
        self._ethereal_ids = frozenset(self.ethereal_items.item_ids)

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8ItemCache:
        """Read loose ITEMCACH.DAT or its named entry in a native U8 save archive."""
        try:
            return cls.from_bytes(read_u8_state_bytes(filepath, "ITEMCACH.DAT"))
        except ValueError as error:
            raise U8ItemCacheError(str(error)) from error

    @classmethod
    def from_bytes(cls, data: bytes) -> U8ItemCache:
        """Decode field-major arrays and metadata; preserve extra record/file bytes."""
        try:
            archive = parse_u8_state_flex(data, "ITEMCACH.DAT", 2)
        except ValueError as error:
            raise U8ItemCacheError(str(error)) from error
        arrays, metadata = archive.records
        if len(arrays) < ITEM_ARRAY_SIZE:
            raise U8ItemCacheError("ITEMCACH.DAT: truncated 9216-slot item arrays")
        if len(metadata) < CACHE_METADATA_SIZE:
            raise U8ItemCacheError("ITEMCACH.DAT: truncated cache metadata")
        fields = [
            struct.unpack_from(f"<{ITEM_SLOT_COUNT}{code}", arrays, offset)
            for _, offset, code in ITEM_ARRAY_FIELDS
        ]
        items = tuple(
            U8CachedItem(index, *(field[index] for field in fields))
            for index in range(ITEM_SLOT_COUNT)
        )
        heads = struct.unpack_from("<4096H", metadata, 10)
        counts = struct.unpack_from("<4096H", metadata, 8202)
        regions = tuple(
            U8CacheRegion(
                index // REGION_SIDE, index % REGION_SIDE, heads[index], counts[index]
            )
            for index in range(4096)
        )
        map_in, min_sum, max_sum, min_diff, max_diff = struct.unpack_from(
            "<5h", metadata
        )
        (
            free_count,
            free_npc_count,
            first_free,
            first_free_npc,
            last_free,
            last_free_npc,
            ethereal_top,
            ethereal_count,
        ) = struct.unpack_from("<h6Hh", metadata, 16394)
        cache = U8CacheMetadata(
            map_in=map_in,
            min_sum=min_sum,
            max_sum=max_sum,
            min_diff=min_diff,
            max_diff=max_diff,
            regions=regions,
            free_count=free_count,
            free_npc_count=free_npc_count,
            first_free=first_free,
            first_free_npc=first_free_npc,
            last_free=last_free,
            last_free_npc=last_free_npc,
            ethereal_top=ethereal_top,
            ethereal_count=ethereal_count,
            trailing_bytes=metadata[CACHE_METADATA_SIZE:],
        )
        return cls(data, items, cache, arrays[ITEM_ARRAY_SIZE:])

    def get_item(self, item_id: int) -> U8CachedItem:
        """Return any native slot including free/stale data; reject invalid references."""
        if not 0 <= item_id < ITEM_SLOT_COUNT:
            raise U8ItemCacheError("ITEMCACH.DAT: item ID must be 0-9215")
        return self.items[item_id]

    def trace_chain(self, head: int) -> U8ItemChain:
        """Follow next links to zero, retaining visited IDs and reporting bad pointers."""
        ids: list[int] = []
        seen: set[int] = set()
        issues: list[str] = []
        current = head
        while current:
            if not 0 < current < ITEM_SLOT_COUNT:
                issues.append(f"item link {current} is outside 1-9215")
                break
            if current in seen:
                issues.append(f"item link cycle at {current}")
                break
            seen.add(current)
            ids.append(current)
            current = self.items[current].next_item
        return U8ItemChain(head, tuple(ids), tuple(issues))

    def slot_membership(self, item_id: int) -> str:
        """Classify allocation from cache lists, never from a stale shape value."""
        self.get_item(item_id)
        if item_id == 0:
            return "null"
        if item_id in self._free_npc_ids:
            return "free_npc"
        if item_id in self._free_item_ids:
            return "free_item"
        if item_id in self._ethereal_ids:
            return "ethereal"
        return "allocated"

    def iter_items(self, *, include_free: bool = False) -> Iterator[U8CachedItem]:
        """Yield stable slot IDs; default omits null/free lists, not zero shapes."""
        return (
            item
            for item in self.items
            if include_free
            or self.slot_membership(item.item_id)
            not in {"null", "free_item", "free_npc"}
        )

    def list_diagnostics(self) -> list[str]:
        """Compare saved free/ethereal counts and tails without rejecting stale slots."""
        issues: list[str] = []
        for name, chain, count, tail in (
            (
                "free_items",
                self.free_items,
                self.metadata.free_count,
                self.metadata.last_free,
            ),
            (
                "free_npcs",
                self.free_npcs,
                self.metadata.free_npc_count,
                self.metadata.last_free_npc,
            ),
            ("ethereal", self.ethereal_items, self.metadata.ethereal_count, None),
        ):
            issues.extend(f"{name}: {issue}" for issue in chain.issues)
            if len(chain.item_ids) != count:
                issues.append(
                    f"{name}: stored count {count}, traversed {len(chain.item_ids)}"
                )
            if (
                tail is not None
                and (chain.item_ids[-1] if chain.item_ids else 0) != tail
            ):
                issues.append(f"{name}: stored tail {tail} differs from traversed tail")
        if self._free_item_ids & self._free_npc_ids:
            issues.append("free item and free NPC lists overlap")
        if (self._free_item_ids | self._free_npc_ids) & self._ethereal_ids:
            issues.append("free and ethereal lists overlap")
        return issues

    def to_bytes(self) -> bytes:
        """Return the exact native ITEMCACH file, not its containing save archive."""
        return self._data
