"""
Ultima 9: Ascension — CLI sub-app.

Registered as ``titan u9 <command>`` in the root CLI.
"""

from __future__ import annotations

__all__ = ["u9_app"]

import csv
import json
import os
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional, cast

import typer
from PIL import Image

from titan.u9.activity import U9Activities, U9ActivityError
from titan.u9.asset_reports import (
    MODEL_REPORT_COLUMNS,
    TEXTURE_REPORT_COLUMNS,
    U9AssetReportError,
    build_model_material_report,
    build_texture_frame_report,
    write_dynamic_report,
)
from titan.u9.animation import U9AnimationError, U9Animations
from titan.u9.books import U9Books, U9BooksError
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.flx_writer import (
    U9FlxWriteError,
    repack,
    repack_equivalent,
    write_flx,
)
from titan.u9.fixed import U9Fixed, U9FixedError
from titan.u9.highway import U9Highway, U9HighwayError
from titan.u9.icon import icon_entry_indices
from titan.u9.mesh_export import MeshExportError, export_obj, export_stl
from titan.u9.model import U9Model, U9ModelError
from titan.u9.model_naming import label_for_model, names_for_model
from titan.u9.map_atlas import (
    DEFAULT_ATLAS_PIXELS_PER_CELL,
    U9MapAtlasError,
    discover_region_files,
    render_map_atlas,
)
from titan.u9.map_render import (
    MAX_MAP_PIXELS_PER_CELL,
    U9MapRenderError,
    U9MapTextureSource,
    render_region_map,
)
from titan.u9.nonfixed import U9Nonfixed, U9NonfixedError
from titan.u9.object_placement import (
    U9ObjectFootprintFilter,
    U9ObjectPlacementError,
    U9SappearModelSource,
)
from titan.u9.npc import NO_CLASS, U9NpcError, U9Npcs
from titan.u9.palette import (
    EXPECTED_SIZE as U9_PALETTE_SIZE,
    PALETTE_TRANSPARENCY_INDEX,
    U9Palette,
    U9PaletteError,
)
from titan.u9.region_scene import U9RegionScene, U9RegionSceneError
from titan.u9.region_glb import (
    DEFAULT_U9_GLB_SCALE,
    U9CellRegion,
    U9GlbExportError,
    export_region_glb,
)
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError
from titan.u9.script_research import export_script_research_bundle
from titan.u9.sound import U9SoundRecord, U9SoundRecordError
from titan.u9.sound_report import (
    SOUND_REPORT_COLUMNS,
    U9SoundReportError,
    build_sound_metadata_report,
)
from titan.u9.sound_writer import (
    U9SoundWriteError,
    discover_sound_replacements,
    replace_sound_record_from_source,
)
from titan.u9.text import U9TextArchive, U9TextError
from titan.u9.terrain import U9Terrain, U9TerrainError
from titan.u9.texture import (
    U9TextureError,
    decode_frame,
    mip_dimensions,
    parse_texture_set,
)
from titan.u9.texture_writer import (
    U9TextureWriteError,
    frame_encoding,
    replace_frames,
)
from titan.u9.triggers import U9Triggers, U9TriggersError
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat, U9TypesDatError

# ============================================================================
# Typer sub-app
# ============================================================================

