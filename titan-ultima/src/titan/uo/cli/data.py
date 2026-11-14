"""``titan uo tiledata-`` / ``animdata-`` / ``artdef-`` / ``def-`` / ``localization-`` / ``sound-export`` — data table and sound commands."""

from __future__ import annotations

__all__ = [
    "tiledata_export_cmd",
    "animdata_export_cmd",
    "artdef_export_cmd",
    "def_export_cmd",
    "localization_export_cmd",
    "sound_export_cmd",
]

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.uo.definfo import UODefFile
from titan.uo.indexed import UOIndexedFile, UOIndexEntry
from titan.uo.localization import (
    UOCliloc,
    UOSkillGroups,
    UOSkills,
    UOSpeech,
    find_localized_text_files,
    parse_iff_text_file,
)
from titan.uo.sound import UOSoundDecoder
from titan.uo.cli import _common


def _load_sounds(
    client: Path,
    *,
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
    limit: Optional[int] = None,
) -> UOIndexedFile:
    uop = client / "soundLegacyMUL.uop"
    if uop.is_file():
        return UOIndexedFile.from_uop(
            uop,
            extension=".dat",
            entry_count=0x10000,
            range_start=range_start,
            range_end=range_end,
            max_entries=limit,
        )

    mul = client / "sound.mul"
    idx = client / "soundidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("soundLegacyMUL.uop or sound.mul/soundidx.mul not found")


