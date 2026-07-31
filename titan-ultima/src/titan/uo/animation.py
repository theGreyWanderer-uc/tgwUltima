"""Ultima Online legacy body animation support."""

from __future__ import annotations

__all__ = [
    "UOAnimationDecoder",
    "UOAnimationFrame",
    "UOAnimationNaming",
    "UOAnimationSlot",
    "animation_naming",
    "legacy_animation_slot",
    "load_mobtype_flags",
    "load_mobtypes",
]

from dataclasses import dataclass
from pathlib import Path
import re
import struct
from typing import Sequence

from PIL import Image

from titan.uo.art import color16_to_rgba
from titan.uo.indexed import UOIndexEntry

_SENTINEL = 0x7FFF7FFF
_MAX_FRAMES = 256
_MAX_DIMENSION = 1024
_HIGH_ACTIONS = (
    "walk",
    "stand",
    "die1",
    "die2",
    "attack1",
    "attack2",
    "attack3",
    "misc1",
    "misc2",
    "misc3",
    "stumble",
    "slap_ground",
    "cast",
    "get_hit1",
    "misc4",
    "get_hit2",
    "get_hit3",
    "fidget1",
    "fidget2",
    "fly",
    "land",
    "die_in_flight",
)
_LOW_ACTIONS = (
    "walk",
    "run",
    "stand",
    "eat",
    "unknown",
    "attack1",
    "attack2",
    "attack3",
    "die1",
    "fidget1",
    "fidget2",
    "lie_down",
    "die2",
)
_PEOPLE_ACTIONS = (
    "walk_unarmed",
    "walk_armed",
    "run_unarmed",
    "run_armed",
    "stand",
    "fidget1",
    "fidget2",
    "stand_onehanded_attack",
    "stand_twohanded_attack",
    "attack_onehanded",
    "attack_unarmed1",
    "attack_unarmed2",
    "attack_twohanded_down",
    "attack_twohanded_wide",
    "attack_twohanded_jab",
    "walk_warmode",
    "cast_directed",
    "cast_area",
    "attack_bow",
    "attack_crossbow",
    "get_hit",
    "die1",
    "die2",
    "onmount_ride_slow",
    "onmount_ride_fast",
    "onmount_stand",
    "onmount_attack",
    "onmount_attack_bow",
    "onmount_attack_crossbow",
    "onmount_slap_horse",
    "turn",
    "attack_unarmed_and_walk",
    "emote_bow",
    "emote_salute",
    "fidget3",
)
_DIRECTION_LABELS = {
    0: "world_03",
    1: "world_02m_04",
    2: "world_01m_05",
    3: "world_00m_06",
    4: "world_07",
}
_TYPE_TO_CATEGORY = {
    "MONSTER": "high",
    "SEA_MONSTER": "high",
    "ANIMAL": "low",
    "HUMAN": "people",
    "EQUIPMENT": "people",
}
_TYPE_TO_KIND = {
    "MONSTER": "monster",
    "SEA_MONSTER": "sea_monster",
    "ANIMAL": "animal",
    "HUMAN": "human",
    "EQUIPMENT": "equipment",
}
_CATEGORY_TO_KIND = {
    "high": "monster",
    "low": "animal",
    "people": "people",
}


@dataclass(frozen=True)
class UOAnimationSlot:
    """Decoded logical position for a legacy animation IDX record."""

    body: int
    action: int
    direction: int
    stride: int
    group: str


@dataclass(frozen=True)
class UOAnimationNaming:
    """Semantic labels and path parts for a legacy animation slot."""

    kind: str
    category: str
    category_source: str
    action_name: str
    direction_name: str
    body_dir: str
    action_dir: str
    direction_dir: str


@dataclass(frozen=True)
class UOAnimationFrame:
    """One decoded legacy animation frame."""

    index: int
    center_x: int
    center_y: int
    width: int
    height: int
    image: Image.Image


def _signed_10(value: int) -> int:
    value &= 0x3FF
    if value & 0x200:
        return value | ~0x3FF
    return value


class UOAnimationDecoder:
    """Decode legacy anim*.mul payloads into frame images."""

    @staticmethod
    def decode(entry: UOIndexEntry) -> list[UOAnimationFrame]:
        data = entry.data
        if len(data) < 516:
            return []

        palette = [struct.unpack_from("<H", data, idx * 2)[0] for idx in range(256)]
        frame_count = struct.unpack_from("<I", data, 512)[0]
        if frame_count <= 0 or frame_count > _MAX_FRAMES:
            return []

        table_start = 516
        table_end = table_start + frame_count * 4
        if table_end > len(data):
            return []

        offsets = [
            struct.unpack_from("<I", data, table_start + idx * 4)[0]
            for idx in range(frame_count)
        ]
        frames: list[UOAnimationFrame] = []

        for frame_index, frame_offset in enumerate(offsets):
            pos = 512 + frame_offset
            if pos + 8 > len(data):
                continue

            center_x, center_y, width, height = struct.unpack_from("<hhhh", data, pos)
            pos += 8
            if (
                width <= 0
                or height <= 0
                or width > _MAX_DIMENSION
                or height > _MAX_DIMENSION
            ):
                continue

            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            guard = 0
            while pos + 4 <= len(data):
                header = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                if header == _SENTINEL:
                    break

                run_length = header & 0x0FFF
                x = _signed_10(header >> 22) + center_x
                y = _signed_10(header >> 12) + center_y + height
                guard += 1

                if run_length <= 0 or run_length > width or guard > width * height:
                    break
                if pos + run_length > len(data):
                    break

                for pixel_index in range(run_length):
                    px = x + pixel_index
                    palette_index = data[pos]
                    pos += 1
                    if 0 <= px < width and 0 <= y < height:
                        image.putpixel((px, y), color16_to_rgba(palette[palette_index]))

            frames.append(
                UOAnimationFrame(
                    frame_index,
                    center_x,
                    center_y,
                    width,
                    height,
                    image,
                )
            )

        return frames


