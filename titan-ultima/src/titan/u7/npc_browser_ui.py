"""Interactive U7 NPC browser menus, previews and exports."""

from __future__ import annotations

import csv
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

from titan import _wizard_ui as ui
from titan._terminal_image import terminal_image
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.save import U7NPC, U7NPCData, U7Schedules
from titan.u7.shape_browser import load_library
from titan.u7.target_picker import game_targets, select_target
from titan.u7.npc_browser import (
    READ_ERRORS,
    Session,
    Source,
    actor_context,
    clean,
    clean_lines,
    filter_npcs,
    inventory_rows,
    load_session,
    npc_detail,
    owner_file,
    save_paths,
    schedules_text,
)


PAGE_SIZE = 15
NPC_PREVIEW_FRAME = 16


def npc_preview(session: Session, npc: U7NPC) -> None:
    """Use the same terminal artwork as shape browsing, always at frame 16."""
    if not sys.stdout.isatty():
        return
    if session.preview_library is None and session.preview_error is None:
        try:
            path = owner_file(session.target, "SHAPES.VGA")
            if path is None:
                raise ValueError("SHAPES.VGA not found for the selected world")
            session.preview_library = load_library(session.target, session.game, path)
        except READ_ERRORS as error:
            # Cache shared resource failures rather than retrying for every NPC.
            session.preview_error = str(error)
    library = session.preview_library
    if library is None:
        print(
            f"  NPC preview unavailable: {clean(session.preview_error or 'missing artwork')}"
        )
        return
    try:
        shape = library.shape(npc.shape)
        if len(shape.frames) <= NPC_PREVIEW_FRAME:
            raise ValueError(
                f"shape {npc.shape} has {len(shape.frames)} frame(s), so frame {NPC_PREVIEW_FRAME} is unavailable"
            )
        image = library.images(shape, npc.shape)[NPC_PREVIEW_FRAME]
        print(f"  NPC shape preview: shape {npc.shape}, frame {NPC_PREVIEW_FRAME}")
        terminal_image(image, reserved_rows=20)
    except READ_ERRORS as error:
        print(f"  NPC preview unavailable: {clean(str(error))}")


def _menu(
    prompt: str, labels: dict[str, str], default: str, *, hotkeys: bool = True
) -> str:
    ui.legacy_menu(prompt, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ", list(labels), default, labels=labels, message=prompt, hotkeys=hotkeys
    )


def _paged(title: str, lines: list[str]) -> None:
    page = 0
    while True:
        print(
            f"\n{title} — page {page + 1}/{max(1, (len(lines) + PAGE_SIZE - 1) // PAGE_SIZE)}"
        )
        print(
            "\n".join(lines[page * PAGE_SIZE : (page + 1) * PAGE_SIZE])
            or "  No entries."
        )
        labels = {"Q": "Back"}
        if (page + 1) * PAGE_SIZE < len(lines):
            labels["N"] = "Next page"
        if page:
            labels["B"] = "Previous page"
        action = _menu("Entries:", labels, "Q", hotkeys=True)
        if action == "Q":
            return
        page += 1 if action == "N" else -1


def _choose_save(target: ArchiveTarget) -> Path | None:
    paths = save_paths(target)
    if not paths:
        print(
            f"  No .sav files found in {target.save_root or (target.gamedat.parent if target.gamedat else target.root) or 'a configured save folder'}; use Other source to select a file."
        )
        return None
    page = 0
    while True:
        labels = {}
        for i, path in enumerate(
            paths[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], page * PAGE_SIZE
        ):
            try:
                with path.open("rb") as stream:
                    title = stream.read(80).split(b"\x00")[0].decode("latin-1")
            except OSError:
                title = "unreadable"
            labels[str(i + 1)] = f"{path.name} — {clean(title)}"
        labels["Q"] = "Back"
        if (page + 1) * PAGE_SIZE < len(paths):
            labels["N"] = "Next page"
        if page:
            labels["B"] = "Previous page"
        action = _menu("Choose saved game:", labels, str(page * PAGE_SIZE + 1))
        if action == "Q":
            return None
        if action in {"N", "B"}:
            page += 1 if action == "N" else -1
        else:
            return paths[int(action) - 1]


