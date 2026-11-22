"""``titan u6`` map render and z-order audit commands."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._meta import meta
from titan.u6.cli._common import (
    _require_gamedir,
    _resolve_palette,
)
from titan.u6.look import U6ObjectNames
from titan.u6.map import U6Chunks, U6Map, render_tile_grid
from titan.u6.map_layers import build_u6_object_stacks
from titan.u6.object import U6WorldObjects, read_basetile
from titan.u6.palette import U6Palette
from titan.u6.tile import U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlags


def _parse_region(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        print(
            f"ERROR: --region must be 'x,y,width,height', got: {value}", file=sys.stderr
        )
        raise SystemExit(1)
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        print(f"ERROR: --region values must be integers: {value}", file=sys.stderr)
        raise SystemExit(1)
    return x, y, w, h


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render the U6 surface world or a dungeon level to PNG."""
    gamedir = _require_gamedir(args.gamedir)
    palette_path = _resolve_palette(gamedir, args.palette)

    map_path = os.path.join(gamedir, "MAP")
    chunks_path = os.path.join(gamedir, "CHUNKS")
    animdata_path = os.path.join(gamedir, "ANIMDATA")
    for path in (map_path, chunks_path, animdata_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Required file not found: {path}")

    if args.dungeon is None and args.region is None and not args.full:
        print(
            "ERROR: Specify --region x,y,w,h, --dungeon N (0-4), or --full "
            "(--full renders the entire 1024x1024-tile surface -- a very "
            "large image).",
            file=sys.stderr,
        )
        return 1

    show_invisible = getattr(args, "show_invisible", False)
    if show_invisible and not args.objects:
        print("ERROR: --show-invisible requires --objects.", file=sys.stderr)
        return 1

    if args.objects:
        for name in ("LZOBJBLK", "LZDNGBLK", "BASETILE", "TILEFLAG"):
            if not os.path.isfile(os.path.join(gamedir, name)):
                raise FileNotFoundError(
                    f"Required file not found for --objects: {os.path.join(gamedir, name)}"
                )

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
    if region is not None:
        x, y, width, height = region
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            print(
                "ERROR: --region requires nonnegative x/y and positive width/height.",
                file=sys.stderr,
            )
            return 1
        if x + width > grid.shape[1] or y + height > grid.shape[0]:
            print(
                f"ERROR: --region exceeds the {grid.shape[1]}x{grid.shape[0]} map.",
                file=sys.stderr,
            )
            return 1

    print(
        f"Rendering {'dungeon ' + str(args.dungeon) if args.dungeon is not None else 'surface'}"
        f"{f' region {region}' if region else ' (full)'} ..."
    )
    img = render_tile_grid(
        grid, tiles, pal, region=region, animdata=anim, tick=args.tick
    )

    if args.objects:
        img = img.convert("RGBA")
        world = U6WorldObjects.from_directory(gamedir)
        basetile = read_basetile(os.path.join(gamedir, "BASETILE"))
        tileflags = U6TileFlags.from_file(os.path.join(gamedir, "TILEFLAG"))
        obj_iter = (
            world.iter_dungeon(args.dungeon)
            if args.dungeon is not None
            else world.iter_surface()
        )

        ox, oy = (region[0], region[1]) if region else (0, 0)
        rh, rw = grid.shape[:2] if region is None else (region[3], region[2])

        stacks = build_u6_object_stacks(
            obj_iter,
            basetile,
            tileflags,
            bounds=(ox, oy, rw, rh),
            show_invisible=show_invisible,
            num_tiles=tiles.num_tiles,
        )
        drawn_records = set()
        for (world_x, world_y, _z), stack in stacks.items():
            px, py = (world_x - ox) * 16, (world_y - oy) * 16
            if stack.background is not None:
                cell = stack.background
                tile = anim.resolve_tile(cell.tile_num, args.tick)
                if 0 <= tile < tiles.num_tiles:
                    # A selected background replaces the ground tile; it is
                    # rendered as terrain, rather than another alpha overlay.
                    img.paste(
                        tiles.to_pil_image(tile, pal, transparent=False), (px, py)
                    )
                    drawn_records.add(cell.record_index)
            for cell in stack.overlays:
                tile = anim.resolve_tile(cell.tile_num, args.tick)
                if 0 <= tile < tiles.num_tiles:
                    img.alpha_composite(
                        tiles.to_pil_image(tile, pal, transparent=True), (px, py)
                    )
                    drawn_records.add(cell.record_index)
        print(f"  overlaid {len(drawn_records)} object(s)")

    out_path = args.output or default_name
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Saved: {out_path}  ({img.width}x{img.height})")
    return 0


def _zorder_audit_scan(
    obj_iter,
    zone_label,
    tiles,
    tileflags,
    basetile,
    anim,
    names,
    min_winner_opacity,
    min_loser_opacity,
    show_invisible: bool = False,
):
    """Describe actual ordered pixel overlaps using the renderer's cell stacks."""
    stacks = build_u6_object_stacks(
        obj_iter,
        basetile,
        tileflags,
        show_invisible=show_invisible,
        num_tiles=tiles.num_tiles,
    )
    masks = {}

    def entry(cell):
        tile = anim.resolve_tile(cell.tile_num, 0)
        if tile not in masks:
            masks[tile] = tiles.to_array(tile) != 0xFF
        mask = masks[tile]
        return dict(
            obj_n=cell.obj.obj_n,
            frame=cell.obj.frame_n,
            tnum=cell.tile_num,
            resolved=tile,
            opac=float(mask.sum() / 256),
            name=names.get_name(cell.tile_num),
            seq=cell.record_index,
            is_anchor=cell.is_anchor,
            mask=mask,
        )

    candidates = []
    for pos, stack in stacks.items():
        if len(stack.overlays) < 2:
            continue
        winner_cell = stack.overlays[-1]
        winner = entry(winner_cell)
        if winner["opac"] < min_winner_opacity:
            continue
        for cell in reversed(stack.overlays[:-1]):
            loser = entry(cell)
            overlap = int((winner["mask"] & loser["mask"]).sum())
            if (
                loser["opac"] < min_loser_opacity
                or loser["name"] == winner["name"]
                or not overlap
            ):
                continue
            if tileflags[winner_cell.tile_num].is_foreground:
                order = (
                    "foreground-anchor"
                    if winner_cell.is_anchor
                    else "foreground-overflow"
                )
            else:
                order = "ordinary-prepend"
            candidates.append((zone_label, pos, winner, loser, order, overlap))
    return candidates


def cmd_map_audit_zorder(args: SimpleNamespace) -> int:
    """Describe ordered object overlaps in ``map-render --objects`` at animation tick zero."""
    gamedir = _require_gamedir(args.gamedir)
    for name in (
        "BASETILE",
        "TILEFLAG",
        "ANIMDATA",
        "LOOK.LZD",
        "LZOBJBLK",
        "LZDNGBLK",
    ):
        if not os.path.isfile(os.path.join(gamedir, name)):
            raise FileNotFoundError(
                f"Required file not found: {os.path.join(gamedir, name)}"
            )

    world = U6WorldObjects.from_directory(gamedir)
    basetile = read_basetile(os.path.join(gamedir, "BASETILE"))
    tileflags = U6TileFlags.from_file(os.path.join(gamedir, "TILEFLAG"))
    tiles = U6Tiles.from_directory(gamedir)
    anim = U6AnimData.from_file(os.path.join(gamedir, "ANIMDATA"))
    names = U6ObjectNames.from_file(os.path.join(gamedir, "LOOK.LZD"))

    kwargs = dict(
        tiles=tiles,
        tileflags=tileflags,
        basetile=basetile,
        anim=anim,
        names=names,
        min_winner_opacity=args.min_winner_opacity,
        min_loser_opacity=args.min_loser_opacity,
        show_invisible=getattr(args, "show_invisible", False),
    )
    candidates = _zorder_audit_scan(world.iter_surface(), "surface", **kwargs)
    if args.dungeons:
        for level in range(5):
            candidates += _zorder_audit_scan(
                world.iter_dungeon(level), f"dungeon{level}", **kwargs
            )

    candidates.sort(key=lambda c: -c[3]["opac"])
    print(f"total ordered overlap candidates: {len(candidates)}")
    seen = set()
    shown = 0
    for zone, pos, winner, loser, order, overlap in candidates:
        key = (loser["obj_n"], loser["tnum"], winner["obj_n"], winner["tnum"])
        tag = "" if key not in seen else " [repeat combo]"
        seen.add(key)
        print(
            f"{zone} {pos} order={order} overlap_pixels={overlap}  UNDER: {loser['name']!r} "
            f"(obj_n={loser['obj_n']} tnum={loser['tnum']} opac={loser['opac']:.2f})  "
            f"OVER: {winner['name']!r} (obj_n={winner['obj_n']} tnum={winner['tnum']} opac={winner['opac']:.2f}){tag}"
        )
        shown += 1
        if args.limit and shown >= args.limit:
            break
    return 0


@meta(
    category="world",
    results=("image",),
    params={"output": "output-file", "palette": "palette"},
)
def map_render_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("-p", "--palette", help="Path to U6PAL")
    ] = None,
    region: Annotated[
        Optional[str],
        typer.Option(
            "--region",
            help="Crop to 'x,y,width,height' within the map; nonnegative x/y, positive width/height",
        ),
    ] = None,
    dungeon: Annotated[
        Optional[int],
        typer.Option(
            "--dungeon", help="Render dungeon level 0-4 instead of the surface"
        ),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Render the entire surface (very large image)"),
    ] = False,
    tick: Annotated[
        int, typer.Option("--tick", help="Animation tick, for water/animated tiles")
    ] = 0,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects",
            help="Overlay visible world objects (furniture, items, etc.) from LZOBJBLK/LZDNGBLK",
        ),
    ] = False,
    show_invisible: Annotated[
        bool,
        typer.Option(
            "--show-invisible",
            help="Include invisible world objects (requires --objects)",
        ),
    ] = False,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output PNG path")
    ] = None,
) -> None:
    """Render the U6 surface world or a dungeon level to PNG."""
    raise SystemExit(
        cmd_map_render(
            SimpleNamespace(
                gamedir=gamedir,
                palette=palette,
                region=region,
                dungeon=dungeon,
                full=full,
                tick=tick,
                objects=objects,
                show_invisible=show_invisible,
                output=output,
            )
        )
    )


