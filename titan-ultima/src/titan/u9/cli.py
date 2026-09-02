"""
Ultima 9: Ascension — CLI sub-app.

Registered as ``titan u9 <command>`` in the root CLI.
"""

from __future__ import annotations

__all__ = ["u9_app"]

import csv
import os
import struct
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer
from PIL import Image

from titan.u9.activity import U9Activities, U9ActivityError
from titan.u9.books import U9Books, U9BooksError
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.fixed import U9Fixed, U9FixedError
from titan.u9.highway import U9Highway, U9HighwayError
from titan.u9.icon import icon_entry_indices
from titan.u9.mesh_export import MeshExportError, export_obj, export_stl
from titan.u9.model import U9Model, U9ModelError
from titan.u9.model_naming import label_for_model, names_for_model
from titan.u9.nonfixed import U9Nonfixed, U9NonfixedError
from titan.u9.npc import NO_CLASS, U9NpcError, U9Npcs
from titan.u9.palette import U9Palette, U9PaletteError
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError
from titan.u9.sound import U9SoundRecord, U9SoundRecordError
from titan.u9.text import U9TextArchive, U9TextError
from titan.u9.terrain import U9Terrain, U9TerrainError
from titan.u9.texture import U9TextureError, decode_frame
from titan.u9.triggers import U9Triggers, U9TriggersError
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat, U9TypesDatError

# ============================================================================
# Typer sub-app
# ============================================================================

u9_app = typer.Typer(
    name="u9",
    help="Ultima 9: Ascension — FLX archive, sound, 3D model, world, script, and navigation commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


# ============================================================================
# CLI COMMANDS — FLX
# ============================================================================

def cmd_flx_list(args: SimpleNamespace) -> int:
    """List an Ultima 9 FLX archive's directory entries."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    used = archive.used_entry_indices()
    print(f"{filepath} — {archive.num_entries} entries ({len(used)} used)")
    print(f"comment: {archive.comment!r}")
    print(f"{'Idx':>6}  {'Offset':>10}  {'Length':>10}")
    print("-" * 32)
    for entry in archive.entries:
        if not entry.is_used:
            continue
        print(f"{entry.index:>6}  {entry.offset:>10}  {entry.length:>10}")
    return 0


def cmd_flx_extract(args: SimpleNamespace) -> int:
    """Extract one entry from an Ultima 9 FLX archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.index < 0 or args.index >= archive.num_entries:
        print(f"ERROR: Index {args.index} out of range (0..{archive.num_entries - 1})", file=sys.stderr)
        return 1

    data = archive.read_entry(args.index)
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{Path(filepath).stem}_{args.index:05d}.bin")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Extracted entry {args.index}: {len(data)} bytes -> {out_path}")
    return 0


def cmd_flx_extract_all(args: SimpleNamespace) -> int:
    """Extract every used entry from an Ultima 9 FLX archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_entries"
    os.makedirs(outdir, exist_ok=True)

    extracted = 0
    for entry in archive.entries:
        if not entry.is_used:
            continue
        data = archive.read_entry(entry.index)
        out_path = os.path.join(outdir, f"{entry.index:05d}.bin")
        with open(out_path, "wb") as f:
            f.write(data)
        extracted += 1

    print(f"Extracted {extracted}/{archive.num_entries} entries -> {outdir}/")
    return 0


# ============================================================================
# CLI COMMANDS — TYPENAME
# ============================================================================

def cmd_typename_dump(args: SimpleNamespace) -> int:
    """Dump type-ID -> display-name pairs from static/TYPENAME.FLX."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        names = U9TypeNames.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    named = [e for e in names if e.name]
    print(f"{filepath} — {len(names)} entries, {len(named)} named")
    print(f"{'TypeID':>7}  Name")
    print("-" * 32)
    for entry in named:
        print(f"{entry.type_id:>7}  {entry.name}")
    return 0


# ============================================================================
# CLI COMMANDS — SOUND
# ============================================================================

