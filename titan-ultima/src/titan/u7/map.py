"""
Ultima 7 map renderer and sampler.

Provides :class:`U7MapRenderer` for rendering U7 maps (top-down oblique
projection with lift offset) and :class:`U7MapSampler` for colour-sampled
minimaps.

U7 world structure::

    12×12 superchunks → 192×192 chunks → 3072×3072 tiles
    Each tile = 8×8 pixels
    Each chunk = 16×16 tiles = 128×128 pixels
    Each superchunk = 16×16 chunks = 256×256 tiles

Data files::

    U7MAP       — 144 superchunks × 256 entries × 2 bytes (terrain indices)
    U7CHUNKS    — terrain definitions, 512 bytes each (16×16 tiles × 2 bytes)
    U7IFIXnn    — fixed objects per superchunk (Flex, 256 records, 4 bytes/obj)
    u7iregnn    — dynamic objects per superchunk (gamedat, variable-length)
    TFA.DAT     — type flag array (3 bytes/shape: flags + dims)
    SHAPES.VGA  — shape graphics (Flex archive)

Projection (Exult Get_shape_location)::

    Ground tile:  screenXY = tileXY * 8   (NW corner of tile)
    Object anchor: screenXY = (tileXY + 1) * 8 - 1 - 4 * lift
                 = tileXY * 8 + 7 - 4 * lift   (SE pixel of base tile)

This is a parallel oblique projection: X/Y are screen-aligned top-down,
Z (lift) shifts diagonally at 45°.  Object anchors are at the SE pixel
of their base tile, offset by +7 from the NW tile corner.

Example::

    from titan.u7.map import U7MapRenderer, U7MapSampler
    from titan.u7.palette import U7Palette

    pal = U7Palette.from_file("STATIC/PALETTES.FLX")
    renderer = U7MapRenderer("STATIC/")

    # Render superchunk 0x55 (Britain area)
    img = renderer.render_superchunk(0x55, pal, include_ireg="gamedat/")
    img.save("britain.png")
"""

from __future__ import annotations

__all__ = ["U7MapObject", "U7TileRectOverlay", "U7MapRenderer", "U7MapSampler"]

import os
import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
from titan.u7.palette import U7Palette
from titan.u7.typeflag import U7TypeFlags

# ---------------------------------------------------------------------------
# Constants (from exult_constants.h)
# ---------------------------------------------------------------------------
C_TILE_SIZE = 8                 # pixels per tile
C_TILES_PER_CHUNK = 16          # tiles per chunk dimension
C_CHUNKS_PER_SCHUNK = 16        # chunks per superchunk dimension
C_NUM_SCHUNKS = 12              # superchunks per dimension
C_NUM_CHUNKS = C_NUM_SCHUNKS * C_CHUNKS_PER_SCHUNK  # 192
C_NUM_TILES = C_TILES_PER_CHUNK * C_NUM_CHUNKS       # 3072
C_CHUNK_BYTES_V1 = C_TILES_PER_CHUNK * C_TILES_PER_CHUNK * 2  # 512
C_CHUNK_BYTES_V2 = C_TILES_PER_CHUNK * C_TILES_PER_CHUNK * 3  # 768

# Exult V2 extended chunks header (10 bytes)
_V2_CHUNKS_MAGIC = b"\xFF\xFF\xFF\xFF" b"exlt" b"\x00\x00"
_V2_CHUNKS_HDR_SIZE = 10

# ---------------------------------------------------------------------------
# Translucency — Exult xform blending (hardcoded fallback from shapeid.cc)
# ---------------------------------------------------------------------------
# 17 blend definitions: (R, G, B, alpha).  R/G/B are divided by 4 before use
# in Exult's create_trans_table; alpha is the blend factor (0-255).
_HARD_BLENDS = [
    (208, 216, 224, 192), (136, 44, 148, 198), (248, 252, 80, 211),
    (144, 148, 252, 247), (64, 216, 64, 201),  (204, 60, 84, 140),
    (144, 40, 192, 128),  (96, 40, 16, 128),   (100, 108, 116, 192),
    (68, 132, 28, 128),   (255, 208, 48, 64),  (28, 52, 255, 128),
    (8, 68, 0, 128),      (255, 8, 8, 118),    (255, 244, 248, 128),
    (56, 40, 32, 128),    (228, 224, 214, 82),
]
# Pre-compute RGBA blend colors (R/4, G/4, B/4, alpha)
_BLEND_RGBA = [(r >> 2, g >> 2, b >> 2, a) for r, g, b, a in _HARD_BLENDS]
_NUM_BLENDS = len(_BLEND_RGBA)
_XFSTART = 0xFF - _NUM_BLENDS  # 238 — first translucent pixel index


def _frame_to_rgba(
    fr: U7Shape.Frame,
    flat_rgb: bytes | list[int],
    *,
    has_translucency: bool = False,
) -> tuple[Image.Image, int, int]:
    """Convert a decoded U7Shape.Frame to ``(RGBA Image, xoff, yoff)``.

    Ground tiles are rendered fully opaque (no transparent index).
    RLE sprites treat pixel value 0xFF as transparent.
    Translucent shapes replace pixel values 238–254 with semi-transparent
    blend colours matching Exult's xform palette.
    """
    indexed = Image.fromarray(fr.pixels, mode="P")
    indexed.putpalette(flat_rgb)
    rgba = indexed.convert("RGBA")

    if fr.is_tile:
        # Terrain tiles: always fully opaque — Exult uses copy8 (no alpha)
        pass
    else:
        # RLE sprites: 0xFF marks pixels not covered by any span
        alpha = np.where(fr.pixels == 0xFF, 0, 255).astype(np.uint8)

        if has_translucency:
            arr = np.array(rgba)
            for i, (r, g, b, a) in enumerate(_BLEND_RGBA):
                mask = fr.pixels == (_XFSTART + i)
                if np.any(mask):
                    arr[mask, 0] = r
                    arr[mask, 1] = g
                    arr[mask, 2] = b
                    alpha[mask] = a
            rgba = Image.fromarray(arr, "RGBA")

        rgba.putalpha(Image.fromarray(alpha, mode="L"))

    return (rgba, fr.xoff, fr.yoff)


# ---------------------------------------------------------------------------
# MapObject — a resolved object ready for rendering
# ---------------------------------------------------------------------------
@dataclass
class U7MapObject:
    """A world object with absolute tile coordinates."""

    tx: int       # absolute tile X (0–3071)
    ty: int       # absolute tile Y (0–3071)
    tz: int       # lift / Z level (0–15)
    shape: int    # shape number
    frame: int    # frame number
    quality: int = 0

    # Screen coordinates (set during projection)
    screen_x: int = 0
    screen_y: int = 0


@dataclass(frozen=True)
class U7TileRectOverlay:
    """World-tile rectangle overlay for map rendering.

    Coordinates are absolute world tile coordinates (0-3071) and inclusive.
    """

    tx0: int
    ty0: int
    tx1: int
    ty1: int
    color: tuple[int, int, int, int]
    label: str | None = None

    def normalized(self) -> "U7TileRectOverlay":
        """Return a copy with ordered tile bounds."""
        nx0 = min(self.tx0, self.tx1)
        ny0 = min(self.ty0, self.ty1)
        nx1 = max(self.tx0, self.tx1)
        ny1 = max(self.ty0, self.ty1)
        return U7TileRectOverlay(nx0, ny0, nx1, ny1, self.color, self.label)


