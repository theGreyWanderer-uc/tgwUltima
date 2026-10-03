"""Read the subsystem sections that follow the process list in ``processes.dat``.

After the typed process list's ``-1`` terminator, a U9 save writes thirteen
sections in a fixed order, each owned by one engine subsystem:

 1. fast-area state
 2. NPC data manager (a second copy of the 512 NPC records, type table,
    pointer tables)
 3. main user-interface state
 4. light system (two counted lists of saved lights, then settings)
 5. weather system
 6. spell manager (active spell process IDs)
 7. physics system (moving objects, then collision/trigger overlaps)
 8. moving platforms (lifts, steps, ships and other moving platforms)
 9. highway manager
10. hint-object manager
11. combat system (combatant NPC types and per-combatant records)
12. book bookmarks
13. the sound system's music list (a count, then 30-byte music nodes)

Every section is walked field by field. Each combatant record's layout is
chosen by the NPC's combat behaviour ID (read from the NPC data manager's
copy of the NPC records): class fields written before a 268-byte common
part, the common part, and class fields written after it, all typed (see
:data:`COMBATANT_CLASS_LAYOUTS`). Some class fields are saved uninitialized
by the game for creatures that never set them (for example a plain human's
attack range), so their values are reported as stored, without range checks.

Example::

    from titan.u9.process_data import U9ProcessDataPrefix
    from titan.u9.process_sections import U9ProcessSections

    prefix = U9ProcessDataPrefix.from_bytes(data)
    sections = U9ProcessSections.from_prefix(data, prefix)
    print(len(sections.lights.ranged_lights), sections.combat.npc_types)
"""

from __future__ import annotations

__all__ = [
    "INTERFACE_ELEMENTS",
    "MOON_PHASES",
    "WEATHER_STATES",
    "U9BookState",
    "U9CollisionOverlap",
    "U9CombatState",
    "U9CombatantClassFields",
    "U9CombatantCommonState",
    "U9CombatantRecord",
    "U9FastAreaEntry",
    "U9FastAreaState",
    "U9HighwayManagerState",
    "U9HighwayMover",
    "U9HintRecord",
    "U9HintManagerState",
    "U9LightSystemState",
    "U9MainInterfaceState",
    "U9MovingPlatform",
    "U9MusicNode",
    "U9MovingPlatformsState",
    "U9NpcManagerState",
    "U9PhysicsObject",
    "U9PhysicsState",
    "U9ProcessSections",
    "U9ProcessSectionsError",
    "U9SavedLight",
    "U9ScreenFadeState",
    "U9SpellManagerState",
    "U9SoundSystemState",
    "U9SupportedObject",
    "U9TriggerOverlap",
    "U9WeatherLight",
    "U9WeatherState",
]

import struct
from dataclasses import dataclass

from titan.u9.npc import RECORD_SIZE as NPC_RECORD_SIZE
from titan.u9.npc import U9Npcs
from titan.u9.process_data import (
    U9PathManagerState,
    U9ProcessDataError,
    U9ProcessDataPrefix,
)

NPC_COUNT = 512
TYPE_TABLE_RECORD_SIZE = 16
LIGHT_RECORD = struct.Struct("<I3B3f3fff3Bffif2Ii")
LIGHT_SETTINGS_COUNT = 23
# Weather: clocks, sky state, storm, wind/gusts, rain/lightning timers, three
# (flag, RGB) lights, two flare shorts, two moon-phase shorts, remover scale.
WEATHER_STATE = struct.Struct("<4if5i3f3f3fi3f4Ii3fi3Bi3Bi3B4hf")
WEATHER_FADE = struct.Struct("<8i2I")
PHYSICS_OBJECT = struct.Struct("<i3f4f3f3f3ffif")
SUPPORTED_OBJECT = struct.Struct("<i3f4ffif3f4f3f")
SUPPORT_OWN_SIZES = {0: 0, 1: 48, 2: 136, 3: 209, 4: 32}
NPC_RECORD_CACHE_SIZE = 352  # one entry per record in NPC.FLX
HIGHWAY_MOVER = struct.Struct("<iiiifiiih2x")  # ends with a Location
HIGHWAY_MOVER_LIMIT = 64
HINT_RECORD = struct.Struct("<ii6i4I")
BOOK_PAGE_COUNT = 0x1002
MUSIC_NODE = struct.Struct("<iiBiBBIIIBBB")
SOUND_SYSTEM_VERSION = 2
COMBAT_TAIL_SIZE = 12
COMBATANT_COMMON_VERSION = 5
COMBATANT_COMMON = struct.Struct("<i7ifi" + "iih2x" + "3ifiiBBii128siBHBH5i3f3i")
COMBAT_BEHAVIOR_OFFSET = 0x44


@dataclass(frozen=True)
class _CombatantBlock:
    """One class save's own fields: a kind, a leading version word (``None``
    when the class writes none) and ``(name, format)`` pairs in stream order.
    Format ``r`` is an object-reference index."""

    kind: str
    version: int | None
    fields: tuple[tuple[str, str], ...]
    layout: struct.Struct
    value_counts: tuple[int, ...]  # unpacked values per field


def _block(kind: str, version: int | None, *fields: tuple[str, str]) -> _CombatantBlock:
    formats = [fmt.replace("r", "i") for _, fmt in fields]
    counts = tuple(
        len(struct.unpack("<" + f, bytes(struct.calcsize("<" + f)))) for f in formats
    )
    prefix = "i" if version is not None else ""
    return _CombatantBlock(
        kind, version, fields, struct.Struct("<" + prefix + "".join(formats)), counts
    )


