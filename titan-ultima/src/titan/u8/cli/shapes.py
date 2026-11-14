"""``titan u8 shape-*`` — shape export, import and U7 conversion commands."""

from __future__ import annotations

__all__ = [
    "shape_export_cmd",
    "shape_batch_cmd",
    "shape_import_cmd",
    "shape_convert_u7_cmd",
    "shape_convert_u7_all_cmd",
]

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer
from PIL import Image

from titan.flex import FlexArchive
from titan.u8.palette import U8Palette
from titan.u8.shape import U8Shape
from titan.u8.shape_names import (
    u8_shape_export_stem as _u8_shape_stem,
    u8_shape_stem_from_path as _u8_shape_stem_from_path,
)
from titan.u8.typeflag import U8TypeFlags
from titan.u8.u7_shape_convert import build_footprint_size_table, convert_shape
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette
from titan.u7.typeflag import U7TypeFlags


def cmd_shape_export(args: SimpleNamespace) -> int:
    """Export frames from a single Shape file to PNG images."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    if args.palette and os.path.isfile(args.palette):
        pal = U8Palette.from_file(args.palette)
    else:
        print(
            "WARNING: No palette specified, using greyscale fallback", file=sys.stderr
        )
        pal = U8Palette.default_palette()

    shape = U8Shape.from_file(filepath)
    if not shape.frames:
        print(f"ERROR: No frames found in {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    base = _u8_shape_stem_from_path(filepath)
    images = shape.to_pngs(pal, transparent=True)

    saved = 0
    for i, img in enumerate(images):
        if img.width <= 1 and img.height <= 1:
            continue
        out_path = os.path.join(outdir, f"{base}_f{i:04d}.png")
        img.save(out_path)
        saved += 1

        outdir_display = outdir.rstrip("/\\") + "/"
        print(
            f"Exported {saved} frames from {os.path.basename(filepath)} "
            f"({len(shape.frames)} total) -> {outdir_display}"
        )
    return 0


def cmd_shape_batch(args: SimpleNamespace) -> int:
    """Batch-export all U8 shapes from a directory of .shp files or U8SHAPES.FLX."""
    srcpath = args.directory
    if not os.path.isdir(srcpath) and not os.path.isfile(srcpath):
        print(f"ERROR: Path not found: {srcpath}", file=sys.stderr)
        return 1

    if args.palette and os.path.isfile(args.palette):
        pal = U8Palette.from_file(args.palette)
    else:
        print(
            "WARNING: No palette specified, using greyscale fallback", file=sys.stderr
        )
        pal = U8Palette.default_palette()

    if os.path.isdir(srcpath):
        outdir = args.output or os.path.join(srcpath, "png")
    else:
        outdir = args.output or f"{Path(srcpath).stem}_png"
    os.makedirs(outdir, exist_ok=True)

    total_frames = 0
    total_shapes = 0
    skipped_empty = 0
    outdir_display = outdir.rstrip("/\\") + "/"

    if os.path.isfile(srcpath):
        archive = FlexArchive.from_file(srcpath)
        for shape_num, record in enumerate(archive.records):
            if not record:
                skipped_empty += 1
                continue
            try:
                shape = U8Shape.from_data(record)
                if not shape.frames:
                    skipped_empty += 1
                    continue

                base = _u8_shape_stem(shape_num)
                images = shape.to_pngs(pal, transparent=True)
                saved = 0
                for i, img in enumerate(images):
                    if img.width <= 1 and img.height <= 1:
                        continue
                    out_path = os.path.join(outdir, f"{base}_f{i:04d}.png")
                    img.save(out_path)
                    saved += 1

                if saved > 0:
                    total_shapes += 1
                    total_frames += saved
            except Exception as e:
                print(f"  WARNING: Failed shape {shape_num:04d}: {e}", file=sys.stderr)

        print(
            f"Batch export complete: {total_frames} frames from "
            f"{total_shapes} shapes -> {outdir_display}"
        )
        if skipped_empty:
            print(f"  ({skipped_empty} empty/no-frame shape slot(s) skipped)")
        return 0

    shp_files = sorted(f for f in os.listdir(srcpath) if f.lower().endswith(".shp"))
    if not shp_files:
        print(f"No .shp files found in {srcpath}")
        return 0

    for shp_file in shp_files:
        shp_path = os.path.join(srcpath, shp_file)
        try:
            shape = U8Shape.from_file(shp_path)
            if not shape.frames:
                continue

            base = _u8_shape_stem_from_path(shp_file)
            images = shape.to_pngs(pal, transparent=True)
            saved = 0
            for i, img in enumerate(images):
                if img.width <= 1 and img.height <= 1:
                    continue
                out_path = os.path.join(outdir, f"{base}_f{i:04d}.png")
                img.save(out_path)
                saved += 1

            if saved > 0:
                total_shapes += 1
                total_frames += saved
        except Exception as e:
            print(f"  WARNING: Failed {shp_file}: {e}", file=sys.stderr)

    print(
        f"Batch export complete: {total_frames} frames from "
        f"{total_shapes} shapes -> {outdir_display}"
    )
    return 0


def cmd_shape_import(args: SimpleNamespace) -> int:
    """Import PNG frames back into a U8 shape file."""
    png_dir = args.directory
    original_path = args.original
    output_path = args.output

    if not os.path.isdir(png_dir):
        print(f"ERROR: Directory not found: {png_dir}", file=sys.stderr)
        return 1
    if not os.path.isfile(original_path):
        print(f"ERROR: Original shape not found: {original_path}", file=sys.stderr)
        return 1

    if args.palette and os.path.isfile(args.palette):
        pal = U8Palette.from_file(args.palette)
    else:
        print(
            "WARNING: No palette specified, using greyscale fallback", file=sys.stderr
        )
        pal = U8Palette.default_palette()

    original = U8Shape.from_file(original_path)
    if not original.frames:
        print(f"ERROR: Original shape has no frames: {original_path}", file=sys.stderr)
        return 1

    png_map: dict[int, str] = {}
    pattern = re.compile(r"_f(\d+)\.png$", re.IGNORECASE)
    for fname in sorted(os.listdir(png_dir)):
        m = pattern.search(fname)
        if m:
            idx = int(m.group(1))
            png_map[idx] = os.path.join(png_dir, fname)

    if not png_map:
        print(
            f"ERROR: No matching *_fNNNN.png files found in {png_dir}", file=sys.stderr
        )
        return 1

    new_shape = U8Shape()
    new_shape.header0 = original.header0
    new_shape.header1 = original.header1

    replaced = 0
    kept = 0

    for i, orig_frame in enumerate(original.frames):
        frame = U8Shape.Frame()
        frame.xoff = orig_frame.xoff
        frame.yoff = orig_frame.yoff
        frame.compressed = orig_frame.compressed
        frame.frame_unknown = orig_frame.frame_unknown
        frame.table_unknown = orig_frame.table_unknown

        if i in png_map:
            try:
                img = Image.open(png_map[i]).convert("RGBA")
            except Exception as e:
                print(f"  WARNING: Cannot read {png_map[i]}: {e}", file=sys.stderr)
                frame.width = orig_frame.width
                frame.height = orig_frame.height
                frame.pixels = orig_frame.pixels
                new_shape.frames.append(frame)
                kept += 1
                continue

            frame.width = img.width
            frame.height = img.height
            frame.pixels = U8Shape.quantize_to_palette(img, pal)
            replaced += 1
        else:
            frame.width = orig_frame.width
            frame.height = orig_frame.height
            frame.pixels = orig_frame.pixels
            kept += 1

        new_shape.frames.append(frame)

    data = new_shape.to_bytes()

    if output_path is None:
        base = Path(original_path).stem
        output_path = os.path.join(png_dir, f"{base}_imported.shp")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(data)

    print(
        f"Shape imported: {replaced} frames replaced, {kept} kept from "
        f"original ({len(new_shape.frames)} total) -> {output_path}"
    )
    print(f"  Output size: {len(data):,} bytes")
    return 0


def cmd_shape_convert_u7(args: SimpleNamespace) -> int:
    """Convert one U8 shape into a U7/Exult-compatible shape (see titan.u8.u7_shape_convert)."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.typeflag):
        print(f"ERROR: TYPEFLAG.DAT not found: {args.typeflag}", file=sys.stderr)
        return 1
    if not os.path.isdir(args.u7_static):
        print(
            f"ERROR: U7 STATIC directory not found: {args.u7_static}", file=sys.stderr
        )
        return 1

    u7_shapes_path = os.path.join(args.u7_static, "SHAPES.VGA")
    if not os.path.isfile(u7_shapes_path):
        print(f"ERROR: SHAPES.VGA not found in {args.u7_static}", file=sys.stderr)
        return 1

    if args.u8_palette and os.path.isfile(args.u8_palette):
        u8_pal = U8Palette.from_file(args.u8_palette)
    else:
        print(
            "WARNING: No U8 palette specified, using greyscale fallback",
            file=sys.stderr,
        )
        u8_pal = U8Palette.default_palette()

    u7_pal_path = args.u7_palette or os.path.join(args.u7_static, "PALETTES.FLX")
    if not os.path.isfile(u7_pal_path):
        print(f"ERROR: U7 palette not found: {u7_pal_path}", file=sys.stderr)
        return 1
    u7_pal = U7Palette.from_file(u7_pal_path)

    u8_tfa = U8TypeFlags.from_file(args.typeflag)
    if args.shape_num < 0 or args.shape_num >= len(u8_tfa):
        print(
            f"ERROR: shape_num {args.shape_num} out of range (0..{len(u8_tfa) - 1})",
            file=sys.stderr,
        )
        return 1
    entry = u8_tfa[args.shape_num]
    footprint = (entry.x, entry.y, entry.z)

    u8_shape = U8Shape.from_file(args.file)
    if not u8_shape.frames:
        print(f"ERROR: No frames found in {args.file}", file=sys.stderr)
        return 1

    u7_shapes = U7FlexArchive.from_file(u7_shapes_path)
    u7_tfa = U7TypeFlags.from_dir(args.u7_static)
    size_table = build_footprint_size_table(u7_tfa, u7_shapes)

    u7_shape = convert_shape(u8_shape, footprint, u8_pal, u7_pal, size_table)
    if not u7_shape.frames:
        print(
            "ERROR: Conversion produced no frames (all-empty source shape?)",
            file=sys.stderr,
        )
        return 1

    output_path = args.output or (Path(args.file).stem + "_u7.shp")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    u7_shape.save(output_path)

    exact_hit = footprint in size_table
    print(
        f"Converted shape {args.shape_num} (footprint {footprint[0]}x{footprint[1]}x{footprint[2]}, "
        f"{'exact' if exact_hit else 'nearest'} calibration match): "
        f"{len(u7_shape.frames)} frame(s) -> {output_path}"
    )
    f0 = u7_shape.frames[0]
    print(f"  frame 0: {f0.width}x{f0.height}px, hotspot at bottom-right corner")
    return 0


