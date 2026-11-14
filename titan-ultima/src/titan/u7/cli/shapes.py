"""``titan u7 shape-*`` — shape export, import, animation and reporting commands."""

from __future__ import annotations

__all__ = [
    "shape_create_cmd",
    "shape_browse_cmd",
    "shape_export_cmd",
    "shape_import_cmd",
    "shape_frame_report_cmd",
    "shape_animate_cmd",
    "shape_batch_cmd",
    "shape_cycle_scan_cmd",
]

import csv
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan import _wizard_ui as ui
from titan.u7 import install
from titan.u7.cli import _common


def cmd_shape_import(args: SimpleNamespace) -> int:
    """Create a standalone U7 SHP from PNG frames in Windows A-Z name order."""
    from titan.u7.palette import U7Palette
    from titan.u7.shape_import import create_u7_shape_from_pngs, sorted_png_frame_paths
    from titan.u7.shape_animation_flag import (
        choose_u7_shape_animation,
        u7_animation_sidecar,
        u7_shape_animation_payload,
        write_u7_animation_payloads,
    )

    source_dir = Path(args.directory)
    if not source_dir.is_dir():
        print(f"ERROR: Shape import directory not found: {source_dir}", file=sys.stderr)
        return 1

    palette_value = getattr(args, "palette", None)
    if not palette_value:
        _, palette_value = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not palette_value:
        game = getattr(args, "game", "bg")
        print(
            "ERROR: Shape import palette not configured: pass --palette or "
            f"configure [u7{game}.paths] palette in titan.toml",
            file=sys.stderr,
        )
        return 1

    palette_path = Path(palette_value)
    if not palette_path.is_file():
        print(f"ERROR: Shape import palette not found: {palette_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    if output_path.suffix.lower() != ".shp":
        print(
            f"ERROR: Shape import output must be a standalone .shp file: {output_path}",
            file=sys.stderr,
        )
        return 1

    png_paths = sorted_png_frame_paths(source_dir)
    if not png_paths:
        print(
            f"ERROR: No PNG frames found in shape import directory: {source_dir}",
            file=sys.stderr,
        )
        return 1

    try:
        palette = U7Palette.from_file(
            str(palette_path),
            palette_index=args.palette_index,
        )
        shape = create_u7_shape_from_pngs(
            png_paths,
            palette,
            allow_cycling=getattr(args, "allow_cycling", False),
            flat=getattr(args, "flat", False),
        )
        animated = choose_u7_shape_animation(
            shape, animated=getattr(args, "animated", None)
        )
        metadata = (
            [
                (
                    u7_animation_sidecar(output_path),
                    u7_shape_animation_payload(shape.to_bytes(), animated),
                )
            ]
            if animated is not None
            else []
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shape.save(str(output_path))
        write_u7_animation_payloads(metadata)
    except (ui.PromptCancelled, KeyboardInterrupt):
        print("Cancelled.")
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: U7 shape import failed: {error}", file=sys.stderr)
        return 1

    print(f"Shape created: {len(shape.frames)} frames -> {output_path}")
    print("  Frame order: Windows A-Z by PNG filename")
    return 0


def _load_translucent_bg_indices(path: str, num_frames: int) -> "list | None":
    """Load an indexed ('P' mode) PNG produced by ``--indexed`` and reuse
    its pixel-index array as the exact-compositing background for every
    frame.  Returns ``None`` (with a printed error) if the file isn't
    already palette-indexed -- this command doesn't attempt to quantize
    an arbitrary RGB image down to indices."""
    import numpy as np
    from PIL import Image

    img = Image.open(path)
    if img.mode != "P":
        print(
            f"ERROR: --translucent-bg file must be a palette-indexed ('P' "
            f"mode) PNG, e.g. produced by --indexed; got mode {img.mode!r}",
            file=sys.stderr,
        )
        return None
    arr = np.array(img)
    return [arr] * num_frames


def cmd_shape_export(args: SimpleNamespace) -> int:
    """Export frames from a U7 shape to PNG."""
    from titan.u7.shape import U7Shape
    from titan.u7.palette import U7Palette
    from titan.u7.flex import U7FlexArchive

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    # Load palette
    if args.palette:
        pal = U7Palette.from_file(args.palette)
    else:
        pal = U7Palette.default_palette()

    # Determine if file is a Flex archive (VGA) or standalone .shp.
    is_flex = U7FlexArchive.is_u7_flex(filepath)
    shape_idx: Optional[int] = None

    if is_flex:
        if args.shape is None:
            print(
                "ERROR: --shape N is required when the input is a VGA "
                "Flex archive (e.g. SHAPES.VGA).",
                file=sys.stderr,
            )
            return 1
        resolved = _common._load_u7_shape_archive(filepath, args)
        if resolved is None:
            return 1
        archive = resolved.effective
        shape_idx = args.shape
        num_records = len(archive.records)
        if shape_idx < 0 or shape_idx >= num_records:
            print(
                f"ERROR: Shape index {shape_idx} out of range "
                f"(archive has {num_records} records)",
                file=sys.stderr,
            )
            return 1
        rec = archive.get_record(shape_idx)
        if not rec:
            print(f"ERROR: Shape {shape_idx} is empty", file=sys.stderr)
            return 1
        from titan.u7.shape import FIRST_OBJ_SHAPE

        shape = U7Shape.from_data(rec, is_tile=(shape_idx < FIRST_OBJ_SHAPE))
        name = f"shape_{shape_idx:04d}"
    else:
        shape = U7Shape.from_file(filepath)
        name = Path(filepath).stem

    if not shape.frames:
        print(f"WARNING: No frames found in {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or name
    os.makedirs(outdir, exist_ok=True)

    if args.frame is not None:
        if args.frame < 0 or args.frame >= len(shape.frames):
            print(
                f"ERROR: Frame {args.frame} out of range "
                f"(shape has {len(shape.frames)} frames)",
                file=sys.stderr,
            )
            return 1
        frames_to_export = [(args.frame, shape.frames[args.frame])]
    else:
        frames_to_export = list(enumerate(shape.frames))

    indexed = getattr(args, "indexed", False)
    cycle_phase_ms = getattr(args, "cycle_phase", 0) or 0
    is_translucent = getattr(args, "translucent", False)
    translucent_bg_path = getattr(args, "translucent_bg", None)
    static_dir = getattr(args, "static", None)

    # Auto-detect translucency from TFA when we know the exact shape number
    # (VGA archive mode) and a STATIC dir was given, unless the user already
    # forced it explicitly -- mirrors shape-animate's existing auto-detection
    # instead of silently exporting flat/wrong colours for translucent shapes.
    auto_detected = False
    if (
        not is_translucent
        and not translucent_bg_path
        and static_dir
        and shape_idx is not None
    ):
        from titan.u7.typeflag import U7TypeFlags

        tfa_entry = U7TypeFlags.from_dir(static_dir).get(shape_idx)
        if tfa_entry is not None and tfa_entry.has_translucency:
            is_translucent = True
            auto_detected = True

    translucency = None
    if is_translucent or translucent_bg_path:
        if not static_dir:
            print(
                "ERROR: --static DIR is required (with --translucent or "
                "--translucent-bg) to load real XFORM.TBL/BLENDS.DAT data",
                file=sys.stderr,
            )
            return 1
        from titan.u7.translucency import U7Translucency

        translucency = U7Translucency.from_dir(static_dir)

    exact_background = None
    if translucent_bg_path:
        exact_background = _load_translucent_bg_indices(
            translucent_bg_path, len(shape.frames)
        )
        if exact_background is None:
            return 1
        is_translucent = True

    if auto_detected:
        print(
            f"NOTE: shape {shape_idx} is TFA-flagged translucent; "
            "auto-applying real BLENDS.DAT compositing.",
            file=sys.stderr,
        )

    if (cycle_phase_ms or is_translucent) and not indexed:
        print(
            "NOTE: RGBA export flattens palette cycling/translucency state "
            "into fixed colours; original pixel indices are not preserved. "
            "Use --indexed to keep exact index values.",
            file=sys.stderr,
        )

    images = shape.to_pngs(
        pal,
        indexed=indexed,
        cycle_phase_ms=cycle_phase_ms,
        has_translucency=is_translucent,
        translucency=translucency,
        exact_background=exact_background,
    )

    for idx, _frame in frames_to_export:
        img = images[idx]
        out_path = os.path.join(outdir, f"{name}_f{idx:04d}.png")
        img.save(out_path)

    print(f"Exported {len(frames_to_export)} frame(s) from {name} to {outdir}/")
    return 0


# LCM of the six colour-cycle range lengths (8,8,4,4,4,3) -- the number of
# 100ms ticks for every cycling range to simultaneously return to its
# original alignment (see titan.u7.palette_cycle).
_CYCLE_FULL_WRAP_STEPS = 24


def cmd_shape_animate(args: SimpleNamespace) -> int:
    """Render a shape's animation (frame-sequence or palette-cycle) to an
    animated GIF."""
    from titan.u7.palette import U7Palette
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
    from titan.u7.flex import U7FlexArchive
    from titan.u7.shape_animation import (
        TICK_MS,
        default_animation_for_tfa,
        has_cycle_pixels,
        save_gif,
        simulate_frame_sequence,
    )

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    pal = (
        U7Palette.from_file(args.palette)
        if args.palette
        else U7Palette.default_palette()
    )

    is_flex = U7FlexArchive.is_u7_flex(filepath)
    if is_flex:
        if args.shape is None:
            print(
                "ERROR: --shape N is required when the input is a VGA "
                "Flex archive (e.g. SHAPES.VGA).",
                file=sys.stderr,
            )
            return 1
        resolved = _common._load_u7_shape_archive(filepath, args)
        if resolved is None:
            return 1
        archive = resolved.effective
        rec = archive.get_record(args.shape)
        if not rec:
            print(f"ERROR: Shape {args.shape} is empty", file=sys.stderr)
            return 1
        shape = U7Shape.from_data(rec, is_tile=(args.shape < FIRST_OBJ_SHAPE))
        name = f"shape_{args.shape:04d}"
    else:
        shape = U7Shape.from_file(filepath)
        name = Path(filepath).stem

    if not shape.frames:
        print(f"WARNING: No frames found in {filepath}", file=sys.stderr)
        return 1

    target_frame = args.frame or 0
    if target_frame < 0 or target_frame >= len(shape.frames):
        print(
            f"ERROR: Frame {target_frame} out of range "
            f"(shape has {len(shape.frames)} frames)",
            file=sys.stderr,
        )
        return 1

    translucency = None
    if args.static:
        from titan.u7.translucency import U7Translucency

        translucency = U7Translucency.from_dir(args.static)

    anim = None
    is_translucent = False
    if args.static and args.shape is not None:
        from titan.u7.typeflag import U7TypeFlags

        tfa = U7TypeFlags.from_dir(args.static)
        entry = tfa.get(args.shape)
        if entry is not None:
            anim = default_animation_for_tfa(entry.anim_type, len(shape.frames))
            # Real per-shape TFA flag -- NOT the same thing as "this frame
            # happens to contain pixels in the 224-254 cycle range" (checked
            # below via has_cycle_pixels). Indices 238-254 are dual-purpose:
            # plain colour cycling on an ordinary shape, but a translucency
            # blend override on one flagged translucent (see
            # titan.u7.translucency). Passing the wrong one here would make
            # a merely-cycling shape's colours freeze at a static blend
            # preview instead of actually animating.
            is_translucent = entry.has_translucency

    mode = args.mode or "auto"
    if mode == "auto":
        mode = "frames" if anim is not None else "cycle"

    outpath = args.output or f"{name}.gif"

    if mode == "frames":
        if anim is None:
            print(
                "ERROR: --mode frames requires --static DIR and --shape N "
                "resolving to a TFA-animated shape (see u7 typeflag-dump)",
                file=sys.stderr,
            )
            return 1

        images = shape.to_pngs(
            pal,
            has_translucency=is_translucent,
            translucency=translucency if is_translucent else None,
        )
        default_steps = 24 if anim.ani_type.name == "HOURLY" else anim.nframes
        steps = args.steps or default_steps
        frame_indices = simulate_frame_sequence(
            anim, 0, steps, hour_start=args.hour_start or 0
        )
        gif_frames = [images[i] for i in frame_indices if 0 <= i < len(images)]
        default_duration = (
            200 if anim.ani_type.name == "HOURLY" else TICK_MS * anim.frame_delay
        )
        duration = args.duration or default_duration
        label = " (translucency-composited)" if is_translucent else ""
        print(
            f"Animating {name}: {anim.ani_type.name.lower()} frame sequence{label}, "
            f"{len(gif_frames)} steps @ {duration}ms"
        )
    else:
        pixels = shape.frames[target_frame].pixels
        if pixels is None:
            print(f"ERROR: Frame {target_frame} has no pixel data", file=sys.stderr)
            return 1
        if not has_cycle_pixels(pixels):
            print(
                f"NOTE: frame {target_frame} has no colour-cycling pixels; "
                "the animation will look static.",
                file=sys.stderr,
            )
        steps = args.steps or _CYCLE_FULL_WRAP_STEPS
        duration = args.duration or TICK_MS
        gif_frames = []
        for step in range(steps):
            imgs = shape.to_pngs(
                pal,
                cycle_phase_ms=step * TICK_MS,
                has_translucency=is_translucent,
                translucency=translucency if is_translucent else None,
            )
            gif_frames.append(imgs[target_frame])
        label = " (translucency-composited)" if is_translucent else ""
        print(
            f"Animating {name} frame {target_frame}: colour-cycle preview{label}, "
            f"{steps} steps @ {duration}ms"
        )

    if not gif_frames:
        print("ERROR: No frames produced for animation", file=sys.stderr)
        return 1

    save_gif(gif_frames, outpath, duration_ms=duration)
    print(f"Saved animated GIF: {outpath}")
    return 0


def cmd_shape_batch_dir(args: SimpleNamespace) -> int:
    """Batch-export every standalone .shp file in a directory to PNG.

    Companion to the VGA-archive path in :func:`cmd_shape_batch` -- for
    a directory of individually-saved shapes (e.g. `titan u8
    shape-convert-u7-all`'s output: one `<num>.shp` per shape, not one
    combined archive). Each file is parsed with :meth:`U7Shape.from_file`,
    which auto-detects ground-tile vs. RLE-sprite framing on its own
    (no VGA shape-index context needed, unlike the archive path).
    """
    from titan.u7.shape import U7Shape
    from titan.u7.palette import U7Palette

    srcdir = args.file
    if args.palette:
        pal = U7Palette.from_file(args.palette)
    else:
        pal = U7Palette.default_palette()

    source_dir_name = Path(srcdir.rstrip("/\\")).name
    outdir = args.output or f"{source_dir_name}_png"
    os.makedirs(outdir, exist_ok=True)

    indexed = getattr(args, "indexed", False)
    cycle_phase_ms = getattr(args, "cycle_phase", 0) or 0

    shp_files = sorted(f for f in os.listdir(srcdir) if f.lower().endswith(".shp"))
    if not shp_files:
        print(f"No .shp files found in {srcdir}")
        return 0

    total_frames = 0
    total_shapes = 0

    for shp_file in shp_files:
        shp_path = os.path.join(srcdir, shp_file)
        try:
            shape = U7Shape.from_file(shp_path)
        except Exception as e:
            print(f"  WARNING: Failed {shp_file}: {e}", file=sys.stderr)
            continue
        if not shape.frames:
            continue

        images = shape.to_pngs(pal, indexed=indexed, cycle_phase_ms=cycle_phase_ms)
        base = Path(shp_file).stem
        shape_dir = os.path.join(outdir, base)
        os.makedirs(shape_dir, exist_ok=True)

        for fi, img in enumerate(images):
            img.save(os.path.join(shape_dir, f"{base}_f{fi:04d}.png"))

        total_shapes += 1
        total_frames += len(images)

    print(f"Exported {total_frames} frame(s) from {total_shapes} shape(s) to {outdir}/")
    return 0


def cmd_shape_batch(args: SimpleNamespace) -> int:
    """Batch-export shapes from a VGA Flex archive, or standalone .shp files from a directory, to PNG."""
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
    from titan.u7.palette import U7Palette

    filepath = args.file
    if os.path.isdir(filepath):
        return cmd_shape_batch_dir(args)
    if not os.path.isfile(filepath):
        print(f"ERROR: File or directory not found: {filepath}", file=sys.stderr)
        return 1

    # Load palette
    if args.palette:
        pal = U7Palette.from_file(args.palette)
    else:
        pal = U7Palette.default_palette()

    resolved = _common._load_u7_shape_archive(filepath, args)
    if resolved is None:
        return 1
    archive = resolved.effective
    base = Path(filepath).stem

    outdir = args.output or f"{base}_png"
    os.makedirs(outdir, exist_ok=True)

    num_records = len(archive.records)
    start = args.range_start if args.range_start is not None else 0
    end = args.range_end if args.range_end is not None else num_records

    indexed = getattr(args, "indexed", False)
    cycle_phase_ms = getattr(args, "cycle_phase", 0) or 0
    if cycle_phase_ms and not indexed:
        print(
            "NOTE: RGBA export flattens palette cycling state into fixed "
            "colours; original pixel indices are not preserved. Use "
            "--indexed to keep exact index values.",
            file=sys.stderr,
        )

    total_frames = 0
    total_shapes = 0

    for shape_idx in range(start, min(end, num_records)):
        rec = archive.get_record(shape_idx)
        if not rec:
            continue

        shape = U7Shape.from_data(rec, is_tile=(shape_idx < FIRST_OBJ_SHAPE))
        if not shape.frames:
            continue

        images = shape.to_pngs(pal, indexed=indexed, cycle_phase_ms=cycle_phase_ms)
        shape_dir = os.path.join(outdir, f"{shape_idx:04d}")
        os.makedirs(shape_dir, exist_ok=True)

        for fi, img in enumerate(images):
            out_path = os.path.join(shape_dir, f"{shape_idx:04d}_f{fi:04d}.png")
            img.save(out_path)

        total_shapes += 1
        total_frames += len(images)

    print(f"Exported {total_frames} frame(s) from {total_shapes} shape(s) to {outdir}/")
    return 0


def _resolved_animation_fields(anim) -> dict:
    """Descriptor columns for a shape's resolved animation parameters
    (type, frame count used, recycle, freeze chance, frame delay) --
    not just a boolean, so a client can reproduce the actual timing.
    Empty/None fields when the shape isn't actually frame-animated."""
    if anim is None:
        return {
            "resolved_ani_type": None,
            "resolved_nframes": None,
            "recycle": None,
            "freeze_first_chance": None,
            "frame_delay": None,
        }
    return {
        "resolved_ani_type": anim.ani_type.name.lower(),
        "resolved_nframes": anim.nframes,
        "recycle": anim.recycle,
        "freeze_first_chance": anim.freeze_first_chance,
        "frame_delay": anim.frame_delay,
    }


def cmd_shape_cycle_scan(args: SimpleNamespace) -> int:
    """Scan a VGA archive for colour-cycling/translucency/frame-animation
    content; export indexed frames and a descriptor for every affected
    shape."""
    from titan.u7.names import U7ShapeNames
    from titan.u7.palette import U7Palette
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
    from titan.u7.shape_cycle_scan import scan_shape
    from titan.u7.translucency import U7Translucency
    from titan.u7.typeflag import U7TypeFlags

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1
    if not args.static:
        print(
            "ERROR: --static DIR is required for TFA animation-type and "
            "translucency lookup",
            file=sys.stderr,
        )
        return 1

    resolved = _common._load_u7_shape_archive(filepath, args)
    if resolved is None:
        return 1
    archive = resolved.effective
    tfa = U7TypeFlags.from_dir(args.static)
    translucency = U7Translucency.from_dir(args.static)
    xfstart = translucency.xfstart if translucency.num_slots else 238
    names = U7ShapeNames.from_static_dir(args.static)

    pal = (
        U7Palette.from_file(args.palette)
        if args.palette
        else U7Palette.default_palette()
    )

    outdir = args.output or "shape_cycle_scan"
    os.makedirs(outdir, exist_ok=True)

    num_records = len(archive.records)
    start = args.range_start if args.range_start is not None else 0
    end = args.range_end if args.range_end is not None else num_records

    reports = []
    for shnum in range(start, min(end, num_records)):
        rec = archive.get_record(shnum)
        if not rec:
            continue
        shape = U7Shape.from_data(rec, is_tile=(shnum < FIRST_OBJ_SHAPE))
        if not shape.frames:
            continue

        name = names.get(shnum) if names else ""
        report = scan_shape(shape, shnum, tfa, xfstart=xfstart, name=name)
        if not report.is_affected:
            continue
        reports.append(report)

        shape_dir = os.path.join(outdir, f"{shnum:04d}")
        os.makedirs(shape_dir, exist_ok=True)
        for fi, img in enumerate(shape.to_pngs(pal, indexed=True)):
            img.save(os.path.join(shape_dir, f"{shnum:04d}_f{fi:04d}.png"))

    rows = [
        {
            "shape": r.shape_num,
            "name": r.name,
            "frame_count": r.frame_count,
            "is_tile_shape": r.is_tile_shape,
            "is_animated": r.is_animated,
            "anim_type": r.anim_type,
            "anim_type_name": r.anim_type_name,
            **_resolved_animation_fields(r.resolved_animation),
            "is_translucent": r.is_translucent,
            "has_any_cycle": r.has_any_cycle,
            "has_any_translucency": r.has_any_translucency,
            "cycle_frame_indices": sorted(r.cycle_frame_indices),
            "translucent_frame_indices": sorted(r.translucent_frame_indices),
            "cycle_indices": sorted(r.all_cycle_indices),
            "translucent_indices": sorted(r.all_translucent_indices),
            "index_255_frame_indices": sorted(r.index_255_frame_indices),
        }
        for r in reports
    ]

    fmt = args.format or "json"
    desc_path = os.path.join(outdir, f"descriptor.{fmt}")
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
        with open(desc_path, "w", newline="") as f:
            f.write(buf.getvalue())
    else:
        with open(desc_path, "w") as f:
            json.dump(rows, f, indent=2)

    translucent_n = sum(1 for r in reports if r.is_translucent)
    animated_n = sum(1 for r in reports if r.has_frame_animation)
    cycle_n = sum(1 for r in reports if r.has_any_cycle and not r.is_translucent)
    print(
        f"Scanned {min(end, num_records) - start} shape(s): {len(reports)} affected "
        f"({translucent_n} translucent, {animated_n} frame-animated, "
        f"{cycle_n} colour-cycling non-translucent)"
    )
    print(f"Indexed frames + {desc_path} written to {outdir}/")
    return 0


def shape_create_cmd(
    source: Annotated[
        Optional[str],
        typer.Argument(help="PNG file or folder of PNG frames (interactive mode)"),
    ] = None,
    animated: Annotated[
        Optional[bool],
        typer.Option(
            "--animate/--no-animate",
            help="Set frame animation explicitly; otherwise ask in the wizard",
        ),
    ] = None,
    config: Annotated[
        Optional[str],
        typer.Option("--config", "-c", help="TOML recipe; generate without prompts"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "--output",
            "-o",
            help="Shape output, or archive destination for archive-only output",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Initial game selection in interactive mode"),
    ] = "bg",
    force: Annotated[
        bool, typer.Option("--force", help="Replace existing output files")
    ] = False,
    allow_cycling: Annotated[
        bool,
        typer.Option(
            "--allow-cycling", help="Allow RGB matching to use cycling indices 224-254"
        ),
    ] = False,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive", help="Original VGA/Flex base for sparse patch inheritance"
        ),
    ] = None,
    preview: Annotated[
        Optional[str],
        typer.Option(
            "--preview", help="Save a source-versus-converted PNG contact sheet"
        ),
    ] = None,
    in_place: Annotated[
        bool,
        typer.Option(
            "--in-place",
            help="Allow the archive destination to be the selected source archive",
        ),
    ] = False,
) -> None:
    """Guide PNG conversion through palette, preview, shape and archive output.

    Accepts a PNG or naturally sorted frame folder. Defaults to the U7 main
    palette, static colours and RLE objects. Supports preview redo, safe free
    slot allocation, explicit flats, sparse patches, archive copies and TOML
    recipes. Existing shape-import and flex-add-shape remain available.
    """
    from titan.u7.shape_wizard import run_from_config, run_wizard

    if config and source:
        raise typer.BadParameter("Use either a source argument or --config")
    if config:
        raise SystemExit(
            run_from_config(
                config,
                output_override=output,
                force=force,
                allow_cycling=allow_cycling,
                base_archive=base_archive,
                preview_path=preview,
                in_place=in_place,
                animated=animated,
            )
        )
    raise SystemExit(
        run_wizard(
            source,
            game=game,
            output_override=output,
            force=force,
            allow_cycling=allow_cycling,
            base_archive=base_archive,
            preview_path=preview,
            in_place=in_place,
            animated=animated,
        )
    )


def shape_browse_cmd(
    archive: Annotated[
        Optional[str],
        typer.Argument(help="Initial VGA/Flex library; otherwise choose interactively"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"], typer.Option("--game", help="Initial game flavour")
    ] = "bg",
    shape: Annotated[
        Optional[int], typer.Option("--shape", help="Initial shape number", min=0)
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "--palette", "-p", help="Palette file; default: selected world's palette"
        ),
    ] = None,
    palette_index: Annotated[
        int,
        typer.Option(
            "--palette-index",
            help="Palette record (0 = U7 main palette)",
            min=0,
            max=255,
        ),
    ] = 0,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive", help="Explicit base for the initial sparse patch archive"
        ),
    ] = None,
) -> None:
    """Browse shapes and frames in colour, then export PNGs or preview a GIF."""
    from titan.u7.shape_browser_ui import run_browser

    raise SystemExit(
        run_browser(
            game=game,
            archive=archive,
            shape=shape,
            palette=palette,
            palette_index=palette_index,
            base_archive=base_archive,
        )
    )


