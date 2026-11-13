"""U6 object cell stacks derived from original compositor behavior.

Ordinary cells prepend, foreground anchors insert before existing foreground,
and foreground overflow appends. Background cells replace the selected ground.
Flags belong to the logical tile, before animation remaps its visible pixels.
MD has a separate compositor; there are no U6 object-ID or coordinate overrides.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from titan.u6.object import U6Object
from titan.u6.tileflag import U6TileFlagEntry

__all__ = ["U6ObjectCell", "U6ObjectCellStack", "build_u6_object_stacks"]


@dataclass(frozen=True)
class U6ObjectCell:
    """One logical sprite cell with its source record and anchor/overflow role."""

    obj: U6Object
    record_index: int
    tile_num: int
    is_anchor: bool


@dataclass
class U6ObjectCellStack:
    """Selected background and overlays in bottom-to-top drawing order."""

    background: U6ObjectCell | None = None
    overlays: list[U6ObjectCell] = field(default_factory=list)


def build_u6_object_stacks(
    objects: Iterable[U6Object],
    basetile: Sequence[int],
    tileflags: Sequence[U6TileFlagEntry],
    *,
    bounds: tuple[int, int, int, int] | None = None,
    show_invisible: bool = False,
    num_tiles: int = 2048,
) -> dict[tuple[int, int, int], U6ObjectCellStack]:
    """Build U6 cell stacks; bounds are absolute x/y/width/height, with clipped overflow.

    World traversal is north-to-south, west-to-east, retaining file order at
    equal coordinates. The original per-cell insertion then reverses ordinary
    overlap order. Background takes precedence over the foreground flag.
    In debug visibility mode, hidden objects and the normally suppressed egg
    marker are included. The static exporter treats the whole region as lit;
    viewport visibility, actors, effects and the DOS allocation cap are outside
    this builder's scope.
    """
    stacks: dict[tuple[int, int, int], U6ObjectCellStack] = {}
    bases = tuple(basetile)
    marker_tile = bases[335] if len(bases) > 335 else -1
    ordered = sorted(enumerate(objects), key=lambda item: (item[1].y, item[1].x))
    for record_index, obj in ordered:
        if not obj.is_on_map or (obj.is_invisible and not show_invisible):
            continue
        if bounds is not None:
            x, y, width, height = bounds
            if not (x <= obj.x <= x + width and y <= obj.y <= y + height):
                continue
        tile = obj.tile_num(bases)
        if not 0 <= tile < min(num_tiles, len(tileflags)):
            continue
        for dx, dy, cell_tile in tileflags[tile].double_size_footprint(tile):
            if not 0 <= cell_tile < min(num_tiles, len(tileflags)):
                continue
            if cell_tile == marker_tile and not show_invisible:
                continue
            cx, cy = obj.x + dx, obj.y + dy
            if bounds is not None and not (
                x <= cx < x + width and y <= cy < y + height
            ):
                continue
            cell = U6ObjectCell(obj, record_index, cell_tile, dx == dy == 0)
            stack = stacks.setdefault((cx, cy, obj.z), U6ObjectCellStack())
            flags = tileflags[cell_tile]
            if flags.is_background:
                stack.background = cell
            elif not flags.is_foreground:
                stack.overlays.insert(0, cell)
            elif not cell.is_anchor:
                stack.overlays.append(cell)
            else:
                first_foreground = next(
                    (
                        i
                        for i, existing in enumerate(stack.overlays)
                        if tileflags[existing.tile_num].is_foreground
                    ),
                    len(stack.overlays),
                )
                stack.overlays.insert(first_foreground, cell)
    return stacks
