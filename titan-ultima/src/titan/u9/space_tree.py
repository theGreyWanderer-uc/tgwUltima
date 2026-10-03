"""Lossless reader for the ``static/treedat.flx`` volume lookup cache.

Each used FLX entry is a map-indexed acceleration structure derived from
``spaces.flx``.  A versioned map header names the visibility-volume IDs on that
map, followed by a flat table of variable-length binary partition nodes.  Child
links are node-table indices, while leaf nodes retain the volume IDs that must
be tested at the end of a lookup.

The cache is not authoritative geometry.  Missing or rejected map entries can
be rebuilt by the game from ``spaces.flx``.  Titan preserves every stored byte
and exposes structural warnings rather than repairing cached data implicitly.
"""

from __future__ import annotations

__all__ = [
    "TREE_CACHE_FORMAT_VERSION",
    "U9MapVolumeIndex",
    "U9VolumeLookupCache",
    "U9VolumeLookupError",
    "U9VolumePartition",
]

import os
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

if TYPE_CHECKING:
    from titan.u9.spaces import U9Spaces

TREE_CACHE_FORMAT_VERSION = 0
_MAP_PREFIX_SIZE = 12
_PARTITION_FIXED_SIZE = 32


class U9VolumeLookupError(Exception):
    """Raised when a used ``treedat.flx`` entry cannot be framed safely."""


@dataclass(frozen=True)
class U9VolumePartition:
    """One flat-table partition node with a variable leaf-membership list."""

    node_index: int
    entry_offset: int
    front_child_index: int
    back_child_index: int
    local_volume_ids: tuple[int, ...]
    partition_normal: tuple[float, float, float]
    partition_w: float
    subtree_volume_count: int
    raw_data: bytes

    @property
    def is_leaf(self) -> bool:
        return self.front_child_index < 0 and self.back_child_index < 0

    @property
    def has_complete_child_pair(self) -> bool:
        return (self.front_child_index < 0) == (self.back_child_index < 0)

    @property
    def child_indices(self) -> tuple[int, ...]:
        return tuple(
            child
            for child in (self.front_child_index, self.back_child_index)
            if child >= 0
        )

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9MapVolumeIndex:
    """One version-0 map cache entry from ``treedat.flx``."""

    map_id: int
    format_version: int
    declared_volume_count: int
    volume_ids: tuple[int, ...]
    declared_partition_count: int
    partitions: tuple[U9VolumePartition, ...]
    trailing_data: bytes
    raw_data: bytes

    @property
    def is_empty(self) -> bool:
        return not self.volume_ids

    @property
    def leaf_membership_count(self) -> int:
        return sum(len(node.local_volume_ids) for node in self.partitions)

    @property
    def duplicated_leaf_memberships(self) -> int:
        members = [
            volume_id for node in self.partitions for volume_id in node.local_volume_ids
        ]
        return len(members) - len(set(members))

    @property
    def root_subtree_volume_count(self) -> int | None:
        if not self.partitions:
            return None
        return self.partitions[0].subtree_volume_count

    @property
    def is_complete(self) -> bool:
        return not self.trailing_data

    def structural_warnings(self) -> tuple[str, ...]:
        """Report graph/count disagreements without altering the cache."""
        warnings: list[str] = []
        node_count = len(self.partitions)
        if self.declared_volume_count != len(self.volume_ids):
            warnings.append("declared_volume_count_mismatch")
        if self.declared_partition_count != node_count:
            warnings.append("declared_partition_count_mismatch")
        if not self.partitions:
            warnings.append("missing_root_partition")
            return tuple(warnings)

        parent_counts = [0] * node_count
        for node in self.partitions:
            if not node.has_complete_child_pair:
                warnings.append(f"node_{node.node_index}_incomplete_child_pair")
            for child_index in node.child_indices:
                if child_index >= node_count:
                    warnings.append(
                        f"node_{node.node_index}_child_{child_index}_out_of_range"
                    )
                else:
                    parent_counts[child_index] += 1
            if node.is_leaf:
                if len(node.local_volume_ids) != node.subtree_volume_count:
                    warnings.append(f"node_{node.node_index}_leaf_count_mismatch")
            elif node.local_volume_ids:
                warnings.append(f"node_{node.node_index}_internal_memberships")

        for node_index, parent_count in enumerate(parent_counts):
            expected = 0 if node_index == 0 else 1
            if parent_count != expected:
                warnings.append(f"node_{node_index}_parent_count_{parent_count}")

        reachable: set[int] = set()
        pending = [0]
        while pending:
            node_index = pending.pop()
            if node_index in reachable or not 0 <= node_index < node_count:
                continue
            reachable.add(node_index)
            pending.extend(self.partitions[node_index].child_indices)
        if len(reachable) != node_count:
            warnings.append("unreachable_partitions")

        root_count = self.root_subtree_volume_count
        if root_count != len(self.volume_ids):
            warnings.append("root_subtree_count_mismatch")
        leaf_ids = {
            volume_id for node in self.partitions for volume_id in node.local_volume_ids
        }
        header_ids = set(self.volume_ids)
        if leaf_ids - header_ids:
            warnings.append("leaf_membership_not_in_map_list")
        if header_ids - leaf_ids:
            warnings.append("map_volume_missing_from_leaves")
        if self.trailing_data:
            warnings.append("trailing_data")
        return tuple(warnings)

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