def cmd_shape_convert_u7_all(args: SimpleNamespace) -> int:
    """Batch-convert every used U8 shape in U8SHAPES.FLX into U7/Exult-compatible shapes."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.typeflag):
        print(f"ERROR: TYPEFLAG.DAT not found: {args.typeflag}", file=sys.stderr)
        return 1
    if not os.path.isdir(args.u7_static):
        print(
            f"ERROR: U7 STATIC directory not found: {args.u7_static}", file=sys.stderr
        )
        return 1

    u7_shapes_path = os.path.join(args.u7_static, "SHAPES.VGA")
    if not os.path.isfile(u7_shapes_path):
        print(f"ERROR: SHAPES.VGA not found in {args.u7_static}", file=sys.stderr)
        return 1

    if args.u8_palette and os.path.isfile(args.u8_palette):
        u8_pal = U8Palette.from_file(args.u8_palette)
    else:
        print(
            "WARNING: No U8 palette specified, using greyscale fallback",
            file=sys.stderr,
        )
        u8_pal = U8Palette.default_palette()

    u7_pal_path = args.u7_palette or os.path.join(args.u7_static, "PALETTES.FLX")
    if not os.path.isfile(u7_pal_path):
        print(f"ERROR: U7 palette not found: {u7_pal_path}", file=sys.stderr)
        return 1
    u7_pal = U7Palette.from_file(u7_pal_path)

    print("Loading U8SHAPES.FLX and TYPEFLAG.DAT...")
    u8_shapes_flx = FlexArchive.from_file(args.file)
    u8_tfa = U8TypeFlags.from_file(args.typeflag)

    print("Building U7 footprint size calibration table (real SHAPES.VGA + TFA.DAT)...")
    u7_shapes = U7FlexArchive.from_file(u7_shapes_path)
    u7_tfa = U7TypeFlags.from_dir(args.u7_static)
    size_table = build_footprint_size_table(u7_tfa, u7_shapes)

    outdir = args.output or "u7_converted"
    os.makedirs(outdir, exist_ok=True)

    total = len(u8_shapes_flx.records)
    converted = 0
    total_frames = 0
    skipped_empty = 0
    skipped_no_output = 0

    for shape_num in range(total):
        if shape_num % 200 == 0:
            print(f"  ... {shape_num}/{total}", flush=True)

        data = u8_shapes_flx.get_record(shape_num)
        if not data:
            skipped_empty += 1
            continue

        u8_shape = U8Shape.from_data(data)
        if not u8_shape.frames:
            skipped_empty += 1
            continue

        entry = u8_tfa[shape_num] if shape_num < len(u8_tfa) else None
        footprint = (entry.x, entry.y, entry.z) if entry is not None else (1, 1, 0)

        u7_shape = convert_shape(u8_shape, footprint, u8_pal, u7_pal, size_table)
        if not u7_shape.frames:
            skipped_no_output += 1
            continue

        u7_shape.save(os.path.join(outdir, f"{shape_num:04d}.shp"))
        converted += 1
        total_frames += len(u7_shape.frames)

    print()
    print(f"total U8SHAPES.FLX slots: {total}")
    print(f"skipped (empty/no source frames): {skipped_empty}")
    print(f"skipped (conversion produced no frames): {skipped_no_output}")
    print(f"converted: {converted} shapes ({total_frames} total frames) -> {outdir}/")
    return 0


def shape_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .shp file")],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to .pal palette file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Export frames from a Shape (.shp) file to PNG."""
    raise SystemExit(
        cmd_shape_export(
            SimpleNamespace(
                file=file,
                palette=palette,
                output=output,
            )
        )
    )


