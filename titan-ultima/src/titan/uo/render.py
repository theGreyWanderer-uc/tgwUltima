"""Isometric rendering of UO facets from terrain, statics, art and texmaps.

Projection, land stretching and draw order follow the uo-client software
renderer (MIT; ``uo-client/src/render/Renderer.cpp``), whose ordering notes
cite the original client. Hue indexing, partial hue, the never-drawn tile
rules and stretched-land lighting follow ClassicUO (BSD-2;
``HuesLoader.GetColor16``, ``GameObject.CanBeDrawn``, ``Land.AllowedToDraw``,
``Land.CalculateNormal`` and ``IsometricWorld.fx`` ``get_light``).
"""

from __future__ import annotations

__all__ = [
    "UOArtSource",
    "UOHueTable",
    "UOMapRenderer",
    "UOTexmapSource",
]

from dataclasses import dataclass
from functools import cmp_to_key
import math
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from titan.uo.hue import UOHuesFile
from titan.uo.map import BLOCK_BYTES, UOMap
from titan.uo.tiledata import UOTileData
from titan.uo.uop import UOPArchive, hash_uop_path

HALF_TILE = 22
TILE = 44
Z_STEP = 4
Z_PAD = 128 * Z_STEP  # reach of a signed-byte altitude
ART_PAD = 512  # allowance for tall or wide static art beyond its cell
# Global screen space: room above row 0 for high z and tall art, below for low z.
SCREEN_TOP_PAD = Z_PAD + ART_PAD
SCREEN_BOTTOM_PAD = Z_PAD

FLAG_BACKGROUND = 0x00000001
FLAG_TRANSLUCENT = 0x00000008
FLAG_WALL = 0x00000010
FLAG_IMPASSABLE = 0x00000040
FLAG_SURFACE = 0x00000200
FLAG_BRIDGE = 0x00000400
FLAG_WINDOW = 0x00001000
FLAG_FOLIAGE = 0x00020000
FLAG_PARTIAL_HUE = 0x00040000
FLAG_NO_DIAGONAL = 0x02000000
FLAG_ROOF = 0x10000000

_NEVER_DRAWN_STATICS = frozenset(
    (0x0001, 0x21BC, 0xA1FE, 0xA1FF, 0xA200, 0xA201, *range(0x2198, 0x21A5))
)
_BACKGROUND_OR_SURFACE_HIDDEN = frozenset((0x9E4C, 0x9E64, 0x9E65, 0x9E7D))

# ClassicUO IsometricWorld.fx: LIGHT_DIRECTION (0, 1, 1); Brightlight is
# TerrainShadowsLevel * 0.1 with the profile default of 15.
_LIGHT = (0.0, 1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0))
_BRIGHTLIGHT = 1.5
_FLAT_LIGHT_BASE = 0.85355339
_LIGHT_QUANTUM = 64
# ClassicUO GameSceneDrawingSorting: Translucent statics draw at AlphaHue 178.
TRANSLUCENT_ALPHA = 178 / 255

# Per-renderer cache caps. Lit terrain quads are keyed by corner heights and
# lights, so a whole-facet render would otherwise grow without bound.
_QUAD_CACHE_LIMIT = 8000
_STATIC_CACHE_LIMIT = 12000

# Diamond positions of the 1,012 stored land-art pixels, in file order.
_LAND_YS: list[int] = []
_LAND_XS: list[int] = []
for _y in range(22):
    for _x in range(21 - _y, 23 + _y):
        _LAND_YS.append(_y)
        _LAND_XS.append(_x)
for _y in range(22):
    for _x in range(_y, 44 - _y):
        _LAND_YS.append(_y + 22)
        _LAND_XS.append(_x)
_LAND_INDEX = (np.array(_LAND_YS), np.array(_LAND_XS))
del _x, _y, _LAND_YS, _LAND_XS

_EXPAND_5BIT = np.array([(v << 3) | (v >> 2) for v in range(32)], dtype=np.uint8)
_COLOR16_RGB = np.stack(
    [
        _EXPAND_5BIT[(np.arange(0x10000) >> 10) & 0x1F],
        _EXPAND_5BIT[(np.arange(0x10000) >> 5) & 0x1F],
        _EXPAND_5BIT[np.arange(0x10000) & 0x1F],
    ],
    axis=1,
)


