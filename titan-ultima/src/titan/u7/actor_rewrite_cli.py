"""Actor header inspection, explicit edit plans and new-file save embedding commands."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer

from titan.u7.actor_rewrite import (
    ActorFileKind,
    ActorSourceFlavor,
    U7ActorHeaderEdit,
    read_actor_save_member,
    read_actor_wire_file,
    rewrite_actor_file,
    rewrite_actor_save,
)
from titan.u7.ireg_tree import ireg_context_sha256
from titan.u7.ireg_tree_cli import load_ireg_cli_context, write_new_u7_output


@dataclass(frozen=True)
class U7ActorEditPlan:
    """A flavor-explicit actor edit plan, optionally targeting one save occurrence."""

    source_sha256: str
    context_sha256: str
    game: Literal["bg", "si"]
    kind: ActorFileKind
    flavor: ActorSourceFlavor
    edits: tuple[U7ActorHeaderEdit, ...]
    save_sha256: str | None = None
    member_path: tuple[int, ...] | None = None


def read_actor_edit_plan(value: object) -> U7ActorEditPlan:
    """Validate JSON actor edit identities, source flavor, header operations and optional save path."""
    from titan.u7.ireg_tree_cli import parse_u7_plan_hash, parse_u7_plan_number

    required = {"source_sha256", "context_sha256", "game", "kind", "flavor", "edits"}
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or set(value) - required - {"save"}
    ):
        raise ValueError(
            "Actor rewrite plan: source/context/game/kind/flavor/edits are required"
        )
    if (
        value["game"] not in ("bg", "si")
        or value["kind"] not in ("npc", "monsters")
        or value["flavor"] not in ("runtime", "original-new-game")
        or not isinstance(value["edits"], list)
    ):
        raise ValueError("Actor rewrite plan: invalid game/kind/flavor/edits")
    edits = []
    for row in value["edits"]:
        if not isinstance(row, dict) or set(row) not in (
            {"index", "expected_sha256", "fields"},
            {"index", "expected_sha256", "header_hex"},
        ):
            raise ValueError(
                "Actor rewrite plan: each actor needs index, hash and fields or header_hex"
            )
        fields = row.get("fields", {})
        if not isinstance(fields, dict) or any(
            not isinstance(key, str)
            or isinstance(item, bool)
            or not isinstance(item, (int, str))
            for key, item in fields.items()
        ):
            raise ValueError(
                "Actor rewrite plan: fields must map names to integers or strings"
            )
        if "header_hex" in row and not isinstance(row["header_hex"], str):
            raise ValueError("Actor rewrite plan: header_hex must be hex text")
        edits.append(
            U7ActorHeaderEdit(
                parse_u7_plan_number(row["index"]),
                parse_u7_plan_hash(row["expected_sha256"]),
                fields,
                bytes.fromhex(row["header_hex"]) if "header_hex" in row else None,
            )
        )
    save_hash = None
    path = None
    if "save" in value:
        saved = value["save"]
        if (
            not isinstance(saved, dict)
            or set(saved) != {"source_sha256", "member_path"}
            or not isinstance(saved["member_path"], list)
            or not 1 <= len(saved["member_path"]) <= 16
        ):
            raise ValueError(
                "Actor rewrite plan: save requires archive hash and 1..16 occurrence indices"
            )
        save_hash = parse_u7_plan_hash(saved["source_sha256"])
        path = tuple(parse_u7_plan_number(index) for index in saved["member_path"])
    return U7ActorEditPlan(
        parse_u7_plan_hash(value["source_sha256"]),
        parse_u7_plan_hash(value["context_sha256"]),
        value["game"],
        value["kind"],
        value["flavor"],
        tuple(edits),
        save_hash,
        path,
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
        raise SystemExit(1) from error


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
        raise SystemExit(1) from error
