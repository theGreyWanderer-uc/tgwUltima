"""Native U8 save snapshots and overviews of verified state layouts.

Only native U8SAVE archives and top-level GAMEDAT *.DAT files are accepted.
Kernel process-specific payloads remain raw; no title or timestamp is invented.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from titan.u8.flags import U8GlobalFlags
from titan.u8.avatar import U8AvatarState
from titan.u8.gumps import U8GumpState
from titan.u8.kernel import U8KernelState
from titan.u8.native_state_report import (
    describe_u8_avatar_state,
    describe_u8_gump_state,
    describe_u8_kernel_state,
)
from titan.u8.itemcach import U8ItemCache
from titan.u8.map_items import U8MapItems
from titan.u8.npcdata import U8NpcData
from titan.u8.save import U8SaveArchive

NATIVE_STATE_ENTRIES = (
    "AVATAR.DAT",
    "FLAG.DAT",
    "GUMPS.DAT",
    "ITEMCACH.DAT",
    "KERNEL.DAT",
    "NONFIXED.DAT",
    "NPCDATA.DAT",
)


def u8_state_digest(data: bytes) -> str:
    """Identify complete entry bytes, including padding and unparsed tails."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class U8SaveSnapshot:
    """One immutable-byte native snapshot, with validated known layouts or errors."""

    source: Path
    source_kind: str
    entries: dict[str, bytes]
    source_files: tuple[Path, ...]
    item_cache: U8ItemCache | None = None
    npc_data: U8NpcData | None = None
    nonfixed: U8MapItems | None = None
    global_flags: U8GlobalFlags | None = None
    avatar: U8AvatarState | None = None
    gumps: U8GumpState | None = None
    kernel: U8KernelState | None = None
    decode_errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_path(cls, filepath: str | Path) -> U8SaveSnapshot:
        """Load a strict native save archive or DAT-only GAMEDAT directory snapshot."""
        path = Path(filepath)
        entries: dict[str, bytes] = {}
        sources: list[Path] = []
        if path.is_dir():
            for candidate in sorted(path.iterdir()):
                if not candidate.is_file() or candidate.suffix.upper() != ".DAT":
                    continue
                name = candidate.name.upper()
                if name in entries:
                    raise ValueError(
                        f"U8 save snapshot: duplicate directory entry {name}"
                    )
                entries[name] = candidate.read_bytes()
                sources.append(candidate)
            if not entries:
                raise ValueError("U8 save snapshot: directory contains no DAT files")
            source_kind = "gamedat_directory"
        else:
            archive = U8SaveArchive.from_file(path)
            for name in archive.entries:
                payload = archive.get_data(name)
                if payload is not None:
                    entries[name.upper()] = payload
            sources.append(path)
            source_kind = "native_save_archive"
        snapshot = cls(path, source_kind, entries, tuple(sources))
        for name, attribute, parser in (
            ("ITEMCACH.DAT", "item_cache", U8ItemCache.from_bytes),
            ("NPCDATA.DAT", "npc_data", U8NpcData.from_bytes),
            (
                "NONFIXED.DAT",
                "nonfixed",
                lambda raw: U8MapItems.from_bytes(raw, kind="nonfixed"),
            ),
            ("FLAG.DAT", "global_flags", U8GlobalFlags.from_bytes),
            ("AVATAR.DAT", "avatar", U8AvatarState.from_bytes),
            ("GUMPS.DAT", "gumps", U8GumpState.from_bytes),
            ("KERNEL.DAT", "kernel", U8KernelState.from_bytes),
        ):
            if name not in entries:
                continue
            try:
                setattr(snapshot, attribute, parser(entries[name]))
            except ValueError as error:
                snapshot.decode_errors[name] = str(error)
        if "FLAG.DAT" not in entries:
            snapshot.global_flags = U8GlobalFlags.zero_default()
        return snapshot


