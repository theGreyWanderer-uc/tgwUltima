"""``titan u7 ireg-rewrite`` / ``ireg-tree`` / ``ireg-tree-edit``: guarded world IREG edits."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

import typer

from titan._meta import meta
from titan.u7.edit_plans import (
    read_ireg_tree_plan,
    write_new_u7_output,
)
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_rewrite import read_ireg_edit_plan, rewrite_ireg_stream
from titan.u7.ireg_tree import read_ireg_tree
from titan.u7.ireg_tree_edit import (
    U7IregSaveTreeResult,
    U7IregTreeEditResult,
    edit_ireg_save_member,
    edit_ireg_tree,
    read_ireg_save_member,
)
from titan.errors import exit_code


@meta(
    results=("file",),
    params={"output": "output-file", "file": "input-file", "edits": "input-file"},
)
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
        raise SystemExit(exit_code(error)) from error


def load_ireg_cli_context(
    static: str, patch_dir: str | None, game: str, custom_game: bool
) -> U7IregContext:
    """Load matching CLI metadata for guarded world/actor writers."""
    from titan.u7.install import resolve_u7_exult_flx
    from titan.u7.world import WorldQueryParams, load_ireg_context, load_query_metadata

    if not Path(static).is_dir():
        raise ValueError(
            "IREG tree: --static must name an existing matching STATIC directory"
        )
    params = WorldQueryParams(
        static_dir=static,
        base_static=static,
        patch_dir=patch_dir,
        game=game,
        custom_game=custom_game,
        exult_flx_path=resolve_u7_exult_flx(game),
    )
    return load_ireg_context(params, load_query_metadata(params)[0])


@meta(results=("json",), params={"output": "output-file", "file": "input-file"})
def ireg_tree_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Exult standalone world IREG, or a save with --member-path"
        ),
    ],
    static: Annotated[
        str,
        typer.Option("--static", help="Matching STATIC for unambiguous class dispatch"),
    ],
    superchunk: Annotated[int, typer.Option("--superchunk", min=0, max=143)],
    member_path: Annotated[
        Optional[str],
        typer.Option(
            "--member-path", help="Comma-separated save occurrence indices, e.g. 7,2"
        ),
    ] = None,
    patch_dir: Annotated[Optional[str], typer.Option("--patch-dir")] = None,
    game: Annotated[Literal["bg", "si"], typer.Option("--game")] = "bg",
    custom_game: Annotated[bool, typer.Option("--custom-game")] = False,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="New JSON file; default stdout"),
    ] = None,
) -> None:
    """Inspect lossless hierarchy, special owners, inherited flags and guarded edit identities."""
    try:
        source = Path(file)
        raw = source.read_bytes()
        saved: dict[str, object] | None = None
        if member_path is not None:
            if re.fullmatch(r"[0-9]+(?:,[0-9]+)*", member_path) is None:
                raise ValueError(
                    "IREG tree: --member-path needs comma-separated occurrence indices"
                )
            path = tuple(int(index) for index in member_path.split(","))
            saved = {
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "member_path": list(path),
            }
            raw = read_ireg_save_member(raw, path, superchunk=superchunk)
        context = load_ireg_cli_context(static, patch_dir, game, custom_game)
        report = read_ireg_tree(raw, context=context, superchunk=superchunk).as_row()
        if saved is not None:
            report["save"] = saved
        content = json.dumps(report, indent=2) + "\n"
        if output is not None:
            destination = Path(output)
            if destination.resolve() == source.resolve():
                raise ValueError("IREG tree: output must differ from source")
            write_new_u7_output(destination, content.encode("utf-8"))
        else:
            print(content, end="")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(exit_code(error)) from error


@meta(results=("file",), params={"output": "output-file", "file": "input-file"})
def ireg_tree_edit_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Source world IREG or save, explicitly selected by the plan"
        ),
    ],
    plan: Annotated[
        str,
        typer.Option(
            "--plan", help="Guarded object authoring plan from ireg-tree identities"
        ),
    ],
    static: Annotated[
        str,
        typer.Option(
            "--static",
            help="Matching STATIC; dispatch fingerprint must match inspection",
        ),
    ],
    patch_dir: Annotated[Optional[str], typer.Option("--patch-dir")] = None,
    game: Annotated[Literal["bg", "si"], typer.Option("--game")] = "bg",
    custom_game: Annotated[bool, typer.Option("--custom-game")] = False,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="New IREG or save archive; never overwrite existing files",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Validate the hierarchy and save embedding without writing",
        ),
    ] = False,
) -> None:
    """Create, convert, promote, delete or reparent Exult world objects and optionally repack a save."""
    try:
        source = Path(file)
        destination = Path(output) if output is not None else None
        if destination is None and not dry_run:
            raise ValueError(
                "IREG tree edit: --output is required unless --dry-run is selected"
            )
        if destination is not None and (
            destination.resolve() == source.resolve() or destination.exists()
        ):
            raise ValueError(
                "IREG tree edit: output must be a new path different from source"
            )
        instructions = read_ireg_tree_plan(
            json.loads(Path(plan).read_text(encoding="utf-8"))
        )
        context = load_ireg_cli_context(static, patch_dir, game, custom_game)
        raw = source.read_bytes()
        result: U7IregTreeEditResult | U7IregSaveTreeResult
        if (
            instructions.member_path is not None
            and instructions.save_sha256 is not None
        ):
            result = edit_ireg_save_member(
                raw,
                instructions.member_path,
                instructions.operations,
                context=context,
                superchunk=instructions.superchunk,
                expected_save_sha256=instructions.save_sha256,
                expected_member_sha256=instructions.source_sha256,
                expected_context_sha256=instructions.context_sha256,
            )
            mode = "save_member"
        else:
            result = edit_ireg_tree(
                raw,
                instructions.operations,
                context=context,
                superchunk=instructions.superchunk,
                expected_sha256=instructions.source_sha256,
                expected_context_sha256=instructions.context_sha256,
            )
            mode = "world_stream"
        report = result.as_row() | {
            "mode": mode,
            "source": str(source),
            "output": str(destination) if destination else None,
            "dry_run": dry_run,
        }
        content = json.dumps(report, indent=2) + "\n"
        if destination is not None and not dry_run:
            write_new_u7_output(destination, result.data)
        print(content, end="")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(exit_code(error)) from error
