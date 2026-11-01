"""Native U9 save browser using Titan's shared Questionary/line menus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from titan import _wizard_ui as ui
from titan.u9.integrity import render_integrity_report
from titan.u9.save_backup import (
    backup_u9_save,
    next_u9_save_output,
    validate_u9_save_output,
)
from titan.u9.save_browser import (
    U9_SAVE_BROWSER_OUTPUT,
    U9_SAVE_BROWSER_VIEWS,
    U9SaveBrowserSession,
    discover_u9_save_archives,
    describe_u9_save_browser_view,
    export_u9_save_browser_bundle,
    extract_u9_save_browser_archive,
    filter_u9_save_browser_rows,
    format_u9_save_browser_rows,
    open_u9_save_browser_session,
)
from titan.u9.save_wording import (
    clean_u9_browser_text,
    describe_u9_browser_map,
    describe_u9_save_integrity,
    load_u9_save_wording,
    render_u9_plain_integrity,
)

PAGE_SIZE = 25
ACTION_KEYS = {
    "backup": "B",
    "try_load": "L",
    "load_older_save": "V",
    "send_report": "S",
    "restore_install": "R",
    "reextract": "X",
    "choose_save": "D",
    "choose_reference": "C",
}


def _menu(title: str, labels: dict[str, str], default: str = "Q") -> str:
    ui.legacy_menu(title, *(f"  [{key}] {value}" for key, value in labels.items()))
    return ui.choice(
        "> ",
        list(labels),
        default if default in labels else next(iter(labels)),
        labels=labels,
        message=title,
        hotkeys=True,
    )


def _path(title: str) -> Path:
    value = ui.path(f"  {title}: ").strip().strip('"')
    if not value:
        raise ValueError("U9 save browser: enter a path")
    return Path(value).expanduser()


def choose_u9_save_browser_source(game_dir: Path | None) -> Path | None:
    """Choose this installation's archives, its working selection, or another source."""
    page = 0
    rows = discover_u9_save_archives(game_dir) if game_dir is not None else []
    while True:
        labels = {
            str(
                index + 1
            ): f"Slot {row['slot']} - {row['description']} - {row['map_name']}"
            + (" (current selection)" if row["selected"] else "")
            for index, row in enumerate(rows)
            if page * PAGE_SIZE <= index < (page + 1) * PAGE_SIZE
        }
        if game_dir is not None:
            labels["W"] = "Inspect current working selection"
        labels["C"] = "Other archive or installation folder"
        if page:
            labels["P"] = "Previous saves"
        if (page + 1) * PAGE_SIZE < len(rows):
            labels["N"] = "Next saves"
        labels["Q"] = "Quit"
        selected = _menu("Choose U9 save:", labels, next(iter(labels)))
        if selected == "Q":
            return None
        if selected == "W":
            return game_dir
        if selected == "C":
            return _path("Save archive or U9 installation/savegame folder")
        if selected in ("P", "N"):
            page += 1 if selected == "N" else -1
        else:
            row = rows[int(selected) - 1]
            return game_dir if row["selected"] else Path(row["path"])


def _row_label(view: str, row: dict[str, Any]) -> str:
    if view == "members":
        return f"{row['name']} - {row['bytes']} bytes"
    if view == "maps":
        return f"{row['display_name']} - {row['bytes']} bytes - {', '.join(row['findings']) or 'no map findings'}"
    if view == "npcs":
        return f"{row['npc_id']}: {row['name'] or 'Unnamed NPC'} - {row['map_name']}"
    return clean_u9_browser_text(json.dumps(row, ensure_ascii=False))[:180]