_STATES = (("previous_state", "i"), ("current_state", "i"), ("next_state", "i"))
_HUMANOID = _block(
    "humanoid",
    3,
    ("current_state", "i"),
    ("next_state", "i"),
    ("pre_combat_turn_tolerance", "f"),
    ("current_animation_id", "i"),
    ("attack_delay", "i"),
    ("stun_effect_id", "i"),
)
_AVATAR = _block(
    "avatar",
    4,
    ("self_damage_kind", "i"),
    ("strike_zone_position", "3f"),
    ("strike_zone_radius", "f"),
    ("self_damage_weapon", "r"),
    ("self_damage_attack_level", "i"),
    ("self_damage_attack_type", "i"),
    ("ability_minimum_damage", "I"),
    ("ability_maximum_damage", "I"),
    ("ability_strike_zone_offset", "f"),
    ("ability_strike_zone_radius", "f"),
    ("ability_damage_type", "i"),
    ("ability_special_effect", "i"),
    ("weapon_item_type", "H2x"),
    ("weapon_kind", "i"),
    ("weapon_minimum_damage", "I"),
    ("weapon_maximum_damage", "I"),
    ("weapon_strike_zone_offset", "f"),
    ("weapon_strike_zone_radius", "f"),
    ("weapon_special_effects", "i"),
    ("self_damage", "i"),
    ("self_damage_position", "3f"),
    ("self_damage_flags", "i"),
    ("self_damage_type", "i"),
    ("weapon_drawn", "B"),  # likely: only the draw and sheathe code sets it
    ("animation_end_callback", "i"),  # action run when the animation ends
    ("animation_end_argument", "i"),  # -1: none
    ("queued_spell", "i"),  # -1: none
    ("queued_spell_flags", "i"),
)
_NINJA = _block("ninja", 1, ("defend_timer", "i"))
_GARGOYLE_DRONE = _block("gargoyle_drone", 1, ("berserk_attacks", "i"))
_RANGED_HUMAN = _block(
    "ranged_human", 1, ("attack_range", "f"), ("stand_and_fire", "B")
)
_GUARD = _block("guard", 1, ("defend_timer", "i"), ("first_attack_after_defense", "B"))
_PIRATE = _block("pirate", 1, ("combat_mode", "i"), ("state_timer", "i"))
_SKELETON = _block("skeleton", 1, ("defend_timer", "i"))
_GOBLIN_SERGEANT = _block(
    "goblin_sergeant",
    1,
    ("last_move_failed", "i"),
    ("move_failures", "5i"),
    ("stuck_timer", "i"),
)
_GOBLIN_GRUNT = _block("goblin_grunt", 1, *_STATES, ("notice_enemy_distance", "f"))
_CRUSTY = _block(
    "crusty",
    2,
    ("animation_complete", "B"),
    ("movement_complete", "B"),
    ("duration_complete", "B"),
    *_STATES,
    ("action_duration", "I"),
    ("action_start", "I"),
    ("flipped_duration", "I"),
    ("flipped_start", "I"),
    ("moved_last_idle", "B"),
    ("threaten_distance", "I"),
    ("pursue_distance", "I"),
    ("attack_distance", "I"),
)
_WINGED_GARGOYLE = _block(
    "winged_gargoyle",
    None,
    ("wing_controller_process_id", "i"),
    ("current_state", "i"),
    ("next_state", "i"),
    ("previous_state", "i"),
    ("action_start", "I"),
    ("action_duration", "I"),
    ("attack_distance", "I"),
)
_GAZER = _block(
    "gazer",
    None,
    ("eye_controller_process_id", "i"),
    ("cycle_controller_process_id", "i"),
    ("current_state", "i"),
    ("next_state", "i"),
    ("previous_state", "i"),
    ("movement_complete", "B"),
    ("animation_complete", "B"),
    ("duration_complete", "B"),
    ("casting_complete", "B"),
    ("ready_to_cast_spell", "B"),
    ("action_start", "I"),
    ("action_duration", "I"),
    ("locating_eye", "B"),
    ("selected_eye", "i"),
)
_SLASHER = _block(
    "slasher_of_veils",
    3,
    ("shield_hit_points", "i"),
    ("shield_active_time", "I"),
    ("flight_state", "i"),
    ("previous_hit_points", "i"),
    ("ready_to_change_state", "B"),
    ("force_state_change", "B"),
    ("time_until_next_attack", "I"),
    ("fly_time", "I"),
    ("hover_time", "I"),
    ("notice_distance", "f"),
    ("avatar_tracking_distance", "f"),
    ("use_activities", "B"),
    ("drift_counter", "B"),
    ("shield", "r"),
    ("saved_health_maximum", "I"),
    ("saved_health_current", "I"),
)
_ZOMBIE = _block(
    "zombie",
    2,
    ("attack_delay", "i"),
    ("split_complete", "B"),
    ("current_state", "i"),
    ("next_state", "i"),
)
_ZOMBIE_PART_FIELDS = (
    ("attack_delay", "i"),
    ("attack_distance", "f"),
    ("current_state", "i"),
    ("next_state", "i"),
)
_ZOMBIE_LEGS = _block("zombie_legs", 2, *_ZOMBIE_PART_FIELDS)
_ZOMBIE_TORSO = _block("zombie_torso", 2, *_ZOMBIE_PART_FIELDS)
_CREEPER = _block(
    "creeper",
    2,
    ("animation_complete", "B"),
    ("duration_complete", "B"),
    *_STATES,
    ("action_duration", "I"),
    ("action_start", "I"),
    ("enemy_distance", "f"),
    ("threaten_distance", "I"),
    ("attack_distance", "I"),
)
_GIANT_RAT = _block(
    "giant_rat",
    3,
    *_STATES,
    ("first_attack_launched", "B"),
    ("threaten_distance", "f"),
    ("pursue_distance", "f"),
    ("action_complete", "B"),
    ("movement_complete", "B"),
    ("duration_complete", "B"),
    ("last_move_failed", "B"),
)
_SMALL_RAT = _block("small_rat", 1, *_STATES)
_GARGOYLE_QUEEN = _block("gargoyle_queen", 1, ("current_state", "i"))
_WOLF = _block(
    "wolf",
    3,
    *_STATES,
    ("attack_distance", "i"),
    ("wander_distance", "i"),
    ("notice_distance", "i"),
    ("action_complete", "B"),
    ("movement_complete", "B"),
    ("duration_complete", "B"),
    ("baseline_notice_distance", "i"),
    ("notice_distance_restore_ms", "i"),
)
_DOG = _block("dog", 1, ("attitude", "i"))
_ICEHOUND = _block("icehound", 2, ("freeze_delay_remaining", "i"))


@dataclass(frozen=True)
class _CombatantLayout:
    leading: tuple[_CombatantBlock, ...] = ()
    trailing: tuple[_CombatantBlock, ...] = ()
    repeats_common: bool = False


def _repeat(layout: _CombatantLayout, *behaviors: int) -> dict[int, _CombatantLayout]:
    return dict.fromkeys(behaviors, layout)