def _inventory(session: Session, npc: U7NPC, *, actor_label: str = "NPC") -> None:
    """Use record order and depth to distinguish repeated container shapes."""
    rows = inventory_rows(session, npc)
    parents: list[int] = []
    page = 0
    print(
        "  Preferred slot is a shape preference, not proof that the item is equipped."
    )
    while True:
        if parents:
            parent = parents[-1]
            depth = rows[parent]["depth"]
            end = next(
                (i for i in range(parent + 1, len(rows)) if rows[i]["depth"] <= depth),
                len(rows),
            )
            indices = [
                i for i in range(parent + 1, end) if rows[i]["depth"] == depth + 1
            ]
            title = f"Contents of item {parent}: {clean(rows[parent]['name']) or 'shape ' + str(rows[parent]['shape'])}"
        else:
            indices = [i for i, row in enumerate(rows) if row["depth"] == 0]
            title = "Inventory and nested contents"
        page = min(page, max(0, (len(indices) - 1) // PAGE_SIZE))
        print(f"\n{title} — {len(indices)} items; page {page + 1}")
        labels = {
            str(
                i
            ): f"{i}: {clean(rows[i]['name']) or 'shape ' + str(rows[i]['shape'])}, frame {rows[i]['frame']}, quality {rows[i]['quality']}"
            + (
                " | contains items"
                if i + 1 < len(rows) and rows[i + 1]["depth"] > rows[i]["depth"]
                else ""
            )
            for i in indices[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        }
        labels["Q"] = f"Back to {actor_label}"
        if parents:
            labels["U"] = "Up to parent inventory"
        if page:
            labels["B"] = "Previous page"
        if (page + 1) * PAGE_SIZE < len(indices):
            labels["N"] = "Next page"
        action = _menu("Choose inventory item:", labels, next(iter(labels)))
        if action == "Q":
            return
        if action == "U":
            parents.pop()
            page = 0
        elif action in {"N", "B"}:
            page += 1 if action == "N" else -1
        else:
            index = int(action)
            item, row = npc.inventory[index], rows[index]
            print(
                f"\nItem {index}: {clean(row['name']) or 'shape ' + str(item.shape)}; frame {item.frame}"
            )
            print(
                f"  Position ({item.x}, {item.y}, {item.lift}); quality {item.quality}; raw quality {item.raw_quality}; record length {item.record_length}"
            )
            print(
                f"  Depth {item.depth}; path {clean(item.path)}; flags: {item.object_flags.name or 'none'}"
            )
            print(f"  Preferred slot: {row['preferred_slot'] or '(not specified)'}")
            print(f"  Saved slot: {row['saved_slot_name'] or row['saved_slot_state']}")
            for special in item.ireg_specials:
                print(
                    f"  IREG {special.kind} at {special.offset}: {json.dumps(special.decoded)}"
                )
            if "effective_ready" in row:
                resolved = row["effective_ready"]
                print(
                    f"  Exult preference: {resolved['effective_slot_name']}; alternatives: {', '.join(resolved['alternate_slot_names'])}"
                )
            print(
                f"  IREG payload: {item.ireg_kind or 'unknown'}; {json.dumps(item.ireg_data)}"
            )
            for warning in item.ireg_warnings:
                print(f"  NOTE: {warning}")
            options = {"B": "Back to inventory", "Q": f"Back to {actor_label}"}
            if index + 1 < len(rows) and rows[index + 1]["depth"] > item.depth:
                options = {"C": "Browse contents", **options}
            action = _menu("Item actions:", options, next(iter(options)), hotkeys=True)
            if action == "Q":
                return
            if action == "C":
                parents.append(index)
                page = 0


def _choose_source(target: ArchiveTarget, default: str) -> Source | None:
    while True:
        initial = owner_file(target, "INITGAME.DAT")
        action = _menu(
            "NPC/save source:",
            {
                "I": f"New-game INITGAME.DAT — {initial or 'not found'}",
                "G": f"Current GAMEDAT — {target.gamedat or 'not found'}",
                "S": "Saved game from this world's save folder",
                "C": "Other save, INITGAME.DAT, GAMEDAT folder, or npc.dat",
                "W": "Change game/world",
                "Q": "Quit",
            },
            default,
        )
        if action == "Q":
            raise ui.PromptCancelled
        if action == "W":
            return None
        if action == "C":
            raw = ui.path("  Save file or GAMEDAT folder: ").strip().strip('"')
            if not raw:
                continue
            return Source(Path(raw).expanduser())
        if action == "S":
            path = _choose_save(target)
            if path:
                return Source(path, "save")
        elif action == "I" and initial:
            return Source(initial, "initial")
        elif action == "G" and target.gamedat and target.gamedat.is_dir():
            return Source(target.gamedat, "live")
        else:
            print("  That source is unavailable; select another or enter its path.")


def _export(session: Session, matches: list[U7NPC], npc: U7NPC | None = None) -> None:
    labels = {
        "N": f"NPC CSV ({len(matches)} matching NPCs)",
        "T": "Source overview (.txt)",
        "Q": "Back",
    }
    if npc is not None:
        labels.update(
            {
                "I": "This NPC's inventory (.csv)",
                "S": "This NPC's daily schedules (.csv)",
                "J": "This NPC, inventory and schedules (.json)",
            }
        )
    action = _menu("Export report:", labels, "J" if npc else "N")
    if action == "Q":
        return
    if action == "T":
        content, suffix = session.overview() + "\n", ".txt"
    elif action == "N":
        subset = U7NPCData(
            matches, npc_flavor=session.npcs.npc_flavor if session.npcs else "unknown"
        )
        content, suffix = subset.dump_csv(), ".csv"
    elif npc is not None and action == "S":
        if session.schedules is None:
            print("  Daily schedule data unavailable in this source.")
            return
        subset_sched = U7Schedules(
            {npc.npc_num: session.schedules.entries.get(npc.npc_num, [])},
            session.schedules.num_npcs,
            session.schedules.format,
            script_names=session.schedules.script_names,
        )
        content, suffix = subset_sched.dump_csv({npc.npc_num: npc.name}), ".csv"
    elif npc is not None and action == "I":
        rows = inventory_rows(session, npc)
        buffer = io.StringIO()
        fields = (
            list(rows[0])
            if rows
            else [
                "shape",
                "frame",
                "name",
                "depth",
                "path",
                "preferred_slot",
                "location",
            ]
        )
        writer = csv.DictWriter(buffer, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        content, suffix = buffer.getvalue(), ".csv"
    elif npc is not None:
        report = {
            "world": session.target.name,
            "source": str(session.source.path),
            "warnings": session.warnings,
            "npc": asdict(npc),
            "appearance": actor_context(session, npc).get("appearance"),
            "actor_context": actor_context(session, npc),
            "script_names": session.schedules.script_names
            if session.schedules is not None
            else (),
            "inventory": inventory_rows(session, npc),
            "schedules": [
                asdict(e) for e in session.schedules.entries.get(npc.npc_num, [])
            ]
            if session.schedules
            else None,
        }
        content, suffix = json.dumps(report, indent=2) + "\n", ".json"
    else:
        return
    default = f"npc_{npc.npc_num}" if npc else "npc_report"
    raw = (
        ui.path(f"  Report output [{default}{suffix}]: ", default + suffix)
        .strip()
        .strip('"')
        or default + suffix
    )
    path = Path(raw).expanduser().absolute()
    resolved = path.resolve()
    protected = [session.target.static, session.target.patch, session.target.gamedat]
    if session.source.path.is_dir():
        protected.append(session.source.path)
    if resolved == session.source.path.resolve() or any(
        p and resolved.is_relative_to(p.resolve()) for p in protected
    ):
        raise ValueError(
            "Choose a report destination outside the game archives and GAMEDAT folders"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation keeps game data and existing reports intact.
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)
    print(f"  Saved {path}")


def _browse_npcs(session: Session, first: int | None = None) -> str:
    if session.npcs is None or not session.npcs.npcs:
        print("  No NPC records available in this source.")
        return "O"
    query, mode, page = "", "all", 0
    current = next((n for n in session.npcs.npcs if n.npc_num == first), None)
    if first is not None and current is None:
        print(f"  NPC {first} is not present; choose an available NPC.")
    while True:
        matches = filter_npcs(session.npcs.npcs, query, mode)
        page = min(page, max(0, (len(matches) - 1) // PAGE_SIZE))
        if current is None:
            labels = {
                str(
                    n.npc_num
                ): f"#{n.npc_num} {clean(n.name) or '(unnamed)'} — map {n.map_num}, HP {n.health}, {n.schedule_name}"
                + (" | party" if n.in_party else "")
                + (" | dead" if n.is_dead else "")
                + (" | unused" if n.unused else "")
                for n in matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            }
            labels.update(
                {
                    "S": "Search by NPC number or name",
                    "F": f"Filter ({mode})",
                    "E": "Export matching NPCs",
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
                f"\nNPCs: {len(matches)} matches; page {page + 1}/{max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)}; search: {clean(query) or '(all)'}"
            )
            action = _menu("Choose NPC:", labels, next(iter(labels)))
            if action in {"Q", "O", "D", "W"}:
                return action
            if action == "S":
                query = ui.text("  NPC number or name [blank = all]: ").strip()
                page = 0
            elif action == "F":
                selected = _menu(
                    "Show:",
                    {
                        "A": "All NPCs",
                        "P": "Party",
                        "L": "Alive, used slots",
                        "D": "Dead",
                        "U": "Unused slots",
                    },
                    "A",
                )
                mode, page = (
                    {
                        "A": "all",
                        "P": "party",
                        "L": "alive",
                        "D": "dead",
                        "U": "unused",
                    }[selected],
                    0,
                )
            elif action in {"N", "B"}:
                page += 1 if action == "N" else -1
            elif action == "E":
                _export(session, matches)
            else:
                current = next(n for n in matches if str(n.npc_num) == action)
            continue
        print("\n" + npc_detail(session, current))
        npc_preview(session, current)
        navigation = filter_npcs(session.npcs.npcs, mode=mode)
        index = navigation.index(current)
        next_npc = navigation[(index + 1) % len(navigation)]
        previous_npc = navigation[(index - 1) % len(navigation)]
        print(
            f"  Browsing {index + 1}/{len(navigation)} NPCs; filter: {mode}. Search applies to the selection list."
        )
        action = _menu(
            "NPC actions:",
            {
                "N": f"Next NPC (#{next_npc.npc_num} {clean(next_npc.name) or 'unnamed'})",
                "B": f"Previous NPC (#{previous_npc.npc_num} {clean(previous_npc.name) or 'unnamed'})",
                "S": "Choose/search NPC",
                "I": "Inventory and nested contents",
                "T": "Daily schedules",
                "E": "Export report",
                "O": "Source overview",
                "D": "Different source",
                "W": "Change world",
                "Q": "Quit",
            },
            "S",
            hotkeys=True,
        )
        try:
            if action in {"Q", "O", "D", "W"}:
                return action
            if action in {"N", "B"}:
                if len(navigation) == 1:
                    print(
                        "  Only one NPC matches the current filter; choose All to browse more NPCs."
                    )
                current = next_npc if action == "N" else previous_npc
            elif action == "S":
                current = None
            elif action == "T":
                _paged("Daily schedules", schedules_text(session, current).splitlines())
            elif action == "I":
                _inventory(session, current)
            elif action == "E":
                _export(session, matches, current)
        except (OSError, ValueError) as error:
            print(f"  ERROR: {error}")


def run_browser(
    *,
    game: str = "bg",
    source: str | None = None,
    npc: int | None = None,
    saves: bool = False,
    have_si_shapes: bool | None = None,
    avatar_skin: int | None = None,
    avatar_female: bool | None = None,
) -> int:
    print("\nTitan U7 NPC / Save Browser")
    try:
        while True:
            flavour = _menu(
                "Game flavour:",
                {"1": "Black Gate", "2": "Serpent Isle"},
                "2" if game == "si" else "1",
            )
            game = "si" if flavour == "2" else "bg"
            base, targets = game_targets(game)
            target = select_target(base, targets)
            print(f"  Selected target: {clean(target.name)}")
            print(
                f"  GAMEDAT: {target.gamedat or 'not found'}; saves: {target.save_root or 'not configured'}"
            )
            while True:
                try:
                    selected = (
                        Source(Path(source))
                        if source
                        else _choose_source(
                            target, "S" if saves else "G" if target.gamedat else "I"
                        )
                    )
                    source = None
                    if selected is None:
                        break
                    session = load_session(target, selected, game)
                    if have_si_shapes is not None:
                        session.have_si_shapes = have_si_shapes
                    session.avatar_skin, session.avatar_female = (
                        avatar_skin,
                        avatar_female,
                    )
                except READ_ERRORS as error:
                    print(f"  ERROR: {error}")
                    continue
                if not saves:
                    print("\n" + session.overview())
                action = "O" if saves else "N"
                while True:
                    try:
                        if action == "N":
                            action = _browse_npcs(session, npc)
                            npc = None
                        elif action == "O":
                            print("\n" + session.overview())
                            labels = {
                                "N": "Browse NPCs",
                                "P": "Party roster",
                                "F": "List source files",
                                "E": "Export report",
                                "D": "Different source",
                                "W": "Change world",
                                "Q": "Quit",
                            }
                            action = _menu(
                                "Source actions:",
                                labels,
                                "N" if session.npcs else "F",
                                hotkeys=True,
                            )
                        elif action == "P":
                            _paged(
                                "Stored party roster",
                                clean_lines(session.info.dump()).splitlines()
                                if session.info
                                else [
                                    "No saveinfo.dat party roster in this source; use the NPC Party filter for actor party flags."
                                ],
                            )
                            action = "O"
                        elif action == "F":
                            _paged(
                                "Source files",
                                [
                                    f"{clean(name)} — {size:,} bytes"
                                    for name, size in session.entries
                                ],
                            )
                            action = "O"
                        elif action == "E":
                            _export(session, session.npcs.npcs if session.npcs else [])
                            action = "O"
                        elif action == "Q":
                            return 0
                        else:
                            break
                    except (OSError, ValueError) as error:
                        print(f"  ERROR: {error}")
                        action = "O"
                if action == "W":
                    break
                npc = None
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
