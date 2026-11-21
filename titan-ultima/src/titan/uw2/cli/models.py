"""``titan uw2`` executable 3D model render and export commands."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._config import DEFAULT_OUTPUT, export_output
from titan._meta import meta
from titan.uw2.cli._common import (
    GameDirOption,
    _require_uw2_game_directory,
)
from titan.uw2.model_export import UW2ModelExportError, export_object_models
from titan.uw2.model_render import UW2ModelRenderError, render_object_models
from titan.errors import exit_code


def cmd_model_render(args: SimpleNamespace) -> int:
    """Render selected executable 3D objects without loading a map."""
    game_directory = _require_uw2_game_directory(args.gamedir)
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
        return exit_code(error)
    for path in written:
        typer.echo(f"Rendered UU2 model: {path}")
    return 0


def cmd_model_export(args: SimpleNamespace) -> int:
    """Export selected or all executable 3D objects as individual OBJ assets."""
    game_directory = _require_uw2_game_directory(args.gamedir)
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
        return exit_code(error)
    for path in written:
        typer.echo(f"Exported UU2 model: {path}")
    typer.echo(f"Exported {len(written)} individual UU2 model items")
    return 0


@meta(results=("files",), params={"output": "output-dir"})
def model_render_cmd(
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output-dir", help="Rendered PNG directory" + DEFAULT_OUTPUT
        ),
    ] = None,
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
    output = export_output(output, "uw2", "model-render")
    items = items or ["0x158", "0x15c", "0x169"]
    views = views or ["iso", "front"]
    raise SystemExit(cmd_model_render(SimpleNamespace(**locals())))


@meta(results=("files",), params={"output": "output-dir"})
def model_export_cmd(
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output-dir", help="Export directory" + DEFAULT_OUTPUT),
    ] = None,
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
    output = export_output(output, "uw2", "model-export")
    raise SystemExit(cmd_model_export(SimpleNamespace(**locals())))
