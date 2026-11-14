"""``titan u9 texture-*`` / ``icon-*`` / ``sdinfo-*`` — texture, UI icon and texture metadata commands."""

from __future__ import annotations

__all__ = [
    "texture_info_cmd",
    "texture_frame_report_cmd",
    "texture_export_cmd",
    "texture_export_all_cmd",
    "icon_list_cmd",
    "icon_export_cmd",
    "icon_export_all_cmd",
    "sdinfo_list_cmd",
    "sdinfo_show_cmd",
    "sdinfo_verify_cmd",
    "texture_import_cmd",
]

import os
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer
from PIL import Image

from titan.u9.asset_reports import (
    TEXTURE_REPORT_COLUMNS,
    U9AssetReportError,
    build_texture_frame_report,
    write_dynamic_report,
)
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.flx_writer import U9FlxWriteError, repack
from titan.u9.icon import icon_entry_indices
from titan.u9.sdinfo import U9SdInfoError
from titan.u9.texture import (
    U9TextureError,
    decode_frame,
    mip_dimensions,
    parse_texture_set,
)
from titan.u9.texture_export import (
    U9TextureExportError,
    export_texture_archives,
    print_texture_export_progress,
)
from titan.u9.texture_writer import U9TextureWriteError, frame_encoding, replace_frames
from titan.u9.cli import _common


