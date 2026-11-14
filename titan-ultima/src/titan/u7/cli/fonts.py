"""``titan u7 font-create`` — font archive creation command."""

from __future__ import annotations

__all__ = ["font_create_cmd"]

from types import SimpleNamespace
from typing import Annotated, Optional

import typer


def cmd_font_create(args: SimpleNamespace) -> int:
    """Create a U7 font shape from a TrueType font."""
    from titan.fonts.wizard import run_wizard, run_from_config

    options = dict(
        output_override=args.output,
        force=getattr(args, "force", False),
        allow_cycling=getattr(args, "allow_cycling", False),
        base_archive=getattr(args, "base_archive", None),
    )
    if args.config:
        return run_from_config(args.config, **options)
    return run_wizard(**options)


def font_create_cmd(
    config: Annotated[
        Optional[str],
        typer.Option(
            "--config", "-c", help="TOML config file (skip interactive prompts)"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output file path"),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Replace existing output files")
    ] = False,
    allow_cycling: Annotated[
        bool,
        typer.Option(
            "--allow-cycling",
            help="Allow gradient colour matching to use cycling indices 224-254",
        ),
    ] = False,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive", help="Base font VGA for a sparse template archive"
        ),
    ] = None,
) -> None:
    """Interactive wizard for creating U7 font shapes from TrueType fonts.

    When run without --config, launches an interactive step-by-step
    wizard that walks through game selection, font slot, TTF source,
    rendering method, dimensions, palette, preview, and output.

    With --config, reads all parameters from a TOML recipe file and
    generates the shape non-interactively.
    """
    raise SystemExit(
        cmd_font_create(
            SimpleNamespace(
                config=config,
                output=output,
                force=force,
                allow_cycling=allow_cycling,
                base_archive=base_archive,
            )
        )
    )
