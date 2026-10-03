"""Tests for titan.u9.trigger_operands' typed views of trigger operands.

The views read the stored words and never change them, so the central
property is losslessness: every record's named fields, branch bits and
leftover bits rebuild ``arg2`` exactly.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_u9_triggers import TERMINATOR, _archive, _record
from titan.u9.trigger_operands import (
    ANY_TARGET_TYPE,
    RETAIL_CONFIRMED,
    RETAIL_CORROBORATED,
    STATUS_BIT_OBJECT_FLAGS,
    TARGETED_OPCODES,
    branch,
    operand_summary,
    parameter_layout,
    parameters,
    target_selection,
)
from titan.u9.triggers import (
    U9TriggerRecord,
    U9Triggers,
    trigger_special_action_info,
)

ROOT = Path(__file__).resolve().parents[2] / "u9data"
CORPUS = {
    "1.19F": ROOT / "gameData_u9" / "static" / "triggers.flx",
    "1.19H": ROOT / "Patches" / "v1.19H" / "static" / "triggers.flx",
}


def _rebuild(record: U9TriggerRecord) -> int:
    """Recompose arg2 from the decoded views alone."""
    view = record.parameters
    assert view is not None
    fields, _ = parameter_layout(record.opcode)
    value = view.unclassified_bits
    for field, (name, decoded) in zip(fields, view.fields):
        assert field.name == name
        value |= decoded << field.shift
    branch_view = record.branch
    if branch_view is not None:
        value |= record.arg2 & branch_view.mask
    return value


class TargetSelectionTests(unittest.TestCase):
    def test_link_selector_is_biased_by_sixteen_and_zero_means_no_filter(self) -> None:
        own = target_selection(0x09, 16, 1094)
        next_link = target_selection(0x09, 17, 1094)
        unfiltered = target_selection(0x09, 0, 1094)
        assert own and next_link and unfiltered
        self.assertEqual((own.link_delta, next_link.link_delta), (0, 1))
        self.assertIsNone(unfiltered.link_delta)
        self.assertEqual(own.target_type, 1094)

    def test_any_type_and_reserved_bits_are_kept_separate(self) -> None:
        view = target_selection(0x01, 0xF0 | 3, 0xE000 | ANY_TARGET_TYPE)
        assert view is not None
        self.assertTrue(view.any_type)
        self.assertEqual(view.link_selector, 0x10 | 3)
        self.assertEqual(view.reserved_arg0_bits, 0xE0)
        self.assertEqual(view.reserved_arg1_bits, 0xE000)

    def test_only_targeted_commands_have_a_target_view(self) -> None:
        self.assertEqual(len(TARGETED_OPCODES), 64)
        self.assertIsNone(target_selection(0x1F, 16, 0))  # inline map transition
        self.assertIsNone(target_selection(0x31, 16, 9))  # inline NPC activity
        self.assertIsNotNone(target_selection(0x51, 16, 9))  # searched, no effect
        self.assertIsNotNone(target_selection(0x21, 16, 9))  # random collection

    def test_speech_uses_targets_except_for_its_type_215_path(self) -> None:
        self.assertIsNone(target_selection(0x30, 16, 0xE000 | 215))
        view = target_selection(0x30, 17, 239)
        assert view is not None
        self.assertEqual((view.link_delta, view.target_type), (1, 239))


class BranchTests(unittest.TestCase):
    def test_on_match_label_is_the_top_three_bits(self) -> None:
        view = branch(0x29, 0x6123)
        assert view is not None
        self.assertEqual((view.form, view.label, view.mask), ("on_match", 3, 0xE000))
        self.assertTrue(branch(0x0E, 0x0123).ends_script)

    def test_count_compare_fields(self) -> None:
        view = branch(0x15, (4 << 8) | (2 << 5) | 3)
        assert view is not None
        self.assertEqual(view.form, "count_compare")
        self.assertEqual((view.label, view.compare_count), (2, 4))
        self.assertEqual(view.compare_operator, "less")
        self.assertIsNone(branch(0x15, 6).compare_operator)  # code 6 never branches

    def test_other_branch_forms(self) -> None:
        self.assertEqual(branch(0x1A, 0b1010).label, 5)
        self.assertEqual(branch(0x4F, 0x8000).label, 1)
        self.assertTrue(branch(0x4F, 0x7FFF).ends_script)
        self.assertEqual(branch(0x17, 4).label, 4)
        self.assertFalse(branch(0x16, 0).ends_script)  # a label is never an ending
        self.assertIsNone(branch(0x01, 0x1234))


class ParameterTests(unittest.TestCase):
    def test_every_opcode_has_a_non_overlapping_layout(self) -> None:
        for opcode in range(0x65):
            with self.subTest(opcode=hex(opcode)):
                layout = parameter_layout(opcode)
                assert layout is not None
                fields, evidence = layout
                self.assertEqual(evidence, RETAIL_CONFIRMED)
                seen = 0
                for field in fields:
                    self.assertFalse(seen & field.mask, field.name)
                    seen |= field.mask
                view = branch(opcode, 0)
                if view is not None and view.form not in ("label", "jump"):
                    self.assertFalse(seen & view.mask)
        self.assertIsNone(parameters(0xFF, 0))

    def test_hide_object_fields_and_unread_high_byte(self) -> None:
        view = parameters(0x09, 0xAB36)
        assert view is not None
        self.assertEqual(view.as_dict(), {"fade": 2, "scale": 1, "sound": 3})
        self.assertEqual(view.unclassified_bits, 0xAB00)
        self.assertEqual(view.evidence, RETAIL_CONFIRMED)

    def test_move_over_time_includes_deferred_callback_flags(self) -> None:
        view = parameters(0x1B, 0x05E5)
        assert view is not None
        self.assertEqual(view.get("destination_link"), 5)
        self.assertEqual(view.get("duration"), 5)
        self.assertEqual(view.get("no_vertical"), 1)
        self.assertEqual(view.get("retry_when_blocked"), 1)
        self.assertEqual(view.get("ignore_collision"), 1)
        self.assertEqual(view.unclassified_bits, 0)

    def test_step_collision_modes_are_retained_for_both_speeds(self) -> None:
        for opcode in (0x2E, 0x54):
            for mode in range(4):
                record = U9TriggerRecord(opcode, 16, 0, 0xFF3F | mode << 6)
                self.assertEqual(record.parameters.get("collision_mode"), mode)
                self.assertEqual(record.parameters.unclassified_bits, 0)
                self.assertEqual(_rebuild(record), record.arg2)

    def test_follow_time_is_per_unit_and_marker_link_is_independent(self) -> None:
        self.assertEqual(
            parameters(0x39, (31 << 11) | 2047).as_dict(),
            {"start_link": 2047, "time_per_unit": 31},
        )

    def test_movement_zero_duration_uses_minimum_without_changing_word(self) -> None:
        for word, duration in ((0, 500), (0xFFE0, 500), (0x0505, 2500), (31, 15500)):
            record = U9TriggerRecord(0x1B, 16, 0, word)
            self.assertEqual(record.movement_duration_ms, duration)
            self.assertEqual(_rebuild(record), word)
        self.assertIsNone(U9TriggerRecord(0x39, 16, 0, 0).movement_duration_ms)

    def test_special_action_uses_whole_word_and_preserves_ignored_values(self) -> None:
        for action in (9, 10, 11):
            self.assertEqual(
                trigger_special_action_info(action).meaning, "reserved no-op"
            )
        for action in (24, 0x100, 0xFFFF):
            record = U9TriggerRecord(0x3D, 16, 0, action)
            self.assertIsNone(record.special_action_info)
            self.assertEqual(record.to_bytes(), _record(0x3D, 16, 0, action))
        self.assertIsNone(trigger_special_action_info(-1))
        self.assertIsNotNone(U9TriggerRecord(0x3D, 16, 0, 0).special_action_info)
        self.assertIsNone(U9TriggerRecord(0x1B, 16, 0, 0).special_action_info)

    def test_status_bits_map_to_object_flags(self) -> None:
        self.assertEqual(len(STATUS_BIT_OBJECT_FLAGS), 10)
        mapped = 0
        for bit in STATUS_BIT_OBJECT_FLAGS:
            mapped |= bit
        self.assertEqual(mapped, 0x1F2F)
        self.assertEqual(parameters(0x06, 0xFFFF).unclassified_bits, 0xE0D0)
        for opcode in (0x29, 0x3B):
            view = parameters(opcode, 0xFFFF)
            assert view is not None
            self.assertEqual(view.get("status_bits"), 0x1F2F)
            self.assertEqual(view.unclassified_bits, 0x00D0)

    def test_sound_category_is_a_byte_and_sample_instance_is_separate(self) -> None:
        for opcode in (0x20, 0x26):
            view = parameters(opcode, 0xAB36)
            assert view is not None
            self.assertEqual(view.as_dict(), {"sound_category": 54})
            self.assertEqual(view.unclassified_bits, 0xAB00)
        for opcode in (0x33, 0x4C):
            self.assertEqual(
                parameters(opcode, 0xA123).as_dict(),
                {"sample": 291, "instance_id": 5},
            )
        self.assertEqual(parameters(0x4D, 0xA123).get("instance_id"), 5)

    def test_link_flags_have_distinct_direction_and_source_roles(self) -> None:
        relative = parameters(0x12, 0x8001)
        self.assertEqual(relative.as_dict(), {"amount": 1, "subtract": 1})
        for word, subtract, source in ((0x4001, 1, 0), (0x8001, 0, 1)):
            view = parameters(0x57, word | 0x2000)
            assert view is not None
            self.assertEqual(
                view.as_dict(),
                {"amount": 1, "subtract": subtract, "source_only": source},
            )
            self.assertEqual(view.unclassified_bits, 0x2000)

    def test_search_radius_decodes_units_without_changing_the_word(self) -> None:
        for word, units in (
            (0, 1280),
            (0x8000, 1280),
            (10, 1280),
            (20, 2560),
            (0x800A, 10),
            (0x7FFF, 4194176),
            (0xFFFF, 32767),
        ):
            record = U9TriggerRecord(0x2C, 0, 0, word)
            self.assertEqual(record.search_radius, units)
            self.assertEqual(record.arg2, word)
            self.assertEqual(_rebuild(record), word)
        self.assertIsNone(U9TriggerRecord(0x20, 0, 0, 10).search_radius)

    def test_relocation_fade_and_projectile_units_are_named(self) -> None:
        self.assertEqual(
            parameters(0x1C, 0x123C).as_dict(),
            {
                "placement_mode": 0,
                "copy_marker_orientation": 1,
                "retain_altitude": 1,
                "destination_link": 0x123,
            },
        )
        fade = parameters(0x63, 0x859E)
        self.assertEqual(
            fade.as_dict(),
            {
                "center_interval_ms": 30,
                "fade_in": 1,
                "edge_interval_ms": 5,
            },
        )
        self.assertEqual(fade.unclassified_bits, 0x8000)
        projectile = parameters(0x2A, 0x2EA9)
        self.assertEqual(
            projectile.as_dict(),
            {
                "x_direction": 1,
                "y_direction": 5,
                "z_direction": 2,
                "targeted": 1,
                "avatar_aim": 1,
                "projectile_kind": 5,
            },
        )

    def test_newly_confirmed_bits_remain_lossless_even_when_not_shipped(self) -> None:
        for opcode in (
            0x12,
            0x1B,
            0x20,
            0x23,
            0x26,
            0x29,
            0x2A,
            0x2C,
            0x2E,
            0x39,
            0x3B,
            0x54,
            0x57,
            0x63,
        ):
            for word in (
                0,
                1,
                0xFFFF,
                0xAAAA,
                0x5555,
                *(1 << bit for bit in range(16)),
            ):
                with self.subTest(opcode=opcode, word=word):
                    record = U9TriggerRecord(opcode, 0, 0, word)
                    self.assertEqual(_rebuild(record), word)

    def test_summary_names_every_view(self) -> None:
        text = operand_summary(0x29, 17, ANY_TARGET_TYPE, 0x2003)
        self.assertIn("targets link +1, any type", text)
        self.assertIn("go to label 1 if matched", text)
        self.assertIn("status_bits=3", text)
        hidden = operand_summary(0x09, 16, 1094, 0xAB36)
        self.assertIn("unread 0xAB00", hidden)
        self.assertIn("unread 0x0001", operand_summary(0x2B, 16, 1, 0x0001))


class TriggerAuditTests(unittest.TestCase):
    def test_unresolved_branch_label_is_reported(self) -> None:
        body = (
            _record(0x16, 16, 0, 1)
            + _record(0x17, 0, 0, 1)
            + _record(0x29, 16, 0, 0x4001)  # label 2 does not exist
            + _record(0x17, 0, 0, 0)  # label 0 ends the script: not reported
            + TERMINATOR
        )
        triggers = U9Triggers(_archive({1: body}))
        trigger = triggers.trigger(1)
        assert trigger is not None
        self.assertEqual(trigger.unresolved_branch_labels(), [(2, 2)])
        self.assertEqual(triggers.unresolved_branch_labels(), {1: [(2, 2)]})


class RetailCorpusTests(unittest.TestCase):
    def test_views_are_lossless_on_every_shipped_record(self) -> None:
        tested = 0
        for build, path in CORPUS.items():
            if not path.is_file():
                continue
            tested += 1
            with self.subTest(build=build):
                for trigger in U9Triggers.from_file(path).triggers():
                    for record in trigger.records:
                        self.assertEqual(_rebuild(record), record.arg2)
                        target = record.target_selection
                        if target is not None:
                            self.assertEqual(target.reserved_arg0_bits, 0)
                            self.assertEqual(target.reserved_arg1_bits, 0)
                        view = record.parameters
                        if view.evidence == RETAIL_CORROBORATED:
                            # Source-backed layouts account for every used bit.
                            self.assertEqual(
                                view.unclassified_bits, 0, hex(record.opcode)
                            )
        if not tested:
            self.skipTest("retail triggers.flx not available")


if __name__ == "__main__":
    unittest.main()
