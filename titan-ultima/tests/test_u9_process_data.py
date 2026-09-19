from __future__ import annotations

import struct
import unittest

from titan.u9.process_data import (
    HANDLE_DATA_OFFSET,
    U9ItemHandleTable,
    U9ProcessDataError,
)


def _process_data(count: int = 4) -> bytes:
    table_end = HANDLE_DATA_OFFSET + 12 + count * 12
    data = bytearray(table_end + 4)
    struct.pack_into("<II", data, 0, 8, 2)
    struct.pack_into("<III", data, HANDLE_DATA_OFFSET, 1, count, 1)
    records = [
        (0, -1, 0),
        (2, -1, 0),
        (0, -1, 0),
        (1, 9, -0x1068),
    ]
    for index, record in enumerate(records[:count]):
        struct.pack_into("<iii", data, HANDLE_DATA_OFFSET + 12 + index * 12, *record)
    struct.pack_into("<I", data, table_end, 2)
    return bytes(data)


class ItemHandleTableTests(unittest.TestCase):
    def test_parses_dynamic_table_and_free_chain(self) -> None:
        table = U9ItemHandleTable.from_bytes(_process_data())
        self.assertEqual(table.count, 4)
        self.assertEqual(table.walk_free_chain(), (1, 2))
        self.assertEqual(table.fixed_entries[0].item_offset, 0x1068)
        self.assertEqual(table.end_offset, HANDLE_DATA_OFFSET + 60)

    def test_requires_following_camera_boundary(self) -> None:
        data = bytearray(_process_data())
        struct.pack_into("<I", data, len(data) - 4, 99)
        with self.assertRaisesRegex(U9ProcessDataError, "camera version"):
            U9ItemHandleTable.from_bytes(bytes(data))

    def test_rejects_broken_free_chain(self) -> None:
        data = bytearray(_process_data())
        struct.pack_into("<i", data, HANDLE_DATA_OFFSET + 12 + 2 * 12, 1)
        with self.assertRaisesRegex(U9ProcessDataError, "cycles"):
            U9ItemHandleTable.from_bytes(bytes(data)).walk_free_chain()


if __name__ == "__main__":
    unittest.main()