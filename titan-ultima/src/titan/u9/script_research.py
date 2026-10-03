"""Deterministic research exports for U9 trigger and activity bytecode.

The CSV files retain raw records beside confirmed typed views. Parallel u16
and u32 columns remain forensic conveniences and do not override the fixed
activity word layout or command-specific operand roles.
"""

from __future__ import annotations

__all__ = ["export_script_research_bundle"]

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from titan.u9.activity import ACTIVITY_OPCODE_CATALOGUE, U9Activities
from titan.u9.triggers import TRIGGER_OPCODE_CATALOGUE, U9TriggerRecord, U9Triggers


def _hex8(value: int) -> str:
    return f"0x{value:02X}"


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


OPERAND_COLUMNS = [
    "target_link_selector",
    "target_link_delta",
    "target_type",
    "target_any_type",
    "branch_form",
    "branch_label",
    "branch_compare",
    "branch_compare_count",
    "parameter_fields",
    "parameter_unclassified_hex",
    "parameter_evidence",
    "special_action_meaning",
]


def _operand_columns(record: U9TriggerRecord) -> dict[str, object]:
    """Typed operand views for one record; blank where a view does not apply."""
    columns: dict[str, object] = dict.fromkeys(OPERAND_COLUMNS, "")
    target = record.target_selection
    if target is not None:
        columns["target_link_selector"] = target.link_selector
        columns["target_link_delta"] = (
            "" if target.link_delta is None else target.link_delta
        )
        columns["target_type"] = target.target_type
        columns["target_any_type"] = int(target.any_type)
    branch = record.branch
    if branch is not None:
        columns["branch_form"] = branch.form
        columns["branch_label"] = branch.label
        if branch.compare_code is not None:
            columns["branch_compare"] = (
                branch.compare_operator or f"code_{branch.compare_code}"
            )
            columns["branch_compare_count"] = branch.compare_count
    parameters = record.parameters
    if parameters is not None:
        columns["parameter_fields"] = ";".join(
            f"{name}={value}" for name, value in parameters.fields
        )
        columns["parameter_unclassified_hex"] = f"0x{parameters.unclassified_bits:04X}"
        columns["parameter_evidence"] = parameters.evidence
    special_action = record.special_action_info
    if special_action is not None:
        columns["special_action_meaning"] = special_action.meaning
    return columns


