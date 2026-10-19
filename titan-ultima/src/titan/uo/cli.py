"""Ultima Online Classic Client CLI sub-app."""

from __future__ import annotations

__all__ = ["uo_app"]

import csv
from dataclasses import dataclass
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import numpy as np
import typer
from PIL import Image

from titan._config import get_config
from titan.uo.housing import footprint_sheet, house_footprint, parse_house_placement_tool
from titan.uo.installs import resolve_install
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
from titan.uo.map import FACET_DIMENSIONS, UOMap
from titan.uo.multi import UOMultis
from titan.uo.radar import UORadarColors
from titan.uo.render import UOMapRenderer
from titan.uo.tiles import FACET_NAMES, FacetTileJob, build_facet_tiles
from titan.uo.capacity_viewer import write_capacity_viewer
from titan.uo.server_profile import ServerProfile, builtin_house_entries
from titan.uo.mixed_packing import CLASSES, HouseKind, MixedSettings, class_for, pack_mixed, zone_distances
from titan.uo.placement import (
    coverage,
    _parse_region_rects,
    build_placement_grids,
    evaluate_placement,
    legal_centres,
    no_housing_region_types,
    region_layers_from_rects,
    region_outlines_from_rects,
    pack_houses,
)
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
    """Resolve CLIENT (a directory or a [uo.installs.*] name) to a directory."""
    return resolve_install(client)[0]


def _out(args: SimpleNamespace) -> Path:
    """Output root: ``-o`` if given, else the install's output, else ``uodata``."""
    if getattr(args, "output", None):
        return Path(args.output)
    try:
        install = resolve_install(getattr(args, "client", None))[1]
    except FileNotFoundError:
        install = None
    if install is not None and install.output is not None:
        return install.output
    return Path("uodata")


def _source(args: SimpleNamespace, key: str) -> str:
    """Source container from ``--container``, else the install's ``maps``/``multis``."""
    if getattr(args, "container", None):
        return args.container
    try:
        install = resolve_install(getattr(args, "client", None))[1]
    except FileNotFoundError:
        install = None
    return getattr(install, key) if install is not None else "auto"


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


def _try_load_cliloc(client: Path, language: str) -> UOCliloc | None:
    try:
        return _load_cliloc(client, language)
    except FileNotFoundError:
        return None


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

    outdir = _out(args)
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
    outdir = _out(args)
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
    outdir = _out(args)
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
    outdir = _out(args)
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

    outdir = _out(args) / "hues"
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

    outdir = _out(args) / "radar"
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


