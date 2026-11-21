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
from titan._meta import meta
from titan._results import record_output
from titan.errors import InstallNotFoundError, exit_code
from titan._cli_aliases import TextOrJson, alias_group

uw1_app = typer.Typer(
    cls=alias_group(
        {
            "--gamedir": "--game-dir",
            "--output": "--output-dir",
            "--json": ("--format", "json"),
        }
    ),
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
        raise InstallNotFoundError(
            "provide --game-dir or set [uw1.game] base in titan.toml"
        )
    return game_directory


@uw1_app.command("texture-info")
@meta(params={"output_format": "format"}, results=("json", "text"))
def texture_info_cmd(
    gamedir: Annotated[
        Optional[str],
        typer.Option("--game-dir", "-g", help="UW1 install root or DATA directory"),
    ] = None,
    output_format: Annotated[
        TextOrJson,
        typer.Option("--format", help="Output format: text (default) or json"),
    ] = TextOrJson.text,
) -> None:
    """Inspect every UW1 floor and wall texture archive."""
    json_output = output_format is TextOrJson.json
    try:
        summaries = inspect_texture_archives(_require_game_directory(gamedir))
    except (OSError, UW1TextureError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(exit_code(error)) from error

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
@meta(results=("files",), params={"output": "output-dir"})
def texture_export_cmd(
    output: Annotated[
        str, typer.Option("-o", "--output-dir", help="Texture export directory")
    ],
    gamedir: Annotated[
        Optional[str],
        typer.Option("--game-dir", "-g", help="UW1 install root or DATA directory"),
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
        raise typer.Exit(exit_code(error)) from error

    typer.echo(
        f"Exported {result['texture_count']} UW1 textures from "
        f"{result['archive_count']} archives -> {Path(output)}"
    )
    typer.echo(f"CSV manifest: {Path(output) / 'textures_manifest.csv'}")
    record_output(output)
    typer.echo(f"JSON manifest: {Path(output) / 'textures_manifest.json'}")