# Combatant class layouts by the NPC's combat behaviour ID (NPC record +0x44),
# in retail stream order. Each class save either appends its fields after its
# parent's (``trailing``) or writes them first (``leading``); the creeper
# writes the common part twice (common, its fields, common). Unlisted IDs save
# the common part only. Checked write by write against the retail class save
# routines and on every combatant record of the save corpus.
COMBATANT_CLASS_LAYOUTS: dict[int, _CombatantLayout] = {
    0: _CombatantLayout(trailing=(_HUMANOID, _AVATAR)),
    4: _CombatantLayout(trailing=(_CRUSTY,)),
    6: _CombatantLayout(trailing=(_SLASHER,)),
    8: _CombatantLayout(trailing=(_ZOMBIE,)),
    9: _CombatantLayout(trailing=(_HUMANOID, _NINJA, _GARGOYLE_DRONE)),
    10: _CombatantLayout(trailing=(_WINGED_GARGOYLE,)),
    11: _CombatantLayout(leading=(_GARGOYLE_QUEEN,)),
    12: _CombatantLayout(trailing=(_GAZER,)),
    14: _CombatantLayout(trailing=(_HUMANOID, _GOBLIN_GRUNT)),
    15: _CombatantLayout(trailing=(_HUMANOID, _GOBLIN_SERGEANT)),
    19: _CombatantLayout(trailing=(_CREEPER,), repeats_common=True),
    20: _CombatantLayout(leading=(_GIANT_RAT,)),
    21: _CombatantLayout(leading=(_SMALL_RAT,)),
    22: _CombatantLayout(trailing=(_HUMANOID, _SKELETON)),
    **_repeat(_CombatantLayout(leading=(_WOLF,)), 25, 26, 27),
    30: _CombatantLayout(leading=(_DOG, _WOLF)),
    **_repeat(_CombatantLayout(trailing=(_HUMANOID, _RANGED_HUMAN)), 34, 38),
    36: _CombatantLayout(trailing=(_HUMANOID, _PIRATE)),
    **_repeat(_CombatantLayout(trailing=(_HUMANOID,)), 39, 41, 49, 56, 63),
    40: _CombatantLayout(trailing=(_HUMANOID, _NINJA)),
    **_repeat(_CombatantLayout(trailing=(_HUMANOID, _GUARD)), 42, 57, 61, 62),
    44: _CombatantLayout(leading=(_ICEHOUND, _WOLF)),
    47: _CombatantLayout(trailing=(_ZOMBIE_LEGS,)),
    48: _CombatantLayout(trailing=(_ZOMBIE_TORSO,)),
}


def _blocks_size(blocks: tuple[_CombatantBlock, ...]) -> int:
    return sum(block.layout.size for block in blocks)


# (bytes written before the common part, bytes written after it).
COMBATANT_LAYOUTS: dict[int, tuple[int, int]] = {
    behavior: (
        _blocks_size(layout.leading),
        _blocks_size(layout.trailing)
        + (COMBATANT_COMMON.size if layout.repeats_common else 0),
    )
    for behavior, layout in COMBATANT_CLASS_LAYOUTS.items()
}
MAX_LIST_COUNT = 0x10000


class U9ProcessSectionsError(U9ProcessDataError):
    """Raised when a section after the process list is malformed."""


class _Reader:
    def __init__(self, data: bytes, offset: int) -> None:
        self.data = data
        self.offset = offset

    def take(self, fmt: str | struct.Struct, label: str) -> tuple:
        s = fmt if isinstance(fmt, struct.Struct) else struct.Struct("<" + fmt)
        if self.offset + s.size > len(self.data):
            raise U9ProcessSectionsError(
                f"truncated {label} at 0x{self.offset:X}: needs {s.size} bytes"
            )
        values = s.unpack_from(self.data, self.offset)
        self.offset += s.size
        return values

    def one(self, fmt: str, label: str) -> int | float:
        return self.take(fmt, label)[0]

    def raw(self, size: int, label: str) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise U9ProcessSectionsError(
                f"truncated {label} at 0x{self.offset:X}: needs {size} bytes"
            )
        chunk = bytes(self.data[self.offset : self.offset + size])
        self.offset += size
        return chunk

    def version(self, expected: int, label: str) -> int:
        at = self.offset
        value = int(self.one("i", f"{label} version"))
        if value != expected:
            raise U9ProcessSectionsError(
                f"unsupported {label} version {value} at 0x{at:X}"
            )
        return value

    def count(self, label: str) -> int:
        at = self.offset
        value = int(self.one("i", f"{label} count"))
        if not 0 <= value <= MAX_LIST_COUNT:
            raise U9ProcessSectionsError(f"invalid {label} count {value} at 0x{at:X}")
        return value

    def continuation(self, label: str) -> bool:
        """A 1-prefixed / 0-terminated list marker."""
        at = self.offset
        value = int(self.one("i", f"{label} marker"))
        if value not in (0, 1):
            raise U9ProcessSectionsError(f"invalid {label} marker {value} at 0x{at:X}")
        return value == 1


# --------------------------------------------------------------- 1: fast area


FAST_AREA_DISPLAY = 0x001
FAST_AREA_ACTIVE = 0x002
FAST_AREA_COLLISION = 0x004
FAST_AREA_WATER = 0x008
FAST_AREA_WATER_KIND_MASK = 0x030
FAST_AREA_WATER_KIND_SHIFT = 4
FAST_AREA_FLAT_WATER = 0x040
FAST_AREA_CHECKED = 0x080
FAST_AREA_INCOMPLETE = 0x100
FAST_AREA_UNDERGROUND_WATER = 0x200
FAST_AREA_WATER_KINDS = ("water", "swamp", "lava", "river")


@dataclass(frozen=True)
class U9FastAreaEntry:
    """One loaded chunk of the fast area around the player.

    ``chunk_x``/``chunk_y`` are the chunk coordinates; ``wrap_x``/``wrap_y``
    the same chunk after map wrap-around (equal to them on unwrapped maps).
    ``flags`` holds the chunk's display/active/collision state and water
    information (see the ``FAST_AREA_*`` bits).
    """

    chunk_x: int
    chunk_y: int
    wrap_x: int
    wrap_y: int
    flags: int

    @property
    def displayed(self) -> bool:
        return bool(self.flags & FAST_AREA_DISPLAY)

    @property
    def active(self) -> bool:
        return bool(self.flags & FAST_AREA_ACTIVE)

    @property
    def collision(self) -> bool:
        return bool(self.flags & FAST_AREA_COLLISION)

    @property
    def has_water(self) -> bool:
        return bool(self.flags & FAST_AREA_WATER)

    @property
    def water_kind(self) -> str:
        """``water``, ``swamp``, ``lava`` or ``river`` (meaningful with water)."""
        index = (self.flags & FAST_AREA_WATER_KIND_MASK) >> FAST_AREA_WATER_KIND_SHIFT
        return FAST_AREA_WATER_KINDS[index]

    @property
    def flat_water(self) -> bool:
        return bool(self.flags & FAST_AREA_FLAT_WATER)

    @property
    def underground_water(self) -> bool:
        return bool(self.flags & FAST_AREA_UNDERGROUND_WATER)


