"""Interactive native U8 save snapshots with shared menus and embedded NPC views."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer

from titan import _wizard_ui as ui
from titan.u8.flags import U8FlagSymbols
from titan.u8.npc_browser import U8NpcSession, discover_u8_npc_sources
from titan.u8.npc_browser_ui import browse_u8_npc_session
from titan.u8.npc_names import load_u8_npc_labels
from titan.u8.npc_source import U8NpcSource
from titan.u8.save_browser import (
    U8_SAVE_BROWSER_OUTPUT,
    U8_SAVE_BROWSER_VIEWS,
    describe_u8_save_browser_view,
    export_u8_save_browser_bundle,
    extract_u8_save_browser_entry,
    filter_u8_save_browser_rows,
    format_u8_save_browser_view,
    next_u8_save_browser_export,
    validate_u8_save_browser_output,
)
from titan.u8.save_diff import compare_u8_save_snapshots, format_u8_save_diff
from titan.u8.save_state import (
    U8SaveSnapshot,
    describe_u8_save_snapshot,
    format_u8_save_info,
)
from titan.u8.shape_browser import (
    U8ShapeLibrary,
    find_u8_browser_file,
    load_u8_shape_library,
)
from titan.u8.shape_browser_ui import browse_u8_npc_shape, choose_u8_shape_target
from titan.u8.state_io import write_u8_state_report

PAGE_SIZE = 25


@dataclass
class U8SaveBrowserSession:
    """Captured snapshot and optional comparison; graphics are loaded only on request."""

    snapshot: U8SaveSnapshot
    output: Path
    game_dir: Path | None = None
    shapes: Path | None = None
    palette: Path | None = None
    anim: Path | None = None
    symbols: U8FlagSymbols | None = None
    names: dict[int, str] = field(default_factory=dict)
    extra_sources: tuple[Path, ...] = ()
    comparison: U8SaveSnapshot | None = None
    library: U8ShapeLibrary | None = None
    names_file: Path | None = None

    @property
    def sources(self) -> tuple[Path, ...]:
        return (
            self.snapshot.source_files
            + self.extra_sources
            + (self.comparison.source_files if self.comparison else ())
        )


def _menu(title: str, labels: dict[str, str], default: str = "B") -> str:
    ui.legacy_menu(title, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ",
        list(labels),
        default if default in labels else next(iter(labels)),
        labels=labels,
        message=title,
        hotkeys=True,
    )


def _path(title: str) -> Path:
    raw = ui.path(f"  {title}: ").strip().strip('"')
    if not raw:
        raise ValueError("U8 save browser: enter a path")
    return Path(raw).expanduser()


def _number(title: str, minimum: int, maximum: int, default: int = 0) -> int:
    while True:
        raw = ui.text(f"  {title}: ", str(default)).strip() or str(default)
        try:
            value = int(raw, 16 if raw.lower().startswith("0x") else 10)
            if minimum <= value <= maximum:
                return value
        except ValueError:
            pass
        print(f"  Enter {minimum}-{maximum} (decimal or hex).")


def choose_u8_save_browser_source(
    game_dir: Path | None, *, comparison: bool = False
) -> Path | None:
    """Choose this installation's native saves/GAMEDAT, or an explicit other source."""
    from titan.u8.shape_browser import discover_u8_shape_targets

    targets = discover_u8_shape_targets(game_dir)
    choices: list[Path] = []
    for target in targets:
        gamedats, saves = discover_u8_npc_sources(target.static)
        choices.extend((*gamedats, *saves))
    choices = list(dict.fromkeys(choices))
    page = 0
    while True:
        labels = {
            str(index + 1): str(path)
            for index, path in enumerate(choices)
            if page * PAGE_SIZE <= index < (page + 1) * PAGE_SIZE
        }
        if page:
            labels["B"] = "Previous sources"
        if (page + 1) * PAGE_SIZE < len(choices):
            labels["N"] = "Next sources"
        labels.update(
            {
                "C": "Other native save or GAMEDAT folder",
                "W": "Choose installation folder",
                "Q": "Cancel comparison" if comparison else "Quit",
            }
        )
        selected = _menu(
            "Choose comparison snapshot:" if comparison else "Choose save snapshot:",
            labels,
            "1",
        )
        if selected == "Q":
            return None
        if selected == "C":
            return _path("Native U8SAVE or GAMEDAT folder")
        if selected == "W":
            return choose_u8_save_browser_source(
                _path("U8 installation/language/STATIC folder"), comparison=comparison
            )
        if selected in {"B", "N"}:
            page += 1 if selected == "N" else -1
        else:
            return choices[int(selected) - 1]


