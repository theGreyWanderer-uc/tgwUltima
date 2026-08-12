"""Tests for UU2 COMOBJ.DAT and OBJECTS.DAT rendering metadata."""

from __future__ import annotations

import unittest

from titan.uw2.object_data import (
    ANIMATION_TABLE_OFFSET,
    UW2AnimationTable,
    UW2CommonObjectTable,
    UW2ObjectDataError,
)


def _common_object_data(record_count: int = 512) -> bytearray:
    return bytearray(2 + record_count * 11)


class UW2CommonObjectTableTests(unittest.TestCase):
    def test_decodes_fountain_render_metadata(self) -> None:
        data = _common_object_data()
        offset = 2 + 302 * 11
        data[offset : offset + 11] = bytes.fromhex("1402002000000D80003C1F")

        fountain = UW2CommonObjectTable.from_data(bytes(data)).get(302)

        self.assertEqual(fountain.height, 40)
        self.assertEqual(fountain.radius, 2)
        self.assertEqual(fountain.render_type_name, "sprite")
        self.assertEqual(fountain.culling_priority, 15)
        self.assertTrue(fountain.can_put_in_inventory)

    def test_rejects_misaligned_table(self) -> None:
        with self.assertRaisesRegex(UW2ObjectDataError, "misaligned"):
            UW2CommonObjectTable.from_data(bytes(14))


class UW2AnimationTableTests(unittest.TestCase):
    def test_decodes_fountain_animation_frames(self) -> None:
        data = bytearray(ANIMATION_TABLE_OFFSET + 16 * 4)
        offset = ANIMATION_TABLE_OFFSET + (457 & 0x0F) * 4
        data[offset : offset + 4] = bytes((33, 0, 5, 4))

        fountain_water = UW2AnimationTable.from_data(bytes(data)).get(457)

        self.assertEqual(fountain_water.start_frame, 5)
        self.assertEqual(fountain_water.frame_count, 4)
        self.assertEqual(fountain_water.end_frame, 8)


if __name__ == "__main__":
    unittest.main()
