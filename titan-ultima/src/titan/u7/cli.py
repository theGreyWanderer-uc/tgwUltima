"""
Ultima 7 — CLI sub-app.

Registered as ``titan u7 <command>`` in the root CLI.
Commands for Ultima 7: The Black Gate and Serpent Isle.
"""

from __future__ import annotations

__all__ = ["u7_app"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

u7_app = typer.Typer(
    name="u7",
    help="Ultima 7 — The Black Gate / Serpent Isle commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — PALETTE
# ============================================================================

def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export palette(s) from PALETTES.FLX or a .pal file."""
    from titan.u7.palette import U7Palette

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or "palettes"
    os.makedirs(outdir, exist_ok=True)

    count = U7Palette.palette_count(filepath)
    indices: list[int]
    if args.index is not None:
        if args.index < 0 or args.index >= count:
            print(f"ERROR: Palette index {args.index} out of range "
                  f"(file has {count} palettes)", file=sys.stderr)
            return 1
        indices = [args.index]
    else:
        indices = list(range(count))

    base = Path(filepath).stem

    for idx in indices:
        pal = U7Palette.from_file(filepath, palette_index=idx)

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

    print(f"Exported {len(indices)} palette(s) to {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SHAPE
# ============================================================================

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

    if is_flex:
        if args.shape is None:
            print("ERROR: --shape N is required when the input is a VGA "
                  "Flex archive (e.g. SHAPES.VGA).", file=sys.stderr)
            return 1
        archive = U7FlexArchive.from_file(filepath)
        shape_idx = args.shape
        num_records = len(archive.records)
        if shape_idx < 0 or shape_idx >= num_records:
            print(f"ERROR: Shape index {shape_idx} out of range "
                  f"(archive has {num_records} records)", file=sys.stderr)
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
            print(f"ERROR: Frame {args.frame} out of range "
                  f"(shape has {len(shape.frames)} frames)", file=sys.stderr)
            return 1
        frames_to_export = [(args.frame, shape.frames[args.frame])]
    else:
        frames_to_export = list(enumerate(shape.frames))

    images = shape.to_pngs(pal)

    for idx, _frame in frames_to_export:
        img = images[idx]
        out_path = os.path.join(outdir, f"{name}_f{idx:04d}.png")
        img.save(out_path)

    print(f"Exported {len(frames_to_export)} frame(s) from {name} "
          f"to {outdir}/")
    return 0


def cmd_shape_batch(args: SimpleNamespace) -> int:
    """Batch-export shapes from a VGA Flex archive to PNG."""
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
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

    archive = U7FlexArchive.from_file(filepath)
    base = Path(filepath).stem

    outdir = args.output or f"{base}_png"
    os.makedirs(outdir, exist_ok=True)

    num_records = len(archive.records)
    start = args.range_start if args.range_start is not None else 0
    end = args.range_end if args.range_end is not None else num_records

    total_frames = 0
    total_shapes = 0

    for shape_idx in range(start, min(end, num_records)):
        rec = archive.get_record(shape_idx)
        if not rec:
            continue

        shape = U7Shape.from_data(rec, is_tile=(shape_idx < FIRST_OBJ_SHAPE))
        if not shape.frames:
            continue

        images = shape.to_pngs(pal)
        shape_dir = os.path.join(outdir, f"{shape_idx:04d}")
        os.makedirs(shape_dir, exist_ok=True)

        for fi, img in enumerate(images):
            out_path = os.path.join(shape_dir, f"{shape_idx:04d}_f{fi:04d}.png")
            img.save(out_path)

        total_shapes += 1
        total_frames += len(images)

    print(f"Exported {total_frames} frame(s) from {total_shapes} shape(s) "
          f"to {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MUSIC
# ============================================================================

def cmd_music_export(args: SimpleNamespace) -> int:
    """Extract music tracks from a U7 music Flex archive to MIDI."""
    from titan.u7.music import extract_music, convert_xmidi_file

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_midi"
    os.makedirs(outdir, exist_ok=True)
    target = (args.target or "mt32").lower()

    # Check if this is a standalone XMIDI file (e.g. ENDSCORE.XMI)
    with open(filepath, "rb") as f:
        magic = f.read(4)

    if magic == b"FORM":
        ok = convert_xmidi_file(filepath, outdir, target=target)
        if ok:
            flavor = "General MIDI" if target == "gm" else "MT-32 MIDI"
            print(f"Converted XMIDI to {flavor} in {outdir}/")
            return 0
        else:
            print("ERROR: Failed to convert XMIDI file", file=sys.stderr)
            return 1

    # Otherwise treat as a Flex archive containing MIDI / XMIDI records
    count = extract_music(filepath, outdir, target=target)
    ext = ".MID"
    flavor = "General MIDI" if target == "gm" else "MT-32 MIDI"
    print(f"Extracted {count} {flavor} track(s) as {ext} to {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — VOC / SPEECH
# ============================================================================

def cmd_voc_export(args: SimpleNamespace) -> int:
    """Decode a Creative Voice (.voc) file to WAV."""
    from titan.u7.sound import VocDecoder

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}.wav")
    VocDecoder.to_wav(filepath, out_path)

    with open(filepath, "rb") as f:
        data = f.read()
    pcm, rate = VocDecoder.decode(data)
    duration = len(pcm) / rate if rate else 0

    print(f"Decoded VOC to WAV: {out_path}")
    print(f"  Sample rate: {rate} Hz, duration: {duration:.1f}s, "
          f"size: {len(pcm):,} bytes")
    return 0


def cmd_speech_export(args: SimpleNamespace) -> int:
    """Extract and decode all speech from a U7 speech Flex archive."""
    from titan.u7.sound import VocDecoder
    from titan.u7.flex import U7FlexArchive

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_wav"

    # Check if this is a single VOC file or a Flex archive
    with open(filepath, "rb") as f:
        header = f.read(max(VOC_HEADER_CHECK, 0x60))

    if VocDecoder.is_voc(header):
        # Single VOC file
        os.makedirs(outdir, exist_ok=True)
        base = Path(filepath).stem
        out_path = os.path.join(outdir, f"{base}.wav")
        VocDecoder.to_wav(filepath, out_path)
        print(f"Decoded 1 VOC file to {outdir}/")
        return 0

    # Flex archive — extract and decode each VOC record
    archive = U7FlexArchive.from_file(filepath)
    os.makedirs(outdir, exist_ok=True)

    decoded = 0
    skipped = 0

    for idx, rec in enumerate(archive.records):
        if not rec:
            continue

        if VocDecoder.is_voc(rec):
            out_path = os.path.join(outdir, f"{idx:04d}.wav")
            VocDecoder.to_wav(filepath, out_path, data=rec)
            decoded += 1
        else:
            # Non-VOC record — save raw (might be text transcripts etc.)
            ext = ".txt" if _looks_like_text(rec) else ".dat"
            out_path = os.path.join(outdir, f"{idx:04d}{ext}")
            with open(out_path, "wb") as f:
                f.write(rec)
            skipped += 1

    print(f"Decoded {decoded} VOC file(s) to WAV in {outdir}/")
    if skipped:
        print(f"  ({skipped} non-VOC record(s) saved as raw)")
    return 0


# 26 bytes needed to check VOC magic
VOC_HEADER_CHECK = 26


def _looks_like_text(data: bytes) -> bool:
    """Heuristic: check if data is likely ASCII text."""
    if not data:
        return False
    # Check first 64 bytes for printable ASCII
    sample = data[:64]
    return all(
        (0x20 <= b <= 0x7E) or b in (0x0A, 0x0D, 0x09)
        for b in sample
    )


# ============================================================================
# TYPER COMMAND WRAPPERS
# ============================================================================

# ---- palette ---------------------------------------------------------------

@u7_app.command("palette-export")
def palette_export_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to PALETTES.FLX or a standalone .pal file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    index: Annotated[
        Optional[int],
        typer.Option("--index", help="Export only this palette index (default: all)"),
    ] = None,
) -> None:
    """Export palettes from PALETTES.FLX as PNG colour swatches and text dumps."""
    raise SystemExit(cmd_palette_export(SimpleNamespace(
        file=file, output=output, index=index,
    )))


@u7_app.command("shape-export")
def shape_export_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to .shp file or VGA Flex archive (e.g. SHAPES.VGA)")],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette",
                     help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    shape: Annotated[
        Optional[int],
        typer.Option("--shape",
                     help="Shape index (required when input is a VGA Flex)"),
    ] = None,
    frame: Annotated[
        Optional[int],
        typer.Option("--frame", help="Export only this frame number"),
    ] = None,
) -> None:
    """Export frames from a U7 shape file to PNG."""
    raise SystemExit(cmd_shape_export(SimpleNamespace(
        file=file, palette=palette, output=output, shape=shape, frame=frame,
    )))


@u7_app.command("shape-batch")
def shape_batch_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to a VGA Flex archive (e.g. SHAPES.VGA, FACES.VGA)")],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette",
                     help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start",
                     help="First shape index to export (default: 0)"),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end",
                     help="Last shape index (exclusive; default: all)"),
    ] = None,
) -> None:
    """Batch-export shapes from a VGA Flex archive to PNG."""
    raise SystemExit(cmd_shape_batch(SimpleNamespace(
        file=file, palette=palette, output=output,
        range_start=range_start, range_end=range_end,
    )))


# ---- music -----------------------------------------------------------------

@u7_app.command("music-export")
def music_export_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to a U7 music archive (ADLIBMUS.DAT, MT32MUS.DAT) "
             "or standalone XMIDI file (ENDSCORE.XMI)")],
    target: Annotated[
        Literal["mt32", "gm"],
        typer.Option(
            "--target",
              help="Export target: original MT-32 MIDI (.MID) or "
                  "General MIDI rewrite (.MID)",
            case_sensitive=False,
        ),
    ] = "mt32",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract U7 music tracks from a Flex archive to MIDI files."""
    raise SystemExit(cmd_music_export(SimpleNamespace(
        file=file, output=output, target=target,
    )))


# ---- voc / speech ----------------------------------------------------------

@u7_app.command("voc-export")
def voc_export_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to a Creative Voice (.voc) file (e.g. INTROSND.DAT)")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decode a Creative Voice (.voc) file to WAV."""
    raise SystemExit(cmd_voc_export(SimpleNamespace(
        file=file, output=output,
    )))


@u7_app.command("speech-export")
def speech_export_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to U7SPEECH.SPC (Flex of VOC records) or a single "
             "VOC file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and decode U7 speech from a Flex archive of VOC files to WAV."""
    raise SystemExit(cmd_speech_export(SimpleNamespace(
        file=file, output=output,
    )))


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MAP
# ============================================================================

def _parse_hex_rgba(color: str) -> tuple[int, int, int, int]:
    """Parse #RRGGBB or #RRGGBBAA into RGBA tuple."""
    txt = color.strip()
    if txt.startswith("#"):
        txt = txt[1:]

    if len(txt) not in (6, 8):
        raise ValueError(
            f"Color '{color}' must be #RRGGBB or #RRGGBBAA.")

    try:
        r = int(txt[0:2], 16)
        g = int(txt[2:4], 16)
        b = int(txt[4:6], 16)
        a = int(txt[6:8], 16) if len(txt) == 8 else 255
    except ValueError as exc:
        raise ValueError(
            f"Color '{color}' is not valid hex.") from exc

    return (r, g, b, a)


def _parse_highlight_tile_rect(
    value: str,
) -> tuple[int, int, int, int, tuple[int, int, int, int], str]:
    """Parse tx0,ty0,tx1,ty1,#RRGGBB[AA][,label] into a typed tuple."""
    parts = [p.strip() for p in value.split(",", 5)]
    if len(parts) not in (5, 6):
        raise ValueError(
            "Expected 'tx0,ty0,tx1,ty1,#RRGGBB[,label]' "
            "(or #RRGGBBAA).")

    try:
        tx0 = int(parts[0], 10)
        ty0 = int(parts[1], 10)
        tx1 = int(parts[2], 10)
        ty1 = int(parts[3], 10)
    except ValueError as exc:
        raise ValueError(
            f"Tile coordinates must be integers in '{value}'.") from exc

    rgba = _parse_hex_rgba(parts[4])
    default_label = f"{tx0},{ty0},{tx1},{ty1}"
    label = parts[5] if len(parts) == 6 and parts[5] else default_label
    return (tx0, ty0, tx1, ty1, rgba, label)

def cmd_map_render(args: SimpleNamespace) -> int:
    """Render a U7 map region (superchunk, chunk range, or full world) to PNG."""
    from titan.u7.map import U7MapRenderer, U7TileRectOverlay
    from titan.u7.palette import U7Palette
    from titan.u7.typeflag import U7TypeFlags

    static_dir = args.static
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}",
              file=sys.stderr)
        return 1

    shapes_path = os.path.join(static_dir, "SHAPES.VGA")
    if not os.path.isfile(shapes_path):
        print(f"ERROR: SHAPES.VGA not found in {static_dir}", file=sys.stderr)
        return 1

    palette_path = args.palette
    if not palette_path:
        palette_path = os.path.join(static_dir, "PALETTES.FLX")
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette not found: {palette_path}", file=sys.stderr)
        return 1

    pal = U7Palette.from_file(palette_path)
    renderer = U7MapRenderer(static_dir)

    view = args.view or "classic"
    if view not in U7MapRenderer.PROJECTIONS:
        print(f"ERROR: Unknown view '{view}'. "
              f"Available: {', '.join(U7MapRenderer.PROJECTIONS.keys())}",
              file=sys.stderr)
        return 1

    # Build exclude set
    exclude: set[int] = set()
    if args.exclude_flags:
        tfa = renderer.tfa
        exclude_kw: dict[str, bool] = {}
        for flag_name in args.exclude_flags:
            exclude_kw[flag_name] = True
        exclude = tfa.build_exclude_set(**exclude_kw)
        active_names = [k for k in exclude_kw if exclude_kw[k]]
        print(f"Typeflag filter: {', '.join(active_names)} -> "
              f"{len(exclude)} shapes excluded")

    gamedat = getattr(args, "gamedat", None)
    overlay_tuples = getattr(args, "highlight_rects", None) or []
    overlays = [
        U7TileRectOverlay(
            tx0=tx0,
            ty0=ty0,
            tx1=tx1,
            ty1=ty1,
            color=color,
            label=label,
        )
        for tx0, ty0, tx1, ty1, color, label in overlay_tuples
    ]
    highlight_width = max(1, int(getattr(args, "highlight_width", 3) or 3))
    highlight_lift = int(getattr(args, "highlight_lift", 0) or 0)
    highlight_fill_alpha = max(
        0, min(255, int(getattr(args, "highlight_fill_alpha", 128) or 128)))
    highlight_labels = bool(getattr(args, "highlight_labels", True))
    ml = getattr(args, "max_lift", None)

    if args.superchunk is not None:
        sc = args.superchunk
        if sc < 0 or sc > 143:
            print(f"ERROR: Superchunk must be 0–143 (got {sc})",
                  file=sys.stderr)
            return 1

        scx = sc % 12
        scy = sc // 12
        print(f"Rendering superchunk {sc} (0x{sc:02X}) at grid ({scx}, {scy}) "
              f"view={view} ...")

        img = renderer.render_superchunk(
            sc, pal,
            view=view,
            include_ireg=gamedat,
            exclude_shapes=exclude,
            max_lift=ml,
            grid=args.grid,
            grid_size=args.grid_size,
            highlight_rects=overlays,
            highlight_width=highlight_width,
            highlight_lift=highlight_lift,
            highlight_fill_alpha=highlight_fill_alpha,
            highlight_labels=highlight_labels,
        )

        out_path = args.output or f"u7_sc{sc:02X}_{view}.png"
    else:
        cx0 = args.chunk_x0
        cy0 = args.chunk_y0
        cx1 = args.chunk_x1 if args.chunk_x1 is not None else cx0 + 15
        cy1 = args.chunk_y1 if args.chunk_y1 is not None else cy0 + 15

        print(f"Rendering chunks ({cx0},{cy0}) to ({cx1},{cy1}) "
              f"view={view} ...")

        img = renderer.render_region(
            cx0, cy0, cx1, cy1, pal,
            view=view,
            gamedat_dir=gamedat,
            exclude_shapes=exclude,
            max_lift=ml,
            grid=args.grid,
            grid_size=args.grid_size,
            highlight_rects=overlays,
            highlight_width=highlight_width,
            highlight_lift=highlight_lift,
            highlight_fill_alpha=highlight_fill_alpha,
            highlight_labels=highlight_labels,
        )

        out_path = args.output or f"u7_c{cx0}-{cy0}_c{cx1}-{cy1}_{view}.png"

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Output: {img.width}×{img.height} -> {out_path}")
    return 0


