"""Summary and complete record views for U8 FIXED/NONFIXED map items."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from typing import Any

from titan.u8.map_items import U8MapItems, U8MapItemsError
from titan.u8.typeflag import U8TypeFlags


def format_u8_map_item_report(
    data: U8MapItems,
    *,
    map_id: int | None = None,
    record_index: int | None = None,
    shape: int | None = None,
    view: str = "summary",
    scope: str = "all",
    typeflag_data: bytes | None = None,
    output_format: str = "text",
) -> str:
    """Show all 256 slot summaries or lossless raw fields with derived parent links."""
    if map_id is not None:
        data.get_map(map_id)
    if record_index is not None and (map_id is None or record_index < 0):
        raise U8MapItemsError(
            "Map items report: --record requires --map and a nonnegative index"
        )
    if record_index is not None and record_index >= len(
        data.get_map(map_id if map_id is not None else 0)
    ):
        raise U8MapItemsError(
            "Map items report: record index is outside the selected map"
        )
    if shape is not None and not 0 <= shape <= 65535:
        raise U8MapItemsError("Map items report: shape must be 0-65535")
    if view not in {"summary", "items"}:
        raise U8MapItemsError("Map items report: view must be summary or items")
    if scope not in {"all", "world", "contained", "npc"}:
        raise U8MapItemsError(
            "Map items report: scope must be all, world, contained or npc"
        )
    if output_format not in {"text", "json", "csv"}:
        raise U8MapItemsError("Map items report: format must be text, json or csv")
    if record_index is not None:
        view = "items"
    types = None
    if typeflag_data is not None:
        if not typeflag_data or len(typeflag_data) % 8 or len(typeflag_data) > 2048 * 8:
            raise U8MapItemsError(
                "Map items report: TYPEFLAG requires 1-2048 complete 8-byte entries"
            )
        types = U8TypeFlags.parse(typeflag_data)
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    map_ids = range(256) if map_id is None else [map_id]
    for current_map in map_ids:
        items = data.get_map(current_map)
        selected = [
            item
            for item in items
            if (record_index is None or item.record_index == record_index)
            and (shape is None or item.shape == shape)
            and (
                scope == "all"
                or scope == "world"
                and item.is_world_object
                or scope == "contained"
                and item.contained
                or scope == "npc"
                and item.location_kind == "npc_registry"
            )
        ]
        diagnostics.extend(
            {
                "map_id": current_map,
                "record_index": item.record_index,
                "issues": list(item.diagnostics),
            }
            for item in selected
            if item.diagnostics
        )
        if view == "summary":
            rows.append(
                {
                    "map_id": current_map,
                    "storage_kind": "npc_registry" if current_map == 0 else "world_map",
                    "file_offset": data.map_offsets[current_map],
                    "payload_bytes": data.map_sizes[current_map],
                    "record_count": len(items),
                    "selected_count": len(selected),
                    "world_count": sum(item.is_world_object for item in selected),
                    "contained_count": sum(item.contained for item in selected),
                    "npc_count": sum(
                        item.location_kind == "npc_registry" for item in selected
                    ),
                    "glob_count": sum(item.glob_num is not None for item in selected),
                    "max_depth": max((item.depth for item in selected), default=0),
                    "diagnostic_count": sum(
                        bool(item.diagnostics) for item in selected
                    ),
                }
            )
        else:
            for item in selected:
                row = asdict(item)
                row.update(
                    status_hex=f"0x{item.status:04X}",
                    status_names=item.status_names(),
                    location_kind=item.location_kind,
                    depth=item.depth,
                    gump_x=item.gump_x,
                    gump_y=item.gump_y,
                    equipment_slot=item.equipment_slot,
                    glob_num=item.glob_num,
                    raw_hex=item.to_bytes().hex(),
                )
                if types is not None:
                    info = types[item.shape] if item.shape < len(types) else None
                    row.update(
                        family=info.family if info is not None else None,
                        family_name=info.family_name() if info is not None else None,
                        shape_flags=info.flag_names() if info is not None else [],
                        equip_type=info.equiptype if info is not None else None,
                    )
                rows.append(row)
    metadata = {
        "file": f"{data.kind.upper()}.DAT",
        "archive_bytes": len(data.raw_data),
        "header_hex": data.raw_data[:128].hex(),
        "map_directory": [
            {"map_id": index, "offset": offset, "size": data.map_sizes[index]}
            for index, offset in enumerate(data.map_offsets)
        ],
        "view": view,
        "scope": scope,
        "map_slot_count": 256,
        "populated_map_count": sum(bool(items) for items in data.maps),
        "total_record_count": sum(len(items) for items in data.maps),
        "diagnostics": diagnostics,
    }
    key = "maps" if view == "summary" else "items"
    if output_format == "json":
        return json.dumps({**metadata, key: rows}, indent=2) + "\n"
    # Always emit a useful CSV header, including for an empty item selection.
    fields = (
        list(rows[0])
        if rows
        else [
            "map_id",
            "record_index",
            "file_offset",
            "x",
            "y",
            "z",
            "shape",
            "frame",
            "status",
            "quality",
            "npc_num",
            "map_num_raw",
            "next_item",
            "archive_kind",
            "parent_record_index",
            "root_record_index",
            "diagnostics",
            "status_hex",
            "status_names",
            "location_kind",
            "depth",
            "gump_x",
            "gump_y",
            "equipment_slot",
            "glob_num",
            "raw_hex",
        ]
    )
    if not rows and types is not None:
        fields.extend(["family", "family_name", "shape_flags", "equip_type"])
    if output_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (tuple, list, dict))
                    else value
                    for field, value in row.items()
                }
            )
        return output.getvalue()
    lines = [
        f"{metadata['file']}: {metadata['total_record_count']} records in {metadata['populated_map_count']} populated slots",
        f"View: {view}; scope: {scope}; selected {key}: {len(rows)}",
        " | ".join(fields),
    ]
    lines.extend(" | ".join(str(row[field]) for field in fields) for row in rows)
    if not rows:
        lines.append("No records match these filters.")
    for issue in diagnostics:
        lines.append(
            f"Diagnostic map {issue['map_id']} record {issue['record_index']}: {', '.join(issue['issues'])}"
        )
    return "\n".join(lines) + "\n"
