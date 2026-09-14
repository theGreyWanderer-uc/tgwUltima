"""Tests for titan.u9.flx_archive's FLX container reader.

Fixtures are hand-built to match the documented byte layout, cross-
validated against u9ed's FLXFile.cs (D:\\_Repos\\_UltimaIX\\u9ed):
a 0x4C-byte comment, then Unknown1/Count/Unknown2/Size/Size2 (4 bytes
each), a 0x20-byte reserved block, then Count 8-byte (offset, length)
directory entries starting at 0x80.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

DIR_OFFSET = 0x80


def _build_flx(comment: bytes, entries_data: list[bytes | None]) -> bytes:
    """Build a minimal valid FLX archive: header + directory + entry payloads."""
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    header[0:len(comment)] = comment
    struct.pack_into("<I", header, 0x50, count)
    struct.pack_into("<I", header, 0x54, 2)  # FLX format-version word
    struct.pack_into("<I", header, 0x58, 0)
    struct.pack_into("<I", header, 0x5C, 0)

    payload = bytearray()
    dir_entries: list[tuple[int, int]] = []
    cursor = DIR_OFFSET + dir_size
    for data in entries_data:
        if data is None:
            dir_entries.append((0, 0))
            continue
        dir_entries.append((cursor, len(data)))
        payload += data
        cursor += len(data)

    directory = bytearray()
    for offset, length in dir_entries:
        directory += struct.pack("<II", offset, length)

    return bytes(header) + bytes(directory) + bytes(payload)


class FlxArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _build_flx(b"test archive", [b"HELLO", None, b"WORLD!!"])

    def test_parses_comment_and_count(self) -> None:
        archive = U9FlxArchive(self.data)
        self.assertTrue(archive.comment.startswith("test archive"))
        self.assertEqual(archive.num_entries, 3)

    def test_used_entry_indices_skips_empty_slot(self) -> None:
        archive = U9FlxArchive(self.data)
        self.assertEqual(archive.used_entry_indices(), [0, 2])

    def test_read_entry_returns_payload(self) -> None:
        archive = U9FlxArchive(self.data)
        self.assertEqual(archive.read_entry(0), b"HELLO")
        self.assertEqual(archive.read_entry(2), b"WORLD!!")

    def test_read_entry_empty_slot_returns_empty_bytes(self) -> None:
        archive = U9FlxArchive(self.data)
        self.assertEqual(archive.read_entry(1), b"")

    def test_read_entry_out_of_range_raises(self) -> None:
        archive = U9FlxArchive(self.data)
        with self.assertRaises(U9FlxArchiveError):
            archive.read_entry(99)

    def test_get_entry_out_of_range_returns_none(self) -> None:
        archive = U9FlxArchive(self.data)
        self.assertIsNone(archive.get_entry(99))
        self.assertIsNone(archive.get_entry(-1))

    def test_too_small_data_raises(self) -> None:
        with self.assertRaises(U9FlxArchiveError):
            U9FlxArchive(b"\x00" * 10)

    def test_zero_entry_archive_is_valid(self) -> None:
        archive = U9FlxArchive(_build_flx(b"empty", []))
        self.assertEqual(archive.num_entries, 0)
        self.assertEqual(archive.used_entry_indices(), [])


class FlxSignatureTests(unittest.TestCase):
    """The reader validates the format word, so arbitrary files are rejected.

    Without that check it validated nothing beyond a length, and accepted 570
    of the 595 files in a game install -- ``ddraw.dll``, ``ConfigINI.exe`` and
    assorted ``.ini`` and ``.txt`` among them. Checking the word at ``0x54``
    narrows that to exactly the 41 real archives.
    """

    def test_arbitrary_binary_is_rejected(self) -> None:
        # a PE image: 'MZ' header then padding, comfortably over 0x80 bytes
        with self.assertRaises(U9FlxArchiveError):
            U9FlxArchive(b"MZ" + b"\x90\x00\x03\x00" + b"\x00" * 1024)

    def test_text_file_is_rejected(self) -> None:
        with self.assertRaises(U9FlxArchiveError):
            U9FlxArchive(b"; a config file\r\n[section]\r\nkey=value\r\n" * 8)

    def test_all_zero_block_is_rejected(self) -> None:
        # the classic false accept: nothing but a length check passes this
        with self.assertRaises(U9FlxArchiveError):
            U9FlxArchive(b"\x00" * 4096)

    def test_wrong_format_word_is_rejected(self) -> None:
        data = bytearray(_build_flx(b"real", [b"payload"]))
        struct.pack_into("<I", data, 0x54, 1)  # FLEX's value, not FLX's
        with self.assertRaises(U9FlxArchiveError) as ctx:
            U9FlxArchive(bytes(data))
        self.assertIn("not an FLX archive", str(ctx.exception))

    def test_implausible_entry_count_is_rejected(self) -> None:
        data = bytearray(_build_flx(b"real", [b"payload"]))
        struct.pack_into("<I", data, 0x50, 0xFFFFFFF)
        with self.assertRaises(U9FlxArchiveError):
            U9FlxArchive(bytes(data))

    def test_directory_overrunning_the_data_is_rejected(self) -> None:
        data = bytearray(_build_flx(b"real", [b"payload"]))
        struct.pack_into("<I", data, 0x50, 4096)  # plausible, but does not fit
        with self.assertRaises(U9FlxArchiveError) as ctx:
            U9FlxArchive(bytes(data))
        self.assertIn("truncated", str(ctx.exception))

    def test_a_real_archive_still_parses(self) -> None:
        archive = U9FlxArchive(_build_flx(b"real", [b"one", None, b"three"]))
        self.assertEqual(archive.num_entries, 3)
        self.assertEqual(archive.read_entry(2), b"three")

    def test_comment_text_is_not_required_to_be_spaces(self) -> None:
        # shipped archives space-pad the comment, but that is cosmetic --
        # requiring it would reject archives titan itself writes with a comment
        archive = U9FlxArchive(_build_flx(b"titan wrote this", [b"x"]))
        self.assertTrue(archive.comment.startswith("titan wrote this"))


if __name__ == "__main__":
    unittest.main()