def _validate_output(session: U8SaveBrowserSession, path: Path) -> None:
    validate_u8_save_browser_output(session.snapshot, path, session.sources)
    if session.comparison is not None:
        validate_u8_save_browser_output(session.comparison, path, session.sources)


def _export(
    session: U8SaveBrowserSession, report: dict[str, Any], output_format: str, stem: str
) -> Path:
    path = next_u8_save_browser_export(
        session.output, stem, ".txt" if output_format == "text" else f".{output_format}"
    )
    _validate_output(session, path)
    write_u8_state_report(
        format_u8_save_browser_view(report, output_format),
        path,
        session.sources,
        "Save browser",
    )
    return path


def _graphics(session: U8SaveBrowserSession) -> U8ShapeLibrary:
    if session.library is None:
        path = session.shapes
        if path is None:
            target = choose_u8_shape_target(session.game_dir)
            if target is None:
                raise ValueError("U8 save browser: graphics selection cancelled")
            path = find_u8_browser_file(target.static, "U8SHAPES.FLX")
        if path is None:
            raise ValueError("U8 save browser: U8SHAPES.FLX not found")
        session.library = load_u8_shape_library(
            path, palette=session.palette, anim=session.anim
        )
    return session.library


def _npcs(session: U8SaveBrowserSession, npc: int | None = None) -> None:
    snapshot = session.snapshot
    if snapshot.npc_data is None or snapshot.item_cache is None:
        raise ValueError(
            "U8 save browser: NPC artwork needs valid NPCDATA and ITEMCACH from this snapshot"
        )
    library = _graphics(session)
    states = describe_u8_save_browser_view(
        snapshot, "npcs", all_slots=True, names=session.names
    )["rows"]
    for state in states:
        state["class_label"] = library.names.get(state["item_shape"], "")
    source = U8NpcSource(
        snapshot.source,
        snapshot.npc_data,
        snapshot.item_cache,
        snapshot.source_files,
        snapshot.avatar,
    )
    npc_session = U8NpcSession(
        source,
        library,
        states,
        session.names,
        session.names_file,
        format_u8_save_info(snapshot),
        snapshot,
    )
    _validate_output(session, session.output)
    browse_u8_npc_session(npc_session, npc=npc, output=session.output)


def _row_label(view: str, row: dict[str, Any], index: int) -> str:
    if view == "entries":
        return f"{row['name']} — {row['size']:,} bytes [{row['decode_status']}]"
    keys = {
        "npcs": ("npc_id", "npc_label", "item_shape", "item_map", "slot_membership"),
        "items": ("item_id", "shape", "frame_low", "map_num_raw", "slot_membership"),
        "regions": ("rx", "ry", "head", "item_count"),
        "flags": ("name", "index", "width", "value"),
        "maps": ("map_id", "record_count", "world_count", "contained_count"),
        "map_items": (
            "record_index",
            "shape",
            "frame",
            "location_kind",
            "parent_record_index",
        ),
        "kernel": ("slot", "ref", "native_class", "process_type_hex", "decode_status"),
    }.get(view, tuple(list(row)[:4]))
    return (
        " · ".join(f"{key}: {row[key]}" for key in keys if key in row) or f"Row {index}"
    )


def _entry(session: U8SaveBrowserSession, row: dict[str, Any]) -> None:
    snapshot, name = session.snapshot, row["name"]
    data = snapshot.entries[name]
    offset = 0
    views = {
        "AVATAR.DAT": "avatar",
        "NPCDATA.DAT": "npcs",
        "ITEMCACH.DAT": "items",
        "FLAG.DAT": "flags",
        "NONFIXED.DAT": "maps",
        "GUMPS.DAT": "gumps",
        "KERNEL.DAT": "kernel",
    }
    while True:
        print(json.dumps(row, indent=2))
        labels = {
            "H": f"Hex bytes at offset {offset} (256-byte page)",
            "I": "Set byte offset",
            "X": "Extract captured entry",
            "B": "Back to entries",
        }
        if name in views and name not in snapshot.decode_errors:
            labels["D"] = "Browse decoded state"
        selected = _menu(f"Entry {name}:", labels)
        if selected == "B":
            return
        if selected == "H":
            for start in range(offset, min(offset + 256, len(data)), 16):
                block = data[start : start + 16]
                printable = "".join(
                    chr(value) if 32 <= value < 127 else "." for value in block
                )
                print(f"{start:08X}  {block.hex(' '):47}  {printable}")
            offset = min(offset + 256, max(0, len(data) - 1))
        elif selected == "I":
            offset = _number("Byte offset", 0, max(0, len(data) - 1))
        elif selected == "X":
            _validate_output(session, session.output)
            print(
                f"  Extracted: {extract_u8_save_browser_entry(snapshot, name, session.output)}"
            )
        else:
            _browse_view(session, views[name])


