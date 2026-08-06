"""Ultima Online Classic Client CLI sub-app."""

from __future__ import annotations

__all__ = ["uo_app"]

import csv
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan._config import get_config
from titan.uo.animation import (
    UOAnimationDecoder,
    animation_naming,
    legacy_animation_slot,
    load_mobtype_flags,
    load_mobtypes,
)
from titan.uo.animresolve import (
    UOAnimationResolution,
    UOAnimationResolver,
    UOAnimationSequence,
    animation_entry_index,
)
from titan.uo.animnames import UOAnimationBodyNames, load_animation_body_names
from titan.uo.animdata import UOAnimData, UOAnimDataEntry
from titan.uo.art import UOArtDecoder
from titan.uo.artdef import UOArtDef, UOArtDefEntry
from titan.uo.definfo import (
    UOBodyConvDefEntry,
    UODefFile,
    UOEquipConvDefEntry,
    UORedirectDefEntry,
    load_all_defs,
)
from titan.uo.font import UOAsciiFonts
from titan.uo.gump import UOGumpDecoder
from titan.uo.hue import UOHuesFile
from titan.uo.indexed import UOIndexedFile, UOIndexEntry
from titan.uo.light import UOLightDecoder
from titan.uo.localization import (
    UOCliloc,
    UOSkillGroups,
    UOSkills,
    UOSpeech,
    find_localized_text_files,
    parse_iff_text_file,
)
from titan.uo.multi import UOMultis
from titan.uo.radar import UORadarColors
from titan.uo.sound import UOSoundDecoder
from titan.uo.tiledata import UOLandTile, UOStaticTile, UOTileData
from titan.uo.texture import UOTextureDecoder

