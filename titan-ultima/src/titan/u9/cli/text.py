"""``titan u9 text-*`` / ``books-*`` — text archive, text key and book commands."""

from __future__ import annotations

__all__ = [
    "text_list_cmd",
    "text_blocks_cmd",
    "text_search_cmd",
    "text_export_cmd",
    "text_import_cmd",
    "text_keys_info_cmd",
    "text_key_lookup_cmd",
    "text_keys_export_cmd",
    "books_list_cmd",
    "books_show_cmd",
    "books_search_cmd",
    "books_export_cmd",
]

import csv
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.books import U9Books, U9BooksError
from titan.u9.flx_archive import U9FlxArchive
from titan.u9.npc import U9NpcError, U9Npcs
from titan.u9.text import U9TextArchive, U9TextError
from titan.u9.text_keys import (
    KEY_ENCODING,
    U9TextKeyTable,
    U9TextKeyTableError,
    key_bucket,
    key_crc,
    reconstruct_keys,
    text_reference_status,
)
from titan.u9.cli import _common


def _load_text(filepath: str) -> Optional[U9TextArchive]:
    """Open a UTF-16 text archive, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9TextArchive.from_file(filepath)
    except U9TextError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_text_list(args: SimpleNamespace) -> int:
    """Print strings from a text archive, optionally just one source block."""
    text = _load_text(args.file)
    if text is None:
        return 1

    try:
        if args.block:
            block = text.block_for(args.block)
            if block is None:
                print(f"No block named {args.block!r}. Try 'titan u9 text-blocks'.")
                return 1
            rows = list(block.lines)
            print(f"{args.file} -- block {block.name!r}, {len(rows)} line(s)")
        else:
            rows = [e for e in text.entries() if args.markers or not e.is_file_marker]
            print(
                f"{args.file} -- {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} "
                f"of {len(text)} used"
            )
    except U9TextError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    shown = rows[: args.limit] if args.limit else rows
    for e in shown:
        print(f"{e.index:>6}  {e.text}")
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_text_blocks(args: SimpleNamespace) -> int:
    """List the source-file blocks in text.flx and how many lines each holds."""
    text = _load_text(args.file)
    if text is None:
        return 1
    try:
        blocks = text.blocks()
    except U9TextError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not blocks:
        print(
            f"{args.file} -- no BEGIN FILE markers; this archive is a flat list "
            f"of {len(text)} strings"
        )
        return 0

    blocks.sort(key=lambda b: -len(b) if args.by_size else b.marker_index)
    shown = blocks[: args.limit] if args.limit else blocks
    total = sum(len(b) for b in blocks)
    print(f"{args.file} -- {len(blocks)} block(s), {total} line(s)")
    print(f"{'Marker':>7}  {'Lines':>6}  Name")
    print("-" * 46)
    for b in shown:
        print(f"{b.marker_index:>7}  {len(b):>6}  {b.name}")
    if args.limit and len(blocks) > args.limit:
        print(f"... ({len(blocks) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_text_search(args: SimpleNamespace) -> int:
    """Find strings containing a substring, with the block each belongs to."""
    text = _load_text(args.file)
    if text is None:
        return 1
    try:
        hits = text.search(args.needle, ignore_case=not args.case_sensitive)
        owner = {}
        for block in text.blocks():
            for line in block.lines:
                owner[line.index] = block.name
    except U9TextError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    shown = hits[: args.limit] if args.limit else hits
    print(f"{args.file} -- {len(hits)} match(es) for {args.needle!r}")
    for e in shown:
        where = owner.get(e.index)
        prefix = f"{e.index:>6}  {where:<18}" if where else f"{e.index:>6}  {'':<18}"
        print(f"{prefix}  {e.text}")
    if args.limit and len(hits) > args.limit:
        print(f"... ({len(hits) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_text_export(args: SimpleNamespace) -> int:
    """Export a text archive to CSV: index, block, marker flag, text."""
    text = _load_text(args.file)
    if text is None:
        return 1
    try:
        entries = text.entries()
        owner = {}
        for block in text.blocks():
            for line in block.lines:
                owner[line.index] = block.name
    except U9TextError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out_path = args.output or f"{Path(args.file).stem}_text.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "block", "is_file_marker", "text"])
        for e in entries:
            writer.writerow(
                [e.index, owner.get(e.index, ""), int(e.is_file_marker), e.text]
            )
    print(f"{args.file} -- wrote {len(entries)} row(s) -> {out_path}")
    return 0


def cmd_text_import(args: SimpleNamespace) -> int:
    """Rebuild a text archive from an edited ``text-export`` CSV."""
    text = _load_text(args.file)
    if text is None:
        return 1
    rows = _common._read_import_csv(args.csv, "index", "text")
    if rows is None:
        return 1
    try:
        changes = {
            index: value
            for index, value in rows.items()
            if (entry := text.entry(index)) is None or entry.text != value
        }
        data = text.rebuilt(changes)
    except U9TextError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    rebuilt = U9TextArchive(U9FlxArchive(data))
    for index, value in changes.items():
        entry = rebuilt.entry(index)
        if entry is None or entry.text != value:
            print(f"ERROR: entry {index} did not read back as written", file=sys.stderr)
            return 1
    wide = sorted({ch for value in changes.values() for ch in value if ord(ch) > 0xFF})

    source = Path(args.file)
    out_path = args.output or str(
        source.with_name(f"{source.stem}_imported{source.suffix}")
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    print(
        f"{args.file} -- {len(rows)} row(s) read, {len(changes)} entr"
        f"{'y' if len(changes) == 1 else 'ies'} changed"
    )
    print(
        f"  Written : {out_path} ({len(data)} bytes, slot count {rebuilt.num_entries})"
    )
    if wide:
        print(
            f"  Warning : {len(wide)} character(s) beyond Latin-1 "
            f"({''.join(wide[:20])}); the game's fonts may not draw them"
        )
    return 0


def _load_text_key_table(filepath: str) -> Optional[U9TextKeyTable]:
    """Open static/text.dat, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9TextKeyTable.from_file(filepath)
    except U9TextKeyTableError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def _load_optional_text(
    filepath: Optional[str],
) -> tuple[bool, Optional[U9TextArchive]]:
    """Open an optional text.flx; the flag is False when one was given but failed."""
    if filepath is None:
        return True, None
    text = _load_text(filepath)
    return text is not None, text


