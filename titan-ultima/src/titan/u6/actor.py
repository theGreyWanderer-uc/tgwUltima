"""
NPC/actor identity table for Ultima 6 (the ``objlist`` structure).

Not documented in ``u6data/u6tech.txt`` at all. ``objlist`` is embedded at
the tail of the decompressed ``LZDNGBLK`` stream for a new game (see
:meth:`titan.u6.object.U6WorldObjects.from_parts`, whose ``objlist_tail``
is this module's input) -- confirmed directly: the byte count remaining
after ``LZDNGBLK``'s 5 dungeon object blocks (7283 bytes, real install)
matches Nuvie's documented table layout (``save/Objlist.h``) almost
exactly, and every field below is read at the exact offset Nuvie's
``ActorManager::load`` uses.

``objlist`` is actually the *entire* save-game state (party roster, game
clock, weather, player karma, etc.) -- this module deliberately covers
only the per-actor identity/placement fields (position, appearance,
stats), not that broader state, which is a different concern.

Layout (fixed-offset table-of-arrays, one 256-entry array per field;
NUM_ACTORS = 256 actor slots, IDs 0-255)::

    0x0000  obj_flags:      u8 x 256
    0x0100  position:       3 bytes x 256 (packed, same scheme as
                             titan.u6.object.unpack_position)
    0x0400  appearance:     2 bytes x 256 (packed obj_n + frame_n, same
                             bit layout as an object record's type field)
    0x0800  status_flags:   u8 x 256  (alignment is 2 bits within this)
    0x0900  strength:       u8 x 256
    0x0a00  dexterity:      u8 x 256
    0x0b00  intelligence:   u8 x 256
    0x0c00  experience:     u16 x 256 (little-endian)
    0x0e00  hp:             u8 x 256
    0x0ff1  level:          u8 x 256
    0x12f1  combat_mode:    u8 x 256
    0x13f1  magic:          u8 x 256
    0x15f1  base appearance ("old" obj_n/frame_n, used as a fallback
             when the live appearance is hidden): 2 bytes x 256
    0x17f1  talk_flags:     u8 x 256
    0x19f1  movement_flags: u8 x 256

Gaps between tables (e.g. 0x0f00-0x0ff1) belong to the broader
save-game state (party names/roster at 0x0f00, etc.) -- see
:mod:`titan.u6.gamestate`, which covers that part of the same buffer.

``talk_flags`` is more than just a name: it's the exact per-actor
register CONVERSE scripts read and write through the ``flag(npc, index)``
function and ``SETF``/``CLEARF`` opcodes (see :mod:`titan.u6.converse`),
confirmed directly against Nuvie's ``ConverseInterpret.cpp``. Bit 0
specifically means "has the player met this NPC" (Nuvie's own
``Actor::is_met``). :meth:`U6Actor.has_talk_flag` and
:attr:`U6Actor.is_met` expose this.

Validated against a real GOG-style install: zero actors decode with an
invalid z (>5); actors 1-9 (likely the starting party and castle staff)
cluster tightly around world (305-333, 348-407) -- essentially on top of
Lord British's Castle at (308, 364), matching where a new game starts;
alignment, hp, and level all decode to plausible ranges.

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.object import U6WorldObjects
    from titan.u6.actor import U6Actors

    world = U6WorldObjects.from_directory("C:/Ultima/Ultima6")
    actors = U6Actors.parse(world.objlist_tail)
    for a in actors:
        if a.obj_n != 0:
            print(a.actor_id, a.x, a.y, a.z, a.hp, a.level)
"""

from __future__ import annotations

__all__ = ["U6Actor", "U6Actors", "U6ActorError"]

import struct
from dataclasses import dataclass

from titan.u6.object import unpack_position

NUM_ACTORS = 256

OFFSET_OBJ_FLAGS = 0x0000
OFFSET_POSITION = 0x0100
OFFSET_APPEARANCE = 0x0400
OFFSET_STATUS_FLAGS = 0x0800
OFFSET_STRENGTH = 0x0900
OFFSET_DEXTERITY = 0x0A00
OFFSET_INTELLIGENCE = 0x0B00
OFFSET_EXPERIENCE = 0x0C00
OFFSET_HP = 0x0E00
OFFSET_LEVEL = 0x0FF1
OFFSET_COMBAT_MODE = 0x12F1
OFFSET_MAGIC = 0x13F1
OFFSET_BASE_APPEARANCE = 0x15F1
OFFSET_TALK_FLAGS = 0x17F1
OFFSET_MOVEMENT_FLAGS = 0x19F1

REQUIRED_SIZE = OFFSET_MOVEMENT_FLAGS + NUM_ACTORS  # smallest buffer this module can fully read

# Status flag bits (confirmed against Nuvie's Actor.h)
STATUS_PROTECTED = 0x01
STATUS_PARALYZED = 0x02
STATUS_ASLEEP = 0x04
STATUS_POISONED = 0x08
STATUS_DEAD = 0x10
STATUS_ATTACK_EVIL = 0x20
STATUS_ATTACK_GOOD = 0x40
STATUS_IN_PARTY = 0x80
STATUS_ALIGNMENT_MASK = 0x60


class U6ActorError(Exception):
    """Raised when objlist data is too short to contain the actor tables."""


