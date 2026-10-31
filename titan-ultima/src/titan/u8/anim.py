"""Read U8 ANIM.DAT actor actions, eight directions and packed frame nodes.

Layout references: Pentagram graphics/AnimDat.cpp and the decoded U8 source
U8/ANIMFILE.C, AHEADER.H, ASTREAM.H, ANODE.H and ANIMCACH.H. ANIM contains
runtime sprite choreography, not models or pixel data. The decoded source
defines a signed nine-bit deltaDir and a four-bit repeat; keep these widths
even though the retail data also fits Pentagram's simpler byte decoding.
Unknown header/frame fields and unreferenced file bytes remain available.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

__all__ = ["U8AnimData", "U8AnimAction", "U8AnimFrame", "U8AnimError"]

SHAPE_COUNT = 2048
ACTION_COUNT = 64
DIRECTION_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
SHAPE_TABLE_SIZE = SHAPE_COUNT * 4
ACTION_TABLE_SIZE = ACTION_COUNT * 4
FRAME_SIZE = 6

# Names from ANIMCACH.H; unlabelled actions retain their numeric identities.
ACTION_NAMES = {
    0: "walk",
    1: "run",
    2: "stand",
    3: "jump_up",
    4: "stand_up",
    5: "draw_weapon",
    6: "sheath_weapon",
    7: "attack",
    8: "advance",
    9: "retreat",
    10: "running_leap",
    11: "shake_head",
    12: "step",
    13: "stumble_back",
    14: "die",
    15: "combat_stand",
    16: "land",
    17: "jump",
    18: "airwalk_jump",
    19: "climb16",
    20: "climb24",
    21: "climb32",
    22: "climb40",
    23: "climb48",
    24: "climb56",
    25: "climb64",
    26: "climb72",
    27: "cast1",
    28: "cast2",
    29: "cast3",
    30: "cast4",
    31: "cast5",
    32: "look_left",
    33: "look_right",
    34: "kneel_down",
    35: "kneel",
    42: "edge_balance",
    44: "fall_back",
    45: "hang",
    46: "climb_up",
    47: "fidget1",
    48: "fidget2",
    49: "kneel2",
    50: "kneel_up",
    51: "sit_down",
    52: "sit_up",
    53: "talk",
    55: "work",
    56: "drown",
    57: "burn",
    58: "kick",
    59: "block_start",
    60: "block_end",
}
ACTION_FLAG_NAMES = {
    0x01: "two_step",
    0x02: "attack",
    0x04: "looping",
    0x08: "unstoppable",
    0x10: "looping2",
    # ANIMPRIM.C failFunction(): collision takes the receiveHit() path.
    0x20: "hit_on_collision",
    # ANIMPRIM.C pop(): restart lastAnim unless standAfter was cleared.
    0x40: "repeat_after_completion",
    0x80: "hanging",
    0x8000: "destroy_actor",
}


class U8AnimError(ValueError):
    """ANIM.DAT has an invalid offset table or truncated animation payload."""


@dataclass(frozen=True)
class U8AnimFrame:
    """One six-byte sprite frame node; delta_dir is in four-world-unit steps."""

    raw: bytes
    frame: int
    special: bool
    flags_hi: int
    delta_z: int
    sfx: int
    delta_dir: int
    on_ground: bool
    attack_range: int
    flipped: bool
    call_usecode: bool
    unknown_flag80: bool

    @property
    def movement_world_units(self) -> int:
        """Signed distance along the selected direction before collision handling."""
        return self.delta_dir * 4


@dataclass(frozen=True)
class U8AnimAction:
    """An actor action with direction-major frames; repeat has no assumed ms unit."""

    shape_num: int
    action_num: int
    offset: int
    raw_header: bytes
    directions: tuple[tuple[U8AnimFrame, ...], ...]

    @property
    def name(self) -> str:
        return ACTION_NAMES.get(self.action_num, f"action_{self.action_num}")

    @property
    def frame_count(self) -> int:
        return self.raw_header[0]

    @property
    def repeat(self) -> int:
        return self.raw_header[2] & 0x0F

    @property
    def flags(self) -> int:
        """Header flag bytes in Pentagram's numbering, including unknown high bits."""
        return self.raw_header[1] | (self.raw_header[3] << 8)

    @property
    def unknown_4(self) -> int:
        """ASTREAM.H unk4: six bits following the repeat nibble."""
        return (int.from_bytes(self.raw_header, "little") >> 20) & 0x3F

    @property
    def unknown_10(self) -> int:
        """ASTREAM.H unk10: five bits preceding destroyActor."""
        return (self.raw_header[3] >> 2) & 0x1F

    def flag_names(self) -> list[str]:
        """Named action flags; raw_header retains every unnamed bit."""
        return [name for bit, name in ACTION_FLAG_NAMES.items() if self.flags & bit]


