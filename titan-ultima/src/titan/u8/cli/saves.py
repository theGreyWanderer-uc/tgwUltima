"""``titan u8 save-list`` / ``save-extract`` — savegame archive commands."""

from __future__ import annotations

__all__ = ["save_list_cmd", "save_extract_cmd"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u8.save import U8SaveArchive


def cmd_save_list(args: SimpleNamespace) -> int:
    """List contents of a U8 save file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        save = U8SaveArchive.from_file(filepath)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    entries = save.list_entries()

    print(f"U8 Save Archive: {filepath}")
    print(f"Entries: {len(entries)}")
    print(f"{'Name':<24} {'Size':>10}")
    print("-" * 36)
    total = 0
    for name, size in entries:
        print(f"{name:<24} {size:>10,}")
        total += size
    print("-" * 36)
    print(f"{'Total':<24} {total:>10,}")
    return 0


def cmd_save_extract(args: SimpleNamespace) -> int:
    """Extract files from a U8 save archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        save = U8SaveArchive.from_file(filepath)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    entries = save.list_entries()

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    entry_filter = getattr(args, "entry", None)
    extracted = 0
    for name, size in entries:
        if entry_filter and name != entry_filter:
            continue
        data = save.get_data(name)
        if data is None:
            continue
        out_path = os.path.join(outdir, name)
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"  {name:<24} {size:>10,} bytes")
        extracted += 1

    if entry_filter and extracted == 0:
        print(f"ERROR: Entry '{entry_filter}' not found in archive", file=sys.stderr)
        return 1

    outdir_display = outdir.rstrip("/\\") + "/"
    print(f"\nExtracted {extracted} file(s) -> {outdir_display}")
    return 0


def save_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to U8 save file")],
) -> None:
    """List contents of a U8 save file (U8SAVE.000, etc.)."""
    raise SystemExit(cmd_save_list(SimpleNamespace(file=file)))


def save_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to U8 save file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    entry: Annotated[
        Optional[str],
        typer.Option("--entry", help="Extract only this named entry"),
    ] = None,
) -> None:
    """Extract files from a U8 save archive."""
    raise SystemExit(
        cmd_save_extract(
            SimpleNamespace(
                file=file,
                output=output,
                entry=entry,
            )
        )
    )