def cmd_icon_list(args: SimpleNamespace) -> int:
    """List candidate 2D UI icon entries in a texture archive -- not referenced by any 3D model material."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.textures):
        print(f"ERROR: Texture file not found: {args.textures}", file=sys.stderr)
        return 1

    try:
        sappear = U9FlxArchive.from_file(args.file)
        textures = U9FlxArchive.from_file(args.textures)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    icon_ids = icon_entry_indices(sappear, textures)
    print(
        f"{args.textures} -- {len(icon_ids)} icon candidate(s) of "
        f"{len(textures.used_entry_indices())} used entries (not referenced by any 3D model material)"
    )
    print(f"{'Idx':>6}  {'Size':<10}  {'Bytes':>9}")
    print("-" * 32)
    for idx in icon_ids[: args.limit] if args.limit else icon_ids:
        blob = textures.read_entry(idx)
        try:
            frame = decode_frame(blob, 0)
            size = f"{frame.width}x{frame.height}"
        except U9TextureError:
            size = "?"
        print(f"{idx:>6}  {size:<10}  {len(blob):>9}")
    if args.limit and len(icon_ids) > args.limit:
        print(f"... ({len(icon_ids) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_texture_info(args: SimpleNamespace) -> int:
    """Inspect one texture-set entry without decoding its pixels."""
    if not os.path.isfile(args.textures):
        print(f"ERROR: File not found: {args.textures}", file=sys.stderr)
        return 1
    try:
        archive = U9FlxArchive.from_file(args.textures)
    except U9FlxArchiveError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if not (0 <= args.entry_id < archive.num_entries):
        print(
            f"ERROR: entry_id {args.entry_id} out of range (0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
        return 1
    blob = archive.read_entry(args.entry_id)
    if not blob:
        print(
            f"ERROR: entry {args.entry_id} is an empty/unused archive slot",
            file=sys.stderr,
        )
        return 1

    try:
        texture_set = parse_texture_set(blob)
    except U9TextureError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    compression = {0: "raw", 1: "BC1/DXT1"}.get(
        texture_set.compression, f"unknown ({texture_set.compression})"
    )
    print(f"{args.textures} -- entry {args.entry_id}")
    print(f"  Max dimensions : {texture_set.frame_width}x{texture_set.frame_height}")
    print(f"  Frames         : {texture_set.frame_count}")
    print(f"  Mip levels     : {texture_set.mip_count} additional")
    print(f"  Reserved 0x03  : {texture_set.reserved_0x03:#04x}")
    print(f"  Compression    : {compression}")
    print(f"  Storage flags  : {texture_set.storage_flags:#06x}")
    print(f"  Playback flags : {texture_set.playback_flags:#010x}")
    print(
        "  Playback       : "
        f"mode={texture_set.animation_mode_code}, rate={texture_set.playback_rate}, "
        f"reverse={texture_set.playback_reverse}, "
        f"range={texture_set.default_first_frame}..{texture_set.default_last_frame} "
        f"({texture_set.playback_status})"
    )
    print(
        "  Size exponents : "
        f"{texture_set.width_exponent}, {texture_set.height_exponent} "
        f"({texture_set.dimension_exponent_status})"
    )
    print(
        f"{'Frame':>5}  {'Size':<11}  {'Encoding':<18}  {'Offset':>8}  "
        f"{'Length':>8}  {'Flags':>10}  Anchor"
    )
    print("-" * 92)
    selectors = _common._load_selectors(args.textures)
    for frame in texture_set.frames:
        try:
            encoding = frame_encoding(
                blob, frame.index, selector=selectors.get(args.entry_id)
            )
        except U9TextureWriteError:
            encoding = "?"
        dimensions = mip_dimensions(frame.width, frame.height, texture_set.mip_count)
        sizes = "/".join(f"{width}x{height}" for width, height in dimensions)
        print(
            f"{frame.index:>5}  {sizes:<11}  {encoding:<18}  {frame.offset:>8}  "
            f"{frame.length:>8}  {frame.flags:#010x}  "
            f"({frame.anchor_x}, {frame.anchor_y})"
        )
    return 0


def cmd_texture_frame_report(args: SimpleNamespace) -> int:
    """Export frame metadata with optional sdInfo/model animation evidence."""
    try:
        rows, warnings = build_texture_frame_report(
            args.source,
            entry_id=getattr(args, "entry", None),
            sappear_path=getattr(args, "sappear", None),
            types_path=getattr(args, "types", None),
            typenames_path=getattr(args, "typenames", None),
            only=getattr(args, "only", None),
        )
        output = write_dynamic_report(
            rows,
            args.output,
            args.format,
            preferred_columns=TEXTURE_REPORT_COLUMNS,
        )
    except (U9AssetReportError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"Wrote {len(rows)} texture frame row(s) to {output}")
    return 0


def cmd_texture_export(args: SimpleNamespace) -> int:
    """Export any bitmap or terrain-panel texture surface to PNG."""
    if not os.path.isfile(args.textures):
        print(f"ERROR: File not found: {args.textures}", file=sys.stderr)
        return 1
    if args.palette and not os.path.isfile(args.palette):
        print(f"ERROR: Palette file not found: {args.palette}", file=sys.stderr)
        return 1
    try:
        archive = U9FlxArchive.from_file(args.textures)
    except U9FlxArchiveError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if not (0 <= args.entry_id < archive.num_entries):
        print(
            f"ERROR: entry_id {args.entry_id} out of range (0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
        return 1
    blob = archive.read_entry(args.entry_id)
    if not blob:
        print(
            f"ERROR: entry {args.entry_id} is an empty/unused archive slot",
            file=sys.stderr,
        )
        return 1

    palette = _common._load_palette(args.palette, args.textures)
    selectors = _common._load_selectors(args.textures)
    try:
        surface = decode_frame(
            blob,
            args.frame,
            palette=palette,
            selector=selectors.get(args.entry_id),
            mip_level=args.mip_level,
        )
    except U9TextureError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(
        outdir,
        f"texture_{args.entry_id:05d}_frame_{args.frame:03d}_mip_{args.mip_level:02d}.png",
    )
    Image.frombytes("RGBA", (surface.width, surface.height), surface.pixels_rgba).save(
        out_path
    )
    print(
        f"Exported entry {args.entry_id} frame {args.frame} mip {args.mip_level} "
        f"({surface.width}x{surface.height}) -> {out_path}"
    )
    return 0


def cmd_texture_export_all(args: SimpleNamespace) -> int:
    """Export every texture frame, using only the best available tier by default."""
    try:
        result = export_texture_archives(
            args.source,
            args.output,
            palette_path=args.palette,
            all_mips=args.all_mips,
            entry_id=args.entry,
            all_tiers=args.all_tiers,
            progress=print_texture_export_progress,
        )
    except (OSError, U9TextureExportError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for failure in result.errors[:10]:
        details = ", ".join(
            f"{key} {failure[key]}"
            for key in ("entry", "frame", "mip")
            if key in failure
        )
        location = (
            f"{failure['archive']} ({details})" if details else str(failure["archive"])
        )
        print(f"ERROR: {location}: {failure['error']}", file=sys.stderr)
    print(f"Exported {result.images_written} PNG(s); {len(result.errors)} error(s).")
    for manifest in result.manifests:
        print(f"  Manifest: {manifest}")
    return 1 if result.errors else 0


def cmd_icon_export(args: SimpleNamespace) -> int:
    """Export one texture archive entry to PNG, regardless of whether any 3D model references it."""
    if not os.path.isfile(args.textures):
        print(f"ERROR: File not found: {args.textures}", file=sys.stderr)
        return 1
    if args.palette and not os.path.isfile(args.palette):
        print(f"ERROR: Palette file not found: {args.palette}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(args.textures)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.entry_id < 0 or args.entry_id >= archive.num_entries:
        print(
            f"ERROR: entry_id {args.entry_id} out of range (0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
        return 1

    blob = archive.read_entry(args.entry_id)
    if not blob:
        print(
            f"ERROR: entry {args.entry_id} is an empty/unused archive slot",
            file=sys.stderr,
        )
        return 1

    palette = _common._load_palette(args.palette, args.textures)
    selectors = _common._load_selectors(args.textures)
    try:
        frame = decode_frame(
            blob, args.frame, palette=palette, selector=selectors.get(args.entry_id)
        )
    except U9TextureError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    # The frame index belongs in the name: an entry can hold many frames, and
    # naming them all after the entry alone made a second export overwrite the
    # first instead of sitting beside it.
    out_path = os.path.join(
        outdir, f"icon_{args.entry_id:05d}_frame_{args.frame:03d}.png"
    )
    Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels_rgba).save(
        out_path
    )
    print(
        f"Exported entry {args.entry_id} frame {args.frame} "
        f"({frame.width}x{frame.height}) -> {out_path}"
    )
    return 0


def cmd_icon_export_all(args: SimpleNamespace) -> int:
    """Batch-export every candidate 2D UI icon (not referenced by any 3D model) to PNG."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.textures):
        print(f"ERROR: Texture file not found: {args.textures}", file=sys.stderr)
        return 1
    if args.palette and not os.path.isfile(args.palette):
        print(f"ERROR: Palette file not found: {args.palette}", file=sys.stderr)
        return 1

    try:
        sappear = U9FlxArchive.from_file(args.file)
        textures = U9FlxArchive.from_file(args.textures)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    palette = _common._load_palette(args.palette, args.textures)
    selectors = _common._load_selectors(args.textures)
    icon_ids = icon_entry_indices(sappear, textures)

    outdir = args.output or "icon_export"
    os.makedirs(outdir, exist_ok=True)

    exported = 0
    failed = 0
    for idx in icon_ids:
        blob = textures.read_entry(idx)
        try:
            frame = decode_frame(blob, 0, palette=palette, selector=selectors.get(idx))
        except U9TextureError:
            failed += 1
            continue
        Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels_rgba).save(
            os.path.join(outdir, f"icon_{idx:05d}.png")
        )
        exported += 1

    print(f"Exported {exported}/{len(icon_ids)} candidate icons -> {outdir}/")
    if failed:
        print(f"  ({failed} skipped: malformed or undecodable texture entry)")
    return 0


