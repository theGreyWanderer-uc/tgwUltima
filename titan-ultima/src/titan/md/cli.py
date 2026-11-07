"""Martian Dreams CLI commands; paths fall back to [md.game] base in titan.toml."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from titan._config import get_config
from titan.md.map_render import MartianMapRenderer
from titan.md.inspect_cli import register_martian_inspection_commands
from titan.u6.lib import U6LibraryError
from titan.u6.actor import U6ActorError
from titan.u6.lzw import U6LzwError
from titan.u6.map import U6ChunksError, U6MapError
from titan.u6.object import U6ObjectError
from titan.u6.palette import U6PaletteError
from titan.u6.tile import U6TilesError
from titan.u6.tileflag import U6TileFlagsError

__all__ = ["md_app"]

md_app = typer.Typer(
    name="md",
    help="Martian Dreams — maps, actors, saved state, dialogue and text.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@md_app.callback()
def martian_dreams_commands() -> None:
    """Martian Dreams map and resource commands."""


@md_app.command("map-render")
def map_render_cmd(
    gamedir: Annotated[
        Optional[str],
        typer.Option(
            "-g", "--gamedir", help="MARTIAN directory or its installation parent"
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Palette file (default: MDPAL)"),
    ] = None,
    region: Annotated[
        Optional[str],
        typer.Option("--region", help="Crop x,y,width,height in world tiles"),
    ] = None,
    dungeon: Annotated[
        Optional[int],
        typer.Option(
            "--dungeon",
            min=0,
            max=4,
            help="Underground level 0-4 instead of the surface",
        ),
    ] = None,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Render the entire selected map (surface: 16384x16384 pixels)",
        ),
    ] = False,
    tick: Annotated[
        int,
        typer.Option(
            "--tick",
            min=0,
            help="Animation tick; confirmed clock, canal and power controls follow the selected state",
        ),
    ] = 0,
    palette_tick: Annotated[
        int,
        typer.Option(
            "--palette-tick",
            min=0,
            help="VGA palette update phase; 0 keeps original colors, separate from tile --tick",
        ),
    ] = 0,
    lighting: Annotated[
        bool,
        typer.Option(
            "--lighting",
            help="DOS lighting, visible wall faces and object clipping; requires a region up to 11x11 tiles, viewed from its center",
        ),
    ] = False,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects",
            help="Overlay visible world objects, including multi-tile sprites",
        ),
    ] = False,
    actors: Annotated[
        bool,
        typer.Option(
            "--actors",
            help="Overlay party members, NPCs and creatures using MD actor offsets",
        ),
    ] = False,
    savegame: Annotated[
        Optional[str],
        typer.Option(
            "--savegame",
            help="Read clock and world flags from DOS SAVEGAME/OBJLIST, plus selected overlays",
        ),
    ] = None,
    show_markers: Annotated[
        bool,
        typer.Option(
            "--show-markers",
            help="Include MD's normally hidden marker tiles in object overlays",
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
    """Render MD surface or underground terrain, optionally with world objects."""
    directory = gamedir or get_config().get("md", {}).get("game", {}).get("base")
    if not directory:
        raise typer.BadParameter("Pass --gamedir or set [md.game] base in titan.toml")
    if region is not None and full:
        raise typer.BadParameter("Choose --region or --full")
    if region is None and dungeon is None and not full:
        raise typer.BadParameter(
            "Specify --region x,y,width,height, --dungeon 0-4, or --full"
        )
    if show_markers and not objects:
        raise typer.BadParameter("--show-markers requires --objects")
    if show_invisible and not objects:
        raise typer.BadParameter("--show-invisible requires --objects")
    crop = None
    if region is not None:
        try:
            x, y, width, height = (int(value) for value in region.split(","))
            crop = (x, y, width, height)
        except ValueError as exc:
            raise typer.BadParameter(
                "--region must be x,y,width,height with four integers"
            ) from exc
    if lighting and (crop is None or not 1 <= crop[2] <= 11 or not 1 <= crop[3] <= 11):
        raise typer.BadParameter(
            "--lighting requires --region with a crop no larger than 11x11 tiles"
        )
    try:
        renderer = MartianMapRenderer.from_directory(directory, palette=palette)
        image = renderer.render_map(
            region=crop,
            dungeon=dungeon,
            tick=tick,
            palette_tick=palette_tick,
            lighting=lighting,
            objects=objects,
            actors=actors,
            savegame=savegame,
            show_markers=show_markers,
            show_invisible=show_invisible,
        )
        filename = (
            "md_surface.png" if dungeon is None else f"md_underground_{dungeon}.png"
        )
        destination = Path(output or filename).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG")
    except (
        OSError,
        ValueError,
        U6LibraryError,
        U6ActorError,
        U6LzwError,
        U6ChunksError,
        U6MapError,
        U6ObjectError,
        U6PaletteError,
        U6TilesError,
        U6TileFlagsError,
    ) as exc:
        typer.echo(f"ERROR: Martian Dreams map render: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Saved: {destination} ({image.width}x{image.height})")


register_martian_inspection_commands(md_app)
