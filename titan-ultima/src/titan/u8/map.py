"""
Ultima 8 map renderer and sampler.

Provides :class:`U8MapRenderer` for isometric map rendering and
:class:`U8MapSampler` for top-down colour-sampled minimaps.

Example::

    from titan.u8.map import U8MapRenderer, U8MapSampler
    from titan.palette import U8Palette

    pal = U8Palette.from_file("U8PAL.PAL")

    with open("FIXED.DAT", "rb") as f:
        fixed_data = f.read()

    all_maps = U8MapRenderer.parse_fixed_dat(fixed_data)
    objects = all_maps[0]
    objects = U8MapRenderer.expand_globs(objects, "glob_extract/")

    img = U8MapRenderer.render_map(objects, "u8shapes/", pal)
    img.save("map_000.png")
"""

from __future__ import annotations

__all__ = ["U8MapRenderer", "U8MapSampler"]

import copy
import os
import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from titan.flex import FlexArchive
from titan.palette import U8Palette
from titan.u8.shape import U8Shape
from titan.u8.typeflag import U8TypeFlags
from titan.u8.save import U8SaveArchive


class U8MapRenderer:
    """
    Render Ultima 8 maps from FIXED.DAT, GLOB.FLX, and shape/palette data.

    Map data (FIXED.DAT / NONFIXED.DAT):
        - 256 maps, each containing 16-byte object entries.
        - Objects with type==2 are GLOB references (quality=glob number).
        - Isometric projection::

            ScreenX = (MapX - MapY) / 4
            ScreenY = (MapX + MapY) / 8 - MapZ

    GLOB.FLX:
        - Pre-assembled map building blocks ("stamps").
        - Each glob contains N x 6-byte sub-objects (X,Y,Z, type, frame).
        - Sub-objects are placed relative to the parent's chunk-aligned coords.
    """

    @dataclass
    class MapObject:
        """A resolved map object ready for rendering."""

        x: int
        y: int
        z: int
        type_num: int
        frame: int
        # Screen coordinates (set during projection)
        screen_x: int = 0
        screen_y: int = 0

    @classmethod
    def parse_fixed_dat(cls, data: bytes) -> dict[int, list[U8MapRenderer.MapObject]]:
        """
        Parse FIXED.DAT into a dict of ``map_number -> list[MapObject]``.

        Only non-empty maps are included.
        """
        if len(data) < 128 + 8:
            return {}
        num_maps = struct.unpack_from("<H", data, 84)[0]
        maps: dict[int, list[U8MapRenderer.MapObject]] = {}

        for m in range(num_maps):
            info_off = 128 + m * 8
            if info_off + 8 > len(data):
                break
            map_pos = struct.unpack_from("<I", data, info_off)[0]
            map_size = struct.unpack_from("<I", data, info_off + 4)[0]
            if map_size == 0:
                continue
            num_objects = map_size // 16
            objects: list[U8MapRenderer.MapObject] = []
            for i in range(num_objects):
                o = map_pos + i * 16
                if o + 16 > len(data):
                    break
                obj_x = struct.unpack_from("<H", data, o)[0]
                obj_y = struct.unpack_from("<H", data, o + 2)[0]
                obj_z = data[o + 4]
                type_num = struct.unpack_from("<H", data, o + 5)[0]
                frame = data[o + 7]
                quality = struct.unpack_from("<H", data, o + 10)[0]
                objects.append(cls.MapObject(
                    x=obj_x, y=obj_y, z=obj_z,
                    type_num=type_num, frame=frame,
                ))
                # Store quality for glob expansion
                objects[-1]._quality = quality  # type: ignore[attr-defined]
            maps[m] = objects
        return maps

    @classmethod
    def load_glob(cls, glob_data: bytes) -> list[U8MapRenderer.MapObject]:
        """Parse a single GLOB record into sub-objects."""
        if len(glob_data) < 2:
            return []
        num = struct.unpack_from("<H", glob_data, 0)[0]
        objs: list[U8MapRenderer.MapObject] = []
        for i in range(num):
            off = 2 + i * 6
            if off + 6 > len(glob_data):
                break
            gx = glob_data[off]
            gy = glob_data[off + 1]
            gz = glob_data[off + 2]
            gtype = struct.unpack_from("<H", glob_data, off + 3)[0]
            gframe = glob_data[off + 5]
            objs.append(cls.MapObject(x=gx, y=gy, z=gz,
                                      type_num=gtype, frame=gframe))
        return objs

    @classmethod
    def expand_globs(
        cls,
        objects: list[U8MapRenderer.MapObject],
        glob_dir: str,
    ) -> list[U8MapRenderer.MapObject]:
        """
        Replace GLOB objects (type==2) with their expanded sub-objects.

        GLOB placement formula::

            MapX = GlobSubX * 2 + (OrigX & ~0x1FF)
            MapY = GlobSubY * 2 + (OrigY & ~0x1FF)
            MapZ = GlobSubZ + OrigZ
        """
        result: list[U8MapRenderer.MapObject] = []
        glob_cache: dict[int, list[U8MapRenderer.MapObject]] = {}

        for obj in objects:
            if obj.type_num != 2:
                result.append(obj)
                continue

            quality = getattr(obj, "_quality", 0)
            glob_file = os.path.join(glob_dir, f"{quality:04d}.dat")
            if not os.path.isfile(glob_file):
                continue

            if quality not in glob_cache:
                with open(glob_file, "rb") as f:
                    glob_cache[quality] = cls.load_glob(f.read())

            base_x = obj.x & ~0x1FF
            base_y = obj.y & ~0x1FF
            base_z = obj.z

            for sub in glob_cache[quality]:
                result.append(cls.MapObject(
                    x=sub.x * 2 + base_x,
                    y=sub.y * 2 + base_y,
                    z=sub.z + base_z,
                    type_num=sub.type_num,
                    frame=sub.frame,
                ))
        return result

    @staticmethod
    def build_exclude_set(typeflag_path: str, **exclude_flags: bool) -> set[int]:
        """
        Build a set of shape numbers to exclude based on typeflag criteria.

        Exclude flag names (keyword args):
            no_fixed, no_solid, no_sea, no_land, no_occl, no_bag,
            no_damaging, no_noisy, no_draw, no_ignore, no_roof, no_transl,
            no_editor, no_explode, no_unk46, no_unk47

        Shape is excluded if ANY of its enabled exclude flags match.
        """
        _flag_bits: dict[str, tuple[int, int]] = {
            'no_fixed': (0, 0x01),
            'no_solid': (0, 0x02),
            'no_sea': (0, 0x04),
            'no_land': (0, 0x08),
            'no_occl': (0, 0x10),
            'no_bag': (0, 0x20),
            'no_damaging': (0, 0x40),
            'no_noisy': (0, 0x80),
            'no_draw': (1, 0x01),
            'no_ignore': (1, 0x02),
            'no_roof': (1, 0x04),
            'no_transl': (1, 0x08),
            'no_editor': (5, 0x10),
            'no_explode': (5, 0x20),
            'no_unk46': (5, 0x40),
            'no_unk47': (5, 0x80),
        }

        if not os.path.isfile(typeflag_path):
            raise FileNotFoundError(
                f"typeflag.dat not found: {typeflag_path}")
        with open(typeflag_path, "rb") as _f:
            _data = _f.read()

        _block = 8
        _exclude_set: set[int] = set()

        for _i in range(len(_data) // _block):
            _off = _i * _block
            _bytes = _data[_off:_off + 8]
            for _flag_name in exclude_flags:
                if exclude_flags[_flag_name] and _flag_name in _flag_bits:
                    _byte_idx, _bit_mask = _flag_bits[_flag_name]
                    if _bytes[_byte_idx] & _bit_mask:
                        _exclude_set.add(_i)
                        break

        return _exclude_set

    @staticmethod
    def parse_nonfixed(
        nf_flex_data: bytes,
        typeflag_data: Optional[bytes] = None,
    ) -> dict[int, list[U8MapRenderer.MapObject]]:
        """
        Parse NONFIXED.DAT (a Flex archive of per-map 16-byte item records).

        NONFIXED.DAT lives inside U8SAVE.000 and contains dynamic world objects.
        Each Flex slot corresponds to a map number.

        If *typeflag_data* is supplied, container depth tracking is used to
        return only top-level (world-placed) objects.
        """
        flex = FlexArchive.from_bytes(nf_flex_data)

        container_shapes: set[int] = set()
        if typeflag_data:
            container_shapes = U8TypeFlags.container_shapes(typeflag_data)

        maps: dict[int, list[U8MapRenderer.MapObject]] = {}

        for map_num in range(len(flex.records)):
            entry = flex.records[map_num]
            if not entry or len(entry) < 16:
                continue

            item_count = len(entry) // 16
            objects: list[U8MapRenderer.MapObject] = []
            contdepth = 0

            for i in range(item_count):
                o = i * 16
                x = struct.unpack_from("<h", entry, o)[0]
                y = struct.unpack_from("<h", entry, o + 2)[0]
                z = entry[o + 4]
                shape = struct.unpack_from("<H", entry, o + 5)[0]
                frame = entry[o + 7]
                quality = struct.unpack_from("<H", entry, o + 10)[0]

                if typeflag_data:
                    while contdepth != x and contdepth > 0:
                        contdepth -= 1

                if contdepth == 0 or not typeflag_data:
                    obj = U8MapRenderer.MapObject(
                        x=x, y=y, z=z,
                        type_num=shape, frame=frame,
                    )
                    obj._quality = quality  # type: ignore[attr-defined]
                    objects.append(obj)

                if typeflag_data and shape in container_shapes:
                    contdepth += 1

            if objects:
                maps[map_num] = objects

        return maps

    @staticmethod
    def load_nonfixed(
        nonfixed_path: str,
        typeflag_path: Optional[str] = None,
    ) -> dict[int, list[U8MapRenderer.MapObject]]:
        """
        Load NONFIXED.DAT objects.  Accepts either:

        - A U8 save file (U8SAVE.000) — extracts NONFIXED.DAT from it.
        - A raw NONFIXED.DAT Flex archive.
        """
        with open(nonfixed_path, "rb") as f:
            data = f.read()

        if U8SaveArchive.is_save_file(data):
            save = U8SaveArchive.from_bytes(data)
            nf = save.get_data("NONFIXED.DAT")
            if nf is None:
                raise ValueError(f"NONFIXED.DAT not found inside {nonfixed_path}")
        else:
            nf = data

        tf_data: Optional[bytes] = None
        if typeflag_path:
            with open(typeflag_path, "rb") as f:
                tf_data = f.read()

        return U8MapRenderer.parse_nonfixed(nf, tf_data)

    # -----------------------------------------------------------------------
    # Projection views
    # -----------------------------------------------------------------------

    PROJECTIONS: dict[str, tuple] = {
        "iso_classic": (
            lambda x, y, z: (x - y) // 4,
            lambda x, y, z: (x + y) // 8 - z,
            lambda x, y, z: (x + y, x, z),
        ),
        "iso_high": (
            lambda x, y, z: (x - y) // 6,
            lambda x, y, z: (x + y) // 6 - z * 2,
            lambda x, y, z: (x + y, x, z),
        ),
        "iso_low": (
            lambda x, y, z: (x - y) // 3,
            lambda x, y, z: (x + y) // 12 - z // 2,
            lambda x, y, z: (x + y, x, z),
        ),
        "iso_north": (
            lambda x, y, z: y // 4,
            lambda x, y, z: x // 8 - z,
            lambda x, y, z: (x, y, z),
        ),
        "iso_south": (
            lambda x, y, z: -y // 4,
            lambda x, y, z: -x // 8 - z,
            lambda x, y, z: (-x, -y, z),
        ),
        "birdseye": (
            lambda x, y, z: x // 4,
            lambda x, y, z: y // 4,
            lambda x, y, z: (z, x + y, x),
        ),
    }

    DEFAULT_VIEW: str = "iso_classic"

    @classmethod
    def project(
        cls,
        obj: U8MapRenderer.MapObject,
        view: str = "iso_classic",
    ) -> None:
        """Calculate screen coordinates for an object using the named view."""
        sx_fn, sy_fn, _ = cls.PROJECTIONS.get(view, cls.PROJECTIONS[cls.DEFAULT_VIEW])
        obj.screen_x = sx_fn(obj.x, obj.y, obj.z)
        obj.screen_y = sy_fn(obj.x, obj.y, obj.z)

    @classmethod
    def render_map(
        cls,
        map_objects: list[U8MapRenderer.MapObject],
        shapes_dir: str,
        palette: U8Palette,
        *,
        view: str = "iso_classic",
        background: tuple[int, int, int, int] = (0, 0, 0, 255),
        grid: bool = False,
        grid_size: int = 2,
        typeflag_path: Optional[str] = None,
    ) -> Image.Image:
        """
        Render a list of map objects to a PIL RGBA image.

        Args:
            map_objects: Resolved and glob-expanded object list.
            shapes_dir: Directory of extracted .shp files.
            palette: Colour palette for shape rendering.
            view: Projection view name.
            background: Background fill colour (RGBA).
            grid: Whether to overlay chunk grid lines.
            grid_size: Grid line thickness in pixels.
            typeflag_path: Optional path to TYPEFLAG.DAT. When provided,
                shape footpad dimensions are used for more accurate
                depth sorting (fixes walls hidden behind floor tiles).

        Returns:
            PIL RGBA Image of the rendered map.
        """
        sx_fn, sy_fn, depth_fn = cls.PROJECTIONS.get(view, cls.PROJECTIONS[cls.DEFAULT_VIEW])

        for obj in map_objects:
            cls.project(obj, view)

        # ----- Depth sort -----
        # When TYPEFLAG dimensions are available we use a Pentagram-style
        # pairwise comparison that checks for clear 3-axis separation of
        # each object's bounding box (back-left-bottom … front-right-top)
        # before falling through to midpoint and diagonal tie-breakers.
        # Without TYPEFLAG we fall back to the simple key-based sort.
        if typeflag_path and os.path.isfile(typeflag_path):
            tf_entries = U8TypeFlags.from_file(typeflag_path)
            # Per-shape: (footX, footY, footZ, anim, trans, draw, solid, occl)
            _info: dict[int, tuple[int, int, int, int, int, int, int, int]] = {}
            for e in tf_entries:
                _info[e.shape_num] = (
                    e.x * 32, e.y * 32, e.z * 8,
                    1 if e.animtype != 0 else 0,
                    1 if e.flags & 0x0800 else 0,   # SI_TRANSL
                    1 if e.flags & 0x0100 else 0,   # SI_DRAW
                    1 if e.flags & 0x0002 else 0,   # SI_SOLID
                    1 if e.flags & 0x0010 else 0,   # SI_OCCL
                )
            _zero_info = (0, 0, 0, 0, 0, 0, 0, 0)

            # Build sort items as tuples for fast comparison:
            # (x, y, z, xleft, yfar, ztop, flat, f32x32,
            #  anim, trans, draw, solid, occl,
            #  type_num, frame, obj_ref)
            _si = []
            for obj in map_objects:
                fx, fy, fz, _a, _t, _d, _s, _o = _info.get(
                    obj.type_num, _zero_info)
                _si.append((
                    obj.x, obj.y, obj.z,
                    obj.x - fx,              # xleft  (back x)
                    obj.y - fy,              # yfar   (back y)
                    obj.z + fz,              # ztop   (top z)
                    1 if fz == 0 else 0,     # flat
                    1 if fx == 128 and fy == 128 else 0,  # f32x32
                    _a, _t, _d, _s, _o,     # anim, trans, draw, solid, occl
                    obj.type_num, obj.frame,
                    obj,
                ))

            def _cmp(a: tuple, b: tuple) -> int:
                """Pentagram-inspired isometric depth comparison.

                Returns -1 if *a* should be drawn before (behind) *b*.
                Ported from Pentagram ``SortItem::operator<`` in
                ``world/ItemSorter.cpp``.
                """
                (ax, ay, az, axl, ayf, azt, af, af32,
                 aa, atr, adr, aso, aoc,
                 at, afr, _) = a
                (bx, by, bz, bxl, byf, bzt, bf, bf32,
                 ba, btr, bdr, bso, boc,
                 bt, bfr, _) = b

                # --- Both flat (zero z-height) ---
                if af and bf:
                    if azt != bzt:
                        return -1 if azt < bzt else 1
                    # Animated always drawn after
                    if aa != ba:
                        return -1 if aa < ba else 1
                    # Translucent always drawn after
                    if atr != btr:
                        return -1 if atr < btr else 1
                    # Draw flag — drawn first
                    if adr != bdr:
                        return -1 if adr > bdr else 1
                    # Solid — drawn first
                    if aso != bso:
                        return -1 if aso > bso else 1
                    # Occluding — drawn first
                    if aoc != boc:
                        return -1 if aoc > boc else 1
                    # 32×32 ground tiles sort first among equal-z flats
                    if af32 != bf32:
                        return -1 if af32 > bf32 else 1
                    # (fall through to x/y separation)
                else:
                    # --- Clear z separation (non-flat) ---
                    if azt <= bz:
                        return -1
                    if bzt <= az:
                        return 1

                # --- Clear x separation (front edge vs back edge) ---
                if ax <= bxl:
                    return -1
                if bx <= axl:
                    return 1

                # --- Clear y separation ---
                if ay <= byf:
                    return -1
                if by <= ayf:
                    return 1

                # ----- Items overlap in all three axes -----

                # Lower z-base draws first
                if az != bz:
                    return -1 if az < bz else 1

                # Biased z: midpoint vs base
                if (azt + az) // 2 <= bz:
                    return -1
                if az >= (bzt + bz) // 2:
                    return 1

                # Biased x: midpoint vs back edge
                if (ax + axl) // 2 <= bxl:
                    return -1
                if axl >= (bx + bxl) // 2:
                    return 1

                # Biased y: midpoint vs far edge
                if (ay + ayf) // 2 <= byf:
                    return -1
                if ayf >= (by + byf) // 2:
                    return 1

                # Front diagonal (x + y) — further from camera first
                axy = ax + ay
                bxy = bx + by
                if axy != bxy:
                    return -1 if axy < bxy else 1

                # Back diagonal (xleft + yfar)
                aback = axl + ayf
                bback = bxl + byf
                if aback != bback:
                    return -1 if aback < bback else 1

                # Final tie-breakers
                if ax != bx:
                    return -1 if ax < bx else 1
                if ay != by:
                    return -1 if ay < by else 1
                if at != bt:
                    return -1 if at < bt else 1
                if afr != bfr:
                    return -1 if afr < bfr else 1
                return 0

            # --- Dependency-graph sort (Pentagram PaintSortItem) ---
            # 1. Initial sort by (z, x, y) — a simple total order for
            #    DFS traversal, matching Pentagram's ListLessThan.
            _si.sort(key=lambda item: (item[2], item[0], item[1]))
            _n = len(_si)

            # 2. Compute screen-space bounding boxes for overlap tests.
            #    Pentagram formulas (iso_classic projection):
            #      sxleft  = xleft/4 - y/4
            #      sxright = x/4     - yfar/4
            #      sytop   = xleft/8 + yfar/8 - ztop
            #      sybot   = x/8     + y/8    - z
            _ss = []
            for _item in _si:
                _ix, _iy, _iz = _item[0], _item[1], _item[2]
                _ixl, _iyf, _izt = _item[3], _item[4], _item[5]
                _ss.append((
                    _ixl // 4 - _iy // 4,       # sxleft
                    _ix // 4 - _iyf // 4,        # sxright
                    _ixl // 8 + _iyf // 8 - _izt, # sytop
                    _ix // 8 + _iy // 8 - _iz,   # sybot
                ))

            # 3. Build dependency graph via sweep-line on screen-X.
            #    For each pair that overlaps on screen, use _cmp to
            #    determine which item paints first (dependency edge).
            _deps: list[list[int]] = [[] for _ in range(_n)]
            _sweep = sorted(range(_n), key=lambda i: _ss[i][0])
            _active: list[int] = []
            for _idx in _sweep:
                _sxl_cur = _ss[_idx][0]
                # Prune expired items from active set
                _active = [a for a in _active
                           if _ss[a][1] > _sxl_cur]
                for _other in _active:
                    _a = _ss[_idx]
                    _b = _ss[_other]
                    # Screen-Y overlap check (AABB)
                    if _a[2] < _b[3] and _b[2] < _a[3]:
                        _cr = _cmp(_si[_idx], _si[_other])
                        if _cr < 0:
                            _deps[_other].append(_idx)
                        elif _cr > 0:
                            _deps[_idx].append(_other)
                _active.append(_idx)

            # 4. Topological DFS paint order (iterative to avoid
            #    Python recursion limits).  Matches Pentagram's
            #    PaintSortItem: paint all dependencies first, then self.
            _order: list[int] = []
            _state = bytearray(_n)  # 0=white 1=gray 2=black
            for _start in range(_n):
                if _state[_start] != 0:
                    continue
                _stack = [(_start, 0)]
                while _stack:
                    _node, _di = _stack[-1]
                    if _state[_node] == 2:
                        _stack.pop()
                        continue
                    if _state[_node] == 0:
                        _state[_node] = 1
                    if _di < len(_deps[_node]):
                        _stack[-1] = (_node, _di + 1)
                        _dep = _deps[_node][_di]
                        if _state[_dep] == 0:
                            _stack.append((_dep, 0))
                        # gray (1) = cycle → skip silently
                    else:
                        _state[_node] = 2
                        _order.append(_node)
                        _stack.pop()

            map_objects[:] = [_si[i][-1] for i in _order]
        else:
            map_objects.sort(key=lambda o: depth_fn(o.x, o.y, o.z))

        if not map_objects:
            return Image.new("RGBA", (1, 1), background)

        min_sx = min(o.screen_x for o in map_objects)
        max_sx = max(o.screen_x for o in map_objects)
        min_sy = min(o.screen_y for o in map_objects)
        max_sy = max(o.screen_y for o in map_objects)

        pad = 256
        width = (max_sx - min_sx) + pad * 2
        height = (max_sy - min_sy) + pad * 2

        off_x = -min_sx + pad
        off_y = -min_sy + pad

        canvas = Image.new("RGBA", (width, height), background)

        shape_cache: dict[int, Optional[U8Shape]] = {}
        frame_cache: dict[tuple[int, int], Optional[tuple[Image.Image, int, int]]] = {}

        flat_rgb = palette.to_flat_rgb()
        rendered = 0
        skipped = 0

        for obj in map_objects:
            key = (obj.type_num, obj.frame)

            if key not in frame_cache:
                if obj.type_num not in shape_cache:
                    shp_path = os.path.join(shapes_dir,
                                            f"{obj.type_num:04d}.shp")
                    if os.path.isfile(shp_path):
                        try:
                            shape_cache[obj.type_num] = U8Shape.from_file(shp_path)
                        except Exception:
                            shape_cache[obj.type_num] = None
                    else:
                        shape_cache[obj.type_num] = None

                shape = shape_cache[obj.type_num]
                if (shape is not None and 0 <= obj.frame < len(shape.frames)):
                    fr = shape.frames[obj.frame]
                    if (fr.pixels is not None
                            and fr.width > 0 and fr.height > 0):
                        indexed = Image.fromarray(fr.pixels, mode="P")
                        indexed.putpalette(flat_rgb)
                        rgba = indexed.convert("RGBA")
                        alpha = np.where(fr.pixels == 0xFF, 0,
                                         255).astype(np.uint8)
                        rgba.putalpha(Image.fromarray(alpha, mode="L"))
                        frame_cache[key] = (rgba, fr.xoff, fr.yoff)
                    else:
                        frame_cache[key] = None
                else:
                    frame_cache[key] = None

            entry = frame_cache.get(key)
            if entry is None:
                skipped += 1
                continue

            img, xoff, yoff = entry

            if view == "birdseye":
                px = obj.screen_x + off_x
                py = obj.screen_y + off_y
            else:
                px = obj.screen_x + off_x - xoff
                py = obj.screen_y + off_y - yoff

            if px + img.width <= 0 or py + img.height <= 0:
                skipped += 1
                continue

            if px < -img.width or py < -img.height:
                skipped += 1
                continue

            canvas.alpha_composite(img, dest=(px, py))
            rendered += 1

        if grid:
            _draw = ImageDraw.Draw(canvas)
            _grid_rgba = (0, 120, 255, 150)
            _CHUNK = 512
            _MAP_END = 64 * _CHUNK
            for _n in range(65):
                _wx = _n * _CHUNK
                _x0 = sx_fn(_wx, 0, 0) + off_x
                _y0 = sy_fn(_wx, 0, 0) + off_y
                _x1 = sx_fn(_wx, _MAP_END, 0) + off_x
                _y1 = sy_fn(_wx, _MAP_END, 0) + off_y
                _draw.line([(_x0, _y0), (_x1, _y1)],
                           fill=_grid_rgba, width=grid_size)
            for _n in range(65):
                _wy = _n * _CHUNK
                _x0 = sx_fn(0, _wy, 0) + off_x
                _y0 = sy_fn(0, _wy, 0) + off_y
                _x1 = sx_fn(_MAP_END, _wy, 0) + off_x
                _y1 = sy_fn(_MAP_END, _wy, 0) + off_y
                _draw.line([(_x0, _y0), (_x1, _y1)],
                           fill=_grid_rgba, width=grid_size)

            # Chunk coordinate labels at each grid intersection
            try:
                _font = ImageFont.truetype("arial.ttf", 10)
            except OSError:
                _font = ImageFont.load_default()
            for _cy in range(64):
                for _cx in range(64):
                    _wx = _cx * _CHUNK
                    _wy = _cy * _CHUNK
                    _lx = sx_fn(_wx, _wy, 0) + off_x + 2
                    _ly = sy_fn(_wx, _wy, 0) + off_y + 1
                    _draw.text((_lx, _ly), f"{_cx},{_cy}",
                               fill=_grid_rgba, font=_font)

        return canvas


class U8MapSampler:
    """
    Colour-sampling minimap technique (reproduces Pentagram's MiniMapGump).

    Default scale of 64 world units/pixel reproduces the original minimap
    resolution (512 x 512 for a 32768-unit U8 map).
    """

    _U8_CHUNK_SIZE: int = 512
    _U8_NUM_CHUNKS: int = 64

    @classmethod
    def sample_map(
        cls,
        map_objects: list,
        shapes_dir: str,
        palette: U8Palette,
        *,
        scale: int = 64,
        grid: bool = False,
        grid_size: int = 2,
    ) -> Image.Image:
        """
        Render a colour-sampled top-down map.

        Args:
            map_objects: Glob-expanded object list (from U8MapRenderer).
            shapes_dir:  Directory of extracted .shp files.
            palette:     U8 colour palette.
            scale:       World units per output pixel (default 64 -> 512 px).
            grid:        Overlay chunk grid lines.
            grid_size:   Grid line thickness in pixels.

        Returns:
            PIL RGB Image.
        """
        if not map_objects:
            return Image.new("RGB", (1, 1), (0, 0, 0))

        max_x = max(o.x for o in map_objects)
        max_y = max(o.y for o in map_objects)
        img_w = max(1, (max_x // scale) + 2)
        img_h = max(1, (max_y // scale) + 2)

        out = np.zeros((img_h, img_w, 3), dtype=np.uint8)

        pal_flat = np.frombuffer(palette.to_flat_rgb(), dtype=np.uint8).reshape(256, 3)

        shape_cache: dict[int, Optional[U8Shape]] = {}

        sorted_objects = sorted(map_objects, key=lambda o: o.z)

        for obj in sorted_objects:
            if obj.type_num not in shape_cache:
                shp_path = os.path.join(shapes_dir, f"{obj.type_num:04d}.shp")
                try:
                    shape_cache[obj.type_num] = (
                        U8Shape.from_file(shp_path)
                        if os.path.isfile(shp_path) else None
                    )
                except Exception:
                    shape_cache[obj.type_num] = None

            shape = shape_cache[obj.type_num]
            if shape is None or obj.frame >= len(shape.frames):
                continue
            fr = shape.frames[obj.frame]
            if fr.pixels is None or fr.width == 0 or fr.height == 0:
                continue

            footpad = max(scale, fr.width * 2)

            px_min = max(0, (obj.x - footpad) // scale)
            px_max = min(img_w - 1, (obj.x - 1) // scale)
            py_min = max(0, (obj.y - footpad) // scale)
            py_max = min(img_h - 1, (obj.y - 1) // scale)

            if px_min > px_max or py_min > py_max:
                continue

            iso_sx = 0
            iso_sy = footpad >> 3

            r_sum = g_sum = b_sum = cnt = 0
            for fj in range(2):
                for fi in range(2):
                    ax = (fi - iso_sx) + fr.xoff
                    ay = (fj - iso_sy) + fr.yoff
                    if ax < 0 or ay < 0 or ax >= fr.width or ay >= fr.height:
                        continue
                    pidx = fr.pixels[ay, ax]
                    if pidx == 0xFF:
                        continue
                    r_sum += int(pal_flat[pidx, 0])
                    g_sum += int(pal_flat[pidx, 1])
                    b_sum += int(pal_flat[pidx, 2])
                    cnt += 1

            if not cnt:
                continue

            color = np.array(
                [r_sum // cnt, g_sum // cnt, b_sum // cnt], dtype=np.uint8
            )

            out[py_min:py_max + 1, px_min:px_max + 1] = color

        _img = Image.fromarray(out, mode="RGB")
        if grid:
            _draw = ImageDraw.Draw(_img)
            _grid_rgb = (0, 0, 255)
            _CHUNK = 512
            for _n in range(65):
                _pos = (_n * _CHUNK) // scale
                if 0 <= _pos < _img.width:
                    _draw.line([(_pos, 0), (_pos, _img.height - 1)],
                               fill=_grid_rgb, width=grid_size)
                if 0 <= _pos < _img.height:
                    _draw.line([(0, _pos), (_img.width - 1, _pos)],
                               fill=_grid_rgb, width=grid_size)

            # Chunk coordinate labels
            try:
                _font = ImageFont.truetype("arial.ttf", 10)
            except OSError:
                _font = ImageFont.load_default()
            for _cy in range(64):
                for _cx in range(64):
                    _px = (_cx * _CHUNK) // scale + 2
                    _py = (_cy * _CHUNK) // scale + 1
                    if 0 <= _px < _img.width and 0 <= _py < _img.height:
                        _draw.text((_px, _py), f"{_cx},{_cy}",
                                   fill=_grid_rgb, font=_font)
        return _img
