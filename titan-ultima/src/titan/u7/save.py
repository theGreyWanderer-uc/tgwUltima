"""
U7 save-game parser.

Provides classes for reading Ultima 7 / Exult save-game files
(both ZIP and FLEX container formats) and inspecting their contents:

* :class:`U7Save` — container reader (ZIP level-1/2 and FLEX)
* :class:`U7GlobalFlags` — ``flaginit`` global-flags byte array
* :class:`U7Identity` — game identification string
* :class:`U7SaveInfo` — save metadata and party roster
* :class:`U7GameState` — ``gamewin.dat`` world state
* :class:`U7UsecodeData` — ``usecode.dat`` party/timer state
* :class:`U7UsecodeVars` — ``usecode.var`` static usecode variables
* :class:`U7Keyring` — ``keyring.dat`` SI keyring values
* :class:`U7FrameFlags` — ``frames.flg`` frame flag table
* :class:`U7Schedules` — NPC daily schedule table
* :class:`U7NPCData` — ``npc.dat`` character records

Example::

    from titan.u7.save import U7Save, U7SaveInfo, U7NPCData

    save = U7Save.from_file("exult00bg.sav")
    info = U7SaveInfo.from_save(save)
    print(info.dump())

    npcs = U7NPCData.from_save(save)
    for npc in npcs.npcs[:10]:
        print(f"{npc.name:16s}  HP={npc.health}  STR={npc.strength}")
"""

from __future__ import annotations

from titan.u7.actor_metadata import U7ActorMetadata
from titan.u7.saved_values import U7SavedValueReader, U7UsecodeValue

__all__ = [
    "U7Save",
    "U7SaveMember",
    "U7GlobalFlags",
    "U7Identity",
    "U7SaveInfo",
    "U7PartyMember",
    "U7GameState",
    "U7UsecodeData",
    "U7UsecodeTimer",
    "U7UsecodeVars",
    "U7UsecodeValue",
    "U7FunctionStatics",
    "U7Keyring",
    "U7FrameFlags",
    "U7Schedules",
    "U7ScheduleEntry",
    "U7NPCData",
    "U7NPC",
    "U7NPCInventoryItem",
    "U7ReadyTypes",
    "U7ReadyRecord",
]

import csv
import io
import json
from pathlib import Path
import struct
from dataclasses import dataclass, field
from typing import Optional, Union

from titan.u7.ireg import U7ObjectFlags, decode_ireg_payload
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_specials import (
    U7IregExtras,
    U7IregIndexId,
    U7IregSpecial,
    read_ireg_index,
    read_ireg_special,
    read_ireg_specials,
)
from titan.u7.ready_metadata import U7ReadyMetadata
from titan.u7.gameplay_metadata import (
    U7GameplayFormat,
    U7GameplayMetadata,
    U7GameplayTable,
    read_gameplay_table,
)
from titan.u7.save_container import (
    U7SaveMember,
    U7SaveContainer,
    read_u7_save_container,
)


# ============================================================================
# U7Save — container reader for .sav files (ZIP or FLEX)
# ============================================================================


class U7Save:
    """
    Read-only parser for Exult savegame files.

    Supports two container formats:

    * **ZIP** (modern, ``save_compression >= 1`` in exult.cfg)
      — First 80 bytes are the title, remainder is a standard ZIP archive.
      Level-1 stores individual files; Level-2 packs groups into
      single ZIP entries with 12-byte name + 4-byte size + data records.

    * **FLEX** (legacy, no compression)
      — 128-byte header (80-byte title, magic, count, padding),
      followed by an entry table (offset+size pairs), then data blobs
      each prefixed with a 13-byte DOS filename.
    """

    def __init__(
        self,
        title: str,
        entries: dict[str, bytes],
        container_format: str,
        *,
        layout: U7SaveContainer | None = None,
    ) -> None:
        self.title = title
        self.members = (
            tuple(layout.members)
            if layout is not None
            else tuple(
                U7SaveMember(name, data, index, "constructed", len(data), 0)
                for index, (name, data) in enumerate(entries.items())
            )
        )
        self._entries = {member.name: member.data for member in self.members}
        self.container_format = container_format  # "zip" or "flex"
        self.raw = layout.raw if layout is not None else b""
        self.warnings = list(layout.warnings) if layout is not None else []
        self.complete = layout.complete if layout is not None else True
        self.declared_count = layout.declared_count if layout is not None else None
        self.flex_directory = tuple(layout.flex_directory) if layout is not None else ()
        self.zip_comment = layout.zip_comment if layout is not None else b""
        self.group_trailing_data = (
            dict(layout.group_trailing_data) if layout is not None else {}
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str, *, strict: bool = False) -> U7Save:
        """Open a ``.sav`` file from disk."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data, strict=strict)

    @classmethod
    def from_bytes(cls, data: bytes, *, strict: bool = False) -> U7Save:
        """Detect the container; strict rejects structural errors, otherwise raw/partial evidence is retained."""
        layout = read_u7_save_container(data, strict=strict)
        return cls(layout.title, {}, layout.container_format, layout=layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_entries(self) -> list[tuple[str, int]]:
        """Return ordered ``(name, actual size)`` tuples, including duplicates and empty payloads."""
        return [(member.name, len(member.data)) for member in self.members]

    def get_data(self, name: str) -> Optional[bytes]:
        """Compatibility name lookup: last exact occurrence, then first matching spelling; use get_all_data for all."""
        # exact match first
        if name in self._entries:
            return self._entries[name]
        # case-insensitive fallback
        lower = name.lower()
        for key, val in self._entries.items():
            if key.lower() == lower:
                return val
        return None

    def get_all_data(self, name: str, *, case_sensitive: bool = False) -> list[bytes]:
        """Return all matching occurrences in archive order, including empty payloads."""
        return [
            member.data
            for member in self.members
            if (
                member.name == name
                if case_sensitive
                else member.name.casefold() == name.casefold()
            )
        ]

    def has_entry(self, name: str) -> bool:
        """Check whether the save contains *name* (case-insensitive)."""
        return self.get_data(name) is not None

    def entry_names(self) -> list[str]:
        """Return archive-order member names without deduplicating them."""
        return [member.name for member in self.members]


# ============================================================================
# U7GlobalFlags — ``flaginit`` parser
# ============================================================================


@dataclass
class U7GlobalFlags:
    """
    Parses the ``flaginit`` byte array from a U7 / Exult savegame.

    Storage format (from Exult ``ucmachine.h``):

    * ``gflags`` is ``std::vector<unsigned char>`` — one byte per flag.
    * Each byte acts as a boolean: 0 = unset, nonzero = set.
    * ``compact_global_flags()`` trims trailing zeros before save.
    * Max 32 768 flags.

    The raw bytes are stored so callers can inspect the actual values
    (they are typically 0 or 1, but the format supports 0–255).
    """

    raw: bytes = field(repr=False)
    """Raw flaginit bytes — one byte per flag index."""

    # Constants matching Exult ucmachine.h
    MAX_FLAGS: int = 32768

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_bytes(cls, data: bytes) -> U7GlobalFlags:
        """Create from raw ``flaginit`` bytes."""
        return cls(raw=data)

    @classmethod
    def from_file(cls, filepath: str) -> U7GlobalFlags:
        """Read a loose ``flaginit`` file from disk."""
        with open(filepath, "rb") as f:
            return cls(raw=f.read())

    @classmethod
    def from_save(cls, save: U7Save) -> U7GlobalFlags:
        """Extract ``flaginit`` from an open :class:`U7Save`."""
        data = save.get_data("flaginit")
        if data is None:
            raise ValueError("Save does not contain 'flaginit'")
        return cls(raw=data)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total number of flags in the file."""
        return len(self.raw)

    def get(self, index: int) -> int:
        """Return the raw byte value at *index* (0 if out of range)."""
        if 0 <= index < len(self.raw):
            return self.raw[index]
        return 0

    def is_set(self, index: int) -> bool:
        """Check whether flag *index* is nonzero."""
        return self.get(index) != 0

    @property
    def set_flags(self) -> list[int]:
        """List of flag indices that are nonzero."""
        return [i for i, v in enumerate(self.raw) if v != 0]

    @property
    def nonzero_count(self) -> int:
        """Number of flags with nonzero values."""
        return sum(1 for v in self.raw if v != 0)

    # ------------------------------------------------------------------
    # Dump helpers
    # ------------------------------------------------------------------

    def dump_summary(self) -> str:
        """One-line summary of flag stats."""
        return f"Global Flags: {self.count} total, {self.nonzero_count} set (nonzero)"

    def dump_detail(self) -> str:
        """
        Full listing of all set flags.

        Each line::

            gflag[  123 / 0x007B] =   1 (0x01)
        """
        lines: list[str] = []
        lines.append(
            f"=== Global Flags ({self.count} total, {self.nonzero_count} set) ==="
        )
        lines.append("")
        for i, v in enumerate(self.raw):
            if v != 0:
                lines.append(f"  gflag[{i:5d} / 0x{i:04X}] = {v:3d} (0x{v:02x})")
        lines.append("")
        lines.append(
            f"Summary: {self.count} total flags, {self.nonzero_count} non-zero."
        )
        return "\n".join(lines)

    def dump_csv(self) -> str:
        """
        CSV with every set flag (index_dec, index_hex, value_dec, value_hex).
        """
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["index", "index_hex", "value", "value_hex"])
        for i, v in enumerate(self.raw):
            if v != 0:
                writer.writerow([i, f"0x{i:04X}", v, f"0x{v:02x}"])
        return buf.getvalue()


