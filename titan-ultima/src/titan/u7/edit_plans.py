"""Guarded U7 edit plans: the JSON plans ``ireg-tree-edit``, ``actor-rewrite`` and
``save-repack`` read, validated before anything is written, and the exclusive
output writer they share. No terminal or config access; the commands are in
``titan.u7.cli.ireg``, ``titan.u7.cli.actors`` and ``titan.u7.cli.saves``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from titan.u7.actor_rewrite import (
    ActorFileKind,
    ActorSourceFlavor,
    U7ActorHeaderEdit,
)
from titan.u7.ireg_authoring import U7IregConvert, U7IregCreate
from titan.u7.ireg_tree_edit import (
    U7IregDelete,
    U7IregReparent,
)
from titan.u7.save_repack import U7SaveReplacement, check_u7_save_hash
from titan.errors import InvalidDataError


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
        raise InvalidDataError(
            "IREG tree plan: hashes must contain 64 hexadecimal digits"
        )
    return value


def parse_u7_plan_number(value: object, maximum: int = 0xFFFFFFFF) -> int:
    """Validate an unsigned plan integer while rejecting JSON booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise InvalidDataError(f"IREG tree plan: expected integer in 0..{maximum}")
    return value


def read_ireg_tree_plan(value: object) -> U7IregTreePlan:
    """Validate world edit identities, authoring records and explicit placement/loss policies."""
    required = {"source_sha256", "context_sha256", "superchunk", "operations"}
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or set(value) - required - {"save"}
    ):
        raise InvalidDataError(
            "IREG tree plan: requires source_sha256, context_sha256, superchunk and operations"
        )
    source_hash, context_hash = (
        parse_u7_plan_hash(value["source_sha256"]),
        parse_u7_plan_hash(value["context_sha256"]),
    )
    superchunk = parse_u7_plan_number(value["superchunk"], 143)
    if not isinstance(value["operations"], list):
        raise InvalidDataError("IREG tree plan: operations must be an array")
    operations: list[U7IregDelete | U7IregReparent | U7IregCreate | U7IregConvert] = []
    for row in value["operations"]:
        if not isinstance(row, dict):
            raise InvalidDataError("IREG tree plan: operation must be an object")
        if row.get("action") == "delete":
            if set(row) != {
                "action",
                "offset",
                "expected_sha256",
                "cascade",
            } or not isinstance(row["cascade"], bool):
                raise InvalidDataError(
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
                raise InvalidDataError(
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
                raise InvalidDataError(
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
                raise InvalidDataError(
                    "IREG tree plan: invalid conversion/promotion fields"
                )
            replacement_hex = row.get("replacement_hex")
            if replacement_hex is not None and not isinstance(replacement_hex, str):
                raise InvalidDataError(
                    "IREG tree plan: replacement_hex must be hex text"
                )
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
            raise InvalidDataError(
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
            raise InvalidDataError(
                "IREG tree plan: save requires source_sha256 and member_path"
            )
        save_hash = parse_u7_plan_hash(saved["source_sha256"])
        path = saved["member_path"]
        if not isinstance(path, list) or not 1 <= len(path) <= 16:
            raise InvalidDataError(
                "IREG tree plan: member_path must contain 1..16 occurrence indices"
            )
        member_path = tuple(parse_u7_plan_number(index) for index in path)
    return U7IregTreePlan(
        source_hash, context_hash, superchunk, tuple(operations), save_hash, member_path
    )


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
    required = {"source_sha256", "context_sha256", "game", "kind", "flavor", "edits"}
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or set(value) - required - {"save"}
    ):
        raise InvalidDataError(
            "Actor rewrite plan: source/context/game/kind/flavor/edits are required"
        )
    if (
        value["game"] not in ("bg", "si")
        or value["kind"] not in ("npc", "monsters")
        or value["flavor"] not in ("runtime", "original-new-game")
        or not isinstance(value["edits"], list)
    ):
        raise InvalidDataError("Actor rewrite plan: invalid game/kind/flavor/edits")
    edits = []
    for row in value["edits"]:
        if not isinstance(row, dict) or set(row) not in (
            {"index", "expected_sha256", "fields"},
            {"index", "expected_sha256", "header_hex"},
        ):
            raise InvalidDataError(
                "Actor rewrite plan: each actor needs index, hash and fields or header_hex"
            )
        fields = row.get("fields", {})
        if not isinstance(fields, dict) or any(
            not isinstance(key, str)
            or isinstance(item, bool)
            or not isinstance(item, (int, str))
            for key, item in fields.items()
        ):
            raise InvalidDataError(
                "Actor rewrite plan: fields must map names to integers or strings"
            )
        if "header_hex" in row and not isinstance(row["header_hex"], str):
            raise InvalidDataError("Actor rewrite plan: header_hex must be hex text")
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
            raise InvalidDataError(
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


def read_u7_repack_plan(
    plan_path: Path, source: bytes
) -> tuple[U7SaveReplacement, ...]:
    """Read explicit replacement files relative to the plan; require source and member hashes."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or set(plan) != {"source_sha256", "replacements"}:
        raise InvalidDataError(
            "U7 save repack: plan requires only source_sha256 and replacements"
        )
    check_u7_save_hash(plan["source_sha256"], source, "source")
    rows = plan["replacements"]
    if not isinstance(rows, list):
        raise InvalidDataError("U7 save repack: replacements must be an array")
    replacements: list[U7SaveReplacement] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "member_path",
            "expected_sha256",
            "file",
        }:
            raise InvalidDataError(
                "U7 save repack: each replacement needs member_path, expected_sha256 and file"
            )
        path, expected, filename = (
            row["member_path"],
            row["expected_sha256"],
            row["file"],
        )
        if (
            not isinstance(path, list)
            or not 1 <= len(path) <= 16
            or any(
                isinstance(index, bool) or not isinstance(index, int) or index < 0
                for index in path
            )
        ):
            raise InvalidDataError(
                "U7 save repack: member_path needs 1..16 nonnegative integer occurrence indices"
            )
        if (
            not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None
        ):
            raise InvalidDataError(
                "U7 save repack: expected_sha256 must have 64 hexadecimal digits"
            )
        if not isinstance(filename, str) or not filename:
            raise InvalidDataError(
                "U7 save repack: replacement file must be a nonempty path"
            )
        replacement_file = Path(filename)
        if not replacement_file.is_absolute():
            replacement_file = plan_path.parent / replacement_file
        replacements.append(
            U7SaveReplacement(tuple(path), replacement_file.read_bytes(), expected)
        )
    return tuple(replacements)
