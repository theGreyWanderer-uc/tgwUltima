"""Tests for titan.u7.translucency and titan.u7.palette_transform.

Builds U7Xforms/U7Blends directly from in-memory data (both are plain
data containers with no file-I/O side effects in their __init__), so
these tests exercise U7Translucency's own join/reversal logic in
isolation without needing real XFORM.TBL/BLENDS.DAT files.
"""

from __future__ import annotations

import unittest

from titan.u7.palette_transform import (
    Ramp,
    generate_remap_xformtable,
    get_ramps,
    remap_all_ramps,
    remap_ramp,
    shift_index,
    xform_index,
)
from titan.u7.shapeinfo import U7Blends, U7BlendRecord, U7Xforms
from titan.u7.translucency import U7Translucency


def _make_translucency(num_slots=3, xform_file_order=None):
    blends = U7Blends(
        [
            U7BlendRecord(
                index=i, r=i, g=i, b=i, alpha=200,
                translucent_palette_index=0xFF - num_slots + i,
            )
            for i in range(num_slots)
        ]
    )
    if xform_file_order is None:
        # File record i is a uniform table of all bytes == i, so each
        # table is trivially distinguishable in assertions.
        xform_file_order = [bytes([i] * 256) for i in range(num_slots)]
    return U7Translucency(U7Xforms(xform_file_order), blends)


class ReversalTests(unittest.TestCase):
    """shapeid.cc:328-339 -- file record i maps to xforms[nxforms-1-i]."""

    def test_slot_0_maps_to_last_file_record(self):
        t = _make_translucency(num_slots=3)
        self.assertEqual(t.table_by_slot(0), bytes([2] * 256))

    def test_last_slot_maps_to_first_file_record(self):
        t = _make_translucency(num_slots=3)
        self.assertEqual(t.table_by_slot(2), bytes([0] * 256))

    def test_out_of_range_slot_returns_none(self):
        t = _make_translucency(num_slots=3)
        self.assertIsNone(t.table_by_slot(3))
        self.assertIsNone(t.table_by_slot(-1))

    def test_missing_file_records_fall_back_to_identity(self):
        # 3 blend slots declared, but only 1 real xform file record --
        # matches Exult's ds.good()==False identity-table fallback.
        t = _make_translucency(num_slots=3, xform_file_order=[bytes([9] * 256)])
        self.assertEqual(t.table_by_slot(2), bytes([9] * 256))
        self.assertEqual(t.table_by_slot(0), bytes(range(256)))
        self.assertEqual(t.table_by_slot(1), bytes(range(256)))


class CompositeIndexTests(unittest.TestCase):
    def test_maps_dest_index_through_real_table(self):
        t = _make_translucency(num_slots=2)
        pixel_value = t.xfstart  # slot 0 -> last file record (all bytes == 1)
        self.assertEqual(t.composite_index(5, pixel_value), 1)

    def test_non_translucent_index_passthrough(self):
        t = _make_translucency(num_slots=2)
        self.assertEqual(t.composite_index(5, 100), 5)


class RgbaPreviewTests(unittest.TestCase):
    def test_preview_uses_raw_undivided_blend_colors(self):
        # Matches Exult's translucency_argb overlay table (shapeid.cc:364-368),
        # which uses the full 0-255 BLENDS.DAT bytes directly -- NOT the /4
        # scaling create_trans_table applies for the indexed remap path.
        t = _make_translucency(num_slots=1)
        preview = t.composite_rgba_preview(t.xfstart)
        blend = t.blends.records[0]
        self.assertEqual(preview, (blend.r, blend.g, blend.b, blend.alpha))

    def test_non_translucent_index_returns_none(self):
        t = _make_translucency(num_slots=1)
        self.assertIsNone(t.composite_rgba_preview(50))


class ShiftIndexTests(unittest.TestCase):
    def test_preserves_index_0_and_255(self):
        self.assertEqual(shift_index(0, 77), 0)
        self.assertEqual(shift_index(255, 77), 255)

    def test_wraps_at_256(self):
        self.assertEqual(shift_index(250, 10), 4)

    def test_ordinary_shift(self):
        self.assertEqual(shift_index(10, 5), 15)


class XformIndexTests(unittest.TestCase):
    def test_uses_same_table_as_translucency(self):
        t = _make_translucency(num_slots=2)
        self.assertEqual(xform_index(7, t, 0), t.table_by_slot(0)[7])

    def test_out_of_range_slot_is_identity(self):
        t = _make_translucency(num_slots=2)
        self.assertEqual(xform_index(7, t, 99), 7)


class RampDetectionTests(unittest.TestCase):
    def test_forced_breaks_at_cycle_starts(self):
        # A perfectly flat (zero brightness-jump) palette should still
        # break exactly at the six cycle-range starts.
        colors = [(10, 10, 10)] * 256
        starts = {r.start for r in get_ramps(colors)}
        for cycle_start in (224, 232, 240, 244, 248, 252):
            self.assertIn(cycle_start, starts)

    def test_index_0_never_in_a_ramp(self):
        colors = [(i % 256, i % 256, i % 256) for i in range(256)]
        for r in get_ramps(colors):
            self.assertGreaterEqual(r.start, 1)

    def test_too_short_input_returns_empty(self):
        self.assertEqual(get_ramps([(0, 0, 0)] * 10), [])

    def test_at_most_32_ramps(self):
        # Alternate brightness every index to force a break constantly.
        colors = [(255 if i % 2 else 0,) * 3 for i in range(256)]
        self.assertLessEqual(len(get_ramps(colors)), 32)


class RampRemapTests(unittest.TestCase):
    def setUp(self):
        self.ramps = [Ramp(1, 10), Ramp(11, 20), Ramp(21, 30)]

    def test_remap_ramp_maps_into_target_proportionally(self):
        self.assertEqual(remap_ramp(1, 0, 1, self.ramps), 11)
        self.assertEqual(remap_ramp(10, 0, 1, self.ramps), 20)

    def test_self_remap_is_identity(self):
        table = generate_remap_xformtable(self.ramps, {0: 0})
        self.assertEqual(table[5], 5)

    def test_out_of_range_ramp_ignored(self):
        table = generate_remap_xformtable(self.ramps, {0: 99})
        self.assertEqual(table[5], 5)

    def test_remap_all_ramps_moves_everything_but_target(self):
        for idx in (1, 11, 21):
            result = remap_all_ramps(idx, 2, self.ramps)
            self.assertTrue(21 <= result <= 30, msg=f"index {idx} -> {result}")

    def test_untouched_indices_stay_identity(self):
        table = generate_remap_xformtable(self.ramps, {0: 1})
        self.assertEqual(table[50], 50)  # outside every ramp


if __name__ == "__main__":
    unittest.main()