class UOArtSource:
    """Lazily decoded land and static art as ``uint16`` arrays (0 = transparent)."""

    def __init__(self, reader) -> None:
        self._reader = reader
        self._land: dict[int, np.ndarray | None] = {}
        self._static: dict[int, np.ndarray | None] = {}

    @classmethod
    def from_client(cls, client: str | Path) -> UOArtSource:
        client = Path(client)
        uop = client / "artLegacyMUL.uop"
        if uop.is_file():
            archive = UOPArchive(uop)

            def read_uop(index: int) -> bytes | None:
                entry = archive.entries_by_hash.get(
                    hash_uop_path(f"build/artlegacymul/{index:08d}.tga")
                )
                return None if entry is None else archive.read_entry(entry)

            return cls(read_uop)

        mul, idx = client / "art.mul", client / "artidx.mul"
        if mul.is_file() and idx.is_file():
            return cls(_MulIndexReader(mul, idx))
        raise FileNotFoundError("artLegacyMUL.uop or art.mul/artidx.mul not found")

    def land(self, tile_id: int) -> np.ndarray | None:
        if tile_id not in self._land:
            self._land[tile_id] = self._decode_land(self._reader(tile_id))
        return self._land[tile_id]

    def static(self, tile_id: int) -> np.ndarray | None:
        if tile_id not in self._static:
            self._static[tile_id] = self._decode_static(self._reader(0x4000 + tile_id))
        return self._static[tile_id]

    @staticmethod
    def _decode_land(data: bytes | None) -> np.ndarray | None:
        if not data or len(data) < 1012 * 2:
            return None
        pixels = np.zeros((TILE, TILE), dtype=np.uint16)
        pixels[_LAND_INDEX] = np.frombuffer(data, dtype="<u2", count=1012)
        return pixels

    @staticmethod
    def _decode_static(data: bytes | None) -> np.ndarray | None:
        if not data or len(data) < 8:
            return None
        width, height = struct.unpack_from("<hh", data, 4)
        if width <= 0 or height <= 0 or width > 2048 or height > 2048:
            return None
        table_end = 8 + height * 2
        if table_end > len(data):
            return None
        words = np.frombuffer(data, dtype="<u2", count=len(data) // 2)
        row_offsets = words[4 : 4 + height]
        base = table_end // 2
        pixels = np.zeros((height, width), dtype=np.uint16)
        for y in range(height):
            pos = base + int(row_offsets[y])
            x = 0
            while pos + 2 <= len(words):
                skip, run = int(words[pos]), int(words[pos + 1])
                pos += 2
                if skip == 0 and run == 0:
                    break
                x += skip
                if x + run > width or pos + run > len(words):
                    return None
                pixels[y, x : x + run] = words[pos : pos + run]
                pos += run
                x += run
        return pixels


class UOTexmapSource:
    """Lazily read ``texmaps.mul`` land textures as square ``uint16`` arrays."""

    def __init__(self, mul: Path, idx: Path) -> None:
        self._reader = _MulIndexReader(mul, idx)
        self._cache: dict[int, np.ndarray | None] = {}

    @classmethod
    def from_client(cls, client: str | Path) -> UOTexmapSource | None:
        client = Path(client)
        mul, idx = client / "texmaps.mul", client / "texidx.mul"
        if mul.is_file() and idx.is_file():
            return cls(mul, idx)
        return None

    def get(self, texture_id: int) -> np.ndarray | None:
        if texture_id not in self._cache:
            data = self._reader(texture_id)
            texture = None
            if data:
                size = 128 if len(data) >= 128 * 128 * 2 else 64
                if len(data) >= size * size * 2:
                    texture = np.frombuffer(
                        data, dtype="<u2", count=size * size
                    ).reshape(size, size)
            self._cache[texture_id] = texture
        return self._cache[texture_id]


class _MulIndexReader:
    """Read single entries from an IDX/MUL pair on demand."""

    def __init__(self, mul: Path, idx: Path) -> None:
        self._index = idx.read_bytes()
        self._mul = mul
        self._size = mul.stat().st_size

    def __call__(self, index: int) -> bytes | None:
        if index < 0 or (index + 1) * 12 > len(self._index):
            return None
        lookup, length, _extra = struct.unpack_from("<III", self._index, index * 12)
        if lookup == 0xFFFFFFFF or length == 0 or lookup + length > self._size:
            return None
        with self._mul.open("rb") as stream:
            stream.seek(lookup)
            return stream.read(length)


class UOHueTable:
    """Hue ramps for remapping art; client hue ``h`` uses ``hues.mul`` entry ``h - 1``."""

    def __init__(self, hues: UOHuesFile) -> None:
        ramps = np.array([hue.colors for hue in hues.hues], dtype=np.uint16) & 0x7FFF
        ramps[ramps == 0] = 1
        self.ramps = ramps

    def apply(self, pixels: np.ndarray, hue: int, *, partial: bool) -> np.ndarray:
        hue &= 0x3FFF
        if hue == 0 or hue > len(self.ramps):
            return pixels
        red = (pixels >> 10) & 0x1F
        mapped = self.ramps[hue - 1][red]
        target = pixels != 0
        if partial:
            target &= (red == ((pixels >> 5) & 0x1F)) & (red == (pixels & 0x1F))
        return np.where(target, mapped, pixels).astype(np.uint16)


@dataclass
class _Draw:
    z: int
    priority: bool
    pixels: np.ndarray  # (h, w, 3) uint8 RGB
    mask: np.ndarray  # (h, w) bool
    dx: int
    dy: int
    foliage: bool = False
    surface: bool = False
    occluder: bool = False
    height: int = 0
    alpha: float = 1.0


def _surface_inside_occluder(floor: _Draw, wall: _Draw) -> bool:
    return (
        floor.surface
        and wall.occluder
        and wall.height > 0
        and wall.z < floor.z < wall.z + wall.height
    )


def _compare_in_cell(a: _Draw, b: _Draw) -> int:
    """uo-client's within-cell order (cells themselves go back to front)."""
    if a.foliage != b.foliage:
        return -1 if b.foliage else 1
    if _surface_inside_occluder(a, b):
        return -1
    if _surface_inside_occluder(b, a):
        return 1
    if a.z != b.z:
        return -1 if a.z < b.z else 1
    if a.priority != b.priority:
        return -1 if a.priority else 1
    if a.height != b.height:
        return -1 if a.height < b.height else 1
    return 0


_CELL_ORDER = cmp_to_key(_compare_in_cell)


class UOMapRenderer:
    """Render a screen-sized isometric view of a facet."""

    def __init__(
        self,
        facet: UOMap,
        art: UOArtSource,
        tiledata: UOTileData,
        *,
        texmaps: UOTexmapSource | None = None,
        hues: UOHueTable | None = None,
    ) -> None:
        self.map = facet
        self.art = art
        self.tiledata = tiledata
        self.texmaps = texmaps
        self.hues = hues
        self._land_blocks = np.frombuffer(facet.land, dtype=np.uint8).reshape(
            facet.block_count, BLOCK_BYTES
        )
        self._quad_cache: dict[tuple, tuple[np.ndarray, np.ndarray, int, int] | None] = {}
        self._land_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._static_cache: dict[
            tuple[int, int, bool], tuple[np.ndarray, np.ndarray] | None
        ] = {}

    @classmethod
    def from_client(
        cls, client: str | Path, facet: UOMap, *, hues: bool = True
    ) -> UOMapRenderer:
        client = Path(client)
        hue_table = None
        if hues and (client / "hues.mul").is_file():
            hue_table = UOHueTable(UOHuesFile.from_file(client / "hues.mul"))
        return cls(
            facet,
            UOArtSource.from_client(client),
            UOTileData.from_file(client / "tiledata.mul"),
            texmaps=UOTexmapSource.from_client(client),
            hues=hue_table,
        )

    # -- public ----------------------------------------------------------

    def facet_screen_size(self) -> tuple[int, int]:
        """Pixel size of the whole facet in global screen coordinates."""
        span = (self.map.width + self.map.height) * HALF_TILE
        return span, span + SCREEN_TOP_PAD + SCREEN_BOTTOM_PAD

    def render(
        self,
        center_x: int,
        center_y: int,
        width: int,
        height: int,
        *,
        center_z: int | None = None,
        statics: bool = True,
        roofs: bool = True,
        shading: bool = True,
    ) -> Image.Image:
        """Render ``width`` x ``height`` pixels centred on cell ``(center_x, center_y)``.

        ``center_z`` defaults to the land altitude at the centre cell.
        ``roofs=False`` drops statics with the tiledata Roof flag.
        ``shading=False`` draws stretched land without normal lighting.
        """
        facet = self.map
        if center_z is None:
            center_z = facet.land_tile(
                min(max(center_x, 0), facet.width - 1),
                min(max(center_y, 0), facet.height - 1),
            ).z
        origin_x = width // 2 - (center_x - center_y) * HALF_TILE
        origin_y = (
            height // 2 + center_z * Z_STEP - HALF_TILE - (center_x + center_y) * HALF_TILE
        )
        return self._render(origin_x, origin_y, width, height, statics, roofs, shading)

    def render_window(
        self,
        left: int,
        top: int,
        width: int,
        height: int,
        *,
        statics: bool = True,
        roofs: bool = True,
        shading: bool = True,
    ) -> Image.Image:
        """Render a window of the facet's global screen space.

        Cell ``(x, y)``'s north vertex at ``z = 0`` sits at global pixel
        ``((x - y + map.height) * 22, (x + y) * 22 + SCREEN_TOP_PAD)``, so the
        whole facet spans :meth:`facet_screen_size`.
        """
        origin_x = self.map.height * HALF_TILE - left
        origin_y = SCREEN_TOP_PAD - top
        return self._render(origin_x, origin_y, width, height, statics, roofs, shading)

    # -- core ------------------------------------------------------------

    def _render(self, origin_x, origin_y, width, height, statics, roofs, shading) -> Image.Image:
        """Draw cells whose north vertex is ``(origin_x + (x-y)*22, origin_y + (x+y)*22)``."""
        facet = self.map
        # Diagonal bands (s = x + y, d = x - y) that can reach the window,
        # padded for altitude and for tall or wide static art.
        s_min = (-origin_y - TILE - Z_PAD - ART_PAD) // HALF_TILE
        s_max = (height - origin_y + Z_PAD + ART_PAD) // HALF_TILE + 1
        d_min = (-origin_x - HALF_TILE - ART_PAD) // HALF_TILE
        d_max = (width - origin_x + HALF_TILE + ART_PAD) // HALF_TILE + 1
        min_x = max(0, (s_min + d_min) // 2)
        max_x = min(facet.width - 1, (s_max + d_max) // 2 + 1)
        min_y = max(0, (s_min - d_max) // 2)
        max_y = min(facet.height - 1, (s_max - d_min) // 2 + 1)
        if min_x > max_x or min_y > max_y:
            return Image.new("RGB", (width, height))

        def in_band(x: int, y: int) -> bool:
            return s_min <= x + y <= s_max and d_min <= x - y <= d_max

        land_ids, land_z, gx0, gy0 = self._land_window(
            min_x - 2, min_y - 2, max_x + 3, max_y + 3
        )

        def z_at(x: int, y: int) -> int:
            gx, gy = x - gx0, y - gy0
            if 0 <= gy < land_z.shape[0] and 0 <= gx < land_z.shape[1]:
                return int(land_z[gy, gx])
            return 0

        cells: dict[tuple[int, int], list[_Draw]] = {}

        for wy in range(min_y, max_y + 1):
            for wx in range(min_x, max_x + 1):
                sx = origin_x + (wx - wy) * HALF_TILE
                sy = origin_y + (wx + wy) * HALF_TILE
                if sx + HALF_TILE < 0 or sx - HALF_TILE >= width:
                    continue
                if sy + TILE + Z_PAD < 0 or sy - Z_PAD >= height:
                    continue
                tile_id = int(land_ids[wy - gy0, wx - gx0])
                draw = self._land_draw(tile_id, wx, wy, sx, sy, z_at, shading)
                if draw is not None:
                    cells.setdefault((wx, wy), []).append(draw)

        if statics:
            for bx in range(min_x // 8, max_x // 8 + 1):
                for by in range(min_y // 8, max_y // 8 + 1):
                    for item in facet.statics_block(bx, by):
                        if not in_band(item.x, item.y):
                            continue
                        draw = self._static_draw(item, origin_x, origin_y, roofs)
                        if draw is None:
                            continue
                        h, w = draw.mask.shape
                        if (
                            draw.dx >= width
                            or draw.dy >= height
                            or draw.dx + w <= 0
                            or draw.dy + h <= 0
                        ):
                            continue
                        cells.setdefault((item.x, item.y), []).append(draw)

        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        for cell in sorted(cells, key=lambda c: (c[0] + c[1], c[0] - c[1])):
            for draw in sorted(cells[cell], key=_CELL_ORDER):
                _blit(canvas, draw)
        return Image.fromarray(canvas)

    # -- land ------------------------------------------------------------

    def _land_window(
        self, x0: int, y0: int, x1: int, y1: int
    ) -> tuple[np.ndarray, np.ndarray, int, int]:
        """Land IDs and altitudes for an inclusive cell rectangle, clipped to the facet."""
        facet = self.map
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(facet.width - 1, x1), min(facet.height - 1, y1)
        bx0, bx1, by0, by1 = x0 // 8, x1 // 8, y0 // 8, y1 // 8
        bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
        block_ids = (
            np.arange(bx0, bx1 + 1)[:, None] * facet.blocks_high
            + np.arange(by0, by1 + 1)[None, :]
        )
        cells = self._land_blocks[block_ids.ravel()][:, 4:].reshape(bw, bh, 8, 8, 3)
        cells = cells.transpose(1, 2, 0, 3, 4).reshape(bh * 8, bw * 8, 3)
        ids = cells[..., 0].astype(np.uint16) | (cells[..., 1].astype(np.uint16) << 8)
        z = cells[..., 2].view(np.int8)
        oy, ox = y0 - by0 * 8, x0 - bx0 * 8
        rows, cols = slice(oy, oy + y1 - y0 + 1), slice(ox, ox + x1 - x0 + 1)
        return ids[rows, cols], z[rows, cols], x0, y0

    def _land_draw(self, tile_id, wx, wy, sx, sy, z_at, shading) -> _Draw | None:
        if tile_id <= 2:
            return None
        art = self.art.land(tile_id)
        if art is None:
            return None
        z0, z1, z2, z3 = (
            z_at(wx, wy),
            z_at(wx + 1, wy),
            z_at(wx + 1, wy + 1),
            z_at(wx, wy + 1),
        )
        flat = z0 == z1 == z2 == z3
        texture_id = (
            self.tiledata.land[tile_id].texture_id
            if tile_id < len(self.tiledata.land)
            else 0
        )
        texture = self.texmaps.get(texture_id) if self.texmaps and texture_id else None

        # uo-client: art when flat and (untextured or the 4x4 neighbourhood is
        # level); otherwise a stretched texmap quad.
        use_art = flat
        if use_art and texture is not None:
            use_art = all(
                z_at(nx, ny) == z0
                for ny in range(wy - 1, wy + 3)
                for nx in range(wx - 1, wx + 3)
            )

        lights = None
        if texture is None or use_art:
            if flat:
                cached = self._land_cache.get(tile_id)
                if cached is None:
                    cached = (_COLOR16_RGB[art], art != 0)
                    self._land_cache[tile_id] = cached
                return _Draw(
                    z=z0,
                    priority=True,
                    pixels=cached[0],
                    mask=cached[1],
                    dx=sx - HALF_TILE,
                    dy=sy - z0 * Z_STEP,
                )
            key = ("art", tile_id, z1 - z0, z2 - z0, z3 - z0)
            uv = ((22, 0), (43, 22), (22, 43), (0, 22))
            source, transparent = art, True
        else:
            hi = texture.shape[0] - 1
            if shading:
                lights = _corner_lights(wx, wy, z_at)
            key = ("tex", texture_id, z1 - z0, z2 - z0, z3 - z0, lights)
            uv = ((0, 0), (hi, 0), (hi, hi), (0, hi))
            source, transparent = texture, False

        if key not in self._quad_cache:
            if len(self._quad_cache) >= _QUAD_CACHE_LIMIT:
                self._quad_cache.clear()
            self._quad_cache[key] = _rasterize_quad(
                source, transparent, z1 - z0, z2 - z0, z3 - z0, uv, lights
            )
        patch = self._quad_cache[key]
        if patch is None:
            return None
        pixels, mask, ox, oy = patch
        return _Draw(
            z=(z0 + z1 + z2 + z3) >> 2,
            priority=True,
            pixels=pixels,
            mask=mask,
            dx=sx + ox,
            dy=sy - z0 * Z_STEP + oy,
        )

    # -- statics ---------------------------------------------------------

    def _static_draw(self, item, origin_x, origin_y, roofs) -> _Draw | None:
        tile_id = item.tile_id
        info = (
            self.tiledata.statics[tile_id]
            if tile_id < len(self.tiledata.statics)
            else None
        )
        if not _can_draw_static(tile_id, info):
            return None
        flags = info.flags if info else 0
        if not roofs and flags & FLAG_ROOF:
            return None

        hue = (item.hue & 0x3FFF) if self.hues is not None else 0
        partial = bool(flags & FLAG_PARTIAL_HUE)
        key = (tile_id, hue, partial)
        if key not in self._static_cache:
            if len(self._static_cache) >= _STATIC_CACHE_LIMIT:
                self._static_cache.clear()
            raw = self.art.static(tile_id)
            if raw is None:
                self._static_cache[key] = None
            else:
                hued = self.hues.apply(raw, hue, partial=partial) if hue else raw
                self._static_cache[key] = (_COLOR16_RGB[hued], raw != 0)
        cached = self._static_cache[key]
        if cached is None:
            return None
        pixels, mask = cached

        sx = origin_x + (item.x - item.y) * HALF_TILE
        sy = origin_y + (item.x + item.y) * HALF_TILE - item.z * Z_STEP
        surface = bool(flags & (FLAG_SURFACE | FLAG_BRIDGE))
        return _Draw(
            z=item.z,
            priority=False,
            pixels=pixels,
            mask=mask,
            dx=sx - mask.shape[1] // 2,
            dy=sy + TILE - mask.shape[0],
            foliage=bool(flags & FLAG_FOLIAGE),
            surface=surface,
            occluder=not surface
            and bool(flags & (FLAG_WALL | FLAG_IMPASSABLE | FLAG_WINDOW)),
            height=info.height if info else 0,
            alpha=TRANSLUCENT_ALPHA if flags & FLAG_TRANSLUCENT else 1.0,
        )


def _can_draw_static(tile_id: int, info) -> bool:
    """ClassicUO ``GameObject.CanBeDrawn`` for map statics."""
    if tile_id in _NEVER_DRAWN_STATICS:
        return False
    if info is None:
        return True
    if tile_id in _BACKGROUND_OR_SURFACE_HIDDEN:
        return not info.flags & (FLAG_BACKGROUND | FLAG_SURFACE)
    if info.name.lower().startswith("nodraw"):
        return False
    return not info.flags & FLAG_NO_DIAGONAL


def _blit(canvas: np.ndarray, draw: _Draw) -> None:
    h, w = draw.mask.shape
    x0, y0 = max(draw.dx, 0), max(draw.dy, 0)
    x1, y1 = min(draw.dx + w, canvas.shape[1]), min(draw.dy + h, canvas.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    rows = slice(y0 - draw.dy, y1 - draw.dy)
    cols = slice(x0 - draw.dx, x1 - draw.dx)
    mask = draw.mask[rows, cols]
    region = canvas[y0:y1, x0:x1]
    src = draw.pixels[rows, cols][mask]
    if draw.alpha >= 1.0:
        region[mask] = src
    else:
        dst = region[mask].astype(np.float32)
        region[mask] = (dst + (src - dst) * draw.alpha + 0.5).astype(np.uint8)


def _light_for_normal(normal: tuple[float, float, float]) -> float:
    base = max(sum(n * l for n, l in zip(normal, _LIGHT)), 0.0) / 2.0 + 0.5
    offset = base - _FLAT_LIGHT_BASE
    return base + _BRIGHTLIGHT * offset - offset


def _vertex_normal(tile, top, right, bottom, left) -> tuple[float, float, float]:
    """ClassicUO ``Land.CalculateNormal``: normalized sum of four face normals."""
    if tile == top == right == bottom == left:
        return (0.0, 0.0, 1.0)

    def cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    # (v, u) pairs; each face contributes cross(v, u).
    faces = (
        ((-22, 22, (bottom - tile) * 4), (-22, -22, (left - tile) * 4)),
        ((22, 22, (right - tile) * 4), (-22, 22, (bottom - tile) * 4)),
        ((22, -22, (top - tile) * 4), (22, 22, (right - tile) * 4)),
        ((-22, -22, (left - tile) * 4), (22, -22, (top - tile) * 4)),
    )
    total = [0.0, 0.0, 0.0]
    for v, u in faces:
        c = cross(v, u)
        total = [total[i] + c[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in total)) or 1.0
    return (total[0] / length, total[1] / length, total[2] / length)


def _corner_lights(wx, wy, z_at) -> tuple[int, ...]:
    """Quantized light factors at the N, E, S, W corners of a stretched quad."""
    z = z_at(wx, wy)
    t10, t20 = z_at(wx, wy - 1), z_at(wx + 1, wy - 1)
    t01, t21, t31 = z_at(wx - 1, wy), z_at(wx + 1, wy), z_at(wx + 2, wy)
    t02, t12 = z_at(wx - 1, wy + 1), z_at(wx, wy + 1)
    t22, t32 = z_at(wx + 1, wy + 1), z_at(wx + 2, wy + 1)
    t13, t23 = z_at(wx, wy + 2), z_at(wx + 1, wy + 2)
    normals = (
        _vertex_normal(z, t10, t21, t12, t01),  # N corner (ClassicUO top)
        _vertex_normal(t21, t20, t31, t22, z),  # E corner (right)
        _vertex_normal(t22, t21, t32, t23, t12),  # S corner (bottom)
        _vertex_normal(t12, z, t22, t13, t02),  # W corner (left)
    )
    return tuple(round(_light_for_normal(n) * _LIGHT_QUANTUM) for n in normals)


def _rasterize_quad(source, transparent, dz1, dz2, dz3, uv, lights=None):
    """Rasterize a land quad relative to its north corner at (0, 0).

    Corners: N (0, 0), E (22, 22 - dz1*4), S (0, 44 - dz2*4), W (-22, 22 - dz3*4),
    drawn as triangles N-E-S and N-S-W with nearest-texel sampling (uo-client
    ``TexTri``). ``lights`` holds quantized N/E/S/W light factors, interpolated
    across each triangle. Returns ``(rgb, mask, ox, oy)`` or ``None``.
    """
    corners = (
        (0, 0),
        (HALF_TILE, HALF_TILE - dz1 * Z_STEP),
        (0, TILE - dz2 * Z_STEP),
        (-HALF_TILE, HALF_TILE - dz3 * Z_STEP),
    )
    ox = min(c[0] for c in corners)
    oy = min(c[1] for c in corners)
    w = max(c[0] for c in corners) - ox + 1
    h = max(c[1] for c in corners) - oy + 1
    py, px = np.mgrid[oy : oy + h, ox : ox + w]
    pixels = np.zeros((h, w), dtype=np.uint16)
    shade = np.ones((h, w), dtype=np.float32)
    mask = np.zeros((h, w), dtype=bool)
    tex_h, tex_w = source.shape
    for a, b, c in ((0, 1, 2), (0, 2, 3)):
        (ax, ay), (bx, by), (cx, cy) = corners[a], corners[b], corners[c]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if area == 0:
            continue
        w0 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
        w1 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
        w2 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        if area > 0:
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        else:
            inside = (w0 <= 0) & (w1 <= 0) & (w2 <= 0)
        if not inside.any():
            continue
        (au, av), (bu, bv), (cu, cv) = uv[a], uv[b], uv[c]
        u = np.clip(((w0 * au + w1 * bu + w2 * cu) / area + 0.5).astype(np.int64), 0, tex_w - 1)
        v = np.clip(((w0 * av + w1 * bv + w2 * cv) / area + 0.5).astype(np.int64), 0, tex_h - 1)
        texels = source[v, u]
        hit = inside & (texels != 0) if transparent else inside
        pixels[hit] = texels[hit]
        if lights is not None:
            la, lb, lc = (lights[i] / _LIGHT_QUANTUM for i in (a, b, c))
            shade[hit] = ((w0 * la + w1 * lb + w2 * lc) / area)[hit]
        mask |= hit
    if not mask.any():
        return None
    rgb = _COLOR16_RGB[pixels]
    if lights is not None:
        rgb = np.clip(rgb * shade[..., None] + 0.5, 0, 255).astype(np.uint8)
    return rgb, mask, ox, oy
