"""Geometry generation for UU2 level tiles."""

from __future__ import annotations

from dataclasses import dataclass

from .topology import neighbor_coords as _neighbor_coords
from .topology import opposite_side as _opposite_side
from .topology import (
    skip_external_side_for_diagonal as _skip_external_side_for_diagonal,
)


SIDES = ("left", "right", "front", "back")


@dataclass(frozen=True)
class TexturedTriangle:
    texture_id: int
    vertices: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    uvs: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


def generate_level_triangles(
    tiles: list[dict],
    *,
    z_scale: float = 1.0 / 32.0,
    ceiling_source: str = "runtime",
    include_ceilings: bool = True,
) -> list[TexturedTriangle]:
    tile_map = {(tile["x"], tile["y"]): tile for tile in tiles}
    triangles: list[TexturedTriangle] = []
    for tile in tiles:
        triangles.extend(
            generate_tile_triangles(
                tile,
                tile_map,
                z_scale=z_scale,
                ceiling_source=ceiling_source,
                include_ceilings=include_ceilings,
            )
        )
    return triangles


def generate_tile_triangles(
    tile: dict,
    tile_map: dict[tuple[int, int], dict],
    *,
    z_scale: float,
    ceiling_source: str,
    include_ceilings: bool,
) -> list[TexturedTriangle]:
    if tile["type_name"] == "solid":
        return []

    x = float(tile["x"])
    y = float(tile["y"])
    floor = float(tile["floor_height"])
    ceiling = float(tile["ceiling_height"])
    slope = float(tile["slope_height"])
    out: list[TexturedTriangle] = []

    wall_texture = int(tile["texture_wall"])
    floor_texture = int(tile["texture_floor"])
    ceiling_texture = int(
        tile["texture_ceiling_ua"]
        if ceiling_source == "ua"
        else tile["texture_ceiling_runtime"]
    )

    diag = _diagonal_wall(
        tile["type_name"], x, y, floor, ceiling, wall_texture, z_scale
    )
    if diag:
        out.extend(diag)

    for side in SIDES:
        if _skip_external_side_for_diagonal(tile["type_name"], side):
            continue

        x1, y1, z1, x2, y2, z2 = _tile_edge_coords(side, tile, int(x), int(y))
        nx, ny = _neighbor_coords(side, int(x), int(y))

        if 0 <= nx < 64 and 0 <= ny < 64:
            neighbor = tile_map[(nx, ny)]
            if neighbor["type_name"] == "solid":
                nz1 = nz2 = float(neighbor["ceiling_height"])
            else:
                adjacent_side = _opposite_side(side)
                _, _, nz1, _, _, nz2 = _tile_edge_coords(
                    adjacent_side, neighbor, nx, ny
                )
                if nz1 == nz2 and nz2 == neighbor["ceiling_height"]:
                    nz1 = nz2 = ceiling
                if nz1 < z1 or nz2 < z2:
                    continue
        else:
            nz1 = nz2 = ceiling

        if z1 == nz1 and z2 == nz2:
            continue

        out.extend(
            _wall_triangles(
                side, x1, y1, z1, x2, y2, z2, nz1, nz2, ceiling, wall_texture, z_scale
            )
        )

    out.extend(
        _floor_and_ceiling_triangles(
            tile["type_name"],
            x,
            y,
            floor,
            ceiling,
            slope,
            floor_texture,
            ceiling_texture,
            z_scale,
            include_ceilings,
        )
    )
    return out


def _tri(
    texture_id: int,
    verts: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    z_scale: float,
) -> TexturedTriangle:
    return TexturedTriangle(
        texture_id=texture_id,
        vertices=tuple((vx, vy, vz * z_scale) for vx, vy, vz in verts),  # type: ignore[arg-type]
        uvs=tuple(uvs),  # type: ignore[arg-type]
    )