# ============================================================================
# Name look-up tables
# ============================================================================

SCHEDULE_TYPE_NAMES: dict[int, str] = {
    0: "combat",
    1: "horiz_pace",
    2: "vert_pace",
    3: "talk",
    4: "dance",
    5: "eat",
    6: "farm",
    7: "tend_shop",
    8: "miner",
    9: "hound",
    10: "stand",
    11: "loiter",
    12: "wander",
    13: "blacksmith",
    14: "sleep",
    15: "wait",
    16: "sit",
    17: "graze",
    18: "bake",
    19: "sew",
    20: "shy",
    21: "lab",
    22: "thief",
    23: "waiter",
    24: "special",
    25: "kid_games",
    26: "eat_at_inn",
    27: "duel",
    28: "preach",
    29: "patrol",
    30: "desk_work",
    31: "follow_avatar",
}

ALIGNMENT_NAMES: dict[int, str] = {
    0: "neutral",
    1: "good",
    2: "evil",
    3: "chaotic",
}

ATTACK_MODE_NAMES: dict[int, str] = {
    0: "nearest",
    1: "weakest",
    2: "strongest",
    3: "berserk",
    4: "protect",
    5: "defend",
    6: "flank",
    7: "flee",
    8: "random",
    9: "manual",
}


# ============================================================================
# U7Identity
# ============================================================================


@dataclass
class U7Identity:
    """Game identity string (``identity`` entry in a save archive).

    The identity file is a short ASCII string naming the game variant,
    for example ``"BLACKGATE"`` or ``"SERPENTISLE"``.
    """

    game: str

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Identity":
        text = data.split(b"\x1a")[0].split(b"\r")[0].split(b"\n")[0]
        return cls(game=text.decode("ascii", errors="replace").strip())

    @classmethod
    def from_save(cls, save: U7Save) -> "U7Identity":
        data = save.get_data("identity")
        if data is None:
            raise ValueError("Save does not contain 'identity'")
        return cls.from_bytes(data)


# ============================================================================
# U7SaveInfo / U7PartyMember
# ============================================================================


@dataclass
class U7PartyMember:
    """One party-member record from ``saveinfo.dat``."""

    name: str
    shape: int
    experience: int
    flags: int
    flags2: int
    food: int
    strength: int
    combat: int
    dexterity: int
    intelligence: int
    magic: int
    mana: int
    training: int
    health: int
    shape_file: int


@dataclass
class U7SaveInfo:
    """Save metadata from ``saveinfo.dat``.

    Contains the real-world save timestamp, in-game clock,
    save counter, and a roster of current party members.
    """

    real_minute: int
    real_hour: int
    real_day: int
    real_month: int
    real_year: int
    game_minute: int
    game_hour: int
    game_day: int
    save_count: int
    party_size: int
    real_second: int
    party: list[U7PartyMember] = field(default_factory=list)
    raw_size: int = 0
    trailing_data: bytes = b""

    @property
    def warnings(self) -> list[str]:
        """Report an incomplete save preview roster or bytes after its declared end."""
        warnings = []
        if len(self.party) != self.party_size:
            warnings.append(
                f"saveinfo.dat party roster is incomplete: {len(self.party)} of "
                f"{self.party_size} records ({self.raw_size} bytes; "
                f"expected {64 + 64 * self.party_size})."
            )
        if self.trailing_data:
            warnings.append(
                f"saveinfo.dat has {len(self.trailing_data)} trailing bytes."
            )
        return warnings

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7SaveInfo":
        if len(data) < 64:
            raise ValueError(f"saveinfo.dat too short: {len(data)} bytes (need >= 64)")
        # SaveGame_Details — 64 bytes
        # 0:real_minute 1:real_hour 2:real_day 3:real_month
        # 4-5:real_year(LE) 6:game_minute 7:game_hour
        # 8-9:game_day(LE) 10-11:save_count(LE) 12:party_size
        # 13:unused 14:real_second  15-63:reserved
        info = cls(
            real_minute=data[0],
            real_hour=data[1],
            real_day=data[2],
            real_month=data[3],
            real_year=struct.unpack_from("<H", data, 4)[0],
            game_minute=data[6],
            game_hour=data[7],
            game_day=struct.unpack_from("<H", data, 8)[0],
            save_count=struct.unpack_from("<H", data, 10)[0],
            party_size=data[12],
            real_second=data[14],
            raw_size=len(data),
            trailing_data=data[64 + 64 * data[12] :],
        )
        # SaveGame_Party — 64 bytes each, after the header
        offset = 64
        for _ in range(info.party_size):
            if offset + 64 > len(data):
                break
            name_raw = data[offset : offset + 18]
            name = name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
            shape = struct.unpack_from("<H", data, offset + 18)[0]
            exp = struct.unpack_from("<I", data, offset + 20)[0]
            fl = struct.unpack_from("<I", data, offset + 24)[0]
            fl2 = struct.unpack_from("<I", data, offset + 28)[0]
            info.party.append(
                U7PartyMember(
                    name=name,
                    shape=shape,
                    experience=exp,
                    flags=fl,
                    flags2=fl2,
                    food=data[offset + 32],
                    strength=data[offset + 33],
                    combat=data[offset + 34],
                    dexterity=data[offset + 35],
                    intelligence=data[offset + 36],
                    magic=data[offset + 37],
                    mana=data[offset + 38],
                    training=data[offset + 39],
                    health=struct.unpack_from("<h", data, offset + 40)[0],
                    shape_file=struct.unpack_from("<H", data, offset + 42)[0],
                )
            )
            offset += 64
        return info

    @classmethod
    def from_save(cls, save: U7Save) -> "U7SaveInfo":
        data = save.get_data("saveinfo.dat")
        if data is None:
            raise ValueError("Save does not contain 'saveinfo.dat'")
        return cls.from_bytes(data)

    def dump(self) -> str:
        lines: list[str] = []
        lines.append("--- Save Metadata ---")
        lines.append(
            f"Saved:      {self.real_year:04d}-{self.real_month:02d}-"
            f"{self.real_day:02d} {self.real_hour:02d}:"
            f"{self.real_minute:02d}:{self.real_second:02d}"
        )
        lines.append(f"Save count: {self.save_count}")
        lines.append(
            f"Game time:  Day {self.game_day}, "
            f"{self.game_hour:02d}:{self.game_minute:02d}"
        )
        lines.append(f"Party size: {self.party_size}")
        if self.party:
            lines.append("")
            lines.append(
                f"  {'#':>2}  {'Name':<18} {'Shape':>5}  {'HP':>4}  "
                f"{'STR':>3}  {'DEX':>3}  {'INT':>3}  {'CMB':>3}  "
                f"{'MAG':>3}  {'MNA':>3}  {'EXP':>8}  {'Food':>4}"
            )
            lines.append("  " + "-" * 82)
            for i, m in enumerate(self.party):
                lines.append(
                    f"  {i:2d}  {m.name:<18} {m.shape:>5}  "
                    f"{m.health:>4}  {m.strength:>3}  {m.dexterity:>3}  "
                    f"{m.intelligence:>3}  {m.combat:>3}  {m.magic:>3}  "
                    f"{m.mana:>3}  {m.experience:>8}  {m.food:>4}"
                )
        lines.extend(f"Warning: {warning}" for warning in self.warnings)
        return "\n".join(lines)


# ============================================================================
# U7GameState
# ============================================================================


