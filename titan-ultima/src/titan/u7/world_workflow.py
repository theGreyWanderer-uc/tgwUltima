"""Repeatable world searches, interactive refinement, and portable TOML recipes."""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import (
    WorldQueryParams,
    WorldResult,
    format_result,
    parse_rectangle,
    resolve_world_sources,
    validate_params,
)
from titan.errors import InvalidDataError


log = logging.getLogger(__name__)


def describe_query(params: WorldQueryParams) -> str:
    base, patch = resolve_world_sources(params)
    classes = (
        ", ".join(U7TypeFlags.SHAPE_CLASS_NAMES[c] for c in params.shape_classes)
        or "all"
    )
    area = (
        f"tiles {params.tile_rect}"
        if params.tile_rect
        else f"superchunks {params.superchunks}"
        if params.superchunks
        else "entire world"
    )
    sources = [
        name
        for enabled, name in (
            (params.include_ifix, "IFIX (fixed objects)"),
            (params.include_ireg, "IREG (dynamic objects)"),
        )
        if enabled
    ]
    return "\n".join(
        [
            f"Game: {params.game.upper()} | Map: {params.map_num}",
            f"Base STATIC: {base}",
            f"Mod patch: {patch or 'none'}",
            f"Mod names: {params.mod_data_dir or patch or 'none'}",
            f"GAMEDAT: {params.gamedat_dir if params.include_ireg else 'not searched'}",
            f"Sources: {', '.join(sources)}",
            f"TEXT.FLX: {params.text_flx_path or 'patch, then base STATIC'}",
            f"Classes: {classes} | Shapes: {params.shape_nums or 'all'} | Frames: {params.frames or 'all'}",
            f"Name: {params.name_filter or 'any'} | Flags (all required): {', '.join(params.tfa_flags) or 'none'}",
            f"Area: {area}",
        ]
    )


def load_recipe(
    path: str, defaults: Optional[WorldQueryParams] = None
) -> WorldQueryParams:
    """Load a validated recipe; recipe-relative paths never depend on the cwd."""
    recipe = Path(path).expanduser().resolve()
    with recipe.open("rb") as stream:
        data = tomllib.load(stream)
    schemas = {
        "world": {
            "game": "game",
            "static": "static_dir",
            "base_static": "base_static",
            "patch": "patch_dir",
            "mod_data": "mod_data_dir",
            "gamedat": "gamedat_dir",
            "text": "text_flx_path",
            "map_num": "map_num",
        },
        "filters": {
            "classes": "shape_classes",
            "shapes": "shape_nums",
            "frames": "frames",
            "name": "name_filter",
            "flags": "tfa_flags",
            "superchunks": "superchunks",
            "tile_rect": "tile_rect",
        },
        "sources": {"ifix": "include_ifix", "ireg": "include_ireg"},
        "output": {"format": "output_format", "path": "output_path"},
    }
    path_fields = {
        "static_dir",
        "base_static",
        "patch_dir",
        "mod_data_dir",
        "gamedat_dir",
        "text_flx_path",
        "output_path",
    }
    integer_fields = {"shape_nums", "frames", "superchunks", "tile_rect"}
    changes: dict[str, Any] = {}
    for section, entries in data.items():
        if section not in schemas or not isinstance(entries, dict):
            raise InvalidDataError(f"Unknown or invalid recipe section: {section}")
        for key, value in entries.items():
            field = schemas[section].get(key)
            if field is None:
                raise InvalidDataError(f"Unknown recipe option: {section}.{key}")
            if field in path_fields:
                if not isinstance(value, str) or not value.strip():
                    raise InvalidDataError(f"{section}.{key} must be a non-empty path")
                p = Path(value).expanduser()
                value = str(p if p.is_absolute() else recipe.parent / p)
            elif field in integer_fields:
                if not isinstance(value, list) or any(
                    type(n) is not int for n in value
                ):
                    raise InvalidDataError(f"{section}.{key} must be an integer array")
                if field == "tile_rect":
                    if len(value) != 4:
                        raise InvalidDataError(
                            "filters.tile_rect must have four coordinates"
                        )
                    value = parse_rectangle(",".join(str(n) for n in value))
            elif field == "shape_classes":
                class_codes = {v: k for k, v in U7TypeFlags.SHAPE_CLASS_NAMES.items()}
                if not isinstance(value, list) or any(
                    not isinstance(c, str) or c not in class_codes for c in value
                ):
                    raise InvalidDataError(
                        "filters.classes must be an array of valid class names"
                    )
                value = [class_codes[c] for c in value]
            elif field == "tfa_flags":
                if not isinstance(value, list) or any(
                    not isinstance(f, str) for f in value
                ):
                    raise InvalidDataError("filters.flags must be a string array")
            elif field in {"include_ifix", "include_ireg"}:
                if type(value) is not bool:
                    raise InvalidDataError(f"{section}.{key} must be a boolean")
            elif field == "map_num":
                if type(value) is not int:
                    raise InvalidDataError("world.map_num must be an integer")
            elif not isinstance(value, str):
                raise InvalidDataError(f"{section}.{key} must be text")
            changes[field] = value
    params = replace(defaults or WorldQueryParams(static_dir=""), **changes)
    validate_params(params, require_gamedat=False)
    return params


