"""House placement legality and packing capacity over a whole facet.

Ports the map-based parts of RunUO ``HousePlacement.Check`` and applies them
to every candidate centre at once with numpy:

- Regions: every occupied cell must be in a region that allows housing, and
  the centre must not be in a NoHousingRegion or Felucca T2A.
- Occupied cells: no road land. For each house tile, the land must not rise
  above it (``BadLand``) and no impassable or non-background surface static
  may overlap it vertically (``BadStatic``).
- Foundation tiles must sit on passable land whose average z equals the
  house z (``NoSurface``). That fixes the house z to the land under the
  foundation.
- Border cells: no impassable or road land, no impassable static, and no
  non-background surface static rising more than 2 above the house z.

Items, mobiles and existing houses are server state and are not modelled.
Packing places houses greedily in row-major order. Each new house's yard
and tiles must stay clear of earlier houses' tiles, which is RunUO's
house-to-house rule. The result is therefore a lower bound on capacity.
"""

from __future__ import annotations

__all__ = [
    "REASONS",
    "PlacementGrids",
    "build_placement_grids",
    "evaluate_placement",
    "legal_centres",
    "level_foundation_centres",
    "PlacementResult",
    "RegionLayer",
    "load_region_layers",
    "region_layers_from_rects",
    "region_outlines",
    "region_outlines_from_rects",
    "coverage",
    "no_housing_region_types",
    "load_region_mask",
    "pack_houses",
    "placement_legality",
]

from dataclasses import dataclass, field
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np

from titan.uo.housing import HouseFootprint, house_footprint
from titan.uo.map import UOMap
from titan.uo.multi import UOMulti
from titan.uo.tiledata import UOTileData

# RunUO HousePlacement.m_RoadIDs: inclusive land ID ranges.
ROAD_LAND_RANGES = (
    (0x0071, 0x0078),
    (0x00E8, 0x00EB),
    (0x07AE, 0x07B1),
    (0x3FF4, 0x3FF4),
    (0x3FF8, 0x3FFB),
    (0x0442, 0x0479),
    (0x0501, 0x0510),
    (0x0009, 0x0015),
    (0x0150, 0x015C),
)
# Region types whose AllowHousing is false for players (RunUO Scripts/Regions).
NO_HOUSING_REGION_TYPES = frozenset(
    ("GuardedRegion", "TownRegion", "DungeonRegion", "Jail", "NoHousingRegion", "GreenAcres")
)
FELUCCA_T2A = (5120, 2304, 6144, 4096)  # SpellHelper.IsFeluccaT2A: x0, y0, x1, y1
# Rejection reasons, in the order a centre is attributed to its first failure.
REASONS = (
    "centre_region",  # centre in a NoHousingRegion or Felucca T2A
    "region",  # an occupied cell's region forbids housing
    "road",  # road land under the house
    "impassable_ground",  # foundation over impassable land (water, rock)
    "not_level",  # foundation land not exactly at the house z
    "land_above",  # land rises above a house tile
    "static",  # a blocking static overlaps a house tile
    "dense_statics",  # more blocking statics in a cell than modelled
    "border_land",  # impassable or road land in the border
    "border_static",  # blocking static in the border
)

_IMPASSABLE = 0x40
_SURFACE = 0x200
_BACKGROUND = 0x1
_BRIDGE = 0x400
_WALL = 0x10
_MAX_STACK = 6  # blocking statics kept per cell; denser cells count as blocked
_INF = np.int16(32000)


@dataclass
class PlacementResult:
    """Legal centres for one house over a facet window."""

    multi_id: int
    footprint: HouseFootprint
    x0: int
    y0: int
    legal: np.ndarray  # (h, w) bool, centres at (x0 + col, y0 + row)
    reasons: dict[str, int] = field(default_factory=dict)
    house_z: np.ndarray | None = None  # (h, w) int16 house z per centre
    # (h, w) uint8: 0 legal, else 1 + index into REASONS of the first failing rule
    reason_grid: np.ndarray | None = None

    @property
    def legal_count(self) -> int:
        return int(self.legal.sum())


_CLASS_DECL = re.compile(r"class\s+(\w+)\s*:\s*([\w.]+)")
_ALLOW_HOUSING = re.compile(r"override\s+bool\s+AllowHousing\s*\([^)]*\)\s*\{")


def _method_body(text: str, open_brace: int) -> str:
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : index]
    return text[open_brace + 1 :]


