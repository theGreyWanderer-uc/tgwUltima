"""Tests for the complete ``TYPENAME.FLX`` object-metadata decoder."""

from __future__ import annotations

import struct
import unittest
from typing import cast

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.typename import (
    DEFAULT_OBJECT_ICON_ID,
    U9TypeNameEntry,
    U9TypeNameError,
    U9TypeNames,
)

DIR_OFFSET = 0x80
CUSTOM_ICON_ID = 7259


def _entry(
    name: str | None,
    *,
    readable_text_id: int = 0,
    object_icon_id: int = DEFAULT_OBJECT_ICON_ID,
    trailing_bytes: bytes = b"",
) -> bytes:
    header = struct.pack("<iH", readable_text_id, object_icon_id)
    if name is None:
        return header
    return header + name.encode("ascii") + b"\x00" + trailing_bytes


def _build_flx(entries_data: list[bytes]) -> bytes:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    header[0:12] = b"TYPENAME.FLX"
    struct.pack_into("<I", header, 0x50, count)
    struct.pack_into("<I", header, 0x54, 2)  # FLX format-version word

    payload = bytearray()
    dir_entries: list[tuple[int, int]] = []
    cursor = DIR_OFFSET + dir_size
    for data in entries_data:
        dir_entries.append((cursor, len(data)))
        payload += data
        cursor += len(data)

    directory = bytearray()
    for offset, length in dir_entries:
        directory += struct.pack("<II", offset, length)

    return bytes(header) + bytes(directory) + bytes(payload)


class TypeNamesTests(unittest.TestCase):
    def setUp(self) -> None:
        data = _build_flx(
            [
                _entry(None),  # type_id 0: unnamed
                _entry("Lord British"),  # type_id 1
                _entry(None, readable_text_id=-1),  # type_id 2: sentinel
                _entry(
                    "Spellbook",
                    readable_text_id=326,
                    object_icon_id=CUSTOM_ICON_ID,
                    trailing_bytes=b"\xaa\xbb",
                ),
            ]
        )
        self.archive = U9FlxArchive(data)

    def test_named_entries_resolve(self) -> None:
        names = U9TypeNames(self.archive)
        self.assertEqual(names.name_for(1), "Lord British")
        self.assertEqual(names.name_for(3), "Spellbook")

    def test_unnamed_entries_are_none(self) -> None:
        names = U9TypeNames(self.archive)
        self.assertIsNone(names.name_for(0))
        self.assertIsNone(names.name_for(2))

    def test_unknown_type_id_is_none(self) -> None:
        names = U9TypeNames(self.archive)
        self.assertIsNone(names.name_for(999))

    def test_len_and_iteration_order(self) -> None:
        names = U9TypeNames(self.archive)
        self.assertEqual(len(names), 4)
        self.assertEqual([e.type_id for e in names], [0, 1, 2, 3])

    def test_header_fields_and_raw_storage_are_decoded(self) -> None:
        names = U9TypeNames(self.archive)
        entry = names.entry_for(3)
        self.assertIsNotNone(entry)
        entry = cast(U9TypeNameEntry, entry)
        self.assertEqual(entry.readable_text_id, 326)
        self.assertEqual(entry.object_icon_id, CUSTOM_ICON_ID)
        self.assertEqual(entry.display_name, "Spellbook")
        self.assertEqual(entry.trailing_bytes, b"\xaa\xbb")
        self.assertEqual(entry.record_representation, "six_byte_header")
        self.assertEqual(entry.warnings, ("post_terminator_bytes_present",))
        self.assertEqual(
            entry.raw,
            _entry(
                "Spellbook",
                readable_text_id=326,
                object_icon_id=CUSTOM_ICON_ID,
                trailing_bytes=b"\xaa\xbb",
            ),
        )
        self.assertTrue(entry.has_readable_text)
        self.assertFalse(entry.uses_default_icon)

    def test_signed_nonpositive_text_references_are_not_readable(self) -> None:
        names = U9TypeNames(self.archive)
        entry = names.entry_for(2)
        self.assertIsNotNone(entry)
        entry = cast(U9TypeNameEntry, entry)
        self.assertEqual(entry.readable_text_id, -1)
        self.assertFalse(entry.has_readable_text)

    def test_compatibility_properties_keep_old_callers_working(self) -> None:
        entry = U9TypeNames(self.archive).entry_for(1)
        self.assertIsNotNone(entry)
        entry = cast(U9TypeNameEntry, entry)
        self.assertEqual(entry.reserved, entry.readable_text_id)
        self.assertEqual(entry.marker, entry.object_icon_id)
        self.assertEqual(entry.name, entry.display_name)

    def test_rejects_a_short_record(self) -> None:
        archive = U9FlxArchive(_build_flx([b"\x00" * 5]))
        with self.assertRaisesRegex(U9TypeNameError, "older two-byte-header"):
            U9TypeNames(archive)

    def test_rejects_unterminated_display_text(self) -> None:
        archive = U9FlxArchive(
            _build_flx([struct.pack("<iH", 0, DEFAULT_OBJECT_ICON_ID) + b"Label"])
        )
        with self.assertRaises(U9TypeNameError):
            U9TypeNames(archive)


if __name__ == "__main__":
    unittest.main()
