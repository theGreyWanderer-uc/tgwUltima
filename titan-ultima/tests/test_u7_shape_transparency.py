"""Tests for context-dependent index-255 transparency: RLE sprites treat
it as transparent; flat (non-RLE) terrain tiles render it as an ordinary
opaque colour.  Exercises titan.u7.shape's real RLE encode/decode path
(not reimplemented here) plus titan.u7.palette_semantics's explicit
context helper.
"""

from __future__ import annotations

import unittest

import numpy as np

from titan.u7.palette_semantics import is_transparent_in_context
from titan.u7.shape import U7Shape


class ContextualTransparencyHelperTests(unittest.TestCase):
    def test_255_transparent_for_rle_sprites(self):
        self.assertTrue(is_transparent_in_context(0xFF, rle_sprite=True))

    def test_255_opaque_for_flat_tiles(self):
        self.assertFalse(is_transparent_in_context(0xFF, rle_sprite=False))

    def test_ordinary_index_never_transparent(self):
        self.assertFalse(is_transparent_in_context(10, rle_sprite=True))
        self.assertFalse(is_transparent_in_context(10, rle_sprite=False))


class RleRoundTripTests(unittest.TestCase):
    """Exercises shape.py's real encode (Frame.to_rle_bytes) and decode
    (U7Shape.from_data) path end to end."""

    def _build_sprite_shape(self, pixels: np.ndarray) -> U7Shape:
        shape = U7Shape()
        frame = U7Shape.Frame()
        frame.height, frame.width = pixels.shape
        frame.xoff = 0
        frame.yoff = 0
        frame.is_tile = False
        frame.pixels = pixels
        shape.frames = [frame]
        return shape

    def test_uncovered_pixels_decode_as_0xff(self):
        pixels = np.full((2, 4), 0xFF, dtype=np.uint8)
        pixels[0, 1] = 5  # one opaque pixel; the rest is "uncovered" by any span
        shape = self._build_sprite_shape(pixels)

        decoded = U7Shape.from_data(shape.to_bytes(), is_tile=False)
        decoded_pixels = decoded.frames[0].pixels

        self.assertEqual(decoded_pixels[0, 1], 5)
        self.assertTrue(np.all(np.where(decoded_pixels == 5, True, decoded_pixels == 0xFF)))

    def test_fully_transparent_frame_round_trips(self):
        pixels = np.full((3, 3), 0xFF, dtype=np.uint8)
        shape = self._build_sprite_shape(pixels)

        decoded = U7Shape.from_data(shape.to_bytes(), is_tile=False)
        decoded_pixels = decoded.frames[0].pixels

        self.assertTrue(np.all(decoded_pixels == 0xFF))

    def test_opaque_pixel_with_real_value_0xff_would_be_ambiguous(self):
        # Documents the actual encoder convention: 0xFF is *always* the
        # transparent sentinel for RLE sprites -- there is no way to
        # author an opaque pixel using palette index 255 in this format.
        # A pixel array containing only 0xFF therefore round-trips as
        # "nothing drawn", not "opaque colour 255 everywhere".
        pixels = np.array([[0xFF, 10, 0xFF]], dtype=np.uint8)
        shape = self._build_sprite_shape(pixels)
        decoded = U7Shape.from_data(shape.to_bytes(), is_tile=False)
        decoded_pixels = decoded.frames[0].pixels
        self.assertEqual(list(decoded_pixels[0]), [0xFF, 10, 0xFF])


class FlatTileOpacityTests(unittest.TestCase):
    def test_flat_tile_has_no_transparent_sentinel(self):
        # Ground tiles are raw 8x8 pixel grids with no RLE header and no
        # transparency concept at all -- every byte is real pixel data,
        # including value 0xFF if a tile happens to use that palette
        # index for an ordinary opaque colour.
        raw_tile = bytes([0xFF] * 64)
        shape = U7Shape.from_data(raw_tile, is_tile=True)
        frame = shape.frames[0]

        self.assertTrue(frame.is_tile)
        self.assertTrue(np.all(frame.pixels == 0xFF))

    def test_flat_tile_round_trips_arbitrary_bytes_unchanged(self):
        raw_tile = bytes(range(64))  # every byte value 0-63, no sentinel meaning
        shape = U7Shape.from_data(raw_tile, is_tile=True)
        re_encoded = shape.frames[0].to_rle_bytes()
        self.assertEqual(re_encoded, raw_tile)


if __name__ == "__main__":
    unittest.main()
