"""Repeatable world searches, interactive refinement, and portable TOML recipes."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Optional

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import (
    ALL_FLAG_NAMES,
    TILE_MAX,
    WorldQueryParams,
    WorldResult,
    format_result,
    load_query_metadata,
    parse_numbers,
    parse_rectangle,
    resolve_world_sources,
    run_query,
    validate_params,
)


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
            raise ValueError(f"Unknown or invalid recipe section: {section}")
        for key, value in entries.items():
            field = schemas[section].get(key)
            if field is None:
                raise ValueError(f"Unknown recipe option: {section}.{key}")
            if field in path_fields:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{section}.{key} must be a non-empty path")
                p = Path(value).expanduser()
                value = str(p if p.is_absolute() else recipe.parent / p)
            elif field in integer_fields:
                if not isinstance(value, list) or any(
                    type(n) is not int for n in value
                ):
                    raise ValueError(f"{section}.{key} must be an integer array")
                if field == "tile_rect":
                    if len(value) != 4:
                        raise ValueError("filters.tile_rect must have four coordinates")
                    value = parse_rectangle(",".join(str(n) for n in value))
            elif field == "shape_classes":
                class_codes = {v: k for k, v in U7TypeFlags.SHAPE_CLASS_NAMES.items()}
                if not isinstance(value, list) or any(
                    not isinstance(c, str) or c not in class_codes for c in value
                ):
                    raise ValueError(
                        "filters.classes must be an array of valid class names"
                    )
                value = [class_codes[c] for c in value]
            elif field == "tfa_flags":
                if not isinstance(value, list) or any(
                    not isinstance(f, str) for f in value
                ):
                    raise ValueError("filters.flags must be a string array")
            elif field in {"include_ifix", "include_ireg"}:
                if type(value) is not bool:
                    raise ValueError(f"{section}.{key} must be a boolean")
            elif field == "map_num":
                if type(value) is not int:
                    raise ValueError("world.map_num must be an integer")
            elif not isinstance(value, str):
                raise ValueError(f"{section}.{key} must be text")
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
    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)


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


class _Cancelled(Exception):
    pass


def _ask(prompt: Any) -> Any:
    answer = prompt.ask()
    if answer is None:
        raise _Cancelled
    return answer


def _validated_text(
    q: Any, label: str, default: str, parser: Callable[[str], Any]
) -> Any:
    while True:
        raw = _ask(q.text(label, default=default))
        try:
            return parser(raw.strip())
        except ValueError as error:
            print(f"  {error}")
            default = raw


def _directory(value: str) -> str:
    if not value or not Path(value).expanduser().is_dir():
        raise ValueError("Enter an existing directory")
    return str(Path(value).expanduser())


def _filters(q: Any, params: WorldQueryParams) -> WorldQueryParams:
    classes = _ask(
        q.checkbox(
            "Shape classes (blank = all):",
            choices=[
                q.Choice(name, checked=code in params.shape_classes)
                for code, name in U7TypeFlags.SHAPE_CLASS_NAMES.items()
            ],
        )
    )
    selected = [
        code for code, name in U7TypeFlags.SHAPE_CLASS_NAMES.items() if name in classes
    ]
    use_ireg = _ask(
        q.confirm(
            "Include IREG dynamic objects?",
            default=params.include_ireg
            or bool(params.gamedat_dir and any(c in (6, 7, 12, 13) for c in selected)),
        )
    )
    gamedat = params.gamedat_dir
    if use_ireg:
        gamedat = _validated_text(q, "GAMEDAT directory:", gamedat or "", _directory)
    name = _ask(
        q.text("Name contains (blank = any):", default=params.name_filter)
    ).strip()
    if name:
        try:
            _, names, _, _ = load_query_metadata(params)
            if names:
                matches = names.find_shapes(name)
                if matches:
                    print(
                        "Matching shapes: "
                        + ", ".join(names.label(n) for n in matches[:8])
                    )
                else:
                    print("No matching shape names; frame names will also be searched.")
        except (ValueError, OSError) as error:
            print(f"Name hints unavailable: {error}")
    shapes = _validated_text(
        q,
        "Shape numbers (comma-separated; blank = all):",
        ",".join(map(str, params.shape_nums)),
        lambda s: parse_numbers(s, 65535, "Shape number"),
    )
    frames = _validated_text(
        q,
        "Frame numbers (comma-separated; blank = all):",
        ",".join(map(str, params.frames)),
        lambda s: parse_numbers(s, 255, "Frame number"),
    )
    flags = _ask(
        q.checkbox(
            "TFA flags (all selected flags required; blank = none):",
            choices=[
                q.Choice(f, checked=f in params.tfa_flags) for f in ALL_FLAG_NAMES
            ],
        )
    )
    return replace(
        params,
        shape_classes=selected,
        include_ireg=use_ireg,
        gamedat_dir=gamedat,
        name_filter=name,
        shape_nums=shapes,
        frames=frames,
        tfa_flags=flags,
    )


def _area(q: Any, params: WorldQueryParams) -> WorldQueryParams:
    default = (
        "Tile rectangle"
        if params.tile_rect
        else "Superchunks"
        if params.superchunks
        else "Entire world"
    )
    kind = _ask(
        q.select(
            "Search area:",
            choices=["Entire world", "Superchunks", "Tile rectangle"],
            default=default,
        )
    )
    chunks = []
    rect = None
    if kind == "Superchunks":

        def nonempty(s: str) -> list[int]:
            values = parse_numbers(s, 143, "Superchunk")
            if not values:
                raise ValueError("Enter at least one superchunk")
            return values

        chunks = _validated_text(
            q,
            "Superchunks (decimal or 0x hex, comma-separated):",
            ",".join(map(str, params.superchunks)),
            nonempty,
        )
    elif kind == "Tile rectangle":
        rect = _validated_text(
            q,
            f"Tile rectangle x0,y0,x1,y1 (0–{TILE_MAX}):",
            ",".join(map(str, params.tile_rect)) if params.tile_rect else "",
            parse_rectangle,
        )
    return replace(params, superchunks=chunks, tile_rect=rect)


def run_wizard(initial: WorldQueryParams) -> int:
    import questionary as q

    print("U7 World Query")
    validate_params(initial)
    try:
        params = replace(initial)
        if not params.static_dir or not Path(params.static_dir).expanduser().is_dir():
            params.static_dir = _validated_text(
                q, "STATIC or mod patch directory:", params.static_dir, _directory
            )
        # Resolve an external mod's base once, rather than discovering an unrelated game.
        try:
            resolve_world_sources(replace(params, include_ireg=False))
        except ValueError as error:
            if not str(error).startswith("Cannot resolve the mod's base STATIC"):
                raise
            print(error)
            params.base_static = _validated_text(
                q, "Base STATIC directory:", params.base_static or "", _directory
            )
        mode = "filters"
        while True:
            if mode in ("filters", "new"):
                if mode == "new":
                    params = replace(
                        params,
                        shape_classes=[],
                        shape_nums=[],
                        frames=[],
                        tfa_flags=[],
                        name_filter="",
                        superchunks=[],
                        tile_rect=None,
                        output_path=None,
                    )
                params = _filters(q, params)
            if mode in ("filters", "new", "area"):
                params = _area(q, params)
            print("\n" + describe_query(params))
            if not _ask(q.confirm("Run this search?", default=True)):
                mode = "filters"
                continue
            try:
                result = run_query(params)
            except (ValueError, OSError) as error:
                print(f"Search could not run: {error}")
                mode = "filters"
                continue
            report_warnings(result)
            print(
                format_result(
                    WorldResult(
                        replace(params, output_format="summary"), result.records
                    )
                )
            )
            while True:
                action = _ask(
                    q.select(
                        "Next action:",
                        choices=[
                            "Refine filters",
                            "Change area",
                            "Show placements",
                            "Export results",
                            "Save recipe",
                            "New search",
                            "Finish",
                        ],
                        default="Finish",
                    )
                )
                if action == "Finish":
                    return 0
                if action in ("Refine filters", "Change area", "New search"):
                    mode = {
                        "Refine filters": "filters",
                        "Change area": "area",
                        "New search": "new",
                    }[action]
                    break
                if action == "Show placements":
                    counts = Counter(r.shape for r in result.records)
                    labels = {r.shape: r.shape_label() for r in result.records}
                    choices = [
                        q.Choice(
                            f"{labels[shape]}: {counts[shape]} placements",
                            value=shape,
                        )
                        for shape in sorted(counts)
                    ]
                    if not choices:
                        print("No placements to show.")
                        continue
                    shape = _ask(q.select("Choose a shape:", choices=choices))
                    subset = WorldResult(
                        replace(params, output_format="full_text"),
                        [r for r in result.records if r.shape == shape],
                    )
                    print(format_result(subset))
                elif action == "Export results":
                    fmt = _ask(
                        q.select(
                            "Export format:",
                            choices=["summary", "full_text", "csv"],
                            default=params.output_format,
                        )
                    )
                    path = _ask(
                        q.path("Output file:", default=params.output_path or "")
                    )
                    if not path.strip():
                        print("Enter an output path.")
                        continue
                    overwrite = False
                    if Path(path).expanduser().exists():
                        overwrite = _ask(
                            q.confirm(
                                "Replace the existing output file?", default=False
                            )
                        )
                        if not overwrite:
                            continue
                    try:
                        exported = WorldResult(
                            replace(params, output_format=fmt), result.records
                        )
                        write_results(exported, path, overwrite=overwrite)
                    except (ValueError, OSError) as error:
                        print(f"Export failed: {error}")
                        continue
                    params = replace(params, output_format=fmt, output_path=path)
                    result.params = params
                    print(f"Wrote {result.count} placements to {path}")
                elif action == "Save recipe":
                    path = _ask(q.path("New TOML recipe file:"))
                    if not path.strip():
                        print("Enter a recipe path.")
                        continue
                    try:
                        save_recipe(params, path)
                    except (ValueError, OSError) as error:
                        print(f"Recipe could not be saved: {error}")
                        continue
                    print(f"Saved recipe to {path}")
    except _Cancelled:
        print("Search cancelled.")
        return 0
