"""Find buildings on a U7 map by their roofs.

Method
1. Roofs. Roof objects (pitched "... roof" shapes, and "floor" shapes at
   lift >= 5, which are flat roofs and upper storeys) are stamped onto a tile
   grid using their TFA footprint. Touching roof tiles form a blob.
2. Rooms. Under each blob, ground-floor walls, windows and doors are
   barriers. The open tiles between them form rooms; open tiles within a few
   tiles of the blob's outer edge are the eaves (outside the walls) and are
   not rooms.
3. Buildings. Rooms joined by a door are one building. Rooms with no door
   between them (a party wall) are different buildings, so a blob of touching
   roofs splits into its houses. Walls and eaves go to the nearest building.

The footprint is the ROOF extent, eaves included. Roofless structures
(ruins, courtyards, open towers) are not found; the place data draws those by
hand.
"""

from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from . import npcs as npc_presence
from .geometry import (
    N4,
    SUPERCHUNK_TILES,
    TILES_PER_CHUNK,
    footprint,
    group_tiles,
    to_rects,
)
from .scan import MapScan
from .signs import NAME_MAX_WORDS, SIGN_REACH, STREET_WORDS, sign_tables

# Pitched roofs are picked by name ("... roof"). These adjust that per game.
# BG leaves its two thatch roofs unnamed; SI names the same shapes.
EXTRA_ROOF_SHAPES = {"bg": {161: "thatch roof", 162: "thatch roof"}, "si": {}}
# SI 394 is a bare "roof", 8x8, mostly at lift 14-15 in huge numbers: taken to
# be the ceiling over caves/dungeons, not a building roof.
EXCLUDED_ROOF_SHAPES = {"bg": set(), "si": {394}}
FLAT = "flat (floor)"
# Lowest lift a "floor" must sit at to count as a flat roof / upper storey.
UPPER_LIFT = 5
# Ground-floor shapes whose name contains one of these block movement between
# rooms. Doors (TFA door flag) are barriers too, and are what joins rooms.
BARRIER_WORDS = ("wall", "fortress", "window", "bars", "portcullis", "fireplace")


def load_zones(game: str) -> list[tuple]:
    """[(zone id, zone name, [rect tuples])] from titan's zone profile."""
    path = Path(__file__).resolve().parent.parent / "zone_profiles" / f"{game}_zones.json"
    if not path.is_file():
        return []
    zones = json.loads(path.read_text(encoding="utf-8")).get("zones", [])
    return [
        (
            z.get("id"),
            z.get("name", ""),
            [(r["tx0"], r["ty0"], r["tx1"], r["ty1"]) for r in z.get("rects", [])],
        )
        for z in zones
    ]


def roof_shape_table(game, tfa, names, count, flat_roofs) -> dict[int, str]:
    """{shape: kind} for every shape treated as a roof."""
    table = dict(EXTRA_ROOF_SHAPES.get(game, {}))
    for shape in range(150, count):
        if tfa.get(shape) is None:
            continue
        name = ((names.get(shape) if names else "") or "").strip().lower()
        if "roof" in name:
            table[shape] = name
        elif flat_roofs and name == "floor":
            table[shape] = FLAT
    for shape in EXCLUDED_ROOF_SHAPES.get(game, ()):
        table.pop(shape, None)
    return table


def door_reach(tfa, obj) -> set:
    """Tiles a door touches: its footprint plus the tiles on its four sides."""
    x0, y0, x1, y1 = footprint(tfa, obj)
    tiles = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    return tiles | {(x + dx, y + dy) for x, y in tiles for dx, dy in N4}