def cmd_sdinfo_list(args: SimpleNamespace) -> int:
    """List texture metadata records: dimensions, frames and mip levels."""
    info = _common._load_sdinfo(args.file)
    if info is None:
        return 1

    try:
        rows = info.records()
    except U9SdInfoError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.animated:
        rows = [r for r in rows if r.is_animated]
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} record(s) of {info.num_entries} slots")
    print(f"{'Index':>6}  {'Size':<11}  {'Max':<11}  {'Frames':>6}  {'Mips':>4}  Notes")
    print("-" * 66)
    for r in shown:
        notes = []
        if r.frames_vary_in_size:
            notes.append("frames differ in size")
        if not r.is_power_of_two:
            notes.append("not power of two")
        print(
            f"{r.index:>6}  {f'{r.width}x{r.height}':<11}  "
            f"{f'{r.max_width}x{r.max_height}':<11}  {r.frame_count:>6}  "
            f"{r.mip_levels:>4}  {', '.join(notes)}"
        )
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_sdinfo_show(args: SimpleNamespace) -> int:
    """Print one texture's metadata record, decoded fields and raw dwords."""
    info = _common._load_sdinfo(args.file)
    if info is None:
        return 1
    try:
        r = info.record(args.index)
    except U9SdInfoError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if r is None:
        print(f"Texture {args.index} is an unused slot.")
        return 0

    print(f"{args.file} -- texture {r.index}")
    print(f"  Frame 0     : {r.width} x {r.height}")
    print(f"  Max frame   : {r.max_width} x {r.max_height}")
    print(f"  Frames      : {r.frame_count}")
    print(f"  Mip levels  : {r.mip_levels}")
    print(
        f"  log2 dims   : {r.log2_width}, {r.log2_height}"
        f"{'' if r.is_power_of_two else '  (dimensions are not powers of two)'}"
    )
    print(f"  Flags       : mip {r.flag:#06x}, frame {r.frame_flag:#06x}")
    print("  Raw dwords  : " + " ".join(f"{v:#010x}" for v in r.fields))
    print("  Dwords 0, 3, 4, 7 and 8 are not decoded.")
    return 0