@meta(category="world", results=("text",))
def map_audit_zorder_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
    min_winner_opacity: Annotated[
        float,
        typer.Option(
            "--min-winner-opacity",
            help="Minimum opacity of the top overlay",
        ),
    ] = 0.60,
    min_loser_opacity: Annotated[
        float,
        typer.Option(
            "--min-loser-opacity",
            help="Minimum opacity of an underlying overlay",
        ),
    ] = 0.10,
    limit: Annotated[
        int, typer.Option("--limit", help="Max rows to print (0 = unlimited)")
    ] = 200,
    dungeons: Annotated[
        bool, typer.Option("--dungeons", help="Also scan all 5 dungeon levels")
    ] = False,
    show_invisible: Annotated[
        bool,
        typer.Option(
            "--show-invisible", help="Include invisible world objects in the audit"
        ),
    ] = False,
) -> None:
    """Inspect ordered object overlaps using map-render's original U6 cell-stack rules.

    Reports distinct named overlays with intersecting opaque pixels at tick zero.
    UNDER/OVER follow the actual draw order; these are deterministic overlaps,
    not unresolved ties or confirmed rendering errors.
    """
    raise SystemExit(
        cmd_map_audit_zorder(
            SimpleNamespace(
                gamedir=gamedir,
                min_winner_opacity=min_winner_opacity,
                min_loser_opacity=min_loser_opacity,
                limit=limit,
                dungeons=dungeons,
                show_invisible=show_invisible,
            )
        )
    )
