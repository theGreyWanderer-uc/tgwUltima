"""``titan u9 sound-*`` — sound archives, categories, environments and templates."""

from __future__ import annotations

__all__ = [
    "sound_category_list_cmd",
    "sound_category_csv_cmd",
    "sound_environment_list_cmd",
    "sound_environment_csv_cmd",
    "sound_template_csv_cmd",
    "sound_association_csv_cmd",
    "sound_list_cmd",
    "sound_extract_pcm_cmd",
    "sound_extract_cmd",
    "sound_report_cmd",
    "sound_import_cmd",
    "sound_import_batch_cmd",
]

import csv
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.asset_reports import U9AssetReportError, write_dynamic_report
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.flx_writer import U9FlxWriteError, repack
from titan.u9.sound import U9SoundRecord, U9SoundRecordError
from titan.u9.sound_category import U9SoundCategories, U9SoundCategoryError
from titan.u9.sound_environment import U9AcousticPresetError, U9AcousticPresets
from titan.u9.sound_control import (
    U9SfxAssociations,
    U9SfxTemplates,
    U9SoundControlError,
)
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
from titan.u9.typename import U9TypeNameError, U9TypeNames
from titan.u9.types_dat import U9TypesDat, U9TypesDatError


def _load_sound_categories(filepath: str) -> Optional[U9SoundCategories]:
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9SoundCategories.from_file(filepath)
    except (U9FlxArchiveError, U9SoundCategoryError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def cmd_sound_category_list(args: SimpleNamespace) -> int:
    """List the master categories stored in ``sound/sfxcat.flx``."""
    categories = _load_sound_categories(args.file)
    if categories is None:
        return 1

    print(
        f"{args.file} — {len(categories)} used categories in "
        f"{categories.archive_slot_count} slots"
    )
    print(f"{'Slot':>4}  {'ID':>3}  {'Refs':>4}  Name")
    print("-" * 52)
    for category in categories:
        print(
            f"{category.archive_index:>4}  {category.category_id:>3}  "
            f"{category.sound_reference_count:>4}  {category.display_name}"
        )
    return 0


def cmd_sound_category_csv(args: SimpleNamespace) -> int:
    """Export every used ``sfxcat.flx`` category record to CSV."""
    categories = _load_sound_categories(args.file)
    if categories is None:
        return 1

    output = args.output or f"{Path(args.file).stem}_categories.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "archive_index",
                "category_id",
                "display_name",
                "record_representation",
                "warnings",
                "id_matches_index",
                "name_is_terminated",
                "name_field_hex",
                "name_padding_hex",
                "alignment_hex",
                "sound_reference_count",
                "raw_hex",
            ]
        )
        for category in categories:
            writer.writerow(
                [
                    category.archive_index,
                    category.category_id,
                    category.display_name,
                    category.record_representation,
                    ";".join(category.warnings),
                    category.id_matches_index,
                    category.name_is_terminated,
                    f"0x{category.name_field.hex()}",
                    f"0x{category.name_padding_bytes.hex()}",
                    f"0x{category.alignment_bytes.hex()}",
                    category.sound_reference_count,
                    f"0x{category.raw.hex()}",
                ]
            )
    print(f"{args.file} — wrote {len(categories)} sound category row(s) -> {output}")
    return 0


