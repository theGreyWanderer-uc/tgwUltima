"""Tests for titan.u9.typename's TYPENAME.FLX decoder.

Fixture built directly from this project's own byte-level reverse
engineering (see D:\\_Repos\\tgwUltima\\u9data) -- neither u9ed nor the
Ultima-9-Blender-Importer reference source covers this archive. Each
entry: u32 reserved(0) + u16 marker(0x1B81) + optional NUL-terminated
ASCII name.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.typename import U9TypeNames

DIR_OFFSET = 0x80
MARKER = 0x1B81


def _entry(name: str | None) -> bytes:
    header = struct.pack("<IH", 0, MARKER)
    if name is None:
        return header
    return header + name.encode("ascii") + b"\x00"


def _build_flx(entries_data: list[bytes]) -> bytes:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    header[0:12] = b"TYPENAME.FLX"
    struct.pack_into("<I", header, 0x50, count)

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
        data = _build_flx([
            _entry(None),               # type_id 0: unnamed
            _entry("Lord British"),     # type_id 1
            _entry(None),               # type_id 2: unnamed
            _entry("Amoranth"),         # type_id 3
        ])
        self.archive = U9FlxArchive(data)

    def test_named_entries_resolve(self) -> None:
        names = U9TypeNames(self.archive)
        self.assertEqual(names.name_for(1), "Lord British")
        self.assertEqual(names.name_for(3), "Amoranth")

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

    def test_marker_is_captured(self) -> None:
        names = U9TypeNames(self.archive)
        entry = next(e for e in names if e.type_id == 1)
        self.assertEqual(entry.marker, MARKER)
        self.assertEqual(entry.reserved, 0)


if __name__ == "__main__":
    unittest.main()