def legacy_animation_slot(entry_index: int, set_name: str) -> UOAnimationSlot:
    """Infer legacy body/action/direction from an anim*.idx entry number.

    This mirrors the legacy index formula used by UOFiddler/ClassicUO:
    base index plus action * 5 plus stored direction 0..4.
    """
    file_type = 1 if set_name == "anim" else int(set_name.removeprefix("anim"))

    if file_type == 3:
        if entry_index < 300 * 65:
            return _slot_from_base(entry_index, body_base=0, index_base=0, stride=65)
        if entry_index < 35000:
            return _slot_from_base(
                entry_index, body_base=300, index_base=33000, stride=110
            )
        return _slot_from_base(entry_index, body_base=400, index_base=35000, stride=175)

    if entry_index < 22000:
        return _slot_from_base(entry_index, body_base=0, index_base=0, stride=110)
    if entry_index < 35000:
        return _slot_from_base(entry_index, body_base=200, index_base=22000, stride=65)
    return _slot_from_base(entry_index, body_base=400, index_base=35000, stride=175)


def _slot_from_base(
    entry_index: int,
    *,
    body_base: int,
    index_base: int,
    stride: int,
) -> UOAnimationSlot:
    relative = entry_index - index_base
    body = body_base + (relative // stride)
    remainder = relative % stride
    action = remainder // 5
    direction = remainder % 5

    if stride == 65:
        group = "low"
    elif stride == 110:
        group = "high"
    else:
        group = "people"

    return UOAnimationSlot(body, action, direction, stride, group)


def load_mobtypes(path: str | Path) -> dict[int, tuple[str, str]]:
    """Load body categories from mobtypes.txt."""
    source = Path(path)
    if not source.is_file():
        return {}

    categories: dict[int, tuple[str, str]] = {}
    for raw_line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line[0].isdigit():
            continue

        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            body = int(parts[0], 10)
        except ValueError:
            continue

        raw_type = parts[1].upper()
        category = _TYPE_TO_CATEGORY.get(raw_type)
        kind = _TYPE_TO_KIND.get(raw_type)
        if category is not None and kind is not None:
            categories[body] = (kind, category)

    return categories


def load_mobtype_flags(path: str | Path) -> dict[int, int]:
    """Load raw body flags from mobtypes.txt."""
    source = Path(path)
    if not source.is_file():
        return {}

    flags_by_body: dict[int, int] = {}
    for raw_line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line[0].isdigit():
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            body = int(parts[0], 10)
            flags = int(parts[2], 16)
        except ValueError:
            continue
        flags_by_body[body] = flags
    return flags_by_body


def animation_naming(
    slot: UOAnimationSlot,
    *,
    set_name: str,
    mobtypes: dict[int, tuple[str, str]],
) -> UOAnimationNaming:
    """Return best-known semantic labels for an animation slot."""
    if set_name == "anim" and slot.body in mobtypes:
        kind, category = mobtypes[slot.body]
        category_source = "mobtypes.txt"
    else:
        category = slot.group
        kind = _CATEGORY_TO_KIND.get(category, category)
        category_source = "physical_range"

    action_name = _action_name(category, slot.action)
    direction_name = _DIRECTION_LABELS.get(
        slot.direction, f"stored_{slot.direction:02d}"
    )

    return UOAnimationNaming(
        kind=kind,
        category=category,
        category_source=category_source,
        action_name=action_name,
        direction_name=direction_name,
        body_dir=f"body_{slot.body:04d}_{_safe_part(category)}",
        action_dir=f"action_{slot.action:02d}_{_safe_part(action_name)}",
        direction_dir=f"direction_{slot.direction:02d}_{_safe_part(direction_name)}",
    )


def _action_name(category: str, action: int) -> str:
    actions: Sequence[str]
    if category == "low":
        actions = _LOW_ACTIONS
    elif category == "people":
        actions = _PEOPLE_ACTIONS
    else:
        actions = _HIGH_ACTIONS

    if 0 <= action < len(actions):
        return actions[action]
    return "unknown"


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "unknown"
