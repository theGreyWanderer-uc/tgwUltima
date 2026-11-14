"""Interactive U7 monster browser menus, previews and exports."""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from titan import _wizard_ui as ui
from titan._terminal_image import play_terminal, terminal_image
from titan.u7 import npc_browser, npc_browser_ui
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.monster import live_monsters_csv
from titan.u7.save import U7NPCData
from titan.u7.shape_browser import ShapeLibrary, load_library, playback_provider
from titan.u7.target_picker import game_targets, select_target
from titan.u7.monster_browser import (
    IREG_NAME,
    MonsterEntry,
    READ_ERRORS,
    Session,
    _csv,
    clean,
    detail,
    equipment_lines,
    filter_entries,
    load_session,
    possible_equipment,
    spawn_rows,
)


PAGE_SIZE = npc_browser_ui.PAGE_SIZE
menu = npc_browser_ui._menu


def _library(session: Session) -> ShapeLibrary | None:
    if session.preview_library is None and session.preview_error is None:
        try:
            path = npc_browser.owner_file(session.target, "SHAPES.VGA")
            if path is None:
                raise ValueError("SHAPES.VGA not found for the selected world")
            session.preview_library = load_library(session.target, session.game, path)
        except READ_ERRORS as error:
            session.preview_error = str(error)
    if session.preview_library is None:
        print(
            f"  Monster preview unavailable: {clean(session.preview_error or 'missing artwork')}"
        )
    return session.preview_library


def preview(
    session: Session, entry: MonsterEntry, frame: int | None = None
) -> int | None:
    if not sys.stdout.isatty():
        return None
    library = _library(session)
    if library is None:
        return None
    try:
        shape = library.shape(entry.shape)
        if not shape.frames:
            raise ValueError(f"Shape {entry.shape} has no frames")
        # Consistent with NPC browsing, with an explicit frame-0 fallback for
        # creatures whose archive has no standing frame 16.
        selected = (
            (16 if len(shape.frames) > 16 else 0)
            if frame is None
            else frame % len(shape.frames)
        )
        print(f"  Monster shape preview: shape {entry.shape}, frame {selected}")
        terminal_image(library.images(shape, entry.shape)[selected], reserved_rows=20)
        return selected
    except READ_ERRORS as error:
        print(f"  Monster preview unavailable: {clean(str(error))}")
        return None


def _spawn_map(session: Session, entry: MonsterEntry) -> int:
    maps = {0, entry.actor.map_num if entry.actor else 0}
    if session.archive:
        for name in session.archive.entry_names():
            match = IREG_NAME.fullmatch(name.replace("\\", "/"))
            if match and match[1]:
                maps.add(int(match[1][3:], 16))
    else:
        root = (
            session.target.gamedat
            if session.source.kind == "definitions"
            else session.source.path
            if session.source.path.is_dir()
            else session.source.path.parent
        )
        if root and root.is_dir():
            for path in root.iterdir():
                if path.is_dir() and re.fullmatch(
                    r"map[0-9a-f]{2}", path.name, re.IGNORECASE
                ):
                    maps.add(int(path.name[3:], 16))
    default = entry.actor.map_num if entry.actor else 0
    return int(
        menu("Spawn egg map:", {str(i): f"Map {i}" for i in sorted(maps)}, str(default))
    )


def write_report(session: Session, path: Path, content: str) -> None:
    path = path.expanduser().absolute()
    resolved = path.resolve()
    protected = [session.target.static, session.target.patch, session.target.gamedat]
    if session.source.path.is_dir():
        protected.append(session.source.path)
    elif session.source.path.name.casefold() == "monsnpcs.dat":
        protected.append(session.source.path.parent)
    if resolved == session.source.path.resolve() or any(
        p and resolved.is_relative_to(p.resolve()) for p in protected
    ):
        raise ValueError(
            "Choose a report destination outside the game archives and GAMEDAT folders"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)
    print(f"  Saved {path}")


