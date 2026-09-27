"""Parse U9's 316-byte NPC records from ``runtime/NPC.FLX`` and saves.

The archive contains 352 authored records. A saved live table contains 512:
the authored prefix followed by 160 clone slots. Record index is identity and
also selects the corresponding activity set in :mod:`titan.u9.activity`.

The layout is known through the final byte. The eight level cells are signed
32-bit integers, matching the reads performed by ``u9.exe`` 1.19F. Values
outside the usual ``-1..3`` domain are retained and reported, never rewritten.
Reserved bytes remain available through explicit offset-named fields as well
as :attr:`U9Npc.raw`.
"""

from __future__ import annotations

__all__ = [
    "AUTHORED_RECORD_COUNT",
    "LIVE_RECORD_COUNT",
    "NO_COMBAT_BEHAVIOR",
    "U9Npc",
    "U9NpcError",
    "U9NpcState",
    "U9NpcTrait",
    "U9Npcs",
]

import os
import struct
from collections import Counter
from dataclasses import dataclass
from enum import IntFlag

RECORD_SIZE = 0x13C  # 316
NAME_OFFSET = 0x04
NAME_FIELD_SIZE = 32
AUTHORED_RECORD_COUNT = 352
LIVE_RECORD_COUNT = 512
NO_COMBAT_BEHAVIOR = -1

# Compatibility alias for callers of the earlier, incorrectly named field.
NO_CLASS = NO_COMBAT_BEHAVIOR
POOL_ELEMENT_SIZE = 32

_POOL_HANDLE = 0x00
_GENDER = 0x24
_MAGIC_TIER = 0x25
_ARMOR = 0x26
_MIGHT_CODE = 0x28
_AGILITY_CODE = 0x2C
_INTELLECT_CODE = 0x30
_HEALTH = 0x34
_MANA = 0x3A
_EARLY_RESERVED = 0x40
_COMBAT_BEHAVIOR = 0x44
_STATE_FLAGS = 0x48
_ROUTINES = 0x4C
_AWARENESS = 0x52
_REGION = 0x58
_POSITION = 0x5C
_POSITION_TAIL = 0x66
_ROUTINE_CURSOR = 0x68
_SCALE = 0x6C
_SCALE_RESERVED = 0x6F
_EQUIPPED_OBJECTS = 0x70
_MODEL_ATTACHMENTS = 0x8C
_ACTIVE_WEAPON_CATEGORY = 0xA8
_INVULNERABILITY_DURATION = 0xAC
_MOVEMENT_BEHAVIOR = 0xB0
_BREATH = 0xB4
_BREATH_RESERVED = 0xBA
_TRAIT_FLAGS = 0xC4
_IMPACT_MATERIAL = 0xC8
_IMPACT_RESERVED = 0xCC
_PROXIMITY_RESERVED = 0xE0
_PROXIMITY = 0xE2
_ROUTINE_TIMING = 0xE6
_TIMING_RESERVED = 0xFC
_ROUTINE_STACK = 0x110
_SPELLBOOK = 0x118
_COMBAT_SKILLS = 0x124
_TRAILING_RESERVED = 0x138

# A savegame embeds the same array at an offset that is not fixed, so the
# block is located by signature rather than hard-coded.
_MIN_BLOCK_RECORDS = 16
MAX_REGION = 239  # runtime/nonfixed.%d tops out here
MAX_SCALE_PERCENT = 200  # largest scale seen in the shipped table


class U9NpcState(IntFlag):
    """Primary NPC state bits stored at record offset ``0x48``."""

    CANNOT_DIE = 0x00000001
    VENOMED = 0x00000002
    DISEASED = 0x00000004
    HEXED = 0x00000008
    WARD_ACTIVE = 0x00000010
    LIFE_DEPLETED = 0x00000020
    SLEEPING = 0x00000040
    POWER_BOOSTED = 0x00000080
    SPAWN_SEATED = 0x00000100
    HIDDEN = 0x00000200
    IMMOBILIZED = 0x00000400
    CLONED_ARCHETYPE = 0x00000800
    BEGUILED = 0x00001000
    DAMAGE_REFLECTING = 0x00002000
    FULL_DAMAGE_REFLECTION = 0x00004000
    FLEEING = 0x00008000
    SPELLCASTING_DISABLED = 0x00010000
    MAGIC_RESISTANT = 0x00020000
    NAME_REVEALED = 0x00040000
    PLAYER_RECOGNIZED = 0x00080000
    POSITION_LOCKED = 0x00100000
    FEAR_IMMUNE = 0x00200000
    ENGAGED_IN_COMBAT = 0x00400000
    ARRIVAL_TRIGGER_ARMED = 0x00800000
    TRAVELLING = 0x01000000
    ROUTE_SEARCH_FAILED = 0x02000000
    HOSTILE_MODE = 0x04000000
    PRIMARY_HOSTILE_MODE = 0x08000000
    DIALOGUE_ACTIVE = 0x10000000
    DEPARTURE_TRIGGER_ARMED = 0x20000000
    ROUTINE_ACTIVE = 0x40000000
    ROUTE_SEARCH_BLOCKED = 0x80000000


