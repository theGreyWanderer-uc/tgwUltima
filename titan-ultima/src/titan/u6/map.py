"""
World map decoder for Ultima 6 (``MAP`` + ``CHUNKS``).

Neither file is documented in ``u6data/u6tech.txt`` at all. This module is
built from Nuvie's ``Map.cpp`` (``loadMap``, ``insertSurfaceSuperChunk``,
``insertDungeonSuperChunk``) and pu6e's ``Map.py``, which independently
agree on every detail -- byte-for-byte, including the file sizes -- and
has been validated end to end against a real GOG-style install: parsing
consumes exactly 32256 bytes with zero leftover, every referenced chunk
number is in range, and rendering the composited surface at Lord British's
Castle's documented coordinates (pu6e's readme: hex 0x134, 0x16c) produces
an unmistakable, correctly-shaped image of the castle, moat, and
surrounding terrain.

Both files are raw and uncompressed (confirmed directly; ``u6tech.txt``
does not claim otherwise for these, unlike its wrong claim about
``TILEINDX.VGA``).

``CHUNKS`` (65536 bytes) is 1024 fixed-size chunks, each an 8x8 grid of
tile numbers (one byte per tile, row-major) indexing into the 0-255
range of :class:`titan.u6.tile.U6Tiles` (ground tiles only, from
``MAPTILES.VGA``'s range -- chunks never reference the object-range
tiles in ``OBJTILES.VGA``).

``MAP`` (32256 bytes) is 69 "superchunks": 64 surface superchunks (a
sequential, row-major 8x8 arrangement covering a combined 1024x1024-tile
world) plus 5 dungeon superchunks (one per dungeon level, each covering
a 256x256-tile level independently). A surface superchunk holds a 16x16
grid of chunk-number references (384 bytes); a dungeon superchunk holds
a 32x32 grid (1536 bytes) -- both packed 3 bytes per 2 chunk-numbers,
12 bits each, little-endian (chunk1 = low byte + high nibble of the
middle byte; chunk2 = high nibble of the middle byte's partner + the
last byte -- see :func:`_unpack_superchunk_refs`).

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Pass an :class:`titan.u6.tile.U6AnimData` to :func:`render_tile_grid` when
rendering surface/dungeon grids. Without it, CHUNKS-referenced animated
placeholder tiles (water, in particular) render as flat, wrong-colored
squares instead of their real content -- see titan.u6.tile's module
docstring for how that was found and confirmed.

Example::

    from titan.u6.tile import U6Tiles, U6AnimData
    from titan.u6.palette import U6Palette
    from titan.u6.map import U6Chunks, U6Map, render_tile_grid

    chunks = U6Chunks.from_file("CHUNKS")
    world_map = U6Map.from_file("MAP")
    grid = world_map.build_surface_grid(chunks)  # 1024x1024 tile numbers

    tiles = U6Tiles.from_directory("C:/Ultima/Ultima6")
    palette = U6Palette.from_file("C:/Ultima/Ultima6/U6PAL")
    animdata = U6AnimData.from_file("C:/Ultima/Ultima6/ANIMDATA")
    img = render_tile_grid(grid, tiles, palette, region=(276, 332, 64, 64), animdata=animdata)
    img.save("lb_castle.png")
"""

from __future__ import annotations

__all__ = [
    "U6Chunks",
    "U6ChunksError",
    "U6Map",
    "U6MapError",
    "render_tile_grid",
    "CHUNK_DIM",
    "SURFACE_SUPERCHUNKS",
    "SURFACE_SIDE_SUPERCHUNKS",
    "SURFACE_CHUNKS_PER_SIDE",
    "DUNGEON_LEVELS",
    "DUNGEON_CHUNKS_PER_SIDE",
    "SURFACE_WORLD_TILES",
    "DUNGEON_WORLD_TILES",
]

import os

import numpy as np
from PIL import Image

from titan.u6.tile import TILE_DIM, TRANSPARENT, U6Tiles

CHUNK_DIM = 8
CHUNK_SIZE = CHUNK_DIM * CHUNK_DIM  # 64

