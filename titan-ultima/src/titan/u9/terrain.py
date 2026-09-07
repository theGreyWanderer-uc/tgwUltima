"""
``static/terrain.%d`` reader and writer for Ultima 9: Ascension.

The height map under the world -- one file per region, ``%d`` in 0..239 with
gaps, alongside the same region's :mod:`titan.u9.fixed` and
:mod:`titan.u9.nonfixed`. Where those two place objects, this places the ground
they stand on and the texture it is painted with::

    File header (0x98 bytes)
    0x00  width         u32   -- region width in *points*, a multiple of 16
    0x04  height        u32   -- region height in points
    0x08  name          char[0x80]  -- NUL-terminated region name
    0x88  water_level   i32
    0x8C  wave_amplitude f32
    0x90  flags         u32   -- region-level flags, individual bits unknown
    0x94  chunk_count   u32

    0x98  tiles         u16 x tile_count  -- chunk index, [x + y*tile_width]
          chunks        1024 bytes each

A *tile* is 16x16 points and covers 8x8 world coordinates; ``tile_width`` is
``width / 16``. Each tile names a chunk, and chunks are shared: 25.6% of tiles
use a chunk referenced by another tile, which is how flat expanses like the
ocean floor are stored once. 17.9% of chunks are referenced by no tile at all.

A chunk is 16x16 points in ``[x + y*16]`` order, each point one ``u32``::

    bits  0-11  height      0..4095
    bit   12    hole        no ground here -- a cave mouth or building interior
    bit   13    swap UV coordinates
    bit   14    mirror UV coordinates
    bit   15    quad split  set on (x+y) odd
    bits 16-20  frame       animation frame within the texture
    bit   21    unused      never set
    bits 22-31  texture     index into static/bitmapsh.flx or bitmap16.flx

All integers are little-endian.

Verified against 168 shipped region files -- 50,780 stored chunks, 55,908
tiles, 12,999,680 stored points and 14,312,448 placed points:

* every tile index is below the file's ``chunk_count`` (55,908/55,908);
* every point's texture resolves to a record in the matching ``sdInfo*.flx``
  (12,999,419/12,999,680, the shortfall being five texture indices with no
  record at all), and every point's frame is below that record's frame count
  (12,999,103/12,999,419);
* the tile grid is exactly twice the same region's ``fixed`` chunk grid on
  164 of 164 regions that have both, which is what confirms ``width`` and
  ``height`` are trustworthy even where the rest of the header is not.

The corpus and an independent terrain importer resolve several ambiguities in
the published community documentation:

* ``texture`` is **10** bits, not 9. It is documented as ``uint9`` spanning
  bits 22-31, which is a ten-bit span; shipped regions reach index 936, so the
  span is right and the width is wrong.
* ``frame`` is **5** bits at 16-20, not the six-bit span 16-21 it is documented
  as occupying. Bit 21 is set on none of the 13 million shipped points.
* Bits 13 and 14 control UV rotation (swap and mirror respectively), while bit
  15 chooses the quadrangle's triangle diagonal. The latter is set exactly when
  ``(x + y)`` is odd on 99.5% of stored points.
* ``water_level`` is signed -- the Abyss stores -12 -- and
  ``wave_amplitude`` is a 32-bit float (usually 0.0, otherwise values such as
  0.5, 1.0, 2.0, 5.0 and 10.0).

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

import math
import os
import struct
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

HEADER_SIZE = 0x98
WIDTH_OFFSET = 0x00
HEIGHT_OFFSET = 0x04
NAME_OFFSET = 0x08
NAME_FIELD_SIZE = 0x80
WATER_LEVEL_OFFSET = 0x88
WAVE_AMPLITUDE_OFFSET = 0x8C
FLAGS_OFFSET = 0x90
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
_SWAP_UV_BIT = 13
_MIRROR_UV_BIT = 14
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

    def __post_init__(self) -> None:
        if any(
            not isinstance(coordinate, int) or isinstance(coordinate, bool)
            for coordinate in (self.x, self.y)
        ):
            raise U9TerrainError("point coordinates must be integers")
        if (
            not isinstance(self.value, int)
            or isinstance(self.value, bool)
            or not 0 <= self.value <= 0xFFFFFFFF
        ):
            raise U9TerrainError("point word must be an integer from 0 to 0xffffffff")

    @classmethod
    def build(
        cls,
        *,
        x: int = 0,
        y: int = 0,
        height: int = 0,
        is_hole: bool = False,
        swap_uv: bool = False,
        mirror_uv: bool = False,
        is_split: bool = False,
        frame: int = 0,
        texture: int = 0,
        spare_bit_set: bool = False,
    ) -> U9TerrainPoint:
        """Build one validated point word from its decoded fields."""
        for label, value, maximum in (
            ("height", height, _HEIGHT_MASK),
            ("frame", frame, _FRAME_MASK),
            ("texture", texture, _TEXTURE_MASK),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= maximum
            ):
                raise U9TerrainError(f"{label} must be an integer from 0 to {maximum}")
        for label, value in (
            ("is_hole", is_hole),
            ("swap_uv", swap_uv),
            ("mirror_uv", mirror_uv),
            ("is_split", is_split),
            ("spare_bit_set", spare_bit_set),
        ):
            if not isinstance(value, bool):
                raise U9TerrainError(f"{label} must be bool")

        word = (
            height
            | (int(is_hole) << _HOLE_BIT)
            | (int(swap_uv) << _SWAP_UV_BIT)
            | (int(mirror_uv) << _MIRROR_UV_BIT)
            | (int(is_split) << _SPLIT_BIT)
            | (frame << _FRAME_SHIFT)
            | (int(spare_bit_set) << _SPARE_BIT)
            | (texture << _TEXTURE_SHIFT)
        )
        return cls(x=x, y=y, value=word)

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
        """Index into the active ``bitmapsh.flx`` or ``bitmap16.flx`` archive."""
        return (self.value >> _TEXTURE_SHIFT) & _TEXTURE_MASK

    @property
    def swap_uv(self) -> bool:
        """Whether the texture's U and V coordinates are swapped."""
        return bool((self.value >> _SWAP_UV_BIT) & 1)

    @property
    def mirror_uv(self) -> bool:
        """Whether the swapped/unswapped texture coordinates are mirrored."""
        return bool((self.value >> _MIRROR_UV_BIT) & 1)

    @property
    def uv_rotation_quarter_turns(self) -> int:
        """Texture rotation encoded by bits 13/14, in 90-degree turns."""
        return int(self.swap_uv) + 2 * int(self.mirror_uv)

    @property
    def uv_rotation_degrees(self) -> int:
        """Texture rotation encoded by bits 13/14, in degrees."""
        return self.uv_rotation_quarter_turns * 90

    @property
    def unknown_flags(self) -> tuple[bool, bool]:
        """Compatibility view of bits 13/14; use :attr:`swap_uv` and
        :attr:`mirror_uv` in new code.
        """
        return self.swap_uv, self.mirror_uv

    @property
    def spare_bit_set(self) -> bool:
        """Bit 21, set on no shipped point; a true here means a bad read."""
        return bool((self.value >> _SPARE_BIT) & 1)

    def to_bytes(self) -> bytes:
        """Serialize the point as one little-endian 32-bit word."""
        return struct.pack("<I", self.value)


