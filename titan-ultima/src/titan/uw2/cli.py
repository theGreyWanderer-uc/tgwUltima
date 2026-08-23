"""Ultima Underworld II CLI, registered as ``titan uw2``."""

from __future__ import annotations

__all__ = ["uw2_app"]

import csv
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._config import get_config
from titan.uw2.gr import UW2GRArchive, UW2GRError
from titan.uw2.grid_render import COORDINATE_MODES, render_grids_direct
from titan.uw2.map_pipeline import (
    MAP_SLOT_COUNT,
    export_render_assets,
    export_terrain_textures,
    extract_maps,
    load_levels,
    render_maps,
    render_maps_direct,
    verify_maps,
)
from titan.uw2.map3d import (
    BACKENDS,
    DEFAULT_ZOOM,
    DOWNSAMPLE_FILTERS,
    TEXTURE_FILTERS,
    export_map_scene,
    render_map_scene,
    render_stacked_worlds,
)
from titan.uw2.model_export import UW2ModelExportError, export_object_models
from titan.uw2.model_render import UW2ModelRenderError, render_object_models
from titan.uw2.object_data import (
    ANIMATION_ITEM_FIRST,
    ANIMATION_ITEM_LAST,
    UW2AnimationTable,
    UW2CommonObjectTable,
    UW2ObjectDataError,
)
from titan.uw2.palette import UW2Palette, UW2PaletteError
from titan.uw2.scene3d import (
    CEILING_SOURCES,
    DEFAULT_Z_SCALE,
    UW2SceneError,
    parse_tile_region,
)
from titan.uw2.terrain import make_contact_sheet
from titan.uw2.texture_catalog import (
    build_texture_catalog,
    export_texture_catalog,
    export_texture_usage,
)

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
    images = []
    for record in archive.images:
        image = record.to_image(palette, transparent_index=args.transparent_index)
        image.save(output / f"{stem}_{record.index:03d}.png")
        images.append(image)
    summary_path = output / f"{stem}_summary.json"
    summary_path.write_text(json.dumps(archive.summary(), indent=2), encoding="utf-8")
    typer.echo(
        f"Exported {len(archive.images)}/{archive.declared_image_count} UU2 GR images: {output}"
    )
    if getattr(args, "contact_sheet", False) and images:
        sheet_path = output / f"{stem}_contact_sheet.png"
        make_contact_sheet(images).save(sheet_path)
        typer.echo(f"Contact sheet: {sheet_path}")
    return 0


def cmd_terrain_export(args: SimpleNamespace) -> int:
    """Export T64.TR terrain textures, optionally with a contact sheet."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
    terrain_path = _uw2_data_file("T64.TR", game_directory)
    palette_path = _uw2_data_file("PALS.DAT", game_directory)
    if not _require_file(terrain_path, "terrain archive"):
        return 1
    if not _require_file(palette_path, "palette"):
        return 1
    try:
        result = export_terrain_textures(
            game_directory,
            args.output,
            contact_sheet=args.contact_sheet,
            scale=args.scale,
        )
    except (OSError, KeyError, ValueError, UW2PaletteError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    typer.echo(
        f"Exported {result['count']} UU2 terrain textures "
        f"({result['resolution']}x{result['resolution']}): {Path(args.output)}"
    )
    if result["contact_sheet"]:
        typer.echo(f"Contact sheet: {result['contact_sheet']}")
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


def cmd_map_verify(args: SimpleNamespace) -> int:
    """Smoke-check LEV.ARK block shapes and decode every populated slot."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
    lev_path = _uw2_data_file("LEV.ARK", game_directory)
    if not _require_file(lev_path, "map archive"):
        return 1
    try:
        report = verify_maps(game_directory)
    except (OSError, KeyError, ValueError, struct.error) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1

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
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
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
        return 1
    for path in written:
        typer.echo(f"Rendered UU2 grid: {path}")
    return 0