uo_app = typer.Typer(
    name="uo",
    help="Ultima Online Classic Client commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _client_path(client: str | None = None) -> Path:
    client_value = client or get_config().get("uo", {}).get("game", {}).get("base")
    if not client_value:
        raise FileNotFoundError(
            "UO client directory not configured; pass CLIENT or set [uo.game] base in titan.toml"
        )
    path = Path(client_value)
    if not path.is_dir():
        raise FileNotFoundError(f"client directory not found: {client_value}")
    return path


def _load_art(
    client: Path,
    *,
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
    limit: Optional[int] = None,
    kind: Literal["all", "land", "static"] = "all",
) -> UOIndexedFile:
    if kind == "static" and range_start is None:
        range_start = 0x4000
    elif kind == "land" and range_end is None:
        range_end = 0x4000

    uop = client / "artLegacyMUL.uop"
    if uop.is_file():
        return UOIndexedFile.from_uop(
            uop,
            entry_count=0x14000,
            range_start=range_start,
            range_end=range_end,
            max_entries=limit,
        )

    mul = client / "art.mul"
    idx = client / "artidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("artLegacyMUL.uop or art.mul/artidx.mul not found")


def _load_gumps(
    client: Path,
    *,
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
    limit: Optional[int] = None,
) -> UOIndexedFile:
    uop = client / "gumpartLegacyMUL.uop"
    if uop.is_file():
        return UOIndexedFile.from_uop(
            uop,
            entry_count=0x10000,
            has_extra_header=True,
            range_start=range_start,
            range_end=range_end,
            max_entries=limit,
        )

    mul = client / "gumpart.mul"
    idx = client / "gumpidx.mul"
    if not mul.is_file():
        mul = client / "Gumpart.mul"
    if not idx.is_file():
        idx = client / "Gumpidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("gumpartLegacyMUL.uop or gumpart.mul/gumpidx.mul not found")


def _load_textures(client: Path) -> UOIndexedFile:
    mul = client / "texmaps.mul"
    idx = client / "texidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("texmaps.mul/texidx.mul not found")


def _load_lights(client: Path) -> UOIndexedFile:
    mul = client / "light.mul"
    idx = client / "lightidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("light.mul/lightidx.mul not found")


def _load_hues(client: Path) -> UOHuesFile:
    path = client / "hues.mul"
    if path.is_file():
        return UOHuesFile.from_file(path)

    raise FileNotFoundError("hues.mul not found")


def _load_radar(client: Path) -> UORadarColors:
    path = client / "radarcol.mul"
    if path.is_file():
        return UORadarColors.from_file(path)

    raise FileNotFoundError("radarcol.mul not found")


def _load_cliloc(client: Path, language: str) -> UOCliloc:
    path = client / f"Cliloc.{language}"
    if path.is_file():
        return UOCliloc.from_file(path)
    raise FileNotFoundError(f"Cliloc.{language} not found")


def _try_load_tilehelp(client: Path, language: str) -> dict[int, str]:
    path = client / f"Tilehelp.{language}"
    if not path.is_file():
        return {}
    text_by_tile: dict[int, str] = {}
    for entry in parse_iff_text_file(path):
        for key in entry.keys:
            text_by_tile[key] = entry.text
    return text_by_tile


def _load_fonts(client: Path, *, max_fonts: int) -> UOAsciiFonts:
    path = client / "fonts.mul"
    if path.is_file():
        return UOAsciiFonts.from_file(path, max_fonts=max_fonts)

    raise FileNotFoundError("fonts.mul not found")


def _load_tiledata(client: Path) -> UOTileData:
    path = client / "tiledata.mul"
    if path.is_file():
        return UOTileData.from_file(path)

    raise FileNotFoundError("tiledata.mul not found")


def _try_load_tiledata(client: Path) -> UOTileData | None:
    try:
        return _load_tiledata(client)
    except FileNotFoundError:
        return None


def _load_animdata(client: Path) -> UOAnimData:
    path = client / "animdata.mul"
    if path.is_file():
        return UOAnimData.from_file(path)
    raise FileNotFoundError("animdata.mul not found")


def _try_load_animdata(client: Path) -> UOAnimData | None:
    try:
        return _load_animdata(client)
    except FileNotFoundError:
        return None


def _load_artdef(client: Path) -> UOArtDef:
    path = client / "art.def"
    if path.is_file():
        return UOArtDef.from_file(path)
    raise FileNotFoundError("art.def not found")


def _try_load_artdef(client: Path) -> UOArtDef | None:
    try:
        return _load_artdef(client)
    except FileNotFoundError:
        return None


def _load_defs(client: Path) -> dict[str, UODefFile]:
    defs = load_all_defs(client)
    if not defs:
        raise FileNotFoundError("no .def files found")
    return defs


def _try_load_defs(client: Path) -> dict[str, UODefFile]:
    try:
        return _load_defs(client)
    except FileNotFoundError:
        return {}


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


def _load_animations(client: Path, set_name: str) -> UOIndexedFile:
    allowed = {"anim", "anim2", "anim3", "anim4", "anim5", "anim6"}
    if set_name not in allowed:
        raise ValueError(f"unsupported animation set: {set_name}")

    mul = client / f"{set_name}.mul"
    idx = client / f"{set_name}.idx"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError(f"{set_name}.mul/{set_name}.idx not found")


def _try_load_animation_sequence(client: Path) -> UOAnimationSequence | None:
    path = client / "AnimationSequence.uop"
    if not path.is_file():
        return None
    try:
        return UOAnimationSequence.from_file(path)
    except Exception:
        return None


def _animation_resolver(
    client: Path,
    defs: dict[str, UODefFile],
) -> UOAnimationResolver:
    return UOAnimationResolver(
        defs=defs,
        sequence=_try_load_animation_sequence(client),
        mobtype_flags=load_mobtype_flags(client / "mobtypes.txt"),
    )


def _entry_iter(
    indexed: UOIndexedFile,
    start: Optional[int],
    end: Optional[int],
) -> list[UOIndexEntry]:
    lo = 0 if start is None else start
    hi = (max(indexed.entries) + 1) if end is None and indexed.entries else (end or 0)
    return [
        entry
        for entry_id, entry in sorted(indexed.entries.items())
        if lo <= entry_id < hi
    ]


def _write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _tile_flag_text(flags: tuple[str, ...]) -> str:
    return "|".join(flags)


def _land_metadata(tile: UOLandTile | None) -> dict[str, object]:
    if tile is None:
        return {
            "tile_name": "",
            "texture_id": "",
            "tile_flags": "",
        }
    return {
        "tile_name": tile.name,
        "texture_id": tile.texture_id,
        "tile_flags": _tile_flag_text(tile.flag_names),
    }


def _animdata_metadata(entry: UOAnimDataEntry | None) -> dict[str, object]:
    if entry is None:
        return {
            "static_animation": "",
            "animdata_frame_count": "",
            "animdata_frame_interval": "",
            "animdata_frame_start": "",
            "animdata_unknown": "",
            "animdata_offsets": "",
            "animdata_active_offsets": "",
        }
    return {
        "static_animation": 1,
        "animdata_frame_count": entry.frame_count,
        "animdata_frame_interval": entry.frame_interval,
        "animdata_frame_start": entry.frame_start,
        "animdata_unknown": entry.unknown,
        "animdata_offsets": "|".join(str(value) for value in entry.frame_offsets),
        "animdata_active_offsets": "|".join(
            str(value) for value in entry.active_offsets
        ),
    }


def _artdef_metadata(entry: UOArtDefEntry | None) -> dict[str, object]:
    if entry is None:
        return {
            "artdef_redirect": "",
            "artdef_targets": "",
            "artdef_first_target": "",
            "artdef_hue": "",
        }
    return {
        "artdef_redirect": 1,
        "artdef_targets": "|".join(str(value) for value in entry.targets),
        "artdef_first_target": "" if entry.first_target is None else entry.first_target,
        "artdef_hue": entry.hue,
    }


def _redirect_metadata(
    prefix: str, entry: UORedirectDefEntry | None
) -> dict[str, object]:
    if entry is None:
        return {
            f"{prefix}_redirect": "",
            f"{prefix}_targets": "",
            f"{prefix}_first_target": "",
            f"{prefix}_hue": "",
            f"{prefix}_line": "",
        }
    return {
        f"{prefix}_redirect": 1,
        f"{prefix}_targets": "|".join(str(value) for value in entry.targets),
        f"{prefix}_first_target": ""
        if entry.first_target is None
        else entry.first_target,
        f"{prefix}_hue": "" if entry.hue is None else entry.hue,
        f"{prefix}_line": entry.line_number,
    }


def _bodyconv_metadata(entry: UOBodyConvDefEntry | None) -> dict[str, object]:
    if entry is None:
        return {
            "bodyconv": "",
            "bodyconv_anim2": "",
            "bodyconv_anim3": "",
            "bodyconv_anim4": "",
            "bodyconv_anim5": "",
            "bodyconv_anim6": "",
            "bodyconv_line": "",
        }
    return {
        "bodyconv": 1,
        "bodyconv_anim2": entry.anim2,
        "bodyconv_anim3": entry.anim3,
        "bodyconv_anim4": entry.anim4,
        "bodyconv_anim5": entry.anim5,
        "bodyconv_anim6": entry.anim6,
        "bodyconv_line": entry.line_number,
    }


def _equipconv_rows(
    entries: list[UOEquipConvDefEntry],
    *,
    body: int,
    equipment: int,
) -> list[UOEquipConvDefEntry]:
    return [
        entry
        for entry in entries
        if entry.body == body and entry.equipment == equipment
    ]


def _equipconv_metadata(entries: list[UOEquipConvDefEntry]) -> dict[str, object]:
    if not entries:
        return {
            "equipconv": "",
            "equipconv_bodies": "",
            "equipconv_convert_to": "",
            "equipconv_gumps": "",
            "equipconv_hues": "",
            "equipconv_comments": "",
        }
    return {
        "equipconv": 1,
        "equipconv_bodies": "|".join(str(entry.body) for entry in entries),
        "equipconv_convert_to": "|".join(str(entry.convert_to) for entry in entries),
        "equipconv_gumps": "|".join(str(entry.gump) for entry in entries),
        "equipconv_hues": "|".join(str(entry.hue) for entry in entries),
        "equipconv_comments": "|".join(
            entry.comment for entry in entries if entry.comment
        ),
    }


def _static_metadata(
    tile: UOStaticTile | None,
    animdata_entry: UOAnimDataEntry | None = None,
    tilehelp: dict[int, str] | None = None,
) -> dict[str, object]:
    if tile is None:
        return {
            "tile_name": "",
            "weight": "",
            "quality": "",
            "misc_data": "",
            "unknown2": "",
            "quantity": "",
            "anim_id": "",
            "unknown3": "",
            "hue": "",
            "stacking_offset": "",
            "value": "",
            "height": "",
            "tile_flags": "",
            "tilehelp": "",
            **_animdata_metadata(animdata_entry),
        }
    help_text = "" if tilehelp is None else tilehelp.get(tile.tile_id, "")
    return {
        "tile_name": tile.name,
        "weight": tile.weight,
        "quality": tile.quality,
        "misc_data": tile.misc_data,
        "unknown2": tile.unknown2,
        "quantity": tile.quantity,
        "anim_id": tile.anim_id,
        "unknown3": tile.unknown3,
        "hue": tile.hue,
        "stacking_offset": tile.stacking_offset,
        "value": tile.value,
        "height": tile.height,
        "tile_flags": _tile_flag_text(tile.flag_names),
        "tilehelp": help_text,
        **_animdata_metadata(animdata_entry),
    }


def _art_metadata(
    tiledata: UOTileData | None,
    animdata: UOAnimData | None,
    artdef: UOArtDef | None,
    defs: dict[str, UODefFile] | None = None,
    tilehelp: dict[int, str] | None = None,
):
    texterr = None if defs is None else defs.get("texterr.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        artdef_entry = artdef.entries.get(entry.index) if artdef is not None else None
        if entry.index < 0x4000:
            texterr_entry = (
                texterr.redirects.get(entry.index) if texterr is not None else None
            )
            land_tile = (
                tiledata.land[entry.index]
                if tiledata is not None and entry.index < len(tiledata.land)
                else None
            )
            return {
                "tile_kind": "land",
                "tile_id": entry.index,
                **_land_metadata(land_tile),
                **_artdef_metadata(artdef_entry),
                **_redirect_metadata("texterr", texterr_entry),
            }

        tile_id = entry.index - 0x4000
        static_tile = (
            tiledata.statics[tile_id]
            if tiledata is not None and tile_id < len(tiledata.statics)
            else None
        )
        anim_entry = animdata.entries.get(tile_id) if animdata is not None else None
        return {
            "tile_kind": "static",
            "tile_id": tile_id,
            **_static_metadata(static_tile, anim_entry, tilehelp),
            **_artdef_metadata(artdef_entry),
            **_redirect_metadata("texterr", None),
        }

    return metadata


def _gump_metadata(defs: dict[str, UODefFile]):
    gumpdef = defs.get("gump.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        redirect = gumpdef.redirects.get(entry.index) if gumpdef is not None else None
        return _redirect_metadata("gumpdef", redirect)

    return metadata


def _texture_metadata(
    tiledata: UOTileData | None,
    defs: dict[str, UODefFile] | None = None,
):
    texterr = None if defs is None else defs.get("texterr.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        if tiledata is None:
            return {
                "land_tile_count": "",
                "land_tile_ids": "",
                "land_tile_names": "",
                "texterr_redirect_count": "",
                "texterr_land_tile_ids": "",
                "texterr_targets": "",
                "texterr_hues": "",
            }

        tiles = tiledata.land_by_texture.get(entry.index, [])
        redirects = [
            redirect
            for tile in tiles
            if texterr is not None
            for redirect in [texterr.redirects.get(tile.tile_id)]
            if redirect is not None
        ]
        return {
            "land_tile_count": len(tiles),
            "land_tile_ids": "|".join(str(tile.tile_id) for tile in tiles[:32]),
            "land_tile_names": "|".join(tile.name for tile in tiles[:16] if tile.name),
            "texterr_redirect_count": len(redirects),
            "texterr_land_tile_ids": "|".join(
                str(redirect.source) for redirect in redirects[:32]
            ),
            "texterr_targets": "|".join(
                str(redirect.first_target)
                for redirect in redirects[:32]
                if redirect.first_target is not None
            ),
            "texterr_hues": "|".join(
                str(redirect.hue)
                for redirect in redirects[:32]
                if redirect.hue is not None
            ),
        }

    return metadata


def _sound_metadata(defs: dict[str, UODefFile]):
    sounddef = defs.get("sound.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        redirect = sounddef.redirects.get(entry.index) if sounddef is not None else None
        return _redirect_metadata("sounddef", redirect)

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


def _animation_def_metadata(
    defs: dict[str, UODefFile],
    *,
    set_name: str,
    body: int,
) -> dict[str, object]:
    bodydef = defs.get("body.def")
    corpse = defs.get("corpse.def")
    anim1 = defs.get("anim1.def")
    anim2 = defs.get("anim2.def")
    bodyconv = defs.get("bodyconv.def")
    equipconv = defs.get("equipconv.def")

    bodyconv_entry = bodyconv.bodyconv.get(body) if bodyconv is not None else None
    equip_matches = (
        [entry for entry in equipconv.equipconv if entry.equipment == body]
        if equipconv is not None
        else []
    )
    return {
        **_redirect_metadata(
            "bodydef", bodydef.redirects.get(body) if bodydef is not None else None
        ),
        **_redirect_metadata(
            "corpse", corpse.redirects.get(body) if corpse is not None else None
        ),
        **_redirect_metadata(
            "anim1def", anim1.redirects.get(body) if anim1 is not None else None
        ),
        **_redirect_metadata(
            "anim2def", anim2.redirects.get(body) if anim2 is not None else None
        ),
        **_bodyconv_metadata(bodyconv_entry),
        "bodyconv_effective_archive": (
            ""
            if bodyconv_entry is None
            else bodyconv_entry.archive_for_set(set_name) or ""
        ),
        **_equipconv_metadata(equip_matches),
    }


def _animation_resolution_metadata(
    resolution: UOAnimationResolution | None,
) -> dict[str, object]:
    if resolution is None:
        return {
            "requested_body": "",
            "requested_action": "",
            "requested_direction": "",
            "resolved_bodydef_body": "",
            "resolved_bodydef_hue": "",
            "resolved_final_body": "",
            "resolved_final_set": "",
            "resolved_file_type": "",
            "resolved_action": "",
            "resolved_direction": "",
            "resolved_raw_entry": "",
            "resolved_uop_frame_path": "",
            "resolved_bodydef_applied": "",
            "resolved_bodyconv_applied": "",
            "resolved_sequence_applied": "",
            "resolved_uop_sequence_body": "",
        }
    return {
        "requested_body": resolution.requested_body,
        "requested_action": resolution.requested_action,
        "requested_direction": resolution.requested_direction,
        "resolved_bodydef_body": resolution.bodydef_body,
        "resolved_bodydef_hue": (
            "" if resolution.bodydef_hue is None else resolution.bodydef_hue
        ),
        "resolved_final_body": resolution.final_body,
        "resolved_final_set": resolution.final_set,
        "resolved_file_type": resolution.final_file_type,
        "resolved_action": resolution.final_action,
        "resolved_direction": resolution.final_direction,
        "resolved_raw_entry": resolution.raw_entry,
        "resolved_uop_frame_path": (
            resolution.uop_frame_path if resolution.is_uop_sequence_body else ""
        ),
        "resolved_bodydef_applied": 1 if resolution.bodydef_applied else 0,
        "resolved_bodyconv_applied": 1 if resolution.bodyconv_applied else 0,
        "resolved_sequence_applied": 1 if resolution.sequence_applied else 0,
        "resolved_uop_sequence_body": 1 if resolution.is_uop_sequence_body else 0,
    }


def _animation_body_name_metadata(
    *,
    body_names: UOAnimationBodyNames | None,
    prefix: str,
    body: int,
) -> dict[str, object]:
    if body_names is None:
        return {
            f"{prefix}_body_name": "",
            f"{prefix}_body_name_source": "",
            f"{prefix}_body_name_alternates": "",
        }

    preferred = body_names.preferred(body)
    return {
        f"{prefix}_body_name": "" if preferred is None else preferred.name,
        f"{prefix}_body_name_source": "" if preferred is None else preferred.source,
        f"{prefix}_body_name_alternates": "|".join(body_names.names_for(body)),
    }


def _animation_body_dir(
    *,
    body: int,
    category: str,
    body_names: UOAnimationBodyNames | None,
) -> str:
    preferred = body_names.preferred(body) if body_names is not None else None
    if preferred is None:
        return f"body_{body:04d}_{_safe_path_part(category)}"
    return (
        f"body_{body:04d}_{_safe_path_part(preferred.name)}_{_safe_path_part(category)}"
    )


def _safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "unknown"


def _export_entries(
    *,
    entries: list[UOIndexEntry],
    outdir: Path,
    group: str,
    decode,
    limit: Optional[int],
    metadata=None,
) -> tuple[int, int, int]:
    target = outdir / group
    target.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved = 0
    failed = 0

    for entry in entries:
        if limit is not None and saved >= limit:
            break

        try:
            image = decode(entry)
        except Exception as exc:
            print(f"  WARNING: failed {group} {entry.index}: {exc}", file=sys.stderr)
            failed += 1
            continue

        if image is None:
            failed += 1
            continue

        filename = f"{entry.index:05d}.png"
        image.save(target / filename)
        row: dict[str, object] = {
            "id": entry.index,
            "file": filename,
            "width": image.width,
            "height": image.height,
            "payload_bytes": len(entry.data),
            "extra": f"0x{entry.extra:08X}",
        }
        if metadata is not None:
            row.update(metadata(entry))
        rows.append(row)
        saved += 1

    _write_manifest(target / "manifest.csv", rows)
    return saved, failed, len(entries)


def cmd_art_export(args: SimpleNamespace) -> int:
    """Export UO art land tiles and static/item sprites to PNG."""
    try:
        client = _client_path(args.client)
        indexed = _load_art(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
            kind=args.kind,
        )
        tiledata = _try_load_tiledata(client)
        animdata = _try_load_animdata(client)
        artdef = _try_load_artdef(client)
        defs = _try_load_defs(client)
        tilehelp = _try_load_tilehelp(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _entry_iter(indexed, args.range_start, args.range_end)
    if args.kind == "land":
        entries = [entry for entry in entries if entry.index < 0x4000]
    elif args.kind == "static":
        entries = [entry for entry in entries if entry.index >= 0x4000]

    outdir = Path(args.output)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="art",
        decode=UOArtDecoder.decode,
        limit=args.limit,
        metadata=_art_metadata(tiledata, animdata, artdef, defs, tilehelp),
    )
    print(
        f"Exported {saved} art image(s) from {total} indexed entrie(s) -> {outdir / 'art'}"
    )
    if failed:
        print(f"  ({failed} art entrie(s) failed or decoded empty)")
    return 0


def cmd_gump_export(args: SimpleNamespace) -> int:
    """Export UO gump images to PNG."""
    try:
        client = _client_path(args.client)
        indexed = _load_gumps(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
        )
        defs = _try_load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _entry_iter(indexed, args.range_start, args.range_end)
    outdir = Path(args.output)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="gumps",
        decode=UOGumpDecoder.decode,
        limit=args.limit,
        metadata=_gump_metadata(defs),
    )
    print(
        f"Exported {saved} gump image(s) from {total} indexed entrie(s) -> {outdir / 'gumps'}"
    )
    if failed:
        print(f"  ({failed} gump entrie(s) failed or decoded empty)")
    return 0


def cmd_texture_export(args: SimpleNamespace) -> int:
    """Export UO land textures to PNG."""
    try:
        client = _client_path(args.client)
        indexed = _load_textures(client)
        tiledata = _try_load_tiledata(client)
        defs = _try_load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _entry_iter(indexed, args.range_start, args.range_end)
    outdir = Path(args.output)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="textures",
        decode=UOTextureDecoder.decode,
        limit=args.limit,
        metadata=_texture_metadata(tiledata, defs),
    )
    print(
        f"Exported {saved} texture image(s) from {total} indexed entrie(s) -> {outdir / 'textures'}"
    )
    if failed:
        print(f"  ({failed} texture entrie(s) failed or decoded empty)")
    return 0


def cmd_light_export(args: SimpleNamespace) -> int:
    """Export UO light masks to PNG."""
    try:
        client = _client_path(args.client)
        indexed = _load_lights(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _entry_iter(indexed, args.range_start, args.range_end)
    outdir = Path(args.output)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="lights",
        decode=UOLightDecoder.decode,
        limit=args.limit,
    )
    print(
        f"Exported {saved} light image(s) from {total} indexed entrie(s) -> {outdir / 'lights'}"
    )
    if failed:
        print(f"  ({failed} light entrie(s) failed or decoded empty)")
    return 0


def cmd_hue_export(args: SimpleNamespace) -> int:
    """Export UO hue ramps to PNG."""
    try:
        client = _client_path(args.client)
        hues = _load_hues(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    start = 0 if args.range_start is None else args.range_start
    end = (
        len(hues.hues)
        if args.range_end is None
        else min(args.range_end, len(hues.hues))
    )
    selected = [hue for hue in hues.hues if start <= hue.index < end]

    outdir = Path(args.output) / "hues"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved = 0

    for hue in selected:
        if args.limit is not None and saved >= args.limit:
            break
        filename = f"{hue.index:05d}.png"
        hue.to_image(swatch_size=args.swatch_size).save(outdir / filename)
        rows.append(
            {
                "index": hue.index,
                "client_id": hue.client_id,
                "file": filename,
                "group": hue.group,
                "entry": hue.entry,
                "table_start": hue.table_start,
                "table_end": hue.table_end,
                "name": hue.name,
            }
        )
        saved += 1

    _write_manifest(outdir / "manifest.csv", rows)
    print(
        f"Exported {saved} hue ramp image(s) from {len(selected)} hue entrie(s) -> {outdir}"
    )
    return 0


def cmd_radar_export(args: SimpleNamespace) -> int:
    """Export the UO radar/minimap color lookup table."""
    try:
        client = _client_path(args.client)
        radar = _load_radar(client)
        tiledata = _try_load_tiledata(client)
        animdata = _try_load_animdata(client)
        defs = _try_load_defs(client)
        tilehelp = _try_load_tilehelp(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "radar"
    outdir.mkdir(parents=True, exist_ok=True)
    radar.to_swatch_image(
        columns=args.columns,
        swatch_size=args.swatch_size,
    ).save(outdir / "radarcol.png")

    rows: list[dict[str, object]] = []
    for color in radar.colors:
        red, green, blue = color.rgb
        is_land = color.index < 0x4000
        tile_id = color.index if is_land else color.index - 0x4000
        row: dict[str, object] = {
            "index": color.index,
            "kind": "land" if is_land else "static",
            "tile_id": tile_id,
            "color16": f"0x{color.color16:04X}",
            "red": red,
            "green": green,
            "blue": blue,
        }
        if is_land:
            land_tile = (
                tiledata.land[tile_id]
                if tiledata is not None and tile_id < len(tiledata.land)
                else None
            )
            row.update(_land_metadata(land_tile))
            texterr = defs.get("texterr.def")
            row.update(
                _redirect_metadata(
                    "texterr",
                    (texterr.redirects.get(tile_id) if texterr is not None else None),
                )
            )
        else:
            static_tile = (
                tiledata.statics[tile_id]
                if tiledata is not None and tile_id < len(tiledata.statics)
                else None
            )
            anim_entry = animdata.entries.get(tile_id) if animdata is not None else None
            row.update(_static_metadata(static_tile, anim_entry, tilehelp))
            row.update(_redirect_metadata("texterr", None))
        rows.append(row)
    _write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(radar.colors)} radar color(s) -> {outdir}")
    return 0


def cmd_tiledata_export(args: SimpleNamespace) -> int:
    """Export UO tile metadata to CSV."""
    try:
        client = _client_path(args.client)
        tiledata = _load_tiledata(client)
        animdata = _try_load_animdata(client)
        defs = _try_load_defs(client)
        tilehelp = _try_load_tilehelp(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "tiledata"
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
                "flag_names": _tile_flag_text(land_tile.flag_names),
                **_redirect_metadata("texterr", texterr_entry),
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
                "flag_names": _tile_flag_text(static_tile.flag_names),
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
                **_animdata_metadata(anim_entry),
            }
        )

    _write_manifest(outdir / "land.csv", land_rows)
    _write_manifest(outdir / "statics.csv", static_rows)
    summary_rows: list[dict[str, object]] = [
        {
            "format": "new" if tiledata.is_new_format else "old",
            "land_count": len(tiledata.land),
            "static_count": len(tiledata.statics),
        }
    ]
    _write_manifest(outdir / "summary.csv", summary_rows)
    print(
        f"Exported {len(tiledata.land)} land and {len(tiledata.statics)} static tiledata row(s) -> {outdir}"
    )
    return 0


def cmd_animdata_export(args: SimpleNamespace) -> int:
    """Export UO static-art animation metadata to CSV."""
    try:
        client = _client_path(args.client)
        animdata = _load_animdata(client)
        tiledata = _try_load_tiledata(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "animdata"
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

    _write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(rows)} animdata row(s) -> {outdir}")
    return 0


def cmd_artdef_export(args: SimpleNamespace) -> int:
    """Export UO art.def redirect metadata to CSV."""
    try:
        client = _client_path(args.client)
        artdef = _load_artdef(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "artdef"
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

    _write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(rows)} art.def redirect row(s) -> {outdir}")
    return 0


def cmd_def_export(args: SimpleNamespace) -> int:
    """Export all UO .def metadata to CSV."""
    try:
        client = _client_path(args.client)
        defs = _load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "defs"
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
        _write_manifest(file_dir / "lines.csv", line_rows)
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

    _write_manifest(outdir / "summary.csv", summary_rows)
    _write_manifest(outdir / "redirects.csv", redirect_rows)
    _write_manifest(outdir / "bodyconv.csv", bodyconv_rows)
    _write_manifest(outdir / "equipconv.csv", equipconv_rows)
    _write_manifest(outdir / "lines.csv", all_line_rows)
    print(f"Exported {len(defs)} DEF file(s) -> {outdir}")
    return 0


def cmd_localization_export(args: SimpleNamespace) -> int:
    """Export UO localization, skill names, speech keywords, and text-list metadata."""
    try:
        client = _client_path(args.client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "localization"
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
        _write_manifest(language_dir / "manifest.csv", rows)
        cliloc_all_rows.extend(rows)
        summary_rows.append(
            {
                "source": path.name,
                "kind": "cliloc",
                "language": language,
                "rows": len(rows),
            }
        )
    _write_manifest(outdir / "cliloc.csv", cliloc_all_rows)

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
        _write_manifest(outdir / "speech.csv", speech_rows)
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
        _write_manifest(outdir / "skills.csv", skill_rows)
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
        _write_manifest(outdir / "skill_groups.csv", skill_group_rows)
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
    _write_manifest(outdir / "system_text.csv", text_rows)
    _write_manifest(outdir / "text_lists.csv", text_rows)
    _write_manifest(outdir / "summary.csv", summary_rows)
    print(f"Exported localization metadata -> {outdir}")
    return 0


def cmd_multi_export(args: SimpleNamespace) -> int:
    """Export UO multi component metadata to CSV."""
    try:
        client = _client_path(args.client)
        multis = UOMultis.from_client(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
            prefer_uop=not args.mul_only,
        )
        tiledata = _try_load_tiledata(client)
        animdata = _try_load_animdata(client)
        tilehelp = _try_load_tilehelp(client, "enu")
        cliloc = _load_cliloc(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "multis"
    outdir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, object]] = []
    component_rows: list[dict[str, object]] = []

    for multi in sorted(multis.multis.values(), key=lambda item: item.multi_id):
        min_x, max_x, min_y, max_y, min_z, max_z = multi.bounds
        summary_rows.append(
            {
                "multi_id": multi.multi_id,
                "source": multi.source,
                "layout": multi.layout,
                "component_count": len(multi.components),
                "visible_component_count": len(multi.visible_components),
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
                "min_z": min_z,
                "max_z": max_z,
                "width": max_x - min_x + 1 if multi.components else 0,
                "height": max_y - min_y + 1 if multi.components else 0,
            }
        )
        for component_index, component in enumerate(multi.components):
            static_tile = (
                tiledata.statics[component.item_id]
                if tiledata is not None and component.item_id < len(tiledata.statics)
                else None
            )
            anim_entry = (
                animdata.entries.get(component.item_id)
                if animdata is not None
                else None
            )
            cliloc_texts = [
                cliloc.entries[value].text
                for value in component.clilocs
                if value in cliloc.entries
            ]
            row: dict[str, object] = {
                "multi_id": multi.multi_id,
                "component": component_index,
                "source": multi.source,
                "layout": multi.layout,
                "item_id": component.item_id,
                "art_id": component.item_id + 0x4000,
                "x": component.x,
                "y": component.y,
                "z": component.z,
                "flags": f"0x{component.flags:X}",
                "extra": f"0x{component.extra:X}",
                "visible": 1 if component.visible else 0,
                "clilocs": "|".join(str(value) for value in component.clilocs),
                "cliloc_text": "|".join(cliloc_texts),
            }
            row.update(_static_metadata(static_tile, anim_entry, tilehelp))
            component_rows.append(row)

    _write_manifest(outdir / "summary.csv", summary_rows)
    _write_manifest(outdir / "components.csv", component_rows)
    print(
        f"Exported {len(summary_rows)} multi(s), {len(component_rows)} component row(s) -> {outdir}"
    )
    return 0


def cmd_font_export(args: SimpleNamespace) -> int:
    """Export UO ASCII font atlases and glyph metadata."""
    try:
        client = _client_path(args.client)
        fonts = _load_fonts(client, max_fonts=args.limit_fonts)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.output) / "fonts"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for font in fonts.fonts:
        font_dir = outdir / f"font_{font.index:03d}"
        font_dir.mkdir(parents=True, exist_ok=True)
        atlas_file = "atlas.png"
        font.atlas(columns=args.columns).save(font_dir / atlas_file)

        if args.glyphs:
            glyph_dir = font_dir / "glyphs"
            glyph_dir.mkdir(parents=True, exist_ok=True)
        else:
            glyph_dir = None

        for glyph in font.glyphs:
            glyph_file = ""
            if glyph_dir is not None and glyph.image is not None:
                glyph_file = f"{glyph.char_code:03d}.png"
                glyph.image.save(glyph_dir / glyph_file)
            rows.append(
                {
                    "font": font.index,
                    "font_header": f"0x{font.header:02X}",
                    "glyph": glyph.index,
                    "char_code": glyph.char_code,
                    "char": glyph.char if 32 <= glyph.char_code < 127 else "",
                    "width": glyph.width,
                    "height": glyph.height,
                    "unknown": f"0x{glyph.unknown:02X}",
                    "atlas": f"font_{font.index:03d}/{atlas_file}",
                    "glyph_file": (
                        f"font_{font.index:03d}/glyphs/{glyph_file}"
                        if glyph_file
                        else ""
                    ),
                }
            )

    _write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(fonts.fonts)} font atlas(es) -> {outdir}")
    return 0


def cmd_sound_export(args: SimpleNamespace) -> int:
    """Export UO sounds to WAV."""
    try:
        client = _client_path(args.client)
        indexed = _load_sounds(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
        )
        defs = _try_load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _entry_iter(indexed, args.range_start, args.range_end)
    outdir = Path(args.output) / "sounds"
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

    _write_manifest(outdir / "manifest.csv", rows)
    print(
        f"Exported {saved} sound(s) from {len(entries)} indexed entrie(s) -> {outdir}"
    )
    if failed:
        print(f"  ({failed} sound entrie(s) failed or decoded empty)")
    return 0


def cmd_animation_export(args: SimpleNamespace) -> int:
    """Export legacy UO animation frames to PNG."""
    try:
        client = _client_path(args.client)
        indexed = _load_animations(client, args.set_name)
        defs = _try_load_defs(client)
        resolver = _animation_resolver(client, defs)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Temporarily disable body-name-based naming for animation exports.
    body_names: UOAnimationBodyNames | None = None

    entries = _entry_iter(indexed, args.range_start, args.range_end)
    mobtypes = load_mobtypes(client / "mobtypes.txt")
    outdir = Path(args.output) / "animations" / args.set_name
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved_entries = 0
    saved_frames = 0
    failed = 0

    for entry in entries:
        if args.limit is not None and saved_entries >= args.limit:
            break
        frames = UOAnimationDecoder.decode(entry)
        if not frames:
            failed += 1
            continue

        slot = legacy_animation_slot(entry.index, args.set_name)
        naming = animation_naming(
            slot,
            set_name=args.set_name,
            mobtypes=mobtypes,
        )
        def_metadata = _animation_def_metadata(
            defs,
            set_name=args.set_name,
            body=slot.body,
        )
        resolution = (
            resolver.resolve(
                body=slot.body,
                action=slot.action,
                direction=slot.direction,
            )
            if args.set_name == "anim"
            else None
        )
        if args.layout == "named":
            body_dir = _animation_body_dir(
                body=slot.body,
                category=naming.category,
                body_names=body_names,
            )
            relative_dir = (
                f"{naming.kind}/{body_dir}/{naming.action_dir}/{naming.direction_dir}"
            )
        elif args.layout == "grouped":
            relative_dir = (
                f"body_{slot.body:04d}"
                f"/action_{slot.action:02d}"
                f"/direction_{slot.direction:02d}"
            )
        else:
            relative_dir = f"{entry.index:05d}"

        entry_dir = outdir / relative_dir
        entry_dir.mkdir(parents=True, exist_ok=True)
        for frame in frames:
            filename = f"frame_{frame.index:03d}.png"
            frame.image.save(entry_dir / filename)
            row: dict[str, object] = {
                "set": args.set_name,
                "raw_entry": entry.index,
                "body": slot.body,
                "action": slot.action,
                "action_name": naming.action_name,
                "direction": slot.direction,
                "direction_name": naming.direction_name,
                "stride": slot.stride,
                "group": slot.group,
                "kind": naming.kind,
                "category": naming.category,
                "category_source": naming.category_source,
                "frame": frame.index,
                "file": f"{relative_dir}/{filename}",
                "width": frame.width,
                "height": frame.height,
                "center_x": frame.center_x,
                "center_y": frame.center_y,
            }
            row.update(
                _animation_body_name_metadata(
                    body_names=body_names,
                    prefix="body",
                    body=slot.body,
                )
            )
            row.update(def_metadata)
            row.update(_animation_resolution_metadata(resolution))
            rows.append(row)
            saved_frames += 1
        saved_entries += 1

    _write_manifest(outdir / "manifest.csv", rows)
    print(
        f"Exported {saved_frames} animation frame(s) from {saved_entries} entrie(s) -> {outdir}"
    )
    if failed:
        print(f"  ({failed} animation entrie(s) failed or decoded empty)")
    return 0


def cmd_animation_resolution_export(args: SimpleNamespace) -> int:
    """Export effective UO animation body/action resolution metadata."""
    try:
        client = _client_path(args.client)
        defs = _try_load_defs(client)
        resolver = _animation_resolver(client, defs)
        mobtypes = load_mobtypes(client / "mobtypes.txt")
        sequence = _try_load_animation_sequence(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Temporarily disable body-name-based naming/metadata for resolution export.
    body_names: UOAnimationBodyNames | None = None

    outdir = Path(args.output) / "animation_resolution"
    outdir.mkdir(parents=True, exist_ok=True)
    start = 0 if args.body_start is None else args.body_start
    end = 2048 if args.body_end is None else args.body_end
    bodies = [body for body in sorted(mobtypes) if start <= body < end]
    if not bodies:
        bodies = list(range(start, end))

    rows: list[dict[str, object]] = []
    saved_bodies = 0
    for body in bodies:
        if args.limit_bodies is not None and saved_bodies >= args.limit_bodies:
            break
        saved_bodies += 1
        for action in range(args.actions):
            for direction in range(args.directions):
                resolution = resolver.resolve(
                    body=body,
                    action=action,
                    direction=direction,
                )
                requested_slot = legacy_animation_slot(
                    animation_entry_index(
                        body=body,
                        action=action,
                        direction=direction,
                        file_type=1,
                    ),
                    "anim",
                )
                requested_naming = animation_naming(
                    requested_slot,
                    set_name="anim",
                    mobtypes=mobtypes,
                )
                resolved_slot = legacy_animation_slot(
                    resolution.raw_entry,
                    resolution.final_set,
                )
                resolved_naming = animation_naming(
                    resolved_slot,
                    set_name=resolution.final_set,
                    mobtypes=mobtypes,
                )
                row: dict[str, object] = {
                    "requested_kind": requested_naming.kind,
                    "requested_category": requested_naming.category,
                    "requested_action_name": requested_naming.action_name,
                    "requested_direction_name": requested_naming.direction_name,
                    "resolved_kind": resolved_naming.kind,
                    "resolved_category": resolved_naming.category,
                    "resolved_action_name": resolved_naming.action_name,
                    "resolved_direction_name": resolved_naming.direction_name,
                    "requested_body_dir": _animation_body_dir(
                        body=body,
                        category=requested_naming.category,
                        body_names=body_names,
                    ),
                    "resolved_body_dir": _animation_body_dir(
                        body=resolution.final_body,
                        category=resolved_naming.category,
                        body_names=body_names,
                    ),
                    "resolved_action_dir": resolved_naming.action_dir,
                    "resolved_direction_dir": resolved_naming.direction_dir,
                }
                row.update(
                    _animation_body_name_metadata(
                        body_names=body_names,
                        prefix="requested",
                        body=body,
                    )
                )
                row.update(
                    _animation_body_name_metadata(
                        body_names=body_names,
                        prefix="resolved",
                        body=resolution.final_body,
                    )
                )
                row.update(_animation_resolution_metadata(resolution))
                rows.append(row)

    sequence_rows: list[dict[str, object]] = []
    if sequence is not None:
        for entry in sorted(sequence.entries.values(), key=lambda item: item.body):
            changed = [
                f"{index}->{value}"
                for index, value in enumerate(entry.replacements)
                if index != value
            ]
            sequence_rows.append(
                {
                    "body": entry.body,
                    "changed_count": len(changed),
                    "changes": "|".join(changed),
                }
            )

    _write_manifest(outdir / "manifest.csv", rows)
    _write_manifest(outdir / "sequence_replacements.csv", sequence_rows)
    print(
        f"Exported {len(rows)} animation resolution row(s), {len(sequence_rows)} sequence row(s) -> {outdir}"
    )
    return 0


def cmd_animation_body_names_export(args: SimpleNamespace) -> int:
    """Export best-effort UO animation body-name clues."""
    _ = args
    print(
        "ERROR: animation body-name export is temporarily disabled while body-name sources are disabled.",
        file=sys.stderr,
    )
    return 1


@uo_app.command("art-export")
def art_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    kind: Annotated[
        Literal["all", "land", "static"],
        typer.Option("--kind", help="Subset to export."),
    ] = "all",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO art land tiles and static/item sprites to PNG."""
    raise SystemExit(cmd_art_export(SimpleNamespace(**locals())))


@uo_app.command("gump-export")
def gump_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO gump images to PNG."""
    raise SystemExit(cmd_gump_export(SimpleNamespace(**locals())))


@uo_app.command("texture-export")
def texture_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO land textures to PNG."""
    raise SystemExit(cmd_texture_export(SimpleNamespace(**locals())))


@uo_app.command("light-export")
def light_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO light masks to PNG."""
    raise SystemExit(cmd_light_export(SimpleNamespace(**locals())))


@uo_app.command("hue-export")
def hue_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum hue ramps to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First zero-based hue index, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last zero-based hue index, exclusive."),
    ] = None,
    swatch_size: Annotated[
        int,
        typer.Option(
            "--swatch-size", help="Pixel size for each of the 32 hue colours."
        ),
    ] = 8,
) -> None:
    """Export UO hue ramps to PNG."""
    raise SystemExit(cmd_hue_export(SimpleNamespace(**locals())))


