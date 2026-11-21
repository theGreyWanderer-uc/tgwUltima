"""Interactive world-query wizard (the terminal half of :mod:`titan.u7.world_workflow`)."""

from __future__ import annotations


import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from titan import _wizard_ui as ui

if sys.version_info >= (3, 11):
    pass
else:
    pass

from titan.u7.typeflag import U7TypeFlags
from titan.u7.target_picker import SelectionCancelled, select_world
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


from titan.u7.world_workflow import (
    describe_query,
    report_warnings,
    save_recipe,
    write_results,
)


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
        ui.select(
            "Search area:",
            q=q,
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
    validate_params(initial, require_gamedat=False)
    try:
        params = select_world(q, replace(initial))
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
                    ui.select(
                        "Next action:",
                        q=q,
                        choices=[
                            "Refine filters",
                            "Change area",
                            "Show placements",
                            "Export results",
                            "Save recipe",
                            "New search",
                            "Change world/map",
                            "Finish",
                        ],
                        default="Finish",
                    )
                )
                if action == "Finish":
                    return 0
                if action == "Change world/map":
                    params = select_world(q, params)
                    mode = "filters"
                    break
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
                    shape = _ask(ui.select("Choose a shape:", q=q, choices=choices))
                    subset = WorldResult(
                        replace(params, output_format="full_text"),
                        [r for r in result.records if r.shape == shape],
                    )
                    print(format_result(subset))
                elif action == "Export results":
                    fmt = _ask(
                        ui.select(
                            "Export format:",
                            q=q,
                            choices=["summary", "full_text", "csv"],
                            default=params.output_format,
                        )
                    )
                    path = _ask(
                        ui.path_prompt(
                            "Output file:", q=q, default=params.output_path or ""
                        )
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
                    path = _ask(ui.path_prompt("New TOML recipe file:", q=q))
                    if not path.strip():
                        print("Enter a recipe path.")
                        continue
                    try:
                        save_recipe(params, path)
                    except (ValueError, OSError) as error:
                        print(f"Recipe could not be saved: {error}")
                        continue
                    print(f"Saved recipe to {path}")
    except (_Cancelled, SelectionCancelled):
        print("Search cancelled.")
        return 0