def cmd_texture_catalog(args: SimpleNamespace) -> int:
    """Join STRINGS.PAK texture descriptions to TERRAIN.DAT properties."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
    strings_path = _uw2_data_file("STRINGS.PAK", game_directory)
    if not _require_file(strings_path, "string archive"):
        return 1
    try:
        destination = export_texture_catalog(game_directory, args.output)
    except (OSError, KeyError, ValueError, struct.error) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    typer.echo(f"Wrote UU2 texture catalog: {destination}")
    return 0


def cmd_texture_usage(args: SimpleNamespace) -> int:
    """Report where each named texture is used, per level and tile role."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
    strings_path = _uw2_data_file("STRINGS.PAK", game_directory)
    lev_path = _uw2_data_file("LEV.ARK", game_directory)
    if not _require_file(strings_path, "string archive"):
        return 1
    if not _require_file(lev_path, "map archive"):
        return 1

    slots = args.slots if args.slots else range(MAP_SLOT_COUNT)
    try:
        catalog = build_texture_catalog(game_directory)
        levels = load_levels(game_directory, slots)
        if not levels:
            raise ValueError(f"no populated UU2 map slots in {sorted(set(slots))}")
        written = export_texture_usage(levels, catalog, args.output)
        if args.write_catalog:
            written.append(export_texture_catalog(game_directory, args.output))
    except (OSError, KeyError, ValueError, struct.error) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1

    typer.echo(
        f"Wrote texture usage for {len(levels)} UU2 levels "
        f"({len(written)} files): {Path(args.output)}"
    )
    return 0