@dataclass(frozen=True)
class U9FastAreaState:
    """Version 1, then a byte-prefixed list of five-word entries."""

    version: int
    entries: tuple[U9FastAreaEntry, ...]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9FastAreaState:
        start = r.offset
        version = r.version(1, "fast-area")
        entries = []
        while True:
            at = r.offset
            flag = int(r.one("B", "fast-area marker"))
            if flag == 0:
                break
            if flag != 1:
                raise U9ProcessSectionsError(
                    f"invalid fast-area marker {flag} at 0x{at:X}"
                )
            entries.append(U9FastAreaEntry(*r.take("5i", "fast-area entry")))
        return cls(version, tuple(entries), start, r.offset)


# ------------------------------------------------------------- 2: NPC manager


@dataclass(frozen=True)
class U9NpcManagerState:
    """The NPC data manager: the NPC records again, plus lookup tables.

    ``npc_records`` is the 512 x 316-byte NPC array (parse it with
    :meth:`npcs`), ``type_table`` the first 512 16-byte type-table entries,
    ``npc_object_offsets`` each NPC's object offset in its region (0 when not
    loaded), then a 12-byte block the game appears never to use (saved
    uninitialized; zero in every checked save), the NPC record cache and
    four reserved words.

    ``npc_record_cache`` has one entry per authored NPC (the 352 records of
    ``NPC.FLX``): 0 not looked up yet, 1 no record in the current map, or the
    offset of that NPC's record in the map's object data. The game uses it
    to copy an original NPC's items into a spawned clone, and clears it when
    a save is loaded.
    """

    version: int
    npc_records: bytes
    type_table: bytes
    npc_object_offsets: tuple[int, ...]
    unused: bytes
    npc_record_cache: tuple[int, ...]
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    def npcs(self) -> U9Npcs:
        return U9Npcs(self.npc_records)

    @classmethod
    def read(cls, r: _Reader) -> U9NpcManagerState:
        start = r.offset
        version = r.version(2, "NPC-manager")
        records = r.raw(NPC_COUNT * NPC_RECORD_SIZE, "NPC records")
        type_table = r.raw(NPC_COUNT * TYPE_TABLE_RECORD_SIZE, "type table")
        offsets = r.take(f"{NPC_COUNT}i", "NPC object offsets")
        block = r.raw(12, "NPC-manager unused block")
        table = r.take(f"{NPC_RECORD_CACHE_SIZE}i", "NPC record cache")
        reserved = r.take("4I", "NPC-manager reserved")
        return cls(
            version,
            records,
            type_table,
            offsets,
            block,
            table,
            reserved,
            start,
            r.offset,  # type: ignore[arg-type]
        )


# -------------------------------------------------------------- 3: main UI


INTERFACE_ELEMENTS = (
    "health_bar",
    "mana_bar",
    "breath_bar",
    "armor_bar",
    "bar_4",
    "compass",
    "backpack",
    "spellbook",
    "journal",
    "toolbelt",
    "map",
)
INTERFACE_MODES = ("maximum", "minimum", "none")
ITEM_TYPE_COUNT = 8192


@dataclass(frozen=True)
class U9MainInterfaceState:
    """The on-screen interface: per-element availability and visibility,
    the display mode, and which item types the player has found.

    ``available`` and ``visible`` hold one flag per :data:`INTERFACE_ELEMENTS`
    entry; ``mode`` indexes :data:`INTERFACE_MODES` (all elements, minimal,
    none); ``found_item_types`` is one flag per item type (8,192).
    """

    version: int
    available: tuple[bool, ...]
    visible: tuple[bool, ...]
    mode: int
    equipment_shown: bool
    found_item_types: bytes
    offset: int
    end_offset: int

    @property
    def mode_name(self) -> str | None:
        return (
            INTERFACE_MODES[self.mode]
            if 0 <= self.mode < len(INTERFACE_MODES)
            else None
        )

    def element_flags(self) -> dict[str, tuple[bool, bool]]:
        """``{element: (available, visible)}`` for every interface element."""
        return dict(zip(INTERFACE_ELEMENTS, zip(self.available, self.visible)))

    def found_types(self) -> tuple[int, ...]:
        """Item type numbers marked as found."""
        return tuple(i for i, flag in enumerate(self.found_item_types) if flag)

    @classmethod
    def read(cls, r: _Reader) -> U9MainInterfaceState:
        start = r.offset
        version = r.version(3, "main-interface")
        n = len(INTERFACE_ELEMENTS)
        available = tuple(bool(b) for b in r.raw(n, "interface availability"))
        visible = tuple(bool(b) for b in r.raw(n, "interface visibility"))
        mode = int(r.one("i", "interface mode"))
        equipment = bool(r.one("B", "equipment-interface flag"))
        found = r.raw(ITEM_TYPE_COUNT, "found item types")
        return cls(version, available, visible, mode, equipment, found, start, r.offset)


# ---------------------------------------------------------------- 4: lights


@dataclass(frozen=True)
class U9SavedLight:
    """One saved light source (70 bytes)."""

    flags: int
    color: tuple[int, int, int]
    position: tuple[float, float, float]
    offset_from_object: tuple[float, float, float]
    diffusion: float
    light_range: float
    base_color: tuple[int, int, int]
    flicker_rate: float
    flicker_level: float
    flickers_randomly: int
    flicker_hue_jitter: float
    reserved: tuple[int, int]
    object_reference_index: int

    @classmethod
    def read(cls, r: _Reader) -> U9SavedLight:
        v = r.take(LIGHT_RECORD, "saved light")
        return cls(
            flags=v[0],
            color=v[1:4],
            position=v[4:7],
            offset_from_object=v[7:10],
            diffusion=v[10],
            light_range=v[11],
            base_color=v[12:15],
            flicker_rate=v[15],
            flicker_level=v[16],
            flickers_randomly=v[17],
            flicker_hue_jitter=v[18],
            reserved=v[19:21],
            object_reference_index=v[21],
        )


@dataclass(frozen=True)
class U9LightSystemState:
    """Ambient light, the unlimited- and limited-range light lists, settings."""

    version: int
    ambient: tuple[int, int, int]
    point_lights_enabled: int
    infinite_lights: tuple[U9SavedLight, ...]
    ranged_lights: tuple[U9SavedLight, ...]
    settings: tuple[int, ...]
    reserved: tuple[int, int]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9LightSystemState:
        start = r.offset
        version = r.version(1, "light-system")
        ambient = r.take("3i", "ambient light")
        enabled = int(r.one("i", "point-source flag"))
        lists = []
        for label in ("unlimited-range light", "limited-range light"):
            n = r.count(label)
            lists.append(tuple(U9SavedLight.read(r) for _ in range(n)))
        settings = r.take(f"{LIGHT_SETTINGS_COUNT}i", "light settings")
        reserved = r.take("2I", "light-system reserved")
        return cls(
            version,
            ambient,
            enabled,
            lists[0],
            lists[1],
            settings,  # type: ignore[arg-type]
            reserved,
            start,
            r.offset,  # type: ignore[arg-type]
        )


