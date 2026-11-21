"""``titan uw2`` LEV.ARK map extract, verify, grid, render and 3D commands."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._cli_aliases import TextOrJson
from titan._config import DEFAULT_OUTPUT, export_output
from titan._meta import meta
from titan.uw2.cli._common import (
    CeilingSourceOption,
    GameDirOption,
    SlotsOption,
    ZScaleOption,
    _require_file,
    _require_uw2_game_directory,
    _uw2_data_file,
)
from titan.uw2.grid_render import COORDINATE_MODES, render_grids_direct
from titan.uw2.map3d import (
    BACKENDS,
    DEFAULT_ZOOM,
    DOWNSAMPLE_FILTERS,
    TEXTURE_FILTERS,
    export_map_scene,
    render_map_scene,
    render_stacked_worlds,
)
from titan.uw2.map_pipeline import (
    export_render_assets,
    extract_maps,
    render_maps,
    render_maps_direct,
    verify_maps,
)
from titan.uw2.scene3d import (
    CEILING_SOURCES,
    DEFAULT_Z_SCALE,
    UW2SceneError,
    parse_tile_region,
)
from titan.errors import exit_code


def cmd_map_extract(args: SimpleNamespace) -> int:
    """Decode LEV.ARK into renderer-ready level JSON."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    lev_path = _uw2_data_file("LEV.ARK", game_directory)
    if not _require_file(lev_path, "map archive"):
        return 1
    try:
        summaries = extract_maps(
            game_directory,
            args.output,
            slots=args.slots,
            write_decoded_blocks=args.write_decoded_blocks,
        )
    except (OSError, KeyError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    typer.echo(f"Extracted {len(summaries)} UU2 maps: {Path(args.output)}")
    return 0


def cmd_map_verify(args: SimpleNamespace) -> int:
    """Smoke-check LEV.ARK block shapes and decode every populated slot."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    lev_path = _uw2_data_file("LEV.ARK", game_directory)
    if not _require_file(lev_path, "map archive"):
        return 1
    try:
        report = verify_maps(game_directory)
    except (OSError, KeyError, ValueError, struct.error) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)

    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        typer.echo(f"Wrote UU2 map verification report: {destination}")

    if args.json_output:
        typer.echo(json.dumps(report, indent=2))
    else:
        slots = report["populated_level_slots"]
        typer.echo(f"LEV.ARK: {report['lev_ark']}")
        typer.echo(f"Header prefix: {report['header_prefix_hex']}")
        typer.echo(
            f"Blocks: {report['block_count']} total, "
            f"{report['available_blocks']} available"
        )
        typer.echo(f"Populated level slots: {len(slots)}")
        typer.echo("Slots: " + ", ".join(str(slot) for slot in slots))
        typer.echo(
            "Observed 0x7c06 markers: "
            + ", ".join(
                f"{marker} x{count}"
                for marker, count in report["level_markers"].items()
            )
        )

    if not report["ok"]:
        typer.echo("", err=True)
        typer.echo("Errors:", err=True)
        for error_text in report["errors"]:
            typer.echo(f"- {error_text}", err=True)
        return 1

    typer.echo("Smoke checks passed.")
    return 0


def cmd_map_grid(args: SimpleNamespace) -> int:
    """Render flat top-down diagnostic grids from original files."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    lev_path = _uw2_data_file("LEV.ARK", game_directory)
    if not _require_file(lev_path, "map archive"):
        return 1
    slots = args.slots if args.slots else [0]
    options = {
        key: value
        for key, value in vars(args).items()
        if key not in {"gamedir", "output", "slots"}
    }
    try:
        written = render_grids_direct(
            game_directory, args.output, slots=slots, **options
        )
    except (OSError, KeyError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    for path in written:
        typer.echo(f"Rendered UU2 grid: {path}")
    return 0


def cmd_map_3d_render(args: SimpleNamespace) -> int:
    """Render one textured map scene from camera presets."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    slots = args.slot if isinstance(args.slot, (list, tuple)) else [args.slot]
    written: list[Path] = []
    try:
        for slot in slots:
            written.extend(
                render_map_scene(
                    game_directory,
                    args.output,
                    slot=slot,
                    region=parse_tile_region(args.region),
                    views=args.views,
                    size=args.size,
                    width=args.width,
                    height=args.height,
                    include_ceilings=args.include_ceilings,
                    include_sprites=not args.no_sprites,
                    model_scale=args.model_scale,
                    sprite_scale=args.sprite_scale,
                    tick=args.tick,
                    ceiling_source=args.ceiling_source,
                    z_scale=args.z_scale,
                    zoom=args.zoom,
                    fit_margin=args.fit_margin,
                    supersample=args.supersample,
                    downsample_filter=args.downsample_filter,
                    texture_filter=args.texture_filter,
                    texture_scale=args.texture_scale,
                    backend=args.backend,
                    name_files=args.name_files,
                    plan_scale=getattr(args, "plan_scale", 1),
                    native=getattr(args, "native", False),
                )
            )
    except (OSError, KeyError, ValueError, UW2SceneError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    for path in written:
        typer.echo(f"Rendered UU2 3D map: {path}")
    return 0


def cmd_map_stack(args: SimpleNamespace) -> int:
    """Render each world's levels as one vertically stacked cutaway."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    lev_path = _uw2_data_file("LEV.ARK", game_directory)
    if not _require_file(lev_path, "map archive"):
        return 1
    try:
        written = render_stacked_worlds(
            game_directory,
            args.output,
            worlds=args.worlds,
            max_levels=args.max_levels,
            views=args.views,
            size=args.size,
            width=args.width,
            height=args.height,
            include_ceilings=args.include_ceilings,
            include_sprites=args.include_sprites,
            stack_gap=args.stack_gap,
            stagger_x=args.stagger_x,
            stagger_y=args.stagger_y,
            ceiling_source=args.ceiling_source,
            z_scale=args.z_scale,
            zoom=args.zoom,
            fit_margin=args.fit_margin,
            supersample=args.supersample,
            downsample_filter=args.downsample_filter,
            texture_filter=args.texture_filter,
            texture_scale=args.texture_scale,
            backend=args.backend,
            tick=args.tick,
        )
    except (OSError, KeyError, ValueError, UW2SceneError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    for path in written:
        typer.echo(f"Rendered UU2 stacked world: {path}")
    return 0


def cmd_map_3d_export(args: SimpleNamespace) -> int:
    """Export one textured map scene as GLB with individual object nodes."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    try:
        written = export_map_scene(
            game_directory,
            args.output,
            slot=args.slot,
            region=parse_tile_region(args.region),
            include_ceilings=args.include_ceilings,
            include_sprites=not args.no_sprites,
            model_scale=args.model_scale,
            sprite_scale=args.sprite_scale,
            tick=args.tick,
            ceiling_source=args.ceiling_source,
            z_scale=args.z_scale,
            name_files=args.name_files,
        )
    except (OSError, KeyError, ValueError, UW2SceneError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    typer.echo(f"Exported UU2 3D map: {written}")
    return 0


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render directly from original archives; intermediates are optional."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    output = Path(args.output)
    workdir = Path(args.workdir or output / "_map_data")
    reuse_workdir = bool(getattr(args, "reuse_workdir", False))
    keep_intermediates = bool(getattr(args, "keep_intermediates", False))
    render_options = {
        key: value
        for key, value in vars(args).items()
        if key
        not in {
            "gamedir",
            "output",
            "workdir",
            "slots",
            "reuse_workdir",
            "keep_intermediates",
        }
    }
    try:
        if reuse_workdir:
            written = render_maps(
                workdir,
                output,
                slots=args.slots,
                **render_options,
            )
        else:
            if keep_intermediates:
                summaries = extract_maps(game_directory, workdir, slots=args.slots)
                if len(summaries) != len(set(args.slots)):
                    missing = sorted(
                        set(args.slots) - {row["slot_index"] for row in summaries}
                    )
                    raise ValueError(f"unavailable UU2 map slots: {missing}")
                counts = export_render_assets(game_directory, workdir)
                typer.echo(
                    "Kept map intermediates: "
                    + ", ".join(f"{name}={count}" for name, count in counts.items())
                )
            written = render_maps_direct(
                game_directory,
                output,
                slots=args.slots,
                **render_options,
            )
    except (OSError, KeyError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    for path in written:
        typer.echo(f"Rendered UU2 map: {path}")
    return 0


def _validate_view_options(
    *,
    downsample_filter: str | None = None,
    texture_filter: str | None = None,
    backend: str | None = None,
    ceiling_source: str | None = None,
) -> None:
    """Reject bad choices as usage errors rather than runtime failures."""
    checks = (
        ("--downsample-filter", downsample_filter, tuple(DOWNSAMPLE_FILTERS)),
        ("--texture-filter", texture_filter, TEXTURE_FILTERS),
        ("--backend", backend, BACKENDS),
        ("--ceiling-source", ceiling_source, CEILING_SOURCES),
    )
    for hint, value, allowed in checks:
        if value is not None and value not in allowed:
            raise typer.BadParameter(
                f"must be one of {', '.join(allowed)}", param_hint=hint
            )


@meta(results=("files",), params={"output": "output-dir"})
def map_extract_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output-dir", help="Extraction directory")
    ],
    slots: SlotsOption = None,
    write_decoded_blocks: Annotated[
        bool,
        typer.Option("--write-decoded-blocks", help="Also preserve decoded ARK blocks"),
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Decode LEV.ARK maps, objects, automap data, notes, and lighting."""
    raise SystemExit(cmd_map_extract(SimpleNamespace(**locals())))


@meta(
    results=("json", "text"),
    params={"output_format": "format", "output": "output-file"},
)
def map_verify_cmd(
    output_format: Annotated[
        TextOrJson,
        typer.Option(
            "--format", help="Output format: text (default) or json (the full report)"
        ),
    ] = TextOrJson.text,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Optional JSON report path")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Smoke-check LEV.ARK block shapes and decode every populated map slot."""
    json_output = output_format is TextOrJson.json
    raise SystemExit(
        cmd_map_verify(
            SimpleNamespace(json_output=json_output, output=output, gamedir=gamedir)
        )
    )


@meta(results=("files",), params={"output": "output-dir"})
def map_3d_render_cmd(
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help=DEFAULT_OUTPUT.strip())
    ] = None,
    slot: Annotated[
        Optional[list[int]],
        typer.Option("--slot", help="Zero-based LEV.ARK map slot; repeat as needed"),
    ] = None,
    region: Annotated[
        Optional[str],
        typer.Option("--region", help="Inclusive tile bounds: x1,y1,x2,y2"),
    ] = None,
    views: Annotated[
        Optional[list[str]],
        typer.Option(
            "--view",
            help="iso-ne/nw/se/sw, low-ne, low-nw, south, low-s, top, or plan",
        ),
    ] = None,
    size: Annotated[int, typer.Option("--size", help="Square PNG size")] = 1200,
    plan_scale: Annotated[
        int,
        typer.Option(
            "--plan-scale",
            help="Tile size for self-sizing views, in multiples of 64 pixels",
        ),
    ] = 1,
    native: Annotated[
        bool,
        typer.Option(
            "--native",
            help="Size every view so no floor tile falls below native resolution",
        ),
    ] = False,
    width: Annotated[
        Optional[int], typer.Option("--width", help="Override --size horizontally")
    ] = None,
    height: Annotated[
        Optional[int], typer.Option("--height", help="Override --size vertically")
    ] = None,
    include_ceilings: Annotated[bool, typer.Option("--include-ceilings")] = False,
    no_sprites: Annotated[bool, typer.Option("--no-sprites")] = False,
    model_scale: Annotated[float, typer.Option("--model-scale")] = 1.0,
    sprite_scale: Annotated[float, typer.Option("--sprite-scale")] = 1.0,
    tick: Annotated[int, typer.Option("--tick", help="ANIMO animation tick")] = 0,
    ceiling_source: CeilingSourceOption = "runtime",
    z_scale: ZScaleOption = DEFAULT_Z_SCALE,
    zoom: Annotated[
        float, typer.Option("--zoom", help="Above 1.0 crops closer in")
    ] = DEFAULT_ZOOM,
    fit_margin: Annotated[
        float, typer.Option("--fit-margin", help="Extra framing around the map")
    ] = 1.0,
    supersample: Annotated[
        int, typer.Option("--supersample", help="Render at N x, then downsample")
    ] = 1,
    downsample_filter: Annotated[
        str, typer.Option("--downsample-filter", help="lanczos, nearest, or box")
    ] = "lanczos",
    texture_filter: Annotated[
        str,
        typer.Option("--texture-filter", help="linear, or nearest for crisp pixels"),
    ] = "linear",
    texture_scale: Annotated[
        int, typer.Option("--texture-scale", help="Nearest pre-scale for textures")
    ] = 1,
    backend: Annotated[
        str, typer.Option("--backend", help="pyvista, software, or auto")
    ] = "auto",
    name_files: Annotated[bool, typer.Option("--name-files")] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Render textured UU2 tile geometry and individually placed objects."""
    output = export_output(output, "uw2", "map-3d-render")
    views = views or ["iso-ne", "top"]
    slot = slot if slot else [0]
    _validate_view_options(
        downsample_filter=downsample_filter,
        texture_filter=texture_filter,
        backend=backend,
        ceiling_source=ceiling_source,
    )
    raise SystemExit(cmd_map_3d_render(SimpleNamespace(**locals())))


@meta(results=("files",), params={"output": "output-dir"})
def map_stack_cmd(
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help=DEFAULT_OUTPUT.strip())
    ] = None,
    worlds: Annotated[
        Optional[list[str]],
        typer.Option("--world", help="World-name slug filter; repeat as needed"),
    ] = None,
    max_levels: Annotated[
        Optional[int],
        typer.Option("--max-levels", help="Only the first N levels per world"),
    ] = None,
    views: Annotated[
        Optional[list[str]],
        typer.Option("--view", help="iso-ne/nw/se/sw, low-ne, low-nw, or top"),
    ] = None,
    size: Annotated[int, typer.Option("--size", help="Square PNG size")] = 2400,
    width: Annotated[
        Optional[int], typer.Option("--width", help="Override --size horizontally")
    ] = None,
    height: Annotated[
        Optional[int], typer.Option("--height", help="Override --size vertically")
    ] = None,
    stack_gap: Annotated[
        float, typer.Option("--stack-gap", help="Vertical distance between levels")
    ] = 7.0,
    stagger_x: Annotated[float, typer.Option("--stagger-x")] = 0.0,
    stagger_y: Annotated[float, typer.Option("--stagger-y")] = 0.0,
    include_ceilings: Annotated[bool, typer.Option("--include-ceilings")] = False,
    include_sprites: Annotated[
        bool, typer.Option("--include-sprites", help="Also place object billboards")
    ] = False,
    tick: Annotated[int, typer.Option("--tick", help="ANIMO animation tick")] = 0,
    ceiling_source: CeilingSourceOption = "runtime",
    z_scale: ZScaleOption = DEFAULT_Z_SCALE,
    zoom: Annotated[float, typer.Option("--zoom")] = DEFAULT_ZOOM,
    fit_margin: Annotated[float, typer.Option("--fit-margin")] = 1.15,
    supersample: Annotated[int, typer.Option("--supersample")] = 1,
    downsample_filter: Annotated[
        str, typer.Option("--downsample-filter", help="lanczos, nearest, or box")
    ] = "lanczos",
    texture_filter: Annotated[
        str, typer.Option("--texture-filter", help="linear or nearest")
    ] = "nearest",
    texture_scale: Annotated[int, typer.Option("--texture-scale")] = 4,
    backend: Annotated[
        str, typer.Option("--backend", help="pyvista, software, or auto")
    ] = "auto",
    gamedir: GameDirOption = None,
) -> None:
    """Render each world's levels as one vertically stacked cutaway."""
    output = export_output(output, "uw2", "map-stack")
    views = views or ["iso-ne"]
    _validate_view_options(
        downsample_filter=downsample_filter,
        texture_filter=texture_filter,
        backend=backend,
        ceiling_source=ceiling_source,
    )
    raise SystemExit(cmd_map_stack(SimpleNamespace(**locals())))


@meta(results=("files",), params={"output": "output-dir"})
def map_3d_export_cmd(
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help=DEFAULT_OUTPUT.strip())
    ] = None,
    slot: Annotated[
        int, typer.Option("--slot", help="Zero-based LEV.ARK map slot")
    ] = 0,
    region: Annotated[
        Optional[str],
        typer.Option("--region", help="Inclusive tile bounds: x1,y1,x2,y2"),
    ] = None,
    include_ceilings: Annotated[bool, typer.Option("--include-ceilings")] = False,
    no_sprites: Annotated[bool, typer.Option("--no-sprites")] = False,
    model_scale: Annotated[float, typer.Option("--model-scale")] = 1.0,
    sprite_scale: Annotated[float, typer.Option("--sprite-scale")] = 1.0,
    tick: Annotated[int, typer.Option("--tick", help="ANIMO animation tick")] = 0,
    ceiling_source: CeilingSourceOption = "runtime",
    z_scale: ZScaleOption = DEFAULT_Z_SCALE,
    name_files: Annotated[bool, typer.Option("--name-files")] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Export textured UU2 map GLB; retain every placed item as named nodes."""
    output = export_output(output, "uw2", "map-3d-export")
    _validate_view_options(ceiling_source=ceiling_source)
    raise SystemExit(cmd_map_3d_export(SimpleNamespace(**locals())))


@meta(results=("files",), params={"output": "output-dir", "workdir": "working-dir"})
def map_render_cmd(
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output-dir", help="Rendered PNG directory" + DEFAULT_OUTPUT
        ),
    ] = None,
    slots: SlotsOption = None,
    workdir: Annotated[
        Optional[str],
        typer.Option("--workdir", help="Optional intermediate data directory"),
    ] = None,
    keep_intermediates: Annotated[
        bool,
        typer.Option(
            "--keep-intermediates",
            help="Also write extracted JSON and texture PNG files",
        ),
    ] = False,
    reuse_workdir: Annotated[
        bool,
        typer.Option(
            "--reuse-workdir",
            help="Use legacy extracted workdir instead of original archives",
        ),
    ] = False,
    tile_size: Annotated[int, typer.Option("--tile-size")] = 64,
    lift_pixels: Annotated[float, typer.Option("--lift-pixels")] = 4.0,
    floor_height_per_lift: Annotated[
        float, typer.Option("--floor-height-per-lift")
    ] = 8.0,
    wall_height_scale: Annotated[float, typer.Option("--wall-height-scale")] = 1.0,
    max_wall_height: Annotated[float, typer.Option("--max-wall-height")] = 24.0,
    no_obstruction_clip: Annotated[bool, typer.Option("--no-obstruction-clip")] = False,
    margin: Annotated[int, typer.Option("--margin")] = 96,
    background: Annotated[str, typer.Option("--background")] = "#08090b",
    orientation: Annotated[
        str, typer.Option("--orientation", help="display or raw")
    ] = "display",
    floor_texture_transform: Annotated[
        str,
        typer.Option(
            "--floor-texture-transform",
            help="auto, none, flip-y, flip-x, or rotate-180",
        ),
    ] = "auto",
    no_doors: Annotated[bool, typer.Option("--no-doors")] = False,
    no_flat_objects: Annotated[bool, typer.Option("--no-flat-objects")] = False,
    no_objects: Annotated[
        bool,
        typer.Option("--no-objects", help="Do not draw OBJECTS.GR or ANIMO.GR sprites"),
    ] = False,
    tick: Annotated[
        int,
        typer.Option("--tick", help="Animation tick used to select ANIMO.GR frames"),
    ] = 0,
    object_scale: Annotated[
        float,
        typer.Option(
            "--object-scale",
            help="Sprite scale at 64-pixel tiles; scales with --tile-size",
        ),
    ] = 2.0,
    no_models: Annotated[
        bool,
        typer.Option("--no-models", help="Do not draw model-based common objects"),
    ] = False,
    model_style: Annotated[
        str,
        typer.Option(
            "--model-style",
            help="icons (OBJECTS.GR, default) or geometry (UW2.EXE)",
        ),
    ] = "icons",
    model_icon_scale: Annotated[
        float,
        typer.Option(
            "--model-icon-scale",
            help="Scale for OBJECTS.GR furniture icons at 64-pixel tiles",
        ),
    ] = 2.0,
    model_scale: Annotated[
        float,
        typer.Option(
            "--model-scale",
            help="Scale for executable model geometry",
        ),
    ] = 1.0,
    solid_fill: Annotated[
        str,
        typer.Option("--solid-fill", help="none, between, adjacent, interior, or bbox"),
    ] = "none",
    solid_fill_texture: Annotated[
        str, typer.Option("--solid-fill-texture", help="wall or floor")
    ] = "wall",
    solid_fill_brightness: Annotated[
        float, typer.Option("--solid-fill-brightness")
    ] = 0.42,
    no_lighting: Annotated[bool, typer.Option("--no-lighting")] = False,
    min_brightness: Annotated[float, typer.Option("--min-brightness")] = 0.35,
    debug_grid: Annotated[bool, typer.Option("--debug-grid")] = False,
    grid_label_step: Annotated[int, typer.Option("--grid-label-step")] = 1,
    grid_coordinate_mode: Annotated[
        str, typer.Option("--grid-coordinate-mode", help="display, raw, or both")
    ] = "display",
    name_files: Annotated[bool, typer.Option("--name-files")] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Render UU2 levels from original files using the U7-style cutaway pipeline."""
    output = export_output(output, "uw2", "map-render")
    slots = slots or [0]
    if keep_intermediates and reuse_workdir:
        raise typer.BadParameter(
            "cannot combine with --reuse-workdir", param_hint="--keep-intermediates"
        )
    if tick < 0:
        raise typer.BadParameter("must be non-negative", param_hint="--tick")
    if object_scale <= 0:
        raise typer.BadParameter("must be positive", param_hint="--object-scale")
    if model_scale <= 0:
        raise typer.BadParameter("must be positive", param_hint="--model-scale")
    if model_icon_scale <= 0:
        raise typer.BadParameter("must be positive", param_hint="--model-icon-scale")
    if model_style not in {"icons", "geometry"}:
        raise typer.BadParameter(
            "must be icons or geometry", param_hint="--model-style"
        )
    if orientation not in {"display", "raw"}:
        raise typer.BadParameter("must be display or raw", param_hint="--orientation")
    if floor_texture_transform not in {
        "auto",
        "none",
        "flip-y",
        "flip-x",
        "rotate-180",
    }:
        raise typer.BadParameter(
            "invalid transform", param_hint="--floor-texture-transform"
        )
    if solid_fill not in {"none", "between", "adjacent", "interior", "bbox"}:
        raise typer.BadParameter("invalid mode", param_hint="--solid-fill")
    if solid_fill_texture not in {"wall", "floor"}:
        raise typer.BadParameter(
            "must be wall or floor", param_hint="--solid-fill-texture"
        )
    if grid_coordinate_mode not in {"display", "raw", "both"}:
        raise typer.BadParameter(
            "must be display, raw, or both", param_hint="--grid-coordinate-mode"
        )
    raise SystemExit(cmd_map_render(SimpleNamespace(**locals())))


@meta(results=("files",), params={"output": "output-dir"})
def map_grid_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output-dir", help="Rendered PNG directory")
    ],
    slots: SlotsOption = None,
    tile_size: Annotated[int, typer.Option("--tile-size")] = 64,
    margin: Annotated[int, typer.Option("--margin")] = 56,
    background: Annotated[str, typer.Option("--background")] = "#08090b",
    grid_label_step: Annotated[int, typer.Option("--grid-label-step")] = 1,
    coordinate_mode: Annotated[
        str, typer.Option("--coordinate-mode", help="display, raw, or both")
    ] = "display",
    no_solid_labels: Annotated[
        bool,
        typer.Option("--no-solid-labels", help="Label only non-solid tiles"),
    ] = False,
    name_files: Annotated[bool, typer.Option("--name-files")] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Render flat top-down diagnostic tile grids with coordinate labels."""
    if coordinate_mode not in COORDINATE_MODES:
        raise typer.BadParameter(
            "must be display, raw, or both", param_hint="--coordinate-mode"
        )
    raise SystemExit(cmd_map_grid(SimpleNamespace(**locals())))
