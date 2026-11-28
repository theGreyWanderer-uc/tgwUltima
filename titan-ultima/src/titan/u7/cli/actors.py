"""``titan u7 actor-headers`` / ``actor-rewrite``: guarded actor header edits."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Annotated, Literal

import typer

from titan._meta import meta
from titan.u7.actor_rewrite import (
    ActorFileKind,
    ActorSourceFlavor,
    read_actor_save_member,
    read_actor_wire_file,
    rewrite_actor_file,
    rewrite_actor_save,
)
from titan.u7.cli.ireg import load_ireg_cli_context
from titan.u7.edit_plans import (
    read_actor_edit_plan,
    write_new_u7_output,
)
from titan.u7.ireg_tree import ireg_context_sha256
from titan.errors import exit_code


@meta(
    category="characters",
    results=("json",),
    params={"output": "output-file", "file": "input-file"},
)
def actor_headers_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Loose NPC.DAT/MONSNPCS.DAT, or save with --member-path"),
    ],
    static: Annotated[str, typer.Option("--static")],
    game: Annotated[Literal["bg", "si"], typer.Option("--game")],
    flavor: Annotated[
        ActorSourceFlavor,
        typer.Option("--flavor", help="Explicit source interpretation"),
    ],
    kind: Annotated[ActorFileKind, typer.Option("--kind")] = "npc",
    member_path: Annotated[str | None, typer.Option("--member-path")] = None,
    patch_dir: Annotated[str | None, typer.Option("--patch-dir")] = None,
    custom_game: Annotated[bool, typer.Option("--custom-game")] = False,
    output: Annotated[str | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Inspect lossless actor headers and exact record hashes for a guarded edit plan."""
    try:
        source = Path(file)
        raw = source.read_bytes()
        saved = None
        if member_path is not None:
            if any(
                not part.isascii() or not part.isdigit()
                for part in member_path.split(",")
            ):
                raise ValueError(
                    "Actor headers: member path must contain comma-separated indices"
                )
            path = tuple(int(part) for part in member_path.split(","))
            saved = {
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "member_path": list(path),
            }
            raw = read_actor_save_member(raw, path, kind=kind)
        context = load_ireg_cli_context(static, patch_dir, game, custom_game)
        actors = read_actor_wire_file(raw, context=context, kind=kind, flavor=flavor)
        report: dict[str, object] = {
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "context_sha256": ireg_context_sha256(context),
            "game": game,
            "flavor": flavor,
            "kind": kind,
            "actors": [actor.as_row() for actor in actors.actors],
            "trailing_hex": actors.trailing.hex(),
        }
        if saved is not None:
            report["save"] = saved
        content = json.dumps(report, indent=2) + "\n"
        if output:
            if Path(output).resolve() == source.resolve():
                raise ValueError("Actor headers: output must differ from source")
            write_new_u7_output(Path(output), content.encode("utf-8"))
        else:
            print(content, end="")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(exit_code(error)) from error


@meta(
    category="characters",
    results=("file",),
    params={"output": "output-file", "file": "input-file"},
)
def actor_rewrite_cmd(
    file: Annotated[
        str, typer.Argument(help="Loose actor stream or explicitly selected save")
    ],
    plan: Annotated[str, typer.Option("--plan")],
    static: Annotated[str, typer.Option("--static")],
    patch_dir: Annotated[str | None, typer.Option("--patch-dir")] = None,
    custom_game: Annotated[bool, typer.Option("--custom-game")] = False,
    output: Annotated[str | None, typer.Option("-o", "--output")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Write guarded actor headers, preserving inventories/specials, optionally into a new save."""
    try:
        source = Path(file)
        destination = Path(output) if output is not None else None
        if (
            destination is None
            and not dry_run
            or destination is not None
            and (destination.resolve() == source.resolve() or destination.exists())
        ):
            raise ValueError(
                "Actor rewrite: --output must be a new path unless using --dry-run"
            )
        instructions = read_actor_edit_plan(
            json.loads(Path(plan).read_text(encoding="utf-8"))
        )
        context = load_ireg_cli_context(
            static, patch_dir, instructions.game, custom_game
        )
        raw = source.read_bytes()
        if (
            instructions.member_path is not None
            and instructions.save_sha256 is not None
        ):
            edited, report = rewrite_actor_save(
                raw,
                instructions.member_path,
                instructions.edits,
                context=context,
                kind=instructions.kind,
                flavor=instructions.flavor,
                expected_save_sha256=instructions.save_sha256,
                expected_sha256=instructions.source_sha256,
                expected_context_sha256=instructions.context_sha256,
            )
        else:
            result = rewrite_actor_file(
                raw,
                instructions.edits,
                context=context,
                kind=instructions.kind,
                flavor=instructions.flavor,
                expected_sha256=instructions.source_sha256,
                expected_context_sha256=instructions.context_sha256,
            )
            edited, report = result.data, result.as_row()
        report.update(
            {
                "source": str(source),
                "output": str(destination) if destination else None,
                "dry_run": dry_run,
            }
        )
        if destination is not None and not dry_run:
            write_new_u7_output(destination, edited)
        print(json.dumps(report, indent=2))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(exit_code(error)) from error