@dataclass
class U7GameState:
    """Exult world state from ``gamewin.dat``; old Exult extensions are optional.

    Layout (all little-endian)::

        0-1   scroll_tx  (uint16)     6-7   hour       (uint16)
        2-3   scroll_ty  (uint16)     8-9   minute     (uint16)
        4-5   day        (uint16)    10-13  special_light (uint32)
       14-17  music_track (int32)    18-21  music_repeat  (uint32)
       22     armageddon  (uint8)    23     ambient_light (uint8)
       24     combat      (uint8)    25     infravision   (uint8)
    """

    scroll_tx: int
    scroll_ty: int
    clock_day: int
    clock_hour: int
    clock_minute: int
    special_light: int
    music_track: int
    music_repeat: int
    armageddon: bool
    ambient_light: bool
    combat: bool
    infravision: bool
    raw_size: int = 26
    raw_flags: bytes = b""
    trailing_data: bytes = b""

    @property
    def music_track_raw(self) -> int | None:
        """Return the stored music bit pattern, or None for an absent extension."""
        return self.music_track & 0xFFFFFFFF if self.raw_size >= 22 else None

    @property
    def music_egg_count(self) -> int:
        """Return Exult's music egg count from the packed repeat word."""
        return (self.music_repeat >> 16) & 0xFFFF

    @property
    def warnings(self) -> list[str]:
        """Report unusual flag bytes and unconsumed window-state extensions."""
        warnings = [
            f"gamewin.dat flag at offset {22 + index} has noncanonical value {value}."
            for index, value in enumerate(self.raw_flags)
            if value not in (0, 1)
        ]
        if self.trailing_data:
            warnings.append(
                f"gamewin.dat has {len(self.trailing_data)} trailing bytes."
            )
        return warnings

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7GameState":
        if len(data) < 10:
            raise ValueError(f"gamewin.dat too short: {len(data)} bytes (need >= 10)")
        if 10 < len(data) < 14 or 14 < len(data) < 22:
            raise ValueError("gamewin.dat has an incomplete light or music extension")
        stx, sty, day, hour, minute = struct.unpack_from("<HHHHH", data, 0)
        sp_light = struct.unpack_from("<I", data, 10)[0] if len(data) >= 14 else 0
        music_trk = struct.unpack_from("<i", data, 14)[0] if len(data) >= 22 else -1
        music_rep = struct.unpack_from("<I", data, 18)[0] if len(data) >= 22 else 0
        arma = data[22] == 1 if len(data) > 22 else False
        ambient = data[23] == 1 if len(data) > 23 else False
        comb = data[24] == 1 if len(data) > 24 else False
        infra = data[25] == 1 if len(data) > 25 else False
        return cls(
            scroll_tx=stx,
            scroll_ty=sty,
            clock_day=day,
            clock_hour=hour,
            clock_minute=minute,
            special_light=sp_light,
            music_track=music_trk,
            music_repeat=music_rep,
            armageddon=arma,
            ambient_light=ambient,
            combat=comb,
            infravision=infra,
            raw_size=len(data),
            raw_flags=data[22:26],
            trailing_data=data[26:],
        )

    @classmethod
    def from_save(cls, save: U7Save) -> "U7GameState":
        data = save.get_data("gamewin.dat")
        if data is None:
            raise ValueError("Save does not contain 'gamewin.dat'")
        return cls.from_bytes(data)

    def dump(self) -> str:
        music = (
            "(not stored)"
            if self.music_track_raw is None
            else (
                f"{'none' if self.music_track == -1 else f'track {self.music_track}'} "
                f"(repeat={self.music_repeat & 1}, eggs={self.music_egg_count})"
            )
        )
        lines = [
            "--- Game State ---",
            f"Camera:      tile ({self.scroll_tx}, {self.scroll_ty})",
            f"Game time:   Day {self.clock_day}, "
            f"{self.clock_hour:02d}:{self.clock_minute:02d}",
            f"Music:       {music}",
            f"Light:       special={self.special_light}, ambient={self.ambient_light}",
            f"Combat:      {self.combat}",
            f"Armageddon:  {self.armageddon}",
            f"Infravision: {self.infravision}",
        ]
        lines.extend(f"Warning: {warning}" for warning in self.warnings)
        return "\n".join(lines)


# ============================================================================
# U7UsecodeData / U7UsecodeVars / U7Keyring / U7FrameFlags
# ============================================================================


@dataclass
class U7UsecodeTimer:
    """One saved usecode timer from ``usecode.dat``."""

    timer_id: int
    value: int


@dataclass
class U7UsecodeData:
    """Exult runtime usecode state with eight stored party slots in BG and SI.

    Exult writes party membership first, followed by either a legacy fixed
    timer block or the newer sparse timer marker, then the saved position/map.
    """

    party_count: int
    party_members: list[int] = field(default_factory=list)
    timers: list[U7UsecodeTimer] = field(default_factory=list)
    timer_format: str = "legacy"
    saved_tx: int = -1
    saved_ty: int = -1
    saved_tz: int = -1
    saved_map: int = -1
    saved_position_raw: tuple[int, int, int] | None = None
    trailing_data: bytes = b""
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7UsecodeData":
        pos = 0

        def read_word(size: int) -> int:
            nonlocal pos
            if pos + size > len(data):
                raise ValueError(
                    f"usecode.dat truncated at offset {pos}: need {size} bytes"
                )
            value = int.from_bytes(data[pos : pos + size], "little")
            pos += size
            return value

        party_count = read_word(2)
        if party_count > 8:
            raise ValueError(
                f"usecode.dat party count {party_count} exceeds eight slots"
            )
        party_slots = [read_word(2) for _ in range(8)]
        party_members = party_slots[:party_count]

        timers: list[U7UsecodeTimer] = []
        timer_format = "legacy"
        warnings: list[str] = []
        marker = read_word(4)
        if marker == 0xFFFFFFFF:
            timer_format = "sparse"
            seen = set()
            while True:
                timer_id = read_word(2)
                if timer_id == 0xFFFF:
                    break
                if timer_id in seen:
                    warnings.append(
                        f"usecode.dat has duplicate sparse timer ID {timer_id}."
                    )
                seen.add(timer_id)
                timers.append(U7UsecodeTimer(timer_id, read_word(4)))
        else:
            timers.append(U7UsecodeTimer(0, marker))
            for timer_id in range(1, 20):
                timers.append(U7UsecodeTimer(timer_id, read_word(4)))

        saved_tx = saved_ty = saved_tz = saved_map = -1
        raw_position = None
        remaining = len(data) - pos
        if remaining:
            if remaining < 6 or remaining == 7:
                raise ValueError("usecode.dat has an incomplete saved position or map")
            raw_position = struct.unpack_from("<hhh", data, pos)
            pos += 6
            if 0 <= raw_position[2] <= 13:
                saved_tx, saved_ty, saved_tz = raw_position
            elif raw_position != (-1, -1, -1):
                warnings.append(
                    "usecode.dat saved position has invalid lift; raw values retained."
                )
            if pos + 2 <= len(data):
                saved_map = read_word(2)
        trailing_data = data[pos:]
        if trailing_data:
            warnings.append(f"usecode.dat has {len(trailing_data)} trailing bytes.")

        return cls(
            party_count=party_count,
            party_members=party_members,
            timers=timers,
            timer_format=timer_format,
            saved_tx=saved_tx,
            saved_ty=saved_ty,
            saved_tz=saved_tz,
            saved_map=saved_map,
            saved_position_raw=raw_position,
            trailing_data=trailing_data,
            warnings=warnings,
        )

    @classmethod
    def from_file(cls, filepath: str) -> "U7UsecodeData":
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def dump(self) -> str:
        nonzero_timers = [t for t in self.timers if t.value != 0]
        lines = [
            "--- Usecode Runtime ---",
            f"Party count: {self.party_count}",
            f"Party NPCs:  {', '.join(str(i) for i in self.party_members) or '(none)'}",
            f"Timers:      {len(self.timers)} parsed ({self.timer_format}), "
            f"{len(nonzero_timers)} nonzero",
        ]
        if self.saved_tx >= 0:
            lines.append(
                f"Saved pos:   ({self.saved_tx}, {self.saved_ty}, "
                f"{self.saved_tz}) map={self.saved_map}"
            )
        lines.extend(f"Warning: {warning}" for warning in self.warnings)
        return "\n".join(lines)


@dataclass
class U7FunctionStatics:
    """Saved function static values identified by a numeric ID or raw name bytes."""

    function_id: int | None
    function_name: bytes | None
    values: list[U7UsecodeValue]
    offset: int
    end_offset: int