def cmd_map_export(args: SimpleNamespace) -> int:
    """Render UO facets as one-pixel-per-tile radar images."""
    try:
        client = _client_path(args.client)
        radar = _load_radar(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    facets = args.facet or [
        facet
        for facet in sorted(FACET_DIMENSIONS)
        if (client / f"staidx{facet}{args.suffix}.mul").is_file()
    ]
    if not facets:
        print("ERROR: no staidxN.mul files found", file=sys.stderr)
        return 1

    outdir = _out(args) / "maps"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for facet in facets:
        try:
            facet_map = UOMap.from_client(
                client,
                facet,
                container=_source(args, "maps"),
                suffix=args.suffix,
                patches=args.patches,
            )
        except Exception as exc:
            print(f"ERROR: facet {facet}: {exc}", file=sys.stderr)
            return 1

        stem = f"map{facet}{args.suffix}"
        facet_map.render_radar(radar, statics=not args.no_statics).save(
            outdir / f"{stem}.png"
        )
        if args.heightmap:
            facet_map.render_heightmap().save(outdir / f"{stem}_height.png")

        source = facet_map.source
        summary = facet_map.static_index_summary()
        rows.append(
            {
                "facet": facet,
                "image": f"{stem}.png",
                "width": facet_map.width,
                "height": facet_map.height,
                "land_container": source.land_container if source else "",
                "land_file": Path(source.land_path).name if source else "",
                "trailing_land_blocks": source.trailing_land_blocks if source else 0,
                "land_patch_blocks": source.land_patch_blocks if source else 0,
                "static_patch_blocks": source.static_patch_blocks if source else 0,
                **summary,
            }
        )
        print(
            f"facet {facet}: {facet_map.width}x{facet_map.height}, "
            f"{summary['static_count']} static(s) -> {outdir / f'{stem}.png'}"
        )

    _write_manifest(outdir / "summary.csv", rows)
    print(f"Exported {len(rows)} facet map(s) -> {outdir}")
    return 0


def _parse_int_list(value: str, count: tuple[int, ...], label: str) -> list[int]:
    parts = [part for part in re.split(r"[,x\s]+", value.strip()) if part]
    if len(parts) not in count:
        raise ValueError(f"{label} needs {' or '.join(map(str, count))} numbers: {value!r}")
    return [int(part) for part in parts]


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render an isometric view of a UO facet like the client."""
    try:
        client = _client_path(args.client)
        center = _parse_int_list(args.center, (2, 3), "--center")
        width, height = _parse_int_list(args.size, (2,), "--size")
        facet_map = UOMap.from_client(
            client,
            args.facet,
            container=_source(args, "maps"),
            suffix=args.suffix,
            patches=args.patches,
        )
        renderer = UOMapRenderer.from_client(client, facet_map, hues=not args.no_hues)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    image = renderer.render(
        center[0],
        center[1],
        width,
        height,
        center_z=center[2] if len(center) == 3 else None,
        statics=not args.no_statics,
        roofs=not args.no_roofs,
        shading=not args.no_shading,
    )
    outdir = _out(args) / "maps" / "render"
    outdir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"map{args.facet}{args.suffix}_{center[0]}_{center[1]}"
    path = outdir / f"{name}.png"
    image.save(path)
    print(f"Rendered facet {args.facet} at {center[0]},{center[1]} ({width}x{height}) -> {path}")
    return 0


def cmd_map_inventory(args: SimpleNamespace) -> int:
    """Count every land and static tile a facet uses, ranked by placements."""
    from titan.uo.map_inventory import build_uo_map_inventory, write_uo_map_inventory
    from titan.uo.render import UOArtSource

    try:
        client = _client_path(args.client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    facets = args.facet or [
        facet
        for facet in sorted(FACET_DIMENSIONS)
        if (client / f"staidx{facet}{args.suffix}.mul").is_file()
    ]
    if not facets:
        print("ERROR: no staidxN.mul files found", file=sys.stderr)
        return 1
    try:
        tiledata = _load_tiledata(client)
        art = None if args.no_previews else UOArtSource.from_client(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    root = _out(args) if args.output else _out(args) / "map-inventory"
    for facet in facets:
        try:
            inventory = build_uo_map_inventory(
                client,
                facet,
                container=_source(args, "maps"),
                suffix=args.suffix,
                patches=args.patches,
                tiledata=tiledata,
            )
            outdir = root / f"map{facet}{args.suffix}"
            summary = write_uo_map_inventory(
                inventory, outdir, previews=not args.no_previews, art=art
            )
        except Exception as exc:
            print(f"ERROR: facet {facet}: {exc}", file=sys.stderr)
            return 1
        statics, land = summary["statics"], summary["land"]
        coverage = statics["coverage_by_top_names_pct"]
        print(
            f"facet {facet}: {statics['placements']:,} statics over {statics['tile_ids']:,} tile IDs "
            f"and {statics['names']:,} names (top 100 names {coverage['top_100']}%); "
            f"{land['cells']:,} land cells over {land['tile_ids']:,} land IDs -> {outdir}"
        )
    return 0


def cmd_map_tiles(args: SimpleNamespace) -> int:
    """Render a whole facet as a zoomable tile pyramid with an offline viewer."""
    try:
        client = _client_path(args.client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = _out(args) / "maps" / "tiles" / f"map{args.facet}{args.suffix}"
    job = FacetTileJob(
        client=str(client),
        facet=args.facet,
        output=str(output),
        tile_size=args.tile_size,
        quality=args.quality,
        container=_source(args, "maps"),
        suffix=args.suffix,
        patches=args.patches,
        statics=not args.no_statics,
        roofs=not args.no_roofs,
        shading=not args.no_shading,
        hues=not args.no_hues,
    )
    workers = args.workers or max(1, min(16, (os.cpu_count() or 2) - 2))
    try:
        build_facet_tiles(job, workers=workers)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def _reference(args: SimpleNamespace) -> dict[str, str]:
    """[uo.reference] settings, overridden by the install's own references."""
    merged = dict(get_config().get("uo", {}).get("reference", {}))
    try:
        install = resolve_install(getattr(args, "client", None))[1]
    except FileNotFoundError:
        install = None
    if install is not None and install.reference:
        merged.update(install.reference)
    return merged


_REGION_FACETS = {0: "Felucca", 1: "Trammel", 2: "Ilshenar", 3: "Malas", 4: "Tokuno", 5: "TerMur"}


@dataclass
class _ServerData:
    """Where house menu and region rules come from for one command run."""

    entries: list
    entries_source: str
    region_rects: list | None
    regions_source: str
    identity: str


def _server_data(args: SimpleNamespace, multis, tiledata, facet_number: int) -> _ServerData:
    """Resolve the house menu and region rules.

    Precedence: explicit ``--placement-source``/``--regions`` flags, then a
    server profile (``--server-profile``, the install's ``server_profile`` or
    ``[uo.reference] server_profile``), then the older ``[uo.reference]``
    file settings, then Titan's built-in house list with no regions.
    """
    reference = _reference(args)
    profile_path = getattr(args, "server_profile", None) or reference.get("server_profile")
    profile = ServerProfile.load(profile_path) if profile_path else None
    facet_name = _REGION_FACETS.get(facet_number, str(facet_number))

    placement = getattr(args, "placement_source", None)
    if placement:
        entries, entries_source = parse_house_placement_tool(placement), str(placement)
    elif profile is not None:
        entries, entries_source = profile.houses, f"server profile {profile.path}"
    elif reference.get("house_placement_tool"):
        placement = reference["house_placement_tool"]
        entries, entries_source = parse_house_placement_tool(placement), str(placement)
    else:
        entries = builtin_house_entries(multis, tiledata)
        entries_source = "built-in house list (no server data)"

    regions_xml = getattr(args, "regions", None)
    scripts = getattr(args, "region_scripts", None)
    if regions_xml:
        forbidding = no_housing_region_types(scripts) if scripts else None
        rects, _ = _parse_region_rects(regions_xml, facet_name, forbidding)
        regions_source = f"{regions_xml} (rules: {scripts or 'built-in RunUO list'})"
        identity = f"{_file_identity(regions_xml)}|{sorted(forbidding) if forbidding else 'runuo'}"
    elif profile is not None:
        rects = profile.region_rects(facet_name)
        regions_source = f"server profile {profile.path}"
        identity = _file_identity(profile.path)
    elif reference.get("regions_xml"):
        regions_xml = reference["regions_xml"]
        scripts = reference.get("emulator_scripts")
        forbidding = no_housing_region_types(scripts) if scripts else None
        rects, _ = _parse_region_rects(regions_xml, facet_name, forbidding)
        regions_source = f"{regions_xml} (rules: {scripts or 'built-in RunUO list'})"
        identity = f"{_file_identity(regions_xml)}|{sorted(forbidding) if forbidding else 'runuo'}"
    else:
        rects, regions_source, identity = None, "none", "no-regions"
    if rects is None and regions_source != "none":
        regions_source += f" (no {facet_name} section)"
    return _ServerData(entries, entries_source, rects, regions_source, identity)


def cmd_house_footprints(args: SimpleNamespace) -> int:
    """Export house placement footprints: emulator house table joined to client multis."""
    try:
        client = _client_path(args.client)
        multis = UOMultis.from_client(client, container=_source(args, "multis"))
        tiledata = _load_tiledata(client)
        cliloc = _try_load_cliloc(client, "enu")
        server = _server_data(args, multis, tiledata, 0)
        entries, source = server.entries, server.entries_source
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _out(args) / "housing"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    cells: dict[str, dict[str, object]] = {}
    missing = 0
    sheet_items = []
    for entry in entries:
        multi = multis.multis.get(entry.multi_id)
        footprint = house_footprint(multi, tiledata) if multi is not None else None
        name = cliloc.entries[entry.cliloc].text if cliloc and entry.cliloc in cliloc.entries else ""
        row: dict[str, object] = {
            "category": entry.category,
            "type": entry.type_name,
            "cliloc": entry.cliloc,
            "name": name,
            "multi_id": f"0x{entry.multi_id:04X}",
            "in_client": footprint is not None,
            "cost": entry.cost,
            "storage": entry.storage,
            "lockdowns": entry.lockdowns,
            "vendors": entry.vendors,
            "offset_x": entry.offset[0],
            "offset_y": entry.offset[1],
            "offset_z": entry.offset[2],
        }
        if footprint is None:
            missing += 1
        else:
            for label, part in (
                ("occupied", footprint.occupied),
                ("foundation", footprint.foundation),
                ("border", footprint.border),
                ("yard", footprint.yard),
            ):
                min_x, max_x, min_y, max_y = footprint.extent(part)
                row[f"{label}_cells"] = len(part)
                row[f"{label}_min_x"], row[f"{label}_max_x"] = min_x, max_x
                row[f"{label}_min_y"], row[f"{label}_max_y"] = min_y, max_y
            min_x, max_x, min_y, max_y = footprint.extent(footprint.occupied)
            row["width"], row["height"] = max_x - min_x + 1, max_y - min_y + 1
            row["stairs_added"] = footprint.stairs_added
            sheet_items.append((entry, name, footprint))
            cells[row["multi_id"]] = {
                key: sorted(getattr(footprint, key))
                for key in ("occupied", "foundation", "border", "yard")
            }
        rows.append(row)

    _write_manifest(outdir / "house_footprints.csv", rows)
    if sheet_items:
        install = resolve_install(args.client)[1]
        label = install.label or install.name if install else str(client)
        footprint_sheet(
            sheet_items,
            scale=args.scale,
            title=f"House footprints: {label} ({multis.source}), {Path(str(source)).name}",
        ).save(outdir / "house_footprints.png")
    meta = {
        "placement_source": str(source),
        "client": str(client),
        "multis": {"source": multis.source, "layout": multis.layout},
        "entries": len(entries),
        "missing_in_client": missing,
        "coordinates": "cells relative to the house centre; centre = cursor - offset",
        "footprints": cells,
    }
    (outdir / "house_footprints.json").write_text(json.dumps(meta), encoding="utf-8")
    print(
        f"Exported {len(rows)} house footprint(s) ({missing} not in the client's "
        f"{multis.source}) -> {outdir}"
    )
    return 0


_WORKSHOP_IDS = frozenset((0x00A0, 0x00A2))  # small stone / marble workshop: the "forges"


def _mixed_house_kinds(entries, multis, tiledata, cliloc, settings):
    """Classic houses plus one square customizable plot per size, classified."""
    kinds = []
    plot_sizes = set()
    for entry in entries:
        multi = multis.multis.get(entry.multi_id)
        if multi is None:
            continue
        label = (
            cliloc.entries[entry.cliloc].text
            if cliloc and entry.cliloc in cliloc.entries
            else entry.type_name
        )
        if entry.category == "ClassicHouses":
            pass
        elif entry.category.endswith("Foundations"):
            size = re.match(r"(\d+)x(\d+)", label)
            if not size or size.group(1) != size.group(2) or size.group(1) in plot_sizes:
                continue
            plot_sizes.add(size.group(1))
        else:
            continue
        footprint = house_footprint(multi, tiledata)
        kinds.append(
            HouseKind(
                entry.multi_id,
                label,
                class_for(len(footprint.occupied), settings, entry.multi_id in _WORKSHOP_IDS),
                footprint,
            )
        )
    return kinds


def _file_identity(path) -> str:
    stat = Path(path).stat()
    return f"{Path(path).resolve()}|{stat.st_size}|{stat.st_mtime_ns}"


def _legal_cache_key(base_key: str, multi) -> str:
    components = sorted((c.item_id, c.x, c.y, c.z, c.flags) for c in multi.components)
    return hashlib.sha1(f"{base_key}|{multi.multi_id}|{components}".encode()).hexdigest()[:20]


def _run_mixed_packing(
    *, grids, kinds, multis, tiledata, window, outlines, land_ids, settings, outdir, cache_key
):
    """Legal centres per kind (cached on disk), zone distances, and the mixed packing.

    ``cache_key`` identifies everything legality depends on besides the house
    itself: map files, tiledata, window, regions and region rules. Cached
    legal centres live in ``outdir/cache`` and are reused only on an exact
    key match.
    """
    x0, y0, x1, y1 = window
    cache_dir = outdir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    centres = []
    for kind in kinds:
        multi = multis.multis[kind.multi_id]
        path = cache_dir / f"legal_{kind.multi_id:04X}_{_legal_cache_key(cache_key, multi)}.npz"
        if path.is_file():
            with np.load(path) as cached:
                rows, cols = cached["rows"].astype(np.int64), cached["cols"].astype(np.int64)
            print(f"  mixed: legal centres for 0x{kind.multi_id:04X} {kind.label} (cached)")
        else:
            print(f"  mixed: legal centres for 0x{kind.multi_id:04X} {kind.label} ({kind.house_class})...")
            rows, cols = legal_centres(grids, multi, tiledata)
            np.savez_compressed(path, rows=rows.astype(np.int32), cols=cols.astype(np.int32))
        centres.append((rows, cols))

    town = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    for region in outlines or []:
        if "Town" not in str(region["type"]) and region["type"] != "NewMaginciaRegion":
            continue
        rx0, ry0 = max(region["x"] - x0, 0), max(region["y"] - y0, 0)
        rx1 = min(region["x"] + region["w"] - x0, x1 - x0)
        ry1 = min(region["y"] + region["h"] - y0, y1 - y0)
        if rx0 < rx1 and ry0 < ry1:
            town[ry0:ry1, rx0:rx1] = True
    rock_ids = np.array([t.name.lower() == "rock" for t in tiledata.land[:0x4000]])
    rock = rock_ids[land_ids[y0:y1, x0:x1] & 0x3FFF]
    town_distance, rock_distance = zone_distances(town.shape, town, rock, settings)
    packing = pack_mixed(window, kinds, centres, town_distance, rock_distance, settings)

    _write_manifest(
        outdir / "mixed_packed.csv",
        [
            {
                "x": x,
                "y": y,
                "multi_id": f"0x{kinds[k].multi_id:04X}",
                "class": kinds[k].house_class,
                "name": kinds[k].label,
            }
            for x, y, k in packing.placed
        ],
    )
    per_kind: dict[str, int] = {}
    for _x, _y, k in packing.placed:
        per_kind[kinds[k].label] = per_kind.get(kinds[k].label, 0) + 1
    summary = {
        "houses_placed": len(packing.placed),
        "by_class": packing.counts,
        "by_house": dict(sorted(per_kind.items(), key=lambda item: -item[1])),
        "zones_by_class": {
            name: int((packing.zone_classes == index).sum())
            for index, name in enumerate(CLASSES)
        },
        "kinds": [
            {
                "multi_id": f"0x{k.multi_id:04X}",
                "name": k.label,
                "class": k.house_class,
                "tiles": k.tiles,
                "legal_centres": int(len(c[0])),
            }
            for k, c in zip(kinds, centres)
        ],
        "settings": {
            key: getattr(settings, key)
            for key in settings.__dataclass_fields__
        },
    }
    return packing, summary


def cmd_house_capacity(args: SimpleNamespace) -> int:
    """Simulate legal house placement over a facet and pack houses greedily."""
    try:
        client = _client_path(args.client)
        tiledata = _load_tiledata(client)
        multis = UOMultis.from_client(client, container=_source(args, "multis"))
        facet = UOMap.from_client(
            client, args.facet, container=_source(args, "maps"), mapped=True
        )
        server = _server_data(args, multis, tiledata, args.facet)
        entries = server.entries
        names = {e.multi_id: e for e in entries}
        if args.multi:
            multi_ids = [int(value, 0) for value in args.multi]
        else:
            sized = [
                (len(house_footprint(multis.multis[e.multi_id], tiledata).occupied), e.multi_id)
                for e in entries
                if e.multi_id in multis.multis
            ]
            multi_ids = [min(sized)[1]]
        missing = [f"0x{m:X}" for m in multi_ids if m not in multis.multis]
        if missing:
            raise ValueError(f"multi(s) not in {multis.source}: {', '.join(missing)}")
        layers = None
        blocked = None
        region_counts: dict[str, int] = {}
        if server.region_rects is not None:
            layers = region_layers_from_rects(server.region_rects, facet.width, facet.height)
            ground = next(l for l in layers if l.z_min <= 0 < l.z_max)
            blocked = ground.blocked
            seen = set()
            for key, allow, _nh, *_rest, rtype in server.region_rects:
                if not allow and key not in seen:
                    seen.add(key)
                    region_counts[rtype] = region_counts.get(rtype, 0) + 1
        else:
            print(
                "WARNING: no region rules for this facet; towns, dungeons and no-housing "
                "areas are not excluded. Pass --server-profile to include them.",
                file=sys.stderr,
            )
        window = _parse_int_list(args.window, (4,), "--window") if args.window else [
            0, 0, min(facet.width, 5120) if args.facet in (0, 1) else facet.width, facet.height
        ]
        cliloc = _try_load_cliloc(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _out(args) / "housing" / "capacity" / f"map{args.facet}"
    outdir.mkdir(parents=True, exist_ok=True)
    radar = _load_radar(client)
    base = None
    radar_rgb = None
    viewer_houses: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "client": str(client),
        "facet": args.facet,
        "window": window,
        "regions": server.regions_source,
        "region_types_forbidding": region_counts,
        "placement_source": server.entries_source,
        "t2a_excluded": args.facet == 0,
        "houses": [],
    }
    x0, y0, x1, y1 = window
    land_ids, _land_z = facet.land_arrays()
    print(f"Preparing placement grids for {(x1 - x0) * (y1 - y0):,} centres...")
    grids = build_placement_grids(
        facet, tiledata, region_layers=layers, t2a=args.facet == 0, window=tuple(window)
    )
    impassable = np.array([bool(t.flags & 0x40) for t in tiledata.land[:0x4000]])
    passable_land = int((~impassable[land_ids[y0:y1, x0:x1] & 0x3FFF]).sum())
    summary["passable_land_cells"] = passable_land

    for multi_id in multi_ids:
        entry = names.get(multi_id)
        label = (
            cliloc.entries[entry.cliloc].text
            if entry and cliloc and entry.cliloc in cliloc.entries
            else f"multi 0x{multi_id:X}"
        )
        print(f"0x{multi_id:04X} {label}: checking {(x1 - x0) * (y1 - y0):,} centres...")
        result = evaluate_placement(grids, multis.multis[multi_id], tiledata)
        covered = coverage(result)
        packings = {order: pack_houses(result, order=order) for order in ("row", "column")}
        best_order = max(packings, key=lambda order: len(packings[order]))
        placed = packings[best_order]
        fp = result.footprint
        fx0, fx1, fy0, fy1 = fp.extent(fp.occupied)
        house = {
            "multi_id": f"0x{multi_id:04X}",
            "name": label,
            "footprint": f"{fx1 - fx0 + 1}x{fy1 - fy0 + 1}",
            "occupied_cells": len(fp.occupied),
            "legal_centres": result.legal_count,
            "covered_cells": int(covered.sum()),
            "covered_share_of_passable_land": round(int(covered.sum()) / passable_land, 4)
            if passable_land else None,
            "rejected_centres_by_first_rule": result.reasons,
            "packed_houses": len(placed),
            "packed_by_order": {order: len(p) for order, p in packings.items()},
            "packed_tiles": len(placed) * len(fp.occupied),
        }
        summary["houses"].append(house)
        viewer_houses.append(
            {"label": label, "result": result, "coverage": covered, "placed": placed}
        )
        stem = f"0x{multi_id:04X}"
        _write_manifest(
            outdir / f"{stem}_packed.csv",
            [{"x": x, "y": y, "z": None} for x, y in placed],
        )
        if base is None:
            radar_rgb = np.asarray(facet.render_radar(radar))[y0:y1, x0:x1]
            base = radar_rgb.astype(np.float32)
            if blocked is not None:
                base[blocked[y0:y1, x0:x1]] *= 0.55
        overlay = base.copy()
        overlay[covered] = overlay[covered] * 0.4 + np.array([60, 200, 90]) * 0.6
        houses = np.zeros_like(covered)
        for x, y in placed:
            for dx, dy in fp.occupied:
                X, Y = x - x0 + dx, y - y0 + dy
                if 0 <= X < houses.shape[1] and 0 <= Y < houses.shape[0]:
                    houses[Y, X] = True
        overlay[houses] = (240, 200, 60)
        Image.fromarray(overlay.clip(0, 255).astype(np.uint8)).save(outdir / f"{stem}_overlay.png")
        print(
            f"  legal centres {result.legal_count:,}; covered cells {house['covered_cells']:,} "
            f"({house['covered_share_of_passable_land']:.1%} of passable land); "
            f"packed {len(placed):,} houses ({best_order} order)"
        )

    outlines = (
        region_outlines_from_rects(server.region_rects)
        if server.region_rects is not None
        else None
    )
    viewer_packings = []
    if not args.no_mixed:
        if not entries or not outlines:
            print("Mixed packing skipped: it needs region rules (towns) to place house sizes.")
        else:
            settings = MixedSettings(seed=args.seed)
            kinds = _mixed_house_kinds(entries, multis, tiledata, cliloc, settings)
            print(f"Mixed packing over {len(kinds)} house kinds...")
            cache_key = "|".join(
                [
                    _file_identity(facet.source.land_path),
                    _file_identity(facet.source.staidx_path),
                    _file_identity(facet.source.statics_path),
                    _file_identity(client / "tiledata.mul"),
                    server.identity,
                    str(tuple(window)),
                    str(args.facet == 0),
                ]
            )
            packing, mixed_summary = _run_mixed_packing(
                cache_key=cache_key,
                grids=grids,
                kinds=kinds,
                multis=multis,
                tiledata=tiledata,
                window=window,
                outlines=outlines,
                land_ids=land_ids,
                settings=settings,
                outdir=outdir,
            )
            summary["mixed"] = mixed_summary
            print(
                f"  mixed: {len(packing.placed):,} houses "
                + ", ".join(f"{c} {n:,}" for c, n in sorted(packing.counts.items()))
            )
            viewer_packings.append(
                {
                    "label": "Mixed: towns small, outskirts large, workshops by mountains",
                    "kinds": [
                        {
                            "label": k.label,
                            "multi": f"0x{k.multi_id:04X}",
                            "class": k.house_class,
                            "footprint": k.footprint,
                        }
                        for k in kinds
                    ],
                    "placed": packing.placed,
                }
            )

    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not args.no_viewer and viewer_houses:
        install = resolve_install(args.client)[1]
        page = write_capacity_viewer(
            outdir / "viewer",
            title=f"House capacity: {FACET_NAMES.get(args.facet, args.facet)}, "
            f"{install.label or install.name if install else client.name}",
            window=tuple(window),
            base_rgb=radar_rgb,
            houses=viewer_houses,
            regions=outlines,
            packings=viewer_packings,
            notes=[
                "Empty world: existing houses, placed items and regions created at "
                "runtime are not included.",
                "Regions are shown as they apply at z 0.",
                "Packing is greedy, so the house count is a lower bound.",
                "Mixed packing is one seeded scenario: house sizes are drawn per "
                "32-tile zone by distance from towns and mountain rock.",
            ],
        )
        print(f"Viewer: {page}")
    print(f"Wrote {outdir}")
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

    outdir = _out(args) / "tiledata"
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

    outdir = _out(args) / "animdata"
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

    outdir = _out(args) / "artdef"
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

    outdir = _out(args) / "defs"
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

    outdir = _out(args) / "localization"
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
            container="mul" if args.mul_only else _source(args, "multis"),
        )
        tiledata = _try_load_tiledata(client)
        animdata = _try_load_animdata(client)
        tilehelp = _try_load_tilehelp(client, "enu")
        cliloc = _load_cliloc(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _out(args) / "multis"
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
        f"Exported {len(summary_rows)} multi(s), {len(component_rows)} component row(s) "
        f"from {multis.source} ({multis.layout}) -> {outdir}"
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

    outdir = _out(args) / "fonts"
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
    outdir = _out(args) / "sounds"
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
    outdir = _out(args) / "animations" / args.set_name
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

    outdir = _out(args) / "animation_resolution"
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


@uo_app.command("map-export")
def map_export_cmd(
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
    facet: Annotated[
        Optional[list[int]],
        typer.Option(
            "--facet",
            "-f",
            help="Facet number to export; repeat for several. Default: every facet with a staidxN.mul.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_statics: Annotated[
        bool,
        typer.Option("--no-statics", help="Render terrain only."),
    ] = False,
    heightmap: Annotated[
        bool,
        typer.Option("--heightmap", help="Also write a greyscale land-altitude PNG."),
    ] = False,
) -> None:
    """Render UO facets as one-pixel-per-tile radar map PNGs."""
    raise SystemExit(cmd_map_export(SimpleNamespace(**locals())))


@uo_app.command("map-render")
def map_render_cmd(
    center: Annotated[
        str,
        typer.Option(
            "--center",
            "-c",
            help="Centre cell as X,Y or X,Y,Z (Z defaults to the land altitude there).",
        ),
    ],
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
    facet: Annotated[
        int,
        typer.Option("--facet", "-f", help="Facet number."),
    ] = 0,
    size: Annotated[
        str,
        typer.Option("--size", help="Image size in pixels, WIDTHxHEIGHT."),
    ] = "1600x1200",
    name: Annotated[
        Optional[str],
        typer.Option("--name", help="Output file stem. Default: mapN_X_Y."),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_statics: Annotated[
        bool,
        typer.Option("--no-statics", help="Render terrain only."),
    ] = False,
    no_roofs: Annotated[
        bool,
        typer.Option("--no-roofs", help="Hide statics flagged as roofs."),
    ] = False,
    no_shading: Annotated[
        bool,
        typer.Option("--no-shading", help="Draw sloped land without normal lighting."),
    ] = False,
    no_hues: Annotated[
        bool,
        typer.Option("--no-hues", help="Ignore static hues."),
    ] = False,
) -> None:
    """Render an isometric view of a UO facet, drawn like the client."""
    raise SystemExit(cmd_map_render(SimpleNamespace(**locals())))


@uo_app.command("map-tiles")
def map_tiles_cmd(
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
    facet: Annotated[
        int,
        typer.Option("--facet", "-f", help="Facet number."),
    ] = 0,
    workers: Annotated[
        int,
        typer.Option("--workers", "-j", help="Worker processes. Default: CPU count - 2, at most 16."),
    ] = 0,
    tile_size: Annotated[
        int,
        typer.Option("--tile-size", help="Tile edge in pixels."),
    ] = 512,
    quality: Annotated[
        int,
        typer.Option("--quality", help="JPEG quality for tiles."),
    ] = 85,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_statics: Annotated[
        bool,
        typer.Option("--no-statics", help="Render terrain only."),
    ] = False,
    no_roofs: Annotated[
        bool,
        typer.Option("--no-roofs", help="Hide statics flagged as roofs."),
    ] = False,
    no_shading: Annotated[
        bool,
        typer.Option("--no-shading", help="Draw sloped land without normal lighting."),
    ] = False,
    no_hues: Annotated[
        bool,
        typer.Option("--no-hues", help="Ignore static hues."),
    ] = False,
) -> None:
    """Render a whole UO facet as a zoomable tile pyramid with an offline viewer."""
    raise SystemExit(cmd_map_tiles(SimpleNamespace(**locals())))


@uo_app.command("map-inventory")
def map_inventory_cmd(
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
            help="Output directory; each facet goes in mapN/ inside it. Default: <install output>/map-inventory.",
        ),
    ] = None,
    facet: Annotated[
        Optional[list[int]],
        typer.Option(
            "--facet",
            "-f",
            help="Facet number to inventory; repeat for several. Default: every facet with a staidxN.mul.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_previews: Annotated[
        bool,
        typer.Option("--no-previews", help="Skip art PNGs and index.html."),
    ] = False,
) -> None:
    """Inventory every land and static tile a facet uses, ranked by placements.

    Writes statics.csv and land.csv (one row per tile ID, with tiledata
    name, category, flags, height, altitude range, block spread and a
    sample cell), names.csv (statics rolled up by tiledata name),
    summary.json and, unless --no-previews, art PNGs with a filterable
    index.html.
    """
    raise SystemExit(cmd_map_inventory(SimpleNamespace(**locals())))


@uo_app.command("house-footprints")
def house_footprints_cmd(
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
    server_profile: Annotated[
        Optional[str],
        typer.Option(
            "--server-profile",
            help="Server profile JSON (regions, region rules, house menu). Default: the install's or [uo.reference] server_profile.",
        ),
    ] = None,
    placement_source: Annotated[
        Optional[str],
        typer.Option(
            "--placement-source",
            help="RunUO/ServUO HousePlacementTool.cs listing the houses a server offers. Default: [uo.reference] house_placement_tool.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Multi source: auto, uop or mul. Default: the install's multis setting, else auto.",
        ),
    ] = None,
    scale: Annotated[
        int,
        typer.Option("--scale", help="Pixels per tile in house_footprints.png."),
    ] = 6,
) -> None:
    """Export house placement footprints (cells as CSV/JSON plus a contact sheet PNG)."""
    raise SystemExit(cmd_house_footprints(SimpleNamespace(**locals())))


@uo_app.command("house-capacity")
def house_capacity_cmd(
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
    facet: Annotated[
        int,
        typer.Option("--facet", "-f", help="Facet number."),
    ] = 0,
    multi: Annotated[
        Optional[list[str]],
        typer.Option(
            "--multi",
            help="House multi ID (e.g. 0x13EC); repeat for several. Default: the smallest house in the placement table.",
        ),
    ] = None,
    window: Annotated[
        Optional[str],
        typer.Option(
            "--window",
            help="Centre window X0,Y0,X1,Y1. Default: Britannia proper (x < 5120) on facets 0/1, else the whole facet.",
        ),
    ] = None,
    regions: Annotated[
        Optional[str],
        typer.Option(
            "--regions",
            help="RunUO/ServUO Regions.xml. Default: the install's or [uo.reference] regions_xml.",
        ),
    ] = None,
    region_scripts: Annotated[
        Optional[str],
        typer.Option(
            "--region-scripts",
            help="Emulator Scripts folder; region types that forbid housing are read from its AllowHousing overrides. Default: emulator_scripts, else RunUO's six types.",
        ),
    ] = None,
    server_profile: Annotated[
        Optional[str],
        typer.Option(
            "--server-profile",
            help="Server profile JSON (regions, region rules, house menu). Default: the install's or [uo.reference] server_profile.",
        ),
    ] = None,
    placement_source: Annotated[
        Optional[str],
        typer.Option(
            "--placement-source",
            help="HousePlacementTool.cs, used for names and the default house. Default: [uo.reference] house_placement_tool.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Multi source: auto, uop or mul. Default: the install's multis setting.",
        ),
    ] = None,
    no_viewer: Annotated[
        bool,
        typer.Option("--no-viewer", help="Skip the interactive viewer (viewer/index.html)."),
    ] = False,
    no_mixed: Annotated[
        bool,
        typer.Option("--no-mixed", help="Skip the mixed-size packing scenario."),
    ] = False,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Random seed for the mixed packing's zone draws."),
    ] = 20261018,
) -> None:
    """Simulate legal house placement on a facet and greedily pack houses."""
    raise SystemExit(cmd_house_capacity(SimpleNamespace(**locals())))


@uo_app.command("tiledata-export")
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


@uo_app.command("animdata-export")
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


@uo_app.command("artdef-export")
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


@uo_app.command("def-export")
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


@uo_app.command("localization-export")
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


@uo_app.command("multi-export")
def multi_export_cmd(
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
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Multi source: auto (MultiCollection.uop, else multi.mul), uop or mul. Default: the install's multis setting, else auto.",
        ),
    ] = None,
    mul_only: Annotated[
        bool,
        typer.Option(
            "--mul-only", help="Shorthand for --container mul."
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


@uo_app.command("animation-export")
def animation_export_cmd(
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
    """Export best-effort UO animation body-name clues."""
    raise SystemExit(cmd_animation_body_names_export(SimpleNamespace(**locals())))
