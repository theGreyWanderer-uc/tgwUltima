"""Tests for titan.u6.schedule's SCHEDULE decoder.

No real game files are used here -- fixtures are hand-built to match the
layout confirmed against Nuvie's ActorManager::loadActorSchedules and
Actor::loadSchedule (see titan/u6/schedule.py's module docstring for the
real-data validation: a real SCHEDULE's header/entry-count sizes are
exactly self-consistent, and decoded entries show a coherent daily
routine -- an NPC sitting, walking to eat at noon, then sitting again).
"""

from __future__ import annotations

import struct
import unittest

from titan.u6.object import pack_position
from titan.u6.schedule import U6ScheduleError, U6Schedules


def _make_entry(hour: int, day_of_week: int, worktype: int, x: int, y: int, z: int) -> bytes:
    b0 = (hour & 0x1F) | ((day_of_week & 0x07) << 5)
    h, p1, p2 = pack_position(x, y, z)
    return bytes([b0, worktype, h, p1, p2])


def _make_schedule(num_actors: int, per_actor_entries: dict[int, list[bytes]]) -> bytes:
    """per_actor_entries: {actor_id: [entry_bytes, ...]}, in actor-id order for offset assignment."""
    all_entries = bytearray()
    offsets = [0] * num_actors
    cursor = 0
    for actor_id in range(num_actors):
        entries = per_actor_entries.get(actor_id, [])
        if not entries:
            offsets[actor_id] = 0xFFFF  # sentinel: no schedule (matches Nuvie's out-of-range check)
            continue
        offsets[actor_id] = cursor
        for e in entries:
            all_entries += e
            cursor += 1
    total = cursor
    header = b"".join(o.to_bytes(2, "little") for o in offsets) + struct.pack("<H", total)
    return header + bytes(all_entries)


class ParseTests(unittest.TestCase):
    def test_rejects_short_data(self):
        # 4 actors need a 10-byte header (4*2 + 2); 9 bytes isn't enough.
        with self.assertRaises(U6ScheduleError):
            U6Schedules.parse(b"\x00" * 9, num_actors=4)

    def test_rejects_inconsistent_entry_count(self):
        # Header claims 5 entries but no entry data follows.
        header = bytes(4 * 2) + struct.pack("<H", 5)
        with self.assertRaises(U6ScheduleError):
            U6Schedules.parse(header, num_actors=4)

    def test_actor_with_no_schedule_is_empty(self):
        data = _make_schedule(4, {})
        schedules = U6Schedules.parse(data, num_actors=4)
        for i in range(4):
            self.assertEqual(schedules.for_actor(i), [])


class EntryDecodeTests(unittest.TestCase):
    def test_single_entry_fields_decode_correctly(self):
        entry = _make_entry(hour=8, day_of_week=2, worktype=146, x=307, y=348, z=0)
        data = _make_schedule(2, {0: [entry]})
        schedules = U6Schedules.parse(data, num_actors=2)
        e = schedules.for_actor(0)[0]
        self.assertEqual(e.hour, 8)
        self.assertEqual(e.day_of_week, 2)
        self.assertEqual(e.worktype, 146)
        self.assertEqual((e.x, e.y, e.z), (307, 348, 0))

    def test_hour_and_day_share_one_byte_correctly(self):
        # hour uses the low 5 bits (0-31), day_of_week the top 3 (0-7).
        entry = _make_entry(hour=23, day_of_week=6, worktype=0, x=0, y=0, z=0)
        data = _make_schedule(1, {0: [entry]})
        e = U6Schedules.parse(data, num_actors=1).for_actor(0)[0]
        self.assertEqual(e.hour, 23)
        self.assertEqual(e.day_of_week, 6)


class MultiActorTests(unittest.TestCase):
    def test_entries_assigned_to_correct_actors_in_order(self):
        e0a = _make_entry(8, 0, 146, 307, 348, 0)
        e0b = _make_entry(12, 0, 147, 316, 367, 0)
        e1a = _make_entry(0, 0, 154, 316, 354, 0)
        data = _make_schedule(3, {0: [e0a, e0b], 1: [e1a]})
        schedules = U6Schedules.parse(data, num_actors=3)

        self.assertEqual(len(schedules.for_actor(0)), 2)
        self.assertEqual(schedules.for_actor(0)[0].worktype, 146)
        self.assertEqual(schedules.for_actor(0)[1].worktype, 147)

        self.assertEqual(len(schedules.for_actor(1)), 1)
        self.assertEqual(schedules.for_actor(1)[0].worktype, 154)

        self.assertEqual(schedules.for_actor(2), [])

    def test_last_actor_takes_all_remaining_entries(self):
        e_a = _make_entry(1, 0, 1, 1, 1, 0)
        e_b = _make_entry(2, 0, 2, 2, 2, 0)
        data = _make_schedule(2, {1: [e_a, e_b]})
        schedules = U6Schedules.parse(data, num_actors=2)
        self.assertEqual(schedules.for_actor(0), [])
        self.assertEqual(len(schedules.for_actor(1)), 2)


if __name__ == "__main__":
    unittest.main()
