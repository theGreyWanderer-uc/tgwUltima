"""UU2 texture descriptions from STRINGS.PAK/TERRAIN.DAT and level usage.

``STRINGS.PAK`` block 10 stores one description per wall texture at the
texture's own index, and the matching floor description at ``510 - texture_id``.
``TERRAIN.DAT`` adds the property word (water, lava, stairs, and similar) for
the same texture ID, so joining the two gives every ``T64.TR`` image a readable
name and its terrain behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from titan.uw2.level import parse_terrain_dat
from titan.uw2.map_pipeline import data_directory
from titan.uw2.strings import GameStrings, clean_display_name

TEXTURE_STRING_BLOCK = 10
"""STRINGS.PAK block holding wall and floor texture descriptions."""

FLOOR_STRING_BASE = 510
"""Floor descriptions are stored at ``FLOOR_STRING_BASE - texture_id``."""

TEXTURE_ID_COUNT = 256
"""T64.TR addresses 256 texture IDs through the level texture mapping."""

USAGE_ROLES = ("floor", "wall", "ceiling_runtime", "ceiling_ua")
"""Tile roles reported per texture, including both ceiling interpretations."""


def build_texture_catalog(source: str | Path) -> dict:
    """Decode every texture ID's wall/floor description and terrain word."""
    data_dir = data_directory(source)
    strings_path = data_dir / "STRINGS.PAK"
    terrain_path = data_dir / "TERRAIN.DAT"
    strings = GameStrings.from_file(strings_path)
    terrain_by_texture: dict[int, dict] = {}
    if terrain_path.is_file():
        terrain = parse_terrain_dat(terrain_path.read_bytes())
        terrain_by_texture = {
            entry["texture_id"]: entry for entry in terrain["entries"]
        }

    return {
        "source": str(Path(source).expanduser()),
        "strings_pak": str(strings_path),
        "terrain_dat": str(terrain_path) if terrain_path.is_file() else None,
        "string_blocks": strings.summary(),
        "texture_name_rule": {
            "wall_description": (
                f"STRINGS.PAK block {TEXTURE_STRING_BLOCK}, string texture_id"
            ),
            "floor_description": (
                f"STRINGS.PAK block {TEXTURE_STRING_BLOCK}, "
                f"string {FLOOR_STRING_BASE} - texture_id"
            ),
        },
        "textures": [
            _texture_entry(texture_id, strings, terrain_by_texture.get(texture_id))
            for texture_id in range(TEXTURE_ID_COUNT)
        ],
    }


def export_texture_catalog(source: str | Path, output: str | Path) -> Path:
    """Write ``texture_catalog.json`` and return its path."""
    catalog = build_texture_catalog(source)
    destination = Path(output) / "texture_catalog.json"
    _write_json(destination, catalog)
    return destination


def catalog_by_texture_id(catalog: dict) -> dict[int, dict]:
    """Index a catalog's ``textures`` list by texture ID."""
    return {entry["texture_id"]: entry for entry in catalog["textures"]}


def level_texture_usage(level: dict, catalog_by_id: dict[int, dict]) -> dict:
    """Group one decoded level's tiles by texture ID and tile role."""
    by_texture: dict[int, dict[str, list[dict]]] = {}
    for tile in level["tiles"]:
        coord = {
            "x": tile["x"],
            "y": tile["y"],
            "display_y": tile["display_y"],
            "type_name": tile["type_name"],
        }
        for role, key in (
            ("floor", "texture_floor"),
            ("wall", "texture_wall"),
            ("ceiling_runtime", "texture_ceiling_runtime"),
            ("ceiling_ua", "texture_ceiling_ua"),
        ):
            texture_id = int(tile[key])
            roles = by_texture.setdefault(
                texture_id, {name: [] for name in USAGE_ROLES}
            )
            roles[role].append(coord)

    textures = []
    for texture_id, role_tiles in sorted(by_texture.items()):
        catalog = catalog_by_id.get(texture_id, {"texture_id": texture_id})
        terrain = catalog.get("terrain") or {}
        textures.append(
            {
                "texture_id": texture_id,
                "image": catalog.get("image"),
                "wall_description": catalog.get("wall_description"),
                "floor_description": catalog.get("floor_description"),
                "terrain_label": terrain.get("label"),
                "terrain_hex": terrain.get("terrain_hex"),
                "counts": {role: len(role_tiles[role]) for role in USAGE_ROLES},
                "tiles": role_tiles,
            }
        )

    return {
        "slot_index": level["slot_index"],
        "level_id_1based": level["level_id_1based"],
        "world_name": level.get("world_name"),
        "level_name": level.get("level_name"),
        "textures": textures,
    }


def export_texture_usage(
    levels: Iterable[dict],
    catalog: dict,
    output: str | Path,
) -> list[Path]:
    """Write per-level usage JSON plus a summary, returning every path written."""
    catalog_by_id = catalog_by_texture_id(catalog)
    output_path = Path(output)
    written: list[Path] = []
    summaries: list[dict] = []
    for level in levels:
        usage = level_texture_usage(level, catalog_by_id)
        destination = (
            output_path / f"level_{usage['slot_index']:03d}_texture_usage.json"
        )
        _write_json(destination, usage)
        written.append(destination)
        summaries.append(_summarize_usage(usage, destination))

    summary_path = output_path / "texture_usage_summary.json"
    _write_json(
        summary_path,
        {
            "catalog_source": catalog.get("source"),
            "level_count": len(summaries),
            "levels": summaries,
        },
    )
    written.append(summary_path)
    return written


def _texture_entry(texture_id: int, strings: GameStrings, terrain: dict | None) -> dict:
    wall_raw = strings.get(TEXTURE_STRING_BLOCK, texture_id)
    floor_raw = strings.get(TEXTURE_STRING_BLOCK, FLOOR_STRING_BASE - texture_id)
    return {
        "texture_id": texture_id,
        "image": f"textures/t64_{texture_id:03d}.png",
        "wall_string_index": texture_id,
        "floor_string_index": FLOOR_STRING_BASE - texture_id,
        "wall_description_raw": wall_raw,
        "floor_description_raw": floor_raw,
        "wall_description": clean_display_name(wall_raw),
        "floor_description": clean_display_name(floor_raw),
        "terrain": terrain,
    }


def _summarize_usage(usage: dict, path: Path) -> dict:
    role_counts = {role: 0 for role in USAGE_ROLES}
    for texture in usage["textures"]:
        for role in USAGE_ROLES:
            role_counts[role] += texture["counts"][role]
    return {
        "slot_index": usage["slot_index"],
        "level_id_1based": usage["level_id_1based"],
        "world_name": usage.get("world_name"),
        "level_name": usage.get("level_name"),
        "texture_count": len(usage["textures"]),
        "role_counts": role_counts,
        "usage_file": str(path),
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