@dataclass(frozen=True)
class U9TerrainChunk:
    """One 16x16-point chunk, held as raw words until a point is asked for."""

    index: int
    values: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.index, int)
            or isinstance(self.index, bool)
            or not 0 <= self.index <= 0xFFFFFFFF
        ):
            raise U9TerrainError("chunk index must be an integer from 0 to 0xffffffff")
        if len(self.values) != POINTS_PER_CHUNK:
            raise U9TerrainError(
                f"chunk needs exactly {POINTS_PER_CHUNK} points, got {len(self.values)}"
            )
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 0xFFFFFFFF
            for value in self.values
        ):
            raise U9TerrainError(
                "chunk point words must be integers from 0 to 0xffffffff"
            )

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

    def replace_point(
        self, x: int, y: int, point: U9TerrainPoint | int
    ) -> U9TerrainChunk:
        """Return a copy with one local point replaced."""
        if not (0 <= x < CHUNK_POINTS and 0 <= y < CHUNK_POINTS):
            raise U9TerrainError(
                f"point ({x}, {y}) out of range for a "
                f"{CHUNK_POINTS}x{CHUNK_POINTS} chunk"
            )
        value = point.value if isinstance(point, U9TerrainPoint) else point
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 0xFFFFFFFF
        ):
            raise U9TerrainError("point word must be an integer from 0 to 0xffffffff")
        values = list(self.values)
        values[x + y * CHUNK_POINTS] = value
        return U9TerrainChunk(index=self.index, values=tuple(values))

    def to_bytes(self) -> bytes:
        """Serialize the exact 1,024-byte chunk."""
        return struct.pack(f"<{POINTS_PER_CHUNK}I", *self.values)

    @property
    def is_flat(self) -> bool:
        """True when every point sits at the same height."""
        return len(set(self.heights())) == 1


