"""Bounded schedule framing shared by loose/save readers and NPC inspection."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class U7ScheduleLayout:
    """Keep cumulative counts, script names and partial/trailing evidence without inventing entries."""

    raw: bytes
    format: str = "u7"
    num_npcs: int = 0
    entry_width: int = 4
    offsets: tuple[int, ...] = ()
    script_names_raw: tuple[bytes, ...] = ()
    records: dict[int, list[bytes]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    complete: bool = True
    parsed_bytes: int = 0
    trailing_data: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes, *, strict: bool = False) -> U7ScheduleLayout:
        result = cls(data)

        def incomplete(message: str) -> U7ScheduleLayout:
            if strict:
                raise ValueError(f"schedule.dat {message}")
            result.complete = False
            result.warnings.append(f"schedule.dat {message}")
            return result

        if len(data) < 4:
            return incomplete("header is incomplete")
        marker = struct.unpack_from("<i", data)[0]
        if marker < -2:
            raise ValueError(f"Unsupported schedule.dat marker {marker}")
        result.format = "exult2" if marker == -2 else "exult" if marker == -1 else "u7"
        pos = 10 if marker == -2 else 8 if marker == -1 else 4
        result.entry_width = 8 if marker < 0 else 4
        if len(data) < pos:
            return incomplete("extended header is incomplete")
        result.num_npcs = struct.unpack_from("<I", data, 4)[0] if marker < 0 else marker
        num_scripts = struct.unpack_from("<H", data, 8)[0] if marker == -2 else 0
        if result.num_npcs > (len(data) - pos) // 2:
            return incomplete("offset table is incomplete")
        offsets = (
            struct.unpack_from(f"<{result.num_npcs}H", data, pos)
            if result.num_npcs
            else ()
        )
        result.offsets = offsets
        if offsets and offsets[0] != 0:
            raise ValueError("Avatar schedule sentinel must be zero")
        if any(a > b for a, b in zip(offsets, offsets[1:])):
            raise ValueError("schedule.dat offsets are not cumulative")
        pos += result.num_npcs * 2
        if num_scripts:
            if pos + 2 > len(data):
                return incomplete("script-name size is incomplete")
            size = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            end = pos + size
            if end > len(data):
                return incomplete("script-name block is incomplete")
            names = []
            for _ in range(num_scripts):
                if pos + 2 > end:
                    return incomplete("script-name length exceeds its block")
                length = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                if pos + length > end:
                    return incomplete("script-name bytes exceed their block")
                names.append(data[pos : pos + length])
                pos += length
            if pos != end:
                return incomplete("script-name block size does not match its names")
            result.script_names_raw = tuple(names)
        previous = 0
        for npc, count in enumerate(offsets):
            for _ in range(count - previous):
                if pos + result.entry_width > len(data):
                    result.parsed_bytes = pos
                    return incomplete("entries are incomplete")
                result.records.setdefault(npc, []).append(
                    data[pos : pos + result.entry_width]
                )
                pos += result.entry_width
            previous = count
        result.parsed_bytes = pos
        result.trailing_data = data[pos:]
        if result.trailing_data:
            result.warnings.append(
                f"schedule.dat has {len(result.trailing_data)} trailing bytes."
            )
        return result
