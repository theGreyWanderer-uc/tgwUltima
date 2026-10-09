"""Stored U8 inventory identities and map-local containment, independent of live cache slots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from titan.u8.container_gump import resolve_u8_shape_container_gumps
from titan.u8.map_items import U8MapItems
from titan.u8.typeflag import U8TypeFlags

U8InventoryId = int | str


def parse_u8_inventory_id(value: str) -> U8InventoryId:
    """Accept a live cache ID or KIND:MAP:RECORD, preserving zero-based stored indices."""
    value = value.strip()
    try:
        if ":" not in value:
            number = int(value, 16 if value.lower().startswith("0x") else 10)
            if not 1 <= number <= 9215:
                raise ValueError
            return number
        kind, map_text, record_text = value.upper().split(":")
        map_id, record_index = int(map_text), int(record_text)
        if (
            kind not in {"FIXED", "NONFIXED"}
            or not 1 <= map_id <= 255
            or record_index < 0
        ):
            raise ValueError
        return f"{kind}:{map_id}:{record_index}"
    except ValueError as error:
        raise ValueError(
            "U8 container browser: use cache ID 1–9215 or FIXED:MAP:RECORD / NONFIXED:MAP:RECORD (map 1–255, record >= 0)"
        ) from error


def u8_inventory_file_stem(number: U8InventoryId) -> str:
    """Use safe unique filenames; preserve existing four-digit live-cache filenames."""
    if isinstance(number, int):
        return f"{number:04d}"
    parsed = parse_u8_inventory_id(number)
    if isinstance(parsed, int):
        return f"{parsed:04d}"
    kind, map_text, record_text = parsed.split(":")
    return f"{kind.lower()}_m{int(map_text):03d}_r{int(record_text):06d}"


def u8_inventory_sort_key(number: U8InventoryId) -> tuple[int, int, int, int]:
    """List live inventories first, then stored inventories by map, archive and record."""
    if isinstance(number, int):
        return (0, 0, 0, number)
    kind, map_text, record_text = number.split(":")
    return (1, int(map_text), int(kind == "NONFIXED"), int(record_text))


def u8_inventory_identity_label(row: dict[str, Any]) -> str:
    """Show the authoritative ID namespace at every item/menu/report entry."""
    if row.get("archive_kind", "cache") == "cache":
        return f"Cache {row['item_id']}"
    return f"Map {row['map_id']} · {row['archive_kind'].upper()} record {row['record_index']}"


@dataclass
class U8StoredInventories:
    """Relevant stored containers, descendants and rejected contained records only."""

    items: dict[U8InventoryId, dict[str, Any]]
    children: dict[U8InventoryId, list[U8InventoryId]]
    containers: list[U8InventoryId]
    map_ids: list[int]
    diagnostics: list[str]


def build_u8_stored_inventories(
    archives: list[U8MapItems],
    *,
    active_map: int,
    properties: dict[int, U8TypeFlags.ShapeEntry],
    names: dict[int, str],
) -> U8StoredInventories:
    """Scan maps 1–255 except the live map; resolve each archive's own depth hierarchy."""
    result = U8StoredInventories({}, {}, [], [], [])
    maps = set()
    for archive in archives:
        for map_id in range(1, 256):
            if map_id == active_map:
                continue
            records = archive.get_map(map_id)
            if records:
                maps.add(map_id)
            parents = {
                item.parent_record_index
                for item in records
                if item.parent_record_index is not None
            }
            container_indices = {
                item.record_index
                for item in records
                if (
                    properties.get(item.shape) is not None
                    and properties[item.shape].family == 6
                )
                or item.record_index in parents
            }
            relevant = {
                item.record_index for item in records if item.contained
            } | container_indices
            for item in records:
                if item.record_index not in relevant:
                    continue
                key = f"{archive.kind.upper()}:{map_id}:{item.record_index}"
                parent = (
                    f"{archive.kind.upper()}:{map_id}:{item.parent_record_index}"
                    if item.parent_record_index is not None
                    else None
                )
                root = (
                    f"{archive.kind.upper()}:{map_id}:{item.root_record_index}"
                    if item.root_record_index is not None
                    else None
                )
                props = properties.get(item.shape)
                family = props.family if props else None
                row = asdict(item)
                row.update(
                    item_id=key,
                    cache_id=None,
                    identity=key,
                    slot_membership="stored_record",
                    frame_low=item.frame,
                    container_id=parent,
                    root_item_id=root,
                    location_kind=item.location_kind,
                    gump_x=item.gump_x,
                    gump_y=item.gump_y,
                    equipment_slot=item.equipment_slot,
                    shape_name=names.get(item.shape, ""),
                    npc_name="",
                    npc_label="",
                    label_source="",
                    is_npc=False,
                    family=family,
                    family_name=props.family_name() if props else "unknown",
                    quantity=item.quality
                    if family in {2, 9}
                    else 1
                    if family is not None
                    else None,
                    quality_meaning={
                        1: "quality",
                        2: "quantity",
                        6: "serialized_contents",
                        9: "quantity",
                    }.get(family or 0, "raw"),
                    contents_head=None,
                    flag_names=item.status_names(),
                    diagnostics=list(item.diagnostics),
                    owner_npc_id=None,
                    owner_name="",
                    child_count=0,
                    gump_previews=[
                        asdict(preview)
                        for preview in resolve_u8_shape_container_gumps(
                            item.shape, family=family
                        )
                    ],
                )
                result.items[key] = row
                if parent is not None:
                    result.children.setdefault(parent, []).append(key)
                if item.record_index in container_indices:
                    result.containers.append(key)
                if item.diagnostics:
                    result.diagnostics.extend(
                        f"{key}: {issue}" for issue in item.diagnostics
                    )
    for container_key in result.containers:
        result.items[container_key]["child_count"] = len(
            result.children.get(container_key, [])
        )
    result.map_ids = sorted(maps)
    result.containers.sort(key=u8_inventory_sort_key)
    return result
