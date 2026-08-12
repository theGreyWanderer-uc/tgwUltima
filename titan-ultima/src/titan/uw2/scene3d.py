"""Shared 3D scene construction for Ultima Underworld II maps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image

from titan.uw2.geometry import TexturedTriangle, generate_tile_triangles
from titan.uw2.map_pipeline import MapRenderAssets, load_levels, load_render_assets
from titan.uw2.model_render import ITEM_MODEL_NAMES, model_texture_index


class UW2SceneError(ValueError):
    """Raised when a UU2 map scene cannot be built or written."""


@dataclass(frozen=True)
class SceneMaterial:
    """One color or image material referenced by scene triangle parts."""

    key: str
    color: tuple[int, int, int, int] = (255, 255, 255, 255)
    image: Image.Image | None = None
    nearest: bool = True


@dataclass(frozen=True)
class SceneTriangle:
    """One already world-transformed triangle."""

    vertices: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    uvs: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass
class ScenePart:
    """Triangle group sharing one material."""

    name: str
    material_key: str
    triangles: list[SceneTriangle] = field(default_factory=list)


@dataclass
class SceneObject:
    """One logical placed object, retained separately in exports."""

    name: str
    kind: str
    metadata: dict[str, object]
    parts: list[ScenePart] = field(default_factory=list)


@dataclass
class UW2Scene:
    """Renderer/exporter-neutral UU2 scene."""

    slot: int
    level_name: str | None
    region: tuple[int, int, int, int]
    materials: dict[str, SceneMaterial] = field(default_factory=dict)
    architecture: list[ScenePart] = field(default_factory=list)
    objects: list[SceneObject] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def triangle_count(self) -> int:
        return sum(len(part.triangles) for part in self.architecture) + sum(
            len(part.triangles) for obj in self.objects for part in obj.parts
        )


def parse_tile_region(value: str | None) -> tuple[int, int, int, int]:
    """Parse inclusive ``x1,y1,x2,y2`` bounds; default to whole map."""
    if value is None:
        return (0, 0, 63, 63)
    try:
        values = tuple(int(part.strip(), 0) for part in value.split(","))
    except ValueError as error:
        raise UW2SceneError("tile region must be x1,y1,x2,y2") from error
    if len(values) != 4:
        raise UW2SceneError("tile region must contain four values: x1,y1,x2,y2")
    x1, y1, x2, y2 = values
    if not (0 <= x1 <= x2 < 64 and 0 <= y1 <= y2 < 64):
        raise UW2SceneError(f"tile region outside 0..63 or reversed: {value}")
    return values


def build_map_scene(
    source: str | Path,
    *,
    slot: int,
    region: tuple[int, int, int, int] = (0, 0, 63, 63),
    include_ceilings: bool = False,
    include_sprites: bool = True,
    model_scale: float = 1.0,
    sprite_scale: float = 1.0,
    tick: int = 0,
) -> UW2Scene:
    """Read original game files and build one map scene fully in memory."""
    levels = load_levels(source, [slot])
    if not levels:
        raise UW2SceneError(f"UU2 LEV.ARK slot {slot} is unavailable")
    return build_level_scene(
        levels[0],
        load_render_assets(source),
        region=region,
        include_ceilings=include_ceilings,
        include_sprites=include_sprites,
        model_scale=model_scale,
        sprite_scale=sprite_scale,
        tick=tick,
    )


def build_level_scene(
    level: dict,
    assets: MapRenderAssets,
    *,
    region: tuple[int, int, int, int] = (0, 0, 63, 63),
    include_ceilings: bool = False,
    include_sprites: bool = True,
    model_scale: float = 1.0,
    sprite_scale: float = 1.0,
    tick: int = 0,
) -> UW2Scene:
    """Build scene from one decoded level plus in-memory source assets."""
    if model_scale <= 0 or sprite_scale <= 0:
        raise UW2SceneError("model and sprite scales must be positive")
    x1, y1, x2, y2 = region
    scene = UW2Scene(
        slot=int(level["slot_index"]),
        level_name=level.get("level_name"),
        region=region,
    )
    tiles = level["tiles"]
    tile_map = {(int(tile["x"]), int(tile["y"])): tile for tile in tiles}
    selected_tiles = [
        tile
        for tile in tiles
        if x1 <= int(tile["x"]) <= x2 and y1 <= int(tile["y"]) <= y2
    ]
    architecture: dict[str, ScenePart] = {}
    for tile in selected_tiles:
        for triangle in generate_tile_triangles(
            tile,
            tile_map,
            z_scale=1.0 / 32.0,
            ceiling_source="runtime",
            include_ceilings=include_ceilings,
        ):
            key = f"terrain_{triangle.texture_id:03d}"
            if key not in scene.materials:
                scene.materials[key] = SceneMaterial(
                    key=key, image=assets.terrain.get(triangle.texture_id)
                )
            part = architecture.setdefault(
                key, ScenePart(name=f"architecture_{key}", material_key=key)
            )
            part.triangles.append(_from_textured_triangle(triangle))
    scene.architecture.extend(architecture.values())

    for obj in level.get("objects", []):
        tile = _object_tile(obj, tile_map, region)
        if tile is None or bool(obj.get("hidden")):
            continue
        item_id = int(obj.get("item_id", 0))
        if item_id == 0:
            continue
        metadata = assets.common_objects.get(item_id)
        model = (
            assets.models.model_for_item(item_id) if assets.models is not None else None
        )
        if model is not None:
            scene.objects.append(
                _build_model_object(scene, obj, tile, model, assets, model_scale)
            )
        elif include_sprites and metadata.render_type == 0:
            image = _object_image(item_id, tick, assets)
            if image is None:
                scene.skipped["missing_sprite"] = (
                    scene.skipped.get("missing_sprite", 0) + 1
                )
                continue
            scene.objects.append(
                _build_sprite_object(
                    scene, obj, tile, image, metadata.height, sprite_scale
                )
            )
        else:
            key = f"render_type_{metadata.render_type_name}"
            scene.skipped[key] = scene.skipped.get(key, 0) + 1
    return scene


def _from_textured_triangle(triangle: TexturedTriangle) -> SceneTriangle:
    return SceneTriangle(vertices=triangle.vertices, uvs=triangle.uvs)


def _object_tile(
    obj: dict,
    tile_map: dict[tuple[int, int], dict],
    region: tuple[int, int, int, int],
) -> dict | None:
    x1, y1, x2, y2 = region
    for ref in obj.get("tile_refs", []):
        x, y = int(ref["x"]), int(ref["y"])
        if x1 <= x <= x2 and y1 <= y <= y2:
            return tile_map[(x, y)]
    return None


def _object_image(
    item_id: int, tick: int, assets: MapRenderAssets
) -> Image.Image | None:
    if 0x01C0 <= item_id <= 0x01CE:
        animation = assets.animations.get(item_id)
        if animation.frame_count:
            frame = animation.start_frame + max(0, tick) % animation.frame_count
            return assets.animo.get(frame)
    return assets.objects.get(item_id)


def _object_name(obj: dict, kind: str) -> str:
    item_id = int(obj["item_id"])
    label = ITEM_MODEL_NAMES.get(item_id, kind)
    return f"object_slot_{int(obj['slot']):04d}_item_{item_id:03d}_{label}"


def _placed_metadata(obj: dict, tile: dict) -> dict[str, object]:
    return {
        "slot": int(obj["slot"]),
        "item_id": int(obj["item_id"]),
        "item_id_hex": f"{int(obj['item_id']):#06x}",
        "tile_x": int(tile["x"]),
        "tile_y": int(tile["y"]),
        "in_tile_x": int(obj.get("in_tile_x", 4)),
        "in_tile_y": int(obj.get("in_tile_y", 4)),
        "zpos": int(obj.get("zpos", tile["floor_height"])),
        "heading": int(obj.get("heading", 0)),
        "flags": int(obj.get("flags", 0)),
        "quality": int(obj.get("quality", 0)),
        "owner": int(obj.get("owner", 0)),
    }


def _build_model_object(scene, obj, tile, model, assets, model_scale) -> SceneObject:
    name = _object_name(obj, "model")
    placed = SceneObject(name=name, kind="model", metadata=_placed_metadata(obj, tile))
    groups: dict[str, ScenePart] = {}
    item_id = int(obj["item_id"])
    texture_index = model_texture_index(item_id, int(obj.get("flags", 0)))
    center_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
    center_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
    base_z = float(obj.get("zpos", tile["floor_height"])) / 32.0
    heading = int(obj.get("heading", 0))
    for triangle in model.triangles:
        textured = triangle.textured and texture_index in assets.tmobj
        if textured:
            material_key = f"tmobj_{texture_index:03d}"
            scene.materials.setdefault(
                material_key,
                SceneMaterial(material_key, image=assets.tmobj[texture_index]),
            )
        else:
            material_key = f"palette_{triangle.palette_index:03d}"
            color = (*assets.palette.colors[triangle.palette_index], 255)
            scene.materials.setdefault(material_key, SceneMaterial(material_key, color))
        part = groups.setdefault(
            material_key,
            ScenePart(name=f"{name}_{material_key}", material_key=material_key),
        )
        vertices = []
        for vertex in triangle.vertices:
            local_x, local_y, local_z = model.oriented_position(
                vertex, heading, model_scale
            )
            x = local_x + center_x
            y = local_y + center_y
            z = (
                float(tile["ceiling_height"]) / 32.0
                if vertex.roof
                # Executable model Z already uses map-height units: table
                # base 96 + native top 10 = food records at zpos 106.
                # Optional footprint scaling only affects horizontal dimensions.
                else base_z + local_z
            )
            vertices.append((x, y, z))
        part.triangles.append(
            SceneTriangle(
                vertices=(vertices[0], vertices[1], vertices[2]),
                uvs=(
                    (triangle.vertices[0].u, 1.0 - triangle.vertices[0].v),
                    (triangle.vertices[1].u, 1.0 - triangle.vertices[1].v),
                    (triangle.vertices[2].u, 1.0 - triangle.vertices[2].v),
                ),
            )
        )
    placed.parts.extend(groups.values())
    placed.metadata.update(
        model_index=model.index,
        texture_index=texture_index,
        triangle_count=sum(len(part.triangles) for part in placed.parts),
    )
    return placed


def _build_sprite_object(scene, obj, tile, image, common_height, sprite_scale):
    name = _object_name(obj, "sprite")
    material_key = f"sprite_slot_{int(obj['slot']):04d}"
    scene.materials[material_key] = SceneMaterial(
        material_key, image=image.convert("RGBA")
    )
    center_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
    center_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
    base_z = float(obj.get("zpos", tile["floor_height"])) / 32.0
    height = max(float(common_height) / 32.0, 0.25) * sprite_scale
    width = height * image.width / max(image.height, 1)
    triangles: list[SceneTriangle] = []
    # Crossed planes remain visible from arbitrary exported-scene cameras.
    for dx, dy in ((width / 2.0, 0.0), (0.0, width / 2.0)):
        a = (center_x - dx, center_y - dy, base_z)
        b = (center_x + dx, center_y + dy, base_z)
        c = (center_x + dx, center_y + dy, base_z + height)
        d = (center_x - dx, center_y - dy, base_z + height)
        triangles.extend(
            (
                SceneTriangle((a, b, c), ((0, 1), (1, 1), (1, 0))),
                SceneTriangle((a, c, d), ((0, 1), (1, 0), (0, 0))),
                SceneTriangle((c, b, a), ((1, 0), (1, 1), (0, 1))),
                SceneTriangle((d, c, a), ((0, 0), (1, 0), (0, 1))),
            )
        )
    placed = SceneObject(
        name=name,
        kind="sprite",
        metadata=_placed_metadata(obj, tile),
        parts=[
            ScenePart(
                name=f"{name}_billboard", material_key=material_key, triangles=triangles
            )
        ],
    )
    placed.metadata.update(
        center_x=center_x,
        center_y=center_y,
        base_z=base_z,
        width=width,
        height=height,
        triangle_count=len(triangles),
    )
    return placed


def iter_scene_parts(scene: UW2Scene) -> Iterable[tuple[ScenePart, SceneObject | None]]:
    """Yield architecture, then object parts with logical owners."""
    for part in scene.architecture:
        yield part, None
    for obj in scene.objects:
        for part in obj.parts:
            yield part, obj
