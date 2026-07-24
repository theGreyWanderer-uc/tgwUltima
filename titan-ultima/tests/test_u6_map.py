"""Tests for titan.u6.map's MAP/CHUNKS world decoder.

No real game files are used here -- fixtures are hand-built to match the
layout confirmed identical between Nuvie's Map.cpp and pu6e's Map.py (see
titan/u6/map.py's module docstring for the real-data validation: exact
byte consumption, in-range chunk references, and a correctly-rendered
crop of Lord British's Castle). ``U6Map.parse``'s size/count overrides
keep these fixtures small instead of requiring the real 64-surface +
5-dungeon-superchunk layout.
"""

from __future__ import annotations

import unittest

import numpy as np

from titan.u6.map import (
    U6Chunks,
    U6ChunksError,
    U6Map,
    U6MapError,
    _unpack_superchunk_refs,
    render_tile_grid,
)
from titan.u6.palette import U6Palette
from titan.u6.tile import MASKTYPE_PLAIN, U6AnimData, U6AnimEntry, U6Tiles


def _pack_refs(refs: list[int]) -> bytes:
    """Inverse of _unpack_superchunk_refs: pack chunk numbers 2-per-3-bytes."""
    out = bytearray()
    for i in range(0, len(refs), 2):
        t1, t2 = refs[i], refs[i + 1]
        b0 = t1 & 0xFF
        b1 = ((t1 >> 8) & 0x0F) | ((t2 << 4) & 0xF0)
        b2 = (t2 >> 4) & 0xFF
        out += bytes([b0, b1, b2])
    return bytes(out)


def _uniform_chunk(fill: int) -> bytes:
    return bytes([fill] * 64)


class UnpackRefsTests(unittest.TestCase):
    def test_round_trips_with_pack_refs(self):
        refs = [0, 1, 2, 3]
        packed = _pack_refs(refs)
        self.assertEqual(_unpack_superchunk_refs(packed, side=2), refs)

    def test_known_byte_values(self):
        # b1's low nibble feeds chunk1's high bits; b1's high nibble feeds chunk2's low bits.
        buf = bytes([0x12, 0x34, 0x56, 0x00, 0x00, 0x00])
        pair = _unpack_superchunk_refs(buf, side=2)
        self.assertEqual(pair[:2], [0x412, 0x563])


class U6ChunksTests(unittest.TestCase):
    def test_rejects_non_multiple_of_64(self):
        with self.assertRaises(U6ChunksError):
            U6Chunks.parse(b"\x00" * 100)

    def test_num_chunks_and_get_chunk(self):
        data = _uniform_chunk(0) + _uniform_chunk(1) + _uniform_chunk(2)
        chunks = U6Chunks.parse(data)
        self.assertEqual(chunks.num_chunks, 3)
        self.assertEqual(chunks.get_chunk(1), _uniform_chunk(1))

    def test_get_chunk_array_shape_and_row_major(self):
        raw = bytes(range(64))
        chunks = U6Chunks.parse(raw)
        arr = chunks.get_chunk_array(0)
        self.assertEqual(arr.shape, (8, 8))
        self.assertEqual(arr[0, 0], 0)
        self.assertEqual(arr[0, 7], 7)
        self.assertEqual(arr[1, 0], 8)
        self.assertEqual(arr[7, 7], 63)