def _load_sound_environments(filepath: str) -> Optional[U9AcousticPresets]:
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9AcousticPresets.from_file(filepath)
    except (OSError, U9FlxArchiveError, U9AcousticPresetError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def cmd_sound_environment_list(args: SimpleNamespace) -> int:
    """List the listener-reverb presets stored in ``sound/sfxenv.flx``."""
    environments = _load_sound_environments(args.file)
    if environments is None:
        return 1

    print(
        f"{args.file} - {len(environments)} used environments in "
        f"{environments.archive_slot_count} slots"
    )
    print(
        f"{'Slot':>4}  {'Code':>4}  {'Volume':>7}  {'Decay':>7}  {'Damping':>7}  Name"
    )
    print("-" * 88)
    for environment in environments:
        print(
            f"{environment.archive_index:>4}  "
            f"{environment.acoustic_profile_code:>4}  "
            f"{environment.reverb_volume:>7.3f}  "
            f"{environment.decay_time_seconds:>7.3f}  "
            f"{environment.high_frequency_damping:>7.3f}  "
            f"{environment.display_name}"
        )
    return 0


def cmd_sound_environment_csv(args: SimpleNamespace) -> int:
    """Export every used ``sfxenv.flx`` environment record to CSV."""
    environments = _load_sound_environments(args.file)
    if environments is None:
        return 1

    output = args.output or f"{Path(args.file).stem}_environments.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    columns = [
        "archive_index",
        "display_name",
        "record_representation",
        "acoustic_profile_code",
        "acoustic_profile_name",
        "reverb_volume",
        "decay_time_seconds",
        "high_frequency_damping",
        "value_status",
        "standard_preset_status",
        "warnings",
        "name_is_terminated",
        "name_field_hex",
        "name_residue_hex",
        "archive_slot_count",
        "archive_warnings",
        "raw_hex",
    ]
    with open(output, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for environment in environments:
            writer.writerow(
                {
                    "archive_index": environment.archive_index,
                    "display_name": environment.display_name,
                    "record_representation": environment.record_representation,
                    "acoustic_profile_code": environment.acoustic_profile_code,
                    "acoustic_profile_name": environment.acoustic_profile_name,
                    "reverb_volume": environment.reverb_volume,
                    "decay_time_seconds": environment.decay_time_seconds,
                    "high_frequency_damping": (environment.high_frequency_damping),
                    "value_status": environment.value_status,
                    "standard_preset_status": environment.standard_preset_status,
                    "warnings": ";".join(environment.warnings),
                    "name_is_terminated": environment.name_is_terminated,
                    "name_field_hex": f"0x{environment.name_field.hex()}",
                    "name_residue_hex": (f"0x{environment.name_residue_bytes.hex()}"),
                    "archive_slot_count": environments.archive_slot_count,
                    "archive_warnings": ";".join(environments.archive_warnings),
                    "raw_hex": f"0x{environment.raw.hex()}",
                }
            )
    print(
        f"{args.file} - wrote {len(environments)} sound environment row(s) -> {output}"
    )
    return 0


def cmd_sound_template_csv(args: SimpleNamespace) -> int:
    """Export every template, action, and weighted sound choice to CSV."""
    try:
        templates = U9SfxTemplates.from_file(args.file)
        categories = (
            U9SoundCategories.from_file(args.categories) if args.categories else None
        )
        sound_names: dict[int, str] = {}
        sound_identity_mismatches: set[int] = set()
        if args.sounds:
            sound_archive = U9FlxArchive.from_file(args.sounds)
            for sound_index in sound_archive.used_entry_indices():
                sound = U9SoundRecord.parse(sound_archive.read_entry(sound_index))
                sound_names[sound_index] = sound.description
                if sound.sound_id != sound_index:
                    sound_identity_mismatches.add(sound_index)
    except (
        OSError,
        U9FlxArchiveError,
        U9SoundCategoryError,
        U9SoundControlError,
        U9SoundRecordError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output = args.output or f"{Path(args.file).stem}_templates.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    columns = [
        "row_kind",
        "archive_index",
        "template_id",
        "template_name",
        "record_representation",
        "template_warnings",
        "id_matches_index",
        "action_count",
        "inner_cone_angle_degrees",
        "outer_cone_angle_degrees",
        "near_distance",
        "far_distance",
        "template_name_field_hex",
        "template_name_padding_hex",
        "template_name_alignment_hex",
        "template_trailing_alignment_hex",
        "action_index",
        "category_id",
        "action_name",
        "master_category_name",
        "sound_reference_count",
        "action_warnings",
        "action_name_field_hex",
        "action_name_padding_hex",
        "action_alignment_hex",
        "choice_index",
        "choice_id",
        "sound_id",
        "sound_name",
        "full_volume_percent",
        "off_axis_volume_percent",
        "active_hour_start",
        "active_hour_stop",
        "pitch_variation_percent",
        "selection_weight",
        "choice_warnings",
        "choice_leading_alignment_hex",
        "choice_trailing_alignment_hex",
        "external_warnings",
        "archive_slot_count",
        "archive_warnings",
        "template_raw_hex",
        "action_raw_hex",
        "choice_raw_hex",
    ]
    row_count = 0
    action_count = 0
    choice_count = 0
    with open(output, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for template in templates:
            template_fields: dict[str, object] = {
                "archive_index": template.archive_index,
                "template_id": template.template_id,
                "template_name": template.name,
                "record_representation": template.record_representation,
                "template_warnings": ";".join(template.warnings),
                "id_matches_index": template.id_matches_index,
                "action_count": template.action_count,
                "inner_cone_angle_degrees": (template.inner_cone_angle_degrees),
                "outer_cone_angle_degrees": template.outer_cone_angle_degrees,
                "near_distance": template.near_distance,
                "far_distance": template.far_distance,
                "template_name_field_hex": f"0x{template.name_field.hex()}",
                "template_name_padding_hex": (f"0x{template.name_padding_bytes.hex()}"),
                "template_name_alignment_hex": (
                    f"0x{template.name_alignment_bytes.hex()}"
                ),
                "template_trailing_alignment_hex": (
                    f"0x{template.trailing_alignment_bytes.hex()}"
                ),
                "archive_slot_count": templates.archive_slot_count,
                "archive_warnings": ";".join(templates.warnings),
                "template_raw_hex": f"0x{template.raw.hex()}",
            }
            if not template.actions:
                writer.writerow({**template_fields, "row_kind": "template"})
                row_count += 1
                continue

            for action_index, action in enumerate(template.actions):
                action_count += 1
                master_category_name = (
                    categories.name_for(action.category_id) if categories else None
                )
                external_warnings: list[str] = []
                if categories is not None and master_category_name is None:
                    external_warnings.append("category_missing")
                elif (
                    master_category_name is not None
                    and master_category_name != action.name
                ):
                    external_warnings.append("action_name_differs_from_master")
                action_fields: dict[str, object] = {
                    **template_fields,
                    "action_index": action_index,
                    "category_id": action.category_id,
                    "action_name": action.name,
                    "master_category_name": master_category_name or "",
                    "sound_reference_count": len(action.sound_references),
                    "action_warnings": ";".join(action.warnings),
                    "action_name_field_hex": f"0x{action.name_field.hex()}",
                    "action_name_padding_hex": (f"0x{action.name_padding_bytes.hex()}"),
                    "action_alignment_hex": f"0x{action.alignment_bytes.hex()}",
                    "action_raw_hex": f"0x{action.raw.hex()}",
                }
                if not action.sound_references:
                    writer.writerow(
                        {
                            **action_fields,
                            "row_kind": "action",
                            "external_warnings": ";".join(external_warnings),
                        }
                    )
                    row_count += 1
                    continue

                for choice_index, choice in enumerate(action.sound_references):
                    choice_count += 1
                    choice_external_warnings = list(external_warnings)
                    if args.sounds and choice.sound_id not in sound_names:
                        choice_external_warnings.append("sound_missing")
                    if choice.sound_id in sound_identity_mismatches:
                        choice_external_warnings.append(
                            "sound_identity_differs_from_slot"
                        )
                    writer.writerow(
                        {
                            **action_fields,
                            "row_kind": "sound_choice",
                            "choice_index": choice_index,
                            "choice_id": choice.choice_id,
                            "sound_id": choice.sound_id,
                            "sound_name": sound_names.get(choice.sound_id, ""),
                            "full_volume_percent": choice.full_volume_percent,
                            "off_axis_volume_percent": (choice.off_axis_volume_percent),
                            "active_hour_start": choice.active_hour_start,
                            "active_hour_stop": choice.active_hour_stop,
                            "pitch_variation_percent": (choice.pitch_variation_percent),
                            "selection_weight": choice.selection_weight,
                            "choice_warnings": ";".join(choice.warnings),
                            "choice_leading_alignment_hex": (
                                f"0x{choice.leading_alignment_bytes.hex()}"
                            ),
                            "choice_trailing_alignment_hex": (
                                f"0x{choice.trailing_alignment_bytes.hex()}"
                            ),
                            "external_warnings": ";".join(choice_external_warnings),
                            "choice_raw_hex": f"0x{choice.raw.hex()}",
                        }
                    )
                    row_count += 1

    print(
        f"{args.file} — wrote {row_count} row(s) from {len(templates)} templates, "
        f"{action_count} actions, and {choice_count} sound choices -> {output}"
    )
    return 0


def cmd_sound_association_csv(args: SimpleNamespace) -> int:
    """Export direct or runtime-effective ``sfxassoc.flx`` links to CSV."""
    try:
        associations = U9SfxAssociations.from_file(args.file)
        types = U9TypesDat.from_file(args.types) if args.types else None
        names = U9TypeNames.from_file(args.typenames) if args.typenames else None
        template_names: dict[int, str] = {}
        template_ids: set[int] | None = None
        template_identity_mismatches: set[int] = set()
        if args.templates:
            templates = U9SfxTemplates.from_file(args.templates)
            template_ids = {template.archive_index for template in templates}
            for template in templates:
                template_names[template.archive_index] = template.name
                if not template.id_matches_index:
                    template_identity_mismatches.add(template.archive_index)
    except (
        OSError,
        U9FlxArchiveError,
        U9SoundControlError,
        U9TypesDatError,
        U9TypeNameError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.effective and types is None:
        print("ERROR: --effective requires --types", file=sys.stderr)
        return 1

    if args.effective and types is not None:
        resolutions = [
            resolution
            for type_record in types
            if (
                resolution := associations.resolve(type_record.type_id, types)
            ).sound_template_id
            is not None
        ]
    else:
        resolutions = [
            associations.resolve(record.object_type_id) for record in associations
        ]

    output = args.output or f"{Path(args.file).stem}_associations.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "object_type_id",
                "display_name",
                "link_source",
                "matched_object_type_id",
                "base_type_id",
                "default_model_id",
                "sound_template_id",
                "sound_template_name",
                "record_representation",
                "warnings",
                "archive_slot_count",
                "archive_warnings",
                "raw_hex",
            ]
        )
        for resolution in resolutions:
            type_record = (
                types.record_for(resolution.requested_object_type_id)
                if types is not None
                else None
            )
            row_warnings: list[str] = []
            if types is not None and type_record is None:
                row_warnings.append("object_type_outside_active_types")
            if (
                template_ids is not None
                and resolution.sound_template_id not in template_ids
            ):
                row_warnings.append("sound_template_missing")
            if resolution.sound_template_id in template_identity_mismatches:
                row_warnings.append("sound_template_identity_differs_from_slot")
            association = resolution.association
            writer.writerow(
                [
                    resolution.requested_object_type_id,
                    names.name_for(resolution.requested_object_type_id)
                    if names
                    else "",
                    resolution.link_source,
                    resolution.matched_object_type_id,
                    type_record.base_type_id if type_record else "",
                    type_record.default_model_id if type_record else "",
                    resolution.sound_template_id,
                    template_names.get(resolution.sound_template_id, "")
                    if resolution.sound_template_id is not None
                    else "",
                    association.record_representation if association else "",
                    ";".join(row_warnings),
                    associations.archive_slot_count,
                    ";".join(associations.warnings),
                    f"0x{association.raw.hex()}" if association else "",
                ]
            )
    print(f"{args.file} — wrote {len(resolutions)} association row(s) -> {output}")
    return 0


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


def sound_category_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to sound/sfxcat.flx")],
) -> None:
    """List U9 master sound categories."""
    raise SystemExit(cmd_sound_category_list(SimpleNamespace(file=file)))


