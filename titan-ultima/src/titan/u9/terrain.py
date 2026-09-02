"""
``static/terrain.%d`` reader for Ultima 9: Ascension.

The height map under the world -- one file per region, ``%d`` in 0..239 with
gaps, alongside the same region's :mod:`titan.u9.fixed` and
:mod:`titan.u9.nonfixed`. Where those two place objects, this places the ground
they stand on and the texture it is painted with::

    File header (0x98 bytes)
    0x00  width         u32   -- region width in *points*, a multiple of 16
    0x04  height        u32   -- region height in points
    0x08  name          char[0x80]  -- NUL-terminated region name
    0x88  unknown       u32   -- 1200 on most regions
    0x8C  unknown       u32
    0x90  unknown       u32
    0x94  chunk_count   u32

    0x98  tiles         u16 x tile_count  -- chunk index, [x + y*tile_width]
          chunks        1024 bytes each

A *tile* is 16x16 points and covers 8x8 world coordinates; ``tile_width`` is
``width / 16``. Each tile names a chunk, and chunks are shared: 25.4% of tiles
point at a chunk some other tile also uses, which is how flat expanses like the
ocean floor are stored once. 17.9% of chunks are referenced by no tile at all.

A chunk is 16x16 points in ``[x + y*16]`` order, each point one ``u32``::

    bits  0-11  height      0..4095
    bit   12    hole        no ground here -- a cave mouth or building interior
    bit   13    unknown
    bit   14    unknown
    bit   15    quad split  set on (x+y) odd
    bits 16-20  frame       animation frame within the texture
    bit   21    unused      never set
    bits 22-31  texture     index into static/bitmap8.flx or bitmap16.flx

All integers are little-endian.

Verified against 168 shipped region files -- 50,780 chunks, 55,908 tiles,
12,999,680 points:

* every tile index is below the file's ``chunk_count`` (55,908/55,908);
* every point's texture resolves to a record in the matching ``sdInfo*.flx``
  (12,999,419/12,999,680, the shortfall being five texture indices with no
  record at all), and every point's frame is below that record's frame count
  (12,999,103/12,999,419);
* the tile grid is exactly twice the same region's ``fixed`` chunk grid on
  164 of 164 regions that have both, which is what confirms ``width`` and
  ``height`` are trustworthy even where the rest of the header is not.

Three corrections to the published community documentation came out of that:

* ``texture`` is **10** bits, not 9. It is documented as ``uint9`` spanning
  bits 22-31, which is a ten-bit span; shipped regions reach index 936, so the
  span is right and the width is wrong.
* ``frame`` is **5** bits at 16-20, not the six-bit span 16-21 it is documented
  as occupying. Bit 21 is set on none of the 13 million shipped points.
* Bit 15 is not a free flag: it is set exactly when ``(x + y)`` is odd on
  99.5% of points, so it carries the quadrangle's split direction. Bits 13 and
  14 sit near 50% and match no positional pattern tested.

``chunk_count`` is authoritative and the file may be longer than it needs to
be: 22 regions carry 2.2 MB past their last declared chunk, and that slack
parses as valid points, so it is stale data from a larger earlier build rather
than padding. This reader stops at ``chunk_count`` and reports the remainder as
:attr:`U9Terrain.slack_bytes`.

Example::

    from titan.u9.terrain import U9Terrain

    region = U9Terrain.from_file("static/terrain.22")
    print(region.name, region.width, region.height)
    print(region.height_at(40, 40))
"""

from __future__ import annotations

__all__ = [
    "U9Terrain",
    "U9TerrainChunk",
    "U9TerrainError",
    "U9TerrainPoint",
]

import os
import struct
from dataclasses import dataclass

HEADER_SIZE = 0x98
WIDTH_OFFSET = 0x00
HEIGHT_OFFSET = 0x04
NAME_OFFSET = 0x08
NAME_FIELD_SIZE = 0x80
CHUNK_COUNT_OFFSET = 0x94

CHUNK_POINTS = 16
POINTS_PER_CHUNK = CHUNK_POINTS * CHUNK_POINTS
POINT_SIZE = 4
CHUNK_SIZE = POINTS_PER_CHUNK * POINT_SIZE

WORLD_UNITS_PER_TILE = 8
MAX_HEIGHT = 0xFFF
MAX_TILE_DIM = 256

_HEIGHT_MASK = 0xFFF
_HOLE_BIT = 12
_UNKNOWN_13_BIT = 13
_UNKNOWN_14_BIT = 14
_SPLIT_BIT = 15
_FRAME_SHIFT = 16
_FRAME_MASK = 0x1F
_SPARE_BIT = 21
_TEXTURE_SHIFT = 22
_TEXTURE_MASK = 0x3FF


class U9TerrainError(Exception):
    """Raised on malformed ``static/terrain.%d`` data."""