def describe_u8_save_snapshot(snapshot: U8SaveSnapshot) -> dict[str, Any]:
    """Build a save overview without treating missing runtime entries as corruption."""
    decoded = {
        "FLAG.DAT",
        "ITEMCACH.DAT",
        "NPCDATA.DAT",
        "NONFIXED.DAT",
        "AVATAR.DAT",
        "GUMPS.DAT",
    }
    overview: dict[str, Any] = {
        "source": str(snapshot.source),
        "source_kind": snapshot.source_kind,
        "entry_count": len(snapshot.entries),
        "payload_bytes": sum(len(raw) for raw in snapshot.entries.values()),
        "entries": [
            {
                "name": name,
                "size": len(raw),
                "sha256": u8_state_digest(raw),
                "decode_status": "invalid"
                if name in snapshot.decode_errors
                else "partial"
                if name == "KERNEL.DAT"
                else "decoded"
                if name in decoded
                else "opaque",
                "error": snapshot.decode_errors.get(name),
            }
            for name, raw in sorted(snapshot.entries.items())
        ],
        "missing_entries": [
            name for name in NATIVE_STATE_ENTRIES if name not in snapshot.entries
        ],
        "notes": [
            "Entry sets vary: initial saves can omit FLAG, GUMPS and KERNEL.",
            "Absent FLAG.DAT uses native zero initialization; absent files remain absent in the inventory.",
            "KERNEL.DAT has partial scheduler/process coverage; derived process bytes remain raw. Unknown entries are opaque.",
            "The native archive header supplies no save title or timestamp.",
        ],
        "decode_errors": snapshot.decode_errors,
    }
    flags = snapshot.global_flags
    if snapshot.avatar is not None:
        overview["avatar"] = describe_u8_avatar_state(snapshot.avatar)
    if snapshot.gumps is not None:
        overview["gumps"] = describe_u8_gump_state(snapshot.gumps)
    if snapshot.kernel is not None:
        overview["kernel"] = describe_u8_kernel_state(snapshot.kernel)
    overview["global_flags"] = (
        None
        if flags is None
        else {
            "defaulted": flags.defaulted,
            "bit_count": 8192,
            "set_bit_count": len(flags.set_bit_indices()),
        }
    )
    cache = snapshot.item_cache
    if cache is not None:
        membership = Counter(
            cache.slot_membership(item.item_id) for item in cache.items
        )
        overview["item_cache"] = {
            "map_in": cache.metadata.map_in,
            "slot_count": len(cache.items),
            "slot_membership_counts": dict(membership),
            "nonzero_allocated_shapes": sum(
                bool(item.shape) for item in cache.iter_items()
            ),
            "free_count_stored": cache.metadata.free_count,
            "free_npc_count_stored": cache.metadata.free_npc_count,
            "ethereal_count_stored": cache.metadata.ethereal_count,
            "nonempty_region_count": sum(
                bool(region.head or region.item_count)
                for region in cache.metadata.regions
            ),
            "list_diagnostics": cache.list_diagnostics(),
        }
    npcs = snapshot.npc_data
    if npcs is not None:
        npc_summary: dict[str, Any] = {
            "slot_count": len(npcs.npcs),
            "stored_in_use_count": sum(npc.in_use for npc in npcs.npcs),
            "nonzero_record_count": sum(any(npc.raw) for npc in npcs.npcs),
            "trailing_byte_count": len(npcs.trailing_bytes),
            "paired_item_cache": cache is not None,
        }
        if cache is not None:
            selected = [
                npc
                for npc in npcs.npcs
                if npc.npc_id
                and cache.get_item(npc.npc_id).shape
                and cache.slot_membership(npc.npc_id)
                not in {"null", "free_npc", "free_item"}
            ]
            npc_summary["present_count"] = len(selected)
            npc_summary["presence_basis"] = (
                "nonzero cache shapes outside free/null lists; not the stored in_use bit"
            )
            npc_summary["map_counts"] = dict(
                Counter(str(cache.get_item(npc.npc_id).map_num_raw) for npc in selected)
            )
            npc_summary["avatar_npc_slot"] = {
                "npc_id": 1,
                "strength": npcs.get_npc(1).strength,
                "dexterity": npcs.get_npc(1).dexterity,
                "intelligence": npcs.get_npc(1).intelligence,
                "hitpoints": npcs.get_npc(1).hitpoints,
                "mana": npcs.get_npc(1).mana,
                "shape": cache.get_item(1).shape,
                "frame": npcs.get_npc(1).full_frame(cache.get_item(1).frame_low),
                "map_num_raw": cache.get_item(1).map_num_raw,
                "slot_membership": cache.slot_membership(1),
            }
        overview["npcs"] = npc_summary
    if snapshot.nonfixed is not None:
        rows = []
        for map_id, items in enumerate(snapshot.nonfixed.maps):
            if items:
                rows.append(
                    {
                        "map_id": map_id,
                        "record_count": len(items),
                        "world_count": sum(item.is_world_object for item in items),
                        "contained_count": sum(item.contained for item in items),
                        "npc_registry_count": sum(
                            item.location_kind == "npc_registry" for item in items
                        ),
                        "diagnostic_count": sum(
                            bool(item.diagnostics) for item in items
                        ),
                    }
                )
        overview["nonfixed"] = {
            "populated_slot_count": len(rows),
            "record_count": sum(row["record_count"] for row in rows),
            "maps": rows,
            "placement_basis": "stored NONFIXED only; live cache and FIXED are separate",
        }
    return overview


def format_u8_save_info(
    snapshot: U8SaveSnapshot, *, output_format: str = "text"
) -> str:
    """Render save entry coverage and verified state summaries as text or JSON."""
    if output_format not in {"text", "json"}:
        raise ValueError("U8 save info: format must be text or json")
    overview = describe_u8_save_snapshot(snapshot)
    if output_format == "json":
        return json.dumps(overview, indent=2) + "\n"
    lines = [
        f"U8 save info: {snapshot.source}",
        f"Source: {snapshot.source_kind}",
        f"Entries: {overview['entry_count']}; payload bytes: {overview['payload_bytes']}",
        "Name | Bytes | Decoding",
    ]
    for entry in overview["entries"]:
        lines.append(f"{entry['name']} | {entry['size']} | {entry['decode_status']}")
        if entry["error"]:
            lines.append(f"  Error: {entry['error']}")
    lines.append(
        "Missing entries: " + (", ".join(overview["missing_entries"]) or "none")
    )
    for key in (
        "global_flags",
        "avatar",
        "item_cache",
        "npcs",
        "nonfixed",
        "gumps",
        "kernel",
    ):
        if key in overview:
            lines.append(f"\n{key}:")
            lines.append(json.dumps(overview[key], indent=2))
    lines.extend(f"Note: {note}" for note in overview["notes"])
    return "\n".join(lines) + "\n"
