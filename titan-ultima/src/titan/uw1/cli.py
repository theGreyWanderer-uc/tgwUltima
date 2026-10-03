"""Ultima Underworld 1 CLI, registered as ``titan uw1``."""

from __future__ import annotations

__all__ = ["uw1_app"]

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from titan._config import get_config
from titan.uw1.texture import (
    UW1TextureError,
    export_all_textures,
    inspect_texture_archives,
)

uw1_app = typer.Typer(
    name="uw1",
    help="Ultima Underworld: The Stygian Abyss — texture archives.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _game_directory(explicit: str | None) -> Path | None:
    configured = get_config().get("uw1", {}).get("game", {}).get("base")
    value = explicit or configured
    return Path(value).expanduser() if value else None


def _require_game_directory(explicit: str | None) -> Path:
    game_directory = _game_directory(explicit)
    if game_directory is None:
        raise UW1TextureError("provide --gamedir or set [uw1.game] base in titan.toml")
    return game_directory


@uw1_app.command("texture-info")
def texture_info_cmd(
    gamedir: Annotated[
        Optional[str],
        typer.Option("--gamedir", "-g", help="UW1 install root or DATA directory"),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON")
    ] = False,
) -> None:
    """Inspect every UW1 floor and wall texture archive."""
    try:
        summaries = inspect_texture_archives(_require_game_directory(gamedir))
    except (OSError, UW1TextureError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error

    if json_output:
        typer.echo(json.dumps(summaries, indent=2))
        return
    total = 0
    for summary in summaries:
        count = summary["texture_count"]
        resolution = summary["resolution"]
        if not isinstance(count, int) or not isinstance(resolution, int):
            raise UW1TextureError("texture summary contains non-integer metadata")
        total += count
        typer.echo(
            f"{summary['archive']}: {count} textures at {resolution}x{resolution}"
        )
    typer.echo(f"Total: {total} textures across {len(summaries)} archives")


@uw1_app.command("texture-export")
def texture_export_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Texture export directory")
    ],
    gamedir: Annotated[
        Optional[str],
        typer.Option("--gamedir", "-g", help="UW1 install root or DATA directory"),
    ] = None,
    scale: Annotated[
        int, typer.Option("--scale", min=1, help="Nearest-neighbour scale factor")
    ] = 1,
    contact_sheets: Annotated[
        bool,
        typer.Option("--contact-sheets", help="Also export one sheet per archive"),
    ] = False,
) -> None:
    """Export all UW1 floor and wall textures to PNG plus CSV/JSON manifests."""
    try:
        result = export_all_textures(
            _require_game_directory(gamedir),
            output,
            scale=scale,
            contact_sheets=contact_sheets,
        )
    except (OSError, UW1TextureError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error

    typer.echo(
        f"Exported {result['texture_count']} UW1 textures from "
        f"{result['archive_count']} archives -> {Path(output)}"
    )
    typer.echo(f"CSV manifest: {Path(output) / 'textures_manifest.csv'}")
    typer.echo(f"JSON manifest: {Path(output) / 'textures_manifest.json'}")
