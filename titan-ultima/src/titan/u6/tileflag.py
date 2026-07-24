"""
TILEFLAG parser for Ultima 6.

TILEFLAG is not documented at all in ``u6data/u6tech.txt``. This module is
built from Nuvie's community-reverse-engineered ``docs/ultima6/tileflag.txt``
and pu6e's ``tile.py`` byte offsets, then confirmed field-for-field against
the actual load sequence and bit-flag macros in the decompiled ``GAME.EXE``
source (``u6-decompiled/SRC/seg_0903.c:227-233`` and ``u6.h:179-244``) --
not just cross-referenced docs. TILEFLAG is a flat, uncompressed 7168-byte
file, verified directly against a real GOG-style install: four back-to-back
per-tile-number byte arrays, each loaded into its own named buffer by the
original game code::

    TerrainType = tileflag[0x000:0x800]   # 2048 bytes, tiles 0-0x7FF
    TileFlag    = tileflag[0x800:0x1000]  # 2048 bytes, tiles 0-0x7FF
    TypeWeight  = tileflag[0x1000:0x1400] # 1024 bytes, objects 0-0x3FF only
    D_B3EF      = tileflag[0x1400:0x1C00] # 2048 bytes, tiles 0-0x7FF

The decompiled source's own inline comments settle two things neither Nuvie
nor pu6e were fully sure of: the TerrainType wall-direction nibble is
W=bit4, S=bit5, E=bit6, N=bit7 (``u6.h:188-195``), and TypeWeight really is
only 1024 entries (matching u6tech.txt's separate note that object weight
is indexed 0-0x3ff). TILE_FLAG1_40/0x80's inline comments ("[Double]
horizontal"/"vertical") actually contradict the macro names built from them
right next to them in the same file (``IsTileDoubleV`` for 0x40,
``IsTileDoubleH`` for 0x80, ``u6.h:213-224``) -- but Jim Ursetto's
independently-derived ``u6notes.txt`` agrees with the *macro names*, not
the comments ("bit 7 (0x40): object vertical size... bit 8 (0x80): object
horizontal size"). Two independent sources against one stale-looking
comment: :attr:`~U6TileFlagEntry.is_double_v` (0x40) is treated as vertical
and :attr:`~U6TileFlagEntry.is_double_h` (0x80) as horizontal, matching both.

A double-sized *object* tile's stored coordinate is its bottom-right cell,
and Jim Ursetto's ``u6notes.txt`` documents the layout of its other
cell(s): consecutively *lower* tile numbers, one per cell, visited
right-to-left within a row starting from the bottom row and moving upward.
:meth:`U6TileFlagEntry.double_size_footprint` resolves this into
``(dx, dy, tile_num)`` offsets from the anchor coordinate (returning a
single ``(0, 0, tile_num)`` cell for an ordinary, non-double tile, so
callers never need to special-case the common case). Wired into
:mod:`titan.u6.cli`'s ``map-render --objects`` and validated against a
real render: beds, a wall banner, and a barrel that previously rendered
as flat, truncated single-tile squares now render as their complete,
correctly-shaped multi-cell sprites (1685 double-sized objects found on
the real surface map alone, so this was not a rare case).

Read for byte-layout reference only -- this is a fresh implementation, not
a translation of GPL or unlicensed source.
"""

from __future__ import annotations

__all__ = ["U6TileFlags", "U6TileFlagEntry", "U6TileFlagsError"]

import os
from dataclasses import dataclass

ARTICLES = ("", "a", "an", "the")


class U6TileFlagsError(Exception):
    """Raised when TILEFLAG data is too short to contain all four regions."""


