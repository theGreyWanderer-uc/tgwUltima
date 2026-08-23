"""Flat top-down diagnostic grid rendering for UU2 levels.

Unlike the U7-style cutaway in :mod:`titan.uw2.map_render`, this view applies
no oblique projection and no wall height at all: every tile is one axis-aligned
square. That makes it the view to reach for when checking tile adjacency,
diagonal cut corners, door headings, and coordinate conventions, because
nothing is displaced by the projection.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from titan.uw2.instances import sub_tile_fraction
from titan.uw2.map_pipeline import load_levels, load_terrain_images
from titan.uw2.render_common import (
    parse_hex_color,
    render_output_filename,
)
from titan.uw2.topology import (
    SIDES,
    clip_diagonal_floor_image,
    find_door_object,
    infer_flag_door_heading,
    neighbor_coords,
    neighbor_is_open_across_side,
    opposite_side,
    skip_external_side_for_diagonal,
    tile_coordinate_label,
)

MAP_TILES = 64
"""Every UU2 level is a fixed 64x64 tile grid."""

COORDINATE_MODES = ("display", "raw", "both")

SOLID_FILL = (7, 8, 10, 255)
MISSING_TEXTURE_FILL = (44, 44, 44, 255)
DOOR_COLOR = (255, 136, 24, 255)
DOOR_LABEL_COLOR = (255, 230, 120, 255)
WALL_EDGE_COLOR = (245, 245, 245, 220)
DIAGONAL_COLOR = (255, 214, 80, 230)
GRID_COLOR = (255, 240, 120, 90)
GRID_LABEL_COLOR = (255, 240, 120, 255)
TILE_LABEL_COLOR = (255, 255, 215, 245)


def default_options() -> dict[str, object]:
    """Diagnostic-grid defaults, kept separate from the cutaway renderer's."""
    return {
        "tile_size": 64,
        "margin": 56,
        "background": "#08090b",
        "grid_label_step": 1,
        "coordinate_mode": "display",
        "no_solid_labels": False,
        "name_files": False,
    }


def render_grid_level(
    level: dict, textures: dict[int, Image.Image], args
) -> Image.Image:
    """Draw one decoded level as a flat, labelled top-down grid."""
    if args.coordinate_mode not in COORDINATE_MODES:
        raise ValueError(
            f"coordinate mode must be one of {COORDINATE_MODES}: {args.coordinate_mode}"
        )
    tile_size = max(12, int(args.tile_size))
    margin = max(0, int(args.margin))
    size = margin + tile_size * MAP_TILES
    canvas = Image.new("RGBA", (size, size), parse_hex_color(args.background))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    tiles = level["tiles"]
    tile_map = {(int(t["x"]), int(t["y"])): t for t in tiles}
    object_map = {obj["slot"]: obj for obj in level.get("objects", [])}

    for tile in tiles:
        left, top = _tile_origin(tile, margin, tile_size)
        box = (left, top, left + tile_size, top + tile_size)
        if tile["type_name"] == "solid":
            draw.rectangle(box, fill=SOLID_FILL)
            continue

        texture = textures.get(int(tile["texture_floor"]))
        if texture is None:
            draw.rectangle(box, fill=MISSING_TEXTURE_FILL)
        else:
            tile_image = texture.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            tile_image = tile_image.resize(
                (tile_size, tile_size), Image.Resampling.NEAREST
            )
            tile_image = clip_diagonal_floor_image(tile_image, tile["type_name"])
            canvas.alpha_composite(tile_image, (left, top))

        door_obj = find_door_object(tile, object_map)
        if tile.get("door_present") or door_obj is not None:
            draw_door_marker(draw, tile, door_obj, left, top, tile_size, tile_map)

    # Edges and diagonals draw in a second pass so neighbouring floor tiles
    # composited later cannot paint over them.
    for tile in tiles:
        if tile["type_name"] == "solid":
            continue
        left, top = _tile_origin(tile, margin, tile_size)
        draw_wall_edges(draw, tile, tile_map, left, top, tile_size)
        draw_diagonal_marker(draw, tile, left, top, tile_size)

    draw_grid_and_labels(draw, tiles, margin, tile_size, args, font)
    return canvas