def _export(
    session: Session, matches: list[MonsterEntry], current: MonsterEntry | None = None
) -> None:
    labels = {
        "C": f"Matching monsters (.csv; {len(matches)} records)",
        "T": "Source overview (.txt)",
        "Q": "Back",
    }
    if current:
        labels.update(
            {
                "J": "This monster and equipment (.json)",
                "P": "Possible spawn equipment (.csv)",
                "G": "Related spawn eggs (.csv)",
            }
        )
        if current.actor:
            labels["I"] = "Actual inventory (.csv)"
    action = menu("Export monster report:", labels, "J" if current else "C")
    if action == "Q":
        return
    suffix = ".csv"
    if action == "T":
        content, suffix = session.overview() + "\n", ".txt"
    elif action == "C":
        if session.source.kind == "definitions":
            rows = [
                {"name": session.name(e), **e.definition.as_row(session.actor_flags)}
                for e in matches
                if e.definition
            ]
            content = _csv(rows, ["name", "shape", "source_file"])
        else:
            # Keep source record numbers stable when the list is filtered.
            rows = []
            for entry in matches:
                if entry.actor:
                    row = next(
                        csv.DictReader(
                            io.StringIO(
                                live_monsters_csv(
                                    U7NPCData([entry.actor]), str(session.source.path)
                                )
                            )
                        )
                    )
                    row["live_index"] = str(entry.number)
                    row["name"] = session.name(entry)
                    rows.append(dict(row))
            content = _csv(rows, ["source_file", "live_index", "shape", "name"])
    elif current is None:
        return
    elif action == "J":
        report = {
            "world": session.target.name,
            "source": str(session.source.path),
            "record_number": current.number,
            "shape": current.shape,
            "name": session.name(current),
            "definition": current.definition.as_row(session.actor_flags)
            if current.definition
            else None,
            "actor_flag_sources": session.actor_flags.sources,
            "effective_actor_flags": session.actor_flags.resolve(
                current.shape,
                legacy_flags=current.definition.legacy_actor_flags
                if current.definition
                else 0,
                legacy_source=current.definition.source_file
                if current.definition
                else "",
            ).as_row(),
            "actual_actor": asdict(current.actor) if current.actor else None,
            "actual_inventory": npc_browser.inventory_rows(session, current.actor)
            if current.actor
            else None,
            "possible_spawn_equipment": possible_equipment(session, current),
            "equipment_notes": equipment_lines(session, current),
            "warnings": session.warnings,
        }
        content, suffix = json.dumps(report, indent=2) + "\n", ".json"
    elif action == "P":
        content = _csv(
            possible_equipment(session, current),
            ["monster_shape", "item_shape", "probability", "quantity"],
        )
    elif action == "I" and current.actor:
        content = _csv(
            npc_browser.inventory_rows(session, current.actor),
            ["shape", "frame", "depth", "path"],
        )
    elif action == "G":
        content = _csv(
            spawn_rows(session, current.shape, _spawn_map(session, current)),
            ["source", "map_num", "monster_shape", "tile_x", "tile_y"],
        )
    else:
        return
    default = f"monster_{current.number}" if current else "monster_report"
    raw = (
        ui.path(f"  Report output [{default}{suffix}]: ", default + suffix)
        .strip()
        .strip('"')
        or default + suffix
    )
    write_report(session, Path(raw), content)


def _source(target: ArchiveTarget, default: str = "D") -> npc_browser.Source | None:
    while True:
        action = menu(
            "Monster source:",
            {
                "D": "Monster definitions (selected world's base + patch)",
                "G": f"Current GAMEDAT — {target.gamedat or 'not found'}",
                "S": "Saved game from this world's save folder",
                "C": "Other save, GAMEDAT, monsnpcs.dat, or MONSTERS.DAT",
                "W": "Change game/world",
                "Q": "Quit",
            },
            default,
        )
        if action == "Q":
            raise ui.PromptCancelled
        if action == "W":
            return None
        if action == "D":
            return npc_browser.Source(
                npc_browser.owner_file(target, "MONSTERS.DAT")
                or target.static
                or target.patch,
                "definitions",
            )
        if action == "G" and target.gamedat and target.gamedat.is_dir():
            return npc_browser.Source(target.gamedat, "live")
        if action == "S":
            path = npc_browser_ui._choose_save(target)
            if path:
                return npc_browser.Source(path, "save")
        elif action == "C":
            raw = (
                ui.path("  Monster source file or GAMEDAT folder: ").strip().strip('"')
            )
            if raw:
                path = Path(raw).expanduser()
                return npc_browser.Source(
                    path,
                    "definitions"
                    if path.name.casefold() == "monsters.dat"
                    else "custom",
                )
        elif action != "D":
            print("  That source is unavailable; select another or enter its path.")


