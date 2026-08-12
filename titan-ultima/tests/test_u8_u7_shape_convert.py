"""Tests for titan.u8.u7_shape_convert (U8 -> U7 shape conversion).

Real-data findings this module's design is grounded in (see its module
docstring for the full account, verified against real Pentagram/Exult
source and real U8/U7 game data, not just theorized):

* U8 and U7 share the same 2:1 dimetric/8-direction sprite convention;
  U8's hotspot sits at bottom-center of the footprint, U7's at
  bottom-right.
* Footprint-calibrated *absolute* target sizes distort shapes whose
  aspect ratio doesn't match the "typical" object at that footprint
  (a real U8 support-post prop, footprint 1x1x4, came out squashed
  when forced into a size averaged from other 1x1x4 objects). Fixed by
  deriving one *uniform* scale factor from matching pixel area instead
  of forcing an absolute width/height -- these tests cover that logic
  directly with hand-built (non-binary) fixtures, since the scaling
  math itself doesn't need real file parsing to verify.
"""

from __future__ import annotations

import unittest

import numpy as np

from titan.palette import U8Palette
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape
from titan.u8.shape import U8Shape
from titan.u8.u7_shape_convert import (
    _median_size,
    convert_frame,
    convert_shape,
    pick_target_size,
)


def _u8_palette() -> U8Palette:
    pal = U8Palette()
    # index 0 = red, index 1 = blue, rest black -- enough to verify quantization.
    pal.colors = [(0, 0, 0)] * 256
    pal.colors[0] = (255, 0, 0)
    pal.colors[1] = (0, 0, 255)
    return pal


def _u7_palette() -> U7Palette:
    pal = U7Palette()
    pal.colors = [(0, 0, 0)] * 256
    pal.colors[10] = (255, 0, 0)  # nearest match for U8's red
    pal.colors[20] = (0, 0, 255)  # nearest match for U8's blue
    return pal


def _solid_u8_frame(width: int, height: int, index: int) -> U8Shape.Frame:
    frame = U8Shape.Frame()
    frame.width = width
    frame.height = height
    frame.xoff = 0
    frame.yoff = 0
    frame.pixels = np.full((height, width), index, dtype=np.uint8)
    return frame


class PickTargetSizeTests(unittest.TestCase):
    def test_exact_footprint_match_uses_median(self) -> None:
        table = {(1, 1, 0): [(10, 20), (12, 22), (14, 24)]}
        self.assertEqual(pick_target_size(table, (1, 1, 0)), (12, 22))

    def test_falls_back_to_nearest_z_same_xy(self) -> None:
        table = {(1, 1, 0): [(10, 10)], (1, 1, 5): [(10, 50)]}
        # Footprint (1,1,2) has no exact entry; z=0 is closer than z=5.
        self.assertEqual(pick_target_size(table, (1, 1, 2)), (10, 10))

    def test_falls_back_to_nearest_footprint_overall(self) -> None:
        table = {(2, 2, 0): [(40, 40)]}
        self.assertEqual(pick_target_size(table, (1, 1, 0)), (40, 40))

    def test_empty_table_uses_generic_formula(self) -> None:
        w, h = pick_target_size({}, (2, 1, 3))
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_footprint_clamped_to_valid_range(self) -> None:
        table = {(8, 8, 7): [(64, 64)]}
        # Out-of-range footprint (e.g. U8 allows up to 15) clamps before lookup.
        self.assertEqual(pick_target_size(table, (15, 15, 15)), (64, 64))


class MedianSizeTests(unittest.TestCase):
    def test_computes_per_axis_median(self) -> None:
        # Widths and heights are medianed independently, not as paired tuples.
        samples = [(10, 100), (30, 10), (20, 20)]
        self.assertEqual(_median_size(samples), (20, 20))