class U9VolumeLookupCache:
    """Lossless map-indexed view of ``static/treedat.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive = archive
        self._maps: dict[int, U9MapVolumeIndex] = {}
        for map_id in archive.used_entry_indices():
            self._maps[map_id] = _parse_map_index(map_id, archive.read_entry(map_id))

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9VolumeLookupCache:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as error:
            raise U9VolumeLookupError(str(error)) from error

    @property
    def num_entries(self) -> int:
        return self.archive.num_entries

    @property
    def used_map_ids(self) -> tuple[int, ...]:
        return tuple(self._maps)

    def map_index(self, map_id: int) -> U9MapVolumeIndex | None:
        return self._maps.get(map_id)

    def map_indices(self) -> tuple[U9MapVolumeIndex, ...]:
        return tuple(self._maps.values())

    def structurally_invalid_map_ids(self) -> tuple[int, ...]:
        return tuple(
            map_index.map_id
            for map_index in self._maps.values()
            if map_index.structural_warnings()
        )

    def maps_requiring_rebuild(self, spaces: U9Spaces) -> tuple[int, ...]:
        """Return maps whose cache is absent, invalid, or disagrees with spaces."""
        volume_ids_by_map: dict[int, list[int]] = {}
        for volume in spaces.spaces():
            volume_ids_by_map.setdefault(volume.world_map_id, []).append(
                volume.space_id
            )

        map_ids = set(self._maps) | set(volume_ids_by_map)
        rebuild: list[int] = []
        for map_id in sorted(map_ids):
            map_index = self._maps.get(map_id)
            expected_ids = tuple(volume_ids_by_map.get(map_id, ()))
            if (
                map_index is None
                or map_index.structural_warnings()
                or map_index.volume_ids != expected_ids
            ):
                rebuild.append(map_id)
        return tuple(rebuild)

    def to_bytes(self) -> bytes:
        """Return the complete original FLX archive byte for byte."""
        return self.archive.to_bytes()


def _read_i32(data: bytes, offset: int, label: str, map_id: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} truncates {label} at {offset:#x}"
        )
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_i32_array(
    data: bytes, offset: int, count: int, label: str, map_id: int
) -> tuple[tuple[int, ...], int]:
    if count < 0:
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} has negative {label} count {count}"
        )
    byte_count = count * 4
    if offset + byte_count > len(data):
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} truncates {label} at {offset:#x}: "
            f"needs {byte_count} bytes, only {len(data) - offset} remain"
        )
    values = struct.unpack_from(f"<{count}i", data, offset) if count else ()
    return tuple(values), offset + byte_count


def _parse_partition(
    data: bytes, offset: int, node_index: int, map_id: int
) -> tuple[U9VolumePartition, int]:
    start = offset
    front_child_index, offset = _read_i32(data, offset, "front child", map_id)
    back_child_index, offset = _read_i32(data, offset, "back child", map_id)
    local_count, offset = _read_i32(data, offset, "leaf membership count", map_id)
    local_volume_ids, offset = _read_i32_array(
        data, offset, local_count, "leaf membership", map_id
    )
    if offset + 16 > len(data):
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} truncates partition equation at {offset:#x}"
        )
    normal_x, normal_y, normal_z, partition_w = struct.unpack_from("<4f", data, offset)
    offset += 16
    subtree_volume_count, offset = _read_i32(
        data, offset, "subtree volume count", map_id
    )
    return (
        U9VolumePartition(
            node_index=node_index,
            entry_offset=start,
            front_child_index=front_child_index,
            back_child_index=back_child_index,
            local_volume_ids=local_volume_ids,
            partition_normal=(normal_x, normal_y, normal_z),
            partition_w=partition_w,
            subtree_volume_count=subtree_volume_count,
            raw_data=data[start:offset],
        ),
        offset,
    )


def _parse_map_index(map_id: int, data: bytes) -> U9MapVolumeIndex:
    if len(data) < _MAP_PREFIX_SIZE:
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} is {len(data)} bytes; "
            f"needs at least {_MAP_PREFIX_SIZE}"
        )
    offset = 0
    format_version, offset = _read_i32(data, offset, "format version", map_id)
    if format_version != TREE_CACHE_FORMAT_VERSION:
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} uses unsupported format version "
            f"{format_version}; expected {TREE_CACHE_FORMAT_VERSION}"
        )
    declared_volume_count, offset = _read_i32(data, offset, "map volume count", map_id)
    volume_ids, offset = _read_i32_array(
        data, offset, declared_volume_count, "map volume list", map_id
    )
    declared_partition_count, offset = _read_i32(
        data, offset, "partition count", map_id
    )
    if declared_partition_count < 0:
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} has negative partition count "
            f"{declared_partition_count}"
        )
    if declared_partition_count * _PARTITION_FIXED_SIZE > len(data) - offset:
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} cannot contain "
            f"{declared_partition_count} partitions in {len(data) - offset} bytes"
        )

    partitions: list[U9VolumePartition] = []
    for node_index in range(declared_partition_count):
        partition, offset = _parse_partition(data, offset, node_index, map_id)
        partitions.append(partition)

    trailing_data = data[offset:]
    if trailing_data:
        raise U9VolumeLookupError(
            f"treedat.flx entry {map_id} has {len(trailing_data)} unexplained "
            "byte(s) after its partition table"
        )
    return U9MapVolumeIndex(
        map_id=map_id,
        format_version=format_version,
        declared_volume_count=declared_volume_count,
        volume_ids=volume_ids,
        declared_partition_count=declared_partition_count,
        partitions=tuple(partitions),
        trailing_data=trailing_data,
        raw_data=data,
    )