class U9NpcTrait(IntFlag):
    """Secondary NPC trait bits stored at record offset ``0xC4``."""

    STATIONARY = 0x0001
    HIGHWAY_PAUSED = 0x0002
    ATTACK_IMMUNE = 0x0004
    REMOVE_WITH_COMBAT_AGENT = 0x0008
    BOSS = 0x0010
    ROUTINE_REFRESH_NEEDED = 0x0020
    SPAWN_SLEEPING = 0x0040
    COMBAT_IGNORED = 0x0080
    HUMANOID_BODY = 0x0100
    UNDEAD_BODY = 0x0200
    SERPENT_VENOMED = 0x0400
    KILL_PENALIZES_KARMA = 0x0800


class U9NpcError(Exception):
    """Raised on malformed ``runtime/NPC.FLX`` data."""


@dataclass(frozen=True)
class U9Npc:
    """One fully framed 316-byte NPC record.

    Fields named ``*_code`` are the signed 32-bit values read by the game.
    Their raw bytes are retained with the rest of the record for exact
    round trips.
    """

    index: int
    pool_handle: int
    name: str
    gender: int
    magic_tier: int
    armor_rating: int
    armor_modifier: int
    might_code: int
    agility_code: int
    intellect_code: int
    health_current: int
    health_bonus_maximum: int
    health_base_maximum: int
    mana_current: int
    mana_bonus_maximum: int
    mana_base_maximum: int
    reserved_0x40: int
    residual_0x41_0x43: bytes
    combat_behavior_id: int
    state_flags: U9NpcState
    active_routine_id: int
    fallback_routine_id: int
    fallback_routine_argument: int
    magic_resistance_modifier: int
    route_search_workers: int
    awareness_radius: int
    awareness_arc_degrees: int
    guaranteed_awareness_percent: int
    region: int
    x: int
    y: int
    z: int
    position_tail: bytes
    routine_stack_depth: int
    routine_step_index: int
    active_routine_argument: int
    scale: tuple[int, int, int]
    reserved_0x6f: int
    equipped_object_offsets: tuple[int, ...]
    model_attachment_ids: tuple[int, ...]
    active_weapon_category_id: int
    invulnerability_duration: int
    movement_behavior_id: int
    breath_current: int
    breath_bonus_maximum: int
    breath_base_maximum: int
    reserved_0xba_0xc3: bytes
    trait_flags: U9NpcTrait
    impact_material_id: int
    reserved_0xcc_0xdf: bytes
    reserved_0xe0: int
    proximity_enter_radius: int
    proximity_exit_radius: int
    queued_routine_argument: int
    route_search_counter: int
    routine_end_time: int
    routine_start_time: int
    primary_routine_duration: int
    queued_routine_id: int
    secondary_routine_duration: int
    reserved_0xfc_0x10f: bytes
    routine_stack: bytes
    spellbook_flags: bytes
    unarmed_skill_code: int
    one_handed_skill_code: int
    two_handed_skill_code: int
    blunt_skill_code: int
    ranged_skill_code: int
    reserved_0x138_0x13b: bytes
    raw: bytes

    @property
    def level_code_items(self) -> tuple[tuple[str, int, bytes], ...]:
        """All eight signed level codes and their exact stored bytes."""
        return (
            ("might", self.might_code, self.raw[_MIGHT_CODE : _MIGHT_CODE + 4]),
            (
                "agility",
                self.agility_code,
                self.raw[_AGILITY_CODE : _AGILITY_CODE + 4],
            ),
            (
                "intellect",
                self.intellect_code,
                self.raw[_INTELLECT_CODE : _INTELLECT_CODE + 4],
            ),
            (
                "unarmed_skill",
                self.unarmed_skill_code,
                self.raw[_COMBAT_SKILLS : _COMBAT_SKILLS + 4],
            ),
            (
                "one_handed_skill",
                self.one_handed_skill_code,
                self.raw[_COMBAT_SKILLS + 4 : _COMBAT_SKILLS + 8],
            ),
            (
                "two_handed_skill",
                self.two_handed_skill_code,
                self.raw[_COMBAT_SKILLS + 8 : _COMBAT_SKILLS + 12],
            ),
            (
                "blunt_skill",
                self.blunt_skill_code,
                self.raw[_COMBAT_SKILLS + 12 : _COMBAT_SKILLS + 16],
            ),
            (
                "ranged_skill",
                self.ranged_skill_code,
                self.raw[_COMBAT_SKILLS + 16 : _COMBAT_SKILLS + 20],
            ),
        )

    @property
    def health_status(self) -> str | None:
        """Runtime consequence of a stored health invariant violation."""
        if (
            self.health_current <= self.health_bonus_maximum
            and self.health_base_maximum <= self.health_bonus_maximum
        ):
            return None
        if not self.has_combat_behavior:
            return "unreachable: no combat AI"
        return "clamped_on_first_write"

    @property
    def health_raw(self) -> bytes:
        """Exact bytes of the three stored health values."""
        return self.raw[_HEALTH:_MANA]

    @property
    def mana_raw(self) -> bytes:
        """Exact bytes of the three stored mana values."""
        return self.raw[_MANA:_EARLY_RESERVED]

    @property
    def breath_raw(self) -> bytes:
        """Exact bytes of the three stored breath values."""
        return self.raw[_BREATH:_BREATH_RESERVED]

    def to_bytes(self) -> bytes:
        """Return the original record unchanged."""
        return self.raw

    @property
    def pool_index(self) -> int:
        """``pool_handle`` as an element index -- the pool's elements are 32 bytes."""
        return self.pool_handle // POOL_ELEMENT_SIZE

    @property
    def is_slot_used(self) -> bool:
        """True when this record slot is occupied.

        ``pool_handle == 0`` is the allocator's free test. In the shipped
        table it means the NPC has no world placement -- it pairs exactly
        with ``region == 0`` and position ``(0, 0, 0)`` -- and some of those
        records are spawn templates rather than absent NPCs.
        """
        return self.pool_handle != 0

    @property
    def has_pool_object(self) -> bool:
        """True when the handle actually addresses a pool object.

        ``pool_handle == 1`` is the allocator's "slot taken, no object yet"
        marker, so it is occupied but not dereferenceable.
        """
        return self.pool_handle > 1

    @property
    def is_female(self) -> bool:
        """Whether the record's binary gender marker is female."""
        return self.gender == 1

    @property
    def has_combat_behavior(self) -> bool:
        """Whether a combat behavior profile is assigned (``-1`` means none)."""
        return self.combat_behavior_id != NO_COMBAT_BEHAVIOR

    @property
    def position(self) -> tuple[int, int, int]:
        """Signed world coordinates as ``(x, y, z)``."""
        return (self.x, self.y, self.z)

    # Compatibility accessors for the earlier partial decoder. Their names
    # are retained so downstream code keeps working, while the primary fields
    # above carry the corrected semantics.
    @property
    def health_max(self) -> int:
        """Compatibility alias for :attr:`health_bonus_maximum`."""
        return self.health_bonus_maximum

    @property
    def health_max2(self) -> int:
        """Compatibility alias for :attr:`health_base_maximum`."""
        return self.health_base_maximum

    @property
    def mana_max(self) -> int:
        """Compatibility alias for :attr:`mana_bonus_maximum`."""
        return self.mana_bonus_maximum

    @property
    def mana_max2(self) -> int:
        """Compatibility alias for :attr:`mana_base_maximum`."""
        return self.mana_base_maximum

    @property
    def class_id(self) -> int:
        """Compatibility alias for :attr:`combat_behavior_id`."""
        return self.combat_behavior_id

    @property
    def has_class(self) -> bool:
        """Compatibility alias for :attr:`has_combat_behavior`."""
        return self.has_combat_behavior

    @property
    def flags(self) -> int:
        """Compatibility integer view of :attr:`state_flags`."""
        return int(self.state_flags)

    @property
    def combat_value(self) -> int:
        """Compatibility alias for :attr:`awareness_radius`."""
        return self.awareness_radius


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
    if not _name_field_ok(
        data[base + NAME_OFFSET : base + NAME_OFFSET + NAME_FIELD_SIZE]
    ):
        return False
    if data[base + _GENDER] > 1:
        return False
    if struct.unpack_from("<I", data, base + _REGION)[0] > MAX_REGION:
        return False
    return all(data[base + _SCALE + i] <= MAX_SCALE_PERCENT for i in range(3))


