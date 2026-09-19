"""Ultima IX ``start.dat`` and ``u9game<N>.sav`` readers."""

from __future__ import annotations

__all__ = [
    "U9SaveArchive",
    "U9SaveError",
    "U9SaveHeader",
    "U9SaveMember",
    "U9StartDat",
]

import os
import struct
from dataclasses import dataclass

START_MAGIC = b"U9.008"
SAVE_MAGIC = b"U9:008"
METADATA_STRUCT = struct.Struct("<3f4f3f3i")
MAX_MAP_NUMBER = 239


class U9SaveError(Exception):
    """Raised when a U9 save selector or archive is malformed."""


@dataclass(frozen=True)
class U9StartDat:
    """The slot selector stored in ``savegame/start.dat``."""

    slot: int

    @classmethod
    def from_bytes(cls, data: bytes) -> U9StartDat:
        if len(data) != 10:
            raise U9SaveError(f"start.dat must be exactly 10 bytes, got {len(data)}")
        if data[:6] != START_MAGIC:
            raise U9SaveError(f"invalid start.dat magic {data[:6]!r}")
        (slot,) = struct.unpack_from("<i", data, 6)
        if slot < 0:
            raise U9SaveError(f"invalid negative save slot {slot}")
        return cls(slot)

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9StartDat:
        with open(filepath, "rb") as file:
            return cls.from_bytes(file.read())


@dataclass(frozen=True)
class U9SaveHeader:
    label: str
    description: str
    saved_position: tuple[float, float, float]
    saved_orientation: tuple[float, float, float, float]
    saved_yaw: float
    saved_pitch: float
    saved_roll: float
    saved_map: int
    saved_time: int
    saved_day: int


@dataclass(frozen=True)
class U9SaveMember:
    """One byte-exact payload from a save archive."""

    name: str
    data: bytes
    offset: int
    map_number: int | None = None


@dataclass(frozen=True)
class U9SaveArchive:
    header: U9SaveHeader
    screenshot: U9SaveMember
    processes: U9SaveMember
    diary: U9SaveMember
    nonfixed: tuple[U9SaveMember, ...]

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9SaveArchive:
        with open(filepath, "rb") as file:
            return cls.from_bytes(file.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> U9SaveArchive:
        if data[:6] != SAVE_MAGIC:
            raise U9SaveError(f"invalid save archive magic {data[:6]!r}")
        cursor = 6

        def read_i32(label: str) -> int:
            nonlocal cursor
            if cursor + 4 > len(data):
                raise U9SaveError(f"truncated before {label}")
            (value,) = struct.unpack_from("<i", data, cursor)
            cursor += 4
            return value

        def read_bytes(length: int, label: str) -> tuple[bytes, int]:
            nonlocal cursor
            if length < 0:
                raise U9SaveError(f"negative {label} length {length}")
            end = cursor + length
            if end > len(data):
                raise U9SaveError(
                    f"{label} extends beyond EOF ({cursor}+{length}>{len(data)})"
                )
            offset = cursor
            value = data[cursor:end]
            cursor = end
            return value, offset

        def read_string(label: str) -> str:
            raw, _ = read_bytes(read_i32(f"{label} length"), label)
            if not raw:
                return ""
            if raw[-1] != 0:
                raise U9SaveError(f"{label} is not NUL-terminated")
            try:
                return raw[:-1].decode("cp1252")
            except UnicodeDecodeError as error:
                raise U9SaveError(f"{label} is not valid text") from error

        label = read_string("label")
        description = read_string("description")
        metadata_raw, _ = read_bytes(METADATA_STRUCT.size, "save metadata")
        values = METADATA_STRUCT.unpack(metadata_raw)
        header = U9SaveHeader(
            label=label,
            description=description,
            saved_position=(values[0], values[1], values[2]),
            saved_orientation=(values[3], values[4], values[5], values[6]),
            saved_yaw=values[7],
            saved_pitch=values[8],
            saved_roll=values[9],
            saved_map=values[10],
            saved_time=values[11],
            saved_day=values[12],
        )

        def read_member(name: str) -> U9SaveMember:
            raw, offset = read_bytes(read_i32(f"{name} length"), name)
            return U9SaveMember(name, raw, offset)

        screenshot = read_member("screenshot")
        processes = read_member("processes.dat")
        diary = read_member("diary.txt")

        nonfixed: list[U9SaveMember] = []
        seen_maps: set[int] = set()
        while True:
            map_number = read_i32("nonfixed map number")
            if map_number == -1:
                break
            if not 0 <= map_number <= MAX_MAP_NUMBER:
                raise U9SaveError(f"invalid nonfixed map number {map_number}")
            if map_number in seen_maps:
                raise U9SaveError(f"duplicate nonfixed map number {map_number}")
            seen_maps.add(map_number)
            name = f"nonfixed.{map_number}"
            raw, offset = read_bytes(read_i32(f"{name} length"), name)
            nonfixed.append(U9SaveMember(name, raw, offset, map_number))
        if cursor != len(data):
            raise U9SaveError(f"{len(data) - cursor} trailing bytes after map terminator")
        return cls(header, screenshot, processes, diary, tuple(nonfixed))

    def member(self, name: str) -> U9SaveMember | None:
        """Return one archived working-file member by case-insensitive name."""
        lowered = name.casefold()
        if lowered == "processes.dat":
            return self.processes
        if lowered == "diary.txt":
            return self.diary
        return next((member for member in self.nonfixed if member.name == lowered), None)