# --------------------------------------------------------------- 5: weather


WEATHER_STATES = ("clear", "overcast", "misty", "raining", "storming")
MOON_PHASES = (
    "new",
    "waxing crescent",
    "first quarter",
    "waxing gibbous",
    "full",
    "waning crescent",
    "last quarter",
    "waning gibbous",
)


def _enum_name(names: tuple[str, ...], value: int) -> str | None:
    return names[value] if 0 <= value < len(names) else None


@dataclass(frozen=True)
class U9WeatherLight:
    """A weather-owned light (sun, secondary light, lightning): whether it
    exists and its current colour (zero when absent)."""

    present: bool
    color: tuple[int, int, int]


@dataclass(frozen=True)
class U9ScreenFadeState:
    """The weather system's screen fade (centre and edge alpha ramps)."""

    fading: int
    center_rate: int
    edge_rate: int
    direction: int
    center_counter: int
    edge_counter: int
    center_alpha: int
    edge_alpha: int


@dataclass(frozen=True)
class U9WeatherState:
    """Version 2: clocks, sky state, storm, wind and gusts, rain and
    lightning timers, the sun/secondary/lightning lights, moon phases, the
    sun-mask objects (counted object references) and the screen fade.

    ``weather_time`` and ``sun_time`` are seconds of the day;
    ``current_state``/``desired_state`` index :data:`WEATHER_STATES`;
    ``transition_time`` is when the desired state is reached; the moon phases
    index :data:`MOON_PHASES`. Gust times are engine tick counts.
    """

    version: int
    weather_time: int
    sun_time: int
    storm_timer: int
    total_seconds: int
    weather_time_ms: float
    underground: int
    sun_enabled: int
    current_state: int
    desired_state: int
    transition_time: int
    storm_position: tuple[float, float, float]
    storm_velocity: tuple[float, float, float]
    storm_intensity: float
    storm_radius: float
    storm_intensity_cap: float
    wind_strength: int
    wind_vector: tuple[float, float]
    wind_direction: float
    gust_magnitude: int
    gust_start_time: int
    gust_end_time: int
    gust_sound_time: int
    rain_drop_count: int
    rain_time: float
    lightning_duration: float
    lightning_time: float
    sun: U9WeatherLight
    secondary_light: U9WeatherLight
    lightning: U9WeatherLight
    lens_flare_enabled: int
    lens_flare_hidden: int
    trammel_phase: int
    felucca_phase: int
    sun_mask_scale: float
    sun_mask_reference_indices: tuple[int, ...]
    screen_fade: U9ScreenFadeState
    reserved: tuple[int, int]
    offset: int
    end_offset: int

    @property
    def current_state_name(self) -> str | None:
        return _enum_name(WEATHER_STATES, self.current_state)

    @property
    def desired_state_name(self) -> str | None:
        return _enum_name(WEATHER_STATES, self.desired_state)

    @property
    def trammel_phase_name(self) -> str | None:
        return _enum_name(MOON_PHASES, self.trammel_phase)

    @property
    def felucca_phase_name(self) -> str | None:
        return _enum_name(MOON_PHASES, self.felucca_phase)

    @classmethod
    def read(cls, r: _Reader) -> U9WeatherState:
        start = r.offset
        version = r.version(2, "weather")
        v = r.take(WEATHER_STATE, "weather state")
        n = r.count("sun mask")
        refs = r.take(f"{n}i", "sun masks")
        t = r.take(WEATHER_FADE, "weather screen fade")
        return cls(
            version=version,
            weather_time=v[0],
            sun_time=v[1],
            storm_timer=v[2],
            total_seconds=v[3],
            weather_time_ms=v[4],
            underground=v[5],
            sun_enabled=v[6],
            current_state=v[7],
            desired_state=v[8],
            transition_time=v[9],
            storm_position=v[10:13],
            storm_velocity=v[13:16],
            storm_intensity=v[16],
            storm_radius=v[17],
            storm_intensity_cap=v[18],
            wind_strength=v[19],
            wind_vector=v[20:22],
            wind_direction=v[22],
            gust_magnitude=v[23],
            gust_start_time=v[24],
            gust_end_time=v[25],
            gust_sound_time=v[26],
            rain_drop_count=v[27],
            rain_time=v[28],
            lightning_duration=v[29],
            lightning_time=v[30],
            sun=U9WeatherLight(bool(v[31]), v[32:35]),
            secondary_light=U9WeatherLight(bool(v[35]), v[36:39]),
            lightning=U9WeatherLight(bool(v[39]), v[40:43]),
            lens_flare_enabled=v[43],
            lens_flare_hidden=v[44],
            trammel_phase=v[45],
            felucca_phase=v[46],
            sun_mask_scale=v[47],
            sun_mask_reference_indices=refs,
            screen_fade=U9ScreenFadeState(*t[:8]),
            reserved=t[8:10],
            offset=start,
            end_offset=r.offset,
        )


# ---------------------------------------------------------- 6: spell manager


@dataclass(frozen=True)
class U9SpellManagerState:
    """Version 0 and the process IDs of the spells running at save time."""

    version: int
    active_spell_process_ids: tuple[int, ...]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9SpellManagerState:
        start = r.offset
        version = r.version(0, "spell-manager")
        n = r.count("active spell")
        ids = r.take(f"{n}i", "active spells")
        return cls(version, ids, start, r.offset)  # type: ignore[arg-type]


# --------------------------------------------------------------- 7: physics


@dataclass(frozen=True)
class U9PhysicsObject:
    """One object under physics simulation at save time."""

    object_reference_index: int
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    velocity: tuple[float, float, float]
    angular_momentum: tuple[float, float, float]
    angular_velocity: tuple[float, float, float]
    water_level: float
    not_moving: int
    mass: float


@dataclass(frozen=True)
class U9TriggerOverlap:
    trigger_object_reference_index: int
    flags: int
    velocity: int


@dataclass(frozen=True)
class U9CollisionOverlap:
    """An object and the trigger objects it overlapped at save time."""

    object_reference_index: int
    triggers: tuple[U9TriggerOverlap, ...]
    reserved: int