def shape_export_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to .shp file or VGA Flex archive (e.g. SHAPES.VGA)"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    shape: Annotated[
        Optional[int],
        typer.Option("--shape", help="Shape index (required when input is a VGA Flex)"),
    ] = None,
    frame: Annotated[
        Optional[int],
        typer.Option("--frame", help="Export only this frame number"),
    ] = None,
    indexed: Annotated[
        bool,
        typer.Option(
            "--indexed",
            help="Preserve palette indices ('P'-mode PNG) instead of flattening to RGBA",
        ),
    ] = False,
    cycle_phase: Annotated[
        int,
        typer.Option(
            "--cycle-phase",
            help="Preview the palette rotated to this elapsed time in milliseconds",
        ),
    ] = 0,
    translucent: Annotated[
        bool,
        typer.Option(
            "--translucent",
            help="Force this shape as TFA-translucent. Not needed for VGA "
            "archive input when --static is given -- translucency is then "
            "auto-detected from TFA.DAT for the given --shape; use this to "
            "assert it explicitly for a standalone .shp (no shape number "
            "to look up) or to override the auto-detected value",
        ),
    ] = False,
    translucent_bg: Annotated[
        Optional[str],
        typer.Option(
            "--translucent-bg",
            help="Indexed ('P'-mode) PNG background for exact translucency "
            "compositing (implies --translucent); without it, translucent "
            "pixels use the approximate RGBA preview blend colour",
        ),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="STATIC directory to load real XFORM.TBL/BLENDS.DAT from, "
            "and to auto-detect translucency from TFA.DAT for --shape N "
            "(VGA archive input only)",
        ),
    ] = None,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive",
            help="Original VGA/Flex archive for sparse patch inheritance",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="BG or SI config fallback for the patch base"),
    ] = "bg",
) -> None:
    """Export frames from a U7 shape file to PNG."""
    raise SystemExit(
        cmd_shape_export(
            SimpleNamespace(
                base_archive=base_archive,
                game=game,
                file=file,
                palette=palette,
                output=output,
                shape=shape,
                frame=frame,
                indexed=indexed,
                cycle_phase=cycle_phase,
                translucent=translucent,
                translucent_bg=translucent_bg,
                static=static,
            )
        )
    )


