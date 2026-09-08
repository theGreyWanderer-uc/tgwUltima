"""Tests for canonical U9 terrain/fixed region coordinates."""

from __future__ import annotations

import struct
import unittest

from titan.u9.fixed import OBJECT_SIZE, PAGE_HEADER_SIZE, U9Fixed
from titan.u9.nonfixed import U9Nonfixed
from titan.u9.region_scene import (
    FIXED_CHUNK_TERRAIN_POINTS,
    REGION_CHUNK_TERRAIN_POINTS,
    TERRAIN_HEIGHT_WORLD_Z,
    TERRAIN_POINT_WORLD_XY,
    U9RegionScene,
    U9RegionSceneError,
)
from titan.u9.terrain import HEADER_SIZE, POINTS_PER_CHUNK, U9Terrain, U9TerrainPoint


def _terrain(width: int = 32, height: int = 32) -> U9Terrain:
    values = [U9TerrainPoint.build(height=3, texture=7).value] * POINTS_PER_CHUNK
    values[1 + 2 * 16] = U9TerrainPoint.build(height=25, texture=8, is_split=True).value
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<II", head, 0, width, height)
    struct.pack_into("<I", head, 0x94, 1)
    tile_count = (width // 16) * (height // 16)
    return U9Terrain(
        bytes(head)
        + struct.pack(f"<{tile_count}H", *([0] * tile_count))
        + struct.pack(f"<{POINTS_PER_CHUNK}I", *values)
    )


def _fixed(*, x: int = 128, y: int = 256, z: int = 300) -> U9Fixed:
    obj = struct.pack("<I4H4hI", 1, x, y, z, 42, 0, 0, 0, -32768, 0x20)
    end = PAGE_HEADER_SIZE + OBJECT_SIZE
    page = struct.pack("<6I", 0, end, 0, 0, 0, 0)
    page += b"\x00" * (PAGE_HEADER_SIZE - len(page)) + obj
    head = bytearray(0x24)
    struct.pack_into("<I", head, 0x08, len(page))
    struct.pack_into("<II", head, 0x10, 1, 1)
    struct.pack_into("<I", head, 0x1C, 1)
    struct.pack_into("<I", head, 0x20, 1)
    return U9Fixed(bytes(head) + page)


def _nonfixed(
    *,
    x: int = 128,
    y: int = 256,
    z: int = 350,
    base_x: int = 0,
    base_y: int = 0,
) -> U9Nonfixed:
    """Build one complete allocator page with indexed and unlinked entities."""
    page = bytearray(0x1000)
    indexed_offset = 0x60
    unlinked_offset = 0x80
    free_offsets = list(range(0xA0, 0x1000, 0x20))
    heads = [0, indexed_offset] + [0] * 15
    page[:0x60] = struct.pack(
        "<7I17I",
        0,
        free_offsets[0],
        0,
        base_x,
        base_y,
        2,
        0,
        *heads,
    )
    page[indexed_offset : indexed_offset + 0x20] = struct.pack(
        "<IHHHH4hIHHI",
        0,
        x,
        y,
        z,
        203,
        0,
        0,
        0,
        -32768,
        0,
        1210,
        7,
        0,
    )
    page[unlinked_offset : unlinked_offset + 0x20] = struct.pack(
        "<IHHHH4hIHHI",
        0,
        x + 128,
        y + 128,
        z + 10,
        295,
        0,
        0,
        0,
        -32768,
        0,
        3009,
        0,
        0,
    )
    for index, offset in enumerate(free_offsets):
        following = free_offsets[index + 1] if index + 1 < len(free_offsets) else 0
        struct.pack_into("<I", page, offset, following)

    header = struct.pack("<5I", 0, 0, 0, len(page), 0x00C00000)
    header += struct.pack("<III", 1, 1, 1)
    header += struct.pack("<II", 1, 0)
    return U9Nonfixed(header + page)


class RegionSceneCoordinateTests(unittest.TestCase):
    def test_coordinate_scales_match_the_legacy_editor(self) -> None:
        self.assertEqual(TERRAIN_POINT_WORLD_XY, 128)
        self.assertEqual(TERRAIN_HEIGHT_WORLD_Z, 4)
        self.assertEqual(FIXED_CHUNK_TERRAIN_POINTS, 32)
        self.assertEqual(REGION_CHUNK_TERRAIN_POINTS, 32)

        scene = U9RegionScene(_terrain(), _fixed())
        position = scene.terrain_world_position(1, 2)
        self.assertEqual((position.x, position.y, position.z), (128, 256, 100))
        self.assertEqual((scene.extent_x, scene.extent_y), (4096, 4096))

    def test_fixed_object_uses_raw_world_units(self) -> None:
        scene = U9RegionScene(_terrain(), _fixed())
        placement = scene.fixed_placements()[0]
        self.assertEqual(
            (placement.position.x, placement.position.y, placement.position.z),
            (128, 256, 300),
        )
        self.assertEqual((placement.terrain_x, placement.terrain_y), (1.0, 2.0))

    def test_cell_preserves_split_and_wraps_edge_heights(self) -> None:
        scene = U9RegionScene(_terrain())
        split = scene.terrain_cell(1, 2)
        self.assertEqual(split.triangle_corner_indices, ((0, 1, 3), (0, 3, 2)))

        edge = scene.terrain_cell(31, 31)
        self.assertEqual(edge.corners[3].x, scene.extent_x)
        self.assertEqual(edge.corners[3].y, scene.extent_y)
        self.assertEqual(edge.corners[3].z, 3 * TERRAIN_HEIGHT_WORLD_Z)

    def test_diagnostics_confirm_fixed_alignment(self) -> None:
        diagnostics = U9RegionScene(_terrain(), _fixed()).diagnostics()
        self.assertEqual(diagnostics.fixed_objects, 1)
        self.assertEqual(diagnostics.fixed_objects_in_bounds, 1)
        self.assertEqual(diagnostics.fixed_objects_out_of_bounds, 0)
        self.assertEqual(diagnostics.fixed_chunk_position_mismatches, 0)

    def test_nonfixed_placements_distinguish_unlinked_records(self) -> None:
        scene = U9RegionScene(_terrain(), nonfixed=_nonfixed())
        indexed = scene.nonfixed_placements()
        allocated = scene.nonfixed_placements(include_unlinked=True)

        self.assertEqual(len(indexed), 1)
        self.assertEqual(len(allocated), 2)
        self.assertTrue(indexed[0].is_spatially_indexed)
        self.assertFalse(allocated[1].is_spatially_indexed)
        self.assertEqual(
            (indexed[0].position.x, indexed[0].position.y, indexed[0].position.z),
            (128, 256, 350),
        )
        self.assertEqual((indexed[0].terrain_x, indexed[0].terrain_y), (1.0, 2.0))

    def test_nonfixed_diagnostics_cover_every_allocated_record(self) -> None:
        diagnostics = U9RegionScene(_terrain(), nonfixed=_nonfixed()).diagnostics()
        self.assertEqual(diagnostics.nonfixed_indexed_entities, 1)
        self.assertEqual(diagnostics.nonfixed_unlinked_entities, 1)
        self.assertEqual(diagnostics.nonfixed_allocated_entities, 2)
        self.assertEqual(diagnostics.nonfixed_entities_in_bounds, 2)
        self.assertEqual(diagnostics.nonfixed_entities_out_of_bounds, 0)
        self.assertEqual(diagnostics.nonfixed_chunk_position_mismatches, 0)
        self.assertEqual(diagnostics.nonfixed_incomplete_chunks, 0)

    def test_rejects_mismatched_terrain_and_fixed_extents(self) -> None:
        with self.assertRaises(U9RegionSceneError):
            U9RegionScene(_terrain(16, 16), _fixed())

    def test_rejects_mismatched_terrain_and_nonfixed_extents(self) -> None:
        with self.assertRaisesRegex(U9RegionSceneError, "terrain/nonfixed"):
            U9RegionScene(_terrain(16, 16), nonfixed=_nonfixed())


if __name__ == "__main__":
    unittest.main()
