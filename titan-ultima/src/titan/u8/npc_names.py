"""NPC identity from native slot dispatch, independent of shared sprite shapes.

Native U8/UPROCESS.C spawnUnk uses referent + 1024 for NPCs with status
0x80 clear. ITEM.C isNpc accepts nonzero references below 256. These are
bundled English usecode symbols, not translated strings read from NPCDATA.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from titan.u8.avatar import U8AvatarState
from titan.u8.shape_names import load_u8_shape_names


def load_u8_npc_labels(path: Path) -> dict[int, str]:
    """Read unique npc_id,name CSV overrides, including decimal or hexadecimal IDs."""
    labels: dict[int, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"npc_id", "name"}.issubset(reader.fieldnames or []):
            raise ValueError("NPC animation names: CSV requires npc_id,name columns")
        for row in reader:
            raw = (row.get("npc_id") or "").strip()
            number = int(raw, 16 if raw.lower().startswith("0x") else 10)
            name = (row.get("name") or "").strip()
            if not 0 <= number <= 255 or not name or number in labels:
                raise ValueError(
                    "NPC animation names: IDs must be unique 0-255 with nonempty names"
                )
            labels[number] = name
    return labels


def describe_u8_npc_identity(
    state: dict[str, Any],
    *,
    labels: dict[int, str] | None = None,
    avatar: U8AvatarState | None = None,
) -> dict[str, Any]:
    """Resolve NPC names by allocated slot/status; never infer identity from a shape."""
    number = state["npc_id"]
    allocated = bool(number and state["item_shape"]) and state[
        "slot_membership"
    ] not in {"null", "free_npc", "free_item"}
    permanent = allocated and not state["item_status"] & 0x80
    unit = (number + 1024 if permanent else state["item_shape"]) if allocated else None
    symbol = load_u8_shape_names().get(unit, "") if unit is not None else ""
    name, source = "", "native_slot_id"
    if labels and number in labels:
        name, source = labels[number], "names_csv"
    elif allocated and number == 1:
        name = avatar.name.strip() if avatar is not None else ""
        name, source = (
            (name, "native_avatar_name") if name else ("Avatar", "native_avatar_slot")
        )
    elif permanent and symbol:
        name = re.sub(r"(?<=\D)(?=\d)", " ", symbol.replace("_", " ").title())
        source = "bundled_npc_usecode_class"
    return {
        "npc_name": name,
        "npc_label": name or f"NPC {number}",
        "label_source": source,
        "npc_usecode_class": unit,
        "npc_usecode_name": symbol,
    }
