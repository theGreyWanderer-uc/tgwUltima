"""``titan u6`` conversation, look and book text commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._meta import meta
from titan.u6.book import U6Books
from titan.u6.converse import disassemble, format_instructions
from titan.u6.lib import U6Library
from titan.u6.look import U6ObjectNames


def cmd_converse_dump(args: SimpleNamespace) -> int:
    """Disassemble one or all scripts from a CONVERSE.A/B library file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    lib = U6Library.from_file(
        filepath, entry_size=args.entry_size, has_size_header=args.size_header
    )

    if args.item is not None:
        if args.item < 0 or args.item >= lib.num_items:
            print(
                f"ERROR: Item {args.item} out of range (0..{lib.num_items - 1})",
                file=sys.stderr,
            )
            return 1
        items = [args.item]
    else:
        items = [i for i in range(lib.num_items) if lib.items[i].size > 0]

    outdir = args.output
    base = Path(filepath).name
    dumped = 0
    for i in items:
        try:
            script = lib.get_item(i)
            text = format_instructions(disassemble(script))
        except Exception as e:
            print(f"  WARNING: Failed to disassemble item {i}: {e}", file=sys.stderr)
            continue
        if outdir:
            os.makedirs(outdir, exist_ok=True)
            out_path = os.path.join(outdir, f"{i:04d}_{base}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        else:
            print(f"=== item {i} ===")
            print(text)
        dumped += 1

    if outdir:
        print(f"Disassembled {dumped}/{len(items)} item(s) -> {outdir}/")
    return 0


def cmd_look_dump(args: SimpleNamespace) -> int:
    """Dump LOOK.LZD's tile-number -> object-name table."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    names = U6ObjectNames.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "look_dump.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"LOOK.LZD — {len(names.entries)} entries\n")
        f.write("=" * 60 + "\n")
        f.write("Each entry's tile number is the LAST tile in the range it\n")
        f.write("names; a tile with no entry of its own uses the next\n")
        f.write("higher tile number that has one.\n\n")
        for e in names.entries:
            f.write(f"{e.tile_num:>5}  {e.name}\n")

    print(f"Dumped {len(names.entries)} entries -> {out_path}")
    return 0


def cmd_book_dump(args: SimpleNamespace) -> int:
    """Dump one or all book/sign texts from BOOK.DAT."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    books = U6Books.from_file(filepath)

    if args.book is not None:
        if args.book < 0 or args.book >= books.num_books:
            print(
                f"ERROR: Book {args.book} out of range (0..{books.num_books - 1})",
                file=sys.stderr,
            )
            return 1
        print(books.get_text(args.book))
        return 0

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "book_dump.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"BOOK.DAT — {books.num_books} texts\n")
        f.write("=" * 60 + "\n\n")
        for i in range(books.num_books):
            f.write(f"--- {i} ---\n{books.get_text(i)}\n\n")
    print(f"Dumped {books.num_books} texts -> {out_path}")
    return 0


@meta(
    category="text",
    results=("files",),
    params={"output": "output-dir", "file": "install-file"},
)
def converse_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to a U6 conversation library file (CONVERSE.A or CONVERSE.B)"
        ),
    ],
    item: Annotated[
        Optional[int],
        typer.Option(
            "--item",
            help="Single item index to disassemble; default: every non-empty item",
        ),
    ] = None,
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
            "-o", "--output-dir", help="Output directory; omit to print to stdout"
        ),
    ] = None,
) -> None:
    """Disassemble one or all scripts from a CONVERSE.A/B library file."""
    raise SystemExit(
        cmd_converse_dump(
            SimpleNamespace(
                file=file,
                item=item,
                entry_size=entry_size,
                size_header=size_header,
                output=output,
            )
        )
    )


@meta(
    category="text",
    results=("files",),
    params={"output": "output-dir", "file": "install-file"},
    resources={"file": "look"},
)
def look_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to LOOK.LZD")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Dump LOOK.LZD's tile-number -> object-name table."""
    raise SystemExit(cmd_look_dump(SimpleNamespace(file=file, output=output)))


@meta(
    category="text",
    results=("files",),
    params={"output": "output-dir", "file": "install-file"},
    resources={"file": "books"},
)
def book_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to BOOK.DAT")],
    book: Annotated[
        Optional[int],
        typer.Option(
            "--book", help="Single book/sign index to print; default: dump every text"
        ),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Dump one or all book/sign texts from BOOK.DAT."""
    raise SystemExit(
        cmd_book_dump(SimpleNamespace(file=file, book=book, output=output))
    )
