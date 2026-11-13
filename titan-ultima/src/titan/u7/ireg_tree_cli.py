"""Inspect and structurally edit guarded Exult world IREG streams or explicit save members."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Optional, cast

import typer

from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_authoring import U7IregCreate, U7IregConvert
from titan.u7.ireg_tree import read_ireg_tree
from titan.u7.ireg_tree_edit import (
    U7IregDelete,
    U7IregReparent,
    U7IregSaveTreeResult,
    U7IregTreeEditResult,
    edit_ireg_save_member,
    edit_ireg_tree,
    read_ireg_save_member,
)


@dataclass(frozen=True)
class U7IregTreePlan:
    """An explicit Exult world-edit plan, optionally embedded in one guarded save occurrence."""

    source_sha256: str
    context_sha256: str
    superchunk: int
    operations: tuple[U7IregDelete | U7IregReparent | U7IregCreate | U7IregConvert, ...]
    save_sha256: str | None = None
    member_path: tuple[int, ...] | None = None


def parse_u7_plan_hash(value: object) -> str:
    """Validate the complete SHA-256 text used by guarded U7 edit plans."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("IREG tree plan: hashes must contain 64 hexadecimal digits")
    return value


def parse_u7_plan_number(value: object, maximum: int = 0xFFFFFFFF) -> int:
    """Validate an unsigned plan integer while rejecting JSON booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise ValueError(f"IREG tree plan: expected integer in 0..{maximum}")
    return value


def read_ireg_tree_plan(value: object) -> U7IregTreePlan:
    """Validate world edit identities, authoring records and explicit placement/loss policies."""
    required = {"source_sha256", "context_sha256", "superchunk", "operations"}
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or set(value) - required - {"save"}
    ):
        raise ValueError(
            "IREG tree plan: requires source_sha256, context_sha256, superchunk and operations"
        )
    source_hash, context_hash = (
        parse_u7_plan_hash(value["source_sha256"]),
        parse_u7_plan_hash(value["context_sha256"]),
    )
    superchunk = parse_u7_plan_number(value["superchunk"], 143)
    if not isinstance(value["operations"], list):
        raise ValueError("IREG tree plan: operations must be an array")
    operations: list[U7IregDelete | U7IregReparent | U7IregCreate | U7IregConvert] = []
    for row in value["operations"]:
        if not isinstance(row, dict):
            raise ValueError("IREG tree plan: operation must be an object")
        if row.get("action") == "delete":
            if set(row) != {
                "action",
                "offset",
                "expected_sha256",
                "cascade",
            } or not isinstance(row["cascade"], bool):
                raise ValueError(
                    "IREG tree plan: delete requires offset, expected_sha256 and boolean cascade"
                )
            operations.append(
                U7IregDelete(
                    parse_u7_plan_number(row["offset"]),
                    parse_u7_plan_hash(row["expected_sha256"]),
                    row["cascade"],
                )
            )
        elif row.get("action") == "reparent":
            if set(row) != {
                "action",
                "offset",
                "expected_sha256",
                "parent_offset",
                "parent_sha256",
                "x",
                "y",
                "lift",
                "index_word",
                "flag_policy",
            } or row["flag_policy"] not in ("preserve", "inherit"):
                raise ValueError(
                    "IREG tree plan: reparent requires explicit parent, placement, index and flag policy"
                )
            parent = (
                None
                if row["parent_offset"] is None
                else parse_u7_plan_number(row["parent_offset"])
            )
            parent_hash = (
                None
                if row["parent_sha256"] is None
                else parse_u7_plan_hash(row["parent_sha256"])
            )
            operations.append(
                U7IregReparent(
                    parse_u7_plan_number(row["offset"]),
                    parse_u7_plan_hash(row["expected_sha256"]),
                    parent,
                    parent_hash,
                    parse_u7_plan_number(row["x"], 3071),
                    parse_u7_plan_number(row["y"], 3071),
                    parse_u7_plan_number(row["lift"], 255),
                    parse_u7_plan_number(row["index_word"], 65535),
                    row["flag_policy"],
                )
            )
        elif row.get("action") == "create":
            if (
                set(row)
                != {
                    "action",
                    "object_id",
                    "record_hex",
                    "parent_offset",
                    "parent_sha256",
                    "x",
                    "y",
                    "lift",
                    "index_word",
                    "flag_policy",
                }
                or not isinstance(row["object_id"], str)
                or not isinstance(row["record_hex"], str)
                or row["flag_policy"] not in ("preserve", "inherit")
            ):
                raise ValueError(
                    "IREG tree plan: creation requires an ID, record hex and explicit placement/policies"
                )
            creation_parent = row["parent_offset"]
            if creation_parent is not None and not isinstance(creation_parent, str):
                creation_parent = parse_u7_plan_number(creation_parent)
            operations.append(
                U7IregCreate(
                    row["object_id"],
                    bytes.fromhex(row["record_hex"]),
                    creation_parent,
                    None
                    if row["parent_sha256"] is None
                    else parse_u7_plan_hash(row["parent_sha256"]),
                    parse_u7_plan_number(row["x"], 3071),
                    parse_u7_plan_number(row["y"], 3071),
                    parse_u7_plan_number(row["lift"], 255),
                    parse_u7_plan_number(row["index_word"], 65535),
                    row["flag_policy"],
                )
            )
        elif row.get("action") in ("convert", "promote"):
            required_conversion = {"action", "offset", "expected_sha256"}
            optional = {
                "shape",
                "frame",
                "lift",
                "record_format",
                "simple_length",
                "body_npc",
                "replacement_hex",
                "allow_data_loss",
                "flag_policy",
            }
            if (
                not required_conversion <= row.keys()
                or set(row) - required_conversion - optional
                or not isinstance(row.get("allow_data_loss", False), bool)
                or row.get("flag_policy", "preserve") not in ("preserve", "inherit")
                or row.get("record_format", "auto")
                not in ("auto", "ordinary", "fd", "fe")
                or row.get("simple_length") not in (None, 6, 10)
            ):
                raise ValueError("IREG tree plan: invalid conversion/promotion fields")
            replacement_hex = row.get("replacement_hex")
            if replacement_hex is not None and not isinstance(replacement_hex, str):
                raise ValueError("IREG tree plan: replacement_hex must be hex text")
            operations.append(
                U7IregConvert(
                    parse_u7_plan_number(row["offset"]),
                    parse_u7_plan_hash(row["expected_sha256"]),
                    None
                    if "shape" not in row
                    else parse_u7_plan_number(row["shape"], 65535),
                    None
                    if "frame" not in row
                    else parse_u7_plan_number(row["frame"], 255),
                    None
                    if "lift" not in row
                    else parse_u7_plan_number(row["lift"], 255),
                    row.get("record_format", "auto"),
                    cast(
                        Literal[6, 10] | None,
                        None
                        if row.get("simple_length") is None
                        else parse_u7_plan_number(row["simple_length"], 10),
                    ),
                    None
                    if "body_npc" not in row
                    else parse_u7_plan_number(row["body_npc"], 65535),
                    bytes.fromhex(replacement_hex)
                    if replacement_hex is not None
                    else None,
                    row.get("allow_data_loss", False),
                    row.get("flag_policy", "preserve"),
                )
            )
        else:
            raise ValueError(
                "IREG tree plan: action must be delete, reparent, create, convert or promote"
            )
    save_hash: str | None = None
    member_path: tuple[int, ...] | None = None
    if "save" in value:
        saved = value["save"]
        if not isinstance(saved, dict) or set(saved) != {
            "source_sha256",
            "member_path",
        }:
            raise ValueError(
                "IREG tree plan: save requires source_sha256 and member_path"
            )
        save_hash = parse_u7_plan_hash(saved["source_sha256"])
        path = saved["member_path"]
        if not isinstance(path, list) or not 1 <= len(path) <= 16:
            raise ValueError(
                "IREG tree plan: member_path must contain 1..16 occurrence indices"
            )
        member_path = tuple(parse_u7_plan_number(index) for index in path)
    return U7IregTreePlan(
        source_hash, context_hash, superchunk, tuple(operations), save_hash, member_path
    )


def load_ireg_cli_context(
    static: str, patch_dir: str | None, game: str, custom_game: bool
) -> U7IregContext:
    """Load matching CLI metadata for guarded world/actor writers."""
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
    )
    return load_ireg_context(params, load_query_metadata(params)[0])


def write_new_u7_output(path: Path, data: bytes) -> None:
    """Write an exclusive new U7 output and remove a partial file if writing fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(data)
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


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
        raise SystemExit(1) from error


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
        raise SystemExit(1) from error