def _load_optional_npc_names(
    filepath: Optional[str],
) -> tuple[bool, Optional[list[str]]]:
    """Read speaker names from an optional NPC.FLX; False when one failed."""
    if filepath is None:
        return True, None
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return False, None
    try:
        return True, [npc.name for npc in U9Npcs.from_file(filepath) if npc.name]
    except U9NpcError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return False, None


def _counts_line(counts: Counter) -> str:
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def cmd_text_keys_info(args: SimpleNamespace) -> int:
    """Summarize the text key table and, optionally, its joins to text.flx."""
    table = _load_text_key_table(args.file)
    if table is None:
        return 1
    ok, text = _load_optional_text(args.text)
    if not ok:
        return 1
    ok, npc_names = _load_optional_npc_names(args.npcs)
    if not ok:
        return 1

    items = table.items
    chains = Counter(len(bucket.items) for bucket in table.buckets)
    print(f"{args.file} -- {table.bucket_count} bucket(s), {len(items)} item(s)")
    print(f"  empty buckets     : {chains.get(0, 0)}")
    print(f"  longest chain     : {max(chains, default=0)}")
    print(f"  trailing bytes    : {len(table.trailing_data)}")
    print(
        f"  reachability      : {_counts_line(Counter(map(table.reachability, items)))}"
    )
    if text is None:
        return 0
    try:
        statuses = Counter(text_reference_status(item, text) for item in items)
        targets = table.text_index_counts()
        unkeyed = [index for index in text.used_indices() if index not in targets]
        keys = reconstruct_keys(table, text, args.speakers or (), npc_names)
    except U9TextError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"  text references   : {_counts_line(statuses)}")
    print(f"  shared targets    : {sum(1 for count in targets.values() if count > 1)}")
    print(f"  lines without key : {len(unkeyed)}")
    methods = Counter(key.method for key in keys.values())
    methods["unresolved"] = len(items) - len(keys)
    print(f"  reconstructed keys: {_counts_line(methods)}")
    return 0


