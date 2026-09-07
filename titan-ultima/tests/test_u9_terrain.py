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
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

from titan.u9.cli import cmd_terrain_textures
from titan.u9.terrain import (
    CHUNK_SIZE,
    HEADER_SIZE,
    POINTS_PER_CHUNK,
    U9Terrain,
    U9TerrainChunk,
    U9TerrainError,
    U9TerrainPoint,
)


def _point(
    *,
    height: int = 0,
    hole: bool = False,
    swap_uv: bool = False,
    mirror_uv: bool = False,
    split: bool = False,
    frame: int = 0,
    spare: bool = False,
    texture: int = 0,
) -> int:
    return (
        (height & 0xFFF)
        | (int(hole) << 12)
        | (int(swap_uv) << 13)
        | (int(mirror_uv) << 14)
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
    water_level: int = 0,
    wave_amplitude: float = 0.0,
    flags: int = 0,
    declared: int | None = None,
    slack: bytes = b"",
) -> bytes:
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<II", head, 0x00, width, height)
    encoded_name = name.encode("cp1252")
    head[0x08 : 0x08 + len(encoded_name)] = encoded_name
    struct.pack_into("<ifI", head, 0x88, water_level, wave_amplitude, flags)
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
        region = U9Terrain(
            _build(16, 16, [0], [_chunk()], name="Avatar’s House")
        )
        self.assertEqual(region.name, "Avatar’s House")

    def test_environment_header_fields_are_typed(self) -> None:
        region = U9Terrain(
            _build(
                16,
                16,
                [0],
                [_chunk()],
                water_level=-12,
                wave_amplitude=1.625,
                flags=0x4E,
            )
        )
        self.assertEqual(region.water_level, -12)
        self.assertAlmostEqual(region.wave_amplitude, 1.625)
        self.assertEqual(region.flags, 0x4E)

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
            _point(
                height=4095,
                texture=1023,
                frame=31,
                swap_uv=True,
                mirror_uv=True,
            ),
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
        self.assertTrue(point.swap_uv)
        self.assertTrue(point.mirror_uv)
        self.assertEqual(point.uv_rotation_quarter_turns, 3)
        self.assertEqual(point.uv_rotation_degrees, 270)
        self.assertEqual(point.unknown_flags, (True, True))

    def test_uv_flag_combinations_encode_quarter_turns(self) -> None:
        self.assertEqual(U9TerrainPoint.build().uv_rotation_degrees, 0)
        self.assertEqual(
            U9TerrainPoint.build(swap_uv=True).uv_rotation_degrees, 90
        )
        self.assertEqual(
            U9TerrainPoint.build(mirror_uv=True).uv_rotation_degrees, 180
        )
        self.assertEqual(
            U9TerrainPoint.build(swap_uv=True, mirror_uv=True).uv_rotation_degrees,
            270,
        )

    def test_point_builder_round_trips_every_field(self) -> None:
        point = U9TerrainPoint.build(
            x=7,
            y=9,
            height=4095,
            is_hole=True,
            swap_uv=True,
            mirror_uv=True,
            is_split=True,
            frame=31,
            texture=1023,
            spare_bit_set=True,
        )
        self.assertEqual(point.value, 0xFFFFFFFF)
        self.assertEqual(point.to_bytes(), b"\xff\xff\xff\xff")

    def test_point_builder_rejects_out_of_range_fields(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9TerrainPoint.build(height=4096)
        with self.assertRaises(U9TerrainError):
            U9TerrainPoint.build(frame=32)
        with self.assertRaises(U9TerrainError):
            U9TerrainPoint.build(texture=1024)

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
        self.assertEqual(self.region.duplicate_tile_reference_count(), 2)
        self.assertEqual(self.region.tiles_using_shared_chunks(), 4)
        self.assertEqual(self.region.referenced_chunks(), {0, 2})

    def test_texture_histogram_counts_placed_tiles_not_stored_chunks(self) -> None:
        histogram = self.region.texture_histogram()
        self.assertEqual(histogram, {0: 1024})

    def test_texture_histogram_excludes_orphans_and_honours_sharing(self) -> None:
        chunks = [
            _chunk(fill=_point(texture=10)),
            _chunk(fill=_point(texture=99)),
            _chunk(fill=_point(texture=20)),
        ]
        region = U9Terrain(_build(32, 32, [0, 2, 2, 0], chunks))
        self.assertEqual(region.texture_histogram(), {10: 512, 20: 512})

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

    def test_missing_chunks_in_a_nonempty_region_are_rejected(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(16, 16, [0], [_chunk()], declared=9))

    def test_non_word_aligned_slack_is_rejected(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(16, 16, [0], [_chunk()], slack=b"x"))


class TerrainSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _build(
            16,
            16,
            [0],
            [_chunk(fill=_point(height=12, texture=34))],
            water_level=-12,
            wave_amplitude=2.5,
            flags=0x35,
            slack=struct.pack("<I", 0x12345678),
        )
        self.region = U9Terrain(self.source)

    def test_exact_round_trip_preserves_slack(self) -> None:
        self.assertEqual(self.region.to_bytes(), self.source)
        self.assertEqual(self.region.slack_data, struct.pack("<I", 0x12345678))
        self.assertEqual(self.region.to_bytes(include_slack=False), self.source[:-4])

    def test_chunk_serialization_and_replacement(self) -> None:
        chunk = self.region.chunk(0)
        point = U9TerrainPoint.build(height=999, texture=88, swap_uv=True)
        replacement = chunk.replace_point(3, 4, point)
        self.assertEqual(len(replacement.to_bytes()), CHUNK_SIZE)

        edited = self.region.replace_chunk(0, replacement)
        changed = edited.chunk(0).point(3, 4)
        self.assertEqual(changed.height, 999)
        self.assertEqual(changed.texture, 88)
        self.assertTrue(changed.swap_uv)
        self.assertEqual(edited.slack_data, self.region.slack_data)

    def test_chunk_requires_exactly_256_words(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9TerrainChunk(index=0, values=(0,))

    def test_builds_a_complete_region_from_decoded_values(self) -> None:
        chunk = U9TerrainChunk(
            index=0,
            values=(_point(height=123, texture=45),) * POINTS_PER_CHUNK,
        )
        region = U9Terrain.build(
            width=16,
            height=16,
            tiles=[0],
            chunks=[chunk],
            name="Builder’s Map",
            water_level=-20,
            wave_amplitude=0.5,
            flags=3,
        )
        self.assertEqual(region.name, "Builder’s Map")
        self.assertEqual(region.water_level, -20)
        self.assertEqual(region.wave_amplitude, 0.5)
        self.assertEqual(region.height_at(15, 15), 123)
        self.assertEqual(U9Terrain(region.to_bytes()).to_bytes(), region.to_bytes())

    def test_replace_tile_redirects_only_the_selected_placement(self) -> None:
        chunks = [
            U9TerrainChunk(index=0, values=(_point(height=1),) * POINTS_PER_CHUNK),
            U9TerrainChunk(index=1, values=(_point(height=2),) * POINTS_PER_CHUNK),
        ]
        region = U9Terrain.build(
            width=32,
            height=16,
            tiles=[0, 0],
            chunks=chunks,
        )
        edited = region.replace_tile(1, 0, 1)
        self.assertEqual(region.height_at(16, 0), 1)
        self.assertEqual(edited.height_at(0, 0), 1)
        self.assertEqual(edited.height_at(16, 0), 2)

    def test_write_can_omit_stale_trailing_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/terrain.1"
            self.region.write(path, include_slack=False)
            with open(path, "rb") as file:
                written = file.read()
        self.assertEqual(written, self.source[:-4])

    def test_builder_rejects_a_wrong_tile_count(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain.build(width=16, height=16, tiles=[], chunks=[])


class TerrainValidationTests(unittest.TestCase):
    def test_rejects_tile_reference_outside_declared_chunks(self) -> None:
        with self.assertRaises(U9TerrainError):
            U9Terrain(_build(16, 16, [1], [_chunk()]))


class TerrainCliTests(unittest.TestCase):
    def test_texture_report_counts_the_placed_surface(self) -> None:
        data = _build(
            32,
            32,
            [0, 1, 1, 0],
            [
                _chunk(fill=_point(texture=10)),
                _chunk(fill=_point(texture=20)),
                _chunk(fill=_point(texture=99)),
            ],
            declared=3,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/terrain.1"
            with open(path, "wb") as file:
                file.write(data)
            output = StringIO()
            with redirect_stdout(output):
                result = cmd_terrain_textures(
                    SimpleNamespace(file=path, sdinfo=None, limit=None)
                )
        self.assertEqual(result, 0)
        self.assertIn("1024 point(s)", output.getvalue())
        self.assertNotIn("       99", output.getvalue())


if __name__ == "__main__":
    unittest.main()