def _parse(data: bytes, base: int, index: int) -> U9Npc:
    r = data[base : base + RECORD_SIZE]
    health = struct.unpack_from("<3H", r, _HEALTH)
    mana = struct.unpack_from("<3H", r, _MANA)
    active_routine, fallback_routine, fallback_argument = struct.unpack_from(
        "<3H", r, _ROUTINES
    )
    magic_resistance, route_workers, awareness_radius = struct.unpack_from(
        "<BBH", r, _AWARENESS
    )
    x, y, z = struct.unpack_from("<iih", r, _POSITION)
    stack_depth, step_index, active_argument = struct.unpack_from(
        "<BBH", r, _ROUTINE_CURSOR
    )
    breath = struct.unpack_from("<3H", r, _BREATH)
    proximity_enter, proximity_exit = struct.unpack_from("<2H", r, _PROXIMITY)
    (
        queued_argument,
        route_counter,
        routine_end,
        routine_start,
        primary_duration,
        queued_routine,
        secondary_duration,
    ) = struct.unpack_from("<HiHHiIi", r, _ROUTINE_TIMING)
    combat_skills = struct.unpack_from("<5i", r, _COMBAT_SKILLS)
    return U9Npc(
        index=index,
        pool_handle=struct.unpack_from("<I", r, _POOL_HANDLE)[0],
        name=r[NAME_OFFSET : NAME_OFFSET + NAME_FIELD_SIZE]
        .split(b"\x00", 1)[0]
        .decode("ascii", errors="replace"),
        gender=r[_GENDER],
        magic_tier=r[_MAGIC_TIER],
        armor_rating=r[_ARMOR],
        armor_modifier=r[_ARMOR + 1],
        might_code=struct.unpack_from("<i", r, _MIGHT_CODE)[0],
        agility_code=struct.unpack_from("<i", r, _AGILITY_CODE)[0],
        intellect_code=struct.unpack_from("<i", r, _INTELLECT_CODE)[0],
        health_current=health[0],
        health_bonus_maximum=health[1],
        health_base_maximum=health[2],
        mana_current=mana[0],
        mana_bonus_maximum=mana[1],
        mana_base_maximum=mana[2],
        reserved_0x40=r[_EARLY_RESERVED],
        residual_0x41_0x43=bytes(r[_EARLY_RESERVED + 1 : _COMBAT_BEHAVIOR]),
        combat_behavior_id=struct.unpack_from("<i", r, _COMBAT_BEHAVIOR)[0],
        state_flags=U9NpcState(struct.unpack_from("<I", r, _STATE_FLAGS)[0]),
        active_routine_id=active_routine,
        fallback_routine_id=fallback_routine,
        fallback_routine_argument=fallback_argument,
        magic_resistance_modifier=magic_resistance,
        route_search_workers=route_workers,
        awareness_radius=awareness_radius,
        awareness_arc_degrees=r[_AWARENESS + 4],
        guaranteed_awareness_percent=r[_AWARENESS + 5],
        region=struct.unpack_from("<i", r, _REGION)[0],
        x=x,
        y=y,
        z=z,
        position_tail=bytes(r[_POSITION_TAIL : _POSITION_TAIL + 2]),
        routine_stack_depth=stack_depth,
        routine_step_index=step_index,
        active_routine_argument=active_argument,
        scale=(r[_SCALE], r[_SCALE + 1], r[_SCALE + 2]),
        reserved_0x6f=r[_SCALE_RESERVED],
        equipped_object_offsets=struct.unpack_from("<7I", r, _EQUIPPED_OBJECTS),
        model_attachment_ids=struct.unpack_from("<7i", r, _MODEL_ATTACHMENTS),
        active_weapon_category_id=struct.unpack_from("<i", r, _ACTIVE_WEAPON_CATEGORY)[
            0
        ],
        invulnerability_duration=struct.unpack_from("<I", r, _INVULNERABILITY_DURATION)[
            0
        ],
        movement_behavior_id=struct.unpack_from("<i", r, _MOVEMENT_BEHAVIOR)[0],
        breath_current=breath[0],
        breath_bonus_maximum=breath[1],
        breath_base_maximum=breath[2],
        reserved_0xba_0xc3=bytes(r[_BREATH_RESERVED:_TRAIT_FLAGS]),
        trait_flags=U9NpcTrait(struct.unpack_from("<I", r, _TRAIT_FLAGS)[0]),
        impact_material_id=struct.unpack_from("<i", r, _IMPACT_MATERIAL)[0],
        reserved_0xcc_0xdf=bytes(r[_IMPACT_RESERVED:_PROXIMITY_RESERVED]),
        reserved_0xe0=struct.unpack_from("<H", r, _PROXIMITY_RESERVED)[0],
        proximity_enter_radius=proximity_enter,
        proximity_exit_radius=proximity_exit,
        queued_routine_argument=queued_argument,
        route_search_counter=route_counter,
        routine_end_time=routine_end,
        routine_start_time=routine_start,
        primary_routine_duration=primary_duration,
        queued_routine_id=queued_routine,
        secondary_routine_duration=secondary_duration,
        reserved_0xfc_0x10f=bytes(r[_TIMING_RESERVED:_ROUTINE_STACK]),
        routine_stack=bytes(r[_ROUTINE_STACK : _ROUTINE_STACK + 8]),
        spellbook_flags=bytes(r[_SPELLBOOK : _SPELLBOOK + 12]),
        unarmed_skill_code=combat_skills[0],
        one_handed_skill_code=combat_skills[1],
        two_handed_skill_code=combat_skills[2],
        blunt_skill_code=combat_skills[3],
        ranged_skill_code=combat_skills[4],
        reserved_0x138_0x13b=bytes(r[_TRAILING_RESERVED:RECORD_SIZE]),
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
        self._block = bytes(block)
        self.npcs: tuple[U9Npc, ...] = tuple(
            _parse(self._block, i * RECORD_SIZE, i)
            for i in range(len(self._block) // RECORD_SIZE)
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
        assert best_start is not None

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
            if not _is_named(
                data[prev + NAME_OFFSET : prev + NAME_OFFSET + NAME_FIELD_SIZE]
            ):
                break
            best_start = prev
            best_len += 1
        # A save serializes exactly 512 slots. Bytes following the table can
        # coincidentally satisfy the structural probe and formerly produced a
        # spurious 513th record in real saves.
        best_len = min(best_len, LIVE_RECORD_COUNT)
        return best_start, best_len

    def npc(self, index: int) -> U9Npc:
        """One NPC by record index -- the same index as its activity set."""
        if index < 0 or index >= len(self.npcs):
            raise U9NpcError(
                f"NPC index {index} out of range (0..{len(self.npcs) - 1})"
            )
        return self.npcs[index]

    def by_name(self, name: str) -> U9Npc | None:
        """First NPC with this exact name, or ``None``."""
        return next((n for n in self.npcs if n.name == name), None)

    def in_region(self, region: int) -> list[U9Npc]:
        return [n for n in self.npcs if n.region == region]

    def by_combat_behavior(self, behavior_id: int) -> list[U9Npc]:
        """All NPCs assigned to one combat behavior profile."""
        return [n for n in self.npcs if n.combat_behavior_id == behavior_id]

    def combat_behavior_histogram(self) -> Counter[int]:
        """Count combat behavior profiles, including the ``-1`` sentinel."""
        return Counter(n.combat_behavior_id for n in self.npcs)

    def by_class(self, class_id: int) -> list[U9Npc]:
        """Compatibility alias for :meth:`by_combat_behavior`."""
        return self.by_combat_behavior(class_id)

    def class_histogram(self) -> Counter[int]:
        """Compatibility alias for :meth:`combat_behavior_histogram`."""
        return self.combat_behavior_histogram()

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

    def to_bytes(self) -> bytes:
        """Return the complete record block unchanged."""
        return self._block

    def __len__(self) -> int:
        return len(self.npcs)

    def __iter__(self):
        return iter(self.npcs)
