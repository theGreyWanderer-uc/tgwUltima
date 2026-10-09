"""Decode U8 egg / trigger search fields from native EGG.C, MONEGG.C and UPROCESS.C."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from titan.u8.shape_names import load_u8_shape_names

from titan.u8.world_search import (
    U8WorldSearchFilters,
    U8WorldSearchSession,
    iter_u8_world_search_rows,
    match_u8_world_search_row,
)

U8_EGG_KINDS = (
    "usecode",
    "teleport",
    "destination",
    "teleport_other",
    "monster",
    "glob",
    "ambient",
)
U8_MONSTER_CHANCES = (5, 10, 20, 35, 50, 65, 80, 100)


@dataclass(frozen=True)
class U8EggSearchFilters:
    """Filter U8 usecode classes, not U7 function numbers; destination IDs are map-local."""

    kinds: tuple[str, ...] = ()
    usecode_class: int | None = None
    destination_map: int | None = None
    destination_id: int | None = None

    def __post_init__(self) -> None:
        if any(kind not in U8_EGG_KINDS for kind in self.kinds):
            raise ValueError("U8 egg search: type must be " + ", ".join(U8_EGG_KINDS))
        if self.usecode_class is not None and not 0 <= self.usecode_class <= 65535:
            raise ValueError("U8 egg search: usecode class must be 0–65535")
        if any(
            value is not None and not 0 <= value <= 255
            for value in (self.destination_map, self.destination_id)
        ):
            raise ValueError("U8 egg search: destination map/ID must be 0–255")


def describe_u8_egg_trigger(row: dict[str, Any]) -> dict[str, Any] | None:
    """Decode verified definition fields; native save records do not carry an egg fired-state bit."""
    family = row["family"]
    kind = {3: "glob", 4: "usecode", 7: "monster"}.get(family)
    if family == 8:
        kind = {0: "teleport", 1: "destination"}.get(row["frame"], "teleport_other")
    if kind is None and row["shape_flags_raw"] & 0x80:
        kind = "ambient"
    if kind is None:
        return None
    result = dict(row)
    result["diagnostics"] = list(row["diagnostics"])
    result.update(
        trigger_kind=kind,
        usecode_class=None,
        usecode_name="",
        usecode_label_source="",
        hatch_event=None,
        range_x_steps=None,
        range_y_steps=None,
        range_x_units=None,
        range_y_units=None,
        trigger_bounds=None,
        z_tolerance=None,
        destination_map=None,
        destination_id=None,
        destination_matches=[],
        teleport_fire_raw=None,
        monster_shape=None,
        monster_count=None,
        monster_id=None,
        monster_activity=None,
        probability_index=None,
        probability_percent=None,
        trigger_state="not captured by these item records",
    )
    if row["archive_kind"] == "glob":
        result["diagnostics"].append(
            "GLOB child has no serialized quality/npc/map bytes; trigger payload unresolved"
        )
        return result
    q, npc, map_raw = row["quality"], row["npc_num"], row["map_num_raw"]
    if kind in {"usecode", "teleport"}:
        rx, ry = npc >> 4, npc & 15
        result.update(
            range_x_steps=rx,
            range_y_steps=ry,
            range_x_units=rx * 32,
            range_y_units=ry * 32,
            z_tolerance=48,
            hatch_event=7 if kind == "usecode" else None,
        )
        if row["world_x"] is not None:
            x, y, z = row["world_x"], row["world_y"], row["world_z"]
            result["trigger_bounds"] = [
                x - rx * 32,
                y - ry * 32,
                x + rx * 32,
                y + ry * 32,
                z - 48,
                z + 48,
            ]
    if kind == "usecode":
        result["usecode_class"] = (q + 0x47F) & 65535
        if q + 0x47F > 65535:
            result["diagnostics"].append("Native 16-bit usecode class wraps past 65535")
    elif kind == "teleport":
        result.update(
            destination_map=map_raw, destination_id=q & 255, teleport_fire_raw=q >> 8
        )
    elif kind == "destination":
        result["destination_id"] = q & 255
    elif kind == "monster":
        probability = q >> 11
        result.update(
            monster_shape=q & 0x7FF,
            monster_shape_name=load_u8_shape_names().get(q & 0x7FF, ""),
            monster_count=npc & 7,
            monster_id=map_raw >> 3,
            monster_activity=map_raw & 7,
            probability_index=probability,
            probability_percent=U8_MONSTER_CHANCES[probability]
            if probability < 8
            else None,
        )
        if probability >= 8:
            result["diagnostics"].append(
                "Monster probability index exceeds native eight-entry chance table"
            )
        result["monster_trigger"] = (
            "explicit usecode hatch; no native proximity EggHatcher"
        )
    elif kind == "ambient":
        unit = (
            row["cache_id"] + 1024
            if row["is_npc"] and not row["status"] & 0x80
            else row["shape"]
        )
        result.update(usecode_class=unit, ambient_events=[15, 16])
        result["trigger_state"] = (
            "SI_NOISY candidate; event handlers not verified against EUSECODE"
        )
    if result["usecode_class"] is not None:
        result["usecode_name"] = load_u8_shape_names().get(result["usecode_class"], "")
        result["usecode_label_source"] = (
            "bundled_english_usecode_class" if result["usecode_name"] else ""
        )
    return result


def query_u8_egg_triggers(
    session: U8WorldSearchSession,
    world_filters: U8WorldSearchFilters = U8WorldSearchFilters(),
    egg_filters: U8EggSearchFilters = U8EggSearchFilters(),
) -> list[dict[str, Any]]:
    """Search verified egg families plus SI_NOISY candidates, and resolve captured teleport targets."""
    if not session.maps.library.properties:
        raise ValueError(
            "U8 egg search: matching TYPEFLAG.DAT is required to identify egg families"
        )
    triggers = [
        result
        for row in iter_u8_world_search_rows(
            session, expand_globs=world_filters.expand_globs
        )
        if (result := describe_u8_egg_trigger(row)) is not None
    ]
    targets: dict[tuple[int, int], list[str]] = {}
    for row in triggers:
        if (
            row["trigger_kind"] == "destination"
            and row["world_x"] is not None
            and row["destination_id"] is not None
        ):
            targets.setdefault((row["map_id"], row["destination_id"]), []).append(
                row["identity"]
            )
    selected = []
    for row in triggers:
        if row["trigger_kind"] == "teleport":
            row["destination_matches"] = targets.get(
                (row["destination_map"], row["destination_id"]), []
            )
            if len(row["destination_matches"]) != 1:
                row["diagnostics"].append(
                    f"Teleport destination has {len(row['destination_matches'])} captured matches"
                )
        if not match_u8_world_search_row(row, world_filters):
            continue
        if egg_filters.kinds and row["trigger_kind"] not in egg_filters.kinds:
            continue
        if (
            egg_filters.usecode_class is not None
            and row["usecode_class"] != egg_filters.usecode_class
        ):
            continue
        if (
            egg_filters.destination_id is not None
            and row["destination_id"] != egg_filters.destination_id
        ):
            continue
        if (
            egg_filters.destination_map is not None
            and row["destination_map"] != egg_filters.destination_map
        ):
            continue
        selected.append(row)
    return selected