def shape_batch_cmd(
    directory: Annotated[
        str,
        typer.Argument(
            help="Directory containing .shp files, or a U8SHAPES.FLX archive"
        ),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to .pal palette file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <dir>/png/)"),
    ] = None,
) -> None:
    """Batch-export all .shp files in a directory, or all shapes in U8SHAPES.FLX, to PNG."""
    raise SystemExit(
        cmd_shape_batch(
            SimpleNamespace(
                directory=directory,
                palette=palette,
                output=output,
            )
        )
    )


def shape_import_cmd(
    directory: Annotated[
        str,
        typer.Argument(help="Directory containing *_fNNNN.png frame images"),
    ],
    original: Annotated[
        str,
        typer.Option(
            "--original", help="Path to the original .shp file (metadata reference)"
        ),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to .pal palette file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output .shp path"),
    ] = None,
) -> None:
    """Import PNG frames back into a U8 shape (.shp) file."""
    raise SystemExit(
        cmd_shape_import(
            SimpleNamespace(
                directory=directory,
                original=original,
                palette=palette,
                output=output,
            )
        )
    )


def shape_convert_u7_cmd(
    file: Annotated[str, typer.Argument(help="Path to the U8 .shp file to convert")],
    shape_num: Annotated[
        int,
        typer.Argument(
            help="This shape's number in TYPEFLAG.DAT/U8SHAPES.FLX (for footprint lookup)"
        ),
    ],
    typeflag: Annotated[
        str, typer.Option("--typeflag", help="Path to U8's TYPEFLAG.DAT")
    ],
    u7_static: Annotated[
        str,
        typer.Option(
            "--u7-static",
            help="Path to a real U7/Exult STATIC directory (SHAPES.VGA + TFA.DAT)",
        ),
    ],
    u8_palette: Annotated[
        Optional[str],
        typer.Option("--u8-palette", help="Path to U8PAL.PAL"),
    ] = None,
    u7_palette: Annotated[
        Optional[str],
        typer.Option(
            "--u7-palette",
            help="Path to U7's PALETTES.FLX (default: <u7-static>/PALETTES.FLX)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output .shp path (default: <name>_u7.shp)"
        ),
    ] = None,
) -> None:
    """Convert a U8 shape into a U7/Exult-compatible shape (resize + palette + hotspot convention).

    Static/scenery shapes only (furniture, items, decor) -- not actor/NPC
    animation sets. See titan.u8.u7_shape_convert's module docstring for
    the reasoning and known limitations.
    """
    raise SystemExit(
        cmd_shape_convert_u7(
            SimpleNamespace(
                file=file,
                shape_num=shape_num,
                typeflag=typeflag,
                u7_static=u7_static,
                u8_palette=u8_palette,
                u7_palette=u7_palette,
                output=output,
            )
        )
    )


def shape_convert_u7_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to U8SHAPES.FLX")],
    typeflag: Annotated[
        str, typer.Option("--typeflag", help="Path to U8's TYPEFLAG.DAT")
    ],
    u7_static: Annotated[
        str,
        typer.Option(
            "--u7-static",
            help="Path to a real U7/Exult STATIC directory (SHAPES.VGA + TFA.DAT)",
        ),
    ],
    u8_palette: Annotated[
        Optional[str],
        typer.Option("--u8-palette", help="Path to U8PAL.PAL"),
    ] = None,
    u7_palette: Annotated[
        Optional[str],
        typer.Option(
            "--u7-palette",
            help="Path to U7's PALETTES.FLX (default: <u7-static>/PALETTES.FLX)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: u7_converted/)"
        ),
    ] = None,
) -> None:
    """Batch-convert every used U8 shape into U7/Exult-compatible shapes, same options as shape-convert-u7."""
    raise SystemExit(
        cmd_shape_convert_u7_all(
            SimpleNamespace(
                file=file,
                typeflag=typeflag,
                u7_static=u7_static,
                u8_palette=u8_palette,
                u7_palette=u7_palette,
                output=output,
            )
        )
    )