@dataclass(frozen=True)
class U9PhysicsState:
    version: int
    map_number: int
    objects: tuple[U9PhysicsObject, ...]
    overlaps: tuple[U9CollisionOverlap, ...]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9PhysicsState:
        start = r.offset
        version = r.version(1, "physics")
        map_number = int(r.one("i", "physics map number"))
        objects = []
        while r.continuation("physics object"):
            v = r.take(PHYSICS_OBJECT, "physics object")
            objects.append(
                U9PhysicsObject(
                    object_reference_index=v[0],
                    position=v[1:4],
                    orientation=v[4:8],
                    velocity=v[8:11],
                    angular_momentum=v[11:14],
                    angular_velocity=v[14:17],
                    water_level=v[17],
                    not_moving=v[18],
                    mass=v[19],
                )
            )
        overlaps = []
        while True:
            at = r.offset
            n = int(r.one("i", "overlap trigger count"))
            if n == 0:
                break
            if not 0 < n <= MAX_LIST_COUNT:
                raise U9ProcessSectionsError(
                    f"invalid overlap trigger count {n} at 0x{at:X}"
                )
            (ref,) = r.take("i", "overlap object")
            triggers = tuple(
                U9TriggerOverlap(*r.take("iii", "trigger overlap")) for _ in range(n)
            )
            (reserved,) = r.take("i", "overlap reserved")
            overlaps.append(U9CollisionOverlap(ref, triggers, reserved))
        return cls(
            version, map_number, tuple(objects), tuple(overlaps), start, r.offset
        )


# ------------------------------------------------------- 8: moving platforms


@dataclass(frozen=True)
class U9SupportedObject:
    """An object riding a moving platform."""

    object_reference_index: int
    old_location: tuple[float, float, float]
    old_orientation: tuple[float, float, float, float]
    old_yaw: float
    support_ticks: int
    delta_yaw: float
    original_location: tuple[float, float, float]
    original_orientation: tuple[float, float, float, float]
    rider_location: tuple[float, float, float]


@dataclass(frozen=True)
class U9MovingPlatform:
    """One moving platform. ``kind``: 0 plain, 1 floating lift (with a path),
    2 floating step, 3 ship, 4 a fifth kind; ``own`` holds the kind's fields."""

    kind: int
    supporting_object_reference_index: int
    reserved: tuple[int, int, int, int]
    supported_objects: tuple[U9SupportedObject, ...]
    path: U9PathManagerState | None
    own: bytes


@dataclass(frozen=True)
class U9MovingPlatformsState:
    version: int
    ignore_state_changes: int
    supports: tuple[U9MovingPlatform, ...]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader, object_reference_count: int) -> U9MovingPlatformsState:
        start = r.offset
        version = r.version(1, "moving-platform")
        ignore = int(r.one("i", "moving-platform flag"))
        supports = []
        while r.continuation("moving platform"):
            at = r.offset
            kind, supporting = r.take("ii", "moving platform")
            if kind not in SUPPORT_OWN_SIZES:
                raise U9ProcessSectionsError(
                    f"unknown moving-platform kind {kind} at 0x{at:X}"
                )
            reserved = r.take("4I", "moving-platform reserved")
            riders = []
            while r.continuation("supported object"):
                v = r.take(SUPPORTED_OBJECT, "supported object")
                riders.append(
                    U9SupportedObject(
                        object_reference_index=v[0],
                        old_location=v[1:4],
                        old_orientation=v[4:8],
                        old_yaw=v[8],
                        support_ticks=v[9],
                        delta_yaw=v[10],
                        original_location=v[11:14],
                        original_orientation=v[14:18],
                        rider_location=v[18:21],
                    )
                )
            path = None
            if kind == 1:
                path = U9PathManagerState.from_bytes(
                    r.data, r.offset, object_reference_count=object_reference_count
                )
                r.offset = path.end_offset
            own = r.raw(SUPPORT_OWN_SIZES[kind], "moving-platform fields")
            supports.append(
                U9MovingPlatform(kind, supporting, reserved, tuple(riders), path, own)  # type: ignore[arg-type]
            )
        return cls(version, ignore, tuple(supports), start, r.offset)


# ------------------------------------------------------- 9: highway manager


@dataclass(frozen=True)
class U9HighwayMover:
    """An NPC travelling along a highway while its object is not loaded.

    The game advances the NPC's stored position node by node (steps of up
    to 512 units) and hands it to the normal walking code once its object is
    loaded. ``speed`` is the highway length divided by the travel time
    (clamped to 1..30, default 7.5). ``frozen_location`` is integer X/Y and
    a 16-bit Z; it is meaningful only while :attr:`position_frozen`.
    """

    flags: int
    npc_number: int
    highway: int
    node: int
    speed: float
    milliseconds_to_next_step: int
    frozen_location: tuple[int, int, int]

    @property
    def walk_started(self) -> bool:
        return bool(self.flags & 0x1)

    @property
    def walk_flag_passed(self) -> bool:
        return bool(self.flags & 0x2)

    @property
    def position_frozen(self) -> bool:
        return bool(self.flags & 0x4)


@dataclass(frozen=True)
class U9HighwayManagerState:
    """Version 2, the highway movers (at most 64; removal swaps in the last
    one, so their order is not the order they started), a step phase (0 or
    1: movers step every second frame) and four reserved words."""

    version: int
    movers: tuple[U9HighwayMover, ...]
    step_phase: int
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9HighwayManagerState:
        start = r.offset
        version = r.version(2, "highway-manager")
        at = r.offset
        n = r.count("highway mover")
        if n > HIGHWAY_MOVER_LIMIT:
            raise U9ProcessSectionsError(f"invalid highway mover count {n} at 0x{at:X}")
        movers = []
        for _ in range(n):
            v = r.take(HIGHWAY_MOVER, "highway mover")
            movers.append(U9HighwayMover(v[0], v[1], v[2], v[3], v[4], v[5], v[6:9]))
        step_phase = int(r.one("i", "highway step phase"))
        reserved = r.take("4I", "highway-manager reserved")
        return cls(version, tuple(movers), step_phase, reserved, start, r.offset)  # type: ignore[arg-type]


# ------------------------------------------------------------ 10: hints


@dataclass(frozen=True)
class U9HintRecord:
    object_reference_index_1: int
    object_reference_index_2: int
    values: tuple[int, int, int, int, int, int]
    reserved: tuple[int, int, int, int]


