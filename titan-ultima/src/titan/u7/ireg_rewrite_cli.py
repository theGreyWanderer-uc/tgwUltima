"""CLI for guarded IREG edits with new-file output and a JSON change report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

import typer

from titan.u7.ireg_rewrite import read_ireg_edit_plan, rewrite_ireg_stream


def ireg_rewrite_cmd(
    file: Annotated[
        str, typer.Argument(help="Standalone IREG stream; the source stays unchanged")
    ],
    edits: Annotated[
        str,
        typer.Option(
            "--edits", help="JSON plan with source SHA-256 and expected record hex"
        ),
    ],
    output: Annotated[
        str,
        typer.Option(
            "-o", "--output", help="New output file; existing paths are rejected"
        ),
    ],
    data_format: Annotated[
        Literal["retail", "exult"],
        typer.Option("--format", help="Explicit source format; no format conversion"),
    ],
    static: Annotated[
        Optional[str],
        typer.Option("--static", help="Matching STATIC/TFA for quality and flag edits"),
    ] = None,
    patch_dir: Annotated[
        Optional[str],
        typer.Option("--patch-dir", help="Sparse metadata patch belonging to STATIC"),
    ] = None,
    game: Annotated[Literal["bg", "si"], typer.Option("--game")] = "bg",
    custom_game: Annotated[
        bool, typer.Option("--custom-game", help="Use custom STATIC text defaults")
    ] = False,
) -> None:
    """Rewrite selected IREG records, preserving every unedited byte and source file."""
    from titan.u7.world import WorldQueryParams, load_ireg_context, load_query_metadata

    try:
        source, destination = Path(file), Path(output)
        if destination.resolve() == source.resolve():
            raise ValueError("IREG rewrite: output must differ from the source file")
        if destination.exists():
            raise FileExistsError(f"IREG rewrite: output already exists: {destination}")
        if patch_dir and not static:
            raise ValueError("IREG rewrite: --patch-dir requires --static")
        if custom_game and not static:
            raise ValueError("IREG rewrite: --custom-game requires --static")
        plan = json.loads(Path(edits).read_text(encoding="utf-8"))
        source_hash, changes = read_ireg_edit_plan(plan)
        context = None
        if static:
            params = WorldQueryParams(
                static_dir=static,
                base_static=static,
                patch_dir=patch_dir,
                game=game,
                custom_game=custom_game,
            )
            context = load_ireg_context(params, load_query_metadata(params)[0])
        result = rewrite_ireg_stream(
            source.read_bytes(),
            changes,
            data_format=data_format,
            context=context,
            expected_sha256=source_hash,
        )
        report = result.as_row() | {
            "source": str(source),
            "output": str(destination),
            "format": data_format,
        }
        content = json.dumps(report, indent=2) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with destination.open("xb") as target:
                created = True
                target.write(result.data)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        print(content, end="")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
