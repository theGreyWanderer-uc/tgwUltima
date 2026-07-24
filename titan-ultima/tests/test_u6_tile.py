"""Tests for titan.u6.tile's tile graphics decoder.

No real game files are used here -- fixtures are hand-built to match the
documented framing (u6data/u6tech.txt "Pixel blocks", cross-checked
against pu6e's tile.py and validated end to end against a real GOG-style
install; see titan/u6/tile.py's module docstring for how that validation
was done). ``from_parts``'s ``num_tiles`` override keeps these fixtures
small instead of requiring a full 0x800-tile MASKTYPE buffer.
"""

from __future__ import annotations

import struct
import unittest

import numpy as np

from titan.u6.palette import U6Palette
from titan.u6.tile import (
    MASKTYPE_PIXELBLOCKS,
    MASKTYPE_PLAIN,
    MASKTYPE_TRANSPARENT,
    U6Tiles,
    U6TilesError,
    read_tile_index,
)


def _pixelblock_body(records: list[tuple[int, int, list[int]]], body_len: int) -> bytes:
    """records: list of (displacement, run_length, pixels); auto-adds the run_length=0 terminator."""
    body = bytearray()
    for disp, run_length, pixels in records:
        body += struct.pack("<HB", disp, run_length)
        body += bytes(pixels)
    body += struct.pack("<HB", 0, 0)  # terminator
    assert len(body) <= body_len, "test fixture: body_len too small for records"
    body += b"\xed" * (body_len - len(body))
    return bytes(body)


def _pixelblock_tile(records: list[tuple[int, int, list[int]]], paragraphs: int = 1) -> bytes:
    body_len = paragraphs * 16 - 1
    return bytes([paragraphs]) + _pixelblock_body(records, body_len)


class FixedFormatTests(unittest.TestCase):
    def test_plain_and_transparent_tiles_read_straight_through(self):
        masktypes = bytes([MASKTYPE_PLAIN, MASKTYPE_TRANSPARENT])
        tile0 = bytes([1] * 256)
        tile1 = bytes([0xFF] * 128 + [2] * 128)
        tiles = U6Tiles.from_parts(masktypes, tile0 + tile1, b"", num_tiles=2)
        self.assertEqual(tiles.num_tiles, 2)
        self.assertEqual(tiles.get_tile(0), tile0)
        self.assertEqual(tiles.get_tile(1), tile1)

    def test_maptiles_objtiles_are_concatenated_in_order(self):
        masktypes = bytes([MASKTYPE_PLAIN, MASKTYPE_PLAIN])
        maptiles = bytes([1] * 256)
        objtiles = bytes([2] * 256)
        tiles = U6Tiles.from_parts(masktypes, maptiles, objtiles, num_tiles=2)
        self.assertEqual(tiles.get_tile(0), maptiles)
        self.assertEqual(tiles.get_tile(1), objtiles)


class PixelBlockTests(unittest.TestCase):
    def test_simple_pixel_blocks_placed_at_correct_offsets(self):
        # block A: displacement 5 from origin -> cursor 5, 3 pixels
        # block B: displacement 20 from end of A (cursor 8) -> cursor 28, 2 pixels
        tile_bytes = _pixelblock_tile([(5, 3, [10, 11, 12]), (20, 2, [20, 21])])
        masktypes = bytes([MASKTYPE_PIXELBLOCKS])
        tiles = U6Tiles.from_parts(masktypes, tile_bytes, b"", num_tiles=1)
        decoded = tiles.get_tile(0)
        self.assertEqual(len(decoded), 256)
        self.assertEqual(decoded[5:8], bytes([10, 11, 12]))
        self.assertEqual(decoded[28:30], bytes([20, 21]))
        # everything else stays transparent
        untouched = decoded[0:5] + decoded[8:28] + decoded[30:]
        self.assertTrue(all(b == 0xFF for b in untouched))

    def test_wraparound_threshold_matches_pu6e_formula(self):
        # displacement 1760 -> actual_add = (1760 % 160) + 160 = 160
        tile_bytes = _pixelblock_tile([(1760, 2, [1, 2])])
        masktypes = bytes([MASKTYPE_PIXELBLOCKS])
        tiles = U6Tiles.from_parts(masktypes, tile_bytes, b"", num_tiles=1)
        decoded = tiles.get_tile(0)
        self.assertEqual(decoded[160:162], bytes([1, 2]))

    def test_mixed_fixed_and_pixelblock_tiles(self):
        masktypes = bytes([MASKTYPE_PLAIN, MASKTYPE_PIXELBLOCKS, MASKTYPE_TRANSPARENT])
        plain_tile = bytes([9] * 256)
        pb_tile = _pixelblock_tile([(0, 1, [42])])
        trans_tile = bytes([0xFF] * 256)
        tiles = U6Tiles.from_parts(masktypes, plain_tile + pb_tile, trans_tile, num_tiles=3)
        self.assertEqual(tiles.get_tile(0), plain_tile)
        self.assertEqual(tiles.get_tile(1)[0], 42)
        self.assertEqual(tiles.get_tile(2), trans_tile)