SURFACE_SUPERCHUNKS = 64
SURFACE_SIDE_SUPERCHUNKS = 8  # 8x8 arrangement of surface superchunks
SURFACE_CHUNKS_PER_SIDE = 16  # 16x16 chunk-refs per surface superchunk
DUNGEON_LEVELS = 5
DUNGEON_CHUNKS_PER_SIDE = 32  # 32x32 chunk-refs per dungeon superchunk

SURFACE_WORLD_TILES = SURFACE_SIDE_SUPERCHUNKS * SURFACE_CHUNKS_PER_SIDE * CHUNK_DIM  # 1024
DUNGEON_WORLD_TILES = DUNGEON_CHUNKS_PER_SIDE * CHUNK_DIM  # 256


class U6ChunksError(Exception):
    """Raised when CHUNKS data isn't a whole number of 64-byte chunks."""


class U6MapError(Exception):
    """Raised when MAP data doesn't match the expected superchunk layout."""


class U6Chunks:
    """Reader for CHUNKS: fixed-size 8x8-tile-number chunks."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U6Chunks:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> U6Chunks:
        if len(data) % CHUNK_SIZE != 0:
            raise U6ChunksError(f"CHUNKS data length {len(data)} is not a multiple of {CHUNK_SIZE}")
        return cls(data)

    @property
    def num_chunks(self) -> int:
        return len(self._data) // CHUNK_SIZE

    def get_chunk(self, chunk_num: int) -> bytes:
        """Return one chunk's 64 raw tile-number bytes (row-major 8x8)."""
        return self._data[chunk_num * CHUNK_SIZE:(chunk_num + 1) * CHUNK_SIZE]

    def get_chunk_array(self, chunk_num: int) -> np.ndarray:
        """Return one chunk as an 8x8 uint8 array of tile numbers."""
        return np.frombuffer(
            self._data, dtype=np.uint8, count=CHUNK_SIZE, offset=chunk_num * CHUNK_SIZE
        ).reshape(CHUNK_DIM, CHUNK_DIM)


def _unpack_superchunk_refs(buf: bytes, side: int) -> list[int]:
    """
    Unpack a superchunk's chunk-number references.

    3 bytes -> 2 chunk numbers (12 bits each, little-endian), row-major
    with x fastest. Confirmed identical between Nuvie's C++
    (``insertSurfaceSuperChunk``/``insertDungeonSuperChunk``) and pu6e's
    Python (``parse_map``).
    """
    n_pairs = (side * side) // 2
    refs: list[int] = []
    for i in range(n_pairs):
        b0, b1, b2 = buf[i * 3], buf[i * 3 + 1], buf[i * 3 + 2]
        refs.append(((b1 & 0x0F) << 8) | b0)
        refs.append((b2 << 4) | (b1 >> 4))
    return refs