def cmd_sound_list(args: SimpleNamespace) -> int:
    """List sound record headers (id, description, format, encoding) in a sound/*.flx archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"{filepath} — {archive.num_entries} entries")
    print(f"{'Idx':>6}  {'Freq':>6}  {'Bits':>4}  {'Ch':>2}  {'Encoding':<14}  {'Bytes':>9}  Description")
    print("-" * 80)
    parsed = 0
    for index in archive.used_entry_indices():
        blob = archive.read_entry(index)
        try:
            record = U9SoundRecord.parse(blob)
        except U9SoundRecordError:
            continue
        parsed += 1
        print(
            f"{index:>6}  {record.frequency:>6}  {record.bits_per_sample:>4}  "
            f"{record.num_channels:>2}  {record.encoding_name:<14}  {len(record.payload):>9}  "
            f"{record.description}"
        )
    print(f"\n{parsed}/{len(archive.used_entry_indices())} entries parsed as sound records")
    return 0


def cmd_sound_extract_pcm(args: SimpleNamespace) -> int:
    """Extract every PCM-encoded entry in a sound/*.flx archive as a playable WAV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_wav"
    os.makedirs(outdir, exist_ok=True)

    extracted = 0
    skipped_encoding = 0
    for index in archive.used_entry_indices():
        blob = archive.read_entry(index)
        try:
            record = U9SoundRecord.parse(blob)
        except U9SoundRecordError:
            continue
        if not record.is_pcm:
            skipped_encoding += 1
            continue
        out_path = os.path.join(outdir, f"{index:05d}_{record.description or record.sound_id}.wav")
        with open(out_path, "wb") as f:
            f.write(record.to_wav_bytes())
        extracted += 1

    print(f"Extracted {extracted} PCM entries -> {outdir}/")
    if skipped_encoding:
        print(f"  ({skipped_encoding} entries skipped: not PCM-encoded, would need codec decoding first)")
    return 0


def cmd_sound_extract(args: SimpleNamespace) -> int:
    """Extract every entry this project can decode (PCM, mono/stereo ADPCM, mono EA MicroTalk) as WAV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_wav"
    os.makedirs(outdir, exist_ok=True)

    extracted = 0
    skipped: dict[str, int] = {}
    for index in archive.used_entry_indices():
        blob = archive.read_entry(index)
        try:
            record = U9SoundRecord.parse(blob)
        except U9SoundRecordError:
            skipped["malformed record"] = skipped.get("malformed record", 0) + 1
            continue

        try:
            wav_bytes = record.to_wav_bytes()
        except U9SoundRecordError:
            reason = f"{record.encoding_name}, {record.num_channels}ch"
            skipped[reason] = skipped.get(reason, 0) + 1
            continue

        out_path = os.path.join(outdir, f"{index:05d}_{record.description or record.sound_id}.wav")
        with open(out_path, "wb") as f:
            f.write(wav_bytes)
        extracted += 1

    print(f"Extracted {extracted}/{len(archive.used_entry_indices())} entries -> {outdir}/")
    for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"  ({count} skipped: {reason})")
    return 0


# ============================================================================
# CLI COMMANDS — MODELS (sappear.flx)
# ============================================================================

def _load_model(sappear_file: str, model_id: int) -> U9Model:
    archive = U9FlxArchive.from_file(sappear_file)
    if model_id < 0 or model_id >= archive.num_entries:
        raise U9ModelError(f"model_id {model_id} out of range (0..{archive.num_entries - 1})")
    blob = archive.read_entry(model_id)
    if not blob:
        raise U9ModelError(f"model_id {model_id} is an empty/unused archive slot")
    return U9Model.parse(blob, model_id=model_id)


def _load_naming(types_path: Optional[str], typenames_path: Optional[str]):
    """Returns (U9TypesDat, U9TypeNames) if both paths are given, else None.

    Naming is optional decoration, so a bad path or a file that is not
    really a TYPES.DAT warns and falls back to unnamed output rather than
    failing the export.
    """
    if not types_path or not typenames_path:
        return None
    try:
        return U9TypesDat.from_file(types_path), U9TypeNames.from_file(typenames_path)
    except (U9TypesDatError, U9FlxArchiveError, OSError) as e:
        print(f"WARNING: could not load type names ({e}); continuing without them", file=sys.stderr)
        return None


def cmd_model_info(args: SimpleNamespace) -> int:
    """Print a model's limb/LOD/material/texture summary."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1

    try:
        model = _load_model(args.file, args.model_id)
    except (U9FlxArchiveError, U9ModelError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    naming = _load_naming(args.types, args.typenames)
    if naming is not None:
        types, typenames = naming
        names = names_for_model(model.model_id, types, typenames)
        if names:
            print(f"model {model.model_id}: possible name(s): {', '.join(names)}")
        else:
            print(f"model {model.model_id}: no named type claims this model")

    print(f"model {model.model_id}: {len(model.limbs)} limb(s)")
    print(f"  bounds: {model.min_bounds} .. {model.max_bounds}")
    print(f"  sphere: center={model.sphere_center} radius={model.sphere_radius:.2f}")
    print(f"  lod_thresholds: {model.lod_thresholds}")
    print()
    print(f"{'Limb':>6}  {'Parent':>6}  {'Root':>5}  {'Position':<30}  LOD triangle/vertex/material counts (texture IDs)")
    print("-" * 100)
    for limb in model.limbs:
        lod_summaries = []
        for lod in limb.lods:
            if lod is None:
                lod_summaries.append("-")
                continue
            tex_ids = sorted({m.texture_id for m in lod.materials if not m.is_invisible})
            lod_summaries.append(
                f"{len(lod.triangles)}t/{len(lod.vertices)}v/{len(lod.materials)}m {tex_ids}"
            )
        pos = tuple(round(v, 2) for v in limb.position)
        print(
            f"{limb.limb_id:>6}  {limb.parent_id:>6}  {str(limb.is_root):>5}  {str(pos):<30}  "
            + " | ".join(lod_summaries)
        )
    return 0


def _make_texture_resolver(textures_path: Optional[str], palette_path: Optional[str]):
    if not textures_path:
        return None
    texture_archive = U9FlxArchive.from_file(textures_path)
    palette = U9Palette.from_file(palette_path) if palette_path else None

    def resolver(texture_id: int, frame: int):
        try:
            blob = texture_archive.read_entry(texture_id)
            return decode_frame(blob, frame, palette=palette)
        except (U9FlxArchiveError, U9TextureError):
            return None

    return resolver


def _validate_model_export_args(args: SimpleNamespace) -> Optional[str]:
    """Returns an error message if args are invalid, else None."""
    if args.format not in ("obj", "stl", "both"):
        return f"--format must be one of obj, stl, both (got {args.format!r})"
    if not os.path.isfile(args.file):
        return f"File not found: {args.file}"
    if args.textures and not os.path.isfile(args.textures):
        return f"Texture file not found: {args.textures}"
    if args.palette and not os.path.isfile(args.palette):
        return f"Palette file not found: {args.palette}"
    if args.types and not os.path.isfile(args.types):
        return f"Types file not found: {args.types}"
    if args.typenames and not os.path.isfile(args.typenames):
        return f"Typenames file not found: {args.typenames}"
    return None


def cmd_model_export(args: SimpleNamespace) -> int:
    """Export one model to OBJ and/or STL, with textures resolved from a texture FLX archive if given."""
    error = _validate_model_export_args(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        model = _load_model(args.file, args.model_id)
    except (U9FlxArchiveError, U9ModelError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    resolver = _make_texture_resolver(args.textures, args.palette)

    naming = _load_naming(args.types, args.typenames)
    label = label_for_model(args.model_id, *naming) if naming is not None else None
    stem = f"model_{args.model_id:05d}" + (f"_{label}" if label else "")

    outdir = args.output or stem
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, stem)

    wrote = []
    try:
        if args.format in ("obj", "both"):
            export_obj(model, base + ".obj", lod_level=args.lod, texture_resolver=resolver)
            wrote.append(base + ".obj")
        if args.format in ("stl", "both"):
            export_stl(model, base + ".stl", lod_level=args.lod)
            wrote.append(base + ".stl")
    except MeshExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Exported model {args.model_id} (LOD {args.lod}) -> {outdir}/")
    for path in wrote:
        print(f"  {path}")
    if args.format in ("obj", "both") and resolver is None:
        print("  (no --textures given: OBJ materials have no images)")

    if args.preview:
        _generate_preview(outdir)
    return 0


def _generate_preview(outdir: str) -> None:
    from titan.u9.preview import PreviewError, PreviewUnavailableError, render_preview

    try:
        for preview_path in render_preview(outdir):
            print(f"  {preview_path}")
    except PreviewUnavailableError as e:
        print(f"  (skipped preview: {e})")
    except PreviewError as e:
        print(f"  (skipped preview: {e})")


def _export_all_one(model_id: int, blob: bytes, outdir: str, resolver, naming, args: SimpleNamespace, stats: Counter) -> None:
    """One model's worth of ``model-export-all`` work: parse, export, preview. Updates ``stats`` in place."""
    try:
        model = U9Model.parse(blob, model_id=model_id)
    except U9ModelError:
        stats["parse_fail"] += 1
        return

    label = label_for_model(model_id, *naming) if naming is not None else None
    stem = f"model_{model_id:05d}" + (f"_{label}" if label else "")
    if label:
        stats["named"] += 1
    model_dir = os.path.join(outdir, stem)
    os.makedirs(model_dir, exist_ok=True)
    base = os.path.join(model_dir, stem)

    try:
        if args.format in ("obj", "both"):
            export_obj(model, base + ".obj", lod_level=args.lod, texture_resolver=resolver)
        if args.format in ("stl", "both"):
            export_stl(model, base + ".stl", lod_level=args.lod)
        stats["exported"] += 1
    except MeshExportError:
        stats["no_geometry"] += 1
        os.rmdir(model_dir)  # nothing was written into it
        return

    if not args.preview or args.format not in ("obj", "both") or stats["preview_unavailable"]:
        return
    from titan.u9.preview import PreviewError, PreviewUnavailableError, render_preview

    try:
        render_preview(model_dir)
        stats["previewed"] += 1
    except PreviewUnavailableError as e:
        stats["preview_unavailable"] = 1
        print(f"  (skipping all further previews: {e})", flush=True)
    except PreviewError:
        stats["preview_failed"] += 1


def cmd_model_export_all(args: SimpleNamespace) -> int:
    """Export every used model in a sappear.flx archive, same options as model-export, one subfolder each."""
    error = _validate_model_export_args(
        SimpleNamespace(
            format=args.format, file=args.file, textures=args.textures, palette=args.palette,
            types=args.types, typenames=args.typenames,
        )
    )
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(args.file)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    resolver = _make_texture_resolver(args.textures, args.palette)
    naming = _load_naming(args.types, args.typenames)
    outdir = args.output or "model_export"
    os.makedirs(outdir, exist_ok=True)

    used = archive.used_entry_indices()
    stats: Counter = Counter()

    for i, model_id in enumerate(used):
        if i % 200 == 0:
            print(f"  ... {i}/{len(used)}", flush=True)
        _export_all_one(model_id, archive.read_entry(model_id), outdir, resolver, naming, args, stats)

    print()
    print(f"total used models: {len(used)}")
    print(f"parse failures (corrupt entries): {stats['parse_fail']}")
    print(f"no visible geometry: {stats['no_geometry']}")
    print(f"exported: {stats['exported']} -> {outdir}/")
    print(f"  of which named: {stats['named']}")
    if args.preview:
        print(f"previews rendered: {stats['previewed']}")
        print(f"preview failures: {stats['preview_failed']}")
    return 0


# ============================================================================
# CLI COMMANDS — 2D UI ICONS (bitmap16.flx/bitmapC.flx/bitmapsh.flx entries
# not referenced by any sappear.flx model -- see titan.u9.icon)
# ============================================================================

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
        print(f"ERROR: entry_id {args.entry_id} out of range (0..{archive.num_entries - 1})", file=sys.stderr)
        return 1

    blob = archive.read_entry(args.entry_id)
    if not blob:
        print(f"ERROR: entry {args.entry_id} is an empty/unused archive slot", file=sys.stderr)
        return 1

    palette = U9Palette.from_file(args.palette) if args.palette else None
    try:
        frame = decode_frame(blob, args.frame, palette=palette)
    except U9TextureError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"icon_{args.entry_id:05d}.png")
    Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels_rgba).save(out_path)
    print(f"Exported entry {args.entry_id} ({frame.width}x{frame.height}) -> {out_path}")
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

    palette = U9Palette.from_file(args.palette) if args.palette else None
    icon_ids = icon_entry_indices(sappear, textures)

    outdir = args.output or "icon_export"
    os.makedirs(outdir, exist_ok=True)

    exported = 0
    failed = 0
    for idx in icon_ids:
        blob = textures.read_entry(idx)
        try:
            frame = decode_frame(blob, 0, palette=palette)
        except U9TextureError:
            failed += 1
            continue
        Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels_rgba).save(
            os.path.join(outdir, f"icon_{idx:05d}.png")
        )
        exported += 1

    print(f"Exported {exported}/{len(icon_ids)} candidate icons -> {outdir}/")
    if failed:
        print(f"  ({failed} skipped: decode failed, likely unsupported bitmapC.flx compression)")
    return 0


# ============================================================================
# CLI COMMANDS — RUNTIME NONFIXED REGIONS (runtime/nonfixed.%d)
# ============================================================================

def _load_region(filepath: str) -> Optional[U9Nonfixed]:
    """Open a nonfixed region file, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Nonfixed.from_file(filepath)
    except U9NonfixedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def _load_typenames(path: Optional[str]) -> Optional[U9TypeNames]:
    if not path:
        return None
    try:
        return U9TypeNames.from_file(path)
    except (U9FlxArchiveError, OSError) as e:
        print(f"WARNING: could not read type names from {path}: {e}", file=sys.stderr)
        return None


def cmd_nonfixed_info(args: SimpleNamespace) -> int:
    """Summarize one runtime/nonfixed.%d region: grid, pages, entities, triggers."""
    region = _load_region(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    pages = sum(len(c.pages) for c in chunks)
    entities = sum(len(c.entities) for c in chunks)
    declared = sum(c.declared_entity_count for c in chunks)
    triggers = sum(c.trigger_count for c in chunks)
    extras = sum(1 for c in chunks for e in c.entities if e.has_extra_data)
    incomplete = [c for c in chunks if not c.is_complete]

    print(f"{args.file} -- {region.width}x{region.height} chunk region")
    print(f"  Header          : {region.header_size} bytes")
    print(f"  Payload         : {region.payload_size} bytes (watermark {region.declared_payload_size})")
    print(f"  Populated chunks: {len(chunks)} of {region.num_chunks}")
    print(f"  Pages           : {pages}")
    print(f"  Entities        : {entities} walked, {declared} declared")
    print(f"  Triggers        : {triggers} (record layout not decoded)")
    print(f"  Extra-data      : {extras} entities carry a block")
    if incomplete:
        missing = declared - entities
        print(
            f"  NOTE: {len(incomplete)} chunk(s) undershot by {missing} entit"
            f"{'y' if missing == 1 else 'ies'}. Enumeration can miss entities; "
            "it never invents them."
        )
    return 0


def cmd_nonfixed_chunks(args: SimpleNamespace) -> int:
    """List every populated chunk in a region with its page and entity counts."""
    region = _load_region(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    print(f"{args.file} -- {len(chunks)} populated chunk(s) of {region.num_chunks}")
    print(f"{'Idx':>5}  {'Grid':<9}  {'Base (x,y)':<15}  {'Pages':>5}  {'Ents':>6}  {'Decl':>6}  {'Trig':>5}  Full")
    print("-" * 74)
    for c in chunks:
        grid = f"{c.chunk_x},{c.chunk_y}"
        base = f"{c.base_x},{c.base_y}"
        flag = "yes" if c.is_complete else f"-{c.declared_entity_count - len(c.entities)}"
        print(
            f"{c.index:>5}  {grid:<9}  {base:<15}  {len(c.pages):>5}  "
            f"{len(c.entities):>6}  {c.declared_entity_count:>6}  {c.trigger_count:>5}  {flag}"
        )
    return 0


def cmd_nonfixed_entities(args: SimpleNamespace) -> int:
    """List dynamic objects in a region, optionally restricted to one chunk."""
    region = _load_region(args.file)
    if region is None:
        return 1

    if args.chunk is not None:
        try:
            cx, cy = (int(v) for v in args.chunk.split(",", 1))
        except ValueError:
            print(f"ERROR: --chunk expects 'X,Y', got {args.chunk!r}", file=sys.stderr)
            return 1
        try:
            chunk = region.chunk(cx, cy)
        except U9NonfixedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if chunk is None:
            print(f"Chunk ({cx}, {cy}) holds no pages.")
            return 0
        chunks = [chunk]
    else:
        chunks = region.chunks()

    names = _load_typenames(args.typenames)
    rows = [(c, e) for c in chunks for e in c.entities]
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} entit{'y' if len(rows) == 1 else 'ies'}")
    header = f"{'Offset':>8}  {'Chunk':<7}  {'World (x,y,z)':<20}  {'Type':>5}  {'Mesh':>5}  {'Trig':>5}  {'Extra':>7}"
    if names:
        header += "  Name"
    print(header)
    print("-" * (len(header) + 8))
    for c, e in shown:
        grid = f"{c.chunk_x},{c.chunk_y}"
        pos = f"{e.world_x},{e.world_y},{e.z}"
        extra = f"{e.extra_data_offset:#07x}" if e.has_extra_data else "-"
        line = (
            f"{e.offset:>#8x}  {grid:<7}  {pos:<20}  {e.type_index:>5}  "
            f"{e.mesh_index:>5}  {e.trigger_id:>5}  {extra:>7}"
        )
        if names:
            line += f"  {names.name_for(e.type_index) or ''}"
        print(line)
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def _entity_fields(entity) -> dict:
    return {
        "x": entity.offset_x,
        "y": entity.offset_y,
        "z": entity.z,
        "type": entity.type_index,
        "rotation": entity.rotation,
        "flags": entity.flags,
        "mesh": entity.mesh_index,
        "trigger": entity.trigger_id,
        "extra": entity.extra_data_offset,
    }


def cmd_nonfixed_diff(args: SimpleNamespace) -> int:
    """Compare two region files entity by entity -- e.g. a patched region against its original."""
    left = _load_region(args.left)
    right = _load_region(args.right)
    if left is None or right is None:
        return 1

    if (left.width, left.height) != (right.width, right.height):
        print(
            f"Region grids differ: {left.width}x{left.height} vs {right.width}x{right.height}",
            file=sys.stderr,
        )
        return 1

    names = _load_typenames(args.typenames)

    def index(region):
        return {
            (c.index, e.offset): (c, e)
            for c in region.chunks()
            for e in c.entities
        }

    a, b = index(left), index(right)
    only_left = sorted(set(a) - set(b))
    only_right = sorted(set(b) - set(a))
    changed = []
    for key in sorted(set(a) & set(b)):
        fa, fb = _entity_fields(a[key][1]), _entity_fields(b[key][1])
        delta = {k: (fa[k], fb[k]) for k in fa if fa[k] != fb[k]}
        if delta:
            changed.append((key, delta))

    print(args.left)
    print(args.right)
    print(
        f"  {len(a)} vs {len(b)} entities  |  "
        f"{len(changed)} changed, {len(only_left)} removed, {len(only_right)} added"
    )
    if not (changed or only_left or only_right):
        print("  No entity-level differences.")
        return 0

    def label(entry):
        chunk, entity = entry
        name = f" {names.name_for(entity.type_index)}" if names else ""
        return f"chunk {chunk.chunk_x},{chunk.chunk_y} @{entity.offset:#08x} type {entity.type_index}{name}"

    if changed:
        print("")
        print("Changed:")
        for key, delta in changed:
            print(f"  {label(a[key])}")
            for field, (old, new) in delta.items():
                print(f"      {field}: {old} -> {new}")
    if only_left:
        print("")
        print(f"Only in {args.left}:")
        for key in only_left:
            print(f"  {label(a[key])}")
    if only_right:
        print("")
        print(f"Only in {args.right}:")
        for key in only_right:
            print(f"  {label(b[key])}")
    return 0


# ============================================================================
# CLI COMMANDS — HIGHWAY NAVIGATION GRAPH (static/highway.dat)
# ============================================================================

def _load_highway(filepath: str) -> Optional[U9Highway]:
    """Open static/highway.dat, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Highway.from_file(filepath)
    except U9HighwayError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_highway_info(args: SimpleNamespace) -> int:
    """Summarize the U9 NPC navigation graph: points, routes, connectivity."""
    highway = _load_highway(args.file)
    if highway is None:
        return 1

    adjacency = highway.neighbors()
    edges = sum(len(v) for v in adjacency.values()) // 2
    unknown = highway.unknown_path_nodes()
    xs = [p.x for p in highway.points]
    ys = [p.y for p in highway.points]
    ids = [p.trigger_id for p in highway.points]

    print(f"{args.file} -- U9 highway navigation graph")
    print(f"  Points          : {len(highway.points)} of {highway.declared_point_count} declared")
    print(f"  Routes          : {len(highway.routes)} of {highway.declared_route_count} declared")
    print(f"  Route block     : {highway.route_bytes} bytes, {highway.route_bytes_consumed} consumed")
    if ids:
        print(f"  Trigger IDs     : {min(ids)}..{max(ids)}")
        print(f"  World extent    : x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
    print(f"  Connectivity    : {len(adjacency)} point(s) appear in a route, {edges} edge(s)")
    if highway.routes:
        longest = max(highway.routes, key=lambda r: r.path_length)
        print(f"  Longest route   : {longest.start_trigger_id} -> {longest.last_trigger_id}, "
              f"{longest.path_length} nodes, distance {longest.route_distance}")
    if unknown:
        print(f"  WARNING: {len(unknown)} route node(s) have no declared point: {unknown[:10]}")
    if not highway.is_complete:
        print("  WARNING: file did not parse completely -- truncated or not a highway.dat")
    print("  Points are keyed by trigger ID; the world markers are entities of")
    print("  type 1134 -- see 'titan u9 nonfixed-entities'.")
    return 0


def cmd_highway_points(args: SimpleNamespace) -> int:
    """List highway navigation points and their absolute world positions."""
    highway = _load_highway(args.file)
    if highway is None:
        return 1

    adjacency = highway.neighbors()
    if args.id is not None:
        point = highway.point(args.id)
        if point is None:
            print(f"No highway point with trigger ID {args.id}.")
            return 0
        points = [point]
    else:
        points = list(highway.points)

    shown = points[: args.limit] if args.limit else points
    print(f"{args.file} -- {len(points)} point(s)")
    print(f"{'TriggerID':>10}  {'X':>8}  {'Y':>8}  {'Links':>5}  Routes")
    print("-" * 52)
    for p in shown:
        links = len(adjacency.get(p.trigger_id, ()))
        through = len(highway.routes_through(p.trigger_id))
        print(f"{p.trigger_id:>10}  {p.x:>8}  {p.y:>8}  {links:>5}  {through}")
    if args.limit and len(points) > args.limit:
        print(f"... ({len(points) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_highway_routes(args: SimpleNamespace) -> int:
    """List precomputed routes through the highway graph."""
    highway = _load_highway(args.file)
    if highway is None:
        return 1

    routes = highway.routes_through(args.id) if args.id is not None else list(highway.routes)
    if args.id is not None and not routes:
        print(f"No route visits trigger ID {args.id}.")
        return 0

    shown = routes[: args.limit] if args.limit else routes
    print(f"{args.file} -- {len(routes)} route(s)")
    for r in shown:
        print(
            f"  {r.start_trigger_id} -> {r.last_trigger_id}  "
            f"nodes {r.path_length}, hops {r.hops}, distance {r.route_distance}"
        )
        if args.paths:
            print(f"      {' -> '.join(str(n) for n in r.path)}")
    if args.limit and len(routes) > args.limit:
        print(f"... ({len(routes) - args.limit} more; raise --limit to see more)")
    return 0


# ============================================================================
# CLI COMMANDS — TRIGGER SCRIPTS (static/triggers.flx)
# ============================================================================

def _load_triggers(filepath: str) -> Optional[U9Triggers]:
    """Open static/triggers.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Triggers.from_file(filepath)
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_trigger_list(args: SimpleNamespace) -> int:
    """List trigger scripts with their record counts."""
    triggers = _load_triggers(args.file)
    if triggers is None:
        return 1

    try:
        entries = triggers.triggers()
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not args.all:
        entries = [t for t in entries if not t.is_empty]
    shown = entries[: args.limit] if args.limit else entries

    empty = sum(1 for t in triggers.triggers() if t.is_empty)
    print(f"{args.file} -- {len(entries)} trigger(s) of {triggers.num_entries} slots ({empty} empty)")
    print(f"{'TriggerID':>10}  {'Records':>7}  {'Slack':>5}  {'Term':>5}  Opcodes")
    print("-" * 66)
    for t in shown:
        term = "yes" if t.terminated else "NO"
        ops = " ".join(f"{o:#04x}" for o in t.opcodes[:6])
        if len(t.opcodes) > 6:
            ops += " ..."
        print(f"{t.trigger_id:>10}  {len(t.records):>7}  {t.slack_records:>5}  {term:>5}  {ops}")
    if args.limit and len(entries) > args.limit:
        print(f"... ({len(entries) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_trigger_show(args: SimpleNamespace) -> int:
    """Dump one trigger script's records."""
    triggers = _load_triggers(args.file)
    if triggers is None:
        return 1

    try:
        trigger = triggers.trigger(args.id)
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if trigger is None:
        print(f"Trigger {args.id} is an unused slot.")
        return 0

    print(f"{args.file} -- trigger {trigger.trigger_id}")
    if trigger.is_empty:
        print("  (empty -- the terminator is the first record)")
    if not trigger.terminated:
        print("  WARNING: no 0xFF terminator; the record list runs to the end of the entry")
    if trigger.slack_records:
        print(f"  {trigger.slack_records} stale record(s) after the terminator, not decoded")
    if trigger.records:
        print(f"  {'#':>3}  {'Opcode':>6}  {'Arg0':>5}  {'Arg1':>6}  {'Arg2':>6}")
        print("  " + "-" * 38)
        for index, r in enumerate(trigger.records):
            print(f"  {index:>3}  {r.opcode:>#6x}  {r.arg0:>5}  {r.arg1:>6}  {r.arg2:>6}")
    print("  Opcode 0x31 runs an activity record; the other 89 are not decoded.")
    return 0


def cmd_trigger_opcodes(args: SimpleNamespace) -> int:
    """Report how often each trigger opcode appears -- a starting point for decoding them."""
    triggers = _load_triggers(args.file)
    if triggers is None:
        return 1

    try:
        histogram = triggers.opcode_histogram()
        unterminated = triggers.unterminated_trigger_ids()
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    total = sum(histogram.values())
    print(f"{args.file} -- {total} body record(s), {len(histogram)} distinct opcode(s)")
    if unterminated:
        print(f"  unterminated trigger(s): {unterminated}")
    print(f"{'Opcode':>7}  {'Count':>7}  {'Share':>7}")
    print("-" * 26)
    rows = histogram.most_common(args.limit) if args.limit else histogram.most_common()
    for opcode, count in rows:
        print(f"{opcode:>#7x}  {count:>7}  {100 * count / total:>6.2f}%")
    if args.limit and len(histogram) > args.limit:
        print(f"... ({len(histogram) - args.limit} more; raise --limit to see more)")
    return 0


# ============================================================================
# CLI COMMANDS — NPC ACTIVITY SEQUENCES (static/activity.flx)
# ============================================================================

def _load_activities(filepath: str) -> Optional[U9Activities]:
    """Open static/activity.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Activities.from_file(filepath)
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_activity_list(args: SimpleNamespace) -> int:
    """List activity sets with their record counts and names."""
    activities = _load_activities(args.file)
    if activities is None:
        return 1

    try:
        entries = activities.activities()
        incomplete = activities.incomplete_activity_ids()
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    shown = entries[: args.limit] if args.limit else entries
    print(f"{args.file} -- {len(entries)} activity set(s) of {activities.num_entries} slots")
    if incomplete:
        print(f"  entries that did not parse cleanly: {incomplete}")
    print(f"{'ID':>5}  {'Records':>7}  {'Steps':>5}  Names")
    print("-" * 72)
    for a in shown:
        steps = sum(len(r.steps) for r in a.records)
        names = ", ".join(a.names[:4])
        if len(a.names) > 4:
            names += ", ..."
        print(f"{a.activity_id:>5}  {len(a.records):>7}  {steps:>5}  {names}")
    if args.limit and len(entries) > args.limit:
        print(f"... ({len(entries) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_activity_show(args: SimpleNamespace) -> int:
    """Dump one activity set's records and steps."""
    activities = _load_activities(args.file)
    if activities is None:
        return 1

    try:
        activity = activities.activity(args.id)
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if activity is None:
        print(f"Activity {args.id} is an unused slot.")
        return 0

    print(f"{args.file} -- activity {activity.activity_id}")
    print(f"  {len(activity.records)} of {activity.declared_record_count} declared record(s), "
          f"{activity.payload_length}-byte payload")
    if activity.trailing_bytes:
        print(f"  WARNING: {activity.trailing_bytes} byte(s) left over after the last record")
    for record in activity.records:
        print(f"  [{record.ordinal}] {record.name}")
        if not record.terminated:
            print("       WARNING: no 0xFF step; the record runs to the end of the entry")
        for index, step in enumerate(record.steps):
            print(f"       {index:>2}  opcode {step.opcode:#04x}  {step.operands.hex(' ')}")
        if not record.steps:
            print("       (no steps)")
    print("  Opcodes 0x01/0x02 move between highway points; the other ten are not decoded.")
    return 0


def cmd_activity_opcodes(args: SimpleNamespace) -> int:
    """Report step opcode and activity name frequency across the archive."""
    activities = _load_activities(args.file)
    if activities is None:
        return 1

    try:
        opcodes = activities.opcode_histogram()
        names = activities.name_histogram()
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    total = sum(opcodes.values())
    print(f"{args.file} -- {total} step(s), {len(opcodes)} distinct opcode(s), "
          f"{len(names)} distinct name(s)")
    print(f"{'Opcode':>7}  {'Count':>7}  {'Share':>7}")
    print("-" * 26)
    for opcode, count in opcodes.most_common():
        print(f"{opcode:>#7x}  {count:>7}  {100 * count / total:>6.2f}%")
    print("")
    print(f"{'Count':>7}  Name")
    print("-" * 30)
    for name, count in names.most_common(args.limit or 15):
        print(f"{count:>7}  {name}")
    return 0


# ============================================================================
# CLI COMMANDS — NPC TABLE (runtime/NPC.FLX, and a savegame's live copy)
# ============================================================================

def _load_npcs(filepath: str, from_save: bool) -> Optional[U9Npcs]:
    """Open runtime/NPC.FLX, or the live array inside a savegame file."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        if from_save:
            return U9Npcs.from_process_data(filepath)
        return U9Npcs.from_file(filepath)
    except U9NpcError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_npc_list(args: SimpleNamespace) -> int:
    """List NPC records; the record index is also the activity set index."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1

    rows = list(npcs)
    if args.region is not None:
        rows = [n for n in rows if n.region == args.region]
    if args.npc_class is not None:
        rows = [n for n in rows if n.class_id == args.npc_class]
    if not args.all:
        rows = [n for n in rows if n.name]
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} NPC(s) of {len(npcs)} record(s)")
    print(f"{'Idx':>5}  {'Name':<24} {'G':>1}  {'Class':>5}  {'Region':>6}  "
          f"{'HP':>5}  {'Mana':>5}  Position")
    print("-" * 90)
    for n in shown:
        cls = "-" if not n.has_class else str(n.class_id)
        print(f"{n.index:>5}  {n.name:<24} {'F' if n.is_female else 'M'}  {cls:>5}  "
              f"{n.region:>6}  {n.health_max:>5}  {n.mana_max:>5}  "
              f"{n.x},{n.y},{n.z}")
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_npc_show(args: SimpleNamespace) -> int:
    """Print one NPC record's decoded fields."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1
    try:
        n = npcs.npc(args.index)
    except U9NpcError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"{args.file} -- NPC {n.index}")
    print(f"  Name        : {n.name!r}")
    print(f"  Gender      : {'female' if n.is_female else 'male'}")
    print(f"  Health      : {n.health_current} / {n.health_max}")
    print(f"  Mana        : {n.mana_current} / {n.mana_max}")
    print(f"  Class       : {n.class_id if n.has_class else 'none (0xFFFF)'}")
    print(f"  Combat value: {n.combat_value}")
    print(f"  Flags       : {n.flags:#010x}")
    print(f"  Region      : {n.region}")
    print(f"  Position    : {n.x}, {n.y}, {n.z}")
    print(f"  Scale       : {n.scale[0]}%, {n.scale[1]}%, {n.scale[2]}%")
    if n.has_pool_object:
        print(f"  Pool handle : {n.pool_handle} (element {n.pool_index} of the region object pool)")
    elif n.is_slot_used:
        print("  Pool handle : 1 -- slot allocated, no pool object yet")
    else:
        print("  Pool handle : 0 -- slot free / no world placement")
    print(f"  Record index {n.index} is also this NPC's activity set index.")
    print("  Undecoded bytes are available as U9Npc.raw.")
    return 0


def cmd_npc_classes(args: SimpleNamespace) -> int:
    """Group NPCs by class_id -- the grouping clusters by faction, not appearance."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1

    histogram = npcs.class_histogram()
    print(f"{args.file} -- {len(histogram)} distinct class_id value(s)")
    for class_id, count in histogram.most_common():
        label = "none (0xFFFF)" if class_id == NO_CLASS else str(class_id)
        members = [n.name for n in npcs.by_class(class_id) if n.name]
        preview = ", ".join(members[: args.members])
        if len(members) > args.members:
            preview += ", ..."
        print(f"  {label:>13}  x{count:<4} {preview}")
    return 0


def cmd_npc_csv(args: SimpleNamespace) -> int:
    """Export every NPC record to CSV: decoded fields, then the whole record as hex."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1

    rows = list(npcs)
    if not args.all:
        rows = [n for n in rows if n.name]

    out_path = args.output or f"{Path(args.file).stem}_npcs.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    header = [
        "index", "name", "gender", "sex",
        "health_current", "health_max", "health_max2",
        "mana_current", "mana_max", "mana_max2",
        "class_id", "flags", "combat_value",
        "region", "x", "y", "z",
        "scale_x", "scale_y", "scale_z",
        "pool_handle", "pool_index",
        # Undecoded but genuinely varying; kept as named columns so they can be
        # correlated without re-slicing the raw bytes.
        "unk_0x4e", "unk_0x56", "unk_0xb0", "unk_0xc4", "unk_0xc8",
        "raw_hex",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for n in rows:
            writer.writerow([
                n.index, n.name, n.gender, "female" if n.is_female else "male",
                n.health_current, n.health_max, n.health_max2,
                n.mana_current, n.mana_max, n.mana_max2,
                n.class_id if n.has_class else "", f"{n.flags:#010x}", n.combat_value,
                n.region, n.x, n.y, n.z,
                n.scale[0], n.scale[1], n.scale[2],
                n.pool_handle, n.pool_index,
                struct.unpack_from("<H", n.raw, 0x4E)[0],
                struct.unpack_from("<H", n.raw, 0x56)[0],
                struct.unpack_from("<I", n.raw, 0xB0)[0],
                struct.unpack_from("<H", n.raw, 0xC4)[0],
                n.raw[0xC8],
                n.raw.hex(),
            ])

    print(f"{args.file} -- wrote {len(rows)} NPC row(s) -> {out_path}")
    print(f"  {len(header)} columns; raw_hex carries the full {len(rows[0].raw) if rows else 0}-byte record")
    if not args.all:
        blank = len(npcs) - len(rows)
        if blank:
            print(f"  {blank} unnamed/blank slot(s) omitted; pass --all to include them")
    return 0


def cmd_npc_diff(args: SimpleNamespace) -> int:
    """Compare a shipped NPC table against a savegame's copy, field by field."""
    left = _load_npcs(args.file, False)
    right = _load_npcs(args.save_file, True)
    if left is None or right is None:
        return 1

    print(f"{args.file}\n{args.save_file}")
    print(f"  {len(left)} authored record(s) vs {len(right)} live record(s)")
    if len(right) > len(left):
        spawned = [n.name for n in list(right)[len(left):] if n.name]
        print(f"  {len(right) - len(left)} extra live slot(s), {len(spawned)} named "
              f"(runtime-spawned): {', '.join(spawned[:8])}"
              + (", ..." if len(spawned) > 8 else ""))

    changed = left.changed_fields(right)
    print(f"  {len(changed)} byte offset(s) differ across the shared records:")
    for offset, count in changed.items():
        print(f"      {offset:#06x}  {count} NPC(s)")

    moved = [
        (a, b) for a, b in zip(left, right)
        if (a.region, a.x, a.y, a.z) != (b.region, b.x, b.y, b.z)
    ]
    print(f"  {len(moved)} NPC(s) moved:")
    for a, b in moved[: args.limit or len(moved)]:
        print(f"      {a.name:<16} region {a.region} {a.x},{a.y},{a.z}"
              f"  ->  region {b.region} {b.x},{b.y},{b.z}")
    return 0


# ============================================================================
# CLI COMMANDS — TEXTURE METADATA (static/sdInfo*.flx)
# ============================================================================

def _load_sdinfo(filepath: str) -> Optional[U9SdInfo]:
    """Open a static/sdInfo*.flx table, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9SdInfo.from_file(filepath)
    except U9SdInfoError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_sdinfo_list(args: SimpleNamespace) -> int:
    """List texture metadata records: dimensions, frames and mip levels."""
    info = _load_sdinfo(args.file)
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
        print(f"{r.index:>6}  {f'{r.width}x{r.height}':<11}  "
              f"{f'{r.max_width}x{r.max_height}':<11}  {r.frame_count:>6}  "
              f"{r.mip_levels:>4}  {', '.join(notes)}")
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_sdinfo_show(args: SimpleNamespace) -> int:
    """Print one texture's metadata record, decoded fields and raw dwords."""
    info = _load_sdinfo(args.file)
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
    print(f"  log2 dims   : {r.log2_width}, {r.log2_height}"
          f"{'' if r.is_power_of_two else '  (dimensions are not powers of two)'}")
    print(f"  Flags       : mip {r.flag:#06x}, frame {r.frame_flag:#06x}")
    print("  Raw dwords  : " + " ".join(f"{v:#010x}" for v in r.fields))
    print("  Dwords 0, 3, 4, 7 and 8 are not decoded.")
    return 0


def cmd_sdinfo_verify(args: SimpleNamespace) -> int:
    """Cross-check a metadata table against its partner texture archive."""
    info = _load_sdinfo(args.file)
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
    for key, label in (("max_dims", "max dimensions"),
                       ("frame_count", "frame count"),
                       ("mip_levels", "mip levels")):
        n = counts[key]
        flag = "" if n == total else "   <-- MISMATCH"
        print(f"  {label:<15}: {n}/{total} ({100 * n / total if total else 0:.1f}%){flag}")
    return 0 if total and all(counts[k] == total for k in ("max_dims", "frame_count", "mip_levels")) else 1


# ============================================================================
# CLI COMMANDS — TEXT ARCHIVES (static/text.flx, static/misctext.flx)
# ============================================================================

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
            print(f"{args.file} -- {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} "
                  f"of {len(text)} used")
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
        print(f"{args.file} -- no BEGIN FILE markers; this archive is a flat list "
              f"of {len(text)} strings")
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
            writer.writerow([e.index, owner.get(e.index, ""), int(e.is_file_marker), e.text])
    print(f"{args.file} -- wrote {len(entries)} row(s) -> {out_path}")
    return 0


# ============================================================================
# CLI COMMANDS — STATIC WORLD GEOMETRY (static/fixed.%d)
# ============================================================================

def _load_fixed(filepath: str) -> Optional[U9Fixed]:
    """Open a static/fixed.<region> file, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Fixed.from_file(filepath)
    except U9FixedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_fixed_info(args: SimpleNamespace) -> int:
    """Summarize one static region: chunk grid, pages and object totals."""
    region = _load_fixed(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    pages = sum(len(c.pages) for c in chunks)
    objects = sum(len(c.objects) for c in chunks)
    chained = sum(1 for c in chunks if len(c.pages) > 1)

    print(f"{args.file} -- {region.width}x{region.height} chunk region")
    print(f"  Header          : {region.header_size} bytes (0x20 + 4*w*h)")
    print(f"  Payload         : {region.payload_size} bytes "
          f"(watermark {region.declared_payload_size})")
    print(f"  Populated chunks: {len(chunks)} of {region.num_chunks}")
    print(f"  Pages           : {pages} ({chained} chunk(s) span more than one)")
    print(f"  Objects         : {objects}")
    print("  Chunk positions come from each page's base, not the table order.")
    return 0


def cmd_fixed_chunks(args: SimpleNamespace) -> int:
    """List populated chunks with their grid position and object counts."""
    region = _load_fixed(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    if args.by_grid:
        chunks.sort(key=lambda c: (c.chunk_y, c.chunk_x))
    shown = chunks[: args.limit] if args.limit else chunks

    print(f"{args.file} -- {len(chunks)} populated chunk(s) of {region.num_chunks}")
    print(f"{'Slot':>5}  {'Grid':<9}  {'Base (x,y)':<15}  {'Pages':>5}  {'Objects':>7}")
    print("-" * 54)
    for c in shown:
        print(f"{c.table_index:>5}  {f'{c.chunk_x},{c.chunk_y}':<9}  "
              f"{f'{c.base_x},{c.base_y}':<15}  {len(c.pages):>5}  {len(c.objects):>7}")
    if args.limit and len(chunks) > args.limit:
        print(f"... ({len(chunks) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_fixed_objects(args: SimpleNamespace) -> int:
    """List immovable objects, optionally restricted to one chunk."""
    region = _load_fixed(args.file)
    if region is None:
        return 1

    if args.chunk is not None:
        try:
            cx, cy = (int(v) for v in args.chunk.split(",", 1))
        except ValueError:
            print(f"ERROR: --chunk expects 'X,Y', got {args.chunk!r}", file=sys.stderr)
            return 1
        try:
            chunk = region.chunk(cx, cy)
        except U9FixedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if chunk is None:
            print(f"Chunk ({cx}, {cy}) holds no pages.")
            return 0
        chunks = [chunk]
    else:
        chunks = region.chunks()

    names = _load_typenames(args.typenames)
    rows = [(c, o) for c in chunks for o in c.objects]
    if args.type is not None:
        rows = [(c, o) for c, o in rows if o.type_index == args.type]
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} object(s)")
    header = (f"{'Offset':>8}  {'Chunk':<7}  {'World (x,y,z)':<20}  {'Type':>5}  "
              f"{'Flags':>10}")
    if names:
        header += "  Name"
    print(header)
    print("-" * (len(header) + 8))
    for c, o in shown:
        line = (f"{o.offset:>#8x}  {f'{c.chunk_x},{c.chunk_y}':<7}  "
                f"{f'{o.world_x},{o.world_y},{o.z}':<20}  {o.type_index:>5}  "
                f"{o.flags:>#10x}")
        if names:
            line += f"  {names.name_for(o.type_index) or ''}"
        print(line)
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_fixed_types(args: SimpleNamespace) -> int:
    """Report which object types a static region uses, most common first."""
    region = _load_fixed(args.file)
    if region is None:
        return 1
    names = _load_typenames(args.typenames)
    histogram = Counter(o.type_index for o in region.objects())
    total = sum(histogram.values())
    print(f"{args.file} -- {total} object(s), {len(histogram)} distinct type(s)")
    print(f"{'Type':>6}  {'Count':>7}  {'Share':>7}  Name")
    print("-" * 46)
    for type_index, count in histogram.most_common(args.limit or None):
        label = (names.name_for(type_index) or "") if names else ""
        print(f"{type_index:>6}  {count:>7}  {100 * count / total:>6.2f}%  {label}")
    if args.limit and len(histogram) > args.limit:
        print(f"... ({len(histogram) - args.limit} more; raise --limit to see more)")
    return 0


# ============================================================================
# CLI COMMANDS -- TERRAIN HEIGHT MAP (static/terrain.%d)
# ============================================================================

def _load_terrain(filepath: str) -> Optional[U9Terrain]:
    """Open a static/terrain.<region> file, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Terrain.from_file(filepath)
    except U9TerrainError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_terrain_info(args: SimpleNamespace) -> int:
    """Summarize one region height map: grid, chunk sharing and height range."""
    region = _load_terrain(args.file)
    if region is None:
        return 1

    print(f"{args.file} -- {region.name or '(unnamed)'}")
    if region.is_empty:
        print("  Unused region slot: a bare header, no tile grid and no chunks.")
        print(f"  Header still declares {region.declared_chunk_count} chunk(s).")
        return 0

    low, high = region.height_range()
    unused = len(region.unused_chunks())
    shared = region.shared_tile_count()
    print(f"  Points          : {region.width}x{region.height}")
    print(f"  World coords    : {region.world_width}x{region.world_height}")
    print(f"  Tiles           : {region.tile_width}x{region.tile_height} "
          f"({region.tile_count} total, {shared} sharing a chunk)")
    print(f"  Chunks          : {region.chunk_count} "
          f"(declared {region.declared_chunk_count}, {unused} referenced by no tile)")
    print(f"  Height range    : {low}..{high}")
    if region.slack_bytes:
        print(f"  Trailing slack  : {region.slack_bytes} bytes past the last chunk")
    return 0


def cmd_terrain_tiles(args: SimpleNamespace) -> int:
    """Print the tile grid as the chunk index each tile refers to."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, no tile grid.")
        return 0

    print(f"{args.file} -- {region.tile_width}x{region.tile_height} tiles "
          f"over {region.chunk_count} chunk(s)")
    width = max(3, len(str(max(region.tiles))))
    for tile_y in range(region.tile_height):
        base = tile_y * region.tile_width
        row = region.tiles[base : base + region.tile_width]
        print(f"{tile_y:>4}  " + " ".join(f"{v:>{width}}" for v in row))
    return 0


def cmd_terrain_chunk(args: SimpleNamespace) -> int:
    """Dump one chunk's 16x16 points, as height, texture or frame."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    try:
        if args.tile is not None:
            try:
                tile_x, tile_y = (int(v) for v in args.tile.split(",", 1))
            except ValueError:
                print(f"ERROR: --tile expects 'X,Y', got {args.tile!r}", file=sys.stderr)
                return 1
            index = region.tile(tile_x, tile_y)
        else:
            index = args.index or 0
        chunk = region.chunk(index)
    except U9TerrainError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    field = args.field
    pick = {
        "height": lambda p: p.height,
        "texture": lambda p: p.texture,
        "frame": lambda p: p.frame,
        "hole": lambda p: int(p.is_hole),
    }[field]
    points = chunk.points()
    values = [pick(p) for p in points]
    holes = sum(1 for p in points if p.is_hole)

    print(f"{args.file} -- chunk {index}, {field} "
          f"({'flat' if chunk.is_flat else 'varied'}, {holes} hole point(s))")
    width = max(2, len(str(max(values))))
    for y in range(16):
        row = values[y * 16 : (y + 1) * 16]
        print(f"{y:>4}  " + " ".join(f"{v:>{width}}" for v in row))
    return 0


def cmd_terrain_textures(args: SimpleNamespace) -> int:
    """Report which ground textures a region paints with, most used first."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, no chunks.")
        return 0

    histogram: Counter = Counter()
    for chunk in region.chunks():
        histogram.update(chunk.textures())
    total = sum(histogram.values())

    info = None
    if args.sdinfo:
        info = _load_sdinfo(args.sdinfo)
        if info is None:
            return 1
        records = {r.index: r for r in info.records()}

    print(f"{args.file} -- {total} point(s), {len(histogram)} distinct texture(s)")
    header = f"{'Texture':>8}  {'Points':>9}  {'Share':>7}"
    if info:
        header += f"  {'Size':>9}  {'Frames':>6}"
    print(header)
    print("-" * len(header))
    for texture, count in histogram.most_common(args.limit or None):
        line = f"{texture:>8}  {count:>9}  {100 * count / total:>6.2f}%"
        if info:
            record = records.get(texture)
            line += (f"  {f'{record.width}x{record.height}':>9}  {record.frame_count:>6}"
                     if record else f"  {'--':>9}  {'--':>6}")
        print(line)
    if args.limit and len(histogram) > args.limit:
        print(f"... ({len(histogram) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_terrain_heightmap(args: SimpleNamespace) -> int:
    """Render a region's height map to a greyscale PNG."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, nothing to render.")
        return 1

    rows = region.heightmap()
    low, high = region.height_range()
    span = max(1, high - low)
    image = Image.new("L", (region.width, region.height))
    image.putdata([(value - low) * 255 // span for row in rows for value in row])
    if args.scale and args.scale > 1:
        image = image.resize(
            (region.width * args.scale, region.height * args.scale), Image.NEAREST
        )

    out_path = args.output or f"{Path(args.file).name.replace('.', '_')}_height.png"
    directory = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(directory, exist_ok=True)
    image.save(out_path)
    print(f"{args.file} -- {region.width}x{region.height}, heights {low}..{high} "
          f"-> {out_path}")
    return 0


def cmd_terrain_export(args: SimpleNamespace) -> int:
    """Export every point of a region to CSV."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, nothing to export.")
        return 1

    out_path = args.output or f"{Path(args.file).name.replace('.', '_')}_points.csv"
    directory = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(directory, exist_ok=True)
    written = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "x", "y", "tile_x", "tile_y", "chunk", "height", "hole",
            "split", "frame", "texture", "flag13", "flag14", "raw",
        ])
        for tile_y in range(region.tile_height):
            for tile_x in range(region.tile_width):
                index = region.tile(tile_x, tile_y)
                for point in region.chunk(index).points():
                    flag13, flag14 = point.unknown_flags
                    writer.writerow([
                        tile_x * 16 + point.x, tile_y * 16 + point.y,
                        tile_x, tile_y, index, point.height, int(point.is_hole),
                        int(point.is_split), point.frame, point.texture,
                        int(flag13), int(flag14), point.value,
                    ])
                    written += 1
    print(f"{args.file} -- wrote {written} point(s) -> {out_path}")
    return 0


# ============================================================================
# CLI COMMANDS -- BOOKS AND SIGNS (static/BOOKS-EN.FLX)
# ============================================================================

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

    print(f"{args.file} -- {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} "
          f"of {books.num_entries} slots")
    print(f"{'Id':>5}  {'Bytes':>7}  {'Pages':>5}  Name")
    print("-" * 60)
    for book in shown:
        note = "  [embedded document]" if book.is_embedded_document else ""
        print(f"{book.book_id:>5}  {len(book):>7}  {len(book.pages):>5}  {book.name}{note}")
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
            snippet = ("..." if start else "") + text[start : at + len(needle) + 40].strip()
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
        writer.writerow(["id", "index", "name", "bytes", "pages", "fonts",
                         "is_embedded_document", "text"])
        for book in rows:
            writer.writerow([
                book.book_id, book.index, book.name, len(book), len(book.pages),
                " ".join(str(v) for v in book.fonts),
                int(book.is_embedded_document),
                "" if book.is_embedded_document else book.text,
            ])
    print(f"{args.file} -- wrote {len(rows)} row(s) -> {out_path}")
    return 0


# ============================================================================
# Typer command wrappers
# ============================================================================

@u9_app.command("flx-list")
def flx_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
) -> None:
    """List an Ultima 9 FLX archive's directory entries."""
    raise SystemExit(cmd_flx_list(SimpleNamespace(file=file)))


@u9_app.command("flx-extract")
def flx_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
    index: Annotated[int, typer.Argument(help="Entry index to extract")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract one entry from an Ultima 9 FLX archive."""
    raise SystemExit(cmd_flx_extract(SimpleNamespace(file=file, index=index, output=output)))


@u9_app.command("flx-extract-all")
def flx_extract_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: <file>_entries/)"),
    ] = None,
) -> None:
    """Extract every used entry from an Ultima 9 FLX archive."""
    raise SystemExit(cmd_flx_extract_all(SimpleNamespace(file=file, output=output)))


@u9_app.command("typename-dump")
def typename_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/TYPENAME.FLX")],
) -> None:
    """Dump type-ID -> display-name pairs from TYPENAME.FLX."""
    raise SystemExit(cmd_typename_dump(SimpleNamespace(file=file)))


@u9_app.command("sound-list")
def sound_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 sound/*.flx file")],
) -> None:
    """List sound record headers (id, description, format, encoding) in a sound archive."""
    raise SystemExit(cmd_sound_list(SimpleNamespace(file=file)))


@u9_app.command("sound-extract-pcm")
def sound_extract_pcm_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 sound/*.flx file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: <file>_wav/)"),
    ] = None,
) -> None:
    """Extract every PCM-encoded entry in a sound archive as a playable WAV."""
    raise SystemExit(cmd_sound_extract_pcm(SimpleNamespace(file=file, output=output)))


@u9_app.command("sound-extract")
def sound_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 sound/*.flx file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: <file>_wav/)"),
    ] = None,
) -> None:
    """Extract every entry this project can decode (PCM, mono/stereo ADPCM, mono EA MicroTalk) as WAV."""
    raise SystemExit(cmd_sound_extract(SimpleNamespace(file=file, output=output)))


@u9_app.command("model-info")
def model_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Model ID (0-7999) to inspect")],
    types: Annotated[
        Optional[str],
        typer.Option("--types", help="Path to static/TYPES.DAT (with --typenames, shows possible name(s))"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option("--typenames", help="Path to static/TYPENAME.FLX (with --types, shows possible name(s))"),
    ] = None,
) -> None:
    """Print a model's limb/LOD/material/texture summary."""
    raise SystemExit(
        cmd_model_info(SimpleNamespace(file=file, model_id=model_id, types=types, typenames=typenames))
    )


@u9_app.command("model-export")
def model_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Model ID (0-7999) to export")],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--textures",
            help="Path to a texture archive -- prefer bitmap16.flx or bitmapsh.flx "
            "(bitmapC.flx is mostly an unsupported compressed format, see titan.u9.texture)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types", help="Path to static/TYPES.DAT (with --typenames, names the output folder/files)"
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames", help="Path to static/TYPENAME.FLX (with --types, names the output folder/files)"
        ),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[str, typer.Option("-f", "--format", help="obj, stl, or both")] = "obj",
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: model_<id>[_<name>]/)"),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            "--preview/--no-preview",
            help="Also render a preview.png (requires pyvista; needs a textured OBJ, camera auto-fit)",
        ),
    ] = True,
) -> None:
    """Export one model to OBJ+MTL(+PNG textures) and/or STL."""
    raise SystemExit(
        cmd_model_export(
            SimpleNamespace(
                file=file, model_id=model_id, textures=textures, palette=palette, types=types,
                typenames=typenames, lod=lod, format=fmt, output=output, preview=preview,
            )
        )
    )


@u9_app.command("model-export-all")
def model_export_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--textures",
            help="Path to a texture archive -- prefer bitmap16.flx or bitmapsh.flx "
            "(bitmapC.flx is mostly an unsupported compressed format, see titan.u9.texture)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types", help="Path to static/TYPES.DAT (with --typenames, names each output folder/files)"
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames", help="Path to static/TYPENAME.FLX (with --types, names each output folder/files)"
        ),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[str, typer.Option("-f", "--format", help="obj, stl, or both")] = "obj",
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: model_export/)"),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            "--preview/--no-preview",
            help="Also render a preview.png for each model (requires pyvista)",
        ),
    ] = True,
) -> None:
    """Export every used model in sappear.flx (one subfolder each), same options as model-export."""
    raise SystemExit(
        cmd_model_export_all(
            SimpleNamespace(
                file=file, textures=textures, palette=palette, types=types,
                typenames=typenames, lod=lod, format=fmt, output=output, preview=preview,
            )
        )
    )


@u9_app.command("icon-list")
def icon_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        str,
        typer.Argument(help="Path to a texture archive, e.g. bitmap16.flx or bitmapsh.flx"),
    ],
    limit: Annotated[int, typer.Option("--limit", help="Max rows to print (0 = unlimited)")] = 200,
) -> None:
    """List candidate 2D UI icon entries (see titan.u9.icon) not referenced by any 3D model material."""
    raise SystemExit(cmd_icon_list(SimpleNamespace(file=file, textures=textures, limit=limit)))


@u9_app.command("icon-export")
def icon_export_cmd(
    textures: Annotated[
        str,
        typer.Argument(help="Path to a texture archive, e.g. bitmap16.flx or bitmapsh.flx"),
    ],
    entry_id: Annotated[int, typer.Argument(help="Entry ID (0-7999) to export")],
    frame: Annotated[int, typer.Option("--frame", help="Frame index within the entry")] = 0,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: current directory)"),
    ] = None,
) -> None:
    """Export one texture archive entry to PNG, regardless of whether any 3D model references it."""
    raise SystemExit(
        cmd_icon_export(SimpleNamespace(textures=textures, entry_id=entry_id, frame=frame, palette=palette, output=output))
    )


@u9_app.command("icon-export-all")
def icon_export_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        str,
        typer.Argument(help="Path to a texture archive, e.g. bitmap16.flx or bitmapsh.flx"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory (default: icon_export/)"),
    ] = None,
) -> None:
    """Batch-export every candidate 2D UI icon (see titan.u9.icon) not referenced by any 3D model."""
    raise SystemExit(
        cmd_icon_export_all(SimpleNamespace(file=file, textures=textures, palette=palette, output=output))
    )


@u9_app.command("nonfixed-info")
def nonfixed_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")],
) -> None:
    """Summarize a U9 runtime region: chunk grid, pages, entities, triggers."""
    raise SystemExit(cmd_nonfixed_info(SimpleNamespace(file=file)))


@u9_app.command("nonfixed-chunks")
def nonfixed_chunks_cmd(
    file: Annotated[str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")],
) -> None:
    """List every populated chunk in a U9 runtime region with its counts."""
    raise SystemExit(cmd_nonfixed_chunks(SimpleNamespace(file=file)))


@u9_app.command("nonfixed-entities")
def nonfixed_entities_cmd(
    file: Annotated[str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")],
    chunk: Annotated[
        Optional[str], typer.Option("-c", "--chunk", help="Restrict to one chunk, as 'X,Y'"),
    ] = None,
    typenames: Annotated[
        Optional[str], typer.Option("-t", "--typenames", help="Path to static/TYPENAME.FLX for object names"),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List the dynamic objects stored in a U9 runtime region."""
    raise SystemExit(
        cmd_nonfixed_entities(SimpleNamespace(file=file, chunk=chunk, typenames=typenames, limit=limit))
    )


@u9_app.command("nonfixed-diff")
def nonfixed_diff_cmd(
    left: Annotated[str, typer.Argument(help="First runtime/nonfixed.<region> file")],
    right: Annotated[str, typer.Argument(help="Second runtime/nonfixed.<region> file")],
    typenames: Annotated[
        Optional[str], typer.Option("-t", "--typenames", help="Path to static/TYPENAME.FLX for object names"),
    ] = None,
) -> None:
    """Compare two U9 runtime regions entity by entity (e.g. patched vs original)."""
    raise SystemExit(cmd_nonfixed_diff(SimpleNamespace(left=left, right=right, typenames=typenames)))


@u9_app.command("highway-info")
def highway_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
) -> None:
    """Summarize the U9 NPC navigation graph: points, routes, connectivity."""
    raise SystemExit(cmd_highway_info(SimpleNamespace(file=file)))


@u9_app.command("highway-points")
def highway_points_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
    id: Annotated[
        Optional[int], typer.Option("-i", "--id", help="Show only the point with this trigger ID"),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 highway navigation points and their world positions."""
    raise SystemExit(cmd_highway_points(SimpleNamespace(file=file, id=id, limit=limit)))


@u9_app.command("highway-routes")
def highway_routes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
    id: Annotated[
        Optional[int], typer.Option("-i", "--id", help="Only routes visiting this trigger ID"),
    ] = None,
    paths: Annotated[
        bool, typer.Option("-p", "--paths", help="Print each route's full node path"),
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum routes to print"),
    ] = None,
) -> None:
    """List the precomputed routes through the U9 highway graph."""
    raise SystemExit(cmd_highway_routes(SimpleNamespace(file=file, id=id, paths=paths, limit=limit)))


@u9_app.command("trigger-list")
def trigger_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    all: Annotated[
        bool, typer.Option("-a", "--all", help="Include empty triggers"),
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 trigger scripts; the trigger ID is the FLX entry index."""
    raise SystemExit(cmd_trigger_list(SimpleNamespace(file=file, all=all, limit=limit)))


@u9_app.command("trigger-show")
def trigger_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    id: Annotated[int, typer.Argument(help="Trigger ID, as carried by a runtime entity")],
) -> None:
    """Dump one U9 trigger script's records."""
    raise SystemExit(cmd_trigger_show(SimpleNamespace(file=file, id=id)))


@u9_app.command("trigger-opcodes")
def trigger_opcodes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum opcodes to print"),
    ] = None,
) -> None:
    """Report trigger opcode frequency across the whole archive."""
    raise SystemExit(cmd_trigger_opcodes(SimpleNamespace(file=file, limit=limit)))


@u9_app.command("activity-list")
def activity_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 NPC activity sets and the named sequences they hold."""
    raise SystemExit(cmd_activity_list(SimpleNamespace(file=file, limit=limit)))


@u9_app.command("activity-show")
def activity_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    id: Annotated[int, typer.Argument(help="Activity set ID (the FLX entry index)")],
) -> None:
    """Dump one U9 activity set's named records and their steps."""
    raise SystemExit(cmd_activity_show(SimpleNamespace(file=file, id=id)))


@u9_app.command("activity-opcodes")
def activity_opcodes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum names to print"),
    ] = None,
) -> None:
    """Report U9 activity step-opcode and sequence-name frequency."""
    raise SystemExit(cmd_activity_opcodes(SimpleNamespace(file=file, limit=limit)))


@u9_app.command("npc-list")
def npc_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save")],
    save: Annotated[
        bool, typer.Option("-s", "--save", help="Read the live array from a savegame processes.dat / .sav"),
    ] = False,
    region: Annotated[
        Optional[int], typer.Option("-r", "--region", help="Only NPCs in this region"),
    ] = None,
    npc_class: Annotated[
        Optional[int], typer.Option("-c", "--class", help="Only NPCs with this class_id"),
    ] = None,
    all: Annotated[bool, typer.Option("-a", "--all", help="Include unnamed/empty slots")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")] = None,
) -> None:
    """List U9 NPC records; the record index is also the activity set index."""
    raise SystemExit(cmd_npc_list(SimpleNamespace(
        file=file, save=save, region=region, npc_class=npc_class, all=all, limit=limit)))


@u9_app.command("npc-show")
def npc_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save")],
    index: Annotated[int, typer.Argument(help="NPC record index")],
    save: Annotated[
        bool, typer.Option("-s", "--save", help="Read the live array from a savegame processes.dat / .sav"),
    ] = False,
) -> None:
    """Print one U9 NPC record's decoded fields."""
    raise SystemExit(cmd_npc_show(SimpleNamespace(file=file, index=index, save=save)))


@u9_app.command("npc-classes")
def npc_classes_cmd(
    file: Annotated[str, typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save")],
    save: Annotated[
        bool, typer.Option("-s", "--save", help="Read the live array from a savegame processes.dat / .sav"),
    ] = False,
    members: Annotated[
        int, typer.Option("-m", "--members", help="Member names to preview per class"),
    ] = 8,
) -> None:
    """Group U9 NPCs by class_id and preview each group's members."""
    raise SystemExit(cmd_npc_classes(SimpleNamespace(file=file, save=save, members=members)))


@u9_app.command("npc-diff")
def npc_diff_cmd(
    file: Annotated[str, typer.Argument(help="Path to the shipped runtime/NPC.FLX")],
    save_file: Annotated[str, typer.Argument(help="Path to a savegame processes.dat or u9game*.sav")],
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum moved NPCs to print")] = None,
) -> None:
    """Compare the shipped U9 NPC table against a savegame's live copy."""
    raise SystemExit(cmd_npc_diff(SimpleNamespace(file=file, save_file=save_file, limit=limit)))


@u9_app.command("npc-csv")
def npc_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output CSV path (default: <file>_npcs.csv)"),
    ] = None,
    save: Annotated[
        bool, typer.Option("-s", "--save", help="Read the live array from a savegame processes.dat / .sav"),
    ] = False,
    all: Annotated[bool, typer.Option("-a", "--all", help="Include unnamed/blank slots")] = False,
) -> None:
    """Export every U9 NPC record to CSV, decoded fields plus the raw record."""
    raise SystemExit(cmd_npc_csv(SimpleNamespace(file=file, output=output, save=save, all=all)))


@u9_app.command("sdinfo-list")
def sdinfo_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sdInfo.flx, sdInfo16.flx or sdInfoC.flx")],
    animated: Annotated[
        bool, typer.Option("-a", "--animated", help="Only textures with more than one frame"),
    ] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")] = None,
) -> None:
    """List U9 texture metadata: dimensions, frame count and mip levels."""
    raise SystemExit(cmd_sdinfo_list(SimpleNamespace(file=file, animated=animated, limit=limit)))


@u9_app.command("sdinfo-show")
def sdinfo_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/sdInfo*.flx table")],
    index: Annotated[int, typer.Argument(help="Texture index -- the same index as in the bitmap archive")],
) -> None:
    """Print one U9 texture's metadata record."""
    raise SystemExit(cmd_sdinfo_show(SimpleNamespace(file=file, index=index)))


@u9_app.command("sdinfo-verify")
def sdinfo_verify_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/sdInfo*.flx table")],
    textures: Annotated[str, typer.Argument(help="Path to its partner bitmap*.flx archive")],
) -> None:
    """Cross-check a U9 texture metadata table against its bitmap archive."""
    raise SystemExit(cmd_sdinfo_verify(SimpleNamespace(file=file, textures=textures)))


@u9_app.command("text-list")
def text_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.flx or static/misctext.flx")],
    block: Annotated[
        Optional[str], typer.Option("-b", "--block", help="Only one source block, by name (e.g. Raven)"),
    ] = None,
    markers: Annotated[bool, typer.Option("-m", "--markers", help="Include BEGIN FILE markers")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum lines to print")] = None,
) -> None:
    """Print strings from a U9 text archive."""
    raise SystemExit(cmd_text_list(SimpleNamespace(file=file, block=block, markers=markers, limit=limit)))


@u9_app.command("text-blocks")
def text_blocks_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.flx")],
    by_size: Annotated[bool, typer.Option("-s", "--by-size", help="Order by line count, largest first")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum blocks to print")] = None,
) -> None:
    """List the source-file blocks in a U9 text archive."""
    raise SystemExit(cmd_text_blocks(SimpleNamespace(file=file, by_size=by_size, limit=limit)))


@u9_app.command("text-search")
def text_search_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.flx or static/misctext.flx")],
    needle: Annotated[str, typer.Argument(help="Substring to look for")],
    case_sensitive: Annotated[bool, typer.Option("-c", "--case-sensitive", help="Match case exactly")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum matches to print")] = None,
) -> None:
    """Search a U9 text archive, showing which block each match belongs to."""
    raise SystemExit(cmd_text_search(SimpleNamespace(
        file=file, needle=needle, case_sensitive=case_sensitive, limit=limit)))


@u9_app.command("text-export")
def text_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/text.flx or static/misctext.flx")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output CSV path (default: <file>_text.csv)"),
    ] = None,
) -> None:
    """Export a U9 text archive to CSV."""
    raise SystemExit(cmd_text_export(SimpleNamespace(file=file, output=output)))


@u9_app.command("fixed-info")
def fixed_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
) -> None:
    """Summarize a U9 static region: chunk grid, pages and object totals."""
    raise SystemExit(cmd_fixed_info(SimpleNamespace(file=file)))


@u9_app.command("fixed-chunks")
def fixed_chunks_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    by_grid: Annotated[bool, typer.Option("-g", "--by-grid", help="Order by grid position, not table slot")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")] = None,
) -> None:
    """List the populated chunks in a U9 static region."""
    raise SystemExit(cmd_fixed_chunks(SimpleNamespace(file=file, by_grid=by_grid, limit=limit)))


@u9_app.command("fixed-objects")
def fixed_objects_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    chunk: Annotated[Optional[str], typer.Option("-c", "--chunk", help="Restrict to one chunk, as 'X,Y'")] = None,
    type: Annotated[Optional[int], typer.Option("-t", "--type", help="Only objects of this type index")] = None,
    typenames: Annotated[
        Optional[str], typer.Option("--typenames", help="Path to static/TYPENAME.FLX for object names"),
    ] = None,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")] = None,
) -> None:
    """List the immovable objects in a U9 static region."""
    raise SystemExit(cmd_fixed_objects(SimpleNamespace(
        file=file, chunk=chunk, type=type, typenames=typenames, limit=limit)))


@u9_app.command("fixed-types")
def fixed_types_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    typenames: Annotated[
        Optional[str], typer.Option("--typenames", help="Path to static/TYPENAME.FLX for object names"),
    ] = None,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum types to print")] = None,
) -> None:
    """Report which object types a U9 static region uses."""
    raise SystemExit(cmd_fixed_types(SimpleNamespace(file=file, typenames=typenames, limit=limit)))


@u9_app.command("terrain-info")
def terrain_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
) -> None:
    """Summarize a U9 region height map."""
    raise SystemExit(cmd_terrain_info(SimpleNamespace(file=file)))


@u9_app.command("terrain-tiles")
def terrain_tiles_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
) -> None:
    """Print a U9 region's tile grid as chunk indices."""
    raise SystemExit(cmd_terrain_tiles(SimpleNamespace(file=file)))


@u9_app.command("terrain-chunk")
def terrain_chunk_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    index: Annotated[Optional[int], typer.Option("-i", "--index", help="Chunk index to dump")] = None,
    tile: Annotated[
        Optional[str], typer.Option("-t", "--tile", help="Dump the chunk a tile uses, as 'X,Y'"),
    ] = None,
    field: Annotated[
        str, typer.Option("-f", "--field", help="Which field to show: height, texture, frame or hole"),
    ] = "height",
) -> None:
    """Dump one 16x16 chunk of a U9 region height map."""
    if field not in ("height", "texture", "frame", "hole"):
        print(f"ERROR: --field must be height, texture, frame or hole, got {field!r}",
              file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(cmd_terrain_chunk(SimpleNamespace(
        file=file, index=index, tile=tile, field=field)))


@u9_app.command("terrain-textures")
def terrain_textures_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    sdinfo: Annotated[
        Optional[str], typer.Option("--sdinfo", help="Path to a matching static/sdInfo*.flx for sizes"),
    ] = None,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum textures to print")] = None,
) -> None:
    """Report which ground textures a U9 region paints with."""
    raise SystemExit(cmd_terrain_textures(SimpleNamespace(file=file, sdinfo=sdinfo, limit=limit)))


@u9_app.command("terrain-heightmap")
def terrain_heightmap_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    scale: Annotated[int, typer.Option("-s", "--scale", help="Nearest-neighbour magnification")] = 1,
) -> None:
    """Render a U9 region height map to a greyscale PNG."""
    raise SystemExit(cmd_terrain_heightmap(SimpleNamespace(file=file, output=output, scale=scale)))


@u9_app.command("terrain-export")
def terrain_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output CSV path"),
    ] = None,
) -> None:
    """Export every point of a U9 region height map to CSV."""
    raise SystemExit(cmd_terrain_export(SimpleNamespace(file=file, output=output)))


@u9_app.command("books-list")
def books_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    by_size: Annotated[bool, typer.Option("-s", "--by-size", help="Order by body size, largest first")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")] = None,
) -> None:
    """List the books, scrolls and signs in a U9 book archive."""
    raise SystemExit(cmd_books_list(SimpleNamespace(file=file, by_size=by_size, limit=limit)))


@u9_app.command("books-show")
def books_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    id: Annotated[int, typer.Option("-i", "--id", help="Book id, as shown by books-list")] = 1,
    name: Annotated[
        Optional[str], typer.Option("-b", "--name", help="Look the book up by name instead"),
    ] = None,
) -> None:
    """Print one U9 book's text."""
    raise SystemExit(cmd_books_show(SimpleNamespace(file=file, id=id, name=name)))


@u9_app.command("books-search")
def books_search_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    needle: Annotated[str, typer.Argument(help="Substring to look for")],
    case_sensitive: Annotated[bool, typer.Option("-c", "--case-sensitive", help="Match case exactly")] = False,
    limit: Annotated[Optional[int], typer.Option("-n", "--limit", help="Maximum matches to print")] = None,
) -> None:
    """Search a U9 book archive, showing the matching passage."""
    raise SystemExit(cmd_books_search(SimpleNamespace(
        file=file, needle=needle, case_sensitive=case_sensitive, limit=limit)))


@u9_app.command("books-export")
def books_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output CSV path"),
    ] = None,
) -> None:
    """Export a U9 book archive to CSV."""
    raise SystemExit(cmd_books_export(SimpleNamespace(file=file, output=output)))