class ErrorHandlingTests(unittest.TestCase):
    def test_unknown_masktype_raises(self):
        with self.assertRaises(U6TilesError):
            U6Tiles.from_parts(bytes([0x7F]), bytes(256), b"", num_tiles=1)

    def test_truncated_pixelblock_record_raises(self):
        # length byte claims 1 paragraph (15 body bytes) but body is too
        # short to hold even one full (displacement, run_length) header.
        tile_bytes = bytes([1]) + b"\x00\x00"
        with self.assertRaises(U6TilesError):
            U6Tiles.from_parts(bytes([MASKTYPE_PIXELBLOCKS]), tile_bytes, b"", num_tiles=1)

    def test_out_of_bounds_pixel_run_raises(self):
        # displacement 1919 is past the 1760 wraparound threshold:
        # actual_add = (1919 % 160) + 160 = 319, so even this single
        # first block (cursor starts at 0) lands a 10-byte run at
        # [319:329], well past the 256-byte tile bound.
        tile_bytes = _pixelblock_tile([(1919, 10, list(range(10)))], paragraphs=2)
        with self.assertRaises(U6TilesError):
            U6Tiles.from_parts(bytes([MASKTYPE_PIXELBLOCKS]), tile_bytes, b"", num_tiles=1)


class TileIndexTests(unittest.TestCase):
    def test_read_tile_index_unpacks_little_endian_words(self):
        import tempfile
        import os as _os

        data = struct.pack("<3H", 0, 16, 32)
        fd, path = tempfile.mkstemp()
        try:
            with _os.fdopen(fd, "wb") as f:
                f.write(data)
            self.assertEqual(read_tile_index(path), (0, 16, 32))
        finally:
            _os.remove(path)


class RenderingTests(unittest.TestCase):
    def test_to_array_shape(self):
        tiles = U6Tiles.from_parts(bytes([MASKTYPE_PLAIN]), bytes(range(256)), b"", num_tiles=1)
        arr = tiles.to_array(0)
        self.assertEqual(arr.shape, (16, 16))
        self.assertEqual(arr[0, 0], 0)
        self.assertEqual(arr[15, 15], 255)

    def test_to_pil_image_transparent_alpha(self):
        tile_data = bytes([1] * 128 + [0xFF] * 128)
        tiles = U6Tiles.from_parts(bytes([MASKTYPE_PLAIN]), tile_data, b"", num_tiles=1)
        palette = U6Palette.parse(bytes(1024))
        img = tiles.to_pil_image(0, palette)
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(img.size, (16, 16))
        alpha = np.array(img)[:, :, 3].flatten().tolist()
        self.assertEqual(alpha[:128], [255] * 128)
        self.assertEqual(alpha[128:], [0] * 128)

    def test_to_pil_image_opaque_mode(self):
        tiles = U6Tiles.from_parts(bytes([MASKTYPE_PLAIN]), bytes(256), b"", num_tiles=1)
        palette = U6Palette.parse(bytes(1024))
        img = tiles.to_pil_image(0, palette, transparent=False)
        self.assertEqual(img.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
