"""
Tile graphics decoder for Ultima 6.

U6 has 0x800 16x16-pixel tiles: the first 0x200 in ``MAPTILES.VGA`` (LZW-
compressed), the remaining 0x600 in ``OBJTILES.VGA`` (raw). Which of three
storage formats each tile uses is given by the per-tile byte in
``MASKTYPE.VGA`` (LZW-compressed; only its first 0x800 bytes are the format
table -- u6data/u6tech.txt notes the remaining ~1920 bytes are unidentified,
matched exactly by a real decompressed MASKTYPE.VGA at 3968 bytes):

    0x00 "plain"       -- fixed 256 bytes, no transparency
    0x05 "transparent" -- fixed 256 bytes, 0xFF pixels are transparent
    0x0A "pixel blocks" -- variable length, RLE-style runs (see below)

``TILEINDX.VGA`` is documented in u6tech.txt as an LZW-compressed lookup
table of byte offsets into the concatenated maptiles+objtiles buffer. Two
things about that turned out to be wrong, checked directly against a real
GOG-style install: it is *not* LZW-compressed (4096 raw bytes = 0x800 words
exactly, and fails the LZW magic-number check), and it is not actually
needed for a straight-through extraction -- tiles are stored back-to-back
in tile-number order with no gaps, so sequentially scanning by each tile's
MASKTYPE-declared length lands on byte-identical offsets to
``tileindx[i] * 16`` for all 0x800 tiles (verified exactly, zero
mismatches). :func:`read_tile_index` is provided for cross-checking, but
:class:`U6Tiles` doesn't need it.

Pixel-blocks decoding (the format u6data/u6tech.txt is least certain
about) is ported from pu6e's ``tile.py``, with one correction: pu6e's own
slice assignment (``tiledata[tileidx:runlength] = run``) writes at the
wrong position whenever ``tileidx > runlength``, which is true for nearly
every run after the first; replaced here with the evidently-intended
``tile[cursor:cursor + run_length]``. The cursor-advance math itself (mod
160, +160 correction band above displacement 1760) is unchanged from
pu6e and has been validated end to end: decoding all 1432 real
pixel-blocks tiles in a genuine install produces zero out-of-bounds
writes, and rendering them with the real in-game palette produces clean,
correctly-bounded, recognizable game art (armor, weapons, books,
furniture, virtue runes, etc.) with no garbled or shifted pixels.

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL or unlicensed source.

Animated tiles (``ANIMDATA``)
------------------------------

Some tile numbers referenced by ``CHUNKS`` are never meant to be drawn
directly: they're placeholders that the real game continuously redirects
to whichever tile currently holds the "active frame" of an animation
(water, fountains, flags, etc. -- see u6data/u6tech.txt's "Multiple
Animation Frames" section). This was discovered the hard way: rendering
tiles 8-15 raw (their real, verified content -- masktype 0x0A,
100%-transparent, no bug here) produced flat white squares scattered
through what should have been a river, because a 100%-transparent tile
under ``to_pil_image(transparent=False)`` falls back to whatever color
sits at palette index 255 (confirmed white in the real ``U6PAL``).
Rendering the tiles their frame actually points at instead (tiles
448-455 for placeholder 8, confirmed directly against a real install)
shows the correct animated blue water. Nuvie's ``TileManager.cpp``
implements the same substitution loop as ``u6tech.txt``'s pseudocode,
confirming both the algorithm and that no other special-casing (palette
cycling doesn't touch this range either; confirmed against Nuvie's
``GamePalette.cpp``, whose cycled ranges are exactly u6tech.txt's
0xE0-0xFB and nowhere near these tile numbers) is needed on top of it.

:class:`U6AnimData` resolves the substitution; feed its output through
:func:`titan.u6.map.render_tile_grid`'s ``animdata``/``tick`` parameters,
or call :meth:`U6AnimData.resolve_grid` directly on a tile-number grid
before rendering.

Example::

    from titan.u6.tile import U6Tiles
    from titan.u6.palette import U6Palette

    tiles = U6Tiles.from_directory("C:/Ultima/Ultima6")
    palette = U6Palette.from_file("C:/Ultima/Ultima6/U6PAL")
    tiles.to_pil_image(600, palette).save("tile_600.png")
"""

from __future__ import annotations

__all__ = [
    "U6Tiles",
    "U6TilesError",
    "read_tile_index",
    "U6AnimData",
    "U6AnimEntry",
    "MASKTYPE_PLAIN",
    "MASKTYPE_TRANSPARENT",
    "MASKTYPE_PIXELBLOCKS",
]

import os
import struct
from dataclasses import dataclass

import numpy as np
from PIL import Image

from titan.u6.lzw import U6Lzw

MASKTYPE_PLAIN = 0x00
MASKTYPE_TRANSPARENT = 0x05
MASKTYPE_PIXELBLOCKS = 0x0A

