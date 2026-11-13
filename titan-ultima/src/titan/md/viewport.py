"""MD visible wall variants and object clipping from GAME.EXE's view compositor."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from titan.md.lighting import MartianLightField
from titan.u6.object import U6Object
from titan.u6.tileflag import U6TileFlagEntry

__all__ = ["MartianViewport", "resolve_martian_view_tiles"]

# Original initialized DS:0f00; -1 preserves the stored wall tile.
_WALL_VARIANTS = (-1, -1, -1, 2, -1, 1, 0, 0, -1, 4, 3, 3, 5, 4, 0, -1)


def resolve_martian_view_tiles(
    field: MartianLightField, tileflags: list[U6TileFlagEntry]
) -> np.ndarray:
    """Select visible/dark tiles and wall faces using original, unmodified neighbor terrain."""
    left, top, width, height = field.crop
    selected = field.terrain[top : top + height, left : left + width].astype(np.uint16)
    if field.bypass_visibility:
        return selected
    flags, ground = field.flags, field.terrain
    for row in range(height):
        for col in range(width):
            x, y = left + col, top + row
            if not flags[y, x] & 128:
                selected[row, col] = 255
                continue
            if not field.brightness[y, x]:
                selected[row, col] = 268
                continue
            tile = int(ground[y, x])
            terrain = tileflags[tile].terrain
            if terrain & 15 != 6 or 40 <= tile <= 45:
                continue
            if 160 <= tile <= 165:
                first = 336
            elif 176 <= tile <= 178:
                first = 352
            elif 224 <= tile <= 229:
                first = 320
            else:
                continue
            visible = (
                (8 if flags[y - 1, x] & 128 else 0)
                | (4 if flags[y, x + 1] & 128 else 0)
                | (2 if flags[y + 1, x] & 128 else 0)
                | (1 if flags[y, x - 1] & 128 else 0)
            )
            southeast = bool(flags[y + 1, x + 1] & 128)
            if first == 352 and not (visible & 6 == 6 and southeast):
                first = 336
            if visible == 15 and southeast:
                continue
            connections = terrain >> 4
            north = tileflags[int(ground[y - 1, x])].terrain
            if connections & 4 and not flags[y - 1, x] & 8:
                if not (north & 15 & 4 and north & 32):
                    connections &= ~8
            west = tileflags[int(ground[y, x - 1])].terrain
            if connections & 2 and not flags[y, x - 1] & 8:
                if not (west & 15 & 4 and west & 64):
                    connections &= ~1
            variant = _WALL_VARIANTS[connections & visible]
            if variant >= 0:
                selected[row, col] = first + variant
    return selected


@dataclass
class MartianViewport:
    """Resolved crop terrain plus the halo needed to clip each object footprint cell."""

    terrain: np.ndarray
    field: MartianLightField
    origin: tuple[int, int]
    tileflags: list[U6TileFlagEntry]

    def allows_cell(self, x: int, y: int) -> bool:
        """Hide overlays on dark/unseen cells and wall cells with an unseen east/south corner."""
        col, row = x - self.origin[0], y - self.origin[1]
        if not 0 <= row < self.terrain.shape[0] or not 0 <= col < self.terrain.shape[1]:
            return False
        tile = int(self.terrain[row, col])
        if tile in (255, 268):
            return False
        if not self.tileflags[tile].terrain & 4:
            return True
        lx, ly = self.field.crop[0] + col, self.field.crop[1] + row
        flags = self.field.flags
        return bool(flags[ly, lx + 1] & flags[ly + 1, lx] & flags[ly + 1, lx + 1] & 128)

    def restore_lower_terrain(
        self,
        objects: Iterable[U6Object],
        basetile: tuple[int, ...],
        level: int,
        *,
        show_invisible: bool = False,
    ) -> None:
        """Apply force-lower cells before the compositor evaluates wall-corner clipping."""
        for obj in sorted(objects, key=lambda o: (-o.y, -o.x)):
            if (
                not obj.is_on_map
                or (obj.is_invisible and not show_invisible)
                or obj.z != level
            ):
                continue
            tile = obj.tile_num(basetile)
            if not 0 <= tile < len(self.tileflags):
                raise ValueError(
                    f"Invalid map object tile {tile} at ({obj.x}, {obj.y}, {level})"
                )
            for dx, dy, cell in self.tileflags[tile].double_size_footprint(tile):
                if cell >= 2041 or not self.tileflags[cell].is_background:
                    continue
                col, row = obj.x + dx - self.origin[0], obj.y + dy - self.origin[1]
                if (
                    0 <= row < self.terrain.shape[0]
                    and 0 <= col < self.terrain.shape[1]
                    and self.terrain[row, col] not in (255, 268)
                ):
                    self.terrain[row, col] = cell
