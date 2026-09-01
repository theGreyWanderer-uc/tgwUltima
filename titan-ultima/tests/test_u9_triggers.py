"""Tests for titan.u9.triggers' static/triggers.flx decoder.

Fixtures match the layout verified against the real archive (242,476 bytes,
10,000 slots, 6,712 used): the FLX entry index is the trigger ID, a body is
a list of 6-byte ``opcode/arg0/arg1/arg2`` records, and the list ends at the
first record whose opcode byte is 0xFF. Records after that terminator are
slack left behind by a trigger that shrank, not instructions.

See ``reference/u9/triggers/u9_triggers_reference.md``.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.triggers import U9Triggers, U9TriggersError

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_SIZE_OFFSET = 0x58
RECORD_SIZE = 6


def _record(opcode: int, arg0: int = 0, arg1: int = 0, arg2: int = 0) -> bytes:
    return struct.pack("<BBHH", opcode, arg0, arg1, arg2)


TERMINATOR = _record(0xFF, 0x10)


def _archive(entries: dict[int, bytes], count: int = 8) -> U9FlxArchive:
    """Build a minimal U9 FLX archive holding the given entry payloads."""
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
    data = bytes(header) + payload
    struct.pack_into("<I", header, FLX_SIZE_OFFSET, len(data))
    return U9FlxArchive(bytes(header) + payload)


class TriggerRecordTests(unittest.TestCase):
    def test_record_fields(self) -> None:
        triggers = U9Triggers(_archive({1: _record(0x33, 16, 2220, 238) + TERMINATOR}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertEqual(len(trigger.records), 1)
        record = trigger.records[0]
        self.assertEqual(record.opcode, 0x33)
        self.assertEqual(record.arg0, 16)
        self.assertEqual(record.arg1, 2220)
        self.assertEqual(record.arg2, 238)
        self.assertFalse(record.is_terminator)

    def test_opcode_is_the_low_byte_not_the_word(self) -> None:
        # 0x1A1B, 0x181B and 0x0E1B are all opcode 0x1B with differing arg0;
        # reading word 0 as the opcode would make them three opcodes.
        body = _record(0x1B, 26, 679, 9413) + _record(0x1B, 24, 679, 9925) + _record(0x1B, 14, 3660, 8839)
        triggers = U9Triggers(_archive({1: body + TERMINATOR}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertEqual(trigger.opcodes, [0x1B, 0x1B, 0x1B])
        self.assertEqual([r.arg0 for r in trigger.records], [26, 24, 14])


class TriggerTerminationTests(unittest.TestCase):
    def test_terminator_ends_the_body_and_is_excluded(self) -> None:
        triggers = U9Triggers(_archive({1: _record(0x01, 1) + TERMINATOR}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertEqual(len(trigger.records), 1)
        self.assertTrue(trigger.terminated)
        self.assertEqual(trigger.slack_records, 0)

    def test_records_after_the_terminator_are_slack(self) -> None:
        # A trigger that shrank leaves stale records in its allocated entry.
        blob = _record(0x01, 1) + TERMINATOR + _record(0x00) + _record(0x1F, 0, 0, 28)
        triggers = U9Triggers(_archive({1: blob}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertEqual(len(trigger.records), 1)
        self.assertEqual(trigger.slack_records, 2)
        self.assertTrue(trigger.terminated)

    def test_leading_terminator_is_an_empty_trigger(self) -> None:
        blob = TERMINATOR + _record(0x00) + _record(0x00)
        triggers = U9Triggers(_archive({1: blob}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertTrue(trigger.is_empty)
        self.assertEqual(trigger.records, ())
        self.assertEqual(trigger.slack_records, 2)
        self.assertTrue(trigger.terminated)

    def test_terminator_matched_on_the_opcode_byte_not_the_word(self) -> None:
        # The shipped archive has one terminator whose arg0 is 0x00 rather
        # than the usual 0x10; matching the word 0x10FF would miss it.
        triggers = U9Triggers(_archive({1: _record(0x01) + _record(0xFF, 0x00)}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertTrue(trigger.terminated)
        self.assertEqual(len(trigger.records), 1)

    def test_unterminated_trigger_is_reported_not_hidden(self) -> None:
        triggers = U9Triggers(_archive({1: _record(0x0C, 0x10, 0xD2F, 0x85A2)}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertFalse(trigger.terminated)
        self.assertEqual(len(trigger.records), 1)
        self.assertEqual(triggers.unterminated_trigger_ids(), [1])


class TriggerArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.triggers = U9Triggers(
            _archive(
                {
                    1: _record(0x01, 5) + TERMINATOR,
                    3: _record(0x0A) + _record(0x01) + TERMINATOR,
                    5: TERMINATOR,
                }
            )
        )

    def test_unused_slots_return_none(self) -> None:
        self.assertIsNone(self.triggers.trigger(0))
        self.assertIsNone(self.triggers.trigger(2))
        self.assertIsNotNone(self.triggers.trigger(1))

    def test_used_trigger_ids(self) -> None:
        self.assertEqual(self.triggers.used_trigger_ids(), [1, 3, 5])

    def test_triggers_returns_every_used_slot(self) -> None:
        ids = [t.trigger_id for t in self.triggers.triggers()]
        self.assertEqual(ids, [1, 3, 5])

    def test_out_of_range_trigger_id_raises(self) -> None:
        with self.assertRaises(U9TriggersError):
            self.triggers.trigger(999)
        with self.assertRaises(U9TriggersError):
            self.triggers.trigger(-1)

    def test_opcode_histogram_excludes_terminators(self) -> None:
        histogram = self.triggers.opcode_histogram()
        self.assertEqual(histogram[0x01], 2)
        self.assertEqual(histogram[0x0A], 1)
        self.assertEqual(histogram[0xFF], 0)
        self.assertEqual(sum(histogram.values()), 3)

    def test_empty_trigger_contributes_nothing(self) -> None:
        trigger = self.triggers.trigger(5)
        assert trigger is not None
        self.assertTrue(trigger.is_empty)
        self.assertEqual(trigger.opcodes, [])


class TriggerValidationTests(unittest.TestCase):
    def test_entry_length_not_a_multiple_of_six_raises(self) -> None:
        triggers = U9Triggers(_archive({1: b"\x01\x02\x03\x04"}))
        with self.assertRaises(U9TriggersError):
            triggers.trigger(1)

    def test_from_file_rejects_a_non_flx_file(self) -> None:
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".flx", delete=False) as f:
            f.write(b"\x01" * 16)
            path = f.name
        try:
            with self.assertRaises(U9TriggersError):
                U9Triggers.from_file(path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