@uo_app.command("radar-export")
def radar_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    columns: Annotated[
        int,
        typer.Option("--columns", help="Swatch columns."),
    ] = 256,
    swatch_size: Annotated[
        int,
        typer.Option("--swatch-size", help="Pixel size for each color entry."),
    ] = 4,
) -> None:
    """Export the UO radar/minimap color lookup table."""
    raise SystemExit(cmd_radar_export(SimpleNamespace(**locals())))


@uo_app.command("tiledata-export")
def tiledata_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
) -> None:
    """Export UO tile metadata to CSV."""
    raise SystemExit(cmd_tiledata_export(SimpleNamespace(**locals())))


@uo_app.command("animdata-export")
def animdata_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
) -> None:
    """Export UO static-art animation metadata to CSV."""
    raise SystemExit(cmd_animdata_export(SimpleNamespace(**locals())))


@uo_app.command("artdef-export")
def artdef_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
) -> None:
    """Export UO art.def redirect metadata to CSV."""
    raise SystemExit(cmd_artdef_export(SimpleNamespace(**locals())))


@uo_app.command("def-export")
def def_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
) -> None:
    """Export all UO .def metadata to CSV."""
    raise SystemExit(cmd_def_export(SimpleNamespace(**locals())))


@uo_app.command("localization-export")
def localization_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    language: Annotated[
        str,
        typer.Option("--language", help="Language code such as enu, or all."),
    ] = "all",
) -> None:
    """Export UO localization and name metadata to CSV."""
    raise SystemExit(cmd_localization_export(SimpleNamespace(**locals())))


