"""Text, JSON and CSV data views over the reusable U8 ANIM.DAT parser."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from typing import Any

from titan.u8.anim import (
    ACTION_COUNT,
    DIRECTION_NAMES,
    SHAPE_COUNT,
    U8AnimData,
    U8AnimError,
)


def format_u8_anim_report(
    data: U8AnimData,
    *,
    shape: int | None = None,
    action: int | None = None,
    direction: int | None = None,
    frames: bool = False,
    output_format: str = "text",
) -> str:
    """Filter actions without renumbering; direction selection includes frame detail."""
    if shape is not None and not 0 <= shape < SHAPE_COUNT:
        raise U8AnimError("ANIM.DAT report: shape must be 0-2047")
    if action is not None and not 0 <= action < ACTION_COUNT:
        raise U8AnimError("ANIM.DAT report: action must be 0-63")
    if direction is not None and not 0 <= direction < len(DIRECTION_NAMES):
        raise U8AnimError("ANIM.DAT report: direction must be 0-7")
    if output_format not in {"text", "json", "csv"}:
        raise U8AnimError("ANIM.DAT report: format must be text, json or csv")
    detailed = frames or direction is not None
    rows: list[dict[str, Any]] = []
    for entry in data.iter_actions():
        if shape is not None and entry.shape_num != shape:
            continue
        if action is not None and entry.action_num != action:
            continue
        row: dict[str, Any] = {
            "shape": entry.shape_num,
            "action": entry.action_num,
            "name": entry.name,
            "offset": entry.offset,
            "frame_count": entry.frame_count,
            "repeat": entry.repeat,
            "flags": entry.flags,
            "flag_names": entry.flag_names(),
            "unknown_4": entry.unknown_4,
            "unknown_10": entry.unknown_10,
            "raw_header": entry.raw_header.hex(),
        }
        if detailed:
            frame_rows = []
            for index, nodes in enumerate(entry.directions):
                if direction is not None and index != direction:
                    continue
                for step, node in enumerate(nodes):
                    frame_row = asdict(node)
                    frame_row["raw"] = node.raw.hex()
                    frame_row["direction"] = index
                    frame_row["direction_name"] = DIRECTION_NAMES[index]
                    frame_row["step"] = step
                    frame_row["movement_world_units"] = node.movement_world_units
                    frame_rows.append(frame_row)
            row["frames"] = frame_rows
        rows.append(row)

    if output_format == "json":
        return (
            json.dumps(
                {
                    "shape_count": len(data.action_offsets),
                    "action_count": len(data.actions),
                    "selected_action_count": len(rows),
                    "direction_names": DIRECTION_NAMES,
                    "repeat_unit": "engine wait count; not milliseconds",
                    "actions": rows,
                },
                indent=2,
            )
            + "\n"
        )
    if output_format == "csv":
        fields = [
            "shape",
            "action",
            "name",
            "offset",
            "frame_count",
            "repeat",
            "flags",
            "flag_names",
            "unknown_4",
            "unknown_10",
            "raw_header",
        ]
        if detailed:
            fields += [
                "direction",
                "direction_name",
                "step",
                "frame",
                "delta_z",
                "sfx",
                "delta_dir",
                "movement_world_units",
                "special",
                "flags_hi",
                "on_ground",
                "attack_range",
                "flipped",
                "call_usecode",
                "unknown_flag80",
                "raw",
            ]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            summary = {key: value for key, value in row.items() if key != "frames"}
            summary["flag_names"] = "|".join(row["flag_names"])
            if detailed:
                for frame_row in row["frames"]:
                    writer.writerow({**summary, **frame_row})
            else:
                writer.writerow(summary)
        return output.getvalue()

    lines = [
        f"ANIM.DAT: {len(data.action_offsets)} populated shape tables, "
        f"{len(data.actions)} actions; {len(rows)} selected",
        "Directions: "
        + ", ".join(f"{i}={name}" for i, name in enumerate(DIRECTION_NAMES)),
        "Repeat: engine wait count, not milliseconds. DeltaDir: signed 9-bit, "
        "4 world units/step. DeltaZ: signed world units.",
        "Shape Action Name               Offset     Frames Repeat Flags  Header",
    ]
    for row in rows:
        lines.append(
            f"{row['shape']:5d} {row['action']:6d} {row['name']:<18} "
            f"0x{row['offset']:08x} {row['frame_count']:6d} {row['repeat']:6d} "
            f"0x{row['flags']:04x} {row['raw_header']}"
        )
        lines.append(
            "  Flags: "
            + (", ".join(row["flag_names"]) or "none")
            + f"; unknown_4={row['unknown_4']}, unknown_10={row['unknown_10']}"
        )
        if detailed:
            for node in row["frames"]:
                markers = [
                    name
                    for name in ("special", "on_ground", "flipped", "call_usecode")
                    if node[name]
                ]
                lines.append(
                    f"  {node['direction_name']:2} step={node['step']:3d} "
                    f"frame={node['frame']:4d} dz={node['delta_z']:4d} "
                    f"sfx={node['sfx']:3d} delta_dir={node['delta_dir']:4d} "
                    f"move={node['movement_world_units']:5d} range={node['attack_range']} "
                    f"flags_hi=0x{node['flags_hi']:x} flag80={int(node['unknown_flag80'])} "
                    f"{','.join(markers) or '-'} raw={node['raw']}"
                )
    if not rows:
        lines.append("No populated actions match these filters.")
    return "\n".join(lines) + "\n"
