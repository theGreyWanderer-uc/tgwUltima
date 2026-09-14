"""Dynamic CSV/JSON metadata rows for Ultima IX audio archives."""

from __future__ import annotations

__all__ = ["SOUND_REPORT_COLUMNS", "U9SoundReportError", "build_sound_metadata_report"]

import struct
from collections import defaultdict
from pathlib import Path
from typing import Any

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.sound import (
    ENCODING_ADPCM,
    ENCODING_EA_MICROTALK,
    ENCODING_PCM,
    HEADER_SIZE,
    U9SoundRecord,
    U9SoundRecordError,
)
from titan.u9.sound_control import (
    U9SoundControlError,
    parse_sfx_associations,
    parse_sfx_template,
)
from titan.u9.typename import U9TypeNames

KNOWN_AUDIO_ARCHIVES = ("speech.flx", "sfx.flx", "music.flx")

SOUND_REPORT_COLUMNS = [
    "archive_kind",
    "audio_archive",
    "archive_size",
    "archive_slot_count",
    "archive_used_count",
    "entry_id",
    "entry_offset",
    "entry_length",
    "record_status",
    "parse_error",
    "sound_id",
    "sound_id_matches_entry",
    "description",
    "source_extension",
    "header_size",
    "declared_payload_length",
    "actual_payload_length",
    "record_trailing_bytes",
    "record_length_exact",
    "frequency_hz",
    "bits_per_sample",
    "channels",
    "encoding_type",
    "encoding_name",
    "is_compressed",
    "wav_decodable",
    "sample_frames",
    "duration_seconds",
    "codec_block_remainder",
    "sfx_template_ids",
    "sfx_template_names",
    "sfx_action_category_ids",
    "sfx_action_category_names",
    "sfx_action_names",
    "sfx_reference_count",
    "sfx_reference_details",
    "associated_type_ids",
    "associated_type_names",
]


class U9SoundReportError(Exception):
    """Raised when audio report inputs cannot be discovered or read."""


def _case_insensitive_child(directory: Path, filename: str) -> Path | None:
    wanted = filename.casefold()
    try:
        return next(
            (child for child in directory.iterdir() if child.name.casefold() == wanted),
            None,
        )
    except OSError:
        return None


def _discover_audio_archives(source: str | Path) -> tuple[list[Path], Path]:
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise U9SoundReportError(f"sound source not found: {path}")
    if path.is_file():
        return [path], path.parent

    sound_dir = _case_insensitive_child(path, "sound")
    helper_dir = sound_dir if sound_dir is not None and sound_dir.is_dir() else path
    archives = [
        candidate
        for name in KNOWN_AUDIO_ARCHIVES
        if (candidate := _case_insensitive_child(helper_dir, name)) is not None
    ]
    if not archives:
        raise U9SoundReportError(
            f"no Speech.flx, sfx.flx, or music.flx found in {helper_dir}"
        )
    return archives, helper_dir


def _read_category_names(path: Path | None) -> dict[int, str]:
    if path is None:
        return {}
    try:
        archive = U9FlxArchive.from_file(path)
    except (OSError, U9FlxArchiveError):
        return {}
    names: dict[int, str] = {}
    for entry_id in archive.used_entry_indices():
        data = archive.read_entry(entry_id)
        if len(data) != 40:
            continue
        name = data[1:].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        if name:
            names[data[0]] = name
    return names