def shape_import_cmd(
    directory: Annotated[
        str,
        typer.Argument(help="Directory containing PNG frame images"),
    ],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Standalone output .shp path"),
    ],
    animated: Annotated[
        Optional[bool],
        typer.Option(
            "--animate/--no-animate",
            help="Set frame animation explicitly; otherwise prompt for multiple RLE frames",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to PALETTES.FLX or .pal file (default: selected game's titan.toml palette)",
        ),
    ] = None,
    palette_index: Annotated[
        int,
        typer.Option("--palette-index", help="Palette record within PALETTES.FLX"),
    ] = 0,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI titan.toml palette defaults"),
    ] = "bg",
    allow_cycling: Annotated[
        bool,
        typer.Option(
            "--allow-cycling",
            help="Allow RGB conversion to choose cycling indices 224-254",
        ),
    ] = False,
    flat: Annotated[
        bool,
        typer.Option(
            "--flat", help="Create raw flat frames; all PNGs must be opaque 8x8"
        ),
    ] = False,
) -> None:
    """Create a standalone U7 SHP from PNG frames in Windows A-Z name order."""
    raise SystemExit(
        cmd_shape_import(
            SimpleNamespace(
                directory=directory,
                palette=palette,
                output=output,
                palette_index=palette_index,
                game=game,
                allow_cycling=allow_cycling,
                flat=flat,
                animated=animated,
            )
        )
    )


