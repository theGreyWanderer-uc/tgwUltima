"""Tests for titan.u6.actor's NPC/actor identity table (the objlist structure).

No real game files are used here -- the fixture is a hand-built buffer
matching the fixed-offset table-of-arrays layout confirmed against
Nuvie's ActorManager::load (see titan/u6/actor.py's module docstring for
the real-data validation: actors 1-9 cluster tightly around Lord
British's Castle, matching where a new game starts).
"""

from __future__ import annotations

import struct
import unittest

from titan.u6.actor import (
    NUM_ACTORS,
    OFFSET_APPEARANCE,
    OFFSET_BASE_APPEARANCE,
    OFFSET_COMBAT_MODE,
    OFFSET_DEXTERITY,
    OFFSET_EXPERIENCE,
    OFFSET_HP,
    OFFSET_INTELLIGENCE,
    OFFSET_LEVEL,
    OFFSET_MAGIC,
    OFFSET_MOVEMENT_FLAGS,
    OFFSET_OBJ_FLAGS,
    OFFSET_POSITION,
    OFFSET_STATUS_FLAGS,
    OFFSET_STRENGTH,
    OFFSET_TALK_FLAGS,
    REQUIRED_SIZE,
    STATUS_DEAD,
    STATUS_IN_PARTY,
    U6ActorError,
    U6Actors,
)
from titan.u6.object import pack_position


def _make_objlist(overrides: dict[int, int | tuple] | None = None) -> bytearray:
    """Build a minimal-but-complete objlist buffer, all zeros except overrides.

    overrides: {actor_id: value} applied uniformly isn't flexible enough, so
    instead each test writes directly into the returned buffer at the
    relevant offset for the actor(s) it cares about.
    """
    return bytearray(REQUIRED_SIZE)


def _set_position(buf: bytearray, actor_id: int, x: int, y: int, z: int) -> None:
    b0, b1, b2 = pack_position(x, y, z)
    off = OFFSET_POSITION + actor_id * 3
    buf[off:off + 3] = bytes([b0, b1, b2])


def _set_appearance(buf: bytearray, actor_id: int, obj_n: int, frame_n: int, offset: int = OFFSET_APPEARANCE) -> None:
    b1 = obj_n & 0xFF
    b2 = ((obj_n >> 8) & 0x03) | ((frame_n << 2) & 0xFC)
    off = offset + actor_id * 2
    buf[off:off + 2] = bytes([b1, b2])


class ParseTests(unittest.TestCase):
    def test_rejects_short_data(self):
        with self.assertRaises(U6ActorError):
            U6Actors.parse(b"\x00" * 100)

    def test_parses_all_256_actors(self):
        buf = _make_objlist()
        actors = U6Actors.parse(bytes(buf))
        self.assertEqual(len(actors), NUM_ACTORS)
        self.assertEqual([a.actor_id for a in actors], list(range(NUM_ACTORS)))

    def test_inactive_by_default(self):
        buf = _make_objlist()
        actors = U6Actors.parse(bytes(buf))
        self.assertFalse(actors[0].is_active)


class PositionAndAppearanceTests(unittest.TestCase):
    def test_position_decodes_correctly(self):
        buf = _make_objlist()
        _set_position(buf, 5, 308, 364, 0)
        actor = U6Actors.parse(bytes(buf))[5]
        self.assertEqual((actor.x, actor.y, actor.z), (308, 364, 0))

    def test_appearance_decodes_correctly(self):
        buf = _make_objlist()
        _set_appearance(buf, 5, obj_n=416, frame_n=3)
        actor = U6Actors.parse(bytes(buf))[5]
        self.assertEqual(actor.obj_n, 416)
        self.assertEqual(actor.frame_n, 3)
        self.assertTrue(actor.is_active)

    def test_base_appearance_separate_from_live_appearance(self):
        buf = _make_objlist()
        _set_appearance(buf, 5, obj_n=416, frame_n=3, offset=OFFSET_APPEARANCE)
        _set_appearance(buf, 5, obj_n=100, frame_n=1, offset=OFFSET_BASE_APPEARANCE)
        actor = U6Actors.parse(bytes(buf))[5]
        self.assertEqual(actor.obj_n, 416)
        self.assertEqual(actor.base_obj_n, 100)
        self.assertEqual(actor.old_frame_n, 1)

    def test_tile_num_uses_basetile_plus_frame(self):
        buf = _make_objlist()
        _set_appearance(buf, 5, obj_n=2, frame_n=1)
        actor = U6Actors.parse(bytes(buf))[5]
        basetile = tuple([0, 0, 500])  # BASETILE[2] = 500
        self.assertEqual(actor.tile_num(basetile), 501)