@dataclass
class U7UsecodeVars:
    """Exult typed static values and complete numeric/named function block counts."""

    global_static_count: int
    local_static_blocks: int = 0
    raw_size: int = 0
    global_values: list[U7UsecodeValue] = field(default_factory=list)
    function_statics: list[U7FunctionStatics] = field(default_factory=list)
    trailing_data: bytes = b""

    @property
    def warnings(self) -> list[str]:
        """Report bytes beyond the saved function-list terminator."""
        return (
            [f"usecode.var has {len(self.trailing_data)} trailing bytes."]
            if self.trailing_data
            else []
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7UsecodeVars":
        reader = U7SavedValueReader(data)
        global_count = reader.word(4)
        globals_ = reader.values(global_count)
        functions = []
        while True:
            start = reader.pos
            marker = reader.word(4)
            if marker == 0xFFFFFFFF:
                break
            name = reader.take(reader.word(2)) if marker == 0xFFFFFFFE else None
            values = reader.values(reader.word(4))
            functions.append(
                U7FunctionStatics(
                    None if marker == 0xFFFFFFFE else marker,
                    name,
                    values,
                    start,
                    reader.pos,
                )
            )
        return cls(
            global_static_count=global_count,
            local_static_blocks=len(functions),
            raw_size=len(data),
            global_values=globals_,
            function_statics=functions,
            trailing_data=data[reader.pos :],
        )

    @classmethod
    def from_file(cls, filepath: str) -> "U7UsecodeVars":
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def dump(self) -> str:
        summary = (
            "--- Usecode Statics ---\n"
            f"Global static values: {self.global_static_count}\n"
            f"Local static blocks:  {self.local_static_blocks}\n"
            f"Raw size:             {self.raw_size} bytes"
        )
        return "\n".join([summary, *(f"Warning: {w}" for w in self.warnings)])


@dataclass
class U7Keyring:
    """SI keyring data from ``keyring.dat``."""

    keys: list[int] = field(default_factory=list)
    trailing_data: bytes = b""

    @property
    def unique_keys(self) -> list[int]:
        """Return sorted key qualities matching Exult's set membership semantics."""
        return sorted(set(self.keys))

    @property
    def warnings(self) -> list[str]:
        """Report an incomplete quality word and duplicates without normalizing input."""
        warnings = []
        if self.trailing_data:
            warnings.append(
                "keyring.dat has an incomplete final quality word (1 byte)."
            )
        if len(self.unique_keys) != len(self.keys):
            warnings.append(
                "keyring.dat has duplicate key qualities; engine membership is unique."
            )
        return warnings

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Keyring":
        keys = [
            struct.unpack_from("<H", data, pos)[0] for pos in range(0, len(data) - 1, 2)
        ]
        return cls(keys=keys, trailing_data=data[len(keys) * 2 :])

    @classmethod
    def from_file(cls, filepath: str) -> "U7Keyring":
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def dump(self) -> str:
        summary = (
            f"--- Keyring ---\nKeys: {len(self.unique_keys)} unique, {len(self.keys)} stored"
            + (f" ({', '.join(str(k) for k in self.keys)})" if self.keys else "")
        )
        return "\n".join([summary, *(f"Warning: {w}" for w in self.warnings)])


@dataclass
class U7FrameFlags:
    """Frame flags from ``frames.flg`` as signed 32-bit values."""

    values: list[int] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7FrameFlags":
        if len(data) % 4 != 0:
            raise ValueError(f"frames.flg size must be divisible by 4, got {len(data)}")
        values = [
            struct.unpack_from("<i", data, pos)[0] for pos in range(0, len(data), 4)
        ]
        return cls(values=values)

    @classmethod
    def from_file(cls, filepath: str) -> "U7FrameFlags":
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    @property
    def non_default_count(self) -> int:
        return sum(1 for value in self.values if value != -1)

    def dump(self) -> str:
        return (
            "--- Frame Flags ---\n"
            f"Entries:      {len(self.values)}\n"
            f"Non-default:  {self.non_default_count}"
        )


# ============================================================================
# U7Schedules
# ============================================================================

_TILES_PER_SCHUNK = 256  # 16 chunks × 16 tiles


@dataclass
class U7ScheduleEntry:
    """A single schedule entry for one NPC."""

    time: int  # 0-7 (3-hour periods: 0=midnight, 1=3am, … 7=9pm)
    type: int  # Schedule type (0-31)
    tx: int  # Absolute tile X
    ty: int  # Absolute tile Y
    tz: int  # Lift (Z)
    days: int  # Day bitmask (0x7F = all 7 days, Exult only)

    @property
    def type_name(self) -> str:
        return SCHEDULE_TYPE_NAMES.get(self.type, f"unknown({self.type})")


@dataclass
class U7Schedules:
    """All NPC schedules from ``schedule.dat``.

    Format auto-detection via the first int32:

    * ``-1`` — Exult 8-byte entries
    * ``-2`` — Exult 8-byte entries + script names
    * positive — original U7 4-byte entries (value = num_npcs)

    The first cumulative count is the Avatar sentinel and must be zero.
    """

    entries: dict = field(default_factory=dict)
    num_npcs: int = 0
    format: str = "u7"  # "u7", "exult", "exult2"
    script_names: tuple[str, ...] = ()
    script_names_raw: tuple[bytes, ...] = ()
    raw: bytes = b""
    warnings: list[str] = field(default_factory=list)
    complete: bool = True
    parsed_bytes: int = 0
    trailing_data: bytes = b""

    def name_for_type(self, schedule_type: int) -> str:
        """Resolve a scripted schedule name only when its stored index is present."""
        index = schedule_type - 0x80
        if 0 <= index < len(self.script_names):
            return self.script_names[index]
        return SCHEDULE_TYPE_NAMES.get(schedule_type, f"unknown({schedule_type})")

    @classmethod
    def from_bytes(cls, data: bytes, *, strict: bool = False) -> "U7Schedules":
        """Decode the shared bounded layout, retaining scripts and explicit partial diagnostics."""
        from titan.u7.schedule_metadata import U7ScheduleLayout

        if len(data) < 4:
            raise ValueError("schedule.dat too short")
        layout = U7ScheduleLayout.from_bytes(data, strict=strict)
        sched = cls(num_npcs=layout.num_npcs, format=layout.format)
        sched.raw = data
        sched.script_names_raw = layout.script_names_raw
        sched.script_names = tuple(
            name.decode("latin-1") for name in layout.script_names_raw
        )
        sched.warnings = layout.warnings
        sched.complete = layout.complete
        sched.parsed_bytes = layout.parsed_bytes
        sched.trailing_data = layout.trailing_data
        for npc_idx, rows in layout.records.items():
            entries = []
            for raw in rows:
                if layout.entry_width == 8:
                    tx, ty, tz, time_val, type_val, days = struct.unpack("<HHBBBB", raw)
                else:
                    b0, sx, sy, schunk = raw
                    time_val, type_val = b0 & 7, b0 >> 3
                    tx = (schunk % 12) * _TILES_PER_SCHUNK + sx
                    ty = (schunk // 12) * _TILES_PER_SCHUNK + sy
                    tz, days = 0, 0x7F
                entries.append(
                    U7ScheduleEntry(
                        time=time_val, type=type_val, tx=tx, ty=ty, tz=tz, days=days
                    )
                )
            sched.entries[npc_idx] = entries
        return sched

    @classmethod
    def from_file(cls, filepath: str, *, strict: bool = False) -> "U7Schedules":
        """Read a loose ``schedule.dat`` file from disk."""
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read(), strict=strict)

    @classmethod
    def from_save(cls, save: U7Save, *, strict: bool = False) -> "U7Schedules":
        data = save.get_data("schedule.dat")
        if data is None:
            raise ValueError("Save does not contain 'schedule.dat'")
        return cls.from_bytes(data, strict=strict)

    def dump_summary(self, npc_names: dict[int, str] | None = None) -> str:
        total = sum(len(v) for v in self.entries.values())
        return (
            f"Schedules: {self.num_npcs} NPCs tracked, "
            f"{len(self.entries)} with entries, "
            f"{total} total entries ({self.format} format)"
        ) + "".join(f"\nWarning: {warning}" for warning in self.warnings)

    def dump_detail(self, npc_names: dict[int, str] | None = None) -> str:
        lines = [
            f"=== Schedules ({self.format} format, {self.num_npcs} NPCs) ===",
            "",
        ]
        for npc_idx in sorted(self.entries):
            ents = self.entries[npc_idx]
            label = ""
            if npc_names:
                name = npc_names.get(npc_idx, "")
                if name:
                    label = f" {name:<16s}"
            lines.append(f"NPC {npc_idx:4d}{label}: {len(ents)} schedule(s)")
            for e in ents:
                lines.append(
                    f"  time={e.time} "
                    f"({e.time * 3:02d}:00-{e.time * 3 + 2:02d}:59)  "
                    f"type={e.type:2d} ({self.name_for_type(e.type):<14s})  "
                    f"at ({e.tx}, {e.ty}, {e.tz})  days=0x{e.days:02X}"
                )
        lines.append("")
        total = sum(len(v) for v in self.entries.values())
        lines.append(f"Total: {len(self.entries)} NPCs with {total} entries")
        lines.extend(f"Warning: {warning}" for warning in self.warnings)
        return "\n".join(lines)

    def dump_csv(self, npc_names: dict[int, str] | None = None) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "npc",
                "name",
                "time_slot",
                "sched_type",
                "sched_name",
                "tx",
                "ty",
                "tz",
                "days",
            ]
        )
        for npc_idx in sorted(self.entries):
            for e in self.entries[npc_idx]:
                name = npc_names.get(npc_idx, "") if npc_names else ""
                writer.writerow(
                    [
                        npc_idx,
                        name,
                        e.time,
                        e.type,
                        self.name_for_type(e.type),
                        e.tx,
                        e.ty,
                        e.tz,
                        f"0x{e.days:02X}",
                    ]
                )
        return buf.getvalue()


def _clean_ascii_text(value: str) -> str:
    """Keep decoded game text console-safe on Windows terminals."""
    return value.encode("ascii", errors="replace").decode("ascii")


# ============================================================================
# IREG skip helpers (for NPC inventory parsing)
# ============================================================================


@dataclass
class U7NPCInventoryItem:
    """One item parsed from an NPC or monster inventory IREG block."""

    shape: int
    frame: int
    x: int
    y: int
    lift: int
    quality: int
    depth: int
    path: str = ""

    # Per-instance IREG object state (titan.u7.ireg), decoded the same way
    # as titan.u7.map's U7MapObject. Optional U7IregContext supplies TFA
    # quality semantics and supplemental body/jawbone dispatch flags.
    raw_quality: int = 0
    object_flags: U7ObjectFlags = U7ObjectFlags.NONE
    raw_flag_byte: int | None = None
    record_length: int = 0
    is_extended: bool = False
    ireg_kind: str = ""
    ireg_data: dict[str, object] = field(default_factory=dict)
    ireg_warnings: list[str] = field(default_factory=list)
    ireg_raw_hex: str = ""
    ireg_offset: int = 0
    ireg_index_id: U7IregIndexId | None = None
    ireg_specials: list[U7IregSpecial] = field(default_factory=list)


_READY_SLOT_NAMES = {
    0x00: "head",
    0x01: "backpack",
    0x02: "belt",
    0x03: "left_hand",
    0x04: "left_finger",
    0x05: "legs",
    0x06: "feet",
    0x07: "right_finger",
    0x08: "right_hand",
    0x09: "torso",
    0x0A: "amulet",
    0x0B: "quiver",
    0x0C: "back_two_handed",
    0x0D: "back_shield",
    0x0E: "earrings",
    0x0F: "cloak",
    0x10: "gloves",
    0x11: "usecode_container",
    0x12: "both_hands",
    0x13: "gloves_and_ring",
    0x14: "neck",
    0x15: "scabbard",
    0x16: "triple_bolts",
    0xFF: "invalid",
}

_READY_BG_TO_EXULT = {
    0x00: 0x01,
    0x01: 0x03,
    0x02: 0x08,
    0x03: 0x02,
    0x04: 0x14,
    0x05: 0x09,
    0x06: 0x04,
    0x07: 0x07,
    0x08: 0x0B,
    0x09: 0x00,
    0x0A: 0x05,
    0x0B: 0x06,
    0x0C: 0x11,
    0x0D: 0x0F,
    0x0E: 0x10,
    0x0F: 0x16,
    0x10: 0x0E,
    0x11: 0x0D,
    0x12: 0x03,
    0x13: 0x0C,
    0x14: 0x12,
    0x15: 0x13,
    0x16: 0x0A,
    0x17: 0x15,
}