def _diagonal_wall(
    type_name: str,
    x: float,
    y: float,
    floor: float,
    ceiling: float,
    texture: int,
    z_scale: float,
) -> list[TexturedTriangle]:
    endpoints = {
        "diagonal_se": ((x, y, floor), (x + 1, y + 1, floor)),
        "diagonal_sw": ((x, y + 1, floor), (x + 1, y, floor)),
        "diagonal_nw": ((x + 1, y + 1, floor), (x, y, floor)),
        "diagonal_ne": ((x + 1, y, floor), (x, y + 1, floor)),
    }.get(type_name)
    if not endpoints:
        return []
    p1, p2 = endpoints
    return _wall_triangles(
        "left",
        p1[0],
        p1[1],
        p1[2],
        p2[0],
        p2[1],
        p2[2],
        ceiling,
        ceiling,
        ceiling,
        texture,
        z_scale,
    )


def _wall_triangles(
    side: str,
    x1: float,
    y1: float,
    z1: float,
    x2: float,
    y2: float,
    z2: float,
    nz1: float,
    nz2: float,
    ceiling: float,
    texture: int,
    z_scale: float,
) -> list[TexturedTriangle]:
    v1 = (ceiling - z1) / 32.0
    v2 = (ceiling - z2) / 32.0
    v3 = (ceiling - nz2) / 32.0
    v4 = (ceiling - nz1) / 32.0

    if side in ("left", "front"):
        return [
            _tri(
                texture,
                [(x1, y1, z1), (x2, y2, z2), (x2, y2, nz2)],
                [(0.0, v1), (1.0, v2), (1.0, v3)],
                z_scale,
            ),
            _tri(
                texture,
                [(x1, y1, z1), (x2, y2, nz2), (x1, y1, nz1)],
                [(0.0, v1), (1.0, v3), (0.0, v4)],
                z_scale,
            ),
        ]

    return [
        _tri(
            texture,
            [(x1, y1, z1), (x1, y1, nz1), (x2, y2, nz2)],
            [(1.0, v1), (1.0, v4), (0.0, v3)],
            z_scale,
        ),
        _tri(
            texture,
            [(x1, y1, z1), (x2, y2, nz2), (x2, y2, z2)],
            [(1.0, v1), (0.0, v3), (0.0, v2)],
            z_scale,
        ),
    ]


