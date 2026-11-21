"""``titan u6`` tile, palette, tile-flag and font export commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._config import export_output
from titan._meta import meta
from titan.u6.cli._common import (
    _require_gamedir,
    _resolve_palette,
)
from titan.u6.font import U6Fonts
from titan.u6.palette import U6Palette
from titan.u6.tile import U6Tiles
from titan.u6.tileflag import U6TileFlags


def _parse_tile_num(value: str) -> int:
    return int(value, 16) if value.lower().startswith("0x") else int(value)


def cmd_tileflag_dump(args: SimpleNamespace) -> int:
    """Parse TILEFLAG and dump all entries as a readable table."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    entries = U6TileFlags.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "tileflag_dump.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"TILEFLAG — {len(entries)} entries\n")
        f.write("=" * 100 + "\n\n")
        header = (
            f"{'Tile':>5}  {'Terrain':>7}  {'Flags':>5}  {'Weight':>6}  {'Extra':>5}  "
            f"{'Article':<7} {'Notes'}\n"
        )
        f.write(header)
        f.write("-" * 100 + "\n")
        for e in entries:
            if e.terrain == 0 and e.flags == 0 and e.weight == 0 and e.extra == 0:
                continue
            notes = []
            if e.is_wet:
                notes.append("wet")
            if e.is_impassable:
                notes.append("impassable")
            if e.is_wall:
                notes.append("wall")
            if e.is_damaging:
                notes.append("damaging")
            if e.is_double:
                notes.append("double")
            if e.is_supporting:
                notes.append("supporting")
            if e.is_breakthrough:
                notes.append("breakthrough")
            f.write(
                f"{e.tile_num:>5}  0x{e.terrain:04X}  0x{e.flags:03X}  {e.weight:>6}  "
                f"0x{e.extra:03X}  {e.article_word or '-':<7} {','.join(notes)}\n"
            )

    print(f"Dumped {len(entries)} entries -> {out_path}")
    return 0


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export U6PAL as a PNG swatch image + text dump."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    pal = U6Palette.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    base = Path(filepath).name

    img_path = os.path.join(outdir, f"{base}_palette.png")
    pal.to_pil_image(swatch_size=16).save(img_path)
    print(f"Palette swatch saved: {img_path}  (256 colors, 16x16 grid)")

    txt_path = os.path.join(outdir, f"{base}_palette.txt")
    with open(txt_path, "w") as f:
        f.write(f"# Palette from {filepath}\n")
        f.write("# Index  R    G    B    Hex\n")
        for i, (r, g, b) in enumerate(pal.colors):
            f.write(f"{i:3d}    {r:3d}  {g:3d}  {b:3d}  #{r:02X}{g:02X}{b:02X}\n")
    print(f"Palette text dump: {txt_path}")
    return 0


def cmd_tile_export(args: SimpleNamespace) -> int:
    """Export one U6 tile to PNG."""
    gamedir = _require_gamedir(args.gamedir)
    palette_path = _resolve_palette(gamedir, args.palette)

    tiles = U6Tiles.from_directory(gamedir)
    pal = U6Palette.from_file(palette_path)

    tile_num = args.tile_num
    if tile_num < 0 or tile_num >= tiles.num_tiles:
        print(
            f"ERROR: Tile {tile_num} out of range (0..{tiles.num_tiles - 1})",
            file=sys.stderr,
        )
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"tile_{tile_num:04d}.png")
    tiles.to_pil_image(tile_num, pal, transparent=True).save(out_path)
    print(f"Exported tile {tile_num} -> {out_path}")
    return 0


def cmd_tile_export_all(args: SimpleNamespace) -> int:
    """Batch-export a range of U6 tiles to PNG."""
    gamedir = _require_gamedir(args.gamedir)
    palette_path = _resolve_palette(gamedir, args.palette)

    tiles = U6Tiles.from_directory(gamedir)
    pal = U6Palette.from_file(palette_path)

    start = args.start
    end = args.end if args.end is not None else tiles.num_tiles - 1
    if start < 0 or end >= tiles.num_tiles or start > end:
        print(
            f"ERROR: Invalid range {start}..{end} (valid: 0..{tiles.num_tiles - 1})",
            file=sys.stderr,
        )
        return 1

    outdir = export_output(args.output, "u6", "tile-export-all")
    os.makedirs(outdir, exist_ok=True)
    exported = 0
    for i in range(start, end + 1):
        tiles.to_pil_image(i, pal, transparent=True).save(
            os.path.join(outdir, f"tile_{i:04d}.png")
        )
        exported += 1

    print(f"Exported {exported} tiles ({start}..{end}) -> {outdir}/")
    return 0


