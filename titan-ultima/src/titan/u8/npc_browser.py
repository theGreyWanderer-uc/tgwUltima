"""Native U8 NPC browser sessions, identity, filters and equipment inspection."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from titan._config import cfg
from titan.u8.npc_names import describe_u8_npc_identity, load_u8_npc_labels
from titan.u8.npc_source import U8NpcSource, load_u8_npc_source
from titan.u8.gumps import U8GumpState
from titan.u8.save import U8SaveArchive
from titan.u8.save_state import U8SaveSnapshot, format_u8_save_info
from titan.u8.shape_browser import U8ShapeLibrary, find_u8_browser_file
from titan.u8.state_report import format_u8_npcdata_report

U8_NPC_BROWSER_OUTPUT = Path("titan-out/u8_npc_browse_export")


@dataclass
class U8NpcSession:
    """One immutable native snapshot and its selected graphics owner."""

    source: U8NpcSource
    library: U8ShapeLibrary
    states: list[dict[str, Any]]
    labels: dict[int, str]
    names_file: Path | None = None
    captured_overview: str | None = None
    snapshot: U8SaveSnapshot | None = None

    @property
    def source_files(self) -> tuple[Path, ...]:
        return (
            self.source.source_files
            + self.library.source_paths
            + ((self.names_file,) if self.names_file else ())
        )


def load_u8_npc_session(
    path: Path,
    library: U8ShapeLibrary,
    *,
    itemcach: Path | None = None,
    names: Path | None = None,
) -> U8NpcSession:
    """Join all native slots once, preserving allocation independently of in_use."""
    path = path.expanduser().resolve()
    native_save = path.is_file() and U8SaveArchive.is_save_file(path.read_bytes())
    if itemcach is None and (path.is_dir() or native_save):
        snapshot = U8SaveSnapshot.from_path(path)
        if snapshot.npc_data is None or snapshot.item_cache is None:
            raise ValueError(
                "U8 NPC browser requires paired valid NPCDATA.DAT and ITEMCACH.DAT"
            )
        source = U8NpcSource(
            path,
            snapshot.npc_data,
            snapshot.item_cache,
            snapshot.source_files,
            snapshot.avatar,
        )
        if "AVATAR.DAT" in snapshot.decode_errors:
            source.diagnostics.append(
                f"Optional Avatar name unavailable: {snapshot.decode_errors['AVATAR.DAT']}"
            )
    else:
        source = load_u8_npc_source(path, itemcach=itemcach)
        snapshot = U8SaveSnapshot(
            path,
            "gamedat_directory" if path.is_dir() else "paired_npc_files",
            {},
            source.source_files,
            item_cache=source.cache,
            npc_data=source.npcs,
            avatar=source.avatar,
        )
        # Capture optional gumps at session load, never reread them when G is pressed.
        gump_path = (
            path
            if native_save
            else find_u8_browser_file(
                path if path.is_dir() else path.parent, "GUMPS.DAT"
            )
        )
        if gump_path:
            try:
                snapshot.gumps = U8GumpState.from_file(gump_path)
                snapshot.source_files = tuple(
                    dict.fromkeys((*snapshot.source_files, gump_path))
                )
            except (ValueError, OSError) as error:
                snapshot.decode_errors["GUMPS.DAT"] = str(error)
    labels = load_u8_npc_labels(names) if names else {}
    states = json.loads(
        format_u8_npcdata_report(
            source.npcs, item_cache=source.cache, all_slots=True, output_format="json"
        )
    )["npcs"]
    for state in states:
        state.update(
            describe_u8_npc_identity(state, labels=labels, avatar=source.avatar)
        )
        state["class_label"] = library.names.get(state["item_shape"], "")
    return U8NpcSession(source, library, states, labels, names, snapshot=snapshot)


def u8_npc_is_allocated(state: dict[str, Any]) -> bool:
    """Use cache shape/free-list membership; initial saves clear every in_use bit."""
    return bool(state["npc_id"] and state["item_shape"]) and state[
        "slot_membership"
    ] not in {"null", "free_npc", "free_item"}


def filter_u8_npcs(
    states: list[dict[str, Any]],
    *,
    query: str = "",
    mode: str = "allocated",
    map_num: int | None = None,
    shape: int | None = None,
) -> list[dict[str, Any]]:
    """Search NPC ID/name/class with independent map, shape and allocation filters."""
    if mode not in {"allocated", "unused", "all", "alive", "dead"}:
        raise ValueError("U8 NPC browser: unknown allocation filter")
    query = query.strip().casefold()
    try:
        wanted = int(query, 16 if query.startswith("0x") else 10) if query else None
    except ValueError:
        wanted = None
    matches = []
    for state in states:
        allocated = u8_npc_is_allocated(state)
        if mode == "allocated" and not allocated or mode == "unused" and allocated:
            continue
        if mode in {"alive", "dead"} and (
            not allocated or bool(state["state_flags"] & 0x10) != (mode == "dead")
        ):
            continue
        if map_num is not None and state["item_map"] != map_num:
            continue
        if shape is not None and state["item_shape"] != shape:
            continue
        if query and not (
            state["npc_id"] == wanted
            if wanted is not None
            else any(
                query in str(state[key]).casefold()
                for key in ("npc_name", "npc_label", "class_label", "npc_usecode_name")
            )
        ):
            continue
        matches.append(state)
    return matches


def describe_u8_npc_equipment(
    session: U8NpcSession, state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep numbered native equipment slots and diagnose stale/invalid item references."""
    rows = []
    for equipment in state["equipment_items"]:
        row = dict(equipment)
        item = row.get("item")
        if item is not None:
            row["class_label"] = session.library.names.get(item["shape"], "")
            row["frame"] = (
                session.source.npcs.get_npc(item["item_id"]).full_frame(
                    item["frame_low"]
                )
                if 0 < item["item_id"] < 256
                else item["frame_low"]
            )
            if item["slot_membership"] in {"null", "free_npc", "free_item"}:
                row["issue"] = "equipment reference points to a free/null cache slot"
            elif not item["shape"]:
                row["issue"] = "equipment reference has no sprite shape"
        rows.append(row)
    return rows