def cmd_map_sample(args: SimpleNamespace) -> int:
    """Render a colour-sampled minimap of U7 world."""
    from titan.u7.map import U7MapRenderer, U7MapSampler
    from titan.u7.palette import U7Palette

    static_dir = args.static
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}",
              file=sys.stderr)
        return 1

    palette_path = args.palette
    if not palette_path:
        palette_path = os.path.join(static_dir, "PALETTES.FLX")
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette not found: {palette_path}", file=sys.stderr)
        return 1

    pal = U7Palette.from_file(palette_path)
    renderer = U7MapRenderer(static_dir)

    scale = args.scale
    grid = getattr(args, "grid", False)
    grid_size = getattr(args, "grid_size", 1)

    # Build exclude set
    exclude: set[int] = set()
    if args.exclude_flags:
        tfa = renderer.tfa
        exclude_kw: dict[str, bool] = {}
        for flag_name in args.exclude_flags:
            exclude_kw[flag_name] = True
        exclude = tfa.build_exclude_set(**exclude_kw)
        print(f"Typeflag filter: {len(exclude)} shapes excluded")

    schunks: list[int] | None = None
    if args.superchunks:
        schunks = args.superchunks

    print(f"Sampling minimap at scale {scale} tiles/pixel ...")

    img = U7MapSampler.sample_map(
        renderer, pal,
        schunks=schunks,
        scale=scale,
        grid=grid,
        grid_size=grid_size,
        exclude_shapes=exclude,
    )

    out_path = args.output or f"u7_minimap_s{scale}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Output: {img.width}×{img.height} -> {out_path}")
    return 0


