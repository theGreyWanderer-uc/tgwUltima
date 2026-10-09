"""Interactive U8 NPC menus with shared terminal controls and read-only exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from PIL import Image

from titan import _wizard_ui as ui
from titan._config import cfg
from titan._terminal_image import terminal_image
from titan.u8.npc_animation_report import export_u8_npc_animation_report
from titan.u8.npc_browser import (
    U8_NPC_BROWSER_OUTPUT,
    U8NpcSession,
    describe_u8_npc_equipment,
    describe_u8_npc_source_overview,
    discover_u8_npc_sources,
    filter_u8_npcs,
    format_u8_npc_browser_summary,
    load_u8_npc_session,
    u8_npc_is_allocated,
)
from titan.u8.shape_browser import (
    U8ShapeLibrary,
    find_u8_browser_file,
    load_u8_shape_library,
)
from titan.u8.shape_browser_ui import browse_u8_npc_shape, choose_u8_shape_target
from titan.u8.state_io import write_u8_state_report

PAGE_SIZE = 30


def _npc_menu(message: str, labels: dict[str, str], default: str | None = None) -> str:
    ui.legacy_menu(message, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ",
        list(labels),
        default or next(iter(labels)),
        labels=labels,
        message=message,
        hotkeys=True,
    )


def _npc_path(message: str, default: str = "") -> Path:
    raw = ui.path(f"  {message}: ", default).strip().strip('"')
    return Path(raw or default).expanduser()


def _npc_optional_number(message: str, current: int | None, maximum: int) -> int | None:
    while True:
        raw = ui.text(
            f"  {message}; blank clears: ", "" if current is None else str(current)
        ).strip()
        if not raw:
            return None
        try:
            value = int(raw, 16 if raw.lower().startswith("0x") else 10)
            if 0 <= value <= maximum:
                return value
        except ValueError:
            pass
        print(f"  Enter 0-{maximum}, or blank.")


def _choose_npc_source(library: U8ShapeLibrary) -> Path | None:
    gamedats, saves = discover_u8_npc_sources(library.path.parent)
    choices = [("GAMEDAT", path) for path in gamedats] + [
        ("Save", path) for path in saves
    ]
    page = 0
    while True:
        labels = {
            str(index + 1): f"{kind}: {path}"
            for index, (kind, path) in enumerate(choices)
            if page * PAGE_SIZE <= index < (page + 1) * PAGE_SIZE
        }
        if page:
            labels["B"] = "Previous sources"
        if (page + 1) * PAGE_SIZE < len(choices):
            labels["N"] = "Next sources"
        labels.update(
            {
                "C": "Other save, GAMEDAT or loose NPCDATA",
                "W": "Change graphics source",
                "Q": "Quit",
            }
        )
        selected = _npc_menu("Choose NPC snapshot:", labels)
        if selected == "Q":
            raise ui.PromptCancelled
        if selected == "W":
            return None
        if selected == "C":
            return _npc_path("Native save, GAMEDAT directory or NPCDATA.DAT")
        if selected in {"N", "B"}:
            page += 1 if selected == "N" else -1
        else:
            return choices[int(selected) - 1][1]


def _choose_npc_record(
    session: U8NpcSession,
    filters: dict[str, Any],
    current: int | None,
    *,
    embedded: bool = False,
) -> dict[str, Any] | str:
    page = 0
    matches = filter_u8_npcs(session.states, **filters)
    ids = [state["npc_id"] for state in matches]
    if current in ids:
        page = ids.index(current) // PAGE_SIZE
    while True:
        matches = filter_u8_npcs(session.states, **filters)
        pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages - 1)
        labels = {
            str(
                state["npc_id"]
            ): f"{state['npc_label']} — shape {state['item_shape']}, map {state['item_map']} [{state['slot_membership']}]"
            for state in matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        }
        if page:
            labels["B"] = "Previous NPC page"
        if page + 1 < pages:
            labels["N"] = "Next NPC page"
        labels.update(
            {
                "S": "Search ID/name/class",
                "F": "Filters",
                "E": "Export list/reports",
                "O": "Source overview",
                "D": "Choose another snapshot",
                "W": "Change graphics source",
                "Q": "Quit",
            }
        )
        if embedded:
            labels.pop("D")
            labels.pop("W")
            labels["Q"] = "Back to parent browser"
        selected = _npc_menu(
            f"NPCs — {len(matches)} matches; page {page + 1}/{pages}; {filters}:",
            labels,
            str(current) if str(current) in labels else None,
        )
        if selected == "S":
            filters["query"] = ui.text(
                "  NPC ID, character name or class label; blank lists all: "
            ).strip()
            page = 0
        elif selected == "F":
            _npc_filters(filters)
            page = 0
        elif selected in {"B", "N"}:
            page += 1 if selected == "N" else -1
        elif selected == "O":
            print(describe_u8_npc_source_overview(session))
        elif selected == "E":
            return "E"
        elif selected in {"D", "W", "Q"}:
            return selected
        else:
            return session.states[int(selected)]


def _npc_filters(filters: dict[str, Any]) -> None:
    while True:
        selected = _npc_menu(
            "NPC filters:",
            {
                "A": f"Allocation/life state: {filters['mode']}",
                "M": f"Stored map: {filters['map_num']}",
                "S": f"Sprite shape: {filters['shape']}",
                "R": "Reset filters and search",
                "B": "Back",
            },
            "B",
        )
        if selected == "B":
            return
        if selected == "A":
            filters["mode"] = _npc_menu(
                "Allocation/life state:",
                {
                    key: key.title()
                    for key in ("allocated", "alive", "dead", "unused", "all")
                },
                filters["mode"],
            )
        elif selected == "M":
            filters["map_num"] = _npc_optional_number(
                "Stored map ID", filters["map_num"], 255
            )
        elif selected == "S":
            filters["shape"] = _npc_optional_number(
                "Sprite shape ID", filters["shape"], 65535
            )
        elif selected == "R":
            filters.update(query="", mode="allocated", map_num=None, shape=None)


def preview_u8_npc_sprite(session: U8NpcSession, state: dict[str, Any]) -> None:
    """Show the stored full NPC frame and item flip; redirected output skips artwork."""
    if not ui.menus_enabled():
        return
    _preview_npc_item(
        session, state["item_shape"], state["item_frame"], state["item_status"]
    )


def _preview_npc_item(
    session: U8NpcSession, shape: int, frame: int, status: int
) -> None:
    if not ui.menus_enabled():
        return
    try:
        image = session.library.image(shape, frame)
        if status & 0x20:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        terminal_image(
            image, reserved_rows=18, pixel_mode="solid-native", max_width_fraction=1.0
        )
    except (ValueError, OSError) as error:
        print(f"  Artwork unavailable: {error}")


def _npc_equipment(session: U8NpcSession, state: dict[str, Any]) -> None:
    rows = describe_u8_npc_equipment(session, state)
    while True:
        labels = {
            str(row["slot"]): f"Slot {row['slot']}: item {row['item_id']}"
            + (
                f" — shape {row['item']['shape']} {row.get('class_label', '')}"
                if row.get("item")
                else " — empty/unavailable"
            )
            + (f" [{row['issue']}]" if row.get("issue") else "")
            for row in rows
        }
        labels["B"] = "Back to NPC"
        selected = _npc_menu(
            f"{state['npc_label']} — numbered equipment slots:", labels, "B"
        )
        if selected == "B":
            return
        row = rows[int(selected)]
        print(json.dumps(row, indent=2))
        if row.get("item") is not None:
            item = row["item"]
            _preview_npc_item(session, item["shape"], row["frame"], item["status"])
        _npc_menu("Equipment details:", {"B": "Back to equipment"}, "B")


def _next_npc_export(output: Path, stem: str, suffix: str = "") -> Path:
    number = 1
    path = output / f"{stem}{suffix}"
    while path.exists():
        number += 1
        path = output / f"{stem}_{number:03d}{suffix}"
    return path


def _npc_exports(
    session: U8NpcSession,
    states: list[dict[str, Any]],
    state: dict[str, Any] | None,
    output: Path,
) -> None:
    labels = {
        "C": "Current list with NPC names (.csv)",
        "M": "All allocated NPCs: HTML, master CSV and sheets",
        "B": "Back",
    }
    if state is not None:
        labels.update(
            {
                "J": "This NPC's complete state (.json)",
                "H": "This NPC: HTML, CSV and contact sheets",
            }
        )
    while True:
        selected = _npc_menu("Export NPC data:", labels, "B")
        if selected == "B":
            return
        try:
            if selected == "C":
                write_u8_state_report(
                    format_u8_npc_browser_summary(states),
                    _next_npc_export(output, "npc_list", ".csv"),
                    session.source_files,
                    "NPC list",
                )
            elif selected == "J" and state is not None:
                write_u8_state_report(
                    json.dumps(state, indent=2),
                    _next_npc_export(output, f"npc_{state['npc_id']:03d}", ".json"),
                    session.source_files,
                    "NPC state",
                )
            else:
                npc_id = (
                    state["npc_id"] if selected == "H" and state is not None else None
                )
                path = _next_npc_export(
                    output,
                    f"npc_{npc_id:03d}_report"
                    if npc_id is not None
                    else "all_npcs_report",
                )
                manifest = export_u8_npc_animation_report(
                    session.library,
                    session.source.npcs,
                    session.source.cache,
                    path,
                    sources=session.source_files,
                    labels=session.labels,
                    avatar=session.source.avatar,
                    npc_id=npc_id,
                    progress=print,
                )
                print(
                    f"  Saved {manifest['npc_count']} named NPC reports; open {path / 'index.html'}"
                )
        except (ValueError, OSError) as error:
            print(f"  Export failed: {error}")


def _browse_npc_session(
    session: U8NpcSession, npc: int | None, output: Path, *, embedded: bool = False
) -> str:
    filters: dict[str, Any] = {
        "query": "",
        "mode": "allocated",
        "map_num": None,
        "shape": None,
    }
    current = session.states[npc] if npc is not None else None
    inventory = None
    gump_number = 0
    if current is not None and not u8_npc_is_allocated(current):
        filters["mode"] = "all"
    while True:
        if current is None:
            picked = _choose_npc_record(session, filters, npc, embedded=embedded)
            if isinstance(picked, str):
                if picked == "E":
                    _npc_exports(
                        session, filter_u8_npcs(session.states, **filters), None, output
                    )
                    continue
                return picked
            current = picked
        npc = current["npc_id"]
        print(
            f"\n  NPC {npc}: {current['npc_label']} — shape {current['item_shape']}; sprite frame {current['item_frame']}"
        )
        print(
            f"  NPC usecode: {current['npc_usecode_class']} {current['npc_usecode_name']}; name source: {current['label_source']}"
        )
        print(
            f"  Map {current['item_map']}; stored position ({current['item_x']}, {current['item_y']}, {current['item_z']}); {current['slot_membership']}"
        )
        print(
            f"  STR {current['strength']} DEX {current['dexterity']} INT {current['intelligence']} HP {current['hitpoints']} MANA {current['mana']}"
        )
        print(
            f"  Flags: {', '.join(current['flag_names']) or '(none)'}; saved action/direction/step: {current['last_action']}/{current['direction']}/{current['animation_step']}"
        )
        preview_u8_npc_sprite(session, current)
        matches = filter_u8_npcs(session.states, **filters)
        ids = [state["npc_id"] for state in matches]
        labels = {
            "S": "NPC selection/search",
            "F": "Filters",
            "I": "Equipment item details",
            "A": "Sprite frames / animation actions",
            "T": "Complete saved state",
            "E": "Export NPC data/reports",
            "O": "Source overview",
            "D": "Choose another snapshot",
            "W": "Change graphics source",
            "Q": "Quit",
        }
        if u8_npc_is_allocated(current):
            labels["G"] = "Preview inventory gump with contents"
            labels["C"] = "Browse inventory and nested containers"
        if embedded:
            labels.pop("D")
            labels.pop("W")
            labels["Q"] = "Back to parent browser"
        if npc in ids and len(ids) > 1:
            index = ids.index(npc)
            following, previous = (
                matches[(index + 1) % len(matches)],
                matches[(index - 1) % len(matches)],
            )
            labels.update(
                N=f"Next: NPC {following['npc_id']} {following['npc_label']}",
                B=f"Previous: NPC {previous['npc_id']} {previous['npc_label']}",
            )
        selected = _npc_menu("NPC details:", labels, "S")
        if selected in {"Q", "D", "W"}:
            return selected
        if selected in {"N", "B"}:
            current = following if selected == "N" else previous
        elif selected in {"S", "F"}:
            if selected == "F":
                _npc_filters(filters)
            current = None
        elif selected == "T":
            print(json.dumps(current, indent=2))
        elif selected == "I":
            _npc_equipment(session, current)
        elif selected == "O":
            print(describe_u8_npc_source_overview(session))
        elif selected == "E":
            _npc_exports(session, matches, current, output)
        elif selected == "A":
            try:
                browse_u8_npc_shape(
                    session.library,
                    current["item_shape"],
                    frame=current["item_frame"],
                    output=output,
                )
            except (ValueError, OSError) as error:
                print(f"  Sprite/animation view unavailable: {error}")
        elif selected in {"G", "C"}:
            # Local imports keep NPC and container menus composable in either direction.
            from titan.u8.container_browser_ui import (
                browse_u8_container_inventory,
                preview_u8_container_gump,
            )
            from titan.u8.npc_inventory import load_u8_npc_inventory

            try:
                if inventory is None:
                    inventory = load_u8_npc_inventory(session)
                if selected == "G":
                    preview_u8_container_gump(
                        inventory, npc, output / "inventory_previews", seed=gump_number
                    )
                    gump_number += 1
                else:
                    browse_u8_container_inventory(
                        inventory,
                        npc,
                        output=output / "inventory_reports",
                        back_label="Back to NPC",
                    )
            except (ValueError, OSError, IndexError, KeyError) as error:
                print(f"  Inventory/gump view unavailable: {error}")


def browse_u8_npc_session(
    session: U8NpcSession,
    *,
    npc: int | None = None,
    output: Path = U8_NPC_BROWSER_OUTPUT,
) -> None:
    """Embed NPC browsing in a captured save snapshot; Q returns to its parent."""
    if npc is not None and not 0 <= npc <= 255:
        raise ValueError("U8 NPC browser: NPC ID must be 0-255")
    _browse_npc_session(session, npc, output, embedded=True)


def run_u8_npc_browser(
    *,
    source: Path | None = None,
    game_dir: Path | None = None,
    shapes: Path | None = None,
    palette: Path | None = None,
    anim: Path | None = None,
    itemcach: Path | None = None,
    npc: int | None = None,
    names: Path | None = None,
    output: Path = U8_NPC_BROWSER_OUTPUT,
) -> int:
    """Browse native NPC snapshots using shared prompts; redirected input uses line menus."""
    print("\nTitan U8 NPC Browser")
    try:
        if npc is not None and not 0 <= npc <= 255:
            raise ValueError("U8 NPC browser: NPC ID must be 0-255")
        configured_shapes = cfg("u8shapes")
        initial_shapes = shapes or (
            Path(configured_shapes) if configured_shapes else None
        )
        library = None
        while True:
            if library is None:
                path = initial_shapes
                initial_shapes = None
                if path is None:
                    target = choose_u8_shape_target(game_dir)
                    if target is None:
                        return 0
                    path = find_u8_browser_file(target.static, "U8SHAPES.FLX")
                    if path is None:
                        print("  U8SHAPES.FLX not found in selected graphics source.")
                        continue
                try:
                    library = load_u8_shape_library(path, palette=palette, anim=anim)
                    print(f"  Graphics: {library.path}")
                    for issue in library.diagnostics:
                        print(f"  Metadata unavailable: {issue}")
                except (ValueError, OSError) as error:
                    print(f"  Cannot open graphics: {error}")
                    if (
                        _npc_menu(
                            "Graphics source:",
                            {"C": "Choose another U8SHAPES.FLX", "Q": "Quit"},
                            "Q",
                        )
                        == "Q"
                    ):
                        return 1
                    initial_shapes = _npc_path("U8SHAPES.FLX")
                    palette, anim = None, None
                    continue
            path = source or _choose_npc_source(library)
            source = None
            if path is None:
                library = None
                palette, anim, itemcach, npc = None, None, None, None
                continue
            try:
                session = load_u8_npc_session(
                    path, library, itemcach=itemcach, names=names
                )
            except (ValueError, OSError) as error:
                print(f"  Cannot open NPC snapshot: {error}")
                if (
                    _npc_menu(
                        "NPC source:",
                        {"D": "Choose another snapshot", "Q": "Quit"},
                        "D",
                    )
                    == "Q"
                ):
                    return 1
                itemcach, npc = None, None
                continue
            print(
                f"  Snapshot: {session.source.path}; {len(filter_u8_npcs(session.states))} allocated NPCs"
            )
            for issue in (
                session.source.diagnostics + session.source.cache.list_diagnostics()
            ):
                print(f"  Data diagnostic: {issue}")
            selected = _browse_npc_session(session, npc, output)
            itemcach, npc = None, None
            if selected == "Q":
                return 0
            if selected == "W":
                library = None
                palette, anim = None, None
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {error}")
        return 1


def npc_browse_cmd(
    source: Annotated[
        Path | None,
        typer.Argument(
            help="Initial native save, GAMEDAT or loose NPCDATA; otherwise choose interactively"
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
        typer.Option(
            "--shapes",
            help="Matching U8SHAPES.FLX; otherwise configured/selected graphics",
        ),
    ] = None,
    palette: Annotated[
        Path | None,
        typer.Option(
            "-p", "--palette", help="Matching U8PAL.PAL; otherwise shapes owner"
        ),
    ] = None,
    anim: Annotated[
        Path | None, typer.Option("--anim", help="Explicit matching ANIM.DAT")
    ] = None,
    itemcach: Annotated[
        Path | None,
        typer.Option(
            "--itemcach",
            help="Matching cache for initial loose NPCDATA; otherwise same snapshot",
        ),
    ] = None,
    npc: Annotated[
        int | None,
        typer.Option(
            "--npc",
            min=0,
            max=255,
            help="Open an exact native NPC slot, including unused data",
        ),
    ] = None,
    names: Annotated[
        Path | None,
        typer.Option(
            "--names",
            help="Optional npc_id,name CSV overrides; permanent NPC names otherwise use usecode classes",
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o", "--output", help="Export folder; existing files are preserved"
        ),
    ] = U8_NPC_BROWSER_OUTPUT,
) -> None:
    """Browse U8 NPC names/state, equipment, sprite animations and report exports."""
    raise SystemExit(
        run_u8_npc_browser(
            source=source,
            game_dir=game_dir,
            shapes=shapes,
            palette=palette,
            anim=anim,
            itemcach=itemcach,
            npc=npc,
            names=names,
            output=output,
        )
    )


def register_u8_npc_browser(app: typer.Typer) -> None:
    """Register the flat npc-browse command without importing the parent CLI."""
    app.command("npc-browse")(npc_browse_cmd)
