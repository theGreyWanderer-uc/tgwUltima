"""``titan u8 palette-export`` / ``xformpal-export`` — palette commands."""

from __future__ import annotations

__all__ = ["palette_export_cmd", "xformpal_export_cmd"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer
from PIL import Image, ImageDraw

from titan.flex import FlexArchive
from titan.u8.palette import U8Palette
from titan.u8.xformpal import U8_XFORM_PALETTE as _U8_XFORM_PAL


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export a U8 palette as a PNG swatch image."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    pal = U8Palette.from_file(filepath)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}_palette.png")
    img = pal.to_pil_image(swatch_size=16)
    img.save(out_path)
    print(f"Palette swatch saved: {out_path}  (256 colors, 16x16 grid)")

    txt_path = os.path.join(outdir, f"{base}_palette.txt")
    with open(txt_path, "w") as f:
        f.write(f"# Palette from {filepath}\n")
        f.write("# Index  R    G    B    Hex\n")
        for i, (r, g, b) in enumerate(pal.colors):
            f.write(f"{i:3d}    {r:3d}  {g:3d}  {b:3d}  #{r:02X}{g:02X}{b:02X}\n")
    print(f"Palette text dump: {txt_path}")
    return 0


def cmd_xformpal_export(args: SimpleNamespace) -> int:
    """Export the U8 transform palette as a labelled PNG swatch + text dump."""
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    cell = 48
    img = Image.new("RGBA", (16 * cell, cell + 20), (32, 32, 32, 255))
    draw = ImageDraw.Draw(img)
    for i, (r, g, b, a) in enumerate(_U8_XFORM_PAL):
        x0 = i * cell
        if a > 0:
            draw.rectangle([x0, 0, x0 + cell - 1, cell - 1], fill=(r, g, b, 255))
        else:
            draw.rectangle([x0, 0, x0 + cell - 1, cell - 1], fill=(0, 0, 0, 255))
        draw.text((x0 + 2, cell + 2), str(i), fill=(200, 200, 200, 255))

    img_path = os.path.join(outdir, "xformpal_swatch.png")
    img.save(img_path)

    txt_path = os.path.join(outdir, "xformpal.txt")
    descriptions = {
        8: "green -> dark grey (standard ghost/translucent)",
        9: "black -> very dark grey (shadow)",
        10: "yellow tint (poison/acid)",
        11: "white -> grey (frost/ethereal)",
        12: "red -> orange (fire/damage)",
        13: "blue glow (magic/mana)",
        14: "dark blue glow (deep water)",
    }
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("U8 Transform Palette (from graphics/XFormBlend.cpp)\n")
        f.write("=" * 55 + "\n")
        f.write("Used for translucent shape rendering (SI_TRANSL flag).\n")
        f.write("Blend: dest*(255-A)/255 + RGB\n\n")
        f.write(f"{'Idx':<5}{'R':>4}{'G':>4}{'B':>4}{'A':>4}  Description\n")
        f.write("-" * 55 + "\n")
        for i, (r, g, b, a) in enumerate(_U8_XFORM_PAL):
            desc = descriptions.get(i, "unused" if a == 0 else "")
            f.write(f"{i:<5}{r:>4}{g:>4}{b:>4}{a:>4}  {desc}\n")

    print(f"Exported: {img_path}")
    print(f"Exported: {txt_path}")

    filepath = getattr(args, "file", None)
    if filepath and os.path.isfile(filepath):
        try:
            flex = FlexArchive.from_file(filepath)
            print(f"\nXFORMPAL.DAT is a Flex archive with {len(flex.records)} entries:")
            for i, rec in enumerate(flex.records):
                print(f"  Entry {i}: {len(rec)} bytes")
            if len(flex.records) >= 2 and len(flex.records[1]) == 32:
                print("\nEntry 1 (32 bytes) — 8 RGBA xform blend colours:")
                rec = flex.records[1]
                for j in range(8):
                    r = rec[j * 4]
                    g = rec[j * 4 + 1]
                    b = rec[j * 4 + 2]
                    a = rec[j * 4 + 3]
                    print(f"  [{j + 8}] R={r:3d} G={g:3d} B={b:3d} A={a:3d}")
        except Exception as e:
            print(f"  (Could not parse {filepath} as Flex: {e})")

    return 0


def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .pal file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Export a U8 palette (.pal) as PNG swatch + text dump."""
    raise SystemExit(cmd_palette_export(SimpleNamespace(file=file, output=output)))


def xformpal_export_cmd(
    file: Annotated[
        Optional[str],
        typer.Argument(help="Path to XFORMPAL.DAT (optional)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Export U8 transform palette as PNG swatch + text dump."""
    raise SystemExit(cmd_xformpal_export(SimpleNamespace(file=file, output=output)))