def _anim_frame(data: bytes, offset: int) -> U8AnimFrame:
    raw = data[offset : offset + FRAME_SIZE]
    sprite, movement = (
        struct.unpack_from("<H", raw)[0],
        int.from_bytes(raw[4:], "little"),
    )
    delta_dir = movement & 0x1FF
    if delta_dir & 0x100:
        delta_dir -= 0x200
    return U8AnimFrame(
        raw=raw,
        frame=sprite & 0x7FF,
        special=bool(sprite & 0x800),
        flags_hi=sprite >> 12,
        delta_z=raw[2] - 256 if raw[2] >= 128 else raw[2],
        sfx=raw[3],
        delta_dir=delta_dir,
        on_ground=bool(movement & 0x200),
        attack_range=(movement >> 10) & 7,
        flipped=bool(movement & 0x2000),
        call_usecode=bool(movement & 0x4000),
        unknown_flag80=bool(movement & 0x8000),
    )


class U8AnimData:
    """Validated ANIM.DAT with stable shape/action IDs and exact original bytes."""

    def __init__(
        self,
        data: bytes,
        shape_offsets: tuple[int, ...],
        action_offsets: dict[int, tuple[int, ...]],
        actions: dict[tuple[int, int], U8AnimAction],
    ) -> None:
        self._data = data
        self.shape_offsets = shape_offsets
        self.action_offsets = action_offsets
        self.actions = actions

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8AnimData:
        """Read and validate a native U8 ANIM.DAT, without changing its source."""
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> U8AnimData:
        """Reject bad offsets/truncation; allow shared tables, actions and dead space."""
        if len(data) < SHAPE_TABLE_SIZE:
            raise U8AnimError("ANIM.DAT: truncated 2048-entry shape offset table")
        shape_offsets = struct.unpack_from(f"<{SHAPE_COUNT}I", data)
        action_offsets: dict[int, tuple[int, ...]] = {}
        table_ranges: list[tuple[int, int]] = []
        for shape, offset in enumerate(shape_offsets):
            if not offset:
                continue
            if offset < SHAPE_TABLE_SIZE or offset + ACTION_TABLE_SIZE > len(data):
                raise U8AnimError(
                    f"ANIM.DAT: shape {shape} action table offset {offset:#x} is out of bounds"
                )
            action_offsets[shape] = struct.unpack_from(
                f"<{ACTION_COUNT}I", data, offset
            )
            table_ranges.append((offset, offset + ACTION_TABLE_SIZE))
        table_ranges = sorted(set(table_ranges))
        for previous, current in zip(table_ranges, table_ranges[1:]):
            if current[0] < previous[1]:
                raise U8AnimError("ANIM.DAT: overlapping shape action tables")

        actions: dict[tuple[int, int], U8AnimAction] = {}
        cache: dict[int, tuple[bytes, tuple[tuple[U8AnimFrame, ...], ...]]] = {}
        for shape, offsets in action_offsets.items():
            for action, offset in enumerate(offsets):
                if not offset:
                    continue
                context = f"ANIM.DAT: shape {shape} action {action} at {offset:#x}"
                if offset < SHAPE_TABLE_SIZE or offset + 4 > len(data):
                    raise U8AnimError(f"{context}: action header is out of bounds")
                if offset not in cache:
                    header = data[offset : offset + 4]
                    count = header[0]
                    end = offset + 4 + count * len(DIRECTION_NAMES) * FRAME_SIZE
                    if end > len(data):
                        raise U8AnimError(
                            f"{context}: truncated eight-direction frame data"
                        )
                    if any(offset < high and end > low for low, high in table_ranges):
                        raise U8AnimError(
                            f"{context}: action payload overlaps an offset table"
                        )
                    # The original allocator rejects a populated stream with zero frames.
                    if not count:
                        raise U8AnimError(
                            f"{context}: populated action has zero frames"
                        )
                    directions = tuple(
                        tuple(
                            _anim_frame(
                                data,
                                offset + 4 + (direction * count + step) * FRAME_SIZE,
                            )
                            for step in range(count)
                        )
                        for direction in range(len(DIRECTION_NAMES))
                    )
                    cache[offset] = header, directions
                header, directions = cache[offset]
                actions[shape, action] = U8AnimAction(
                    shape, action, offset, header, directions
                )
        return cls(data, shape_offsets, action_offsets, actions)

    def get_action(self, shape: int, action: int) -> U8AnimAction | None:
        """Return an action or None for an empty slot; reject IDs outside U8 tables."""
        if not 0 <= shape < SHAPE_COUNT or not 0 <= action < ACTION_COUNT:
            raise U8AnimError("ANIM.DAT: shape must be 0-2047 and action must be 0-63")
        return self.actions.get((shape, action))

    def iter_actions(self) -> Iterator[U8AnimAction]:
        """Yield populated actions in shape/action table order."""
        return iter(self.actions.values())

    def to_bytes(self) -> bytes:
        """Return the original file, including unknown bits, aliases and dead space."""
        return self._data
