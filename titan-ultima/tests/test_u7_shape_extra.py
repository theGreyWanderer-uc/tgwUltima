"""Tests for titan.u7.shape_extra: the non-TFA Extra shape-metadata model
(field_type/barge_type/mountain_tops from Exult's shape_info.txt), kept
separate from the TFA model per titanWork.md.

The BG/SI field_type section content embedded below is copied verbatim
from the real D:\\_Repos\\exult\\data\\{bg,si}\\shape_info.txt sources, so
these tests double as a real-data regression check without requiring the
Exult repo to be present.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from titan.u7.shape_extra import U7FieldType, U7ShapeExtraTable, U7ShapeInfo
from titan.u7.typeflag import U7TypeFlags

_BG_FIELD_TYPE_SECTION = """
%%section field_type
#	What kind of field this is.
#
#	Format
#		:shapenum/type
#
:895/0

#		Sleep field.
#
:902/1

#		Poison field.
#
:900/2

#		Caltrops.
#
:756/3

#		Campfire.
#
:825/4
%%endsection
"""

_SI_FIELD_TYPE_SECTION = """
%%section field_type
:561/0
:895/0
:902/1
:900/2
:756/3
:825/4
%%endsection
"""

_BARGE_TYPE_SECTION = """
%%section barge_type
:774/4
:796/5
:292/2
:251/3
%%endsection
"""

_MOUNTAIN_TOPS_SECTION = """
%%section mountain_tops
:180/1
:182/1
:983/2
%%endsection
"""


class FieldTypeParsingTests(unittest.TestCase):
    def test_bg_shape_756_is_caltrops(self):
        table = U7ShapeExtraTable.from_text(_BG_FIELD_TYPE_SECTION)
        extra = table.get(756)
        self.assertEqual(extra.field_type, U7FieldType.CALTROPS)

    def test_si_shape_756_is_caltrops(self):
        table = U7ShapeExtraTable.from_text(_SI_FIELD_TYPE_SECTION)
        extra = table.get(756)
        self.assertEqual(extra.field_type, U7FieldType.CALTROPS)

    def test_all_bg_field_types_decode(self):
        table = U7ShapeExtraTable.from_text(_BG_FIELD_TYPE_SECTION)
        self.assertEqual(table.get(895).field_type, U7FieldType.FIRE)
        self.assertEqual(table.get(902).field_type, U7FieldType.SLEEP)
        self.assertEqual(table.get(900).field_type, U7FieldType.POISON)
        self.assertEqual(table.get(756).field_type, U7FieldType.CALTROPS)
        self.assertEqual(table.get(825).field_type, U7FieldType.CAMPFIRE)

    def test_unlisted_shape_defaults_to_none(self):
        table = U7ShapeExtraTable.from_text(_BG_FIELD_TYPE_SECTION)
        extra = table.get(1)
        self.assertEqual(extra.field_type, U7FieldType.NONE)
        self.assertIsNone(extra.barge_type)
        self.assertIsNone(extra.mountain_top)


class BargeAndMountainTopParsingTests(unittest.TestCase):
    def test_barge_type_parses(self):
        table = U7ShapeExtraTable.from_text(_BARGE_TYPE_SECTION)
        self.assertEqual(table.get(774).barge_type, 4)
        self.assertEqual(table.get(292).barge_type, 2)

    def test_mountain_top_parses(self):
        table = U7ShapeExtraTable.from_text(_MOUNTAIN_TOPS_SECTION)
        self.assertEqual(table.get(180).mountain_top, 1)
        self.assertEqual(table.get(983).mountain_top, 2)

    def test_combined_sections_merge_by_shape(self):
        combined = _BG_FIELD_TYPE_SECTION + _BARGE_TYPE_SECTION + _MOUNTAIN_TOPS_SECTION
        table = U7ShapeExtraTable.from_text(combined)
        caltrops = table.get(756)
        self.assertEqual(caltrops.field_type, U7FieldType.CALTROPS)
        self.assertIsNone(caltrops.barge_type)
        seat = table.get(292)
        self.assertEqual(seat.barge_type, 2)
        self.assertEqual(seat.field_type, U7FieldType.NONE)


class FromDirTests(unittest.TestCase):
    def test_loose_static_dir_file_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "shape_info.txt"), "w", encoding="latin-1") as f:
                f.write(_BG_FIELD_TYPE_SECTION)
            table = U7ShapeExtraTable.from_dir(tmp, game="bg")
            self.assertEqual(table.get(756).field_type, U7FieldType.CALTROPS)

    def test_missing_file_and_no_exult_flx_returns_empty_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = U7ShapeExtraTable.from_dir(tmp, game="bg", exult_flx_path=None)
            self.assertEqual(table.get(756).field_type, U7FieldType.NONE)


class U7ShapeInfoFacadeTests(unittest.TestCase):
    def _entry_with_contact_effect(self, shape_num: int, has_contact_effect: bool):
        base = bytearray(3 * 1024)
        byte1 = 0x05  # shape_class=5 (quality_flags)
        if has_contact_effect:
            byte1 |= 0x10
        base[shape_num * 3 + 1] = byte1
        tfa_bytes = bytes(base) + bytes(512)
        return U7TypeFlags.parse(tfa_bytes).get(shape_num)

    def test_caltrops_becomes_field_object(self):
        entry = self._entry_with_contact_effect(756, has_contact_effect=True)
        extra = U7ShapeExtraTable.from_text(_BG_FIELD_TYPE_SECTION).get(756)
        info = U7ShapeInfo(tfa=entry, extra=extra)
        self.assertTrue(info.is_typed_field)
        self.assertTrue(info.becomes_field_object)

    def test_contact_effect_without_field_type_does_not_become_field_object(self):
        # has_contact_effect true, but no field_type entry for this shape.
        entry = self._entry_with_contact_effect(1, has_contact_effect=True)
        extra = U7ShapeExtraTable.from_text(_BG_FIELD_TYPE_SECTION).get(1)
        info = U7ShapeInfo(tfa=entry, extra=extra)
        self.assertFalse(info.is_typed_field)
        self.assertFalse(info.becomes_field_object)

    def test_field_type_without_contact_effect_does_not_become_field_object(self):
        # field_type entry present, but has_contact_effect bit not set.
        entry = self._entry_with_contact_effect(756, has_contact_effect=False)
        extra = U7ShapeExtraTable.from_text(_BG_FIELD_TYPE_SECTION).get(756)
        info = U7ShapeInfo(tfa=entry, extra=extra)
        self.assertTrue(info.is_typed_field)
        self.assertFalse(info.becomes_field_object)


if __name__ == "__main__":
    unittest.main()