def _load_sfx_links(
    helper_dir: Path,
) -> tuple[
    dict[int, list[dict[str, Any]]], dict[int, list[int]], dict[int, str], list[str]
]:
    warnings: list[str] = []
    references: dict[int, list[dict[str, Any]]] = defaultdict(list)
    template_types: dict[int, list[int]] = defaultdict(list)
    categories = _read_category_names(_case_insensitive_child(helper_dir, "sfxcat.flx"))

    template_path = _case_insensitive_child(helper_dir, "SFXTMPL.FLX")
    if template_path is not None:
        try:
            archive = U9FlxArchive.from_file(template_path)
            for entry_id in archive.used_entry_indices():
                template = parse_sfx_template(archive.read_entry(entry_id))
                if template.template_id != entry_id:
                    warnings.append(
                        f"SFX template slot {entry_id} contains ID {template.template_id}"
                    )
                for action in template.actions:
                    for reference in action.sound_references:
                        references[reference.sound_id].append(
                            {
                                "template_id": entry_id,
                                "template_name": template.name,
                                "template_unknown_2c": template.unknown_2c,
                                "template_unknown_30": template.unknown_30,
                                "template_unknown_34": template.unknown_34.hex(),
                                "category_id": action.category_id,
                                "action_name": action.name,
                                "reference_unknown_00": reference.unknown_00,
                                "reference_unknown_08": reference.unknown_08,
                                "reference_unknown_0c": reference.unknown_0c,
                            }
                        )
        except (OSError, U9FlxArchiveError, U9SoundControlError) as error:
            warnings.append(f"could not load SFXTMPL.FLX links: {error}")

    association_path = _case_insensitive_child(helper_dir, "sfxassoc.flx")
    if association_path is not None:
        try:
            association_archive = U9FlxArchive.from_file(association_path)
            for association in parse_sfx_associations(association_archive):
                template_types[association.template_id].append(association.type_id)
        except (OSError, U9FlxArchiveError, U9SoundControlError) as error:
            warnings.append(f"could not load sfxassoc.flx links: {error}")
    return references, template_types, categories, warnings


def _load_type_names(helper_dir: Path) -> U9TypeNames | None:
    candidates = (helper_dir, helper_dir.parent / "static")
    for directory in candidates:
        names_path = _case_insensitive_child(directory, "TYPENAME.FLX")
        if names_path is None:
            continue
        try:
            return U9TypeNames.from_file(names_path)
        except (OSError, U9FlxArchiveError):
            pass
    return None