class U9Terrain:
    """Lossless reader and writer for one ``static/terrain.%d`` region file."""

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
        self.name_field = raw_name
        self.name = raw_name.split(b"\x00", 1)[0].decode("cp1252")

        self.water_level = struct.unpack_from("<i", data, WATER_LEVEL_OFFSET)[0]
        self.wave_amplitude = struct.unpack_from("<f", data, WAVE_AMPLITUDE_OFFSET)[0]
        if not math.isfinite(self.wave_amplitude):
            raise U9TerrainError(
                f"wave amplitude is not finite: {self.wave_amplitude!r}"
            )
        self.flags = struct.unpack_from("<I", data, FLAGS_OFFSET)[0]

        self.declared_chunk_count = struct.unpack_from("<I", data, CHUNK_COUNT_OFFSET)[0]

        self._chunk_base = HEADER_SIZE + self.tile_count * 2
        if len(data) < self._chunk_base:
            raise U9TerrainError(
                f"truncated: a {self.tile_width}x{self.tile_height} tile grid "
                f"needs {self._chunk_base} bytes of header, file is {len(data)}"
            )

        self._data = data
        self.tiles = struct.unpack_from(f"<{self.tile_count}H", data, HEADER_SIZE)

        remaining = len(data) - self._chunk_base
        if self.is_empty:
            self.chunk_count = 0
        else:
            needed = self.declared_chunk_count * CHUNK_SIZE
            if remaining < needed:
                room = remaining // CHUNK_SIZE
                raise U9TerrainError(
                    f"truncated: header declares {self.declared_chunk_count} chunks, "
                    f"file holds {room} complete chunk(s)"
                )
            self.chunk_count = self.declared_chunk_count
            invalid = next(
                (index for index in self.tiles if index >= self.chunk_count), None
            )
            if invalid is not None:
                raise U9TerrainError(
                    f"tile grid refers to chunk {invalid}, but only "
                    f"{self.chunk_count} chunk(s) are declared"
                )

        if self.slack_bytes % POINT_SIZE:
            raise U9TerrainError(
                f"trailing data is not a whole number of point words: "
                f"{self.slack_bytes} bytes"
            )

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Terrain:
        with open(filepath, "rb") as f:
            return cls(f.read())

    @classmethod
    def build(
        cls,
        *,
        width: int,
        height: int,
        tiles: Sequence[int],
        chunks: Sequence[U9TerrainChunk],
        name: str = "",
        water_level: int = 0,
        wave_amplitude: float = 0.0,
        flags: int = 0,
        slack_data: bytes = b"",
    ) -> U9Terrain:
        """Build and validate a complete terrain file from decoded values."""
        for label, value in (("width", width), ("height", height)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise U9TerrainError(f"{label} must be a non-negative integer")
        if width % CHUNK_POINTS or height % CHUNK_POINTS:
            raise U9TerrainError(
                f"region is {width}x{height} points, which is not a whole "
                f"number of {CHUNK_POINTS}-point tiles"
            )
        expected_tiles = (width // CHUNK_POINTS) * (height // CHUNK_POINTS)
        if len(tiles) != expected_tiles:
            raise U9TerrainError(
                f"{width}x{height} points need {expected_tiles} tile references, "
                f"got {len(tiles)}"
            )
        if any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index <= 0xFFFF
            for index in tiles
        ):
            raise U9TerrainError("tile references must be integers from 0 to 65535")
        if any(not isinstance(chunk, U9TerrainChunk) for chunk in chunks):
            raise U9TerrainError("chunks must contain only U9TerrainChunk values")
        if not isinstance(name, str):
            raise U9TerrainError("name must be a string")
        try:
            encoded_name = name.encode("cp1252")
        except UnicodeEncodeError as error:
            raise U9TerrainError("name must be encodable as Windows-1252") from error
        if len(encoded_name) >= NAME_FIELD_SIZE:
            raise U9TerrainError(
                f"encoded name must be at most {NAME_FIELD_SIZE - 1} bytes"
            )
        if not isinstance(slack_data, bytes):
            raise U9TerrainError("slack_data must be bytes")

        header = bytearray(HEADER_SIZE)
        try:
            struct.pack_into("<II", header, WIDTH_OFFSET, width, height)
            header[NAME_OFFSET : NAME_OFFSET + len(encoded_name)] = encoded_name
            struct.pack_into("<i", header, WATER_LEVEL_OFFSET, water_level)
            struct.pack_into("<f", header, WAVE_AMPLITUDE_OFFSET, wave_amplitude)
            struct.pack_into("<I", header, FLAGS_OFFSET, flags)
            struct.pack_into("<I", header, CHUNK_COUNT_OFFSET, len(chunks))
            tile_data = struct.pack(f"<{len(tiles)}H", *tiles) if tiles else b""
        except (OverflowError, struct.error) as error:
            raise U9TerrainError(
                f"terrain header value is out of range: {error}"
            ) from error

        data = (
            bytes(header)
            + tile_data
            + b"".join(chunk.to_bytes() for chunk in chunks)
            + slack_data
        )
        return cls(data)

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
    def slack_data(self) -> bytes:
        """Raw stale point words following the last declared chunk."""
        start = self._chunk_base + self.chunk_count * CHUNK_SIZE
        return self._data[start:]

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
        """Duplicate tile references beyond the first use of each chunk.

        Kept for compatibility; :meth:`duplicate_tile_reference_count` names
        this metric precisely.
        """
        return self.duplicate_tile_reference_count()

    def duplicate_tile_reference_count(self) -> int:
        """Tile references beyond the first use of each referenced chunk."""
        return self.tile_count - len(self.referenced_chunks())

    def tiles_using_shared_chunks(self) -> int:
        """Tiles whose referenced chunk occurs more than once in the grid."""
        counts = Counter(self.tiles)
        return sum(count for count in counts.values() if count > 1)

    def texture_histogram(self) -> Counter[int]:
        """Texture usage across placed terrain points, including shared tiles."""
        histogram: Counter[int] = Counter()
        for index, tile_uses in Counter(self.tiles).items():
            for texture, point_count in Counter(self.chunk(index).textures()).items():
                histogram[texture] += tile_uses * point_count
        return histogram

    def to_bytes(self, *, include_slack: bool = True) -> bytes:
        """Serialize the parsed terrain, optionally omitting stale trailing data."""
        if include_slack:
            return self._data
        end = self._chunk_base + self.chunk_count * CHUNK_SIZE
        return self._data[:end]

    def replace_chunk(self, index: int, chunk: U9TerrainChunk) -> U9Terrain:
        """Return a parsed copy with one declared chunk replaced.

        A chunk may be referenced by several tiles, so this deliberately edits
        every placement of that shared chunk. Trailing stale data is preserved.
        """
        if not (0 <= index < self.chunk_count):
            raise U9TerrainError(
                f"chunk {index} out of range (0..{self.chunk_count - 1})"
            )
        if not isinstance(chunk, U9TerrainChunk):
            raise U9TerrainError("replacement must be a U9TerrainChunk")
        data = bytearray(self._data)
        offset = self._chunk_base + index * CHUNK_SIZE
        data[offset : offset + CHUNK_SIZE] = chunk.to_bytes()
        return U9Terrain(bytes(data))

    def replace_tile(
        self, tile_x: int, tile_y: int, chunk_index: int
    ) -> U9Terrain:
        """Return a parsed copy with one tile redirected to a declared chunk."""
        self.tile(tile_x, tile_y)
        if not isinstance(chunk_index, int) or isinstance(chunk_index, bool):
            raise U9TerrainError("chunk index must be an integer")
        if not 0 <= chunk_index < self.chunk_count:
            raise U9TerrainError(
                f"chunk {chunk_index} out of range (0..{self.chunk_count - 1})"
            )
        data = bytearray(self._data)
        tile_index = tile_x + tile_y * self.tile_width
        struct.pack_into("<H", data, HEADER_SIZE + tile_index * 2, chunk_index)
        return U9Terrain(bytes(data))

    def write(
        self,
        filepath: str | os.PathLike[str],
        *,
        include_slack: bool = True,
    ) -> None:
        """Write the terrain bytes to *filepath*."""
        with open(filepath, "wb") as file:
            file.write(self.to_bytes(include_slack=include_slack))

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