def _floor_and_ceiling_triangles(
    type_name: str,
    x: float,
    y: float,
    floor: float,
    ceiling: float,
    slope: float,
    floor_texture: int,
    ceiling_texture: int,
    z_scale: float,
    include_ceilings: bool,
) -> list[TexturedTriangle]:
    out: list[TexturedTriangle] = []
    floor_slope = floor + slope
    tri2_used = True

    ceil_tri1 = _tri(
        ceiling_texture,
        [(x, y, ceiling), (x + 1, y + 1, ceiling), (x + 1, y, ceiling)],
        [(0, 0), (1, 1), (1, 0)],
        z_scale,
    )
    ceil_tri2 = _tri(
        ceiling_texture,
        [(x, y, ceiling), (x, y + 1, ceiling), (x + 1, y + 1, ceiling)],
        [(0, 0), (0, 1), (1, 1)],
        z_scale,
    )
    floor_tri2 = None

    if type_name == "open":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y, floor), (x + 1, y + 1, floor)],
            [(0, 0), (1, 0), (1, 1)],
            z_scale,
        )
        floor_tri2 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y + 1, floor), (x, y + 1, floor)],
            [(0, 0), (1, 1), (0, 1)],
            z_scale,
        )
    elif type_name == "diagonal_se":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y, floor), (x + 1, y + 1, floor)],
            [(0, 0), (1, 0), (1, 1)],
            z_scale,
        )
        tri2_used = False
    elif type_name == "diagonal_sw":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y, floor), (x, y + 1, floor)],
            [(0, 0), (1, 0), (0, 1)],
            z_scale,
        )
        ceil_tri1 = _tri(
            ceiling_texture,
            [(x, y, ceiling), (x, y + 1, ceiling), (x + 1, y, ceiling)],
            [(0, 0), (0, 1), (1, 0)],
            z_scale,
        )
        tri2_used = False
    elif type_name == "diagonal_nw":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y + 1, floor), (x, y + 1, floor)],
            [(0, 0), (1, 1), (0, 1)],
            z_scale,
        )
        ceil_tri1 = ceil_tri2
        tri2_used = False
    elif type_name == "diagonal_ne":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y + 1, floor), (x + 1, y, floor), (x + 1, y + 1, floor)],
            [(0, 1), (1, 0), (1, 1)],
            z_scale,
        )
        ceil_tri1 = _tri(
            ceiling_texture,
            [(x, y + 1, ceiling), (x + 1, y + 1, ceiling), (x + 1, y, ceiling)],
            [(0, 1), (1, 1), (1, 0)],
            z_scale,
        )
        tri2_used = False
    elif type_name == "slope_n":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y, floor), (x + 1, y + 1, floor_slope)],
            [(0, 0), (1, 0), (1, 1)],
            z_scale,
        )
        floor_tri2 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y + 1, floor_slope), (x, y + 1, floor_slope)],
            [(0, 0), (1, 1), (0, 1)],
            z_scale,
        )
    elif type_name == "slope_s":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor_slope), (x + 1, y, floor_slope), (x + 1, y + 1, floor)],
            [(0, 0), (1, 0), (1, 1)],
            z_scale,
        )
        floor_tri2 = _tri(
            floor_texture,
            [(x, y, floor_slope), (x + 1, y + 1, floor), (x, y + 1, floor)],
            [(0, 0), (1, 1), (0, 1)],
            z_scale,
        )
    elif type_name == "slope_e":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y, floor_slope), (x + 1, y + 1, floor_slope)],
            [(0, 0), (1, 0), (1, 1)],
            z_scale,
        )
        floor_tri2 = _tri(
            floor_texture,
            [(x, y, floor), (x + 1, y + 1, floor_slope), (x, y + 1, floor)],
            [(0, 0), (1, 1), (0, 1)],
            z_scale,
        )
    elif type_name == "slope_w":
        floor_tri1 = _tri(
            floor_texture,
            [(x, y, floor_slope), (x + 1, y, floor), (x + 1, y + 1, floor)],
            [(0, 0), (1, 0), (1, 1)],
            z_scale,
        )
        floor_tri2 = _tri(
            floor_texture,
            [(x, y, floor_slope), (x + 1, y + 1, floor), (x, y + 1, floor_slope)],
            [(0, 0), (1, 1), (0, 1)],
            z_scale,
        )
    else:
        return []

    out.append(floor_tri1)
    if tri2_used and floor_tri2 is not None:
        out.append(floor_tri2)
    if include_ceilings:
        out.append(ceil_tri1)
        if tri2_used:
            out.append(ceil_tri2)
    return out


def _tile_edge_coords(
    side: str, tile: dict, basex: int, basey: int
) -> tuple[float, float, float, float, float, float]:
    if side == "left":
        x1, x2, y1, y2 = basex, basex, basey, basey + 1
    elif side == "right":
        x1, x2, y1, y2 = basex + 1, basex + 1, basey, basey + 1
    elif side == "front":
        x1, x2, y1, y2 = basex, basex + 1, basey + 1, basey + 1
    else:
        x1, x2, y1, y2 = basex, basex + 1, basey, basey

    z1 = z2 = float(tile["floor_height"])
    slope = float(tile["slope_height"])
    type_name = tile["type_name"]
    ceiling = float(tile["ceiling_height"])

    if side == "left":
        if type_name in ("slope_w", "slope_s"):
            z1 += slope
        if type_name in ("slope_w", "slope_n"):
            z2 += slope
        if type_name in ("diagonal_se", "diagonal_ne"):
            z1 = z2 = ceiling
    elif side == "right":
        if type_name in ("slope_e", "slope_s"):
            z1 += slope
        if type_name in ("slope_e", "slope_n"):
            z2 += slope
        if type_name in ("diagonal_sw", "diagonal_nw"):
            z1 = z2 = ceiling
    elif side == "front":
        if type_name in ("slope_n", "slope_w"):
            z1 += slope
        if type_name in ("slope_n", "slope_e"):
            z2 += slope
        if type_name in ("diagonal_se", "diagonal_sw"):
            z1 = z2 = ceiling
    elif side == "back":
        if type_name in ("slope_s", "slope_w"):
            z1 += slope
        if type_name in ("slope_s", "slope_e"):
            z2 += slope
        if type_name in ("diagonal_nw", "diagonal_ne"):
            z1 = z2 = ceiling

    return float(x1), float(y1), z1, float(x2), float(y2), z2
