"""Joined NPC animation inventories, reusable contact sheets and offline reports."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from titan.u8.anim import DIRECTION_NAMES
from titan.u8.avatar import U8AvatarState
from titan.u8.itemcach import U8ItemCache
from titan.u8.npcdata import U8NpcData
from titan.u8.npc_names import describe_u8_npc_identity
from titan.u8.npc_names import load_u8_npc_labels as load_u8_npc_labels
from titan.u8.shape_names import U8_USECODE_CLASS_NAMES_FILE
from titan.u8.npc_animation_html import (
    render_npc_animation_index,
    render_npc_animation_page,
)
from titan.u8.shape_browser import (
    U8ShapeLibrary,
    describe_u8_browser_shape,
    export_u8_browser_contact_sheets,
    u8_contact_sheet_groups,
)
from titan.u8.state_report import format_u8_npcdata_report

ANIMATION_FIELDS = [
    "npc_id",
    "npc_name",
    "npc_label",
    "label_source",
    "npc_usecode_class",
    "npc_usecode_name",
    "shape",
    "class_label",
    "row_kind",
    "action",
    "direction",
    "direction_name",
    "step",
    "frame",
    "animation_name",
    "frame_label",
    "valid_frame",
    "width",
    "height",
    "xoff",
    "yoff",
    "compressed",
    "table_unknown",
    "frame_unknown_hex",
    "action_offset",
    "action_frame_count",
    "repeat",
    "action_flags",
    "action_flag_names",
    "action_unknown_4",
    "action_unknown_10",
    "action_raw_header",
    "delta_z",
    "sfx",
    "delta_dir",
    "movement_world_units",
    "special",
    "flags_hi",
    "on_ground",
    "attack_range",
    "flipped",
    "call_usecode",
    "unknown_flag80",
    "node_raw",
    "matches_saved_context",
    "matches_saved_frame",
    "saved_action",
    "saved_direction",
    "saved_step",
    "saved_frame",
    "slot_membership",
    "map",
    "x",
    "y",
    "z",
    "strength",
    "dexterity",
    "intelligence",
    "hitpoints",
    "mana",
    "state_flags",
    "control_flags",
    "npc_flag_names",
    "npc_report",
    "contact_sheet",
]


def describe_u8_npc_animations(
    library: U8ShapeLibrary,
    npcs: U8NpcData,
    cache: U8ItemCache,
    *,
    npc_id: int | None = None,
    labels: dict[int, str] | None = None,
    avatar: U8AvatarState | None = None,
) -> dict[str, Any]:
    """Inventory allocated NPCs, retaining invalid nodes and unreferenced raw frames."""
    if library.animations is None:
        raise ValueError("NPC animation report requires a valid paired ANIM.DAT")
    selection = json.loads(
        format_u8_npcdata_report(
            npcs, item_cache=cache, npc_id=npc_id, output_format="json"
        )
    )
    inventory: dict[str, Any] = {
        "selection_basis": selection["selection_basis"],
        "diagnostics": [*library.diagnostics, *selection["list_diagnostics"]],
        "shapes": {},
        "npcs": [],
    }
    for state in selection["npcs"]:
        number = state["item_shape"]
        state.update(
            {
                **describe_u8_npc_identity(state, labels=labels, avatar=avatar),
                "class_label": library.names.get(number, ""),
                "page": f"npcs/npc_{state['npc_id']:03d}.html",
            }
        )
        inventory["npcs"].append(state)
        if number in inventory["shapes"]:
            continue
        shape: dict[str, Any] = {
            "shape": number,
            "rows": [],
            "diagnostics": [],
            "metadata": None,
        }
        inventory["shapes"][number] = shape
        try:
            metadata = describe_u8_browser_shape(library, number)
            shape["metadata"] = metadata
        except ValueError as error:
            shape["diagnostics"].append(str(error))
            continue
        referenced = set()
        for action in library.actions(number):
            for direction, nodes in enumerate(action.directions):
                for step, node in enumerate(nodes):
                    valid = 0 <= node.frame < metadata["frame_count"]
                    referenced.add(node.frame)
                    row = {
                        **{
                            key: value
                            for key, value in asdict(node).items()
                            if key != "raw"
                        },
                        **(metadata["frames"][node.frame] if valid else {}),
                        "row_kind": "animation",
                        "action": action.action_num,
                        "animation_name": action.name,
                        "direction": direction,
                        "direction_name": DIRECTION_NAMES[direction],
                        "step": step,
                        "frame_label": f"{action.name} {DIRECTION_NAMES[direction]} step {step}",
                        "valid_frame": valid,
                        "action_offset": action.offset,
                        "action_frame_count": action.frame_count,
                        "repeat": action.repeat,
                        "action_flags": action.flags,
                        "action_flag_names": "|".join(action.flag_names()),
                        "action_unknown_4": action.unknown_4,
                        "action_unknown_10": action.unknown_10,
                        "action_raw_header": action.raw_header.hex(),
                        "node_raw": node.raw.hex(),
                        "movement_world_units": node.movement_world_units,
                        "contact_sheet": "",
                    }
                    shape["rows"].append(row)
                    if not valid:
                        shape["diagnostics"].append(
                            f"Action {action.action_num} {DIRECTION_NAMES[direction]} step {step} references missing sprite frame {node.frame}"
                        )
        for frame in metadata["frames"]:
            if frame["frame"] not in referenced:
                shape["rows"].append(
                    {
                        **frame,
                        "row_kind": "unreferenced",
                        "animation_name": "",
                        "frame_label": f"Raw frame {frame['frame']}; no ANIM reference",
                        "valid_frame": True,
                        "contact_sheet": "",
                    }
                )
    return inventory


def u8_npc_animation_rows(
    state: dict[str, Any], shape: dict[str, Any]
) -> list[dict[str, Any]]:
    """Repeat NPC context in CSV rows without claiming unique names for sprite frames."""
    context = {
        "npc_id": state["npc_id"],
        "npc_name": state["npc_name"],
        "npc_label": state["npc_label"],
        "label_source": state["label_source"],
        "npc_usecode_class": state["npc_usecode_class"],
        "npc_usecode_name": state["npc_usecode_name"],
        "shape": state["item_shape"],
        "class_label": state["class_label"],
        "saved_action": state["last_action"],
        "saved_direction": state["direction"],
        "saved_step": state["animation_step"],
        "saved_frame": state["item_frame"],
        "npc_flag_names": "|".join(state["flag_names"]),
        "slot_membership": state["slot_membership"],
        "map": state["item_map"],
        "x": state["item_x"],
        "y": state["item_y"],
        "z": state["item_z"],
        **{
            key: state[key]
            for key in (
                "strength",
                "dexterity",
                "intelligence",
                "hitpoints",
                "mana",
                "state_flags",
                "control_flags",
            )
        },
    }
    rows = []
    for frame in shape["rows"]:
        anchor = (
            f"action_{frame['action']:02d}_{frame['direction_name'].lower()}"
            if frame["row_kind"] == "animation"
            else "unreferenced"
        )
        rows.append(
            {
                **context,
                **frame,
                "npc_report": f"{state['page']}#{anchor}",
                "matches_saved_context": frame["row_kind"] == "animation"
                and (frame["action"], frame["direction"], frame["step"])
                == (state["last_action"], state["direction"], state["animation_step"]),
                "matches_saved_frame": frame["frame"] == state["item_frame"],
            }
        )
    return rows


def _attach_contact_sheets(
    library: U8ShapeLibrary, shape: dict[str, Any], staging: Path
) -> None:
    if shape["metadata"] is None:
        return
    number = shape["shape"]
    directory = staging / "assets" / f"shape_{number:04d}"
    by_frame: dict[tuple[int, int, int], str] = {}
    for group in u8_contact_sheet_groups(library, number, animated=True):
        try:
            paths = export_u8_browser_contact_sheets(
                library, number, directory, animated=True, group=group.key
            )
        except ValueError as error:
            shape["diagnostics"].append(f"Contact sheet {group.label}: {error}")
            continue
        for step in range(group.frame_count):
            path = paths[step // 12]
            by_frame[
                (
                    group.action if group.action is not None else -1,
                    group.direction,
                    step,
                )
            ] = path.relative_to(staging).as_posix()
    raw_pages = {}
    for row in shape["rows"]:
        if row["row_kind"] == "animation":
            row["contact_sheet"] = by_frame.get(
                (row["action"], row["direction"], row["step"]), ""
            )
        else:
            page = row["frame"] // 12
            if page not in raw_pages:
                group = u8_contact_sheet_groups(library, number)[page]
                path = export_u8_browser_contact_sheets(
                    library, number, directory, group=group.key
                )[0]
                raw_pages[page] = path.relative_to(staging).as_posix()
            row["contact_sheet"] = raw_pages[page]


def export_u8_npc_animation_report(
    library: U8ShapeLibrary,
    npcs: U8NpcData,
    cache: U8ItemCache,
    output: Path,
    *,
    sources: tuple[Path, ...] = (),
    npc_id: int | None = None,
    labels: dict[int, str] | None = None,
    avatar: U8AvatarState | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Prepare complete reports before publishing to a new or empty output folder."""
    output = output.expanduser().resolve()
    name_sources = (
        (U8_USECODE_CLASS_NAMES_FILE,) if U8_USECODE_CLASS_NAMES_FILE.is_file() else ()
    )
    source_files = tuple(
        dict.fromkeys(
            path.resolve() for path in (*sources, *library.source_paths, *name_sources)
        )
    )
    if any(source == output or output in source.parents for source in source_files):
        raise ValueError("NPC animation report: output must not contain input files")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(
            "NPC animation report: output must be a new or empty directory"
        )
    inventory = describe_u8_npc_animations(
        library, npcs, cache, npc_id=npc_id, labels=labels, avatar=avatar
    )
    if not inventory["npcs"]:
        raise ValueError("NPC animation report: no NPCs match this snapshot/selection")
    manifest: dict[str, Any] = {
        "format_version": 1,
        "selection_basis": inventory["selection_basis"],
        "npc_count": len(inventory["npcs"]),
        "shape_count": len(inventory["shapes"]),
        "animation_name_scope": "ANIM action labels; reused frames retain action/direction/step context",
        "repeat_unit": "native wait count, not milliseconds",
        "sources": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in source_files
        ],
        "diagnostics": inventory["diagnostics"],
        "npcs": [],
        "shapes": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-", dir=output.parent
    ) as temporary:
        staging = Path(temporary)
        for number, shape in inventory["shapes"].items():
            if progress:
                progress(f"Rendering animation sets for shape {number}...")
            _attach_contact_sheets(library, shape, staging)
            manifest["shapes"].append(
                {
                    "shape": number,
                    "row_count": len(shape["rows"]),
                    "diagnostics": shape["diagnostics"],
                }
            )
        (staging / "npcs").mkdir()
        master_count = 0
        with (staging / "master.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(
                stream, fieldnames=ANIMATION_FIELDS, extrasaction="raise"
            )
            writer.writeheader()
            for state in inventory["npcs"]:
                shape = inventory["shapes"][state["item_shape"]]
                rows = u8_npc_animation_rows(state, shape)
                for row in rows:
                    writer.writerow({key: row.get(key, "") for key in ANIMATION_FIELDS})
                master_count += len(rows)
                page = render_npc_animation_page(state, shape, rows)
                (staging / state["page"]).write_text(page, encoding="utf-8")
                manifest["npcs"].append(
                    {
                        "npc_id": state["npc_id"],
                        "label": state["npc_label"],
                        "npc_name": state["npc_name"],
                        "label_source": state["label_source"],
                        "npc_usecode_class": state["npc_usecode_class"],
                        "npc_usecode_name": state["npc_usecode_name"],
                        "shape": state["item_shape"],
                        "page": state["page"],
                        "row_count": len(rows),
                        "diagnostics": shape["diagnostics"],
                    }
                )
        manifest["row_count"] = master_count
        manifest["contact_sheet_count"] = len(list(staging.rglob("*.png")))
        (staging / "npc_state.json").write_text(
            json.dumps(inventory["npcs"], indent=2), encoding="utf-8"
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        (staging / "index.html").write_text(
            render_npc_animation_index(manifest), encoding="utf-8"
        )
        # Staging is a verified sibling on the output drive. Publish once,
        # avoiding a second write of thousands of sheets and partial bundles.
        if staging.resolve().parent != output.parent:
            raise ValueError(
                "NPC animation report: staging must share the output parent"
            )
        if output.exists():
            if not output.is_dir() or any(output.iterdir()):
                raise ValueError(
                    "NPC animation report: output became nonempty while preparing reports"
                )
            output.rmdir()  # Empty only; a concurrent new file prevents removal.
        staging.rename(output)
    return manifest