NUM_TILES = 0x800
TILE_DIM = 16
TILE_PIXELS = TILE_DIM * TILE_DIM
TRANSPARENT = 0xFF

# Cursor-advance constants for the "pixel blocks" format; see module docstring.
DISPLACEMENT_MODULUS = 160
DISPLACEMENT_WRAP_THRESHOLD = 1760
DISPLACEMENT_WRAP_CORRECTION = 160

# ANIMDATA struct layout: a u16 count, then four fixed-size 0x20-entry
# arrays regardless of how many entries are actually in use (matches the
# real 194-byte file: 2 + 32*2 + 32*2 + 32*1 + 32*1).
ANIMDATA_MAX_ENTRIES = 0x20


class U6TilesError(Exception):
    """Raised on malformed tile or masktype data."""


def read_tile_index(filepath: str | os.PathLike[str]) -> tuple[int, ...]:
    """
    Read TILEINDX.VGA: 0x800 raw, uncompressed little-endian words, each a
    16-byte-paragraph offset into the concatenated maptiles+objtiles buffer.

    Not needed by :class:`U6Tiles` (see module docstring); exposed for
    cross-checking and tooling.
    """
    with open(filepath, "rb") as f:
        data = f.read()
    count = len(data) // 2
    return struct.unpack(f"<{count}H", data[:count * 2])


class U6Tiles:
    """Decoder for U6's 16x16 tile graphics (MAPTILES.VGA + OBJTILES.VGA)."""

    def __init__(self, tiles: list[bytes]) -> None:
        self.tiles = tiles  # each: 256 bytes, row-major palette indices, 0xFF = transparent

    @property
    def num_tiles(self) -> int:
        return len(self.tiles)

    @classmethod
    def from_directory(cls, dirpath: str | os.PathLike[str]) -> U6Tiles:
        """Load MASKTYPE.VGA, MAPTILES.VGA, and OBJTILES.VGA from a game directory."""
        def p(name: str) -> str:
            return os.path.join(dirpath, name)

        masktype_raw = U6Lzw.decompress_file(p("MASKTYPE.VGA"))
        maptiles = U6Lzw.decompress_file(p("MAPTILES.VGA"))
        with open(p("OBJTILES.VGA"), "rb") as f:
            objtiles = f.read()
        return cls.from_parts(masktype_raw, maptiles, objtiles)

    @classmethod
    def from_parts(
        cls, masktype_raw: bytes, maptiles: bytes, objtiles: bytes, num_tiles: int = NUM_TILES
    ) -> U6Tiles:
        """
        Build from already-decoded MASKTYPE.VGA, MAPTILES.VGA (LZW-decoded),
        and OBJTILES.VGA (raw).

        ``num_tiles`` defaults to the real format's fixed 0x800 and only
        needs overriding in tests, where building a full-size synthetic
        MASKTYPE buffer for a handful of tiles under test would be
        needless bulk.
        """
        if len(masktype_raw) < num_tiles:
            raise U6TilesError(f"masktype data too short: {len(masktype_raw)} bytes, need {num_tiles}")
        masktypes = masktype_raw[:num_tiles]
        alltiles = maptiles + objtiles

        tiles: list[bytes] = []
        pos = 0
        for i in range(num_tiles):
            mt = masktypes[i]
            if mt in (MASKTYPE_PLAIN, MASKTYPE_TRANSPARENT):
                if pos + TILE_PIXELS > len(alltiles):
                    raise U6TilesError(f"tile {i}: fixed-format tile runs past end of data")
                tiles.append(alltiles[pos:pos + TILE_PIXELS])
                pos += TILE_PIXELS
            elif mt == MASKTYPE_PIXELBLOCKS:
                tile, consumed = cls._decode_pixelblock_tile(alltiles, pos, i)
                tiles.append(tile)
                pos += consumed
            else:
                raise U6TilesError(f"tile {i}: unknown masktype {mt:#x}")
        return cls(tiles)

    @staticmethod
    def _decode_pixelblock_tile(alltiles: bytes, start: int, tile_num: int) -> tuple[bytes, int]:
        """
        Decode one variable-length "pixel blocks" tile.

        Framing: one length byte (paragraphs, i.e. 16-byte units), then
        ``(displacement: u16, run_length: u8, pixels: run_length bytes)``
        records until a zero-length record, padded to the paragraph
        boundary with 0xED. See module docstring for the cursor-advance
        math and its provenance.
        """
        length_byte = alltiles[start]
        body_len = length_byte * 16 - 1
        body_start = start + 1
        body_end = body_start + body_len
        if body_end > len(alltiles):
            raise U6TilesError(f"tile {tile_num}: pixel-block body runs past end of data")

        tile = bytearray([TRANSPARENT] * TILE_PIXELS)
        p = body_start
        cursor = 0
        while p < body_end:
            if p + 3 > body_end:
                raise U6TilesError(f"tile {tile_num}: truncated pixel-block record")
            disp, run_length = struct.unpack_from("<HB", alltiles, p)
            p += 3
            if run_length == 0:
                break

            actual_add = disp % DISPLACEMENT_MODULUS
            if disp >= DISPLACEMENT_WRAP_THRESHOLD:
                actual_add += DISPLACEMENT_WRAP_CORRECTION
            cursor += actual_add
            end = cursor + run_length
            if cursor < 0 or end > TILE_PIXELS:
                raise U6TilesError(f"tile {tile_num}: pixel run [{cursor}:{end}] out of bounds")

            tile[cursor:end] = alltiles[p:p + run_length]
            p += run_length
            cursor = end

        return bytes(tile), body_end - start

    def get_tile(self, tile_num: int) -> bytes:
        """Return one tile's 256 raw palette-index bytes (row-major, 0xFF = transparent)."""
        return self.tiles[tile_num]

    def to_array(self, tile_num: int) -> np.ndarray:
        """Return one tile as a 16x16 uint8 array of palette indices (0xFF = transparent)."""
        return np.frombuffer(self.tiles[tile_num], dtype=np.uint8).reshape(TILE_DIM, TILE_DIM)

    def to_pil_image(self, tile_num: int, palette, transparent: bool = True) -> Image.Image:
        """
        Render one tile to a PIL Image using ``palette``
        (e.g. :class:`titan.u6.palette.U6Palette`).

        Args:
            transparent: If ``True`` (default), returns RGBA with 0xFF
                pixels at alpha=0. If ``False``, returns flat RGB.
        """
        arr = self.to_array(tile_num)
        indexed = Image.fromarray(arr, mode="P")
        indexed.putpalette(palette.to_flat_rgb())
        if not transparent:
            return indexed.convert("RGB")

        rgba = indexed.convert("RGBA")
        alpha = np.where(arr == TRANSPARENT, 0, 255).astype(np.uint8)
        rgba.putalpha(Image.fromarray(alpha, mode="L"))
        return rgba


