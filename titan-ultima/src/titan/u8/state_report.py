"""Data views for U8 saved item cache, regions, NPC state and equipment links."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from typing import Any

from titan.u8.itemcach import (
    ITEM_SLOT_COUNT,
    NPC_SLOT_COUNT,
    U8ItemCache,
    U8ItemCacheError,
)
from titan.u8.npcdata import U8NpcData, U8NpcDataError


def _render_u8_state_report(
    label: str,
    metadata: dict[str, Any],
    key: str,
    rows: list[dict[str, Any]],
    fields: list[str],
    output_format: str,
) -> str:
    if output_format not in {"text", "json", "csv"}:
        raise ValueError("U8 saved state report: format must be text, json or csv")
    if output_format == "json":
        return json.dumps({"file": label, **metadata, key: rows}, indent=2) + "\n"
    if output_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    name: json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (list, tuple, dict))
                    else value
                    for name, value in row.items()
                }
            )
        return output.getvalue()
    lines = [f"{label}: {len(rows)} selected {key}"]
    if "cache" in metadata:
        cache = metadata["cache"]
        lines.append(
            f"Cache map: {cache['map_in']}; free items: {cache['free_count']}; free NPCs: {cache['free_npc_count']}; ethereal: {cache['ethereal_count']}"
        )
    lines.extend(f"List diagnostic: {issue}" for issue in metadata["list_diagnostics"])
    if "selection_basis" in metadata:
        lines.append(f"Selection: {metadata['selection_basis']}")
    lines.append(" | ".join(fields))
    for row in rows:
        lines.append(
            " | ".join(
                "-" if row[field] is None else str(row[field]) for field in fields
            )
        )
    if not rows:
        lines.append("No slots match these filters.")
    return "\n".join(lines) + "\n"


def format_u8_itemcach_report(
    data: U8ItemCache,
    *,
    item_id: int | None = None,
    shape: int | None = None,
    view: str = "items",
    all_slots: bool = False,
    output_format: str = "text",
) -> str:
    """Show items or native region cells; explicit item IDs include free/null slots."""
    if item_id is not None and not 0 <= item_id < ITEM_SLOT_COUNT:
        raise U8ItemCacheError("ITEMCACH.DAT report: item ID must be 0-9215")
    if shape is not None and not 0 <= shape <= 65535:
        raise U8ItemCacheError("ITEMCACH.DAT report: shape must be 0-65535")
    if view not in {"items", "regions"}:
        raise U8ItemCacheError("ITEMCACH.DAT report: view must be items or regions")
    if view == "regions" and (item_id is not None or shape is not None):
        raise U8ItemCacheError(
            "ITEMCACH.DAT report: item/shape filters require the items view"
        )
    cache = asdict(data.metadata)
    cache["trailing_bytes"] = data.metadata.trailing_bytes.hex()
    metadata = {
        "slot_count": ITEM_SLOT_COUNT,
        "cache": cache,
        "array_trailing_bytes": data.array_tail.hex(),
        "list_diagnostics": data.list_diagnostics(),
        "lists": {
            "free_items": asdict(data.free_items),
            "free_npcs": asdict(data.free_npcs),
            "ethereal": asdict(data.ethereal_items),
        },
    }
    rows: list[dict[str, Any]] = []
    if view == "regions":
        fields = ["rx", "ry", "head", "item_count"]
        rows = [
            asdict(region)
            for region in data.metadata.regions
            if all_slots or region.head or region.item_count
        ]
    else:
        fields = [
            "item_id",
            "slot_membership",
            "npc_slot",
            "shape",
            "frame_low",
            "x",
            "y",
            "z",
            "location_kind",
            "container_id",
            "gump_x",
            "gump_y",
            "status",
            "status_names",
            "quality",
            "npc_num",
            "map_num_raw",
            "next_item",
        ]
        items = (
            (data.get_item(item_id),)
            if item_id is not None
            else data.iter_items(include_free=all_slots)
        )
        for item in items:
            if shape is not None and item.shape != shape:
                continue
            rows.append(
                {
                    **asdict(item),
                    "slot_membership": data.slot_membership(item.item_id),
                    "npc_slot": 0 < item.item_id < NPC_SLOT_COUNT,
                    "location_kind": item.location_kind,
                    "container_id": item.container_id,
                    "gump_x": item.y & 255 if item.container_id is not None else None,
                    "gump_y": item.y >> 8 if item.container_id is not None else None,
                    "status_names": item.status_names(),
                }
            )
    return _render_u8_state_report(
        "ITEMCACH.DAT", metadata, view, rows, fields, output_format
    )


def format_u8_npcdata_report(
    data: U8NpcData,
    *,
    item_cache: U8ItemCache | None = None,
    npc_id: int | None = None,
    map_num: int | None = None,
    all_slots: bool = False,
    output_format: str = "text",
) -> str:
    """Join slot IDs, full sprite frames and equipment; preserve raw stored NPC flags."""
    if npc_id is not None and not 0 <= npc_id < NPC_SLOT_COUNT:
        raise U8NpcDataError("NPCDATA.DAT report: NPC ID must be 0-255")
    if map_num is not None and not 0 <= map_num <= 255:
        raise U8NpcDataError("NPCDATA.DAT report: map must be 0-255")
    if map_num is not None and item_cache is None:
        raise U8NpcDataError("NPCDATA.DAT report: map filter requires ITEMCACH.DAT")
    basis = (
        "all stored slots"
        if all_slots
        else (
            "nonzero cache shapes outside free/null slots"
            if item_cache is not None
            else "nonzero NPC records; activity unknown without ITEMCACH.DAT"
        )
    )
    if npc_id is not None:
        basis = "explicit NPC slot, including unused data"
    metadata = {
        "slot_count": NPC_SLOT_COUNT,
        "paired_item_cache": item_cache is not None,
        "selection_basis": basis,
        "trailing_bytes": data.trailing_bytes.hex(),
        "stats_interpretation": "signed eight-bit chars from decoded NPC.H; raw bytes retained",
        "list_diagnostics": item_cache.list_diagnostics()
        if item_cache is not None
        else [],
    }
    fields = [
        "npc_id",
        "strength",
        "dexterity",
        "intelligence",
        "hitpoints",
        "mana",
        "direction",
        "last_action",
        "frame_hi",
        "animation_step",
        "fall_start_z",
        "alignment_raw",
        "alignment",
        "enemy_alignment",
        "control_flags",
        "unknown_control_bits",
        "state_flags",
        "flag_names",
        "in_use",
        "equipment",
        "unknown_0a",
        "unknown_0c_1a",
        "raw",
        "slot_membership",
        "item_shape",
        "item_frame",
        "item_x",
        "item_y",
        "item_z",
        "item_status",
        "item_quality",
        "item_npc_num",
        "item_map",
        "item_next",
        "equipment_items",
    ]
    rows: list[dict[str, Any]] = []
    npcs = (data.get_npc(npc_id),) if npc_id is not None else data.iter_npcs()
    for npc in npcs:
        item = item_cache.get_item(npc.npc_id) if item_cache is not None else None
        membership = (
            item_cache.slot_membership(npc.npc_id) if item_cache is not None else None
        )
        if npc_id is None and not all_slots:
            if npc.npc_id == 0:
                continue
            if item is not None:
                if not item.shape or membership in {"free_npc", "free_item", "null"}:
                    continue
            elif not any(npc.raw):
                continue
        if map_num is not None and item is not None and item.map_num_raw != map_num:
            continue
        equipment_items = []
        if item_cache is not None:
            for slot, reference in enumerate(npc.equipment):
                equipment_row: dict[str, Any] = {"slot": slot, "item_id": reference}
                if reference == 0:
                    equipment_row["item"] = None
                elif reference >= ITEM_SLOT_COUNT:
                    equipment_row["item"] = None
                    equipment_row["issue"] = "item reference outside 1-9215"
                else:
                    equipped = item_cache.get_item(reference)
                    equipment_row["item"] = {
                        **asdict(equipped),
                        "slot_membership": item_cache.slot_membership(reference),
                        "container_id": equipped.container_id,
                    }
                equipment_items.append(equipment_row)
        row = {
            **asdict(npc),
            "raw": npc.raw.hex(),
            "unknown_0c_1a": npc.unknown_0c_1a.hex(),
            "alignment": npc.alignment,
            "enemy_alignment": npc.enemy_alignment,
            "unknown_control_bits": npc.control_flags & 0xFFE0,
            "flag_names": npc.flag_names(),
            "in_use": npc.in_use,
            "slot_membership": membership,
            "item_shape": item.shape if item is not None else None,
            "item_frame": npc.full_frame(item.frame_low) if item is not None else None,
            "item_x": item.x if item is not None else None,
            "item_y": item.y if item is not None else None,
            "item_z": item.z if item is not None else None,
            "item_status": item.status if item is not None else None,
            "item_quality": item.quality if item is not None else None,
            "item_npc_num": item.npc_num if item is not None else None,
            "item_map": item.map_num_raw if item is not None else None,
            "item_next": item.next_item if item is not None else None,
            "equipment_items": equipment_items,
        }
        rows.append(row)
    return _render_u8_state_report(
        "NPCDATA.DAT", metadata, "npcs", rows, fields, output_format
    )
