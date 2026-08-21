#!/usr/bin/env python3
"""Render UU2 levels as a U7-style overhead cutaway image."""

from __future__ import annotations

import argparse
from collections import deque
import json
from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from titan.uw2.exe_models import MODEL_ICON_ITEM_IDS, UW2ModelArchive
from titan.uw2.object_data import UW2AnimationTable, UW2CommonObjectTable
from titan.uw2.palette import UW2Palette

from titan.uw2.render_common import (
    load_gr_textures,
    load_terrain_textures,
    parse_hex_color,
    render_output_filename,
)
from titan.uw2.instances import (
    REMOVABLE_WALL_ITEM,
    THIN_WALL_ITEM,
    is_wall_mounted,
    object_material_for,
)
from titan.uw2.topology import (
    SIDES,
    clip_diagonal_floor_image,
    diagonal_hypotenuse_endpoints,
    find_door_object,
    infer_flag_door_heading,
    is_blocked_diagonal_neighbor,
    iter_tile_objects,
    neighbor_coords,
    neighbor_is_open_across_side,
    opposite_side,
    skip_external_side_for_diagonal,
    tile_coordinate_label,
)


SIDE_SHADE = {
    "left": 0.74,
    "right": 0.86,
    "back": 0.68,
    "front": 0.94,
    "diagonal": 0.82,
}


@dataclass
class FloorPrimitive:
    texture_id: int
    type_name: str
    x: int
    y: int
    sort_key: tuple[float, float, int]


@dataclass
class WallPrimitive:
    texture_id: int
    texture_kind: str
    side: str
    quad: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]
    sort_key: tuple[float, float, int]


@dataclass
class SolidFillPrimitive:
    texture_id: int
    x: int
    y: int
    sort_key: tuple[float, float, int]


@dataclass
class SpritePrimitive:
    image: Image.Image
    x: float
    y: float
    item_id: int
    slot: int
    sort_key: tuple[float, float, int]
    background: bool = False


