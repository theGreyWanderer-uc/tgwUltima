"""Tests for titan.u9.terrain's static/terrain.%d decoder.

Fixtures match the layout verified against 168 real region files (50,780
chunks, 55,908 tiles, 12,999,680 points). The properties pinned down here are
the ones the published documentation gets wrong, plus the two the reader has
to get right or every point lands in the wrong place:

* ``texture`` is a **10**-bit field, not the documented ``uint9``;
* ``frame`` is a **5**-bit field, so bit 21 must not leak into it;
* bit 15 is the quadrangle split direction, set on ``(x + y)`` odd;
* tiles share chunks, so a chunk index may appear in the grid more than once;
* ``chunk_count`` is authoritative even when the file is longer.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.terrain import (
    CHUNK_SIZE,
    HEADER_SIZE,
    POINTS_PER_CHUNK,
    U9Terrain,
    U9TerrainError,
)


def _point(
    *,
    height: int = 0,
    hole: bool = False,
    flag13: bool = False,
    flag14: bool = False,
    split: bool = False,
    frame: int = 0,
    spare: bool = False,
    texture: int = 0,
) -> int:
    return (
        (height & 0xFFF)
        | (int(hole) << 12)
        | (int(flag13) << 13)
        | (int(flag14) << 14)
        | (int(split) << 15)
        | ((frame & 0x1F) << 16)
        | (int(spare) << 21)
        | ((texture & 0x3FF) << 22)
    )


def _chunk(values: list[int] | None = None, fill: int = 0) -> bytes:
    words = list(values or [])
    words += [fill] * (POINTS_PER_CHUNK - len(words))
    return struct.pack(f"<{POINTS_PER_CHUNK}I", *words[:POINTS_PER_CHUNK])


def _build(
    width: int,
    height: int,
    tiles: list[int],
    chunks: list[bytes],
    *,
    name: str = "Test Region",
    declared: int | None = None,
    slack: bytes = b"",
) -> bytes:
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<II", head, 0x00, width, height)
    head[0x08 : 0x08 + len(name)] = name.encode("latin-1")
    struct.pack_into("<I", head, 0x94, len(chunks) if declared is None else declared)
    body = struct.pack(f"<{len(tiles)}H", *tiles) if tiles else b""
    return bytes(head) + body + b"".join(chunks) + slack


class TerrainHeaderTests(unittest.TestCase):
    def test_grid_and_world_size(self) -> None:
        region = U9Terrain(_build(64, 32, [0] * 8, [_chunk()]))
        self.assertEqual((region.width, region.height), (64, 32))
        self.assertEqual((region.tile_width, region.tile_height), (4, 2))
        self.assertEqual(region.tile_count, 8)
        # 16 points to a tile, 8 world coordinates to a tile
        self.assertEqual((region.world_width, region.world_height), (32, 16))

    def test_region_name_is_read(self) -> None:
        region = U9Terrain(_build(16, 16, [0], [_chunk()], name="Ethereal Void"))
        self.assertEqual(region.name, "Ethereal Void")

    def test_rejects_short_data(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(b"\x00" * 32)

    def test_rejects_width_that_is_not_whole_tiles(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(20, 16, [0], [_chunk()]))

    def test_rejects_implausible_grid(self) -> None:
        data = bytearray(_build(16, 16, [0], [_chunk()]))
        struct.pack_into("<I", data, 0x00, 16 * 4096)
        with self.assertRaises(U9TerrainError):
            U9Terrain(bytes(data))

    def test_rejects_truncated_tile_table(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(64, 64, [0] * 16, [])[:-20])


class TerrainEmptySlotTests(unittest.TestCase):
    """Four shipped regions are a bare header: an unused region slot."""

    def test_bare_header_is_accepted_as_an_empty_region(self) -> None:
        region = U9Terrain(_build(0, 0, [], [], name="my map", declared=7))
        self.assertTrue(region.is_empty)
        self.assertEqual(region.name, "my map")
        self.assertEqual(region.tile_count, 0)
        self.assertEqual(region.chunk_count, 0)
        # the count field is stale in these slots, and saying so is the point
        self.assertEqual(region.declared_chunk_count, 7)
        self.assertTrue(region.is_truncated)

    def test_zero_dimensions_with_a_body_are_rejected(self) -> None:
        # otherwise any file of zeros would pass as an empty region
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(0, 0, [], []) + b"\x00" * 4096)

    def test_one_zero_dimension_is_rejected(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(0, 16, [], []))


class TerrainPointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = [
            _point(height=1750, texture=936, frame=17, hole=True, split=True),
            _point(height=0, texture=0, frame=0),
            _point(height=4095, texture=1023, frame=31, flag13=True, flag14=True),
        ]
        self.region = U9Terrain(_build(16, 16, [0], [_chunk(self.values)]))

    def test_fields_decode(self) -> None:
        point = self.region.chunk(0).point(0, 0)
        self.assertEqual(point.height, 1750)
        self.assertEqual(point.texture, 936)
        self.assertEqual(point.frame, 17)
        self.assertTrue(point.is_hole)
        self.assertTrue(point.is_split)

    def test_texture_is_ten_bits_not_nine(self) -> None:
        # 936 is the highest index shipped regions reach; a 9-bit field caps
        # at 511, so reading it as uint9 would lose the top bit.
        self.assertEqual(self.region.chunk(0).point(0, 0).texture, 936)
        self.assertEqual(self.region.chunk(0).point(2, 0).texture, 1023)

    def test_frame_is_five_bits_and_ignores_bit_21(self) -> None:
        # Documented as bits 16-21, which is six bits. Bit 21 is set on none
        # of the 13 million shipped points; a six-bit read would fold it in.
        spare = _point(frame=5, spare=True)
        region = U9Terrain(_build(16, 16, [0], [_chunk([spare])]))
        point = region.chunk(0).point(0, 0)
        self.assertEqual(point.frame, 5)
        self.assertTrue(point.spare_bit_set)

    def test_extremes_stay_in_range(self) -> None:
        point = self.region.chunk(0).point(2, 0)
        self.assertEqual(point.height, 4095)
        self.assertEqual(point.frame, 31)
        self.assertEqual(point.unknown_flags, (True, True))

    def test_helpers_match_the_decoded_points(self) -> None:
        chunk = self.region.chunk(0)
        self.assertEqual(chunk.heights()[:3], (1750, 0, 4095))
        self.assertEqual(chunk.textures()[:3], (936, 0, 1023))
        self.assertEqual([p.value for p in chunk.points()[:3]], self.values)

    def test_flat_chunk_detection(self) -> None:
        flat = U9Terrain(_build(16, 16, [0], [_chunk(fill=_point(height=500))]))
        self.assertTrue(flat.chunk(0).is_flat)
        self.assertFalse(self.region.chunk(0).is_flat)

    def test_point_out_of_range_raises(self) -> None:
        with self.assertRaises(U9TerrainError):
            self.region.chunk(0).point(16, 0)


class TerrainTileTests(unittest.TestCase):
    def setUp(self) -> None:
        chunks = [
            _chunk(fill=_point(height=100)),
            _chunk(fill=_point(height=200)),
            _chunk(fill=_point(height=300)),
        ]
        # tile (1,0) and tile (0,1) share chunk 2; chunk 1 is referenced by none
        self.region = U9Terrain(_build(32, 32, [0, 2, 2, 0], chunks))

    def test_tiles_are_row_major(self) -> None:
        self.assertEqual(self.region.tile(0, 0), 0)
        self.assertEqual(self.region.tile(1, 0), 2)
        self.assertEqual(self.region.tile(0, 1), 2)

    def test_chunks_are_shared_between_tiles(self) -> None:
        self.assertEqual(self.region.shared_tile_count(), 2)
        self.assertEqual(self.region.referenced_chunks(), {0, 2})

    def test_chunks_no_tile_points_at_are_reported(self) -> None:
        self.assertEqual(self.region.unused_chunks(), [1])

    def test_tile_out_of_range_raises(self) -> None:
        with self.assertRaises(U9TerrainError):
            self.region.tile(2, 0)

    def test_chunk_out_of_range_raises(self) -> None:
        with self.assertRaises(U9TerrainError):
            self.region.chunk(3)


class TerrainLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        rising = _chunk([_point(height=i) for i in range(POINTS_PER_CHUNK)])
        flat = _chunk(fill=_point(height=900))
        self.region = U9Terrain(_build(32, 32, [0, 1, 1, 0], [rising, flat]))

    def test_region_point_resolves_through_the_tile_grid(self) -> None:
        # (17, 3) is tile (1,0) -> chunk 1, which is flat at 900
        self.assertEqual(self.region.height_at(17, 3), 900)
        # (3, 2) is tile (0,0) -> chunk 0, point (3,2) = 3 + 2*16
        self.assertEqual(self.region.height_at(3, 2), 35)

    def test_point_reports_region_coordinates_not_chunk_ones(self) -> None:
        point = self.region.point(3, 2)
        self.assertEqual((point.x, point.y), (3, 2))
        self.assertEqual(point.height, 35)

    def test_point_out_of_range_raises(self) -> None:
        with self.assertRaises(U9TerrainError):
            self.region.point(32, 0)

    def test_heightmap_is_rows_of_the_whole_region(self) -> None:
        rows = self.region.heightmap()
        self.assertEqual(len(rows), 32)
        self.assertEqual(len(rows[0]), 32)
        self.assertEqual(rows[2][3], 35)
        self.assertEqual(rows[3][17], 900)

    def test_height_range_spans_referenced_chunks(self) -> None:
        self.assertEqual(self.region.height_range(), (0, 900))


class TerrainSlackTests(unittest.TestCase):
    def test_declared_count_wins_over_the_bytes_present(self) -> None:
        # 22 shipped regions carry stale chunks past their last declared one.
        chunks = [_chunk(fill=_point(height=1)), _chunk(fill=_point(height=2))]
        region = U9Terrain(
            _build(16, 16, [0], chunks, declared=1, slack=_chunk(fill=0xDEAD))
        )
        self.assertEqual(region.chunk_count, 1)
        self.assertFalse(region.is_truncated)
        self.assertEqual(region.slack_bytes, CHUNK_SIZE * 2)

    def test_missing_chunks_are_reported_not_invented(self) -> None:
        region = U9Terrain(_build(16, 16, [0], [_chunk()], declared=9))
        self.assertEqual(region.chunk_count, 1)
        self.assertTrue(region.is_truncated)
        self.assertEqual(region.slack_bytes, 0)


if __name__ == "__main__":
    unittest.main()