class ConvertFrameTests(unittest.TestCase):
    def test_returns_none_for_empty_frame(self) -> None:
        empty = U8Shape.Frame()
        self.assertIsNone(convert_frame(empty, 1.0, _u8_palette(), _u7_palette()))

    def test_scales_uniformly_and_sets_bottom_right_hotspot(self) -> None:
        src = _solid_u8_frame(4, 8, index=0)
        frame = convert_frame(src, 2.0, _u8_palette(), _u7_palette())
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual((frame.width, frame.height), (8, 16))
        self.assertEqual((frame.origin_x, frame.origin_y), (0, 0))
        self.assertEqual(frame.hotspot_x_from_left, frame.width - 1)
        self.assertEqual(frame.hotspot_y_from_top, frame.height - 1)
        self.assertFalse(frame.is_tile)

    def test_quantizes_to_nearest_u7_palette_color(self) -> None:
        src = _solid_u8_frame(4, 4, index=1)  # U8 index 1 = blue
        frame = convert_frame(src, 1.0, _u8_palette(), _u7_palette())
        # All opaque pixels should map to U7's blue slot (index 20).
        self.assertTrue(np.all(frame.pixels == 20))

    def test_transparent_pixels_stay_transparent(self) -> None:
        src = U8Shape.Frame()
        src.width, src.height = 2, 2
        src.pixels = np.full((2, 2), 0xFF, dtype=np.uint8)  # fully transparent
        frame = convert_frame(src, 1.0, _u8_palette(), _u7_palette())
        self.assertTrue(np.all(frame.pixels == 0xFF))


class ConvertShapeTests(unittest.TestCase):
    def test_converts_all_non_empty_frames_with_consistent_scale(self) -> None:
        shape = U8Shape()
        shape.frames = [_solid_u8_frame(10, 20, index=0), _solid_u8_frame(10, 20, index=1)]
        # Target area 800 = 4x the 10x20 source's area 200 -> uniform linear scale sqrt(4) = 2.0.
        table = {(1, 1, 0): [(20, 40)]}
        u7_shape = convert_shape(shape, (1, 1, 0), _u8_palette(), _u7_palette(), table)

        self.assertEqual(len(u7_shape.frames), 2)
        for frame in u7_shape.frames:
            self.assertEqual((frame.width, frame.height), (20, 40))

    def test_empty_source_shape_returns_empty_u7_shape(self) -> None:
        shape = U8Shape()  # no frames at all
        u7_shape = convert_shape(shape, (1, 1, 0), _u8_palette(), _u7_palette(), {})
        self.assertIsInstance(u7_shape, U7Shape)
        self.assertEqual(len(u7_shape.frames), 0)

    def test_degenerate_first_frame_does_not_blow_up_scale(self) -> None:
        """Regression test for real shape 580 (an animated growth/VFX effect):
        frame sizes ranged 1x1 up to 119x62 within the same shape. Using the
        1x1 first frame as the scale reference computed a huge scale factor
        that then blew up every other frame -- one hit a ~41GB allocation
        during palette requantization. The fix uses the *largest* frame as
        the reference, and MAX_OUTPUT_DIM clamps as a safety net either way.
        """
        shape = U8Shape()
        shape.frames = [
            _solid_u8_frame(1, 1, index=0),  # degenerate placeholder first frame
            _solid_u8_frame(100, 100, index=1),  # the shape's real, much larger content
        ]
        # A generous calibrated target for a (1,1,0) footprint -- if scale were
        # derived from the 1x1 frame, this alone would already demand a huge
        # blowup; derived from the 100x100 frame, the scale should be ~1.0.
        table = {(1, 1, 0): [(100, 100)]}
        u7_shape = convert_shape(shape, (1, 1, 0), _u8_palette(), _u7_palette(), table)

        self.assertEqual(len(u7_shape.frames), 2)
        for frame in u7_shape.frames:
            self.assertLessEqual(frame.width, 64)
            self.assertLessEqual(frame.height, 64)
        # The 1x1 frame should stay tiny (scale ~1.0), not balloon to 64x64.
        self.assertLessEqual(u7_shape.frames[0].width, 2)
        self.assertLessEqual(u7_shape.frames[0].height, 2)


if __name__ == "__main__":
    unittest.main()