def cmd_font_export(args: SimpleNamespace) -> int:
    """Export the English and runic/gargoyle fonts from U6.CH."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    fonts = U6Fonts.from_file(filepath)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    english_path = os.path.join(outdir, "font_english.png")
    runic_path = os.path.join(outdir, "font_runic_gargoyle.png")
    fonts.english.to_contact_sheet(scale=args.scale).save(english_path)
    fonts.runic.to_contact_sheet(scale=args.scale).save(runic_path)
    print(f"Exported: {english_path}")
    print(f"Exported: {runic_path}")

    if args.text:
        eng_path = os.path.join(outdir, "text_english.png")
        run_path = os.path.join(outdir, "text_runic_gargoyle.png")
        fonts.english.render_text(args.text, bg=(0, 0, 0), scale=args.scale).save(
            eng_path
        )
        fonts.runic.render_text(args.text, bg=(0, 0, 0), scale=args.scale).save(
            run_path
        )
        print(f"Exported: {eng_path}")
        print(f"Exported: {run_path}")
    return 0


@meta(
    results=("files",),
    params={"output": "output-dir", "file": "install-file"},
    resources={"file": "tileflag"},
)
def tileflag_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to TILEFLAG")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Parse TILEFLAG and dump all entries as a readable table."""
    raise SystemExit(cmd_tileflag_dump(SimpleNamespace(file=file, output=output)))


@meta(
    results=("files",),
    params={"output": "output-dir", "file": "palette"},
    resources={"file": "palette"},
)
def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to U6PAL")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Export U6PAL as a PNG swatch + text dump."""
    raise SystemExit(cmd_palette_export(SimpleNamespace(file=file, output=output)))


@meta(results=("files",), params={"output": "output-dir", "palette": "palette"})
def tile_export_cmd(
    tile_num: Annotated[
        str, typer.Argument(help="Tile number, decimal or 0x-hex (0-0x7FF)")
    ],
    gamedir: Annotated[
        Optional[str],
        typer.Option("-g", "--game-dir", help="U6 game directory"),
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("-p", "--palette", help="Path to U6PAL")
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Export one U6 tile to PNG."""
    raise SystemExit(
        cmd_tile_export(
            SimpleNamespace(
                tile_num=_parse_tile_num(tile_num),
                gamedir=gamedir,
                palette=palette,
                output=output,
            )
        )
    )


@meta(results=("files",), params={"output": "output-dir", "palette": "palette"})
def tile_export_all_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("-p", "--palette", help="Path to U6PAL")
    ] = None,
    start: Annotated[
        int, typer.Option("--start", help="First tile number (inclusive)")
    ] = 0,
    end: Annotated[
        Optional[int],
        typer.Option("--end", help="Last tile number (inclusive); default: last tile"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output-dir", help="Output directory (default: tiles_png/)"
        ),
    ] = None,
) -> None:
    """Batch-export a range of U6 tiles to PNG."""
    raise SystemExit(
        cmd_tile_export_all(
            SimpleNamespace(
                gamedir=gamedir,
                palette=palette,
                start=start,
                end=end,
                output=output,
            )
        )
    )


@meta(
    results=("files",),
    params={"output": "output-dir", "file": "install-file"},
    resources={"file": "font"},
)
def font_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to U6.CH")],
    text: Annotated[
        Optional[str],
        typer.Option(
            "--text", help="Also render this text in both fonts, for comparison"
        ),
    ] = None,
    scale: Annotated[
        int, typer.Option("--scale", help="Pixel scale factor for the exported images")
    ] = 3,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
) -> None:
    """Export the English and runic/gargoyle fonts from U6.CH as contact sheets."""
    raise SystemExit(
        cmd_font_export(
            SimpleNamespace(file=file, text=text, scale=scale, output=output)
        )
    )