def cmd_typeflag_dump(args: SimpleNamespace) -> int:
    """Dump U7 type flag information."""
    from titan.u7.typeflag import U7TypeFlags

    static_dir = args.static
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}",
              file=sys.stderr)
        return 1

    tfa = U7TypeFlags.from_dir(static_dir)
    print(f"Loaded {len(tfa)} shape entries from {static_dir}")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = tfa.dump_csv()
    elif fmt == "detail":
        content = tfa.dump_detail()
    else:
        content = tfa.dump_summary()

    if args.output:
        out_path = args.output
        with open(out_path, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {out_path}")
    else:
        # Print stats to terminal (always useful)
        stats = tfa._compute_stats()
        for label, count in stats:
            if label == "":
                print()
            elif label.startswith("---"):
                print(f"\n{label}")
            else:
                print(f"  {label:30s}: {count:5d}")

    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SAVE
# ============================================================================

def cmd_save_list(args: SimpleNamespace) -> int:
    """List contents of an Exult U7 savegame file."""
    from titan.u7.save import U7Save

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    entries = save.list_entries()

    print(f"U7 Save: {filepath}")
    print(f"Title:   {save.title}")
    print(f"Format:  {save.container_format.upper()}")
    print(f"Entries: {len(entries)}")
    print()
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
    """Extract files from an Exult U7 savegame archive."""
    from titan.u7.save import U7Save

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    entries = save.list_entries()

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    entry_filter = getattr(args, 'entry', None)
    extracted = 0
    for name, size in entries:
        if entry_filter and name.lower() != entry_filter.lower():
            continue
        data = save.get_data(name)
        if data is None:
            continue
        # Handle entries with subdirectory names (e.g. "map00/u7ireg12")
        out_path = os.path.join(outdir, name)
        out_parent = os.path.dirname(out_path)
        if out_parent:
            os.makedirs(out_parent, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"  {name:<24} {size:>10,} bytes")
        extracted += 1

    if entry_filter and extracted == 0:
        print(f"ERROR: Entry '{entry_filter}' not found in archive",
              file=sys.stderr)
        return 1

    print(f"\nExtracted {extracted} file(s) -> {outdir.rstrip(os.sep)}/")
    return 0


def cmd_gflag_dump(args: SimpleNamespace) -> int:
    """Dump global flags from a savegame or loose flaginit file."""
    from titan.u7.save import U7Save, U7GlobalFlags

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    # Determine whether this is a .sav archive or a loose flaginit file
    ext = os.path.splitext(filepath)[1].lower()
    basename = os.path.basename(filepath).lower()

    if ext == ".sav":
        save = U7Save.from_file(filepath)
        gflags = U7GlobalFlags.from_save(save)
        print(f"Source: {filepath} ({save.container_format.upper()} save)")
        print(f"Title:  {save.title}")
    elif basename == "flaginit":
        gflags = U7GlobalFlags.from_file(filepath)
        print(f"Source: {filepath} (loose flaginit file)")
    else:
        # Try as .sav first, fallback to raw flaginit
        try:
            save = U7Save.from_file(filepath)
            gflags = U7GlobalFlags.from_save(save)
            print(f"Source: {filepath} ({save.container_format.upper()} save)")
            print(f"Title:  {save.title}")
        except (ValueError, KeyError):
            gflags = U7GlobalFlags.from_file(filepath)
            print(f"Source: {filepath} (raw flaginit)")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = gflags.dump_csv()
    elif fmt == "detail":
        content = gflags.dump_detail()
    else:
        content = gflags.dump_summary()

    if args.output:
        out_path = args.output
        with open(out_path, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {out_path}")
    else:
        print()
        print(content)

    return 0


def cmd_save_info(args: SimpleNamespace) -> int:
    """Show identity, save metadata, party roster, and game state."""
    from titan.u7.save import (
        U7Save, U7Identity, U7SaveInfo, U7GameState, U7Schedules,
    )

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    lines: list[str] = []
    lines.append(f"=== U7 Save Info ===")
    lines.append(f"File:    {filepath}")
    lines.append(f"Title:   {save.title}")
    lines.append(f"Format:  {save.container_format.upper()}")

    # Identity
    try:
        ident = U7Identity.from_save(save)
        lines.append(f"Game:    {ident.game}")
    except (ValueError, KeyError):
        pass

    lines.append("")

    # Save metadata
    try:
        info = U7SaveInfo.from_save(save)
        lines.append(info.dump())
    except (ValueError, KeyError):
        lines.append("(saveinfo.dat not found)")

    lines.append("")

    # Game state
    try:
        gs = U7GameState.from_save(save)
        lines.append(gs.dump())
    except (ValueError, KeyError):
        lines.append("(gamewin.dat not found)")

    lines.append("")

    # Schedule summary
    try:
        sched = U7Schedules.from_save(save)
        lines.append(sched.dump_summary())
    except (ValueError, KeyError):
        pass

    content = "\n".join(lines)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"Save info written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_save_npcs(args: SimpleNamespace) -> int:
    """Dump NPC data from a savegame."""
    from titan.u7.save import U7Save, U7NPCData

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    print(f"Source: {filepath} ({save.container_format.upper()} save)")
    print(f"Title:  {save.title}")

    # Load TFA for container detection if STATIC path provided
    container_shapes: set[int] | None = None
    static_dir = getattr(args, "static", None)
    if static_dir:
        from titan.u7.typeflag import U7TypeFlags
        tfa = U7TypeFlags.from_dir(static_dir)
        container_shapes = set()
        for entry in tfa.entries:
            if entry.shape_class == 6:
                container_shapes.add(entry.shape)
        print(f"TFA:    {len(container_shapes)} container shapes loaded")
    else:
        print("TFA:    (no --static, using heuristic container detection)")

    npcs = U7NPCData.from_save(save, container_shapes=container_shapes)

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = npcs.dump_csv()
    elif fmt == "detail":
        content = npcs.dump_detail()
    else:
        content = npcs.dump_summary()

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def cmd_save_schedules(args: SimpleNamespace) -> int:
    """Dump NPC schedules from a savegame."""
    from titan.u7.save import U7Save, U7Schedules

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    print(f"Source: {filepath} ({save.container_format.upper()} save)")
    print(f"Title:  {save.title}")

    sched = U7Schedules.from_save(save)

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = sched.dump_csv()
    elif fmt == "detail":
        content = sched.dump_detail()
    else:
        content = sched.dump_summary()

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


# ============================================================================
# TYPER COMMAND WRAPPERS — MAP
# ============================================================================

# Common exclude flag names (matches U7TypeFlags.build_exclude_set kwargs)
_EXCLUDE_FLAG_CHOICES = [
    "no_solid", "no_water", "no_animated", "no_sfx",
    "no_transparent", "no_translucent", "no_door",
    "no_barge", "no_light", "no_poisonous",
    "no_strange_movement", "no_building",
]


@u7_app.command("map-render")
def map_render_cmd(
    static: Annotated[str, typer.Argument(
        help="Path to STATIC directory containing U7MAP, U7CHUNKS, "
             "SHAPES.VGA, etc.")],
    superchunk: Annotated[
        Optional[str],
        typer.Option("--superchunk", "--sc",
                     help="Superchunk number 0–143 (decimal or hex, e.g. 85 or 0x55)"),
    ] = None,
    chunk_x0: Annotated[
        Optional[int],
        typer.Option("--cx0", help="Start chunk X (0–191)"),
    ] = None,
    chunk_y0: Annotated[
        Optional[int],
        typer.Option("--cy0", help="Start chunk Y (0–191)"),
    ] = None,
    chunk_x1: Annotated[
        Optional[int],
        typer.Option("--cx1", help="End chunk X (inclusive)"),
    ] = None,
    chunk_y1: Annotated[
        Optional[int],
        typer.Option("--cy1", help="End chunk Y (inclusive)"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette",
                     help="Path to PALETTES.FLX (default: STATIC/PALETTES.FLX)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    view: Annotated[
        Optional[str],
        typer.Option("--view",
                     help="Projection view: classic, flat, steep"),
    ] = None,
    gamedat: Annotated[
        Optional[str],
        typer.Option("--gamedat",
                     help="Path to gamedat/ directory for IREG dynamic objects"),
    ] = None,
    grid: Annotated[
        bool,
        typer.Option("--grid/--no-grid",
                     help="Overlay chunk grid (blue) and superchunk "
                          "borders (red) with coordinate labels"),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width in pixels"),
    ] = 1,
    full: Annotated[
        bool,
        typer.Option("--full",
                     help="Render the entire world map (shorthand for "
                          "--cx0 0 --cy0 0 --cx1 191 --cy1 191)"),
    ] = False,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option("--exclude",
                     help=f"Exclude shapes by TFA flag. "
                          f"Repeatable. Choices: {', '.join(_EXCLUDE_FLAG_CHOICES)}"),
    ] = None,
    max_lift: Annotated[
        Optional[int],
        typer.Option("--max-lift",
                     help="Maximum object lift (tz) to render (0-15). "
                          "Objects above this lift are hidden."),
    ] = None,
    highlight_tile_rect: Annotated[
        Optional[list[str]],
        typer.Option(
            "--highlight-tile-rect",
            "--hrect",
            help=(
                "Highlight tile rectangle (repeatable): "
                "tx0,ty0,tx1,ty1,#RRGGBB[,label] or #RRGGBBAA[,label]"
            ),
        ),
    ] = None,
    highlight_width: Annotated[
        int,
        typer.Option(
            "--highlight-width",
            help="Highlight outline width in pixels",
        ),
    ] = 3,
    highlight_lift: Annotated[
        int,
        typer.Option(
            "--highlight-lift",
            help="Projection lift value for highlighted rectangles",
        ),
    ] = 0,
    highlight_fill_alpha: Annotated[
        int,
        typer.Option(
            "--highlight-fill-alpha",
            help="Highlight fill alpha (0-255)",
        ),
    ] = 128,
    highlight_labels: Annotated[
        bool,
        typer.Option(
            "--highlight-labels/--no-highlight-labels",
            help="Draw labels on highlighted rectangles",
        ),
    ] = True,
    zone_profile: Annotated[
        Optional[str],
        typer.Option(
            "--zone-profile",
            help=(
                "Load named zone profile overlay data and convert it to "
                "highlight rectangles (e.g. si_zones, bg_zones)"
            ),
        ),
    ] = None,
    zone_id: Annotated[
        Optional[list[str]],
        typer.Option(
            "--zone-id",
            help=(
                "Zone ID to include from --zone-profile. Repeatable. "
                "Examples: --zone-id 3 --zone-id 13 or --zone-id A"
            ),
        ),
    ] = None,
    all_zones: Annotated[
        bool,
        typer.Option(
            "--all-zones",
            help=(
                "Include all zones from --zone-profile. "
                "Default behavior when no --zone-id is supplied"
            ),
        ),
    ] = False,
) -> None:
    """Render a U7 map region (superchunk, chunk range, or full world) to PNG."""
    if full:
        chunk_x0, chunk_y0, chunk_x1, chunk_y1 = 0, 0, 191, 191
    if superchunk is None and chunk_x0 is None:
        print("ERROR: Specify --superchunk N, --full, or --cx0/--cy0 chunk range.",
              file=sys.stderr)
        raise SystemExit(1)

    sc_int: int | None = None
    if superchunk is not None:
        try:
            sc_int = int(superchunk, 0)
        except ValueError:
            print(f"ERROR: --superchunk '{superchunk}' is not a valid integer.",
                  file=sys.stderr)
            raise SystemExit(1)

    parsed_highlights: list[tuple[int, int, int, int, tuple[int, int, int, int], str]] = []
    if highlight_tile_rect:
        for raw in highlight_tile_rect:
            try:
                parsed_highlights.append(_parse_highlight_tile_rect(raw))
            except ValueError as exc:
                print(f"ERROR: --highlight-tile-rect '{raw}': {exc}",
                      file=sys.stderr)
                raise SystemExit(1)

    if zone_profile is None and (zone_id or all_zones):
        print("ERROR: --zone-id/--all-zones requires --zone-profile.",
              file=sys.stderr)
        raise SystemExit(1)

    if zone_profile:
        from titan.u7.zones import (
            U7ZoneProfileError,
            build_zone_highlight_rects,
        )

        try:
            profile_rects = build_zone_highlight_rects(
                zone_profile,
                zone_ids=zone_id,
                include_all=all_zones,
            )
        except U7ZoneProfileError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)

        parsed_highlights.extend(profile_rects)
        print(f"Zone profile '{zone_profile}' -> {len(profile_rects)} rectangle(s)")

    raise SystemExit(cmd_map_render(SimpleNamespace(
        static=static, superchunk=sc_int,
        chunk_x0=chunk_x0 or 0, chunk_y0=chunk_y0 or 0,
        chunk_x1=chunk_x1, chunk_y1=chunk_y1,
        palette=palette, output=output, view=view,
        gamedat=gamedat, grid=grid, grid_size=grid_size,
        exclude_flags=exclude, max_lift=max_lift,
        highlight_rects=parsed_highlights,
        highlight_width=highlight_width,
        highlight_lift=highlight_lift,
        highlight_fill_alpha=highlight_fill_alpha,
        highlight_labels=highlight_labels,
    )))


@u7_app.command("map-sample")
def map_sample_cmd(
    static: Annotated[str, typer.Argument(
        help="Path to STATIC directory")],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette",
                     help="Path to PALETTES.FLX (default: STATIC/PALETTES.FLX)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    scale: Annotated[
        int,
        typer.Option("--scale",
                     help="Tiles per output pixel (1=full, 4=768px, 8=384px)"),
    ] = 4,
    grid: Annotated[
        bool,
        typer.Option("--grid/--no-grid",
                     help="Overlay chunk grid (blue, scale<=2) and "
                          "superchunk grid (red) with coordinate labels"),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width in pixels"),
    ] = 1,
    superchunks: Annotated[
        Optional[list[int]],
        typer.Option("--sc",
                     help="Only sample these superchunks (repeatable)"),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option("--exclude",
                     help="Exclude shapes by TFA flag (repeatable)"),
    ] = None,
) -> None:
    """Render a colour-sampled U7 world minimap to PNG."""
    raise SystemExit(cmd_map_sample(SimpleNamespace(
        static=static, palette=palette, output=output,
        scale=scale, grid=grid, grid_size=grid_size,
        superchunks=superchunks, exclude_flags=exclude,
    )))


