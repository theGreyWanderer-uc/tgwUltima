"""
NPC schedule decoder for Ultima 6 (``SCHEDULE``).

Not documented in ``u6data/u6tech.txt``. Built from and confirmed
field-for-field against Nuvie's ``ActorManager::loadActorSchedules`` and
``Actor::loadSchedule``. Validated against a real ``SCHEDULE`` (3329
bytes): the header sizes and entry count are exactly self-consistent
(``256 actors * 2 bytes + 2 count bytes + 563 entries * 5 bytes ==
3329``, matching the file size precisely).

Layout::

    offset table: u16 x 256, little-endian -- one per actor (0-255),
                  the *entry index* (not byte offset) where that actor's
                  schedule begins
    total_count:  u16 -- total number of schedule entries across all actors
    entries:      total_count x 5-byte records

    entry = hour_and_day: u8, worktype: u8, h: u8, b1: u8, b2: u8

    hour = hour_and_day & 0x1f          # 5 bits
    day_of_week = hour_and_day >> 5     # 3 bits
    x, y, z = unpack_position(h, b1, b2)  # same packing as titan.u6.object

An actor's entry count is the gap to the *next* actor's offset (the same
"next offset determines length" trick used throughout this project --
MAP's superchunks, U6Lib_n's items). An offset >= total_count means "no
schedule"; Nuvie treats that case, and a last-actor/next-offset-invalid
case, specially -- both replicated here exactly (see
:meth:`U6Schedules.parse`).

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.schedule import U6Schedules

    schedules = U6Schedules.from_file("C:/Ultima/Ultima6/SCHEDULE")
    for entry in schedules.for_actor(1):
        print(entry.hour, entry.worktype, entry.x, entry.y, entry.z)
"""

from __future__ import annotations

__all__ = ["U6Schedules", "U6ScheduleEntry", "U6ScheduleError", "NUM_ACTORS"]

import os
import struct
from dataclasses import dataclass

from titan.u6.object import unpack_position

NUM_ACTORS = 256
ENTRY_SIZE = 5
HEADER_SIZE = NUM_ACTORS * 2 + 2  # offset table + total_count


class U6ScheduleError(Exception):
    """Raised when SCHEDULE data is too short or internally inconsistent."""


@dataclass
class U6ScheduleEntry:
    """One schedule entry: at ``hour`` on ``day_of_week``, do ``worktype`` at (x, y, z)."""

    hour: int
    day_of_week: int
    worktype: int
    x: int
    y: int
    z: int


class U6Schedules:
    """Per-actor schedule lists, indexed by actor ID (0-255)."""

    def __init__(self, per_actor: list[list[U6ScheduleEntry]]) -> None:
        self.per_actor = per_actor

    def for_actor(self, actor_id: int) -> list[U6ScheduleEntry]:
        return self.per_actor[actor_id]

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str], num_actors: int = NUM_ACTORS) -> U6Schedules:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data, num_actors=num_actors)

    @classmethod
    def parse(cls, data: bytes, num_actors: int = NUM_ACTORS) -> U6Schedules:
        header_size = num_actors * 2 + 2
        if len(data) < header_size:
            raise U6ScheduleError(f"SCHEDULE data too short: {len(data)} bytes, need at least {header_size}")

        offsets = struct.unpack_from(f"<{num_actors}H", data, 0)
        total = struct.unpack_from("<H", data, num_actors * 2)[0]

        entries_start = header_size
        needed = entries_start + total * ENTRY_SIZE
        if len(data) < needed:
            raise U6ScheduleError(f"SCHEDULE data too short for {total} entries: {len(data)} bytes, need {needed}")

        entries: list[U6ScheduleEntry] = []
        for i in range(total):
            off = entries_start + i * ENTRY_SIZE
            b0, b1, h, p1, p2 = data[off:off + ENTRY_SIZE]
            x, y, z = unpack_position(h, p1, p2)
            entries.append(U6ScheduleEntry(hour=b0 & 0x1F, day_of_week=b0 >> 5, worktype=b1, x=x, y=y, z=z))

        per_actor: list[list[U6ScheduleEntry]] = []
        for i in range(num_actors):
            start = offsets[i]
            if start > total - 1:
                per_actor.append([])
                continue
            if i == num_actors - 1:
                end = total
            else:
                nxt = offsets[i + 1]
                end = total if nxt > total - 1 else nxt
            per_actor.append(entries[start:end])

        return cls(per_actor)
