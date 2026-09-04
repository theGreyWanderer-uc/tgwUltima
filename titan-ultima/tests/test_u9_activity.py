"""Tests for titan.u9.activity's static/activity.flx decoder.

Fixtures match the layout verified against the real archive (352 FLX slots,
214 used, all 214 parsing with their bodies consumed exactly): an 8-byte
entry header, then records of ``u8 ordinal, char name[15], 9-byte steps
ending at a 0xFF step``.

The three properties these pin down are the ones that were easy to get
wrong -- the name field is fixed width rather than a bare C string, a
record's extent is local rather than implied by its name, and ``ordinal``
is a label that need not start at 1 or run without gaps. See the module
docstring for the evidence behind each.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.activity import U9Activities, U9ActivityError
from titan.u9.flx_archive import U9FlxArchive

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_VERSION_OFFSET = 0x54
FLX_SIZE_OFFSET = 0x58
NAME_FIELD_SIZE = 15


def _step(opcode: int, operands: bytes = b"\x00" * 8) -> bytes:
    return bytes([opcode]) + operands.ljust(8, b"\x00")[:8]


TERMINATOR = _step(0xFF)


def _record(ordinal: int, name: str, steps: list[bytes], padding: bytes = b"\x00") -> bytes:
    raw = name.encode() + b"\x00"
    field = (raw + padding * NAME_FIELD_SIZE)[:NAME_FIELD_SIZE]
    return bytes([ordinal]) + field + b"".join(steps) + TERMINATOR


def _entry(records: list[bytes], count: int | None = None) -> bytes:
    body = b"".join(records)
    return struct.pack("<II", len(records) if count is None else count, len(body)) + body


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
    struct.pack_into("<I", header, FLX_VERSION_OFFSET, 2)
    struct.pack_into("<I", header, FLX_SIZE_OFFSET, len(header) + len(payload))
    return U9FlxArchive(bytes(header) + payload)


class ActivityRecordTests(unittest.TestCase):
    def test_parses_records_and_steps(self) -> None:
        entry = _entry([
            _record(1, "Sequence 1", [_step(0x04, bytes([0x1F]))]),
            _record(2, "After Yew", [_step(0x03, b"\xb4\xcc\x09"), _step(0x0A, b"\x01")]),
        ])
        activities = U9Activities(_archive({1: entry}))
        activity = activities.activity(1)
        assert activity is not None
        self.assertEqual(activity.declared_record_count, 2)
        self.assertEqual(activity.names, ["Sequence 1", "After Yew"])
        self.assertEqual([len(r.steps) for r in activity.records], [1, 2])
        self.assertEqual(activity.records[1].opcodes, [0x03, 0x0A])
        self.assertEqual(activity.records[0].steps[0].operands, b"\x1f\x00\x00\x00\x00\x00\x00\x00")

    def test_body_is_consumed_exactly(self) -> None:
        entry = _entry([_record(1, "Stand", [_step(0x01)])])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(activity.trailing_bytes, 0)
        self.assertTrue(activity.is_complete)

    def test_terminator_is_excluded_from_the_steps(self) -> None:
        entry = _entry([_record(1, "Loiter", [_step(0x0A), _step(0x04)])])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(len(activity.records[0].steps), 2)
        self.assertTrue(activity.records[0].terminated)
        self.assertNotIn(0xFF, activity.records[0].opcodes)

    def test_record_with_no_steps(self) -> None:
        entry = _entry([_record(1, "Sequence 1", [])])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(activity.records[0].steps, ())
        self.assertTrue(activity.is_complete)


class ActivityNameFieldTests(unittest.TestCase):
    """The name occupies a fixed 15-byte field; past the NUL is padding."""

    def test_name_field_is_fixed_width_regardless_of_name_length(self) -> None:
        short = _entry([_record(1, "Ide", [_step(0x04)])])
        long = _entry([_record(1, "walking in hse", [_step(0x04)])])
        # 1 ordinal + 15 name + 9 step + 9 terminator, whatever the name.
        self.assertEqual(len(short) - 8, 34)
        self.assertEqual(len(long) - 8, 34)

    def test_padding_after_the_nul_is_not_part_of_the_name(self) -> None:
        # Real records pad with MSVC's 0xCD heap fill or stale text.
        entry = _entry([_record(1, "Idle", [_step(0x04)], padding=b"\xcd")])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(activity.records[0].name, "Idle")

    def test_stale_text_in_padding_is_not_read(self) -> None:
        # One shipped record's padding still reads "me" behind "Idle".
        field = b"Idle\x00me\x00" + b"\x00" * 7
        raw = bytes([1]) + field + _step(0x04) + TERMINATOR
        entry = struct.pack("<II", 1, len(raw)) + raw
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(activity.records[0].name, "Idle")
        self.assertTrue(activity.is_complete)

    def test_maximum_length_name_fills_the_field(self) -> None:
        entry = _entry([_record(1, "walking in hse", [_step(0x04)])])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(activity.records[0].name, "walking in hse")


class ActivityOrdinalTests(unittest.TestCase):
    """ordinal is a label, not a counter -- do not validate it."""

    def test_ordinals_starting_at_two_are_accepted(self) -> None:
        entry = _entry([_record(2, "Sequence 2", [])])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual([r.ordinal for r in activity.records], [2])
        self.assertTrue(activity.is_complete)

    def test_gapped_ordinals_are_accepted(self) -> None:
        entry = _entry([
            _record(1, "Idle", [_step(0x04)]),
            _record(2, "Sailing", [_step(0x04)]),
            _record(12, "To LBC", [_step(0x03)]),
            _record(13, "teleport", [_step(0x03)]),
        ])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual([r.ordinal for r in activity.records], [1, 2, 12, 13])
        self.assertTrue(activity.is_complete)


class ActivityArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.activities = U9Activities(
            _archive(
                {
                    1: _entry([_record(1, "Sequence 1", [_step(0x04)])]),
                    3: _entry([
                        _record(1, "Stand", [_step(0x03), _step(0x0A)]),
                        _record(2, "Loiter", [_step(0x03)]),
                    ]),
                }
            )
        )

    def test_unused_slots_return_none(self) -> None:
        self.assertIsNone(self.activities.activity(0))
        self.assertIsNone(self.activities.activity(2))
        self.assertIsNotNone(self.activities.activity(1))

    def test_used_activity_ids(self) -> None:
        self.assertEqual(self.activities.used_activity_ids(), [1, 3])

    def test_out_of_range_id_raises(self) -> None:
        with self.assertRaises(U9ActivityError):
            self.activities.activity(999)

    def test_opcode_histogram_excludes_terminators(self) -> None:
        histogram = self.activities.opcode_histogram()
        self.assertEqual(histogram[0x03], 2)
        self.assertEqual(histogram[0x0A], 1)
        self.assertEqual(histogram[0x04], 1)
        self.assertEqual(histogram[0xFF], 0)

    def test_name_histogram(self) -> None:
        histogram = self.activities.name_histogram()
        self.assertEqual(histogram["Stand"], 1)
        self.assertEqual(histogram["Sequence 1"], 1)

    def test_no_incomplete_entries(self) -> None:
        self.assertEqual(self.activities.incomplete_activity_ids(), [])


class ActivityValidationTests(unittest.TestCase):
    def test_unterminated_record_is_reported_not_hidden(self) -> None:
        # The pre-patch original's entry 76 is exactly this shape; the
        # v1.19H patch deletes it.
        raw = bytes([1]) + b"Sequence 1\x00\x00\x00\x00\x00" + _step(0x04) * 3
        entry = struct.pack("<II", 1, len(raw)) + raw
        activities = U9Activities(_archive({1: entry}))
        activity = activities.activity(1)
        assert activity is not None
        self.assertFalse(activity.records[0].terminated)
        self.assertFalse(activity.is_complete)
        self.assertEqual(activities.incomplete_activity_ids(), [1])

    def test_payload_longer_than_the_entry_raises(self) -> None:
        raw = _record(1, "Stand", [])
        entry = struct.pack("<II", 1, len(raw) + 500) + raw
        activities = U9Activities(_archive({1: entry}))
        with self.assertRaises(U9ActivityError):
            activities.activity(1)

    def test_entry_too_small_for_a_header_raises(self) -> None:
        activities = U9Activities(_archive({1: b"\x01\x02\x03"}))
        with self.assertRaises(U9ActivityError):
            activities.activity(1)

    def test_from_file_rejects_a_non_flx_file(self) -> None:
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".flx", delete=False) as f:
            f.write(b"\x01" * 16)
            path = f.name
        try:
            with self.assertRaises(U9ActivityError):
                U9Activities.from_file(path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
