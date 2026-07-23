"""Tests for titan.u7.shape_cycle_scan: per-frame colour-cycle vs
translucency-blend pixel classification, and whole-shape scanning.

No real game files required -- synthetic frames and a hand-built
U7TypeFlags cover every classification case.  The module's correctness
against real data was independently cross-checked against a manual
Black Gate SHAPES.VGA inventory (52 TFA-translucent shapes, 66
frame-animated, 138 non-translucent shapes with cycle pixels across
1,046 frames, 48 of those terrain shapes across 369 frames) -- this
suite locks in the underlying classification rules that produced an
exact match.
"""

from __future__ import annotations

import unittest

import numpy as np

from titan.u7.shape import U7Shape
from titan.u7.shape_cycle_scan import scan_frame, scan_shape
from titan.u7.typeflag import U7TypeFlags

FLAG_IS_ANIMATED = 0x04
FLAG_TRANSLUCENT = 0x80  # byte index 2


def _make_tfa_bytes(entries: dict, num_shapes: int = 4) -> bytes:
    """entries: shape_num -> (byte0, byte2)."""
    base = bytearray(num_shapes * 3)
    for shnum, (byte0, byte2) in entries.items():
        base[shnum * 3] = byte0
        base[shnum * 3 + 2] = byte2
    return bytes(base)


def _make_shape(frames_pixels: list, is_tile: bool = False) -> U7Shape:
    shape = U7Shape()
    for px in frames_pixels:
        frame = U7Shape.Frame()
        frame.height, frame.width = px.shape
        frame.is_tile = is_tile
        frame.pixels = px
        shape.frames.append(frame)
    return shape