def _monster_action(
    session: Session,
    current: MonsterEntry,
    action: str,
    frame: int | None,
    matches: list[MonsterEntry],
) -> int | None:
    if action == "F":
        return frame + 1 if frame is not None else None
    if action == "P":
        if sys.stdout.isatty():
            library = _library(session)
            if library:
                play_terminal(
                    playback_provider(
                        library,
                        library.shape(current.shape),
                        current.shape,
                        frame or 0,
                        "F",
                    ),
                    title=f"Monster {session.name(current)}",
                )
        else:
            print("  Frame playback requires an interactive terminal.")
    elif action == "T":
        print(
            "  Possible spawn equipment; chances do not describe this actor's actual inventory."
        )
        npc_browser_ui._paged(
            "Possible spawn equipment", equipment_lines(session, current)
        )
    elif action == "I" and current.actor:
        npc_browser_ui._inventory(session, current.actor, actor_label="monster")
    elif action == "G":
        map_num = _spawn_map(session, current)
        print(
            f"  Scanning source spawn eggs for shape {current.shape}, map {map_num}..."
        )
        rows = spawn_rows(session, current.shape, map_num)
        npc_browser_ui._paged(
            "Related spawn eggs",
            [
                f"{r['source']} | map {r['map_num']}, tile ({r['tile_x']}, {r['tile_y']}, {r['lift']}), frame {r['monster_frame']}, count {r['count']}, chance {r['probability']}%, {r['criteria']}"
                for r in rows
            ],
        )
    elif action == "E":
        _export(session, matches, current)
    return frame