@dataclass(frozen=True)
class U9HintManagerState:
    version: int
    hints: tuple[U9HintRecord, ...]
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9HintManagerState:
        start = r.offset
        version = r.version(3, "hint-manager")
        n = r.count("hint")
        hints = []
        for _ in range(n):
            v = r.take(HINT_RECORD, "hint")
            hints.append(U9HintRecord(v[0], v[1], v[2:8], v[8:12]))  # type: ignore[arg-type]
        reserved = r.take("4I", "hint-manager reserved")
        return cls(version, tuple(hints), reserved, start, r.offset)  # type: ignore[arg-type]


# ------------------------------------------------------------ 11: combat


@dataclass(frozen=True)
class U9CombatantCommonState:
    """The 268-byte part every combatant saves (version 5)."""

    version: int
    npc_type: int
    stun_delay: int
    has_enemies: int
    impact_animation_kind: int
    invulnerable_timer: int
    current_animation_id: int
    attack_level: int
    combatant_radius: float
    noticed_enemies: int
    home_location: tuple[int, int, int]
    near_avatar: int
    idle_without_enemies_delay: int
    route_speed: int
    route_tolerance: float
    route_failures: int
    route_failure_limit: int
    waiting_for_route: int
    locked_in_place: int
    poisoned_hit_points: int
    poison_timer: int
    carried_object_bytes: bytes
    preferred_target_kind: int
    ally_kind: int
    ally_reference: int
    stored_ally_kind: int
    stored_ally_reference: int
    homing_missile_enemy_type: int
    ghost_push_counter: int
    uses_straight_line_paths: int
    projectile_immune: int
    combat_fog_active: int
    last_destination: tuple[float, float, float]
    wander_failures: int
    reversing: int
    charm_source_npc_type: int

    @classmethod
    def read(cls, r: _Reader, expected_npc_type: int) -> U9CombatantCommonState:
        at = r.offset
        v = r.take(COMBATANT_COMMON, "combatant common part")
        if v[0] != COMBATANT_COMMON_VERSION:
            raise U9ProcessSectionsError(
                f"unsupported combatant version {v[0]} at 0x{at:X}"
            )
        if v[1] != expected_npc_type:
            raise U9ProcessSectionsError(
                f"combatant at 0x{at:X} is NPC type {v[1]}, expected {expected_npc_type}"
            )
        return cls(
            version=v[0],
            npc_type=v[1],
            stun_delay=v[2],
            has_enemies=v[3],
            impact_animation_kind=v[4],
            invulnerable_timer=v[5],
            current_animation_id=v[6],
            attack_level=v[7],
            combatant_radius=v[8],
            noticed_enemies=v[9],
            home_location=v[10:13],
            near_avatar=v[13],
            idle_without_enemies_delay=v[14],
            route_speed=v[15],
            route_tolerance=v[16],
            route_failures=v[17],
            route_failure_limit=v[18],
            waiting_for_route=v[19],
            locked_in_place=v[20],
            poisoned_hit_points=v[21],
            poison_timer=v[22],
            carried_object_bytes=v[23],
            preferred_target_kind=v[24],
            ally_kind=v[25],
            ally_reference=v[26],
            stored_ally_kind=v[27],
            stored_ally_reference=v[28],
            homing_missile_enemy_type=v[29],
            ghost_push_counter=v[30],
            uses_straight_line_paths=v[31],
            projectile_immune=v[32],
            combat_fog_active=v[33],
            last_destination=v[34:37],
            wander_failures=v[37],
            reversing=v[38],
            charm_source_npc_type=v[39],
        )


@dataclass(frozen=True)
class U9CombatantClassFields:
    """One class save's own fields, in stream order.

    ``kind`` names the class (``humanoid``, ``avatar``, ``wolf`` ...).
    ``values`` holds ``(name, value)`` pairs: vectors and arrays as tuples,
    object references as reference-table indices (names without a suffix,
    such as ``shield``), byte flags as their stored byte. Index by name
    (``fields["current_state"]``).
    """

    kind: str
    version: int | None
    values: tuple[tuple[str, object], ...]
    object_reference_indices: tuple[int, ...] = ()

    def __getitem__(self, name: str) -> object:
        for key, value in self.values:
            if key == name:
                return value
        raise KeyError(name)

    @property
    def fields(self) -> dict[str, object]:
        return dict(self.values)

    @classmethod
    def read(cls, r: _Reader, block: _CombatantBlock) -> U9CombatantClassFields:
        at = r.offset
        raw = r.take(block.layout, f"{block.kind.replace('_', '-')} combatant fields")
        cursor = 0
        if block.version is not None:
            if raw[0] != block.version:
                raise U9ProcessSectionsError(
                    f"unsupported {block.kind.replace('_', '-')} combatant "
                    f"version {raw[0]} at 0x{at:X}"
                )
            cursor = 1
        values: list[tuple[str, object]] = []
        references: list[int] = []
        for (name, fmt), count in zip(block.fields, block.value_counts):
            chunk = raw[cursor : cursor + count]
            values.append((name, chunk[0] if count == 1 else tuple(chunk)))
            if fmt == "r":
                references.append(chunk[0])
            cursor += count
        return cls(block.kind, block.version, tuple(values), tuple(references))


@dataclass(frozen=True)
class U9CombatantRecord:
    """One combatant: class fields written before the common part, the
    common part, and class fields written after it.

    The class is chosen by the NPC's combat behaviour ID (``combat_behavior``,
    from the NPC data manager's copy of the NPC record). ``leading_fields``
    and ``trailing_fields`` decode the class saves in stream order (outermost
    parent first for trailing fields, the subclass first for leading ones);
    ``leading``/``trailing`` keep the same bytes raw. ``repeated_common`` is
    the second common part the creeper class writes.
    """

    npc_type: int
    combat_behavior: int
    leading: bytes
    common: U9CombatantCommonState
    trailing: bytes
    offset: int
    end_offset: int
    leading_fields: tuple[U9CombatantClassFields, ...] = ()
    trailing_fields: tuple[U9CombatantClassFields, ...] = ()
    repeated_common: U9CombatantCommonState | None = None

    @property
    def class_fields(self) -> tuple[U9CombatantClassFields, ...]:
        return self.leading_fields + self.trailing_fields