class ScanFrameTests(unittest.TestCase):
    def test_non_translucent_all_224_254_are_cycle(self):
        px = np.array([[224, 240, 254]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=False)
        self.assertEqual(r.cycle_indices, frozenset({224, 240, 254}))
        self.assertEqual(r.translucent_indices, frozenset())
        self.assertTrue(r.has_cycle)
        self.assertFalse(r.has_translucency)

    def test_translucent_splits_at_xfstart(self):
        px = np.array([[224, 230, 238, 250]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=True, xfstart=238)
        self.assertEqual(r.cycle_indices, frozenset({224, 230}))
        self.assertEqual(r.translucent_indices, frozenset({238, 250}))

    def test_translucent_with_only_low_range_pixels_has_no_translucency(self):
        px = np.array([[224, 230]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=True, xfstart=238)
        self.assertTrue(r.has_cycle)
        self.assertFalse(r.has_translucency)

    def test_outside_range_ignored(self):
        px = np.array([[0, 100, 223, 255]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=False)
        self.assertEqual(r.cycle_indices, frozenset())
        self.assertFalse(r.has_cycle)

    def test_respects_custom_xfstart(self):
        # A hypothetical archive with only 3 blend slots -> xfstart=252.
        px = np.array([[240, 252]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=True, xfstart=252)
        self.assertEqual(r.cycle_indices, frozenset({240}))
        self.assertEqual(r.translucent_indices, frozenset({252}))

    def test_rle_frame_index_255_is_transparent(self):
        px = np.array([[10, 255]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=False, is_tile=False)
        self.assertFalse(r.is_tile)
        self.assertTrue(r.has_index_255)
        self.assertTrue(r.index_255_is_transparent)

    def test_flat_tile_frame_index_255_is_opaque(self):
        px = np.array([[10, 255]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=False, is_tile=True)
        self.assertTrue(r.is_tile)
        self.assertTrue(r.has_index_255)
        self.assertFalse(r.index_255_is_transparent)

    def test_no_index_255_present(self):
        px = np.array([[10, 20]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=False, is_tile=False)
        self.assertFalse(r.has_index_255)

    def test_255_is_never_classified_as_cycle_or_translucent(self):
        px = np.array([[255]], dtype=np.uint8)
        r = scan_frame(px, 0, is_translucent=True, xfstart=238)
        self.assertFalse(r.has_cycle)
        self.assertFalse(r.has_translucency)


class ScanShapeTests(unittest.TestCase):
    def test_translucent_animated_shape(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({0: (FLAG_IS_ANIMATED, FLAG_TRANSLUCENT)}))
        shape = _make_shape([np.array([[238, 10]], dtype=np.uint8)])
        report = scan_shape(shape, 0, tfa, xfstart=238)

        self.assertTrue(report.is_translucent)
        self.assertTrue(report.is_animated)
        self.assertEqual(report.anim_type, 0)  # defaulted, zero nibble
        self.assertTrue(report.has_frame_animation)
        self.assertTrue(report.has_any_translucency)
        self.assertFalse(report.has_any_cycle)
        self.assertTrue(report.is_affected)

    def test_plain_cycling_shape_not_translucent(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({1: (0x00, 0x00)}))
        shape = _make_shape([np.array([[226, 10]], dtype=np.uint8)])
        report = scan_shape(shape, 1, tfa, xfstart=238)

        self.assertFalse(report.is_translucent)
        self.assertFalse(report.is_animated)
        self.assertFalse(report.has_frame_animation)
        self.assertTrue(report.has_any_cycle)
        self.assertFalse(report.has_any_translucency)
        self.assertEqual(report.all_cycle_indices, frozenset({226}))
        self.assertTrue(report.is_affected)

    def test_unaffected_shape(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({2: (0x00, 0x00)}))
        shape = _make_shape([np.array([[10, 20]], dtype=np.uint8)])
        report = scan_shape(shape, 2, tfa, xfstart=238)
        self.assertFalse(report.is_affected)

    def test_scans_every_frame_not_just_first(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({3: (0x00, 0x00)}))
        shape = _make_shape([
            np.array([[10]], dtype=np.uint8),
            np.array([[10]], dtype=np.uint8),
            np.array([[240]], dtype=np.uint8),  # only frame 2 has a cycle pixel
        ])
        report = scan_shape(shape, 3, tfa, xfstart=238)
        self.assertEqual(report.cycle_frame_indices, [2])
        self.assertTrue(report.is_affected)

    def test_translucent_flag_without_any_high_index_content_is_unaffected(self):
        # Matches a real finding: some TFA-translucent Black Gate shapes
        # simply don't use any pixel in the cycle/translucency range at
        # all, so they render as ordinary opaque sprites regardless of
        # the flag.
        tfa = U7TypeFlags.parse(_make_tfa_bytes({0: (0x00, FLAG_TRANSLUCENT)}))
        shape = _make_shape([np.array([[10, 20]], dtype=np.uint8)])
        report = scan_shape(shape, 0, tfa, xfstart=238)
        self.assertTrue(report.is_translucent)
        self.assertFalse(report.is_affected)

    def test_missing_tfa_entry_defaults_safely(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({}, num_shapes=1))
        shape = _make_shape([np.array([[10]], dtype=np.uint8)])
        report = scan_shape(shape, 99, tfa, xfstart=238)  # out of TFA range
        self.assertFalse(report.is_translucent)
        self.assertFalse(report.is_animated)
        self.assertEqual(report.anim_type, -1)
        self.assertFalse(report.is_affected)

    def test_resolved_animation_exposes_full_parameters(self):
        # anim_type 5 -> LOOPING, recycle=0, freeze_first_chance=20,
        # frame_delay=1 (titan.u7.shape_animation.default_animation_for_tfa).
        tfa_bytes = bytearray(3 * 1024)
        tfa_bytes[0] = FLAG_IS_ANIMATED
        anim_table = bytearray(512)
        anim_table[0] = 5  # shape 0's low nibble
        tfa = U7TypeFlags.parse(bytes(tfa_bytes) + bytes(anim_table))

        shape = _make_shape([np.array([[10]], dtype=np.uint8)] * 6)
        report = scan_shape(shape, 0, tfa, xfstart=238)

        self.assertIsNotNone(report.resolved_animation)
        anim = report.resolved_animation
        self.assertEqual(anim.ani_type.name, "LOOPING")
        self.assertEqual(anim.nframes, 6)
        self.assertEqual(anim.recycle, 0)
        self.assertEqual(anim.freeze_first_chance, 20)
        self.assertEqual(anim.frame_delay, 1)

    def test_resolved_animation_is_none_when_not_animated(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({1: (0x00, 0x00)}))
        shape = _make_shape([np.array([[10]], dtype=np.uint8)])
        report = scan_shape(shape, 1, tfa, xfstart=238)
        self.assertIsNone(report.resolved_animation)
        self.assertFalse(report.has_frame_animation)

    def test_resolved_animation_none_for_leftover_nibble_without_is_animated(self):
        # Mirrors a real Black Gate finding: a nonzero nibble with
        # is_animated=False must NOT resolve to an animation -- Exult's
        # Frame_animator never consults it (objs/animate.cc:273).
        tfa_bytes = bytearray(3 * 1024)
        anim_table = bytearray(512)
        anim_table[0] = 9  # shape 0's low nibble, but is_animated stays 0
        tfa = U7TypeFlags.parse(bytes(tfa_bytes) + bytes(anim_table))

        shape = _make_shape([np.array([[10]], dtype=np.uint8)])
        report = scan_shape(shape, 0, tfa, xfstart=238)

        self.assertEqual(report.anim_type, 9)  # raw value still reported
        self.assertIsNone(report.resolved_animation)  # but not resolved/actionable
        self.assertFalse(report.has_frame_animation)

    def test_is_tile_shape_true_for_tile_frames(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({2: (0x00, 0x00)}))
        shape = _make_shape([np.array([[10]], dtype=np.uint8)], is_tile=True)
        report = scan_shape(shape, 2, tfa, xfstart=238)
        self.assertTrue(report.is_tile_shape)

    def test_is_tile_shape_false_for_rle_frames(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({3: (0x00, 0x00)}))
        shape = _make_shape([np.array([[10]], dtype=np.uint8)], is_tile=False)
        report = scan_shape(shape, 3, tfa, xfstart=238)
        self.assertFalse(report.is_tile_shape)

    def test_index_255_frame_indices_tracked_per_shape(self):
        tfa = U7TypeFlags.parse(_make_tfa_bytes({0: (0x00, 0x00)}))
        shape = _make_shape([
            np.array([[10]], dtype=np.uint8),
            np.array([[255]], dtype=np.uint8),
        ])
        report = scan_shape(shape, 0, tfa, xfstart=238)
        self.assertEqual(report.index_255_frame_indices, [1])


if __name__ == "__main__":
    unittest.main()
