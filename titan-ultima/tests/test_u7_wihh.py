"""WIHH weapon attachments remain distinct from SHP frame origins."""

from __future__ import annotations

import unittest

from titan.u7.wihh import U7WeaponInHandOffsets


class U7WeaponInHandOffsetsTests(unittest.TestCase):
    def test_reads_named_weapon_attachment_coordinates(self) -> None:
        data = bytearray(2048 + 64)
        data[2:4] = (2048).to_bytes(2, "little")  # shape 1 record
        data[2048:2052] = bytes([5, 14, 64, 2])

        table = U7WeaponInHandOffsets.from_bytes(bytes(data))
        frame_zero, frame_one = table.get(1)[:2]

        self.assertEqual((frame_zero.attachment_x, frame_zero.attachment_y), (5, 14))
        self.assertTrue(frame_zero.draw_weapon)
        self.assertEqual(
            (frame_one.raw_attachment_x, frame_one.raw_attachment_y), (64, 2)
        )
        self.assertEqual((frame_one.attachment_x, frame_one.attachment_y), (255, 255))
        self.assertFalse(frame_one.draw_weapon)

    def test_csv_names_attachment_columns_explicitly(self) -> None:
        table = U7WeaponInHandOffsets([], {}, 0)

        header = table.dump_csv().splitlines()[0]

        self.assertIn("attachment_x,attachment_y", header)
        self.assertIn("raw_attachment_x,raw_attachment_y", header)


if __name__ == "__main__":
    unittest.main()
