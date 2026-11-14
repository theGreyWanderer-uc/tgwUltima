"""``titan u7 map-*`` — map creation, JSON interchange, rendering and inventory commands."""

from __future__ import annotations

__all__ = [
    "map_create_cmd",
    "map_export_json_cmd",
    "map_render_json_cmd",
    "map_render_cmd",
    "map_sample_cmd",
    "map_inventory_cmd",
]

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.u7 import install


def _parse_hex_rgba(color: str) -> tuple[int, int, int, int]:
    """Parse #RRGGBB or #RRGGBBAA into RGBA tuple."""
    txt = color.strip()
    if txt.startswith("#"):
        txt = txt[1:]

    if len(txt) not in (6, 8):
        raise ValueError(f"Color '{color}' must be #RRGGBB or #RRGGBBAA.")

    try:
        r = int(txt[0:2], 16)
        g = int(txt[2:4], 16)
        b = int(txt[4:6], 16)
        a = int(txt[6:8], 16) if len(txt) == 8 else 255
    except ValueError as exc:
        raise ValueError(f"Color '{color}' is not valid hex.") from exc

    return (r, g, b, a)


def _parse_highlight_tile_rect(
    value: str,
) -> tuple[int, int, int, int, tuple[int, int, int, int], str]:
    """Parse tx0,ty0,tx1,ty1,#RRGGBB[AA][,label] into a typed tuple."""
    parts = [p.strip() for p in value.split(",", 5)]
    if len(parts) not in (5, 6):
        raise ValueError("Expected 'tx0,ty0,tx1,ty1,#RRGGBB[,label]' (or #RRGGBBAA).")

    try:
        tx0 = int(parts[0], 10)
        ty0 = int(parts[1], 10)
        tx1 = int(parts[2], 10)
        ty1 = int(parts[3], 10)
    except ValueError as exc:
        raise ValueError(f"Tile coordinates must be integers in '{value}'.") from exc

    rgba = _parse_hex_rgba(parts[4])
    default_label = f"{tx0},{ty0},{tx1},{ty1}"
    label = parts[5] if len(parts) == 6 and parts[5] else default_label
    return (tx0, ty0, tx1, ty1, rgba, label)


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render a U7 map region (superchunk, chunk range, or full world) to PNG."""
    from titan.u7.map import U7MapRenderer, U7TileRectOverlay
    from titan.u7.palette import U7Palette
    from titan.u7.shape_archive import find_archive

    game = getattr(args, "game", "bg")
    configured_static, configured_palette = install.resolve_u7_static_and_palette(game)
    static_dir = args.static
    if not static_dir:
        static_dir = configured_static
    if not static_dir or not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    map_root = getattr(args, "map_root", None)
    if map_root and not os.path.isdir(map_root):
        print(f"ERROR: Map root directory not found: {map_root}", file=sys.stderr)
        return 1

    patch_dir = getattr(args, "patch_dir", None)
    shapes_path = (
        find_archive(Path(patch_dir), "SHAPES.VGA") if patch_dir else None
    ) or find_archive(Path(static_dir), "SHAPES.VGA")
    if shapes_path is None:
        print(f"ERROR: SHAPES.VGA not found in {static_dir}", file=sys.stderr)
        return 1

    base_static_dir = (
        getattr(args, "base_static", None)
        if hasattr(args, "base_static")
        else (
            install.resolve_u7_patch_base_static(static_dir, configured_static)
            if args.static
            else None
        )
    )
    palette_path = args.palette
    if not palette_path:
        palette_path = configured_palette
        if (not palette_path or not os.path.isfile(palette_path)) and base_static_dir:
            palette_path = os.path.join(base_static_dir, "PALETTES.FLX")
    if not palette_path:
        palette_path = os.path.join(static_dir, "PALETTES.FLX")
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette not found: {palette_path}", file=sys.stderr)
        return 1

    palette_index = getattr(args, "palette_index", 0)
    pal = (
        U7Palette.from_file(palette_path, palette_index=palette_index)
        if palette_index
        else U7Palette.from_file(palette_path)
    )
    map_num = int(getattr(args, "map_num", 0) or 0)
    patch_options = {"patch_dir": patch_dir} if patch_dir else {}
    renderer = U7MapRenderer(
        static_dir,
        map_num=map_num,
        map_root=map_root,
        base_static_dir=base_static_dir,
        game=game,
        **patch_options,
    )

    view = args.view or "classic"
    if view not in U7MapRenderer.PROJECTIONS:
        print(
            f"ERROR: Unknown view '{view}'. "
            f"Available: {', '.join(U7MapRenderer.PROJECTIONS.keys())}",
            file=sys.stderr,
        )
        return 1

    if renderer.shapes_vga_base_fill_count:
        print(
            "Sparse SHAPES.VGA overlay: filled "
            f"{renderer.shapes_vga_base_fill_count} empty records from "
            f"{base_static_dir}"
        )

    # Build exclude set
    exclude: set[int] = set()
    if args.exclude_flags:
        tfa = renderer.tfa
        exclude_kw: dict[str, bool] = {}
        for flag_name in args.exclude_flags:
            exclude_kw[flag_name] = True
        exclude = tfa.build_exclude_set(**exclude_kw)
        active_names = [k for k in exclude_kw if exclude_kw[k]]
        print(
            f"Typeflag filter: {', '.join(active_names)} -> "
            f"{len(exclude)} shapes excluded"
        )

    gamedat = getattr(args, "gamedat", None)
    if gamedat and map_num > 0:
        map_ireg_dir = os.path.join(gamedat, f"map{map_num:02x}")
        if os.path.isdir(map_ireg_dir):
            gamedat = map_ireg_dir
    overlay_tuples = getattr(args, "highlight_rects", None) or []
    overlays = [
        U7TileRectOverlay(
            tx0=tx0,
            ty0=ty0,
            tx1=tx1,
            ty1=ty1,
            color=color,
            label=label,
        )
        for tx0, ty0, tx1, ty1, color, label in overlay_tuples
    ]
    highlight_width = max(1, int(getattr(args, "highlight_width", 3) or 3))
    highlight_lift = int(getattr(args, "highlight_lift", 0) or 0)
    highlight_fill_alpha = max(
        0, min(255, int(getattr(args, "highlight_fill_alpha", 128) or 128))
    )
    highlight_labels = bool(getattr(args, "highlight_labels", True))
    ml = getattr(args, "max_lift", None)
    render_options = {}
    if hasattr(args, "resolution"):
        render_options["resolution"] = args.resolution
    progress = getattr(args, "progress", None)
    if progress is not None:
        render_options["progress"] = progress

    if args.superchunk is not None:
        sc = args.superchunk
        if sc < 0 or sc > 143:
            print(f"ERROR: Superchunk must be 0–143 (got {sc})", file=sys.stderr)
            return 1

        scx = sc % 12
        scy = sc // 12
        print(
            f"Rendering superchunk {sc} (0x{sc:02X}) at grid ({scx}, {scy}) "
            f"view={view} ..."
        )

        img = renderer.render_superchunk(
            sc,
            pal,
            view=view,
            include_ireg=gamedat,
            exclude_shapes=exclude,
            max_lift=ml,
            grid=args.grid,
            grid_size=args.grid_size,
            highlight_rects=overlays,
            highlight_width=highlight_width,
            highlight_lift=highlight_lift,
            highlight_fill_alpha=highlight_fill_alpha,
            highlight_labels=highlight_labels,
        )

        out_path = args.output or f"u7_sc{sc:02X}_{view}.png"
    else:
        cx0 = args.chunk_x0
        cy0 = args.chunk_y0
        cx1 = args.chunk_x1 if args.chunk_x1 is not None else cx0 + 15
        cy1 = args.chunk_y1 if args.chunk_y1 is not None else cy0 + 15

        print(f"Rendering chunks ({cx0},{cy0}) to ({cx1},{cy1}) view={view} ...")

        img = renderer.render_region(
            cx0,
            cy0,
            cx1,
            cy1,
            pal,
            view=view,
            gamedat_dir=gamedat,
            exclude_shapes=exclude,
            max_lift=ml,
            grid=args.grid,
            grid_size=args.grid_size,
            highlight_rects=overlays,
            highlight_width=highlight_width,
            highlight_lift=highlight_lift,
            highlight_fill_alpha=highlight_fill_alpha,
            highlight_labels=highlight_labels,
            **render_options,
        )

        out_path = args.output or f"u7_c{cx0}-{cy0}_c{cx1}-{cy1}_{view}.png"

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress:
        progress(99, "Writing PNG")
    img.save(out_path)
    if progress:
        progress(100, "PNG saved")
    print(f"Output: {img.width}×{img.height} -> {out_path}")
    return 0


def cmd_map_create(args: SimpleNamespace) -> int:
    """Create one native Exult map namespace, optionally from universal JSON."""
    from titan.u7.native_map_create import (
        U7NativeMapCreateError,
        create_u7_native_map,
    )

    try:
        result = create_u7_native_map(
            args.output_root,
            args.map_num,
            source_json=args.from_json,
            gamedat_root=args.gamedat_root,
            materialize_empty=args.materialize_empty,
            overwrite_map=args.overwrite_map,
            update_chunks=args.update_chunks,
            dry_run=args.dry_run,
        )
    except (OSError, U7NativeMapCreateError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    action = "Would create" if result.dry_run else "Created"
    print(f"{action} native U7 map {result.map_number:02x}: {result.map_directory}")
    if result.gamedat_directory:
        print(f"GAMEDAT namespace: {result.gamedat_directory}")
    if result.empty_map:
        state = (
            "materialized zero U7MAP"
            if result.materialized_empty_map
            else "missing U7MAP"
        )
        print(f"Empty map: {state}")
    else:
        print(
            f"U7MAP: {result.u7map_bytes} bytes; "
            f"IFIX: {result.ifix_files} files / {result.fixed_objects} objects"
        )
        print(
            f"U7CHUNKS: {result.chunks_action}; "
            f"{result.definitions_written} definitions "
            f"({result.definitions_appended} appended)"
        )
        print(f"Remapped map references: {result.remapped_definition_references}")
    return 0


def cmd_map_export_json(args: SimpleNamespace) -> int:
    """Export a complete U7 map, terrain definitions, and IFIX objects to JSON."""
    from titan.u7.map_json import (
        U7MapJsonError,
        build_u7_map_document,
        write_u7_map_document,
    )

    static_dir = args.static
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(args.game)
    if not static_dir:
        print("ERROR: No STATIC directory supplied or configured.", file=sys.stderr)
        return 1

    try:
        document = build_u7_map_document(
            static_dir,
            game=args.game,
            map_number=args.map_num,
            include_fixed_objects=args.include_fixed,
            include_shape_metadata=args.include_shape_metadata,
            wrap_x=args.wrap_x,
            wrap_y=args.wrap_y,
        )
        write_u7_map_document(document, args.output, pretty=args.pretty)
    except (OSError, U7MapJsonError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    counts = document["counts"]
    print(
        f"Exported {counts['definitions']} definitions, "
        f"{counts['map_chunk_references']} chunk references, and "
        f"{counts['fixed_objects']} fixed objects."
    )
    print(f"Output: {args.output}")
    return 0


def cmd_map_render_json(args: SimpleNamespace) -> int:
    """Render a universal U7 map JSON without consulting U7 map data files."""
    from PIL import Image

    from titan.u7.map_json import (
        U7MapJsonError,
        load_u7_map_document,
        renderer_from_u7_map_document,
    )
    from titan.u7.palette import U7Palette

    try:
        document = load_u7_map_document(args.json_file)
        static_dir = args.static
        if not static_dir:
            static_dir, _ = install.resolve_u7_static_and_palette(document["game"])
        if not static_dir:
            raise U7MapJsonError("No graphics STATIC directory supplied or configured")

        palette_path = args.palette
        if not palette_path:
            _, palette_path = install.resolve_u7_static_and_palette(document["game"])
        if not palette_path:
            palette_path = os.path.join(static_dir, "PALETTES.FLX")

        palette = U7Palette.from_file(palette_path)
        renderer = renderer_from_u7_map_document(
            document,
            static_dir,
            allow_asset_mismatch=args.allow_asset_mismatch,
        )

        if args.superchunk is not None:
            if not 0 <= args.superchunk < 144:
                raise U7MapJsonError("Superchunk must be between 0 and 143")
            image = renderer.render_superchunk(
                args.superchunk,
                palette,
                view=args.view,
                grid=args.grid,
                grid_size=args.grid_size,
            )
            output = args.output or f"u7_json_sc{args.superchunk:02X}.png"
            os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
            image.save(output)
            print(f"Output: {image.width}x{image.height} -> {output}")
            return 0

        if not args.tiles_dir and not args.output:
            raise U7MapJsonError(
                "World render requires --tiles-dir, --output overview, or both"
            )
        if args.overview_scale < 1:
            raise U7MapJsonError("--overview-scale must be at least 1")

        logical_superchunk_pixels = 2048
        scaled_superchunk_pixels = logical_superchunk_pixels // args.overview_scale
        if scaled_superchunk_pixels < 1:
            raise U7MapJsonError("--overview-scale is too large")
        overview = None
        if args.output:
            overview = Image.new(
                "RGBA",
                (scaled_superchunk_pixels * 12, scaled_superchunk_pixels * 12),
                (0, 0, 0, 255),
            )
        if args.tiles_dir:
            os.makedirs(args.tiles_dir, exist_ok=True)

        for superchunk in range(144):
            image = renderer.render_superchunk(
                superchunk,
                palette,
                view=args.view,
                grid=args.grid,
                grid_size=args.grid_size,
            )
            if args.tiles_dir:
                tile_path = os.path.join(
                    args.tiles_dir, f"superchunk_{superchunk:03d}.png"
                )
                image.save(tile_path)
            if overview is not None:
                logical = image.crop((64, 64, 2112, 2112))
                if args.overview_scale != 1:
                    logical = logical.resize(
                        (scaled_superchunk_pixels, scaled_superchunk_pixels),
                        Image.Resampling.LANCZOS,
                    )
                overview.paste(
                    logical,
                    (
                        (superchunk % 12) * scaled_superchunk_pixels,
                        (superchunk // 12) * scaled_superchunk_pixels,
                    ),
                )
            if superchunk % 12 == 11:
                print(f"Rendered superchunk row {superchunk // 12 + 1}/12")

        if overview is not None:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            overview.save(args.output)
            print(f"Overview: {overview.width}x{overview.height} -> {args.output}")
        if args.tiles_dir:
            manifest = {
                "schema": "titan.u7.map-render-tiles",
                "schema_version": 1,
                "source_json": os.path.basename(args.json_file),
                "view": args.view,
                "tile_count": 144,
                "tile_pixels": [2176, 2176],
                "logical_origin": [64, 64],
                "logical_pixels": [2048, 2048],
                "filename_pattern": "superchunk_{decimal:03d}.png",
            }
            manifest_path = os.path.join(args.tiles_dir, "render_manifest.json")
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(manifest, handle, indent=2)
                handle.write("\n")
            print(f"Tiles: 144 -> {args.tiles_dir}")
    except (OSError, U7MapJsonError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_map_sample(args: SimpleNamespace) -> int:
    """Render a colour-sampled minimap of U7 world."""
    from titan.u7.map import U7MapRenderer, U7MapSampler
    from titan.u7.palette import U7Palette

    static_dir = args.static
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    palette_path = args.palette
    if not palette_path:
        _, palette_path = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not palette_path:
        palette_path = os.path.join(static_dir, "PALETTES.FLX")
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette not found: {palette_path}", file=sys.stderr)
        return 1

    pal = U7Palette.from_file(palette_path)
    renderer = U7MapRenderer(static_dir)

    scale = args.scale
    grid = getattr(args, "grid", False)
    grid_size = getattr(args, "grid_size", 1)

    # Build exclude set
    exclude: set[int] = set()
    if args.exclude_flags:
        tfa = renderer.tfa
        exclude_kw: dict[str, bool] = {}
        for flag_name in args.exclude_flags:
            exclude_kw[flag_name] = True
        exclude = tfa.build_exclude_set(**exclude_kw)
        print(f"Typeflag filter: {len(exclude)} shapes excluded")

    schunks: list[int] | None = None
    if args.superchunks:
        schunks = args.superchunks

    print(f"Sampling minimap at scale {scale} tiles/pixel ...")

    img = U7MapSampler.sample_map(
        renderer,
        pal,
        schunks=schunks,
        scale=scale,
        grid=grid,
        grid_size=grid_size,
        exclude_shapes=exclude,
    )

    out_path = args.output or f"u7_minimap_s{scale}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Output: {img.width}×{img.height} -> {out_path}")
    return 0


# Common exclude flag names (matches U7TypeFlags.build_exclude_set kwargs)
_EXCLUDE_FLAG_CHOICES = [
    "no_solid",
    "no_water",
    "no_animated",
    "no_sfx",
    "no_transparent",
    "no_translucent",
    "no_door",
    "no_barge",
    "no_light",
    "no_poisonous",
    "no_strange_movement",
    "no_building",
]


def map_create_cmd(
    output_root: Annotated[
        str,
        typer.Option(
            "--output-root",
            help="Required PATCH-like root where mapNN and shared u7chunks are written",
        ),
    ],
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help="Required secondary map number; 1 becomes map01, 16 becomes map10",
        ),
    ],
    from_json: Annotated[
        Optional[str],
        typer.Option(
            "--from-json",
            help="Universal U7 map JSON to materialize; omit for an empty map",
        ),
    ] = None,
    gamedat_root: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat-root",
            help="Optional explicit GAMEDAT-like root where an empty mapNN is created",
        ),
    ] = None,
    materialize_empty: Annotated[
        bool,
        typer.Option(
            "--materialize-empty/--directory-only",
            help="For empty maps, write a 73728-byte all-zero u7map",
        ),
    ] = False,
    overwrite_map: Annotated[
        bool,
        typer.Option(
            "--overwrite-map",
            help="Explicitly permit replacement of an existing mapNN namespace",
        ),
    ] = False,
    update_chunks: Annotated[
        bool,
        typer.Option(
            "--update-chunks",
            help="Explicitly permit appending missing definitions to existing u7chunks",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Validate and report planned native files without writing",
        ),
    ] = False,
) -> None:
    """Create an empty or JSON-backed native Exult map in explicit folders."""
    raise SystemExit(
        cmd_map_create(
            SimpleNamespace(
                output_root=output_root,
                map_num=map_num,
                from_json=from_json,
                gamedat_root=gamedat_root,
                materialize_empty=materialize_empty,
                overwrite_map=overwrite_map,
                update_chunks=update_chunks,
                dry_run=dry_run,
            )
        )
    )


def map_export_json_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC containing U7MAP, U7CHUNKS, U7IFIX, and graphics"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Ultima VII game data format"),
    ] = "bg",
    map_num: Annotated[
        int,
        typer.Option("--map-num", help="Map number; zero is the main world"),
    ] = 0,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output JSON path"),
    ] = "u7_map.json",
    include_fixed: Annotated[
        bool,
        typer.Option(
            "--include-fixed/--no-fixed",
            help="Include fixed IFIX objects required by terrain such as mountains",
        ),
    ] = True,
    include_shape_metadata: Annotated[
        bool,
        typer.Option(
            "--shape-metadata/--no-shape-metadata",
            help="Include dimensions and names for referenced shape frames",
        ),
    ] = True,
    wrap_x: Annotated[
        bool,
        typer.Option("--wrap-x/--no-wrap-x", help="Declare horizontal map wrapping"),
    ] = False,
    wrap_y: Annotated[
        bool,
        typer.Option("--wrap-y/--no-wrap-y", help="Declare vertical map wrapping"),
    ] = False,
    pretty: Annotated[
        bool,
        typer.Option("--pretty/--compact", help="Pretty or compact JSON output"),
    ] = False,
) -> None:
    """Export a complete U7 map to universal JSON."""
    raise SystemExit(
        cmd_map_export_json(
            SimpleNamespace(
                static=static,
                game=game,
                map_num=map_num,
                output=output,
                include_fixed=include_fixed,
                include_shape_metadata=include_shape_metadata,
                wrap_x=wrap_x,
                wrap_y=wrap_y,
                pretty=pretty,
            )
        )
    )


def map_render_json_cmd(
    json_file: Annotated[
        str,
        typer.Argument(help="Universal U7 map JSON file"),
    ],
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="STATIC graphics directory; map files are not read"
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="PALETTES.FLX path"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Overview PNG, or PNG for --superchunk"),
    ] = None,
    tiles_dir: Annotated[
        Optional[str],
        typer.Option(
            "--tiles-dir", help="Write 144 normal-renderer superchunk PNG tiles"
        ),
    ] = None,
    superchunk: Annotated[
        Optional[str],
        typer.Option("--superchunk", "--sc", help="Render only one superchunk"),
    ] = None,
    overview_scale: Annotated[
        int,
        typer.Option(
            "--overview-scale",
            help="Normal-render pixels per overview pixel; 8 gives 3072x3072",
        ),
    ] = 8,
    view: Annotated[
        Literal["classic", "flat", "steep"],
        typer.Option("--view", help="Map projection"),
    ] = "classic",
    grid: Annotated[
        bool,
        typer.Option("--grid/--no-grid", help="Draw chunk and superchunk grids"),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width"),
    ] = 1,
    allow_asset_mismatch: Annotated[
        bool,
        typer.Option(
            "--allow-asset-mismatch",
            help="Render despite graphics hashes differing from JSON provenance",
        ),
    ] = False,
) -> None:
    """Render universal map JSON without U7MAP, U7CHUNKS, or U7IFIX."""
    sc_int: int | None = None
    if superchunk is not None:
        try:
            sc_int = int(superchunk, 0)
        except ValueError:
            print(f"ERROR: Invalid superchunk integer: {superchunk}", file=sys.stderr)
            raise SystemExit(1)
    raise SystemExit(
        cmd_map_render_json(
            SimpleNamespace(
                json_file=json_file,
                static=static,
                palette=palette,
                output=output,
                tiles_dir=tiles_dir,
                superchunk=sc_int,
                overview_scale=overview_scale,
                view=view,
                grid=grid,
                grid_size=grid_size,
                allow_asset_mismatch=allow_asset_mismatch,
            )
        )
    )


def map_render_cmd(
    ctx: typer.Context,
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to base STATIC or a mod patch containing SHAPES.VGA "
            "and type data; sparse records inherit from the configured game "
            "base or a nearby STATIC; also supplies map data unless "
            "--map-root is used "
            "(default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option(
            "--game",
            help="Use the BG or SI config for defaults and sparse patch base assets",
        ),
    ] = "bg",
    map_root: Annotated[
        Optional[str],
        typer.Option(
            "--map-root",
            help=(
                "Optional separate root containing U7CHUNKS and U7MAP/U7IFIX "
                "map data; defaults to the STATIC argument"
            ),
        ),
    ] = None,
    superchunk: Annotated[
        Optional[str],
        typer.Option(
            "--superchunk",
            "--sc",
            help="Superchunk number 0–143 (decimal or hex, e.g. 85 or 0x55)",
        ),
    ] = None,
    chunk_x0: Annotated[
        Optional[int],
        typer.Option("--cx0", help="Start chunk X (0–191)"),
    ] = None,
    chunk_y0: Annotated[
        Optional[int],
        typer.Option("--cy0", help="Start chunk Y (0–191)"),
    ] = None,
    chunk_x1: Annotated[
        Optional[int],
        typer.Option("--cx1", help="End chunk X (inclusive)"),
    ] = None,
    chunk_y1: Annotated[
        Optional[int],
        typer.Option("--cy1", help="End chunk Y (inclusive)"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help=(
                "Path to PALETTES.FLX (default: configured game palette, "
                "inferred patch base, then selected STATIC)"
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    view: Annotated[
        Optional[str],
        typer.Option("--view", help="Projection view: classic, flat, steep"),
    ] = None,
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat", help="Path to gamedat/ directory for IREG dynamic objects"
        ),
    ] = None,
    grid: Annotated[
        bool,
        typer.Option(
            "--grid/--no-grid",
            help="Overlay chunk grid (blue) and superchunk "
            "borders (red) with coordinate labels",
        ),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width in pixels"),
    ] = 1,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Render the entire world map (shorthand for "
            "--cx0 0 --cy0 0 --cx1 191 --cy1 191)",
        ),
    ] = False,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option(
            "--exclude",
            help=f"Exclude shapes by TFA flag. "
            f"Repeatable. Choices: {', '.join(_EXCLUDE_FLAG_CHOICES)}",
        ),
    ] = None,
    max_lift: Annotated[
        Optional[int],
        typer.Option(
            "--max-lift",
            help="Maximum object lift (tz) to render (0-15). "
            "Objects above this lift are hidden.",
        ),
    ] = None,
    highlight_tile_rect: Annotated[
        Optional[list[str]],
        typer.Option(
            "--highlight-tile-rect",
            "--hrect",
            help=(
                "Highlight tile rectangle (repeatable): "
                "tx0,ty0,tx1,ty1,#RRGGBB[,label] or #RRGGBBAA[,label]"
            ),
        ),
    ] = None,
    highlight_width: Annotated[
        int,
        typer.Option(
            "--highlight-width",
            help="Highlight outline width in pixels",
        ),
    ] = 3,
    highlight_lift: Annotated[
        int,
        typer.Option(
            "--highlight-lift",
            help="Projection lift value for highlighted rectangles",
        ),
    ] = 0,
    highlight_fill_alpha: Annotated[
        int,
        typer.Option(
            "--highlight-fill-alpha",
            help="Highlight fill alpha (0-255)",
        ),
    ] = 128,
    highlight_labels: Annotated[
        bool,
        typer.Option(
            "--highlight-labels/--no-highlight-labels",
            help="Draw labels on highlighted rectangles",
        ),
    ] = True,
    zone_profile: Annotated[
        Optional[str],
        typer.Option(
            "--zone-profile",
            help=(
                "Load named zone profile overlay data and convert it to "
                "highlight rectangles (e.g. si_zones, bg_zones)"
            ),
        ),
    ] = None,
    zone_id: Annotated[
        Optional[list[str]],
        typer.Option(
            "--zone-id",
            help=(
                "Zone ID to include from --zone-profile. Repeatable. "
                "Examples: --zone-id 3 --zone-id 13 or --zone-id A"
            ),
        ),
    ] = None,
    all_zones: Annotated[
        bool,
        typer.Option(
            "--all-zones",
            help=(
                "Include all zones from --zone-profile. "
                "Default behavior when no --zone-id is supplied"
            ),
        ),
    ] = False,
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help=(
                "Map number: 0 = default world map (root STATIC), "
                "1+ = mapNN/ inside the map root and gamedat (default: 0)"
            ),
        ),
    ] = 0,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Open the map-render wizard using supplied options as defaults",
        ),
    ] = False,
) -> None:
    """Render a U7 map to PNG. With no render options, open the guided wizard."""
    wizard_mode = interactive or not any(
        source is not None and source.name == "COMMANDLINE"
        for name in ctx.params
        if name not in {"game", "interactive"}
        for source in [ctx.get_parameter_source(name)]
    )
    if full:
        chunk_x0, chunk_y0, chunk_x1, chunk_y1 = 0, 0, 191, 191
    if not wizard_mode and superchunk is None and chunk_x0 is None:
        print(
            "ERROR: Specify --superchunk N, --full, or --cx0/--cy0 chunk range.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    sc_int: int | None = None
    if superchunk is not None:
        try:
            sc_int = int(superchunk, 0)
        except ValueError:
            print(
                f"ERROR: --superchunk '{superchunk}' is not a valid integer.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    parsed_highlights: list[
        tuple[int, int, int, int, tuple[int, int, int, int], str]
    ] = []
    if highlight_tile_rect:
        for raw in highlight_tile_rect:
            try:
                parsed_highlights.append(_parse_highlight_tile_rect(raw))
            except ValueError as exc:
                print(f"ERROR: --highlight-tile-rect '{raw}': {exc}", file=sys.stderr)
                raise SystemExit(1)

    if zone_profile is None and (zone_id or all_zones):
        print("ERROR: --zone-id/--all-zones requires --zone-profile.", file=sys.stderr)
        raise SystemExit(1)

    if zone_profile:
        from titan.u7.zones import (
            U7ZoneProfileError,
            build_zone_highlight_rects,
        )

        try:
            profile_rects = build_zone_highlight_rects(
                zone_profile,
                zone_ids=zone_id,
                include_all=all_zones,
            )
        except U7ZoneProfileError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)

        parsed_highlights.extend(profile_rects)
        print(f"Zone profile '{zone_profile}' -> {len(profile_rects)} rectangle(s)")

    render_args = SimpleNamespace(
        wizard_scope="3"
        if full
        else "1"
        if sc_int is not None
        else "2"
        if chunk_x0 is not None
        else None,
        game=game,
        static=static,
        map_root=map_root,
        superchunk=sc_int,
        chunk_x0=chunk_x0 or 0,
        chunk_y0=chunk_y0 or 0,
        chunk_x1=chunk_x1,
        chunk_y1=chunk_y1,
        palette=palette,
        output=output,
        view=view,
        gamedat=gamedat,
        grid=grid,
        grid_size=grid_size,
        exclude_flags=exclude,
        max_lift=max_lift,
        map_num=map_num,
        highlight_rects=parsed_highlights,
        highlight_width=highlight_width,
        highlight_lift=highlight_lift,
        highlight_fill_alpha=highlight_fill_alpha,
        highlight_labels=highlight_labels,
    )
    if wizard_mode:
        from titan.u7.map_wizard import run_wizard

        raise SystemExit(run_wizard(render_args))
    raise SystemExit(cmd_map_render(render_args))


def map_sample_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to PALETTES.FLX (default: STATIC/PALETTES.FLX)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    scale: Annotated[
        int,
        typer.Option(
            "--scale", help="Tiles per output pixel (1=full, 4=768px, 8=384px)"
        ),
    ] = 4,
    grid: Annotated[
        bool,
        typer.Option(
            "--grid/--no-grid",
            help="Overlay chunk grid (blue, scale<=2) and "
            "superchunk grid (red) with coordinate labels",
        ),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width in pixels"),
    ] = 1,
    superchunks: Annotated[
        Optional[list[int]],
        typer.Option("--sc", help="Only sample these superchunks (repeatable)"),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option("--exclude", help="Exclude shapes by TFA flag (repeatable)"),
    ] = None,
) -> None:
    """Render a colour-sampled U7 world minimap to PNG."""
    raise SystemExit(
        cmd_map_sample(
            SimpleNamespace(
                game=game,
                static=static,
                palette=palette,
                output=output,
                scale=scale,
                grid=grid,
                grid_size=grid_size,
                superchunks=superchunks,
                exclude_flags=exclude,
            )
        )
    )


def map_inventory_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Optional[Literal["bg", "si"]],
        typer.Option("--game", help="Use config section for BG or SI (default: bg)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output folder (default: u7data/map-inventory/<game>-map<NN>)",
        ),
    ] = None,
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num", help="Map number: 0 = world map, 1+ = mapNN/ inside STATIC"
        ),
    ] = 0,
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat",
            help="Count movable objects from this GAMEDAT folder instead of INITGAME.DAT",
        ),
    ] = None,
    initgame: Annotated[
        Optional[str],
        typer.Option(
            "--initgame",
            help="INITGAME.DAT to read movable objects from (default: STATIC/INITGAME.DAT)",
        ),
    ] = None,
    no_ireg: Annotated[
        bool,
        typer.Option(
            "--no-ireg",
            help="Skip movable objects (u7ireg); count terrain, chunk and fixed objects only",
        ),
    ] = False,
    contents: Annotated[
        bool,
        typer.Option(
            "--contents", help="Also count objects inside containers and bodies"
        ),
    ] = False,
    no_previews: Annotated[
        bool,
        typer.Option("--no-previews", help="Skip sprite PNGs and index.html"),
    ] = False,
    palette: Annotated[
        int,
        typer.Option("--palette", help="PALETTES.FLX index for sprite previews"),
    ] = 0,
    base_static: Annotated[
        Optional[str],
        typer.Option("--base-static", help="Original STATIC for a mod patch"),
    ] = None,
    patch: Annotated[
        Optional[str],
        typer.Option("--patch", help="Mod patch overriding the base STATIC"),
    ] = None,
    mod_data: Annotated[
        Optional[str],
        typer.Option("--mod-data", help="Mod textmsg.txt and shape_info.txt directory"),
    ] = None,
    text: Annotated[
        Optional[str],
        typer.Option("--text", help="Path to TEXT.FLX for shape names"),
    ] = None,
    superchunk: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Limit to a superchunk, hex or decimal (repeatable): 0x55"
        ),
    ] = None,
    tile_rect: Annotated[
        Optional[list[str]],
        typer.Option(
            "--tile-rect", help="Limit to a tile rectangle tx0,ty0,tx1,ty1 (repeatable)"
        ),
    ] = None,
    cx0: Annotated[
        Optional[int], typer.Option("--cx0", help="Limit to chunks from X (0-191)")
    ] = None,
    cy0: Annotated[
        Optional[int], typer.Option("--cy0", help="Limit to chunks from Y (0-191)")
    ] = None,
    cx1: Annotated[
        Optional[int],
        typer.Option("--cx1", help="Limit to chunks to X (inclusive; default cx0)"),
    ] = None,
    cy1: Annotated[
        Optional[int],
        typer.Option("--cy1", help="Limit to chunks to Y (inclusive; default cy0)"),
    ] = None,
) -> None:
    """Inventory every ground tile and object a U7 map uses, ranked by placements.

    Counts flat ground from the chunk templates, objects stored in chunk
    templates, fixed objects (U7IFIX) and the starting world's movable
    objects (u7ireg in INITGAME.DAT, or a GAMEDAT folder). Writes
    objects.csv, flats.csv, shapes.csv, summary.json and, unless
    --no-previews, sprite PNGs with a filterable index.html.

    --sc, --tile-rect and --cx0/--cy0/--cx1/--cy1 limit the inventory to an
    area (several combine) and add placements.csv, listing every placement
    in it. Objects count when their footprint overlaps the area.

    \b
    Examples:
      titan u7 map-inventory
      titan u7 map-inventory --sc 0x55
      titan u7 map-inventory --cx0 60 --cy0 72 --cx1 62 --cy1 74
      titan u7 map-inventory --game si --contents
      titan u7 map-inventory STATIC/ --gamedat gamedat/ -o inventory/
    """
    from titan.u7.map_inventory import (
        build_u7_map_inventory,
        chunk_rect,
        superchunk_rect,
        write_u7_map_inventory,
    )
    from titan.u7.world import parse_rectangle

    area: list[tuple[int, int, int, int]] = []
    labels: list[str] = []
    try:
        for raw in superchunk or []:
            sc = int(raw, 0)
            if not 0 <= sc < 144:
                raise ValueError(f"Superchunk must be 0-143 (0x00-0x8F): {raw}")
            area.append(superchunk_rect(sc))
            labels.append(f"sc{sc:02X}")
        for raw in tile_rect or []:
            rect = parse_rectangle(raw)
            area.append(rect)
            labels.append("t{}_{}_{}_{}".format(*rect))
        if cx0 is not None or cy0 is not None:
            if cx0 is None or cy0 is None:
                raise ValueError("Give both --cx0 and --cy0")
            x1 = cx0 if cx1 is None else cx1
            y1 = cy0 if cy1 is None else cy1
            if not all(0 <= v <= 191 for v in (cx0, cy0, x1, y1)):
                raise ValueError("Chunk coordinates must be 0-191")
            area.append(chunk_rect(cx0, cy0, x1, y1))
            labels.append(
                f"c{min(cx0, x1)}_{min(cy0, y1)}_{max(cx0, x1)}_{max(cy0, y1)}"
            )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

    game = game or "bg"
    configured_static, _ = install.resolve_u7_static_and_palette(game)
    static_dir = static or configured_static
    if not static_dir:
        print(
            "ERROR: Provide a STATIC directory or configure one in titan.toml",
            file=sys.stderr,
        )
        raise SystemExit(1)
    text_flx = text or (
        None if patch else install.resolve_u7_text_flx(game, static_dir)
    )
    try:
        inventory = build_u7_map_inventory(
            static_dir,
            game=game,
            map_num=map_num,
            gamedat_dir=gamedat,
            initgame=initgame,
            include_ireg=not no_ireg,
            include_contents=contents,
            base_static=base_static,
            patch_dir=patch,
            mod_data_dir=mod_data,
            text_flx_path=text_flx,
            area=area or None,
        )
        stem = f"{game}-map{map_num:02d}" + "".join(f"-{label}" for label in labels)
        outdir = Path(output or Path("u7data") / "map-inventory" / stem)
        summary = write_u7_map_inventory(
            inventory, outdir, previews=not no_previews, palette_index=palette
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

    objects, flats = summary["objects"], summary["flats"]
    print("Sources: " + "; ".join(f"{k}: {v}" for k, v in summary["sources"].items()))
    print(
        f"Objects: {objects['placements']:,} placements, {objects['shapes']} shapes, "
        f"{objects['shape_frames']} shape:frames "
        f"({', '.join(f'{k} {v:,}' for k, v in objects['by_source'].items())})"
    )
    print(
        "  coverage by top shapes: "
        + ", ".join(
            f"{k.replace('top_', '')}: {v}%"
            for k, v in objects["coverage_by_top_shapes_pct"].items()
        )
    )
    print(
        f"Ground: {flats['cells']:,} cells, {flats['shapes']} flat shapes, {flats['shape_frames']} shape:frames"
    )
    if contents:
        print(f"Container contents: {summary['contents']:,}")
    if area:
        print(
            f"Area: {len(inventory.placements):,} placements listed in placements.csv"
        )
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"Wrote {outdir}")
