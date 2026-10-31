"""Decode U8 NPCDATA.DAT's 256 packed 49-byte NPC records and preserved tail.

References: decoded ITEM/NPC.H/C and Pentagram world/World.cpp. NPC slot IDs
join ITEMCACH item IDs; frame_hi combines with that file's frame_low byte.
The initial retail state leaves in_use clear even for NPCs with item shapes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from titan.u8.itemcach import NPC_SLOT_COUNT
from titan.u8.state_io import parse_u8_state_flex, read_u8_state_bytes

__all__ = ["U8NpcData", "U8NpcState", "U8NpcDataError"]

NPC_RECORD_SIZE = 49
NPC_ARRAY_SIZE = NPC_SLOT_COUNT * NPC_RECORD_SIZE
NPC_CONTROL_FLAG_NAMES = {
    1: "invincible",
    2: "ascending",
    4: "descending",
    8: "anim_lock",
    # ANIMPRIM.C fail() sets this latch; non-stand initialize() clears it.
    16: "animation_failed",
}
NPC_STATE_FLAG_NAMES = {
    0x0001: "in_use",
    0x0002: "falling",
    0x0004: "first_step",
    0x0008: "in_combat",
    0x0010: "dead",
    # ANIMPRIM.C weaponCheck() records contact, suppressing later hit checks.
    0x0020: "weapon_hit",
    0x0040: "combat_pending",
    0x0080: "balancing",
    0x0100: "air_walk",
    0x0200: "swinging",
    0x0400: "immortal",
    0x0800: "withstand_death",
    0x1000: "feign_death",
    0x2000: "stunned",
    0x4000: "poisoned",
    0x8000: "pathfinding",
}


class U8NpcDataError(ValueError):
    """NPCDATA.DAT has an invalid container or truncated native NPC array."""


@dataclass(frozen=True)
class U8NpcState:
    """One native slot; stats use decoded signed chars, HP and direction use bytes."""

    npc_id: int
    raw: bytes
    strength: int
    dexterity: int
    intelligence: int
    hitpoints: int
    direction: int
    last_action: int
    frame_hi: int
    animation_step: int
    fall_start_z: int
    unknown_0a: int
    alignment_raw: int
    unknown_0c_1a: bytes
    control_flags: int
    equipment: tuple[int, ...]
    mana: int
    state_flags: int

    @property
    def alignment(self) -> int:
        return self.alignment_raw & 15

    @property
    def enemy_alignment(self) -> int:
        """Unshifted enemy mask, as consumed by the original alignment getter."""
        return self.alignment_raw & 0xF0

    @property
    def in_use(self) -> bool:
        """Stored flag only; it does not identify every NPC in the initial save."""
        return bool(self.state_flags & 1)

    def flag_names(self) -> list[str]:
        return [
            name
            for bit, name in NPC_CONTROL_FLAG_NAMES.items()
            if self.control_flags & bit
        ] + [
            name for bit, name in NPC_STATE_FLAG_NAMES.items() if self.state_flags & bit
        ]

    def full_frame(self, frame_low: int) -> int:
        """Combine the corresponding ITEMCACH low byte with this NPC's high byte."""
        if not 0 <= frame_low <= 255:
            raise U8NpcDataError("NPCDATA.DAT: frame low byte must be 0-255")
        return frame_low | (self.frame_hi << 8)


class U8NpcData:
    """All native NPC slots, including padding/state residue and record tail."""

    def __init__(
        self, data: bytes, npcs: tuple[U8NpcState, ...], trailing_bytes: bytes
    ) -> None:
        self._data = data
        self.npcs = npcs
        self.trailing_bytes = trailing_bytes

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8NpcData:
        """Read loose NPCDATA.DAT or its named entry in a native U8 save archive."""
        try:
            return cls.from_bytes(read_u8_state_bytes(filepath, "NPCDATA.DAT"))
        except ValueError as error:
            raise U8NpcDataError(str(error)) from error

    @classmethod
    def from_bytes(cls, data: bytes) -> U8NpcData:
        """Parse exactly 256 records; preserve additional record bytes without guessing."""
        try:
            archive = parse_u8_state_flex(data, "NPCDATA.DAT", 1)
        except ValueError as error:
            raise U8NpcDataError(str(error)) from error
        record = archive.records[0]
        if len(record) < NPC_ARRAY_SIZE:
            raise U8NpcDataError("NPCDATA.DAT: truncated 256-slot NPC array")
        npcs = []
        for npc_id in range(NPC_SLOT_COUNT):
            raw = record[npc_id * NPC_RECORD_SIZE : (npc_id + 1) * NPC_RECORD_SIZE]
            strength, dexterity, intelligence, hp, direction, action = (
                struct.unpack_from("<bbbBBH", raw)
            )
            npcs.append(
                U8NpcState(
                    npc_id=npc_id,
                    raw=raw,
                    strength=strength,
                    dexterity=dexterity,
                    intelligence=intelligence,
                    hitpoints=hp,
                    direction=direction,
                    last_action=action,
                    frame_hi=raw[7],
                    animation_step=raw[8],
                    fall_start_z=raw[9],
                    unknown_0a=raw[10],
                    alignment_raw=raw[11],
                    unknown_0c_1a=raw[12:27],
                    control_flags=struct.unpack_from("<H", raw, 27)[0],
                    equipment=struct.unpack_from("<8H", raw, 29),
                    mana=struct.unpack_from("<h", raw, 45)[0],
                    state_flags=struct.unpack_from("<H", raw, 47)[0],
                )
            )
        return cls(data, tuple(npcs), record[NPC_ARRAY_SIZE:])

    def get_npc(self, npc_id: int) -> U8NpcState:
        """Return a native slot including unused data; reject IDs outside 0-255."""
        if not 0 <= npc_id < NPC_SLOT_COUNT:
            raise U8NpcDataError("NPCDATA.DAT: NPC ID must be 0-255")
        return self.npcs[npc_id]

    def iter_npcs(self) -> Iterator[U8NpcState]:
        """Yield every slot in native order; occupancy requires ITEMCACH context."""
        return iter(self.npcs)

    def to_bytes(self) -> bytes:
        """Return the exact native NPCDATA file, not its containing save archive."""
        return self._data