@u7_app.command("typeflag-dump")
def typeflag_dump_cmd(
    static: Annotated[str, typer.Argument(
        help="Path to STATIC directory containing TFA.DAT")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format",
                     help="Output format: summary (default), detail, csv"),
    ] = None,
) -> None:
    """Dump U7 type flag data (TFA.DAT, SHPDIMS.DAT, WGTVOL.DAT, OCCLUDE.DAT)."""
    raise SystemExit(cmd_typeflag_dump(SimpleNamespace(
        static=static, output=output, format=format,
    )))


# ============================================================================
# TYPER COMMAND WRAPPERS — SAVE
# ============================================================================

@u7_app.command("save-list")
def save_list_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to Exult .sav file")],
) -> None:
    """List contents of an Exult U7 savegame file (ZIP or FLEX)."""
    raise SystemExit(cmd_save_list(SimpleNamespace(file=file)))


@u7_app.command("save-extract")
def save_extract_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Output directory (default: save filename stem)"),
    ] = None,
    entry: Annotated[
        Optional[str],
        typer.Option("-e", "--entry",
                     help="Extract only this named entry"),
    ] = None,
) -> None:
    """Extract files from an Exult U7 savegame archive."""
    raise SystemExit(cmd_save_extract(SimpleNamespace(
        file=file, output=output, entry=entry,
    )))


