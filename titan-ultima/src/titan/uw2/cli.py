"""Ultima Underworld II CLI, registered as ``titan uw2``."""

from __future__ import annotations

__all__ = ["uw2_app"]

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._config import get_config
from titan.uw2.gr import UW2GRArchive, UW2GRError
from titan.uw2.map_pipeline import (
    export_render_assets,
    extract_maps,
    render_maps,
    render_maps_direct,
)
from titan.uw2.object_data import (
    ANIMATION_ITEM_FIRST,
    ANIMATION_ITEM_LAST,
    UW2AnimationTable,
    UW2CommonObjectTable,
    UW2ObjectDataError,
)
from titan.uw2.palette import UW2Palette, UW2PaletteError

uw2_app = typer.Typer(
    name="uw2",
    help="Ultima Underworld II — maps, palettes, shapes, and object metadata.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _uw2_game_directory(explicit: str | None) -> Path | None:
    """Resolve explicit game dir, then ``[uw2.game] base`` from titan.toml."""
    configured = get_config().get("uw2", {}).get("game", {}).get("base")
    value = explicit or configured
    return Path(value).expanduser() if value else None


def _uw2_data_file(value: str, game_directory: Path | None) -> Path:
    """Resolve absolute/path-like input or a file name below UU2 ``DATA``."""
    path = Path(value).expanduser()
    if path.is_file() or path.is_absolute() or game_directory is None:
        return path
    data_directory = (
        game_directory
        if game_directory.name.upper() == "DATA"
        else game_directory / "DATA"
    )
    return data_directory / path


def _require_file(path: Path, label: str) -> bool:
    if path.is_file():
        return True
    typer.echo(f"ERROR: UU2 {label} file not found: {path}", err=True)
    return False


def _resolve_gr_archive_inputs(
    args: SimpleNamespace,
) -> tuple[Path, Path | None] | None:
    game_directory = _uw2_game_directory(args.gamedir)
    archive = _uw2_data_file(args.file, game_directory)
    allpals_value = args.allpals or "ALLPALS.DAT"
    allpals_candidate = _uw2_data_file(allpals_value, game_directory)
    if not _require_file(archive, "GR archive"):
        return None
    if not allpals_candidate.is_file():
        if args.allpals:
            _require_file(allpals_candidate, "auxiliary palette")
            return None
        return archive, None
    return archive, allpals_candidate


def _resolve_shape_inputs(
    args: SimpleNamespace,
) -> tuple[Path, Path, Path | None] | None:
    archive_inputs = _resolve_gr_archive_inputs(args)
    if archive_inputs is None:
        return None
    game_directory = _uw2_game_directory(args.gamedir)
    palette = _uw2_data_file(args.palette or "PALS.DAT", game_directory)
    if not _require_file(palette, "palette"):
        return None
    archive, allpals = archive_inputs
    return archive, palette, allpals


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export one PALS.DAT palette as PNG swatches and text."""
    game_directory = _uw2_game_directory(args.gamedir)
    path = _uw2_data_file(args.file, game_directory)
    if not _require_file(path, "palette"):
        return 1
    try:
        palette = UW2Palette.from_file(path, index=args.index)
    except (OSError, UW2PaletteError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    output = Path(args.output or ".")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{path.stem.lower()}_{args.index:02d}"
    png_path = output / f"{stem}.png"
    text_path = output / f"{stem}.txt"
    palette.to_swatch_image(args.swatch_size).save(png_path)
    text_path.write_text(
        "# Index  R    G    B    Hex\n"
        + "".join(
            f"{index:3d}    {red:3d}  {green:3d}  {blue:3d}  #{red:02X}{green:02X}{blue:02X}\n"
            for index, (red, green, blue) in enumerate(palette.colors)
        ),
        encoding="utf-8",
    )
    typer.echo(f"Exported UU2 palette {args.index}: {png_path}")
    typer.echo(f"Palette text: {text_path}")
    return 0


def cmd_shape_info(args: SimpleNamespace) -> int:
    """Print or save UU2 GR archive metadata."""
    resolved = _resolve_gr_archive_inputs(args)
    if resolved is None:
        return 1
    archive_path, allpals_path = resolved
    try:
        archive = UW2GRArchive.from_file(archive_path, allpals_path)
    except (OSError, UW2GRError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    summary = archive.summary()
    if args.json:
        text = json.dumps(summary, indent=2)
    else:
        text = (
            f"{archive_path}: {archive.declared_image_count} declared, "
            f"{len(archive.images)} decoded\n"
            + "Idx  Type  Size       Offset  Aux\n"
            + "-----------------------------------\n"
            + "".join(
                f"{image.index:3d}  {image.bitmap_type:#04x}  "
                f"{image.width:3d}x{image.height:<3d}  {image.offset:#08x}  "
                f"{image.auxiliary_palette_index if image.auxiliary_palette_index is not None else '-'}\n"
                for image in archive.images
            )
        )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote UU2 GR info: {output}")
    else:
        typer.echo(text, nl=False)
    return 0


def cmd_shape_export(args: SimpleNamespace) -> int:
    """Export one indexed image from a UU2 GR archive."""
    resolved = _resolve_shape_inputs(args)
    if resolved is None:
        return 1
    archive_path, palette_path, allpals_path = resolved
    try:
        palette = UW2Palette.from_file(palette_path, index=args.palette_index)
        archive = UW2GRArchive.from_file(archive_path, allpals_path)
        image = archive.image(args.index).to_image(
            palette, transparent_index=args.transparent_index
        )
    except (OSError, UW2GRError, UW2PaletteError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    output = Path(args.output or ".")
    output.mkdir(parents=True, exist_ok=True)
    output_path = output / f"{archive_path.stem.lower()}_{args.index:03d}.png"
    image.save(output_path)
    typer.echo(
        f"Exported UU2 GR image {args.index} ({image.width}x{image.height}): {output_path}"
    )
    return 0


def cmd_shape_batch(args: SimpleNamespace) -> int:
    """Export every non-empty image from a UU2 GR archive."""
    resolved = _resolve_shape_inputs(args)
    if resolved is None:
        return 1
    archive_path, palette_path, allpals_path = resolved
    try:
        palette = UW2Palette.from_file(palette_path, index=args.palette_index)
        archive = UW2GRArchive.from_file(archive_path, allpals_path)
    except (OSError, UW2GRError, UW2PaletteError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    output = Path(args.output or f"{archive_path.stem.lower()}_png")
    output.mkdir(parents=True, exist_ok=True)
    stem = archive_path.stem.lower()
    for record in archive.images:
        record.to_image(palette, transparent_index=args.transparent_index).save(
            output / f"{stem}_{record.index:03d}.png"
        )
    summary_path = output / f"{stem}_summary.json"
    summary_path.write_text(json.dumps(archive.summary(), indent=2), encoding="utf-8")
    typer.echo(
        f"Exported {len(archive.images)}/{archive.declared_image_count} UU2 GR images: {output}"
    )
    return 0


def _resolve_object_tables(
    args: SimpleNamespace,
) -> tuple[UW2CommonObjectTable, UW2AnimationTable | None] | None:
    game_directory = _uw2_game_directory(args.gamedir)
    common_path = _uw2_data_file(args.comobj or "COMOBJ.DAT", game_directory)
    objects_path = _uw2_data_file(args.objects or "OBJECTS.DAT", game_directory)
    if not _require_file(common_path, "common object metadata"):
        return None
    try:
        common = UW2CommonObjectTable.from_file(common_path)
        animations = (
            UW2AnimationTable.from_file(objects_path)
            if objects_path.is_file()
            else None
        )
    except (OSError, UW2ObjectDataError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return None
    if args.objects and animations is None:
        _require_file(objects_path, "animation metadata")
        return None
    return common, animations


def _object_record_dict(
    item_id: int,
    common: UW2CommonObjectTable,
    animations: UW2AnimationTable | None,
) -> dict[str, object]:
    result = common.get(item_id).to_dict()
    if (
        animations is not None
        and ANIMATION_ITEM_FIRST <= item_id <= ANIMATION_ITEM_LAST
    ):
        result["animation"] = animations.get(item_id).to_dict()
    return result


def cmd_object_info(args: SimpleNamespace) -> int:
    """Print rendering metadata for one UU2 item ID."""
    tables = _resolve_object_tables(args)
    if tables is None:
        return 1
    common, animations = tables
    try:
        result = _object_record_dict(args.item_id, common, animations)
    except UW2ObjectDataError as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    typer.echo(json.dumps(result, indent=2))
    return 0


def cmd_object_dump(args: SimpleNamespace) -> int:
    """Export all UU2 COMOBJ.DAT rendering metadata to JSON or CSV."""
    tables = _resolve_object_tables(args)
    if tables is None:
        return 1
    common, animations = tables
    records = [
        _object_record_dict(record.item_id, common, animations)
        for record in common.records
    ]
    output = Path(args.output or f"uw2_objects.{args.format}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    else:
        flat_records = []
        for record in records:
            flat = {key: value for key, value in record.items() if key != "animation"}
            animation = record.get("animation")
            if isinstance(animation, dict):
                flat.update(
                    {f"animation_{key}": value for key, value in animation.items()}
                )
            flat_records.append(flat)
        fieldnames = list(flat_records[0])
        for record in flat_records[1:]:
            fieldnames.extend(key for key in record if key not in fieldnames)
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_records)
    typer.echo(f"Exported {len(records)} UU2 object metadata records: {output}")
    return 0


def cmd_map_extract(args: SimpleNamespace) -> int:
    """Decode LEV.ARK into renderer-ready level JSON."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
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
        return 1
    typer.echo(f"Extracted {len(summaries)} UU2 maps: {Path(args.output)}")
    return 0


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render directly from original archives; intermediates are optional."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
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
        return 1
    for path in written:
        typer.echo(f"Rendered UU2 map: {path}")
    return 0


GameDirOption = Annotated[
    Optional[str],
    typer.Option(
        "-g",
        "--gamedir",
        help="UU2 install root or DATA directory; falls back to [uw2.game] base",
    ),
]
PaletteOption = Annotated[
    Optional[str],
    typer.Option("-p", "--palette", help="PALS.DAT path/name (default: PALS.DAT)"),
]
AllPalsOption = Annotated[
    Optional[str],
    typer.Option(
        "-a",
        "--allpals",
        help="ALLPALS.DAT path/name (default: ALLPALS.DAT when found)",
    ),
]

SlotsOption = Annotated[
    Optional[list[int]],
    typer.Option("--slots", help="Zero-based LEV.ARK map slots (repeat values)"),
]


@uw2_app.command("map-extract")
def map_extract_cmd(
    output: Annotated[str, typer.Option("-o", "--output", help="Extraction directory")],
    slots: SlotsOption = None,
    write_decoded_blocks: Annotated[
        bool,
        typer.Option("--write-decoded-blocks", help="Also preserve decoded ARK blocks"),
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Decode LEV.ARK maps, objects, automap data, notes, and lighting."""
    raise SystemExit(cmd_map_extract(SimpleNamespace(**locals())))


@uw2_app.command("map-render")
def map_render_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Rendered PNG directory")
    ] = "uw2_maps",
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
    ] = 2.0,
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


@uw2_app.command("palette-export")
def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="PALS.DAT path/name")] = "PALS.DAT",
    index: Annotated[int, typer.Option("--index", help="Palette index")] = 0,
    swatch_size: Annotated[
        int, typer.Option("--swatch-size", help="Pixels per color swatch")
    ] = 16,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Export one UU2 PALS.DAT palette as PNG swatches and text."""
    raise SystemExit(
        cmd_palette_export(
            SimpleNamespace(
                file=file,
                index=index,
                swatch_size=swatch_size,
                output=output,
                gamedir=gamedir,
            )
        )
    )


@uw2_app.command("shape-info")
def shape_info_cmd(
    file: Annotated[str, typer.Argument(help="UU2 .GR archive path/name")],
    palette: PaletteOption = None,
    allpals: AllPalsOption = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Optional report path")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON metadata")
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """List dimensions and bitmap types in a UU2 GR shape archive."""
    raise SystemExit(
        cmd_shape_info(
            SimpleNamespace(
                file=file,
                palette=palette,
                allpals=allpals,
                output=output,
                json=json_output,
                gamedir=gamedir,
            )
        )
    )


@uw2_app.command("shape-export")
def shape_export_cmd(
    file: Annotated[str, typer.Argument(help="UU2 .GR archive path/name")],
    index: Annotated[int, typer.Argument(help="Image index")],
    palette: PaletteOption = None,
    allpals: AllPalsOption = None,
    palette_index: Annotated[
        int, typer.Option("--palette-index", help="PALS.DAT palette index")
    ] = 0,
    transparent_index: Annotated[
        int, typer.Option("--transparent-index", help="Transparent palette index")
    ] = 0,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Export one image from a UU2 GR shape archive to PNG."""
    raise SystemExit(cmd_shape_export(SimpleNamespace(**locals())))


@uw2_app.command("shape-batch")
def shape_batch_cmd(
    file: Annotated[str, typer.Argument(help="UU2 .GR archive path/name")],
    palette: PaletteOption = None,
    allpals: AllPalsOption = None,
    palette_index: Annotated[
        int, typer.Option("--palette-index", help="PALS.DAT palette index")
    ] = 0,
    transparent_index: Annotated[
        int, typer.Option("--transparent-index", help="Transparent palette index")
    ] = 0,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Export every non-empty image from a UU2 GR shape archive to PNG."""
    raise SystemExit(cmd_shape_batch(SimpleNamespace(**locals())))


@uw2_app.command("object-info")
def object_info_cmd(
    item_id: Annotated[int, typer.Argument(help="UU2 item ID (0..511)")],
    comobj: Annotated[
        Optional[str], typer.Option("--comobj", help="COMOBJ.DAT path/name")
    ] = None,
    objects: Annotated[
        Optional[str], typer.Option("--objects", help="OBJECTS.DAT path/name")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Print one UU2 item's render type and optional animation frames."""
    raise SystemExit(cmd_object_info(SimpleNamespace(**locals())))


@uw2_app.command("object-dump")
def object_dump_cmd(
    comobj: Annotated[
        Optional[str], typer.Option("--comobj", help="COMOBJ.DAT path/name")
    ] = None,
    objects: Annotated[
        Optional[str], typer.Option("--objects", help="OBJECTS.DAT path/name")
    ] = None,
    format_name: Annotated[
        str, typer.Option("-f", "--format", help="json or csv")
    ] = "json",
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output file")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Export all UU2 COMOBJ.DAT render metadata as JSON or CSV."""
    if format_name not in {"json", "csv"}:
        raise typer.BadParameter("must be json or csv", param_hint="--format")
    raise SystemExit(
        cmd_object_dump(
            SimpleNamespace(
                comobj=comobj,
                objects=objects,
                format=format_name,
                output=output,
                gamedir=gamedir,
            )
        )
    )