def cmd_text_key_lookup(args: SimpleNamespace) -> int:
    """Look up one key the way the game does and show the selected line."""
    table = _load_text_key_table(args.file)
    if table is None:
        return 1
    ok, text = _load_optional_text(args.text)
    if not ok:
        return 1
    if table.bucket_count <= 0:
        print(f"{args.file} -- the table has no buckets, so no key can be found")
        return 1
    try:
        key = args.key.encode(KEY_ENCODING)
        bucket = key_bucket(key, table.bucket_count)
        crc = key_crc(key)
    except (UnicodeEncodeError, ValueError) as error:
        print(f"ERROR: cannot use this key: {error}", file=sys.stderr)
        return 1

    print(f"{args.file} -- key {args.key!r}")
    print(f"  bucket {bucket}  crc 0x{crc:08x}")
    item = table.lookup_bytes(key)
    if item is None:
        print("  not found")
        return 1
    print(
        f"  item {item.bucket}:{item.position} at 0x{item.offset:x} "
        f"-> text index {item.text_index}"
    )
    if text is not None:
        status = text_reference_status(item, text)
        entry = text.entry(item.text_index) if status == "valid" else None
        print(f"  text: {entry.text if entry else f'({status})'}")
    return 0


TEXT_KEY_CSV_COLUMNS = (
    "bucket",
    "position",
    "offset",
    "stored_hash",
    "stored_crc_hex",
    "text_index",
    "reachability",
    "text_reference_status",
    "items_sharing_text_index",
    "key_status",
    "key_method",
    "speaker",
    "key",
    "text",
)


def cmd_text_keys_export(args: SimpleNamespace) -> int:
    """Export every stored item, with its text join and verified key, to CSV."""
    table = _load_text_key_table(args.file)
    if table is None:
        return 1
    ok, text = _load_optional_text(args.text)
    if not ok:
        return 1
    ok, npc_names = _load_optional_npc_names(args.npcs)
    if not ok:
        return 1
    try:
        keys = (
            reconstruct_keys(table, text, args.speakers or (), npc_names)
            if text
            else {}
        )
    except U9TextError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    targets = table.text_index_counts()
    out_path = args.output or f"{Path(args.file).stem}_keys.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(TEXT_KEY_CSV_COLUMNS)
        for item in table.items:
            status = text_reference_status(item, text) if text else "not_checked"
            entry = text.entry(item.text_index) if status == "valid" else None
            key = keys.get((item.bucket, item.position))
            if text is None:
                key_status = "not_checked"
            else:
                key_status = "verified" if key else "unresolved"
            writer.writerow(
                [
                    item.bucket,
                    item.position,
                    item.offset,
                    item.stored_hash,
                    f"0x{item.stored_crc:08x}",
                    item.text_index,
                    table.reachability(item),
                    status,
                    targets[item.text_index],
                    key_status,
                    key.method if key else "",
                    (key.speaker or "") if key else "",
                    key.text if key else "",
                    entry.text if entry else "",
                ]
            )
    print(f"{args.file} -- wrote {len(table.items)} row(s) -> {out_path}")
    if text is not None:
        print(
            f"  verified keys: {len(keys)}, unresolved: {len(table.items) - len(keys)}"
        )
    return 0


def _load_books(filepath: str) -> Optional[U9Books]:
    """Open a BOOKS-*.FLX archive, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Books.from_file(filepath)
    except U9BooksError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_books_list(args: SimpleNamespace) -> int:
    """List the books, scrolls and signs in the archive."""
    books = _load_books(args.file)
    if books is None:
        return 1
    try:
        rows = books.books()
    except U9BooksError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.by_size:
        rows.sort(key=lambda b: -len(b))
    shown = rows[: args.limit] if args.limit else rows

    print(
        f"{args.file} -- {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} "
        f"of {books.num_entries} slots"
    )
    print(f"{'Id':>5}  {'Bytes':>7}  {'Pages':>5}  Name")
    print("-" * 60)
    for book in shown:
        note = "  [embedded document]" if book.is_embedded_document else ""
        print(
            f"{book.book_id:>5}  {len(book):>7}  {len(book.pages):>5}  {book.name}{note}"
        )
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_books_show(args: SimpleNamespace) -> int:
    """Print one book's text, by id or by name."""
    books = _load_books(args.file)
    if books is None:
        return 1
    try:
        if args.name:
            book = books.by_name(args.name)
            if book is None:
                print(f"No book named {args.name!r}. Try 'titan u9 books-list'.")
                return 1
        else:
            book = books.book(args.id - 1)
            if book is None:
                print(f"Book id {args.id} is an unused slot.")
                return 1
    except U9BooksError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"{book.book_id}: {book.name}  ({len(book)} bytes)")
    if book.is_embedded_document:
        print("  This entry is an embedded document, not game text -- the shipped")
        print("  archive has a word processor file here in place of the prose.")
        return 0
    print("-" * 60)
    pages = book.pages
    for number, page in enumerate(pages, start=1):
        if len(pages) > 1:
            print(f"[page {number}/{len(pages)}]")
        print(page.replace("\r\n", "\n").rstrip())
    return 0