def _sample_metadata(record: U9SoundRecord) -> tuple[int | None, int | None]:
    """Return estimated/declared sample frames and incomplete codec bytes."""
    if record.encoding_type == ENCODING_PCM:
        frame_size = record.num_channels * max(1, record.bits_per_sample // 8)
        return (len(record.payload) // frame_size, len(record.payload) % frame_size)
    if record.encoding_type == ENCODING_ADPCM:
        block_size = (
            15 if record.num_channels == 1 else 30 if record.num_channels == 2 else 0
        )
        if block_size:
            return (
                len(record.payload) // block_size * 28,
                len(record.payload) % block_size,
            )
    if record.encoding_type == ENCODING_EA_MICROTALK and len(record.payload) >= 4:
        return (struct.unpack_from("<I", record.payload, 0)[0], None)
    return (None, None)


def _link_fields(
    sound_id: int,
    references: dict[int, list[dict[str, Any]]],
    template_types: dict[int, list[int]],
    categories: dict[int, str],
    type_names: U9TypeNames | None,
) -> dict[str, Any]:
    links = references.get(sound_id, [])
    template_ids = sorted({int(link["template_id"]) for link in links})
    type_ids = sorted(
        {
            type_id
            for template_id in template_ids
            for type_id in template_types.get(template_id, [])
        }
    )
    fields: dict[str, Any] = {
        "sfx_template_ids": template_ids,
        "sfx_template_names": sorted({str(link["template_name"]) for link in links}),
        "sfx_action_category_ids": sorted({int(link["category_id"]) for link in links}),
        "sfx_action_names": sorted({str(link["action_name"]) for link in links}),
        "sfx_reference_count": len(links),
        "sfx_reference_details": links,
        "associated_type_ids": type_ids,
    }
    category_names = sorted(
        {
            categories[int(link["category_id"])]
            for link in links
            if int(link["category_id"]) in categories
        }
    )
    if category_names:
        fields["sfx_action_category_names"] = category_names
    if type_names is not None:
        fields["associated_type_names"] = sorted(
            {name for type_id in type_ids if (name := type_names.name_for(type_id))}
        )
    return fields


def build_sound_metadata_report(
    source: str | Path, *, entry_id: int | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build one dynamic metadata row per used audio record in one or all archives."""
    archive_paths, helper_dir = _discover_audio_archives(source)
    references, template_types, categories, warnings = _load_sfx_links(helper_dir)
    type_names = _load_type_names(helper_dir)
    rows: list[dict[str, Any]] = []

    for archive_path in archive_paths:
        try:
            archive = U9FlxArchive.from_file(archive_path)
        except (OSError, U9FlxArchiveError) as error:
            raise U9SoundReportError(
                f"could not read {archive_path}: {error}"
            ) from error
        kind = archive_path.stem.casefold()
        if entry_id is not None:
            if not 0 <= entry_id < archive.num_entries:
                warnings.append(
                    f"{archive_path.name}: entry {entry_id} is outside 0..{archive.num_entries - 1}"
                )
                continue
            indices = [entry_id]
        else:
            indices = archive.used_entry_indices()
        used_count = len(archive.used_entry_indices())

        for current_id in indices:
            entry = archive.get_entry(current_id)
            data = archive.read_entry(current_id)
            base: dict[str, Any] = {
                "archive_kind": kind,
                "audio_archive": str(archive_path),
                "archive_size": archive_path.stat().st_size,
                "archive_slot_count": archive.num_entries,
                "archive_used_count": used_count,
                "entry_id": current_id,
                "entry_offset": entry.offset if entry else None,
                "entry_length": entry.length if entry else 0,
            }
            if not data:
                rows.append(
                    {**base, "record_status": "empty", "parse_error": "unused FLX slot"}
                )
                continue
            try:
                record = U9SoundRecord.parse(data)
            except U9SoundRecordError as error:
                rows.append(
                    {**base, "record_status": "parse-error", "parse_error": str(error)}
                )
                continue
            declared = struct.unpack_from("<I", data, 0x28)[0]
            available = max(0, len(data) - HEADER_SIZE)
            actual = min(declared, available)
            trailing = max(0, available - declared)
            sample_frames, block_remainder = _sample_metadata(record)
            row = {
                **base,
                "record_status": "ok"
                if len(data) == HEADER_SIZE + declared
                else "length-mismatch",
                "parse_error": "",
                "sound_id": record.sound_id,
                "sound_id_matches_entry": record.sound_id == current_id,
                "description": record.description,
                "source_extension": Path(record.description).suffix,
                "header_size": HEADER_SIZE,
                "declared_payload_length": declared,
                "actual_payload_length": actual,
                "record_trailing_bytes": trailing,
                "record_length_exact": len(data) == HEADER_SIZE + declared,
                "frequency_hz": record.frequency,
                "bits_per_sample": record.bits_per_sample,
                "channels": record.num_channels,
                "encoding_type": record.encoding_type,
                "encoding_name": record.encoding_name,
                "is_compressed": record.encoding_type != ENCODING_PCM,
                "wav_decodable": record.is_pcm
                or record.is_decodable_adpcm
                or record.is_decodable_microtalk,
                "sample_frames": sample_frames,
                "duration_seconds": (
                    round(sample_frames / record.frequency, 6)
                    if sample_frames is not None and record.frequency
                    else None
                ),
                "codec_block_remainder": block_remainder,
            }
            if kind == "sfx":
                row.update(
                    _link_fields(
                        record.sound_id,
                        references,
                        template_types,
                        categories,
                        type_names,
                    )
                )
            rows.append(row)

    rows.sort(key=lambda row: (str(row["archive_kind"]), int(row["entry_id"])))
    if not rows:
        raise U9SoundReportError("no matching audio records were found")
    return rows, warnings