def shape_frame_report_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to a U7 shape Flex archive such as SHAPES.VGA"),
    ],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output CSV or JSON report path"),
    ],
    wihh: Annotated[
        Optional[str],
        typer.Option(
            "--wihh",
            help="Path to WIHH.DAT (default: discover it beside the archive)",
        ),
    ] = None,
    format: Annotated[
        Literal["csv", "json"],
        typer.Option("-f", "--format", help="Report format: csv (default) or json"),
    ] = "csv",
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive",
            help="Original VGA/Flex archive for sparse patch inheritance",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="BG or SI config fallback for the patch base"),
    ] = "bg",
) -> None:
    """Export every shape/frame origin, drawing hotspot, and WIHH attachment."""
    raise SystemExit(
        cmd_shape_frame_report(
            SimpleNamespace(
                base_archive=base_archive,
                game=game,
                file=file,
                output=output,
                wihh=wihh,
                format=format,
            )
        )
    )


def shape_animate_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to .shp file or VGA Flex archive (e.g. SHAPES.VGA)"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output .gif path (default: <name>.gif)"),
    ] = None,
    shape: Annotated[
        Optional[int],
        typer.Option(
            "--shape",
            help="Shape index (required for VGA input; also used as the TFA "
            "shape number for --mode frames/auto when --static is given)",
        ),
    ] = None,
    frame: Annotated[
        Optional[int],
        typer.Option("--frame", help="Frame to animate in --mode cycle (default: 0)"),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="STATIC directory for TFA animation-type lookup and real "
            "XFORM.TBL/BLENDS.DAT translucency data",
        ),
    ] = None,
    mode: Annotated[
        Literal["auto", "frames", "cycle"],
        typer.Option(
            "--mode",
            help="auto (default): use TFA frame-sequence animation if --static "
            "resolves one, else colour-cycle preview. frames/cycle force one.",
        ),
    ] = "auto",
    steps: Annotated[
        Optional[int],
        typer.Option(
            "--steps", help="Number of animation steps (default depends on mode/type)"
        ),
    ] = None,
    duration: Annotated[
        Optional[int],
        typer.Option(
            "--duration",
            help="Milliseconds per GIF frame (default depends on mode/type)",
        ),
    ] = None,
    hour_start: Annotated[
        Optional[int],
        typer.Option(
            "--hour-start", help="Starting in-game hour for HOURLY-type animations"
        ),
    ] = None,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive",
            help="Original VGA/Flex archive for sparse patch inheritance",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="BG or SI config fallback for the patch base"),
    ] = "bg",
) -> None:
    """Render a shape's frame-sequence or palette-cycle animation to an
    animated GIF."""
    raise SystemExit(
        cmd_shape_animate(
            SimpleNamespace(
                base_archive=base_archive,
                game=game,
                file=file,
                palette=palette,
                output=output,
                shape=shape,
                frame=frame,
                static=static,
                mode=mode,
                steps=steps,
                duration=duration,
                hour_start=hour_start,
            )
        )
    )


