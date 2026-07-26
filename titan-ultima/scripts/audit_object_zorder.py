"""
Whole-map audit for unresolved object z-order ties in ``titan u6 map-render
--objects``.

Walks every on-map object (surface + all 5 dungeon levels), reproduces the
same anchor/overflow/layer-tier logic ``titan.u6.cli``'s ``cmd_map_render``
uses to composite ``--objects``, and flags every world coordinate where two
or more objects land on the exact same final tier: a coin-flip tie decided
by LZOBJBLK file order, not a deliberate hierarchy. Among those true ties,
it reports the ones where an opaque "winner" (>= --min-winner-opacity) could
plausibly be burying a "loser" with real content (>= --min-loser-opacity) --
the precise pattern behind every hidden-object bug found by hand in this
project so far (a bed's curtain fabric swallowed by carpet, a sword hidden
by its own wall mount, a cookfire buried under its logs, 30+ doors nearly
erased by their own doorway frame, ...).

Ties where a background/supporting object is correctly covered by
whatever's placed on it are NOT reported -- only same-tier coincidences.
A reported pair is a *candidate*, not a confirmed bug: some are genuine,
some are ambiguous or intentional. Cross-check against a real screenshot
before trusting one, the way every fix landed in this project was.

IMPORTANT: the layering rules below (CARPET_OBJ_N, SECRET_DOOR_OBJ_N,
DOORWAY_OBJ_N, WALL_MOUNT_OBJ_N, MISFLAGGED_FOREGROUND_TILES, and the
band/tier logic in layer()/is_background()) are a hand-kept copy of the
same rules in titan.u6.cli's cmd_map_render. If that function's layering
logic changes, update this file to match or the audit will drift out of
sync with what actually renders.

Usage::

    cd titan-ultima
    python scripts/audit_object_zorder.py -g C:/Ultima/Ultima6
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from titan.u6.look import U6ObjectNames
from titan.u6.object import U6WorldObjects, read_basetile
from titan.u6.tile import U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlags

CARPET_OBJ_N = 303
SECRET_DOOR_OBJ_N = 334
DOORWAY_OBJ_N = 301
BACKGROUND_OBJ_NS = {CARPET_OBJ_N, SECRET_DOOR_OBJ_N, DOORWAY_OBJ_N}

WALL_MOUNT_OBJ_N = 140
SUPPORTING_OBJ_NS = {WALL_MOUNT_OBJ_N}

MISFLAGGED_SUPPORTING_TILES = {758}  # basket

# See titan.u6.cli's cmd_map_render for the full history of each entry.
# obj_n=339 dead body (frames 0-8, tiles 1262-1270; obj_n=338's own frame
# 9, tile 1271 "pile of bones", stays unlisted/plain). obj_n=341 dead
# gargoyle (frames 0-3, tiles 1276-1279) stays unlisted/plain; its rival
# club (545) is listed instead. obj_n=17/18 cloth/leather armour (528/529)
# stay unlisted/plain; their rivals (mug 645, nightshade mushroom 581,
# candle 647) are listed instead. Cleaver/knife (637-639) beat blood
# (1259-1261). Magic bow (565) beats part of a map (1757, dungeon2 loot).
MISFLAGGED_FOREGROUND_TILES = {
    1126, 1127, 1132, 1133,  # cookfire
    1262, 1263, 1264, 1265, 1266, 1267, 1268, 1269, 1270,  # dead body
    545,  # club
    645, 581, 647,  # mug, nightshade mushroom, candle
    637, 638, 639,  # cleaver, knife
    565,  # magic bow
    1240, 1241, 1242, 1247,  # sign plaques that beat their own signpost (1246). Tile 1243
    # ("north") needs a *coordinate*-specific override at (294,407)/(284,410) -- the only
    # 2 of its 11 placements paired with a second, winning plaque on the same post -- not
    # modeled here since this script's layer() only sees obj_n/tnum, not position; see
    # SIGN_NORTH_LOSES_TO_POST_AT in titan.u6.cli's cmd_map_render for the real fix.
}


def build_helpers(tileflags: U6TileFlags):
    def is_background(obj_n: int, cell_tnum: int) -> bool:
        if obj_n in BACKGROUND_OBJ_NS:
            return True
        return cell_tnum < len(tileflags) and tileflags[cell_tnum].is_background

    def layer(obj_n: int, cell_tnum: int) -> int:
        if is_background(obj_n, cell_tnum):
            return 0
        if cell_tnum in MISFLAGGED_FOREGROUND_TILES:
            return 2
        if cell_tnum >= len(tileflags):
            return 1
        tf = tileflags[cell_tnum]
        if tf.is_foreground:
            return 2
        if tf.is_supporting or tf.is_warm or obj_n in SUPPORTING_OBJ_NS or cell_tnum in MISFLAGGED_SUPPORTING_TILES:
            return 0
        return 1

    return is_background, layer


def scan(obj_iter, zone_label, tiles, tileflags, basetile, anim, names, is_background, layer,
         min_winner_opacity, min_loser_opacity):
    opacity_cache: dict[int, float] = {}

    def opacity(tnum: int) -> float:
        if tnum not in opacity_cache:
            arr = tiles.to_array(tnum)
            opacity_cache[tnum] = (arr != 0xFF).sum() / 256.0
        return opacity_cache[tnum]

    by_pos: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    seq = 0
    for obj in obj_iter:
        if not obj.is_on_map:
            continue
        tnum = obj.tile_num(basetile)
        if tnum < 0 or tnum >= tiles.num_tiles:
            continue
        tf = tileflags[tnum] if tnum < len(tileflags) else None
        footprint = tf.double_size_footprint(tnum) if tf else [(0, 0, tnum)]
        for dx, dy, cell_tnum in footprint:
            if cell_tnum < 0 or cell_tnum >= tiles.num_tiles:
                continue
            resolved = anim.resolve_tile(cell_tnum, 0)
            if resolved < 0 or resolved >= tiles.num_tiles:
                continue
            is_anchor = dx == 0 and dy == 0
            by_pos[(obj.x + dx, obj.y + dy, obj.z)].append(dict(
                obj_n=obj.obj_n, frame=obj.frame_n, tnum=resolved,
                is_anchor=is_anchor, opac=opacity(resolved),
                name=names.get_name(resolved), seq=seq,
            ))
            seq += 1

    candidates = []
    for pos, entries in by_pos.items():
        if len(entries) < 2:
            continue

        def real_anchor(e):
            return e["is_anchor"] and not is_background(e["obj_n"], e["tnum"])

        has_real_anchor = any(real_anchor(e) for e in entries)
        tiered = []
        for e in entries:
            band = 0 if (has_real_anchor and not real_anchor(e)) else 1
            tier = band * 3 + layer(e["obj_n"], e["tnum"])
            tiered.append((tier, e))

        maxtier = max(t for t, _ in tiered)
        tied_at_top = [e for t, e in tiered if t == maxtier]
        if len(tied_at_top) < 2:
            continue
        tied_at_top.sort(key=lambda e: -e["seq"])
        winner = tied_at_top[0]
        for loser in tied_at_top[1:]:
            if loser["opac"] >= min_loser_opacity and winner["opac"] >= min_winner_opacity and loser["name"] != winner["name"]:
                candidates.append((zone_label, pos, winner, loser, maxtier))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-g", "--gamedir", required=True, help="U6 game directory")
    parser.add_argument("--min-winner-opacity", type=float, default=0.60)
    parser.add_argument("--min-loser-opacity", type=float, default=0.10)
    parser.add_argument("--limit", type=int, default=200, help="max rows to print (0 = unlimited)")
    parser.add_argument("--dungeons", action="store_true", help="also scan all 5 dungeon levels")
    args = parser.parse_args()

    gamedir = args.gamedir
    world = U6WorldObjects.from_directory(gamedir)
    basetile = read_basetile(f"{gamedir}/BASETILE")
    tileflags = U6TileFlags.from_file(f"{gamedir}/TILEFLAG")
    tiles = U6Tiles.from_directory(gamedir)
    anim = U6AnimData.from_file(f"{gamedir}/ANIMDATA")
    names = U6ObjectNames.from_file(f"{gamedir}/LOOK.LZD")
    is_background, layer = build_helpers(tileflags)

    kwargs = dict(
        tiles=tiles, tileflags=tileflags, basetile=basetile, anim=anim, names=names,
        is_background=is_background, layer=layer,
        min_winner_opacity=args.min_winner_opacity, min_loser_opacity=args.min_loser_opacity,
    )
    candidates = scan(world.iter_surface(), "surface", **kwargs)
    if args.dungeons:
        for level in range(5):
            candidates += scan(world.iter_dungeon(level), f"dungeon{level}", **kwargs)

    candidates.sort(key=lambda c: -c[3]["opac"])
    print(f"total true-tie candidates: {len(candidates)}")
    seen = set()
    shown = 0
    for zone, pos, winner, loser, tier in candidates:
        key = (loser["obj_n"], loser["tnum"], winner["obj_n"], winner["tnum"])
        tag = "" if key not in seen else " [repeat combo]"
        seen.add(key)
        print(
            f"{zone} {pos} tier={tier}  HIDDEN: {loser['name']!r} "
            f"(obj_n={loser['obj_n']} tnum={loser['tnum']} opac={loser['opac']:.2f})  "
            f"BY: {winner['name']!r} (obj_n={winner['obj_n']} tnum={winner['tnum']} opac={winner['opac']:.2f}){tag}"
        )
        shown += 1
        if args.limit and shown >= args.limit:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
