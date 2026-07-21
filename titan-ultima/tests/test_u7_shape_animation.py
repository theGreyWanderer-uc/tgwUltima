"""Tests for titan.u7.shape_animation: Exult's default per-anim-type
timing (ported from aniinf.cc/animate.cc) and colour-cycle pixel
detection.  No real game files required -- every case here is checked
against the exact values traced from the Exult source.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from titan.u7.shape_animation import (
    AniType,
    default_animation_for_tfa,
    has_cycle_pixels,
    save_gif,
    simulate_frame_sequence,
)


class DefaultAnimationForTfaTests(unittest.TestCase):
    def test_type_0_and_1_are_timesynched(self):
        for t in (0, 1):
            anim = default_animation_for_tfa(t, 12)
            self.assertEqual(anim.ani_type, AniType.TIMESYNCHED)
            self.assertEqual(anim.nframes, 12)
            self.assertEqual(anim.frame_delay, 1)

    def test_type_5_is_looping_with_partial_freeze_chance(self):
        anim = default_animation_for_tfa(5, 6)
        self.assertEqual(anim.ani_type, AniType.LOOPING)
        self.assertEqual(anim.recycle, 0)
        self.assertEqual(anim.freeze_first_chance, 20)

    def test_type_6_is_random_frames(self):
        anim = default_animation_for_tfa(6, 8)
        self.assertEqual(anim.ani_type, AniType.RANDOM_FRAMES)

    def test_type_8_is_hourly(self):
        anim = default_animation_for_tfa(8, 4)
        self.assertEqual(anim.ani_type, AniType.HOURLY)

    def test_types_9_and_10_are_looping_with_distinct_chances(self):
        self.assertEqual(default_animation_for_tfa(9, 6).freeze_first_chance, 8)
        self.assertEqual(default_animation_for_tfa(10, 6).freeze_first_chance, 6)

    def test_type_11_is_looping_frozen_by_default(self):
        anim = default_animation_for_tfa(11, 8)
        self.assertEqual(anim.ani_type, AniType.LOOPING)
        self.assertEqual(anim.freeze_first_chance, 0)
        self.assertEqual(anim.recycle, 7)  # nframes - 1

    def test_types_12_and_14_are_slow_timesynched(self):
        for t in (12, 14):
            anim = default_animation_for_tfa(t, 10)
            self.assertEqual(anim.ani_type, AniType.TIMESYNCHED)
            self.assertEqual(anim.frame_delay, 4)

    def test_type_13_is_non_looping(self):
        anim = default_animation_for_tfa(13, 5)
        self.assertEqual(anim.ani_type, AniType.NON_LOOPING)

    def test_type_15_clamps_to_six_frames(self):
        anim = default_animation_for_tfa(15, 20)
        self.assertEqual(anim.nframes, 6)
        self.assertEqual(anim.frame_delay, 4)

    def test_type_15_clamps_further_when_fewer_real_frames_exist(self):
        anim = default_animation_for_tfa(15, 3)
        self.assertEqual(anim.nframes, 3)

    def test_unhandled_types_return_none(self):
        for t in (2, 3, 4, 7, -1, 16, 99):
            self.assertIsNone(default_animation_for_tfa(t, 10))


class SimulateFrameSequenceTests(unittest.TestCase):
    def test_timesynched_cycles_and_wraps(self):
        anim = default_animation_for_tfa(1, 12)
        seq = simulate_frame_sequence(anim, 0, 16)
        self.assertEqual(seq, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1, 2, 3])

    def test_timesynched_respects_first_frame_offset(self):
        anim = default_animation_for_tfa(1, 4)
        seq = simulate_frame_sequence(anim, 100, 5)
        self.assertEqual(seq, [100, 101, 102, 103, 100])

    def test_hourly_wraps_at_nframes_not_24(self):
        anim = default_animation_for_tfa(8, 4)
        seq = simulate_frame_sequence(anim, 0, 6, hour_start=0)
        self.assertEqual(seq, [0, 1, 2, 3, 0, 1])

    def test_hourly_respects_start_hour(self):
        anim = default_animation_for_tfa(8, 4)
        seq = simulate_frame_sequence(anim, 0, 3, hour_start=2)
        self.assertEqual(seq, [2, 3, 0])

    def test_non_looping_clamps_at_last_frame(self):
        anim = default_animation_for_tfa(13, 4)
        seq = simulate_frame_sequence(anim, 0, 8)
        self.assertEqual(seq, [0, 1, 2, 3, 3, 3, 3, 3])

    def test_looping_frozen_when_chance_is_zero(self):
        anim = default_animation_for_tfa(11, 8)  # freeze_first_chance=0
        seq = simulate_frame_sequence(anim, 0, 10)
        self.assertEqual(seq, [0] * 10)

    def test_looping_with_recycle_jumps_after_first_full_pass(self):
        # recycle=2 on a 6-frame loop: after the first full cycle back to
        # 0, it jumps to (nframes-recycle) instead of restarting at 0,
        # replaying only the last `recycle` frames from then on.
        from titan.u7.shape_animation import AnimationInfo

        anim = AnimationInfo(AniType.LOOPING, nframes=6, recycle=2, freeze_first_chance=100)
        seq = simulate_frame_sequence(anim, 0, 10)
        self.assertEqual(seq, [1, 2, 3, 4, 5, 4, 5, 4, 5, 4])

    def test_random_frames_is_deterministic_sequential_fallback(self):
        anim = default_animation_for_tfa(6, 5)
        seq = simulate_frame_sequence(anim, 0, 7)
        self.assertEqual(seq, [0, 1, 2, 3, 4, 0, 1])

    def test_single_frame_shape_never_changes(self):
        anim = default_animation_for_tfa(1, 1)
        seq = simulate_frame_sequence(anim, 5, 4)
        self.assertEqual(seq, [5, 5, 5, 5])


class HasCyclePixelsTests(unittest.TestCase):
    def test_detects_pixels_in_any_cycle_range(self):
        px = np.array([[10, 224, 30]], dtype=np.uint8)
        self.assertTrue(has_cycle_pixels(px))

    def test_no_cycle_pixels_returns_false(self):
        px = np.array([[10, 20, 30]], dtype=np.uint8)
        self.assertFalse(has_cycle_pixels(px))

    def test_boundary_223_excluded_224_included(self):
        self.assertFalse(has_cycle_pixels(np.array([[223]], dtype=np.uint8)))
        self.assertTrue(has_cycle_pixels(np.array([[224]], dtype=np.uint8)))

    def test_boundary_254_included_255_excluded(self):
        self.assertTrue(has_cycle_pixels(np.array([[254]], dtype=np.uint8)))
        self.assertFalse(has_cycle_pixels(np.array([[255]], dtype=np.uint8)))


class SaveGifTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writes_multi_frame_gif(self):
        frames = [
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)),
            Image.new("RGBA", (4, 4), (0, 255, 0, 255)),
            Image.new("RGBA", (4, 4), (0, 0, 255, 255)),
        ]
        path = os.path.join(self.tmpdir, "test.gif")
        save_gif(frames, path, duration_ms=100)

        with Image.open(path) as img:
            count = 0
            try:
                while True:
                    img.seek(count)
                    count += 1
            except EOFError:
                pass
        self.assertEqual(count, 3)

    def test_empty_frames_raises(self):
        with self.assertRaises(ValueError):
            save_gif([], os.path.join(self.tmpdir, "empty.gif"), duration_ms=100)


if __name__ == "__main__":
    unittest.main()
