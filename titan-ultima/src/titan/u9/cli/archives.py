"""``titan u9 flx-*`` — FLX archive listing, extraction and packing."""

from __future__ import annotations

__all__ = [
    "flx_list_cmd",
    "flx_extract_cmd",
    "flx_extract_all_cmd",
    "flx_pack_cmd",
    "flx_repack_cmd",
]

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.flx_writer import U9FlxWriteError, repack, repack_equivalent, write_flx


def cmd_flx_list(args: SimpleNamespace) -> int:
    """List an Ultima 9 FLX archive's directory entries."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    used = archive.used_entry_indices()
    print(f"{filepath} — {archive.num_entries} entries ({len(used)} used)")
    print(f"comment: {archive.comment!r}")
    print(f"{'Idx':>6}  {'Offset':>10}  {'Length':>10}")
    print("-" * 32)
    for entry in archive.entries:
        if not entry.is_used:
            continue
        print(f"{entry.index:>6}  {entry.offset:>10}  {entry.length:>10}")
    return 0


def cmd_flx_extract(args: SimpleNamespace) -> int:
    """Extract one entry from an Ultima 9 FLX archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.index < 0 or args.index >= archive.num_entries:
        print(
            f"ERROR: Index {args.index} out of range (0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
        return 1

    data = archive.read_entry(args.index)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{Path(filepath).stem}_{args.index:05d}.bin")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Extracted entry {args.index}: {len(data)} bytes -> {out_path}")
    return 0


def cmd_flx_extract_all(args: SimpleNamespace) -> int:
    """Extract every used entry from an Ultima 9 FLX archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_entries"
    os.makedirs(outdir, exist_ok=True)

    extracted = 0
    for entry in archive.entries:
        if not entry.is_used:
            continue
        data = archive.read_entry(entry.index)
        out_path = os.path.join(outdir, f"{entry.index:05d}.bin")
        with open(out_path, "wb") as f:
            f.write(data)
        extracted += 1

    print(f"Extracted {extracted}/{archive.num_entries} entries -> {outdir}/")
    return 0


_FLX_ENTRY_RE = re.compile(r"^(\d+)\.bin$", re.IGNORECASE)


def _entries_from_dir(directory: str) -> Optional[dict]:
    """Read NNNNN.bin files back into an {index: blob} table."""
    if not os.path.isdir(directory):
        print(f"ERROR: Directory not found: {directory}", file=sys.stderr)
        return None
    entries: dict = {}
    skipped = 0
    for name in sorted(os.listdir(directory)):
        match = _FLX_ENTRY_RE.match(name)
        if match is None:
            skipped += 1
            continue
        with open(os.path.join(directory, name), "rb") as f:
            entries[int(match.group(1))] = f.read()
    if not entries:
        print(f"ERROR: No NNNNN.bin entry files in {directory}", file=sys.stderr)
        return None
    if skipped:
        print(f"  (ignored {skipped} file(s) not named NNNNN.bin)")
    return entries


def cmd_flx_pack(args: SimpleNamespace) -> int:
    """Build an FLX archive from a directory of NNNNN.bin entry files."""
    entries = _entries_from_dir(args.directory)
    if entries is None:
        return 1
    try:
        written = write_flx(
            args.output, entries, count=args.count, comment=args.comment
        )
    except U9FlxWriteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    slots = args.count if args.count is not None else max(entries) + 1
    print(
        f"Packed {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
        f"into {slots} slot(s) -> {args.output} ({written} bytes)"
    )
    if args.count is None:
        print("  Slot count was inferred. Pass --count to match an original archive.")
    return 0


def cmd_flx_repack(args: SimpleNamespace) -> int:
    """Rebuild an FLX archive, optionally replacing entries, and verify the result."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    try:
        archive = U9FlxArchive.from_file(args.file)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    replacements: dict = {}
    if args.replace:
        entries = _entries_from_dir(args.replace)
        if entries is None:
            return 1
        replacements = entries

    try:
        data = repack(archive, replacements)
    except U9FlxWriteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    with open(args.file, "rb") as f:
        original = f.read()

    identical = data == original
    equivalent = repack_equivalent(original, data)

    out_path = args.output or (Path(args.file).stem + "_repacked.flx")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    print(
        f"{args.file} -- {len(archive.used_entry_indices())} used of "
        f"{archive.num_entries} slot(s)"
    )
    if replacements:
        print(
            f"  Replaced        : {len(replacements)} entr"
            f"{'y' if len(replacements) == 1 else 'ies'}"
        )
    print(
        f"  Written         : {out_path} ({len(data)} bytes, "
        f"{len(data) - len(original):+d})"
    )
    if not replacements:
        print(f"  Byte-identical  : {'yes' if identical else 'no'}")
        print(f"  Same contents   : {'yes' if equivalent else 'NO -- THIS IS A BUG'}")
        if not identical and equivalent:
            print("  The rebuild drops bytes no directory entry points at, and may")
            print("  reorder payloads. Every entry the archive declares is preserved.")
    return 0 if (equivalent or replacements) else 1


def flx_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
) -> None:
    """List an Ultima 9 FLX archive's directory entries."""
    raise SystemExit(cmd_flx_list(SimpleNamespace(file=file)))


def flx_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
    index: Annotated[int, typer.Argument(help="Entry index to extract")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract one entry from an Ultima 9 FLX archive."""
    raise SystemExit(
        cmd_flx_extract(SimpleNamespace(file=file, index=index, output=output))
    )


def flx_extract_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: <file>_entries/)"
        ),
    ] = None,
) -> None:
    """Extract every used entry from an Ultima 9 FLX archive."""
    raise SystemExit(cmd_flx_extract_all(SimpleNamespace(file=file, output=output)))


def flx_pack_cmd(
    directory: Annotated[
        str, typer.Argument(help="Directory of NNNNN.bin entry files")
    ],
    output: Annotated[str, typer.Argument(help="Output .flx path")],
    count: Annotated[
        Optional[int],
        typer.Option(
            "-c", "--count", help="Directory slot count (default: smallest that fits)"
        ),
    ] = None,
    comment: Annotated[
        Optional[str],
        typer.Option("--comment", help="ASCII comment, max 76 bytes"),
    ] = None,
) -> None:
    """Build a U9 FLX archive from extracted entry files."""
    raise SystemExit(
        cmd_flx_pack(
            SimpleNamespace(
                directory=directory, output=output, count=count, comment=comment
            )
        )
    )


def flx_repack_cmd(
    file: Annotated[str, typer.Argument(help="Path to an existing U9 FLX archive")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output path (default: <stem>_repacked.flx)"
        ),
    ] = None,
    replace: Annotated[
        Optional[str],
        typer.Option("-r", "--replace", help="Directory of NNNNN.bin files to swap in"),
    ] = None,
) -> None:
    """Rebuild a U9 FLX archive, optionally replacing entries, and verify it."""
    raise SystemExit(
        cmd_flx_repack(SimpleNamespace(file=file, output=output, replace=replace))
    )