def no_housing_region_types(scripts_dir: str | Path) -> frozenset[str]:
    """Region classes whose AllowHousing is false for players, from emulator source.

    A class forbids housing when it, or a base class, overrides
    ``AllowHousing`` with a body that returns ``false`` on some path
    (including player-only checks such as GreenAcres), or returns a field
    (as NoHousingRegion's ``m_SmartChecking`` does; false by default).
    BaseHouse's owner check is not a region rule and is ignored.
    """
    bases: dict[str, str] = {}
    roots: set[str] = set()
    for path in Path(scripts_dir).rglob("*.cs"):
        text = path.read_text(encoding="utf-8", errors="replace")
        decls = list(_CLASS_DECL.finditer(text))
        for decl in decls:
            bases.setdefault(decl.group(1), decl.group(2).split(".")[-1])
        for override in _ALLOW_HOUSING.finditer(text):
            owner = None
            for decl in decls:
                if decl.start() < override.start():
                    owner = decl.group(1)
            body = _method_body(text, override.end() - 1)
            if owner and owner != "BaseHouse" and (
                re.search(r"return\s+false\s*;", body)
                or re.search(r"return\s+(this\.)?m_\w+\s*;", body)
            ):
                roots.add(owner)

    def forbids(name: str) -> bool:
        seen = set()
        while name and name not in seen:
            if name in roots:
                return True
            seen.add(name)
            name = bases.get(name, "")
        return False

    return frozenset(name for name in bases if forbids(name))


@dataclass
class RegionLayer:
    """Region rules for house z in ``[z_min, z_max)``."""

    z_min: int
    z_max: int
    blocked: np.ndarray  # AllowHousing false for a player
    centre: np.ndarray  # inside a NoHousingRegion chain (centre rule)


_REGION_MIN_Z, _REGION_MAX_Z = -128, 128  # Region.MinZ / MaxZ


def _parse_region_rects(path, facet_name, forbidding_types):
    """Every region rectangle of one facet, lowest rank first.

    Each item is ``(rank key, allow, in no-housing chain, x, y, w, h, z1, z2,
    name, type)``; see :func:`load_region_layers` for the rules.
    """
    root = ET.parse(path).getroot()
    facet = next(
        (f for f in root.iter("Facet") if f.get("name", "").lower() == facet_name.lower()),
        None,
    )
    if facet is None:
        raise ValueError(f"no <Facet name={facet_name!r}> in {path}")
    types = NO_HOUSING_REGION_TYPES if forbidding_types is None else forbidding_types
    rects: list[tuple] = []
    counts: dict[str, int] = {}
    order = 0

    def walk(element, parent_priority, level, parent_allow, parent_no_housing, parent_name):
        nonlocal order
        for region in element.findall("region"):
            rtype = region.get("type", "")
            name = region.get("name") or parent_name or rtype
            priority = int(region.get("priority", parent_priority))
            if rtype == "NoHousingRegion":
                smart = region.find("smartNoHousing")
                allow = smart is not None and smart.get("active", "").lower() == "true"
            elif rtype in types:
                allow = False
            else:
                allow = parent_allow
            no_housing = parent_no_housing or rtype == "NoHousingRegion"
            if not allow:
                counts[rtype] = counts.get(rtype, 0) + 1
            zrange = region.find("zrange")
            rz1 = int(zrange.get("min", _REGION_MIN_Z)) if zrange is not None else _REGION_MIN_Z
            rz2 = int(zrange.get("max", _REGION_MAX_Z)) if zrange is not None else _REGION_MAX_Z
            key = (priority, level, -order)
            order += 1
            for r in region.findall("rect"):
                rects.append((
                    key, allow, no_housing,
                    int(r.get("x", 0)), int(r.get("y", 0)),
                    int(r.get("width", 0)), int(r.get("height", 0)),
                    int(r.get("zmin", rz1)), int(r.get("zmax", rz2)),
                    name, rtype,
                ))
            walk(region, priority, level + 1, allow, no_housing, name)

    walk(facet, 50, 0, True, False, "")
    rects.sort(key=lambda r: r[0])
    return rects, counts


def region_outlines(
    path: str | Path,
    facet_name: str,
    *,
    forbidding_types: frozenset[str] | None = None,
    z: int = 0,
) -> list[dict[str, object]]:
    """Region rectangles from ``Regions.xml`` that contain house z ``z``.

    See :func:`region_outlines_from_rects`.
    """
    rects, _counts = _parse_region_rects(path, facet_name, forbidding_types)
    return region_outlines_from_rects(rects, z=z)


