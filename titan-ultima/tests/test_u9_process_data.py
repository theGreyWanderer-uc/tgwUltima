from __future__ import annotations

import struct
import unittest

from titan.u9.process_data import (
    HANDLE_DATA_OFFSET,
    OBJECT_REFERENCE_DATA_OFFSET,
    U9ItemHandleEntry,
    U9ItemHandleTable,
    U9ObjectReferenceEntry,
    U9ObjectReferenceTable,
    U9ProcessDataError,
)


def _process_data(count: int = 4) -> bytes:
    table_end = OBJECT_REFERENCE_DATA_OFFSET + 12 + count * 12
    data = bytearray(table_end + 4)
    struct.pack_into("<II", data, 0, 8, 2)
    struct.pack_into("<III", data, OBJECT_REFERENCE_DATA_OFFSET, 1, count, 1)
    records = [
        (0, -1, 0),
        (2, -1, 0),
        (0, -1, 0),
        (1, 9, -0x1068),
    ]
    for index, record in enumerate(records[:count]):
        struct.pack_into(
            "<iii",
            data,
            OBJECT_REFERENCE_DATA_OFFSET + 12 + index * 12,
            *record,
        )
    struct.pack_into("<I", data, table_end, 2)
    return bytes(data)


class ObjectReferenceTableTests(unittest.TestCase):
    def test_generalized_names_preserve_legacy_imports(self) -> None:
        self.assertIs(U9ItemHandleTable, U9ObjectReferenceTable)
        self.assertIs(U9ItemHandleEntry, U9ObjectReferenceEntry)
        self.assertEqual(HANDLE_DATA_OFFSET, OBJECT_REFERENCE_DATA_OFFSET)

        legacy_entry = U9ItemHandleEntry(
            index=7,
            usage_count=2,
            map_number=9,
            encoded_item_offset=-0x1068,
        )
        self.assertEqual(legacy_entry.reference_count, 2)
        self.assertEqual(legacy_entry.encoded_object_offset, -0x1068)

    def test_parses_dynamic_table_and_free_chain(self) -> None:
        table = U9ObjectReferenceTable.from_bytes(_process_data())
        self.assertEqual(table.count, 4)
        self.assertEqual(table.walk_free_chain(), (1, 2))
        self.assertEqual(table.fixed_entries[0].object_offset, 0x1068)
        self.assertEqual(table.end_offset, OBJECT_REFERENCE_DATA_OFFSET + 60)

    def test_preserves_serialized_reference_entry_semantics(self) -> None:
        table = U9ObjectReferenceTable.from_bytes(_process_data())

        free_entry = table.entries[1]
        self.assertTrue(free_entry.is_free)
        self.assertFalse(free_entry.is_live)
        self.assertEqual(free_entry.next_free_index, 2)

        fixed_entry = table.entries[3]
        self.assertTrue(fixed_entry.is_live)
        self.assertTrue(fixed_entry.is_fixed)
        self.assertEqual(fixed_entry.map_number, 9)
        self.assertEqual(fixed_entry.encoded_object_offset, -0x1068)
        self.assertEqual(fixed_entry.object_offset, 0x1068)

    def test_requires_following_camera_boundary(self) -> None:
        data = bytearray(_process_data())
        struct.pack_into("<I", data, len(data) - 4, 99)
        with self.assertRaisesRegex(U9ProcessDataError, "camera version"):
            U9ObjectReferenceTable.from_bytes(bytes(data))

    def test_rejects_broken_free_chain(self) -> None:
        data = bytearray(_process_data())
        struct.pack_into("<i", data, OBJECT_REFERENCE_DATA_OFFSET + 12 + 2 * 12, 1)
        with self.assertRaisesRegex(U9ProcessDataError, "cycles"):
            U9ObjectReferenceTable.from_bytes(bytes(data)).walk_free_chain()

    def test_rejects_negative_free_link(self) -> None:
        # A negative link must not index the tuple from its end.
        data = bytearray(_process_data())
        struct.pack_into("<i", data, OBJECT_REFERENCE_DATA_OFFSET + 12 + 2 * 12, -1)
        with self.assertRaisesRegex(U9ProcessDataError, "leaves table at entry -1"):
            U9ObjectReferenceTable.from_bytes(bytes(data)).walk_free_chain()


if __name__ == "__main__":
    unittest.main()