def sound_category_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to sound/sfxcat.flx")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="CSV output path"),
    ] = None,
) -> None:
    """Export complete U9 master sound-category records to CSV."""
    raise SystemExit(cmd_sound_category_csv(SimpleNamespace(file=file, output=output)))


def sound_environment_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to sound/sfxenv.flx")],
) -> None:
    """List U9 acoustic environment presets."""
    raise SystemExit(cmd_sound_environment_list(SimpleNamespace(file=file)))


def sound_environment_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to sound/sfxenv.flx")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="CSV output path"),
    ] = None,
) -> None:
    """Export complete U9 acoustic environment records to CSV."""
    raise SystemExit(
        cmd_sound_environment_csv(SimpleNamespace(file=file, output=output))
    )


def sound_template_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to sound/SFXTMPL.FLX")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="CSV output path"),
    ] = None,
    categories: Annotated[
        Optional[str],
        typer.Option("--categories", help="Optional sound/sfxcat.flx join"),
    ] = None,
    sounds: Annotated[
        Optional[str],
        typer.Option("--sounds", help="Optional sound/sfx.flx join"),
    ] = None,
) -> None:
    """Export complete U9 sound templates, actions, and weighted choices."""
    raise SystemExit(
        cmd_sound_template_csv(
            SimpleNamespace(
                file=file,
                output=output,
                categories=categories,
                sounds=sounds,
            )
        )
    )


