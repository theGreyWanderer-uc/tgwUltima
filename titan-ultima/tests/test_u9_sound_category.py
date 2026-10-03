"""Tests for the complete ``sfxcat.flx`` sound-category decoder."""

from __future__ import annotations

import struct
import unittest
from typing import cast

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.sound_category import (
    CATEGORY_RECORD_SIZE,
    U9SoundCategories,
    U9SoundCategory,
    U9SoundCategoryError,
)

DIRECTORY_OFFSET = 0x80


def _category_record(
    category_id: int,
    display_name: str,
    *,
    alignment_bytes: bytes = b"\x00\x00",
    sound_reference_count: int = 0,
) -> bytes:
    record = bytearray(CATEGORY_RECORD_SIZE)
    record[0] = category_id
    encoded = display_name.encode("ascii")
    record[1 : 1 + len(encoded)] = encoded
    record[34:36] = alignment_bytes
    struct.pack_into("<I", record, 36, sound_reference_count)
    return bytes(record)


def _build_flx(entries: list[bytes | None]) -> U9FlxArchive:
    header = bytearray(DIRECTORY_OFFSET)
    header[:10] = b"sfxcat.flx"
    struct.pack_into("<I", header, 0x50, len(entries))
    struct.pack_into("<I", header, 0x54, 2)
    cursor = DIRECTORY_OFFSET + len(entries) * 8
    directory = bytearray()
    payload = bytearray()
    for entry in entries:
        if entry is None:
            directory += struct.pack("<II", 0, 0)
            continue
        directory += struct.pack("<II", cursor, len(entry))
        payload += entry
        cursor += len(entry)
    return U9FlxArchive(bytes(header + directory + payload))


class SoundCategoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.categories = U9SoundCategories(
            _build_flx(
                [
                    _category_record(0, "Attack"),
                    None,
                    _category_record(
                        2,
                        "Footfall - Stone",
                        alignment_bytes=b"AZ",
                        sound_reference_count=3,
                    ),
                ]
            )
        )

    def test_decodes_every_fixed_field(self) -> None:
        category = self.categories.category(2)
        self.assertIsNotNone(category)
        category = cast(U9SoundCategory, category)
        self.assertEqual(category.archive_index, 2)
        self.assertEqual(category.category_id, 2)
        self.assertEqual(category.display_name, "Footfall - Stone")
        self.assertEqual(len(category.name_field), 33)
        self.assertEqual(category.alignment_bytes, b"AZ")
        self.assertEqual(category.sound_reference_count, 3)
        self.assertEqual(len(category.raw), CATEGORY_RECORD_SIZE)
        self.assertTrue(category.id_matches_index)
        self.assertEqual(category.record_representation, "master_category_record")
        self.assertTrue(category.name_is_terminated)
        self.assertEqual(
            category.warnings,
            ("nonzero_alignment_bytes", "inactive_reference_count_nonzero"),
        )

    def test_lookup_and_archive_counts(self) -> None:
        self.assertEqual(len(self.categories), 2)
        self.assertEqual(self.categories.archive_slot_count, 3)
        self.assertEqual(self.categories.name_for(0), "Attack")
        self.assertIsNone(self.categories.name_for(1))

    def test_preserves_a_stored_id_that_differs_from_its_slot(self) -> None:
        categories = U9SoundCategories(
            _build_flx([None, _category_record(7, "Mismatch")])
        )
        category = categories.category(7)
        self.assertIsNotNone(category)
        category = cast(U9SoundCategory, category)
        self.assertFalse(category.id_matches_index)
        self.assertEqual(category.warnings, ("stored_id_differs_from_archive_index",))

    def test_reports_nonzero_name_padding_without_discarding_it(self) -> None:
        record = bytearray(_category_record(0, "Attack"))
        record[20] = 0x7F
        category = next(iter(U9SoundCategories(_build_flx([bytes(record)]))))
        self.assertIn("nonzero_name_padding", category.warnings)
        self.assertIn(0x7F, category.name_padding_bytes)

    def test_rejects_a_non_40_byte_record(self) -> None:
        with self.assertRaises(U9SoundCategoryError):
            U9SoundCategories(_build_flx([b"\x00" * 39]))

    def test_rejects_duplicate_stored_ids(self) -> None:
        with self.assertRaises(U9SoundCategoryError):
            U9SoundCategories(
                _build_flx(
                    [
                        _category_record(4, "First"),
                        _category_record(4, "Second"),
                    ]
                )
            )


if __name__ == "__main__":
    unittest.main()