class StatTableTests(unittest.TestCase):
    def test_each_stat_reads_from_its_own_offset(self):
        buf = _make_objlist()
        actor_id = 42
        buf[OFFSET_OBJ_FLAGS + actor_id] = 0x01
        buf[OFFSET_STRENGTH + actor_id] = 50
        buf[OFFSET_DEXTERITY + actor_id] = 60
        buf[OFFSET_INTELLIGENCE + actor_id] = 70
        struct.pack_into("<H", buf, OFFSET_EXPERIENCE + actor_id * 2, 12345)
        buf[OFFSET_HP + actor_id] = 99
        buf[OFFSET_LEVEL + actor_id] = 7
        buf[OFFSET_COMBAT_MODE + actor_id] = 2
        buf[OFFSET_MAGIC + actor_id] = 30
        buf[OFFSET_TALK_FLAGS + actor_id] = 0xAB
        buf[OFFSET_MOVEMENT_FLAGS + actor_id] = 0xCD

        actor = U6Actors.parse(bytes(buf))[actor_id]
        self.assertEqual(actor.obj_flags, 0x01)
        self.assertEqual(actor.strength, 50)
        self.assertEqual(actor.dexterity, 60)
        self.assertEqual(actor.intelligence, 70)
        self.assertEqual(actor.experience, 12345)
        self.assertEqual(actor.hp, 99)
        self.assertEqual(actor.level, 7)
        self.assertEqual(actor.combat_mode, 2)
        self.assertEqual(actor.magic, 30)
        self.assertEqual(actor.talk_flags, 0xAB)
        self.assertEqual(actor.movement_flags, 0xCD)

    def test_stats_are_independent_per_actor(self):
        buf = _make_objlist()
        buf[OFFSET_HP + 0] = 10
        buf[OFFSET_HP + 1] = 200
        actors = U6Actors.parse(bytes(buf))
        self.assertEqual(actors[0].hp, 10)
        self.assertEqual(actors[1].hp, 200)


class StatusFlagAndAlignmentTests(unittest.TestCase):
    def test_alignment_formula(self):
        buf = _make_objlist()
        for alignment_bits, expected in [(0x00, 1), (0x20, 2), (0x40, 3), (0x60, 4)]:
            buf[OFFSET_STATUS_FLAGS + 0] = alignment_bits
            actor = U6Actors.parse(bytes(buf))[0]
            self.assertEqual(actor.alignment, expected)

    def test_is_dead(self):
        buf = _make_objlist()
        buf[OFFSET_STATUS_FLAGS + 0] = STATUS_DEAD
        actor = U6Actors.parse(bytes(buf))[0]
        self.assertTrue(actor.is_dead)

    def test_is_in_party_bit(self):
        buf = _make_objlist()
        buf[OFFSET_STATUS_FLAGS + 0] = STATUS_IN_PARTY
        actor0 = U6Actors.parse(bytes(buf))[0]
        self.assertTrue(actor0.is_in_party)

        buf[OFFSET_STATUS_FLAGS + 1] = 0x20  # unrelated bit (part of the alignment mask)
        actor1 = U6Actors.parse(bytes(buf))[1]
        self.assertFalse(actor1.is_in_party)


class TalkFlagTests(unittest.TestCase):
    def test_has_talk_flag_bit_test(self):
        buf = _make_objlist()
        buf[OFFSET_TALK_FLAGS + 0] = 0b00100100  # bits 2 and 5 set
        actor = U6Actors.parse(bytes(buf))[0]
        for i in range(8):
            self.assertEqual(actor.has_talk_flag(i), i in (2, 5), f"bit {i}")

    def test_has_talk_flag_rejects_out_of_range_index(self):
        buf = _make_objlist()
        actor = U6Actors.parse(bytes(buf))[0]
        with self.assertRaises(ValueError):
            actor.has_talk_flag(8)
        with self.assertRaises(ValueError):
            actor.has_talk_flag(-1)

    def test_is_met_is_bit_zero(self):
        buf = _make_objlist()
        buf[OFFSET_TALK_FLAGS + 0] = 0x01
        actor = U6Actors.parse(bytes(buf))[0]
        self.assertTrue(actor.is_met)

    def test_is_met_false_by_default(self):
        buf = _make_objlist()
        actor = U6Actors.parse(bytes(buf))[0]
        self.assertFalse(actor.is_met)


if __name__ == "__main__":
    unittest.main()