@dataclass
class U6AnimEntry:
    """One ANIMDATA record: a placeholder tile and where its active frame lives."""

    placeholder_tile: int
    first_frame_tile: int
    and_mask: int
    shift: int

    def frame_for_tick(self, tick: int) -> int:
        """The 0-based frame index active at ``tick`` (a free-running counter)."""
        return (tick & self.and_mask) >> self.shift

    def resolve(self, tick: int) -> int:
        """The real tile number to draw in place of :attr:`placeholder_tile` at ``tick``."""
        return self.first_frame_tile + self.frame_for_tick(tick)


class U6AnimData:
    """
    Parser and resolver for ``ANIMDATA``'s tile-substitution table.

    Some CHUNKS-referenced tile numbers are pure placeholders (in the real
    game data, always 100%-transparent, content-free tiles -- see module
    docstring) that must be substituted with whichever tile currently
    holds their "active frame" before rendering, matching Nuvie's
    ``TileManager::updateTileAnim`` substitution loop and u6tech.txt's
    equivalent pseudocode.
    """

    def __init__(self, entries: list[U6AnimEntry]) -> None:
        self.entries = entries
        self._by_placeholder = {e.placeholder_tile: e for e in entries}

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U6AnimData:
        data = U6Lzw.decompress_file(filepath)
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> U6AnimData:
        n = ANIMDATA_MAX_ENTRIES
        num_entries = struct.unpack_from("<H", data, 0)[0]
        tile_to_animate = struct.unpack_from(f"<{n}H", data, 2)
        first_anim_frame = struct.unpack_from(f"<{n}H", data, 2 + n * 2)
        and_masks = struct.unpack_from(f"<{n}B", data, 2 + n * 2 + n * 2)
        shift_values = struct.unpack_from(f"<{n}B", data, 2 + n * 2 + n * 2 + n)

        entries = [
            U6AnimEntry(
                placeholder_tile=tile_to_animate[i],
                first_frame_tile=first_anim_frame[i],
                and_mask=and_masks[i],
                shift=shift_values[i],
            )
            for i in range(num_entries)
        ]
        return cls(entries)

    def resolve_tile(self, tile_num: int, tick: int = 0) -> int:
        """Return the tile number actually displayed for ``tile_num`` at ``tick``."""
        entry = self._by_placeholder.get(tile_num)
        return entry.resolve(tick) if entry is not None else tile_num

    def resolve_grid(self, grid: np.ndarray, tick: int = 0) -> np.ndarray:
        """
        Return a copy of ``grid`` with every animated placeholder tile
        substituted.

        Widens to ``uint16`` regardless of ``grid``'s own dtype: raw
        CHUNKS-derived grids are ``uint8`` (tile numbers 0-255), but
        substituted tile numbers can exceed 255 (e.g. water's frames run
        up to 511), which would silently wrap in a ``uint8`` array.
        """
        out = grid.astype(np.uint16)
        for entry in self.entries:
            out[grid == entry.placeholder_tile] = entry.resolve(tick)
        return out