@dataclass(frozen=True)
class U9TerrainPoint:
    """One 32-bit height-map point, decoded."""

    x: int
    y: int
    value: int

    @property
    def height(self) -> int:
        """Ground height, 0..4095."""
        return self.value & _HEIGHT_MASK

    @property
    def is_hole(self) -> bool:
        """No ground here -- a cave mouth or building interior."""
        return bool((self.value >> _HOLE_BIT) & 1)

    @property
    def is_split(self) -> bool:
        """Quadrangle split direction; set on ``(x + y)`` odd."""
        return bool((self.value >> _SPLIT_BIT) & 1)

    @property
    def frame(self) -> int:
        """Animation frame within :attr:`texture`."""
        return (self.value >> _FRAME_SHIFT) & _FRAME_MASK

    @property
    def texture(self) -> int:
        """Index into ``static/bitmap8.flx`` or ``static/bitmap16.flx``."""
        return (self.value >> _TEXTURE_SHIFT) & _TEXTURE_MASK

    @property
    def unknown_flags(self) -> tuple[bool, bool]:
        """Bits 13 and 14, whose meaning is not decoded."""
        return (
            bool((self.value >> _UNKNOWN_13_BIT) & 1),
            bool((self.value >> _UNKNOWN_14_BIT) & 1),
        )

    @property
    def spare_bit_set(self) -> bool:
        """Bit 21, set on no shipped point; a true here means a bad read."""
        return bool((self.value >> _SPARE_BIT) & 1)


