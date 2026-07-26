"""
Ultima 6: The False Prophet — CLI sub-app.

Registered as ``titan u6 <command>`` in the root CLI.

Most commands accept ``-g/--gamedir`` (a directory containing the
standard, fixed U6 filenames: MASKTYPE.VGA, MAPTILES.VGA, OBJTILES.VGA,
U6PAL, ANIMDATA, MAP, CHUNKS) rather than per-file paths, since -- unlike
U7/U8 -- a real U6 install has no path variability to account for.
Falls back to ``[u6.game] base`` in ``titan.toml`` if ``--gamedir`` is
omitted.
"""

from __future__ import annotations

__all__ = ["u6_app"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._config import get_config
from titan.u6.actor import U6Actors
from titan.u6.book import U6Books
from titan.u6.converse import format_instructions, disassemble
from titan.u6.flags import (
    U6FlagsError,
    compare_flags,
    read_talk_flags,
    set_gargish_flag,
    set_quest_flag,
    set_talk_flag,
)
from titan.u6.font import U6Fonts
from titan.u6.gamestate import U6GameState
from titan.u6.lib import U6Library
from titan.u6.look import U6ObjectNames
from titan.u6.lzw import U6Lzw
from titan.u6.map import U6Chunks, U6Map, render_tile_grid
from titan.u6.object import U6WorldObjects, read_basetile
from titan.u6.palette import U6Palette
from titan.u6.schedule import U6Schedules
from titan.u6.tile import U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlags

# ============================================================================
# Typer sub-app
# ============================================================================

u6_app = typer.Typer(
    name="u6",
    help="Ultima 6: The False Prophet — tile, map, library, and data commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


# ============================================================================
# Shared helpers
# ============================================================================

def _u6_gamedir(explicit: Optional[str]) -> Optional[str]:
    """Resolve a U6 game directory: explicit arg, else ``[u6.game] base`` in titan.toml."""
    if explicit:
        return explicit
    return get_config().get("u6", {}).get("game", {}).get("base")


def _require_gamedir(explicit: Optional[str]) -> str:
    gamedir = _u6_gamedir(explicit)
    if not gamedir or not os.path.isdir(gamedir):
        print(
            "ERROR: No U6 game directory found. Pass --gamedir, or set "
            '[u6.game] base = "..." in titan.toml.',
            file=sys.stderr,
        )
        raise SystemExit(1)
    return gamedir


def _resolve_palette(gamedir: str, explicit: Optional[str]) -> str:
    path = explicit or os.path.join(gamedir, "U6PAL")
    if not os.path.isfile(path):
        print(f"ERROR: Palette not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    return path


def _parse_tile_num(value: str) -> int:
    return int(value, 16) if value.lower().startswith("0x") else int(value)


def _load_objlist_from_source(source: str) -> bytes:
    """Load objlist bytes from either a real save's SAVEGAME/ folder or a fresh gamedir, auto-detected."""
    if os.path.isfile(os.path.join(source, "OBJLIST")):
        return U6WorldObjects.from_savegame(source).objlist_tail
    if os.path.isfile(os.path.join(source, "LZDNGBLK")):
        return U6WorldObjects.from_directory(source).objlist_tail
    print(
        f"ERROR: {source} is neither a save's SAVEGAME folder (needs OBJLIST) "
        "nor a fresh gamedir (needs LZDNGBLK)",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _parse_region(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        print(f"ERROR: --region must be 'x,y,width,height', got: {value}", file=sys.stderr)
        raise SystemExit(1)
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        print(f"ERROR: --region values must be integers: {value}", file=sys.stderr)
        raise SystemExit(1)
    return x, y, w, h


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — LZW
# ============================================================================

def cmd_lzw_decompress(args: SimpleNamespace) -> int:
    """Decompress a single U6 LZW file to raw bytes."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        data = f.read()
    was_compressed = U6Lzw.is_valid(data)
    decoded = U6Lzw.decompress(data)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{Path(filepath).name}.bin")
    with open(out_path, "wb") as f:
        f.write(decoded)

    label = "LZW-compressed" if was_compressed else "raw (not LZW)"
    print(f"{label}: {len(data)} -> {len(decoded)} bytes -> {out_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — LIBRARY (lib_16 / lib_32)
# ============================================================================

def cmd_lib_list(args: SimpleNamespace) -> int:
    """List a U6 library file's items (CONVERSE.A/B, PORTRAIT.*, etc.)."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    lib = U6Library.from_file(filepath, entry_size=args.entry_size, has_size_header=args.size_header)

    print(f"{filepath} — lib_{args.entry_size * 8}, {lib.num_items} items")
    print(f"{'Idx':>5}  {'Offset':>8}  {'Flag':>4}  {'Size':>7}  {'Decoded':>7}")
    print("-" * 42)
    for i in range(lib.num_items):
        item = lib.items[i]
        if item.size == 0:
            print(f"{i:>5}  {'-':>8}  {'-':>4}  {'-':>7}  {'(empty)':>7}")
            continue
        try:
            decoded_len = len(lib.get_item(i))
        except Exception:
            decoded_len = -1
        print(f"{i:>5}  {item.offset:>8}  0x{item.flag:02X}  {item.size:>7}  {decoded_len:>7}")
    return 0


def cmd_lib_extract(args: SimpleNamespace) -> int:
    """Extract one item from a U6 library file (decompressed automatically)."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    lib = U6Library.from_file(filepath, entry_size=args.entry_size, has_size_header=args.size_header)
    if args.item < 0 or args.item >= lib.num_items:
        print(f"ERROR: Item {args.item} out of range (0..{lib.num_items - 1})", file=sys.stderr)
        return 1

    data = lib.get_item(args.item)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{Path(filepath).name}_{args.item:04d}.bin")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Extracted item {args.item}: {len(data)} bytes -> {out_path}")
    return 0


def cmd_lib_extract_all(args: SimpleNamespace) -> int:
    """Extract every non-empty item from a U6 library file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    lib = U6Library.from_file(filepath, entry_size=args.entry_size, has_size_header=args.size_header)
    outdir = args.output or f"{Path(filepath).name}_items"
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).name
    extracted = 0
    for i in range(lib.num_items):
        if lib.items[i].size == 0:
            continue
        data = lib.get_item(i)
        out_path = os.path.join(outdir, f"{i:04d}_{base}.bin")
        with open(out_path, "wb") as f:
            f.write(data)
        extracted += 1

    print(f"Extracted {extracted}/{lib.num_items} item(s) -> {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — TILEFLAG
# ============================================================================

def cmd_tileflag_dump(args: SimpleNamespace) -> int:
    """Parse TILEFLAG and dump all entries as a readable table."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    entries = U6TileFlags.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "tileflag_dump.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"TILEFLAG — {len(entries)} entries\n")
        f.write("=" * 100 + "\n\n")
        header = (f"{'Tile':>5}  {'Terrain':>7}  {'Flags':>5}  {'Weight':>6}  {'Extra':>5}  "
                  f"{'Article':<7} {'Notes'}\n")
        f.write(header)
        f.write("-" * 100 + "\n")
        for e in entries:
            if e.terrain == 0 and e.flags == 0 and e.weight == 0 and e.extra == 0:
                continue
            notes = []
            if e.is_wet:
                notes.append("wet")
            if e.is_impassable:
                notes.append("impassable")
            if e.is_wall:
                notes.append("wall")
            if e.is_damaging:
                notes.append("damaging")
            if e.is_double:
                notes.append("double")
            if e.is_supporting:
                notes.append("supporting")
            if e.is_breakthrough:
                notes.append("breakthrough")
            f.write(f"{e.tile_num:>5}  0x{e.terrain:04X}  0x{e.flags:03X}  {e.weight:>6}  "
                     f"0x{e.extra:03X}  {e.article_word or '-':<7} {','.join(notes)}\n")

    print(f"Dumped {len(entries)} entries -> {out_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — PALETTE
# ============================================================================

def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export U6PAL as a PNG swatch image + text dump."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    pal = U6Palette.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    base = Path(filepath).name

    img_path = os.path.join(outdir, f"{base}_palette.png")
    pal.to_pil_image(swatch_size=16).save(img_path)
    print(f"Palette swatch saved: {img_path}  (256 colors, 16x16 grid)")

    txt_path = os.path.join(outdir, f"{base}_palette.txt")
    with open(txt_path, "w") as f:
        f.write(f"# Palette from {filepath}\n")
        f.write("# Index  R    G    B    Hex\n")
        for i, (r, g, b) in enumerate(pal.colors):
            f.write(f"{i:3d}    {r:3d}  {g:3d}  {b:3d}  #{r:02X}{g:02X}{b:02X}\n")
    print(f"Palette text dump: {txt_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — TILE
# ============================================================================

def cmd_tile_export(args: SimpleNamespace) -> int:
    """Export one U6 tile to PNG."""
    gamedir = _require_gamedir(args.gamedir)
    palette_path = _resolve_palette(gamedir, args.palette)

    tiles = U6Tiles.from_directory(gamedir)
    pal = U6Palette.from_file(palette_path)

    tile_num = args.tile_num
    if tile_num < 0 or tile_num >= tiles.num_tiles:
        print(f"ERROR: Tile {tile_num} out of range (0..{tiles.num_tiles - 1})", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"tile_{tile_num:04d}.png")
    tiles.to_pil_image(tile_num, pal, transparent=True).save(out_path)
    print(f"Exported tile {tile_num} -> {out_path}")
    return 0


def cmd_tile_export_all(args: SimpleNamespace) -> int:
    """Batch-export a range of U6 tiles to PNG."""
    gamedir = _require_gamedir(args.gamedir)
    palette_path = _resolve_palette(gamedir, args.palette)

    tiles = U6Tiles.from_directory(gamedir)
    pal = U6Palette.from_file(palette_path)

    start = args.start
    end = args.end if args.end is not None else tiles.num_tiles - 1
    if start < 0 or end >= tiles.num_tiles or start > end:
        print(f"ERROR: Invalid range {start}..{end} (valid: 0..{tiles.num_tiles - 1})", file=sys.stderr)
        return 1

    outdir = args.output or "tiles_png"
    os.makedirs(outdir, exist_ok=True)
    exported = 0
    for i in range(start, end + 1):
        tiles.to_pil_image(i, pal, transparent=True).save(os.path.join(outdir, f"tile_{i:04d}.png"))
        exported += 1

    print(f"Exported {exported} tiles ({start}..{end}) -> {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MAP
# ============================================================================

def cmd_map_render(args: SimpleNamespace) -> int:
    """Render the U6 surface world or a dungeon level to PNG."""
    gamedir = _require_gamedir(args.gamedir)
    palette_path = _resolve_palette(gamedir, args.palette)

    map_path = os.path.join(gamedir, "MAP")
    chunks_path = os.path.join(gamedir, "CHUNKS")
    animdata_path = os.path.join(gamedir, "ANIMDATA")
    for path in (map_path, chunks_path, animdata_path):
        if not os.path.isfile(path):
            print(f"ERROR: Required file not found: {path}", file=sys.stderr)
            return 1

    if args.dungeon is None and args.region is None and not args.full:
        print(
            "ERROR: Specify --region x,y,w,h, --dungeon N (0-4), or --full "
            "(--full renders the entire 1024x1024-tile surface -- a very "
            "large image).",
            file=sys.stderr,
        )
        return 1

    if args.objects:
        for name in ("LZOBJBLK", "LZDNGBLK", "BASETILE", "TILEFLAG"):
            if not os.path.isfile(os.path.join(gamedir, name)):
                print(f"ERROR: Required file not found for --objects: {os.path.join(gamedir, name)}", file=sys.stderr)
                return 1

    chunks = U6Chunks.from_file(chunks_path)
    world_map = U6Map.from_file(map_path)
    tiles = U6Tiles.from_directory(gamedir)
    pal = U6Palette.from_file(palette_path)
    anim = U6AnimData.from_file(animdata_path)

    if args.dungeon is not None:
        if args.dungeon < 0 or args.dungeon > 4:
            print("ERROR: --dungeon must be 0-4", file=sys.stderr)
            return 1
        grid = world_map.build_dungeon_grid(args.dungeon, chunks)
        default_name = f"dungeon_{args.dungeon}.png"
    else:
        grid = world_map.build_surface_grid(chunks)
        default_name = "surface.png"

    region = _parse_region(args.region) if args.region else None

    print(f"Rendering {'dungeon ' + str(args.dungeon) if args.dungeon is not None else 'surface'}"
          f"{f' region {region}' if region else ' (full)'} ...")
    img = render_tile_grid(grid, tiles, pal, region=region, animdata=anim, tick=args.tick)

    if args.objects:
        img = img.convert("RGBA")
        world = U6WorldObjects.from_directory(gamedir)
        basetile = read_basetile(os.path.join(gamedir, "BASETILE"))
        tileflags = U6TileFlags.from_file(os.path.join(gamedir, "TILEFLAG"))
        obj_iter = world.iter_dungeon(args.dungeon) if args.dungeon is not None else world.iter_surface()

        ox, oy = (region[0], region[1]) if region else (0, 0)
        rh, rw = grid.shape[:2] if region is None else (region[3], region[2])

        # Carpet's own TILEFLAG data only marks 2 of its 18 frames (the
        # heavily-repeated fill piece) is_background -- the many border/
        # corner frames aren't flagged at all, even though they're the same
        # floor-covering object. Found from a room where a table+candle
        # pair anchored on an unflagged corner/edge carpet frame was still
        # getting covered by it. Since every carpet frame is unambiguously
        # floor, not furniture, obj_n is a more reliable background signal
        # here than the per-tile flag alone.
        CARPET_OBJ_N = 303

        # A secret door (obj_n=334) is drawn 100% opaque and wall-colored
        # by design -- its whole purpose is to be indistinguishable from a
        # normal wall segment -- but TILEFLAG never marks it is_background.
        # Found from a "picture" object anchored on the exact same tile as
        # a secret door (a picture hung to visually mark/disguise the door,
        # a common decorating trick): both plain-tier anchors tied, and the
        # fully-opaque secret door always won, making the picture
        # completely invisible.
        SECRET_DOOR_OBJ_N = 334

        # A doorway (obj_n=301) is the threshold frame that a door,
        # portcullis, or other fixture sits inside -- it's is_foreground
        # like whatever fills it, so the two tie and file order decides,
        # arbitrarily, which one wins. A 1990s U6 level-design reference
        # (it-he.org's "List of Useful Objects") gives the authoritative
        # order directly: "Place the doorway first, and then put the door
        # on top." A whole-map audit for same-tier ties found 30+ doorways
        # winning that coin flip instead, each nearly erasing its own door
        # (12-30% opaque door losing to a 74-97% opaque doorway).
        DOORWAY_OBJ_N = 301
        BACKGROUND_OBJ_NS = {CARPET_OBJ_N, SECRET_DOOR_OBJ_N, DOORWAY_OBJ_N}

        # A wall mount (obj_n=140) is a rack that a decorative sword or
        # shield hangs on, the same "things get placed on top of this"
        # role as is_supporting furniture, but TILEFLAG doesn't flag it.
        # Found from a decorative sword anchored on the exact same tile as
        # its wall mount, tied at the plain tier and losing to it.
        WALL_MOUNT_OBJ_N = 140
        SUPPORTING_OBJ_NS = {WALL_MOUNT_OBJ_N}

        # A basket (obj_n=191, frame 0 = tile 758 specifically -- the same
        # obj_n's other frames are "open crate"/"crate"/"small jug"/"milk
        # bottle", so this can't be an obj_n-wide rule) is a container: its
        # contents should show on top of it, the same "things get placed on
        # top of this" role as is_supporting furniture. Confirmed against a
        # real screenshot showing baskets (yellow) and a bunch of grapes
        # (purple) as distinct, both-visible objects -- not the grapes
        # nested invisibly inside the basket, which is what six placements
        # sharing a basket's coordinate with a grapes anchor were rendering.
        MISFLAGGED_SUPPORTING_TILES = {758}

        # Sign plaque tile 1243 ("north") appears at 11 coordinates on the map; at 9 of them
        # it's the only plaque on its post and must beat the post like any other (handled by
        # the natural plain tier beating the post's natural plain tier... except it doesn't --
        # see below). At exactly 2 of them (294,407 and 284,410) it's paired with a *second*,
        # winning plaque ("south", tile 1241, in MISFLAGGED_FOREGROUND_TILES above) sharing
        # the same post. Demoting tile 1243 globally would fix those 2 but break the other 9,
        # so this is a (world_x, world_y) coordinate override, not a tile-number one: verified
        # from the raw LZOBJBLK object order that 1243 has a *higher* seq than the post at
        # these exact 2 spots, so it was independently beating the post and painting its own
        # full-height plank, indistinguishable in size from 1241's, producing an unwanted
        # double-wide plank (confirmed against a real screenshot: the game shows one plank
        # with the post visible only in the gaps around it, not two side-by-side planks).
        SIGN_NORTH_LOSES_TO_POST_AT = {(294, 407), (284, 410)}

        # Ground clutter found in a dungeon loot pile, none of it flagged
        # anything at all (TILEFLAG is entirely False on every one of these
        # tiles), so ties there are decided by file-order coincidence.
        # First attempt demoted the *losing* side (pile of bones, dead
        # gargoyle, blood, armor) to background/tier 0. That's wrong: a
        # dead body must still win over blood *and* a pile of bones, a club
        # must win over a dead gargoyle, and small items (mug, mushroom,
        # candle) must win over a dropped piece of armor -- but those same
        # "loser" tiles also need to win over supporting furniture they're
        # sitting on/in (confirmed: a leather armor piece hidden under a
        # table, and a pile of bones hidden under an altar's overflow cell,
        # both regressed by that demotion, since table/altar's own
        # is_supporting tier is *also* 0). Promoting the *winning* side to
        # foreground instead avoids that: it beats its specific plain-tier
        # rival while leaving the loser at its natural plain tier, which
        # already beats is_supporting furniture on its own.
        #
        # obj_n=339 is "dead body" for frames 0-8 (tiles 1262-1270, listed
        # in full since obj_n=338 also aliases the same tiles for its own
        # frames 3-5) and "pile of bones" only for frame 9 (tile 1271, left
        # unlisted -- it now stays at its natural plain tier). obj_n=341 is
        # "dead gargoyle" for frames 0-3 (tiles 1276-1279, left unlisted)
        # but "giant rat" for frames 4-5 -- its confirmed rival is a club
        # (tile 545), listed instead. obj_n=17/18 (cloth/leather armour,
        # tiles 528/529, left unlisted) are LOOK.LZD's first frame in each
        # range; their confirmed rivals are a mug (645), a nightshade
        # mushroom (581), and a candle (647), listed instead.
        MISFLAGGED_FOREGROUND_TILES = {
            1126, 1127, 1132, 1133,  # cookfire
            1262, 1263, 1264, 1265, 1266, 1267, 1268, 1269, 1270,  # dead body
            545,  # club
            645, 581, 647,  # mug, nightshade mushroom, candle
            637, 638, 639,  # cleaver, knife (confirmed rival: blood, tile 1259-1261)
            565,  # magic bow (confirmed rival: part of a map, tile 1757, dungeon2 loot pile)
            # obj_n=332's directional sign plaques need to beat their own signpost (frame 6,
            # tile 1246, also unflagged) -- 26 placements on the map share a plaque+post
            # coordinate, and the post was winning file order, completely erasing the plaque
            # instead of the post merely peeking through the plaque's transparent corners.
            # First attempt demoted the post to supporting instead, which fixed the 24
            # single-plaque placements but broke the 2 that pair TWO plaques on one post
            # (294,407 and 284,410) even worse than before: with the post no longer competing
            # at all, the *losing* plaque (1243, "north") was left free to independently beat
            # the post (it already did, per its actual seq order -- see
            # SIGN_NORTH_LOSES_TO_POST_AT below) and paint its own full-height plank next to
            # 1241's, producing an unwanted double-wide plank (confirmed against a real
            # screenshot: the game shows one plank with the post visible only in the gaps
            # around it, not two side-by-side planks). Promoting only the 4 plaque frames that
            # are never a same-post "loser" (1240, 1241, 1242, and 1247 -- obj_n=332 frame 7,
            # a plain-horizontal variant used at 4 more real coordinates, found the same way:
            # its seq is lower than the post's at all 4) leaves the post's tier alone -- each
            # of those beats it on its own regardless.
            1240, 1241, 1242, 1247,
        }

        def is_background(obj_n: int, cell_tnum: int) -> bool:
            if obj_n in BACKGROUND_OBJ_NS:
                return True
            return cell_tnum < len(tileflags) and tileflags[cell_tnum].is_background

        def layer(obj_n: int, cell_tnum: int) -> int:
            """0 = supporting furniture, a heat/light source, or a background fill (drawn first, e.g. a table, a forge fire, or a rug's floor tile), 1 = plain, 2 = foreground/toptile (drawn last, e.g. a curtain)."""
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

        drawn = 0
        seq = 0
        draws: list[tuple[int, bool, int, int, int, int]] = []
        for obj in obj_iter:
            if not obj.is_on_map:
                continue
            if not (ox <= obj.x < ox + rw and oy <= obj.y < oy + rh):
                continue
            tnum = obj.tile_num(basetile)
            if tnum < 0 or tnum >= tiles.num_tiles:
                continue
            footprint = tileflags[tnum].double_size_footprint(tnum) if tnum < len(tileflags) else [(0, 0, tnum)]
            for dx, dy, cell_tnum in footprint:
                if cell_tnum < 0 or cell_tnum >= tiles.num_tiles:
                    continue
                # Object cells can themselves be animated placeholders (a
                # drawbridge crank/chain, or a clock's second frame), the
                # same mechanism already used for terrain -- found from a
                # crank and chain that rendered as fully transparent
                # because ANIMDATA lists them as placeholders (tiles 1009
                # and 1020) whose real content lives at a different,
                # tick-selected tile.
                cell_tnum = anim.resolve_tile(cell_tnum, args.tick)
                if cell_tnum < 0 or cell_tnum >= tiles.num_tiles:
                    continue
                px = (obj.x + dx - ox) * 16
                py = (obj.y + dy - oy) * 16
                draws.append((seq, dx == 0 and dy == 0, px, py, cell_tnum, obj.obj_n))
                seq += 1
            drawn += 1

        # Objects placed at the same coordinate, or whose footprints
        # overflow onto one, can claim overlapping cells. Two rules settle
        # who wins, cheapest/strongest first:
        #
        # 1. Any object's own anchor cell (its real (x, y) placement) beats
        #    every *other* object's mere secondary/overflow cell landing on
        #    the same spot, regardless of flags -- confirmed against a real
        #    screenshot where a hammer (anchored on its own tile) stayed
        #    visible under a forge hood's overhanging secondary cell, even
        #    though that cell is flagged is_foreground. This pass doesn't
        #    apply to an anchor that's background (a rug's floor tile,
        #    individually anchored per carpet piece): a background tile
        #    shouldn't out-rank a neighbor's overflow just for being
        #    "anchored" there, since being background already means it's
        #    meant to sit under everything nearby, not claim priority over
        #    it -- found from a bed whose is_foreground curtain-fabric
        #    overflow cells were getting swallowed by an underlying
        #    carpet's individually-anchored floor tiles.
        # 2. Within each of those two bands (the overflow cells competing
        #    among themselves, and the anchor cells competing among
        #    themselves -- e.g. two objects double-sized from the identical
        #    anchor coordinate, like a bed and its curtain), TILEFLAG's own
        #    flags settle it the same way: is_supporting furniture (a
        #    table, per its docstring -- "other objects can be placed on
        #    top of this one"), is_warm (a heat/light source, e.g. a
        #    forge's fire), or background (a rug's floor tile) sits under
        #    whatever's placed on/near it, and is_foreground ("toptile")
        #    sits over everything else. Applying rule 2 *within* the
        #    overflow band too (not just collapsing it to a single flat
        #    tier) matters here: a forge hood's overflow cell is_foreground
        #    and must still stay above the fire's overflow cell beneath it,
        #    even though a hammer's anchor beats them both. The is_warm
        #    half of this rule was found from two other forges where a
        #    fire and a pair of pliers are anchored at the *identical*
        #    coordinate (not an overflow at all): with neither flagged
        #    supporting/foreground, both fell into the plain tier, and the
        #    fire (92% opaque) happened to win the file-order tiebreak and
        #    completely hid the pliers (21% opaque) underneath it.
        #
        # A stable sort by (band, sub-tier, original file order) applies
        # both rules per pixel position while preserving file order within
        # a tier.
        #
        # Independently corroborated after the fact by a 1990s U6 level-
        # design reference (it-he.org's "List of Useful Objects"): a canopy
        # bed's curtain piece is catalogued as a "4 Poster overlay" meant to
        # be placed on top of a plain bed, and its door-building instructions
        # say to place the doorway first and "put the door on top" -- both
        # match the layering this code already produces.
        by_pos: dict[tuple[int, int], list[tuple[int, bool, int, int, int, int]]] = {}
        for d in draws:
            by_pos.setdefault((d[2], d[3]), []).append(d)

        tiered: list[tuple[int, int, int, int, int]] = []
        for group in by_pos.values():
            def real_anchor(entry: tuple[int, bool, int, int, int, int]) -> bool:
                _, is_anchor, _, _, cell_tnum, obj_n = entry
                return is_anchor and not is_background(obj_n, cell_tnum)

            has_real_anchor = any(real_anchor(d) for d in group)
            for entry in group:
                seqn, _is_anchor, px, py, cell_tnum, obj_n = entry
                band = 0 if (has_real_anchor and not real_anchor(entry)) else 1
                world_xy = (px // 16 + ox, py // 16 + oy)
                if cell_tnum == 1243 and world_xy in SIGN_NORTH_LOSES_TO_POST_AT:
                    tier = 0
                else:
                    tier = band * 3 + layer(obj_n, cell_tnum)
                tiered.append((tier, seqn, px, py, cell_tnum))

        tiered.sort(key=lambda d: (d[0], d[1]))
        for _tier, _seq, px, py, cell_tnum in tiered:
            sprite = tiles.to_pil_image(cell_tnum, pal, transparent=True)
            img.alpha_composite(sprite, (px, py))
        print(f"  overlaid {drawn} object(s)")

    out_path = args.output or default_name
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Saved: {out_path}  ({img.width}x{img.height})")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — OBJECTS / ACTORS
# ============================================================================

def cmd_object_list(args: SimpleNamespace) -> int:
    """List world objects in a surface block or dungeon level."""
    gamedir = _require_gamedir(args.gamedir)
    for name in ("LZOBJBLK", "LZDNGBLK"):
        if not os.path.isfile(os.path.join(gamedir, name)):
            print(f"ERROR: Required file not found: {os.path.join(gamedir, name)}", file=sys.stderr)
            return 1

    world = U6WorldObjects.from_directory(gamedir)

    if args.dungeon is not None:
        if args.dungeon < 0 or args.dungeon > 4:
            print("ERROR: --dungeon must be 0-4", file=sys.stderr)
            return 1
        objs = world.dungeon_objects[args.dungeon]
        label = f"dungeon {args.dungeon}"
    elif args.block is not None:
        if args.block < 0 or args.block >= len(world.surface_objects):
            print(f"ERROR: --block must be 0-{len(world.surface_objects) - 1}", file=sys.stderr)
            return 1
        objs = world.surface_objects[args.block]
        label = f"surface block {args.block}"
    else:
        objs = list(world.iter_surface())
        label = "all surface blocks"

    print(f"{label}: {len(objs)} top-level object(s)")
    print(f"{'X':>5} {'Y':>5} {'Z':>2}  {'ObjN':>5} {'Frm':>3}  {'Qty':>4} {'Qual':>4}  {'Flags':<16} Contains")
    print("-" * 78)
    for o in objs[:args.limit]:
        flags = []
        if o.is_ok_to_take:
            flags.append("take")
        if o.is_invisible:
            flags.append("invis")
        if o.is_temporary:
            flags.append("temp")
        if o.is_lit:
            flags.append("lit")
        print(f"{o.x:>5} {o.y:>5} {o.z:>2}  {o.obj_n:>5} {o.frame_n:>3}  {o.qty:>4} {o.quality:>4}  "
              f"{','.join(flags) or '-':<16} {len(o.contains)}")
    if len(objs) > args.limit:
        print(f"... ({len(objs) - args.limit} more not shown; increase --limit to see more)")
    return 0


def cmd_egg_list(args: SimpleNamespace) -> int:
    """List every egg (object spawner) in a surface block or dungeon level, with what it spawns."""
    gamedir = _require_gamedir(args.gamedir)
    for name in ("LZOBJBLK", "LZDNGBLK", "BASETILE", "LOOK.LZD"):
        if not os.path.isfile(os.path.join(gamedir, name)):
            print(f"ERROR: Required file not found: {os.path.join(gamedir, name)}", file=sys.stderr)
            return 1

    world = U6WorldObjects.from_directory(gamedir)
    basetile = read_basetile(os.path.join(gamedir, "BASETILE"))
    names = U6ObjectNames.from_file(os.path.join(gamedir, "LOOK.LZD"))

    if args.dungeon is not None:
        if args.dungeon < 0 or args.dungeon > 4:
            print("ERROR: --dungeon must be 0-4", file=sys.stderr)
            return 1
        objs = world.dungeon_objects[args.dungeon]
        label = f"dungeon {args.dungeon}"
    elif args.block is not None:
        if args.block < 0 or args.block >= len(world.surface_objects):
            print(f"ERROR: --block must be 0-{len(world.surface_objects) - 1}", file=sys.stderr)
            return 1
        objs = world.surface_objects[args.block]
        label = f"surface block {args.block}"
    else:
        objs = list(world.iter_surface())
        label = "all surface blocks"

    eggs = [o for o in objs if o.is_egg]
    print(f"{label}: {len(eggs)} egg(s)")
    print(f"{'X':>5} {'Y':>5} {'Z':>2}  {'Chance':>6}  {'Spawns':<20} {'Max':>3}  {'Qual':>4}")
    print("-" * 60)
    for egg in eggs[:args.limit]:
        target = egg.spawn_target
        if target is None:
            print(f"{egg.x:>5} {egg.y:>5} {egg.z:>2}  {egg.spawn_probability:>5}%  (no spawn target)")
            continue
        tnum = target.tile_num(basetile)
        name = names.get_name(tnum) or "?"
        print(f"{egg.x:>5} {egg.y:>5} {egg.z:>2}  {egg.spawn_probability:>5}%  {name:<20} {target.qty:>3}  {target.quality:>4}")
    if len(eggs) > args.limit:
        print(f"... ({len(eggs) - args.limit} more not shown; increase --limit to see more)")
    return 0


def cmd_actor_list(args: SimpleNamespace) -> int:
    """List the NPC/actor identity table (position, appearance, stats)."""
    gamedir = _require_gamedir(args.gamedir)
    if not os.path.isfile(os.path.join(gamedir, "LZDNGBLK")):
        print(f"ERROR: Required file not found: {os.path.join(gamedir, 'LZDNGBLK')}", file=sys.stderr)
        return 1

    world = U6WorldObjects.from_directory(gamedir)
    actors = U6Actors.parse(world.objlist_tail)

    if not args.all:
        actors = [a for a in actors if a.is_active]

    print(f"{len(actors)} actor(s) {'(all 256 slots)' if args.all else '(active only; use --all for every slot)'}")
    print(f"{'ID':>4}  {'X':>5} {'Y':>5} {'Z':>2}  {'ObjN':>5} {'Frm':>3}  "
          f"{'STR':>3} {'DEX':>3} {'INT':>3} {'HP':>4} {'Lvl':>3}  {'Algn':>4}")
    print("-" * 68)
    for a in actors:
        print(f"{a.actor_id:>4}  {a.x:>5} {a.y:>5} {a.z:>2}  {a.obj_n:>5} {a.frame_n:>3}  "
              f"{a.strength:>3} {a.dexterity:>3} {a.intelligence:>3} {a.hp:>4} {a.level:>3}  {a.alignment:>4}")
    return 0


def cmd_gamestate_dump(args: SimpleNamespace) -> int:
    """Show party roster, player state, and game clock/weather from objlist."""
    gamedir = _require_gamedir(args.gamedir)
    if not os.path.isfile(os.path.join(gamedir, "LZDNGBLK")):
        print(f"ERROR: Required file not found: {os.path.join(gamedir, 'LZDNGBLK')}", file=sys.stderr)
        return 1

    world = U6WorldObjects.from_directory(gamedir)
    state = U6GameState.parse(world.objlist_tail)

    print(f"Date: {state.clock.date_string()}   Time: {state.clock.time_string()}   "
          f"Rest counter: {state.clock.rest_counter}")
    print(f"Wind: {state.wind_direction or 'calm'}")
    print(f"Karma: {state.player.karma}   Alcohol: {state.player.alcohol}   "
          f"Gender: {state.player.gender_word}   Knows Gargish: {state.player.knows_gargish}   "
          f"Quest flag: {state.player.quest_flag}")
    if state.player.solo_mode:
        print(f"Solo mode: party-roster index {state.player.solo_member_index}")
    else:
        print("Solo mode: off (full party active)")

    print(f"\nParty ({state.party.num_members} member(s), "
          f"combat mode {'on' if state.party.in_combat_mode else 'off'}):")
    print(f"{'#':>3}  {'Name':<14} {'Actor ID':>8}")
    print("-" * 30)
    for i, member in enumerate(state.party.members):
        print(f"{i:>3}  {member.name:<14} {member.actor_id:>8}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — STORY FLAGS
# ============================================================================

def cmd_flags_dump(args: SimpleNamespace) -> int:
    """Dump every actor's talk_flags plus quest_flag/knows_gargish from a gamedir or SAVEGAME folder."""
    objlist = _load_objlist_from_source(args.source)
    flags = read_talk_flags(objlist)
    state = U6GameState.parse(objlist)

    print(f"Quest flag: {state.player.quest_flag}   Knows Gargish: {state.player.knows_gargish}")
    print()
    print(f"{'Actor':>5}  {'Flags':<8} Bits set")
    print("-" * 40)
    for actor_id in range(len(flags)):
        value = flags[actor_id]
        if not args.all and value == 0:
            continue
        bits = [str(i) for i in range(8) if value & (1 << i)]
        print(f"{actor_id:>5}  0b{value:08b}  {','.join(bits) or '-'}")
    return 0


def cmd_flags_compare(args: SimpleNamespace) -> int:
    """Diff story-flag state (talk_flags, quest_flag, knows_gargish) between two gamedirs/SAVEGAME folders."""
    objlist_a = _load_objlist_from_source(args.source_a)
    objlist_b = _load_objlist_from_source(args.source_b)
    diffs = compare_flags(objlist_a, objlist_b)

    if not diffs:
        print("No differences.")
        return 0
    print(f"{len(diffs)} difference(s):")
    for d in diffs:
        print(f"  {d}")
    return 0


def cmd_flags_set(args: SimpleNamespace) -> int:
    """Set/clear one actor's talk flag, or the quest/gargish global flag, in a save's OBJLIST."""
    objlist_path = os.path.join(args.savegame, "OBJLIST")
    if not os.path.isfile(objlist_path):
        print(f"ERROR: Required file not found: {objlist_path}", file=sys.stderr)
        return 1

    with open(objlist_path, "rb") as f:
        data = bytearray(f.read())

    if args.actor is not None:
        if args.flag is None or args.value is None:
            print("ERROR: --actor requires --flag and --value", file=sys.stderr)
            return 1
        try:
            set_talk_flag(data, args.actor, args.flag, bool(args.value))
        except U6FlagsError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        desc = f"actor {args.actor} talk_flag bit {args.flag} -> {bool(args.value)}"
    elif args.quest_flag is not None:
        set_quest_flag(data, args.quest_flag)
        desc = f"quest_flag -> {args.quest_flag}"
    elif args.gargish is not None:
        set_gargish_flag(data, bool(args.gargish))
        desc = f"knows_gargish -> {bool(args.gargish)}"
    else:
        print("ERROR: specify --actor/--flag/--value, --quest-flag, or --gargish", file=sys.stderr)
        return 1

    if args.in_place and not args.output:
        backup_path = objlist_path + ".bak"
        if not os.path.isfile(backup_path):
            with open(objlist_path, "rb") as f:
                original = f.read()
            with open(backup_path, "wb") as f:
                f.write(original)
            print(f"Backed up original -> {backup_path}")
        out_path = objlist_path
    else:
        out_path = args.output or objlist_path + ".new"

    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Set {desc}")
    print(f"Wrote: {out_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — CONVERSE
# ============================================================================

def cmd_converse_dump(args: SimpleNamespace) -> int:
    """Disassemble one or all scripts from a CONVERSE.A/B library file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    lib = U6Library.from_file(filepath, entry_size=args.entry_size, has_size_header=args.size_header)

    if args.item is not None:
        if args.item < 0 or args.item >= lib.num_items:
            print(f"ERROR: Item {args.item} out of range (0..{lib.num_items - 1})", file=sys.stderr)
            return 1
        items = [args.item]
    else:
        items = [i for i in range(lib.num_items) if lib.items[i].size > 0]

    outdir = args.output
    base = Path(filepath).name
    dumped = 0
    for i in items:
        try:
            script = lib.get_item(i)
            text = format_instructions(disassemble(script))
        except Exception as e:
            print(f"  WARNING: Failed to disassemble item {i}: {e}", file=sys.stderr)
            continue
        if outdir:
            os.makedirs(outdir, exist_ok=True)
            out_path = os.path.join(outdir, f"{i:04d}_{base}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        else:
            print(f"=== item {i} ===")
            print(text)
        dumped += 1

    if outdir:
        print(f"Disassembled {dumped}/{len(items)} item(s) -> {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — FONT
# ============================================================================

def cmd_font_export(args: SimpleNamespace) -> int:
    """Export the English and runic/gargoyle fonts from U6.CH."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    fonts = U6Fonts.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    english_path = os.path.join(outdir, "font_english.png")
    runic_path = os.path.join(outdir, "font_runic_gargoyle.png")
    fonts.english.to_contact_sheet(scale=args.scale).save(english_path)
    fonts.runic.to_contact_sheet(scale=args.scale).save(runic_path)
    print(f"Exported: {english_path}")
    print(f"Exported: {runic_path}")

    if args.text:
        eng_path = os.path.join(outdir, "text_english.png")
        run_path = os.path.join(outdir, "text_runic_gargoyle.png")
        fonts.english.render_text(args.text, bg=(0, 0, 0), scale=args.scale).save(eng_path)
        fonts.runic.render_text(args.text, bg=(0, 0, 0), scale=args.scale).save(run_path)
        print(f"Exported: {eng_path}")
        print(f"Exported: {run_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — LOOK
# ============================================================================

def cmd_look_dump(args: SimpleNamespace) -> int:
    """Dump LOOK.LZD's tile-number -> object-name table."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    names = U6ObjectNames.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "look_dump.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"LOOK.LZD — {len(names.entries)} entries\n")
        f.write("=" * 60 + "\n")
        f.write("Each entry's tile number is the LAST tile in the range it\n")
        f.write("names; a tile with no entry of its own uses the next\n")
        f.write("higher tile number that has one.\n\n")
        for e in names.entries:
            f.write(f"{e.tile_num:>5}  {e.name}\n")

    print(f"Dumped {len(names.entries)} entries -> {out_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — BOOK
# ============================================================================

def cmd_book_dump(args: SimpleNamespace) -> int:
    """Dump one or all book/sign texts from BOOK.DAT."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    books = U6Books.from_file(filepath)

    if args.book is not None:
        if args.book < 0 or args.book >= books.num_books:
            print(f"ERROR: Book {args.book} out of range (0..{books.num_books - 1})", file=sys.stderr)
            return 1
        print(books.get_text(args.book))
        return 0

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "book_dump.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"BOOK.DAT — {books.num_books} texts\n")
        f.write("=" * 60 + "\n\n")
        for i in range(books.num_books):
            f.write(f"--- {i} ---\n{books.get_text(i)}\n\n")
    print(f"Dumped {books.num_books} texts -> {out_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SCHEDULE
# ============================================================================

def cmd_schedule_dump(args: SimpleNamespace) -> int:
    """Dump one or all actors' schedules from SCHEDULE."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    schedules = U6Schedules.from_file(filepath)
    actor_ids = [args.actor] if args.actor is not None else range(len(schedules.per_actor))

    outdir = args.output
    lines: list[str] = []
    for actor_id in actor_ids:
        if actor_id < 0 or actor_id >= len(schedules.per_actor):
            print(f"ERROR: Actor {actor_id} out of range (0..{len(schedules.per_actor) - 1})", file=sys.stderr)
            return 1
        entries = schedules.for_actor(actor_id)
        if not entries:
            continue
        lines.append(f"--- actor {actor_id}: {len(entries)} entries ---")
        lines.append(f"{'Hour':>4} {'Day':>3}  {'Worktype':>8}  {'X':>5} {'Y':>5} {'Z':>2}")
        for e in entries:
            lines.append(f"{e.hour:>4} {e.day_of_week:>3}  {e.worktype:>8}  {e.x:>5} {e.y:>5} {e.z:>2}")

    text = "\n".join(lines)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        out_path = os.path.join(outdir, "schedule_dump.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"Dumped schedules for {len(actor_ids)} actor(s) -> {out_path}")
    else:
        print(text)
    return 0


# ============================================================================
# Typer command wrappers
# ============================================================================

@u6_app.command("lzw-decompress")
def lzw_decompress_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 LZW-compressed file")],
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Decompress a single U6 LZW file to raw bytes."""
    raise SystemExit(cmd_lzw_decompress(SimpleNamespace(file=file, output=output)))


@u6_app.command("lib-list")
def lib_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 library file (e.g. CONVERSE.A)")],
    entry_size: Annotated[int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")] = 4,
    size_header: Annotated[
        bool, typer.Option("--size-header", help="File has a leading 4-byte size header (MD/SE)"),
    ] = False,
) -> None:
    """List a U6 library file's items."""
    raise SystemExit(cmd_lib_list(SimpleNamespace(file=file, entry_size=entry_size, size_header=size_header)))


@u6_app.command("lib-extract")
def lib_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 library file")],
    item: Annotated[int, typer.Argument(help="Item index to extract")],
    entry_size: Annotated[int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")] = 4,
    size_header: Annotated[bool, typer.Option("--size-header", help="File has a leading 4-byte size header")] = False,
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Extract one item from a U6 library file."""
    raise SystemExit(cmd_lib_extract(SimpleNamespace(
        file=file, item=item, entry_size=entry_size, size_header=size_header, output=output,
    )))


@u6_app.command("lib-extract-all")
def lib_extract_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 library file")],
    entry_size: Annotated[int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")] = 4,
    size_header: Annotated[bool, typer.Option("--size-header", help="File has a leading 4-byte size header")] = False,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: <file>_items/)"),
    ] = None,
) -> None:
    """Extract every non-empty item from a U6 library file."""
    raise SystemExit(cmd_lib_extract_all(SimpleNamespace(
        file=file, entry_size=entry_size, size_header=size_header, output=output,
    )))


@u6_app.command("tileflag-dump")
def tileflag_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to TILEFLAG")],
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Parse TILEFLAG and dump all entries as a readable table."""
    raise SystemExit(cmd_tileflag_dump(SimpleNamespace(file=file, output=output)))


@u6_app.command("palette-export")
def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to U6PAL")],
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Export U6PAL as a PNG swatch + text dump."""
    raise SystemExit(cmd_palette_export(SimpleNamespace(file=file, output=output)))


@u6_app.command("tile-export")
def tile_export_cmd(
    tile_num: Annotated[str, typer.Argument(help="Tile number, decimal or 0x-hex (0-0x7FF)")],
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory"),
    ] = None,
    palette: Annotated[Optional[str], typer.Option("-p", "--palette", help="Path to U6PAL")] = None,
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Export one U6 tile to PNG."""
    raise SystemExit(cmd_tile_export(SimpleNamespace(
        tile_num=_parse_tile_num(tile_num), gamedir=gamedir, palette=palette, output=output,
    )))


@u6_app.command("tile-export-all")
def tile_export_all_cmd(
    gamedir: Annotated[Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory")] = None,
    palette: Annotated[Optional[str], typer.Option("-p", "--palette", help="Path to U6PAL")] = None,
    start: Annotated[int, typer.Option("--start", help="First tile number (inclusive)")] = 0,
    end: Annotated[
        Optional[int], typer.Option("--end", help="Last tile number (inclusive); default: last tile"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: tiles_png/)"),
    ] = None,
) -> None:
    """Batch-export a range of U6 tiles to PNG."""
    raise SystemExit(cmd_tile_export_all(SimpleNamespace(
        gamedir=gamedir, palette=palette, start=start, end=end, output=output,
    )))


@u6_app.command("map-render")
def map_render_cmd(
    gamedir: Annotated[Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory")] = None,
    palette: Annotated[Optional[str], typer.Option("-p", "--palette", help="Path to U6PAL")] = None,
    region: Annotated[
        Optional[str], typer.Option("--region", help="Crop to 'x,y,width,height' (tile coordinates)"),
    ] = None,
    dungeon: Annotated[
        Optional[int], typer.Option("--dungeon", help="Render dungeon level 0-4 instead of the surface"),
    ] = None,
    full: Annotated[
        bool, typer.Option("--full", help="Render the entire surface (very large image)"),
    ] = False,
    tick: Annotated[int, typer.Option("--tick", help="Animation tick, for water/animated tiles")] = 0,
    objects: Annotated[
        bool, typer.Option("--objects", help="Overlay world objects (furniture, items, etc.) from LZOBJBLK/LZDNGBLK"),
    ] = False,
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output PNG path")] = None,
) -> None:
    """Render the U6 surface world or a dungeon level to PNG."""
    raise SystemExit(cmd_map_render(SimpleNamespace(
        gamedir=gamedir, palette=palette, region=region, dungeon=dungeon,
        full=full, tick=tick, objects=objects, output=output,
    )))


@u6_app.command("object-list")
def object_list_cmd(
    gamedir: Annotated[Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory")] = None,
    block: Annotated[
        Optional[int], typer.Option("--block", help="Surface superchunk block number (0-63)"),
    ] = None,
    dungeon: Annotated[
        Optional[int], typer.Option("--dungeon", help="Dungeon level (0-4) instead of a surface block"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows to print")] = 200,
) -> None:
    """List world objects in a surface block or dungeon level."""
    raise SystemExit(cmd_object_list(SimpleNamespace(gamedir=gamedir, block=block, dungeon=dungeon, limit=limit)))


@u6_app.command("egg-list")
def egg_list_cmd(
    gamedir: Annotated[Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory")] = None,
    block: Annotated[
        Optional[int], typer.Option("--block", help="Surface superchunk block number (0-63)"),
    ] = None,
    dungeon: Annotated[
        Optional[int], typer.Option("--dungeon", help="Dungeon level (0-4) instead of a surface block"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows to print")] = 200,
) -> None:
    """List every egg (object spawner) in a surface block or dungeon level, with what it spawns."""
    raise SystemExit(cmd_egg_list(SimpleNamespace(gamedir=gamedir, block=block, dungeon=dungeon, limit=limit)))


@u6_app.command("actor-list")
def actor_list_cmd(
    gamedir: Annotated[Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory")] = None,
    all: Annotated[
        bool, typer.Option("--all", help="Show all 256 actor slots, including inactive/unused ones"),
    ] = False,
) -> None:
    """List the NPC/actor identity table (position, appearance, stats)."""
    raise SystemExit(cmd_actor_list(SimpleNamespace(gamedir=gamedir, all=all)))


@u6_app.command("gamestate-dump")
def gamestate_dump_cmd(
    gamedir: Annotated[Optional[str], typer.Option("-g", "--gamedir", help="U6 game directory")] = None,
) -> None:
    """Show party roster, player state, and game clock/weather from objlist."""
    raise SystemExit(cmd_gamestate_dump(SimpleNamespace(gamedir=gamedir)))


@u6_app.command("flags-dump")
def flags_dump_cmd(
    source: Annotated[str, typer.Argument(help="A gamedir (LZDNGBLK) or a save's SAVEGAME folder (OBJLIST)")],
    all: Annotated[bool, typer.Option("--all", help="Show every actor, including all-zero talk_flags")] = False,
) -> None:
    """Dump every actor's talk_flags plus quest_flag/knows_gargish."""
    raise SystemExit(cmd_flags_dump(SimpleNamespace(source=source, all=all)))


@u6_app.command("flags-compare")
def flags_compare_cmd(
    source_a: Annotated[str, typer.Argument(help="First gamedir or SAVEGAME folder")],
    source_b: Annotated[str, typer.Argument(help="Second gamedir or SAVEGAME folder")],
) -> None:
    """Diff story-flag state (talk_flags, quest_flag, knows_gargish) between two sources."""
    raise SystemExit(cmd_flags_compare(SimpleNamespace(source_a=source_a, source_b=source_b)))


@u6_app.command("flags-set")
def flags_set_cmd(
    savegame: Annotated[str, typer.Argument(help="A save's SAVEGAME folder (containing OBJLIST)")],
    actor: Annotated[Optional[int], typer.Option("--actor", help="Actor ID (0-255) whose talk flag to set")] = None,
    flag: Annotated[Optional[int], typer.Option("--flag", help="Talk-flag bit index (0-7); requires --actor")] = None,
    value: Annotated[Optional[int], typer.Option("--value", help="0 to clear, 1 to set; requires --actor/--flag")] = None,
    quest_flag: Annotated[Optional[int], typer.Option("--quest-flag", help="Set the global quest_flag byte")] = None,
    gargish: Annotated[Optional[int], typer.Option("--gargish", help="0/1: set whether the player knows Gargish")] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Write the modified OBJLIST here instead of alongside the original"),
    ] = None,
    in_place: Annotated[
        bool, typer.Option("--in-place", help="Overwrite the save's own OBJLIST (backed up to OBJLIST.bak first)"),
    ] = False,
) -> None:
    """Set/clear one actor's talk flag, or the quest/gargish global flag, in a save's OBJLIST."""
    raise SystemExit(cmd_flags_set(SimpleNamespace(
        savegame=savegame, actor=actor, flag=flag, value=value,
        quest_flag=quest_flag, gargish=gargish, output=output, in_place=in_place,
    )))


@u6_app.command("converse-dump")
def converse_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 conversation library file (CONVERSE.A or CONVERSE.B)")],
    item: Annotated[
        Optional[int], typer.Option("--item", help="Single item index to disassemble; default: every non-empty item"),
    ] = None,
    entry_size: Annotated[int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")] = 4,
    size_header: Annotated[bool, typer.Option("--size-header", help="File has a leading 4-byte size header")] = False,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory; omit to print to stdout"),
    ] = None,
) -> None:
    """Disassemble one or all scripts from a CONVERSE.A/B library file."""
    raise SystemExit(cmd_converse_dump(SimpleNamespace(
        file=file, item=item, entry_size=entry_size, size_header=size_header, output=output,
    )))


@u6_app.command("font-export")
def font_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to U6.CH")],
    text: Annotated[
        Optional[str], typer.Option("--text", help="Also render this text in both fonts, for comparison"),
    ] = None,
    scale: Annotated[int, typer.Option("--scale", help="Pixel scale factor for the exported images")] = 3,
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Export the English and runic/gargoyle fonts from U6.CH as contact sheets."""
    raise SystemExit(cmd_font_export(SimpleNamespace(file=file, text=text, scale=scale, output=output)))


@u6_app.command("look-dump")
def look_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to LOOK.LZD")],
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Dump LOOK.LZD's tile-number -> object-name table."""
    raise SystemExit(cmd_look_dump(SimpleNamespace(file=file, output=output)))


@u6_app.command("book-dump")
def book_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to BOOK.DAT")],
    book: Annotated[
        Optional[int], typer.Option("--book", help="Single book/sign index to print; default: dump every text"),
    ] = None,
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output directory")] = None,
) -> None:
    """Dump one or all book/sign texts from BOOK.DAT."""
    raise SystemExit(cmd_book_dump(SimpleNamespace(file=file, book=book, output=output)))


@u6_app.command("schedule-dump")
def schedule_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to SCHEDULE")],
    actor: Annotated[
        Optional[int], typer.Option("--actor", help="Single actor ID (0-255); default: every actor with a schedule"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory; omit to print to stdout"),
    ] = None,
) -> None:
    """Dump one or all actors' schedules from SCHEDULE."""
    raise SystemExit(cmd_schedule_dump(SimpleNamespace(file=file, actor=actor, output=output)))