def _sound_metadata(defs: dict[str, UODefFile]):
    sounddef = defs.get("sound.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        redirect = sounddef.redirects.get(entry.index) if sounddef is not None else None
        return _common._redirect_metadata("sounddef", redirect)

    return metadata


def _localized_text_category(stem: str) -> str:
    cleaned = stem.lower()
    if cleaned.startswith("gt_"):
        return "gt"
    if cleaned.startswith("intloc"):
        return "intloc"
    if cleaned.startswith("skill"):
        return "skill_text"
    if cleaned in {
        "chat",
        "gesture",
        "intro",
        "options",
        "optnuotd",
        "professn",
        "skilname",
        "tilehelp",
        "tooltips",
    }:
        return cleaned
    return "system"


def cmd_tiledata_export(args: SimpleNamespace) -> int:
    """Export UO tile metadata to CSV."""
    try:
        client = _common._client_path(args.client)
        tiledata = _common._load_tiledata(client)
        animdata = _common._try_load_animdata(client)
        defs = _common._try_load_defs(client)
        tilehelp = _common._try_load_tilehelp(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "tiledata"
    outdir.mkdir(parents=True, exist_ok=True)

    texterr = defs.get("texterr.def")
    land_rows: list[dict[str, object]] = []
    for land_tile in tiledata.land:
        texterr_entry = (
            texterr.redirects.get(land_tile.tile_id) if texterr is not None else None
        )
        land_rows.append(
            {
                "tile_id": land_tile.tile_id,
                "name": land_tile.name,
                "texture_id": land_tile.texture_id,
                "flags": f"0x{land_tile.flags:016X}",
                "flag_names": _common._tile_flag_text(land_tile.flag_names),
                **_common._redirect_metadata("texterr", texterr_entry),
            }
        )
    static_rows: list[dict[str, object]] = []
    for static_tile in tiledata.statics:
        anim_entry = (
            animdata.entries.get(static_tile.tile_id) if animdata is not None else None
        )
        static_rows.append(
            {
                "tile_id": static_tile.tile_id,
                "name": static_tile.name,
                "flags": f"0x{static_tile.flags:016X}",
                "flag_names": _common._tile_flag_text(static_tile.flag_names),
                "weight": static_tile.weight,
                "quality": static_tile.quality,
                "misc_data": static_tile.misc_data,
                "unknown2": static_tile.unknown2,
                "quantity": static_tile.quantity,
                "anim_id": static_tile.anim_id,
                "unknown3": static_tile.unknown3,
                "hue": static_tile.hue,
                "stacking_offset": static_tile.stacking_offset,
                "value": static_tile.value,
                "height": static_tile.height,
                "tilehelp": tilehelp.get(static_tile.tile_id, ""),
                **_common._animdata_metadata(anim_entry),
            }
        )

    _common._write_manifest(outdir / "land.csv", land_rows)
    _common._write_manifest(outdir / "statics.csv", static_rows)
    summary_rows: list[dict[str, object]] = [
        {
            "format": "new" if tiledata.is_new_format else "old",
            "land_count": len(tiledata.land),
            "static_count": len(tiledata.statics),
        }
    ]
    _common._write_manifest(outdir / "summary.csv", summary_rows)
    print(
        f"Exported {len(tiledata.land)} land and {len(tiledata.statics)} static tiledata row(s) -> {outdir}"
    )
    return 0


def cmd_animdata_export(args: SimpleNamespace) -> int:
    """Export UO static-art animation metadata to CSV."""
    try:
        client = _common._client_path(args.client)
        animdata = _common._load_animdata(client)
        tiledata = _common._try_load_tiledata(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "animdata"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for entry in sorted(animdata.entries.values(), key=lambda item: item.tile_id):
        static_tile = (
            tiledata.statics[entry.tile_id]
            if tiledata is not None and entry.tile_id < len(tiledata.statics)
            else None
        )
        rows.append(
            {
                "tile_id": entry.tile_id,
                "tile_name": "" if static_tile is None else static_tile.name,
                "frame_count": entry.frame_count,
                "frame_interval": entry.frame_interval,
                "frame_start": entry.frame_start,
                "unknown": entry.unknown,
                "offsets": "|".join(str(value) for value in entry.frame_offsets),
                "active_offsets": "|".join(
                    str(value) for value in entry.active_offsets
                ),
            }
        )

    _common._write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(rows)} animdata row(s) -> {outdir}")
    return 0


def cmd_artdef_export(args: SimpleNamespace) -> int:
    """Export UO art.def redirect metadata to CSV."""
    try:
        client = _common._client_path(args.client)
        artdef = _common._load_artdef(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "artdef"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = [
        {
            "source": entry.source,
            "kind": "land" if entry.source < 0x4000 else "static",
            "tile_id": entry.source if entry.source < 0x4000 else entry.source - 0x4000,
            "targets": "|".join(str(value) for value in entry.targets),
            "first_target": "" if entry.first_target is None else entry.first_target,
            "hue": entry.hue,
        }
        for entry in sorted(artdef.entries.values(), key=lambda item: item.source)
    ]

    _common._write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(rows)} art.def redirect row(s) -> {outdir}")
    return 0


def cmd_def_export(args: SimpleNamespace) -> int:
    """Export all UO .def metadata to CSV."""
    try:
        client = _common._client_path(args.client)
        defs = _common._load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "defs"
    outdir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, object]] = []
    redirect_rows: list[dict[str, object]] = []
    bodyconv_rows: list[dict[str, object]] = []
    equipconv_rows: list[dict[str, object]] = []
    all_line_rows: list[dict[str, object]] = []

    for name, def_file in sorted(defs.items()):
        file_dir = outdir / Path(name).stem.lower()
        file_dir.mkdir(parents=True, exist_ok=True)
        line_rows = [
            {
                "file": line.file,
                "line": line.line_number,
                "kind": line.kind,
                "command": line.command,
                "args": "|".join(line.args),
                "comment": line.comment,
                "raw": line.raw,
            }
            for line in def_file.lines
        ]
        _common._write_manifest(file_dir / "lines.csv", line_rows)
        all_line_rows.extend(line_rows)

        summary_rows.append(
            {
                "file": def_file.path.name,
                "lines": len(def_file.lines),
                "redirects": len(def_file.redirects),
                "bodyconv_rows": len(def_file.bodyconv),
                "equipconv_rows": len(def_file.equipconv),
            }
        )

        for redirect_entry in sorted(
            def_file.redirects.values(), key=lambda item: item.source
        ):
            redirect_rows.append(
                {
                    "file": def_file.path.name,
                    "line": redirect_entry.line_number,
                    "source": redirect_entry.source,
                    "targets": "|".join(str(value) for value in redirect_entry.targets),
                    "first_target": (
                        ""
                        if redirect_entry.first_target is None
                        else redirect_entry.first_target
                    ),
                    "hue": "" if redirect_entry.hue is None else redirect_entry.hue,
                }
            )

        for bodyconv_entry in sorted(
            def_file.bodyconv.values(), key=lambda item: item.body
        ):
            bodyconv_rows.append(
                {
                    "file": def_file.path.name,
                    "line": bodyconv_entry.line_number,
                    "body": bodyconv_entry.body,
                    "anim2": bodyconv_entry.anim2,
                    "anim3": bodyconv_entry.anim3,
                    "anim4": bodyconv_entry.anim4,
                    "anim5": bodyconv_entry.anim5,
                    "anim6": bodyconv_entry.anim6,
                }
            )

        for equipconv_entry in def_file.equipconv:
            equipconv_rows.append(
                {
                    "file": def_file.path.name,
                    "line": equipconv_entry.line_number,
                    "body": equipconv_entry.body,
                    "equipment": equipconv_entry.equipment,
                    "convert_to": equipconv_entry.convert_to,
                    "gump": equipconv_entry.gump,
                    "hue": equipconv_entry.hue,
                    "comment": equipconv_entry.comment,
                }
            )

    _common._write_manifest(outdir / "summary.csv", summary_rows)
    _common._write_manifest(outdir / "redirects.csv", redirect_rows)
    _common._write_manifest(outdir / "bodyconv.csv", bodyconv_rows)
    _common._write_manifest(outdir / "equipconv.csv", equipconv_rows)
    _common._write_manifest(outdir / "lines.csv", all_line_rows)
    print(f"Exported {len(defs)} DEF file(s) -> {outdir}")
    return 0


