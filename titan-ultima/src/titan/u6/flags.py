"""
Story-flag read/compare/write tool for Ultima 6.

Ties together :mod:`titan.u6.actor`'s per-NPC ``talk_flags`` (256 actors x
8 bits -- the CONVERSE quest/narrative flag register, see that module's
docstring) and :mod:`titan.u6.gamestate`'s two true global bytes
(``quest_flag``, ``knows_gargish``) into one read/compare/write surface,
operating directly on raw ``objlist`` bytes
(:attr:`titan.u6.object.U6WorldObjects.objlist_tail`, whether that comes
from a fresh install's ``LZOBJBLK``/``LZDNGBLK`` or a real save's
``SAVEGAME/OBJLIST`` -- both share the exact same byte layout).

Ultima 6 does *not* have one big "global flags" table distinct from
per-NPC flags: confirmed against Nuvie's own documentation
(``docs/ultima6/u6converse.txt``'s CONVERSE globals table) and
``Converse.cpp`` (``player->set_quest_flag((uint8)get_var(U6TALK_VAR_QUESTF))``)
-- the single ``quest_flag`` byte at 0x1bf1 is a one-bit boolean ("on a
quest: yes/no", CONVERSE global variable ``$1a``), not a bitmask of many
story milestones. The *real* distributed story-state mechanism is each of
the 256 actors' independent 8-bit ``talk_flags`` register (see
:meth:`titan.u6.actor.U6Actor.has_talk_flag`/:attr:`~titan.u6.actor.U6Actor.is_met`),
each bit independently settable via CONVERSE's ``SETF``/``CLEARF``
opcodes and readable via ``flag(index)`` -- this is what actually encodes
"has this happened yet" for nearly every quest/conversation branch in the
game. This module treats "story flags" as that combined surface: every
actor's 8 talk-flag bits, plus ``quest_flag`` and ``knows_gargish``.

This is the first *write* path in ``titan.u6`` -- every other module is
read-only extraction. :func:`set_talk_flag`/:func:`set_quest_flag`/
:func:`set_gargish_flag` mutate a ``bytearray`` in place and return it;
callers choose whether/where to persist it (see ``titan.u6.cli``'s
``flags-set``, which writes a fresh ``OBJLIST`` file alongside the
original by default rather than silently overwriting a real save).

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.object import U6WorldObjects
    from titan.u6.flags import read_talk_flags, compare_flags

    before = U6WorldObjects.from_savegame("saves/slot1").objlist_tail
    after = U6WorldObjects.from_savegame("saves/slot2").objlist_tail
    for diff in compare_flags(before, after):
        print(diff)
"""

from __future__ import annotations

__all__ = [
    "U6FlagDiff",
    "U6FlagsError",
    "read_talk_flags",
    "set_talk_flag",
    "set_quest_flag",
    "set_gargish_flag",
    "compare_flags",
]

from dataclasses import dataclass

from titan.u6.actor import NUM_ACTORS, OFFSET_TALK_FLAGS, U6Actors
from titan.u6.gamestate import OFFSET_GARGISH_LANG, OFFSET_QUEST_FLAG, U6GameState


class U6FlagsError(Exception):
    """Raised for an out-of-range actor/flag index, or objlist data too short to reach it."""


def read_talk_flags(objlist: bytes) -> dict[int, int]:
    """Every actor's raw 8-bit ``talk_flags`` byte, keyed by actor ID (0-255)."""
    actors = U6Actors.parse(objlist)
    return {a.actor_id: a.talk_flags for a in actors}


def set_talk_flag(objlist: bytearray, actor_id: int, index: int, value: bool) -> bytearray:
    """Set (``True``) or clear (``False``) one of an actor's 8 talk-flag bits, in place."""
    if not 0 <= actor_id < NUM_ACTORS:
        raise U6FlagsError(f"actor_id must be 0-{NUM_ACTORS - 1}, got {actor_id}")
    if not 0 <= index <= 7:
        raise U6FlagsError(f"talk flag index must be 0-7, got {index}")
    off = OFFSET_TALK_FLAGS + actor_id
    if off >= len(objlist):
        raise U6FlagsError(f"objlist data too short to reach actor {actor_id}'s talk_flags")
    if value:
        objlist[off] |= (1 << index)
    else:
        objlist[off] &= ~(1 << index) & 0xFF
    return objlist


def set_quest_flag(objlist: bytearray, value: int) -> bytearray:
    """Set the single global ``quest_flag`` byte (CONVERSE global ``$1a``: 0/1 = off a quest / on a quest)."""
    if OFFSET_QUEST_FLAG >= len(objlist):
        raise U6FlagsError("objlist data too short to reach quest_flag")
    objlist[OFFSET_QUEST_FLAG] = value & 0xFF
    return objlist


def set_gargish_flag(objlist: bytearray, value: bool) -> bytearray:
    """Set whether the player knows Gargish."""
    if OFFSET_GARGISH_LANG >= len(objlist):
        raise U6FlagsError("objlist data too short to reach the Gargish-language flag")
    objlist[OFFSET_GARGISH_LANG] = 1 if value else 0
    return objlist


@dataclass
class U6FlagDiff:
    """One difference found by :func:`compare_flags`."""

    kind: str  # "talk_flag", "quest_flag", or "gargish_flag"
    actor_id: int | None  # only set for kind == "talk_flag"
    bit: int | None  # only set for kind == "talk_flag"
    before: int
    after: int

    def __str__(self) -> str:
        if self.kind == "talk_flag":
            action = "set" if self.after else "cleared"
            return f"actor {self.actor_id} talk_flag bit {self.bit} {action}"
        return f"{self.kind} changed {self.before} -> {self.after}"


def compare_flags(a: bytes, b: bytes) -> list[U6FlagDiff]:
    """Diff two ``objlist`` buffers' story-flag state (``talk_flags``, ``quest_flag``, ``knows_gargish``)."""
    a_flags = read_talk_flags(a)
    b_flags = read_talk_flags(b)
    diffs: list[U6FlagDiff] = []
    for actor_id in range(NUM_ACTORS):
        changed = a_flags[actor_id] ^ b_flags[actor_id]
        if not changed:
            continue
        for bit in range(8):
            if changed & (1 << bit):
                diffs.append(U6FlagDiff(
                    kind="talk_flag", actor_id=actor_id, bit=bit,
                    before=(a_flags[actor_id] >> bit) & 1,
                    after=(b_flags[actor_id] >> bit) & 1,
                ))

    a_state = U6GameState.parse(a)
    b_state = U6GameState.parse(b)
    if a_state.player.quest_flag != b_state.player.quest_flag:
        diffs.append(U6FlagDiff(
            kind="quest_flag", actor_id=None, bit=None,
            before=a_state.player.quest_flag, after=b_state.player.quest_flag,
        ))
    if a_state.player.knows_gargish != b_state.player.knows_gargish:
        diffs.append(U6FlagDiff(
            kind="gargish_flag", actor_id=None, bit=None,
            before=int(a_state.player.knows_gargish), after=int(b_state.player.knows_gargish),
        ))
    return diffs
