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

__all__ = [
    "U7Save", "U7GlobalFlags", "U7Identity", "U7SaveInfo",
    "U7PartyMember", "U7GameState", "U7UsecodeData", "U7UsecodeTimer",
    "U7UsecodeVars", "U7Keyring", "U7FrameFlags", "U7Schedules",
    "U7ScheduleEntry", "U7NPCData", "U7NPC",
]

import csv
import io
import os
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Optional, Union


# ---------------------------------------------------------------------------
# FLEX magic constants (from Exult Flex.h)
# ---------------------------------------------------------------------------
_FLEX_MAGIC1 = 0xFFFF1A00
_FLEX_TITLE_LEN = 80     # bytes
_FLEX_HEADER_LEN = 128   # 0x80


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
    ) -> None:
        self.title = title
        self._entries = entries          # name -> raw data
        self.container_format = container_format   # "zip" or "flex"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str) -> U7Save:
        """Open a ``.sav`` file from disk."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> U7Save:
        """Parse a savegame from raw bytes (auto-detects format)."""
        if len(data) < _FLEX_HEADER_LEN:
            raise ValueError("File too small for a U7 savegame")

        # --- Detect format ---
        # FLEX: magic1 at offset 0x50
        magic1 = struct.unpack_from("<I", data, 0x50)[0]
        if magic1 == _FLEX_MAGIC1:
            return cls._parse_flex(data)

        # ZIP: after 80-byte title, look for PK signature
        if data[_FLEX_TITLE_LEN:_FLEX_TITLE_LEN + 2] == b"PK":
            return cls._parse_zip(data)

        # Exult mod patch INITGAME.DAT files can be plain ZIP archives
        # without the 80-byte save title prefix.
        if data[:2] == b"PK":
            return cls._parse_raw_zip(data)

        raise ValueError(
            "Unrecognised U7 savegame format (not FLEX, not ZIP)"
        )

    # ------------------------------------------------------------------
    # FLEX parser
    # ------------------------------------------------------------------

    @classmethod
    def _parse_flex(cls, data: bytes) -> U7Save:
        title = data[:_FLEX_TITLE_LEN].split(b"\x00")[0].decode(
            "latin-1", errors="replace"
        )
        count = struct.unpack_from("<I", data, 0x54)[0]

        # Entry table starts at 0x80: N × (offset_u32, size_u32)
        entries: dict[str, bytes] = {}
        pos = _FLEX_HEADER_LEN
        for _ in range(count):
            if pos + 8 > len(data):
                break
            offset, size = struct.unpack_from("<II", data, pos)
            pos += 8
            if size <= 13 or offset + size > len(data):
                continue   # empty / padding entry
            # First 13 bytes of the blob are the DOS 8.3 filename
            name_raw = data[offset:offset + 13]
            name = name_raw.split(b"\x00")[0].decode("latin-1",
                                                      errors="replace")
            name = name.rstrip(".")   # Exult strips trailing dots
            payload = data[offset + 13:offset + size]
            entries[name] = payload

        return cls(title=title, entries=entries, container_format="flex")

    # ------------------------------------------------------------------
    # ZIP parser (level-1 and level-2)
    # ------------------------------------------------------------------

    @classmethod
    def _parse_zip(cls, data: bytes) -> U7Save:
        title = data[:_FLEX_TITLE_LEN].split(b"\x00")[0].decode(
            "latin-1", errors="replace"
        )
        zip_data = data[_FLEX_TITLE_LEN:]
        return cls._parse_zip_payload(zip_data, title)

    @classmethod
    def _parse_raw_zip(cls, data: bytes) -> U7Save:
        return cls._parse_zip_payload(data, "")

    @classmethod
    def _parse_zip_payload(cls, zip_data: bytes, title: str) -> U7Save:
        entries: dict[str, bytes] = {}

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for info in zf.infolist():
                raw = zf.read(info.filename)
                name_lower = info.filename.lower()

                # Level-2 grouped entries: "gamedat" or "mapXX"
                if name_lower == "gamedat" or (
                    name_lower.startswith("map")
                    and len(name_lower) == 5
                    and name_lower[3:].isdigit()
                ):
                    cls._unpack_level2(raw, entries,
                                       prefix="" if name_lower == "gamedat"
                                       else name_lower + "/")
                else:
                    # Level-1: each ZIP entry is one file
                    entries[info.filename] = raw

        return cls(title=title, entries=entries, container_format="zip")

    @staticmethod
    def _unpack_level2(
        blob: bytes,
        entries: dict[str, bytes],
        prefix: str,
    ) -> None:
        """Decode a Level-2 packed group (12-byte name + 4-byte size + data)."""
        pos = 0
        while pos + 16 <= len(blob):
            name_raw = blob[pos:pos + 12]
            size = struct.unpack_from("<I", blob, pos + 12)[0]
            pos += 16
            # Terminator: 12 zero-bytes for name + 0 size
            if name_raw == b"\x00" * 12 and size == 0:
                break
            name = name_raw.split(b"\x00")[0].decode(
                "latin-1", errors="replace"
            ).rstrip(".")
            if not name:
                pos += size
                continue
            payload = blob[pos:pos + size]
            entries[prefix + name] = payload
            pos += size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_entries(self) -> list[tuple[str, int]]:
        """Return list of ``(name, size)`` tuples."""
        return [(name, len(data)) for name, data in self._entries.items()]

    def get_data(self, name: str) -> Optional[bytes]:
        """Get raw bytes for a named entry (case-insensitive)."""
        # exact match first
        if name in self._entries:
            return self._entries[name]
        # case-insensitive fallback
        lower = name.lower()
        for key, val in self._entries.items():
            if key.lower() == lower:
                return val
        return None

    def has_entry(self, name: str) -> bool:
        """Check whether the save contains *name* (case-insensitive)."""
        return self.get_data(name) is not None

    def entry_names(self) -> list[str]:
        """Return list of entry names."""
        return list(self._entries.keys())


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
        return (
            f"Global Flags: {self.count} total, "
            f"{self.nonzero_count} set (nonzero)"
        )

    def dump_detail(self) -> str:
        """
        Full listing of all set flags.

        Each line::

            gflag[  123 / 0x007B] =   1 (0x01)
        """
        lines: list[str] = []
        lines.append(
            f"=== Global Flags ({self.count} total, "
            f"{self.nonzero_count} set) ==="
        )
        lines.append("")
        for i, v in enumerate(self.raw):
            if v != 0:
                lines.append(
                    f"  gflag[{i:5d} / 0x{i:04X}] = {v:3d} (0x{v:02x})"
                )
        lines.append("")
        lines.append(
            f"Summary: {self.count} total flags, "
            f"{self.nonzero_count} non-zero."
        )
        return "\n".join(lines)

    def dump_csv(self) -> str:
        """
        CSV with every set flag (index_dec, index_hex, value_dec, value_hex).
        """
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(["index", "index_hex", "value", "value_hex"])
        for i, v in enumerate(self.raw):
            if v != 0:
                writer.writerow([i, f"0x{i:04X}", v, f"0x{v:02x}"])
        return buf.getvalue()


# ============================================================================
# Name look-up tables
# ============================================================================

SCHEDULE_TYPE_NAMES: dict[int, str] = {
    0: "combat", 1: "horiz_pace", 2: "vert_pace", 3: "talk",
    4: "dance", 5: "eat", 6: "farm", 7: "tend_shop",
    8: "miner", 9: "hound", 10: "stand", 11: "loiter",
    12: "wander", 13: "blacksmith", 14: "sleep", 15: "wait",
    16: "sit", 17: "graze", 18: "bake", 19: "sew",
    20: "shy", 21: "lab", 22: "thief", 23: "waiter",
    24: "special", 25: "kid_games", 26: "eat_at_inn", 27: "duel",
    28: "preach", 29: "patrol", 30: "desk_work", 31: "follow_avatar",
}

ALIGNMENT_NAMES: dict[int, str] = {
    0: "neutral", 1: "good", 2: "evil", 3: "chaotic",
}

ATTACK_MODE_NAMES: dict[int, str] = {
    0: "nearest", 1: "weakest", 2: "strongest", 3: "berserk",
    4: "protect", 5: "defend", 6: "flank", 7: "flee",
    8: "random", 9: "manual",
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
    party: list = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7SaveInfo":
        if len(data) < 64:
            raise ValueError(
                f"saveinfo.dat too short: {len(data)} bytes (need >= 64)"
            )
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
        return "\n".join(lines)


# ============================================================================
# U7GameState
# ============================================================================

@dataclass
class U7GameState:
    """World state from ``gamewin.dat`` — camera position, clock, flags.

    Layout (all little-endian)::

        0-1   scroll_tx  (uint16)     6-7   hour       (uint16)
        2-3   scroll_ty  (uint16)     8-9   minute     (uint16)
        4-5   day        (uint16)    10-13  special_light (uint32)
       14-17  music_track (uint32)   18-21  music_repeat  (uint32)
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

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7GameState":
        if len(data) < 22:
            raise ValueError(
                f"gamewin.dat too short: {len(data)} bytes (need >= 22)"
            )
        stx, sty, day, hour, minute = struct.unpack_from("<HHHHH", data, 0)
        sp_light = struct.unpack_from("<I", data, 10)[0] if len(data) >= 14 else 0
        music_trk = struct.unpack_from("<I", data, 14)[0] if len(data) >= 18 else 0
        music_rep = struct.unpack_from("<I", data, 18)[0] if len(data) >= 22 else 0
        arma = bool(data[22]) if len(data) > 22 else False
        ambient = bool(data[23]) if len(data) > 23 else False
        comb = bool(data[24]) if len(data) > 24 else False
        infra = bool(data[25]) if len(data) > 25 else False
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
        )

    @classmethod
    def from_save(cls, save: U7Save) -> "U7GameState":
        data = save.get_data("gamewin.dat")
        if data is None:
            raise ValueError("Save does not contain 'gamewin.dat'")
        return cls.from_bytes(data)

    def dump(self) -> str:
        lines = [
            "--- Game State ---",
            f"Camera:      tile ({self.scroll_tx}, {self.scroll_ty})",
            f"Game time:   Day {self.clock_day}, "
            f"{self.clock_hour:02d}:{self.clock_minute:02d}",
            f"Music:       track {self.music_track} "
            f"(repeat={self.music_repeat & 1})",
            f"Light:       special={self.special_light}, "
            f"ambient={self.ambient_light}",
            f"Combat:      {self.combat}",
            f"Armageddon:  {self.armageddon}",
            f"Infravision: {self.infravision}",
        ]
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
    """Runtime usecode state from loose ``usecode.dat``.

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

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7UsecodeData":
        if len(data) < 2:
            raise ValueError("usecode.dat too short")

        pos = 0

        def read_u16(default: int = 0) -> int:
            nonlocal pos
            if pos + 2 > len(data):
                pos = len(data)
                return default
            value = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            return value

        def read_u32(default: int = 0) -> int:
            nonlocal pos
            if pos + 4 > len(data):
                pos = len(data)
                return default
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            return value

        party_count = read_u16()
        party_slots = [read_u16() for _ in range(10)]
        party_members = party_slots[: min(party_count, len(party_slots))]

        timers: list[U7UsecodeTimer] = []
        timer_format = "legacy"
        marker = read_u32()
        if marker == 0xFFFFFFFF:
            timer_format = "sparse"
            while pos + 2 <= len(data):
                timer_id = read_u16()
                if timer_id == 0xFFFF:
                    break
                timers.append(U7UsecodeTimer(timer_id, read_u32()))
        else:
            timers.append(U7UsecodeTimer(0, marker))
            for timer_id in range(1, 20):
                if pos + 4 > len(data):
                    break
                timers.append(U7UsecodeTimer(timer_id, read_u32()))

        saved_tx = saved_ty = saved_tz = saved_map = -1
        if pos + 8 <= len(data):
            saved_tx = read_u16()
            saved_ty = read_u16()
            saved_tz = read_u16()
            saved_map = read_u16()

        return cls(
            party_count=party_count,
            party_members=party_members,
            timers=timers,
            timer_format=timer_format,
            saved_tx=saved_tx,
            saved_ty=saved_ty,
            saved_tz=saved_tz,
            saved_map=saved_map,
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
        return "\n".join(lines)


@dataclass
class U7UsecodeVars:
    """Lightweight summary of ``usecode.var`` static variable data."""

    global_static_count: int
    local_static_blocks: int = 0
    raw_size: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7UsecodeVars":
        if len(data) < 4:
            raise ValueError("usecode.var too short")
        global_count = struct.unpack_from("<I", data, 0)[0]
        pos = 4
        # Full Usecode_value decoding needs symbol and class context.  For now
        # count function-static block sentinels when the global section is empty,
        # which covers the common empty file and keeps this parser conservative.
        local_blocks = 0
        if global_count == 0:
            while pos + 4 <= len(data):
                marker = struct.unpack_from("<I", data, pos)[0]
                if marker == 0xFFFFFFFF:
                    break
                local_blocks += 1
                break
        return cls(
            global_static_count=global_count,
            local_static_blocks=local_blocks,
            raw_size=len(data),
        )

    @classmethod
    def from_file(cls, filepath: str) -> "U7UsecodeVars":
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def dump(self) -> str:
        return (
            "--- Usecode Statics ---\n"
            f"Global static values: {self.global_static_count}\n"
            f"Local static blocks:  {self.local_static_blocks}\n"
            f"Raw size:             {self.raw_size} bytes"
        )


@dataclass
class U7Keyring:
    """SI keyring data from ``keyring.dat``."""

    keys: list[int] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Keyring":
        keys = [
            struct.unpack_from("<H", data, pos)[0]
            for pos in range(0, len(data) - 1, 2)
        ]
        return cls(keys=keys)

    @classmethod
    def from_file(cls, filepath: str) -> "U7Keyring":
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def dump(self) -> str:
        return (
            "--- Keyring ---\n"
            f"Keys: {len(self.keys)}"
            + (f" ({', '.join(str(k) for k in self.keys)})" if self.keys else "")
        )


@dataclass
class U7FrameFlags:
    """Frame flags from ``frames.flg`` as signed 32-bit values."""

    values: list[int] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7FrameFlags":
        if len(data) % 4 != 0:
            raise ValueError(
                f"frames.flg size must be divisible by 4, got {len(data)}"
            )
        values = [
            struct.unpack_from("<i", data, pos)[0]
            for pos in range(0, len(data), 4)
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

    time: int   # 0-7 (3-hour periods: 0=midnight, 1=3am, … 7=9pm)
    type: int   # Schedule type (0-31)
    tx: int     # Absolute tile X
    ty: int     # Absolute tile Y
    tz: int     # Lift (Z)
    days: int   # Day bitmask (0x7F = all 7 days, Exult only)

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
    """

    entries: dict = field(default_factory=dict)
    num_npcs: int = 0
    format: str = "u7"  # "u7", "exult", "exult2"

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Schedules":
        if len(data) < 4:
            raise ValueError("schedule.dat too short")

        magic = struct.unpack_from("<i", data, 0)[0]
        pos = 4

        if magic == -1:
            fmt = "exult"
            num_npcs = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif magic == -2:
            fmt = "exult2"
            num_npcs = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            num_scripts = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        else:
            fmt = "u7"
            num_npcs = magic

        sched = cls(num_npcs=num_npcs, format=fmt)
        if num_npcs == 0:
            return sched

        # Offset table — num_npcs × uint16 (cumulative entry counts)
        table_start = pos
        if table_start + num_npcs * 2 > len(data):
            return sched
        offsets: list[int] = []
        for i in range(num_npcs):
            offsets.append(struct.unpack_from("<H", data, table_start + i * 2)[0])
        pos = table_start + num_npcs * 2

        # Skip script names for -2 format
        if fmt == "exult2" and num_scripts > 0:
            if pos + 2 <= len(data):
                total_sz = struct.unpack_from("<H", data, pos)[0]
                pos += 2 + total_sz

        # Parse entries
        entry_size = 8 if fmt.startswith("exult") else 4
        prev_count = 0
        for npc_idx, cum_count in enumerate(offsets):
            n_entries = cum_count - prev_count
            prev_count = cum_count
            if n_entries <= 0:
                continue
            npc_entries: list[U7ScheduleEntry] = []
            for _ in range(n_entries):
                if pos + entry_size > len(data):
                    break
                if entry_size == 8:
                    tx = struct.unpack_from("<H", data, pos)[0]
                    ty = struct.unpack_from("<H", data, pos + 2)[0]
                    tz = data[pos + 4]
                    time_val = data[pos + 5]
                    type_val = data[pos + 6]
                    days = data[pos + 7]
                else:
                    b0 = data[pos]
                    time_val = b0 & 7
                    type_val = (b0 >> 3) & 0x1F
                    sx = data[pos + 1]
                    sy = data[pos + 2]
                    schunk = data[pos + 3]
                    tx = (schunk % 12) * _TILES_PER_SCHUNK + sx
                    ty = (schunk // 12) * _TILES_PER_SCHUNK + sy
                    tz = 0
                    days = 0x7F
                npc_entries.append(
                    U7ScheduleEntry(
                        time=time_val,
                        type=type_val,
                        tx=tx,
                        ty=ty,
                        tz=tz,
                        days=days,
                    )
                )
                pos += entry_size
            if npc_entries:
                sched.entries[npc_idx] = npc_entries
        return sched

    @classmethod
    def from_file(cls, filepath: str) -> "U7Schedules":
        """Read a loose ``schedule.dat`` file from disk."""
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    @classmethod
    def from_save(cls, save: U7Save) -> "U7Schedules":
        data = save.get_data("schedule.dat")
        if data is None:
            raise ValueError("Save does not contain 'schedule.dat'")
        return cls.from_bytes(data)

    def dump_summary(self, npc_names: dict[int, str] | None = None) -> str:
        total = sum(len(v) for v in self.entries.values())
        return (
            f"Schedules: {self.num_npcs} NPCs tracked, "
            f"{len(self.entries)} with entries, "
            f"{total} total entries ({self.format} format)"
        )

    def dump_detail(self, npc_names: dict[int, str] | None = None) -> str:
        lines = [
            f"=== Schedules ({self.format} format, "
            f"{self.num_npcs} NPCs) ===",
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
                    f"type={e.type:2d} ({e.type_name:<14s})  "
                    f"at ({e.tx}, {e.ty}, {e.tz})  days=0x{e.days:02X}"
                )
        lines.append("")
        total = sum(len(v) for v in self.entries.values())
        lines.append(
            f"Total: {len(self.entries)} NPCs with {total} entries"
        )
        return "\n".join(lines)

    def dump_csv(self, npc_names: dict[int, str] | None = None) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(["npc", "name", "time_slot", "sched_type", "sched_name", "tx", "ty", "tz", "days"])
        for npc_idx in sorted(self.entries):
            for e in self.entries[npc_idx]:
                name = npc_names.get(npc_idx, "") if npc_names else ""
                writer.writerow([
                    npc_idx, name, e.time, e.type, e.type_name,
                    e.tx, e.ty, e.tz, f"0x{e.days:02X}",
                ])
        return buf.getvalue()


def _clean_ascii_text(value: str) -> str:
    """Keep decoded game text console-safe on Windows terminals."""
    return value.encode("ascii", errors="replace").decode("ascii")


# ============================================================================
# IREG skip helpers (for NPC inventory parsing)
# ============================================================================

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

        # Check for container nesting (testlen 12 or 13)
        testlen = entry_len - extended
        if testlen in (12, 13) and entry_start + 6 + extended <= len(data):
            ed = data[entry_start : entry_start + entry_len]
            if extended:
                shape = ed[2] + 256 * ed[3]
            else:
                shape = ed[2] + 256 * (ed[3] & 3)
            type_off = 4 + extended
            type_val = (
                (ed[type_off] + 256 * ed[type_off + 1])
                if len(ed) > type_off + 1
                else 0
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
    ``0xFF 0x01`` (IREG_ENDMARK).
    """
    while pos < len(data):
        if data[pos] != 0xFF:
            return pos
        pos += 1  # consume 0xFF

        if pos >= len(data):
            break
        if data[pos] == 0x02:  # IREG_ENDMARK
            pos += 1
            return pos

        # type(1) + len(2) + data(len)
        if pos + 3 > len(data):
            break
        pos += 1
        sp_len = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + sp_len
    return pos


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
    unused: bool = False

    @property
    def schedule_name(self) -> str:
        return SCHEDULE_TYPE_NAMES.get(
            self.schedule_type, f"?{self.schedule_type}"
        )

    @property
    def alignment_name(self) -> str:
        return ALIGNMENT_NAMES.get(self.alignment, f"?{self.alignment}")

    @property
    def attack_mode_name(self) -> str:
        return ATTACK_MODE_NAMES.get(
            self.attack_mode, f"?{self.attack_mode}"
        )

    @property
    def is_dead(self) -> bool:
        return bool(self.rflags & (1 << 15))


class U7NPCData:
    """All NPCs from ``npc.dat``.

    Reads each NPC's fixed-header fields (stats, position, name) and
    skips any IREG inventory data.  For reliable container-nesting
    detection, pass a set of container shape numbers via
    *container_shapes* (shape class 6 from
    :class:`~titan.u7.typeflag.U7TypeFlags`).
    """

    def __init__(
        self,
        npcs: list,
        num_npcs1: int = 0,
        num_npcs2: int = 0,
    ):
        self.npcs: list[U7NPC] = npcs
        self.num_npcs1 = num_npcs1
        self.num_npcs2 = num_npcs2

    # ---- factory ----------------------------------------------------------

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        container_shapes: Union[set, None] = None,
        sex_unknown: bool = False,
        original_new_game: bool = False,
    ) -> "U7NPCData":
        if len(data) < 4:
            raise ValueError("npc.dat too short")

        num1 = struct.unpack_from("<H", data, 0)[0]
        num2 = struct.unpack_from("<H", data, 2)[0]
        pos = 4
        npcs: list[U7NPC] = []
        total = num1 + num2

        for npc_idx in range(total):
            if pos + 78 > len(data):
                break
            try:
                npc, pos = cls._read_one_npc(
                    data,
                    pos,
                    npc_idx,
                    container_shapes,
                    sex_unknown,
                    original_new_game,
                )
                npcs.append(npc)
            except (struct.error, IndexError, ValueError):
                break
        return cls(npcs=npcs, num_npcs1=num1, num_npcs2=num2)

    @classmethod
    def from_save(
        cls,
        save: U7Save,
        container_shapes: Union[set, None] = None,
    ) -> "U7NPCData":
        data = save.get_data("npc.dat")
        if data is None:
            raise ValueError("Save does not contain 'npc.dat'")
        return cls.from_bytes(data, container_shapes)

    @classmethod
    def from_file(
        cls,
        filepath: str,
        container_shapes: Union[set, None] = None,
        sex_unknown: bool = False,
        original_new_game: bool = False,
    ) -> "U7NPCData":
        """Read a loose ``npc.dat`` file from disk."""
        with open(filepath, "rb") as f:
            return cls.from_bytes(
                f.read(),
                container_shapes,
                sex_unknown,
                original_new_game,
            )

    @classmethod
    def from_initgame_file(
        cls,
        filepath: str,
        container_shapes: Union[set, None] = None,
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
                    original_new_game=True,
                )
        raise ValueError(f"INITGAME.DAT does not contain npc.dat: {filepath}")

    @classmethod
    def from_monsnpcs_bytes(
        cls,
        data: bytes,
        container_shapes: Union[set, None] = None,
    ) -> "U7NPCData":
        """Read Exult ``monsnpcs.dat`` monster actors.

        ``monsnpcs.dat`` stores one uint16 monster count followed by actor
        records in the same serialized form used by ``npc.dat``.  Adapt that
        single count to the two-count ``npc.dat`` header so the shared actor
        reader can parse it.
        """
        if len(data) < 2:
            raise ValueError("monsnpcs.dat too short")
        count = struct.unpack_from("<H", data, 0)[0]
        npc_like = struct.pack("<HH", count, 0) + data[2:]
        return cls.from_bytes(npc_like, container_shapes=container_shapes)

    @classmethod
    def from_monsnpcs_file(
        cls,
        filepath: str,
        container_shapes: Union[set, None] = None,
    ) -> "U7NPCData":
        """Read a loose Exult ``monsnpcs.dat`` file from disk."""
        with open(filepath, "rb") as f:
            return cls.from_monsnpcs_bytes(f.read(), container_shapes)

    @classmethod
    def npc_name_map(
        cls,
        save: U7Save,
        container_shapes: Union[set, None] = None,
    ) -> dict[int, str]:
        """Extract ``{npc_index: name}`` from ``npc.dat`` in a save."""
        npc_data = cls.from_save(save, container_shapes)
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
        sex_unknown: bool,
        original_new_game: bool,
    ) -> tuple:
        """Parse one NPC record.  Returns ``(U7NPC, new_pos)``."""
        # -- fixed header (78 bytes) ----------------------------------------
        locx = data[pos]                                            # 0
        locy = data[pos + 1]                                        # 1
        shnum = struct.unpack_from("<H", data, pos + 2)[0]          # 2-3
        iflag1 = struct.unpack_from("<H", data, pos + 4)[0]         # 4-5
        schunk = data[pos + 6]                                      # 6
        map_num = data[pos + 7]                                     # 7
        if original_new_game:
            map_num = 0
        usefun_lift = struct.unpack_from("<H", data, pos + 8)[0]    # 8-9
        health = struct.unpack_from("<b", data, pos + 10)[0]        # signed
        # skip 3                                                    # 11-13
        iflag2 = struct.unpack_from("<H", data, pos + 14)[0]       # 14-15
        rflags = struct.unpack_from("<H", data, pos + 16)[0]       # 16-17
        strength_val = data[pos + 18]                               # 18
        dexterity = data[pos + 19]                                  # 19
        intel_val = data[pos + 20]                                  # 20
        combat_val = data[pos + 21]                                 # 21
        schedule_type = data[pos + 22]                              # 22
        amode_byte = data[pos + 23]                                 # 23
        # charmalign / skip — 1 byte consumed either way            # 24
        unk0 = data[pos + 25]                                       # 25
        unk1 = data[pos + 26]                                       # 26
        # magic / mana — 2 bytes consumed either way                # 27-28
        if original_new_game or unk0 == 0:
            magic_val = data[pos + 27]
            mana_val = data[pos + 28]
            if npc_idx == 0:
                magic = magic_val & 0x1F
                mana = mana_val & 0x1F
            else:
                magic = 0
                mana = 0
        else:
            magic = unk0 & 0x7F
            mana = unk1

        face_num = struct.unpack_from("<H", data, pos + 29)[0]     # 29-30
        if original_new_game:
            face_num = npc_idx
        # skip 1                                                    # 31
        experience = struct.unpack_from("<I", data, pos + 32)[0]   # 32-35
        training = data[pos + 36]                                   # 36
        # skip 2+2 (attackers)                                      # 37-40
        # skip 2 (oppressor)                                        # 41-42
        # skip 4                                                    # 43-46
        # schedule_loc tx,ty                                        # 47-50
        type_flags = struct.unpack_from("<H", data, pos + 51)[0]   # 51-52
        # skip 5                                                    # 53-57
        # next_schedule(1), skip 1+2+2                              # 58-63
        shape16 = struct.unpack_from("<H", data, pos + 64)[0]      # 64-65
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
        p += 7   # skip 7
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
        strength = strength_val & 0x3F
        intelligence = intel_val & 0x1F
        combat = combat_val & 0x7F

        unused = iflag2 == 0 and npc_idx > 0
        has_contents = (
            bool(iflag1 and not unused)
            if original_new_game
            else bool(iflag1 & 1)
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
        )

        # -- skip inventory / scheduled usecode ----------------------------
        if has_contents:
            p = _skip_ireg_inventory(data, p, container_shapes)
        if has_sched_usecode:
            p = _skip_special_ireg(data, p)

        return npc, p

    # ---- dump helpers ----------------------------------------------------

    def dump_summary(self) -> str:
        named = sum(1 for n in self.npcs if n.name)
        in_party = sum(1 for n in self.npcs if n.in_party)
        alive = sum(1 for n in self.npcs if n.health > 0)
        return (
            f"NPCs: {len(self.npcs)} parsed "
            f"({self.num_npcs1}+{self.num_npcs2} declared), "
            f"{named} named, {in_party} in party, {alive} alive"
        )

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
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow([
            "npc_num", "name", "shape", "frame", "tile_x", "tile_y", "lift", "map_num",
            "health", "strength", "dex", "intelligence", "combat", "magic", "mana", "exp", "training", "food",
            "current_sched_type", "current_sched_name", "attack_mode", "alignment",
            "face", "type_flags", "type_flags_hex", "in_party", "female", "has_inventory",
            "dead", "unused",
        ])
        for n in self.npcs:
            female = "UNKNOWN" if n.is_female is None else str(n.is_female)
            writer.writerow([
                n.npc_num, n.name, n.shape, n.frame,
                n.tile_x, n.tile_y, n.lift, n.map_num,
                n.health, n.strength, n.dexterity,
                n.intelligence, n.combat, n.magic, n.mana,
                n.experience, n.training, n.food,
                n.schedule_type, n.schedule_name, n.attack_mode,
                n.alignment, n.face_num, n.type_flags,
                f"0x{n.type_flags:04X}", n.in_party, female, n.has_inventory,
                n.is_dead, n.unused,
            ])
        return buf.getvalue()