@uo_app.command("multi-export")
def multi_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum multis to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First multi ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last multi ID, exclusive."),
    ] = None,
    mul_only: Annotated[
        bool,
        typer.Option(
            "--mul-only", help="Ignore MultiCollection.uop and read multi.mul."
        ),
    ] = False,
) -> None:
    """Export UO multi component metadata to CSV."""
    raise SystemExit(cmd_multi_export(SimpleNamespace(**locals())))


@uo_app.command("font-export")
def font_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    limit_fonts: Annotated[
        int,
        typer.Option("--limit-fonts", help="Maximum fonts to parse/export."),
    ] = 10,
    columns: Annotated[
        int,
        typer.Option("--columns", help="Atlas columns."),
    ] = 16,
    glyphs: Annotated[
        bool,
        typer.Option("--glyphs", help="Also export individual glyph PNGs."),
    ] = False,
) -> None:
    """Export UO ASCII font atlases and glyph metadata."""
    raise SystemExit(cmd_font_export(SimpleNamespace(**locals())))


@uo_app.command("sound-export")
def sound_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
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


@uo_app.command("animation-export")
def animation_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    set_name: Annotated[
        Literal["anim", "anim2", "anim3", "anim4", "anim5", "anim6"],
        typer.Option("--set", help="Legacy animation file set."),
    ] = "anim",
    layout: Annotated[
        Literal["named", "grouped", "raw"],
        typer.Option("--layout", help="Output folder layout."),
    ] = "named",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum decoded animation entries to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First animation entry, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last animation entry, exclusive."),
    ] = None,
) -> None:
    """Export legacy UO animation frames to PNG."""
    raise SystemExit(cmd_animation_export(SimpleNamespace(**locals())))


@uo_app.command("animation-resolution-export")
def animation_resolution_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
    body_start: Annotated[
        Optional[int],
        typer.Option("--body-start", help="First requested body ID, inclusive."),
    ] = None,
    body_end: Annotated[
        Optional[int],
        typer.Option("--body-end", help="Last requested body ID, exclusive."),
    ] = None,
    limit_bodies: Annotated[
        Optional[int],
        typer.Option("--limit-bodies", help="Maximum requested bodies to export."),
    ] = None,
    actions: Annotated[
        int,
        typer.Option("--actions", help="Number of requested actions per body."),
    ] = 68,
    directions: Annotated[
        int,
        typer.Option("--directions", help="Number of requested directions per action."),
    ] = 5,
) -> None:
    """Export effective UO animation body/action resolution metadata."""
    raise SystemExit(cmd_animation_resolution_export(SimpleNamespace(**locals())))


@uo_app.command("animation-body-names-export")
def animation_body_names_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Ultima Online Classic Client install directory; optional if [uo.game] base is configured."
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output directory."),
    ] = "uodata",
) -> None:
    """Export best-effort UO animation body-name clues."""
    raise SystemExit(cmd_animation_body_names_export(SimpleNamespace(**locals())))
