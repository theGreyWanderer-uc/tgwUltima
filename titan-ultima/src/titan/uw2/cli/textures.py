"""``titan uw2`` texture catalog and usage commands."""

from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

from titan._meta import meta
from titan.uw2.cli._common import (
    GameDirOption,
    SlotsOption,
    _require_file,
    _require_uw2_game_directory,
    _uw2_data_file,
)
from titan.uw2.map_pipeline import (
    MAP_SLOT_COUNT,
    load_levels,
)
from titan.uw2.texture_catalog import (
    build_texture_catalog,
    export_texture_catalog,
    export_texture_usage,
)
from titan.errors import exit_code


def cmd_texture_catalog(args: SimpleNamespace) -> int:
    """Join STRINGS.PAK texture descriptions to TERRAIN.DAT properties."""
    game_directory = _require_uw2_game_directory(args.gamedir)
    strings_path = _uw2_data_file("STRINGS.PAK", game_directory)
    if not _require_file(strings_path, "string archive"):
        return 1
    try:
        destination = export_texture_catalog(game_directory, args.output)
    except (OSError, KeyError, ValueError, struct.error) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return exit_code(error)
    typer.echo(f"Wrote UU2 texture catalog: {destination}")
    return 0


def cmd_texture_usage(args: SimpleNamespace) -> int:
    """Report where each named texture is used, per level and tile role."""
    game_directory = _require_uw2_game_directory(args.gamedir)
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
        return exit_code(error)

    typer.echo(
        f"Wrote texture usage for {len(levels)} UU2 levels "
        f"({len(written)} files): {Path(args.output)}"
    )
    return 0


@meta(category="graphics", results=("files",), params={"output": "output-dir"})
def texture_catalog_cmd(
    output: Annotated[
        str,
        typer.Option("-o", "--output-dir", help="Directory for texture_catalog.json"),
    ],
    gamedir: GameDirOption = None,
) -> None:
    """Export decoded T64.TR texture names and TERRAIN.DAT properties."""
    raise SystemExit(cmd_texture_catalog(SimpleNamespace(**locals())))


@meta(category="graphics", results=("files",), params={"output": "output-dir"})
def texture_usage_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output-dir", help="Usage JSON directory")
    ],
    slots: SlotsOption = None,
    write_catalog: Annotated[
        bool,
        typer.Option("--write-catalog", help="Also write texture_catalog.json"),
    ] = False,
    gamedir: GameDirOption = None,
) -> None:
    """Report per-level floor/wall/ceiling texture usage with tile coordinates."""
    raise SystemExit(cmd_texture_usage(SimpleNamespace(**locals())))