def _sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_script_research_bundle(
    triggers: U9Triggers,
    activities: U9Activities,
    output_dir: str | os.PathLike[str],
    *,
    source_files: Mapping[str, str | os.PathLike[str]] | None = None,
) -> tuple[Path, ...]:
    """Export lossless occurrence tables, opcode summaries, and cross-links.

    ``entry_offset`` columns are relative to the start of the FLX entry, not
    the archive. This makes them usable with either an extracted entry or an
    engine buffer returned by the archive reader.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    trigger_rows = []
    trigger_counts: Counter[int] = Counter()
    trigger_ids_by_opcode: dict[int, set[int]] = defaultdict(set)
    trigger_arg0: dict[int, set[int]] = defaultdict(set)
    trigger_arg1: dict[int, set[int]] = defaultdict(set)
    trigger_arg2: dict[int, set[int]] = defaultdict(set)
    parsed_triggers = triggers.triggers()
    for trigger in parsed_triggers:
        parts = [("body", trigger_record) for trigger_record in trigger.records]
        if trigger.terminator is not None:
            parts.append(("terminator", trigger.terminator))
        parts.extend(("slack", trigger_record) for trigger_record in trigger.slack)
        for index, (role, trigger_record) in enumerate(parts):
            opcode_info = trigger_record.opcode_info
            transition = trigger_record.map_transition
            trigger_rows.append(
                {
                    "trigger_id": trigger.trigger_id,
                    "record_index": index,
                    "entry_offset": trigger_record.entry_offset,
                    "stream_role": role,
                    "opcode": _hex8(trigger_record.opcode),
                    "opcode_decimal": trigger_record.opcode,
                    "semantic_name": trigger_record.semantic_name,
                    "semantic_evidence": (
                        "" if opcode_info is None else opcode_info.evidence
                    ),
                    "arg0": trigger_record.arg0,
                    "arg1": trigger_record.arg1,
                    "arg2": trigger_record.arg2,
                    "arg2_low": trigger_record.arg2_low,
                    "arg2_high": trigger_record.arg2_high,
                    "raw_hex": trigger_record.to_bytes().hex(),
                    "map_destination_link_delta": (
                        ""
                        if transition is None
                        or transition.destination_link_delta is None
                        else transition.destination_link_delta
                    ),
                    "map_number": "" if transition is None else transition.map_number,
                    "map_effect_variant": (
                        "" if transition is None else transition.effect_variant
                    ),
                    "map_retain_running_tasks": (
                        ""
                        if transition is None
                        else int(transition.retain_running_tasks)
                    ),
                    "map_relative_position": (
                        "" if transition is None else int(transition.relative_position)
                    ),
                    "map_unclassified_flag_bits_hex": (
                        ""
                        if transition is None
                        else f"0x{transition.unclassified_flag_bits:02X}"
                    ),
                    "map_unclassified_parameter_bits_hex": (
                        ""
                        if transition is None
                        else f"0x{transition.unclassified_parameter_bits:04X}"
                    ),
                    "entry_terminated": int(trigger.terminated),
                    "slack_record_count": trigger.slack_records,
                    **_operand_columns(trigger_record),
                }
            )
            if role == "body":
                trigger_counts[trigger_record.opcode] += 1
                trigger_ids_by_opcode[trigger_record.opcode].add(trigger.trigger_id)
                trigger_arg0[trigger_record.opcode].add(trigger_record.arg0)
                trigger_arg1[trigger_record.opcode].add(trigger_record.arg1)
                trigger_arg2[trigger_record.opcode].add(trigger_record.arg2)

    trigger_opcode_rows = [
        {
            "opcode": _hex8(info.opcode),
            "opcode_decimal": info.opcode,
            "occurrences": trigger_counts[info.opcode],
            "trigger_count": len(trigger_ids_by_opcode[info.opcode]),
            "distinct_arg0": len(trigger_arg0[info.opcode]),
            "distinct_arg1": len(trigger_arg1[info.opcode]),
            "distinct_arg2": len(trigger_arg2[info.opcode]),
            "observed_in_archive": int(trigger_counts[info.opcode] != 0),
            "semantic_name": info.meaning,
            "semantic_evidence": info.evidence,
            "operand_notes": (
                "arg0 low 5 bits=destination link selector; arg2 low byte=map; "
                "arg2 bits 8-9=effect; bit 14=retain tasks; bit 15=relative"
                if info.opcode == 0x1F
                else (
                    "arg1=activity_id; arg2 low byte=record ordinal"
                    if info.opcode == 0x31
                    else ""
                )
            ),
        }
        for info in TRIGGER_OPCODE_CATALOGUE
    ]

    activity_rows = []
    activity_counts: Counter[int] = Counter()
    activity_ids_by_opcode: dict[int, set[int]] = defaultdict(set)
    activity_records_by_opcode: dict[int, set[tuple[int, int]]] = defaultdict(set)
    activity_lookup = {}
    parsed_activities = activities.activities()
    for activity in parsed_activities:
        for record_index, activity_record in enumerate(activity.records):
            activity_lookup[(activity.activity_id, activity_record.ordinal)] = (
                activity_record.name
            )
            steps = [("body", step) for step in activity_record.steps]
            if activity_record.terminator is not None:
                steps.append(("repeat_marker", activity_record.terminator))
            for step_index, (role, step) in enumerate(steps):
                u16 = step.operands_u16
                u32 = step.operands_u32
                movement = step.movement_points
                relocation = step.relocation_target
                npc_action = step.npc_action
                activity_opcode_info = step.opcode_info
                activity_rows.append(
                    {
                        "activity_id": activity.activity_id,
                        "record_index": record_index,
                        "record_ordinal": activity_record.ordinal,
                        "record_name": activity_record.name,
                        "record_entry_offset": activity_record.entry_offset,
                        "step_index": step_index,
                        "entry_offset": step.entry_offset,
                        "stream_role": role,
                        "opcode": _hex8(step.opcode),
                        "opcode_decimal": step.opcode,
                        "semantic_name": step.semantic_name,
                        "semantic_evidence": (
                            ""
                            if activity_opcode_info is None
                            else activity_opcode_info.evidence
                        ),
                        "raw_hex": step.to_bytes().hex(),
                        "operands_hex": step.operands.hex(),
                        "parameter_0": step.parameter_0,
                        "parameter_1": step.parameter_1,
                        "scheduled_minute": step.scheduled_minute,
                        "duration_code": step.duration_code,
                        "duration_value": (
                            "" if step.duration_value is None else step.duration_value
                        ),
                        "duration_remainder": (
                            ""
                            if step.duration_remainder is None
                            else step.duration_remainder
                        ),
                        "u16_0": u16[0],
                        "u16_1": u16[1],
                        "u16_2": u16[2],
                        "u16_3": u16[3],
                        "u32_0": u32[0],
                        "u32_1": u32[1],
                        "movement_source": "" if movement is None else movement[0],
                        "movement_destination": "" if movement is None else movement[1],
                        "movement_cautious": (
                            "" if movement is None else int(step.opcode == 0x02)
                        ),
                        "relocation_destination": (
                            "" if relocation is None else relocation[0]
                        ),
                        "relocation_map": "" if relocation is None else relocation[1],
                        "npc_action_kind": "" if npc_action is None else npc_action[0],
                        "npc_action_argument": (
                            "" if npc_action is None else npc_action[1]
                        ),
                        "conversation_topic": (
                            ""
                            if step.conversation_topic is None
                            else step.conversation_topic
                        ),
                        "object_selector": (
                            "" if step.object_selector is None else step.object_selector
                        ),
                        "sequence_ordinal": (
                            ""
                            if step.sequence_ordinal is None
                            else step.sequence_ordinal
                        ),
                        "trigger_phase": (
                            "" if step.trigger_phase is None else step.trigger_phase
                        ),
                        "branch_label": (
                            "" if step.branch_label is None else step.branch_label
                        ),
                        "npc_action_name": (
                            ""
                            if step.npc_action_kind is None
                            else step.npc_action_kind.name or ""
                        ),
                        "npc_action_performed": (
                            ""
                            if step.npc_action_kind is None
                            else int(step.npc_action_kind.performed)
                        ),
                    }
                )
                if role == "body":
                    activity_counts[step.opcode] += 1
                    activity_ids_by_opcode[step.opcode].add(activity.activity_id)
                    activity_records_by_opcode[step.opcode].add(
                        (activity.activity_id, record_index)
                    )

    activity_opcode_rows = [
        {
            "opcode": _hex8(info.opcode),
            "opcode_decimal": info.opcode,
            "occurrences": activity_counts[info.opcode],
            "activity_count": len(activity_ids_by_opcode[info.opcode]),
            "record_count": len(activity_records_by_opcode[info.opcode]),
            "observed_in_archive": int(activity_counts[info.opcode] != 0),
            "semantic_name": info.meaning,
            "semantic_evidence": info.evidence,
            "operand_notes": info.parameter_roles,
        }
        for info in ACTIVITY_OPCODE_CATALOGUE
    ]

    link_rows = []
    for trigger in parsed_triggers:
        for record_index, record in enumerate(trigger.records):
            reference = record.activity_reference
            if reference is None:
                continue
            activity_id, ordinal = reference
            name = activity_lookup.get(reference)
            link_rows.append(
                {
                    "trigger_id": trigger.trigger_id,
                    "record_index": record_index,
                    "entry_offset": record.entry_offset,
                    "activity_id": activity_id,
                    "record_ordinal": ordinal,
                    "record_name": "" if name is None else name,
                    "resolved": int(name is not None),
                    "arg0": record.arg0,
                    "arg2_high": record.arg2_high,
                }
            )

    paths = {
        "trigger_occurrences": destination / "trigger_occurrences.csv",
        "trigger_opcodes": destination / "trigger_opcodes.csv",
        "activity_occurrences": destination / "activity_occurrences.csv",
        "activity_opcodes": destination / "activity_opcodes.csv",
        "trigger_activity_links": destination / "trigger_activity_links.csv",
        "manifest": destination / "script_research_manifest.json",
    }
    _write_csv(
        paths["trigger_occurrences"],
        [
            "trigger_id",
            "record_index",
            "entry_offset",
            "stream_role",
            "opcode",
            "opcode_decimal",
            "semantic_name",
            "semantic_evidence",
            "arg0",
            "arg1",
            "arg2",
            "arg2_low",
            "arg2_high",
            "raw_hex",
            "map_destination_link_delta",
            "map_number",
            "map_effect_variant",
            "map_retain_running_tasks",
            "map_relative_position",
            "map_unclassified_flag_bits_hex",
            "map_unclassified_parameter_bits_hex",
            "entry_terminated",
            "slack_record_count",
            *OPERAND_COLUMNS,
        ],
        trigger_rows,
    )
    _write_csv(
        paths["trigger_opcodes"],
        [
            "opcode",
            "opcode_decimal",
            "occurrences",
            "trigger_count",
            "distinct_arg0",
            "distinct_arg1",
            "distinct_arg2",
            "observed_in_archive",
            "semantic_name",
            "semantic_evidence",
            "operand_notes",
        ],
        trigger_opcode_rows,
    )
    _write_csv(
        paths["activity_occurrences"],
        [
            "activity_id",
            "record_index",
            "record_ordinal",
            "record_name",
            "record_entry_offset",
            "step_index",
            "entry_offset",
            "stream_role",
            "opcode",
            "opcode_decimal",
            "semantic_name",
            "semantic_evidence",
            "raw_hex",
            "operands_hex",
            "parameter_0",
            "parameter_1",
            "scheduled_minute",
            "duration_code",
            "duration_value",
            "duration_remainder",
            "u16_0",
            "u16_1",
            "u16_2",
            "u16_3",
            "u32_0",
            "u32_1",
            "movement_source",
            "movement_destination",
            "movement_cautious",
            "relocation_destination",
            "relocation_map",
            "npc_action_kind",
            "npc_action_argument",
            "conversation_topic",
            "object_selector",
            "sequence_ordinal",
            "trigger_phase",
            "branch_label",
            "npc_action_name",
            "npc_action_performed",
        ],
        activity_rows,
    )
    _write_csv(
        paths["activity_opcodes"],
        [
            "opcode",
            "opcode_decimal",
            "occurrences",
            "activity_count",
            "record_count",
            "observed_in_archive",
            "semantic_name",
            "semantic_evidence",
            "operand_notes",
        ],
        activity_opcode_rows,
    )
    _write_csv(
        paths["trigger_activity_links"],
        [
            "trigger_id",
            "record_index",
            "entry_offset",
            "activity_id",
            "record_ordinal",
            "record_name",
            "resolved",
            "arg0",
            "arg2_high",
        ],
        link_rows,
    )

    sources = {}
    for name, source_path in sorted((source_files or {}).items()):
        source = Path(source_path)
        sources[name] = {
            "path": str(source.resolve()),
            "size": source.stat().st_size,
            "sha256": _sha256(source),
        }
    manifest = {
        "formats": {
            "trigger_record": "<BBHH (6 bytes)",
            "activity_entry_header": "<II (8 bytes)",
            "activity_record_prefix": "<B + char[15] (16 bytes)",
            "activity_step": "<BHHHH (9 bytes)",
        },
        "sources": sources,
        "triggers": {
            "archive_slots": triggers.num_entries,
            "used_entries": len(parsed_triggers),
            "body_records": sum(trigger_counts.values()),
            "distinct_body_opcodes": len(trigger_counts),
            "runtime_catalogue_opcodes": len(TRIGGER_OPCODE_CATALOGUE),
            "catalogued_opcodes_observed": sum(
                1
                for info in TRIGGER_OPCODE_CATALOGUE
                if trigger_counts[info.opcode] != 0
            ),
            "unterminated_ids": [
                trigger.trigger_id
                for trigger in parsed_triggers
                if not trigger.terminated
            ],
        },
        "activities": {
            "archive_slots": activities.num_entries,
            "used_entries": len(parsed_activities),
            "records": sum(len(activity.records) for activity in parsed_activities),
            "body_steps": sum(activity_counts.values()),
            "distinct_body_opcodes": len(activity_counts),
            "runtime_catalogue_opcodes": len(ACTIVITY_OPCODE_CATALOGUE),
            "catalogued_opcodes_observed": sum(
                1
                for info in ACTIVITY_OPCODE_CATALOGUE
                if activity_counts[info.opcode] != 0
            ),
            "incomplete_ids": [
                activity.activity_id
                for activity in parsed_activities
                if not activity.is_complete
            ],
        },
        "known_cross_links": {
            "trigger_opcode": "0x31",
            "total": len(link_rows),
            "resolved": sum(1 for row in link_rows if row["resolved"] == 1),
        },
    }
    with paths["manifest"].open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")

    return tuple(paths.values())
