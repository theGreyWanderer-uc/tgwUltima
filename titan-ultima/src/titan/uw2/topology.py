"""Shared tile-adjacency, diagonal-boundary, and tile-object helpers.

These were previously duplicated (with drifting behavior) across
render_uuw2_as_u7_style.py, render_level_flat_grid.py, and geometry.py.
Renderers should import from here instead of re-implementing this logic so a
fix made once applies everywhere.
"""

from __future__ import annotations

from PIL import Image, ImageDraw


SIDES = ("left", "right", "back", "front")

_DIAGONAL_SKIPPED_SIDES = {
    "diagonal_se": ("left", "front"),
    "diagonal_sw": ("right", "front"),
    "diagonal_nw": ("right", "back"),
    "diagonal_ne": ("left", "back"),
}


def neighbor_coords(side: str, x: int, y: int) -> tuple[int, int]:
    if side == "left":
        return x - 1, y
    if side == "right":
        return x + 1, y
    if side == "back":
        return x, y - 1
    return x, y + 1


def opposite_side(side: str) -> str:
    return {
        "left": "right",
        "right": "left",
        "back": "front",
        "front": "back",
    }[side]


def skip_external_side_for_diagonal(type_name: str, side: str) -> bool:
    return side in _DIAGONAL_SKIPPED_SIDES.get(type_name, ())


def neighbor_is_open_across_side(neighbor: dict | None, neighbor_side: str) -> bool:
    if neighbor is None or neighbor["type_name"] == "solid":
        return False
    return not skip_external_side_for_diagonal(neighbor["type_name"], neighbor_side)


def is_blocked_diagonal_neighbor(neighbor: dict | None, neighbor_side: str) -> bool:
    return (
        neighbor is not None
        and str(neighbor["type_name"]).startswith("diagonal_")
        and skip_external_side_for_diagonal(neighbor["type_name"], neighbor_side)
    )


def diagonal_floor_polygon(
    type_name: str, width: int, height: int, orientation: str = "display"
):
    if orientation == "raw":
        return {
            "diagonal_se": [(0, 0), (width, 0), (width, height)],
            "diagonal_sw": [(0, 0), (width, 0), (0, height)],
            "diagonal_nw": [(0, 0), (width, height), (0, height)],
            "diagonal_ne": [(0, height), (width, 0), (width, height)],
        }.get(type_name)

    return {
        "diagonal_se": [(0, height), (width, height), (width, 0)],
        "diagonal_sw": [(0, height), (width, height), (0, 0)],
        "diagonal_nw": [(0, 0), (width, 0), (0, height)],
        "diagonal_ne": [(0, 0), (width, 0), (width, height)],
    }.get(type_name)


def clip_diagonal_floor_image(
    texture: Image.Image, type_name: str, orientation: str = "display"
) -> Image.Image:
    if not type_name.startswith("diagonal_"):
        return texture

    width, height = texture.size
    polygon = diagonal_floor_polygon(type_name, width, height, orientation)
    if polygon is None:
        return texture

    mask = Image.new("L", texture.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(polygon, fill=255)
    clipped = texture.copy()
    clipped.putalpha(mask)
    return clipped


def tile_coordinate_label(raw_x: int, raw_y: int, display_y: int, mode: str) -> str:
    if mode == "raw":
        return f"{raw_x},{raw_y}"
    if mode == "both":
        return f"{raw_x},{display_y}\nraw {raw_y}"
    return f"{raw_x},{display_y}"


def iter_tile_objects(tile: dict, object_map: dict[int, dict]):
    current = int(tile.get("object_chain_start", 0))
    seen: set[int] = set()
    while current and current not in seen:
        seen.add(current)
        obj = object_map.get(current)
        if obj is None:
            return
        yield obj
        current = int(obj.get("next", 0))


def find_door_object(tile: dict, object_map: dict[int, dict]) -> dict | None:
    for obj in iter_tile_objects(tile, object_map):
        item_id = int(obj.get("item_id", 0))
        if 0x0140 <= item_id < 0x0150:
            return obj
    return None


def infer_flag_door_heading(tile: dict, tile_map: dict[tuple[int, int], dict]) -> int:
    x = int(tile["x"])
    y = int(tile["y"])
    left_open = neighbor_is_open_across_side(
        tile_map.get(neighbor_coords("left", x, y)), "right"
    )
    right_open = neighbor_is_open_across_side(
        tile_map.get(neighbor_coords("right", x, y)), "left"
    )
    back_open = neighbor_is_open_across_side(
        tile_map.get(neighbor_coords("back", x, y)), "front"
    )
    front_open = neighbor_is_open_across_side(
        tile_map.get(neighbor_coords("front", x, y)), "back"
    )

    if left_open and right_open and not (back_open or front_open):
        return 2
    if back_open and front_open and not (left_open or right_open):
        return 0
    return 0


def diagonal_hypotenuse_endpoints(type_name: str, x: int, y: int):
    """Return ((point_a, side_a), (point_b, side_b)) for a diagonal tile's
    hypotenuse, pairing each endpoint with the skipped side whose edge it
    terminates. Returns None for non-diagonal types."""
    endpoints = {
        "diagonal_se": (((x, y), "left"), ((x + 1, y + 1), "front")),
        "diagonal_sw": (((x, y + 1), "front"), ((x + 1, y), "right")),
        "diagonal_nw": (((x + 1, y + 1), "right"), ((x, y), "back")),
        "diagonal_ne": (((x + 1, y), "back"), ((x, y + 1), "left")),
    }.get(type_name)
    return endpoints
