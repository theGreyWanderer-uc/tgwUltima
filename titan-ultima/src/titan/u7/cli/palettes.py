"""``titan u7 palette-*`` — palette browsing, inspection and export commands."""

from __future__ import annotations

__all__ = ["palette_browse_cmd", "palette_export_cmd", "palette_info_cmd"]

import csv
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export palette(s) from PALETTES.FLX or a .pal file."""
    from titan.u7.palette import PaletteEncoding, U7Palette

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or "palettes"
    os.makedirs(outdir, exist_ok=True)

    slots = U7Palette.enumerate_slots(filepath)
    count = len(slots)
    encoding_value = getattr(args, "encoding", None) or "auto"
    encoding: PaletteEncoding
    if encoding_value == "auto":
        encoding = "auto"
    elif encoding_value == "6bit":
        encoding = "6bit"
    elif encoding_value == "8bit":
        encoding = "8bit"
    else:
        print(
            f"ERROR: Unknown encoding {encoding_value!r}; expected 'auto', '6bit', or '8bit'",
            file=sys.stderr,
        )
        return 1

    if args.index is not None:
        if args.index < 0 or args.index >= count:
            print(
                f"ERROR: Palette index {args.index} out of range "
                f"(file has {count} slots)",
                file=sys.stderr,
            )
            return 1
        indices = [args.index]
    else:
        for s in slots:
            if s.is_empty:
                print(f"  Skipping palette {s.index}: empty slot")
            elif not s.is_valid:
                print(f"  Skipping palette {s.index}: {s.error}")
        indices = [s.index for s in slots if not s.is_empty and s.is_valid]

    base = Path(filepath).stem
    exported = 0

    for idx in indices:
        try:
            pal = U7Palette.from_file(filepath, palette_index=idx, encoding=encoding)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        tag = f"{base}_pal{idx:02d}" if count > 1 else base

        img_path = os.path.join(outdir, f"{tag}_swatch.png")
        img = pal.to_pil_image(swatch_size=16)
        img.save(img_path)
        print(f"Swatch saved: {img_path}")

        txt_path = os.path.join(outdir, f"{tag}.txt")
        with open(txt_path, "w") as f:
            f.write(pal.to_text())
            f.write("\n")
        print(f"  Text saved: {txt_path}")
        exported += 1

    print(f"Exported {exported} palette(s) to {outdir}/")
    return 0


def _palette_inspection_rows(filepath: str) -> list[dict]:
    """One row per Flex slot: occupancy, validity, semantic name, and
    (for populated/valid slots) decoded encoding."""
    from titan.u7.palette import U7Palette
    from titan.u7.palette_semantics import palette_slot_name

    rows: list[dict] = []
    for slot in U7Palette.enumerate_slots(filepath):
        row = {
            "index": slot.index,
            "offset": slot.offset,
            "length": slot.length,
            "is_empty": slot.is_empty,
            "is_valid": slot.is_valid,
            "error": slot.error or "",
            "name": palette_slot_name(slot.index) or "",
            "encoding": "",
        }
        if not slot.is_empty and slot.is_valid:
            try:
                pal = U7Palette.from_file(filepath, palette_index=slot.index)
                row["encoding"] = pal.encoding
            except ValueError:
                pass
        rows.append(row)
    return rows


def _palette_info_text(filepath: str, rows: list[dict], detail: bool) -> str:
    from titan.u7.palette_semantics import CYCLE_RANGES

    lines = [
        f"{filepath}: {len(rows)} slot(s), {sum(1 for r in rows if not r['is_empty'])} populated"
    ]
    for row in rows:
        if not detail and row["is_empty"]:
            continue
        name = f" ({row['name']})" if row["name"] else ""
        enc = f" [{row['encoding']}]" if row["encoding"] else ""
        if row["is_empty"]:
            status = "empty"
        elif not row["is_valid"]:
            status = f"invalid: {row['error']}"
        else:
            status = "ok"
        prefix = (
            f"  slot {row['index']:2d}: offset=0x{row['offset']:06x} length={row['length']:4d} "
            if detail
            else f"  {row['index']:2d}: "
        )
        lines.append(f"{prefix}{status}{name}{enc}")

    if detail:
        lines.append("")
        lines.append(
            "Colour-cycling ranges (apply to every populated palette; see titan.u7.palette_cycle):"
        )
        for r in CYCLE_RANGES:
            lines.append(f"  {r.name:8s} {r.start:3d}-{r.end:3d}")

    return "\n".join(lines)


def cmd_palette_info(args: SimpleNamespace) -> int:
    """Inspect a PALETTES.FLX archive: slot occupancy, semantic names,
    encoding, and colour-cycling ranges."""
    from titan.u7.palette_semantics import CYCLE_RANGES

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    fmt = getattr(args, "format", None) or "summary"
    rows = _palette_inspection_rows(filepath)

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
        content = buf.getvalue()
    elif fmt == "json":
        content = json.dumps(
            {
                "slots": rows,
                "cycle_ranges": [
                    {"name": r.name, "start": r.start, "end": r.end}
                    for r in CYCLE_RANGES
                ],
            },
            indent=2,
        )
    else:
        content = _palette_info_text(filepath, rows, detail=(fmt == "detail"))

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"Palette info written to: {args.output}")
    else:
        print(content)

    return 0


def palette_browse_cmd(
    file: Annotated[
        Optional[str],
        typer.Argument(help="Initial PALETTES.FLX or standalone .pal file"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"], typer.Option("--game", help="Initial game flavour")
    ] = "bg",
    index: Annotated[
        int, typer.Option("--index", help="Initial palette record", min=0)
    ] = 0,
    encoding: Annotated[
        Literal["auto", "6bit", "8bit"],
        typer.Option("--encoding", help="Initial component encoding"),
    ] = "auto",
) -> None:
    """Browse game/mod palettes, indexed colours, cycling and gradient ramps."""
    from titan.u7.palette_browser_ui import run_browser

    raise SystemExit(run_browser(game=game, file=file, index=index, encoding=encoding))


def palette_export_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to PALETTES.FLX or a standalone .pal file")
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    index: Annotated[
        Optional[int],
        typer.Option("--index", help="Export only this palette index (default: all)"),
    ] = None,
    encoding: Annotated[
        Literal["auto", "6bit", "8bit"],
        typer.Option(
            "--encoding",
            help="Component encoding: auto-detect (default), or force 6-bit/8-bit",
        ),
    ] = "auto",
) -> None:
    """Export palettes from PALETTES.FLX as PNG colour swatches and text dumps."""
    raise SystemExit(
        cmd_palette_export(
            SimpleNamespace(
                file=file,
                output=output,
                index=index,
                encoding=encoding,
            )
        )
    )


def palette_info_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to PALETTES.FLX or a standalone .pal file")
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write info dump to this file"),
    ] = None,
    format: Annotated[
        Literal["summary", "detail", "csv", "json"],
        typer.Option(
            "-f",
            "--format",
            help="Output format: summary (default), detail, csv, json",
        ),
    ] = "summary",
) -> None:
    """Inspect a PALETTES.FLX archive: slot occupancy, semantic names,
    raw encoding, and colour-cycling ranges -- without exporting any files."""
    raise SystemExit(
        cmd_palette_info(
            SimpleNamespace(
                file=file,
                output=output,
                format=format,
            )
        )
    )
