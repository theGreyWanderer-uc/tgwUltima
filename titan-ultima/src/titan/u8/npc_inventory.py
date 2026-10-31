"""Captured NPC inventory graphs for shared gump and nested-container previews."""

from __future__ import annotations

from titan.u8.container_browser import U8ContainerSession, build_u8_container_session
from titan.u8.npc_browser import U8NpcSession
from titan.u8.save_state import U8SaveSnapshot
from titan.u8.shape_browser import find_u8_browser_file, load_u8_shape_library


def load_u8_npc_inventory(session: U8NpcSession) -> U8ContainerSession:
    """Reuse the selected NPC snapshot and owner graphics; never load another save's cache."""
    snapshot = session.snapshot or U8SaveSnapshot(
        session.source.path,
        "gamedat_directory" if session.source.path.is_dir() else "paired_npc_files",
        {},
        session.source.source_files,
        item_cache=session.source.cache,
        npc_data=session.source.npcs,
        avatar=session.source.avatar,
    )
    path = find_u8_browser_file(session.library.path.parent, "U8GUMPS.FLX")
    gumps = (
        load_u8_shape_library(path, palette=session.library.palette_path)
        if path
        else None
    )
    inventory = build_u8_container_session(
        snapshot, session.library, gumps=gumps, include_stored=False
    )
    # Retain captured name overrides, without rereading the override CSV.
    inventory.names_file = session.names_file
    for state in session.states:
        row = inventory.items.get(state["npc_id"])
        if row:
            row.update(
                npc_name=state["npc_name"],
                npc_label=state["npc_label"],
                label_source=state["label_source"],
            )
    for row in inventory.items.values():
        owner = row["owner_npc_id"]
        if owner is not None:
            row["owner_name"] = session.states[owner]["npc_label"]
    inventory.npc_session = session
    return inventory
