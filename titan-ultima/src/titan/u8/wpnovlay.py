"""Read U8 WPNOVLAY.DAT weapon sprite offsets using ANIM.DAT sequence lengths.

References: Pentagram graphics/WpnOvlayDat.cpp, docs/u8wpnovlay.txt and the
decoded U8 WPNCACHE.C/H and DLITEM.C. Flex record IDs are avatar action IDs.
Payloads have no headers: overlay type, direction, then animation step.
All overlay types are retained, including glow and unassigned slots.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from titan.flex import (
    FLEX_COUNT_OFFSET,
    FLEX_HEADER_SIZE,
    FLEX_RECORD_ENTRY_SIZE,
    FLEX_TABLE_OFFSET,
    FlexArchive,
)
from titan.u8.anim import ACTION_COUNT, DIRECTION_NAMES, U8AnimAction, U8AnimData

__all__ = [
    "U8WeaponOverlayData",
    "U8WeaponOverlayAction",
    "U8WeaponOverlayType",
    "U8WeaponOverlayFrame",
    "U8WeaponOverlayError",
]

OVERLAY_FRAME_SIZE = 4
# Executable mappings from WPNCACHE.C; these are not stored in WPNOVLAY.DAT.
OVERLAY_NAMES = {
    0: "mace",
    1: "sword",
    2: "axe",
    3: "dagger",
    4: "earth_glow",
    5: "air_glow",
    6: "fire_glow",
}
OVERLAY_SHAPES = {0: 241, 1: 243, 2: 244, 3: 245, 4: 398, 5: 399, 6: 400}
WEAPON_OVERLAY_TYPES = {
    0x1A1: 0,
    0x1A2: 3,
    0x1A3: 2,
    0x1A4: 1,
    0x21C: 0,
    0x21D: 1,
    0x21E: 1,
    0x32F: 0,
    0x330: 0,
    0x331: 1,
    0x332: 1,
    0x333: 1,
    0x334: 3,
    0x335: 1,
    0x336: 2,
}


class U8WeaponOverlayError(ValueError):
    """Weapon overlay data or its pairing with avatar ANIM.DAT is invalid."""


@dataclass(frozen=True)
class U8WeaponOverlayFrame:
    """A four-byte weapon frame with signed screen-pixel X/Y draw offsets."""

    raw: bytes
    x_offset: int
    y_offset: int
    frame: int


@dataclass(frozen=True)
class U8WeaponOverlayType:
    """One overlay slot with eight directional sequences; IDs are never compacted."""

    type_num: int
    directions: tuple[tuple[U8WeaponOverlayFrame, ...], ...]

    @property
    def name(self) -> str:
        return OVERLAY_NAMES.get(self.type_num, f"overlay_{self.type_num}")

    @property
    def shape_num(self) -> int | None:
        """Executable sprite mapping, or None for an unassigned overlay slot."""
        return OVERLAY_SHAPES.get(self.type_num)


@dataclass(frozen=True)
class U8WeaponOverlayAction:
    """Weapon overlays joined to the corresponding avatar animation (shape 1)."""

    action_num: int
    offset: int
    raw: bytes
    avatar_animation: U8AnimAction
    overlays: tuple[U8WeaponOverlayType, ...]

    @property
    def name(self) -> str:
        return self.avatar_animation.name

    @property
    def frame_count(self) -> int:
        """Steps per direction, supplied by ANIM.DAT rather than overlay bytes."""
        return self.avatar_animation.frame_count


class U8WeaponOverlayData:
    """Validated weapon overlays; preserve the original Flex file byte-for-byte."""

    def __init__(
        self,
        data: bytes,
        record_entries: tuple[tuple[int, int], ...],
        actions: dict[int, U8WeaponOverlayAction],
    ) -> None:
        self._data = data
        self.record_entries = record_entries
        self.actions = actions

    @classmethod
    def from_file(
        cls, filepath: str | Path, animations: U8AnimData
    ) -> U8WeaponOverlayData:
        """Read WPNOVLAY.DAT paired with already-parsed avatar animation data."""
        return cls.from_bytes(Path(filepath).read_bytes(), animations)

    @classmethod
    def from_bytes(cls, data: bytes, animations: U8AnimData) -> U8WeaponOverlayData:
        """Validate Flex bounds and exact type/direction/step payload divisions."""
        if len(data) < FLEX_HEADER_SIZE:
            raise U8WeaponOverlayError("WPNOVLAY.DAT: truncated Flex header")
        count = struct.unpack_from("<I", data, FLEX_COUNT_OFFSET)[0]
        if count > ACTION_COUNT:
            raise U8WeaponOverlayError("WPNOVLAY.DAT: more than 64 action slots")
        table_end = FLEX_TABLE_OFFSET + count * FLEX_RECORD_ENTRY_SIZE
        if table_end > len(data):
            raise U8WeaponOverlayError("WPNOVLAY.DAT: truncated Flex record table")
        entries = tuple(
            struct.unpack_from(
                "<II", data, FLEX_TABLE_OFFSET + i * FLEX_RECORD_ENTRY_SIZE
            )
            for i in range(count)
        )
        for action, (offset, size) in enumerate(entries):
            if size and (offset < table_end or offset + size > len(data)):
                raise U8WeaponOverlayError(
                    f"WPNOVLAY.DAT: action {action} record bounds are invalid"
                )
        # Reuse Titan's Flex header/container reader after checking its byte-read bounds.
        try:
            archive = FlexArchive.from_bytes(data)
        except ValueError as error:
            raise U8WeaponOverlayError(f"WPNOVLAY.DAT: {error}") from error

        actions: dict[int, U8WeaponOverlayAction] = {}
        for action, record in enumerate(archive.records):
            if not record:
                continue
            animation = animations.get_action(1, action)
            if animation is None:
                raise U8WeaponOverlayError(
                    f"WPNOVLAY.DAT: action {action} has no avatar animation in ANIM.DAT"
                )
            block_size = (
                animation.frame_count * len(DIRECTION_NAMES) * OVERLAY_FRAME_SIZE
            )
            type_count, remainder = divmod(len(record), block_size)
            if remainder:
                raise U8WeaponOverlayError(
                    f"WPNOVLAY.DAT: action {action} payload size {len(record)} "
                    f"is not a multiple of its {block_size}-byte overlay block"
                )
            overlays = []
            for overlay_type in range(type_count):
                directions = []
                for direction in range(len(DIRECTION_NAMES)):
                    nodes = []
                    for step in range(animation.frame_count):
                        offset = (
                            (overlay_type * len(DIRECTION_NAMES) + direction)
                            * animation.frame_count
                            + step
                        ) * OVERLAY_FRAME_SIZE
                        raw = record[offset : offset + OVERLAY_FRAME_SIZE]
                        x, y, frame = struct.unpack("<bbH", raw)
                        nodes.append(U8WeaponOverlayFrame(raw, x, y, frame))
                    directions.append(tuple(nodes))
                overlays.append(U8WeaponOverlayType(overlay_type, tuple(directions)))
            actions[action] = U8WeaponOverlayAction(
                action, entries[action][0], record, animation, tuple(overlays)
            )
        return cls(data, entries, actions)

    def get_action(self, action: int) -> U8WeaponOverlayAction | None:
        """Return a populated action or None; reject IDs outside native U8's table."""
        if not 0 <= action < ACTION_COUNT:
            raise U8WeaponOverlayError("WPNOVLAY.DAT: action must be 0-63")
        return self.actions.get(action)

    def get_frame(
        self,
        action: int,
        overlay_type: int,
        direction: int,
        step: int,
    ) -> U8WeaponOverlayFrame | None:
        """Look up an overlay frame; missing actions/types/steps return None."""
        if overlay_type < 0 or step < 0 or not 0 <= direction < len(DIRECTION_NAMES):
            raise U8WeaponOverlayError(
                "WPNOVLAY.DAT: type/step must be nonnegative and direction must be 0-7"
            )
        entry = self.get_action(action)
        if (
            entry is None
            or overlay_type >= len(entry.overlays)
            or step >= entry.frame_count
        ):
            return None
        return entry.overlays[overlay_type].directions[direction][step]

    def iter_actions(self) -> Iterator[U8WeaponOverlayAction]:
        """Yield populated overlay actions in their original Flex slot order."""
        return iter(self.actions.values())

    def to_bytes(self) -> bytes:
        """Return the exact original file, including empty slots and unused bytes."""
        return self._data
