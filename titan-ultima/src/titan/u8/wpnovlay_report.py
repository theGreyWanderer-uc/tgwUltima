"""Text, JSON and CSV data views for U8 weapon overlay placement and frames."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from titan.u8.anim import ACTION_COUNT, DIRECTION_NAMES
from titan.u8.wpnovlay import U8WeaponOverlayData, U8WeaponOverlayError


def format_u8_wpnovlay_report(
    data: U8WeaponOverlayData,
    *,
    action: int | None = None,
    overlay_type: int | None = None,
    direction: int | None = None,
    frames: bool = False,
    output_format: str = "text",
) -> str:
    """Filter original IDs; direction selection includes per-step frame details."""
    if action is not None and not 0 <= action < ACTION_COUNT:
        raise U8WeaponOverlayError("WPNOVLAY.DAT report: action must be 0-63")
    if overlay_type is not None and overlay_type < 0:
        raise U8WeaponOverlayError(
            "WPNOVLAY.DAT report: overlay type must be nonnegative"
        )
    if direction is not None and not 0 <= direction < len(DIRECTION_NAMES):
        raise U8WeaponOverlayError("WPNOVLAY.DAT report: direction must be 0-7")
    if output_format not in {"text", "json", "csv"}:
        raise U8WeaponOverlayError(
            "WPNOVLAY.DAT report: format must be text, json or csv"
        )
    detailed = frames or direction is not None
    actions: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for entry in data.iter_actions():
        if action is not None and entry.action_num != action:
            continue
        action_row: dict[str, Any] = {
            "action": entry.action_num,
            "name": entry.name,
            "offset": entry.offset,
            "size": len(entry.raw),
            "frame_count": entry.frame_count,
            "type_count": len(entry.overlays),
            "avatar_shape": 1,
            "avatar_attack": bool(entry.avatar_animation.flags & 2),
        }
        overlays: list[dict[str, Any]] = []
        for overlay in entry.overlays:
            if overlay_type is not None and overlay.type_num != overlay_type:
                continue
            type_row: dict[str, Any] = {
                "overlay_type": overlay.type_num,
                "overlay_name": overlay.name,
                "overlay_shape": overlay.shape_num,
            }
            summary = {**action_row, **type_row}
            if detailed:
                frame_rows = []
                for dir_index, nodes in enumerate(overlay.directions):
                    if direction is not None and direction != dir_index:
                        continue
                    for step, node in enumerate(nodes):
                        frame_row = {
                            "direction": dir_index,
                            "direction_name": DIRECTION_NAMES[dir_index],
                            "step": step,
                            "avatar_frame": entry.avatar_animation.directions[
                                dir_index
                            ][step].frame,
                            "frame": node.frame,
                            "x_offset": node.x_offset,
                            "y_offset": node.y_offset,
                            "raw": node.raw.hex(),
                        }
                        frame_rows.append(frame_row)
                        csv_rows.append({**summary, **frame_row})
                type_row["frames"] = frame_rows
            else:
                csv_rows.append(summary)
            overlays.append(type_row)
        if overlays:
            actions.append({**action_row, "overlays": overlays})

    if output_format == "json":
        return (
            json.dumps(
                {
                    "record_count": len(data.record_entries),
                    "action_count": len(data.actions),
                    "selected_action_count": len(actions),
                    "direction_names": DIRECTION_NAMES,
                    "offset_unit": "screen pixels relative to avatar draw position",
                    "shape_mapping_source": "decoded U8 WPNCACHE.C executable table",
                    "actions": actions,
                },
                indent=2,
            )
            + "\n"
        )
    if output_format == "csv":
        fields = [
            "action",
            "name",
            "offset",
            "size",
            "frame_count",
            "type_count",
            "avatar_shape",
            "avatar_attack",
            "overlay_type",
            "overlay_name",
            "overlay_shape",
        ]
        if detailed:
            fields += [
                "direction",
                "direction_name",
                "step",
                "avatar_frame",
                "frame",
                "x_offset",
                "y_offset",
                "raw",
            ]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(csv_rows)
        return output.getvalue()

    lines = [
        f"WPNOVLAY.DAT: {len(data.record_entries)} slots, {len(data.actions)} "
        f"populated actions; {len(actions)} selected",
        "Offsets: signed screen pixels relative to avatar draw position.",
        "Sprite shape mappings: executable table; unassigned slots remain available.",
        "Action Name               Frames Types Type Overlay        Shape",
    ]
    for action_row in actions:
        for type_row in action_row["overlays"]:
            shape = type_row["overlay_shape"]
            lines.append(
                f"{action_row['action']:6d} {action_row['name']:<18} "
                f"{action_row['frame_count']:6d} {action_row['type_count']:5d} "
                f"{type_row['overlay_type']:4d} {type_row['overlay_name']:<14} "
                + (str(shape) if shape is not None else "unassigned")
            )
            if detailed:
                for node in type_row["frames"]:
                    lines.append(
                        f"  {node['direction_name']:2} step={node['step']:3d} "
                        f"avatar_frame={node['avatar_frame']:4d} frame={node['frame']:5d} "
                        f"x={node['x_offset']:4d} y={node['y_offset']:4d} raw={node['raw']}"
                    )
    if not actions:
        lines.append("No populated overlays match these filters.")
    return "\n".join(lines) + "\n"
