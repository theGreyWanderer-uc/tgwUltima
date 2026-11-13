"""Guarded save repacking CLI: occurrence paths, payload hashes and new output files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from titan.u7.save_repack import U7SaveReplacement, check_u7_save_hash, repack_u7_save


def read_u7_repack_plan(
    plan_path: Path, source: bytes
) -> tuple[U7SaveReplacement, ...]:
    """Read explicit replacement files relative to the plan; require source and member hashes."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or set(plan) != {"source_sha256", "replacements"}:
        raise ValueError(
            "U7 save repack: plan requires only source_sha256 and replacements"
        )
    check_u7_save_hash(plan["source_sha256"], source, "source")
    rows = plan["replacements"]
    if not isinstance(rows, list):
        raise ValueError("U7 save repack: replacements must be an array")
    replacements: list[U7SaveReplacement] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "member_path",
            "expected_sha256",
            "file",
        }:
            raise ValueError(
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
            raise ValueError(
                "U7 save repack: member_path needs 1..16 nonnegative integer occurrence indices"
            )
        if (
            not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None
        ):
            raise ValueError(
                "U7 save repack: expected_sha256 must have 64 hexadecimal digits"
            )
        if not isinstance(filename, str) or not filename:
            raise ValueError("U7 save repack: replacement file must be a nonempty path")
        replacement_file = Path(filename)
        if not replacement_file.is_absolute():
            replacement_file = plan_path.parent / replacement_file
        replacements.append(
            U7SaveReplacement(tuple(path), replacement_file.read_bytes(), expected)
        )
    return tuple(replacements)


def save_repack_cmd(
    file: Annotated[
        str, typer.Argument(help="Source U7 named Flex or ZIP save/INITGAME")
    ],
    plan: Annotated[
        str,
        typer.Option(
            "--plan", help="JSON plan with source/member hashes and replacement files"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="New output archive; existing paths are rejected"
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Validate and report without writing an archive"
        ),
    ] = False,
) -> None:
    """Repack selected save occurrences, retaining unedited members and container metadata."""
    try:
        source = Path(file)
        destination = Path(output) if output is not None else None
        if destination is None and not dry_run:
            raise ValueError(
                "U7 save repack: --output is required unless --dry-run is selected"
            )
        if destination is not None:
            if destination.resolve() == source.resolve():
                raise ValueError(
                    "U7 save repack: output must differ from the source file"
                )
            if destination.exists():
                raise FileExistsError(
                    f"U7 save repack: output already exists: {destination}"
                )
        raw = source.read_bytes()
        replacements = read_u7_repack_plan(Path(plan), raw)
        result = repack_u7_save(raw, replacements)
        report = result.as_row() | {
            "source": str(source),
            "output": str(destination) if destination else None,
            "dry_run": dry_run,
        }
        content = json.dumps(report, indent=2) + "\n"
        if destination is not None and not dry_run:
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