_READY_SI_TO_EXULT = {
    0x00: 0x08,
    0x01: 0x03,
    0x02: 0x0F,
    0x03: 0x0A,
    0x04: 0x00,
    0x05: 0x10,
    0x06: 0x11,
    0x07: 0x07,
    0x08: 0x04,
    0x09: 0x0E,
    0x0A: 0x0B,
    0x0B: 0x02,
    0x0C: 0x09,
    0x0D: 0x06,
    0x0E: 0x05,
    0x0F: 0x01,
    0x10: 0x0D,
    0x11: 0x0C,
    0x12: 0x16,
    0x14: 0x12,
    0x15: 0x13,
    0x16: 0x14,
    0x17: 0x15,
}


@dataclass
class U7ReadyRecord:
    """One stored ready preference, retaining its spell flag and raw nine-byte record."""

    shape: int
    slot: int
    spell_flag: bool
    raw: bytes

    @property
    def ready_code(self) -> int:
        """Return the game-specific five-bit ready code before BG/SI translation."""
        return self.raw[2] >> 3


class U7ReadyTypes(U7GameplayMetadata):
    """Decoded `ready.dat` ready-slot preferences."""

    def __init__(
        self,
        slots: dict[int, int],
        records: list[U7ReadyRecord] | None = None,
        table: U7GameplayTable | None = None,
        *,
        data_format: U7GameplayFormat = "exult",
    ) -> None:
        super().__init__(table, data_format=data_format)
        self.slots = slots
        self.records = records or []
        self.spell_flags = {record.shape: record.spell_flag for record in self.records}

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        *,
        data_format: U7GameplayFormat = "exult",
    ) -> "U7ReadyTypes":
        for name in ("ready.dat", "READY.DAT"):
            path = Path(static_dir) / name
            if path.is_file():
                return cls.from_file(str(path), game=game, data_format=data_format)
        return cls({}, data_format=data_format)

    @classmethod
    def from_file(
        cls, filepath: str, game: str = "bg", *, data_format: U7GameplayFormat = "exult"
    ) -> "U7ReadyTypes":
        return cls.from_bytes(
            Path(filepath).read_bytes(), game=game, data_format=data_format
        )

    @classmethod
    def from_bytes(
        cls, data: bytes, game: str = "bg", *, data_format: U7GameplayFormat = "exult"
    ) -> "U7ReadyTypes":
        table = read_gameplay_table(data, 9, "READY.DAT", data_format=data_format)
        mapping = _READY_BG_TO_EXULT if game.lower() == "bg" else _READY_SI_TO_EXULT
        slots: dict[int, int] = {}
        records = []
        for raw in table.records:
            shape = int.from_bytes(raw[:2], "little")
            slot = mapping.get(raw[2] >> 3, 0xFF)
            slots[shape] = slot
            records.append(U7ReadyRecord(shape, slot, bool(raw[2] & 1), raw))
        return cls(slots, records, table)

    def spell_flag_for_shape(self, shape: int) -> bool | None:
        """Return the stored spell flag; None means that no flag was loaded for the shape."""
        return self.spell_flags.get(shape)

    def slot_for_shape(self, shape: int) -> int | None:
        return self.slots.get(shape)

    def slot_name_for_shape(self, shape: int) -> str:
        slot = self.slot_for_shape(shape)
        if slot is None or slot == 0xFF:
            return ""
        return _READY_SLOT_NAMES.get(slot, f"ready_{slot}")


def _read_ireg_inventory(
    data: bytes,
    pos: int,
    container_shapes: Union[set, None] = None,
    valid_shape_count: int | None = None,
    depth: int = 0,
    path: str = "",
    inherited_flags: U7ObjectFlags = U7ObjectFlags.NONE,
    ireg_context: U7IregContext | None = None,
    extras: U7IregExtras | None = None,
    offset_base: int = 0,
) -> tuple[list[U7NPCInventoryItem], int]:
    """Read one NPC inventory IREG section starting at *pos*.

    Quality/lift/flag-byte offsets and invisible/okay_to_take/temporary
    decoding are shared with :mod:`titan.u7.map` via
    :func:`titan.u7.ireg.decode_ireg_payload`. Optional ``ireg_context``
    supplies TFA and supplemental flags; missing context is recorded on
    each item's ``ireg_warnings`` alongside the retained raw payload.
    """
    items: list[U7NPCInventoryItem] = []
    extras = extras if extras is not None else U7IregExtras()
    scope_offset = pos
    last_item: U7NPCInventoryItem | None = None
    last_offset: int | None = None
    index_id: U7IregIndexId | None = None
    while pos < len(data):
        entry_offset = pos
        entry_len = data[pos]
        pos += 1

        if entry_len == 0 or entry_len == 1:
            return items, pos

        if entry_len == 2:
            index_id, pos = read_ireg_index(
                data, entry_offset, scope_offset, offset_base=offset_base
            )
            extras.indices.append(index_id)
            if not index_id.complete:
                extras.warnings.append(
                    f"IREG offset {entry_offset + offset_base}: index ID is truncated"
                )
                break
            continue

        extended = False
        extended_lift = False
        if entry_len in (0xFD, 0xFE):
            if entry_len == 0xFE:
                extended = True
            extended_lift = True
            if pos >= len(data):
                break
            entry_len = data[pos]
            pos += 1
        elif entry_len == 0xFF:
            special, pos = read_ireg_special(
                data, entry_offset, offset_base=offset_base
            )
            extras.add_special(special, last_offset)
            if last_item is not None:
                last_item.ireg_specials.append(special)
                last_item.ireg_warnings.extend(special.warnings)
            if special.type_id == 2:
                return items, pos
            continue

        entry_start = pos
        pos += entry_len
        if pos > len(data):
            extras.warnings.append(
                f"IREG offset {entry_offset + offset_base}: object payload is truncated"
            )
            break

        testlen = entry_len - (1 if extended else 0)
        if testlen not in (6, 10, 12, 13, 14, 18):
            continue

        ed = data[entry_start : entry_start + entry_len]
        decoded = decode_ireg_payload(
            ed,
            entlen=entry_len,
            extended=extended,
            extended_lift=extended_lift,
            inherited_flags=inherited_flags,
            shape_class=None,
            context=ireg_context,
        )
        if decoded is None:
            continue

        shape = decoded.shape
        frame = decoded.frame
        valid_shape = valid_shape_count is None or shape < valid_shape_count
        item_path = f"{path}/{shape}:{frame}" if path else f"{shape}:{frame}"
        if valid_shape:
            last_item = U7NPCInventoryItem(
                shape=shape,
                frame=frame,
                x=ed[0],
                y=ed[1],
                lift=decoded.lift,
                quality=decoded.quality,
                depth=depth,
                path=item_path,
                raw_quality=decoded.raw_quality,
                object_flags=decoded.object_flags,
                raw_flag_byte=decoded.raw_flag_byte,
                record_length=decoded.record_length,
                is_extended=decoded.is_extended,
                ireg_kind=decoded.kind,
                ireg_data=decoded.class_data,
                ireg_warnings=decoded.context_warnings,
                ireg_raw_hex=decoded.raw_hex,
                ireg_offset=entry_offset + offset_base,
                ireg_index_id=index_id,
            )
            last_offset = entry_offset + offset_base
            items.append(last_item)
        else:
            last_item, last_offset = None, None

        if valid_shape and decoded.has_children_marker:
            is_container = (
                True
                if ireg_context is not None
                else shape in container_shapes
                if container_shapes is not None
                else True
            )
            if is_container:
                child_items, pos = _read_ireg_inventory(
                    data,
                    pos,
                    container_shapes,
                    valid_shape_count,
                    depth + 1,
                    item_path,
                    inherited_flags=decoded.child_inherit_flags,
                    ireg_context=ireg_context,
                    extras=extras,
                    offset_base=offset_base,
                )
                items.extend(child_items)
    return items, pos


def _skip_ireg_inventory(
    data: bytes,
    pos: int,
    container_shapes: Union[set, None] = None,
) -> int:
    """Skip one IREG section starting at *pos*.

    Handles nested containers when *container_shapes* is provided
    (set of shape numbers that are container class = 6 from TFA).
    Falls back to treating all 12-byte entries with type != 0 as
    containers when *container_shapes* is ``None``.

    Returns position after the terminating ``0x01`` marker.
    """
    while pos < len(data):
        entry_len = data[pos]
        pos += 1

        if entry_len == 0 or entry_len == 1:
            return pos  # End of this container / section

        if entry_len == 2:
            pos += 2  # 2-byte index id
            continue

        extended = 0
        if entry_len in (0xFD, 0xFE):
            if entry_len == 0xFE:
                extended = 1
            if pos >= len(data):
                break
            entry_len = data[pos]
            pos += 1
        elif entry_len == 0xFF:
            # Special IREG: type(1), then either ENDMARK(2) or len(2)+data.
            if pos >= len(data):
                break
            sp_type = data[pos]
            pos += 1
            if sp_type == 2:
                return pos
            if pos + 2 > len(data):
                break
            sp_len = struct.unpack_from("<H", data, pos)[0]
            pos += 2 + sp_len
            continue

        # Regular or extended entry: consume entry_len bytes
        entry_start = pos
        pos += entry_len
        if pos > len(data):
            break

        # Check for container/body nesting (testlen 12, 13, or 14 -- see
        # decode_ireg_payload's has_children_marker for the full decode).
        testlen = entry_len - extended
        if testlen in (12, 13, 14) and entry_start + 6 + extended <= len(data):
            ed = data[entry_start : entry_start + entry_len]
            if extended:
                shape = ed[2] + 256 * ed[3]
            else:
                shape = ed[2] + 256 * (ed[3] & 3)
            type_off = 4 + extended
            type_val = (
                (ed[type_off] + 256 * ed[type_off + 1]) if len(ed) > type_off + 1 else 0
            )
            is_container = False
            if type_val != 0:
                if container_shapes is not None:
                    is_container = shape in container_shapes
                else:
                    is_container = True
            if is_container:
                pos = _skip_ireg_inventory(data, pos, container_shapes)
    return pos