def _row_details(
    session: U8SaveBrowserSession, report: dict[str, Any], row: dict[str, Any]
) -> None:
    view = report["view"]
    if view == "entries":
        _entry(session, row)
        return
    while True:
        print(json.dumps(row, indent=2))
        labels = {"J": "Export this record (.json)", "B": "Back to rows"}
        if view == "maps":
            labels["D"] = "Browse stored records for this map"
        if view == "kernel":
            labels["D"] = "Decoded process and raw object/payload"
        if view == "npcs" and session.snapshot.item_cache is not None:
            labels["N"] = "NPC artwork, equipment and animations"
        shape = row.get("item_shape") if view == "npcs" else row.get("shape")
        if shape:
            labels["S"] = "Browse this shape's frames/animations"
        selected = _menu("Record details:", labels)
        if selected == "B":
            return
        if selected == "J":
            _export(session, {**report, "rows": [row]}, "json", f"{view}_record")
        elif selected == "N":
            _npcs(session, row["npc_id"])
        elif selected == "S":
            if shape is None:
                raise ValueError("U8 save browser: no shape in this record")
            _validate_output(session, session.output)
            frame = (
                row.get("item_frame")
                if view == "npcs"
                else row.get("frame", row.get("frame_low", 0))
            )
            if (
                view == "items"
                and row["item_id"] < 256
                and session.snapshot.npc_data is not None
            ):
                frame = session.snapshot.npc_data.get_npc(row["item_id"]).full_frame(
                    row["frame_low"]
                )
            browse_u8_npc_shape(
                _graphics(session), shape, frame=frame or 0, output=session.output
            )
        elif view == "maps":
            _browse_view(session, "map_items", map_id=row["map_id"])
        else:
            _browse_view(session, "process", slot=row["slot"])


def _browse_view(session: U8SaveBrowserSession, view: str, **selection: Any) -> None:
    report = describe_u8_save_browser_view(
        session.snapshot,
        view,
        symbols=session.symbols,
        names=session.names,
        **selection,
    )
    query, page = "", 0
    while True:
        rows = filter_u8_save_browser_rows(report["rows"], query)
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages - 1)
        labels = {
            str(index): _row_label(view, row, index)
            for index, row in enumerate(rows)
            if page * PAGE_SIZE <= index < (page + 1) * PAGE_SIZE
        }
        labels.update(
            {
                "F": "Search display fields",
                "O": "View metadata and coverage",
                "J": "Export matching rows (.json)",
                "C": "Export matching rows (.csv)",
                "T": "Export matching rows (.txt)",
                "Q": "Back to save",
            }
        )
        if page:
            labels["B"] = "Previous page"
        if page + 1 < pages:
            labels["N"] = "Next page"
        if view in {"flags", "npcs", "items", "regions", "maps"}:
            labels["A"] = "Toggle all slots/bits (clears packed flag selection)"
        if view == "flags":
            labels["I"] = "Inspect a packed flag field by index/width"
        selected = _menu(
            f"{U8_SAVE_BROWSER_VIEWS[view]} — {len(rows)} matches; page {page + 1}/{pages}:",
            labels,
            "Q",
        )
        try:
            if selected == "Q":
                return
            if selected in {"N", "B"}:
                page += 1 if selected == "N" else -1
            elif selected == "F":
                query, page = ui.text("  Search; blank clears: ").strip(), 0
            elif selected == "O":
                print(json.dumps(report["metadata"], indent=2))
            elif selected in {"J", "C", "T"}:
                _export(
                    session,
                    {**report, "rows": rows, "query": query},
                    {"J": "json", "C": "csv", "T": "text"}[selected],
                    view,
                )
            elif selected in {"A", "I"}:
                if selected == "I":
                    index = _number("Bit index", 0, 8191)
                    selection.update(
                        index=index,
                        width=_number("Field width", 1, min(16, 8192 - index), 1),
                        all_slots=False,
                    )
                else:
                    selection.update(all_slots=not selection.get("all_slots", False))
                    selection.pop("index", None)
                    selection.pop("width", None)
                report = describe_u8_save_browser_view(
                    session.snapshot,
                    view,
                    symbols=None if selection.get("all_slots") else session.symbols,
                    names=session.names,
                    **selection,
                )
                query, page = "", 0
            else:
                _row_details(session, report, rows[int(selected)])
        except (ValueError, OSError) as error:
            print(f"  View/export unavailable: {error}")