@dataclass(frozen=True)
class U9TerrainChunk:
    """One 16x16-point chunk, held as raw words until a point is asked for."""

    index: int
    values: tuple[int, ...]

    def point(self, x: int, y: int) -> U9TerrainPoint:
        """One point by its position within the chunk."""
        if not (0 <= x < CHUNK_POINTS and 0 <= y < CHUNK_POINTS):
            raise U9TerrainError(
                f"point ({x}, {y}) out of range for a "
                f"{CHUNK_POINTS}x{CHUNK_POINTS} chunk"
            )
        return U9TerrainPoint(x=x, y=y, value=self.values[x + y * CHUNK_POINTS])

    def points(self) -> list[U9TerrainPoint]:
        """Every point, in ``[x + y*16]`` order."""
        return [
            U9TerrainPoint(x=i % CHUNK_POINTS, y=i // CHUNK_POINTS, value=v)
            for i, v in enumerate(self.values)
        ]

    def heights(self) -> tuple[int, ...]:
        """Just the heights, cheaper than building every point."""
        return tuple(v & _HEIGHT_MASK for v in self.values)

    def textures(self) -> tuple[int, ...]:
        """Just the texture indices."""
        return tuple((v >> _TEXTURE_SHIFT) & _TEXTURE_MASK for v in self.values)

    @property
    def is_flat(self) -> bool:
        """True when every point sits at the same height."""
        return len(set(self.heights())) == 1


class U9Terrain:
    """Reader for one ``static/terrain.%d`` region file."""

    def __init__(self, data: bytes) -> None:
        if len(data) < HEADER_SIZE:
            raise U9TerrainError(
                f"data too small to contain a terrain header: {len(data)} bytes"
            )

        self.width, self.height = struct.unpack_from("<II", data, WIDTH_OFFSET)
        # Four shipped regions are a bare header and nothing else: an unused
        # region slot. Accept that exact shape, and only that one, so an
        # unrelated file of zeros cannot pass as an empty region.
        if self.width == 0 or self.height == 0:
            if (self.width, self.height) != (0, 0) or len(data) != HEADER_SIZE:
                raise U9TerrainError(
                    f"region is {self.width}x{self.height} points in a "
                    f"{len(data)}-byte file -- not a terrain file?"
                )
        if self.width % CHUNK_POINTS or self.height % CHUNK_POINTS:
            raise U9TerrainError(
                f"region is {self.width}x{self.height} points, which is not a "
                f"whole number of {CHUNK_POINTS}-point tiles"
            )

        self.tile_width = self.width // CHUNK_POINTS
        self.tile_height = self.height // CHUNK_POINTS
        if self.tile_width > MAX_TILE_DIM or self.tile_height > MAX_TILE_DIM:
            raise U9TerrainError(
                f"implausible tile grid {self.tile_width}x{self.tile_height} "
                f"-- not a terrain file?"
            )

        raw_name = data[NAME_OFFSET : NAME_OFFSET + NAME_FIELD_SIZE]
        self.name = raw_name.split(b"\x00", 1)[0].decode("latin-1")

        self.declared_chunk_count = struct.unpack_from("<I", data, CHUNK_COUNT_OFFSET)[0]

        self._chunk_base = HEADER_SIZE + self.tile_count * 2
        if len(data) < self._chunk_base:
            raise U9TerrainError(
                f"truncated: a {self.tile_width}x{self.tile_height} tile grid "
                f"needs {self._chunk_base} bytes of header, file is {len(data)}"
            )

        self._data = data
        self.tiles = struct.unpack_from(f"<{self.tile_count}H", data, HEADER_SIZE)

        room = (len(data) - self._chunk_base) // CHUNK_SIZE
        # The count is authoritative; 22 shipped regions carry stale chunks
        # past it, so trust the smaller of the two and report the remainder.
        self.chunk_count = min(self.declared_chunk_count, room)

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Terrain:
        with open(filepath, "rb") as f:
            return cls(f.read())

    @property
    def tile_count(self) -> int:
        return self.tile_width * self.tile_height

    @property
    def world_width(self) -> int:
        """Region width in world coordinates -- two points to the unit."""
        return self.tile_width * WORLD_UNITS_PER_TILE

    @property
    def world_height(self) -> int:
        return self.tile_height * WORLD_UNITS_PER_TILE

    @property
    def slack_bytes(self) -> int:
        """Bytes past the last chunk this reader will look at."""
        return len(self._data) - self._chunk_base - self.chunk_count * CHUNK_SIZE

    @property
    def is_empty(self) -> bool:
        """True for an unused region slot: a bare header and no grid."""
        return self.tile_count == 0

    @property
    def is_truncated(self) -> bool:
        """True when the file holds fewer chunks than its header declares.

        Set on the empty region slots, whose ``chunk_count`` field is stale.
        """
        return self.chunk_count < self.declared_chunk_count

    def tile(self, tile_x: int, tile_y: int) -> int:
        """The chunk index a tile refers to."""
        if not (0 <= tile_x < self.tile_width and 0 <= tile_y < self.tile_height):
            raise U9TerrainError(
                f"tile ({tile_x}, {tile_y}) out of range for a "
                f"{self.tile_width}x{self.tile_height} grid"
            )
        return self.tiles[tile_x + tile_y * self.tile_width]

    def chunk(self, index: int) -> U9TerrainChunk:
        """One chunk by index."""
        if not (0 <= index < self.chunk_count):
            raise U9TerrainError(
                f"chunk {index} out of range (0..{self.chunk_count - 1})"
            )
        offset = self._chunk_base + index * CHUNK_SIZE
        values = struct.unpack_from(f"<{POINTS_PER_CHUNK}I", self._data, offset)
        return U9TerrainChunk(index=index, values=values)

    def chunks(self) -> list[U9TerrainChunk]:
        """Every chunk, in file order."""
        return [self.chunk(i) for i in range(self.chunk_count)]

    def chunk_for_tile(self, tile_x: int, tile_y: int) -> U9TerrainChunk:
        """The chunk a tile refers to."""
        return self.chunk(self.tile(tile_x, tile_y))

    def referenced_chunks(self) -> set[int]:
        """Chunk indices at least one tile points at."""
        return set(self.tiles)

    def unused_chunks(self) -> list[int]:
        """Chunk indices no tile points at -- 17.9% of shipped chunks."""
        used = self.referenced_chunks()
        return [i for i in range(self.chunk_count) if i not in used]

    def shared_tile_count(self) -> int:
        """Tiles whose chunk is also used by another tile."""
        return self.tile_count - len(self.referenced_chunks())

    def point(self, x: int, y: int) -> U9TerrainPoint:
        """One point by its position in the whole region, in points."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise U9TerrainError(
                f"point ({x}, {y}) out of range for a "
                f"{self.width}x{self.height} region"
            )
        chunk = self.chunk_for_tile(x // CHUNK_POINTS, y // CHUNK_POINTS)
        local = chunk.point(x % CHUNK_POINTS, y % CHUNK_POINTS)
        return U9TerrainPoint(x=x, y=y, value=local.value)

    def height_at(self, x: int, y: int) -> int:
        """Ground height at a region point."""
        return self.point(x, y).height

    def heightmap(self) -> list[list[int]]:
        """The whole region's heights as ``rows[y][x]``."""
        cache = {
            i: self.chunk(i).heights()
            for i in sorted(self.referenced_chunks())
            if i < self.chunk_count
        }
        rows: list[list[int]] = []
        for y in range(self.height):
            tile_y, point_y = divmod(y, CHUNK_POINTS)
            base = tile_y * self.tile_width
            row: list[int] = []
            for tile_x in range(self.tile_width):
                heights = cache.get(self.tiles[base + tile_x])
                if heights is None:
                    row.extend([0] * CHUNK_POINTS)
                else:
                    start = point_y * CHUNK_POINTS
                    row.extend(heights[start : start + CHUNK_POINTS])
            rows.append(row)
        return rows

    def height_range(self) -> tuple[int, int]:
        """Lowest and highest point in the region."""
        low, high = MAX_HEIGHT, 0
        for index in sorted(self.referenced_chunks()):
            if index >= self.chunk_count:
                continue
            heights = self.chunk(index).heights()
            low = min(low, min(heights))
            high = max(high, max(heights))
        return (low, high) if high >= low else (0, 0)