def sound_association_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to sound/sfxassoc.flx")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="CSV output path"),
    ] = None,
    templates: Annotated[
        Optional[str],
        typer.Option("--templates", help="Optional sound/SFXTMPL.FLX join"),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option("--types", help="Optional static/TYPES.DAT join"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option("--typenames", help="Optional static/TYPENAME.FLX labels"),
    ] = None,
    effective: Annotated[
        bool,
        typer.Option(
            "--effective",
            help="Include direct and base-type fallback links; requires --types",
        ),
    ] = False,
) -> None:
    """Export direct or runtime-effective object sound-template links."""
    raise SystemExit(
        cmd_sound_association_csv(
            SimpleNamespace(
                file=file,
                output=output,
                templates=templates,
                types=types,
                typenames=typenames,
                effective=effective,
            )
        )
    )


def sound_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 sound/*.flx file")],
) -> None:
    """List sound record headers (id, description, format, encoding) in a sound archive."""
    raise SystemExit(cmd_sound_list(SimpleNamespace(file=file)))


def sound_extract_pcm_cmd(
    file: Annotated[str, typer.Argument(help="Path to a U9 sound/*.flx file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <file>_wav/)"),
    ] = None,
) -> None:
    """Extract every PCM-encoded entry in a sound archive as a playable WAV."""
    raise SystemExit(cmd_sound_extract_pcm(SimpleNamespace(file=file, output=output)))


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