@u7_app.command("gflag-dump")
def gflag_dump_cmd(
    file: Annotated[str, typer.Argument(
        help="Exult .sav file or loose flaginit file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format",
                     help="Output format: summary (default), detail, csv"),
    ] = None,
) -> None:
    """Dump global flags from a U7 savegame or flaginit file."""
    raise SystemExit(cmd_gflag_dump(SimpleNamespace(
        file=file, output=output, format=format,
    )))


@u7_app.command("save-info")
def save_info_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Write output to this file"),
    ] = None,
) -> None:
    """Show save metadata: identity, timestamp, party, game state."""
    raise SystemExit(cmd_save_info(SimpleNamespace(
        file=file, output=output,
    )))


@u7_app.command("save-npcs")
def save_npcs_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to Exult .sav file")],
    static: Annotated[
        Optional[str],
        typer.Option("--static",
                     help="Path to STATIC directory (for TFA container detection)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format",
                     help="Output format: summary (default), detail, csv"),
    ] = None,
) -> None:
    """Dump NPC data from an Exult U7 savegame."""
    raise SystemExit(cmd_save_npcs(SimpleNamespace(
        file=file, static=static, output=output, format=format,
    )))


@u7_app.command("save-schedules")
def save_schedules_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format",
                     help="Output format: summary (default), detail, csv"),
    ] = None,
) -> None:
    """Dump NPC schedules from an Exult U7 savegame."""
    raise SystemExit(cmd_save_schedules(SimpleNamespace(
        file=file, output=output, format=format,
    )))


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — FONT CREATE
# ============================================================================

def cmd_font_create(args: SimpleNamespace) -> int:
    """Create a U7 font shape from a TrueType font."""
    from titan.fonts.wizard import run_wizard, run_from_config

    if args.config:
        return run_from_config(args.config, output_override=args.output)
    return run_wizard()


@u7_app.command("font-create")
def font_create_cmd(
    config: Annotated[
        Optional[str],
        typer.Option("--config", "-c",
                     help="TOML config file (skip interactive prompts)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output",
                     help="Output file path"),
    ] = None,
) -> None:
    """Interactive wizard for creating U7 font shapes from TrueType fonts.

    When run without --config, launches an interactive step-by-step
    wizard that walks through game selection, font slot, TTF source,
    rendering method, dimensions, palette, preview, and output.

    With --config, reads all parameters from a TOML recipe file and
    generates the shape non-interactively.
    """
    raise SystemExit(cmd_font_create(SimpleNamespace(
        config=config, output=output,
    )))