def split_blob(blob, barrier, ground_doors, tfa, eave_depth, min_room):
    """Split one roof blob into buildings.

    Returns (parts, rooms_per_part, eaves): each part is a list of tiles.
    """
    blob_set = set(blob)
    open_tiles = blob_set - barrier

    # Eaves: open tiles within eave_depth steps of the blob's outer edge.
    eaves = {
        t
        for t in open_tiles
        if any((t[0] + dx, t[1] + dy) not in blob_set for dx, dy in N4)
    }
    frontier = set(eaves)
    for _ in range(eave_depth - 1):
        frontier = {
            (x + dx, y + dy) for x, y in frontier for dx, dy in N4
        } & open_tiles - eaves
        eaves |= frontier

    rooms = [r for r in group_tiles(open_tiles - eaves) if len(r) >= min_room]
    if len(rooms) < 2:
        return [blob], [len(rooms)], eaves
    room_of = {t: i for i, r in enumerate(rooms) for t in r}

    # Rooms joined by a door are the same building.
    parent = list(range(len(rooms)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    has_door = set()
    for obj in ground_doors:
        touched = {room_of[t] for t in door_reach(tfa, obj) if t in room_of}
        has_door |= touched
        first, *rest = touched or [None]
        for other in rest:
            parent[find(other)] = find(first)

    # A group of rooms with no door at all (stairwells, closets, walkways
    # over a street) is not a building: it is absorbed by its neighbours.
    roots = sorted({find(i) for i in has_door})
    if len(roots) < 2:
        return [blob], [len(rooms)], eaves
    rooms = [r for i, r in enumerate(rooms) if find(i) in roots]
    part_of_room = [roots.index(find(room_of[r[0]])) for r in rooms]

    rooms_per_part = [0] * len(roots)
    owner = {}
    for i, room in enumerate(rooms):
        part = part_of_room[i]
        rooms_per_part[part] += 1
        for t in room:
            owner[t] = part

    # Walls, eaves and closets go to the nearest building.
    queue = deque(owner)
    while queue:
        x, y = queue.popleft()
        for dx, dy in N4:
            nxt = (x + dx, y + dy)
            if nxt in blob_set and nxt not in owner:
                owner[nxt] = owner[(x, y)]
                queue.append(nxt)
    parts = [[] for _ in roots]
    for t in blob:
        parts[owner[t]].append(t)
    return parts, rooms_per_part, eaves


@dataclass
class BuildingFinds:
    """Result of find_buildings().

    ``records`` keep the finder's long-standing JSONL record format. The other
    fields are what review tools and renders need besides the records.
    """

    records: list[dict]
    places_other: list[dict] = field(default_factory=list)
    street_signs: list[dict] = field(default_factory=list)
    loose_signs: list[dict] = field(default_factory=list)
    roof_lift: dict = field(default_factory=dict)
    all_eaves: set = field(default_factory=set)


def find_buildings(
    scan: MapScan,
    places: list[dict] | None = None,
    *,
    area: tuple[int, int, int, int] | None = None,
    min_tiles: int = 16,
    flat_roofs: bool = True,
    split: bool = True,
    eave_depth: int = 3,
    min_room: int = 9,
) -> BuildingFinds:
    """Find every building on the scanned map and name it.

    ``places`` are place-data entries (id, name, anchor, type, ...): each one
    names the building containing its anchor tile, a printed-map name before a
    reviewed one. ``area`` (inclusive tiles) keeps only buildings touching it.
    """
    game, tfa, names = scan.game, scan.tfa, scan.names
    roofs = roof_shape_table(game, tfa, names, scan.shape_count, flat_roofs)
    barrier_shapes = {
        s
        for s in range(150, scan.shape_count)
        if tfa.get(s) is not None
        and any(w in scan.shape_name(s).lower() for w in BARRIER_WORDS)
    }

    # 1. Read the map: roofs, ground-floor barriers and doors.
    roof_lift: dict = {}  # tile -> highest roof lift
    roof_objs, doors, sign_objs = [], [], []
    barrier: set = set()
    sign_kinds, texts = sign_tables(scan.usecode, game)
    texts.update({shape: {} for shape in sign_kinds if shape not in texts})

    def take(obj, source):
        if obj.shape in texts:
            sign_objs.append(obj)
        entry = tfa.get(obj.shape)
        is_door = entry is not None and entry.is_door
        if is_door:
            doors.append((obj, source))
        if obj.tz < UPPER_LIFT and (is_door or obj.shape in barrier_shapes):
            x0, y0, x1, y1 = footprint(tfa, obj)
            barrier.update(
                (x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
            )
        kind = roofs.get(obj.shape)
        if kind is None or (kind == FLAT and obj.tz < UPPER_LIFT):
            return
        x0, y0, x1, y1 = footprint(tfa, obj)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if roof_lift.get((x, y), -1) < obj.tz:
                    roof_lift[(x, y)] = obj.tz
        roof_objs.append(obj)

    for obj in scan.fixed:
        take(obj, "ifix")
    for obj in scan.template_objects():
        take(obj, "chunk")
    # Doors are mostly movable objects, so the starting world counts too.
    for obj in scan.ireg or ():
        take(obj, "ireg")
    ground_doors = [obj for obj, _ in doors if obj.tz < UPPER_LIFT]

    # 2. Blobs of touching roof, then split each into buildings.
    blobs = [g for g in group_tiles(roof_lift) if len(g) >= min_tiles]
    doors_by_tile: dict = {}
    for obj in ground_doors:
        x0, y0, x1, y1 = footprint(tfa, obj)
        for x in range(x0 - 1, x1 + 2):
            for y in range(y0 - 1, y1 + 2):
                doors_by_tile.setdefault((x, y), []).append(obj)

    buildings = []  # (tiles, blob index, parts in blob, rooms)
    all_eaves: set = set()
    for b, blob in enumerate(blobs):
        if not split:
            buildings.append((blob, b, 1, None))
            continue
        near = {id(o): o for t in blob for o in doors_by_tile.get(t, ())}
        parts, rooms, eaves = split_blob(
            blob, barrier, list(near.values()), tfa, eave_depth, min_room
        )
        all_eaves |= eaves
        for part, n_rooms in zip(parts, rooms):
            buildings.append((part, b, len(parts), n_rooms))
    buildings.sort(key=lambda b: (min(y for _, y in b[0]), min(x for x, _ in b[0])))
    label_of = {tile: i for i, b in enumerate(buildings) for tile in b[0]}

    shapes_of = [Counter() for _ in buildings]
    for obj in roof_objs:
        i = label_of.get((obj.tx, obj.ty))
        if i is not None:
            shapes_of[i][obj.shape] += 1

    # A door belongs to every building it touches. It is an outside door when
    # it also touches the eaves or open ground beyond the roof.
    doors_of = [[] for _ in buildings]
    for obj, source in doors:
        reach = door_reach(tfa, obj)
        hits = {label_of[t] for t in reach if t in label_of}
        if obj.tz >= UPPER_LIFT:
            kind = "upper"
        elif any(t in all_eaves or t not in roof_lift for t in reach - barrier):
            kind = "outside"
        else:
            kind = "inside"
        for i in hits:
            doors_of[i].append(
                {
                    "tx": obj.tx,
                    "ty": obj.ty,
                    "tz": obj.tz,
                    "shape": obj.shape,
                    "frame": obj.frame,
                    "name": scan.shape_name(obj.shape),
                    "kind": kind,
                    "source": source,
                }
            )

    # A sign names the nearest building within SIGN_REACH tiles. Street
    # signs are kept apart: they name the road, not a building.
    signs_of = [[] for _ in buildings]
    street_signs, loose_signs = [], []
    for obj in sign_objs:
        text, runic = texts[obj.shape].get(obj.quality, (None, False))
        sign = {
            "tx": obj.tx,
            "ty": obj.ty,
            "tz": obj.tz,
            "shape": obj.shape,
            "frame": obj.frame,
            "quality": obj.quality,
            "text": text,
            "runic": runic,
            "kind": sign_kinds[obj.shape],
            # Outside: open ground or eaves within two tiles. Name signs
            # hang outside; exhibit and room plaques are indoors.
            "outside": any(
                (obj.tx + dx, obj.ty + dy) not in roof_lift
                or (obj.tx + dx, obj.ty + dy) in all_eaves
                for dx in range(-2, 3)
                for dy in range(-2, 3)
            ),
        }
        if text and text.split()[-1].lower() in STREET_WORDS:
            street_signs.append(sign)
            continue
        owner = None
        for d in range(SIGN_REACH + 1):
            ring = Counter(
                label_of[(obj.tx + dx, obj.ty + dy)]
                for dx in range(-d, d + 1)
                for dy in range(-d, d + 1)
                if max(abs(dx), abs(dy)) == d
                and (obj.tx + dx, obj.ty + dy) in label_of
            )
            if ring:
                owner = ring.most_common(1)[0][0]
                break
        if owner is None:
            loose_signs.append(sign)
        else:
            signs_of[owner].append(sign)

    # Places: each goes to the building that contains its anchor.
    places_of = [[] for _ in buildings]
    places_other = []
    for place in places or ():
        anchor = place.get("anchor")
        owner = label_of.get(tuple(anchor)) if anchor else None
        if owner is not None and place.get("type", "building") == "building":
            places_of[owner].append(place)
        else:
            status = (
                "dropped" if place.get("dropped")
                else "not placed" if not anchor
                else "area" if place.get("type") == "area"
                # a roofless building the finder cannot see, drawn by hand
                else "footprint" if place.get("rects")
                else "no building at anchor"
            )
            places_other.append({"status": status, **place})
    # A printed-map name always beats one typed in during review.
    for found in places_of:
        found.sort(key=lambda p: p.get("source") == "review")

    # Who is here when a new game begins (see npcs.py).
    npcs_of = npc_presence.presence(
        scan.npcs, lambda tx, ty: label_of.get((tx, ty)), len(buildings)
    )
    zones = load_zones(game)

    # 3. One record per building.
    records, seen_ids = [], Counter()
    for i, (group, blob_index, blob_parts, n_rooms) in enumerate(buildings):
        xs = [x for x, _ in group]
        ys = [y for _, y in group]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        if area and (bx1 < area[0] or bx0 > area[2] or by1 < area[1] or by0 > area[3]):
            continue
        lifts = Counter(roof_lift[t] for t in group)
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        kinds = {"flat" if roofs[s] == FLAT else "pitched" for s in shapes_of[i]}
        wall_tiles = sum(1 for t in group if t in barrier)
        flags = []
        if not doors_of[i]:
            flags.append("no_doors")
        if not wall_tiles:
            flags.append("no_ground_walls")
        if n_rooms == 0:
            flags.append("no_rooms")
        # high: walls, a room and a door. medium: walls and a room but no
        # door object (huts with an open doorway, sealed rooms). low: no
        # walls or no room under the roof (wagons, canopies, wall walks,
        # ceilings over special locations).
        if not wall_tiles or n_rooms == 0:
            confidence = "low"
        elif not doors_of[i]:
            confidence = "medium"
        else:
            confidence = "high"
        base_id = f"{scan.game_id}-m{scan.map_num}-{bx0:04d}-{by0:04d}"
        seen_ids[base_id] += 1
        suffix = "" if seen_ids[base_id] == 1 else f"-{seen_ids[base_id]}"
        # The name is an outside sign or plaque: a short one before a long
        # one (announcements run long), then the one nearest an outside door.
        out_doors = [d for d in doors_of[i] if d["kind"] == "outside"]

        def name_rank(s, out_doors=out_doors):
            near = min(
                (abs(s["tx"] - d["tx"]) + abs(s["ty"] - d["ty"]) for d in out_doors),
                default=0,
            )
            return (len(s["text"].split()) > NAME_MAX_WORDS, near)

        candidates = sorted(
            (s for s in signs_of[i] if s["text"] and s["outside"]), key=name_rank
        ) or sorted(
            # Failing that, a sign (never a plaque) hung indoors.
            (s for s in signs_of[i] if s["text"] and s["kind"] == "sign"),
            key=name_rank,
        )
        sign_names = [s["text"] for s in candidates]
        name_source = candidates[0]["kind"] if candidates else None
        records.append(
            {
                "id": base_id + suffix,
                "game": scan.game_id,
                "map": scan.map_num,
                # The official name leads; the sign reading stays alongside.
                "name": (
                    places_of[i][0]["name"]
                    if places_of[i]
                    else sign_names[0] if sign_names else None
                ),
                "name_source": (
                    ("review" if places_of[i][0].get("source") == "review" else "official")
                    if places_of[i]
                    else name_source
                ),
                "places": [
                    {k: p.get(k) for k in ("id", "town", "number", "name", "keeper")}
                    for p in places_of[i]
                ],
                "sign_name": sign_names[0] if sign_names else None,
                # Start of the game only: positions and schedules both change
                # during play.
                "npcs_at_start": npcs_of[i],
                "npcs_basis": npc_presence.BASIS,
                "signs": sorted(signs_of[i], key=lambda s: (s["ty"], s["tx"])),
                "bbox": {"tx0": bx0, "ty0": by0, "tx1": bx1, "ty1": by1},
                "size": [bx1 - bx0 + 1, by1 - by0 + 1],
                "center": [round(cx, 1), round(cy, 1)],
                "tile_count": len(group),
                "rects": [list(r) for r in to_rects(group)],
                "roof_kind": "mixed" if len(kinds) > 1 else "".join(kinds) or "none",
                "roof_lifts": {str(k): v for k, v in sorted(lifts.items())},
                "max_roof_lift": max(lifts),
                "roof_shapes": [
                    {"shape": s, "name": roofs[s], "count": n}
                    for s, n in shapes_of[i].most_common()
                ],
                "rooms": n_rooms,
                "wall_tiles": wall_tiles,
                "blob": blob_index,
                "blob_parts": blob_parts,
                "confidence": confidence,
                "flags": flags,
                "doors": sorted(doors_of[i], key=lambda d: (d["ty"], d["tx"])),
                "zones": [
                    {"id": zid, "name": zname}
                    for zid, zname, rects in zones
                    if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects)
                ],
                "chunks": {
                    "cx0": bx0 // TILES_PER_CHUNK,
                    "cy0": by0 // TILES_PER_CHUNK,
                    "cx1": bx1 // TILES_PER_CHUNK,
                    "cy1": by1 // TILES_PER_CHUNK,
                },
                "superchunks": sorted(
                    {
                        (y // SUPERCHUNK_TILES) * 12 + x // SUPERCHUNK_TILES
                        for x in (bx0, bx1)
                        for y in (by0, by1)
                    }
                ),
            }
        )
    return BuildingFinds(
        records=records,
        places_other=places_other,
        street_signs=street_signs,
        loose_signs=loose_signs,
        roof_lift=roof_lift,
        all_eaves=all_eaves,
    )