def cmd_books_search(args: SimpleNamespace) -> int:
    """Find books whose text or title contains a substring."""
    books = _load_books(args.file)
    if books is None:
        return 1
    try:
        hits = books.search(args.needle, ignore_case=not args.case_sensitive)
    except U9BooksError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    shown = hits[: args.limit] if args.limit else hits
    print(f"{args.file} -- {len(hits)} match(es) for {args.needle!r}")
    needle = args.needle if args.case_sensitive else args.needle.lower()
    for book in shown:
        text = book.text.replace("\r\n", " ")
        hay = text if args.case_sensitive else text.lower()
        at = hay.find(needle)
        if at < 0:
            snippet = book.name
        else:
            start = max(0, at - 30)
            snippet = ("..." if start else "") + text[
                start : at + len(needle) + 40
            ].strip()
        print(f"{book.book_id:>5}  {book.name[:28]:<28}  {snippet}")
    if args.limit and len(hits) > args.limit:
        print(f"... ({len(hits) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_books_export(args: SimpleNamespace) -> int:
    """Export the archive to CSV: id, name, pages, fonts and text."""
    books = _load_books(args.file)
    if books is None:
        return 1
    try:
        rows = books.books()
    except U9BooksError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out_path = args.output or f"{Path(args.file).stem}_books.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "index",
                "name",
                "bytes",
                "pages",
                "fonts",
                "is_embedded_document",
                "text",
            ]
        )
        for book in rows:
            writer.writerow(
                [
                    book.book_id,
                    book.index,
                    book.name,
                    len(book),
                    len(book.pages),
                    " ".join(str(v) for v in book.fonts),
                    int(book.is_embedded_document),
                    "" if book.is_embedded_document else book.text,
                ]
            )
    print(f"{args.file} -- wrote {len(rows)} row(s) -> {out_path}")
    return 0


def text_list_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/text.flx or static/misctext.flx")
    ],
    block: Annotated[
        Optional[str],
        typer.Option(
            "-b", "--block", help="Only one source block, by name (e.g. Raven)"
        ),
    ] = None,
    markers: Annotated[
        bool, typer.Option("-m", "--markers", help="Include BEGIN FILE markers")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum lines to print")
    ] = None,
) -> None:
    """Print strings from a U9 text archive."""
    raise SystemExit(
        cmd_text_list(
            SimpleNamespace(file=file, block=block, markers=markers, limit=limit)
        )
    )


def text_blocks_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.flx")],
    by_size: Annotated[
        bool, typer.Option("-s", "--by-size", help="Order by line count, largest first")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum blocks to print")
    ] = None,
) -> None:
    """List the source-file blocks in a U9 text archive."""
    raise SystemExit(
        cmd_text_blocks(SimpleNamespace(file=file, by_size=by_size, limit=limit))
    )


def text_search_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/text.flx or static/misctext.flx")
    ],
    needle: Annotated[str, typer.Argument(help="Substring to look for")],
    case_sensitive: Annotated[
        bool, typer.Option("-c", "--case-sensitive", help="Match case exactly")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum matches to print")
    ] = None,
) -> None:
    """Search a U9 text archive, showing which block each match belongs to."""
    raise SystemExit(
        cmd_text_search(
            SimpleNamespace(
                file=file, needle=needle, case_sensitive=case_sensitive, limit=limit
            )
        )
    )


