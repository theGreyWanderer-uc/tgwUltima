"""``titan uw2`` palette, GR shape and terrain export commands."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._cli_aliases import TextOrJson
from titan._meta import meta
from titan.uw2.cli._common import (
    AllPalsOption,
    GameDirOption,
    PaletteOption,
    _require_file,
    _require_uw2_game_directory,
    _uw2_data_file,
    _uw2_game_directory,
)
from titan.uw2.gr import UW2GRArchive, UW2GRError
from titan.uw2.map_pipeline import (
    export_terrain_textures,
)
from titan.uw2.palette import UW2Palette, UW2PaletteError
from titan.uw2.terrain import make_contact_sheet
from titan.errors import exit_code


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
        return exit_code(error)
    output = Path(args.output or ".")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{path.stem.lower()}_{args.index:02d}"
    png_path = output / f"{stem}.png"
    text_path = output / f"{stem}.txt"
    palette.to_pil_image(args.swatch_size).save(png_path)
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
        return exit_code(error)
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
        return exit_code(error)
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
        return exit_code(error)
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
    game_directory = _require_uw2_game_directory(args.gamedir)
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
        return exit_code(error)
    typer.echo(
        f"Exported {result['count']} UU2 terrain textures "
        f"({result['resolution']}x{result['resolution']}): {Path(args.output)}"
    )
    if result["contact_sheet"]:
        typer.echo(f"Contact sheet: {result['contact_sheet']}")
    return 0


@meta(
    category="palettes",
    results=("files",),
    params={"output": "output-dir", "file": "palette"},
)
def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="PALS.DAT path/name")] = "PALS.DAT",
    index: Annotated[int, typer.Option("--index", help="Palette index")] = 0,
    swatch_size: Annotated[
        int, typer.Option("--swatch-size", help="Pixels per color swatch")
    ] = 16,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
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


@meta(
    category="graphics",
    results=("json", "text"),
    params={
        "output_format": "format",
        "output": "output-file",
        "palette": "palette",
        "file": "install-file",
        "allpals": "palette",
    },
)
def shape_info_cmd(
    file: Annotated[str, typer.Argument(help="UU2 .GR archive path/name")],
    palette: PaletteOption = None,
    allpals: AllPalsOption = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Optional report path")
    ] = None,
    output_format: Annotated[
        TextOrJson,
        typer.Option("--format", help="Output format: text (default) or json"),
    ] = TextOrJson.text,
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
                json=output_format is TextOrJson.json,
                gamedir=gamedir,
            )
        )
    )


@meta(
    category="graphics",
    results=("files",),
    params={
        "output": "output-dir",
        "palette": "palette",
        "file": "install-file",
        "allpals": "palette",
    },
)
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
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Export one image from a UU2 GR shape archive to PNG."""
    raise SystemExit(cmd_shape_export(SimpleNamespace(**locals())))


@meta(
    category="graphics",
    results=("files",),
    params={
        "output": "output-dir",
        "palette": "palette",
        "file": "install-file",
        "allpals": "palette",
    },
)
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
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
    contact_sheet: Annotated[
        bool,
        typer.Option("--contact-sheet", help="Also write a tiled contact sheet"),
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Export every non-empty image from a UU2 GR shape archive to PNG."""
    raise SystemExit(cmd_shape_batch(SimpleNamespace(**locals())))


@meta(category="graphics", results=("files",), params={"output": "output-dir"})
def terrain_export_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output-dir", help="Terrain PNG directory")
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