def _skip_special_ireg(data: bytes, pos: int) -> int:
    """Skip scheduled usecode (``read_special_ireg`` format).

    Each entry is prefixed by ``0xFF``.  The sequence ends with
    ``0xFF 0x02`` (IREG_ENDMARK).
    """
    return read_ireg_specials(data, pos)[1]


# ============================================================================
# U7NPCData / U7NPC
# ============================================================================


@dataclass
class U7NPC:
    """Parsed data for a single NPC from ``npc.dat``."""

    npc_num: int
    name: str
    shape: int
    frame: int
    # Position
    tile_x: int = 0
    tile_y: int = 0
    superchunk: int = 0
    map_num: int = 0
    lift: int = 0
    # Core stats
    health: int = 0
    strength: int = 0
    dexterity: int = 0
    intelligence: int = 0
    combat: int = 0
    magic: int = 0
    mana: int = 0
    experience: int = 0
    training: int = 0
    food: int = 0
    # Schedule / behaviour
    schedule_type: int = 0
    attack_mode: int = 0
    alignment: int = 0
    face_num: int = 0
    type_flags: int = 0
    rflags: int = 0
    # Derived booleans
    in_party: bool = False
    is_female: bool | None = False
    has_inventory: bool = False
    inventory: list[U7NPCInventoryItem] = field(default_factory=list)
    unused: bool = False
    metadata: U7ActorMetadata | None = None
    used_in_game_raw: int | None = None
    unused_compatibility: bool = False
    ireg_specials: list[U7IregSpecial] = field(default_factory=list)
    inventory_ireg: U7IregExtras | None = None
    ireg_warnings: list[str] = field(default_factory=list)

    @property
    def schedule_name(self) -> str:
        return SCHEDULE_TYPE_NAMES.get(self.schedule_type, f"?{self.schedule_type}")

    @property
    def alignment_name(self) -> str:
        return ALIGNMENT_NAMES.get(self.alignment, f"?{self.alignment}")

    @property
    def attack_mode_name(self) -> str:
        return ATTACK_MODE_NAMES.get(self.attack_mode, f"?{self.attack_mode}")

    @property
    def is_dead(self) -> bool:
        if self.metadata is not None:
            return self.metadata.is_dead
        return bool(self.rflags & (1 << 15))


