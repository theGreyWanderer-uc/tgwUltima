"""Install resolution, output and option helpers shared by UO command families."""

from __future__ import annotations

__all__ = [
    "_animdata_metadata",
    "_client_path",
    "_entry_iter",
    "_equipconv_rows",
    "_land_metadata",
    "_load_animdata",
    "_load_artdef",
    "_load_cliloc",
    "_load_defs",
    "_load_radar",
    "_load_tiledata",
    "_out",
    "_parse_int_list",
    "_redirect_metadata",
    "_source",
    "_static_metadata",
    "_tile_flag_text",
    "_try_load_animdata",
    "_try_load_defs",
    "_try_load_tiledata",
    "_try_load_tilehelp",
    "_write_manifest",
]

import csv
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from titan.uo.installs import resolve_install
from titan.uo.animdata import UOAnimData, UOAnimDataEntry
from titan.uo.artdef import UOArtDef
from titan.uo.definfo import (
    UODefFile,
    UOEquipConvDefEntry,
    UORedirectDefEntry,
    load_all_defs,
)
from titan.uo.indexed import UOIndexedFile, UOIndexEntry
from titan.uo.localization import UOCliloc, parse_iff_text_file
from titan.uo.radar import UORadarColors
from titan.uo.tiledata import UOLandTile, UOStaticTile, UOTileData


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


def _parse_int_list(value: str, count: tuple[int, ...], label: str) -> list[int]:
    parts = [part for part in re.split(r"[,x\s]+", value.strip()) if part]
    if len(parts) not in count:
        raise ValueError(
            f"{label} needs {' or '.join(map(str, count))} numbers: {value!r}"
        )
    return [int(part) for part in parts]
