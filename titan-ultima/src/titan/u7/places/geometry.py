"""Tile-grid helpers shared by the building and dungeon finders.

All coordinates are inclusive world tiles (0-3071). A rectangle is
``(x0, y0, x1, y1)`` with both corners inside it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator

WORLD_TILES = 3072
TILES_PER_CHUNK = 16
SUPERCHUNK_TILES = 256
NUM_SUPERCHUNKS = 144

N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))

Tile = tuple[int, int]
Rect = tuple[int, int, int, int]


def footprint(tfa, obj) -> Rect:
    """Tiles covered by an object, clipped to the world.

    An object at (tx, ty) with a TFA footprint of dx by dy tiles covers
    tx-dx+1..tx and ty-dy+1..ty.
    """
    entry = tfa.get(obj.shape)
    dx, dy = (1, 1)
    if entry is not None:
        dx, dy, _ = entry.footpad_tiles(obj.frame)
    x0, y0 = max(obj.tx - max(dx, 1) + 1, 0), max(obj.ty - max(dy, 1) + 1, 0)
    return x0, y0, min(obj.tx, WORLD_TILES - 1), min(obj.ty, WORLD_TILES - 1)


def group_tiles(tiles: Iterable[Tile]) -> Iterator[list[Tile]]:
    """Split a set of tiles into 4-connected groups."""
    remaining = set(tiles)
    while remaining:
        start = remaining.pop()
        group, queue = [start], deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in N4:
                nxt = (x + dx, y + dy)
                if nxt in remaining:
                    remaining.remove(nxt)
                    group.append(nxt)
                    queue.append(nxt)
        yield group


def group_near(tiles: Iterable[Tile], gap: int) -> Iterator[list[Tile]]:
    """Split a set of tiles into groups of tiles within ``gap`` of each other."""
    steps = [
        (dx, dy)
        for dx in range(-gap, gap + 1)
        for dy in range(-gap, gap + 1)
        if (dx, dy) != (0, 0)
    ]
    remaining = set(tiles)
    while remaining:
        start = remaining.pop()
        group, queue = [start], deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in steps:
                nxt = (x + dx, y + dy)
                if nxt in remaining:
                    remaining.remove(nxt)
                    group.append(nxt)
                    queue.append(nxt)
        yield group


def to_rects(group: Iterable[Tile]) -> list[Rect]:
    """Exact cover of a tile group by rectangles (row runs merged downwards)."""
    rows: dict[int, list[int]] = {}
    for x, y in group:
        rows.setdefault(y, []).append(x)
    open_rects: dict[tuple[int, int], int] = {}  # (x0, x1) -> y0 still growing
    done: list[Rect] = []
    for y in range(min(rows), max(rows) + 2):
        runs = set()
        xs = sorted(rows.get(y, ()))
        if xs:
            start = prev = xs[0]
            for x in xs[1:]:
                if x != prev + 1:
                    runs.add((start, prev))
                    start = x
                prev = x
            runs.add((start, prev))
        for run in [r for r in open_rects if r not in runs]:
            done.append((run[0], open_rects.pop(run), run[1], y - 1))
        for run in runs:
            open_rects.setdefault(run, y)
    return sorted(done, key=lambda r: (r[1], r[0]))


def chunk_area(chunks: tuple[int, int, int, int] | None) -> Rect | None:
    """Inclusive tile rectangle of a chunk rectangle (cx0, cy0, cx1, cy1)."""
    if not chunks:
        return None
    cx0, cy0, cx1, cy1 = chunks
    return (
        cx0 * TILES_PER_CHUNK,
        cy0 * TILES_PER_CHUNK,
        (cx1 + 1) * TILES_PER_CHUNK - 1,
        (cy1 + 1) * TILES_PER_CHUNK - 1,
    )


def in_rects(x: float, y: float, rects: Iterable[Iterable[int]]) -> bool:
    """True when (x, y) lies inside any of the rectangles."""
    return any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in map(tuple, rects))