def _inspect_member(session: U9SaveBrowserSession, row: dict[str, Any]) -> None:
    if session.archive is None:
        return
    member = next(
        member
        for member in (
            session.archive.screenshot,
            session.archive.processes,
            session.archive.diary,
            *session.archive.nonfixed,
        )
        if member.name == row["name"]
    )
    while True:
        print(json.dumps(row, indent=2, ensure_ascii=False))
        selected = _menu(
            "Member details:",
            {"H": "Hex preview", "X": "Extract a separate copy", "Q": "Back"},
        )
        if selected == "Q":
            return
        if selected == "H":
            raw = ui.text("  Offset (decimal or 0x hex): ", "0").strip() or "0"
            offset = int(raw, 16 if raw.lower().startswith("0x") else 10)
            if not 0 <= offset <= len(member.data):
                raise ValueError("U9 save browser: offset is outside the member")
            for start in range(offset, min(offset + 256, len(member.data)), 16):
                print(f"  {start:08X}  {member.data[start : start + 16].hex(' ')}")
        else:
            validate_u9_save_output(
                session.output, session.save_directory, session.sources
            )
            filename = (
                "screenshot.bin"
                if member is session.archive.screenshot
                else member.name
            )
            target = next_u9_save_output(session.output, "member_" + filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(member.data)
            print(f"  Extracted: {target}")


def _browse_view(session: U9SaveBrowserSession, view: str) -> None:
    original = describe_u9_save_browser_view(session, view)
    query, page = "", 0
    while True:
        rows = filter_u9_save_browser_rows(original, query)
        page = min(page, max(0, (len(rows) - 1) // PAGE_SIZE))
        print(f"\n{U9_SAVE_BROWSER_VIEWS[view]} - {len(rows)} rows; page {page + 1}")
        labels = {
            str(index + 1): _row_label(view, row)
            for index, row in enumerate(rows)
            if page * PAGE_SIZE <= index < (page + 1) * PAGE_SIZE
        }
        labels.update(
            {
                "F": "Filter / search",
                "J": "Export all filtered rows as JSON",
                "C": "Export all filtered rows as CSV",
                "Q": "Back",
            }
        )
        if page:
            labels["P"] = "Previous page"
        if (page + 1) * PAGE_SIZE < len(rows):
            labels["N"] = "Next page"
        selected = _menu("View actions:", labels)
        if selected == "Q":
            return
        if selected == "F":
            query, page = ui.text("  Filter (blank clears): ", query), 0
        elif selected in ("P", "N"):
            page += 1 if selected == "N" else -1
        elif selected in ("J", "C"):
            kind = "json" if selected == "J" else "csv"
            validate_u9_save_output(
                session.output, session.save_directory, session.sources
            )
            path = next_u9_save_output(session.output, view, "." + kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(format_u9_save_browser_rows(rows, kind), encoding="utf-8")
            print(f"  Saved: {path}")
        elif view == "members":
            _inspect_member(session, rows[int(selected) - 1])
        else:
            print(json.dumps(rows[int(selected) - 1], indent=2, ensure_ascii=False))


def _browse_u9_save_session(session: U9SaveBrowserSession) -> str:
    while True:
        plain = describe_u9_save_integrity(session.report)
        print(f"\n  Source: {session.source}")
        if session.archive is not None:
            header = session.archive.header
            print(
                f"  Slot: {session.report.slot}; {clean_u9_browser_text(header.description)}"
            )
            print(
                f"  Place: {describe_u9_browser_map(header.header_map)['display_name']}; saved day {header.day}"
            )
        print("\n" + render_u9_plain_integrity(plain))
        if not session.report.no_save_selected:
            axes = plain["axes"]
            print(
                f"\n  Working files: {axes['custody']}; file structure: {axes['structure']}; map references: {axes['compatibility']}"
            )
        labels = {
            "O": "Save overview",
            "I": "Integrity summary",
            "T": "Details / technical report",
            "F": "Archive members and hex inspection",
            "M": "Saved maps",
            "A": "Named NPC state",
            "P": "Saved activities",
            "H": "Object-link details",
            "E": "Export offline report",
            "D": "Choose another save",
            "U": "Refresh checks",
            "Q": "Quit",
        }
        for action in plain["actions"]:
            if (
                action != "backup"
                or session.report.archive
                and Path(session.report.archive).is_file()
            ):
                labels[ACTION_KEYS[action]] = plain["action_labels"][action]
        selected = _menu("Save actions:", labels)
        if selected in ("Q", "D", "V"):
            return "Q" if selected == "Q" else "D"
        try:
            if selected == "T":
                print(render_integrity_report(session.report))
            elif selected in ("E", "S"):
                folder = export_u9_save_browser_bundle(session)
                print(f"  Saved complete report: {folder / 'index.html'}")
            elif selected == "B":
                validate_u9_save_output(
                    session.output, session.save_directory, session.sources
                )
                archive_path = session.report.archive
                if archive_path is None:
                    raise ValueError(
                        "U9 save browser: no archive is available to back up"
                    )
                folder = backup_u9_save(
                    Path(archive_path),
                    session.save_directory,
                    session.output,
                    slot=session.report.slot,
                )
                print(f"  Backup complete: {folder}")
            elif selected == "X":
                print(
                    f"  Extracted inspection copy: {extract_u9_save_browser_archive(session)}"
                )
            elif selected in ("L", "R"):
                action = "try_load" if selected == "L" else "restore_install"
                print("  " + load_u9_save_wording()["actions"][action]["description"])
            elif selected == "C":
                reference = _path("Trusted creation-time map directory")
                session = open_u9_save_browser_session(
                    session.source,
                    slot=session.requested_slot,
                    static_directory=session.static_directory,
                    fixed_reference_directory=reference,
                    output=session.output,
                )
            elif selected == "U":
                session = open_u9_save_browser_session(
                    session.source,
                    slot=session.requested_slot,
                    static_directory=session.static_directory,
                    fixed_reference_directory=session.fixed_reference_directory,
                    output=session.output,
                )
            elif selected == "O":
                print(
                    json.dumps(
                        session.report.artifacts.get("archive", {}),
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            elif selected != "I":
                _browse_view(
                    session,
                    {
                        "F": "members",
                        "M": "maps",
                        "A": "npcs",
                        "P": "processes",
                        "H": "references",
                    }[selected],
                )
        except (ValueError, OSError) as error:
            print(f"  View/action unavailable: {clean_u9_browser_text(error)}")


def run_u9_save_browser(
    *,
    source: Path | None = None,
    game_dir: Path | None = None,
    slot: int | None = None,
    static_directory: Path | None = None,
    fixed_reference_directory: Path | None = None,
    output: Path = U9_SAVE_BROWSER_OUTPUT,
    report_only: bool = False,
) -> int:
    """Browse without modifying saves; redirected input uses shared line menus."""
    if source is None and game_dir is None:
        from titan.u9.install import configured_u9_path

        game_dir = configured_u9_path("base")
        if game_dir is not None and static_directory is None:
            static_directory = configured_u9_path("static")
    print("\nTitan U9 Save Browser")
    try:
        if source is None and slot is not None:
            if game_dir is None:
                raise ValueError(
                    "U9 save browser: --slot needs a source folder or --game-dir"
                )
            source = game_dir
        if report_only and source is None:
            source = game_dir
            if source is None:
                raise ValueError(
                    "U9 save browser: --report needs a source or --game-dir"
                )
        while True:
            chosen = source or choose_u9_save_browser_source(game_dir)
            source = None
            if chosen is None:
                return 0
            session = open_u9_save_browser_session(
                chosen,
                slot=slot,
                static_directory=static_directory,
                fixed_reference_directory=fixed_reference_directory,
                output=output,
            )
            slot = None
            if report_only:
                print(
                    render_u9_plain_integrity(
                        describe_u9_save_integrity(session.report)
                    )
                )
                print(
                    f"\n  Offline report: {export_u9_save_browser_bundle(session) / 'index.html'}"
                )
                return 0
            game_dir = session.save_directory
            if _browse_u9_save_session(session) == "Q":
                return 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {clean_u9_browser_text(error)}")
        return 1


def save_browse_cmd(
    source: Annotated[
        Path | None,
        typer.Argument(help="Initial U9 archive or installation/savegame folder"),
    ] = None,
    game_dir: Annotated[
        Path | None,
        typer.Option(
            "--game-dir",
            help="Installation or savegame folder (default: [u9.game].base)",
        ),
    ] = None,
    slot: Annotated[
        int | None,
        typer.Option(
            "--slot", help="Check a folder's explicit working slot instead of start.dat"
        ),
    ] = None,
    static: Annotated[
        Path | None, typer.Option("--static", help="Installed fixed-map directory")
    ] = None,
    fixed_reference: Annotated[
        Path | None,
        typer.Option("--fixed-reference", help="Trusted creation-time map directory"),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o", "--output", help="Exports and backups; earlier files are preserved"
        ),
    ] = U9_SAVE_BROWSER_OUTPUT,
    report_only: Annotated[
        bool,
        typer.Option(
            "--report", help="Write an offline report without opening interactive menus"
        ),
    ] = False,
) -> None:
    """Browse U9 saves, plain integrity findings, maps, NPCs and separate backups."""
    raise SystemExit(
        run_u9_save_browser(
            source=source,
            game_dir=game_dir,
            slot=slot,
            static_directory=static,
            fixed_reference_directory=fixed_reference,
            output=output,
            report_only=report_only,
        )
    )


def register_u9_save_browser(app: typer.Typer) -> None:
    """Register save-browse alongside the read-only save-check command."""
    app.command("save-browse")(save_browse_cmd)
