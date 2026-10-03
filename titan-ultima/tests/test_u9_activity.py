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

from titan.u9.activity import (
    ACTIVITY_OPCODE_CATALOGUE,
    GESTURE_ANIMATION_IDS,
    U9Activities,
    U9ActivityError,
    U9ActivityStep,
    activity_action_argument,
    activity_opcode_info,
)
from titan.u9.flx_archive import U9FlxArchive

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_VERSION_OFFSET = 0x54
FLX_SIZE_OFFSET = 0x58
NAME_FIELD_SIZE = 15


def _step(opcode: int, operands: bytes = b"\x00" * 8) -> bytes:
    return bytes([opcode]) + operands.ljust(8, b"\x00")[:8]


TERMINATOR = _step(0xFF)


def _record(
    ordinal: int, name: str, steps: list[bytes], padding: bytes = b"\x00"
) -> bytes:
    raw = name.encode() + b"\x00"
    field = (raw + padding * NAME_FIELD_SIZE)[:NAME_FIELD_SIZE]
    return bytes([ordinal]) + field + b"".join(steps) + TERMINATOR


def _entry(records: list[bytes], count: int | None = None) -> bytes:
    body = b"".join(records)
    return (
        struct.pack("<II", len(records) if count is None else count, len(body)) + body
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
    struct.pack_into("<I", header, FLX_VERSION_OFFSET, 2)
    struct.pack_into("<I", header, FLX_SIZE_OFFSET, len(header) + len(payload))
    return U9FlxArchive(bytes(header) + payload)


class ActivityRecordTests(unittest.TestCase):
    def test_parses_records_and_steps(self) -> None:
        entry = _entry(
            [
                _record(1, "Sequence 1", [_step(0x04, bytes([0x1F]))]),
                _record(
                    2, "After Yew", [_step(0x03, b"\xb4\xcc\x09"), _step(0x0A, b"\x01")]
                ),
            ]
        )
        activities = U9Activities(_archive({1: entry}))
        activity = activities.activity(1)
        assert activity is not None
        self.assertEqual(activity.declared_record_count, 2)
        self.assertEqual(activity.names, ["Sequence 1", "After Yew"])
        self.assertEqual([len(r.steps) for r in activity.records], [1, 2])
        self.assertEqual(activity.records[1].opcodes, [0x03, 0x0A])
        self.assertEqual(
            activity.records[0].steps[0].operands, b"\x1f\x00\x00\x00\x00\x00\x00\x00"
        )
        self.assertEqual(activity.records[0].entry_offset, 8)
        self.assertEqual(activity.records[0].steps[0].entry_offset, 24)
        self.assertEqual(activity.to_bytes(), entry)

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
        self.assertEqual(
            activity.records[0].raw_name_field,
            (b"Idle\x00" + b"\xcd" * NAME_FIELD_SIZE)[:NAME_FIELD_SIZE],
        )
        self.assertEqual(activity.to_bytes(), entry)

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
        entry = _entry(
            [
                _record(1, "Idle", [_step(0x04)]),
                _record(2, "Sailing", [_step(0x04)]),
                _record(12, "To LBC", [_step(0x03)]),
                _record(13, "teleport", [_step(0x03)]),
            ]
        )
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual([r.ordinal for r in activity.records], [1, 2, 12, 13])
        self.assertTrue(activity.is_complete)


class ActivityOperandTests(unittest.TestCase):
    def test_fixed_operand_words_and_parallel_forensic_views(self) -> None:
        operands = struct.pack("<HHHH", 0x1234, 0x5678, 0x9ABC, 0xDEF0)
        entry = _entry([_record(1, "Walk", [_step(0x01, operands)])])
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        step = activity.records[0].steps[0]
        self.assertEqual(step.operands_u16, (0x1234, 0x5678, 0x9ABC, 0xDEF0))
        self.assertEqual(step.operands_u32, (0x56781234, 0xDEF09ABC))
        self.assertEqual(step.parameter_0, 0x1234)
        self.assertEqual(step.parameter_1, 0x5678)
        self.assertEqual(step.scheduled_minute, 0x9ABC)
        self.assertEqual(step.duration_code, 0xDEF0)
        self.assertEqual(step.duration_value, 0xDEF0 >> 2)
        self.assertEqual(step.duration_remainder, 0)
        self.assertEqual(step.movement_points, (0x1234, 0x5678))
        self.assertEqual(step.to_bytes(), _step(0x01, operands))
        terminator = activity.records[0].terminator
        assert terminator is not None
        self.assertEqual(terminator.entry_offset, 33)
        self.assertTrue(terminator.is_repeat_marker)
        self.assertEqual(terminator.semantic_name, "repeat activity cycle")

    def test_command_specific_views_do_not_reinterpret_other_commands(self) -> None:
        relocation = struct.pack("<HHHH", 0xCCB4, 9, 720, 31)
        action = struct.pack("<HHHH", 4, 12, 0, 43)
        entry = _entry(
            [_record(1, "Typed", [_step(0x03, relocation), _step(0x04, action)])]
        )
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        relocate_step, action_step = activity.records[0].steps
        self.assertEqual(relocate_step.relocation_target, (0xCCB4, 9))
        self.assertIsNone(relocate_step.movement_points)
        self.assertIsNone(relocate_step.duration_value)
        self.assertEqual(action_step.npc_action, (4, 12))
        self.assertEqual(action_step.duration_value, 10)
        self.assertEqual(action_step.duration_remainder, 3)

    def test_control_flow_and_interaction_parameter_views(self) -> None:
        cases = {
            0x05: ("conversation_topic", 100),
            0x06: ("object_selector", 3343),
            0x07: ("sequence_ordinal", 2),
            0x09: ("trigger_phase", 3),
            0x0A: ("sequence_ordinal", 12),
            0x0B: ("branch_label", 7),
            0x0C: ("branch_label", 7),
        }
        records = [
            _record(
                index,
                f"Case {opcode}",
                [_step(opcode, struct.pack("<HHHH", value, 99, 12, 16))],
            )
            for index, (opcode, (_, value)) in enumerate(cases.items(), start=1)
        ]
        activity = U9Activities(_archive({1: _entry(records)})).activity(1)
        assert activity is not None
        for record, (_, (property_name, expected)) in zip(
            activity.records, cases.items(), strict=True
        ):
            self.assertEqual(getattr(record.steps[0], property_name), expected)

    def test_catalogue_covers_every_runtime_command(self) -> None:
        self.assertEqual(
            [info.opcode for info in ACTIVITY_OPCODE_CATALOGUE], list(range(13))
        )
        self.assertEqual(
            activity_opcode_info(0x08).meaning,  # type: ignore[union-attr]
            "return from activity sequence",
        )
        self.assertIsNone(activity_opcode_info(0x80))


class ActivityArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.activities = U9Activities(
            _archive(
                {
                    1: _entry([_record(1, "Sequence 1", [_step(0x04)])]),
                    3: _entry(
                        [
                            _record(1, "Stand", [_step(0x03), _step(0x0A)]),
                            _record(2, "Loiter", [_step(0x03)]),
                        ]
                    ),
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
    def test_trailing_and_post_payload_bytes_are_preserved(self) -> None:
        record = _record(1, "Stand", [])
        entry = struct.pack("<II", 1, len(record) + 2) + record + b"xy" + b"post"
        activity = U9Activities(_archive({1: entry})).activity(1)
        assert activity is not None
        self.assertEqual(activity.trailing_data, b"xy")
        self.assertEqual(activity.post_payload_data, b"post")
        self.assertFalse(activity.is_complete)
        self.assertEqual(activity.to_bytes(), entry)

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


class ActivityActionArgumentTests(unittest.TestCase):
    def test_gesture_examples_from_shipped_activity_archive(self) -> None:
        for raw, selector, clip, scale, repeat in (
            (0xA049, 73, 805, 0.8, True),
            (0x8072, 114, 937, 1.0, True),
            (0x3072, 114, 937, 0.7, False),
        ):
            with self.subTest(raw=raw):
                word = activity_action_argument(24, raw)
                self.assertEqual(word.gesture_selector, selector)
                self.assertEqual(word.gesture_animation_id, clip)
                self.assertAlmostEqual(word.playback_scale, scale)  # type: ignore[arg-type]
                self.assertEqual(word.repeat, repeat)
                self.assertEqual(word.unused_bits, 0)
                self.assertIsNone(word.target_link)

    def test_manipulation_high_bit_is_speed_not_repeat(self) -> None:
        pickup = activity_action_argument(26, 0xC001)
        drop = activity_action_argument(27, 0xC00B)
        self.assertEqual(pickup.target_link, 1)
        self.assertEqual(drop.placement_marker_link, 11)
        for word in (pickup, drop):
            self.assertEqual(word.speed_step, 6)
            self.assertAlmostEqual(word.playback_scale, 0.4)  # type: ignore[arg-type]
            self.assertIsNone(word.repeat)
        self.assertIsNone(drop.target_link)
        self.assertIsNone(pickup.placement_marker_link)

    def test_full_word_selectors_keep_kind_and_zero_meanings(self) -> None:
        cases = {
            4: "starting_marker_link",
            30: "starting_marker_link",
            35: "starting_marker_link",
            36: "starting_marker_link",
            5: "heading_degrees",
            20: "facing_link",
            23: "facing_base_type",
            28: "facing_link",
        }
        for kind, name in cases.items():
            for raw in (0, 360, 0xFFFF):
                with self.subTest(kind=kind, raw=raw):
                    word = activity_action_argument(kind, raw)
                    self.assertEqual(getattr(word, name), raw)
                    self.assertEqual(word.consumed_mask, 0xFFFF)
                    self.assertIsNone(word.speed_step)
                    self.assertIsNone(word.request_assistance)
        self.assertIsNone(activity_action_argument(20, 12).facing_base_type)
        self.assertIsNone(activity_action_argument(23, 12).facing_link)

    def test_furniture_bit_and_ignored_bits(self) -> None:
        for kind in (13, 31, 32, 37, 38):
            name = "nearest_chair" if kind == 31 else "nearest_bed"
            for raw, nearest in ((0xFFFE, False), (0xFFFF, True)):
                word = activity_action_argument(kind, raw)
                self.assertEqual(getattr(word, name), nearest)
                self.assertEqual(word.unused_bits, 0xFFFE)
                self.assertEqual(word.consumed_mask, 1)
                self.assertEqual(word.raw_word, raw)

    def test_combat_uses_any_nonzero_word_without_a_target_selector(self) -> None:
        for raw in (0, 1, 2, 0x8000, 0xFFFF):
            word = activity_action_argument(0xFFFF, raw)
            self.assertEqual(word.request_assistance, raw != 0)
            self.assertIsNone(word.target_link)
        self.assertIsNone(activity_action_argument(0xFFFE, 1).request_assistance)

    def test_unperformed_unknown_and_ignored_arguments_are_preserved(self) -> None:
        for kind in (
            0,
            1,
            2,
            3,
            6,
            12,
            14,
            15,
            16,
            17,
            18,
            19,
            21,
            22,
            29,
            33,
            34,
            39,
            0xFFFE,
        ):
            word = activity_action_argument(kind, 0xA5A5)
            self.assertEqual(word.unused_bits, 0xA5A5)
            self.assertEqual(word.consumed_mask, 0)
            self.assertIsNone(word.gesture_selector)
            self.assertIsNone(word.nearest_bed)

    def test_gesture_table_aliases_and_bounds(self) -> None:
        self.assertEqual(len(GESTURE_ANIMATION_IDS), 121)
        self.assertEqual(GESTURE_ANIMATION_IDS[117:119], (1113, 1113))
        self.assertEqual(activity_action_argument(24, 120).gesture_animation_id, 426)
        for selector in (121, 122, 4095):
            word = activity_action_argument(24, selector | 0xF000)
            self.assertEqual(word.gesture_selector, selector)
            self.assertIsNone(word.gesture_animation_id)
            self.assertEqual(word.raw_word, selector | 0xF000)

    def test_every_packed_gesture_and_manipulation_word_round_trips(self) -> None:
        for raw in range(0x10000):
            gesture = activity_action_argument(24, raw)
            selector, speed, repeat = (
                gesture.gesture_selector,
                gesture.speed_step,
                gesture.repeat,
            )
            assert selector is not None and speed is not None and repeat is not None
            self.assertEqual(
                selector | (speed << 12) | (int(repeat) << 15),
                raw,
            )
            pickup = activity_action_argument(26, raw)
            link, speed = pickup.target_link, pickup.speed_step
            assert link is not None and speed is not None
            self.assertEqual(
                link | (speed << 13),
                raw,
            )

    def test_typed_step_view_keeps_all_stored_words(self) -> None:
        operands = struct.pack("<4H", 24, 0xA049, 719, 43)
        step = U9ActivityStep(4, operands)
        word = step.npc_action_argument
        assert word is not None
        self.assertEqual(word.kind.name, "gesture")
        self.assertEqual(word.raw_word, 0xA049)
        self.assertEqual(step.to_bytes(), bytes([4]) + operands)
        self.assertEqual(step.npc_action, (24, 0xA049))
        self.assertIsNone(U9ActivityStep(5, operands).npc_action_argument)
        for kind, raw in ((24, -1), (24, 65536), (-1, 0), (65536, 0)):
            with self.assertRaises(ValueError):
                activity_action_argument(kind, raw)


if __name__ == "__main__":
    unittest.main()
