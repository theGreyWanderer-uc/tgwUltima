"""Tests for the lossless ``static/treedat.flx`` cache reader."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.cli import cmd_treedat_csv
from titan.u9.flx_archive import U9FlxArchive
from titan.u9.space_tree import U9VolumeLookupCache, U9VolumeLookupError
from titan.u9.spaces import U9Spaces

DIR_OFFSET = 0x80


def _archive(entries: dict[int, bytes], count: int = 256) -> U9FlxArchive:
    header = bytearray(DIR_OFFSET + count * 8)
    payload = bytearray()
    for index in range(count):
        blob = entries.get(index)
        if blob is None:
            continue
        offset = len(header) + len(payload)
        struct.pack_into("<II", header, DIR_OFFSET + index * 8, offset, len(blob))
        payload += blob
    struct.pack_into("<I", header, 0x50, count)
    struct.pack_into("<I", header, 0x54, 2)
    struct.pack_into(
        "<II", header, 0x58, len(header) + len(payload), len(header) + len(payload)
    )
    return U9FlxArchive(bytes(header + payload))


def _partition(
    *,
    front: int = -1,
    back: int = -1,
    volume_ids: tuple[int, ...] = (),
    equation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    subtree_count: int | None = None,
) -> bytes:
    count = len(volume_ids) if subtree_count is None else subtree_count
    return (
        struct.pack("<iii", front, back, len(volume_ids))
        + struct.pack(f"<{len(volume_ids)}i", *volume_ids)
        + struct.pack("<4f", *equation)
        + struct.pack("<i", count)
    )


def _map_entry(
    volume_ids: tuple[int, ...],
    partitions: tuple[bytes, ...],
    *,
    version: int = 0,
) -> bytes:
    return (
        struct.pack("<ii", version, len(volume_ids))
        + struct.pack(f"<{len(volume_ids)}i", *volume_ids)
        + struct.pack("<i", len(partitions))
        + b"".join(partitions)
    )


def _space_entry(world_map_id: int) -> bytes:
    return struct.pack(
        "<32siIIihhhH",
        b"Test".ljust(32, b"\x00"),
        world_map_id,
        0,
        0,
        0,
        -1,
        0,
        0,
        0,
    )


class VolumeLookupCacheTests(unittest.TestCase):
    def test_parses_empty_map_cache_and_round_trips(self) -> None:
        entry = _map_entry((), (_partition(),))
        archive = _archive({1: entry})
        cache = U9VolumeLookupCache(archive)
        map_index = cache.map_index(1)
        if map_index is None:
            self.fail("expected map 1 cache")

        self.assertTrue(map_index.is_empty)
        self.assertEqual(map_index.format_version, 0)
        self.assertEqual(map_index.root_subtree_volume_count, 0)
        self.assertEqual(map_index.structural_warnings(), ())
        self.assertEqual(map_index.to_bytes(), entry)
        self.assertEqual(cache.to_bytes(), archive.to_bytes())

    def test_parses_flat_node_table_and_leaf_memberships(self) -> None:
        entry = _map_entry(
            (4, 5),
            (
                _partition(
                    front=1,
                    back=2,
                    equation=(1.0, 0.0, 0.0, -64.0),
                    subtree_count=2,
                ),
                _partition(volume_ids=(4,)),
                _partition(volume_ids=(5,)),
            ),
        )
        map_index = U9VolumeLookupCache(_archive({4: entry})).map_index(4)
        if map_index is None:
            self.fail("expected map 4 cache")

        self.assertEqual(map_index.volume_ids, (4, 5))
        self.assertEqual(len(map_index.partitions), 3)
        root = map_index.partitions[0]
        self.assertFalse(root.is_leaf)
        self.assertEqual(root.child_indices, (1, 2))
        self.assertEqual(root.partition_normal, (1.0, 0.0, 0.0))
        self.assertEqual(root.partition_w, -64.0)
        self.assertEqual(map_index.leaf_membership_count, 2)
        self.assertEqual(map_index.structural_warnings(), ())

    def test_accepts_duplicate_leaf_memberships_for_split_volumes(self) -> None:
        entry = _map_entry(
            (9,),
            (
                _partition(front=1, back=2, subtree_count=1),
                _partition(volume_ids=(9,)),
                _partition(volume_ids=(9,)),
            ),
        )
        map_index = U9VolumeLookupCache(_archive({1: entry})).map_index(1)
        if map_index is None:
            self.fail("expected map 1 cache")

        self.assertEqual(map_index.duplicated_leaf_memberships, 1)
        self.assertEqual(map_index.structural_warnings(), ())

    def test_treats_any_negative_child_index_as_no_child(self) -> None:
        entry = _map_entry(
            (9,),
            (_partition(front=-2, back=-3, volume_ids=(9,)),),
        )
        map_index = U9VolumeLookupCache(_archive({1: entry})).map_index(1)
        if map_index is None:
            self.fail("expected map 1 cache")

        self.assertTrue(map_index.partitions[0].is_leaf)
        self.assertEqual(map_index.structural_warnings(), ())

    def test_reports_graph_and_membership_disagreements(self) -> None:
        entry = _map_entry(
            (1,),
            (_partition(front=2, back=-1, volume_ids=(2,), subtree_count=7),),
        )
        map_index = U9VolumeLookupCache(_archive({1: entry})).map_index(1)
        if map_index is None:
            self.fail("expected map 1 cache")

        self.assertEqual(
            map_index.structural_warnings(),
            (
                "node_0_incomplete_child_pair",
                "node_0_child_2_out_of_range",
                "node_0_internal_memberships",
                "root_subtree_count_mismatch",
                "leaf_membership_not_in_map_list",
                "map_volume_missing_from_leaves",
            ),
        )

    def test_identifies_maps_that_the_runtime_must_rebuild(self) -> None:
        cache_entry = _map_entry((1,), (_partition(volume_ids=(1,)),))
        cache = U9VolumeLookupCache(_archive({4: cache_entry}))
        spaces = U9Spaces(_archive({1: _space_entry(4), 2: _space_entry(9)}, count=8))

        self.assertEqual(cache.maps_requiring_rebuild(spaces), (9,))

    def test_rejects_unknown_version_and_truncated_counts(self) -> None:
        with self.assertRaisesRegex(U9VolumeLookupError, "unsupported format version"):
            U9VolumeLookupCache(
                _archive({1: _map_entry((), (_partition(),), version=1)})
            )

        with self.assertRaisesRegex(U9VolumeLookupError, "map volume list"):
            U9VolumeLookupCache(_archive({1: struct.pack("<iii", 0, 4, 0)}))

        with self.assertRaisesRegex(U9VolumeLookupError, "partition table"):
            U9VolumeLookupCache(
                _archive({1: _map_entry((), (_partition(),)) + b"stale"})
            )

    def test_csv_export_writes_map_node_and_membership_tables(self) -> None:
        entry = _map_entry((4,), (_partition(volume_ids=(4,)),))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "treedat.flx"
            archive_path.write_bytes(_archive({9: entry}).to_bytes())
            spaces_path = root / "spaces.flx"
            spaces_path.write_bytes(
                _archive({4: _space_entry(9), 5: _space_entry(105)}).to_bytes()
            )
            output = root / "csv"

            result = cmd_treedat_csv(
                SimpleNamespace(
                    file=str(archive_path),
                    output=str(output),
                    spaces=str(spaces_path),
                )
            )

            self.assertEqual(result, 0)
            self.assertIn(
                "runtime_rebuild_required",
                (output / "u9_treedat_maps.csv").read_text("utf-8"),
            )
            self.assertIn(
                "missing_cache",
                (output / "u9_treedat_maps.csv").read_text("utf-8"),
            )
            self.assertIn(
                "partition_normal_x",
                (output / "u9_treedat_nodes.csv").read_text("utf-8"),
            )
            self.assertIn(
                "membership_index",
                (output / "u9_treedat_node_volumes.csv").read_text("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