def cmd_localization_export(args: SimpleNamespace) -> int:
    """Export UO localization, skill names, speech keywords, and text-list metadata."""
    try:
        client = _common._client_path(args.client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "localization"
    outdir.mkdir(parents=True, exist_ok=True)
    languages = (
        sorted(
            path.suffix.lstrip(".").lower()
            for path in client.glob("Cliloc.*")
            if path.suffix
        )
        if args.language == "all"
        else [args.language.lower()]
    )

    summary_rows: list[dict[str, object]] = []
    cliloc_all_rows: list[dict[str, object]] = []
    for language in languages:
        path = client / f"Cliloc.{language}"
        if not path.is_file():
            continue
        cliloc = UOCliloc.from_file(path)
        language_dir = outdir / "cliloc" / language
        language_dir.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, object]] = [
            {
                "language": language,
                "number": entry.number,
                "flag": entry.flag,
                "text": entry.text,
            }
            for entry in sorted(cliloc.entries.values(), key=lambda item: item.number)
        ]
        _common._write_manifest(language_dir / "manifest.csv", rows)
        cliloc_all_rows.extend(rows)
        summary_rows.append(
            {
                "source": path.name,
                "kind": "cliloc",
                "language": language,
                "rows": len(rows),
            }
        )
    _common._write_manifest(outdir / "cliloc.csv", cliloc_all_rows)

    speech_path = client / "speech.mul"
    if speech_path.is_file():
        speech = UOSpeech.from_file(speech_path)
        speech_rows: list[dict[str, object]] = [
            {
                "keyword_id": entry.keyword_id,
                "text": entry.text,
            }
            for entry in speech.entries
        ]
        _common._write_manifest(outdir / "speech.csv", speech_rows)
        summary_rows.append(
            {
                "source": speech_path.name,
                "kind": "speech",
                "language": "",
                "rows": len(speech_rows),
            }
        )

    skills_idx = client / "Skills.idx"
    skills_mul = client / "skills.mul"
    skills_by_id: dict[int, str] = {}
    if skills_idx.is_file() and skills_mul.is_file():
        skills = UOSkills.from_files(skills_idx, skills_mul)
        skills_by_id = {entry.skill_id: entry.name for entry in skills.entries}
        skill_rows: list[dict[str, object]] = [
            {
                "skill_id": entry.skill_id,
                "action": entry.action,
                "name": entry.name,
            }
            for entry in skills.entries
        ]
        _common._write_manifest(outdir / "skills.csv", skill_rows)
        summary_rows.append(
            {
                "source": "Skills.idx/skills.mul",
                "kind": "skills",
                "language": "",
                "rows": len(skill_rows),
            }
        )

    skillgrp_path = client / "skillgrp.mul"
    if skillgrp_path.is_file():
        skill_groups = UOSkillGroups.from_file(skillgrp_path)
        skill_group_rows: list[dict[str, object]] = [
            {
                "group_id": group.group_id,
                "name": group.name,
                "skill_ids": "|".join(str(skill_id) for skill_id in group.skills),
                "skill_names": "|".join(
                    skills_by_id.get(skill_id, "") for skill_id in group.skills
                ),
            }
            for group in skill_groups.groups
        ]
        _common._write_manifest(outdir / "skill_groups.csv", skill_group_rows)
        summary_rows.append(
            {
                "source": skillgrp_path.name,
                "kind": "skill_groups",
                "language": "",
                "rows": len(skill_group_rows),
            }
        )

    text_rows: list[dict[str, object]] = []
    for path in find_localized_text_files(client):
        language = path.suffix.lstrip(".").lower()
        if args.language != "all" and language != args.language:
            continue
        entries = parse_iff_text_file(path)
        category = _localized_text_category(path.stem)
        file_rows = [
            {
                "category": category,
                "source": entry.source,
                "language": entry.language,
                "index": entry.index,
                "keys": "|".join(str(key) for key in entry.keys),
                "text": entry.text,
            }
            for entry in entries
        ]
        text_rows.extend(file_rows)
        summary_rows.append(
            {
                "source": path.name,
                "kind": "system_text",
                "category": category,
                "language": language,
                "rows": len(file_rows),
            }
        )
    _common._write_manifest(outdir / "system_text.csv", text_rows)
    _common._write_manifest(outdir / "text_lists.csv", text_rows)
    _common._write_manifest(outdir / "summary.csv", summary_rows)
    print(f"Exported localization metadata -> {outdir}")
    return 0