@dataclass(frozen=True)
class U9CombatState:
    """Version 3, the combatants' NPC types, one record per combatant, and
    three final words."""

    version: int
    npc_types: tuple[int, ...]
    combatants: tuple[U9CombatantRecord, ...]
    tail: tuple[int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader, npc_records: bytes) -> U9CombatState:
        start = r.offset
        version = r.version(3, "combat")
        n = r.count("combatant")
        npc_types = r.take(f"{n}i", "combatant NPC types")
        combatants = []
        for npc_type in npc_types:
            if not 0 <= npc_type < NPC_COUNT:
                raise U9ProcessSectionsError(f"invalid combatant NPC type {npc_type}")
            (behavior,) = struct.unpack_from(
                "<i", npc_records, npc_type * NPC_RECORD_SIZE + COMBAT_BEHAVIOR_OFFSET
            )
            layout = COMBATANT_CLASS_LAYOUTS.get(behavior, _CombatantLayout())
            record_start = r.offset
            leading_fields = tuple(
                U9CombatantClassFields.read(r, block) for block in layout.leading
            )
            common_start = r.offset
            common = U9CombatantCommonState.read(r, npc_type)
            trailing_start = r.offset
            trailing_fields = tuple(
                U9CombatantClassFields.read(r, block) for block in layout.trailing
            )
            repeated = (
                U9CombatantCommonState.read(r, npc_type)
                if layout.repeats_common
                else None
            )
            combatants.append(
                U9CombatantRecord(
                    npc_type,
                    behavior,
                    bytes(r.data[record_start:common_start]),
                    common,
                    bytes(r.data[trailing_start : r.offset]),
                    record_start,
                    r.offset,
                    leading_fields,
                    trailing_fields,
                    repeated,
                )
            )
        tail = r.take("3i", "combat tail")
        return cls(version, npc_types, tuple(combatants), tail, start, r.offset)  # type: ignore[arg-type]


# ------------------------------------------------------ 12-13: book, sound


@dataclass(frozen=True)
class U9BookState:
    """Version 1, a page bookmark per book, two chapter bookmarks, a word."""

    version: int
    page_bookmarks: tuple[int, ...]
    chapter_bookmarks: tuple[int, int]
    word: int
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9BookState:
        start = r.offset
        version = r.version(1, "book")
        pages = r.take(f"{BOOK_PAGE_COUNT}i", "page bookmarks")
        chapters = r.take("2i", "chapter bookmarks")
        word = int(r.one("i", "book word"))
        return cls(version, pages, chapters, word, start, r.offset)  # type: ignore[arg-type]


@dataclass(frozen=True)
class U9MusicNode:
    """One entry of the music list (30 bytes).

    Tick values are absolute engine ticks; the game rebases them on load.
    ``unused`` is a byte nothing sets.
    """

    track: int
    priority: int
    playing: int
    piece: int
    start_volume: int
    target_volume: int
    fade_start_tick: int
    fade_end_tick: int
    last_update_tick: int
    fading_in: int
    remove_after_fade: int
    unused: int


@dataclass(frozen=True)
class U9SoundSystemState:
    """The sound system's music list: version 2, a count, that many music
    nodes. It is the last section, so it must end at the end of the file."""

    version: int
    music_nodes: tuple[U9MusicNode, ...]
    offset: int
    end_offset: int

    @classmethod
    def read(cls, r: _Reader) -> U9SoundSystemState:
        start = r.offset
        version = r.version(SOUND_SYSTEM_VERSION, "sound-system")
        n = r.count("music node")
        nodes = tuple(U9MusicNode(*r.take(MUSIC_NODE, "music node")) for _ in range(n))
        if r.offset != len(r.data):
            raise U9ProcessSectionsError(
                f"{len(r.data) - r.offset} bytes follow the music list at "
                f"0x{r.offset:X}"
            )
        return cls(version, nodes, start, r.offset)


# -------------------------------------------------------------- the reader


def _validate_references(sections: U9ProcessSections, count: int) -> None:
    """Every object reference in these sections must index the table."""

    def check(value: int, label: str) -> None:
        if not 0 <= value < count:
            raise U9ProcessSectionsError(
                f"{label} object-reference index {value} is outside 0..{count - 1}"
            )

    for light in sections.lights.infinite_lights + sections.lights.ranged_lights:
        check(light.object_reference_index, "saved light")
    for ref in sections.weather.sun_mask_reference_indices:
        check(ref, "sun mask")
    for obj in sections.physics.objects:
        check(obj.object_reference_index, "physics")
    for overlap in sections.physics.overlaps:
        check(overlap.object_reference_index, "overlap")
        for trigger in overlap.triggers:
            check(trigger.trigger_object_reference_index, "overlap trigger")
    for support in sections.moving_platforms.supports:
        check(support.supporting_object_reference_index, "moving platform")
        for rider in support.supported_objects:
            check(rider.object_reference_index, "supported object")
    for hint in sections.hints.hints:
        check(hint.object_reference_index_1, "hint")
        check(hint.object_reference_index_2, "hint")
    for block in (b for c in sections.combat.combatants for b in c.class_fields):
        for ref in block.object_reference_indices:
            check(ref, f"{block.kind.replace('_', ' ')} combatant")


@dataclass(frozen=True)
class U9ProcessSections:
    """All thirteen sections after the process list, ending at end of file."""

    fast_area: U9FastAreaState
    npc_manager: U9NpcManagerState
    main_interface: U9MainInterfaceState
    lights: U9LightSystemState
    weather: U9WeatherState
    spell_manager: U9SpellManagerState
    physics: U9PhysicsState
    moving_platforms: U9MovingPlatformsState
    highway_manager: U9HighwayManagerState
    hints: U9HintManagerState
    combat: U9CombatState
    books: U9BookState
    sounds: U9SoundSystemState
    offset: int
    end_offset: int

    @classmethod
    def from_prefix(cls, data: bytes, prefix: U9ProcessDataPrefix) -> U9ProcessSections:
        if prefix.terminator_offset is None:
            raise U9ProcessSectionsError(
                "the process list was not read to its terminator"
            )
        return cls.from_bytes(
            data,
            prefix.terminator_offset + 4,
            object_reference_count=prefix.object_references.count,
        )

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9ProcessSections:
        r = _Reader(data, offset)
        fast_area = U9FastAreaState.read(r)
        npc_manager = U9NpcManagerState.read(r)
        main_interface = U9MainInterfaceState.read(r)
        lights = U9LightSystemState.read(r)
        weather = U9WeatherState.read(r)
        spell_manager = U9SpellManagerState.read(r)
        physics = U9PhysicsState.read(r)
        moving_platforms = U9MovingPlatformsState.read(r, object_reference_count)
        highway_manager = U9HighwayManagerState.read(r)
        hints = U9HintManagerState.read(r)

        combat = U9CombatState.read(r, npc_manager.npc_records)
        books = U9BookState.read(r)
        sounds = U9SoundSystemState.read(r)
        sections = cls(
            fast_area,
            npc_manager,
            main_interface,
            lights,
            weather,
            spell_manager,
            physics,
            moving_platforms,
            highway_manager,
            hints,
            combat,
            books,
            sounds,
            offset,
            r.offset,
        )
        _validate_references(sections, object_reference_count)
        return sections
