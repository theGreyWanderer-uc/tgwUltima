from __future__ import annotations

import struct
import unittest

from titan.u9.savegame import U9SaveArchive, U9SaveError, U9StartDat


def _archive(*, maps: tuple[tuple[int, bytes], ...] = ((9, b"map-nine"),)) -> bytes:
    data = bytearray(b"U9:008")
    for text in (b"", b"Test save\x00"):
        data += struct.pack("<i", len(text)) + text
    data += struct.pack("<3f4f3f3i", 1, 2, 3, 0, 0, 0, 1, 4, 5, 6, 9, 700, 2)
    for payload in (b"shot", b"process", b""):
        data += struct.pack("<i", len(payload)) + payload
    for map_number, payload in maps:
        data += struct.pack("<ii", map_number, len(payload)) + payload
    data += struct.pack("<i", -1)
    return bytes(data)


class StartDatTests(unittest.TestCase):
    def test_reads_selected_slot(self) -> None:
        self.assertEqual(U9StartDat.from_bytes(b"U9.008" + struct.pack("<i", 631)).slot, 631)

    def test_rejects_wrong_size_or_magic(self) -> None:
        with self.assertRaises(U9SaveError):
            U9StartDat.from_bytes(b"U9.008")
        with self.assertRaises(U9SaveError):
            U9StartDat.from_bytes(b"U9:008" + struct.pack("<i", 1))


class SaveArchiveTests(unittest.TestCase):
    def test_reads_header_and_exact_members(self) -> None:
        archive = U9SaveArchive.from_bytes(_archive())
        self.assertEqual(archive.header.description, "Test save")
        self.assertEqual(archive.header.saved_map, 9)
        self.assertEqual(archive.processes.data, b"process")
        self.assertEqual(archive.member("NONFIXED.9").data, b"map-nine")

    def test_rejects_duplicate_maps(self) -> None:
        with self.assertRaisesRegex(U9SaveError, "duplicate"):
            U9SaveArchive.from_bytes(_archive(maps=((9, b"a"), (9, b"b"))))

    def test_rejects_trailing_bytes_and_truncation(self) -> None:
        with self.assertRaisesRegex(U9SaveError, "trailing"):
            U9SaveArchive.from_bytes(_archive() + b"x")
        with self.assertRaises(U9SaveError):
            U9SaveArchive.from_bytes(_archive()[:-5])


if __name__ == "__main__":
    unittest.main()