def cmd_model_render(args: SimpleNamespace) -> int:
    """Render selected executable 3D objects without loading a map."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
    try:
        item_ids = [int(value, 0) for value in args.items]
        written = render_object_models(
            game_directory,
            args.output,
            item_ids=item_ids,
            flags=args.flags,
            size=args.size,
            views=args.views,
        )
    except (OSError, ValueError, UW2ModelRenderError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    for path in written:
        typer.echo(f"Rendered UU2 model: {path}")
    return 0


def cmd_model_export(args: SimpleNamespace) -> int:
    """Export selected or all executable 3D objects as individual OBJ assets."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
    try:
        item_ids = [int(value, 0) for value in args.items] if args.items else None
        written = export_object_models(
            game_directory,
            args.output,
            item_ids=item_ids,
            flags=args.flags,
        )
    except (OSError, ValueError, UW2ModelExportError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return 1
    for path in written:
        typer.echo(f"Exported UU2 model: {path}")
    typer.echo(f"Exported {len(written)} individual UU2 model items")
    return 0


def cmd_map_3d_render(args: SimpleNamespace) -> int:
    """Render one textured map scene from camera presets."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
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
        return 1
    for path in written:
        typer.echo(f"Rendered UU2 3D map: {path}")
    return 0


def cmd_map_stack(args: SimpleNamespace) -> int:
    """Render each world's levels as one vertically stacked cutaway."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
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
        return 1
    for path in written:
        typer.echo(f"Rendered UU2 stacked world: {path}")
    return 0


def cmd_map_3d_export(args: SimpleNamespace) -> int:
    """Export one textured map scene as GLB with individual object nodes."""
    game_directory = _uw2_game_directory(args.gamedir)
    if game_directory is None:
        typer.echo("ERROR: provide --gamedir or configure [uw2.game] base", err=True)
        return 1
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
        return 1
    typer.echo(f"Exported UU2 3D map: {written}")
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

CeilingSourceOption = Annotated[
    str,
    typer.Option(
        "--ceiling-source",
        help="runtime port rule, or ua for UnderworldAdventures mapping[32]",
    ),
]

ZScaleOption = Annotated[
    float,
    typer.Option("--z-scale", help="Map height units per rendered unit"),
]


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


@uw2_app.command("model-render")
def model_render_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Rendered PNG directory")
    ] = "uw2_models",
    items: Annotated[
        Optional[list[str]],
        typer.Option("--item", help="Item ID in decimal or 0x hex; repeat as needed"),
    ] = None,
    flags: Annotated[
        int,
        typer.Option("--flags", help="Object flags used for dynamic texture choice"),
    ] = 0,
    size: Annotated[
        int, typer.Option("--size", help="Square image size in pixels")
    ] = 900,
    views: Annotated[
        Optional[list[str]],
        typer.Option("--view", help="iso, front, side, or top; repeat as needed"),
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Render standalone polygon objects decoded directly from UW2.EXE."""
    items = items or ["0x158", "0x15c", "0x169"]
    views = views or ["iso", "front"]
    raise SystemExit(cmd_model_render(SimpleNamespace(**locals())))


@uw2_app.command("model-export")
def model_export_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Export directory")
    ] = "uw2_model_exports",
    items: Annotated[
        Optional[list[str]],
        typer.Option(
            "--item",
            help="Item ID in decimal or 0x hex; repeat. Omit to export all mapped items",
        ),
    ] = None,
    flags: Annotated[
        int,
        typer.Option("--flags", help="Object flags used for dynamic texture choice"),
    ] = 0,
    gamedir: GameDirOption = None,
) -> None:
    """Export individual textured polygon objects from UW2.EXE to OBJ."""
    raise SystemExit(cmd_model_export(SimpleNamespace(**locals())))


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


@uw2_app.command("map-verify")
def map_verify_cmd(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the full report as JSON")
    ] = False,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Optional JSON report path")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Smoke-check LEV.ARK block shapes and decode every populated map slot."""
    raise SystemExit(cmd_map_verify(SimpleNamespace(**locals())))


@uw2_app.command("map-3d-render")
def map_3d_render_cmd(
    output: Annotated[str, typer.Option("-o", "--output")] = "uw2_maps_3d",
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
    views = views or ["iso-ne", "top"]
    slot = slot if slot else [0]
    _validate_view_options(
        downsample_filter=downsample_filter,
        texture_filter=texture_filter,
        backend=backend,
        ceiling_source=ceiling_source,
    )
    raise SystemExit(cmd_map_3d_render(SimpleNamespace(**locals())))


@uw2_app.command("map-stack")
def map_stack_cmd(
    output: Annotated[str, typer.Option("-o", "--output")] = "uw2_stacks",
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
    views = views or ["iso-ne"]
    _validate_view_options(
        downsample_filter=downsample_filter,
        texture_filter=texture_filter,
        backend=backend,
        ceiling_source=ceiling_source,
    )
    raise SystemExit(cmd_map_stack(SimpleNamespace(**locals())))


@uw2_app.command("map-3d-export")
def map_3d_export_cmd(
    output: Annotated[str, typer.Option("-o", "--output")] = "uw2_maps_3d",
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
    _validate_view_options(ceiling_source=ceiling_source)
    raise SystemExit(cmd_map_3d_export(SimpleNamespace(**locals())))


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


@uw2_app.command("map-grid")
def map_grid_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Rendered PNG directory")
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


@uw2_app.command("texture-catalog")
def texture_catalog_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Directory for texture_catalog.json")
    ],
    gamedir: GameDirOption = None,
) -> None:
    """Export decoded T64.TR texture names and TERRAIN.DAT properties."""
    raise SystemExit(cmd_texture_catalog(SimpleNamespace(**locals())))


@uw2_app.command("texture-usage")
def texture_usage_cmd(
    output: Annotated[str, typer.Option("-o", "--output", help="Usage JSON directory")],
    slots: SlotsOption = None,
    write_catalog: Annotated[
        bool,
        typer.Option("--write-catalog", help="Also write texture_catalog.json"),
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Report per-level floor/wall/ceiling texture usage with tile coordinates."""
    raise SystemExit(cmd_texture_usage(SimpleNamespace(**locals())))


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
    contact_sheet: Annotated[
        bool,
        typer.Option("--contact-sheet", help="Also write a tiled contact sheet"),
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Export every non-empty image from a UU2 GR shape archive to PNG."""
    raise SystemExit(cmd_shape_batch(SimpleNamespace(**locals())))


@uw2_app.command("terrain-export")
def terrain_export_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Terrain PNG directory")
    ],
    contact_sheet: Annotated[
        bool,
        typer.Option("--contact-sheet", help="Also write t64_contact_sheet.png"),
    ] = False,
    scale: Annotated[
        int,
        typer.Option("--scale", help="Nearest-neighbour upscale factor"),
    ] = 1,
    gamedir: GameDirOption = None,
) -> None:
    """Export T64.TR terrain textures as PNG with an optional contact sheet."""
    raise SystemExit(cmd_terrain_export(SimpleNamespace(**locals())))


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
