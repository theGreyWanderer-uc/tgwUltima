"""One document describing every named place on a U7 map.

``build_places_document`` reads the player's own game files (roofs, floors,
doors, signs, NPC start positions) and adds the bundled place data (names,
town outlines, hand-drawn areas). Nothing from the game files is shipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from titan._version import TITAN_VERSION

from . import npcs as npc_presence
from .buildings import BuildingFinds, find_buildings
from .data import load_place_data
from .dungeons import DungeonFinds, find_dungeons
from .geometry import in_rects
from .scan import MapScan

FORMAT = "titan-u7-places"
VERSION = 1
COORDINATES = (
    "Inclusive world tiles (0-3071). bbox and rects are [x0, y0, x1, y1] with "
    "both corners inside; center is [x, y]."
)


def _bbox(rects) -> list[int]:
    return [
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    ]


def _center(rects) -> list[float]:
    area = sum((r[2] - r[0] + 1) * (r[3] - r[1] + 1) for r in rects)
    cx = sum((r[0] + r[2]) / 2 * (r[2] - r[0] + 1) * (r[3] - r[1] + 1) for r in rects)
    cy = sum((r[1] + r[3]) / 2 * (r[2] - r[0] + 1) * (r[3] - r[1] + 1) for r in rects)
    return [round(cx / area, 1), round(cy / area, 1)]


def _npcs(entries: list[dict]) -> list[dict]:
    return [
        {k: n[k] for k in ("num", "name", "starts_here", "start", "sleeps_here",
                           "works_here", "schedule_here")}
        for n in entries
    ]  # fmt: skip


class _Towns:
    """Town outlines from the place data, and which town a point is in."""

    def __init__(self, regions: list[dict]):
        self.towns = [r for r in regions if r.get("kind") == "town" and r.get("rects")]

    def at(self, x: float, y: float) -> str | None:
        for town in self.towns:
            if in_rects(x, y, town["rects"]):
                return town["name"]
        return None

    def records(self) -> list[dict]:
        return [
            {"id": t["id"], "name": t["name"], "rects": t["rects"]} for t in self.towns
        ]


def _building(rec: dict, places_by_id: dict, towns: _Towns) -> dict:
    b = rec["bbox"]
    legend = []
    for p in rec["places"]:
        entry = {k: v for k, v in p.items() if v is not None}
        rects = places_by_id.get(p["id"], {}).get("rects")
        if rects:  # a building shared by places, each with its own part
            entry["rects"] = rects
        legend.append(entry)
    town = next((p["town"] for p in rec["places"] if p.get("town")), None)
    return {
        "id": rec["id"],
        "name": rec["name"],
        "name_source": rec["name_source"],
        "town": town or towns.at(*rec["center"]),
        "detected": True,
        "places": legend,
        "sign_name": rec["sign_name"],
        "bbox": [b["tx0"], b["ty0"], b["tx1"], b["ty1"]],
        "center": rec["center"],
        "tile_count": rec["tile_count"],
        "rects": rec["rects"],
        "roof": rec["roof_kind"],
        "rooms": rec["rooms"],
        "confidence": rec["confidence"],
        "flags": rec["flags"],
        "doors": [
            {k: d[k] for k in ("tx", "ty", "tz", "kind", "name")} for d in rec["doors"]
        ],
        "signs": [
            {k: s[k] for k in ("tx", "ty", "tz", "kind", "text", "runic", "outside")}
            for s in rec["signs"]
        ],
        "npcs_at_start": _npcs(rec["npcs_at_start"]),
        "zones": rec["zones"],
    }


def _drawn_buildings(finds: BuildingFinds, scan: MapScan, towns: _Towns) -> list[dict]:
    """Roofless buildings the finder cannot see, drawn by hand in the place data."""
    drawn = [p for p in finds.places_other if p["status"] == "footprint"]

    def owner_at(tx, ty):
        return next(
            (i for i, p in enumerate(drawn) if in_rects(tx, ty, p["rects"])), None
        )

    npcs_of = npc_presence.presence(scan.npcs, owner_at, len(drawn))
    out = []
    for p, npcs in zip(drawn, npcs_of):
        rects = [list(r) for r in p["rects"]]
        center = _center(rects)
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "name_source": "review" if p.get("source") == "review" else "official",
                "town": p.get("town") or towns.at(*center),
                "detected": False,
                "places": [
                    {
                        k: p[k]
                        for k in ("id", "town", "number", "name", "keeper")
                        if p.get(k) is not None
                    }
                ],
                "sign_name": None,
                "bbox": _bbox(rects),
                "center": center,
                "tile_count": sum((r[2] - r[0] + 1) * (r[3] - r[1] + 1) for r in rects),
                "rects": rects,
                "roof": "none",
                "rooms": None,
                "confidence": None,
                "flags": ["hand_drawn"],
                "doors": [],
                "signs": [],
                "npcs_at_start": _npcs(npcs),
                "zones": [],
            }
        )
    return out


def _dungeon(rec: dict, towns: _Towns) -> dict:
    b = rec["bbox"]
    return {
        "id": rec["id"],
        "name": rec["name"],
        "name_source": rec["name_source"],
        "town": towns.at(*rec["center"]),
        "bbox": [b["tx0"], b["ty0"], b["tx1"], b["ty1"]],
        "center": rec["center"],
        "tile_count": rec["tile_count"],
        "rects": rec["rects"],
        "entrances": rec["entrances"],
        "floor": rec["floor"],
        "door_count": rec["doors"],
        "signs": [
            {k: s[k] for k in ("tx", "ty", "tz", "kind", "text")} for s in rec["signs"]
        ],
        "npcs_at_start": _npcs(rec["npcs_at_start"]),
        "zones": rec["zones"],
    }


def _areas(finds: BuildingFinds, towns: _Towns) -> list[dict]:
    out = []
    for p in finds.places_other:
        if p["status"] != "area":
            continue
        rects = [list(r) for r in p.get("rects") or []]
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "town": p.get("town") or towns.at(*p["anchor"]),
                "anchor": p["anchor"],
                "rects": rects,
            }
        )
    return out


def assemble_document(
    scan: MapScan,
    data: dict,
    buildings: BuildingFinds,
    dungeons: DungeonFinds,
) -> dict:
    """The export document from finder results and the place data."""
    towns = _Towns(data.get("regions", []))
    places_by_id = {p["id"]: p for p in data.get("places", [])}
    building_records = [_building(r, places_by_id, towns) for r in buildings.records]
    building_records += _drawn_buildings(buildings, scan, towns)
    dungeon_records = [_dungeon(r, towns) for r in dungeons.records]
    areas = _areas(buildings, towns)
    return {
        "format": FORMAT,
        "version": VERSION,
        "game": data.get("game") or f"u7-{scan.game}",
        "map": scan.map_num,
        "generator": f"titan-ultima {TITAN_VERSION}",
        "coordinates": COORDINATES,
        "npcs_basis": npc_presence.BASIS,
        "counts": {
            "towns": len(towns.towns),
            "buildings": len(building_records),
            "buildings_named": sum(1 for b in building_records if b["name"]),
            "dungeons": len(dungeon_records),
            "dungeons_named": sum(1 for d in dungeon_records if d["name"]),
            "areas": len(areas),
        },
        "towns": towns.records(),
        "buildings": building_records,
        "dungeons": dungeon_records,
        "areas": areas,
    }


def build_places_document(
    static_dir: str | None = None, game: str = "bg", map_num: int = 0
) -> dict:
    """Find and name every building, dungeon, area and town on a U7 map."""
    data = load_place_data(game)
    if data.get("map", 0) != map_num:
        raise ValueError(
            f"Place data covers map {data.get('map', 0)}, not map {map_num}."
        )
    scan = MapScan.load(static_dir, game, map_num)
    buildings = find_buildings(scan, data["places"])
    dungeons = find_dungeons(scan, data["regions"])
    return assemble_document(scan, data, buildings, dungeons)


def write_places_document(
    document: dict, path: str | Path, *, pretty: bool = False
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(document, indent=2, ensure_ascii=False)
        if pretty
        else json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    )
    path.write_text(text + "\n", encoding="utf-8")
    return path