@dataclass
class ModelTrianglePrimitive:
    points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    fill: tuple[int, int, int, int]
    sort_key: tuple[float, float, int]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--levels-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "uuw2_output" / "levels",
    )
    parser.add_argument(
        "--texture-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "uuw2_output" / "textures",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "uuw2_output"
        / "renders_u7_style",
    )
    parser.add_argument("--slots", type=int, nargs="+", default=[0])
    parser.add_argument("--tile-size", type=int, default=64)
    parser.add_argument(
        "--lift-pixels",
        type=float,
        default=4.0,
        help="U7-style screen offset in pixels per generated lift unit.",
    )
    parser.add_argument(
        "--floor-height-per-lift",
        type=float,
        default=8.0,
        help="UU2 floor-height units represented by one U7-style lift unit.",
    )
    parser.add_argument(
        "--wall-height-scale",
        type=float,
        default=1.0,
        help="Scale for vertical wall panel screen height.",
    )
    parser.add_argument(
        "--max-wall-height",
        type=float,
        default=24.0,
        help="Maximum vertical wall panel screen height in pixels. Use 0 for no cap. "
        "This projection has no depth buffer, so tall walls can paint over floors that "
        "are further back on screen; keep this low (well under one --tile-size) for "
        "levels with uneven terrain, e.g. caves. See --no-obstruction-clip.",
    )
    parser.add_argument(
        "--no-obstruction-clip",
        action="store_true",
        help="Disable the per-wall clip that shortens a wall so it doesn't visually reach "
        "over the floor of the tile behind it. On by default; this projection has no real "
        "depth buffer, so tall walls in uneven terrain (e.g. caves) can otherwise paint over "
        "floors that should stay visible.",
    )
    parser.add_argument("--margin", type=int, default=96)
    parser.add_argument("--background", default="#08090b")
    parser.add_argument(
        "--orientation",
        choices=("display", "raw"),
        default="display",
        help="Use extracted display_y orientation by default; raw keeps archive row order.",
    )
    parser.add_argument(
        "--floor-texture-transform",
        choices=("auto", "none", "flip-y", "flip-x", "rotate-180"),
        default="auto",
        help="Transform floor texture images. Auto flips vertically for display orientation.",
    )
    parser.add_argument(
        "--door-texture-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "uuw2_output"
        / "gr_textures"
        / "doors",
        help="Directory containing exported DOORS.GR PNGs.",
    )
    parser.add_argument(
        "--tmflat-texture-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "uuw2_output"
        / "gr_textures"
        / "tmflat",
        help="Directory containing exported TMFLAT.GR PNGs.",
    )
    parser.add_argument(
        "--tmobj-texture-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "uuw2_output"
        / "gr_textures"
        / "tmobj",
        help="Directory containing exported TMOBJ.GR PNGs.",
    )
    parser.add_argument(
        "--no-doors", action="store_true", help="Do not draw door panels"
    )
    parser.add_argument(
        "--no-flat-objects", action="store_true", help="Do not draw flat object decals"
    )
    parser.add_argument(
        "--solid-fill",
        choices=("none", "between", "adjacent", "interior", "bbox"),
        default="none",
        help="Draw solid/inaccessible cells as dark structural infill. Interior fills solid components not connected to the map edge; between fills solid cells with open space on at least two sides; adjacent fills solid cells touching open space; bbox fills solid cells inside the non-solid bounding box.",
    )
    parser.add_argument(
        "--solid-fill-texture",
        choices=("wall", "floor"),
        default="wall",
        help="Texture source for --solid-fill cells.",
    )
    parser.add_argument(
        "--solid-fill-brightness",
        type=float,
        default=0.42,
        help="Brightness multiplier for solid infill textures.",
    )
    parser.add_argument(
        "--no-lighting",
        action="store_true",
        help="Ignore each level's DL.DAT ambient light_level and render at full brightness.",
    )
    parser.add_argument(
        "--min-brightness",
        type=float,
        default=0.35,
        help="Brightness multiplier applied at DL.DAT light_level 0 (darkest levels). "
        "Level light_level 15 (or a level with no DL.DAT entry) always renders at 1.0.",
    )
    parser.add_argument(
        "--debug-grid", action="store_true", help="Draw tile grid and coordinate labels"
    )
    parser.add_argument(
        "--grid-label-step",
        type=int,
        default=1,
        help="Label every Nth tile when --debug-grid is enabled.",
    )
    parser.add_argument(
        "--grid-coordinate-mode",
        choices=("display", "raw", "both"),
        default="display",
        help="Coordinate labels to draw. Display mode labels x,display_y for the rendered orientation.",
    )
    parser.add_argument("--name-files", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    textures = load_terrain_textures(args.texture_dir)
    door_textures = load_gr_textures(args.door_texture_dir, "doors")
    tmflat_textures = load_gr_textures(args.tmflat_texture_dir, "tmflat")
    tmobj_textures = load_gr_textures(args.tmobj_texture_dir, "tmobj")

    for slot in args.slots:
        level_path = args.levels_dir / f"level_{slot:03d}.json"
        level = json.loads(level_path.read_text(encoding="utf-8"))
        image = render_level(
            level, textures, door_textures, tmflat_textures, tmobj_textures, args
        )
        out_path = args.output / render_output_filename(
            slot, level, "u7_style_noceilings", args.name_files
        )
        image.save(out_path)
        print(f"Wrote {out_path} ({image.width}x{image.height})")

    return 0


def level_brightness_factor(level: dict, args) -> float:
    """Map a level's DL.DAT light_level (0..15) to a brightness multiplier.

    Levels with no DL.DAT entry, or --no-lighting, render at full brightness.
    Darkest levels (light_level 0) render at --min-brightness rather than
    black, since this is a top-down cutaway map, not a first-person view --
    floor/wall art should stay legible even in "dark" levels.
    """
    light_level = level.get("light_level")
    if args.no_lighting or light_level is None:
        return 1.0
    normalized = max(0, min(15, int(light_level))) / 15.0
    min_brightness = max(0.0, min(1.0, args.min_brightness))
    return min_brightness + normalized * (1.0 - min_brightness)


def apply_level_lighting(scene: Image.Image, level: dict, args) -> Image.Image:
    factor = level_brightness_factor(level, args)
    if factor >= 0.999:
        return scene
    alpha = scene.getchannel("A")
    dimmed = (
        ImageEnhance.Brightness(scene.convert("RGB")).enhance(factor).convert("RGBA")
    )
    dimmed.putalpha(alpha)
    return dimmed


def transform_floor_texture(
    texture: Image.Image, orientation: str, transform: str
) -> Image.Image:
    if transform == "auto":
        transform = "flip-y" if orientation == "display" else "none"
    if transform == "none":
        return texture
    if transform == "flip-y":
        return texture.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if transform == "flip-x":
        return texture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if transform == "rotate-180":
        return texture.transpose(Image.Transpose.ROTATE_180)
    raise ValueError(f"Unsupported floor texture transform: {transform}")


def render_level(
    level: dict,
    textures: dict[int, Image.Image],
    door_textures: dict[int, Image.Image],
    tmflat_textures: dict[int, Image.Image],
    tmobj_textures: dict[int, Image.Image],
    args,
    *,
    object_textures: dict[int, Image.Image] | None = None,
    animation_textures: dict[int, Image.Image] | None = None,
    common_objects: UW2CommonObjectTable | None = None,
    animations: UW2AnimationTable | None = None,
    models: UW2ModelArchive | None = None,
    palette: UW2Palette | None = None,
) -> Image.Image:
    tiles = level["tiles"]
    tile_map = {(tile["x"], tile["y"]): tile for tile in tiles}
    object_map = {obj["slot"]: obj for obj in level.get("objects", [])}
    non_solid = [tile for tile in tiles if tile["type_name"] != "solid"]
    min_floor = min((tile["floor_height"] for tile in non_solid), default=0)
    y_size = max((tile["y"] for tile in tiles), default=63) + 1

    floors: list[FloorPrimitive] = []
    solid_fills: list[SolidFillPrimitive] = []
    panels: list[WallPrimitive] = []
    sprites: list[SpritePrimitive] = []
    model_triangles: list[ModelTrianglePrimitive] = []
    solid_fill_coords = solid_cells_to_fill(tiles, tile_map, args.solid_fill)
    for tile in tiles:
        if (tile["x"], tile["y"]) not in solid_fill_coords:
            continue
        floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
        rx, ry = tile_origin(tile, y_size, args.orientation)
        sx, sy = project_point(rx, ry, floor_lift, args.tile_size, args.lift_pixels)
        texture_id = int(
            tile["texture_wall"]
            if args.solid_fill_texture == "wall"
            else tile["texture_floor"]
        )
        solid_fills.append(
            SolidFillPrimitive(
                texture_id=texture_id,
                x=round(sx),
                y=round(sy),
                sort_key=(sy - 0.1, sx - 0.1, floor_lift),
            )
        )

    for tile in non_solid:
        floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
        rx, ry = tile_origin(tile, y_size, args.orientation)
        sx, sy = project_point(rx, ry, floor_lift, args.tile_size, args.lift_pixels)
        floors.append(
            FloorPrimitive(
                texture_id=int(tile["texture_floor"]),
                type_name=tile["type_name"],
                x=round(sx),
                y=round(sy),
                sort_key=(sy, sx, floor_lift),
            )
        )
        panels.extend(make_tile_walls(tile, tile_map, min_floor, y_size, args))
        if not args.no_doors and (
            tile.get("door_present") or find_door_object(tile, object_map) is not None
        ):
            door = make_door_panel(
                tile, level, object_map, tile_map, min_floor, y_size, args
            )
            if door is not None:
                panels.append(door)
        if not args.no_flat_objects:
            panels.extend(
                make_flat_object_panels(tile, object_map, min_floor, y_size, args)
            )
        if not getattr(args, "no_objects", False):
            sprites.extend(
                make_sprite_primitives(
                    tile,
                    object_map,
                    min_floor,
                    y_size,
                    args,
                    object_textures or {},
                    animation_textures or {},
                    common_objects,
                    animations,
                )
            )
        if (
            getattr(args, "model_style", "icons") == "geometry"
            and not getattr(args, "no_models", False)
            and models is not None
            and palette is not None
        ):
            model_triangles.extend(
                make_model_primitives(
                    tile,
                    object_map,
                    min_floor,
                    y_size,
                    args,
                    models,
                    palette,
                )
            )

    min_x, min_y, max_x, max_y = primitive_bounds(
        floors, solid_fills, panels, sprites, model_triangles, args.tile_size
    )
    width = int(np.ceil(max_x - min_x + args.margin * 2))
    height = int(np.ceil(max_y - min_y + args.margin * 2))
    origin_x = min_x - args.margin
    origin_y = min_y - args.margin

    scene = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    scene_draw = ImageDraw.Draw(scene)
    for floor in sorted(floors, key=lambda item: item.sort_key):
        texture = textures.get(floor.texture_id)
        if texture is None:
            continue
        texture = transform_floor_texture(
            texture, args.orientation, args.floor_texture_transform
        )
        tile_image = texture.resize(
            (args.tile_size, args.tile_size), Image.Resampling.NEAREST
        )
        tile_image = clip_diagonal_floor_image(
            tile_image, floor.type_name, args.orientation
        )
        scene.alpha_composite(
            tile_image, (round(floor.x - origin_x), round(floor.y - origin_y))
        )

    for solid in sorted(solid_fills, key=lambda item: item.sort_key):
        texture = textures.get(solid.texture_id)
        if texture is None:
            continue
        fill_image = texture.resize(
            (args.tile_size, args.tile_size), Image.Resampling.NEAREST
        )
        fill_image = ImageEnhance.Brightness(fill_image).enhance(
            max(0.05, args.solid_fill_brightness)
        )
        alpha = Image.new("L", fill_image.size, 210)
        fill_image.putalpha(alpha)
        scene.alpha_composite(
            fill_image, (round(solid.x - origin_x), round(solid.y - origin_y))
        )

    for sprite in sorted(
        (sprite for sprite in sprites if sprite.background),
        key=lambda item: item.sort_key,
    ):
        sprite_x = round(sprite.x - sprite.image.width / 2 - origin_x)
        sprite_y = round(sprite.y - sprite.image.height - origin_y)
        scene.alpha_composite(sprite.image, (sprite_x, sprite_y))

    depth_primitives: list[WallPrimitive | SpritePrimitive | ModelTrianglePrimitive] = [
        *panels,
        *(sprite for sprite in sprites if not sprite.background),
        *model_triangles,
    ]
    depth_primitives.sort(key=lambda item: item.sort_key)
    for primitive in depth_primitives:
        if isinstance(primitive, SpritePrimitive):
            sprite_x = round(primitive.x - primitive.image.width / 2 - origin_x)
            sprite_y = round(primitive.y - primitive.image.height - origin_y)
            scene.alpha_composite(primitive.image, (sprite_x, sprite_y))
            continue
        if isinstance(primitive, ModelTrianglePrimitive):
            points = [
                (round(x - origin_x), round(y - origin_y)) for x, y in primitive.points
            ]
            scene_draw.polygon(points, fill=primitive.fill)
            continue
        wall = primitive
        source = {
            "door": door_textures,
            "tmflat": tmflat_textures,
            "tmobj": tmobj_textures,
        }.get(wall.texture_kind, textures)
        texture = source.get(wall.texture_id)
        if texture is None:
            if wall.texture_kind == "door":
                texture = make_door_fallback_texture()
            elif wall.texture_kind in ("tmflat", "tmobj"):
                continue
            else:
                continue
        elif wall.texture_kind in ("door", "tmflat", "tmobj"):
            texture = texture.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        else:
            texture = ImageEnhance.Brightness(texture).enhance(
                SIDE_SHADE.get(wall.side, SIDE_SHADE["diagonal"])
            )
        if wall.texture_kind == "door":
            texture = ImageEnhance.Brightness(texture).enhance(1.08)
        elif wall.texture_kind in ("tmflat", "tmobj"):
            texture = ImageEnhance.Brightness(texture).enhance(1.12)
        shifted_quad = (
            (wall.quad[0][0] - origin_x, wall.quad[0][1] - origin_y),
            (wall.quad[1][0] - origin_x, wall.quad[1][1] - origin_y),
            (wall.quad[2][0] - origin_x, wall.quad[2][1] - origin_y),
            (wall.quad[3][0] - origin_x, wall.quad[3][1] - origin_y),
        )
        draw_textured_parallelogram(scene, texture, shifted_quad)

    scene = apply_level_lighting(scene, level, args)

    canvas = Image.new("RGBA", (width, height), parse_hex_color(args.background))
    canvas.alpha_composite(scene)

    if args.debug_grid:
        draw_debug_grid(canvas, tiles, min_floor, y_size, origin_x, origin_y, args)

    return canvas


def make_sprite_primitives(
    tile: dict,
    object_map: dict[int, dict],
    min_floor: int,
    y_size: int,
    args,
    object_textures: dict[int, Image.Image],
    animation_textures: dict[int, Image.Image],
    common_objects: UW2CommonObjectTable | None,
    animations: UW2AnimationTable | None,
) -> list[SpritePrimitive]:
    """Build upright sprite overlays for ordinary and ANIMO map objects."""
    if common_objects is None:
        return []
    sprites: list[SpritePrimitive] = []
    for obj in iter_tile_objects(tile, object_map):
        item_id = int(obj.get("item_id", 0))
        if bool(obj.get("hidden")) or 0x0140 <= item_id <= 0x014F:
            continue
        if flat_object_texture(obj)[0] is not None:
            continue
        metadata = common_objects.get(item_id)
        is_model_icon = (
            metadata.render_type == 2
            and item_id in MODEL_ICON_ITEM_IDS
            and getattr(args, "model_style", "icons") == "icons"
            and not getattr(args, "no_models", False)
        )
        if metadata.render_type != 0 and not is_model_icon:
            continue
        image = object_textures.get(item_id)
        if 0x01C0 <= item_id <= 0x01CE and animations is not None:
            animation = animations.get(item_id)
            if animation.frame_count > 0:
                tick = max(0, int(getattr(args, "tick", 0)))
                frame = animation.start_frame + tick % animation.frame_count
                image = animation_textures.get(frame)
        if image is None:
            continue
        scale_option = "model_icon_scale" if is_model_icon else "object_scale"
        default_scale = 2.0
        scale = max(0.01, float(getattr(args, scale_option, default_scale)))
        scale *= float(args.tile_size) / 64.0
        sprite = image.resize(
            (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            ),
            Image.Resampling.NEAREST,
        )
        raw_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
        raw_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
        display_x, display_y = transform_boundary_point(
            raw_x, raw_y, y_size, args.orientation
        )
        object_lift = round(
            (float(obj.get("zpos", tile["floor_height"])) - float(min_floor))
            / max(float(args.floor_height_per_lift), 0.001)
        )
        screen_x, screen_y = project_point(
            display_x,
            display_y,
            object_lift,
            args.tile_size,
            args.lift_pixels,
        )
        sprites.append(
            SpritePrimitive(
                image=sprite,
                x=screen_x,
                y=screen_y,
                item_id=item_id,
                slot=int(obj.get("slot", 0)),
                sort_key=(screen_y + 0.5, screen_x, object_lift),
                background=is_model_icon,
            )
        )
    return sprites


def make_model_primitives(
    tile: dict,
    object_map: dict[int, dict],
    min_floor: int,
    y_size: int,
    args,
    models: UW2ModelArchive,
    palette: UW2Palette,
) -> list[ModelTrianglePrimitive]:
    """Project executable model triangles into cutaway screen space."""
    primitives: list[ModelTrianglePrimitive] = []
    model_scale = max(0.01, float(getattr(args, "model_scale", 1.0)))
    for obj in iter_tile_objects(tile, object_map):
        if bool(obj.get("hidden")):
            continue
        model = models.model_for_item(int(obj.get("item_id", 0)))
        if model is None:
            continue
        heading = int(obj.get("heading", 0)) & 0x07
        center_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
        center_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
        object_lift = round(
            (float(obj.get("zpos", tile["floor_height"])) - float(min_floor))
            / max(float(args.floor_height_per_lift), 0.001)
        )
        for triangle in model.triangles:
            points: list[tuple[float, float]] = []
            transformed = []
            for vertex in triangle.vertices:
                rotated_x, rotated_y, local_z = model.oriented_position(
                    vertex, heading, model_scale
                )
                raw_x = center_x + rotated_x
                raw_y = center_y + rotated_y
                display_x, display_y = transform_boundary_point(
                    raw_x, raw_y, y_size, args.orientation
                )
                screen_x, screen_y = project_point(
                    display_x,
                    display_y,
                    object_lift,
                    args.tile_size,
                    args.lift_pixels,
                )
                vertex_z = (
                    wall_screen_height(tile, args) / (model_scale * args.tile_size)
                    if vertex.roof
                    else local_z
                )
                height_pixels = vertex_z * model_scale * args.tile_size
                points.append((screen_x - height_pixels, screen_y - height_pixels))
                transformed.append((rotated_x, rotated_y, vertex_z * model_scale))
            fill = _model_face_color(
                triangle.palette_index,
                transformed,
                palette,
            )
            average_x = sum(point[0] for point in points) / 3.0
            average_y = sum(point[1] for point in points) / 3.0
            average_z = sum(vertex[2] for vertex in transformed) / 3.0
            primitives.append(
                ModelTrianglePrimitive(
                    points=(points[0], points[1], points[2]),
                    fill=fill,
                    sort_key=(average_y, average_x, round(average_z * 1000)),
                )
            )
    return primitives


def _model_face_color(
    palette_index: int,
    vertices: list[tuple[float, float, float]],
    palette: UW2Palette,
) -> tuple[int, int, int, int]:
    first, second, third = vertices
    edge_a = tuple(second[index] - first[index] for index in range(3))
    edge_b = tuple(third[index] - first[index] for index in range(3))
    normal = (
        edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
        edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
        edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
    )
    length = math.sqrt(sum(component * component for component in normal))
    upward = abs(normal[2]) / length if length > 0.000001 else 1.0
    side_light = (normal[0] - normal[1]) / length if length > 0.000001 else 0.0
    brightness = min(1.15, max(0.48, 0.62 + upward * 0.38 + side_light * 0.08))
    red, green, blue = palette.colors[palette_index & 0xFF]
    return (
        min(255, round(red * brightness)),
        min(255, round(green * brightness)),
        min(255, round(blue * brightness)),
        255,
    )


def solid_cells_to_fill(
    tiles: list[dict],
    tile_map: dict[tuple[int, int], dict],
    mode: str,
) -> set[tuple[int, int]]:
    if mode == "none":
        return set()

    non_solid = [tile for tile in tiles if tile["type_name"] != "solid"]
    if not non_solid:
        return set()

    if mode == "interior":
        min_x = min(int(tile["x"]) for tile in tiles)
        max_x = max(int(tile["x"]) for tile in tiles)
        min_y = min(int(tile["y"]) for tile in tiles)
        max_y = max(int(tile["y"]) for tile in tiles)
        solid_coords = {
            (int(tile["x"]), int(tile["y"]))
            for tile in tiles
            if tile["type_name"] == "solid"
        }
        visited: set[tuple[int, int]] = set()
        interior: set[tuple[int, int]] = set()
        for start in sorted(solid_coords):
            if start in visited:
                continue
            component: set[tuple[int, int]] = set()
            touches_edge = False
            queue = deque([start])
            visited.add(start)
            while queue:
                x, y = queue.popleft()
                component.add((x, y))
                if x in (min_x, max_x) or y in (min_y, max_y):
                    touches_edge = True
                for side in SIDES:
                    neighbor_coord = neighbor_coords(side, x, y)
                    if neighbor_coord in solid_coords and neighbor_coord not in visited:
                        visited.add(neighbor_coord)
                        queue.append(neighbor_coord)
            if not touches_edge:
                interior.update(component)
        return interior

    if mode == "bbox":
        min_x = min(int(tile["x"]) for tile in non_solid)
        max_x = max(int(tile["x"]) for tile in non_solid)
        min_y = min(int(tile["y"]) for tile in non_solid)
        max_y = max(int(tile["y"]) for tile in non_solid)
        return {
            (int(tile["x"]), int(tile["y"]))
            for tile in tiles
            if tile["type_name"] == "solid"
            and min_x <= int(tile["x"]) <= max_x
            and min_y <= int(tile["y"]) <= max_y
        }

    out: set[tuple[int, int]] = set()
    for tile in tiles:
        if tile["type_name"] != "solid":
            continue
        x = int(tile["x"])
        y = int(tile["y"])
        for side in SIDES:
            neighbor = tile_map.get(neighbor_coords(side, x, y))
            if neighbor is not None and neighbor["type_name"] != "solid":
                out.add((x, y))
                if mode == "adjacent":
                    break
    if mode == "between":
        filtered: set[tuple[int, int]] = set()
        for x, y in out:
            open_neighbors = 0
            for side in SIDES:
                neighbor = tile_map.get(neighbor_coords(side, x, y))
                if neighbor is not None and neighbor["type_name"] != "solid":
                    open_neighbors += 1
            if open_neighbors >= 2:
                filtered.add((x, y))
        return filtered
    return out


def draw_debug_grid(
    canvas: Image.Image,
    tiles: list[dict],
    min_floor: int,
    y_size: int,
    origin_x: float,
    origin_y: float,
    args,
) -> None:
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()
    label_step = max(1, int(args.grid_label_step))
    tile_by_xy = {(int(tile["x"]), int(tile["y"])): tile for tile in tiles}

    for y in range(y_size + 1):
        points = [
            grid_project_point(x, y, 0, min_floor, y_size, origin_x, origin_y, args)
            for x in range(0, 65)
        ]
        draw.line(points, fill=(255, 240, 120, 95), width=1)

    for x in range(65):
        points = [
            grid_project_point(x, y, 0, min_floor, y_size, origin_x, origin_y, args)
            for y in range(0, y_size + 1)
        ]
        draw.line(points, fill=(255, 240, 120, 95), width=1)

    for tile in tiles:
        raw_x = int(tile["x"])
        raw_y = int(tile["y"])
        display_y = y_size - 1 - raw_y
        if raw_x % label_step != 0 or display_y % label_step != 0:
            continue

        floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
        center = grid_project_point(
            raw_x + 0.5,
            raw_y + 0.5,
            floor_lift,
            min_floor,
            y_size,
            origin_x,
            origin_y,
            args,
        )
        label = tile_coordinate_label(
            raw_x, raw_y, display_y, args.grid_coordinate_mode
        )
        bbox = draw.textbbox(center, label, font=font, anchor="mm")
        pad = 2
        draw.rectangle(
            (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
            fill=(0, 0, 0, 150),
            outline=(255, 240, 120, 130),
        )
        draw.text(center, label, font=font, anchor="mm", fill=(255, 255, 210, 245))

    for coord in range(0, 64, label_step):
        raw_y = y_size - 1 - coord if args.orientation == "display" else coord
        left_tile = tile_by_xy.get((0, raw_y))
        top_raw_y = y_size - 1 if args.orientation == "display" else 0
        top_axis_y = y_size + 0.45 if args.orientation == "display" else -0.45
        top_tile = tile_by_xy.get((coord, top_raw_y))
        left_lift = (
            floor_lift_units(left_tile, min_floor, args.floor_height_per_lift)
            if left_tile
            else 0
        )
        top_lift = (
            floor_lift_units(top_tile, min_floor, args.floor_height_per_lift)
            if top_tile
            else 0
        )

        lx, ly = grid_project_point(
            -0.45, raw_y + 0.5, left_lift, min_floor, y_size, origin_x, origin_y, args
        )
        tx, ty = grid_project_point(
            coord + 0.5,
            top_axis_y,
            top_lift,
            min_floor,
            y_size,
            origin_x,
            origin_y,
            args,
        )
        draw.text(
            (lx, ly), str(coord), font=font, anchor="mm", fill=(255, 240, 120, 255)
        )
        draw.text(
            (tx, ty), str(coord), font=font, anchor="mm", fill=(255, 240, 120, 255)
        )

    canvas.alpha_composite(overlay)


def grid_project_point(
    x: float,
    y: float,
    lift: int,
    min_floor: int,
    y_size: int,
    origin_x: float,
    origin_y: float,
    args,
) -> tuple[float, float]:
    _ = min_floor
    tx, ty = transform_boundary_point(x, y, y_size, args.orientation)
    sx, sy = project_point(tx, ty, lift, args.tile_size, args.lift_pixels)
    return sx - origin_x, sy - origin_y


def make_tile_walls(
    tile: dict,
    tile_map: dict[tuple[int, int], dict],
    min_floor: int,
    y_size: int,
    args,
) -> list[WallPrimitive]:
    walls = []
    height_limit = (
        None
        if args.no_obstruction_clip
        else obstruction_limited_wall_height(tile, tile_map, min_floor, y_size, args)
    )
    if tile["type_name"].startswith("diagonal_"):
        walls.extend(
            make_diagonal_wall(tile, min_floor, y_size, args, height_limit=height_limit)
        )
        walls.extend(
            make_diagonal_corner_fills(tile, tile_map, min_floor, y_size, args)
        )

    for side in SIDES:
        if skip_external_side_for_diagonal(tile["type_name"], side):
            continue
        nx, ny = neighbor_coords(side, tile["x"], tile["y"])
        neighbor = tile_map.get((nx, ny))
        if neighbor_is_open_across_side(neighbor, opposite_side(side)):
            continue
        sort_bias = (
            0.6 if is_blocked_diagonal_neighbor(neighbor, opposite_side(side)) else 0.0
        )
        walls.append(
            make_edge_wall(
                tile,
                side,
                min_floor,
                y_size,
                args,
                sort_bias=sort_bias,
                height_limit=height_limit,
            )
        )
    return walls


def obstruction_limited_wall_height(
    tile: dict,
    tile_map: dict[tuple[int, int], dict],
    min_floor: int,
    y_size: int,
    args,
) -> float | None:
    """Cap wall height so it doesn't visually reach over the floor of the
    nearest tile "behind" this one in screen space.

    Both floor lift and wall height shift a tile's screen position up-left by
    the same amount per pixel, so a wall taller than the gap to the next
    tile back can paint over that tile's floor even though nothing about the
    draw order is wrong -- the quad itself reaches further than it should.
    Raw (x-k, y-k) (or (x-k, y+k) under display orientation, which is what
    raw (x-k, y-k) maps to) is exactly the diagonal of tiles whose floor
    footprint that reach direction can land on, k tiles out. Solid tiles
    along that diagonal have nothing to protect, so the search walks past
    them to the nearest non-solid one; it's bounded by how far the tallest
    possible wall (max_wall_height) could reach at all. Returns None when no
    such tile is in reach.
    """
    x = int(tile["x"])
    y = int(tile["y"])
    step = -1 if args.orientation == "raw" else 1
    max_reach = (
        args.max_wall_height
        if args.max_wall_height and args.max_wall_height > 0
        else args.tile_size * 8
    )
    max_steps = int(max_reach // args.tile_size) + 2

    neighbor = None
    for k in range(1, max_steps + 1):
        candidate = tile_map.get((x - k, y + k * step))
        if candidate is None:
            break
        if candidate["type_name"] != "solid":
            neighbor = candidate
            break
    if neighbor is None:
        return None

    _, tile_base = wall_corner_points(
        tile, (x, y), min_floor, y_size, args, height_override=0.0
    )
    _, neighbor_base = wall_corner_points(
        neighbor,
        (int(neighbor["x"]), int(neighbor["y"])),
        min_floor,
        y_size,
        args,
        height_override=0.0,
    )
    entry_height = (
        max(tile_base[0] - neighbor_base[0], tile_base[1] - neighbor_base[1])
        - args.tile_size
    )
    return entry_height if entry_height > 0 else None


def make_edge_wall(
    tile: dict,
    side: str,
    min_floor: int,
    y_size: int,
    args,
    sort_bias: float = 0.0,
    height_limit: float | None = None,
) -> WallPrimitive:
    wall_height = wall_screen_height(tile, args)
    if height_limit is not None:
        wall_height = min(wall_height, height_limit)
    a, b = edge_points(tile["x"], tile["y"], side)
    top_a, base_a = wall_corner_points(
        tile, a, min_floor, y_size, args, height_override=wall_height
    )
    top_b, base_b = wall_corner_points(
        tile, b, min_floor, y_size, args, height_override=wall_height
    )
    sort_y = max(base_a[1], base_b[1])
    sort_x = max(base_a[0], base_b[0])
    return WallPrimitive(
        texture_id=int(tile["texture_wall"]),
        texture_kind="terrain",
        side=visual_side(side, args.orientation),
        quad=(top_a, top_b, base_a, base_b),
        sort_key=(
            sort_y + sort_bias,
            sort_x + sort_bias,
            floor_lift_units(tile, min_floor, args.floor_height_per_lift),
        ),
    )


def make_diagonal_wall(
    tile: dict,
    min_floor: int,
    y_size: int,
    args,
    height_limit: float | None = None,
) -> list[WallPrimitive]:
    endpoints = diagonal_hypotenuse_endpoints(tile["type_name"], tile["x"], tile["y"])
    if endpoints is None:
        return []

    wall_height = wall_screen_height(tile, args)
    if height_limit is not None:
        wall_height = min(wall_height, height_limit)
    floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
    top_a, base_a = wall_corner_points(
        tile, endpoints[0][0], min_floor, y_size, args, height_override=wall_height
    )
    top_b, base_b = wall_corner_points(
        tile, endpoints[1][0], min_floor, y_size, args, height_override=wall_height
    )
    return [
        WallPrimitive(
            texture_id=int(tile["texture_wall"]),
            texture_kind="terrain",
            side="diagonal",
            quad=(top_a, top_b, base_a, base_b),
            sort_key=(max(base_a[1], base_b[1]), max(base_a[0], base_b[0]), floor_lift),
        )
    ]


def wall_corner_points(
    tile: dict,
    raw_point: tuple[float, float],
    min_floor: int,
    y_size: int,
    args,
    height_override: float | None = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Project a raw tile-grid corner using `tile`'s own floor lift and wall
    height, returning (top, base) screen points. Pass height_override to use
    a caller-computed height (e.g. clamped by obstruction_limited_wall_height)
    instead of `tile`'s natural wall_screen_height."""
    tx, ty = transform_boundary_point(
        raw_point[0], raw_point[1], y_size, args.orientation
    )
    floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
    base = project_point(tx, ty, floor_lift, args.tile_size, args.lift_pixels)
    wall_height = (
        wall_screen_height(tile, args) if height_override is None else height_override
    )
    top = (base[0] - wall_height, base[1] - wall_height)
    return top, base


def make_diagonal_corner_fills(
    tile: dict,
    tile_map: dict[tuple[int, int], dict],
    min_floor: int,
    y_size: int,
    args,
) -> list[WallPrimitive]:
    """Bridge the gap that opens at a diagonal tile's hypotenuse endpoints
    when the bordering neighbor has different floor/ceiling heights.

    make_diagonal_wall and the neighbor's own make_edge_wall each project the
    shared grid corner using their own tile's floor lift and wall height. When
    those heights match, the two panels share an exact edge. When they don't
    (common in dungeons with uneven floors), the panels' top and/or base
    corners land at different screen points, leaving a background-colored
    notch. This fills that notch with a small connecting panel.
    """
    endpoints = diagonal_hypotenuse_endpoints(tile["type_name"], tile["x"], tile["y"])
    if endpoints is None:
        return []

    floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
    fills: list[WallPrimitive] = []
    for raw_point, side in endpoints:
        nx, ny = neighbor_coords(side, tile["x"], tile["y"])
        neighbor = tile_map.get((nx, ny))
        if neighbor is None or neighbor["type_name"] == "solid":
            continue

        diag_top, diag_base = wall_corner_points(
            tile, raw_point, min_floor, y_size, args
        )
        neighbor_top, neighbor_base = wall_corner_points(
            neighbor, raw_point, min_floor, y_size, args
        )
        if diag_top == neighbor_top and diag_base == neighbor_base:
            continue

        fills.append(
            WallPrimitive(
                texture_id=int(tile["texture_wall"]),
                texture_kind="terrain",
                side="diagonal",
                quad=(diag_top, neighbor_top, diag_base, neighbor_base),
                sort_key=(
                    max(diag_base[1], neighbor_base[1]) + 0.75,
                    max(diag_base[0], neighbor_base[0]) + 0.75,
                    floor_lift,
                ),
            )
        )
    return fills


def make_door_panel(
    tile: dict,
    level: dict,
    object_map: dict[int, dict],
    tile_map: dict[tuple[int, int], dict],
    min_floor: int,
    y_size: int,
    args,
) -> WallPrimitive | None:
    door_obj = find_door_object(tile, object_map)
    if door_obj is None:
        door_texture_id = first_door_texture(level)
        heading = infer_flag_door_heading(tile, tile_map)
    else:
        door_kind = int(door_obj["item_id"]) & 0x07
        door_raw = level.get("texture_mapping", {}).get("door_raw", [])
        if door_kind >= 6 or door_kind >= len(door_raw):
            return None
        door_texture_id = int(door_raw[door_kind])
        heading = int(door_obj.get("heading", 0))

    floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
    wall_height = wall_screen_height(tile, args) * 0.95
    if door_obj is not None:
        a, b = door_line_points_from_object(tile["x"], tile["y"], door_obj)
    else:
        a, b = door_line_points(tile["x"], tile["y"], heading)
    a = transform_boundary_point(a[0], a[1], y_size, args.orientation)
    b = transform_boundary_point(b[0], b[1], y_size, args.orientation)
    base_a = project_point(a[0], a[1], floor_lift, args.tile_size, args.lift_pixels)
    base_b = project_point(b[0], b[1], floor_lift, args.tile_size, args.lift_pixels)
    top_a = (base_a[0] - wall_height, base_a[1] - wall_height)
    top_b = (base_b[0] - wall_height, base_b[1] - wall_height)
    return WallPrimitive(
        texture_id=door_texture_id,
        texture_kind="door",
        side="door",
        quad=(top_a, top_b, base_a, base_b),
        sort_key=(
            max(base_a[1], base_b[1]) + 0.25,
            max(base_a[0], base_b[0]) + 0.25,
            floor_lift,
        ),
    )


def make_flat_object_panels(
    tile: dict,
    object_map: dict[int, dict],
    min_floor: int,
    y_size: int,
    args,
) -> list[WallPrimitive]:
    panels: list[WallPrimitive] = []
    for obj in iter_tile_objects(tile, object_map):
        texture_kind, texture_id = flat_object_texture(obj)
        if texture_kind is None:
            continue
        panels.append(
            make_decal_panel(
                tile, obj, texture_kind, texture_id, min_floor, y_size, args
            )
        )
    return panels


def flat_object_texture(obj: dict) -> tuple[str | None, int]:
    """Texture archive and image for a flat wall-mounted decal object.

    Delegates to the shared rules in :mod:`titan.uw2.instances`. Only the
    object-texture classes are drawn as decals here; bridges and special walls
    borrow a level architectural texture and are handled as map geometry.
    """
    item_id = int(obj.get("item_id", 0))
    if not is_wall_mounted(item_id) or item_id in (
        THIN_WALL_ITEM,
        REMOVABLE_WALL_ITEM,
    ):
        return None, 0
    reference = object_material_for(obj)
    if reference is None or reference.is_terrain:
        return None, 0
    return reference.source, reference.index


def make_decal_panel(
    tile: dict,
    obj: dict,
    texture_kind: str,
    texture_id: int,
    min_floor: int,
    y_size: int,
    args,
) -> WallPrimitive:
    floor_lift = floor_lift_units(tile, min_floor, args.floor_height_per_lift)
    decal_height = min(24.0, max(10.0, wall_screen_height(tile, args) * 0.25))
    z_shift = min(
        wall_screen_height(tile, args) - decal_height,
        max(
            0.0,
            (float(obj.get("zpos", 0)) / 128.0) * wall_screen_height(tile, args) * 0.65,
        ),
    )
    a, b = decal_line_points(tile, obj)
    a = transform_boundary_point(a[0], a[1], y_size, args.orientation)
    b = transform_boundary_point(b[0], b[1], y_size, args.orientation)
    base_a = project_point(a[0], a[1], floor_lift, args.tile_size, args.lift_pixels)
    base_b = project_point(b[0], b[1], floor_lift, args.tile_size, args.lift_pixels)
    base_a = (base_a[0] - z_shift, base_a[1] - z_shift)
    base_b = (base_b[0] - z_shift, base_b[1] - z_shift)
    top_a = (base_a[0] - decal_height, base_a[1] - decal_height)
    top_b = (base_b[0] - decal_height, base_b[1] - decal_height)
    return WallPrimitive(
        texture_id=texture_id,
        texture_kind=texture_kind,
        side="decal",
        quad=(top_a, top_b, base_a, base_b),
        sort_key=(
            max(base_a[1], base_b[1]) + 0.5,
            max(base_a[0], base_b[0]) + 0.5,
            floor_lift,
        ),
    )


def decal_line_points(
    tile: dict, obj: dict
) -> tuple[tuple[float, float], tuple[float, float]]:
    x = int(tile["x"])
    y = int(tile["y"])
    heading = int(obj.get("heading", 0))
    obj_x = min(7, max(0, int(obj.get("in_tile_x", 4)))) / 8.0
    obj_y = min(7, max(0, int(obj.get("in_tile_y", 4)))) / 8.0
    half_width = 0.14
    if str(tile["type_name"]).startswith("diagonal_") and heading not in (0, 2, 4, 6):
        return diagonal_decal_line_points(
            x, y, tile["type_name"], obj_x, obj_y, half_width
        )
    if heading == 2:
        center = y + obj_y
        return (x + 1.0, center - half_width), (x + 1.0, center + half_width)
    if heading == 4:
        center = x + obj_x
        return (center + half_width, y), (center - half_width, y)
    if heading == 6:
        center = y + obj_y
        return (x, center + half_width), (x, center - half_width)
    center = x + obj_x
    return (center - half_width, y + 1.0), (center + half_width, y + 1.0)


def diagonal_decal_line_points(
    x: int,
    y: int,
    type_name: str,
    obj_x: float,
    obj_y: float,
    half_width: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    endpoints = {
        "diagonal_se": ((x, y), (x + 1, y + 1)),
        "diagonal_sw": ((x, y + 1), (x + 1, y)),
        "diagonal_nw": ((x + 1, y + 1), (x, y)),
        "diagonal_ne": ((x + 1, y), (x, y + 1)),
    }.get(type_name)
    if endpoints is None:
        center = x + obj_x
        return (center - half_width, y + 1.0), (center + half_width, y + 1.0)

    ax, ay = endpoints[0]
    bx, by = endpoints[1]
    dx = bx - ax
    dy = by - ay
    px = x + obj_x
    py = y + obj_y
    length_sq = dx * dx + dy * dy
    t = 0.5 if length_sq <= 0.001 else ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = min(1.0 - half_width, max(half_width, t))
    return (
        (ax + dx * (t - half_width), ay + dy * (t - half_width)),
        (ax + dx * (t + half_width), ay + dy * (t + half_width)),
    )


def first_door_texture(level: dict) -> int:
    door_raw = level.get("texture_mapping", {}).get("door_raw", [])
    return int(door_raw[0]) if door_raw else 0


def door_line_points(
    x: int, y: int, heading: int
) -> tuple[tuple[float, float], tuple[float, float]]:
    inset = 0.08
    if heading in (2, 6):
        return (x + 0.5, y + inset), (x + 0.5, y + 1.0 - inset)
    return (x + inset, y + 0.5), (x + 1.0 - inset, y + 0.5)


def door_line_points_from_object(
    x: int, y: int, obj: dict
) -> tuple[tuple[float, float], tuple[float, float]]:
    heading = int(obj.get("heading", 0))
    obj_x = (min(7, max(0, int(obj.get("in_tile_x", 4)))) + 0.5) / 8.0
    obj_y = (min(7, max(0, int(obj.get("in_tile_y", 4)))) + 0.5) / 8.0
    inset = 0.08
    if heading in (2, 6):
        center = x + obj_x
        return (center, y + inset), (center, y + 1.0 - inset)
    center = y + obj_y
    return (x + inset, center), (x + 1.0 - inset, center)


def make_door_fallback_texture() -> Image.Image:
    image = Image.new("RGBA", (32, 64), (92, 55, 31, 255))
    pixels = image.load()
    if pixels is None:
        raise RuntimeError("Pillow did not expose fallback door pixels")
    for y in range(64):
        for x in range(32):
            if x in (0, 31) or y in (0, 63) or x in (15, 16):
                pixels[x, y] = (38, 24, 14, 255)
            elif (x // 7 + y // 11) % 2 == 0:
                pixels[x, y] = (119, 74, 41, 255)
    return image


def floor_lift_units(tile: dict, min_floor: int, floor_height_per_lift: float) -> int:
    scale = max(floor_height_per_lift, 0.001)
    return round((float(tile["floor_height"]) - float(min_floor)) / scale)


def wall_screen_height(tile: dict, args) -> float:
    height_units = max(1.0, float(tile["ceiling_height"]) - float(tile["floor_height"]))
    normalized = height_units / 32.0
    wall_height = max(
        12.0, normalized * (args.tile_size * 0.5) * args.wall_height_scale
    )
    if args.max_wall_height and args.max_wall_height > 0:
        wall_height = min(wall_height, args.max_wall_height)
    return wall_height


def project_point(
    x: float, y: float, lift: int, tile_size: int, lift_pixels: float
) -> tuple[float, float]:
    offset = lift * lift_pixels
    return x * tile_size - offset, y * tile_size - offset


def tile_origin(tile: dict, y_size: int, orientation: str) -> tuple[float, float]:
    if orientation == "raw":
        return float(tile["x"]), float(tile["y"])
    return float(tile["x"]), float(y_size - 1 - tile["y"])


def transform_boundary_point(
    x: float, y: float, y_size: int, orientation: str
) -> tuple[float, float]:
    if orientation == "raw":
        return float(x), float(y)
    return float(x), float(y_size - y)


def visual_side(side: str, orientation: str) -> str:
    if orientation == "raw":
        return side
    if side == "front":
        return "back"
    if side == "back":
        return "front"
    return side


def edge_points(
    x: int, y: int, side: str
) -> tuple[tuple[float, float], tuple[float, float]]:
    if side == "left":
        return (x, y), (x, y + 1)
    if side == "right":
        return (x + 1, y), (x + 1, y + 1)
    if side == "back":
        return (x, y), (x + 1, y)
    return (x, y + 1), (x + 1, y + 1)


def primitive_bounds(
    floors: list[FloorPrimitive],
    solid_fills: list[SolidFillPrimitive],
    walls: list[WallPrimitive],
    sprites: list[SpritePrimitive],
    model_triangles: list[ModelTrianglePrimitive],
    tile_size: int,
) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for floor in floors:
        xs.extend([floor.x, floor.x + tile_size])
        ys.extend([floor.y, floor.y + tile_size])
    for solid in solid_fills:
        xs.extend([solid.x, solid.x + tile_size])
        ys.extend([solid.y, solid.y + tile_size])
    for wall in walls:
        for x, y in wall.quad:
            xs.append(x)
            ys.append(y)
    for sprite in sprites:
        xs.extend(
            [
                sprite.x - sprite.image.width / 2,
                sprite.x + sprite.image.width / 2,
            ]
        )
        ys.extend([sprite.y - sprite.image.height, sprite.y])
    for triangle in model_triangles:
        xs.extend(point[0] for point in triangle.points)
        ys.extend(point[1] for point in triangle.points)
    return min(xs), min(ys), max(xs), max(ys)


def draw_textured_parallelogram(
    canvas: Image.Image,
    texture: Image.Image,
    quad: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ],
) -> None:
    top_a, top_b, base_a, _base_b = quad
    min_x = max(0, int(np.floor(min(point[0] for point in quad))))
    min_y = max(0, int(np.floor(min(point[1] for point in quad))))
    max_x = min(canvas.width - 1, int(np.ceil(max(point[0] for point in quad))))
    max_y = min(canvas.height - 1, int(np.ceil(max(point[1] for point in quad))))
    if max_x < min_x or max_y < min_y:
        return

    e1 = np.array([top_b[0] - top_a[0], top_b[1] - top_a[1]], dtype=np.float64)
    e2 = np.array([base_a[0] - top_a[0], base_a[1] - top_a[1]], dtype=np.float64)
    det = e1[0] * e2[1] - e1[1] * e2[0]
    if abs(det) < 0.001:
        return

    inv = np.array([[e2[1], -e2[0]], [-e1[1], e1[0]]], dtype=np.float64) / det
    dest = np.array(canvas, dtype=np.uint8)
    src = np.array(texture.convert("RGBA"), dtype=np.uint8)
    src_h, src_w = src.shape[:2]
    origin = np.array(top_a, dtype=np.float64)

    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            uv = inv @ (np.array([px + 0.5, py + 0.5], dtype=np.float64) - origin)
            u, v = float(uv[0]), float(uv[1])
            if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
                continue
            sx = min(src_w - 1, max(0, int(u * src_w)))
            sy = min(src_h - 1, max(0, int(v * src_h)))
            pixel = src[sy, sx]
            alpha = int(pixel[3])
            if alpha == 0:
                continue
            if alpha == 255:
                dest[py, px] = pixel
            else:
                inv_alpha = 255 - alpha
                dest[py, px, :3] = (
                    pixel[:3] * alpha + dest[py, px, :3] * inv_alpha
                ) // 255
                dest[py, px, 3] = min(
                    255, alpha + int(dest[py, px, 3]) * inv_alpha // 255
                )

    canvas.paste(Image.fromarray(dest, "RGBA"))


if __name__ == "__main__":
    raise SystemExit(main())