def _compare(session: U8SaveBrowserSession) -> None:
    report = None
    while True:
        if session.comparison is None:
            path = choose_u8_save_browser_source(session.game_dir, comparison=True)
            if path is None:
                return
            session.comparison = U8SaveSnapshot.from_path(path)
        if report is None:
            report = compare_u8_save_snapshots(
                session.snapshot, session.comparison, symbols=session.symbols
            )
        print(
            f"\n  Before: {session.snapshot.source}\n  After: {session.comparison.source}\n  Changed entries: {report['changed_entry_count']}"
        )
        for name, section in report["sections"].items():
            print(
                f"  {name}: {section['total_count']} rows; {section['omitted_count']} omitted"
            )
        selected = _menu(
            "Compare snapshots:",
            {
                "O": "Full comparison text and coverage",
                "S": "Inspect a comparison section",
                "J": "Export all comparison rows (.json)",
                "T": "Export all comparison rows (.txt)",
                "D": "Different comparison snapshot",
                "B": "Back to save",
            },
        )
        if selected == "B":
            return
        if selected == "D":
            session.comparison = None
            report = None
        elif selected == "O":
            print(
                format_u8_save_diff(
                    session.snapshot, session.comparison, symbols=session.symbols
                )
            )
        elif selected == "S":
            sections = list(report["sections"])
            labels = {
                str(index): f"{name}: {report['sections'][name]['total_count']} rows"
                for index, name in enumerate(sections)
            }
            labels["B"] = "Back"
            choice = _menu("Comparison sections:", labels)
            if choice != "B":
                section = report["sections"][sections[int(choice)]]
                print(json.dumps(section, indent=2))
        else:
            kind = "json" if selected == "J" else "text"
            path = next_u8_save_browser_export(
                session.output, "save_diff", ".json" if kind == "json" else ".txt"
            )
            validate_u8_save_browser_output(session.snapshot, path, session.sources)
            validate_u8_save_browser_output(session.comparison, path, session.sources)
            write_u8_state_report(
                format_u8_save_diff(
                    session.snapshot,
                    session.comparison,
                    symbols=session.symbols,
                    limit=0,
                    output_format=kind,
                ),
                path,
                session.sources,
                "Save comparison",
            )


def _browse_snapshot(session: U8SaveBrowserSession) -> str:
    overview = describe_u8_save_snapshot(session.snapshot)
    while True:
        print(
            f"\n  Snapshot: {session.snapshot.source}\n  {overview['entry_count']} entries; {overview['payload_bytes']:,} payload bytes; {len(session.snapshot.decode_errors)} decode errors"
        )
        if session.snapshot.avatar is not None:
            print(f"  Avatar: {session.snapshot.avatar.name}")
        if session.snapshot.item_cache is not None:
            print(
                f"  Cache map: {session.snapshot.item_cache.metadata.map_in}; NPCs: {overview.get('npcs', {}).get('present_count', 'unavailable')}"
            )
        labels = {
            "O": "Complete save overview",
            "F": "Entries, hex inspection and extraction",
            "A": "Avatar extension state",
            "N": "Named NPC state",
            "P": "NPC artwork/equipment/animations",
            "I": "Cached items",
            "R": "Cache regions",
            "G": "Global flags / packed fields",
            "M": "Stored NONFIXED maps",
            "U": "Container gumps",
            "V": "Gump rectangles",
            "K": "Kernel processes",
            "C": "Compare with another snapshot",
            "E": "Export offline overview and data bundle",
            "D": "Choose another save snapshot",
            "W": "Change graphics source",
            "Q": "Quit",
        }
        selected = _menu("Save actions:", labels, "F")
        if selected in {"Q", "D"}:
            return selected
        try:
            if selected == "O":
                print(format_u8_save_info(session.snapshot))
            elif selected == "P":
                _npcs(session)
            elif selected == "C":
                _compare(session)
            elif selected == "E":
                path = next_u8_save_browser_export(session.output, "save_report")
                if session.comparison:
                    validate_u8_save_browser_output(
                        session.comparison, path, session.sources
                    )
                result = export_u8_save_browser_bundle(
                    session.snapshot,
                    path,
                    symbols=session.symbols,
                    names=session.names,
                    sources=session.sources,
                )
                print(
                    f"  Saved {result['file_count']} files; open {path / 'index.html'}"
                )
            elif selected == "W":
                session.library, session.shapes, session.palette, session.anim = (
                    None,
                    None,
                    None,
                    None,
                )
                _graphics(session)
            else:
                _browse_view(
                    session,
                    {
                        "F": "entries",
                        "A": "avatar",
                        "N": "npcs",
                        "I": "items",
                        "R": "regions",
                        "G": "flags",
                        "M": "maps",
                        "U": "gumps",
                        "V": "rects",
                        "K": "kernel",
                    }[selected],
                )
        except (ValueError, OSError) as error:
            print(f"  View/export unavailable: {error}")


