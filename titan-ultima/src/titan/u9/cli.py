"""
Ultima 9: Ascension — CLI sub-app.

Registered as ``titan u9 <command>`` in the root CLI.
"""

from __future__ import annotations

__all__ = ["u9_app"]

import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.mesh_export import MeshExportError, export_obj, export_stl
from titan.u9.model import U9Model, U9ModelError
from titan.u9.model_naming import label_for_model, names_for_model
from titan.u9.palette import U9Palette, U9PaletteError
from titan.u9.sound import U9SoundRecord, U9SoundRecordError
from titan.u9.texture import U9TextureError, decode_frame
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat

# ============================================================================
# Typer sub-app
# ============================================================================

u9_app = typer.Typer(
    name="u9",
    help="Ultima 9: Ascension — FLX archive, sound, and 3D model commands.",
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
    """Returns (U9TypesDat, U9TypeNames) if both paths are given, else None."""
    if not types_path or not typenames_path:
        return None
    return U9TypesDat.from_file(types_path), U9TypeNames.from_file(typenames_path)


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
