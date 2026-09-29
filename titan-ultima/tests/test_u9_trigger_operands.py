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
from titan.u9.triggers import U9TriggerRecord, U9Triggers

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
        self.assertEqual(len(TARGETED_OPCODES), 63)
        self.assertIsNone(target_selection(0x1F, 16, 0))  # inline map transition
        self.assertIsNone(target_selection(0x31, 16, 9))  # inline NPC activity
        self.assertIsNotNone(target_selection(0x51, 16, 9))  # searched, no effect


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
                self.assertIn(evidence, (RETAIL_CONFIRMED, RETAIL_CORROBORATED))
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

    def test_move_over_time_keeps_source_only_bits_unread(self) -> None:
        view = parameters(0x1B, 0x05E5)
        assert view is not None
        self.assertEqual(view.get("destination_link"), 5)
        self.assertEqual(view.get("duration"), 5)
        self.assertEqual(view.get("no_vertical"), 1)
        self.assertEqual(view.unclassified_bits, 0x00A0)

    def test_status_bits_map_to_object_flags(self) -> None:
        self.assertEqual(len(STATUS_BIT_OBJECT_FLAGS), 10)
        mapped = 0
        for bit in STATUS_BIT_OBJECT_FLAGS:
            mapped |= bit
        self.assertEqual(mapped, 0x1F2F)
        self.assertEqual(parameters(0x06, 0xFFFF).unclassified_bits, 0xE0D0)

    def test_summary_names_every_view(self) -> None:
        text = operand_summary(0x29, 17, ANY_TARGET_TYPE, 0x2003)
        self.assertIn("targets link +1, any type", text)
        self.assertIn("go to label 1 if matched", text)
        self.assertIn("status_bits=3", text)
        hidden = operand_summary(0x09, 16, 1094, 0xAB36)
        self.assertIn("unread 0xAB00", hidden)
        # A source-backed layout's leftover bits are unclassified, not "unread".
        self.assertIn("unclassified 0x0001", operand_summary(0x2B, 16, 1, 0x0001))


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