def cmd_sdinfo_verify(args: SimpleNamespace) -> int:
    """Cross-check a metadata table against its partner texture archive."""
    info = _common._load_sdinfo(args.file)
    if info is None:
        return 1
    if not os.path.isfile(args.textures):
        print(f"ERROR: File not found: {args.textures}", file=sys.stderr)
        return 1
    try:
        counts = info.cross_check(U9FlxArchive.from_file(args.textures))
    except (U9SdInfoError, U9FlxArchiveError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    total = counts["compared"]
    print(f"{args.file}")
    print(f"{args.textures}")
    print(f"  Same index set : {'yes' if counts['same_index_set'] else 'NO'}")
    print(f"  Compared       : {total} entries")
    for key, label in (
        ("max_dims", "max dimensions"),
        ("frame_count", "frame count"),
        ("mip_levels", "mip levels"),
    ):
        n = counts[key]
        flag = "" if n == total else "   <-- MISMATCH"
        print(
            f"  {label:<15}: {n}/{total} ({100 * n / total if total else 0:.1f}%){flag}"
        )
    return (
        0
        if total
        and all(counts[k] == total for k in ("max_dims", "frame_count", "mip_levels"))
        else 1
    )


_NUMBERED_TEXTURE_FRAME_PATTERN = re.compile(
    r"^(?P<frame_index>[0-9]+)\.png$", re.IGNORECASE
)


def _numbered_texture_frame_paths(directory: str | Path) -> list[tuple[int, Path]]:
    """Find ``N.png`` files and return their numeric frame indices in order."""
    source_dir = Path(directory)
    if not source_dir.is_dir():
        raise ValueError(f"Texture batch import directory not found: {source_dir}")

    indexed_paths: dict[int, Path] = {}
    for path in source_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        match = _NUMBERED_TEXTURE_FRAME_PATTERN.fullmatch(path.name)
        if match is None:
            raise ValueError(
                "Texture batch import PNG filenames must be numeric frame indices; "
                f"found {path.name!r}"
            )
        frame_index = int(match.group("frame_index"))
        previous = indexed_paths.get(frame_index)
        if previous is not None:
            raise ValueError(
                "Texture batch import has duplicate frame index "
                f"{frame_index}: {previous.name!r} and {path.name!r}"
            )
        indexed_paths[frame_index] = path

    if not indexed_paths:
        raise ValueError(f"Texture batch import found no N.png files in: {source_dir}")
    return sorted(indexed_paths.items())


def cmd_texture_import(args: SimpleNamespace) -> int:
    """Replace one or more existing texture frames with same-size PNGs."""
    image_path = getattr(args, "image", None)
    frames_dir = getattr(args, "frames_dir", None)
    if bool(image_path) == bool(frames_dir):
        print(
            "ERROR: Texture import requires either IMAGE or --frames-dir, not both",
            file=sys.stderr,
        )
        return 1
    if not os.path.isfile(args.textures):
        print(f"ERROR: Archive not found: {args.textures}", file=sys.stderr)
        return 1
    if image_path and not os.path.isfile(image_path):
        print(f"ERROR: Image not found: {image_path}", file=sys.stderr)
        return 1
    if args.palette and not os.path.isfile(args.palette):
        print(f"ERROR: Palette file not found: {args.palette}", file=sys.stderr)
        return 1

    try:
        if image_path:
            frame_paths = [(args.frame, Path(image_path))]
        else:
            if frames_dir is None:
                raise ValueError("Texture batch import directory was not provided")
            frame_paths = _numbered_texture_frame_paths(frames_dir)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(args.textures)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not (0 <= args.entry_id < archive.num_entries):
        print(
            f"ERROR: entry_id {args.entry_id} out of range "
            f"(0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
        return 1
    blob = archive.read_entry(args.entry_id)
    if not blob:
        print(
            f"ERROR: entry {args.entry_id} is an unused archive slot", file=sys.stderr
        )
        return 1

    palette = _common._load_palette(args.palette, args.textures)
    selectors = _common._load_selectors(args.textures)
    selector = selectors.get(args.entry_id)

    try:
        replacements: dict[int, tuple[bytes, int, int]] = {}
        encodings: dict[int, str] = {}
        for frame_index, path in frame_paths:
            with Image.open(path) as source_image:
                image = source_image.convert("RGBA")
            replacements[frame_index] = (image.tobytes(), image.width, image.height)
            encodings[frame_index] = frame_encoding(
                blob, frame_index, selector=selector
            )
        patched = replace_frames(
            blob,
            replacements,
            palette=palette,
            selector=selector,
        )
    except (OSError, U9TextureWriteError, struct.error) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out_path = args.output or f"{Path(args.textures).stem}_patched.flx"
    try:
        data = repack(archive, {args.entry_id: patched})
    except U9FlxWriteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    if image_path:
        _rgba, width, height = replacements[args.frame]
        print(
            f"{image_path} ({width}x{height}) -> "
            f"{Path(args.textures).name} entry {args.entry_id} frame {args.frame}"
        )
    else:
        frame_indices = ", ".join(str(index) for index in sorted(replacements))
        print(
            f"{len(replacements)} PNG frame(s) from {frames_dir} -> "
            f"{Path(args.textures).name} entry {args.entry_id}"
        )
        print(f"  Frame indices   : {frame_indices}")
    encoding_counts = Counter(encodings.values())
    encoding_summary = ", ".join(
        f"{encoding} ({count})" for encoding, count in sorted(encoding_counts.items())
    )
    print(f"  Encoding(s)     : {encoding_summary}")
    print(
        f"  Entry length    : {len(patched)} bytes (unchanged: "
        f"{'yes' if len(patched) == len(blob) else 'NO'})"
    )
    print(f"  Written         : {out_path} ({len(data)} bytes)")
    if "bc1" in encoding_counts:
        print(
            "  BC1 is lossy by design; re-encoding will not reproduce the original bytes."
        )
    if "paletted" in encoding_counts and palette is None:
        print("  WARNING: no --palette given for an 8-bit frame.")
    print("  The other quality tiers still hold the old image -- see the reference doc")
    print("  on which archive the game loads for a given texture-detail setting.")
    return 0


def texture_info_cmd(
    textures: Annotated[
        str,
        typer.Argument(
            help="Texture FLX: bitmap*.flx, Texture8.<region>, or texture16.<region>"
        ),
    ],
    entry_id: Annotated[int, typer.Argument(help="Texture-set entry ID to inspect")],
) -> None:
    """Inspect one U9 bitmap or terrain-panel texture entry."""
    raise SystemExit(
        cmd_texture_info(SimpleNamespace(textures=textures, entry_id=entry_id))
    )


def texture_frame_report_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Texture archive or static directory containing all tiers"),
    ],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output CSV or JSON report path"),
    ],
    entry: Annotated[
        Optional[int],
        typer.Option("--entry", help="Limit the report to one texture entry ID"),
    ] = None,
    sappear: Annotated[
        Optional[str],
        typer.Option(
            "--sappear",
            help="Optional sappear.flx path for model-backed animation evidence",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option("--types", help="Optional path to static/TYPES.DAT"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option("--typenames", help="Optional path to static/TYPENAME.FLX"),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option("-f", "--format", help="Report format: csv or json"),
    ] = "csv",
    only: Annotated[
        Optional[str],
        typer.Option(
            "--only",
            help="Filter: animated, multiframe, static, unresolved, or errors",
        ),
    ] = None,
) -> None:
    """Export per-frame texture metadata with discovered companion-file fields."""
    raise SystemExit(
        cmd_texture_frame_report(
            SimpleNamespace(
                source=source,
                output=output,
                entry=entry,
                sappear=sappear,
                types=types,
                typenames=typenames,
                format=fmt,
                only=only,
            )
        )
    )


def texture_export_cmd(
    textures: Annotated[
        str,
        typer.Argument(
            help="Texture FLX: bitmap*.flx, Texture8.<region>, or texture16.<region>"
        ),
    ],
    entry_id: Annotated[int, typer.Argument(help="Texture-set entry ID to export")],
    frame: Annotated[
        int, typer.Option("--frame", help="Frame index within the entry")
    ] = 0,
    mip_level: Annotated[
        int, typer.Option("--mip", help="Stored mip level: 0 is the base image")
    ] = 0,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal for 8-bit palette indices",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: current directory)"
        ),
    ] = None,
) -> None:
    """Export any U9 bitmap or terrain-panel texture surface to PNG."""
    raise SystemExit(
        cmd_texture_export(
            SimpleNamespace(
                textures=textures,
                entry_id=entry_id,
                frame=frame,
                mip_level=mip_level,
                palette=palette,
                output=output,
            )
        )
    )