def text_export_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/text.flx or static/misctext.flx")
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output CSV path (default: <file>_text.csv)"
        ),
    ] = None,
) -> None:
    """Export a U9 text archive to CSV."""
    raise SystemExit(cmd_text_export(SimpleNamespace(file=file, output=output)))


def text_import_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Original text archive (text.flx, misctext.flx, Tbrk.*, Mbrk.*)"
        ),
    ],
    csv_path: Annotated[
        str, typer.Argument(metavar="CSV", help="Edited text-export CSV (index, text)")
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output archive (default: <stem>_imported<ext>)"
        ),
    ] = None,
) -> None:
    """Rebuild a U9 text archive with the texts from an edited CSV."""
    raise SystemExit(
        cmd_text_import(SimpleNamespace(file=file, csv=csv_path, output=output))
    )


def text_keys_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.dat")],
    text: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--text",
            help="Path to static/text.flx, to check targets and recover keys",
        ),
    ] = None,
    speakers: Annotated[
        Optional[list[str]],
        typer.Option(
            "-s",
            "--speaker",
            help="Extra speaker name to try when recovering keys (repeatable)",
        ),
    ] = None,
    npcs: Annotated[
        Optional[str],
        typer.Option(
            "--npcs",
            help="Path to runtime/NPC.FLX; its record names are the speakers the game uses",
        ),
    ] = None,
) -> None:
    """Summarize the U9 text key table and its links to text.flx."""
    raise SystemExit(
        cmd_text_keys_info(
            SimpleNamespace(file=file, text=text, speakers=speakers, npcs=npcs)
        )
    )


def text_key_lookup_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.dat")],
    key: Annotated[str, typer.Argument(help="Full key, e.g. 'Avatar : Farewell.'")],
    text: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--text",
            help="Path to static/text.flx, to check targets and recover keys",
        ),
    ] = None,
) -> None:
    """Look up one text key the way the game does."""
    raise SystemExit(
        cmd_text_key_lookup(SimpleNamespace(file=file, key=key, text=text))
    )


def text_keys_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.dat")],
    text: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--text",
            help="Path to static/text.flx, to check targets and recover keys",
        ),
    ] = None,
    speakers: Annotated[
        Optional[list[str]],
        typer.Option(
            "-s",
            "--speaker",
            help="Extra speaker name to try when recovering keys (repeatable)",
        ),
    ] = None,
    npcs: Annotated[
        Optional[str],
        typer.Option(
            "--npcs",
            help="Path to runtime/NPC.FLX; its record names are the speakers the game uses",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output CSV path (default: <file>_keys.csv)"
        ),
    ] = None,
) -> None:
    """Export every U9 text key item, its target line and recovered key, to CSV."""
    raise SystemExit(
        cmd_text_keys_export(
            SimpleNamespace(
                file=file, text=text, speakers=speakers, npcs=npcs, output=output
            )
        )
    )


def books_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    by_size: Annotated[
        bool, typer.Option("-s", "--by-size", help="Order by body size, largest first")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List the books, scrolls and signs in a U9 book archive."""
    raise SystemExit(
        cmd_books_list(SimpleNamespace(file=file, by_size=by_size, limit=limit))
    )


def books_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    id: Annotated[
        int, typer.Option("-i", "--id", help="Book id, as shown by books-list")
    ] = 1,
    name: Annotated[
        Optional[str],
        typer.Option("-b", "--name", help="Look the book up by name instead"),
    ] = None,
) -> None:
    """Print one U9 book's text."""
    raise SystemExit(cmd_books_show(SimpleNamespace(file=file, id=id, name=name)))


def books_search_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    needle: Annotated[str, typer.Argument(help="Substring to look for")],
    case_sensitive: Annotated[
        bool, typer.Option("-c", "--case-sensitive", help="Match case exactly")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum matches to print")
    ] = None,
) -> None:
    """Search a U9 book archive, showing the matching passage."""
    raise SystemExit(
        cmd_books_search(
            SimpleNamespace(
                file=file, needle=needle, case_sensitive=case_sensitive, limit=limit
            )
        )
    )


def books_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output CSV path"),
    ] = None,
) -> None:
    """Export a U9 book archive to CSV."""
    raise SystemExit(cmd_books_export(SimpleNamespace(file=file, output=output)))
