"""Native GUMPS.DAT container UI state; BarkGump::save writes no bytes."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from titan.u8.state_io import read_u8_state_bytes


@dataclass(frozen=True)
class U8ContainerGump:
    """One 66-byte saved container gump; the referent is a reusable cache item ID."""

    index: int
    file_offset: int
    raw_data: bytes
    gump_type_raw: int
    container_id: int
    rect: tuple[int, int, int, int]
    drag_offset: tuple[int, int]
    drag_start: tuple[int, int]
    world_location: tuple[int, int, int]
    shape: int
    frame: int


@dataclass(frozen=True)
class U8GumpState:
    """Container gumps, all 16 saved screen rectangles and the independent counter."""

    raw_data: bytes
    containers: tuple[U8ContainerGump, ...]
    rects: tuple[tuple[int, int, int, int], ...]
    gump_count: int

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8GumpState:
        """Read loose GUMPS.DAT or its entry in a native U8 save archive."""
        return cls.from_bytes(read_u8_state_bytes(filepath, "GUMPS.DAT"))

    @classmethod
    def from_bytes(cls, data: bytes) -> U8GumpState:
        """Validate labels, sentinel and exact footer; preserve marker padding bytes."""
        if len(data) < 196:
            raise ValueError("GUMPS.DAT: truncated container state")
        if data[:32].split(b"\x00", 1)[0] != b"CONTAINER GUMPS START HERE":
            raise ValueError("GUMPS.DAT: invalid container notice")
        position = 32
        containers: list[U8ContainerGump] = []
        while True:
            if position + 2 > len(data):
                raise ValueError("GUMPS.DAT: missing container sentinel")
            gump_type = struct.unpack_from("<H", data, position)[0]
            if gump_type == 0xFFFF:
                position += 2
                break
            if position + 66 > len(data):
                raise ValueError("GUMPS.DAT: truncated container record")
            raw = data[position : position + 66]
            if raw[2:18].split(b"\x00", 1)[0] != b"CONTAINER GUMP" or (
                raw[18:22] != b"REF="
                or raw[24:29] != b"RECT="
                or raw[50:56] != b"SHAPE="
                or raw[58:64] != b"FRAME="
            ):
                raise ValueError("GUMPS.DAT: invalid container record labels")
            containers.append(
                U8ContainerGump(
                    len(containers),
                    position,
                    raw,
                    gump_type,
                    struct.unpack_from("<H", raw, 22)[0],
                    struct.unpack_from("<4h", raw, 29),
                    struct.unpack_from("<2h", raw, 37),
                    struct.unpack_from("<2h", raw, 41),
                    struct.unpack_from("<HHB", raw, 45),
                    struct.unpack_from("<h", raw, 56)[0],
                    struct.unpack_from("<h", raw, 64)[0],
                )
            )
            position += 66
        if position + 162 != len(data):
            raise ValueError("GUMPS.DAT: truncated footer or unexpected trailing bytes")
        if data[position : position + 16].split(b"\x00", 1)[
            0
        ] != b"CONTAINER RECTS" or (
            data[position + 144 : position + 160].split(b"\x00", 1)[0]
            != b"GUMP COUNTER"
        ):
            raise ValueError("GUMPS.DAT: invalid footer labels")
        rects = tuple(
            struct.unpack_from("<4h", data, position + 16 + index * 8)
            for index in range(16)
        )
        count = struct.unpack_from("<h", data, position + 160)[0]
        return cls(bytes(data), tuple(containers), rects, count)

    def diagnostics(self) -> list[str]:
        """Flag unusual UI counters/types without changing retained stored values."""
        issues = []
        if not 0 <= self.gump_count <= 16:
            issues.append("stored gump counter is outside 0-16")
        if self.gump_count != len(self.containers):
            issues.append("stored gump counter differs from serialized container count")
        if any(gump.gump_type_raw != 0 for gump in self.containers):
            issues.append("serialized container type is not zero")
        return issues

    def to_bytes(self) -> bytes:
        """Return the exact saved UI state, including all rectangle and marker residue."""
        return self.raw_data
