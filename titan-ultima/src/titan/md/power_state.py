"""Restore MD power-dependent map art using the DOS post-load rules.

Animation ranges use retail BASETILE boundary pairs (188, 189), (191, 192),
(432, 433) and (435, 436), with exclusive upper bounds. Object adjustments follow
GAME.EXE 2238:0a85–0c02, not the broader live activation handler.
See reference/md/animation/md_power_animation_reference.md for executable
checks and save normalization details.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from titan.u6.object import U6Object

__all__ = ["is_martian_power_tile", "restore_martian_power_objects"]

_POWER_TILE_RANGES = ((848, 851), (854, 858), (1980, 1984), (1992, 1994))


def is_martian_power_tile(tile: int) -> bool:
    """Identify tiles stopped by the retail MD power flag, using exclusive range ends."""
    return any(start <= tile < end for start, end in _POWER_TILE_RANGES)


def restore_martian_power_objects(
    objects: Iterable[U6Object], power_active: bool
) -> list[U6Object]:
    """Restore saved lamp/furnace frames and steam leaks without mutating source records."""
    source = list(objects)
    steam_positions = {
        (obj.x, obj.y, obj.z) for obj in source if obj.is_on_map and obj.obj_n == 209
    }
    restored: list[U6Object] = []
    created: list[U6Object] = []
    for obj in source:
        if not obj.is_on_map:
            restored.append(obj)
            continue
        if not power_active and obj.obj_n == 209:
            continue
        frame = obj.frame_n
        if power_active:
            if obj.obj_n == 154:
                frame = 1
            elif obj.obj_n == 233 and frame in (1, 3):
                frame += 4
            elif obj.obj_n == 208:
                mask = 1023 if obj.z == 0 else 255
                position = (obj.x & mask, (obj.y + 1) & mask, obj.z)
                if position not in steam_positions:
                    created.append(U6Object(0, *position, 209, 1, 0, 0))
                    steam_positions.add(position)
        elif obj.obj_n in (154, 233) and frame in (5, 7):
            frame -= 4
        restored.append(replace(obj, frame_n=frame) if frame != obj.frame_n else obj)
    return restored + created
