"""Decode all 77 bytes of native AVATAR.DAT, separate from NPC slot 1.

Decoded ITEM/NPC.H defines the packed extension saved from strengthPoints.
Field suffixes in that header are object offsets, not offsets in this file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from titan.u8.state_io import read_u8_state_bytes


@dataclass(frozen=True)
class U8AvatarState:
    """Avatar extension state; raw toggles and uninitialized padding are retained."""

    raw_data: bytes
    strength_points: int
    intelligence_points: int
    dexterity_points: int
    name_raw: bytes
    sex: int
    power_avatar_raw: int
    hackmover_raw: int
    cheater_raw: int
    can_cheat_raw: int
    in_stasis: int
    random_seed_raw: int
    music_track_raw: int
    padding_33: bytes
    footsteps_raw: int
    language_raw: int
    text_speed_raw: int
    hunger: int
    cant_save_raw: int
    backpack_position: tuple[int, int]
    status_gump_position: tuple[int, int]
    unknown_point_42: tuple[int, int]
    speed_limiting_raw: int
    sound_on_raw: int
    music_on_raw: int
    padding_49: bytes

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8AvatarState:
        """Read loose AVATAR.DAT or its entry inside a native U8 save archive."""
        return cls.from_bytes(read_u8_state_bytes(filepath, "AVATAR.DAT"))

    @classmethod
    def from_bytes(cls, data: bytes) -> U8AvatarState:
        """Require the native 77-byte extension and decode DOS signed ints/chars."""
        if len(data) != 77:
            raise ValueError(f"AVATAR.DAT: expected 77 bytes, found {len(data)}")
        points = struct.unpack_from("<3h", data)
        return cls(
            raw_data=bytes(data),
            strength_points=points[0],
            intelligence_points=points[1],
            dexterity_points=points[2],
            name_raw=data[6:38],
            sex=struct.unpack_from("<h", data, 38)[0],
            power_avatar_raw=data[40],
            hackmover_raw=data[41],
            cheater_raw=data[42],
            can_cheat_raw=data[43],
            in_stasis=struct.unpack_from("<h", data, 44)[0],
            random_seed_raw=struct.unpack_from("<I", data, 46)[0],
            music_track_raw=data[50],
            padding_33=data[51:52],
            footsteps_raw=struct.unpack_from("<H", data, 52)[0],
            language_raw=struct.unpack_from("<b", data, 54)[0],
            text_speed_raw=struct.unpack_from("<b", data, 55)[0],
            hunger=data[56],
            cant_save_raw=data[57],
            backpack_position=struct.unpack_from("<hh", data, 58),
            status_gump_position=struct.unpack_from("<hh", data, 62),
            unknown_point_42=struct.unpack_from("<hh", data, 66),
            speed_limiting_raw=data[70],
            sound_on_raw=data[71],
            music_on_raw=data[72],
            padding_49=data[73:77],
        )

    @property
    def name(self) -> str:
        """Display a NUL-terminated DOS name; retain all 32 bytes separately."""
        return self.name_raw.split(b"\x00", 1)[0].decode("cp437")

    @property
    def random_seed_signed(self) -> int:
        """Interpret the preserved 32-bit random seed as the native signed long."""
        return (
            self.random_seed_raw
            if self.random_seed_raw < 0x80000000
            else self.random_seed_raw - 0x100000000
        )

    @property
    def language_code(self) -> str | None:
        """Return the native language letter when the stored signed index is valid."""
        codes = "EFGSIRDHJACPBNM"
        return codes[self.language_raw] if 0 <= self.language_raw < len(codes) else None

    def to_bytes(self) -> bytes:
        """Return the exact avatar extension, including unknowns and padding."""
        return self.raw_data
