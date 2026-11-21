"""``titan u6`` LZW and ``.LIB`` archive commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._meta import meta
from titan.u6.lib import U6Library
from titan.u6.lzw import U6Lzw


def cmd_lzw_decompress(args: SimpleNamespace) -> int:
    """Decompress a single U6 LZW file to raw bytes."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(filepath, "rb") as f:
        data = f.read()
    was_compressed = U6Lzw.is_valid(data)
    decoded = U6Lzw.decompress(data)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{Path(filepath).name}.bin")
    with open(out_path, "wb") as f:
        f.write(decoded)

    label = "LZW-compressed" if was_compressed else "raw (not LZW)"
    print(f"{label}: {len(data)} -> {len(decoded)} bytes -> {out_path}")
    return 0


def cmd_lib_list(args: SimpleNamespace) -> int:
    """List a U6 library file's items (CONVERSE.A/B, PORTRAIT.*, etc.)."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    lib = U6Library.from_file(
        filepath, entry_size=args.entry_size, has_size_header=args.size_header
    )

    print(f"{filepath} — lib_{args.entry_size * 8}, {lib.num_items} items")
    print(f"{'Idx':>5}  {'Offset':>8}  {'Flag':>4}  {'Size':>7}  {'Decoded':>7}")
    print("-" * 42)
    for i in range(lib.num_items):
        item = lib.items[i]
        if item.size == 0:
            print(f"{i:>5}  {'-':>8}  {'-':>4}  {'-':>7}  {'(empty)':>7}")
            continue
        try:
            decoded_len = len(lib.get_item(i))
        except Exception:
            decoded_len = -1
        print(
            f"{i:>5}  {item.offset:>8}  0x{item.flag:02X}  {item.size:>7}  {decoded_len:>7}"
        )
    return 0


def cmd_lib_extract(args: SimpleNamespace) -> int:
    """Extract one item from a U6 library file (decompressed automatically)."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    lib = U6Library.from_file(
        filepath, entry_size=args.entry_size, has_size_header=args.size_header
    )
    if args.item < 0 or args.item >= lib.num_items:
        print(
            f"ERROR: Item {args.item} out of range (0..{lib.num_items - 1})",
            file=sys.stderr,
        )
        return 1

    data = lib.get_item(args.item)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{Path(filepath).name}_{args.item:04d}.bin")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Extracted item {args.item}: {len(data)} bytes -> {out_path}")
    return 0


def cmd_lib_extract_all(args: SimpleNamespace) -> int:
    """Extract every non-empty item from a U6 library file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    lib = U6Library.from_file(
        filepath, entry_size=args.entry_size, has_size_header=args.size_header
    )
    outdir = args.output or f"{Path(filepath).name}_items"
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).name
    extracted = 0
    for i in range(lib.num_items):
        if lib.items[i].size == 0:
            continue
        data = lib.get_item(i)
        out_path = os.path.join(outdir, f"{i:04d}_{base}.bin")
        with open(out_path, "wb") as f:
            f.write(data)
        extracted += 1

    print(f"Extracted {extracted}/{lib.num_items} item(s) -> {outdir}/")
    return 0


@meta(results=("files",), params={"output": "output-dir", "file": "install-file"})
def lzw_decompress_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 LZW-compressed file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Decompress a single U6 LZW file to raw bytes."""
    raise SystemExit(cmd_lzw_decompress(SimpleNamespace(file=file, output=output)))


@meta(results=("text",), params={"file": "install-file"})
def lib_list_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a U6 library file (e.g. CONVERSE.A)")
    ],
    entry_size: Annotated[
        int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")
    ] = 4,
    size_header: Annotated[
        bool,
        typer.Option(
            "--size-header", help="File has a leading 4-byte size header (MD/SE)"
        ),
    ] = False,
) -> None:
    """List a U6 library file's items."""
    raise SystemExit(
        cmd_lib_list(
            SimpleNamespace(file=file, entry_size=entry_size, size_header=size_header)
        )
    )


@meta(results=("files",), params={"output": "output-dir", "file": "install-file"})
def lib_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 library file")],
    item: Annotated[int, typer.Argument(help="Item index to extract")],
    entry_size: Annotated[
        int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")
    ] = 4,
    size_header: Annotated[
        bool,
        typer.Option("--size-header", help="File has a leading 4-byte size header"),
    ] = False,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Extract one item from a U6 library file."""
    raise SystemExit(
        cmd_lib_extract(
            SimpleNamespace(
                file=file,
                item=item,
                entry_size=entry_size,
                size_header=size_header,
                output=output,
            )
        )
    )


@meta(results=("files",), params={"output": "output-dir", "file": "install-file"})
def lib_extract_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U6 library file")],
    entry_size: Annotated[
        int, typer.Option("--entry-size", help="2 for lib_16, 4 for lib_32")
    ] = 4,
    size_header: Annotated[
        bool,
        typer.Option("--size-header", help="File has a leading 4-byte size header"),
    ] = False,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output-dir", help="Output directory (default: <file>_items/)"
        ),
    ] = None,
) -> None:
    """Extract every non-empty item from a U6 library file."""
    raise SystemExit(
        cmd_lib_extract_all(
            SimpleNamespace(
                file=file,
                entry_size=entry_size,
                size_header=size_header,
                output=output,
            )
        )
    )