def run_u8_save_browser(
    *,
    source: Path | None = None,
    game_dir: Path | None = None,
    compare: Path | None = None,
    shapes: Path | None = None,
    palette: Path | None = None,
    anim: Path | None = None,
    symbols: Path | None = None,
    names: Path | None = None,
    output: Path = U8_SAVE_BROWSER_OUTPUT,
) -> int:
    """Browse native saves/GAMEDAT; redirected input uses shared line-menu fallback."""
    print("\nTitan U8 Save Browser")
    try:
        flag_symbols = U8FlagSymbols.from_file(symbols) if symbols else None
        labels = load_u8_npc_labels(names) if names else {}
        extra_sources = tuple(path for path in (symbols, names) if path is not None)
        comparison = U8SaveSnapshot.from_path(compare) if compare else None
        while True:
            path = source or choose_u8_save_browser_source(game_dir)
            source = None
            if path is None:
                return 0
            try:
                snapshot = U8SaveSnapshot.from_path(path)
            except (ValueError, OSError) as error:
                print(f"  Cannot open save snapshot: {error}")
                if (
                    _menu(
                        "Save source:",
                        {"D": "Choose another snapshot", "Q": "Quit"},
                        "Q",
                    )
                    == "Q"
                ):
                    return 1
                continue
            session = U8SaveBrowserSession(
                snapshot,
                output,
                game_dir,
                shapes,
                palette,
                anim,
                flag_symbols,
                labels,
                extra_sources,
                comparison,
            )
            session.names_file = names
            if _browse_snapshot(session) == "Q":
                return 0
            # A new primary snapshot never silently inherits the previous comparison.
            comparison = None
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {error}")
        return 1


def save_browse_cmd(
    source: Annotated[
        Path | None,
        typer.Argument(
            help="Initial native U8SAVE or GAMEDAT folder; otherwise choose interactively"
        ),
    ] = None,
    game_dir: Annotated[
        Path | None,
        typer.Option(
            "--game-dir",
            help="U8 installation/language/STATIC folder for save discovery and graphics",
        ),
    ] = None,
    compare: Annotated[
        Path | None,
        typer.Option(
            "--compare",
            help="Initial comparison native save or GAMEDAT; selected save is the before snapshot",
        ),
    ] = None,
    shapes: Annotated[
        Path | None,
        typer.Option(
            "--shapes", help="Matching U8SHAPES.FLX for optional NPC/shape artwork"
        ),
    ] = None,
    palette: Annotated[
        Path | None,
        typer.Option(
            "-p", "--palette", help="Matching U8PAL.PAL; otherwise shapes owner"
        ),
    ] = None,
    anim: Annotated[
        Path | None,
        typer.Option(
            "--anim", help="Matching ANIM.DAT for optional animation browsing"
        ),
    ] = None,
    symbols: Annotated[
        Path | None,
        typer.Option(
            "--symbols",
            help="Optional native FLAGSYM.DAT with verified offsets and widths",
        ),
    ] = None,
    names: Annotated[
        Path | None,
        typer.Option(
            "--names", help="Optional npc_id,name CSV overrides for native NPC names"
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o", "--output", help="Export folder; existing files are preserved"
        ),
    ] = U8_SAVE_BROWSER_OUTPUT,
) -> None:
    """Browse native save entries/state, NPCs, flags, maps, kernel and comparisons."""
    raise SystemExit(
        run_u8_save_browser(
            source=source,
            game_dir=game_dir,
            compare=compare,
            shapes=shapes,
            palette=palette,
            anim=anim,
            symbols=symbols,
            names=names,
            output=output,
        )
    )


def register_u8_save_browser(app: typer.Typer) -> None:
    """Register save-browse without importing the parent CLI."""
    app.command("save-browse")(save_browse_cmd)