@dataclass
class U6Actor:
    """One actor (NPC/monster/party member) slot, 0-255."""

    actor_id: int
    x: int
    y: int
    z: int
    obj_n: int
    frame_n: int
    obj_flags: int
    status_flags: int
    strength: int
    dexterity: int
    intelligence: int
    experience: int
    hp: int
    level: int
    combat_mode: int
    magic: int
    base_obj_n: int
    old_frame_n: int
    talk_flags: int
    movement_flags: int

    @property
    def alignment(self) -> int:
        """1-4 (Nuvie: ``((status_flags & 0x60) >> 5) + 1``)."""
        return ((self.status_flags & STATUS_ALIGNMENT_MASK) >> 5) + 1

    @property
    def is_active(self) -> bool:
        """Whether this slot has a real appearance (``obj_n != 0``); most unused slots are 0."""
        return self.obj_n != 0

    @property
    def is_dead(self) -> bool:
        return bool(self.status_flags & STATUS_DEAD)

    @property
    def is_in_party(self) -> bool:
        return (self.status_flags & STATUS_IN_PARTY) == STATUS_IN_PARTY

    @property
    def is_poisoned(self) -> bool:
        return bool(self.status_flags & STATUS_POISONED)

    @property
    def is_asleep(self) -> bool:
        return bool(self.status_flags & STATUS_ASLEEP)

    @property
    def is_paralyzed(self) -> bool:
        return bool(self.status_flags & STATUS_PARALYZED)

    @property
    def is_protected(self) -> bool:
        return bool(self.status_flags & STATUS_PROTECTED)

    def has_talk_flag(self, index: int) -> bool:
        """
        Test one of this actor's 8 CONVERSE quest/narrative flags (0-7).

        This is exactly the register CONVERSE scripts read and write via
        the ``flag(npc, index)`` function and the ``SETF``/``CLEARF``
        opcodes (see :mod:`titan.u6.converse`) -- confirmed directly
        against Nuvie's ``ConverseInterpret.cpp``, whose ``U6OP_FLAG``
        case tests ``get_talk_flags() & (1 << index)`` for ``index <= 7``,
        and whose ``Actor.h`` defines bit 0 specifically as "has the
        player met this NPC" (see :attr:`is_met`).
        """
        if index < 0 or index > 7:
            raise ValueError(f"talk flag index must be 0-7, got {index}")
        return bool(self.talk_flags & (1 << index))

    @property
    def is_met(self) -> bool:
        """Whether the player has met this NPC before (talk flag bit 0; Nuvie's ``Actor::is_met``)."""
        return self.has_talk_flag(0)

    def tile_num(self, basetile: tuple[int, ...]) -> int:
        """Actual MAPTILES/OBJTILES tile number: ``BASETILE[obj_n] + frame_n``."""
        return basetile[self.obj_n] + self.frame_n


class U6Actors:
    """Parser for the actor identity tables within ``objlist``."""

    @classmethod
    def parse(cls, data: bytes) -> list[U6Actor]:
        if len(data) < REQUIRED_SIZE:
            raise U6ActorError(f"objlist data too short: {len(data)} bytes, need at least {REQUIRED_SIZE}")

        def bytes_at(offset: int) -> bytes:
            return data[offset:offset + NUM_ACTORS]

        obj_flags = bytes_at(OFFSET_OBJ_FLAGS)
        status_flags = bytes_at(OFFSET_STATUS_FLAGS)
        strength = bytes_at(OFFSET_STRENGTH)
        dexterity = bytes_at(OFFSET_DEXTERITY)
        intelligence = bytes_at(OFFSET_INTELLIGENCE)
        experience = struct.unpack_from(f"<{NUM_ACTORS}H", data, OFFSET_EXPERIENCE)
        hp = bytes_at(OFFSET_HP)
        level = bytes_at(OFFSET_LEVEL)
        combat_mode = bytes_at(OFFSET_COMBAT_MODE)
        magic = bytes_at(OFFSET_MAGIC)
        talk_flags = bytes_at(OFFSET_TALK_FLAGS)
        movement_flags = bytes_at(OFFSET_MOVEMENT_FLAGS)

        actors: list[U6Actor] = []
        for i in range(NUM_ACTORS):
            pos_off = OFFSET_POSITION + i * 3
            x, y, z = unpack_position(data[pos_off], data[pos_off + 1], data[pos_off + 2])

            app_off = OFFSET_APPEARANCE + i * 2
            b1, b2 = data[app_off], data[app_off + 1]
            obj_n = b1 | ((b2 & 0x03) << 8)
            frame_n = (b2 & 0xFC) >> 2

            base_off = OFFSET_BASE_APPEARANCE + i * 2
            bb1, bb2 = data[base_off], data[base_off + 1]
            base_obj_n = bb1 | ((bb2 & 0x03) << 8)
            old_frame_n = (bb2 & 0xFC) >> 2

            actors.append(U6Actor(
                actor_id=i,
                x=x, y=y, z=z,
                obj_n=obj_n, frame_n=frame_n,
                obj_flags=obj_flags[i],
                status_flags=status_flags[i],
                strength=strength[i],
                dexterity=dexterity[i],
                intelligence=intelligence[i],
                experience=experience[i],
                hp=hp[i],
                level=level[i],
                combat_mode=combat_mode[i],
                magic=magic[i],
                base_obj_n=base_obj_n,
                old_frame_n=old_frame_n,
                talk_flags=talk_flags[i],
                movement_flags=movement_flags[i],
            ))
        return actors
