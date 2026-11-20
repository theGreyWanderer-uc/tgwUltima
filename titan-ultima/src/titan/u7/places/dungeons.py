"""Find dungeons and caves on a U7 map.

Method
1. Cover. Mountain-top objects (and Serpent Isle's dark ceiling, shape 394)
   are stamped onto a tile grid: everything under them is underground.
2. Floor. Under the cover the ground is "ethereal void" except where a
   passage or room has been cut, where it is cave floor, stone floor or
   similar (FLOOR_WORDS). Those tiles are the dungeon.
3. Dungeons. Floor tiles within GAP tiles of each other form one dungeon,
   so walls and doors inside it do not break it up.
4. Entrances. Where a dungeon's floor comes within reach of open, walkable
   ground outside the cover.

A dungeon linked only by teleporter or stairs comes out as separate parts;
basements under buildings (no mountain cover) are not found.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import npcs as npc_presence
from .buildings import load_zones
from .geometry import (
    SUPERCHUNK_TILES,
    TILES_PER_CHUNK,
    WORLD_TILES,
    footprint,
    group_near,
    to_rects,
)
from .scan import MapScan
from .signs import SIGN_REACH, sign_tables

# Objects whose name contains one of these roof over the underground.
COVER_WORDS = ("mountain",)
EXTRA_COVER_SHAPES = {"bg": set(), "si": {394}}
COVER_MIN_LIFT = 4
# Ground under the cover that is a cut passage or room, by name.
FLOOR_WORDS = ("floor", "cavern", "tile", "damage causing cell", "serpent highway")
# Ground that is nothing at all.
VOID_WORDS = ("void",)
# Floor tiles this close together belong to the same dungeon.
GAP = 3
# How far from a floor tile open ground may be and still count as its way in.
ENTRANCE_REACH = 2
# Regions that outline open land; their rects must not name caves under it.
LAND_KINDS = ("town", "island")


@dataclass
class DungeonFinds:
    """Result of find_dungeons(); ``records`` keep the finder's JSONL format.

    ``cover`` is the underground mask (one byte per world tile, row-major),
    kept for overview renders; ``unplaced`` names dungeon regions that matched
    no find.
    """

    records: list[dict]
    cover: bytearray = field(default_factory=bytearray)
    unplaced: list[str] = field(default_factory=list)


def find_dungeons(
    scan: MapScan,
    regions: list[dict] | None = None,
    *,
    area: tuple[int, int, int, int] | None = None,
    min_tiles: int = 150,
    gap: int = GAP,
) -> DungeonFinds:
    """Find every dungeon and cave on the scanned map and name it.

    A region names the find within two tiles of its anchor, and any find
    whose centre lies inside one of its rects. Town and island regions cover
    open land and never name a cave.
    """
    game, tfa = scan.game, scan.tfa

    def named(shape, words):
        name = scan.shape_name(shape).lower()
        return any(w in name for w in words)

    cover_shapes = {
        s
        for s in range(150, scan.shape_count)
        if tfa.get(s) is not None and named(s, COVER_WORDS)
    } | EXTRA_COVER_SHAPES[game]

    # 1. Cover, from the fixed objects.
    n_chunks = WORLD_TILES // TILES_PER_CHUNK
    cover = bytearray(WORLD_TILES * WORLD_TILES)
    for obj in scan.fixed:
        if obj.shape in cover_shapes and obj.tz >= COVER_MIN_LIFT:
            x0, y0, x1, y1 = footprint(tfa, obj)
            for y in range(y0, y1 + 1):
                row = y * WORLD_TILES
                cover[row + x0 : row + x1 + 1] = b"\x01" * (x1 - x0 + 1)

    # 2. Ground, from the chunk templates: floor under cover is dungeon;
    #    open ground outside the cover is where entrances lead.
    kind_of: dict[int, str] = {}  # ground shape -> floor | void | open | blocked

    def ground_kind(shape):
        if shape not in kind_of:
            entry = tfa.get(shape)
            if named(shape, VOID_WORDS):
                kind = "void"
            elif named(shape, FLOOR_WORDS):
                kind = "floor"
            elif shape >= 150 or (entry is not None and (entry.is_solid or entry.is_water)):
                kind = "blocked"
            else:
                kind = "open"
            kind_of[shape] = kind
        return kind_of[shape]

    terrain_map, terrains = scan.renderer.terrain_map, scan.renderer.terrains
    floor_shape: dict = {}  # dungeon floor tile -> ground shape
    open_ground: set = set()  # walkable tiles outside the cover
    for cx in range(n_chunks):
        for cy in range(n_chunks):
            template = terrain_map[cx][cy]
            if template >= len(terrains):
                continue
            bx, by = cx * TILES_PER_CHUNK, cy * TILES_PER_CHUNK
            rows = [
                cover[(by + ly) * WORLD_TILES + bx : (by + ly) * WORLD_TILES + bx + 16]
                for ly in range(TILES_PER_CHUNK)
            ]
            for i, (shape, _frame) in enumerate(terrains[template]):
                lx, ly = i % TILES_PER_CHUNK, i // TILES_PER_CHUNK
                kind = ground_kind(shape)
                if rows[ly][lx]:
                    if kind == "floor":
                        floor_shape[(bx + lx, by + ly)] = shape
                elif kind in ("open", "floor"):
                    open_ground.add((bx + lx, by + ly))

    # 3. Dungeons.
    groups = [g for g in group_near(floor_shape, gap) if len(g) >= min_tiles]
    groups.sort(key=lambda g: (min(y for _, y in g), min(x for x, _ in g)))
    label_of = {t: i for i, g in enumerate(groups) for t in g}

    # 4. Entrances: floor tiles within reach of open ground, clustered.
    reach = [
        (dx, dy)
        for dx in range(-ENTRANCE_REACH, ENTRANCE_REACH + 1)
        for dy in range(-ENTRANCE_REACH, ENTRANCE_REACH + 1)
    ]
    entrances_of = []
    for group in groups:
        edge = [
            (x, y)
            for x, y in group
            if any((x + dx, y + dy) in open_ground for dx, dy in reach)
        ]
        spots = []
        for cluster in group_near(edge, 4):
            xs, ys = [x for x, _ in cluster], [y for _, y in cluster]
            spots.append(
                {"tx": sum(xs) // len(xs), "ty": sum(ys) // len(ys), "tiles": len(cluster)}
            )
        entrances_of.append(sorted(spots, key=lambda s: (s["ty"], s["tx"])))

    # Movable objects inside: doors, signs and plaques.
    sign_kinds, texts = sign_tables(scan.usecode, game)
    doors_in = Counter()
    signs_of = [[] for _ in groups]

    def owner_near(tx, ty, reach_tiles):
        for d in range(reach_tiles + 1):
            ring = Counter(
                label_of[(tx + dx, ty + dy)]
                for dx in range(-d, d + 1)
                for dy in range(-d, d + 1)
                if max(abs(dx), abs(dy)) == d and (tx + dx, ty + dy) in label_of
            )
            if ring:
                return ring.most_common(1)[0][0]
        return None

    for obj in scan.ireg or ():
        entry = tfa.get(obj.shape)
        if entry is not None and entry.is_door:
            owner = owner_near(obj.tx, obj.ty, 1)
            if owner is not None:
                doors_in[owner] += 1
        elif obj.shape in sign_kinds:
            text = texts.get(obj.shape, {}).get(obj.quality, (None, False))[0]
            owner = owner_near(obj.tx, obj.ty, SIGN_REACH) if text else None
            if owner is not None:
                signs_of[owner].append(
                    {"tx": obj.tx, "ty": obj.ty, "tz": obj.tz, "text": text,
                     "kind": sign_kinds[obj.shape], "quality": obj.quality}
                )  # fmt: skip

    # Names from the place data's dungeon regions.
    region_of: dict = {}
    unplaced = []
    for region in regions or ():
        if region.get("kind") in LAND_KINDS:
            continue
        hit = False
        if region.get("anchor"):
            owner = owner_near(*region["anchor"], 2)
            if owner is not None:
                region_of.setdefault(owner, region)
                hit = True
        for x0, y0, x1, y1 in region.get("rects") or []:
            for i, group in enumerate(groups):
                cx = sum(x for x, _ in group) / len(group)
                cy = sum(y for _, y in group) / len(group)
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    region_of.setdefault(i, region)
                    hit = True
        if not hit and region.get("kind") == "dungeon":
            unplaced.append(region["name"])

    # Who is here when a new game begins (see npcs.py).
    npcs_of = npc_presence.presence(
        scan.npcs, lambda tx, ty: owner_near(tx, ty, 1), len(groups)
    )
    zones = load_zones(game)

    records = []
    for i, group in enumerate(groups):
        xs, ys = [x for x, _ in group], [y for _, y in group]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        if area and (bx1 < area[0] or bx0 > area[2] or by1 < area[1] or by0 > area[3]):
            continue
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        floors = Counter(scan.shape_name(floor_shape[t]).lower() for t in group)
        region = region_of.get(i)
        records.append(
            {
                "id": f"{scan.game_id}-m{scan.map_num}-d-{bx0:04d}-{by0:04d}",
                "game": scan.game_id,
                "map": scan.map_num,
                "kind": "dungeon",
                "name": region["name"] if region else None,
                "name_source": (
                    ("review" if region.get("source") == "review" else "official")
                    if region
                    else None
                ),
                "region": region["id"] if region else None,
                "bbox": {"tx0": bx0, "ty0": by0, "tx1": bx1, "ty1": by1},
                "size": [bx1 - bx0 + 1, by1 - by0 + 1],
                "center": [round(cx, 1), round(cy, 1)],
                # a floor tile, usable as an anchor in the place data
                "anchor": list(min(group, key=lambda t: abs(t[0] - cx) + abs(t[1] - cy))),
                "tile_count": len(group),
                "rects": [list(r) for r in to_rects(group)],
                "entrances": entrances_of[i],
                "floor": dict(floors.most_common()),
                "doors": doors_in[i],
                "signs": sorted(signs_of[i], key=lambda s: (s["ty"], s["tx"])),
                # Start of the game only: positions and schedules both change
                # during play.
                "npcs_at_start": npcs_of[i],
                "npcs_basis": npc_presence.BASIS,
                "zones": [
                    {"id": zid, "name": zname}
                    for zid, zname, rects in zones
                    if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects)
                ],
                "chunks": {
                    "cx0": bx0 // 16, "cy0": by0 // 16, "cx1": bx1 // 16, "cy1": by1 // 16,
                },  # fmt: skip
                "superchunks": sorted(
                    {
                        (y // SUPERCHUNK_TILES) * 12 + x // SUPERCHUNK_TILES
                        for x in range(bx0, bx1 + 256, 256)
                        for y in range(by0, by1 + 256, 256)
                        if x <= bx1 + 255
                        and y <= by1 + 255
                        and x < WORLD_TILES
                        and y < WORLD_TILES
                    }
                ),
            }
        )
    return DungeonFinds(records=records, cover=cover, unplaced=unplaced)