def format_u8_npc_browser_summary(states: list[dict[str, Any]]) -> str:
    """Export filter results with names and native IDs; equipment remains JSON cells."""
    fields = [
        "npc_id",
        "npc_name",
        "npc_label",
        "label_source",
        "npc_usecode_class",
        "npc_usecode_name",
        "item_shape",
        "class_label",
        "item_frame",
        "item_map",
        "item_x",
        "item_y",
        "item_z",
        "strength",
        "dexterity",
        "intelligence",
        "hitpoints",
        "mana",
        "state_flags",
        "control_flags",
        "flag_names",
        "slot_membership",
        "last_action",
        "direction",
        "animation_step",
        "equipment",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for state in states:
        writer.writerow(
            {
                key: json.dumps(state[key])
                if key in {"equipment", "flag_names"}
                else state[key]
                for key in fields
            }
        )
    return "\ufeff" + stream.getvalue()


def describe_u8_npc_source_overview(session: U8NpcSession) -> str:
    """Use the native save overview for saves/directories and a paired-loose overview otherwise."""
    if session.captured_overview is not None:
        return session.captured_overview
    path = session.source.path
    if path.is_dir() or U8SaveArchive.is_save_file(path.read_bytes()):
        return format_u8_save_info(U8SaveSnapshot.from_path(path))
    return json.dumps(
        {
            "source": str(path),
            "paired_files": [str(p) for p in session.source.source_files],
            "allocated_npc_count": len(filter_u8_npcs(session.states)),
            "diagnostics": session.source.diagnostics
            + session.source.cache.list_diagnostics(),
        },
        indent=2,
    )


def discover_u8_npc_sources(static: Path) -> tuple[list[Path], list[Path]]:
    """Discover only the selected installation's GAMEDAT and U8SAVE siblings."""
    roots: tuple[Path, ...] = (static.parent,)
    if static.parent.name.upper() in {"ENGLISH", "FRENCH", "GERMAN"}:
        roots += (static.parent.parent,)
    game_dirs: list[Path] = []
    save_dirs: list[Path] = []
    for root in roots:
        for owner in (root, root / "cloud_saves"):
            if not owner.is_dir():
                continue
            for path in owner.iterdir():
                if (
                    path.is_dir()
                    and path.name.casefold() == "gamedat"
                    and find_u8_browser_file(path, "NPCDATA.DAT")
                ):
                    game_dirs.append(path)
                if path.is_dir() and path.name.casefold() == "savegame":
                    save_dirs.append(path)
    # An explicit configured source must belong to this installation.
    for key, collection in (("gamedat", game_dirs), ("savegame", save_dirs)):
        value = cfg(key)
        if value:
            path = Path(value).expanduser().resolve()
            if path.is_dir() and any(root.resolve() in path.parents for root in roots):
                collection.append(path)
    saves = [
        file
        for folder in dict.fromkeys(save_dirs)
        for file in sorted(folder.iterdir())
        if file.is_file() and file.name.upper().startswith("U8SAVE.")
    ]
    return list(dict.fromkeys(game_dirs)), list(dict.fromkeys(saves))
