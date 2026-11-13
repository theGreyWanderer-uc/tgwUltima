"""Read-only MD party, clock, dream and berry state from original DOS OBJLIST.

Offsets follow Nuvie's save/Objlist.h, GameClock.cpp and scripts/md/init.lua.
GAME.EXE's save-load reconstruction requires actor 118 talk flags 5 AND 6
for wet canals; flag 5 alone fills the cistern.
See reference/md/animation/md_water_animation_reference.md.
Power uses actor 115 flag 2 (scripts/md/usecode.lua activate_power_system).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime

from titan.md.actor import MD_ACTOR_LAYOUT
from titan.u6.gamestate import U6PartyMember

__all__ = [
    "MD_STATE_REQUIRED_SIZE",
    "MartianClock",
    "MartianBerryTimer",
    "MartianGameState",
]

MD_STATE_REQUIRED_SIZE = 0x1D55


@dataclass(frozen=True)
class MartianClock:
    """MD clock fields use the Gregorian date at OBJLIST 0x1cf3."""

    minute: int
    hour: int
    day: int
    month: int
    year: int

    def iso_string(self) -> str:
        """Format the saved in-game date and time without a host timezone conversion."""
        return datetime(
            self.year, self.month, self.day, self.hour, self.minute
        ).isoformat(timespec="minutes")


@dataclass(frozen=True)
class MartianBerryTimer:
    """Nibble-packed purple, green and brown berry timers for actor slots 0-15."""

    actor_id: int
    purple: int
    green: int
    brown: int


@dataclass
class MartianGameState:
    """Confirmed MD fields only; U6 karma, sacred-quest and Gargish fields are not reused."""

    party: list[U6PartyMember]
    clock: MartianClock
    gender: int
    in_dream_mode: bool
    dream_stage: int
    hours_until_healing: int
    blue_berry_counter: int
    berry_timers: list[MartianBerryTimer]
    power_active: bool
    cistern_filled: bool
    canal_valves_open: bool
    street_lights_active: bool
    saved_light_level: int
    active_party_index: int

    @property
    def brown_berry_vision(self) -> bool:
        """The DOS renderer uses the selected party actor's low-nibble brown berry timer."""
        actor_id = (
            self.party[self.active_party_index].actor_id
            if self.active_party_index < len(self.party)
            else 0
        )
        return any(
            timer.actor_id == actor_id and timer.brown > 0
            for timer in self.berry_timers
        )

    @property
    def canals_filled(self) -> bool:
        """Canal water needs both cistern pressure and opened valves in the DOS engine."""
        return self.cistern_filled and self.canal_valves_open

    @classmethod
    def parse(cls, data: bytes) -> MartianGameState:
        """Decode a packaged or DOS-saved MD OBJLIST, rejecting incomplete state."""
        if len(data) < MD_STATE_REQUIRED_SIZE:
            raise ValueError(
                f"Martian Dreams OBJLIST too short: {len(data)} bytes, need {MD_STATE_REQUIRED_SIZE}"
            )
        count = data[0xFF0]
        if count > 16:
            raise ValueError(f"Invalid Martian Dreams party size: {count}")
        party = [
            U6PartyMember(
                name=data[0xF00 + i * 14 : 0xF00 + (i + 1) * 14]
                .split(b"\0", 1)[0]
                .decode("latin-1"),
                actor_id=data[0xFE0 + i],
            )
            for i in range(count)
        ]
        minute, hour, day, month, year = struct.unpack_from("<4BH", data, 0x1CF3)
        clock = MartianClock(minute, hour, day, month, year)
        try:
            clock.iso_string()
        except ValueError as exc:
            raise ValueError(f"Invalid Martian Dreams game clock: {exc}") from exc
        timers = [
            MartianBerryTimer(
                i,
                data[0x1D2F + i * 2] & 15,
                data[0x1D2F + i * 2] >> 4,
                data[0x1D30 + i * 2] & 15,
            )
            for i in range(16)
        ]
        return cls(
            party=party,
            clock=clock,
            gender=data[0x1D27],
            in_dream_mode=bool(struct.unpack_from("<H", data, 0x1D29)[0] & 0x10),
            dream_stage=struct.unpack_from("<H", data, 0x1D53)[0],
            hours_until_healing=data[0x1CF2],
            blue_berry_counter=data[0x1D05],
            berry_timers=timers,
            power_active=bool(data[MD_ACTOR_LAYOUT.talk_flags + 115] & (1 << 2)),
            cistern_filled=bool(data[MD_ACTOR_LAYOUT.talk_flags + 118] & (1 << 5)),
            canal_valves_open=bool(data[MD_ACTOR_LAYOUT.talk_flags + 118] & (1 << 6)),
            street_lights_active=bool(
                data[MD_ACTOR_LAYOUT.talk_flags + 115] & (1 << 4)
            ),
            saved_light_level=data[0x1CFA],
            active_party_index=data[0x1CF9],
        )
