"""Tests for titan.u9.sdinfo's static/sdInfo*.flx decoder.

Fixtures match the layout established by correlating each table against its
partner ``bitmap*.flx`` archive: 48-byte records of twelve little-endian
``u32``, index-parallel to the textures they describe.

The properties pinned down here are the ones that were easy to get wrong --
two fields carry a flag in their high half, and reading either whole rather
than masked silently mismatches on thousands of real entries.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.sdinfo import RECORD_SIZE, U9SdInfo, U9SdInfoError

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_SIZE_OFFSET = 0x58


def _record(
    *,
    width: int = 64,
    height: int = 64,
    max_width: int | None = None,
    max_height: int | None = None,
    frame_count: int = 1,
    mip_levels: int = 4,
    flag: int = 0,
    frame_flag: int = 0,
    log2: tuple[int, int] = (6, 6),
    unknown0: int = 0,
) -> bytes:
    max_width = width if max_width is None else max_width
    max_height = height if max_height is None else max_height
    packed = log2[0] | (log2[1] << 8) | ((frame_count - 1) << 24)
    return struct.pack(
        "<12I",
        unknown0,
        packed,
        mip_levels | (flag << 16),
        0x01010100,
        0,
        width,
        height,
        0,
        0,
        max_width,
        max_height,
        frame_count | (frame_flag << 16),
    )


def _archive(entries: dict[int, bytes], count: int = 8) -> U9FlxArchive:
    header = bytearray(FLX_DIR_OFFSET + count * 8)
    payload = b""
    directory = []
    base = len(header)
    for index in range(count):
        blob = entries.get(index, b"")
        if blob:
            directory.append((base + len(payload), len(blob)))
            payload += blob
        else:
            directory.append((0, 0))
    for index, (offset, length) in enumerate(directory):
        struct.pack_into("<II", header, FLX_DIR_OFFSET + index * 8, offset, length)
    struct.pack_into("<I", header, FLX_COUNT_OFFSET, count)
    struct.pack_into("<I", header, FLX_SIZE_OFFSET, len(header) + len(payload))
    return U9FlxArchive(bytes(header) + payload)


def _texture_entry(width: int, height: int, mips: int, frame_count: int) -> bytes:
    """Just the 12-byte entry header that cross_check reads."""
    return struct.pack("<4HI", width, mips, height, 0, frame_count) + b"\x00" * 4


class SdInfoRecordTests(unittest.TestCase):
    def test_record_is_48_bytes(self) -> None:
        self.assertEqual(RECORD_SIZE, 48)
        self.assertEqual(len(_record()), 48)

    def test_decodes_every_field(self) -> None:
        info = U9SdInfo(_archive({1: _record(
            width=32, height=16, max_width=64, max_height=64,
            frame_count=9, mip_levels=5, log2=(5, 4),
        )}))
        r = info.record(1)
        assert r is not None
        self.assertEqual((r.width, r.height), (32, 16))
        self.assertEqual((r.max_width, r.max_height), (64, 64))
        self.assertEqual(r.frame_count, 9)
        self.assertEqual(r.mip_levels, 5)
        self.assertEqual((r.log2_width, r.log2_height), (5, 4))
        self.assertEqual(len(r.fields), 12)

    def test_animated_and_varying_frames(self) -> None:
        one = U9SdInfo(_archive({1: _record(frame_count=1)})).record(1)
        many = U9SdInfo(_archive({1: _record(frame_count=9, max_width=128)})).record(1)
        assert one is not None and many is not None
        self.assertFalse(one.is_animated)
        self.assertFalse(one.frames_vary_in_size)
        self.assertTrue(many.is_animated)
        self.assertTrue(many.frames_vary_in_size)

    def test_power_of_two_detection(self) -> None:
        pow2 = U9SdInfo(_archive({1: _record(width=64, height=32)})).record(1)
        odd = U9SdInfo(_archive({1: _record(width=22, height=39)})).record(1)
        assert pow2 is not None and odd is not None
        self.assertTrue(pow2.is_power_of_two)
        self.assertFalse(odd.is_power_of_two)


class SdInfoHighHalfTests(unittest.TestCase):
    """Two fields carry a flag above their value. Mask, do not read whole."""

    def test_frame_count_ignores_its_high_half(self) -> None:
        # sdInfoC.flx sets this flag on 5,687 of 6,576 entries; an unmasked
        # read matches the real frame count on only 13.5% of them.
        r = U9SdInfo(_archive({1: _record(frame_count=3, frame_flag=1)})).record(1)
        assert r is not None
        self.assertEqual(r.frame_count, 3)
        self.assertEqual(r.frame_flag, 1)
        self.assertEqual(r.fields[11], 3 | (1 << 16))

    def test_mip_levels_ignores_its_high_half(self) -> None:
        r = U9SdInfo(_archive({1: _record(mip_levels=5, flag=1)})).record(1)
        assert r is not None
        self.assertEqual(r.mip_levels, 5)
        self.assertEqual(r.flag, 1)


class SdInfoArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.info = U9SdInfo(_archive({
            1: _record(width=64, height=64, frame_count=1),
            3: _record(width=128, height=128, frame_count=9),
        }))

    def test_used_indices_and_len(self) -> None:
        self.assertEqual(self.info.used_indices(), [1, 3])
        self.assertEqual(len(self.info), 2)

    def test_unused_slot_returns_none(self) -> None:
        self.assertIsNone(self.info.record(0))
        self.assertIsNone(self.info.record(2))

    def test_records_are_in_index_order(self) -> None:
        self.assertEqual([r.index for r in self.info.records()], [1, 3])

    def test_out_of_range_raises(self) -> None:
        with self.assertRaises(U9SdInfoError):
            self.info.record(99)
        with self.assertRaises(U9SdInfoError):
            self.info.record(-1)

    def test_short_record_raises(self) -> None:
        info = U9SdInfo(_archive({1: _record()[:40]}))
        with self.assertRaises(U9SdInfoError):
            info.record(1)


class SdInfoCrossCheckTests(unittest.TestCase):
    def test_agreeing_pair_scores_full_marks(self) -> None:
        info = U9SdInfo(_archive({
            1: _record(width=64, height=64, mip_levels=4, frame_count=1),
            3: _record(width=32, height=32, max_width=128, max_height=64,
                       mip_levels=5, frame_count=9),
        }))
        textures = _archive({
            1: _texture_entry(64, 64, 4, 1),
            3: _texture_entry(128, 64, 5, 9),
        })
        counts = info.cross_check(textures)
        self.assertEqual(counts["same_index_set"], 1)
        self.assertEqual(counts["compared"], 2)
        self.assertEqual(counts["max_dims"], 2)
        self.assertEqual(counts["frame_count"], 2)
        self.assertEqual(counts["mip_levels"], 2)

    def test_disagreement_is_reported_not_hidden(self) -> None:
        info = U9SdInfo(_archive({1: _record(frame_count=9, mip_levels=4)}))
        textures = _archive({1: _texture_entry(64, 64, 4, 3)})
        counts = info.cross_check(textures)
        self.assertEqual(counts["compared"], 1)
        self.assertEqual(counts["mip_levels"], 1)
        self.assertEqual(counts["frame_count"], 0)

    def test_mismatched_index_sets_are_flagged(self) -> None:
        info = U9SdInfo(_archive({1: _record()}))
        textures = _archive({1: _texture_entry(64, 64, 4, 1), 2: _texture_entry(8, 8, 1, 1)})
        self.assertEqual(info.cross_check(textures)["same_index_set"], 0)


if __name__ == "__main__":
    unittest.main()
