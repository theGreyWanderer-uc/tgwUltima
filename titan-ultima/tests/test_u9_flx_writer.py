"""Tests for titan.u9.flx_writer's FLX container writer.

The writer's job is to produce a container the reader accepts and the game
would too, so most of these assert against :mod:`titan.u9.flx_archive` rather
than against hand-built bytes. The header constants pinned here were measured
across all 25 shipped archives, which agree exactly:

* the comment field is **space**-filled, not NUL-padded;
* ``unknown1`` is 0, ``unknown2`` is 2, and both size fields hold the total
  file size;
* payload starts immediately after the directory with no gap and no alignment.

Round-tripping the real archives is covered here structurally; the full
25-archive check lives outside the suite because it reads 600 MB.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest

from titan.u9.flx_archive import (
    COMMENT_SIZE,
    COUNT_OFFSET,
    DIR_OFFSET,
    SIZE2_OFFSET,
    SIZE_OFFSET,
    U9FlxArchive,
)
from titan.u9.flx_writer import (
    COMMENT_FILL,
    U9FlxWriteError,
    build_flx,
    repack,
    repack_equivalent,
    write_flx,
)


class FlxHeaderTests(unittest.TestCase):
    def test_header_constants_match_shipped_archives(self) -> None:
        data = build_flx({0: b"abc"})
        self.assertEqual(data[:COMMENT_SIZE], bytes([COMMENT_FILL]) * COMMENT_SIZE)
        self.assertEqual(struct.unpack_from("<I", data, 0x4C)[0], 0)
        self.assertEqual(struct.unpack_from("<I", data, 0x54)[0], 2)
        self.assertEqual(struct.unpack_from("<I", data, 0x60 + 8)[0], 1)

    def test_comment_is_space_padded_not_nul_padded(self) -> None:
        # Every shipped archive pads with 0x20; a NUL-padded field would be a
        # visible difference from the originals.
        data = build_flx({0: b"x"}, comment="titan")
        self.assertTrue(data[:COMMENT_SIZE].startswith(b"titan"))
        self.assertEqual(set(data[5:COMMENT_SIZE]), {COMMENT_FILL})

    def test_both_size_fields_hold_the_total_length(self) -> None:
        data = build_flx({0: b"a" * 100, 3: b"b" * 7})
        self.assertEqual(struct.unpack_from("<I", data, SIZE_OFFSET)[0], len(data))
        self.assertEqual(struct.unpack_from("<I", data, SIZE2_OFFSET)[0], len(data))

    def test_payload_starts_immediately_after_the_directory(self) -> None:
        data = build_flx({0: b"abc"}, count=4)
        offset, length = struct.unpack_from("<II", data, DIR_OFFSET)
        self.assertEqual(offset, DIR_OFFSET + 4 * 8)
        self.assertEqual(length, 3)

    def test_entries_are_packed_with_no_gap_or_alignment(self) -> None:
        data = build_flx({0: b"abc", 1: b"de"})
        first = struct.unpack_from("<II", data, DIR_OFFSET)
        second = struct.unpack_from("<II", data, DIR_OFFSET + 8)
        self.assertEqual(second[0], first[0] + first[1])
        self.assertEqual(len(data), second[0] + second[1])


class FlxContentTests(unittest.TestCase):
    def test_round_trips_through_the_reader(self) -> None:
        blobs = {0: b"first", 2: b"third", 7: bytes(range(256))}
        archive = U9FlxArchive(build_flx(blobs, count=8))
        self.assertEqual(archive.num_entries, 8)
        for index, blob in blobs.items():
            self.assertEqual(archive.read_entry(index), blob)

    def test_unused_slots_are_zero_pairs(self) -> None:
        archive = U9FlxArchive(build_flx({0: b"a", 3: b"b"}, count=5))
        self.assertEqual(archive.used_entry_indices(), [0, 3])
        for index in (1, 2, 4):
            entry = archive.get_entry(index)
            self.assertEqual((entry.offset, entry.length), (0, 0))
            self.assertFalse(entry.is_used)

    def test_empty_blob_writes_an_unused_slot(self) -> None:
        archive = U9FlxArchive(build_flx({0: b"a", 1: b"", 2: b"c"}))
        self.assertEqual(archive.used_entry_indices(), [0, 2])

    def test_dense_sequence_input(self) -> None:
        archive = U9FlxArchive(build_flx([b"a", b"bb", b"ccc"]))
        self.assertEqual(archive.num_entries, 3)
        self.assertEqual(archive.read_entry(1), b"bb")

    def test_empty_archive_is_valid(self) -> None:
        archive = U9FlxArchive(build_flx({}, count=4))
        self.assertEqual(archive.num_entries, 4)
        self.assertEqual(archive.used_entry_indices(), [])

    def test_count_over_allocates_like_shipped_archives(self) -> None:
        # sappear.flx declares 8,000 slots for 3,764 entries
        archive = U9FlxArchive(build_flx({0: b"a"}, count=64))
        self.assertEqual(archive.num_entries, 64)
        self.assertEqual(archive.used_entry_indices(), [0])

    def test_large_binary_payloads_survive(self) -> None:
        blob = bytes((i * 7) % 256 for i in range(70000))
        archive = U9FlxArchive(build_flx({5: blob}))
        self.assertEqual(archive.read_entry(5), blob)


class FlxValidationTests(unittest.TestCase):
    def test_count_smaller_than_the_highest_index_raises(self) -> None:
        with self.assertRaises(U9FlxWriteError):
            build_flx({9: b"x"}, count=4)

    def test_negative_index_raises(self) -> None:
        with self.assertRaises(U9FlxWriteError):
            build_flx({-1: b"x"})

    def test_implausible_count_raises(self) -> None:
        with self.assertRaises(U9FlxWriteError):
            build_flx({}, count=10_000_000)

    def test_non_ascii_comment_raises(self) -> None:
        with self.assertRaises(U9FlxWriteError):
            build_flx({0: b"x"}, comment="café")

    def test_oversized_comment_raises(self) -> None:
        with self.assertRaises(U9FlxWriteError):
            build_flx({0: b"x"}, comment="x" * (COMMENT_SIZE + 1))


class FlxRepackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = build_flx({0: b"alpha", 1: b"beta", 4: b"delta"}, count=8)
        self.archive = U9FlxArchive(self.original)

    def test_repack_without_changes_is_byte_identical(self) -> None:
        # true whenever the source already stores payloads in index order
        # with no slack, which 19 of the 25 shipped archives do
        self.assertEqual(repack(self.archive), self.original)

    def test_repack_preserves_the_slot_count(self) -> None:
        rebuilt = U9FlxArchive(repack(self.archive))
        self.assertEqual(rebuilt.num_entries, 8)

    def test_replacement_changes_one_entry_only(self) -> None:
        rebuilt = U9FlxArchive(repack(self.archive, {1: b"REPLACED-AND-LONGER"}))
        self.assertEqual(rebuilt.read_entry(0), b"alpha")
        self.assertEqual(rebuilt.read_entry(1), b"REPLACED-AND-LONGER")
        self.assertEqual(rebuilt.read_entry(4), b"delta")

    def test_replacement_can_clear_a_slot(self) -> None:
        rebuilt = U9FlxArchive(repack(self.archive, {1: b""}))
        self.assertEqual(rebuilt.used_entry_indices(), [0, 4])

    def test_replacement_out_of_range_raises(self) -> None:
        with self.assertRaises(U9FlxWriteError):
            repack(self.archive, {99: b"x"})

    def test_repack_equivalent_ignores_payload_order(self) -> None:
        # 6 shipped archives store payloads out of index order, so a rebuild is
        # a different file holding identical entries -- that is still correct.
        reordered = build_flx({4: b"delta", 0: b"alpha", 1: b"beta"}, count=8)
        self.assertTrue(repack_equivalent(self.original, reordered))

    def test_repack_equivalent_rejects_changed_content(self) -> None:
        other = build_flx({0: b"alpha", 1: b"CHANGED", 4: b"delta"}, count=8)
        self.assertFalse(repack_equivalent(self.original, other))

    def test_repack_equivalent_rejects_a_changed_slot_count(self) -> None:
        other = build_flx({0: b"alpha", 1: b"beta", 4: b"delta"}, count=16)
        self.assertFalse(repack_equivalent(self.original, other))

    def test_repack_equivalent_rejects_garbage(self) -> None:
        self.assertFalse(repack_equivalent(self.original, b"not an archive"))


class FlxWriteFileTests(unittest.TestCase):
    def test_write_flx_writes_a_readable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.flx")
            written = write_flx(path, {0: b"hello", 2: b"world"}, count=4)
            self.assertEqual(written, os.path.getsize(path))
            archive = U9FlxArchive.from_file(path)
            self.assertEqual(archive.read_entry(2), b"world")


if __name__ == "__main__":
    unittest.main()
