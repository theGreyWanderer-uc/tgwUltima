"""Tests for titan.u7.palette_cycle: Exult's six colour-cycling ranges."""

from __future__ import annotations

import math
import unittest
from functools import reduce

from titan.u7.palette import U7Palette
from titan.u7.palette_cycle import apply_all_cycles, rotate_range
from titan.u7.palette_semantics import CYCLE_RANGES


class RotateRangeTests(unittest.TestCase):
    def test_single_step_moves_last_to_front(self):
        colors = list(range(256))
        result = rotate_range(colors, 224, 8, steps=1)
        self.assertEqual(result[224:232], [231, 224, 225, 226, 227, 228, 229, 230])

    def test_full_length_wrap_returns_original(self):
        colors = list(range(256))
        result = rotate_range(colors, 224, 8, steps=8)
        self.assertEqual(result, colors)

    def test_zero_steps_is_noop(self):
        colors = list(range(256))
        self.assertEqual(rotate_range(colors, 224, 8, steps=0), colors)

    def test_does_not_mutate_input(self):
        colors = list(range(256))
        original = list(colors)
        rotate_range(colors, 224, 8, steps=3)
        self.assertEqual(colors, original)

    def test_outside_range_untouched(self):
        colors = list(range(256))
        result = rotate_range(colors, 224, 8, steps=1)
        self.assertEqual(result[:224], colors[:224])
        self.assertEqual(result[232:], colors[232:])


class ApplyAllCyclesTests(unittest.TestCase):
    def test_all_six_ranges_rotate_last_to_front(self):
        colors = list(range(256))
        result = apply_all_cycles(colors, steps=1)
        for rng in CYCLE_RANGES:
            window = result[rng.start:rng.start + rng.length]
            expected = [rng.start + rng.length - 1] + list(
                range(rng.start, rng.start + rng.length - 1)
            )
            self.assertEqual(window, expected, msg=f"range {rng.name}")

    def test_lcm_wrap_returns_original(self):
        colors = list(range(256))
        lengths = [r.length for r in CYCLE_RANGES]
        lcm = reduce(lambda a, b: a * b // math.gcd(a, b), lengths)
        self.assertEqual(apply_all_cycles(colors, steps=lcm), colors)

    def test_total_cycled_colors_is_31(self):
        self.assertEqual(sum(r.length for r in CYCLE_RANGES), 31)


class AtCyclePhaseTests(unittest.TestCase):
    def test_matches_manual_rotation(self):
        pal = U7Palette.default_palette()
        cycled = pal.at_cycle_phase(250, rot_speed_ms=100)  # 2 steps
        manual = apply_all_cycles(pal.colors, steps=2)
        self.assertEqual(cycled.colors, manual)

    def test_zero_elapsed_is_identity(self):
        pal = U7Palette.default_palette()
        cycled = pal.at_cycle_phase(0)
        self.assertEqual(cycled.colors, pal.colors)

    def test_preserves_metadata(self):
        pal = U7Palette.default_palette()
        pal.source = "test-source"
        pal.flex_index = 3
        cycled = pal.at_cycle_phase(500)
        self.assertEqual(cycled.source, "test-source")
        self.assertEqual(cycled.flex_index, 3)

    def test_default_rot_speed_is_100ms(self):
        pal = U7Palette.default_palette()
        one_tick = pal.at_cycle_phase(100)
        manual = apply_all_cycles(pal.colors, steps=1)
        self.assertEqual(one_tick.colors, manual)


if __name__ == "__main__":
    unittest.main()
