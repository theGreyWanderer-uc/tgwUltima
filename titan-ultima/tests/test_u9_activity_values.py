"""Tests for the activity value catalogues and set-level audits.

Covers the action kinds of begin-action steps (``0x04``), the runtime's
ordinal fallback (a set not starting at ordinal 1 runs the NPC's default
activity) and call/switch steps naming a missing ordinal.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tests.test_u9_activity import _archive, _entry, _record, _step
from titan.u9.activity import (
    ACTION_KIND_CATALOGUE,
    U9Activities,
    activity_action_kind,
)

ROOT = Path(__file__).resolve().parents[2] / "u9data"
CORPUS = {
    "1.19F": ROOT / "gameData_u9" / "static" / "activity.flx",
    "1.19H": ROOT / "Patches" / "v1.19H" / "static" / "activity.flx",
}


def _operands(
    parameter_0: int, parameter_1: int = 0, minute: int = 0, duration: int = 0
) -> bytes:
    return struct.pack("<HHHH", parameter_0, parameter_1, minute, duration)


class ActionKindTests(unittest.TestCase):
    def test_catalogue_covers_dispatched_range_and_specials(self) -> None:
        values = [kind.value for kind in ACTION_KIND_CATALOGUE]
        self.assertEqual(values[:39], list(range(39)))
        self.assertEqual(values[39:], [0xFFFE, 0xFFFF])
        self.assertEqual(
            len({kind.name for kind in ACTION_KIND_CATALOGUE}), len(values)
        )

    def test_unperformed_kinds_match_the_retail_switch(self) -> None:
        unperformed = {
            kind.value for kind in ACTION_KIND_CATALOGUE if not kind.performed
        }
        self.assertEqual(unperformed, {0, 6, 7, 8, 9, 10, 11, 12, 14, 15, 19, 21, 22})
        self.assertTrue(activity_action_kind(1).performed)
        self.assertEqual(activity_action_kind(0xFFFF).name, "combat")

    def test_uncatalogued_values_start_nothing(self) -> None:
        for value in (39, 45, 60001, 0xFFFD):
            with self.subTest(value=value):
                kind = activity_action_kind(value)
                self.assertIsNone(kind.name)
                self.assertFalse(kind.performed)

    def test_step_view_only_on_begin_action(self) -> None:
        body = _entry(
            [
                _record(
                    1,
                    "Stand",
                    [_step(0x04, _operands(31, 7, 0, 40)), _step(0x05, _operands(31))],
                )
            ]
        )
        activity = U9Activities(_archive({1: body})).activity(1)
        assert activity is not None
        begin, speech = activity.records[0].steps[:2]
        kind = begin.npc_action_kind
        assert kind is not None
        self.assertEqual((kind.name, kind.performed), ("sit_in_chair", True))
        self.assertEqual(begin.npc_action, (31, 7))
        self.assertEqual(begin.duration_value, 10)
        self.assertIsNone(speech.npc_action_kind)


class OrdinalAuditTests(unittest.TestCase):
    def test_set_not_starting_at_ordinal_one_runs_the_default_activity(self) -> None:
        body = _entry([_record(2, "Sequence 2", []), _record(3, "Sequence 3", [])])
        activity = U9Activities(_archive({1: body})).activity(1)
        assert activity is not None
        self.assertTrue(activity.starts_with_default_activity)
        normal = U9Activities(
            _archive({1: _entry([_record(1, "Stand", [])])})
        ).activity(1)
        assert normal is not None
        self.assertFalse(normal.starts_with_default_activity)

    def test_call_and_switch_to_missing_ordinal_are_reported(self) -> None:
        body = _entry(
            [
                _record(
                    1,
                    "Sequence 1",
                    [_step(0x07, _operands(2)), _step(0x0A, _operands(5))],
                ),
                _record(2, "Sequence 2", [_step(0x0A, _operands(1))]),
            ]
        )
        activity = U9Activities(_archive({1: body})).activity(1)
        assert activity is not None
        self.assertEqual(activity.unresolved_sequence_references(), [(1, 1, 5)])


class RetailCorpusTests(unittest.TestCase):
    def test_shipped_sets(self) -> None:
        tested = 0
        for build, path in CORPUS.items():
            if not path.is_file():
                continue
            tested += 1
            with self.subTest(build=build):
                activities = U9Activities.from_file(path).activities()
                self.assertEqual(
                    [
                        a.activity_id
                        for a in activities
                        if a.starts_with_default_activity
                    ],
                    [92, 157, 238, 271, 273],
                )
                self.assertEqual(
                    {
                        a.activity_id
                        for a in activities
                        if a.unresolved_sequence_references()
                    },
                    {110, 180},
                )
                steps = [
                    step
                    for activity in activities
                    for record in activity.records
                    for step in record.steps
                    if step.opcode == 0x04
                ]
                self.assertEqual(
                    sum(step.npc_action_kind.performed for step in steps), 311
                )
                # "Sequence N" is the authoring default: N is always the ordinal.
                defaults = [
                    record
                    for activity in activities
                    for record in activity.records
                    if record.name.startswith("Sequence ")
                ]
                self.assertGreater(len(defaults), 300)
                for record in defaults:
                    self.assertEqual(record.name, f"Sequence {record.ordinal}")
        if not tested:
            self.skipTest("retail activity.flx not available")


if __name__ == "__main__":
    unittest.main()
