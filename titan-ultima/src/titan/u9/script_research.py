"""Deterministic research exports for U9 trigger and activity bytecode.

The CSV files produced here deliberately include multiple integer views of
unknown operands. They are evidence tables for reverse engineering, not an
assertion that every operand has the displayed type.
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

from titan.u9.activity import U9Activities
from titan.u9.triggers import U9Triggers


def _hex8(value: int) -> str:
    return f"0x{value:02X}"


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
            trigger_rows.append(
                {
                    "trigger_id": trigger.trigger_id,
                    "record_index": index,
                    "entry_offset": trigger_record.entry_offset,
                    "stream_role": role,
                    "opcode": _hex8(trigger_record.opcode),
                    "opcode_decimal": trigger_record.opcode,
                    "arg0": trigger_record.arg0,
                    "arg1": trigger_record.arg1,
                    "arg2": trigger_record.arg2,
                    "arg2_low": trigger_record.arg2_low,
                    "arg2_high": trigger_record.arg2_high,
                    "entry_terminated": int(trigger.terminated),
                    "slack_record_count": trigger.slack_records,
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
            "opcode": _hex8(opcode),
            "opcode_decimal": opcode,
            "occurrences": count,
            "trigger_count": len(trigger_ids_by_opcode[opcode]),
            "distinct_arg0": len(trigger_arg0[opcode]),
            "distinct_arg1": len(trigger_arg1[opcode]),
            "distinct_arg2": len(trigger_arg2[opcode]),
            "known_semantics": (
                "run activity record: arg1=activity_id, arg2_low=ordinal"
                if opcode == 0x31
                else ""
            ),
        }
        for opcode, count in sorted(trigger_counts.items())
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
                steps.append(("terminator", activity_record.terminator))
            for step_index, (role, step) in enumerate(steps):
                u16 = step.operands_u16
                u32 = step.operands_u32
                movement = step.movement_points
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
                        "operands_hex": step.operands.hex(),
                        "u16_0": u16[0],
                        "u16_1": u16[1],
                        "u16_2": u16[2],
                        "u16_3": u16[3],
                        "u32_0": u32[0],
                        "u32_1": u32[1],
                        "movement_source": "" if movement is None else movement[0],
                        "movement_destination": "" if movement is None else movement[1],
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
            "opcode": _hex8(opcode),
            "opcode_decimal": opcode,
            "occurrences": count,
            "activity_count": len(activity_ids_by_opcode[opcode]),
            "record_count": len(activity_records_by_opcode[opcode]),
            "known_semantics": (
                "move between highway points: u16_0=source, u16_1=destination"
                if opcode in (0x01, 0x02)
                else ""
            ),
        }
        for opcode, count in sorted(activity_counts.items())
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
            "arg0",
            "arg1",
            "arg2",
            "arg2_low",
            "arg2_high",
            "entry_terminated",
            "slack_record_count",
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
            "known_semantics",
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
            "operands_hex",
            "u16_0",
            "u16_1",
            "u16_2",
            "u16_3",
            "u32_0",
            "u32_1",
            "movement_source",
            "movement_destination",
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
            "known_semantics",
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
            "activity_step": "<B + uint8[8] (9 bytes)",
        },
        "sources": sources,
        "triggers": {
            "archive_slots": triggers.num_entries,
            "used_entries": len(parsed_triggers),
            "body_records": sum(trigger_counts.values()),
            "distinct_body_opcodes": len(trigger_counts),
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