u9_app = typer.Typer(
    name="u9",
    help="Ultima 9: Ascension — archive, palette, texture, sound, model, world, script, and navigation commands.",
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
        print(
            f"ERROR: Index {args.index} out of range (0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
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
# CLI COMMANDS -- PALETTE (ankh.pal)
# ============================================================================


def cmd_palette_info(args: SimpleNamespace) -> int:
    """Inspect the layout and colour statistics of a U9 ankh.pal file."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    try:
        palette = U9Palette.from_file(args.file)
    except (OSError, U9PaletteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    file_size = os.path.getsize(args.file)
    distinct = len(set(palette.colors))
    duplicate_groups = palette.duplicate_groups()
    duplicate_entries = sum(len(indices) - 1 for _, indices in duplicate_groups)
    nonzero_reserved = sum(value != 0 for value in palette.reserved)
    transparency = palette.color_for(PALETTE_TRANSPARENCY_INDEX)

    print(f"{args.file} -- Ultima IX palette")
    print(f"  File size       : {file_size} bytes")
    print("  Layout          : 256 x 4 bytes (R, G, B, reserved)")
    print(f"  Colours         : 256 entries, {distinct} distinct")
    print(
        f"  Duplicates      : {duplicate_entries} repeated entries in "
        f"{len(duplicate_groups)} colour groups"
    )
    print(f"  Reserved bytes  : {nonzero_reserved} non-zero")
    print(
        f"  Transparency    : index {PALETTE_TRANSPARENCY_INDEX} "
        f"#{transparency[0]:02X}{transparency[1]:02X}{transparency[2]:02X}"
    )
    if file_size > U9_PALETTE_SIZE:
        print(f"  Trailing data   : {file_size - U9_PALETTE_SIZE} bytes")
    if args.duplicates:
        print("\nRepeated colours:")
        for color, indices in duplicate_groups:
            index_text = ", ".join(str(index) for index in indices)
            print(
                f"  #{color[0]:02X}{color[1]:02X}{color[2]:02X} "
                f"{color!s:<17} indices {index_text}"
            )
    return 0


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export a U9 palette as a PNG swatch and lossless text table."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    if args.swatch_size <= 0:
        print("ERROR: --swatch-size must be greater than zero", file=sys.stderr)
        return 1
    try:
        palette = U9Palette.from_file(args.file)
    except (OSError, U9PaletteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    base = Path(args.file).stem
    image_path = os.path.join(outdir, f"{base}_palette.png")
    text_path = os.path.join(outdir, f"{base}_palette.txt")

    palette.to_pil_image(args.swatch_size).save(image_path)
    with open(text_path, "w", encoding="utf-8", newline="\n") as file:
        file.write(f"# Ultima IX palette from {args.file}\n")
        file.write(
            "# The fourth byte is reserved, not alpha. Texture index 254 is transparent.\n"
        )
        file.write("# Index    R    G    B  Reserved  Alpha  Hex\n")
        for index, ((r, g, b), reserved) in enumerate(
            zip(palette.colors, palette.reserved)
        ):
            alpha = palette.rgba_for(index)[3]
            file.write(
                f"{index:3d}    {r:3d}  {g:3d}  {b:3d}      "
                f"{reserved:3d}    {alpha:3d}  #{r:02X}{g:02X}{b:02X}\n"
            )

    print(f"Palette swatch saved: {image_path}  (256 colors, 16x16 grid)")
    print(f"Palette text dump: {text_path}")
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
    print(
        f"{'Idx':>6}  {'Freq':>6}  {'Bits':>4}  {'Ch':>2}  {'Encoding':<14}  {'Bytes':>9}  Description"
    )
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
    print(
        f"\n{parsed}/{len(archive.used_entry_indices())} entries parsed as sound records"
    )
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
        out_path = os.path.join(
            outdir, f"{index:05d}_{record.description or record.sound_id}.wav"
        )
        with open(out_path, "wb") as f:
            f.write(record.to_wav_bytes())
        extracted += 1

    print(f"Extracted {extracted} PCM entries -> {outdir}/")
    if skipped_encoding:
        print(
            f"  ({skipped_encoding} entries skipped: not PCM-encoded, would need codec decoding first)"
        )
    return 0


def cmd_sound_extract(args: SimpleNamespace) -> int:
    """Extract decoded WAV, native payload, or complete record data."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(filepath)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output_format = getattr(args, "format", "wav")
    if output_format not in {"wav", "payload", "record"}:
        print("ERROR: format must be wav, payload, or record", file=sys.stderr)
        return 1
    requested_entry = getattr(args, "entry", None)
    if requested_entry is not None and not 0 <= requested_entry < archive.num_entries:
        print(
            f"ERROR: entry {requested_entry} out of range (0..{archive.num_entries - 1})",
            file=sys.stderr,
        )
        return 1

    suffix = "wav" if output_format == "wav" else output_format
    outdir = args.output or f"{Path(filepath).stem}_{suffix}"
    os.makedirs(outdir, exist_ok=True)

    extracted = 0
    skipped: dict[str, int] = {}
    indices = (
        [requested_entry]
        if requested_entry is not None
        else archive.used_entry_indices()
    )
    for index in indices:
        blob = archive.read_entry(index)
        if not blob:
            skipped["empty slot"] = skipped.get("empty slot", 0) + 1
            continue
        try:
            record = U9SoundRecord.parse(blob)
        except U9SoundRecordError:
            skipped["malformed record"] = skipped.get("malformed record", 0) + 1
            continue

        if output_format == "wav":
            try:
                output_bytes = record.to_wav_bytes()
            except U9SoundRecordError:
                reason = f"{record.encoding_name}, {record.num_channels}ch"
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            extension = ".wav"
        elif output_format == "payload":
            output_bytes = record.payload
            extension = ".payload.bin"
        else:
            output_bytes = blob
            extension = ".record.bin"

        label = re.sub(r"[^A-Za-z0-9._-]+", "_", record.description).strip("._")
        out_path = os.path.join(
            outdir, f"{index:05d}_{label or record.sound_id}{extension}"
        )
        with open(out_path, "wb") as f:
            f.write(output_bytes)
        extracted += 1

    print(
        f"Extracted {extracted}/{len(indices)} {output_format} entr{'y' if len(indices) == 1 else 'ies'} -> {outdir}/"
    )
    for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"  ({count} skipped: {reason})")
    return 0


def cmd_sound_report(args: SimpleNamespace) -> int:
    """Write dynamic metadata for one or all U9 audio archives."""
    try:
        rows, warnings = build_sound_metadata_report(
            args.source, entry_id=getattr(args, "entry", None)
        )
        output = write_dynamic_report(
            rows,
            args.output,
            args.format,
            preferred_columns=SOUND_REPORT_COLUMNS,
        )
    except (U9SoundReportError, U9AssetReportError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(rows)} sound metadata row(s) -> {output}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    return 0


def _write_sound_archive(
    archive_path: str,
    replacements: dict[int, bytes],
    output: str | None,
) -> tuple[Path, int]:
    archive = U9FlxArchive.from_file(archive_path)
    patched = repack(archive, replacements)
    destination = Path(output or f"{Path(archive_path).stem}_patched.flx").resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(patched)
    return destination, len(patched)


def cmd_sound_import(args: SimpleNamespace) -> int:
    """Replace one existing U9 sound record from WAV or native binary data."""
    if not os.path.isfile(args.archive):
        print(f"ERROR: Archive not found: {args.archive}", file=sys.stderr)
        return 1
    try:
        archive = U9FlxArchive.from_file(args.archive)
        if not 0 <= args.entry_id < archive.num_entries:
            raise U9SoundWriteError(
                f"entry {args.entry_id} out of range (0..{archive.num_entries - 1})"
            )
        current = archive.read_entry(args.entry_id)
        if not current:
            raise U9SoundWriteError(f"entry {args.entry_id} is an unused slot")
        replacement = replace_sound_record_from_source(
            current,
            args.audio,
            expected_entry_id=args.entry_id,
            description=getattr(args, "description", None),
        )
        destination, output_size = _write_sound_archive(
            args.archive, {args.entry_id: replacement}, args.output
        )
    except (OSError, U9FlxArchiveError, U9FlxWriteError, U9SoundWriteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Replaced sound entry {args.entry_id} from {args.audio}")
    print(f"  Record length: {len(current)} -> {len(replacement)} bytes")
    print(f"  Written      : {destination} ({output_size} bytes)")
    if (
        Path(args.audio).suffix.casefold() == ".wav"
        and Path(args.archive).stem.casefold() == "music"
    ):
        print(
            "  WARNING: shipped music is ADPCM; PCM music playback needs in-game testing."
        )
    return 0


def cmd_sound_import_batch(args: SimpleNamespace) -> int:
    """Validate and replace multiple sound slots, then repack the archive once."""
    if not os.path.isfile(args.archive):
        print(f"ERROR: Archive not found: {args.archive}", file=sys.stderr)
        return 1
    try:
        archive = U9FlxArchive.from_file(args.archive)
        sources = discover_sound_replacements(args.directory)
        replacements: dict[int, bytes] = {}
        for entry_id, source in sources.items():
            if not 0 <= entry_id < archive.num_entries:
                raise U9SoundWriteError(
                    f"entry {entry_id} from {source.name} is outside "
                    f"0..{archive.num_entries - 1}"
                )
            current = archive.read_entry(entry_id)
            if not current:
                raise U9SoundWriteError(f"entry {entry_id} is an unused slot")
            replacements[entry_id] = replace_sound_record_from_source(
                current, source, expected_entry_id=entry_id
            )
        destination, output_size = _write_sound_archive(
            args.archive, replacements, args.output
        )
    except (OSError, U9FlxArchiveError, U9FlxWriteError, U9SoundWriteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Replaced {len(replacements)} sound record(s) from {args.directory}")
    print(f"  Entries : {', '.join(str(value) for value in sorted(replacements))}")
    print(f"  Written : {destination} ({output_size} bytes)")
    if Path(args.archive).stem.casefold() == "music" and any(
        source.suffix.casefold() == ".wav" for source in sources.values()
    ):
        print(
            "  WARNING: shipped music is ADPCM; PCM music playback needs in-game testing."
        )
    return 0


# ============================================================================
# CLI COMMANDS — MODELS (sappear.flx)
# ============================================================================


def _load_model(sappear_file: str, model_id: int) -> U9Model:
    archive = U9FlxArchive.from_file(sappear_file)
    if model_id < 0 or model_id >= archive.num_entries:
        raise U9ModelError(
            f"model_id {model_id} out of range (0..{archive.num_entries - 1})"
        )
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
        print(
            f"WARNING: could not load type names ({e}); continuing without them",
            file=sys.stderr,
        )
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

    print(
        f"model {model.model_id}: {len(model.limbs)} limb(s), {model.record_format} record"
    )
    print(f"  bounds: {model.min_bounds} .. {model.max_bounds}")
    print(f"  sphere: center={model.sphere_center} radius={model.sphere_radius:.2f}")
    print(f"  lod_thresholds: {model.lod_thresholds}")
    print()
    print(
        f"{'Limb':>6}  {'Parent':>6}  {'Root':>5}  {'Position':<30}  "
        "LOD render t/v/m [+ mount mt/mv] (texture IDs)"
    )
    print("-" * 100)
    for limb in model.limbs:
        lod_summaries = []
        for lod in limb.lods:
            if lod is None:
                lod_summaries.append("-")
                continue
            tex_ids = sorted(
                {m.texture_id for m in lod.materials if not m.is_invisible}
            )
            mounts = (
                f" + {len(lod.mount_triangles)}mt/{len(lod.mount_vertices)}mv"
                if lod.mount_triangles or lod.mount_vertices
                else ""
            )
            lod_summaries.append(
                f"{len(lod.triangles)}t/{len(lod.vertices)}v/{len(lod.materials)}m"
                f"{mounts} {tex_ids}"
            )
        pos = tuple(round(v, 2) for v in limb.position)
        print(
            f"{limb.limb_id:>6}  {limb.parent_id:>6}  {str(limb.is_root):>5}  {str(pos):<30}  "
            + " | ".join(lod_summaries)
        )
    return 0


def cmd_model_material_report(args: SimpleNamespace) -> int:
    """Export model/material metadata joined to every discovered texture tier."""
    try:
        rows, warnings = build_model_material_report(
            args.source,
            model_id=getattr(args, "model", None),
            textures_path=getattr(args, "textures", None),
            types_path=getattr(args, "types", None),
            typenames_path=getattr(args, "typenames", None),
            only=getattr(args, "only", None),
        )
        output = write_dynamic_report(
            rows,
            args.output,
            args.format,
            preferred_columns=MODEL_REPORT_COLUMNS,
        )
    except (U9AssetReportError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"Wrote {len(rows)} model/material row(s) to {output}")
    return 0


PALETTE_FILENAME = "ankh.pal"


def _find_case_insensitive_file(directory: Path, filename: str) -> Optional[Path]:
    """Find one adjacent U9 data file without assuming Windows casing."""
    if not directory.is_dir():
        return None
    wanted = filename.casefold()
    return next(
        (path for path in directory.iterdir() if path.name.casefold() == wanted),
        None,
    )


def _find_palette(
    explicit: Optional[str], beside: Optional[str]
) -> tuple[Optional[str], bool]:
    """Resolve which palette file to use.

    Returns ``(path, was_auto_discovered)``. An explicit ``-p`` always wins.
    Otherwise ``ankh.pal`` is looked for next to the archive being read, which
    is where the game keeps it -- decoding an 8-bit frame without it silently
    produces a scrambled greyscale image rather than an error, so finding it is
    worth doing automatically.
    """
    if explicit:
        return explicit, False
    if not beside:
        return None, False
    directory = os.path.dirname(os.path.abspath(beside))
    try:
        entries = os.listdir(directory)
    except OSError:
        return None, False
    for name in entries:
        if name.lower() == PALETTE_FILENAME:
            return os.path.join(directory, name), True
    return None, False


def _load_palette(
    explicit: Optional[str], beside: Optional[str], *, quiet: bool = False
):
    """Load the palette for a decode, reporting where it came from."""
    path, auto = _find_palette(explicit, beside)
    if path is None:
        if not quiet:
            print(
                f"  NOTE: no {PALETTE_FILENAME} found next to the archive; 8-bit frames "
                f"will decode as scrambled greyscale. Pass -p to supply one."
            )
        return None
    try:
        palette = U9Palette.from_file(path)
    except (U9PaletteError, OSError) as e:
        print(f"ERROR: could not read palette {path}: {e}", file=sys.stderr)
        return None
    if auto and not quiet:
        print(f"  Palette         : {path} (found automatically)")
    return palette


SDINFO_FOR_ARCHIVE = {
    "bitmapsh.flx": "sdInfo.flx",
    "bitmap16.flx": "sdInfo16.flx",
    "bitmapc.flx": "sdInfoC.flx",
}


def _load_selectors(textures_path: Optional[str], *, quiet: bool = False) -> dict:
    """Map entry index -> the engine's pixel-format selector, from sdInfo.

    The selector is the only thing separating the two one-byte-per-texel
    formats, so decoding without it silently renders 42 ALPHA_INTENSITY_44
    frames as plain masks. The matching sdInfo archive sits beside the bitmap
    archive, so it is found the same way ankh.pal is.
    """
    if not textures_path:
        return {}
    partner = SDINFO_FOR_ARCHIVE.get(os.path.basename(textures_path).lower())
    if partner is None:
        return {}
    directory = os.path.dirname(os.path.abspath(textures_path))
    try:
        entries = os.listdir(directory)
    except OSError:
        return {}
    match = next((n for n in entries if n.lower() == partner.lower()), None)
    if match is None:
        if not quiet:
            print(
                f"  NOTE: no {partner} beside the archive; ALPHA_INTENSITY_44 frames "
                f"will decode as plain masks."
            )
        return {}
    try:
        info = U9SdInfo.from_file(os.path.join(directory, match))
    except (U9SdInfoError, OSError):
        return {}
    if not quiet:
        print(
            f"  Format table    : {os.path.join(directory, match)} (found automatically)"
        )
    return {r.index: r.format_selector for r in info.records()}


def _make_texture_resolver(textures_path: Optional[str], palette_path: Optional[str]):
    if not textures_path:
        return None
    texture_archive = U9FlxArchive.from_file(textures_path)
    palette = _load_palette(palette_path, textures_path)
    selectors = _load_selectors(textures_path)

    def resolver(texture_id: int, frame: int):
        try:
            blob = texture_archive.read_entry(texture_id)
            return decode_frame(
                blob, frame, palette=palette, selector=selectors.get(texture_id)
            )
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
            export_obj(
                model, base + ".obj", lod_level=args.lod, texture_resolver=resolver
            )
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


def _export_all_one(
    model_id: int,
    blob: bytes,
    outdir: str,
    resolver,
    naming,
    args: SimpleNamespace,
    stats: Counter,
) -> None:
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
            export_obj(
                model, base + ".obj", lod_level=args.lod, texture_resolver=resolver
            )
        if args.format in ("stl", "both"):
            export_stl(model, base + ".stl", lod_level=args.lod)
        stats["exported"] += 1
    except MeshExportError:
        stats["no_geometry"] += 1
        os.rmdir(model_dir)  # nothing was written into it
        return

    if (
        not args.preview
        or args.format not in ("obj", "both")
        or stats["preview_unavailable"]
    ):
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
            format=args.format,
            file=args.file,
            textures=args.textures,
            palette=args.palette,
            types=args.types,
            typenames=args.typenames,
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
        _export_all_one(
            model_id,
            archive.read_entry(model_id),
            outdir,
            resolver,
            naming,
            args,
            stats,
        )

    print()
    print(f"total used models: {len(used)}")
    print(f"parse failures: {stats['parse_fail']}")
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
    print(f"  Compression    : {compression}")
    print(f"  Header 0x0C    : {texture_set.unknown:#010x}")
    print(
        f"{'Frame':>5}  {'Size':<11}  {'Encoding':<10}  {'Offset':>8}  {'Length':>8}  Flags"
    )
    print("-" * 69)
    selectors = _load_selectors(args.textures)
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
            f"{frame.index:>5}  {sizes:<11}  {encoding:<10}  {frame.offset:>8}  "
            f"{frame.length:>8}  {frame.flags:#06x}/{frame.unknown_word:#06x}"
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

    palette = _load_palette(args.palette, args.textures)
    selectors = _load_selectors(args.textures)
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

    palette = _load_palette(args.palette, args.textures)
    selectors = _load_selectors(args.textures)
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

    palette = _load_palette(args.palette, args.textures)
    selectors = _load_selectors(args.textures)
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
    """Summarize a runtime region's pages, entities, and shared allocator."""
    region = _load_region(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    pages = sum(len(c.pages) for c in chunks)
    indexed = sum(len(c.entities) for c in chunks)
    allocated = sum(len(c.allocated_entities) for c in chunks)
    unlinked = sum(len(c.unlinked_entities) for c in chunks)
    extras = sum(len(c.extra_data_records) for c in chunks)
    referenced_extras = len(
        {
            e.extra_data_offset
            for c in chunks
            for e in c.allocated_entities
            if e.extra_data_offset
        }
    )
    incomplete = [c for c in chunks if not c.allocation_is_complete]

    print(f"{args.file} -- {region.width}x{region.height} chunk region")
    print(f"  Header          : {region.header_size} bytes")
    print(
        f"  Payload         : {region.payload_size} bytes (watermark {region.declared_payload_size})"
    )
    print(f"  Populated chunks: {len(chunks)} of {region.num_chunks}")
    print(f"  Pages           : {pages}")
    print(f"  Entities        : {indexed} spatially indexed, {allocated} allocated")
    print(f"  Unlinked records: {unlinked}")
    print(f"  Extra-data      : {extras} allocated, {referenced_extras} referenced")
    print(f"  Allocator       : {'complete' if not incomplete else 'incomplete'}")
    if incomplete:
        print(
            f"  NOTE: {len(incomplete)} chunk(s) contain truncated or inconsistent "
            "allocator data."
        )
    return 0


def cmd_nonfixed_chunks(args: SimpleNamespace) -> int:
    """List every populated chunk in a region with its page and entity counts."""
    region = _load_region(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    print(f"{args.file} -- {len(chunks)} populated chunk(s) of {region.num_chunks}")
    print(
        f"{'Idx':>5}  {'Grid':<9}  {'Base (x,y)':<15}  {'Pages':>5}  "
        f"{'Index':>6}  {'Alloc':>6}  {'Loose':>5}  {'Extra':>5}  Full"
    )
    print("-" * 88)
    for c in chunks:
        grid = f"{c.chunk_x},{c.chunk_y}"
        base = f"{c.base_x},{c.base_y}"
        flag = "yes" if c.allocation_is_complete else "no"
        print(
            f"{c.index:>5}  {grid:<9}  {base:<15}  {len(c.pages):>5}  "
            f"{len(c.entities):>6}  {len(c.allocated_entities):>6}  "
            f"{len(c.unlinked_entities):>5}  {len(c.extra_data_records):>5}  {flag}"
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
    include_unlinked = getattr(args, "include_unlinked", False)
    rows = []
    for chunk in chunks:
        unlinked_offsets = {entity.offset for entity in chunk.unlinked_entities}
        selected = chunk.allocated_entities if include_unlinked else chunk.entities
        rows.extend(
            (
                chunk,
                entity,
                "unlinked" if entity.offset in unlinked_offsets else "indexed",
            )
            for entity in selected
        )
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} entit{'y' if len(rows) == 1 else 'ies'}")
    header = (
        f"{'Offset':>8}  {'Chunk':<7}  {'State':<8}  {'World (x,y,z)':<20}  "
        f"{'Type':>5}  {'Mesh':>5}  {'Trig':>5}  {'Extra':>7}"
    )
    if names:
        header += "  Name"
    print(header)
    print("-" * (len(header) + 8))
    for c, e, state in shown:
        grid = f"{c.chunk_x},{c.chunk_y}"
        pos = f"{e.world_x},{e.world_y},{e.z}"
        extra = f"{e.extra_data_offset:#07x}" if e.has_extra_data else "-"
        line = (
            f"{e.offset:>#8x}  {grid:<7}  {state:<8}  {pos:<20}  {e.type_index:>5}  "
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
            (c.index, e.offset): (c, e) for c in region.chunks() for e in c.entities
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
    print(
        f"  Points          : {len(highway.points)} of {highway.declared_point_count} declared"
    )
    print(
        f"  Routes          : {len(highway.routes)} of {highway.declared_route_count} declared"
    )
    print(
        f"  Route block     : {highway.route_bytes} bytes, {highway.route_bytes_consumed} consumed"
    )
    if ids:
        print(f"  Trigger IDs     : {min(ids)}..{max(ids)}")
        print(f"  World extent    : x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
    print(
        f"  Connectivity    : {len(adjacency)} point(s) appear in a route, {edges} edge(s)"
    )
    if highway.routes:
        longest = max(highway.routes, key=lambda r: r.path_length)
        print(
            f"  Longest route   : {longest.start_trigger_id} -> {longest.last_trigger_id}, "
            f"{longest.path_length} nodes, distance {longest.route_distance}"
        )
    if unknown:
        print(
            f"  WARNING: {len(unknown)} route node(s) have no declared point: {unknown[:10]}"
        )
    if not highway.is_complete:
        print(
            "  WARNING: file did not parse completely -- truncated or not a highway.dat"
        )
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

    routes = (
        highway.routes_through(args.id) if args.id is not None else list(highway.routes)
    )
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
# CLI COMMANDS — ANIMATION CLIPS (static/anim.flx)
# ============================================================================


def _load_animations(filepath: str) -> Optional[U9Animations]:
    """Open static/anim.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Animations.from_file(filepath)
    except U9AnimationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_animation_list(args: SimpleNamespace) -> int:
    """List animation clips with their frame, part and suffix counts."""
    animations = _load_animations(args.file)
    if animations is None:
        return 1

    animation_ids = animations.used_animation_ids()
    shown = animation_ids[: args.limit] if args.limit else animation_ids
    print(
        f"{args.file} -- {len(animation_ids)} animation clip(s) "
        f"of {animations.num_entries} slots"
    )
    print(
        f"{'ID':>5}  {'Frames':>6}  {'Parts':>5}  {'Last ms':>8}  {'Suffix':>6}  Source"
    )
    print("-" * 96)
    for animation_id in shown:
        try:
            animation = animations.animation(animation_id)
        except U9AnimationError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if animation is None:
            continue
        print(
            f"{animation.animation_id:>5}  {animation.frame_count:>6}  "
            f"{len(animation.parts):>5}  {animation.duration_ms:>8}  "
            f"{len(animation.suffixes):>6}  {animation.source_name}"
        )
    if args.limit and len(animation_ids) > args.limit:
        print(
            f"... ({len(animation_ids) - args.limit} more; raise --limit to see more)"
        )
    return 0


def cmd_animation_show(args: SimpleNamespace) -> int:
    """Show one animation, optionally dumping one part's frame transforms."""
    animations = _load_animations(args.file)
    if animations is None:
        return 1

    try:
        animation = animations.animation(args.id)
    except U9AnimationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if animation is None:
        print(f"Animation {args.id} is an unused slot.")
        return 0

    print(f"{args.file} -- animation {animation.animation_id}")
    print(f"  Source          : {animation.source_name}")
    print(
        f"  Source frames   : {animation.start_frame}..{animation.end_frame} "
        f"({animation.frame_count} total)"
    )
    print(
        f"  Timing          : {animation.source_fps} fps, "
        f"{animation.frame_interval_ms} nominal ms, last timestamp {animation.duration_ms} ms"
    )
    print(
        f"  Structure       : {len(animation.header_words)} header words, "
        f"{len(animation.parts)} parts, {len(animation.suffixes)} suffix records"
    )

    if args.part is None:
        parts = animation.parts[: args.limit] if args.limit else animation.parts
        print(f"  {'Part ID':>7}  {'Frames':>6}  {'Last ms':>8}  Name")
        print("  " + "-" * 52)
        for part in parts:
            last_ms = part.frames[-1].time_ms if part.frames else 0
            print(
                f"  {part.part_id:>7}  {part.frame_count:>6}  {last_ms:>8}  {part.name}"
            )
        if args.limit and len(animation.parts) > args.limit:
            print(
                f"  ... ({len(animation.parts) - args.limit} more; "
                "raise --limit to see more)"
            )
    else:
        selected_part = animation.part(args.part)
        if selected_part is None:
            print(
                f"ERROR: animation {animation.animation_id} has no part ID {args.part}",
                file=sys.stderr,
            )
            return 1
        frames = (
            selected_part.frames[: args.limit] if args.limit else selected_part.frames
        )
        print(
            f"  Part {selected_part.part_id}: {selected_part.name} "
            f"({selected_part.frame_count} frames)"
        )
        for index, frame in enumerate(frames):
            rotation = ", ".join(f"{value:.6g}" for value in frame.rotation)
            position = ", ".join(f"{value:.6g}" for value in frame.position)
            scale = ", ".join(f"{value:.6g}" for value in frame.scale)
            print(
                f"    {index:>4}  {frame.time_ms:>6} ms  "
                f"q=({rotation})  p=({position})  s=({scale})"
            )
        if args.limit and selected_part.frame_count > args.limit:
            print(
                f"    ... ({selected_part.frame_count - args.limit} more; "
                "raise --limit to see more)"
            )

    if animation.suffixes:
        suffixes = " ".join(
            f"({a}, {b}, {c})"
            for a, b, c in (suffix.values for suffix in animation.suffixes)
        )
        print(f"  Raw suffixes    : {suffixes}")
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
    print(
        f"{args.file} -- {len(entries)} trigger(s) of {triggers.num_entries} slots ({empty} empty)"
    )
    print(f"{'TriggerID':>10}  {'Records':>7}  {'Slack':>5}  {'Term':>5}  Opcodes")
    print("-" * 66)
    for t in shown:
        term = "yes" if t.terminated else "NO"
        ops = " ".join(f"{o:#04x}" for o in t.opcodes[:6])
        if len(t.opcodes) > 6:
            ops += " ..."
        print(
            f"{t.trigger_id:>10}  {len(t.records):>7}  {t.slack_records:>5}  {term:>5}  {ops}"
        )
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
        print(
            "  WARNING: no 0xFF terminator; the record list runs to the end of the entry"
        )
    if trigger.slack_records:
        print(
            f"  {trigger.slack_records} stale record(s) after the terminator (preserved)"
        )
    if trigger.records:
        print(f"  {'#':>3}  {'Opcode':>6}  {'Arg0':>5}  {'Arg1':>6}  {'Arg2':>6}")
        print("  " + "-" * 38)
        for index, r in enumerate(trigger.records):
            print(
                f"  {index:>3}  {r.opcode:>#6x}  {r.arg0:>5}  {r.arg1:>6}  {r.arg2:>6}"
            )
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
    print(
        f"{args.file} -- {len(entries)} activity set(s) of {activities.num_entries} slots"
    )
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
    print(
        f"  {len(activity.records)} of {activity.declared_record_count} declared record(s), "
        f"{activity.payload_length}-byte payload"
    )
    if activity.trailing_bytes:
        print(
            f"  WARNING: {activity.trailing_bytes} byte(s) left over after the last record"
        )
    for record in activity.records:
        print(f"  [{record.ordinal}] {record.name}")
        if not record.terminated:
            print(
                "       WARNING: no 0xFF step; the record runs to the end of the entry"
            )
        for index, step in enumerate(record.steps):
            print(
                f"       {index:>2}  opcode {step.opcode:#04x}  {step.operands.hex(' ')}"
            )
        if not record.steps:
            print("       (no steps)")
    print(
        "  Opcodes 0x01/0x02 move between highway points; the other ten are not decoded."
    )
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
    print(
        f"{args.file} -- {total} step(s), {len(opcodes)} distinct opcode(s), "
        f"{len(names)} distinct name(s)"
    )
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


def cmd_script_research_export(args: SimpleNamespace) -> int:
    """Export trigger/activity evidence tables for Ghidra analysis."""
    triggers = _load_triggers(args.triggers)
    activities = _load_activities(args.activities)
    if triggers is None or activities is None:
        return 1

    try:
        paths = export_script_research_bundle(
            triggers,
            activities,
            args.output,
            source_files={
                "triggers": args.triggers,
                "activities": args.activities,
            },
        )
    except (OSError, U9TriggersError, U9ActivityError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(paths)} Ghidra research file(s) to {args.output}")
    for path in paths:
        print(f"  {path}")
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
    print(
        f"{'Idx':>5}  {'Name':<24} {'G':>1}  {'Class':>5}  {'Region':>6}  "
        f"{'HP':>5}  {'Mana':>5}  Position"
    )
    print("-" * 90)
    for n in shown:
        cls = "-" if not n.has_class else str(n.class_id)
        print(
            f"{n.index:>5}  {n.name:<24} {'F' if n.is_female else 'M'}  {cls:>5}  "
            f"{n.region:>6}  {n.health_max:>5}  {n.mana_max:>5}  "
            f"{n.x},{n.y},{n.z}"
        )
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
        print(
            f"  Pool handle : {n.pool_handle} (element {n.pool_index} of the region object pool)"
        )
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
        "index",
        "name",
        "gender",
        "sex",
        "health_current",
        "health_max",
        "health_max2",
        "mana_current",
        "mana_max",
        "mana_max2",
        "class_id",
        "flags",
        "combat_value",
        "region",
        "x",
        "y",
        "z",
        "scale_x",
        "scale_y",
        "scale_z",
        "pool_handle",
        "pool_index",
        # Undecoded but genuinely varying; kept as named columns so they can be
        # correlated without re-slicing the raw bytes.
        "unk_0x4e",
        "unk_0x56",
        "unk_0xb0",
        "unk_0xc4",
        "unk_0xc8",
        "raw_hex",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for n in rows:
            writer.writerow(
                [
                    n.index,
                    n.name,
                    n.gender,
                    "female" if n.is_female else "male",
                    n.health_current,
                    n.health_max,
                    n.health_max2,
                    n.mana_current,
                    n.mana_max,
                    n.mana_max2,
                    n.class_id if n.has_class else "",
                    f"{n.flags:#010x}",
                    n.combat_value,
                    n.region,
                    n.x,
                    n.y,
                    n.z,
                    n.scale[0],
                    n.scale[1],
                    n.scale[2],
                    n.pool_handle,
                    n.pool_index,
                    struct.unpack_from("<H", n.raw, 0x4E)[0],
                    struct.unpack_from("<H", n.raw, 0x56)[0],
                    struct.unpack_from("<I", n.raw, 0xB0)[0],
                    struct.unpack_from("<H", n.raw, 0xC4)[0],
                    n.raw[0xC8],
                    n.raw.hex(),
                ]
            )

    print(f"{args.file} -- wrote {len(rows)} NPC row(s) -> {out_path}")
    print(
        f"  {len(header)} columns; raw_hex carries the full {len(rows[0].raw) if rows else 0}-byte record"
    )
    if not args.all:
        blank = len(npcs) - len(rows)
        if blank:
            print(
                f"  {blank} unnamed/blank slot(s) omitted; pass --all to include them"
            )
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
        spawned = [n.name for n in list(right)[len(left) :] if n.name]
        print(
            f"  {len(right) - len(left)} extra live slot(s), {len(spawned)} named "
            f"(runtime-spawned): {', '.join(spawned[:8])}"
            + (", ..." if len(spawned) > 8 else "")
        )

    changed = left.changed_fields(right)
    print(f"  {len(changed)} byte offset(s) differ across the shared records:")
    for offset, count in changed.items():
        print(f"      {offset:#06x}  {count} NPC(s)")

    moved = [
        (a, b)
        for a, b in zip(left, right)
        if (a.region, a.x, a.y, a.z) != (b.region, b.x, b.y, b.z)
    ]
    print(f"  {len(moved)} NPC(s) moved:")
    for a, b in moved[: args.limit or len(moved)]:
        print(
            f"      {a.name:<16} region {a.region} {a.x},{a.y},{a.z}"
            f"  ->  region {b.region} {b.x},{b.y},{b.z}"
        )
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
    print(
        f"  Payload         : {region.payload_size} bytes "
        f"(watermark {region.declared_payload_size})"
    )
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
        print(
            f"{c.table_index:>5}  {f'{c.chunk_x},{c.chunk_y}':<9}  "
            f"{f'{c.base_x},{c.base_y}':<15}  {len(c.pages):>5}  {len(c.objects):>7}"
        )
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
    header = (
        f"{'Offset':>8}  {'Chunk':<7}  {'World (x,y,z)':<20}  {'Type':>5}  "
        f"{'Flags':>10}"
    )
    if names:
        header += "  Name"
    print(header)
    print("-" * (len(header) + 8))
    for c, o in shown:
        line = (
            f"{o.offset:>#8x}  {f'{c.chunk_x},{c.chunk_y}':<7}  "
            f"{f'{o.world_x},{o.world_y},{o.z}':<20}  {o.type_index:>5}  "
            f"{o.flags:>#10x}"
        )
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
    """Summarize one region height map, including its environment header."""
    region = _load_terrain(args.file)
    if region is None:
        return 1

    print(f"{args.file} -- {region.name or '(unnamed)'}")
    print(f"  Water level     : {region.water_level}")
    print(f"  Wave amplitude  : {region.wave_amplitude:g}")
    print(f"  Region flags    : 0x{region.flags:08x}")
    if region.is_empty:
        print("  Unused region slot: a bare header, no tile grid and no chunks.")
        print(f"  Header still declares {region.declared_chunk_count} chunk(s).")
        return 0

    low, high = region.height_range()
    unused = len(region.unused_chunks())
    duplicates = region.duplicate_tile_reference_count()
    shared = region.tiles_using_shared_chunks()
    print(f"  Points          : {region.width}x{region.height}")
    print(f"  World coords    : {region.world_width}x{region.world_height}")
    print(
        f"  Tiles           : {region.tile_width}x{region.tile_height} "
        f"({region.tile_count} total, {shared} use shared chunks, "
        f"{duplicates} duplicate references)"
    )
    print(
        f"  Chunks          : {region.chunk_count} "
        f"(declared {region.declared_chunk_count}, {unused} referenced by no tile)"
    )
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

    print(
        f"{args.file} -- {region.tile_width}x{region.tile_height} tiles "
        f"over {region.chunk_count} chunk(s)"
    )
    width = max(3, len(str(max(region.tiles))))
    for tile_y in range(region.tile_height):
        base = tile_y * region.tile_width
        row = region.tiles[base : base + region.tile_width]
        print(f"{tile_y:>4}  " + " ".join(f"{v:>{width}}" for v in row))
    return 0


def cmd_terrain_chunk(args: SimpleNamespace) -> int:
    """Dump one decoded field from a chunk's 16x16 points."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    try:
        if args.tile is not None:
            try:
                tile_x, tile_y = (int(v) for v in args.tile.split(",", 1))
            except ValueError:
                print(
                    f"ERROR: --tile expects 'X,Y', got {args.tile!r}", file=sys.stderr
                )
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
        "swap": lambda p: int(p.swap_uv),
        "mirror": lambda p: int(p.mirror_uv),
        "uv-rotation": lambda p: p.uv_rotation_degrees,
        "split": lambda p: int(p.is_split),
        "spare": lambda p: int(p.spare_bit_set),
        "raw": lambda p: p.value,
    }[field]
    points = chunk.points()
    values = [pick(p) for p in points]
    holes = sum(1 for p in points if p.is_hole)

    print(
        f"{args.file} -- chunk {index}, {field} "
        f"({'flat' if chunk.is_flat else 'varied'}, {holes} hole point(s))"
    )
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

    histogram = region.texture_histogram()
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
            line += (
                f"  {f'{record.width}x{record.height}':>9}  {record.frame_count:>6}"
                if record
                else f"  {'--':>9}  {'--':>6}"
            )
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
    print(
        f"{args.file} -- {region.width}x{region.height}, heights {low}..{high} "
        f"-> {out_path}"
    )
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
        writer.writerow(
            [
                "x",
                "y",
                "tile_x",
                "tile_y",
                "chunk",
                "height",
                "hole",
                "swap_uv",
                "mirror_uv",
                "uv_rotation_degrees",
                "split",
                "frame",
                "texture",
                "spare",
                "raw",
            ]
        )
        for tile_y in range(region.tile_height):
            for tile_x in range(region.tile_width):
                index = region.tile(tile_x, tile_y)
                for point in region.chunk(index).points():
                    writer.writerow(
                        [
                            tile_x * 16 + point.x,
                            tile_y * 16 + point.y,
                            tile_x,
                            tile_y,
                            index,
                            point.height,
                            int(point.is_hole),
                            int(point.swap_uv),
                            int(point.mirror_uv),
                            point.uv_rotation_degrees,
                            int(point.is_split),
                            point.frame,
                            point.texture,
                            int(point.spare_bit_set),
                            point.value,
                        ]
                    )
                    written += 1
    print(f"{args.file} -- wrote {written} point(s) -> {out_path}")
    return 0


def cmd_map_atlas(args: SimpleNamespace) -> int:
    """Render a labelled, numerically ordered catalogue of U9 regions."""
    object_meshes = getattr(args, "objects", False)
    object_lod = getattr(args, "object_lod", 0)
    needs_models = args.object_footprints or object_meshes
    static_directory = Path(args.static)
    runtime_directory = Path(args.runtime) if args.runtime else None
    if not static_directory.is_dir():
        print(f"ERROR: Static directory not found: {static_directory}", file=sys.stderr)
        return 1
    if runtime_directory is not None and not runtime_directory.is_dir():
        print(
            f"ERROR: Runtime directory not found: {runtime_directory}",
            file=sys.stderr,
        )
        return 1

    textures_path = args.textures
    if textures_path is None:
        match = _find_case_insensitive_file(static_directory, "bitmap16.flx")
        textures_path = str(match) if match is not None else None
    if textures_path is None or not os.path.isfile(textures_path):
        print(
            "ERROR: bitmap16.flx was not found in the static directory; "
            "pass --textures",
            file=sys.stderr,
        )
        return 1

    models_path = args.models
    types_path = args.types
    try:
        sources = discover_region_files(
            static_directory,
            runtime_directory=runtime_directory,
            region_ids=tuple(args.region_ids or ()),
        )
    except U9MapAtlasError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if needs_models:
        if models_path is None:
            match = _find_case_insensitive_file(static_directory, "sappear.flx")
            models_path = str(match) if match is not None else None
        if models_path is None or not os.path.isfile(models_path):
            print(
                "ERROR: sappear.flx was not found in the static directory; "
                "pass --models",
                file=sys.stderr,
            )
            return 1
        if any(source.fixed_path is not None for source in sources):
            if types_path is None:
                match = _find_case_insensitive_file(static_directory, "TYPES.DAT")
                types_path = str(match) if match is not None else None
            if types_path is None or not os.path.isfile(types_path):
                print(
                    "ERROR: TYPES.DAT was not found in the static directory; "
                    "pass --types",
                    file=sys.stderr,
                )
                return 1

    output_directory = Path(args.output or "u9_map_atlas")
    try:
        textures = U9MapTextureSource.from_file(
            textures_path,
            palette_path=args.palette,
            sdinfo_path=args.sdinfo,
        )
        object_models = (
            U9SappearModelSource.from_file(models_path)
            if needs_models and models_path is not None
            else None
        )
        object_types = (
            U9TypesDat.from_file(types_path)
            if needs_models and types_path is not None
            else None
        )
        result = render_map_atlas(
            sources,
            textures,
            output_directory,
            thumbnail_size=args.thumbnail_size,
            columns=args.columns,
            pixels_per_cell=args.pixels_per_cell,
            hillshade=args.hillshade,
            hillshade_strength=args.hillshade_strength,
            water=args.water,
            water_frame=args.water_frame,
            fixed_markers=args.fixed_markers,
            fixed_marker_radius=args.fixed_marker_radius,
            nonfixed_markers=args.nonfixed_markers,
            nonfixed_marker_radius=args.nonfixed_marker_radius,
            include_unlinked_nonfixed=args.include_unlinked_nonfixed,
            object_meshes=object_meshes,
            object_mesh_models=object_models if object_meshes else None,
            object_textures=textures if object_meshes else None,
            object_lod=object_lod,
            object_footprints=args.object_footprints,
            object_models=object_models,
            object_types=object_types,
            object_footprint_source=args.object_footprint_source,
            object_type_ids=tuple(args.object_type_ids or ()),
            object_model_ids=tuple(args.object_model_ids or ()),
            object_footprint_style=args.object_footprint_style,
            cell_grid=args.cell_grid,
            tile_grid=args.tile_grid,
            tile_coordinates=args.tile_coordinates,
            chunk_labels=args.chunk_labels,
            flip_y=args.flip_y,
            continue_on_error=not args.strict,
        )
    except (
        OSError,
        U9MapAtlasError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
        U9FlxArchiveError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    metadata = Path(args.metadata) if args.metadata else output_directory / "atlas.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    manifest = result.manifest()
    manifest["sources"] = {
        "static_directory": str(static_directory.resolve()),
        "runtime_directory": (
            str(runtime_directory.resolve()) if runtime_directory else None
        ),
        "textures": str(Path(textures_path).resolve()),
        "palette": (
            str(textures.palette_path.resolve()) if textures.palette_path else None
        ),
        "sdinfo": str(textures.sdinfo_path.resolve()) if textures.sdinfo_path else None,
        "models": str(Path(models_path).resolve()) if models_path else None,
        "types": str(Path(types_path).resolve()) if types_path else None,
    }
    manifest["rendering"] = {
        "pixels_per_cell": args.pixels_per_cell,
        "hillshade": args.hillshade,
        "hillshade_strength": args.hillshade_strength,
        "water": args.water,
        "water_frame": args.water_frame,
        "fixed_markers": args.fixed_markers,
        "fixed_marker_radius": args.fixed_marker_radius,
        "nonfixed_markers": args.nonfixed_markers,
        "nonfixed_marker_radius": args.nonfixed_marker_radius,
        "include_unlinked_nonfixed": args.include_unlinked_nonfixed,
        "objects": object_meshes,
        "object_lod": object_lod,
        "object_footprints": args.object_footprints,
        "object_footprint_source": args.object_footprint_source,
        "object_type_ids": list(args.object_type_ids or ()),
        "object_model_ids": list(args.object_model_ids or ()),
        "object_footprint_style": args.object_footprint_style,
        "cell_grid": args.cell_grid,
        "tile_grid": args.tile_grid,
        "tile_coordinates": args.tile_coordinates,
        "chunk_labels": args.chunk_labels,
        "flip_y": args.flip_y,
    }
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(
        f"Rendered {diagnostics.rendered_regions}/{diagnostics.requested_regions} "
        f"region(s) -> {result.atlas_path}"
    )
    print(f"  Manifest         : {metadata}")
    print(f"  Region previews  : {result.regions_directory}")
    print(
        f"  Fixed/nonfixed   : {diagnostics.regions_with_fixed}/"
        f"{diagnostics.regions_with_nonfixed} region(s)"
    )
    print(f"  Missing textures : {diagnostics.regions_with_missing_textures} region(s)")
    for record in result.regions:
        if record.error:
            print(f"  FAILED region {record.region_id}: {record.error}")
    if diagnostics.failed_regions:
        print(
            f"  Render failures  : {diagnostics.failed_regions} "
            f"({'strict mode disabled' if not args.strict else 'strict mode enabled'})"
        )
    print("  Ordering         : numeric region ID; geographic adjacency not inferred")
    return 0


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render terrain with decoded textures and optional object placements."""
    object_meshes = getattr(args, "objects", False)
    object_lod = getattr(args, "object_lod", 0)
    object_footprints = getattr(args, "object_footprints", False)
    needs_models = object_footprints or object_meshes
    object_footprint_source = cast(
        Literal["all", "fixed", "nonfixed"],
        getattr(args, "object_footprint_source", "all"),
    )
    object_type_ids = tuple(getattr(args, "object_type_ids", None) or ())
    object_model_ids = tuple(getattr(args, "object_model_ids", None) or ())
    object_footprint_style = cast(
        Literal["outline", "fill"],
        getattr(args, "object_footprint_style", "outline"),
    )
    object_legend = getattr(args, "object_legend", True)
    models_path = getattr(args, "models", None)
    types_path = getattr(args, "types", None)
    for label, path in (
        ("Terrain", args.terrain),
        ("Fixed", args.fixed),
        ("Nonfixed", args.nonfixed),
        ("Models", models_path),
        ("Types", types_path),
    ):
        if path is not None and not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 1

    textures_path = args.textures
    if textures_path is None:
        terrain_dir = Path(args.terrain).resolve().parent
        textures_match = _find_case_insensitive_file(terrain_dir, "bitmap16.flx")
        textures_path = str(textures_match) if textures_match is not None else None
    if textures_path is None or not os.path.isfile(textures_path):
        print(
            "ERROR: bitmap16.flx was not found beside the terrain file; "
            "pass --textures",
            file=sys.stderr,
        )
        return 1

    terrain_dir = Path(args.terrain).resolve().parent
    if needs_models:
        if args.fixed is None and args.nonfixed is None:
            print(
                "ERROR: --objects/--object-footprints requires --fixed or --nonfixed",
                file=sys.stderr,
            )
            return 1
        if models_path is None:
            models_match = _find_case_insensitive_file(terrain_dir, "sappear.flx")
            models_path = str(models_match) if models_match is not None else None
        if models_path is None or not os.path.isfile(models_path):
            print(
                "ERROR: sappear.flx was not found beside the terrain file; "
                "pass --models",
                file=sys.stderr,
            )
            return 1
        if args.fixed is not None and types_path is None:
            types_match = _find_case_insensitive_file(terrain_dir, "TYPES.DAT")
            types_path = str(types_match) if types_match is not None else None
        if args.fixed is not None and (
            types_path is None or not os.path.isfile(types_path)
        ):
            print(
                "ERROR: TYPES.DAT was not found beside the terrain file; pass --types",
                file=sys.stderr,
            )
            return 1

    try:
        scene = U9RegionScene.from_files(
            args.terrain,
            fixed_path=args.fixed,
            nonfixed_path=args.nonfixed,
        )
        textures = U9MapTextureSource.from_file(
            textures_path,
            palette_path=args.palette,
            sdinfo_path=args.sdinfo,
        )
        object_models = (
            U9SappearModelSource.from_file(models_path)
            if needs_models and models_path is not None
            else None
        )
        object_types = (
            U9TypesDat.from_file(types_path)
            if needs_models and types_path is not None
            else None
        )
        result = render_region_map(
            scene,
            textures,
            pixels_per_cell=args.pixels_per_cell,
            hillshade=args.hillshade,
            hillshade_strength=args.hillshade_strength,
            water=args.water,
            water_frame=args.water_frame,
            fixed_markers=args.fixed_markers,
            fixed_marker_radius=args.fixed_marker_radius,
            nonfixed_markers=args.nonfixed_markers,
            nonfixed_marker_radius=args.nonfixed_marker_radius,
            include_unlinked_nonfixed=args.include_unlinked_nonfixed,
            object_meshes=object_meshes,
            object_mesh_models=object_models if object_meshes else None,
            object_textures=textures if object_meshes else None,
            object_lod=object_lod,
            object_footprints=object_footprints,
            object_models=object_models,
            object_types=object_types,
            object_footprint_source=object_footprint_source,
            object_type_ids=object_type_ids,
            object_model_ids=object_model_ids,
            object_footprint_style=object_footprint_style,
            object_legend=object_legend,
            flip_y=args.flip_y,
        )
    except (
        OSError,
        U9FixedError,
        U9NonfixedError,
        U9TerrainError,
        U9RegionSceneError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
        U9FlxArchiveError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else Path(f"{args.terrain}_map.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(output)
    metadata = Path(args.metadata) if args.metadata else output.with_suffix(".json")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    report = result.diagnostics.to_dict()
    report.update(
        {
            "terrain_file": str(Path(args.terrain).resolve()),
            "fixed_file": str(Path(args.fixed).resolve()) if args.fixed else None,
            "nonfixed_file": (
                str(Path(args.nonfixed).resolve()) if args.nonfixed else None
            ),
            "object_model_file": (
                str(Path(models_path).resolve()) if models_path else None
            ),
            "object_types_file": (
                str(Path(types_path).resolve()) if types_path else None
            ),
            "texture_file": str(textures.archive_path.resolve()),
            "palette_file": (
                str(textures.palette_path.resolve()) if textures.palette_path else None
            ),
            "sdinfo_file": (
                str(textures.sdinfo_path.resolve()) if textures.sdinfo_path else None
            ),
        }
    )
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(
        f"Rendered {diagnostics.terrain_name or '(unnamed)'}: "
        f"{diagnostics.image_width}x{diagnostics.image_height} -> {output}"
    )
    print(f"  Metadata        : {metadata}")
    print(f"  Texture keys    : {diagnostics.texture_keys}")
    print(
        f"  Missing textures: {len(diagnostics.missing_texture_keys)} key(s), "
        f"{diagnostics.missing_texture_cells} cell(s)"
    )
    if diagnostics.water_enabled:
        print(
            f"  Global water    : Z {diagnostics.water_level}, "
            f"texture {diagnostics.water_texture_id} frame {diagnostics.water_frame}"
        )
        print(
            f"  Water coverage  : {diagnostics.water_visible_cells} cell(s), "
            f"{diagnostics.water_visible_pixels} output pixel(s)"
        )
        print(
            f"  Water texture   : "
            f"{'MISSING (diagnostic magenta)' if diagnostics.water_texture_missing else 'decoded'}"
        )
    if args.fixed:
        print(
            f"  Fixed objects   : {diagnostics.fixed_objects} "
            f"({diagnostics.fixed_objects_in_bounds} in bounds, "
            f"{diagnostics.fixed_objects_out_of_bounds} outside)"
        )
        print(f"  Chunk mismatches: {diagnostics.fixed_chunk_position_mismatches}")
    if args.nonfixed:
        print(f"  Nonfixed indexed: {diagnostics.nonfixed_indexed_entities}")
        print(
            f"  Unlinked records : {diagnostics.nonfixed_unlinked_entities} "
            f"({'included' if args.include_unlinked_nonfixed else 'excluded'} from markers)"
        )
        print(f"  Markers drawn    : {diagnostics.nonfixed_markers_drawn}")
        print(
            f"  Known allocated : {diagnostics.nonfixed_allocated_entities} "
            f"({diagnostics.nonfixed_entities_in_bounds} in bounds, "
            f"{diagnostics.nonfixed_entities_out_of_bounds} outside)"
        )
        print(
            "  Chunk mismatches: "
            f"{diagnostics.nonfixed_chunk_position_mismatches} nonfixed"
        )
        print(f"  Incomplete chunks: {diagnostics.nonfixed_incomplete_chunks}")
    if diagnostics.object_footprints_enabled:
        print(
            f"  Model footprints: {diagnostics.object_footprints_drawn} shown / "
            f"{diagnostics.object_footprints_resolved_total} resolved "
            f"({diagnostics.object_footprints_filtered_out} filtered)"
        )
        print(
            f"  Displayed models: {len(diagnostics.object_model_ids_drawn)} distinct; "
            f"source={diagnostics.object_footprint_source_filter}, "
            f"style={diagnostics.object_footprint_style}"
        )
        if args.fixed:
            print(
                f"  Fixed resolved  : {diagnostics.fixed_footprints_resolved} "
                f"({diagnostics.fixed_footprints_without_model} type(s) without a model, "
                f"{diagnostics.fixed_footprints_unresolved} unresolved)"
            )
        if args.nonfixed:
            print(
                f"  Nonfixed resolved: {diagnostics.nonfixed_footprints_resolved} "
                f"({diagnostics.nonfixed_footprints_unresolved} unresolved)"
            )
        if diagnostics.missing_object_model_ids:
            print(
                "  Missing model IDs: "
                + ", ".join(
                    str(value) for value in diagnostics.missing_object_model_ids
                )
            )
        if diagnostics.malformed_object_model_ids:
            print(
                "  Malformed models : "
                + ", ".join(
                    str(value) for value in diagnostics.malformed_object_model_ids
                )
            )
    if diagnostics.object_meshes_enabled:
        print(
            f"  Object meshes   : {diagnostics.object_mesh_placements_drawn} drawn / "
            f"{diagnostics.object_mesh_placements_selected} selected at LOD "
            f"{diagnostics.object_mesh_lod}"
        )
        print(
            f"  Mesh triangles  : {diagnostics.object_mesh_triangles_drawn} visible / "
            f"{diagnostics.object_mesh_triangles_considered} considered; "
            f"{diagnostics.object_mesh_pixels_drawn} pixel writes"
        )
        if diagnostics.missing_object_texture_keys:
            print(
                "  Object textures : "
                f"{len(diagnostics.missing_object_texture_keys)} missing frame(s)"
            )
    return 0


def cmd_map_export_glb(args: SimpleNamespace) -> int:
    """Export textured terrain, water, and placed models as a Y-up GLB."""
    models_path = getattr(args, "models", None)
    types_path = getattr(args, "types", None)
    for label, path in (
        ("Terrain", args.terrain),
        ("Fixed", args.fixed),
        ("Nonfixed", args.nonfixed),
        ("Models", models_path),
        ("Types", types_path),
    ):
        if path is not None and not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 1

    terrain_dir = Path(args.terrain).resolve().parent
    textures_path = args.textures
    if textures_path is None:
        match = _find_case_insensitive_file(terrain_dir, "bitmap16.flx")
        textures_path = str(match) if match is not None else None
    if textures_path is None or not os.path.isfile(textures_path):
        print(
            "ERROR: bitmap16.flx was not found beside the terrain file; "
            "pass --textures",
            file=sys.stderr,
        )
        return 1

    has_object_input = args.fixed is not None or args.nonfixed is not None
    if args.objects and has_object_input:
        if models_path is None:
            match = _find_case_insensitive_file(terrain_dir, "sappear.flx")
            models_path = str(match) if match is not None else None
        if models_path is None or not os.path.isfile(models_path):
            print(
                "ERROR: sappear.flx was not found beside the terrain file; "
                "pass --models",
                file=sys.stderr,
            )
            return 1
        if args.fixed is not None and types_path is None:
            match = _find_case_insensitive_file(terrain_dir, "TYPES.DAT")
            types_path = str(match) if match is not None else None
        if args.fixed is not None and (
            types_path is None or not os.path.isfile(types_path)
        ):
            print(
                "ERROR: TYPES.DAT was not found beside the terrain file; pass --types",
                file=sys.stderr,
            )
            return 1

    output = Path(args.output) if args.output else Path(f"{args.terrain}_map.glb")
    try:
        scene = U9RegionScene.from_files(
            args.terrain,
            fixed_path=args.fixed,
            nonfixed_path=args.nonfixed,
        )
        textures = U9MapTextureSource.from_file(
            textures_path,
            palette_path=args.palette,
            sdinfo_path=args.sdinfo,
        )
        cell_region = U9CellRegion.parse(args.cell_region) if args.cell_region else None
        model_source = (
            U9SappearModelSource.from_file(models_path)
            if args.objects and has_object_input and models_path is not None
            else None
        )
        object_types = (
            U9TypesDat.from_file(types_path)
            if args.objects and args.fixed is not None and types_path is not None
            else None
        )
        object_filter = U9ObjectFootprintFilter(
            source=args.object_source,
            type_ids=frozenset(args.object_type or ()),
            model_ids=frozenset(args.object_model or ()),
        )
        result = export_region_glb(
            scene,
            textures,
            output,
            cell_region=cell_region,
            include_terrain=args.terrain_layer,
            include_water=args.water,
            water_frame=args.water_frame,
            include_objects=args.objects,
            object_models=model_source,
            object_types=object_types,
            object_filter=object_filter,
            include_unlinked_nonfixed=args.include_unlinked_nonfixed,
            lod_level=args.lod,
            coordinate_scale=args.coordinate_scale,
        )
    except (
        OSError,
        U9FixedError,
        U9NonfixedError,
        U9TerrainError,
        U9RegionSceneError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
        U9FlxArchiveError,
        U9GlbExportError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    metadata = Path(args.metadata) if args.metadata else output.with_suffix(".json")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    manifest = result.manifest()
    manifest["sources"] = {
        "terrain": str(Path(args.terrain).resolve()),
        "fixed": str(Path(args.fixed).resolve()) if args.fixed else None,
        "nonfixed": str(Path(args.nonfixed).resolve()) if args.nonfixed else None,
        "models": str(Path(models_path).resolve()) if models_path else None,
        "types": str(Path(types_path).resolve()) if types_path else None,
        "textures": str(Path(textures_path).resolve()),
        "palette": (
            str(textures.palette_path.resolve()) if textures.palette_path else None
        ),
        "sdinfo": (
            str(textures.sdinfo_path.resolve()) if textures.sdinfo_path else None
        ),
    }
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(
        f"Exported {diagnostics.terrain_name or '(unnamed)'} cells "
        f"{diagnostics.cell_region} -> {result.glb_path}"
    )
    print(f"  Manifest         : {metadata}")
    print(
        f"  Terrain          : {diagnostics.terrain_cells_exported} cell(s), "
        f"{diagnostics.terrain_triangles} triangle(s), "
        f"{diagnostics.terrain_materials} material(s)"
    )
    if diagnostics.water_enabled:
        print(
            f"  Water            : Z {diagnostics.water_level}, "
            f"{diagnostics.water_triangles} triangle(s)"
        )
    if diagnostics.objects_enabled:
        print(
            f"  Objects          : {diagnostics.object_placements_exported} exported / "
            f"{diagnostics.object_placements_in_region} selected in region, "
            f"{diagnostics.object_triangles} triangle(s)"
        )
        print(
            f"  Object models    : "
            f"{len(diagnostics.object_model_ids_exported)} distinct"
        )
        print(
            f"  Object meshes    : {diagnostics.object_meshes_exported} shared mesh(es) / "
            f"{diagnostics.object_parts_exported} placement part node(s)"
        )
    print(
        f"  Scene geometry   : {diagnostics.geometry_meshes} mesh(es) / "
        f"{diagnostics.geometry_nodes} node(s)"
    )
    if diagnostics.missing_texture_keys:
        print(
            f"  Missing textures : {len(diagnostics.missing_texture_keys)} "
            "(magenta fallback; see manifest)"
        )
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


# ============================================================================
# CLI COMMANDS -- FLX PACKING
# ============================================================================

_FLX_ENTRY_RE = re.compile(r"^(\d+)\.bin$", re.IGNORECASE)


def _entries_from_dir(directory: str) -> Optional[dict]:
    """Read NNNNN.bin files back into an {index: blob} table."""
    if not os.path.isdir(directory):
        print(f"ERROR: Directory not found: {directory}", file=sys.stderr)
        return None
    entries: dict = {}
    skipped = 0
    for name in sorted(os.listdir(directory)):
        match = _FLX_ENTRY_RE.match(name)
        if match is None:
            skipped += 1
            continue
        with open(os.path.join(directory, name), "rb") as f:
            entries[int(match.group(1))] = f.read()
    if not entries:
        print(f"ERROR: No NNNNN.bin entry files in {directory}", file=sys.stderr)
        return None
    if skipped:
        print(f"  (ignored {skipped} file(s) not named NNNNN.bin)")
    return entries


def cmd_flx_pack(args: SimpleNamespace) -> int:
    """Build an FLX archive from a directory of NNNNN.bin entry files."""
    entries = _entries_from_dir(args.directory)
    if entries is None:
        return 1
    try:
        written = write_flx(
            args.output, entries, count=args.count, comment=args.comment
        )
    except U9FlxWriteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    slots = args.count if args.count is not None else max(entries) + 1
    print(
        f"Packed {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
        f"into {slots} slot(s) -> {args.output} ({written} bytes)"
    )
    if args.count is None:
        print("  Slot count was inferred. Pass --count to match an original archive.")
    return 0


def cmd_flx_repack(args: SimpleNamespace) -> int:
    """Rebuild an FLX archive, optionally replacing entries, and verify the result."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    try:
        archive = U9FlxArchive.from_file(args.file)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    replacements: dict = {}
    if args.replace:
        entries = _entries_from_dir(args.replace)
        if entries is None:
            return 1
        replacements = entries

    try:
        data = repack(archive, replacements)
    except U9FlxWriteError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    with open(args.file, "rb") as f:
        original = f.read()

    identical = data == original
    equivalent = repack_equivalent(original, data)

    out_path = args.output or (Path(args.file).stem + "_repacked.flx")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    print(
        f"{args.file} -- {len(archive.used_entry_indices())} used of "
        f"{archive.num_entries} slot(s)"
    )
    if replacements:
        print(
            f"  Replaced        : {len(replacements)} entr"
            f"{'y' if len(replacements) == 1 else 'ies'}"
        )
    print(
        f"  Written         : {out_path} ({len(data)} bytes, "
        f"{len(data) - len(original):+d})"
    )
    if not replacements:
        print(f"  Byte-identical  : {'yes' if identical else 'no'}")
        print(f"  Same contents   : {'yes' if equivalent else 'NO -- THIS IS A BUG'}")
        if not identical and equivalent:
            print("  The rebuild drops bytes no directory entry points at, and may")
            print("  reorder payloads. Every entry the archive declares is preserved.")
    return 0 if (equivalent or replacements) else 1


# ============================================================================
# CLI COMMANDS -- TEXTURE IMPORT (PNG -> bitmap/terrain-panel FLX)
# ============================================================================


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

    palette = _load_palette(args.palette, args.textures)
    selectors = _load_selectors(args.textures)
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
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract one entry from an Ultima 9 FLX archive."""
    raise SystemExit(
        cmd_flx_extract(SimpleNamespace(file=file, index=index, output=output))
    )


@u9_app.command("flx-extract-all")
def flx_extract_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 .flx/.FLX file")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: <file>_entries/)"
        ),
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


@u9_app.command("palette-info")
def palette_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/ankh.pal")],
    duplicates: Annotated[
        bool,
        typer.Option(
            "-d", "--duplicates", help="List every repeated colour and its indices"
        ),
    ] = False,
) -> None:
    """Inspect a U9 ankh.pal colour table and its duplicate entries."""
    raise SystemExit(
        cmd_palette_info(SimpleNamespace(file=file, duplicates=duplicates))
    )


@u9_app.command("palette-export")
def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/ankh.pal")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: current directory)"
        ),
    ] = None,
    swatch_size: Annotated[
        int,
        typer.Option("--swatch-size", help="Pixel size of each colour square"),
    ] = 16,
) -> None:
    """Export a U9 palette as a 16x16 PNG swatch and text table."""
    raise SystemExit(
        cmd_palette_export(
            SimpleNamespace(file=file, output=output, swatch_size=swatch_size)
        )
    )


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
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <file>_wav/)"),
    ] = None,
) -> None:
    """Extract every PCM-encoded entry in a sound archive as a playable WAV."""
    raise SystemExit(cmd_sound_extract_pcm(SimpleNamespace(file=file, output=output)))


@u9_app.command("sound-extract")
def sound_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 sound/*.flx file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <file>_wav/)"),
    ] = None,
    entry: Annotated[
        Optional[int],
        typer.Option("--entry", help="Extract only this FLX entry ID"),
    ] = None,
    format: Annotated[
        str,
        typer.Option("-f", "--format", help="wav, payload, or record"),
    ] = "wav",
) -> None:
    """Extract decoded WAV, native payload, or complete U9 sound records."""
    raise SystemExit(
        cmd_sound_extract(
            SimpleNamespace(file=file, output=output, entry=entry, format=format)
        )
    )


@u9_app.command("sound-report")
def sound_report_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Audio FLX file, sound directory, or unpacked data root"),
    ],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output CSV or JSON report path"),
    ],
    entry: Annotated[
        Optional[int],
        typer.Option("--entry", help="Limit each discovered archive to one entry ID"),
    ] = None,
    format: Annotated[
        str,
        typer.Option("-f", "--format", help="csv or json"),
    ] = "csv",
) -> None:
    """Export dynamic record sizes, codecs, duration, and SFX-template links."""
    raise SystemExit(
        cmd_sound_report(
            SimpleNamespace(source=source, output=output, entry=entry, format=format)
        )
    )


@u9_app.command("sound-import")
def sound_import_cmd(
    archive: Annotated[str, typer.Argument(help="Target Speech/sfx/music FLX")],
    entry_id: Annotated[int, typer.Argument(help="Existing entry ID to replace")],
    audio: Annotated[
        str,
        typer.Argument(help="PCM WAV, native .payload.bin, or complete .record.bin"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output archive (default: <stem>_patched.flx)"
        ),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option(
            "--description", help="Replacement record description for WAV input"
        ),
    ] = None,
) -> None:
    """Replace one existing U9 sound record and rebuild its FLX archive."""
    raise SystemExit(
        cmd_sound_import(
            SimpleNamespace(
                archive=archive,
                entry_id=entry_id,
                audio=audio,
                output=output,
                description=description,
            )
        )
    )


@u9_app.command("sound-import-batch")
def sound_import_batch_cmd(
    archive: Annotated[str, typer.Argument(help="Target Speech/sfx/music FLX")],
    directory: Annotated[
        str,
        typer.Argument(
            help="Directory of <entry>[_label].wav/.payload.bin/.record.bin files"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output archive (default: <stem>_patched.flx)"
        ),
    ] = None,
) -> None:
    """Replace many existing sound records and repack the FLX once."""
    raise SystemExit(
        cmd_sound_import_batch(
            SimpleNamespace(archive=archive, directory=directory, output=output)
        )
    )


@u9_app.command("model-info")
def model_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Model ID (0-7999) to inspect")],
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="Path to static/TYPES.DAT (with --typenames, shows possible name(s))",
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="Path to static/TYPENAME.FLX (with --types, shows possible name(s))",
        ),
    ] = None,
) -> None:
    """Print a model's limb/LOD/material/texture summary."""
    raise SystemExit(
        cmd_model_info(
            SimpleNamespace(
                file=file, model_id=model_id, types=types, typenames=typenames
            )
        )
    )


@u9_app.command("model-material-report")
def model_material_report_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Path to static/sappear.flx or its static directory"),
    ],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output CSV or JSON report path"),
    ],
    model: Annotated[
        Optional[int],
        typer.Option("--model", help="Limit the report to one model ID"),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture archive or directory (default: beside sappear.flx)",
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
            "--only", help="Filter: animated, textured, unresolved, or errors"
        ),
    ] = None,
) -> None:
    """Export model materials and their per-tier texture/animation metadata."""
    raise SystemExit(
        cmd_model_material_report(
            SimpleNamespace(
                source=source,
                output=output,
                model=model,
                textures=textures,
                types=types,
                typenames=typenames,
                format=fmt,
                only=only,
            )
        )
    )


@u9_app.command("model-export")
def model_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Model ID (0-7999) to export")],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--textures",
            help="Path to a texture archive: bitmap16.flx, bitmapsh.flx or "
            "bitmapC.flx -- all three decode, and hold the same textures",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="Path to static/TYPES.DAT (with --typenames, names the output folder/files)",
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="Path to static/TYPENAME.FLX (with --types, names the output folder/files)",
        ),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[
        str, typer.Option("-f", "--format", help="obj, stl, or both")
    ] = "obj",
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: model_<id>[_<name>]/)"
        ),
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
                file=file,
                model_id=model_id,
                textures=textures,
                palette=palette,
                types=types,
                typenames=typenames,
                lod=lod,
                format=fmt,
                output=output,
                preview=preview,
            )
        )
    )


@u9_app.command("model-export-all")
def model_export_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--textures",
            help="Path to a texture archive: bitmap16.flx, bitmapsh.flx or "
            "bitmapC.flx -- all three decode, and hold the same textures",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="Path to static/TYPES.DAT (with --typenames, names each output folder/files)",
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="Path to static/TYPENAME.FLX (with --types, names each output folder/files)",
        ),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[
        str, typer.Option("-f", "--format", help="obj, stl, or both")
    ] = "obj",
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: model_export/)"
        ),
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
                file=file,
                textures=textures,
                palette=palette,
                types=types,
                typenames=typenames,
                lod=lod,
                format=fmt,
                output=output,
                preview=preview,
            )
        )
    )


@u9_app.command("texture-info")
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


@u9_app.command("texture-frame-report")
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


@u9_app.command("texture-export")
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


@u9_app.command("icon-list")
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


@u9_app.command("icon-export")
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


@u9_app.command("icon-export-all")
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


@u9_app.command("nonfixed-info")
def nonfixed_info_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")
    ],
) -> None:
    """Summarize a U9 runtime region and its page allocator."""
    raise SystemExit(cmd_nonfixed_info(SimpleNamespace(file=file)))


@u9_app.command("nonfixed-chunks")
def nonfixed_chunks_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")
    ],
) -> None:
    """List every populated chunk in a U9 runtime region with its counts."""
    raise SystemExit(cmd_nonfixed_chunks(SimpleNamespace(file=file)))


@u9_app.command("nonfixed-entities")
def nonfixed_entities_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")
    ],
    chunk: Annotated[
        Optional[str],
        typer.Option("-c", "--chunk", help="Restrict to one chunk, as 'X,Y'"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
    include_unlinked: Annotated[
        bool,
        typer.Option(
            "--include-unlinked",
            help="Include allocated records absent from the live spatial index",
        ),
    ] = False,
) -> None:
    """List the dynamic objects stored in a U9 runtime region."""
    raise SystemExit(
        cmd_nonfixed_entities(
            SimpleNamespace(
                file=file,
                chunk=chunk,
                typenames=typenames,
                limit=limit,
                include_unlinked=include_unlinked,
            )
        )
    )


@u9_app.command("nonfixed-diff")
def nonfixed_diff_cmd(
    left: Annotated[str, typer.Argument(help="First runtime/nonfixed.<region> file")],
    right: Annotated[str, typer.Argument(help="Second runtime/nonfixed.<region> file")],
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
) -> None:
    """Compare two U9 runtime regions entity by entity (e.g. patched vs original)."""
    raise SystemExit(
        cmd_nonfixed_diff(SimpleNamespace(left=left, right=right, typenames=typenames))
    )


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
        Optional[int],
        typer.Option("-i", "--id", help="Show only the point with this trigger ID"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 highway navigation points and their world positions."""
    raise SystemExit(cmd_highway_points(SimpleNamespace(file=file, id=id, limit=limit)))


@u9_app.command("highway-routes")
def highway_routes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
    id: Annotated[
        Optional[int],
        typer.Option("-i", "--id", help="Only routes visiting this trigger ID"),
    ] = None,
    paths: Annotated[
        bool,
        typer.Option("-p", "--paths", help="Print each route's full node path"),
    ] = False,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum routes to print"),
    ] = None,
) -> None:
    """List the precomputed routes through the U9 highway graph."""
    raise SystemExit(
        cmd_highway_routes(SimpleNamespace(file=file, id=id, paths=paths, limit=limit))
    )


@u9_app.command("animation-list")
def animation_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 animation clips, source paths, frame counts and animated parts."""
    raise SystemExit(cmd_animation_list(SimpleNamespace(file=file, limit=limit)))


@u9_app.command("animation-show")
def animation_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    id: Annotated[int, typer.Argument(help="Animation ID (the FLX entry index)")],
    part: Annotated[
        Optional[int],
        typer.Option("-p", "--part", help="Dump transform frames for this part ID"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum parts or frames to print"),
    ] = None,
) -> None:
    """Show one U9 animation's structure or one part's transform frames."""
    raise SystemExit(
        cmd_animation_show(SimpleNamespace(file=file, id=id, part=part, limit=limit))
    )


@u9_app.command("trigger-list")
def trigger_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    all: Annotated[
        bool,
        typer.Option("-a", "--all", help="Include empty triggers"),
    ] = False,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 trigger scripts; the trigger ID is the FLX entry index."""
    raise SystemExit(cmd_trigger_list(SimpleNamespace(file=file, all=all, limit=limit)))


@u9_app.command("trigger-show")
def trigger_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    id: Annotated[
        int, typer.Argument(help="Trigger ID, as carried by a runtime entity")
    ],
) -> None:
    """Dump one U9 trigger script's records."""
    raise SystemExit(cmd_trigger_show(SimpleNamespace(file=file, id=id)))


@u9_app.command("trigger-opcodes")
def trigger_opcodes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum opcodes to print"),
    ] = None,
) -> None:
    """Report trigger opcode frequency across the whole archive."""
    raise SystemExit(cmd_trigger_opcodes(SimpleNamespace(file=file, limit=limit)))


@u9_app.command("activity-list")
def activity_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
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
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum names to print"),
    ] = None,
) -> None:
    """Report U9 activity step-opcode and sequence-name frequency."""
    raise SystemExit(cmd_activity_opcodes(SimpleNamespace(file=file, limit=limit)))


@u9_app.command("script-research-export")
def script_research_export_cmd(
    triggers: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    activities: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    output: Annotated[
        str,
        typer.Option(
            "-o", "--output", help="Directory for CSV and JSON evidence tables"
        ),
    ] = "u9-script-research",
) -> None:
    """Export lossless trigger/activity evidence tables for Ghidra research."""
    raise SystemExit(
        cmd_script_research_export(
            SimpleNamespace(
                triggers=triggers,
                activities=activities,
                output=output,
            )
        )
    )


@u9_app.command("npc-list")
def npc_list_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
    region: Annotated[
        Optional[int],
        typer.Option("-r", "--region", help="Only NPCs in this region"),
    ] = None,
    npc_class: Annotated[
        Optional[int],
        typer.Option("-c", "--class", help="Only NPCs with this class_id"),
    ] = None,
    all: Annotated[
        bool, typer.Option("-a", "--all", help="Include unnamed/empty slots")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List U9 NPC records; the record index is also the activity set index."""
    raise SystemExit(
        cmd_npc_list(
            SimpleNamespace(
                file=file,
                save=save,
                region=region,
                npc_class=npc_class,
                all=all,
                limit=limit,
            )
        )
    )


@u9_app.command("npc-show")
def npc_show_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    index: Annotated[int, typer.Argument(help="NPC record index")],
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
) -> None:
    """Print one U9 NPC record's decoded fields."""
    raise SystemExit(cmd_npc_show(SimpleNamespace(file=file, index=index, save=save)))


@u9_app.command("npc-classes")
def npc_classes_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
    members: Annotated[
        int,
        typer.Option("-m", "--members", help="Member names to preview per class"),
    ] = 8,
) -> None:
    """Group U9 NPCs by class_id and preview each group's members."""
    raise SystemExit(
        cmd_npc_classes(SimpleNamespace(file=file, save=save, members=members))
    )


@u9_app.command("npc-diff")
def npc_diff_cmd(
    file: Annotated[str, typer.Argument(help="Path to the shipped runtime/NPC.FLX")],
    save_file: Annotated[
        str, typer.Argument(help="Path to a savegame processes.dat or u9game*.sav")
    ],
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum moved NPCs to print")
    ] = None,
) -> None:
    """Compare the shipped U9 NPC table against a savegame's live copy."""
    raise SystemExit(
        cmd_npc_diff(SimpleNamespace(file=file, save_file=save_file, limit=limit))
    )


@u9_app.command("npc-csv")
def npc_csv_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output CSV path (default: <file>_npcs.csv)"
        ),
    ] = None,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
    all: Annotated[
        bool, typer.Option("-a", "--all", help="Include unnamed/blank slots")
    ] = False,
) -> None:
    """Export every U9 NPC record to CSV, decoded fields plus the raw record."""
    raise SystemExit(
        cmd_npc_csv(SimpleNamespace(file=file, output=output, save=save, all=all))
    )


@u9_app.command("sdinfo-list")
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


@u9_app.command("sdinfo-show")
def sdinfo_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/sdInfo*.flx table")],
    index: Annotated[
        int,
        typer.Argument(help="Texture index -- the same index as in the bitmap archive"),
    ],
) -> None:
    """Print one U9 texture's metadata record."""
    raise SystemExit(cmd_sdinfo_show(SimpleNamespace(file=file, index=index)))


@u9_app.command("sdinfo-verify")
def sdinfo_verify_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/sdInfo*.flx table")],
    textures: Annotated[
        str, typer.Argument(help="Path to its partner bitmap*.flx archive")
    ],
) -> None:
    """Cross-check a U9 texture metadata table against its bitmap archive."""
    raise SystemExit(cmd_sdinfo_verify(SimpleNamespace(file=file, textures=textures)))


@u9_app.command("text-list")
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


@u9_app.command("text-blocks")
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


@u9_app.command("text-search")
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


@u9_app.command("text-export")
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


@u9_app.command("fixed-info")
def fixed_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
) -> None:
    """Summarize a U9 static region: chunk grid, pages and object totals."""
    raise SystemExit(cmd_fixed_info(SimpleNamespace(file=file)))


@u9_app.command("fixed-chunks")
def fixed_chunks_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    by_grid: Annotated[
        bool,
        typer.Option("-g", "--by-grid", help="Order by grid position, not table slot"),
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List the populated chunks in a U9 static region."""
    raise SystemExit(
        cmd_fixed_chunks(SimpleNamespace(file=file, by_grid=by_grid, limit=limit))
    )


@u9_app.command("fixed-objects")
def fixed_objects_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    chunk: Annotated[
        Optional[str],
        typer.Option("-c", "--chunk", help="Restrict to one chunk, as 'X,Y'"),
    ] = None,
    type: Annotated[
        Optional[int],
        typer.Option("-t", "--type", help="Only objects of this type index"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List the immovable objects in a U9 static region."""
    raise SystemExit(
        cmd_fixed_objects(
            SimpleNamespace(
                file=file, chunk=chunk, type=type, typenames=typenames, limit=limit
            )
        )
    )


@u9_app.command("fixed-types")
def fixed_types_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum types to print")
    ] = None,
) -> None:
    """Report which object types a U9 static region uses."""
    raise SystemExit(
        cmd_fixed_types(SimpleNamespace(file=file, typenames=typenames, limit=limit))
    )


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
    index: Annotated[
        Optional[int], typer.Option("-i", "--index", help="Chunk index to dump")
    ] = None,
    tile: Annotated[
        Optional[str],
        typer.Option("-t", "--tile", help="Dump the chunk a tile uses, as 'X,Y'"),
    ] = None,
    field: Annotated[
        str,
        typer.Option(
            "-f",
            "--field",
            help=(
                "Field: height, texture, frame, hole, swap, mirror, "
                "uv-rotation, split, spare or raw"
            ),
        ),
    ] = "height",
) -> None:
    """Dump one 16x16 chunk of a U9 region height map."""
    choices = (
        "height",
        "texture",
        "frame",
        "hole",
        "swap",
        "mirror",
        "uv-rotation",
        "split",
        "spare",
        "raw",
    )
    if field not in choices:
        print(
            f"ERROR: --field must be {', '.join(choices)}, got {field!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(
        cmd_terrain_chunk(
            SimpleNamespace(file=file, index=index, tile=tile, field=field)
        )
    )


@u9_app.command("terrain-textures")
def terrain_textures_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    sdinfo: Annotated[
        Optional[str],
        typer.Option(
            "--sdinfo", help="Path to a matching static/sdInfo*.flx for sizes"
        ),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum textures to print")
    ] = None,
) -> None:
    """Report which ground textures a U9 region paints with."""
    raise SystemExit(
        cmd_terrain_textures(SimpleNamespace(file=file, sdinfo=sdinfo, limit=limit))
    )


@u9_app.command("terrain-heightmap")
def terrain_heightmap_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    scale: Annotated[
        int, typer.Option("-s", "--scale", help="Nearest-neighbour magnification")
    ] = 1,
) -> None:
    """Render a U9 region height map to a greyscale PNG."""
    raise SystemExit(
        cmd_terrain_heightmap(SimpleNamespace(file=file, output=output, scale=scale))
    )


@u9_app.command("terrain-export")
def terrain_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output CSV path"),
    ] = None,
) -> None:
    """Export every point of a U9 region height map to CSV."""
    raise SystemExit(cmd_terrain_export(SimpleNamespace(file=file, output=output)))


@u9_app.command("map-atlas")
def map_atlas_cmd(
    static: Annotated[
        str,
        typer.Argument(help="Directory containing terrain.N and fixed.N files"),
    ],
    runtime: Annotated[
        Optional[str],
        typer.Option(
            "--runtime", help="Directory containing matching nonfixed.N files"
        ),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture tier FLX (default: static/bitmap16.flx)",
        ),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option(
            "--models",
            help="sappear.flx for object meshes/footprints (auto-discovered in static)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="TYPES.DAT for fixed model lookup (auto-discovered in static)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette", help="ankh.pal (auto-discovered beside textures)"
        ),
    ] = None,
    sdinfo: Annotated[
        Optional[str],
        typer.Option("--sdinfo", help="Matching sdInfo*.flx (auto-discovered)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory (default: ./u9_map_atlas)",
        ),
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Manifest path (default: OUTPUT/atlas.json)"),
    ] = None,
    region_ids: Annotated[
        Optional[list[int]],
        typer.Option(
            "--region",
            min=0,
            help="Region ID to render (repeatable; default: every terrain.N)",
        ),
    ] = None,
    pixels_per_cell: Annotated[
        int,
        typer.Option(
            "--pixels-per-cell",
            min=1,
            max=MAX_MAP_PIXELS_PER_CELL,
            help="Full preview detail per 128-unit terrain cell",
        ),
    ] = DEFAULT_ATLAS_PIXELS_PER_CELL,
    thumbnail_size: Annotated[
        int,
        typer.Option(
            "--thumbnail-size",
            min=32,
            max=1024,
            help="Square map area for each labelled atlas card",
        ),
    ] = 224,
    columns: Annotated[
        int,
        typer.Option("--columns", min=1, max=32, help="Atlas card columns"),
    ] = 6,
    hillshade: Annotated[
        bool,
        typer.Option("--hillshade/--no-hillshade", help="Shade decoded terrain relief"),
    ] = True,
    hillshade_strength: Annotated[
        float,
        typer.Option(
            "--hillshade-strength",
            min=0.0,
            max=1.0,
            help="Relief shading blend",
        ),
    ] = 0.55,
    water: Annotated[
        bool,
        typer.Option("--water/--no-water", help="Render each region's water surface"),
    ] = True,
    water_frame: Annotated[
        int,
        typer.Option("--water-frame", min=0, help="Water texture frame"),
    ] = 0,
    fixed_markers: Annotated[
        bool,
        typer.Option(
            "--fixed-markers/--no-fixed-markers",
            help="Draw fixed-object anchor markers",
        ),
    ] = True,
    fixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--fixed-marker-radius", min=1, help="Fixed marker radius in output pixels"
        ),
    ] = 1,
    nonfixed_markers: Annotated[
        bool,
        typer.Option(
            "--nonfixed-markers/--no-nonfixed-markers",
            help="Draw indexed nonfixed placement markers",
        ),
    ] = True,
    nonfixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--nonfixed-marker-radius",
            min=1,
            help="Nonfixed marker radius in output pixels",
        ),
    ] = 1,
    include_unlinked_nonfixed: Annotated[
        bool,
        typer.Option(
            "--include-unlinked-nonfixed",
            help="Also draw allocated records absent from the spatial index",
        ),
    ] = False,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects/--no-objects",
            help="Rasterize textured sappear model triangles at object placements",
        ),
    ] = False,
    object_lod: Annotated[
        int,
        typer.Option(
            "--object-lod",
            min=0,
            help="sappear model LOD used by --objects (LOD 0 preserves coverage)",
        ),
    ] = 0,
    object_footprints: Annotated[
        bool,
        typer.Option(
            "--object-footprints/--no-object-footprints",
            help="Draw transformed sappear model bounds",
        ),
    ] = False,
    object_footprint_source: Annotated[
        str,
        typer.Option(
            "--object-source", help="Object source filter: all, fixed, or nonfixed"
        ),
    ] = "all",
    object_type_ids: Annotated[
        Optional[list[int]],
        typer.Option("--object-type", help="Type ID filter (repeatable)"),
    ] = None,
    object_model_ids: Annotated[
        Optional[list[int]],
        typer.Option("--object-model", help="sappear model ID filter (repeatable)"),
    ] = None,
    object_footprint_style: Annotated[
        str,
        typer.Option(
            "--object-footprint-style", help="Footprint style: outline or fill"
        ),
    ] = "outline",
    cell_grid: Annotated[
        bool,
        typer.Option(
            "--cell-grid/--no-cell-grid",
            help="Overlay every terrain-cell boundary (needs 4+ pixels per cell)",
        ),
    ] = False,
    tile_grid: Annotated[
        bool,
        typer.Option(
            "--tile-grid/--no-tile-grid",
            help="Overlay 16x16-cell tile/chunk-placement boundaries",
        ),
    ] = False,
    tile_coordinates: Annotated[
        bool,
        typer.Option(
            "--tile-coordinates/--no-tile-coordinates",
            help=(
                "Label each tile placement with its stored x,y coordinate "
                "and cell origin (needs 4+ pixels per cell)"
            ),
        ),
    ] = False,
    chunk_labels: Annotated[
        bool,
        typer.Option(
            "--chunk-labels/--no-chunk-labels",
            help="Label each tile with its referenced stored chunk ID (needs 2+ pixels per cell)",
        ),
    ] = False,
    flip_y: Annotated[
        bool,
        typer.Option(
            "--flip-y/--no-flip-y",
            help="Invert U9 Y into image rows as the legacy editor does",
        ),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Stop at the first malformed region instead of making an error card",
        ),
    ] = False,
) -> None:
    """Render all discovered U9 regions as a labelled visual catalogue."""
    raise SystemExit(
        cmd_map_atlas(
            SimpleNamespace(
                static=static,
                runtime=runtime,
                textures=textures,
                models=models,
                types=types,
                palette=palette,
                sdinfo=sdinfo,
                output=output,
                metadata=metadata,
                region_ids=region_ids,
                pixels_per_cell=pixels_per_cell,
                thumbnail_size=thumbnail_size,
                columns=columns,
                hillshade=hillshade,
                hillshade_strength=hillshade_strength,
                water=water,
                water_frame=water_frame,
                fixed_markers=fixed_markers,
                fixed_marker_radius=fixed_marker_radius,
                nonfixed_markers=nonfixed_markers,
                nonfixed_marker_radius=nonfixed_marker_radius,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                objects=objects,
                object_lod=object_lod,
                object_footprints=object_footprints,
                object_footprint_source=object_footprint_source,
                object_type_ids=object_type_ids,
                object_model_ids=object_model_ids,
                object_footprint_style=object_footprint_style,
                cell_grid=cell_grid,
                tile_grid=tile_grid,
                tile_coordinates=tile_coordinates,
                chunk_labels=chunk_labels,
                flip_y=flip_y,
                strict=strict,
            )
        )
    )


@u9_app.command("map-render")
def map_render_cmd(
    terrain: Annotated[
        str, typer.Argument(help="Path to a static/terrain.<region> file")
    ],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture tier FLX (default: adjacent bitmap16.flx)",
        ),
    ] = None,
    fixed: Annotated[
        Optional[str],
        typer.Option("--fixed", help="Matching static/fixed.<region> overlay"),
    ] = None,
    nonfixed: Annotated[
        Optional[str],
        typer.Option(
            "--nonfixed",
            help="Matching runtime or savegame nonfixed.<region> overlay",
        ),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option(
            "--models",
            help="sappear.flx for object meshes/footprints (auto-discovered beside terrain)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="TYPES.DAT for fixed model lookup (auto-discovered beside terrain)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette", help="ankh.pal (auto-discovered beside textures)"
        ),
    ] = None,
    sdinfo: Annotated[
        Optional[str],
        typer.Option("--sdinfo", help="Matching sdInfo*.flx (auto-discovered)"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output PNG path")
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Output JSON path (default: beside PNG)"),
    ] = None,
    pixels_per_cell: Annotated[
        int,
        typer.Option(
            "--pixels-per-cell",
            min=1,
            max=MAX_MAP_PIXELS_PER_CELL,
            help="Output detail per 128-unit terrain cell",
        ),
    ] = 1,
    hillshade: Annotated[
        bool,
        typer.Option("--hillshade/--no-hillshade", help="Shade decoded terrain relief"),
    ] = True,
    hillshade_strength: Annotated[
        float,
        typer.Option(
            "--hillshade-strength",
            min=0.0,
            max=1.0,
            help="Relief shading blend",
        ),
    ] = 0.55,
    water: Annotated[
        bool,
        typer.Option(
            "--water/--no-water",
            help="Render the map-wide water surface from the terrain header",
        ),
    ] = True,
    water_frame: Annotated[
        int,
        typer.Option(
            "--water-frame",
            min=0,
            help="Static frame from water texture entry 49",
        ),
    ] = 0,
    fixed_markers: Annotated[
        bool,
        typer.Option(
            "--fixed-markers/--no-fixed-markers",
            help="Draw fixed-object anchor markers when --fixed is supplied",
        ),
    ] = True,
    fixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--fixed-marker-radius", min=1, help="Fixed marker radius in output pixels"
        ),
    ] = 1,
    nonfixed_markers: Annotated[
        bool,
        typer.Option(
            "--nonfixed-markers/--no-nonfixed-markers",
            help="Draw indexed authored placements when --nonfixed is supplied",
        ),
    ] = True,
    nonfixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--nonfixed-marker-radius",
            min=1,
            help="Nonfixed marker radius in output pixels",
        ),
    ] = 1,
    include_unlinked_nonfixed: Annotated[
        bool,
        typer.Option(
            "--include-unlinked-nonfixed",
            help="Also draw allocated records absent from the spatial index",
        ),
    ] = False,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects/--no-objects",
            help="Rasterize textured sappear model triangles at object placements",
        ),
    ] = False,
    object_lod: Annotated[
        int,
        typer.Option(
            "--object-lod",
            min=0,
            help="sappear model LOD used by --objects (LOD 0 preserves coverage)",
        ),
    ] = 0,
    object_footprints: Annotated[
        bool,
        typer.Option(
            "--object-footprints/--no-object-footprints",
            help="Draw transformed sappear model bounds beneath object anchors",
        ),
    ] = False,
    object_footprint_source: Annotated[
        str,
        typer.Option(
            "--object-source",
            help="Object source filter: all, fixed, or nonfixed",
        ),
    ] = "all",
    object_type_ids: Annotated[
        Optional[list[int]],
        typer.Option(
            "--object-type",
            help="Type ID object filter (repeatable; matches fixed and nonfixed)",
        ),
    ] = None,
    object_model_ids: Annotated[
        Optional[list[int]],
        typer.Option(
            "--object-model",
            help="sappear model ID object filter (repeatable)",
        ),
    ] = None,
    object_footprint_style: Annotated[
        str,
        typer.Option(
            "--object-footprint-style",
            help="Footprint polygon style: outline or fill",
        ),
    ] = "outline",
    object_legend: Annotated[
        bool,
        typer.Option(
            "--object-legend/--no-object-legend",
            help="Embed footprint colours, filters, and display counts",
        ),
    ] = True,
    flip_y: Annotated[
        bool,
        typer.Option(
            "--flip-y/--no-flip-y",
            help="Invert U9 Y into image rows as the legacy editor does",
        ),
    ] = True,
) -> None:
    """Render one textured U9 region with optional object overlays."""
    raise SystemExit(
        cmd_map_render(
            SimpleNamespace(
                terrain=terrain,
                textures=textures,
                fixed=fixed,
                nonfixed=nonfixed,
                models=models,
                types=types,
                palette=palette,
                sdinfo=sdinfo,
                output=output,
                metadata=metadata,
                pixels_per_cell=pixels_per_cell,
                hillshade=hillshade,
                hillshade_strength=hillshade_strength,
                water=water,
                water_frame=water_frame,
                fixed_markers=fixed_markers,
                fixed_marker_radius=fixed_marker_radius,
                nonfixed_markers=nonfixed_markers,
                nonfixed_marker_radius=nonfixed_marker_radius,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                objects=objects,
                object_lod=object_lod,
                object_footprints=object_footprints,
                object_footprint_source=object_footprint_source,
                object_type_ids=object_type_ids,
                object_model_ids=object_model_ids,
                object_footprint_style=object_footprint_style,
                object_legend=object_legend,
                flip_y=flip_y,
            )
        )
    )


@u9_app.command("map-export-glb")
def map_export_glb_cmd(
    terrain: Annotated[
        str, typer.Argument(help="Path to a static/terrain.<region> file")
    ],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture tier FLX (default: adjacent bitmap16.flx)",
        ),
    ] = None,
    fixed: Annotated[
        Optional[str],
        typer.Option("--fixed", help="Matching static/fixed.<region> objects"),
    ] = None,
    nonfixed: Annotated[
        Optional[str],
        typer.Option("--nonfixed", help="Matching runtime/save nonfixed.<region>"),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option(
            "--models",
            help="sappear.flx (auto-discovered beside terrain for objects)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="TYPES.DAT (auto-discovered for fixed-object model lookup)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="ankh.pal (auto-discovered)"),
    ] = None,
    sdinfo: Annotated[
        Optional[str],
        typer.Option("--sdinfo", help="Matching sdInfo*.flx (auto-discovered)"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output .glb path")
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Output JSON manifest (default: beside GLB)"),
    ] = None,
    cell_region: Annotated[
        Optional[str],
        typer.Option(
            "--cell-region",
            help="Half-open terrain rectangle x0,y0,x1,y1 (default: full region)",
        ),
    ] = None,
    terrain_layer: Annotated[
        bool,
        typer.Option(
            "--terrain/--no-terrain", help="Include textured terrain geometry"
        ),
    ] = True,
    water: Annotated[
        bool,
        typer.Option("--water/--no-water", help="Include the global water plane"),
    ] = True,
    water_frame: Annotated[
        int,
        typer.Option("--water-frame", min=0, help="Water texture 49 frame"),
    ] = 0,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects/--no-objects",
            help="Include supplied fixed/nonfixed model geometry",
        ),
    ] = True,
    include_unlinked_nonfixed: Annotated[
        bool,
        typer.Option(
            "--include-unlinked-nonfixed",
            help="Also export allocated nonfixed records absent from the index",
        ),
    ] = False,
    object_source: Annotated[
        str,
        typer.Option(
            "--object-source", help="Object source filter: all, fixed, or nonfixed"
        ),
    ] = "all",
    object_type: Annotated[
        Optional[list[int]],
        typer.Option("--object-type", help="Type ID filter (repeatable)"),
    ] = None,
    object_model: Annotated[
        Optional[list[int]],
        typer.Option("--object-model", help="sappear model ID filter (repeatable)"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", min=0, help="Model LOD level")] = 0,
    coordinate_scale: Annotated[
        float,
        typer.Option(
            "--coordinate-scale",
            min=0.000001,
            help="GLB units per native U9 unit (default matches model export)",
        ),
    ] = DEFAULT_U9_GLB_SCALE,
) -> None:
    """Export one textured U9 region rectangle as a Y-up GLB scene."""
    raise SystemExit(
        cmd_map_export_glb(
            SimpleNamespace(
                terrain=terrain,
                textures=textures,
                fixed=fixed,
                nonfixed=nonfixed,
                models=models,
                types=types,
                palette=palette,
                sdinfo=sdinfo,
                output=output,
                metadata=metadata,
                cell_region=cell_region,
                terrain_layer=terrain_layer,
                water=water,
                water_frame=water_frame,
                objects=objects,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                object_source=object_source,
                object_type=object_type,
                object_model=object_model,
                lod=lod,
                coordinate_scale=coordinate_scale,
            )
        )
    )


@u9_app.command("books-list")
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


@u9_app.command("books-show")
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


@u9_app.command("books-search")
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


@u9_app.command("books-export")
def books_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/BOOKS-EN.FLX")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output CSV path"),
    ] = None,
) -> None:
    """Export a U9 book archive to CSV."""
    raise SystemExit(cmd_books_export(SimpleNamespace(file=file, output=output)))


@u9_app.command("flx-pack")
def flx_pack_cmd(
    directory: Annotated[
        str, typer.Argument(help="Directory of NNNNN.bin entry files")
    ],
    output: Annotated[str, typer.Argument(help="Output .flx path")],
    count: Annotated[
        Optional[int],
        typer.Option(
            "-c", "--count", help="Directory slot count (default: smallest that fits)"
        ),
    ] = None,
    comment: Annotated[
        Optional[str],
        typer.Option("--comment", help="ASCII comment, max 76 bytes"),
    ] = None,
) -> None:
    """Build a U9 FLX archive from extracted entry files."""
    raise SystemExit(
        cmd_flx_pack(
            SimpleNamespace(
                directory=directory, output=output, count=count, comment=comment
            )
        )
    )


@u9_app.command("flx-repack")
def flx_repack_cmd(
    file: Annotated[str, typer.Argument(help="Path to an existing U9 FLX archive")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output path (default: <stem>_repacked.flx)"
        ),
    ] = None,
    replace: Annotated[
        Optional[str],
        typer.Option("-r", "--replace", help="Directory of NNNNN.bin files to swap in"),
    ] = None,
) -> None:
    """Rebuild a U9 FLX archive, optionally replacing entries, and verify it."""
    raise SystemExit(
        cmd_flx_repack(SimpleNamespace(file=file, output=output, replace=replace))
    )


@u9_app.command("texture-import")
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
