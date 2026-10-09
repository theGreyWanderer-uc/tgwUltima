"""Complete U8 FIXED/NONFIXED OneItem records and serialized containment.

References: native ITEM/GLOB.H and ITEMCACH.C loadMapLevel/dumpMapLevel;
Pentagram world/Map.cpp. Native unsigned/int widths are two bytes. Map
record indices are local to their Flex slot, never cached item references.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from pathlib import Path

from titan.u8.itemcach import ITEM_STATUS_NAMES
from titan.u8.state_io import parse_u8_state_flex, read_u8_state_bytes

__all__ = ["U8MapItems", "U8MapItem", "U8MapItemsError"]

MAP_SLOT_COUNT = 256
ONE_ITEM = struct.Struct("<HHBHBHHBBH")


class U8MapItemsError(ValueError):
    """The map-item archive or a requested selection is malformed."""


@dataclass(frozen=True)
class U8MapItem:
    """Every raw OneItem field plus derived, map-local containment references."""

    map_id: int
    record_index: int
    file_offset: int
    x: int
    y: int
    z: int
    shape: int
    frame: int
    status: int
    quality: int
    npc_num: int
    map_num_raw: int
    next_item: int
    archive_kind: str
    parent_record_index: int | None = None
    root_record_index: int | None = None
    diagnostics: tuple[str, ...] = ()

    @property
    def contained(self) -> bool:
        return bool(self.status & 0x0008)

    @property
    def depth(self) -> int:
        return self.x if self.contained else 0

    @property
    def location_kind(self) -> str:
        if self.shape == 0:
            return "null_shape"
        if self.contained:
            return "contained"
        if self.z >= 251:
            return "inactive_z"
        if self.map_id == 0:
            return "npc_registry"
        return "world_stored"

    @property
    def is_world_object(self) -> bool:
        """Eligible stored world placement, excluding native-rejected records."""
        return self.location_kind == "world_stored" and not self.diagnostics

    @property
    def gump_x(self) -> int | None:
        return self.y & 0xFF if self.contained else None

    @property
    def gump_y(self) -> int | None:
        return self.y >> 8 if self.contained else None

    @property
    def equipment_slot(self) -> int | None:
        return self.z if self.contained and self.status & 0x0200 else None

    @property
    def glob_num(self) -> int | None:
        return self.quality if self.shape == 2 else None

    def status_names(self) -> list[str]:
        return [name for mask, name in ITEM_STATUS_NAMES.items() if self.status & mask]

    def to_bytes(self) -> bytes:
        """Encode precisely the ten raw fields; derived references are excluded."""
        return ONE_ITEM.pack(
            self.x,
            self.y,
            self.z,
            self.shape,
            self.frame,
            self.status,
            self.quality,
            self.npc_num,
            self.map_num_raw,
            self.next_item,
        )


def _resolve_items(items: list[U8MapItem]) -> tuple[U8MapItem, ...]:
    """Resolve native flag/depth order, retaining rejected records for inspection."""
    path: list[U8MapItem] = []
    resolved: list[U8MapItem] = []
    for item in items:
        issues: list[str] = []
        # Native loadMapLevel skips these before changing its container state.
        if item.shape == 0:
            issues.append("native loader skips zero shape")
        if item.x >= 32768 or item.y >= 32768:
            issues.append("native loader rejects signed-negative X/Y")
        if item.z >= 251:
            issues.append("native loader rejects Z >= 251")
        if item.shape >= 2048:
            issues.append("native loader rejects shape >= 2048")
        if item.npc_num == 255 and item.map_id != 0:
            issues.append("native loader rejects NPC number 255 outside slot 0")
        parent = root = None
        if not issues:
            if not item.contained:
                root = item.record_index
                path = [item]
            elif item.depth == 0 or item.depth > len(path):
                issues.append("contained depth has no serialized parent")
                # Do not invent a world placement or bridge an unresolved subtree.
                path = []
            else:
                parent = path[item.depth - 1].record_index
                root = path[0].record_index
                path = path[: item.depth] + [item]
        resolved.append(
            replace(
                item,
                parent_record_index=parent,
                root_record_index=root,
                diagnostics=tuple(issues),
            )
        )
    return tuple(resolved)


@dataclass(frozen=True)
class U8MapItems:
    """Immutable decoded archive; to_bytes preserves header, gaps and dead space."""

    kind: str
    maps: tuple[tuple[U8MapItem, ...], ...]
    map_offsets: tuple[int, ...]
    map_sizes: tuple[int, ...]
    raw_data: bytes

    @classmethod
    def from_file(cls, filepath: str | Path, *, kind: str = "fixed") -> U8MapItems:
        return cls.from_bytes(
            read_u8_state_bytes(filepath, f"{kind.upper()}.DAT"),
            kind=kind,
        )

    @classmethod
    def from_bytes(cls, data: bytes, *, kind: str = "fixed") -> U8MapItems:
        if kind not in {"fixed", "nonfixed"}:
            raise U8MapItemsError("Map items: kind must be fixed or nonfixed")
        label = f"{kind.upper()}.DAT"
        try:
            archive = parse_u8_state_flex(data, label, MAP_SLOT_COUNT)
        except ValueError as error:
            raise U8MapItemsError(str(error)) from error
        maps: list[tuple[U8MapItem, ...]] = []
        offsets: list[int] = []
        sizes: list[int] = []
        intervals: list[tuple[int, int]] = []
        for map_id, payload in enumerate(archive.records):
            offset, size = struct.unpack_from("<II", data, 128 + map_id * 8)
            if size % ONE_ITEM.size:
                raise U8MapItemsError(
                    f"{label}: map {map_id} has a partial 16-byte item"
                )
            if size:
                intervals.append((offset, offset + size))
            offsets.append(offset)
            sizes.append(size)
            items = [
                U8MapItem(
                    map_id,
                    index,
                    offset + index * ONE_ITEM.size,
                    x=fields[0],
                    y=fields[1],
                    z=fields[2],
                    shape=fields[3],
                    frame=fields[4],
                    status=fields[5],
                    quality=fields[6],
                    npc_num=fields[7],
                    map_num_raw=fields[8],
                    next_item=fields[9],
                    archive_kind=kind,
                )
                for index, fields in enumerate(ONE_ITEM.iter_unpack(payload))
            ]
            maps.append(_resolve_items(items))
        intervals.sort()
        if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
            raise U8MapItemsError(f"{label}: map payloads overlap")
        return cls(kind, tuple(maps), tuple(offsets), tuple(sizes), bytes(data))

    def get_map(self, map_id: int) -> tuple[U8MapItem, ...]:
        if not 0 <= map_id < MAP_SLOT_COUNT:
            raise U8MapItemsError("Map items: map ID must be 0-255")
        return self.maps[map_id]

    def to_bytes(self) -> bytes:
        """Return the exact original archive, including all unused bytes."""
        return self.raw_data
