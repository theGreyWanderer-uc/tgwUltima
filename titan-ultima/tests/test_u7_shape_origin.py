"""U7 frame origins use the same xright/ybelow convention as Exult Studio."""

from __future__ import annotations

import struct
import unittest

import numpy as np

from titan.u7.shape import U7Shape


class U7ShapeOriginTests(unittest.TestCase):
    def test_exult_studio_origin_round_trips_without_changing_extents(self) -> None:
        frame = U7Shape.Frame()
        frame.width = 5
        frame.height = 7
        frame.origin_x = -2
        frame.origin_y = 3
        frame.pixels = np.full((7, 5), 1, dtype=np.uint8)

        shape = U7Shape()
        shape.frames = [frame]
        encoded = shape.to_bytes()

        # A one-frame SHP starts its RLE frame at byte 8.  The header order is
        # xright, xleft, yabove, ybelow; Exult Studio displays the first and
        # last values as Origin X/Y.
        self.assertEqual(struct.unpack_from("<hhhh", encoded, 8), (-2, 6, 3, 3))

        decoded = U7Shape.from_data(encoded).frames[0]
        self.assertEqual((decoded.origin_x, decoded.origin_y), (-2, 3))
        self.assertEqual(
            (decoded.hotspot_x_from_left, decoded.hotspot_y_from_top), (6, 3)
        )
        np.testing.assert_array_equal(decoded.pixels, frame.pixels)

    def test_top_left_hotspot_conversion_produces_studio_origin(self) -> None:
        frame = U7Shape.Frame()
        frame.width = 35
        frame.height = 28

        frame.set_hotspot_from_top_left(34, 27)

        self.assertEqual((frame.origin_x, frame.origin_y), (0, 0))

    def test_raw_tile_uses_exult_synthetic_origin_values(self) -> None:
        tile = U7Shape.from_data(bytes(range(64)), is_tile=True).frames[0]

        self.assertEqual((tile.origin_x, tile.origin_y), (-1, -1))
        self.assertEqual((tile.hotspot_x_from_left, tile.hotspot_y_from_top), (8, 8))


if __name__ == "__main__":
    unittest.main()