def save_recipe(params: WorldQueryParams, path: str) -> None:
    """Save paths relative to the recipe where possible; refuse implicit overwrite."""
    validate_params(params)
    target = Path(path).expanduser().resolve()
    base, patch = resolve_world_sources(params)

    def portable(value: Optional[str]) -> Optional[str]:
        if value is None or not value:
            return None
        resolved = Path(value).expanduser().resolve()
        try:
            return str(resolved.relative_to(target.parent))
        except ValueError:
            return str(resolved)

    world: dict[str, Any] = {"game": params.game, "map_num": params.map_num}
    world.update(
        {
            key: portable(value)
            for key, value in {
                "static": params.static_dir,
                "base_static": str(base) if patch else params.base_static,
                "patch": str(patch) if patch else None,
                "mod_data": params.mod_data_dir,
                "gamedat": params.gamedat_dir,
                "text": params.text_flx_path,
            }.items()
            if value
        }
    )
    filters: dict[str, Any] = {
        "classes": [U7TypeFlags.SHAPE_CLASS_NAMES[c] for c in params.shape_classes],
        "shapes": params.shape_nums,
        "frames": params.frames,
        "name": params.name_filter,
        "flags": params.tfa_flags,
        "superchunks": params.superchunks,
    }
    if params.tile_rect is not None:
        filters["tile_rect"] = list(params.tile_rect)
    output = {"format": params.output_format}
    if params.output_path:
        output["path"] = portable(params.output_path) or ""
    data = tomli_w.dumps(
        {
            "world": world,
            "filters": filters,
            "sources": {"ifix": params.include_ifix, "ireg": params.include_ireg},
            "output": output,
        }
    )
    # Exclusive create avoids silently replacing an existing recipe.
    with target.open("x", encoding="utf-8") as stream:
        stream.write(data)


def report_warnings(result: WorldResult) -> None:
    """Log the query's warnings (the CLI shows them as ``Warning: ...`` on stderr)."""
    for warning in result.warnings:
        log.warning("%s", warning)


def write_results(result: WorldResult, path: str, *, overwrite: bool = False) -> None:
    """Protect input data and avoid implicit overwrites during interactive export."""
    target = Path(path).expanduser().resolve()
    base, patch = resolve_world_sources(result.params)
    protected = [
        base,
        patch,
        Path(result.params.gamedat_dir) if result.params.gamedat_dir else None,
        Path(result.params.mod_data_dir) if result.params.mod_data_dir else None,
    ]
    for directory in protected:
        if directory is not None and (
            target == directory.resolve() or directory.resolve() in target.parents
        ):
            raise ValueError("Export outside the game, patch, and GAMEDAT directories")
    if (
        result.params.text_flx_path
        and target == Path(result.params.text_flx_path).expanduser().resolve()
    ):
        raise ValueError("Output must be distinct from TEXT.FLX")
    with target.open("w" if overwrite else "x", encoding="utf-8", newline="") as stream:
        stream.write(format_result(result))