class U6Map:
    """Reader for MAP: surface + dungeon superchunk chunk-reference grids."""

    def __init__(
        self,
        surface_superchunks: list[list[int]],
        dungeon_superchunks: list[list[int]],
        surface_side: int = SURFACE_CHUNKS_PER_SIDE,
        dungeon_side: int = DUNGEON_CHUNKS_PER_SIDE,
        surface_arrangement: int = SURFACE_SIDE_SUPERCHUNKS,
    ) -> None:
        self.surface_superchunks = surface_superchunks
        self.dungeon_superchunks = dungeon_superchunks
        self.surface_side = surface_side
        self.dungeon_side = dungeon_side
        self.surface_arrangement = surface_arrangement

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str], **kwargs) -> U6Map:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data, **kwargs)

    @classmethod
    def parse(
        cls,
        data: bytes,
        num_surface_superchunks: int = SURFACE_SUPERCHUNKS,
        num_dungeon_levels: int = DUNGEON_LEVELS,
        surface_side: int = SURFACE_CHUNKS_PER_SIDE,
        dungeon_side: int = DUNGEON_CHUNKS_PER_SIDE,
        surface_arrangement: int = SURFACE_SIDE_SUPERCHUNKS,
    ) -> U6Map:
        """
        Parse MAP data. Defaults match the real 32256-byte format; the
        other parameters only need overriding to build small fixtures in
        tests.
        """
        surface_bytes = (surface_side * surface_side * 3) // 2
        dungeon_bytes = (dungeon_side * dungeon_side * 3) // 2
        expected = num_surface_superchunks * surface_bytes + num_dungeon_levels * dungeon_bytes
        if len(data) != expected:
            raise U6MapError(f"MAP data is {len(data)} bytes, expected {expected}")

        pos = 0
        surface: list[list[int]] = []
        for _ in range(num_surface_superchunks):
            surface.append(_unpack_superchunk_refs(data[pos:pos + surface_bytes], surface_side))
            pos += surface_bytes

        dungeon: list[list[int]] = []
        for _ in range(num_dungeon_levels):
            dungeon.append(_unpack_superchunk_refs(data[pos:pos + dungeon_bytes], dungeon_side))
            pos += dungeon_bytes

        return cls(surface, dungeon, surface_side=surface_side, dungeon_side=dungeon_side,
                   surface_arrangement=surface_arrangement)

    def build_surface_grid(self, chunks: U6Chunks) -> np.ndarray:
        """Composite the full surface into one tile-number grid."""
        side = self.surface_side
        world_side = self.surface_arrangement * side * CHUNK_DIM
        grid = np.zeros((world_side, world_side), dtype=np.uint8)
        for schunk_num, refs in enumerate(self.surface_superchunks):
            world_x = (schunk_num % self.surface_arrangement) * side * CHUNK_DIM
            world_y = (schunk_num // self.surface_arrangement) * side * CHUNK_DIM
            self._paint_superchunk(grid, refs, chunks, side, world_x, world_y)
        return grid

    def build_dungeon_grid(self, level: int, chunks: U6Chunks) -> np.ndarray:
        """Composite one dungeon level (0-based) into a tile-number grid."""
        side = self.dungeon_side
        world_side = side * CHUNK_DIM
        grid = np.zeros((world_side, world_side), dtype=np.uint8)
        self._paint_superchunk(grid, self.dungeon_superchunks[level], chunks, side, 0, 0)
        return grid

    @staticmethod
    def _paint_superchunk(
        grid: np.ndarray, refs: list[int], chunks: U6Chunks, side: int, world_x: int, world_y: int
    ) -> None:
        for cy in range(side):
            for cx in range(side):
                chunk_arr = chunks.get_chunk_array(refs[cx + cy * side])
                y0 = world_y + cy * CHUNK_DIM
                x0 = world_x + cx * CHUNK_DIM
                grid[y0:y0 + CHUNK_DIM, x0:x0 + CHUNK_DIM] = chunk_arr


def render_tile_grid(
    grid: np.ndarray,
    tiles: U6Tiles,
    palette,
    region: tuple[int, int, int, int] | None = None,
    transparent: bool = False,
    animdata=None,
    tick: int = 0,
) -> Image.Image:
    """
    Render a 2D grid of tile numbers to an image.

    Args:
        grid: HxW uint8 array of tile numbers, e.g. from
            :meth:`U6Map.build_surface_grid`.
        region: optional ``(x, y, width, height)`` in tile coordinates to
            crop before rendering, so a small area can be rendered
            without materializing a full-world image.
        transparent: if ``True``, tile value 0xFF renders as alpha=0.
        animdata: optional :class:`titan.u6.tile.U6AnimData`. When given,
            animated placeholder tiles (e.g. water) are substituted for
            their real frame before rendering -- omitting this renders
            those tiles' raw (always-blank) content instead, which is
            usually not what you want. See titan.u6.tile's module
            docstring for why this matters.
        tick: animation tick passed to ``animdata`` (ignored otherwise).
    """
    if region is not None:
        x, y, w, h = region
        grid = grid[y:y + h, x:x + w]

    if animdata is not None:
        grid = animdata.resolve_grid(grid, tick)

    max_tile = int(grid.max()) + 1
    tile_stack = np.stack([tiles.to_array(i) for i in range(max_tile)])  # (N, 16, 16)
    h, w = grid.shape
    pixels = tile_stack[grid]  # (H, W, 16, 16)
    indexed = pixels.transpose(0, 2, 1, 3).reshape(h * TILE_DIM, w * TILE_DIM)

    img = Image.fromarray(indexed, mode="P")
    img.putpalette(palette.to_flat_rgb())
    if not transparent:
        return img.convert("RGB")

    rgba = img.convert("RGBA")
    alpha = np.where(indexed == TRANSPARENT, 0, 255).astype(np.uint8)
    rgba.putalpha(Image.fromarray(alpha, mode="L"))
    return rgba
