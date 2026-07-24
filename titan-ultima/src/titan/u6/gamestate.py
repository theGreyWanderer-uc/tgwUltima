"""
Broader save-game state for Ultima 6: party, player, and game clock/weather.

Not documented anywhere. Covers the rest of the ``objlist`` structure
:mod:`titan.u6.actor` deliberately left out (see that module's docstring):
built from and confirmed field-for-field against Nuvie's ``Party.cpp``,
``Player.cpp``, ``GameClock.cpp``, and ``Weather.cpp`` (all of which
share the same ``objlist`` buffer at fixed offsets, exactly like the
per-actor tables).

Validated against a real ``objlist_tail`` (the tail of ``LZDNGBLK``'s
decompressed stream -- a fresh game's initial state): the starting party
is Avatar/Dupre/Shamino/Iolo at actor IDs 1/2/3/4, exactly matching
``N_AVATAR=1``/``N_DUPRE=2``/``N_SHAMINO=3``/``N_IOLO=4`` from
:mod:`titan.u6.converse`'s default symbol table (u6edit's help docs) --
tying this module directly back to the CONVERSE disassembler's own
validation (item 2 there was confirmed to be Dupre's script). The game
clock decodes to July 4, year 161 at 8:00, matching Ultima VI's actual
in-lore start date.

Layout (all offsets within the shared ``objlist`` buffer)::

    0x0f00  party member names: PARTY_NAME_SLOT_SIZE bytes each,
            num_in_party entries (not a fixed 16-slot array -- only as
            many names as are actually in the party)
    0x0fe0  party roster: 1 byte each (actor ID), num_in_party entries
    0x0ff0  num_in_party: u8
    0x1bf1  quest_flag: u8
    0x1bf2  rest_counter: u8
    0x1bf3  game time: minute u8, hour u8, day u8, month u8, year u16 (LE)
    0x1bf9  karma: u8
    0x1bfa  wind_dir: u8 (0-7 = N/NE/E/SE/S/SW/W/NW; >7, typically 0xff, = calm)
    0x1c03  timers: u8 x 16 (spell/effect countdowns; not further decoded)
    0x1c17  alcohol: u8
    0x1c5f  gargish_flag: u8 (nonzero = player has learned Gargish)
    0x1c69  party combat_mode: u8 (party-wide; distinct from each actor's
            own per-actor combat_mode in titan.u6.actor)
    0x1c6a  solo_mode: u8 (0xff = full party mode; otherwise the 0-based
            party-roster index of the sole active member)
    0x1c71  gender: u8 (0=male, 1=female; matches Converse.h's
            U6TALK_VAR_SEX comment)

Deliberately not covered: the moonstone/eclipse/command-bar offsets also
documented in Nuvie's ``save/Objlist.h`` -- UI layout and a handful of
rarer bits of state, lower value for a format-extraction tool than the
core party/player/clock state above.

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.object import U6WorldObjects
    from titan.u6.gamestate import U6GameState

    world = U6WorldObjects.from_directory("C:/Ultima/Ultima6")
    state = U6GameState.parse(world.objlist_tail)
    print(state.clock.date_string(), state.clock.time_string())
    for member in state.party.members:
        print(member.name, member.actor_id)
"""

from __future__ import annotations

__all__ = [
    "U6GameState",
    "U6GameStateError",
    "U6Party",
    "U6PartyMember",
    "U6PlayerState",
    "U6GameClock",
    "WIND_DIRECTIONS",
    "PARTY_MODE_SENTINEL",
]

import struct
from dataclasses import dataclass, field

NUM_TIMERS = 16
PARTY_NAME_MAX_LENGTH = 13
PARTY_NAME_SLOT_SIZE = PARTY_NAME_MAX_LENGTH + 1  # + null terminator

OFFSET_PARTY_NAMES = 0x0F00
OFFSET_PARTY_ROSTER = 0x0FE0
OFFSET_NUM_IN_PARTY = 0x0FF0
OFFSET_QUEST_FLAG = 0x1BF1
OFFSET_REST_COUNTER = 0x1BF2
OFFSET_GAMETIME = 0x1BF3
OFFSET_KARMA = 0x1BF9
OFFSET_WIND_DIR = 0x1BFA
OFFSET_TIMERS = 0x1C03
OFFSET_ALCOHOL = 0x1C17
OFFSET_GARGISH_LANG = 0x1C5F
OFFSET_PARTY_COMBAT_MODE = 0x1C69
OFFSET_SOLO_MODE = 0x1C6A
OFFSET_GENDER = 0x1C71