class U7NPCData:
    """All NPCs from ``npc.dat``.

    Reads each NPC's fixed-header fields (stats, position, name) and
    decodes embedded IREG inventory data.  For reliable container-nesting
    detection, pass a set of container shape numbers via
    *container_shapes* (shape class 6 from
    :class:`~titan.u7.typeflag.U7TypeFlags`).
    """

    def __init__(
        self,
        npcs: list,
        num_npcs1: int = 0,
        num_npcs2: int = 0,
        npc_flavor: str = "runtime",
        *,
        fix_unused: bool = False,
        warnings: list[str] | None = None,
    ):
        self.npcs: list[U7NPC] = npcs
        self.num_npcs1 = num_npcs1
        self.num_npcs2 = num_npcs2
        self.npc_flavor = npc_flavor
        self.fix_unused = fix_unused
        self.warnings = list(warnings or [])
        if fix_unused:
            self.warnings.append(
                "NPC.DAT: Avatar used-in-game word is zero; Exult legacy unused compatibility is active."
            )
        self._parsed_bytes = 0

    # ---- factory ----------------------------------------------------------

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        sex_unknown: bool = False,
        original_new_game: bool = False,
        npc_flavor: str | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Read ``npc.dat`` bytes.

        ``npc_flavor`` may be ``"runtime"``, ``"original"``, ``"unknown"``,
        or ``"auto"``.  The older ``original_new_game`` and ``sex_unknown``
        booleans are still honored for callers that already know provenance.
        ``game`` selects BG's six-bit or SI's five-bit strength field; source
        flavor does not identify the game. The default preserves BG behavior.
        """
        if len(data) < 4:
            raise ValueError("npc.dat too short")

        if npc_flavor:
            flavor = npc_flavor.lower().replace("_", "-")
            if flavor in {"original", "original-new-game", "initgame"}:
                original_new_game = True
                sex_unknown = False
            elif flavor in {"runtime", "exult", "exult-runtime"}:
                original_new_game = False
                sex_unknown = False
            elif flavor == "unknown":
                original_new_game = False
                sex_unknown = True
            elif flavor == "auto":
                return cls.from_bytes_auto(
                    data,
                    container_shapes,
                    valid_shape_count,
                    game=game,
                    ireg_context=ireg_context,
                )
            else:
                raise ValueError(f"Unknown npc.dat flavor: {npc_flavor}")

        return cls._from_bytes_core(
            data,
            container_shapes,
            valid_shape_count,
            sex_unknown=sex_unknown,
            original_new_game=original_new_game,
            npc_flavor=(
                "unknown"
                if sex_unknown
                else ("original-new-game" if original_new_game else "runtime")
            ),
            game=game,
            ireg_context=ireg_context,
        )

    @classmethod
    def from_bytes_auto(
        cls,
        data: bytes,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Auto-detect runtime vs original new-game ``npc.dat`` where possible.

        A loose ``npc.dat`` has no explicit magic.  Titan scores both parses
        structurally.  When both forms look equally plausible, it preserves all
        parsed fields but marks sex as unknown rather than choosing the wrong
        bit-9 interpretation.
        """
        runtime = cls._from_bytes_core(
            data,
            container_shapes,
            valid_shape_count,
            sex_unknown=False,
            original_new_game=False,
            npc_flavor="runtime",
            game=game,
            ireg_context=ireg_context,
        )
        original = cls._from_bytes_core(
            data,
            container_shapes,
            valid_shape_count,
            sex_unknown=False,
            original_new_game=True,
            npc_flavor="original-new-game",
            game=game,
            ireg_context=ireg_context,
        )
        runtime_score = cls._score_npc_parse(runtime, data)
        original_score = cls._score_npc_parse(original, data)

        if original_score >= runtime_score + 5:
            return original
        if runtime_score >= original_score + 5:
            return runtime
        return cls._from_bytes_core(
            data,
            container_shapes,
            valid_shape_count,
            sex_unknown=True,
            original_new_game=False,
            npc_flavor="unknown",
            game=game,
            ireg_context=ireg_context,
        )

    @classmethod
    def _from_bytes_core(
        cls,
        data: bytes,
        container_shapes: Union[set, None],
        valid_shape_count: int | None,
        sex_unknown: bool,
        original_new_game: bool,
        npc_flavor: str,
        *,
        monster_actors: bool = False,
        offset_base: int = 0,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Read actor streams, keeping monster ordinals separate from NPC identities."""
        game = game.lower()
        if game not in ("bg", "si"):
            raise ValueError(f"U7 actor game must be bg or si: {game}")
        num1 = struct.unpack_from("<H", data, 0)[0]
        num2 = struct.unpack_from("<H", data, 2)[0]
        pos = 4
        npcs: list[U7NPC] = []
        total = num1 + num2
        fix_unused = False

        for npc_idx in range(total):
            if pos + 78 > len(data):
                break
            try:
                npc, pos = cls._read_one_npc(
                    data,
                    pos,
                    npc_idx,
                    container_shapes,
                    valid_shape_count,
                    sex_unknown,
                    original_new_game,
                    actor_npc_num=-1 if monster_actors else npc_idx,
                    offset_base=offset_base,
                    game=game,
                    ireg_context=ireg_context,
                    has_usecode=npc_idx < num1 if not monster_actors else False,
                    fix_unused=fix_unused,
                )
                fix_unused = npc.unused_compatibility
                npcs.append(npc)
            except (struct.error, IndexError, ValueError):
                break
        result = cls(
            npcs=npcs,
            num_npcs1=num1,
            num_npcs2=num2,
            npc_flavor=npc_flavor,
            fix_unused=fix_unused,
        )
        result._parsed_bytes = pos
        result.warnings.extend(
            f"Actor {npc.npc_num}: {warning}"
            for npc in npcs
            for warning in npc.ireg_warnings
        )
        return result

    @staticmethod
    def _score_npc_parse(parsed: "U7NPCData", data: bytes) -> int:
        declared = parsed.num_npcs1 + parsed.num_npcs2
        score = len(parsed.npcs) * 10
        score -= max(0, declared - len(parsed.npcs)) * 20
        score += sum(2 for npc in parsed.npcs if npc.name)
        score += sum(
            1 for npc in parsed.npcs if 0 <= npc.shape <= 1023 and 0 <= npc.frame <= 63
        )
        consumed = getattr(parsed, "_parsed_bytes", 0)
        if consumed == len(data):
            score += 20
        elif consumed < len(data):
            score -= min(20, len(data) - consumed)
        else:
            score -= 40
        return score

    @classmethod
    def from_save(
        cls,
        save: U7Save,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        data = save.get_data("npc.dat")
        if data is None:
            raise ValueError("Save does not contain 'npc.dat'")
        result = cls.from_bytes(
            data,
            container_shapes,
            valid_shape_count,
            npc_flavor="runtime",
            game=game,
            ireg_context=ireg_context,
        )
        result.warnings[:0] = save.warnings
        return result

    @classmethod
    def from_file(
        cls,
        filepath: str,
        container_shapes: Union[set, None] = None,
        sex_unknown: bool = False,
        original_new_game: bool = False,
        npc_flavor: str | None = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Read a loose ``npc.dat`` file from disk."""
        with open(filepath, "rb") as f:
            return cls.from_bytes(
                f.read(),
                container_shapes,
                valid_shape_count,
                sex_unknown,
                original_new_game,
                npc_flavor=npc_flavor,
                game=game,
                ireg_context=ireg_context,
            )

    @classmethod
    def from_initgame_file(
        cls,
        filepath: str,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Read original new-game NPC data from ``STATIC/INITGAME.DAT``.

        Exult extracts ``npc.dat`` from ``INITGAME.DAT`` and reads it with
        ``Game::is_new_game()`` set.  In that mode Exult treats most type flags
        as garbage, but uses raw type-flag bit 9 inverted to initialize
        ``Actor::tf_sex``.
        """
        from titan.u7.flex import U7FlexArchive

        archive = U7FlexArchive.from_file(filepath)
        for record in archive.records:
            if len(record) <= 13:
                continue
            name = (
                record[:13]
                .split(b"\x00", 1)[0]
                .decode("ascii", errors="replace")
                .rstrip(".")
                .lower()
            )
            if name == "npc.dat":
                return cls.from_bytes(
                    record[13:],
                    container_shapes=container_shapes,
                    valid_shape_count=valid_shape_count,
                    npc_flavor="original-new-game",
                    game=game,
                    ireg_context=ireg_context,
                )
        raise ValueError(f"INITGAME.DAT does not contain npc.dat: {filepath}")

    @classmethod
    def from_monsnpcs_bytes(
        cls,
        data: bytes,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Read Exult ``monsnpcs.dat`` monster actors.

        ``monsnpcs.dat`` stores one uint16 monster count followed by actor
        records in the same serialized form used by ``npc.dat``.  Adapt that
        single count to the two-count ``npc.dat`` header. Decode with Exult's
        non-NPC actor identity (-1), retaining ordinals only for reporting.
        """
        if len(data) < 2:
            raise ValueError("monsnpcs.dat too short")
        count = struct.unpack_from("<H", data, 0)[0]
        npc_like = struct.pack("<HH", count, 0) + data[2:]
        return cls._from_bytes_core(
            npc_like,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            sex_unknown=False,
            original_new_game=False,
            npc_flavor="runtime",
            monster_actors=True,
            offset_base=-2,
            game=game,
            ireg_context=ireg_context,
        )

    @classmethod
    def from_monsnpcs_file(
        cls,
        filepath: str,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> "U7NPCData":
        """Read a loose Exult ``monsnpcs.dat`` file from disk."""
        with open(filepath, "rb") as f:
            return cls.from_monsnpcs_bytes(
                f.read(),
                container_shapes,
                valid_shape_count,
                game=game,
                ireg_context=ireg_context,
            )

    @classmethod
    def npc_name_map(
        cls,
        save: U7Save,
        container_shapes: Union[set, None] = None,
        valid_shape_count: int | None = None,
        *,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
    ) -> dict[int, str]:
        """Extract ``{npc_index: name}`` from ``npc.dat`` in a save."""
        npc_data = cls.from_save(
            save,
            container_shapes,
            valid_shape_count,
            game=game,
            ireg_context=ireg_context,
        )
        return npc_data.name_map()

    def name_map(self) -> dict[int, str]:
        """Return ``{npc_index: name}`` for named NPCs."""
        return {n.npc_num: n.name for n in self.npcs if n.name}

    # ---- internal NPC reader ---------------------------------------------

    @classmethod
    def _read_one_npc(
        cls,
        data: bytes,
        pos: int,
        npc_idx: int,
        container_shapes: Union[set, None],
        valid_shape_count: int | None,
        sex_unknown: bool,
        original_new_game: bool,
        *,
        actor_npc_num: int | None = None,
        offset_base: int = 0,
        game: str = "bg",
        ireg_context: U7IregContext | None = None,
        has_usecode: bool | None = None,
        fix_unused: bool = False,
    ) -> tuple:
        """Decode one actor; a monster's reporting ordinal is not an NPC identity."""
        if actor_npc_num is None:
            actor_npc_num = npc_idx
        # -- fixed header (78 bytes) ----------------------------------------
        locx = data[pos]  # 0
        locy = data[pos + 1]  # 1
        shnum = struct.unpack_from("<H", data, pos + 2)[0]  # 2-3
        iflag1 = struct.unpack_from("<H", data, pos + 4)[0]  # 4-5
        schunk = data[pos + 6]  # 6
        map_num = data[pos + 7]  # 7
        if original_new_game:
            map_num = 0
        usefun_lift = struct.unpack_from("<H", data, pos + 8)[0]  # 8-9
        health = struct.unpack_from("<b", data, pos + 10)[0]  # signed
        # skip 3                                                    # 11-13
        iflag2 = struct.unpack_from("<H", data, pos + 14)[0]  # 14-15
        rflags = struct.unpack_from("<H", data, pos + 16)[0]  # 16-17
        strength_val = data[pos + 18]  # 18
        dexterity = data[pos + 19]  # 19
        intel_val = data[pos + 20]  # 20
        combat_val = data[pos + 21]  # 21
        schedule_type = data[pos + 22]  # 22
        amode_byte = data[pos + 23]  # 23
        # charmalign / skip — 1 byte consumed either way            # 24
        unk0 = data[pos + 25]  # 25
        unk1 = data[pos + 26]  # 26
        # magic / mana — 2 bytes consumed either way                # 27-28
        if original_new_game or unk0 == 0:
            magic_val = data[pos + 27]
            mana_val = data[pos + 28]
            if actor_npc_num == 0:
                magic = magic_val & 0x1F
                mana = mana_val & 0x1F
            else:
                magic = 0
                mana = 0
        else:
            magic = unk0 & 0x7F
            mana = unk1

        face_num = struct.unpack_from("<H", data, pos + 29)[0]  # 29-30
        if original_new_game:
            face_num = actor_npc_num
        # skip 1                                                    # 31
        experience = struct.unpack_from("<I", data, pos + 32)[0]  # 32-35
        training = data[pos + 36]  # 36
        # skip 2+2 (attackers)                                      # 37-40
        # skip 2 (oppressor)                                        # 41-42
        # skip 4                                                    # 43-46
        # schedule_loc tx,ty                                        # 47-50
        type_flags = struct.unpack_from("<H", data, pos + 51)[0]  # 51-52
        # skip 5                                                    # 53-57
        # next_schedule(1), skip 1+2+2                              # 58-63
        shape16 = struct.unpack_from("<H", data, pos + 64)[0]  # 64-65
        # 66-67: polymorph/skip, 68-71: ext_flags
        # 72-73: sched_tz+spare, 74-77: flags2
        p = pos + 78

        # -- optional variable-size fields ---------------------------------
        usecode_name_used = (not original_new_game) and bool(iflag1 & 8)

        if usecode_name_used:
            funsize = data[p]
            p += 1 + funsize

        # skin byte — always consumed in Exult saves
        p += 1

        # -- trailing fixed section ----------------------------------------
        p += 14  # skip 14
        food = struct.unpack_from("<b", data, p)[0]  # signed food
        p += 1
        p += 7  # skip 7
        name_raw = data[p : p + 16]
        name = _clean_ascii_text(
            name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        ).strip()
        p += 16

        # -- decode fields -------------------------------------------------
        shape = shnum & 0x3FF
        frame = (shnum >> 10) & 0x3F
        if shape16 != 0 and not original_new_game:
            shape = shape16

        lift = (usefun_lift >> 12) & 0xF
        alignment = (rflags >> 3) & 3
        attack_mode = amode_byte & 0xF
        # SI bits 5..6 hold skin and bit 7 freeze; BG keeps bit 5 in strength.
        strength = strength_val & (0x1F if game == "si" else 0x3F)
        intelligence = intel_val & 0x1F
        combat = combat_val & 0x7F

        # Exult shares this state from Avatar through both NPC groups. Monsters
        # have semantic identity -1 and cannot activate or use the slot repair.
        compatibility = actor_npc_num >= 0 and (
            fix_unused or (actor_npc_num == 0 and iflag2 == 0)
        )
        unused = iflag2 == 0 and actor_npc_num > 0 and not compatibility
        has_contents = (
            bool(iflag1 and not unused) if original_new_game else bool(iflag1 & 1)
        )
        has_sched_usecode = (not original_new_game) and bool(iflag1 & 2)
        in_party_rf = bool(rflags & (1 << 0xB))
        in_party_tf = False if original_new_game else bool(type_flags & (1 << 12))
        if sex_unknown:
            is_female = None
        elif original_new_game:
            is_female = not bool(type_flags & (1 << 9))
        else:
            is_female = bool(type_flags & (1 << 9))

        sc_x = schunk % 12
        sc_y = schunk // 12
        tile_x = (sc_x * 16 + (locx >> 4)) * 16 + (locx & 0xF)
        tile_y = (sc_y * 16 + (locy >> 4)) * 16 + (locy & 0xF)

        npc = U7NPC(
            npc_num=npc_idx,
            name=name,
            shape=shape,
            frame=frame,
            tile_x=tile_x,
            tile_y=tile_y,
            superchunk=schunk,
            map_num=map_num,
            lift=lift,
            health=health,
            strength=strength,
            dexterity=dexterity,
            intelligence=intelligence,
            combat=combat,
            magic=magic,
            mana=mana,
            experience=experience,
            training=training,
            food=food,
            schedule_type=schedule_type,
            attack_mode=attack_mode,
            alignment=alignment,
            face_num=face_num,
            type_flags=type_flags,
            rflags=rflags,
            in_party=in_party_rf or in_party_tf,
            is_female=is_female,
            has_inventory=has_contents,
            unused=unused,
            used_in_game_raw=iflag2,
            unused_compatibility=compatibility,
            metadata=U7ActorMetadata.from_bytes(
                data[pos:p],
                game=game,
                original_new_game=original_new_game,
                npc_num=actor_npc_num,
                health=health,
                strength=strength,
                has_usecode=has_usecode,
            ),
        )
        if npc.metadata is not None and npc.metadata.effective_flags & (1 << 6):
            npc.in_party = True

        # -- skip inventory / scheduled usecode ----------------------------
        if has_contents:
            inventory_start = p
            npc.inventory_ireg = U7IregExtras()
            npc.inventory, p = _read_ireg_inventory(
                data,
                p,
                container_shapes,
                valid_shape_count,
                ireg_context=ireg_context,
                extras=npc.inventory_ireg,
                offset_base=offset_base,
            )
            npc.inventory_ireg.raw_hex = data[inventory_start:p].hex()
            npc.ireg_warnings.extend(npc.inventory_ireg.warnings)
        if has_sched_usecode:
            npc.ireg_specials, p = read_ireg_specials(
                data, p, owner_offset=pos + offset_base, offset_base=offset_base
            )
            for special in npc.ireg_specials:
                npc.ireg_warnings.extend(
                    f"IREG offset {special.offset}: {warning}"
                    for warning in special.warnings
                )

        return npc, p

    # ---- dump helpers ----------------------------------------------------

    def dump_summary(self) -> str:
        named = sum(1 for n in self.npcs if n.name)
        in_party = sum(1 for n in self.npcs if n.in_party)
        alive = sum(1 for n in self.npcs if not n.is_dead and not n.unused)
        return (
            f"NPCs: {len(self.npcs)} parsed "
            f"({self.num_npcs1}+{self.num_npcs2} declared), "
            f"{named} named, {in_party} in party, {alive} alive"
        ) + "".join(f"\nWarning: {warning}" for warning in self.warnings)

    def dump_detail(self) -> str:
        lines = [
            f"=== NPC Data ({len(self.npcs)} parsed, "
            f"{self.num_npcs1}+{self.num_npcs2} declared) ===",
            "",
        ]
        for n in self.npcs:
            party = " [PARTY]" if n.in_party else ""
            sex = "?" if n.is_female is None else ("F" if n.is_female else "M")
            inv = " [INV]" if n.has_inventory else ""
            dead = " [DEAD]" if n.is_dead else ""
            un = " [UNUSED]" if n.unused else ""
            lines.append(
                f"NPC {n.npc_num:4d}: {n.name or '(unnamed)':<16s} "
                f"shape={n.shape:4d}:{n.frame}  "
                f"pos=({n.tile_x},{n.tile_y},{n.lift}) "
                f"map={n.map_num}  "
                f"HP={n.health:3d}  "
                f"STR={n.strength:2d} DEX={n.dexterity:2d} "
                f"INT={n.intelligence:2d} CMB={n.combat:2d}  "
                f"MAG={n.magic:2d} MNA={n.mana:2d}  "
                f"EXP={n.experience:6d}  "
                f"sched={n.schedule_name:<14s} "
                f"align={n.alignment_name} "
                f"{sex}{party}{inv}{dead}{un}"
            )
        return "\n".join(lines)

    def dump_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "npc_num",
                "name",
                "shape",
                "frame",
                "tile_x",
                "tile_y",
                "lift",
                "map_num",
                "health",
                "strength",
                "dex",
                "intelligence",
                "combat",
                "magic",
                "mana",
                "exp",
                "training",
                "food",
                "current_sched_type",
                "current_sched_name",
                "attack_mode",
                "alignment",
                "face",
                "type_flags",
                "type_flags_hex",
                "in_party",
                "female",
                "has_inventory",
                "inventory_count",
                "dead",
                "unused",
                "actor_extensions",
                "used_in_game_raw",
                "unused_compatibility",
                "ireg_specials",
                "ireg_warnings",
            ]
        )
        for n in self.npcs:
            female = "UNKNOWN" if n.is_female is None else str(n.is_female)
            writer.writerow(
                [
                    n.npc_num,
                    n.name,
                    n.shape,
                    n.frame,
                    n.tile_x,
                    n.tile_y,
                    n.lift,
                    n.map_num,
                    n.health,
                    n.strength,
                    n.dexterity,
                    n.intelligence,
                    n.combat,
                    n.magic,
                    n.mana,
                    n.experience,
                    n.training,
                    n.food,
                    n.schedule_type,
                    n.schedule_name,
                    n.attack_mode,
                    n.alignment,
                    n.face_num,
                    n.type_flags,
                    f"0x{n.type_flags:04X}",
                    n.in_party,
                    female,
                    n.has_inventory,
                    len(n.inventory),
                    n.is_dead,
                    n.unused,
                    json.dumps(n.metadata.as_row()) if n.metadata is not None else "",
                    n.used_in_game_raw,
                    n.unused_compatibility,
                    json.dumps([special.as_row() for special in n.ireg_specials]),
                    json.dumps(n.ireg_warnings),
                ]
            )
        return buf.getvalue()

    def dump_inventory_csv(
        self,
        shape_names: object | None = None,
        ready_types: U7ReadyTypes | None = None,
        npc_nums: set[int] | None = None,
        *,
        effective_ready: U7ReadyMetadata | None = None,
    ) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "npc_num",
                "npc_name",
                "item_index",
                "shape",
                "shape_hex",
                "item_name",
                "frame",
                "x",
                "y",
                "lift",
                "quality",
                "depth",
                "location",
                "ready_slot",
                "path",
                "path_names",
                "effective_ready",
                "ireg_kind",
                "ireg_data",
                "ireg_warnings",
                "ireg_raw_hex",
                "saved_index_word",
                "saved_index_id",
                "saved_slot_name",
                "ireg_index_raw_hex",
                "ireg_specials",
            ]
        )
        for n in self.npcs:
            if npc_nums is not None and n.npc_num not in npc_nums:
                continue
            for index, item in enumerate(n.inventory):
                item_name = _shape_name(shape_names, item.shape)
                writer.writerow(
                    [
                        n.npc_num,
                        n.name,
                        index,
                        item.shape,
                        f"0x{item.shape:04X}",
                        item_name,
                        item.frame,
                        item.x,
                        item.y,
                        item.lift,
                        item.quality,
                        item.depth,
                        _inventory_location(item, ready_types),
                        ready_types.slot_name_for_shape(item.shape)
                        if ready_types
                        else "",
                        item.path,
                        _inventory_path_names(item.path, shape_names),
                        json.dumps(
                            effective_ready.resolve(item.shape, item.frame).as_row()
                        )
                        if effective_ready
                        else "",
                        item.ireg_kind,
                        json.dumps(item.ireg_data),
                        json.dumps(item.ireg_warnings),
                        item.ireg_raw_hex,
                        item.ireg_index_id.raw_word if item.ireg_index_id else "",
                        item.ireg_index_id.index if item.ireg_index_id else "",
                        item.ireg_index_id.slot_name if item.ireg_index_id else "",
                        item.ireg_index_id.raw_hex if item.ireg_index_id else "",
                        json.dumps(
                            [special.as_row() for special in item.ireg_specials]
                        ),
                    ]
                )
        return buf.getvalue()