class U6MapTests(unittest.TestCase):
    def setUp(self):
        self.chunks = U6Chunks.parse(b"".join(_uniform_chunk(i) for i in range(4)))

    def test_rejects_wrong_size(self):
        with self.assertRaises(U6MapError):
            U6Map.parse(
                b"\x00" * 5,
                num_surface_superchunks=1,
                num_dungeon_levels=0,
                surface_side=2,
                surface_arrangement=1,
            )

    def test_surface_grid_composited_correctly(self):
        # Two 2x2-chunk-ref superchunks, arranged side by side (arrangement=2).
        schunk0 = _pack_refs([0, 1, 2, 3])
        schunk1 = _pack_refs([3, 2, 1, 0])
        m = U6Map.parse(
            schunk0 + schunk1,
            num_surface_superchunks=2,
            num_dungeon_levels=0,
            surface_side=2,
            surface_arrangement=2,
        )
        grid = m.build_surface_grid(self.chunks)
        self.assertEqual(grid.shape, (32, 32))  # 2 superchunks-wide * 2 chunks * 8 tiles

        # Superchunk 0 at world (0,0): refs [0,1,2,3] -> (cx,cy) row-major.
        self.assertTrue(np.all(grid[0:8, 0:8] == 0))
        self.assertTrue(np.all(grid[0:8, 8:16] == 1))
        self.assertTrue(np.all(grid[8:16, 0:8] == 2))
        self.assertTrue(np.all(grid[8:16, 8:16] == 3))

        # Superchunk 1 at world (16,0): refs [3,2,1,0].
        self.assertTrue(np.all(grid[0:8, 16:24] == 3))
        self.assertTrue(np.all(grid[0:8, 24:32] == 2))
        self.assertTrue(np.all(grid[8:16, 16:24] == 1))
        self.assertTrue(np.all(grid[8:16, 24:32] == 0))

    def test_dungeon_grid_composited_correctly(self):
        dchunk = _pack_refs([0, 1, 2, 3])
        m = U6Map.parse(
            dchunk,
            num_surface_superchunks=0,
            num_dungeon_levels=1,
            dungeon_side=2,
        )
        grid = m.build_dungeon_grid(0, self.chunks)
        self.assertEqual(grid.shape, (16, 16))
        self.assertTrue(np.all(grid[0:8, 0:8] == 0))
        self.assertTrue(np.all(grid[0:8, 8:16] == 1))
        self.assertTrue(np.all(grid[8:16, 0:8] == 2))
        self.assertTrue(np.all(grid[8:16, 8:16] == 3))


class RenderTileGridTests(unittest.TestCase):
    def setUp(self):
        masktypes = bytes([MASKTYPE_PLAIN, MASKTYPE_PLAIN])
        tile0 = bytes([10] * 256)
        tile1 = bytes([20] * 256)
        self.tiles = U6Tiles.from_parts(masktypes, tile0 + tile1, b"", num_tiles=2)
        self.palette = U6Palette.parse(bytes(1024))
        self.grid = np.array([[0, 1], [1, 0]], dtype=np.uint8)

    def test_render_full_grid_size(self):
        img = render_tile_grid(self.grid, self.tiles, self.palette)
        self.assertEqual(img.size, (32, 32))
        self.assertEqual(img.mode, "RGB")

    def test_render_region_crop(self):
        img = render_tile_grid(self.grid, self.tiles, self.palette, region=(1, 0, 1, 1))
        self.assertEqual(img.size, (16, 16))

    def test_render_transparent_mode(self):
        img = render_tile_grid(self.grid, self.tiles, self.palette, transparent=True)
        self.assertEqual(img.mode, "RGBA")


class RenderTileGridAnimDataTests(unittest.TestCase):
    """Covers the fix for placeholder tiles (e.g. water) rendering as flat
    white squares instead of their real, substituted content."""

    def setUp(self):
        masktypes = bytes([MASKTYPE_PLAIN, MASKTYPE_PLAIN, MASKTYPE_PLAIN])
        tile0 = bytes([0xFF] * 256)  # placeholder: 100% transparent, like real water tiles 8-15
        tile1 = bytes([20] * 256)
        tile2 = bytes([30] * 256)  # the "real" frame tile 0 should be substituted with
        self.tiles = U6Tiles.from_parts(masktypes, tile0 + tile1 + tile2, b"", num_tiles=3)
        self.palette = U6Palette.parse(bytes(1024))
        self.grid = np.array([[0, 1]], dtype=np.uint8)
        self.anim = U6AnimData([U6AnimEntry(placeholder_tile=0, first_frame_tile=2, and_mask=0, shift=0)])

    def test_without_animdata_placeholder_renders_as_raw_transparent_fallback(self):
        img = render_tile_grid(self.grid, self.tiles, self.palette, transparent=False)
        # tile 0 is 100% index-0xFF; opaque mode falls back to palette[0xFF] for every pixel.
        expected = self.palette.colors[0xFF]
        self.assertEqual(img.getpixel((0, 0)), expected)

    def test_with_animdata_placeholder_renders_as_substituted_frame(self):
        img = render_tile_grid(self.grid, self.tiles, self.palette, transparent=False, animdata=self.anim)
        expected = self.palette.colors[30]
        self.assertEqual(img.getpixel((0, 0)), expected)

    def test_untouched_tile_unaffected_by_animdata(self):
        img = render_tile_grid(self.grid, self.tiles, self.palette, transparent=False, animdata=self.anim)
        expected = self.palette.colors[20]
        self.assertEqual(img.getpixel((16, 0)), expected)


if __name__ == "__main__":
    unittest.main()