def texture_export_all_cmd(
    source: Annotated[
        str,
        typer.Argument(
            help="Texture FLX, STATIC directory or installation root (default: configured STATIC)"
        ),
    ],
    output: Annotated[
        str,
        typer.Option(
            "-o", "--output", help="Output root; each archive gets its own folder"
        ),
    ] = "u9_textures",
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="ankh.pal override; otherwise use config or the archive's companion",
        ),
    ] = None,
    all_mips: Annotated[
        bool,
        typer.Option(
            "--all-mips", help="Export every stored mip level as well as base images"
        ),
    ] = False,
    all_tiers: Annotated[
        bool,
        typer.Option(
            "--all-tiers",
            help="Export all available bitmap tiers instead of only the highest quality",
        ),
    ] = False,
    entry: Annotated[
        Optional[int],
        typer.Option(
            "--entry",
            min=0,
            help="Limit export to this texture entry ID in each archive",
        ),
    ] = None,
) -> None:
    """Export every texture frame; default to the best tier at full resolution."""
    raise SystemExit(
        cmd_texture_export_all(
            SimpleNamespace(
                source=source,
                output=output,
                palette=palette,
                all_mips=all_mips,
                all_tiers=all_tiers,
                entry=entry,
            )
        )
    )


def icon_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        str,
        typer.Argument(
            help="Path to a texture archive, e.g. bitmap16.flx or bitmapsh.flx"
        ),
    ],
    limit: Annotated[
        int, typer.Option("--limit", help="Max rows to print (0 = unlimited)")
    ] = 200,
) -> None:
    """List candidate 2D UI icon entries (see titan.u9.icon) not referenced by any 3D model material."""
    raise SystemExit(
        cmd_icon_list(SimpleNamespace(file=file, textures=textures, limit=limit))
    )