@dataclass
class U6TileFlagEntry:
    """Decoded TILEFLAG record for a single tile/object number."""

    tile_num: int
    terrain: int  # TerrainType byte
    flags: int  # TileFlag byte
    weight: int  # TypeWeight byte; 0 for tile_num >= 0x400 (no weight data there)
    extra: int  # D_B3EF byte

    # --- TerrainType (u6.h TERRAIN_FLAG_*) ---
    @property
    def is_wet(self) -> bool:
        return bool(self.terrain & 0x01)

    @property
    def is_impassable(self) -> bool:
        return bool(self.terrain & 0x02)

    @property
    def is_wall(self) -> bool:
        return bool(self.terrain & 0x04)

    @property
    def is_damaging(self) -> bool:
        return bool(self.terrain & 0x08)

    @property
    def wall_west(self) -> bool:
        return bool(self.terrain & 0x10)

    @property
    def wall_south(self) -> bool:
        return bool(self.terrain & 0x20)

    @property
    def wall_east(self) -> bool:
        return bool(self.terrain & 0x40)

    @property
    def wall_north(self) -> bool:
        return bool(self.terrain & 0x80)

    @property
    def movement_impedance(self) -> int:
        """Raw pathfinding-cost nibble (``TerrainType >> 4``); dual-purposed with the wall-direction bits above."""
        return self.terrain >> 4

    # --- TileFlag (u6.h TILE_FLAG1_*) ---
    @property
    def light_level(self) -> int:
        return self.flags & 0x03

    @property
    def is_opaque(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def is_window(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def is_foreground(self) -> bool:
        """'toptile' -- always drawn on top of other shapes at the same spot."""
        return bool(self.flags & 0x10)

    @property
    def no_shoot_through(self) -> bool:
        return bool(self.flags & 0x20)

    @property
    def is_double_v(self) -> bool:
        """One of a double-sized object's two axis flags; see module docstring caveat."""
        return bool(self.flags & 0x40)

    @property
    def is_double_h(self) -> bool:
        """One of a double-sized object's two axis flags; see module docstring caveat."""
        return bool(self.flags & 0x80)

    @property
    def is_double(self) -> bool:
        return bool(self.flags & 0xC0)

    def double_size_footprint(self, tile_num: int) -> list[tuple[int, int, int]]:
        """
        Resolve a placed tile into ``(dx, dy, tile_num)`` cell offsets from
        its anchor (stored) coordinate, honoring :attr:`is_double_v`/
        :attr:`is_double_h`. The stored coordinate is the object's
        bottom-right cell; additional cells use consecutively lower tile
        numbers, visited right-to-left within a row, bottom row first (see
        module docstring). Always includes ``(0, 0, tile_num)``; returns
        just that single cell when neither double flag is set.
        """
        width = 2 if self.is_double_h else 1
        height = 2 if self.is_double_v else 1
        cells: list[tuple[int, int, int]] = []
        step = 0
        for row in range(height):
            for col in range(width):
                cells.append((-col, -row, tile_num - step))
                step += 1
        return cells

    # --- D_B3EF (u6.h TILE_FLAG2_*) ---
    @property
    def is_warm(self) -> bool:
        """Visible in the dark under an infravision effect."""
        return bool(self.extra & 0x01)

    @property
    def is_supporting(self) -> bool:
        """Other objects can be placed on top of this one (e.g. tables)."""
        return bool(self.extra & 0x02)

    @property
    def is_breakthrough(self) -> bool:
        """Forces the underlying maptile passable when this object tile is present."""
        return bool(self.extra & 0x04)

    @property
    def is_generic(self) -> bool:
        """"Ge" in Nuvie's docs -- decompiled source comments it as replicate/vanish-able."""
        return bool(self.extra & 0x08)

    @property
    def is_ignored_on_look(self) -> bool:
        return bool(self.extra & 0x10)

    @property
    def is_background(self) -> bool:
        return bool(self.extra & 0x20)

    @property
    def article(self) -> int:
        """0-3, indexing :data:`ARTICLES` ("", "a", "an", "the")."""
        return (self.extra >> 6) & 0x03

    @property
    def article_word(self) -> str:
        return ARTICLES[self.article]


class U6TileFlags:
    """Parser for the flat, uncompressed ``TILEFLAG`` file."""

    NUM_TILES = 0x800
    NUM_WEIGHTED = 0x400
    TERRAIN_SIZE = 0x800
    FLAGS_SIZE = 0x800
    WEIGHT_SIZE = 0x400
    EXTRA_SIZE = 0x800
    TOTAL_SIZE = TERRAIN_SIZE + FLAGS_SIZE + WEIGHT_SIZE + EXTRA_SIZE  # 7168

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> list[U6TileFlagEntry]:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> list[U6TileFlagEntry]:
        if len(data) < cls.TOTAL_SIZE:
            raise U6TileFlagsError(
                f"TILEFLAG data too short: {len(data)} bytes, need at least {cls.TOTAL_SIZE}"
            )

        terrain_end = cls.TERRAIN_SIZE
        flags_end = terrain_end + cls.FLAGS_SIZE
        weight_end = flags_end + cls.WEIGHT_SIZE
        extra_end = weight_end + cls.EXTRA_SIZE

        terrain = data[0:terrain_end]
        flags = data[terrain_end:flags_end]
        weight = data[flags_end:weight_end]
        extra = data[weight_end:extra_end]

        return [
            U6TileFlagEntry(
                tile_num=i,
                terrain=terrain[i],
                flags=flags[i],
                weight=weight[i] if i < cls.NUM_WEIGHTED else 0,
                extra=extra[i],
            )
            for i in range(cls.NUM_TILES)
        ]