def region_outlines_from_rects(rects, *, z: int = 0) -> list[dict[str, object]]:
    """Region rectangles that contain house z ``z``, lowest rank first.

    Later entries win where rectangles overlap, as in ``Region.Find``.
    ``rects`` is a region rectangle list as produced from ``Regions.xml`` or
    a server profile (``titan.uo.server_profile``).
    """
    return [
        {
            "name": name, "type": rtype, "allow": allow, "no_housing": no_housing,
            "priority": key[0], "x": x, "y": y, "w": w, "h": h,
        }
        for key, allow, no_housing, x, y, w, h, z1, z2, name, rtype in rects
        if z1 <= z < z2
    ]


def load_region_layers(
    path: str | Path,
    facet_name: str,
    width: int,
    height: int,
    *,
    forbidding_types: frozenset[str] | None = None,
) -> tuple[list[RegionLayer], dict[str, int]]:
    """Rasterize RunUO/ServUO ``Regions.xml`` for one facet, per z band.

    Follows the emulators' ``Region.Find``. At each cell the region with the
    highest priority wins, then the deepest child. A region without its own
    ``priority`` inherits its parent's (default 50); equal ranks keep file
    order, the first listed winning. A rectangle only contains points within
    its z range: ``zmin``/``zmax`` on the rect, else the region's
    ``<zrange min max>``, else -128..127. The house check tests at the
    house's z, so a layer is built for each band between z breakpoints.

    The winning region decides AllowHousing through its parent chain: the
    nearest region whose type overrides it decides, and NoHousingRegion
    follows its ``smartNoHousing`` flag. Regions created at runtime
    (champion spawns, treasure areas, houses) are not in the file and are
    not modelled.
    """
    rects, counts = _parse_region_rects(path, facet_name, forbidding_types)
    return region_layers_from_rects(rects, width, height), counts


def region_layers_from_rects(rects, width: int, height: int) -> list[RegionLayer]:
    """Paint region rectangles (lowest rank first) into per-z-band layers.

    ``rects`` items are ``(rank key, allow, in no-housing chain, x, y, w, h,
    z1, z2, name, type)``, sorted by rank key.
    """
    breaks = sorted(
        {_REGION_MIN_Z, _REGION_MAX_Z}
        | {z for r in rects for z in (r[7], r[8]) if _REGION_MIN_Z < z < _REGION_MAX_Z}
    )
    layers: list[RegionLayer] = []
    for z_min, z_max in zip(breaks, breaks[1:]):
        blocked = np.zeros((height, width), dtype=bool)
        centre = np.zeros((height, width), dtype=bool)
        for _key, allow, no_housing, x, y, w, h, z1, z2, _name, _type in rects:
            if not z1 <= z_min < z2:
                continue
            xs = slice(max(x, 0), max(min(x + w, width), 0))
            ys = slice(max(y, 0), max(min(y + h, height), 0))
            blocked[ys, xs] = not allow
            centre[ys, xs] = no_housing
        if (
            layers
            and np.array_equal(layers[-1].blocked, blocked)
            and np.array_equal(layers[-1].centre, centre)
        ):
            layers[-1].z_max = z_max
        else:
            layers.append(RegionLayer(z_min, z_max, blocked, centre))
    return layers