def icon_export_cmd(
    textures: Annotated[
        str,
        typer.Argument(
            help="Path to a texture archive, e.g. bitmap16.flx or bitmapsh.flx"
        ),
    ],
    entry_id: Annotated[int, typer.Argument(help="Entry ID (0-7999) to export")],
    frame: Annotated[
        int, typer.Option("--frame", help="Frame index within the entry")
    ] = 0,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: current directory)"
        ),
    ] = None,
) -> None:
    """Export one texture archive entry to PNG, regardless of whether any 3D model references it."""
    raise SystemExit(
        cmd_icon_export(
            SimpleNamespace(
                textures=textures,
                entry_id=entry_id,
                frame=frame,
                palette=palette,
                output=output,
            )
        )
    )


def icon_export_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        str,
        typer.Argument(
            help="Path to a texture archive, e.g. bitmap16.flx or bitmapsh.flx"
        ),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: icon_export/)"),
    ] = None,
) -> None:
    """Batch-export every candidate 2D UI icon (see titan.u9.icon) not referenced by any 3D model."""
    raise SystemExit(
        cmd_icon_export_all(
            SimpleNamespace(
                file=file, textures=textures, palette=palette, output=output
            )
        )
    )


def sdinfo_list_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to static/sdInfo.flx, sdInfo16.flx or sdInfoC.flx"),
    ],
    animated: Annotated[
        bool,
        typer.Option("-a", "--animated", help="Only textures with more than one frame"),
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List U9 texture metadata: dimensions, frame count and mip levels."""
    raise SystemExit(
        cmd_sdinfo_list(SimpleNamespace(file=file, animated=animated, limit=limit))
    )


def sdinfo_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/sdInfo*.flx table")],
    index: Annotated[
        int,
        typer.Argument(help="Texture index -- the same index as in the bitmap archive"),
    ],
) -> None:
    """Print one U9 texture's metadata record."""
    raise SystemExit(cmd_sdinfo_show(SimpleNamespace(file=file, index=index)))


def sdinfo_verify_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/sdInfo*.flx table")],
    textures: Annotated[
        str, typer.Argument(help="Path to its partner bitmap*.flx archive")
    ],
) -> None:
    """Cross-check a U9 texture metadata table against its bitmap archive."""
    raise SystemExit(cmd_sdinfo_verify(SimpleNamespace(file=file, textures=textures)))


def texture_import_cmd(
    textures: Annotated[
        str,
        typer.Argument(
            help="Texture FLX: bitmap*.flx, Texture8.<region>, or texture16.<region>"
        ),
    ],
    entry_id: Annotated[int, typer.Argument(help="Entry ID to replace")],
    image: Annotated[
        Optional[str],
        typer.Argument(help="One PNG to import; omit when using --frames-dir"),
    ] = None,
    frame: Annotated[
        int,
        typer.Option("--frame", help="Frame index for the single IMAGE workflow"),
    ] = 0,
    frames_dir: Annotated[
        Optional[str],
        typer.Option(
            "--frames-dir",
            help="Batch import N.png files, mapping each number to its frame index",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- required for 8-bit frames",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output archive path (default: <stem>_patched.flx)"
        ),
    ] = None,
) -> None:
    """Replace existing U9 texture frames with one PNG or numbered PNGs."""
    raise SystemExit(
        cmd_texture_import(
            SimpleNamespace(
                textures=textures,
                entry_id=entry_id,
                image=image,
                frame=frame,
                frames_dir=frames_dir,
                palette=palette,
                output=output,
            )
        )
    )