def cmd_sound_export(args: SimpleNamespace) -> int:
    """Export UO sounds to WAV."""
    try:
        client = _common._client_path(args.client)
        indexed = _load_sounds(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
        )
        defs = _common._try_load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _common._entry_iter(indexed, args.range_start, args.range_end)
    outdir = _common._out(args) / "sounds"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved = 0
    failed = 0
    metadata = _sound_metadata(defs)

    for entry in entries:
        if args.limit is not None and saved >= args.limit:
            break
        sound = UOSoundDecoder.decode(entry)
        if sound is None:
            failed += 1
            continue

        filename = f"{sound.index:05d}.wav"
        (outdir / filename).write_bytes(sound.to_wav())
        row: dict[str, object] = {
            "id": sound.index,
            "file": filename,
            "name": sound.name,
            "pcm_bytes": len(sound.pcm),
            "seconds": f"{sound.seconds:.3f}",
            "sample_rate": 22050,
            "channels": 1,
            "bits_per_sample": 16,
        }
        row.update(metadata(entry))
        rows.append(row)
        saved += 1

    _common._write_manifest(outdir / "manifest.csv", rows)
    print(
        f"Exported {saved} sound(s) from {len(entries)} indexed entrie(s) -> {outdir}"
    )
    if failed:
        print(f"  ({failed} sound entrie(s) failed or decoded empty)")
    return 0


def tiledata_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
) -> None:
    """Export UO tile metadata to CSV."""
    raise SystemExit(cmd_tiledata_export(SimpleNamespace(**locals())))


def animdata_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
) -> None:
    """Export UO static-art animation metadata to CSV."""
    raise SystemExit(cmd_animdata_export(SimpleNamespace(**locals())))


def artdef_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
) -> None:
    """Export UO art.def redirect metadata to CSV."""
    raise SystemExit(cmd_artdef_export(SimpleNamespace(**locals())))


def def_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
) -> None:
    """Export all UO .def metadata to CSV."""
    raise SystemExit(cmd_def_export(SimpleNamespace(**locals())))


def localization_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    language: Annotated[
        str,
        typer.Option("--language", help="Language code such as enu, or all."),
    ] = "all",
) -> None:
    """Export UO localization and name metadata to CSV."""
    raise SystemExit(cmd_localization_export(SimpleNamespace(**locals())))


def sound_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded sounds to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First sound ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last sound ID, exclusive."),
    ] = None,
) -> None:
    """Export UO sounds to WAV."""
    raise SystemExit(cmd_sound_export(SimpleNamespace(**locals())))