def load_region_mask(
    path: str | Path,
    facet_name: str,
    width: int,
    height: int,
    *,
    forbidding_types: frozenset[str] | None = None,
    z: int = 0,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """The region layer holding house z ``z``: ``(no_housing, centre, counts)``."""
    layers, counts = load_region_layers(
        path, facet_name, width, height, forbidding_types=forbidding_types
    )
    layer = next(item for item in layers if item.z_min <= z < item.z_max)
    return layer.blocked, layer.centre, counts


def _land_tables(tiledata: UOTileData) -> tuple[np.ndarray, np.ndarray]:
    impassable = np.zeros(0x4000, dtype=bool)
    for tile in tiledata.land[:0x4000]:
        impassable[tile.tile_id] = bool(tile.flags & _IMPASSABLE)
    road = np.zeros(0x4000, dtype=bool)
    for lo, hi in ROAD_LAND_RANGES:
        road[lo : hi + 1] = True
    return impassable, road


def _static_tables(tiledata: UOTileData):
    n = 0x10000
    flags = np.zeros(n, dtype=np.int64)
    height = np.zeros(n, dtype=np.int16)
    for tile in tiledata.statics[:n]:
        flags[tile.tile_id] = tile.flags
        height[tile.tile_id] = tile.height
    calc_height = np.where(flags & _BRIDGE, height // 2, height).astype(np.int16)
    blocking = ((flags & _IMPASSABLE) != 0) | (((flags & _SURFACE) != 0) & ((flags & _BACKGROUND) == 0))
    impassable = (flags & _IMPASSABLE) != 0
    surface_fg = ((flags & _SURFACE) != 0) & ((flags & _BACKGROUND) == 0)
    return calc_height, blocking, impassable, surface_fg


@dataclass
class PlacementGrids:
    """Per-cell placement data over a window, shared by every house type.

    Built once by :func:`build_placement_grids`; :func:`evaluate_placement`
    then checks any house against it, over the whole window or at chosen
    centres. Arrays are padded by ``pad`` cells (outside the facet counts as
    blocked), so footprints reaching up to ``pad - 2`` cells from their
    centre can be checked.
    """

    window: tuple[int, int, int, int]
    origin: tuple[int, int]  # (gx0, gy0): facet cell of grid row/col 0 before padding
    pad: int
    cells: dict[str, np.ndarray]
    static_starts: list[np.ndarray]
    static_ends: list[np.ndarray]
    region_layers: list[RegionLayer]
    region_padded: list[np.ndarray]
    t2a: bool

    @property
    def shape(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.window
        return (y1 - y0, x1 - x0)


def build_placement_grids(
    facet: UOMap,
    tiledata: UOTileData,
    *,
    region_blocked: np.ndarray | None = None,
    region_centre: np.ndarray | None = None,
    region_layers: list[RegionLayer] | None = None,
    t2a: bool = False,
    window: tuple[int, int, int, int] | None = None,
    reach: int = 22,
) -> PlacementGrids:
    """Prepare land, static and region grids for ``window`` = (x0, y0, x1, y1).

    ``reach`` is the largest footprint or border offset from a house centre
    that will be checked (a castle's border reaches 17).
    """
    if region_layers is None and (region_blocked is not None or region_centre is not None):
        shape = (facet.height, facet.width)
        region_layers = [
            RegionLayer(
                _REGION_MIN_Z,
                _REGION_MAX_Z,
                region_blocked if region_blocked is not None else np.zeros(shape, dtype=bool),
                region_centre if region_centre is not None else np.zeros(shape, dtype=bool),
            )
        ]
    x0, y0, x1, y1 = window or (0, 0, facet.width, facet.height)
    margin = reach + 2
    gx0, gy0 = max(0, x0 - margin), max(0, y0 - margin)
    gx1, gy1 = min(facet.width, x1 + margin), min(facet.height, y1 + margin)
    pad = margin + 2

    land_ids, land_z = _land_grid(facet, gx0, gy0, gx1 + 1, gy1 + 1)
    land_imp_tab, road_tab = _land_tables(tiledata)
    calc_h, blocking_tab, imp_tab, surf_tab = _static_tables(tiledata)

    z = land_z.astype(np.int16)
    z_top, z_left = z[:-1, :-1], z[1:, :-1]
    z_right, z_bottom = z[:-1, 1:], z[1:, 1:]
    land_start = np.minimum(np.minimum(z_top, z_left), np.minimum(z_right, z_bottom))
    use_lr = np.abs(z_top - z_bottom) > np.abs(z_left - z_right)
    land_avg = np.where(
        use_lr, np.floor_divide(z_left + z_right, 2), np.floor_divide(z_top + z_bottom, 2)
    ).astype(np.int16)
    ids = land_ids[:-1, :-1]

    gh, gw = land_avg.shape
    blk_s, blk_e, overflow, border_imp, border_surf_top = _static_grids(
        facet, gx0, gy0, gh, gw, calc_h, blocking_tab, imp_tab, surf_tab
    )

    def padded(arr, fill):
        return np.pad(arr, pad, constant_values=fill)

    cells = {
        "avg": padded(land_avg, _INF),
        "start": padded(land_start, _INF),
        "imp": padded(land_imp_tab[ids & 0x3FFF], True),
        "road": padded(road_tab[ids & 0x3FFF], True),
        "overflow": padded(overflow, True),
        "bimp": padded(border_imp, True),
        "bsurf": padded(border_surf_top, _INF),
    }
    layers = region_layers or []
    return PlacementGrids(
        window=(x0, y0, x1, y1),
        origin=(gx0, gy0),
        pad=pad,
        cells=cells,
        static_starts=[padded(s, _INF) for s in blk_s],
        static_ends=[padded(e, -_INF) for e in blk_e],
        region_layers=layers,
        region_padded=[padded(l.blocked[gy0 : gy0 + gh, gx0 : gx0 + gw], True) for l in layers],
        t2a=t2a,
    )


def _house_tiles(multi: UOMulti, tiledata: UOTileData, footprint: HouseFootprint):
    """Per occupied cell, ``(z, top, is_foundation)`` for each house tile."""
    tiles: dict[tuple[int, int], list[tuple[int, int, bool]]] = {}
    for comp in multi.components:
        if comp.item_id == 0x1:
            continue
        info = tiledata.statics[comp.item_id] if comp.item_id < len(tiledata.statics) else None
        flags = info.flags if info else 0
        top = comp.z + (info.height if info else 0) + (16 if flags & _SURFACE else 0)
        tiles.setdefault((comp.x, comp.y), []).append(
            (comp.z, top, comp.z == 0 and bool(flags & _WALL))
        )
    if footprint.stairs_added:
        stair_info = tiledata.statics[0x63]
        stair_top = stair_info.height + (16 if stair_info.flags & _SURFACE else 0)
        for cell in footprint.occupied:
            if cell not in tiles:
                tiles[cell] = [(0, stair_top, bool(stair_info.flags & _WALL))]
    return tiles


def evaluate_placement(
    grids: PlacementGrids,
    multi: UOMulti,
    tiledata: UOTileData,
    *,
    centres: tuple[np.ndarray, np.ndarray] | None = None,
) -> PlacementResult:
    """Check ``multi`` over the whole window, or only at ``centres``.

    ``centres`` are ``(rows, cols)`` index arrays into the window. Then the
    result's ``legal``, ``house_z`` and ``reason_grid`` are 1-D, one entry
    per centre, and ``x0``/``y0`` are the window origin.
    """
    footprint = house_footprint(multi, tiledata)
    if not footprint.foundation:
        raise ValueError(f"multi 0x{multi.multi_id:X} has no foundation tiles")
    ex0, ex1, ey0, ey1 = HouseFootprint.extent(footprint.occupied | footprint.border)
    if max(abs(ex0), abs(ex1), abs(ey0), abs(ey1)) > grids.pad - 2:
        raise ValueError(f"multi 0x{multi.multi_id:X} reaches beyond the prepared grids")

    x0, y0, x1, y1 = grids.window
    gx0, gy0 = grids.origin
    oy, ox = y0 - gy0 + grids.pad, x0 - gx0 + grids.pad
    if centres is None:
        rows, cols = y1 - y0, x1 - x0
        shape = (rows, cols)

        def at(arr, dx, dy):
            return arr[oy + dy : oy + dy + rows, ox + dx : ox + dx + cols]

        def centre_cells(arr):
            return arr[y0:y1, x0:x1]

        xx = np.arange(x0, x1)[None, :]
        yy = np.arange(y0, y1)[:, None]
    else:
        crow, ccol = (np.asarray(a, dtype=np.int64) for a in centres)
        shape = crow.shape

        def at(arr, dx, dy):
            return arr[oy + dy + crow, ox + dx + ccol]

        def centre_cells(arr):
            return arr[y0 + crow, x0 + ccol]

        xx, yy = x0 + ccol, y0 + crow

    C = grids.cells
    tiles = _house_tiles(multi, tiledata, footprint)
    f0 = min(footprint.foundation)
    house_z = at(C["avg"], *f0)

    reasons: dict[str, np.ndarray] = {}

    def fail(name: str, mask: np.ndarray) -> None:
        reasons[name] = reasons.get(name, np.zeros(shape, dtype=bool)) | mask

    centre_bad = np.zeros(shape, dtype=bool)
    if grids.region_layers:
        # Each centre uses the layer for its house z (clamped to the region range).
        z_clamped = np.clip(house_z, _REGION_MIN_Z, _REGION_MAX_Z - 1)
        region_bad = np.zeros(shape, dtype=bool)
        for layer, reg in zip(grids.region_layers, grids.region_padded):
            in_band = (z_clamped >= layer.z_min) & (z_clamped < layer.z_max)
            if not in_band.any():
                continue
            band_bad = np.zeros(shape, dtype=bool)
            for (dx, dy) in footprint.occupied:
                band_bad |= at(reg, dx, dy)
            region_bad |= in_band & band_bad
            centre_bad |= in_band & centre_cells(layer.centre)
        fail("region", region_bad)

    for (dx, dy) in footprint.occupied:
        fail("road", at(C["road"], dx, dy))
        fail("dense_statics", at(C["overflow"], dx, dy))
        avg, start = at(C["avg"], dx, dy), at(C["start"], dx, dy)
        for tz, top, is_foundation in tiles.get((dx, dy), ()):
            a, b = house_z + tz, house_z + top
            fail("land_above", (b > start) & (avg > a))
            if is_foundation:
                fail("impassable_ground", at(C["imp"], dx, dy))
                fail("not_level", avg != house_z)
            hit = np.zeros(shape, dtype=bool)
            for s_arr, e_arr in zip(grids.static_starts, grids.static_ends):
                hit |= (at(s_arr, dx, dy) < b) & (at(e_arr, dx, dy) > a)
            fail("static", hit)

    for (dx, dy) in footprint.border:
        fail("border_land", at(C["imp"], dx, dy) | at(C["road"], dx, dy))
        fail("border_static", at(C["bimp"], dx, dy) | (at(C["bsurf"], dx, dy) > house_z + 2))

    if grids.t2a:
        tx0, ty0, tx1, ty1 = FELUCCA_T2A
        centre_bad |= (xx >= tx0) & (xx < tx1) & (yy >= ty0) & (yy < ty1)
    fail("centre_region", centre_bad)

    legal = np.ones(shape, dtype=bool)
    for mask in reasons.values():
        legal &= ~mask
    # Record each failing centre once, under the first reason that rejects it.
    remaining = np.ones(shape, dtype=bool)
    counts: dict[str, int] = {}
    reason_grid = np.zeros(shape, dtype=np.uint8)
    for code, name in enumerate(REASONS, 1):
        if name in reasons:
            hit = reasons[name] & remaining
            counts[name] = int(hit.sum())
            reason_grid[hit] = code
            remaining &= ~hit
    return PlacementResult(
        multi.multi_id,
        footprint,
        x0,
        y0,
        legal,
        counts,
        house_z=np.array(house_z),
        reason_grid=reason_grid,
    )


def legal_centres(
    grids: PlacementGrids,
    multi: UOMulti,
    tiledata: UOTileData,
    centres: tuple[np.ndarray, np.ndarray] | None = None,
    *,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Legal window centres of ``multi``, without failure reasons.

    Applies the same rules as :func:`evaluate_placement` but drops a centre
    as soon as one cell fails, visiting cells in a scattered order so most
    candidates fall within a few cells. ``centres`` defaults to
    :func:`level_foundation_centres`. Results are identical to the full
    check's ``legal``.
    """
    footprint = house_footprint(multi, tiledata)
    if centres is None:
        centres = level_foundation_centres(grids, multi, tiledata)
    crow, ccol = (np.asarray(a, dtype=np.int64) for a in centres)
    x0, y0, x1, y1 = grids.window
    gx0, gy0 = grids.origin
    oy, ox = y0 - gy0 + grids.pad, x0 - gx0 + grids.pad
    C = grids.cells
    tiles = _house_tiles(multi, tiledata, footprint)
    f0 = min(footprint.foundation)

    def at(arr, dx, dy):
        return arr[oy + dy + crow, ox + dx + ccol]

    def keep(mask):
        nonlocal crow, ccol, house_z, band
        crow, ccol, house_z = crow[mask], ccol[mask], house_z[mask]
        if band is not None:
            band = band[mask]

    house_z = at(C["avg"], *f0)
    band = None
    # Centre rules first: T2A and the no-housing centre region.
    bad = np.zeros(len(crow), dtype=bool)
    if grids.t2a:
        tx0, ty0, tx1, ty1 = FELUCCA_T2A
        xx, yy = x0 + ccol, y0 + crow
        bad |= (xx >= tx0) & (xx < tx1) & (yy >= ty0) & (yy < ty1)
    if grids.region_layers:
        z_clamped = np.clip(house_z, _REGION_MIN_Z, _REGION_MAX_Z - 1)
        band = np.zeros(len(crow), dtype=np.int16)
        for index, layer in enumerate(grids.region_layers):
            in_band = (z_clamped >= layer.z_min) & (z_clamped < layer.z_max)
            band[in_band] = index
            bad |= in_band & layer.centre[y0 + crow, x0 + ccol]
    keep(~bad)

    rng = np.random.default_rng(seed)
    occupied = sorted(footprint.occupied)
    border = sorted(footprint.border)
    cells = [("occ", c) for c in occupied] + [("border", c) for c in border]
    order = rng.permutation(len(cells))
    for index in order:
        if len(crow) == 0:
            break
        kind, (dx, dy) = cells[index]
        if kind == "border":
            bad = at(C["imp"], dx, dy) | at(C["road"], dx, dy) | at(C["bimp"], dx, dy)
            bad |= at(C["bsurf"], dx, dy) > house_z + 2
            keep(~bad)
            continue
        bad = at(C["road"], dx, dy) | at(C["overflow"], dx, dy)
        if band is not None:
            for layer_index, reg in enumerate(grids.region_padded):
                sel = band == layer_index
                if sel.any():
                    bad[sel] |= reg[oy + dy + crow[sel], ox + dx + ccol[sel]]
        avg, start = at(C["avg"], dx, dy), at(C["start"], dx, dy)
        for tz, top, is_foundation in tiles.get((dx, dy), ()):
            a, b = house_z + tz, house_z + top
            bad |= (b > start) & (avg > a)
            if is_foundation:
                bad |= at(C["imp"], dx, dy) | (avg != house_z)
            for s_arr, e_arr in zip(grids.static_starts, grids.static_ends):
                bad |= (at(s_arr, dx, dy) < b) & (at(e_arr, dx, dy) > a)
        keep(~bad)
    return crow, ccol


def level_foundation_centres(
    grids: PlacementGrids, multi: UOMulti, tiledata: UOTileData
) -> tuple[np.ndarray, np.ndarray]:
    """Window centres whose foundation is level and on passable land.

    This is exactly the ``impassable_ground``/``not_level`` part of the
    check, cheap because it only visits foundation cells. Every legal centre
    is among these, so the full check can then run on them alone.
    """
    footprint = house_footprint(multi, tiledata)
    x0, y0, x1, y1 = grids.window
    gx0, gy0 = grids.origin
    oy, ox = y0 - gy0 + grids.pad, x0 - gx0 + grids.pad
    rows, cols = y1 - y0, x1 - x0

    def at(arr, dx, dy):
        return arr[oy + dy : oy + dy + rows, ox + dx : ox + dx + cols]

    f0 = min(footprint.foundation)
    house_z = at(grids.cells["avg"], *f0)
    ok = np.ones((rows, cols), dtype=bool)
    for (dx, dy) in footprint.foundation:
        ok &= ~at(grids.cells["imp"], dx, dy)
        ok &= at(grids.cells["avg"], dx, dy) == house_z
    return np.nonzero(ok)


def placement_legality(
    facet: UOMap,
    tiledata: UOTileData,
    multi: UOMulti,
    *,
    region_blocked: np.ndarray | None = None,
    region_centre: np.ndarray | None = None,
    region_layers: list[RegionLayer] | None = None,
    t2a: bool = False,
    window: tuple[int, int, int, int] | None = None,
) -> PlacementResult:
    """Return the legal centres of ``multi`` in ``window`` = (x0, y0, x1, y1).

    Regions come either as ``region_layers`` (per z band, chosen by each
    centre's house z) or as one ``region_blocked``/``region_centre`` pair
    applied at every z. To check several houses over the same window, build
    the grids once with :func:`build_placement_grids` and call
    :func:`evaluate_placement` per house.
    """
    footprint = house_footprint(multi, tiledata)
    ex0, ex1, ey0, ey1 = HouseFootprint.extent(footprint.occupied | footprint.border)
    grids = build_placement_grids(
        facet,
        tiledata,
        region_blocked=region_blocked,
        region_centre=region_centre,
        region_layers=region_layers,
        t2a=t2a,
        window=window,
        reach=max(abs(ex0), abs(ex1), abs(ey0), abs(ey1)),
    )
    return evaluate_placement(grids, multi, tiledata)


def _land_grid(facet: UOMap, x0: int, y0: int, x1: int, y1: int):
    """Land IDs and z for cells [x0, x1) x [y0, y1), edge-clamped past the facet."""
    blocks = np.frombuffer(facet.land, dtype=np.uint8).reshape(facet.block_count, 196)
    xs = np.clip(np.arange(x0, x1), 0, facet.width - 1)
    ys = np.clip(np.arange(y0, y1), 0, facet.height - 1)
    block = (xs[None, :] // 8) * facet.blocks_high + (ys[:, None] // 8)
    cell = (ys[:, None] % 8) * 8 + (xs[None, :] % 8)
    base = 4 + cell * 3
    raw = blocks[block, base], blocks[block, base + 1], blocks[block, base + 2]
    ids = raw[0].astype(np.uint16) | (raw[1].astype(np.uint16) << 8)
    z = raw[2].view(np.int8)
    return ids, z


def _static_grids(facet, gx0, gy0, gh, gw, calc_h, blocking_tab, imp_tab, surf_tab):
    """Per-cell static summaries over a window.

    Returns blocking intervals (``_MAX_STACK`` start/end grids), an overflow
    mask for denser cells, border impassable presence, and the highest
    non-background surface top.
    """
    records = facet.static_records()
    keep = (
        (records["x"] >= gx0) & (records["x"] < gx0 + gw)
        & (records["y"] >= gy0) & (records["y"] < gy0 + gh)
    )
    rec = records[keep]
    ids = rec["tile_id"].astype(np.int64)
    cx = rec["x"] - gx0
    cy = rec["y"] - gy0
    z = rec["z"].astype(np.int16)
    top = z + calc_h[ids]

    border_imp = np.zeros((gh, gw), dtype=bool)
    border_imp[cy[imp_tab[ids]], cx[imp_tab[ids]]] = True
    surf_top = np.full((gh, gw), -_INF, dtype=np.int16)
    s_mask = surf_tab[ids]
    np.maximum.at(surf_top, (cy[s_mask], cx[s_mask]), top[s_mask])

    b = blocking_tab[ids]
    bx, by, bz, btop = cx[b], cy[b], z[b], top[b]
    cell = by.astype(np.int64) * gw + bx
    order = np.argsort(cell, kind="stable")
    cell, bz, btop = cell[order], bz[order], btop[order]
    first = np.r_[True, cell[1:] != cell[:-1]]
    run_start = np.maximum.accumulate(np.where(first, np.arange(len(cell)), 0))
    rank = np.arange(len(cell)) - run_start

    starts = [np.full((gh, gw), _INF, dtype=np.int16) for _ in range(_MAX_STACK)]
    ends = [np.full((gh, gw), -_INF, dtype=np.int16) for _ in range(_MAX_STACK)]
    for k in range(_MAX_STACK):
        sel = rank == k
        flat_s, flat_e = starts[k].reshape(-1), ends[k].reshape(-1)
        flat_s[cell[sel]] = bz[sel]
        flat_e[cell[sel]] = btop[sel]
    overflow = np.zeros(gh * gw, dtype=bool)
    overflow[cell[rank >= _MAX_STACK]] = True
    return starts, ends, overflow.reshape(gh, gw), border_imp, surf_top


def pack_houses(result: PlacementResult, *, order: str = "row") -> list[tuple[int, int]]:
    """Greedily place houses at legal centres, scanning ``row`` or ``column`` first.

    A centre is rejected once its tiles or yard would touch tiles of a house
    already placed (RunUO rule 3; houses also may not overlap).
    """
    fp = result.footprint
    occupied = np.array(sorted(fp.occupied), dtype=np.int64)
    reach = np.array(sorted(fp.yard | fp.occupied), dtype=np.int64)
    # Centres c' that conflict with a house at c: c' + reach hits c + occupied,
    # i.e. c' - c in occupied - reach.
    diffs = (occupied[:, None, :] - reach[None, :, :]).reshape(-1, 2)
    diffs = np.unique(diffs, axis=0)
    dx0, dy0 = diffs.min(axis=0)
    dx1, dy1 = diffs.max(axis=0)
    stamp = np.zeros((dy1 - dy0 + 1, dx1 - dx0 + 1), dtype=bool)
    stamp[diffs[:, 1] - dy0, diffs[:, 0] - dx0] = True

    h, w = result.legal.shape
    blocked = np.zeros((h - dy0 + dy1 + 1, w - dx0 + dx1 + 1), dtype=bool)
    # blocked[r - dy0, c - dx0] corresponds to centre (r, c)
    legal = result.legal if order == "row" else result.legal.T
    rows, cols = np.nonzero(legal)
    if order != "row":
        rows, cols = cols, rows
    placed: list[tuple[int, int]] = []
    sh, sw = stamp.shape
    for r, c in zip(rows.tolist(), cols.tolist()):
        if blocked[r - dy0, c - dx0]:
            continue
        placed.append((result.x0 + c, result.y0 + r))
        region = blocked[r : r + sh, c : c + sw]
        region |= stamp
    return placed


def coverage(result: PlacementResult) -> np.ndarray:
    """Cells of the window covered by at least one legal placement's tiles."""
    h, w = result.legal.shape
    cells = np.array(sorted(result.footprint.occupied))
    mx0, my0 = np.minimum(cells.min(axis=0), 0)
    mx1, my1 = np.maximum(cells.max(axis=0), 0)
    # out[R, C] is window cell (R + my0, C + mx0).
    out = np.zeros((h + my1 - my0, w + mx1 - mx0), dtype=bool)
    for dx, dy in cells:
        out[dy - my0 : dy - my0 + h, dx - mx0 : dx - mx0 + w] |= result.legal
    return out[-my0 : -my0 + h, -mx0 : -mx0 + w]