def shape_batch_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to a VGA Flex archive (e.g. SHAPES.VGA, FACES.VGA), "
            "or a directory of standalone .shp files"
        ),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option(
            "--range-start",
            help="First shape index to export (default: 0; VGA archive input only)",
        ),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option(
            "--range-end",
            help="Last shape index (exclusive; default: all; VGA archive input only)",
        ),
    ] = None,
    indexed: Annotated[
        bool,
        typer.Option(
            "--indexed",
            help="Preserve palette indices ('P'-mode PNG) instead of flattening to RGBA",
        ),
    ] = False,
    cycle_phase: Annotated[
        int,
        typer.Option(
            "--cycle-phase",
            help="Preview the palette rotated to this elapsed time in milliseconds",
        ),
    ] = 0,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive",
            help="Original VGA/Flex archive for sparse patch inheritance",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="BG or SI config fallback for the patch base"),
    ] = "bg",
) -> None:
    """Batch-export shapes from a VGA Flex archive, or standalone .shp files from a directory, to PNG."""
    raise SystemExit(
        cmd_shape_batch(
            SimpleNamespace(
                base_archive=base_archive,
                game=game,
                file=file,
                palette=palette,
                output=output,
                range_start=range_start,
                range_end=range_end,
                indexed=indexed,
                cycle_phase=cycle_phase,
            )
        )
    )


