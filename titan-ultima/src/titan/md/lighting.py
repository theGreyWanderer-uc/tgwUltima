"""MD snapshot lighting: original clock thresholds, flood fill and dither tiles.

Lighting is a view operation: use a bounded crop no larger than the DOS 11x11
viewport. Atlas exports remain full bright.
See reference/md/palette/md_lighting_palette_reference.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

from titan.md.gamestate import MartianGameState
from titan.u6.object import U6Object
from titan.u6.palette import U6Palette
from titan.u6.tile import U6Tiles
from titan.u6.tileflag import U6TileFlagEntry

__all__ = [
    "martian_light_strength",
    "restore_martian_lamp_posts",
    "martian_readied_light",
    "build_martian_lightmap",
    "build_martian_light_field",
    "MartianLightField",
    "apply_martian_lightmap",
]

# GAME.EXE initialized DS:0ea6. This is not a Euclidean-distance approximation.
_LIGHT_DISTANCE = (
    (0, 1, 2, 3, 4, 5, 6, 7),
    (1, 1, 2, 3, 4, 5, 6, 7),
    (2, 2, 3, 4, 5, 6, 6, 7),
    (3, 3, 4, 4, 5, 6, 7, 8),
    (4, 4, 5, 5, 6, 7, 7, 8),
    (5, 5, 6, 6, 7, 7, 8, 9),
    (6, 6, 6, 7, 7, 8, 8, 9),
    (7, 7, 7, 8, 8, 9, 9, 10),
)
_NEIGHBORS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))


@dataclass
class MartianLightField:
    """Local 40x40 DOS light/visibility context and the requested crop within it."""

    terrain: np.ndarray
    flags: np.ndarray
    brightness: np.ndarray
    crop: tuple[int, int, int, int]
    bypass_visibility: bool = False

    @property
    def levels(self) -> np.ndarray:
        """Return detached 0–4 light levels for the requested crop."""
        x, y, width, height = self.crop
        return self.brightness[y : y + height, x : x + width].copy()


def martian_light_strength(
    state: MartianGameState, level: int, held_light: int = 0
) -> int:
    """Compute the DOS view light strength, preserving saved dream illumination."""
    if state.in_dream_mode:
        return state.saved_light_level
    minute = state.clock.hour * 60 + state.clock.minute
    if level > 0 or minute < 400 or minute > 1080:
        strength = 0
    elif minute < 440:
        strength = (minute - 400) // 10 + 2
    elif minute > 1040:
        strength = (1080 - minute) // 10 + 2
    else:
        strength = 7
    # The original replaces, rather than maximizes, this value below strength 4.
    return held_light if strength < 4 and held_light else strength


def restore_martian_lamp_posts(
    objects: Iterable[U6Object], state: MartianGameState
) -> list[U6Object]:
    """Select lamp-post frame 7 at night with street-light power; otherwise use frame 3."""
    frame = 7 if state.street_lights_active and not 6 <= state.clock.hour <= 17 else 3
    return [
        replace(obj, frame_n=frame) if obj.is_on_map and obj.obj_n == 228 else obj
        for obj in objects
    ]


def martian_readied_light(
    inventory: Iterable[U6Object],
    tileflags: list[U6TileFlagEntry],
    basetile: tuple[int, ...],
) -> int:
    """Return the strongest readied torch/candle/lamp/lantern light, excluding carried items."""
    return max(
        (
            tileflags[obj.tile_num(basetile)].light_level
            for obj in inventory
            if obj.is_readied and obj.obj_n in (110, 112, 114, 116, 118)
        ),
        default=0,
    )


def _flood_martian_light(
    terrain: np.ndarray,
    flags: np.ndarray,
    brightness: np.ndarray,
    tileflags: list[U6TileFlagEntry],
    source: tuple[int, int],
    strength: int,
    view: tuple[int, int],
    *,
    viewer: bool,
) -> None:
    """Propagate original light/visibility around blockers and nearby cross-axis windows."""
    sx, sy = source
    vx, vy = view
    seen: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()

    def open_cell(x: int, y: int) -> bool:
        cell = int(flags[y, x])
        ground = tileflags[int(terrain[y, x])].flags
        if cell & 32:
            return False
        if ground & 8 or cell & 16:
            return (x == vx + 5 and abs(y - vy - 5) < 2) or (
                y == vy + 5 and abs(x - vx - 5) < 2
            )
        return bool(cell & 4) or not ground & 4

    def add(x: int, y: int, *, initial: bool = False) -> None:
        if (
            0 <= x < 40
            and 0 <= y < 40
            and (x, y) not in seen
            and (initial or not flags[y, x] & 64)
        ):
            seen.add((x, y))
            flags[y, x] |= 64
            queue.append((x, y))

    if open_cell(sx, sy):
        add(sx, sy, initial=True)
    else:
        if open_cell(sx + 1, sy):
            add(sx + 1, sy, initial=True)
        if open_cell(sx, sy + 1):
            add(sx, sy + 1, initial=True)
    while queue:
        x, y = queue.popleft()
        dx, dy = abs(x - sx), abs(y - sy)
        if dx >= 8 or dy >= 8:
            continue
        brightness[y, x] = max(
            int(brightness[y, x]),
            min(4, max(0, 4 + strength - _LIGHT_DISTANCE[dx][dy])),
        )
        if viewer:
            flags[y, x] |= 128
        if not open_cell(x, y):
            continue
        for ox, oy in _NEIGHBORS:
            nx, ny = x + ox, y + oy
            if viewer:
                if not -1 <= nx - vx <= 11 or not -1 <= ny - vy <= 11:
                    continue
            else:
                dx, dy = abs(nx - sx), abs(ny - sy)
                if dx >= 8 or dy >= 8 or _LIGHT_DISTANCE[dx][dy] > strength + 4:
                    continue
            add(nx, ny)


def build_martian_light_field(
    grid: np.ndarray,
    objects: Iterable[U6Object],
    tileflags: list[U6TileFlagEntry],
    basetile: tuple[int, ...],
    state: MartianGameState,
    region: tuple[int, int, int, int],
    level: int,
    held_light: int = 0,
) -> MartianLightField:
    """Build DOS illumination and retain the surrounding visibility needed for terrain edges."""
    x, y, width, height = region
    if not 1 <= width <= 11 or not 1 <= height <= 11:
        raise ValueError(
            "Martian Dreams lighting requires a crop no larger than 11x11 tiles"
        )
    cx, cy = x + width // 2, y + height // 2
    stride = grid.shape[0]
    # Object positions retain the original ten-bit domain underground too;
    # only terrain lookup wraps at the size of the stored level grid.
    bx, by = ((cx - 16) & 1023) & ~7, ((cy - 16) & 1023) & ~7
    local_x, local_y = (cx - bx) & 1023, (cy - by) & 1023
    view = (local_x - 5, local_y - 5)
    terrain = grid[np.ix_((np.arange(40) + by) % stride, (np.arange(40) + bx) % stride)]
    flags = np.zeros((40, 40), dtype=np.uint8)
    brightness = np.zeros((40, 40), dtype=np.uint8)
    crop = (local_x - width // 2, local_y - height // 2, width, height)
    if state.brown_berry_vision:
        # Original full-bright initialization uses flags 3, not the normal
        # visibility bit; the compositor still applies its wall-corner rules.
        flags.fill(3)
        brightness.fill(4)
        return MartianLightField(terrain, flags, brightness, crop, True)
    for obj in objects:
        if not obj.is_on_map or obj.z != level:
            continue
        ox, oy = (obj.x - bx) & 1023, (obj.y - by) & 1023
        if not 8 <= ox <= 31 or not 8 <= oy <= 31:
            continue
        tile = obj.tile_num(basetile)
        entry = tileflags[tile]
        if entry.is_window:
            flags[oy, ox] |= 16
        elif entry.is_opaque:
            flags[oy, ox] |= 32
        elif entry.extra & 32:
            flags[oy, ox] |= 4
        # Original footprint handling tests the preceding tile's opacity.
        if tile > 0 and tileflags[tile - 1].is_opaque:
            if entry.is_double_v:
                flags[oy - 1, ox] |= 32
            if entry.is_double_h:
                flags[oy, ox - 1] |= 32
        if entry.terrain & 4:
            flags[oy, ox] |= 8
            if entry.is_double_v:
                flags[oy - 1, ox] |= 8
            if entry.is_double_h:
                flags[oy, ox - 1] |= 8
        flags[oy, ox] = (int(flags[oy, ox]) & ~3) | max(
            int(flags[oy, ox]) & 3, entry.light_level
        )
    strength = martian_light_strength(state, level, held_light)
    if not 0 <= strength <= 7:
        raise ValueError(
            "Martian Dreams saved dream light level must be between 0 and 7"
        )
    _flood_martian_light(
        terrain,
        flags,
        brightness,
        tileflags,
        (local_x, local_y),
        strength,
        view,
        viewer=True,
    )
    if strength < 7:
        for sy in range(8, 32):
            for sx in range(8, 32):
                light = int(flags[sy, sx]) & 3
                if light and flags[sy, sx] & 128:
                    if (
                        tileflags[int(terrain[sy, sx])].terrain & 4
                        and not flags[sy + 1, sx] & 128
                    ):
                        continue
                    radius = light + 1
                    flags[
                        sy - radius : sy + radius + 1, sx - radius : sx + radius + 1
                    ] &= 191
                    _flood_martian_light(
                        terrain,
                        flags,
                        brightness,
                        tileflags,
                        (sx, sy),
                        light,
                        view,
                        viewer=False,
                    )
    # Unseen cells cannot become visible merely because another source illuminates them.
    brightness[flags & 128 == 0] = 0
    return MartianLightField(terrain, flags, brightness, crop)


def build_martian_lightmap(
    grid: np.ndarray,
    objects: Iterable[U6Object],
    tileflags: list[U6TileFlagEntry],
    basetile: tuple[int, ...],
    state: MartianGameState,
    region: tuple[int, int, int, int],
    level: int,
    held_light: int = 0,
) -> np.ndarray:
    """Return cropped DOS light levels, including map lights outside the crop."""
    return build_martian_light_field(
        grid, objects, tileflags, basetile, state, region, level, held_light
    ).levels


def apply_martian_lightmap(
    image: Image.Image, levels: np.ndarray, tiles: U6Tiles, palette: U6Palette
) -> None:
    """Composite retail darkness tiles 268–271 over completed terrain and object layers."""
    masks = {
        level: tiles.to_pil_image(268 + level, palette, transparent=level != 0)
        for level in range(4)
    }
    for y, row in enumerate(levels):
        for x, value in enumerate(row):
            level = int(value)
            if level < 4:
                mask = masks[level]
                image.paste(mask, (x * 16, y * 16), mask if level else None)
