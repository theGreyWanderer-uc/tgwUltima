"""
``runtime/NPC.FLX`` reader for Ultima 9: Ascension.

The game's NPC table. Unlike every other FLX archive in U9, this one holds
a *single* used entry whose payload is a flat array of fixed-size records --
352 of them, one per NPC. **The record index is the NPC's identity**: it is
also the activity set index in :mod:`titan.u9.activity`, which is what ties
an NPC to the behaviour scripts it runs.

The same record array appears twice more in a savegame, byte-identically:
in ``savegame/processes.dat`` and again inside ``savegame/u9game1.sav``.
:meth:`U9Npcs.from_process_data` reads that live copy.

``runtime/NPC.FLX`` is *mostly* static but the engine does write back to it.
Two installs of the same build diverged by 29 bytes across 5 NPC records
after play -- position on all five, and ``unknown_id`` on two of them.

Each record is 316 bytes (``0x13C``)::

    0x00  unknown_id      u16   -- unique per NPC, multiple of 32, 0 = unplaced
    0x02  (zero)          u16   -- zero in every record of every file seen
    0x04  name            char[32], NUL-terminated
    0x24  gender          u8    -- 0 male, 1 female
    0x34  health_current  u16
    0x36  health_max      u16
    0x38  health_max2     u16   -- always equal to health_max
    0x3A  mana_current    u16
    0x3C  mana_max        u16
    0x3E  mana_max2       u16   -- always equal to mana_max
    0x44  class_id        u16   -- 0..62, 0xFFFF = none; see below
    0x54  combat_value    u16   -- 0 on non-combatants
    0x58  region          u32   -- runtime/nonfixed.<region>
    0x5C  x               u32   -- absolute world X
    0x60  y               u32   -- absolute world Y
    0x64  z               u16   -- elevation
    0x6C  scale_x         u8    -- percent
    0x6D  scale_y         u8
    0x6E  scale_z         u8

All integers are little-endian. The gaps are undecoded, and 200 of the 316
bytes are identical across all 352 records in the shipped file.

**The record is 316 bytes, not 323.** The Ultima Codex wiki documents
``0x143``/323. That does not divide the 111,232-byte payload (344 records
with 120 bytes left over) and lands every field on noise. 316 divides it
exactly into 352, and the Codex's own field offsets then validate:

===============================  ==========  ==========
check                            316 stride  323 stride
===============================  ==========  ==========
records                          352         344
remainder bytes                  0           120
plausible ASCII name             351         17
gender is 0 or 1                 352         273
region <= 239                    352         237
scale bytes in 1..200            350         14
health_max == health_max2        341         34
===============================  ==========  ==========

The last byte that ever varies is ``0x13B``, which is the final byte of a
316-byte record.

``class_id`` is a grouping this module names but does not claim to fully
understand. It is *not* appearance: members of one group span dozens of
distinct ``TYPES.DAT`` models. It clusters semantically -- class 10 is every
gargoyle in the game (``Valkadesh``, ``Winged Gargoyle``, ``Vassgralem``,
...), 36 is pirates and bandits, 62 is guards, 39 mages, 34 townsfolk -- so
faction or behaviour class is the natural reading.

Comparing the shipped table against a real savegame identifies which fields
the engine writes back. Position, region and a handful of undecoded fields
(``0x68``, ``0xEC``, ``0xF0``, ``0x110``) change; name, stats and
``class_id`` do not. ``unknown_id`` changes rarely -- one NPC across twelve
savegame files -- but it does change, and it is reallocated rather than
edited: both observed new values were slots free in the shipped table.

In one save three NPCs had moved, and all three were standing exactly on a
:mod:`titan.u9.highway` navigation point -- direct confirmation that the
highway graph drives NPC movement.

In a live region the entity that represents an NPC carries the **NPC's
record index in its** ``type_index`` **field**, not a ``TYPES.DAT`` type.
Matching that way against a savegame's ``nonfixed.9`` finds 159 of 169
NPCs, 157 of them at exactly the position the NPC record gives.

Example::

    from titan.u9.npc import U9Npcs

    npcs = U9Npcs.from_file("runtime/NPC.FLX")
    print(len(npcs))                    # 352
    print(npcs.npc(166).name)           # Dermot
    print(npcs.by_name("Mariah").index) # 65
"""

from __future__ import annotations

__all__ = ["U9Npc", "U9NpcError", "U9Npcs"]

import os
import struct
from collections import Counter
from dataclasses import dataclass

RECORD_SIZE = 0x13C  # 316
NAME_OFFSET = 0x04
NAME_FIELD_SIZE = 32
NO_CLASS = 0xFFFF