def shape_cycle_scan_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to a VGA Flex archive (e.g. SHAPES.VGA)"),
    ],
    static: Annotated[
        str,
        typer.Option(
            "--static",
            help="STATIC directory for TFA animation-type and real "
            "XFORM.TBL/BLENDS.DAT translucency lookup (required)",
        ),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: shape_cycle_scan/)"
        ),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First shape index to scan (default: 0)"),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last shape index (exclusive; default: all)"),
    ] = None,
    format: Annotated[
        Literal["json", "csv"],
        typer.Option("-f", "--format", help="Descriptor format: json (default) or csv"),
    ] = "json",
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive",
            help="Original VGA/Flex archive for sparse patch inheritance",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="BG or SI config fallback for the patch base"),
    ] = "bg",
) -> None:
    """Scan a VGA archive for colour-cycling, translucency, and TFA
    frame-animation content, exporting indexed frames plus a descriptor
    for every affected shape."""
    raise SystemExit(
        cmd_shape_cycle_scan(
            SimpleNamespace(
                base_archive=base_archive,
                game=game,
                file=file,
                static=static,
                palette=palette,
                output=output,
                range_start=range_start,
                range_end=range_end,
                format=format,
            )
        )
    )


def cmd_shape_frame_report(args: SimpleNamespace) -> int:
    """Export all shape frames, drawing anchors, and WIHH attachments."""
    from titan.u7.shape_frame_report import build_u7_shape_frame_report
    from titan.u7.wihh import U7WeaponInHandOffsets

    archive_path = Path(args.file)
    if not archive_path.is_file():
        print(
            f"ERROR: U7 shape Flex archive not found: {archive_path}",
            file=sys.stderr,
        )
        return 1

    explicit_wihh_path = getattr(args, "wihh", None)
    wihh_path: Optional[Path] = None
    if explicit_wihh_path:
        wihh_path = Path(explicit_wihh_path)
        if not wihh_path.is_file():
            print(f"ERROR: WIHH.DAT not found: {wihh_path}", file=sys.stderr)
            return 1
    else:
        for filename in ("WIHH.DAT", "wihh.dat"):
            candidate = archive_path.parent / filename
            if candidate.is_file():
                wihh_path = candidate
                break

    try:
        resolved = _common._load_u7_shape_archive(str(archive_path), args)
        if resolved is None:
            return 1
        archive = resolved.effective
        wihh = (
            U7WeaponInHandOffsets.from_file(
                str(wihh_path),
                shape_count=len(archive.records),
            )
            if wihh_path is not None
            else None
        )
        report = build_u7_shape_frame_report(
            archive,
            archive_path=str(archive_path.resolve()),
            wihh=wihh,
            wihh_path=str(wihh_path.resolve()) if wihh_path else None,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: Shape frame report failed: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = report.to_json() if args.format == "json" else report.to_csv()
    try:
        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            output_file.write(content)
            if args.format == "json":
                output_file.write("\n")
    except OSError as exc:
        print(f"ERROR: Could not write shape frame report: {exc}", file=sys.stderr)
        return 1

    print(f"Shape frame report written to: {output_path}")
    print(
        f"  Shapes: {report.shape_count} records "
        f"({report.populated_shape_count} populated, {report.empty_shape_count} empty)"
    )
    print(f"  Frames: {report.frame_count}")
    print(
        f"  WIHH: {wihh_path if wihh_path else 'not found; attachment columns are blank'}"
    )
    if report.parse_error_count:
        print(
            f"  WARNING: {report.parse_error_count} record(s) could not be decoded; "
            "see shape_status and parse_error columns",
            file=sys.stderr,
        )
    return 0