REQUIRED_SIZE = OFFSET_GENDER + 1  # smallest buffer this module can fully read

PARTY_MODE_SENTINEL = 0xFF
WIND_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

MONTH_NAMES = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


class U6GameStateError(Exception):
    """Raised when objlist data is too short to contain these fields."""


@dataclass
class U6PartyMember:
    name: str
    actor_id: int


@dataclass
class U6Party:
    members: list[U6PartyMember] = field(default_factory=list)
    in_combat_mode: bool = False

    @property
    def num_members(self) -> int:
        return len(self.members)


@dataclass
class U6GameClock:
    minute: int
    hour: int
    day: int
    month: int
    year: int
    rest_counter: int
    timers: list[int]

    def date_string(self) -> str:
        month_name = MONTH_NAMES[self.month] if 0 < self.month < len(MONTH_NAMES) else str(self.month)
        return f"{month_name} {self.day}, year {self.year}"

    def time_string(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


@dataclass
class U6PlayerState:
    quest_flag: int
    karma: int
    alcohol: int
    knows_gargish: bool
    solo_mode: bool
    solo_member_index: int | None  # 0-based party-roster index; None if in full party mode
    gender: int  # 0=male, 1=female

    @property
    def gender_word(self) -> str:
        return "female" if self.gender == 1 else "male"


@dataclass
class U6GameState:
    party: U6Party
    clock: U6GameClock
    player: U6PlayerState
    wind_direction: str | None  # None = calm

    @classmethod
    def parse(cls, data: bytes) -> U6GameState:
        if len(data) < REQUIRED_SIZE:
            raise U6GameStateError(f"objlist data too short: {len(data)} bytes, need at least {REQUIRED_SIZE}")

        num_in_party = data[OFFSET_NUM_IN_PARTY]
        names_needed = OFFSET_PARTY_NAMES + num_in_party * PARTY_NAME_SLOT_SIZE
        roster_needed = OFFSET_PARTY_ROSTER + num_in_party
        if len(data) < max(names_needed, roster_needed):
            raise U6GameStateError(
                f"objlist data too short for {num_in_party} party member(s): {len(data)} bytes"
            )

        members: list[U6PartyMember] = []
        for i in range(num_in_party):
            off = OFFSET_PARTY_NAMES + i * PARTY_NAME_SLOT_SIZE
            raw_name = data[off:off + PARTY_NAME_SLOT_SIZE]
            name = raw_name.split(b"\x00", 1)[0].decode("latin-1")
            actor_id = data[OFFSET_PARTY_ROSTER + i]
            members.append(U6PartyMember(name=name, actor_id=actor_id))
        party = U6Party(members=members, in_combat_mode=bool(data[OFFSET_PARTY_COMBAT_MODE]))

        minute, hour, day, month = data[OFFSET_GAMETIME:OFFSET_GAMETIME + 4]
        year = struct.unpack_from("<H", data, OFFSET_GAMETIME + 4)[0]
        timers = list(data[OFFSET_TIMERS:OFFSET_TIMERS + NUM_TIMERS])
        clock = U6GameClock(
            minute=minute, hour=hour, day=day, month=month, year=year,
            rest_counter=data[OFFSET_REST_COUNTER], timers=timers,
        )

        solo_raw = data[OFFSET_SOLO_MODE]
        solo_mode = solo_raw != PARTY_MODE_SENTINEL
        player = U6PlayerState(
            quest_flag=data[OFFSET_QUEST_FLAG],
            karma=data[OFFSET_KARMA],
            alcohol=data[OFFSET_ALCOHOL],
            knows_gargish=bool(data[OFFSET_GARGISH_LANG]),
            solo_mode=solo_mode,
            solo_member_index=solo_raw if solo_mode else None,
            gender=data[OFFSET_GENDER],
        )

        wind_raw = data[OFFSET_WIND_DIR]
        wind_direction = WIND_DIRECTIONS[wind_raw] if wind_raw <= 7 else None

        return cls(party=party, clock=clock, player=player, wind_direction=wind_direction)
