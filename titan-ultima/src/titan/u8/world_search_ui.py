"""U8 world-query and egg-query wizards sharing captured sources and paged search flow."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any, Callable

import typer

from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan.u8.egg_search import (
    U8_EGG_KINDS,
    U8EggSearchFilters,
    describe_u8_egg_trigger,
    query_u8_egg_triggers,
)
from titan.u8.map_browser import load_u8_map_session, validate_u8_map_output
from titan.u8.save_browser_ui import choose_u8_save_browser_source
from titan.u8.shape_browser import find_u8_browser_file, load_u8_shape_library
from titan.u8.shape_browser_ui import choose_u8_shape_target
from titan.u8.world_search import (
    U8_EGG_SEARCH_OUTPUT,
    U8_WORLD_SEARCH_OUTPUT,
    U8WorldSearchFilters,
    U8WorldSearchSession,
    build_u8_world_search_session,
    export_u8_world_search_bundle,
    format_u8_world_search_results,
    next_u8_world_search_export,
    query_u8_world_items,
)


def parse_u8_search_number(value: str) -> int:
    """Accept decimal and explicit 0x hexadecimal filter numbers, including leading zeroes."""
    text = value.strip()
    try:
        return int(text, 16 if text.lower().startswith("0x") else 10)
    except ValueError as error:
        raise ValueError(
            "U8 world search: enter a decimal or 0x hexadecimal number"
        ) from error


def parse_u8_search_area(value: str) -> tuple[int, int, int, int] | None:
    """Normalize an inclusive world-unit rectangle, with blank meaning all positions."""
    if not value.strip():
        return None
    parts = tuple(parse_u8_search_number(part) for part in value.split(","))
    if len(parts) != 4:
        raise ValueError("U8 world search: area must contain x0,y0,x1,y1")
    x0, y0, x1, y1 = parts
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _search_menu(title: str, labels: dict[str, str], default: str = "B") -> str:
    return ui.choice(title, list(labels), default, labels=labels)


def _edit_u8_search_filters(
    filters: U8WorldSearchFilters, egg_filters: U8EggSearchFilters, eggs: bool
) -> tuple[U8WorldSearchFilters, U8EggSearchFilters]:
    while True:
        print(
            json.dumps(
                {
                    "world": asdict(filters),
                    "eggs": asdict(egg_filters) if eggs else None,
                },
                indent=2,
            )
        )
        labels = {
            "N": "Name / NPC / owner / flags search",
            "S": "Shape IDs (comma separated)",
            "M": "Map (blank = all)",
            "A": "World area x0,y0,x1,y1",
            "Z": "Z range min,max",
            "F": "Family (blank = all)",
            "O": "Location scope",
            "D": "Storage source",
            "G": "Toggle GLOB child expansion",
            "I": "Item status mask",
            "H": "Shape flag mask",
            "R": "Reset filters",
            "B": "Back to results",
        }
        if eggs:
            labels.update(
                T="Trigger types",
                C="Usecode class (decimal or hex)",
                P="Teleport destination map,ID (blank = all)",
            )
        selected = _search_menu("Search filters:", labels)
        if selected == "B":
            return filters, egg_filters
        try:
            if selected == "N":
                filters = replace(filters, query=ui.text("Search:", filters.query))
            elif selected == "S":
                value = ui.text("Shape IDs:", ",".join(map(str, filters.shapes)))
                filters = replace(
                    filters,
                    shapes=tuple(
                        parse_u8_search_number(part)
                        for part in value.split(",")
                        if part.strip()
                    ),
                )
            elif selected in {"M", "F", "I", "H"}:
                key = {
                    "M": "map_id",
                    "F": "family",
                    "I": "status_mask",
                    "H": "shape_flag_mask",
                }[selected]
                old = getattr(filters, key)
                value = ui.text(key + ":", str(old) if old is not None else "")
                changes: dict[str, Any] = {
                    key: parse_u8_search_number(value)
                    if value.strip()
                    else (0 if selected in {"I", "H"} else None)
                }
                filters = replace(filters, **changes)
            elif selected == "A":
                value = ui.text(
                    "World rectangle:",
                    ",".join(map(str, filters.area)) if filters.area else "",
                )
                filters = replace(filters, area=parse_u8_search_area(value))
            elif selected == "Z":
                value = ui.text("Z range min,max:", f"{filters.min_z},{filters.max_z}")
                low, high = (parse_u8_search_number(part) for part in value.split(","))
                filters = replace(filters, min_z=low, max_z=high)
            elif selected == "O":
                filters = replace(
                    filters,
                    scope=ui.choice(
                        "Location scope:",
                        ["world", "all", "contained", "diagnostics"],
                        filters.scope,
                    ),
                )
            elif selected == "D":
                filters = replace(
                    filters,
                    storage=ui.choice(
                        "Storage:",
                        ["all", "cache", "fixed", "nonfixed", "glob"],
                        filters.storage,
                    ),
                )
            elif selected == "G":
                filters = replace(filters, expand_globs=not filters.expand_globs)
            elif selected == "T":
                value = ui.text(
                    "Types (comma separated; blank = all): " + ", ".join(U8_EGG_KINDS),
                    ",".join(egg_filters.kinds),
                )
                egg_filters = replace(
                    egg_filters,
                    kinds=tuple(
                        part.strip().lower()
                        for part in value.split(",")
                        if part.strip()
                    ),
                )
            elif selected == "C":
                value = ui.text(
                    "Usecode class:",
                    str(egg_filters.usecode_class)
                    if egg_filters.usecode_class is not None
                    else "",
                )
                egg_filters = replace(
                    egg_filters,
                    usecode_class=parse_u8_search_number(value)
                    if value.strip()
                    else None,
                )
            elif selected == "P":
                value = ui.text("Destination map,ID (both required):")
                if value.strip():
                    map_id, target = (
                        parse_u8_search_number(part) for part in value.split(",")
                    )
                    egg_filters = replace(
                        egg_filters, destination_map=map_id, destination_id=target
                    )
                else:
                    egg_filters = replace(
                        egg_filters, destination_map=None, destination_id=None
                    )
            elif selected == "R":
                filters, egg_filters = U8WorldSearchFilters(), U8EggSearchFilters()
        except ValueError as error:
            print(f"  Invalid filter: {error}")


def _export_u8_search(
    session: U8WorldSearchSession,
    rows: list[dict[str, Any]],
    output: Path,
    filters: U8WorldSearchFilters,
    egg_filters: U8EggSearchFilters,
    eggs: bool,
) -> None:
    destination = next_u8_world_search_export(output, eggs=eggs)
    export_u8_world_search_bundle(
        session,
        rows,
        destination,
        filters=filters,
        eggs=eggs,
        egg_filters=asdict(egg_filters) if eggs else None,
    )
    print(f"  Exported {len(rows):,} results: {destination / 'index.html'}")


def _search_result_label(row: dict[str, Any]) -> str:
    name = row.get("npc_label") or row["shape_name"] or "unlabelled"
    return f"{row['identity']} — {name}; map {row['map_id']}; shape {row['shape']}, frame {row['frame']}; ({row['world_x']}, {row['world_y']}, {row['world_z']}); {row.get('trigger_kind', row['location_kind'])}"


def _inspect_u8_search_result(
    session: U8WorldSearchSession,
    row: dict[str, Any],
    output: Path,
    filters: U8WorldSearchFilters,
    egg_filters: U8EggSearchFilters,
    eggs: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="titan-u8-world-preview-") as temporary:
        number = 0
        while True:
            print(json.dumps(row, indent=2))
            labels = {
                "V": "Preview native item sprite",
                "S": "Open shape browser",
                "E": "Export this result",
                "B": "Back to results",
            }
            if row["map_id"] not in {None, 0}:
                labels["M"] = "Open map browser (stored map artwork)"
            inventory = session.inventory
            key = row.get("item_id")
            if inventory and key in inventory.containers:
                labels["C"] = "Open container / NPC inventory browser"
            if (
                inventory
                and inventory.npc_session
                and row.get("owner_npc_id") is not None
            ):
                labels["N"] = "Open owning NPC browser"
            parent = row.get("container_id") or row.get("glob_parent")
            if parent is not None:
                labels["P"] = "Inspect parent container / GLOB stamp"
            if row.get("destination_matches"):
                labels["D"] = "Inspect captured teleport destination"
            selected = _search_menu("Search result:", labels)
            if selected == "B":
                return
            try:
                if selected == "V":
                    image = session.maps.library.image(row["shape"], row["frame"])
                    if row["status"] & 0x20:
                        from PIL import Image

                        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    number += 1
                    path = Path(temporary) / f"item_{number:04d}.png"
                    image.save(path)
                    open_preview(path)
                elif selected == "S":
                    from titan.u8.shape_browser_ui import browse_u8_npc_shape

                    browse_u8_npc_shape(
                        session.maps.library,
                        row["shape"],
                        frame=row["frame"],
                        output=output / "shapes",
                    )
                elif selected == "M":
                    from titan.u8.map_browser_ui import browse_u8_map_session

                    if session.coverage["active_map"] == row["map_id"]:
                        print(
                            "  Map browser artwork uses stored FIXED/NONFIXED; live search positions come from ITEMCACH."
                        )
                    browse_u8_map_session(
                        session.maps, map_id=row["map_id"], output=output / "maps"
                    )
                elif (
                    selected == "C"
                    and inventory is not None
                    and isinstance(key, (int, str))
                ):
                    from titan.u8.container_browser_ui import (
                        browse_u8_container_inventory,
                    )

                    browse_u8_container_inventory(
                        inventory, key, output=output / "inventories"
                    )
                elif selected == "N" and inventory and inventory.npc_session:
                    from titan.u8.npc_browser_ui import browse_u8_npc_session

                    browse_u8_npc_session(
                        inventory.npc_session,
                        npc=row["owner_npc_id"],
                        output=output / "npcs",
                    )
                elif selected == "E":
                    _export_u8_search(
                        session, [row], output, filters, egg_filters, eggs
                    )
                elif selected in {"P", "D"}:
                    if selected == "D":
                        identity = ui.choice(
                            "Teleport target:",
                            row["destination_matches"],
                            row["destination_matches"][0],
                        )
                    else:
                        identity = (
                            f"CACHE:{parent}"
                            if isinstance(parent, int)
                            else str(parent)
                        )
                    found = session.by_identity.get(identity)
                    if found:
                        row = (
                            describe_u8_egg_trigger(found) if eggs else None
                        ) or found
                    else:
                        print("  Parent/target is not a captured indexed record.")
            except (ValueError, OSError, IndexError) as error:
                print(f"  Preview/link unavailable: {error}")


def browse_u8_world_search(
    session: U8WorldSearchSession,
    *,
    filters: U8WorldSearchFilters = U8WorldSearchFilters(),
    egg_filters: U8EggSearchFilters = U8EggSearchFilters(),
    eggs: bool = False,
    output: Path = U8_WORLD_SEARCH_OUTPUT,
) -> None:
    """Keep search filters and page position while inspecting items and linked browsers."""
    page = 0
    dirty = True
    rows: list[dict[str, Any]] = []
    while True:
        if dirty:
            print("  Searching captured maps…")
            rows = (
                query_u8_egg_triggers(session, filters, egg_filters)
                if eggs
                else query_u8_world_items(session, filters)
            )
            dirty = False
        pages = max(1, (len(rows) + 24) // 25)
        page = min(page, pages - 1)
        print(
            f"\nU8 {'eggs / triggers' if eggs else 'world'}; {len(rows):,} results; page {page + 1}/{pages}; GLOB children {'included' if filters.expand_globs else 'off'}; filters {asdict(filters)}"
        )
        labels = {
            row["identity"]: _search_result_label(row)
            for row in rows[page * 25 : (page + 1) * 25]
        }
        labels.update(
            F="Search filters",
            E="Export all matching results",
            K="Previous page",
            J="Next page",
            Q="Quit search",
        )
        selected = _search_menu("Choose result:", labels, next(iter(labels)))
        if selected == "Q":
            return
        if selected == "F":
            filters, egg_filters = _edit_u8_search_filters(filters, egg_filters, eggs)
            page, dirty = 0, True
        elif selected == "K":
            page = max(0, page - 1)
        elif selected == "J":
            page = min(pages - 1, page + 1)
        elif selected == "E":
            _export_u8_search(session, rows, output, filters, egg_filters, eggs)
        else:
            row = next(row for row in rows if row["identity"] == selected)
            _inspect_u8_search_result(session, row, output, filters, egg_filters, eggs)


def run_u8_world_search(
    *,
    source: Path | None = None,
    game_dir: Path | None = None,
    shapes: Path | None = None,
    palette: Path | None = None,
    fixed: Path | None = None,
    names: Path | None = None,
    static_only: bool = False,
    filters: U8WorldSearchFilters = U8WorldSearchFilters(),
    egg_filters: U8EggSearchFilters = U8EggSearchFilters(),
    eggs: bool = False,
    output: Path | None = None,
    export: bool = False,
    output_format: str | None = None,
) -> int:
    """Capture one matching STATIC/save owner, then browse or run a deterministic query export."""
    output = output or (U8_EGG_SEARCH_OUTPUT if eggs else U8_WORLD_SEARCH_OUTPUT)
    try:
        if static_only and source is not None:
            raise ValueError(
                "U8 world search: specify a snapshot or --static-only, not both"
            )
        if output_format is not None and output_format not in {"table", "csv", "json"}:
            raise ValueError("U8 world search: format must be table, csv or json")
        if output_format is not None and export:
            raise ValueError("U8 world search: choose --format or --export, not both")
        if shapes is None:
            target = choose_u8_shape_target(game_dir)
            if target is None:
                return 0
            shapes = find_u8_browser_file(target.static, "U8SHAPES.FLX")
            if shapes is None:
                raise ValueError("U8 world search: selected STATIC has no U8SHAPES.FLX")
        library = load_u8_shape_library(shapes, palette=palette)
        if source is None and not static_only:
            source = choose_u8_save_browser_source(library.path.parent)
            if source is None:
                return 0
        maps = load_u8_map_session(library, source=source, fixed=fixed, names=names)
        session = build_u8_world_search_session(maps)
        validate_u8_map_output(maps, output)
        if eggs and not library.properties:
            raise ValueError("U8 egg search: matching TYPEFLAG.DAT is required")
        if output_format is None:
            print("\nTitan U8 " + ("Egg / Trigger Search" if eggs else "World Search"))
            print(json.dumps(session.coverage, indent=2))
            for issue in session.diagnostics:
                print(f"  Diagnostic: {issue}")
        if export or output_format is not None:
            rows = (
                query_u8_egg_triggers(session, filters, egg_filters)
                if eggs
                else query_u8_world_items(session, filters)
            )
            if output_format is not None:
                print(format_u8_world_search_results(rows, output_format), end="")
            if export:
                _export_u8_search(session, rows, output, filters, egg_filters, eggs)
        else:
            browse_u8_world_search(
                session,
                filters=filters,
                egg_filters=egg_filters,
                eggs=eggs,
                output=output,
            )
        return 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {error}")
        return 1


def _make_u8_search_command(eggs: bool) -> Callable[..., None]:
    def u8_search_cmd(
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
                "--palette", "-p", help="Matching U8PAL.PAL; defaults to shapes owner"
            ),
        ] = None,
        fixed: Annotated[
            Path | None,
            typer.Option(
                "--fixed", help="Matching FIXED.DAT; defaults to shapes owner"
            ),
        ] = None,
        names: Annotated[
            Path | None,
            typer.Option("--names", help="Optional npc_id,name CSV overrides"),
        ] = None,
        static_only: Annotated[
            bool,
            typer.Option("--static-only", help="Search FIXED without a save snapshot"),
        ] = False,
        query: Annotated[
            str,
            typer.Option(
                "--query",
                "-q",
                help="Shape/NPC/owner name, identity or flags substring",
            ),
        ] = "",
        shape: Annotated[
            list[str] | None,
            typer.Option("--shape", help="Shape ID, decimal/hex; repeatable"),
        ] = None,
        map_id: Annotated[
            int | None,
            typer.Option(
                "--map",
                "-m",
                min=0,
                max=255,
                help="Native world map, not an egg's map byte",
            ),
        ] = None,
        family: Annotated[
            int | None,
            typer.Option("--family", min=0, max=15, help="TYPEFLAG family ID"),
        ] = None,
        storage: Annotated[
            str, typer.Option("--storage", help="all, cache, fixed, nonfixed or glob")
        ] = "all",
        scope: Annotated[
            str, typer.Option("--scope", help="world, all, contained or diagnostics")
        ] = "world",
        area: Annotated[
            str,
            typer.Option("--area", help="Inclusive world-unit rectangle x0,y0,x1,y1"),
        ] = "",
        min_z: Annotated[int, typer.Option("--min-z", min=0, max=250)] = 0,
        max_z: Annotated[int, typer.Option("--max-z", min=0, max=250)] = 250,
        status_mask: Annotated[
            str,
            typer.Option(
                "--status-mask", help="Require all item status bits, decimal/hex"
            ),
        ] = "0",
        shape_flags: Annotated[
            str,
            typer.Option(
                "--shape-flags", help="Require all TYPEFLAG bits, decimal/hex"
            ),
        ] = "0",
        expand_globs: Annotated[
            bool,
            typer.Option(
                "--expand-globs",
                help="Also search derived GLOB children; retains stamp identities",
            ),
        ] = False,
        egg_type: Annotated[
            list[str] | None,
            typer.Option(
                "--type",
                help="egg-query only: usecode, teleport, destination, teleport_other, monster, glob, ambient; repeatable",
            ),
        ] = None,
        usecode_class: Annotated[
            str | None,
            typer.Option(
                "--class", help="egg-query only: U8 usecode class, decimal/hex"
            ),
        ] = None,
        destination_map: Annotated[
            int | None,
            typer.Option(
                "--destination-map",
                min=0,
                max=255,
                help="egg-query only: teleport destination map",
            ),
        ] = None,
        destination_id: Annotated[
            int | None,
            typer.Option(
                "--destination-id",
                min=0,
                max=255,
                help="egg-query only: teleport target ID",
            ),
        ] = None,
        output: Annotated[
            Path | None,
            typer.Option(
                "--output", "-o", help="Export root; each report uses a fresh directory"
            ),
        ] = None,
        export: Annotated[
            bool,
            typer.Option(
                "--export",
                help="Export matching HTML/CSV/JSON and native sprite previews, then exit",
            ),
        ] = False,
        output_format: Annotated[
            str | None,
            typer.Option(
                "--format", "-f", help="Print table, csv or json and exit; no menu"
            ),
        ] = None,
    ) -> None:
        try:
            if not eggs and any(
                value is not None
                for value in (egg_type, usecode_class, destination_map, destination_id)
            ):
                raise ValueError("U8 world search: trigger filters require egg-query")
            filters = U8WorldSearchFilters(
                query=query,
                shapes=tuple(parse_u8_search_number(value) for value in shape or []),
                map_id=map_id,
                family=family,
                storage=storage,
                scope=scope,
                area=parse_u8_search_area(area),
                min_z=min_z,
                max_z=max_z,
                status_mask=parse_u8_search_number(status_mask),
                shape_flag_mask=parse_u8_search_number(shape_flags),
                expand_globs=expand_globs,
            )
            triggers = U8EggSearchFilters(
                kinds=tuple(value.lower() for value in egg_type or []),
                usecode_class=parse_u8_search_number(usecode_class)
                if usecode_class is not None
                else None,
                destination_map=destination_map,
                destination_id=destination_id,
            )
        except ValueError as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(1) from error
        raise typer.Exit(
            run_u8_world_search(
                source=source,
                game_dir=game_dir,
                shapes=shapes,
                palette=palette,
                fixed=fixed,
                names=names,
                static_only=static_only,
                filters=filters,
                egg_filters=triggers,
                eggs=eggs,
                output=output,
                export=export,
                output_format=output_format,
            )
        )

    u8_search_cmd.__doc__ = (
        "Search U8 egg/trigger definitions, hatch ranges, usecode classes and teleport targets."
        if eggs
        else "Search U8 world items across maps, live cache and inventories; browse results or export reports."
    )
    return u8_search_cmd


def register_u8_world_search(app: typer.Typer) -> None:
    """Register U8 world-query and egg-query with shared source selection and search options."""
    app.command("world-query")(_make_u8_search_command(False))
    app.command("egg-query")(_make_u8_search_command(True))
