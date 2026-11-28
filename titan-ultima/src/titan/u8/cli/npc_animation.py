"""Read-only CLI for master CSV and per-NPC HTML animation reports."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from titan._config import export_dir
from titan.u8.npc_source import load_u8_npc_source
from titan.u8.npc_animation_report import (
    export_u8_npc_animation_report,
    load_u8_npc_labels,
)
from titan.u8.shape_browser import find_u8_browser_file, load_u8_shape_library
from titan._meta import configured_install, meta
from titan.errors import exit_code


@meta(
    category="models",
    results=("files",),
    params={
        "output": "output-dir",
        "palette": "palette",
        "source": "input-file",
        "anim": "install-file",
        "itemcach": "input-file",
        "names": "input-file",
        "shapes": "install-file",
    },
    resources={"shapes": "u8shapes"},
)
def npc_animation_report_cmd(
    source: Annotated[
        Path,
        typer.Argument(help="Native U8SAVE, GAMEDAT directory, or loose NPCDATA.DAT"),
    ],
    shapes: Annotated[
        Path | None,
        typer.Option(
            "--shapes", help="Matching U8SHAPES.FLX; otherwise configured U8 shapes"
        ),
    ] = None,
    anim: Annotated[
        Path | None,
        typer.Option("--anim", help="Matching ANIM.DAT; otherwise shapes owner"),
    ] = None,
    palette: Annotated[
        Path | None,
        typer.Option("-p", "--palette", help="U8PAL.PAL; otherwise shapes owner"),
    ] = None,
    itemcach: Annotated[
        Path | None,
        typer.Option(
            "--itemcach",
            help="Paired ITEMCACH.DAT/save; otherwise same snapshot or sibling file",
        ),
    ] = None,
    npc: Annotated[
        int | None,
        typer.Option(
            "--npc",
            min=0,
            max=255,
            help="Report one native NPC slot; default allocated NPCs",
        ),
    ] = None,
    names: Annotated[
        Path | None,
        typer.Option(
            "--names",
            help="npc_id,name CSV overrides; default permanent NPC names use native usecode classes",
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output-dir",
            help="New or empty output directory for CSV, HTML and contact sheets",
        ),
    ] = None,
) -> None:
    """Export a master animation CSV and per-NPC HTML reports with contact sheets."""
    if output is None:
        output = export_dir("u8", U8_NPC_ANIMATION_OUTPUT)
    try:
        install = configured_install("u8")
        if shapes is None:
            configured = install.resources.get("u8shapes") if install else None
            if configured:
                shapes = Path(configured)
        if shapes is None:
            raise ValueError(
                "NPC animation report: supply --shapes or configure U8 shapes"
            )
        anim = anim or find_u8_browser_file(shapes.parent, "ANIM.DAT")
        if anim is None:
            raise ValueError("NPC animation report: supply matching --anim ANIM.DAT")
        library = load_u8_shape_library(
            shapes, anim=anim, palette=palette, install=install
        )
        native = load_u8_npc_source(source, itemcach=itemcach)
        for issue in native.diagnostics:
            typer.echo(issue)
        labels = load_u8_npc_labels(names) if names is not None else None
        sources = native.source_files + ((names,) if names is not None else ())
        manifest = export_u8_npc_animation_report(
            library,
            native.npcs,
            native.cache,
            output,
            sources=sources,
            npc_id=npc,
            labels=labels,
            avatar=native.avatar,
            progress=typer.echo,
        )
        print(
            f"Saved {manifest['npc_count']} NPC reports, {manifest['row_count']} CSV rows and {manifest['contact_sheet_count']} contact sheets to: {output}"
        )
        print(f"Open: {output / 'index.html'}")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(exit_code(error)) from error


U8_NPC_ANIMATION_OUTPUT = "npc-animation-report"
"""Default export folder name, under :func:`titan._config.export_dir` ("u8")."""


def register_u8_npc_animation_report(app: typer.Typer) -> None:
    app.command("npc-animation-report")(npc_animation_report_cmd)