_UNKNOWN_ID = 0x00
_GENDER = 0x24
_HEALTH = 0x34
_MANA = 0x3A
_CLASS_ID = 0x44
_COMBAT_VALUE = 0x54
_REGION = 0x58
_POSITION = 0x5C
_ELEVATION = 0x64
_SCALE = 0x6C

# A savegame embeds the same array at an offset that is not fixed, so the
# block is located by signature rather than hard-coded.
_MIN_BLOCK_RECORDS = 16
MAX_REGION = 239          # runtime/nonfixed.%d tops out here
MAX_SCALE_PERCENT = 200   # largest scale seen in the shipped table


class U9NpcError(Exception):
    """Raised on malformed ``runtime/NPC.FLX`` data."""


@dataclass(frozen=True)
class U9Npc:
    """One 316-byte NPC record."""

    index: int
    unknown_id: int
    name: str
    gender: int
    health_current: int
    health_max: int
    health_max2: int
    mana_current: int
    mana_max: int
    mana_max2: int
    class_id: int
    combat_value: int
    region: int
    x: int
    y: int
    z: int
    scale: tuple[int, int, int]
    raw: bytes

    @property
    def is_female(self) -> bool:
        return self.gender == 1

    @property
    def has_class(self) -> bool:
        """False when ``class_id`` is the 0xFFFF "none" sentinel."""
        return self.class_id != NO_CLASS

    @property
    def position(self) -> tuple[int, int, int]:
        return (self.x, self.y, self.z)


def _name_field_ok(field: bytes) -> bool:
    """True for a NUL-terminated printable name, empty included.

    One shipped record has a blank name field, so an empty name has to be
    allowed or a scan breaks the array in two at that record.
    """
    if len(field) < NAME_FIELD_SIZE or b"\x00" not in field:
        return False
    return all(32 <= c < 127 for c in field.split(b"\x00", 1)[0])


def _is_named(field: bytes) -> bool:
    return _name_field_ok(field) and field[0] != 0


def _record_ok(data: bytes, base: int) -> bool:
    """Cheap structural validity test for one record at ``base``.

    The name field alone is too weak to bound the array -- unrelated bytes
    after it satisfy "NUL-terminated printable" often enough to overshoot by
    a third. Three more fields with narrow legal ranges pin the end down.
    """
    if base + RECORD_SIZE > len(data):
        return False
    if not _name_field_ok(data[base + NAME_OFFSET : base + NAME_OFFSET + NAME_FIELD_SIZE]):
        return False
    if data[base + _GENDER] > 1:
        return False
    if struct.unpack_from("<I", data, base + _REGION)[0] > MAX_REGION:
        return False
    return all(data[base + _SCALE + i] <= MAX_SCALE_PERCENT for i in range(3))


def _parse(data: bytes, base: int, index: int) -> U9Npc:
    r = data[base : base + RECORD_SIZE]
    hc, hm, hm2 = struct.unpack_from("<3H", r, _HEALTH)
    mc, mm, mm2 = struct.unpack_from("<3H", r, _MANA)
    return U9Npc(
        index=index,
        unknown_id=struct.unpack_from("<H", r, _UNKNOWN_ID)[0],
        name=r[NAME_OFFSET : NAME_OFFSET + NAME_FIELD_SIZE]
        .split(b"\x00", 1)[0]
        .decode("ascii", errors="replace"),
        gender=r[_GENDER],
        health_current=hc,
        health_max=hm,
        health_max2=hm2,
        mana_current=mc,
        mana_max=mm,
        mana_max2=mm2,
        class_id=struct.unpack_from("<H", r, _CLASS_ID)[0],
        combat_value=struct.unpack_from("<H", r, _COMBAT_VALUE)[0],
        region=struct.unpack_from("<I", r, _REGION)[0],
        x=struct.unpack_from("<I", r, _POSITION)[0],
        y=struct.unpack_from("<I", r, _POSITION + 4)[0],
        z=struct.unpack_from("<H", r, _ELEVATION)[0],
        scale=(r[_SCALE], r[_SCALE + 1], r[_SCALE + 2]),
        raw=bytes(r),
    )