class U7MapRenderer:
    """
    Render Ultima 7 maps from STATIC data files.

    Handles terrain tiles (U7MAP + U7CHUNKS), fixed objects (U7IFIX),
    and optionally dynamic objects (u7ireg).

    Supports configurable view projections and typeflag-based filtering.
    """

    # ------------------------------------------------------------------
    # Projection views
    # ------------------------------------------------------------------
    # U7 uses a top-down view where X→right, Y→down on screen,
    # with lift (Z) creating a 45° diagonal offset of 4px per level.
    #
    # Different views vary the lift effect.
    PROJECTIONS: dict[str, dict] = {
        "classic": {
            "desc": "Standard U7 top-down with 45° lift offset",
            "sx": lambda tx, ty, tz: tx * C_TILE_SIZE - 4 * tz,
            "sy": lambda tx, ty, tz: ty * C_TILE_SIZE - 4 * tz,
        },
        "flat": {
            "desc": "Pure top-down, lift ignored",
            "sx": lambda tx, ty, tz: tx * C_TILE_SIZE,
            "sy": lambda tx, ty, tz: ty * C_TILE_SIZE,
        },
        "steep": {
            "desc": "Exaggerated lift (8px per level)",
            "sx": lambda tx, ty, tz: tx * C_TILE_SIZE - 8 * tz,
            "sy": lambda tx, ty, tz: ty * C_TILE_SIZE - 8 * tz,
        },
    }
    DEFAULT_VIEW = "classic"

    def __init__(self, static_dir: str) -> None:
        self.static_dir = static_dir
        self._terrain_map: list[list[int]] | None = None
        self._terrains: list[list[tuple[int, int]]] | None = None  # terrain shapes
        self._tfa: U7TypeFlags | None = None
        self._shapes_vga: U7FlexArchive | None = None

    # ------------------------------------------------------------------
    # Lazy loaders
    # ------------------------------------------------------------------

    @property
    def terrain_map(self) -> list[list[int]]:
        """192×192 terrain index grid from U7MAP."""
        if self._terrain_map is None:
            self._terrain_map = self._parse_u7map()
        return self._terrain_map

    @property
    def terrains(self) -> list[list[tuple[int, int]]]:
        """List of terrain definitions from U7CHUNKS."""
        if self._terrains is None:
            self._terrains = self._parse_u7chunks()
        return self._terrains

    @property
    def tfa(self) -> U7TypeFlags:
        """Type Flag Array data."""
        if self._tfa is None:
            self._tfa = U7TypeFlags.from_dir(self.static_dir)
        return self._tfa

    @property
    def shapes_vga(self) -> U7FlexArchive:
        """SHAPES.VGA Flex archive."""
        if self._shapes_vga is None:
            path = os.path.join(self.static_dir, "SHAPES.VGA")
            self._shapes_vga = U7FlexArchive.from_file(path)
        return self._shapes_vga

    # ------------------------------------------------------------------
    # U7MAP parser
    # ------------------------------------------------------------------

    def _parse_u7map(self) -> list[list[int]]:
        """
        Parse U7MAP into a 192×192 terrain index grid.

        Returns ``grid[cx][cy]`` = terrain index into U7CHUNKS.
        """
        path = os.path.join(self.static_dir, "U7MAP")
        with open(path, "rb") as f:
            data = f.read()

        grid = [[0] * C_NUM_CHUNKS for _ in range(C_NUM_CHUNKS)]

        for schunk in range(C_NUM_SCHUNKS * C_NUM_SCHUNKS):  # 0–143
            scx = C_CHUNKS_PER_SCHUNK * (schunk % C_NUM_SCHUNKS)
            scy = C_CHUNKS_PER_SCHUNK * (schunk // C_NUM_SCHUNKS)
            base = schunk * C_CHUNKS_PER_SCHUNK * C_CHUNKS_PER_SCHUNK * 2

            for cy in range(C_CHUNKS_PER_SCHUNK):
                for cx in range(C_CHUNKS_PER_SCHUNK):
                    off = base + (cy * C_CHUNKS_PER_SCHUNK + cx) * 2
                    if off + 2 > len(data):
                        continue
                    terrain_idx = struct.unpack_from("<H", data, off)[0]
                    grid[scx + cx][scy + cy] = terrain_idx

        return grid

    # ------------------------------------------------------------------
    # U7CHUNKS parser
    # ------------------------------------------------------------------

    def _parse_u7chunks(self) -> list[list[tuple[int, int]]]:
        """
        Parse U7CHUNKS terrain definitions.

        Supports both V1 (original, 2 bytes/tile: 10-bit shape + 5-bit
        frame) and Exult V2 (3 bytes/tile with 10-byte header: 16-bit
        shape + 8-bit frame).

        Returns a list of terrains, each being 256 ``(shape, frame)``
        tuples for the 16×16 tiles (row-major: ``[tiley * 16 + tilex]``).
        """
        path = os.path.join(self.static_dir, "U7CHUNKS")
        with open(path, "rb") as f:
            data = f.read()

        # Detect Exult V2 extended format
        is_v2 = (len(data) >= _V2_CHUNKS_HDR_SIZE
                 and data[:_V2_CHUNKS_HDR_SIZE] == _V2_CHUNKS_MAGIC)

        if is_v2:
            payload = data[_V2_CHUNKS_HDR_SIZE:]
            chunk_bytes = C_CHUNK_BYTES_V2
            tile_bytes = 3
        else:
            payload = data
            chunk_bytes = C_CHUNK_BYTES_V1
            tile_bytes = 2

        num_terrains = len(payload) // chunk_bytes
        terrains: list[list[tuple[int, int]]] = []

        for t in range(num_terrains):
            base = t * chunk_bytes
            tiles: list[tuple[int, int]] = []
            for i in range(C_TILES_PER_CHUNK * C_TILES_PER_CHUNK):
                off = base + i * tile_bytes
                if off + tile_bytes > len(payload):
                    tiles.append((0, 0))
                    continue
                if is_v2:
                    shnum = payload[off] + 256 * payload[off + 1]  # 16-bit shape
                    frnum = payload[off + 2]                        # 8-bit frame
                else:
                    b0 = payload[off]
                    b1 = payload[off + 1]
                    shnum = b0 + 256 * (b1 & 0x03)  # 10-bit shape
                    frnum = (b1 >> 2) & 0x1F          # 5-bit frame
                tiles.append((shnum, frnum))
            terrains.append(tiles)

        return terrains

    # ------------------------------------------------------------------
    # IFIX parser
    # ------------------------------------------------------------------

    @staticmethod
    def parse_ifix(
        ifix_path: str,
        schunk_num: int,
    ) -> list[U7MapObject]:
        """
        Parse a U7IFIXnn Flex file into absolute-tile MapObjects.

        Original format: 4 bytes per object::

            Byte 0: high nibble = tx (0–15), low nibble = ty (0–15)
            Byte 1: low nibble = lift (0–15)
            Byte 2: shape low byte
            Byte 3: bits 0–1 = shape high bits (10-bit total),
                     bits 2–7 = frame (0–63)
        """
        if not os.path.isfile(ifix_path):
            return []

        flex = U7FlexArchive.from_file(ifix_path)
        scx = C_CHUNKS_PER_SCHUNK * (schunk_num % C_NUM_SCHUNKS)
        scy = C_CHUNKS_PER_SCHUNK * (schunk_num // C_NUM_SCHUNKS)

        objects: list[U7MapObject] = []

        for chunk_idx in range(len(flex.records)):
            rec = flex.get_record(chunk_idx)
            if not rec:
                continue

            # Chunk position within superchunk
            local_cx = chunk_idx % C_CHUNKS_PER_SCHUNK
            local_cy = chunk_idx // C_CHUNKS_PER_SCHUNK
            abs_cx = scx + local_cx
            abs_cy = scy + local_cy

            # Detect format: V2 (5 bytes/obj) vs V1 (4 bytes/obj)
            entry_size = 4
            if len(rec) % 5 == 0 and len(rec) % 4 != 0:
                entry_size = 5

            num_entries = len(rec) // entry_size
            for i in range(num_entries):
                off = i * entry_size
                if off + entry_size > len(rec):
                    break

                if entry_size == 4:
                    b0, b1, b2, b3 = rec[off], rec[off+1], rec[off+2], rec[off+3]
                    local_tx = (b0 >> 4) & 0x0F
                    local_ty = b0 & 0x0F
                    lift = b1 & 0x0F
                    shnum = b2 + 256 * (b3 & 0x03)
                    frnum = b3 >> 2
                else:
                    # Exult V2 format
                    b0 = rec[off]
                    local_tx = (b0 >> 4) & 0x0F
                    local_ty = b0 & 0x0F
                    lift = rec[off + 1]
                    shnum = struct.unpack_from("<H", rec, off + 2)[0]
                    frnum = rec[off + 4]

                abs_tx = abs_cx * C_TILES_PER_CHUNK + local_tx
                abs_ty = abs_cy * C_TILES_PER_CHUNK + local_ty

                objects.append(U7MapObject(
                    tx=abs_tx, ty=abs_ty, tz=lift,
                    shape=shnum, frame=frnum,
                ))

        return objects

    # ------------------------------------------------------------------
    # IREG parser
    # ------------------------------------------------------------------

    @staticmethod
    def parse_ireg(
        ireg_path: str,
        schunk_num: int,
    ) -> list[U7MapObject]:
        """
        Parse a u7iregNN file into absolute-tile MapObjects.

        IREG files contain variable-length entries for dynamic objects.
        We parse the standard 6-byte entries (simple objects) and skip
        containers/eggs for now.
        """
        if not os.path.isfile(ireg_path):
            return []

        with open(ireg_path, "rb") as f:
            data = f.read()

        scx = C_CHUNKS_PER_SCHUNK * (schunk_num % C_NUM_SCHUNKS)
        scy = C_CHUNKS_PER_SCHUNK * (schunk_num // C_NUM_SCHUNKS)

        objects: list[U7MapObject] = []
        pos = 0
        dlen = len(data)

        while pos < dlen:
            if pos >= dlen:
                break

            entlen = data[pos]
            pos += 1

            if entlen == 0 or entlen == 1:
                # End-of-container / padding
                continue

            if entlen == 2:
                # 2-byte index ID — skip
                pos += 2
                continue

            # Special markers
            if entlen in (253, 254, 255):
                # Extended entries — skip for now (complex parsing)
                # We try to skip safely by reading remaining bytes
                if entlen == 255:
                    # IREG_SPECIAL: next byte tells sub-type
                    if pos < dlen:
                        pos += 1  # sub-type byte
                    continue
                if entlen == 254:
                    # IREG_EXTENDED: 2-byte shape numbers, read entlen byte
                    if pos < dlen:
                        actual_len = data[pos]
                        pos += 1
                        pos += actual_len
                    continue
                if entlen == 253:
                    # IREG_EXTENDED2: extended lift
                    if pos < dlen:
                        actual_len = data[pos]
                        pos += 1
                        pos += actual_len
                    continue
                continue

            # Standard entry: entlen bytes of payload
            if pos + entlen > dlen:
                break

            payload = data[pos:pos + entlen]
            pos += entlen

            if entlen < 6:
                continue

            # Parse standard 6-byte object entry
            b0 = payload[0]
            b1 = payload[1]
            b2 = payload[2]
            b3 = payload[3]
            b4 = payload[4]
            b5 = payload[5]

            chunk_cx = (b0 >> 4) & 0x0F    # chunk X within superchunk
            tile_x = b0 & 0x0F              # tile X within chunk
            chunk_cy = (b1 >> 4) & 0x0F
            tile_y = b1 & 0x0F

            shnum = b2 + 256 * (b3 & 0x03)
            frnum = b3 >> 2

            # Lift: the byte has nibbles swapped in old format
            lift = b4 & 0x0F

            quality = b5

            abs_tx = (scx + chunk_cx) * C_TILES_PER_CHUNK + tile_x
            abs_ty = (scy + chunk_cy) * C_TILES_PER_CHUNK + tile_y

            objects.append(U7MapObject(
                tx=abs_tx, ty=abs_ty, tz=lift,
                shape=shnum, frame=frnum, quality=quality,
            ))

        return objects

    # ------------------------------------------------------------------
    # Load all objects for a superchunk
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Find a nearby flat tile for RLE terrain gaps (Exult chunkter.cc)
    # ------------------------------------------------------------------

    def _find_nearby_flat(
        self,
        terrain: list[tuple[int, int]],
        tilex: int,
        tiley: int,
    ) -> tuple[int, int] | None:
        """Find a flat tile near (tilex, tiley) in the given terrain.

        Matches Exult ``Chunk_terrain::paint_tile`` logic: search
        immediate neighbours first, then whole chunk.  Skips shape 12
        frame 0 (palette-cycling void tile) and RLE shapes.
        """
        # Check if a shape is a flat tile (non-RLE)
        def _is_flat(shnum: int) -> bool:
            return shnum < FIRST_OBJ_SHAPE

        # Search ±1 neighbours
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                nx, ny = tilex + dx, tiley + dy
                if 0 <= nx < C_TILES_PER_CHUNK and 0 <= ny < C_TILES_PER_CHUNK:
                    s, f = terrain[ny * C_TILES_PER_CHUNK + nx]
                    if s == 12 and f == 0:
                        continue  # void tile
                    if _is_flat(s):
                        return (s, f)

        # Search whole chunk
        for ty in range(C_TILES_PER_CHUNK):
            for tx in range(C_TILES_PER_CHUNK):
                s, f = terrain[ty * C_TILES_PER_CHUNK + tx]
                if s == 12 and f == 0:
                    continue  # void tile
                if _is_flat(s):
                    return (s, f)

        return None

    def load_superchunk(
        self,
        schunk: int,
        *,
        include_fixed: bool = True,
        include_ireg: str | None = None,
        exclude_shapes: set[int] | None = None,
    ) -> tuple[list[U7MapObject], list[tuple[int, int, int, int]]]:
        """
        Load terrain tiles and objects for a single superchunk.

        Parameters
        ----------
        schunk:
            Superchunk number (0–143).
        include_fixed:
            Load IFIX fixed objects.
        include_ireg:
            Path to gamedat directory for IREG dynamic objects.
        exclude_shapes:
            Set of shape numbers to exclude.

        Returns
        -------
        (objects, ground_tiles)
            objects: list of U7MapObject for non-flat objects
            ground_tiles: list of (abs_tx, abs_ty, shape, frame)
                          for flat terrain tiles from U7CHUNKS
        """
        scx = C_CHUNKS_PER_SCHUNK * (schunk % C_NUM_SCHUNKS)
        scy = C_CHUNKS_PER_SCHUNK * (schunk // C_NUM_SCHUNKS)

        exclude = exclude_shapes or set()

        # --- Ground tiles from terrain map ---
        # Flat tiles go into ground_tiles; RLE terrain shapes become objects
        # (matching Exult Chunk_terrain::paint_tile + Terrain_game_object).
        ground_tiles: list[tuple[int, int, int, int]] = []
        for cy in range(C_CHUNKS_PER_SCHUNK):
            for cx in range(C_CHUNKS_PER_SCHUNK):
                abs_cx = scx + cx
                abs_cy = scy + cy
                terrain_idx = self.terrain_map[abs_cx][abs_cy]
                if terrain_idx >= len(self.terrains):
                    continue
                terrain = self.terrains[terrain_idx]
                for tiley in range(C_TILES_PER_CHUNK):
                    for tilex in range(C_TILES_PER_CHUNK):
                        shnum, frnum = terrain[tiley * C_TILES_PER_CHUNK + tilex]
                        if shnum in exclude:
                            continue
                        abs_tx = abs_cx * C_TILES_PER_CHUNK + tilex
                        abs_ty = abs_cy * C_TILES_PER_CHUNK + tiley
                        ground_tiles.append((abs_tx, abs_ty, shnum, frnum))

        # --- IFIX fixed objects ---
        objects: list[U7MapObject] = []
        if include_fixed:
            ifix_name = f"U7IFIX{schunk:02X}"
            ifix_path = os.path.join(self.static_dir, ifix_name)
            ifix_objs = self.parse_ifix(ifix_path, schunk)
            for obj in ifix_objs:
                if obj.shape not in exclude:
                    objects.append(obj)

        # --- IREG dynamic objects ---
        if include_ireg:
            ireg_name = f"u7ireg{schunk:02x}"
            ireg_path = os.path.join(include_ireg, ireg_name)
            ireg_objs = self.parse_ireg(ireg_path, schunk)
            for obj in ireg_objs:
                if obj.shape not in exclude:
                    objects.append(obj)

        return objects, ground_tiles

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    @classmethod
    def project(cls, obj: U7MapObject, view: str = "classic") -> None:
        """Set screen coordinates for an object using the named view."""
        proj = cls.PROJECTIONS.get(view, cls.PROJECTIONS[cls.DEFAULT_VIEW])
        obj.screen_x = proj["sx"](obj.tx, obj.ty, obj.tz)
        obj.screen_y = proj["sy"](obj.tx, obj.ty, obj.tz)

    @staticmethod
    def _draw_tile_rect_overlays(
        canvas: Image.Image,
        overlays: list[U7TileRectOverlay],
        *,
        sx_fn,
        sy_fn,
        origin_sx: int,
        origin_sy: int,
        pad: int,
        canvas_w: int,
        canvas_h: int,
        width: int,
        lift: int,
        fill_alpha: int,
        show_labels: bool,
    ) -> None:
        """Draw tile-aligned rectangle overlays in screen space.

        The overlay is drawn into a transparent layer then composited over
        the rendered map so fill alpha blends with terrain/sprites.
        """
        if not overlays:
            return

        overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        max_tile = C_NUM_TILES - 1
        line_w = max(1, width)
        clamped_fill_alpha = max(0, min(255, fill_alpha))
        try:
            font = ImageFont.truetype("arial.ttf", 108)
        except OSError:
            font = ImageFont.load_default()

        for raw in overlays:
            rect = raw.normalized()

            tx0 = max(0, min(rect.tx0, max_tile))
            ty0 = max(0, min(rect.ty0, max_tile))
            tx1 = max(0, min(rect.tx1, max_tile))
            ty1 = max(0, min(rect.ty1, max_tile))

            if tx0 > tx1 or ty0 > ty1:
                continue

            x0 = sx_fn(tx0, ty0, lift) - origin_sx + pad
            y0 = sy_fn(tx0, ty0, lift) - origin_sy + pad
            # Inclusive tile rect: bottom-right is the SE edge of (tx1, ty1).
            x1 = sx_fn(tx1 + 1, ty1 + 1, lift) - origin_sx + pad - 1
            y1 = sy_fn(tx1 + 1, ty1 + 1, lift) - origin_sy + pad - 1

            if x1 < 0 or y1 < 0 or x0 >= canvas_w or y0 >= canvas_h:
                continue

            cr, cg, cb, ca = rect.color
            fill_col = (cr, cg, cb, min(ca, clamped_fill_alpha))
            if clamped_fill_alpha > 0:
                draw.rectangle([(x0, y0), (x1, y1)], fill=fill_col)
            draw.rectangle([(x0, y0), (x1, y1)], outline=rect.color, width=line_w)

            if show_labels:
                coord_label = f"{tx0},{ty0},{tx1},{ty1}"
                center_label = rect.label or coord_label

                # Draw coordinate label near the top-left of the rectangle.
                coord_x = x0 + 8
                coord_y = y0 + 8
                coord_bbox = draw.textbbox((coord_x, coord_y), coord_label, font=font)
                if coord_bbox is not None:
                    draw.rectangle(
                        [(coord_bbox[0] - 4, coord_bbox[1] - 2),
                         (coord_bbox[2] + 4, coord_bbox[3] + 2)],
                        fill=(0, 0, 0, 180),
                    )
                draw.text((coord_x, coord_y), coord_label, fill=rect.color, font=font)

                # Draw the main label centered in the rectangle.
                bbox0 = draw.textbbox((0, 0), center_label, font=font)
                text_w = max(1, bbox0[2] - bbox0[0])
                text_h = max(1, bbox0[3] - bbox0[1])

                rect_w = max(1, x1 - x0 + 1)
                rect_h = max(1, y1 - y0 + 1)
                text_x = x0 + (rect_w - text_w) // 2
                text_y = y0 + (rect_h - text_h) // 2

                # Ensure text remains visible against varied terrain colours.
                bbox = draw.textbbox((text_x, text_y), center_label, font=font)
                if bbox is not None:
                    bg = (0, 0, 0, 180)
                    draw.rectangle(
                        [(bbox[0] - 2, bbox[1] - 1), (bbox[2] + 2, bbox[3] + 1)],
                        fill=bg,
                    )
                draw.text((text_x, text_y), center_label, fill=rect.color, font=font)

        canvas.alpha_composite(overlay)

    # ------------------------------------------------------------------
    # Depth sort (Exult-style)
    # ------------------------------------------------------------------

    @staticmethod
    def _compare(
        a: U7MapObject,
        b: U7MapObject,
        tfa: U7TypeFlags | None,
    ) -> int:
        """
        Exult-style depth comparison for two objects.

        Returns -1 if *a* paints before (behind) *b*, +1 if after, 0 if equal.
        Based on Exult's ``Game_object::compare()`` from ``objs/objs.cc``.
        """
        # Get 3D extents
        ax, ay, az = a.tx, a.ty, a.tz
        bx, by, bz = b.tx, b.ty, b.tz
        axs = ays = azs = 1
        bxs = bys = bzs = 1

        if tfa is not None:
            ae = tfa.get(a.shape)
            if ae is not None:
                fx, fy, fz = ae.footpad_tiles(a.frame)
                axs, ays, azs = fx, fy, fz

            be = tfa.get(b.shape)
            if be is not None:
                fx, fy, fz = be.footpad_tiles(b.frame)
                bxs, bys, bzs = fx, fy, fz

        # Bounding box edges (Exult convention: object at tx occupies
        # tx-xs+1..tx, ty-ys+1..ty, tz..tz+zs-1)
        axleft = ax - axs + 1
        ayleft = ay - ays + 1
        aztop = az + azs
        a_flat = (azs == 0)
        if a_flat:
            aztop = az  # flat objects: ztop = tz

        bxleft = bx - bxs + 1
        byleft = by - bys + 1
        bztop = bz + bzs
        b_flat = (bzs == 0)
        if b_flat:
            bztop = bz

        # Both flat
        if a_flat and b_flat:
            if az != bz:
                return -1 if az < bz else 1
            # Fall through to x/y

        # Clear Z separation (non-flat)
        if not (a_flat and b_flat):
            if aztop <= bz:
                return -1
            if bztop <= az:
                return 1

        # Clear X separation
        if ax < bxleft:
            return -1
        if bx < axleft:
            return 1

        # Clear Y separation
        if ay < byleft:
            return -1
        if by < ayleft:
            return 1

        # Overlapping — use Z as tiebreaker
        if az != bz:
            return -1 if az < bz else 1

        # Y tiebreaker
        if ay != by:
            return -1 if ay < by else 1

        # X tiebreaker
        if ax != bx:
            return -1 if ax < bx else 1

        return 0

    # ------------------------------------------------------------------
    # DAG-based topological depth sort
    # ------------------------------------------------------------------

    def _dag_sort(
        self,
        objects: list[U7MapObject],
        tfa: U7TypeFlags,
        sboxes: list[tuple[int, int, int, int]] | None = None,
    ) -> list[U7MapObject]:
        """
        Depth-sort objects using an Exult-style sweep-line DAG.

        Builds a dependency graph from pairwise screen-overlap tests,
        then returns objects in topological (back-to-front) order.
        Falls back to a simple key sort for batches larger than 5000.

        Parameters
        ----------
        sboxes:
            Pre-computed screen bounding boxes ``(x_lo, x_hi, y_lo, y_hi)``
            for each object.  When provided, these are used for the
            overlap filter instead of TFA tile estimates.  Using actual
            sprite pixel bounds avoids missing pairs where a tall/wide
            sprite extends far beyond its tile footprint.
        """
        n = len(objects)
        if n == 0:
            return []
        if n > 5000:
            return sorted(objects, key=lambda o: (o.tz, o.ty, o.tx))

        deps: list[list[int]] = [[] for _ in range(n)]
        if sboxes is None:
            sboxes = []
            for obj in objects:
                e = tfa.get(obj.shape)
                dx = e.dims_x if e else 1
                dy = e.dims_y if e else 1
                dz = e.dims_z if e else 0
                sx_lo = obj.screen_x - dx * C_TILE_SIZE
                sx_hi = obj.screen_x + C_TILE_SIZE
                sy_lo = obj.screen_y - dy * C_TILE_SIZE - dz * 4
                sy_hi = obj.screen_y + C_TILE_SIZE
                sboxes.append((sx_lo, sx_hi, sy_lo, sy_hi))

        sweep = sorted(range(n), key=lambda i: sboxes[i][0])
        active: list[int] = []
        for idx in sweep:
            sxl_cur = sboxes[idx][0]
            active = [a for a in active if sboxes[a][1] > sxl_cur]
            for other in active:
                a_box = sboxes[idx]
                b_box = sboxes[other]
                if a_box[2] < b_box[3] and b_box[2] < a_box[3]:
                    cmp = self._compare(objects[idx], objects[other], tfa)
                    if cmp < 0:
                        deps[other].append(idx)
                    elif cmp > 0:
                        deps[idx].append(other)
            active.append(idx)

        order: list[int] = []
        state = bytearray(n)
        for start in range(n):
            if state[start] != 0:
                continue
            stack = [(start, 0)]
            while stack:
                node, di = stack[-1]
                if state[node] == 2:
                    stack.pop()
                    continue
                if state[node] == 0:
                    state[node] = 1
                if di < len(deps[node]):
                    stack[-1] = (node, di + 1)
                    dep = deps[node][di]
                    if state[dep] == 0:
                        stack.append((dep, 0))
                else:
                    state[node] = 2
                    order.append(node)
                    stack.pop()

        return [objects[i] for i in order]

    # ------------------------------------------------------------------
    # Render a superchunk
    # ------------------------------------------------------------------

    def render_superchunk(
        self,
        schunk: int,
        palette: U7Palette,
        *,
        view: str = "classic",
        include_ireg: str | None = None,
        exclude_shapes: set[int] | None = None,
        max_lift: int | None = None,
        background: tuple[int, int, int, int] = (0, 0, 0, 255),
        grid: bool = False,
        grid_size: int = 1,
        highlight_rects: list[U7TileRectOverlay] | None = None,
        highlight_width: int = 3,
        highlight_lift: int = 0,
        highlight_fill_alpha: int = 128,
        highlight_labels: bool = True,
    ) -> Image.Image:
        """
        Render a single superchunk (256×256 tiles) to an RGBA image.

        Parameters
        ----------
        schunk:
            Superchunk number (0–143).
        palette:
            U7 colour palette.
        view:
            Projection view name.
        include_ireg:
            Path to gamedat directory for IREG objects.
        exclude_shapes:
            Set of shape numbers to skip.
        max_lift:
            Maximum object lift (tz) to render.  Objects above this
            lift are discarded.  ``None`` (default) renders all lifts.
        background:
            Background RGBA colour.
        grid:
            Overlay chunk grid lines.
        grid_size:
            Grid line width.
        highlight_rects:
            Optional list of world-tile rectangles to outline.
        highlight_width:
            Outline width in pixels for highlighted rectangles.
        highlight_lift:
            Lift level for projection of highlighted rectangles.
        highlight_fill_alpha:
            Fill alpha for highlighted rectangles (0-255).
        highlight_labels:
            Draw text labels for highlighted rectangles.

        Returns
        -------
        PIL RGBA Image.
        """
        objects, ground_tiles = self.load_superchunk(
            schunk,
            include_ireg=include_ireg,
            exclude_shapes=exclude_shapes,
        )
        if max_lift is not None:
            objects = [o for o in objects if o.tz <= max_lift]
        proj = self.PROJECTIONS.get(view, self.PROJECTIONS[self.DEFAULT_VIEW])
        sx_fn = proj["sx"]
        sy_fn = proj["sy"]

        scx = C_CHUNKS_PER_SCHUNK * (schunk % C_NUM_SCHUNKS)
        scy = C_CHUNKS_PER_SCHUNK * (schunk // C_NUM_SCHUNKS)

        # Base tile range for this superchunk
        base_tx = scx * C_TILES_PER_CHUNK
        base_ty = scy * C_TILES_PER_CHUNK
        ntiles = C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK  # 256

        # Canvas size: for classic view, tiles span 256*8=2048 px,
        # lift can shift up to 15*4=60px. Add padding.
        canvas_w = ntiles * C_TILE_SIZE + 128
        canvas_h = ntiles * C_TILE_SIZE + 128
        pad = 64

        canvas = Image.new("RGBA", (canvas_w, canvas_h), background)

        # Palette for rendering
        flat_rgb = palette.to_flat_rgb()

        # Shape/frame cache
        shape_cache: dict[int, U7Shape | None] = {}
        frame_cache: dict[tuple[int, int], tuple[Image.Image, int, int] | None] = {}

        def _get_frame(shnum: int, frnum: int) -> tuple[Image.Image, int, int] | None:
            key = (shnum, frnum)
            if key in frame_cache:
                return frame_cache[key]

            if shnum not in shape_cache:
                rec = self.shapes_vga.get_record(shnum) if shnum < len(self.shapes_vga.records) else None
                if rec:
                    try:
                        shape_cache[shnum] = U7Shape.from_data(
                            rec, is_tile=(shnum < FIRST_OBJ_SHAPE))
                    except Exception:
                        shape_cache[shnum] = None
                else:
                    shape_cache[shnum] = None

            shape = shape_cache[shnum]
            if shape is None or frnum >= len(shape.frames):
                frame_cache[key] = None
                return None

            fr = shape.frames[frnum]
            if fr.pixels is None or fr.width == 0 or fr.height == 0:
                frame_cache[key] = None
                return None

            tfa_entry = self.tfa.get(shnum)
            has_trans = (tfa_entry.has_translucency if tfa_entry else False)
            frame_cache[key] = _frame_to_rgba(
                fr, flat_rgb, has_translucency=has_trans)
            return frame_cache[key]

        # --- 1. Paint ground tiles ---
        # RLE terrain shapes (shape >= FIRST_OBJ_SHAPE) are promoted to
        # objects so they get the correct SE anchor (+7) and participate
        # in depth sorting.  A nearby flat tile fills the gap left behind.
        rle_terrain_objs: list[U7MapObject] = []
        origin_sx = sx_fn(base_tx, base_ty, 0)
        origin_sy = sy_fn(base_tx, base_ty, 0)

        for abs_tx, abs_ty, shnum, frnum in ground_tiles:
            entry = _get_frame(shnum, frnum)
            if entry is None:
                continue
            img, xoff, yoff = entry
            px = sx_fn(abs_tx, abs_ty, 0) - origin_sx + pad
            py = sy_fn(abs_tx, abs_ty, 0) - origin_sy + pad
            if img.width == C_TILE_SIZE and img.height == C_TILE_SIZE:
                canvas.alpha_composite(img, dest=(px, py))
            else:
                # RLE terrain: find a nearby flat to fill the 8×8 gap,
                # then queue the RLE shape as an object.
                cx = abs_tx // C_TILES_PER_CHUNK
                cy = abs_ty // C_TILES_PER_CHUNK
                terrain_idx = self.terrain_map[cx][cy]
                if terrain_idx < len(self.terrains):
                    tilex = abs_tx % C_TILES_PER_CHUNK
                    tiley = abs_ty % C_TILES_PER_CHUNK
                    flat = self._find_nearby_flat(
                        self.terrains[terrain_idx], tilex, tiley)
                    if flat:
                        flat_entry = _get_frame(flat[0], flat[1])
                        if flat_entry and (flat_entry[0].width == C_TILE_SIZE
                                           and flat_entry[0].height == C_TILE_SIZE):
                            canvas.alpha_composite(flat_entry[0], dest=(px, py))
                rle_terrain_objs.append(U7MapObject(
                    tx=abs_tx, ty=abs_ty, tz=0,
                    shape=shnum, frame=frnum))

        # --- 2. Depth-sort and paint objects ---
        for obj in objects:
            self.project(obj, view)
        for obj in rle_terrain_objs:
            self.project(obj, view)
        all_objects = rle_terrain_objs + objects

        tfa = self.tfa

        # Build sboxes from actual sprite pixel bounds so the sweep-line
        # doesn't miss overlapping pairs (sprites extend far beyond the
        # tile footprint for tall shapes like statues/columns).
        sprite_sboxes: list[tuple[int, int, int, int]] = []
        for obj in all_objects:
            entry = _get_frame(obj.shape, obj.frame)
            if entry:
                img, xoff, yoff = entry
                ax = obj.screen_x + 7 - xoff
                ay = obj.screen_y + 7 - yoff
                sprite_sboxes.append((ax, ax + img.width, ay, ay + img.height))
            else:
                e = tfa.get(obj.shape)
                dx = e.dims_x if e else 1
                dy = e.dims_y if e else 1
                dz = e.dims_z if e else 0
                sprite_sboxes.append((
                    obj.screen_x - dx * C_TILE_SIZE,
                    obj.screen_x + C_TILE_SIZE,
                    obj.screen_y - dy * C_TILE_SIZE - dz * 4,
                    obj.screen_y + C_TILE_SIZE))

        sorted_objects = self._dag_sort(all_objects, tfa, sboxes=sprite_sboxes)

        for obj in sorted_objects:
            entry = _get_frame(obj.shape, obj.frame)
            if entry is None:
                continue
            img, xoff, yoff = entry
            # +7: anchor at SE pixel of tile (Exult convention)
            px = obj.screen_x - origin_sx + pad + 7 - xoff
            py = obj.screen_y - origin_sy + pad + 7 - yoff
            if (px + img.width <= 0 or py + img.height <= 0 or
                    px >= canvas_w or py >= canvas_h):
                continue
            canvas.alpha_composite(img, dest=(px, py))

        # --- 3. Grid overlay ---
        if grid:
            draw = ImageDraw.Draw(canvas)
            chunk_rgba = (0, 120, 255, 100)
            sc_rgba = (255, 40, 40, 180)
            try:
                font = ImageFont.truetype("arial.ttf", 11)
            except OSError:
                font = ImageFont.load_default()

            chunk_px = C_TILES_PER_CHUNK * C_TILE_SIZE  # 128
            for i in range(C_CHUNKS_PER_SCHUNK + 1):
                x = i * chunk_px + pad
                draw.line([(x, pad), (x, ntiles * C_TILE_SIZE + pad)],
                          fill=chunk_rgba, width=grid_size)
                y = i * chunk_px + pad
                draw.line([(pad, y), (ntiles * C_TILE_SIZE + pad, y)],
                          fill=chunk_rgba, width=grid_size)

            # Chunk coordinate labels
            for cy_i in range(C_CHUNKS_PER_SCHUNK):
                for cx_i in range(C_CHUNKS_PER_SCHUNK):
                    abs_cx = scx + cx_i
                    abs_cy = scy + cy_i
                    lx = cx_i * chunk_px + pad + 2
                    ly = cy_i * chunk_px + pad + 1
                    draw.text((lx, ly), f"{abs_cx},{abs_cy}",
                              fill=chunk_rgba, font=font)

            # Superchunk border (red) with label
            sx0 = pad
            sy0 = pad
            sx1 = C_CHUNKS_PER_SCHUNK * chunk_px + pad
            sy1 = C_CHUNKS_PER_SCHUNK * chunk_px + pad
            for edge in [
                [(sx0, sy0), (sx1, sy0)],
                [(sx0, sy1), (sx1, sy1)],
                [(sx0, sy0), (sx0, sy1)],
                [(sx1, sy0), (sx1, sy1)],
            ]:
                draw.line(edge, fill=sc_rgba, width=max(grid_size, 2))
            try:
                sc_font = ImageFont.truetype("arial.ttf", 18)
            except OSError:
                sc_font = ImageFont.load_default()
            draw.text((sx0 + 4, sy0 + 14), f"SC {schunk}",
                      fill=sc_rgba, font=sc_font)

        if highlight_rects:
            self._draw_tile_rect_overlays(
            canvas,
                highlight_rects,
                sx_fn=sx_fn,
                sy_fn=sy_fn,
                origin_sx=origin_sx,
                origin_sy=origin_sy,
                pad=pad,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
                width=highlight_width,
                lift=highlight_lift,
                fill_alpha=highlight_fill_alpha,
                show_labels=highlight_labels,
            )

        return canvas

    # ------------------------------------------------------------------
    # Render a range of chunks (region)
    # ------------------------------------------------------------------

    def render_region(
        self,
        chunk_x0: int,
        chunk_y0: int,
        chunk_x1: int,
        chunk_y1: int,
        palette: U7Palette,
        *,
        view: str = "classic",
        gamedat_dir: str | None = None,
        exclude_shapes: set[int] | None = None,
        max_lift: int | None = None,
        background: tuple[int, int, int, int] = (0, 0, 0, 255),
        grid: bool = False,
        grid_size: int = 1,
        highlight_rects: list[U7TileRectOverlay] | None = None,
        highlight_width: int = 3,
        highlight_lift: int = 0,
        highlight_fill_alpha: int = 128,
        highlight_labels: bool = True,
    ) -> Image.Image:
        """
        Render a rectangular region of chunks to an RGBA image.

        Parameters
        ----------
        chunk_x0, chunk_y0:
            Top-left chunk coordinates (inclusive).
        chunk_x1, chunk_y1:
            Bottom-right chunk coordinates (inclusive).
        palette:
            U7 colour palette.
        view:
            Projection view name.
        gamedat_dir:
            Path to gamedat directory for IREG objects.
        exclude_shapes:
            Set of shape numbers to skip.
        max_lift:
            Maximum object lift (tz) to render.  Objects above this
            lift are discarded.  ``None`` (default) renders all lifts.
        background:
            Background RGBA colour.
        grid:
            Overlay chunk grid lines.
        grid_size:
            Grid line width.
        highlight_rects:
            Optional list of world-tile rectangles to outline.
        highlight_width:
            Outline width in pixels for highlighted rectangles.
        highlight_lift:
            Lift level for projection of highlighted rectangles.
        highlight_fill_alpha:
            Fill alpha for highlighted rectangles (0-255).
        highlight_labels:
            Draw text labels for highlighted rectangles.

        Returns
        -------
        PIL RGBA Image.
        """
        exclude = exclude_shapes or set()
        proj = self.PROJECTIONS.get(view, self.PROJECTIONS[self.DEFAULT_VIEW])
        sx_fn = proj["sx"]
        sy_fn = proj["sy"]

        # Clamp ranges
        chunk_x0 = max(0, min(chunk_x0, C_NUM_CHUNKS - 1))
        chunk_y0 = max(0, min(chunk_y0, C_NUM_CHUNKS - 1))
        chunk_x1 = max(chunk_x0, min(chunk_x1, C_NUM_CHUNKS - 1))
        chunk_y1 = max(chunk_y0, min(chunk_y1, C_NUM_CHUNKS - 1))

        base_tx = chunk_x0 * C_TILES_PER_CHUNK
        base_ty = chunk_y0 * C_TILES_PER_CHUNK
        w_tiles = (chunk_x1 - chunk_x0 + 1) * C_TILES_PER_CHUNK
        h_tiles = (chunk_y1 - chunk_y0 + 1) * C_TILES_PER_CHUNK

        pad = 64
        canvas_w = w_tiles * C_TILE_SIZE + pad * 2
        canvas_h = h_tiles * C_TILE_SIZE + pad * 2

        canvas = Image.new("RGBA", (canvas_w, canvas_h), background)
        flat_rgb = palette.to_flat_rgb()

        shape_cache: dict[int, U7Shape | None] = {}
        frame_cache: dict[tuple[int, int], tuple[Image.Image, int, int] | None] = {}

        def _get_frame(shnum: int, frnum: int) -> tuple[Image.Image, int, int] | None:
            key = (shnum, frnum)
            if key in frame_cache:
                return frame_cache[key]

            if shnum not in shape_cache:
                rec = self.shapes_vga.get_record(shnum) if shnum < len(self.shapes_vga.records) else None
                if rec:
                    try:
                        shape_cache[shnum] = U7Shape.from_data(
                            rec, is_tile=(shnum < FIRST_OBJ_SHAPE))
                    except Exception:
                        shape_cache[shnum] = None
                else:
                    shape_cache[shnum] = None

            shape = shape_cache[shnum]
            if shape is None or frnum >= len(shape.frames):
                frame_cache[key] = None
                return None

            fr = shape.frames[frnum]
            if fr.pixels is None or fr.width == 0 or fr.height == 0:
                frame_cache[key] = None
                return None

            tfa_entry = self.tfa.get(shnum)
            has_trans = (tfa_entry.has_translucency if tfa_entry else False)
            frame_cache[key] = _frame_to_rgba(
                fr, flat_rgb, has_translucency=has_trans)
            return frame_cache[key]

        origin_sx = sx_fn(base_tx, base_ty, 0)
        origin_sy = sy_fn(base_tx, base_ty, 0)

        # Collect which superchunks we need
        needed_schunks: set[int] = set()
        for cy in range(chunk_y0, chunk_y1 + 1):
            for cx in range(chunk_x0, chunk_x1 + 1):
                sx_idx = cx // C_CHUNKS_PER_SCHUNK
                sy_idx = cy // C_CHUNKS_PER_SCHUNK
                needed_schunks.add(sy_idx * C_NUM_SCHUNKS + sx_idx)

        # --- 1. Paint ground tiles ---
        # RLE terrain shapes are promoted to objects (same as render_superchunk).
        rle_terrain_objs: list[U7MapObject] = []
        for cy in range(chunk_y0, chunk_y1 + 1):
            for cx in range(chunk_x0, chunk_x1 + 1):
                terrain_idx = self.terrain_map[cx][cy]
                if terrain_idx >= len(self.terrains):
                    continue
                terrain = self.terrains[terrain_idx]
                for tiley in range(C_TILES_PER_CHUNK):
                    for tilex in range(C_TILES_PER_CHUNK):
                        shnum, frnum = terrain[tiley * C_TILES_PER_CHUNK + tilex]
                        if shnum in exclude:
                            continue
                        abs_tx = cx * C_TILES_PER_CHUNK + tilex
                        abs_ty = cy * C_TILES_PER_CHUNK + tiley
                        entry = _get_frame(shnum, frnum)
                        if entry is None:
                            continue
                        img, xoff, yoff = entry
                        px = sx_fn(abs_tx, abs_ty, 0) - origin_sx + pad
                        py = sy_fn(abs_tx, abs_ty, 0) - origin_sy + pad
                        if img.width == C_TILE_SIZE and img.height == C_TILE_SIZE:
                            canvas.alpha_composite(img, dest=(px, py))
                        else:
                            # RLE terrain: fill gap with nearby flat, queue as object
                            flat = self._find_nearby_flat(terrain, tilex, tiley)
                            if flat:
                                flat_entry = _get_frame(flat[0], flat[1])
                                if (flat_entry
                                        and flat_entry[0].width == C_TILE_SIZE
                                        and flat_entry[0].height == C_TILE_SIZE):
                                    canvas.alpha_composite(
                                        flat_entry[0], dest=(px, py))
                            rle_terrain_objs.append(U7MapObject(
                                tx=abs_tx, ty=abs_ty, tz=0,
                                shape=shnum, frame=frnum))

        # --- 2. Collect ALL objects, sort globally, and paint ---
        # Sorting all objects together (rather than per-superchunk) ensures
        # correct depth ordering for objects that straddle superchunk
        # boundaries (e.g., interior objects vs roofs in adjacent SCs).
        tfa = self.tfa
        all_objects: list[U7MapObject] = []

        for obj in rle_terrain_objs:
            self.project(obj, view)
        all_objects.extend(rle_terrain_objs)

        _lift_ok = (lambda tz: True) if max_lift is None else (lambda tz: tz <= max_lift)

        for sc in sorted(needed_schunks):
            ifix_name = f"U7IFIX{sc:02X}"
            ifix_path = os.path.join(self.static_dir, ifix_name)
            ifix_objs = self.parse_ifix(ifix_path, sc)
            for obj in ifix_objs:
                obj_cx = obj.tx // C_TILES_PER_CHUNK
                obj_cy = obj.ty // C_TILES_PER_CHUNK
                if (chunk_x0 <= obj_cx <= chunk_x1 and
                        chunk_y0 <= obj_cy <= chunk_y1 and
                        obj.shape not in exclude and
                        _lift_ok(obj.tz)):
                    self.project(obj, view)
                    all_objects.append(obj)

            if gamedat_dir:
                ireg_name = f"u7ireg{sc:02x}"
                ireg_path = os.path.join(gamedat_dir, ireg_name)
                ireg_objs = self.parse_ireg(ireg_path, sc)
                for obj in ireg_objs:
                    obj_cx = obj.tx // C_TILES_PER_CHUNK
                    obj_cy = obj.ty // C_TILES_PER_CHUNK
                    if (chunk_x0 <= obj_cx <= chunk_x1 and
                            chunk_y0 <= obj_cy <= chunk_y1 and
                            obj.shape not in exclude and
                            _lift_ok(obj.tz)):
                        self.project(obj, view)
                        all_objects.append(obj)

        if all_objects:
            # Build sboxes from actual sprite pixel bounds
            sprite_sboxes: list[tuple[int, int, int, int]] = []
            for obj in all_objects:
                entry = _get_frame(obj.shape, obj.frame)
                if entry:
                    img, xoff, yoff = entry
                    ax = obj.screen_x + 7 - xoff
                    ay = obj.screen_y + 7 - yoff
                    sprite_sboxes.append(
                        (ax, ax + img.width, ay, ay + img.height))
                else:
                    e = tfa.get(obj.shape)
                    dx = e.dims_x if e else 1
                    dy = e.dims_y if e else 1
                    dz = e.dims_z if e else 0
                    sprite_sboxes.append((
                        obj.screen_x - dx * C_TILE_SIZE,
                        obj.screen_x + C_TILE_SIZE,
                        obj.screen_y - dy * C_TILE_SIZE - dz * 4,
                        obj.screen_y + C_TILE_SIZE))

            sorted_objects = self._dag_sort(
                all_objects, tfa, sboxes=sprite_sboxes)

            # Paint objects with +7 SE anchor offset
            for obj in sorted_objects:
                entry = _get_frame(obj.shape, obj.frame)
                if entry is None:
                    continue
                img, xoff, yoff = entry
                px = obj.screen_x - origin_sx + pad + 7 - xoff
                py = obj.screen_y - origin_sy + pad + 7 - yoff
                if (px + img.width <= 0 or py + img.height <= 0 or
                        px >= canvas_w or py >= canvas_h):
                    continue
                canvas.alpha_composite(img, dest=(px, py))

        # --- 3. Grid ---
        if grid:
            draw = ImageDraw.Draw(canvas)
            chunk_rgba = (0, 120, 255, 100)
            sc_rgba = (255, 40, 40, 180)
            try:
                font = ImageFont.truetype("arial.ttf", 11)
            except OSError:
                font = ImageFont.load_default()

            chunk_px = C_TILES_PER_CHUNK * C_TILE_SIZE  # 128

            # Chunk grid lines (blue)
            for i in range(chunk_x1 - chunk_x0 + 2):
                x = i * chunk_px + pad
                draw.line([(x, pad), (x, h_tiles * C_TILE_SIZE + pad)],
                          fill=chunk_rgba, width=grid_size)
            for i in range(chunk_y1 - chunk_y0 + 2):
                y = i * chunk_px + pad
                draw.line([(pad, y), (w_tiles * C_TILE_SIZE + pad, y)],
                          fill=chunk_rgba, width=grid_size)

            # Chunk coordinate labels (blue)
            for cy_i in range(chunk_y1 - chunk_y0 + 1):
                for cx_i in range(chunk_x1 - chunk_x0 + 1):
                    abs_cx = chunk_x0 + cx_i
                    abs_cy = chunk_y0 + cy_i
                    lx = cx_i * chunk_px + pad + 2
                    ly = cy_i * chunk_px + pad + 1
                    draw.text((lx, ly), f"{abs_cx},{abs_cy}",
                              fill=chunk_rgba, font=font)

            # Superchunk grid lines (red) with labels
            try:
                sc_font = ImageFont.truetype("arial.ttf", 18)
            except OSError:
                sc_font = ImageFont.load_default()

            # Determine superchunk boundaries that fall within the region
            sc_x0 = chunk_x0 // C_CHUNKS_PER_SCHUNK
            sc_y0 = chunk_y0 // C_CHUNKS_PER_SCHUNK
            sc_x1 = chunk_x1 // C_CHUNKS_PER_SCHUNK
            sc_y1 = chunk_y1 // C_CHUNKS_PER_SCHUNK

            sc_line_w = max(grid_size, 2)
            # Vertical superchunk boundaries
            for scx in range(sc_x0, sc_x1 + 2):
                cx = scx * C_CHUNKS_PER_SCHUNK
                if cx < chunk_x0 or cx > chunk_x1 + 1:
                    continue
                x = (cx - chunk_x0) * chunk_px + pad
                draw.line([(x, pad), (x, h_tiles * C_TILE_SIZE + pad)],
                          fill=sc_rgba, width=sc_line_w)
            # Horizontal superchunk boundaries
            for scy in range(sc_y0, sc_y1 + 2):
                cy = scy * C_CHUNKS_PER_SCHUNK
                if cy < chunk_y0 or cy > chunk_y1 + 1:
                    continue
                y = (cy - chunk_y0) * chunk_px + pad
                draw.line([(pad, y), (w_tiles * C_TILE_SIZE + pad, y)],
                          fill=sc_rgba, width=sc_line_w)

            # Superchunk number labels (red)
            for scy in range(sc_y0, sc_y1 + 1):
                for scx in range(sc_x0, sc_x1 + 1):
                    sc_num = scy * C_NUM_SCHUNKS + scx
                    # Top-left chunk of this superchunk
                    sc_cx = scx * C_CHUNKS_PER_SCHUNK
                    sc_cy = scy * C_CHUNKS_PER_SCHUNK
                    # Position relative to the rendered region
                    lx = (max(sc_cx, chunk_x0) - chunk_x0) * chunk_px + pad + 4
                    ly = (max(sc_cy, chunk_y0) - chunk_y0) * chunk_px + pad + 14
                    draw.text((lx, ly), f"SC {sc_num}",
                              fill=sc_rgba, font=sc_font)

        if highlight_rects:
            self._draw_tile_rect_overlays(
            canvas,
                highlight_rects,
                sx_fn=sx_fn,
                sy_fn=sy_fn,
                origin_sx=origin_sx,
                origin_sy=origin_sy,
                pad=pad,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
                width=highlight_width,
                lift=highlight_lift,
                fill_alpha=highlight_fill_alpha,
                show_labels=highlight_labels,
            )

        return canvas

    # ------------------------------------------------------------------
    # Available superchunks summary
    # ------------------------------------------------------------------

    def superchunk_summary(self) -> dict[int, dict]:
        """Return a summary dict of all superchunks and their object counts."""
        result: dict[int, dict] = {}
        for sc in range(C_NUM_SCHUNKS * C_NUM_SCHUNKS):
            ifix_name = f"U7IFIX{sc:02X}"
            ifix_path = os.path.join(self.static_dir, ifix_name)
            n_ifix = 0
            if os.path.isfile(ifix_path):
                try:
                    objs = self.parse_ifix(ifix_path, sc)
                    n_ifix = len(objs)
                except Exception:
                    pass
            scx = sc % C_NUM_SCHUNKS
            scy = sc // C_NUM_SCHUNKS
            result[sc] = {
                "hex": f"{sc:02X}",
                "grid_x": scx,
                "grid_y": scy,
                "ifix_objects": n_ifix,
            }
        return result


class U7MapSampler:
    """
    Colour-sampling minimap for U7 maps.

    Produces a top-down overview image by sampling the central pixel colour
    of each ground tile, scaled by configurable world-units-per-pixel.
    """

    @classmethod
    def sample_map(
        cls,
        renderer: U7MapRenderer,
        palette: U7Palette,
        *,
        schunks: list[int] | None = None,
        scale: int = 4,
        grid: bool = False,
        grid_size: int = 1,
        exclude_shapes: set[int] | None = None,
    ) -> Image.Image:
        """
        Colour-sample a minimap.

        Parameters
        ----------
        renderer:
            Initialized U7MapRenderer.
        palette:
            U7 colour palette.
        schunks:
            List of superchunk numbers to include (default: all non-empty).
        scale:
            Tiles per output pixel. 1 = full resolution (3072×3072),
            4 = 768×768, 8 = 384×384.
        grid:
            Overlay chunk (blue) and superchunk (red) grid lines
            with coordinate labels.
        grid_size:
            Grid line width.
        exclude_shapes:
            Shapes to skip.

        Returns
        -------
        PIL RGB Image.
        """
        exclude = exclude_shapes or set()

        # Output dimensions
        out_w = C_NUM_TILES // scale
        out_h = C_NUM_TILES // scale
        out = np.zeros((out_h, out_w, 3), dtype=np.uint8)

        pal_flat = np.frombuffer(palette.to_flat_rgb(), dtype=np.uint8).reshape(256, 3)

        # Shape pixel cache (center pixel colour)
        tile_color_cache: dict[tuple[int, int], tuple[int, int, int] | None] = {}
        shapes_vga = renderer.shapes_vga

        def _tile_color(shnum: int, frnum: int) -> tuple[int, int, int] | None:
            # Shape 18 frame 16 is a near-black fortress floor tile
            # (rgb 8,8,8). Remap to frame 0 (stone grey) so castles
            # don't render as black voids on the minimap.
            if shnum == 18 and frnum == 16:
                frnum = 0
            key = (shnum, frnum)
            if key in tile_color_cache:
                return tile_color_cache[key]

            rec = shapes_vga.get_record(shnum) if shnum < len(shapes_vga.records) else None
            if not rec:
                tile_color_cache[key] = None
                return None

            try:
                shape = U7Shape.from_data(rec, is_tile=(shnum < FIRST_OBJ_SHAPE))
            except Exception:
                tile_color_cache[key] = None
                return None

            if frnum >= len(shape.frames):
                tile_color_cache[key] = None
                return None

            fr = shape.frames[frnum]
            if fr.pixels is None or fr.width == 0 or fr.height == 0:
                tile_color_cache[key] = None
                return None

            # Sample center pixel
            cy = fr.height // 2
            cx = fr.width // 2
            pidx = int(fr.pixels[cy, cx])
            if pidx == 0xFF:
                # Try a few other pixels
                for dy, dx in [(0, 0), (1, 1), (2, 2)]:
                    if dy < fr.height and dx < fr.width:
                        pidx = int(fr.pixels[dy, dx])
                        if pidx != 0xFF:
                            break
            if pidx == 0xFF:
                tile_color_cache[key] = None
                return None

            color = (int(pal_flat[pidx, 0]),
                     int(pal_flat[pidx, 1]),
                     int(pal_flat[pidx, 2]))
            tile_color_cache[key] = color
            return color

        # Determine which superchunks to process
        if schunks is None:
            schunks = list(range(C_NUM_SCHUNKS * C_NUM_SCHUNKS))

        # RLE terrain shapes (>= FIRST_OBJ_SHAPE) are handled by
        # sampling a nearby flat tile for correct ground colour —
        # matching render_superchunk's nearby-flat fill logic.

        for sc in schunks:
            scx = C_CHUNKS_PER_SCHUNK * (sc % C_NUM_SCHUNKS)
            scy = C_CHUNKS_PER_SCHUNK * (sc // C_NUM_SCHUNKS)

            for cy in range(C_CHUNKS_PER_SCHUNK):
                for cx in range(C_CHUNKS_PER_SCHUNK):
                    abs_cx = scx + cx
                    abs_cy = scy + cy
                    terrain_idx = renderer.terrain_map[abs_cx][abs_cy]
                    if terrain_idx >= len(renderer.terrains):
                        continue
                    terrain = renderer.terrains[terrain_idx]

                    for tiley in range(C_TILES_PER_CHUNK):
                        for tilex in range(C_TILES_PER_CHUNK):
                            shnum, frnum = terrain[
                                tiley * C_TILES_PER_CHUNK + tilex]
                            if shnum in exclude:
                                continue

                            abs_tx = abs_cx * C_TILES_PER_CHUNK + tilex
                            abs_ty = abs_cy * C_TILES_PER_CHUNK + tiley

                            px = abs_tx // scale
                            py = abs_ty // scale
                            if px >= out_w or py >= out_h:
                                continue

                            # RLE terrain and void tile (shape 12 frame 0):
                            # fill with nearby flat tile colour.
                            # Shape 12/0 is a palette-cycling void used as
                            # filler under mountain sprites; its static
                            # sample is a misleading blue.
                            if shnum >= FIRST_OBJ_SHAPE or (
                                    shnum == 12 and frnum == 0):
                                flat = renderer._find_nearby_flat(
                                    terrain, tilex, tiley)
                                if flat:
                                    color = _tile_color(flat[0], flat[1])
                                    if color is not None:
                                        out[py, px] = color
                                continue

                            color = _tile_color(shnum, frnum)
                            if color is not None:
                                out[py, px] = color

        # Note: IFIX objects are NOT overlaid here.  Unlike the full
        # renderer (render_superchunk / render_region), which paints
        # complete sprites with proper depth sorting, the sampler maps
        # each shape to a single centre-pixel colour.  For large sprites
        # like mountain walls (shapes 180–183, 64×64 px) this produces
        # a meaningless lavender/purple dot instead of useful ground
        # colour.  The terrain's nearby-flat fill already provides the
        # correct minimap colour for RLE terrain tiles.

        img = Image.fromarray(out, mode="RGB")

        if grid:
            draw = ImageDraw.Draw(img)
            chunk_rgb = (0, 120, 255)
            sc_rgb = (255, 40, 40)

            chunk_px = C_TILES_PER_CHUNK // scale  # pixels per chunk
            schunk_px = C_CHUNKS_PER_SCHUNK * chunk_px  # pixels per SC

            # --- Chunk grid (blue) — only when spacing >= 8 px ---
            if chunk_px >= 8:
                try:
                    font_size = max(7, min(chunk_px // 3, 11))
                    chunk_font = ImageFont.truetype("arial.ttf", font_size)
                except OSError:
                    chunk_font = ImageFont.load_default()

                for i in range(C_NUM_CHUNKS + 1):
                    pos = i * chunk_px
                    if 0 <= pos < img.width:
                        draw.line([(pos, 0), (pos, img.height - 1)],
                                  fill=chunk_rgb, width=grid_size)
                    if 0 <= pos < img.height:
                        draw.line([(0, pos), (img.width - 1, pos)],
                                  fill=chunk_rgb, width=grid_size)

                # Chunk coordinate labels
                if chunk_px >= 12:
                    for cy_i in range(C_NUM_CHUNKS):
                        for cx_i in range(C_NUM_CHUNKS):
                            lx = cx_i * chunk_px + 1
                            ly = cy_i * chunk_px + 1
                            if lx < img.width and ly < img.height:
                                draw.text((lx, ly), f"{cx_i},{cy_i}",
                                          fill=chunk_rgb, font=chunk_font)

            # --- Superchunk grid (red) ---
            try:
                sc_font_size = max(8, min(schunk_px // 4, 18))
                sc_font = ImageFont.truetype("arial.ttf", sc_font_size)
            except OSError:
                sc_font = ImageFont.load_default()

            sc_line_w = max(grid_size, 2)
            for i in range(C_NUM_SCHUNKS + 1):
                pos = i * schunk_px
                if 0 <= pos < img.width:
                    draw.line([(pos, 0), (pos, img.height - 1)],
                              fill=sc_rgb, width=sc_line_w)
                if 0 <= pos < img.height:
                    draw.line([(0, pos), (img.width - 1, pos)],
                              fill=sc_rgb, width=sc_line_w)

            # Superchunk number labels
            for scy_i in range(C_NUM_SCHUNKS):
                for scx_i in range(C_NUM_SCHUNKS):
                    sc_num = scy_i * C_NUM_SCHUNKS + scx_i
                    lx = scx_i * schunk_px + 2
                    ly = scy_i * schunk_px + 2
                    if lx < img.width and ly < img.height:
                        draw.text((lx, ly), f"SC {sc_num}",
                                  fill=sc_rgb, font=sc_font)

        return img