def draw_door_marker(
    draw: ImageDraw.ImageDraw,
    tile: dict,
    door_obj: dict | None,
    left: int,
    top: int,
    tile_size: int,
    tile_map: dict[tuple[int, int], dict],
) -> None:
    """Mark a door across the axis its heading implies, at its in-tile offset."""
    pad = max(3, tile_size // 10)
    width = max(3, tile_size // 12)
    if door_obj is not None:
        heading = int(door_obj.get("heading", 0))
        obj_x = sub_tile_fraction(door_obj.get("in_tile_x", 4))
        obj_y = sub_tile_fraction(door_obj.get("in_tile_y", 4))
    else:
        heading = infer_flag_door_heading(tile, tile_map)
        obj_x = 0.5
        obj_y = 0.5

    if heading in (2, 6):
        door_x = left + round(tile_size * obj_x)
        draw.line(
            (door_x, top + pad, door_x, top + tile_size - pad),
            fill=DOOR_COLOR,
            width=width,
        )
    else:
        door_y = top + round(tile_size * obj_y)
        draw.line(
            (left + pad, door_y, left + tile_size - pad, door_y),
            fill=DOOR_COLOR,
            width=width,
        )
    draw.text(
        (left + tile_size - pad, top + pad), "D", anchor="ra", fill=DOOR_LABEL_COLOR
    )


def draw_wall_edges(
    draw: ImageDraw.ImageDraw,
    tile: dict,
    tile_map: dict[tuple[int, int], dict],
    left: int,
    top: int,
    tile_size: int,
) -> None:
    """Outline every side this tile does not share with an open neighbour."""
    width = max(2, tile_size // 16)
    for side in SIDES:
        if skip_external_side_for_diagonal(tile["type_name"], side):
            continue
        neighbor = tile_map.get(neighbor_coords(side, int(tile["x"]), int(tile["y"])))
        if neighbor_is_open_across_side(neighbor, opposite_side(side)):
            continue
        draw.line(
            edge_screen_points(side, left, top, tile_size),
            fill=WALL_EDGE_COLOR,
            width=width,
        )


def draw_diagonal_marker(
    draw: ImageDraw.ImageDraw, tile: dict, left: int, top: int, tile_size: int
) -> None:
    """Draw the hypotenuse of a diagonal tile's floor triangle."""
    width = max(2, tile_size // 14)
    line = {
        "diagonal_se": (left, top + tile_size, left + tile_size, top),
        "diagonal_nw": (left, top + tile_size, left + tile_size, top),
        "diagonal_sw": (left, top, left + tile_size, top + tile_size),
        "diagonal_ne": (left, top, left + tile_size, top + tile_size),
    }.get(tile["type_name"])
    if line:
        draw.line(line, fill=DIAGONAL_COLOR, width=width)


def draw_grid_and_labels(
    draw: ImageDraw.ImageDraw,
    tiles: list[dict],
    margin: int,
    tile_size: int,
    args,
    font: ImageFont.ImageFont,
) -> None:
    """Draw the tile grid, edge rulers, and per-tile coordinate labels."""
    label_step = max(1, int(args.grid_label_step))
    map_size = tile_size * MAP_TILES
    for index in range(MAP_TILES + 1):
        pos = margin + index * tile_size
        draw.line((margin, pos, margin + map_size, pos), fill=GRID_COLOR, width=1)
        draw.line((pos, margin, pos, margin + map_size), fill=GRID_COLOR, width=1)

    for coord in range(0, MAP_TILES, label_step):
        center = margin + coord * tile_size + tile_size // 2
        draw.text(
            (center, margin // 2),
            str(coord),
            anchor="mm",
            fill=GRID_LABEL_COLOR,
            font=font,
        )
        draw.text(
            (margin // 2, center),
            str(coord),
            anchor="mm",
            fill=GRID_LABEL_COLOR,
            font=font,
        )

    for tile in tiles:
        x = int(tile["x"])
        raw_y = int(tile["y"])
        display_y = MAP_TILES - 1 - raw_y
        if x % label_step != 0 or display_y % label_step != 0:
            continue
        if args.no_solid_labels and tile["type_name"] == "solid":
            continue
        left, top = _tile_origin(tile, margin, tile_size)
        label = tile_coordinate_label(x, raw_y, display_y, args.coordinate_mode)
        center = (left + tile_size // 2, top + tile_size // 2)
        bbox = draw.textbbox(center, label, font=font, anchor="mm")
        pad = 2
        draw.rectangle(
            (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
            fill=(0, 0, 0, 155),
            outline=(255, 240, 120, 135),
        )
        draw.text(center, label, anchor="mm", fill=TILE_LABEL_COLOR, font=font)


def edge_screen_points(
    side: str, left: int, top: int, tile_size: int
) -> tuple[int, int, int, int]:
    """Screen endpoints of one tile side, in display orientation."""
    if side == "left":
        return left, top, left, top + tile_size
    if side == "right":
        return left + tile_size, top, left + tile_size, top + tile_size
    if side == "back":
        return left, top + tile_size, left + tile_size, top + tile_size
    return left, top, left + tile_size, top


def render_grids_direct(
    source: str | Path,
    output: str | Path,
    *,
    slots: Iterable[int],
    **options: object,
) -> list[Path]:
    """Read original UU2 files and write flat diagnostic grid PNG files."""
    requested = list(slots)
    levels = load_levels(source, requested)
    found = {int(level["slot_index"]) for level in levels}
    missing = sorted(set(requested) - found)
    if missing:
        raise ValueError(f"unavailable UU2 map slots: {missing}")

    textures = load_terrain_images(source)
    merged = default_options()
    merged.update(options)
    args = SimpleNamespace(**merged)
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for level in levels:
        image = render_grid_level(level, textures, args)
        destination = output_path / render_output_filename(
            int(level["slot_index"]), level, "flat_grid", args.name_files
        )
        image.save(destination)
        written.append(destination)
    return written


def _tile_origin(tile: dict, margin: int, tile_size: int) -> tuple[int, int]:
    display_y = MAP_TILES - 1 - int(tile["y"])
    return margin + int(tile["x"]) * tile_size, margin + display_y * tile_size