class U9Npcs:
    """Reader for the U9 NPC record array."""

    def __init__(self, block: bytes) -> None:
        if len(block) < RECORD_SIZE:
            raise U9NpcError(
                f"data too small for one {RECORD_SIZE}-byte NPC record: {len(block)} bytes"
            )
        if len(block) % RECORD_SIZE:
            raise U9NpcError(
                f"{len(block)} bytes is not a whole number of {RECORD_SIZE}-byte "
                f"records ({len(block) % RECORD_SIZE} left over) -- not an NPC block?"
            )
        self._block = block
        self.npcs: tuple[U9Npc, ...] = tuple(
            _parse(block, i * RECORD_SIZE, i) for i in range(len(block) // RECORD_SIZE)
        )

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Npcs:
        """Read ``runtime/NPC.FLX``, whose single used entry is the record array."""
        from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

        try:
            archive = U9FlxArchive.from_file(filepath)
        except U9FlxArchiveError as e:
            raise U9NpcError(f"not a readable FLX archive: {e}") from e
        used = archive.used_entry_indices()
        if not used:
            raise U9NpcError("archive holds no used entries")
        return cls(archive.read_entry(used[0]))

    @classmethod
    def from_process_data(cls, filepath: str | os.PathLike[str]) -> U9Npcs:
        """Read the live NPC array out of a savegame's ``processes.dat``.

        The array's offset is not fixed, so it is found by signature: the
        longest run of consecutive records whose name fields are plausible
        NUL-terminated ASCII.
        """
        with open(filepath, "rb") as f:
            data = f.read()
        base, count = cls.find_block(data)
        if base is None:
            raise U9NpcError("no NPC record array found in this file")
        return cls(data[base : base + count * RECORD_SIZE])

    @staticmethod
    def find_block(data: bytes) -> tuple[int | None, int]:
        """Locate the NPC record array in an arbitrary buffer.

        Returns ``(offset, record_count)``, or ``(None, 0)`` if no run of at
        least 16 consecutive plausible records is present.

        Runs are scored by how many of their records carry a *non-empty*
        name, so a long stretch of zero padding -- which satisfies the
        NUL-terminated test trivially -- cannot outrank the real array.
        """
        best_start, best_len, best_score = None, 0, 0
        limit = len(data) - RECORD_SIZE
        start = 0
        while start <= limit:
            field = data[start + NAME_OFFSET : start + NAME_OFFSET + NAME_FIELD_SIZE]
            if not _is_named(field):
                start += 1
                continue
            run = score = 0
            pos = start
            while pos <= limit:
                if not _record_ok(data, pos):
                    break
                run += 1
                score += _is_named(
                    data[pos + NAME_OFFSET : pos + NAME_OFFSET + NAME_FIELD_SIZE]
                )
                pos += RECORD_SIZE
            if score > best_score:
                best_start, best_len, best_score = start, run, score
            start = pos if run else start + 1
        if best_len < _MIN_BLOCK_RECORDS:
            return None, 0

        # A forward scan can latch onto the array one record late whenever the
        # true first record does not start a run on its own. Walk back along
        # the record grid to recover it.
        #
        # Only *named* records are crossed going backwards. A blank record is
        # legal inside the array, but a run of blanks is also what unrelated
        # zero padding looks like, and extending into that drags the start
        # far below the real array.
        while best_start >= RECORD_SIZE:
            prev = best_start - RECORD_SIZE
            if not _record_ok(data, prev):
                break
            if not _is_named(data[prev + NAME_OFFSET : prev + NAME_OFFSET + NAME_FIELD_SIZE]):
                break
            best_start = prev
            best_len += 1
        return best_start, best_len

    def npc(self, index: int) -> U9Npc:
        """One NPC by record index -- the same index as its activity set."""
        if index < 0 or index >= len(self.npcs):
            raise U9NpcError(f"NPC index {index} out of range (0..{len(self.npcs) - 1})")
        return self.npcs[index]

    def by_name(self, name: str) -> U9Npc | None:
        """First NPC with this exact name, or ``None``."""
        return next((n for n in self.npcs if n.name == name), None)

    def in_region(self, region: int) -> list[U9Npc]:
        return [n for n in self.npcs if n.region == region]

    def by_class(self, class_id: int) -> list[U9Npc]:
        return [n for n in self.npcs if n.class_id == class_id]

    def class_histogram(self) -> Counter[int]:
        """How many NPCs carry each ``class_id``, the sentinel included."""
        return Counter(n.class_id for n in self.npcs)

    def changed_fields(self, other: U9Npcs) -> dict[int, int]:
        """Byte offsets that differ against another copy, and how many NPCs differ.

        Comparing the shipped table with a savegame's copy is what separates
        static identity from runtime state.

        Only the shared prefix is compared. A savegame's array is longer than
        the shipped one -- it appends runtime-spawned creatures after the 352
        authored NPCs -- and those extra slots have no counterpart here.
        """
        counts: Counter[int] = Counter()
        for a, b in zip(self.npcs, other.npcs):
            for offset in range(RECORD_SIZE):
                if a.raw[offset] != b.raw[offset]:
                    counts[offset] += 1
        return dict(sorted(counts.items()))

    def __len__(self) -> int:
        return len(self.npcs)

    def __iter__(self):
        return iter(self.npcs)