def _inventory_location(
    item: U7NPCInventoryItem,
    ready_types: U7ReadyTypes | None = None,
) -> str:
    if item.depth > 0 and item.path.startswith("801:"):
        return "backpack"
    if item.depth > 0:
        return "nested_container"
    if item.ireg_index_id is not None:
        if item.ireg_index_id.slot_name:
            return f"saved_readied:{item.ireg_index_id.slot_name}"
        if item.ireg_index_id.index == -1:
            return "actor_inventory"
        return "invalid_saved_slot"
    if item.shape == 801:
        return "backpack_container"
    return "actor_top_slot_unrecorded"


def _inventory_path_names(path: str, shape_names: object | None) -> str:
    if not path or shape_names is None:
        return ""
    parts: list[str] = []
    for token in path.split("/"):
        shape_text, _, frame_text = token.partition(":")
        try:
            shape = int(shape_text)
        except ValueError:
            parts.append(token)
            continue
        name = _shape_name(shape_names, shape)
        label = f"{shape}:{frame_text}"
        if name:
            label = f"{label} ({name})"
        parts.append(label)
    return "/".join(parts)


def _shape_name(shape_names: object | None, shape: int) -> str:
    if shape_names is None:
        return ""
    get_name = getattr(shape_names, "get", None)
    if not callable(get_name):
        return ""
    value = get_name(shape)
    return str(value) if value else ""
