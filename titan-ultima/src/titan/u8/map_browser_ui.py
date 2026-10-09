"""U8 map-browse wizard using shared menus, native records and external PNG previews."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any

import typer

from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan.u8.map import U8MapRenderer
from titan.u8.map_browser import (
    U8_MAP_BROWSER_OUTPUT,
    U8MapBrowserFilters,
    U8MapBrowserSession,
    describe_u8_map_rows,
    describe_u8_map_summary,
    export_u8_map_bundle,
    filter_u8_map_rows,
    load_u8_map_session,
    map_npc_rows,
    next_u8_map_export,
    render_u8_browser_map,
    u8_map_container_children,
    validate_u8_map_output,
)
from titan.u8.map_items import U8MapItem
from titan.u8.npc_browser_ui import browse_u8_npc_session
from titan.u8.save_browser_ui import choose_u8_save_browser_source
from titan.u8.shape_browser import find_u8_browser_file, load_u8_shape_library
from titan.u8.shape_browser_ui import browse_u8_npc_shape, choose_u8_shape_target

PAGE_SIZE = 25


def _map_menu(title: str, labels: dict[str, str], default: str = "B") -> str:
    ui.legacy_menu(title, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ",
        list(labels),
        default if default in labels else next(iter(labels)),
        labels=labels,
        message=title,
        hotkeys=True,
    )


def _map_number(title: str, low: int, high: int, default: int = 0) -> int:
    while True:
        raw = ui.text(f"  {title}: ", str(default)).strip() or str(default)
        try:
            value = int(raw, 16 if raw.lower().startswith("0x") else 10)
            if low <= value <= high:
                return value
        except ValueError:
            pass
        print(f"  Enter {low}-{high} (decimal or hex).")


def _choose_map(session: U8MapBrowserSession) -> int | None:
    page = 0
    numbers = session.map_ids
    while True:
        labels = {}
        for map_id in numbers[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
            summary = describe_u8_map_summary(session, map_id)
            labels[str(map_id)] = (
                f"Map {map_id:03d} — FIXED {summary['fixed_records']:,}; "
                f"NONFIXED {summary['nonfixed_records']:,}; "
                f"contained {summary['contained_records']:,}; NPCs {summary['allocated_npcs']}"
                + (" [NPC registry, no world render]" if map_id == 0 else "")
            )
        if page:
            labels["P"] = "Previous maps"
        if (page + 1) * PAGE_SIZE < len(numbers):
            labels["N"] = "Next maps"
        labels.update({"I": "Enter any map ID, including empty slots", "Q": "Quit"})
        selected = _map_menu("Choose map:", labels, next(iter(labels)))
        if selected == "Q":
            return None
        if selected == "I":
            return _map_number("Map ID", 0, 255)
        if selected in {"P", "N"}:
            page += 1 if selected == "N" else -1
        else:
            return int(selected)


def _map_filters(current: U8MapBrowserFilters) -> U8MapBrowserFilters:
    while True:
        print(json.dumps(asdict(current), indent=2))
        selected = _map_menu(
            "Object/image filters:",
            {
                "S": "Storage: FIXED / NONFIXED / both",
                "V": "Records: all / world / contained / diagnostics",
                "F": "Exact shape ID or clear",
                "Q": "Search labels, flags, coordinates and record fields",
                "H": "World height range (Z); inventory slot Z is unaffected",
                "R": "Toggle hidden roofs (including expanded GLOB children)",
                "E": "Toggle hidden editor markers in images (records remain visible)",
                "C": "Clear all filters",
                "B": "Back to map",
            },
        )
        if selected == "B":
            return current
        if selected == "S":
            value = _map_menu("Storage:", {"B": "Both", "F": "FIXED", "N": "NONFIXED"})
            current = replace(
                current, storage={"B": "both", "F": "fixed", "N": "nonfixed"}[value]
            )
        elif selected == "V":
            value = _map_menu(
                "Records:",
                {"A": "All", "W": "World", "C": "Contained", "D": "Diagnostics"},
                "A",
            )
            current = replace(
                current,
                scope={"A": "all", "W": "world", "C": "contained", "D": "diagnostics"}[
                    value
                ],
            )
        elif selected == "F":
            raw = ui.text("  Shape ID (blank clears): ").strip()
            if not raw:
                current = replace(current, shape=None)
            else:
                try:
                    current = replace(
                        current,
                        shape=int(raw, 16 if raw.lower().startswith("0x") else 10),
                    )
                except ValueError as error:
                    print(f"  {error}")
        elif selected == "Q":
            current = replace(
                current, query=ui.text("  Search: ", current.query).strip()
            )
        elif selected == "H":
            low = _map_number("Minimum world Z", 0, 250, current.min_z)
            high = _map_number("Maximum world Z", low, 250, max(low, current.max_z))
            current = replace(current, min_z=low, max_z=high)
        elif selected == "R":
            current = replace(current, hide_roofs=not current.hide_roofs)
        elif selected == "E":
            current = replace(current, hide_editor=not current.hide_editor)
        else:
            current = U8MapBrowserFilters()


def _row_label(row: dict[str, Any]) -> str:
    return (
        f"{row['archive_kind']} #{row['record_index']} — "
        f"shape {row['shape']} {row['shape_name']}, frame {row['frame']}; "
        f"({row['x']}, {row['y']}, {row['z']}) [{row['location_kind']}]"
    )


def _object_detail(session: U8MapBrowserSession, item: U8MapItem, output: Path) -> None:
    while True:
        row = next(
            row
            for row in describe_u8_map_rows(session, item.map_id)
            if row["archive_kind"] == item.archive_kind
            and row["record_index"] == item.record_index
        )
        print(json.dumps(row, indent=2))
        children = u8_map_container_children(session, item)
        labels = {
            "C": f"Immediate container children ({len(children)})",
            "B": "Back to objects",
        }
        if item.shape in session.library.records:
            labels["S"] = "Browse this shape/frame and animation sets"
        if item.parent_record_index is not None:
            labels["P"] = "Inspect parent container"
        selected = _map_menu("Object details:", labels)
        if selected == "B":
            return
        if selected == "S":
            validate_u8_map_output(session, output)
            browse_u8_npc_shape(
                session.library, item.shape, frame=item.frame, output=output
            )
        elif selected == "C":
            keys = {(child.archive_kind, child.record_index) for child in children}
            rows = [
                row
                for row in describe_u8_map_rows(session, item.map_id)
                if (row["archive_kind"], row["record_index"]) in keys
            ]
            _browse_map_objects(session, item.map_id, rows, output)
        else:
            item = next(
                candidate
                for candidate in session.records(item.map_id)
                if candidate.archive_kind == item.archive_kind
                and candidate.record_index == item.parent_record_index
            )


def _browse_map_objects(
    session: U8MapBrowserSession,
    map_id: int,
    rows: list[dict[str, Any]],
    output: Path,
) -> None:
    page = 0
    while True:
        print(
            f"  {len(rows):,} object records; page {page + 1} of {max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)}"
        )
        labels = {
            str(index + 1): _row_label(row)
            for index, row in enumerate(rows)
            if page * PAGE_SIZE <= index < (page + 1) * PAGE_SIZE
        }
        if page:
            labels["P"] = "Previous objects"
        if (page + 1) * PAGE_SIZE < len(rows):
            labels["N"] = "Next objects"
        labels["B"] = "Back"
        selected = _map_menu("Objects:", labels)
        if selected == "B":
            return
        if selected in {"P", "N"}:
            page += 1 if selected == "N" else -1
            continue
        row = rows[int(selected) - 1]
        item = next(
            item
            for item in session.records(map_id)
            if item.archive_kind == row["archive_kind"]
            and item.record_index == row["record_index"]
        )
        _object_detail(session, item, output)


def _browse_map_npcs(session: U8MapBrowserSession, map_id: int, output: Path) -> None:
    rows = map_npc_rows(session, map_id)
    if not rows or session.npc_session is None:
        print("  No allocated NPC slots on this map, or NPCDATA/ITEMCACH unavailable.")
        return
    page = 0
    while True:
        labels = {
            str(
                row["npc_id"]
            ): f"{row['npc_label']} — shape {row['item_shape']}; ({row['item_x']}, {row['item_y']}, {row['item_z']})"
            for row in rows[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        }
        if page:
            labels["P"] = "Previous NPCs"
        if (page + 1) * PAGE_SIZE < len(rows):
            labels["N"] = "Next NPCs"
        labels["B"] = "Back to map"
        selected = _map_menu("Captured NPCs on this map:", labels)
        if selected == "B":
            return
        if selected in {"P", "N"}:
            page += 1 if selected == "N" else -1
        else:
            validate_u8_map_output(session, output)
            browse_u8_npc_session(session.npc_session, npc=int(selected), output=output)


def _browse_map_session(
    session: U8MapBrowserSession,
    initial_map: int | None,
    output: Path,
    *,
    embedded: bool = False,
) -> None:
    filters = U8MapBrowserFilters()
    view = "iso_classic"
    scale = 64
    grid = False
    map_id = initial_map
    with tempfile.TemporaryDirectory(prefix="titan-u8-map-preview-") as temporary:
        previews = Path(temporary)
        preview_number = 0
        while True:
            if map_id is None:
                map_id = _choose_map(session)
                if map_id is None:
                    return
            print(json.dumps(describe_u8_map_summary(session, map_id), indent=2))
            print(
                f"  Image: {view}; overview scale {scale}; grid {grid}; filters {asdict(filters)}"
            )
            selected = _map_menu(
                f"Map {map_id:03d}:",
                {
                    "T": "Preview top-down colour overview in image viewer",
                    "I": "Preview isometric map in image viewer",
                    "O": "Browse objects and containers",
                    "N": "Browse named NPCs on this map",
                    "F": "Object/image filters",
                    "V": "Image projection / scale / grid",
                    "E": "Export fresh HTML + PNG + CSV + JSON report",
                    "M": "Choose another map",
                    "Q": "Back to parent browser" if embedded else "Quit",
                },
                "O",
            )
            if selected == "Q":
                return
            try:
                if selected == "M":
                    map_id = None
                elif selected == "F":
                    filters = _map_filters(filters)
                elif selected == "V":
                    keys = {
                        str(index + 1): name
                        for index, name in enumerate(U8MapRenderer.PROJECTIONS)
                    }
                    chosen = _map_menu("Isometric projection:", keys, "1")
                    view = keys[chosen]
                    scale = _map_number(
                        "Overview world units per pixel", 1, 4096, scale
                    )
                    grid = (
                        _map_menu(
                            "Chunk grid:",
                            {"Y": "Show", "N": "Hide"},
                            "Y" if grid else "N",
                        )
                        == "Y"
                    )
                elif selected == "O":
                    rows = filter_u8_map_rows(
                        session, describe_u8_map_rows(session, map_id), filters
                    )
                    _browse_map_objects(session, map_id, rows, output)
                elif selected == "N":
                    _browse_map_npcs(session, map_id, output)
                elif selected == "E":
                    path = export_u8_map_bundle(
                        session,
                        map_id,
                        next_u8_map_export(output, map_id),
                        filters=filters,
                        view=view,
                        scale=scale,
                        grid=grid,
                    )
                    print(f"  Exported: {path / 'index.html'}")
                else:
                    image, info = render_u8_browser_map(
                        session,
                        map_id,
                        filters=filters,
                        view="sample" if selected == "T" else view,
                        scale=scale,
                        grid=grid,
                    )
                    preview_number += 1
                    path = previews / f"map_{map_id:03d}_{preview_number:03d}.png"
                    image.save(path)
                    print(json.dumps(info, indent=2))
                    print(f"  Preview: {path}")
                    if not open_preview(path):
                        print(
                            "  Image viewer unavailable; use Export to save the PNG permanently."
                        )
            except (ValueError, OSError) as error:
                print(f"  Cannot complete map action: {error}")


def run_u8_map_browser(
    *,
    source: Path | None = None,
    game_dir: Path | None = None,
    shapes: Path | None = None,
    palette: Path | None = None,
    fixed: Path | None = None,
    globs: Path | None = None,
    map_id: int | None = None,
    names: Path | None = None,
    output: Path = U8_MAP_BROWSER_OUTPUT,
    static_only: bool = False,
    export: bool = False,
) -> int:
    """Browse one matching STATIC/save pair; --export provides a reproducible report run."""
    print("\nTitan U8 Map Browser")
    try:
        if map_id is not None and not 0 <= map_id <= 255:
            raise ValueError("U8 map browser: map ID must be 0-255")
        if static_only and source is not None:
            raise ValueError(
                "U8 map browser: choose either a snapshot or --static-only"
            )
        if export and map_id is None:
            raise ValueError("U8 map browser: --export requires --map")
        if shapes is None:
            target = choose_u8_shape_target(game_dir)
            if target is None:
                return 0
            shapes = find_u8_browser_file(target.static, "U8SHAPES.FLX")
            if shapes is None:
                raise ValueError("U8 map browser: selected STATIC has no U8SHAPES.FLX")
        library = load_u8_shape_library(shapes, palette=palette)
        if source is None and not static_only:
            selected = _map_menu(
                "Map state:",
                {"S": "Choose native save / GAMEDAT", "F": "FIXED only", "Q": "Quit"},
                "S",
            )
            if selected == "Q":
                return 0
            if selected == "S":
                source = choose_u8_save_browser_source(library.path.parent)
                if source is None:
                    return 0
        session = load_u8_map_session(
            library, source=source, fixed=fixed, globs=globs, names=names
        )
        print(f"  STATIC: {library.path.parent}; FIXED: {session.fixed_path}")
        print(
            f"  State: {source or 'FIXED only'}; {len(session.map_ids)} populated map slots"
        )
        for issue in library.diagnostics:
            print(f"  Metadata diagnostic: {issue}")
        if session.snapshot:
            for name, issue in session.snapshot.decode_errors.items():
                print(f"  Snapshot diagnostic ({name}): {issue}")
        if export and map_id is not None:
            path = export_u8_map_bundle(
                session, map_id, next_u8_map_export(output, map_id)
            )
            print(f"  Exported: {path / 'index.html'}")
        else:
            _browse_map_session(session, map_id, output)
        return 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {error}")
        return 1


def browse_u8_map_session(
    session: U8MapBrowserSession,
    *,
    map_id: int | None = None,
    output: Path = U8_MAP_BROWSER_OUTPUT,
) -> None:
    """Embed a captured map session; Q returns to the calling browser."""
    if map_id is not None and not 0 <= map_id <= 255:
        raise ValueError("U8 map browser: map ID must be 0-255")
    _browse_map_session(session, map_id, output, embedded=True)


def map_browse_cmd(
    source: Annotated[
        Path | None,
        typer.Argument(
            help="Native U8SAVE, GAMEDAT or loose NONFIXED.DAT; otherwise choose interactively"
        ),
    ] = None,
    game_dir: Annotated[
        Path | None,
        typer.Option(
            "--game-dir", help="U8 installation, language or STATIC directory"
        ),
    ] = None,
    shapes: Annotated[
        Path | None,
        typer.Option("--shapes", help="Matching U8SHAPES.FLX world graphics"),
    ] = None,
    palette: Annotated[
        Path | None,
        typer.Option(
            "-p",
            "--palette",
            help="Matching U8PAL.PAL; otherwise selected shapes owner",
        ),
    ] = None,
    fixed: Annotated[
        Path | None,
        typer.Option(
            "--fixed", help="Matching FIXED.DAT; otherwise selected STATIC owner"
        ),
    ] = None,
    globs: Annotated[
        Path | None,
        typer.Option(
            "--globs", help="Matching GLOB.FLX; otherwise selected STATIC owner"
        ),
    ] = None,
    map_id: Annotated[
        int | None,
        typer.Option(
            "--map",
            "-m",
            min=0,
            max=255,
            help="Initial native map slot (0 is the NPC registry)",
        ),
    ] = None,
    names: Annotated[
        Path | None, typer.Option("--names", help="Optional npc_id,name CSV overrides")
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o", "--output", help="Export folder; every report uses a fresh directory"
        ),
    ] = U8_MAP_BROWSER_OUTPUT,
    static_only: Annotated[
        bool, typer.Option("--static-only", help="Browse FIXED without a snapshot")
    ] = False,
    export: Annotated[
        bool, typer.Option("--export", help="Export the selected --map report and exit")
    ] = False,
) -> None:
    """Browse U8 maps, native objects/containers, named NPCs and PNG/data exports."""
    raise SystemExit(
        run_u8_map_browser(
            source=source,
            game_dir=game_dir,
            shapes=shapes,
            palette=palette,
            fixed=fixed,
            globs=globs,
            map_id=map_id,
            names=names,
            output=output,
            static_only=static_only,
            export=export,
        )
    )


def register_u8_map_browser(app: typer.Typer) -> None:
    """Register the interactive map browser alongside existing U8 render commands."""
    app.command("map-browse")(map_browse_cmd)