def browse(session: Session, first: int | None = None) -> str:
    if not session.records:
        print(
            "  No monster records available in this source; choose another source or view."
        )
    query, mode, page = "", "all", 0
    current = next((e for e in session.records if e.shape == first), None)
    frame = None
    if first is not None and current is None:
        print(f"  Monster shape {first} is not present; choose an available monster.")
    while True:
        matches = filter_entries(session, query, mode)
        page = min(page, max(0, (len(matches) - 1) // PAGE_SIZE))
        if current is None:
            labels = {
                str(
                    e.number
                ): f"{'Instance #' + str(e.number) + ' — ' if e.actor else ''}shape {e.shape}: {session.name(e)}"
                + (f" | map {e.actor.map_num}, HP {e.actor.health}" if e.actor else "")
                for e in matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            }
            labels.update(
                {
                    "S": "Search by shape/name (#number for a live instance)",
                    "F": f"Filter ({mode})",
                    "E": "Export matching monsters",
                    "O": "Source overview",
                    "D": "Different source",
                    "W": "Change world",
                    "Q": "Quit",
                }
            )
            if (page + 1) * PAGE_SIZE < len(matches):
                labels["N"] = "Next page"
            if page:
                labels["B"] = "Previous page"
            print(
                f"\nMonsters: {len(matches)} matches; page {page + 1}/{max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)}; search: {clean(query) or '(all)'}"
            )
            action = menu("Choose monster:", labels, next(iter(labels)))
            if action == "S":
                query = ui.text("  Shape, name or #instance [blank = all]: ").strip()
                page = 0
            elif action == "F":
                filters = {
                    "A": "All",
                    "G": "Good",
                    "E": "Evil",
                    "U": "Neutral",
                    "C": "Chaotic",
                }
                modes = {
                    "A": "all",
                    "G": "good",
                    "E": "evil",
                    "U": "neutral",
                    "C": "chaotic",
                }
                if session.source.kind != "definitions":
                    filters.update({"L": "Alive", "D": "Dead"})
                    modes.update({"L": "alive", "D": "dead"})
                mode = modes[menu("Show monsters:", filters, "A")]
                page = 0
            elif action in {"N", "B"}:
                page += 1 if action == "N" else -1
            elif action == "E":
                try:
                    _export(session, matches)
                except READ_ERRORS as error:
                    print(f"  ERROR: {error}")
            elif action in {"Q", "D", "W", "O"}:
                return action
            else:
                current = next(e for e in matches if str(e.number) == action)
                frame = None
            continue
        print("\n" + detail(session, current))
        frame = preview(session, current, frame)
        navigation = filter_entries(session, mode=mode)
        index = navigation.index(current)
        following, previous = (
            navigation[(index + 1) % len(navigation)],
            navigation[(index - 1) % len(navigation)],
        )
        print(
            f"  Browsing {index + 1}/{len(navigation)} monsters; filter: {mode}. Search applies to the selection list."
        )
        labels = {
            "N": f"Next monster ({following.number}: {session.name(following)})",
            "B": f"Previous monster ({previous.number}: {session.name(previous)})",
            "S": "Choose/search monster",
            "F": "Next preview frame",
            "P": "Play shape frames",
            "T": "Possible spawn equipment",
            "G": "Related spawn eggs",
            "E": "Export report",
            "O": "Source overview",
            "D": "Different source",
            "W": "Change world",
            "Q": "Quit",
        }
        if current.actor:
            labels["I"] = "Actual inventory and nested contents"
        action = menu("Monster actions:", labels, "S")
        if action in {"Q", "D", "W", "O"}:
            return action
        if action in {"N", "B"}:
            if len(navigation) == 1:
                print(
                    "  Only one monster matches this filter; choose All to browse more."
                )
            current, frame = (following if action == "N" else previous), None
        elif action == "S":
            current, frame = None, None
        else:
            try:
                frame = _monster_action(session, current, action, frame, matches)
            except READ_ERRORS as error:
                print(f"  ERROR: {error}")


def run_browser(
    *, game: str = "bg", source: str | None = None, shape: int | None = None
) -> int:
    print("\nTitan U7 Monster Browser")
    try:
        while True:
            flavour = menu(
                "Game flavour:",
                {"1": "Black Gate", "2": "Serpent Isle"},
                "2" if game == "si" else "1",
            )
            game = "si" if flavour == "2" else "bg"
            base, targets = game_targets(game)
            target = select_target(base, targets)
            print(f"  Selected target: {clean(target.name)}")
            print(f"  Base: {target.static or 'not found'}; patch: {target.patch}")
            while True:
                try:
                    selected: npc_browser.Source | None
                    if source:
                        path = Path(source)
                        selected = npc_browser.Source(
                            path,
                            "definitions"
                            if path.name.casefold() == "monsters.dat"
                            else "custom",
                        )
                        source = None
                    else:
                        selected = _source(target)
                    if selected is None:
                        break
                    session = load_session(target, selected, game)
                except READ_ERRORS as error:
                    print(f"  ERROR: {error}")
                    continue
                print("\n" + session.overview())
                while True:
                    try:
                        action = browse(session, shape)
                        shape = None
                        if action == "O":
                            print("\n" + session.overview())
                            action = menu(
                                "Source actions:",
                                {
                                    "M": "Browse monsters",
                                    "E": "Export report",
                                    "D": "Different source",
                                    "W": "Change world",
                                    "Q": "Quit",
                                },
                                "M",
                            )
                            if action == "E":
                                _export(session, session.records)
                        if action == "Q":
                            return 0
                        if action in {"D", "W"}:
                            break
                    except READ_ERRORS as error:
                        print(f"  ERROR: {error}")
                if action == "W":
                    break
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
