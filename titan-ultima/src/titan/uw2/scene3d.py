"""Shared 3D scene construction for Ultima Underworld II maps."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image

from titan.uw2.geometry import TexturedTriangle, generate_tile_triangles
from titan.uw2.instances import (
    BED_ITEM,
    DOOR_FRAME_MODEL,
    DOORS,
    REMOVABLE_WALL_ITEM,
    TERRAIN,
    TMFLAT,
    TMOBJ,
    WALL_ROLE,
    MaterialRef,
    bed_face_palette,
    bed_palette_indices,
    door_class,
    door_lift,
    door_panel_model,
    door_swing_radians,
    door_texture_id,
    is_door,
    is_open_door,
    is_portcullis,
    is_secret_door,
    is_wall_mounted,
    object_material_for,
    portcullis_bar_model,
    special_model_index,
    terrain_texture_id,
    writing_message_index,
    writing_prefix_index,
)
from titan.uw2.map_pipeline import MapRenderAssets, load_levels, load_render_assets
from titan.uw2.model_render import ITEM_MODEL_NAMES


class UW2SceneError(ValueError):
    """Raised when a UU2 map scene cannot be built or written."""


DEFAULT_Z_SCALE = 1.0 / 32.0
"""Level height units are 1/32 of a tile edge."""

CEILING_SOURCES = ("runtime", "ua")
"""``runtime`` follows the runtime port; ``ua`` uses UnderworldAdventures' mapping[32]."""


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
    ceiling_source: str = "runtime",
    z_scale: float = DEFAULT_Z_SCALE,
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
        ceiling_source=ceiling_source,
        z_scale=z_scale,
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
    ceiling_source: str = "runtime",
    z_scale: float = DEFAULT_Z_SCALE,
) -> UW2Scene:
    """Build scene from one decoded level plus in-memory source assets."""
    if model_scale <= 0 or sprite_scale <= 0:
        raise UW2SceneError("model and sprite scales must be positive")
    if ceiling_source not in CEILING_SOURCES:
        raise UW2SceneError(f"ceiling source must be one of {CEILING_SOURCES}")
    if z_scale <= 0:
        raise UW2SceneError("z scale must be positive")
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
            z_scale=z_scale,
            ceiling_source=ceiling_source,
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
        if is_door(item_id) and assets.models is not None:
            scene.objects.append(
                _build_door_object(
                    scene, obj, tile, assets, model_scale, z_scale, level=level
                )
            )
            continue
        model = None
        if assets.models is not None:
            model = assets.models.model_for_item(item_id)
            if model is None:
                special = special_model_index(item_id)
                if special is not None:
                    model = assets.models.model(special)
        if model is not None:
            scene.objects.append(
                _build_model_object(
                    scene,
                    obj,
                    tile,
                    model,
                    assets,
                    model_scale,
                    z_scale,
                    level=level,
                )
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
                    scene, obj, tile, image, metadata.height, sprite_scale, z_scale
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
    item_id = int(obj["item_id"])
    metadata: dict[str, object] = {
        "slot": int(obj["slot"]),
        "item_id": item_id,
        "item_id_hex": f"{item_id:#06x}",
        "tile_x": int(tile["x"]),
        "tile_y": int(tile["y"]),
        "in_tile_x": int(obj.get("in_tile_x", 4)),
        "in_tile_y": int(obj.get("in_tile_y", 4)),
        "zpos": int(obj.get("zpos", tile["floor_height"])),
        "heading": int(obj.get("heading", 0)),
        "flags": int(obj.get("flags", 0)),
        "quality": int(obj.get("quality", 0)),
        "owner": int(obj.get("owner", 0)),
        "enchanted": bool(obj.get("enchanted", False)),
    }
    if is_wall_mounted(item_id):
        metadata["wall_mounted"] = True
    if item_id == REMOVABLE_WALL_ITEM:
        # A thin wall the player can remove; exporters should keep it separate
        # from baked terrain so it stays individually addressable.
        metadata["removable_wall"] = True
    if item_id == BED_ITEM:
        # Applied to the bedding faces; recorded here so an exporter can see
        # which owner produced them without recomputing the formula.
        sheet, pillow = bed_palette_indices(int(obj.get("owner", 0)))
        metadata["bed_sheet_palette_index"] = sheet
        metadata["bed_pillow_palette_index"] = pillow
    link = obj.get("special_link")
    if link:
        metadata["trigger_link"] = int(link)
    return metadata


def _register_material(scene: UW2Scene, reference, level: dict, assets) -> str | None:
    """Register the material a :class:`MaterialRef` names; return its scene key."""
    if reference is None:
        return None
    if reference.source == TMOBJ:
        key = f"tmobj_{reference.index:03d}"
        image = assets.tmobj.get(reference.index)
    elif reference.source == TMFLAT:
        key = f"tmflat_{reference.index:03d}"
        image = assets.tmflat.get(reference.index)
    elif reference.source == DOORS:
        texture_id = door_texture_id(reference, level)
        if texture_id is None:
            return None
        key = f"doors_{texture_id:03d}"
        image = assets.doors.get(texture_id)
    elif reference.is_terrain:
        texture_id = terrain_texture_id(reference, level)
        if texture_id is None:
            return None
        key = f"terrain_{texture_id:03d}"
        image = assets.terrain.get(texture_id)
    else:
        return None
    if image is None:
        return None
    scene.materials.setdefault(key, SceneMaterial(key, image=image))
    return key


def _writing_metadata(obj: dict, strings) -> dict[str, object]:
    """Readable sign text for a writing object, when strings are available."""
    index = writing_message_index(obj)
    result: dict[str, object] = {
        "writing_prefix_index": writing_prefix_index(int(obj.get("flags", 0))),
    }
    if index is not None:
        result["writing_message_index"] = index
    if strings is None:
        return result
    prefix = strings.get(8, result["writing_prefix_index"])
    if prefix:
        result["writing_prefix"] = prefix
    if index is not None:
        message = strings.get(8, index)
        if message:
            result["writing_text"] = message.strip()
    return result


def _build_model_object(
    scene,
    obj,
    tile,
    model,
    assets,
    model_scale,
    z_scale=DEFAULT_Z_SCALE,
    level: dict | None = None,
) -> SceneObject:
    name = _object_name(obj, "model")
    metadata = _placed_metadata(obj, tile)
    reference = object_material_for(obj)
    textured_key = _register_material(scene, reference, level or {}, assets)
    if reference is not None:
        metadata["texture_source"] = reference.source
        metadata["texture_index"] = reference.index
        if reference.role:
            metadata["texture_role"] = reference.role
    if int(obj["item_id"]) == 0x0166:
        metadata.update(_writing_metadata(obj, getattr(assets, "strings", None)))
    placed = SceneObject(name=name, kind="model", metadata=metadata)
    groups: dict[str, ScenePart] = {}
    center_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
    center_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
    base_z = float(obj.get("zpos", tile["floor_height"])) * z_scale
    heading = int(obj.get("heading", 0))
    bed_owner = int(obj.get("owner", 0)) if int(obj["item_id"]) == BED_ITEM else None
    for triangle in model.triangles:
        if triangle.textured and textured_key is not None:
            material_key = textured_key
        else:
            palette_index = triangle.palette_index
            if bed_owner is not None:
                owner_colour = bed_face_palette(triangle, bed_owner)
                if owner_colour is not None:
                    palette_index = owner_colour
            material_key = f"palette_{palette_index:03d}"
            color = (*assets.palette.colors[palette_index], 255)
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
                float(tile["ceiling_height"]) * z_scale
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
        triangle_count=sum(len(part.triangles) for part in placed.parts),
    )
    return placed


def _build_door_object(
    scene,
    obj,
    tile,
    assets,
    model_scale,
    z_scale=DEFAULT_Z_SCALE,
    level: dict | None = None,
) -> SceneObject:
    """Compose a doorway as one object with separately named frame and panel.

    The frame is the fixed surround, its roof vertices reaching the tile
    ceiling. The panel is the moving leaf: hinged doors swing about one vertical
    edge, portcullises rise straight up. Both stay in one ``SceneObject`` so an
    exporter keeps the doorway together while still addressing the parts.
    """
    item_id = int(obj["item_id"])
    level = level or {}
    name = _object_name(obj, "door")
    metadata = _placed_metadata(obj, tile)
    doordir = int(obj.get("doordir", 0))
    swing = door_swing_radians(item_id, int(obj.get("flags", 0)), doordir)
    lift = door_lift(item_id, int(obj.get("flags", 0)))
    metadata.update(
        door_class=door_class(item_id),
        door_open=is_open_door(item_id),
        door_portcullis=is_portcullis(item_id),
        door_secret=is_secret_door(item_id),
        doordir=doordir,
        door_swing_degrees=round(math.degrees(swing), 3),
        door_lift=round(lift, 4),
    )

    placed = SceneObject(name=name, kind="door", metadata=metadata)
    frame_model = assets.models.model(DOOR_FRAME_MODEL)
    panel_model = assets.models.model(door_panel_model(item_id))
    if is_portcullis(item_id):
        # The executable has no portcullis; its slot holds the solid door
        # panel, which would read as a slab across the doorway.
        panel_model = portcullis_bar_model(panel_model)
        metadata["door_geometry"] = "reconstructed"
    else:
        metadata["door_geometry"] = "decoded"

    # The frame borrows the wall it is cut into; the panel takes a door texture,
    # except a secret door which also wears the wall.
    frame_reference = MaterialRef(TERRAIN, int(tile["wall_texture_index"]), WALL_ROLE)
    frame_key = _register_material(scene, frame_reference, level, assets)
    panel_reference = object_material_for(obj, tile)
    panel_key = _register_material(scene, panel_reference, level, assets)
    if panel_reference is not None:
        metadata["texture_source"] = panel_reference.source
        metadata["texture_index"] = panel_reference.index

    _emit_model_parts(
        scene,
        placed,
        f"{name}_frame",
        frame_model,
        obj,
        tile,
        assets,
        model_scale,
        z_scale,
        textured_key=frame_key,
    )
    _emit_model_parts(
        scene,
        placed,
        f"{name}_panel",
        panel_model,
        obj,
        tile,
        assets,
        model_scale,
        z_scale,
        textured_key=panel_key,
        swing=swing,
        lift=lift,
        doordir=doordir,
    )
    placed.metadata.update(
        model_index=frame_model.index,
        panel_model_index=panel_model.index,
        triangle_count=sum(len(part.triangles) for part in placed.parts),
    )
    return placed


def _emit_model_parts(
    scene,
    placed,
    name,
    model,
    obj,
    tile,
    assets,
    model_scale,
    z_scale,
    *,
    textured_key: str | None,
    swing: float = 0.0,
    lift: float = 0.0,
    doordir: int = 0,
) -> None:
    """Append one model's triangles to a scene object, optionally hinged."""
    groups: dict[str, ScenePart] = {}
    center_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
    center_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
    base_z = float(obj.get("zpos", tile["floor_height"])) * z_scale
    heading = int(obj.get("heading", 0))
    hinge = _door_hinge(model, doordir) if swing else None

    for triangle in model.triangles:
        if triangle.textured and textured_key is not None:
            material_key = textured_key
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
            local_x, local_y, local_z = model.local_position(vertex)
            if hinge is not None:
                local_x, local_y = _rotate_about(local_x, local_y, hinge, swing)
            local_x, local_y, local_z = _oriented(
                model, local_x, local_y, local_z, heading, model_scale
            )
            z = (
                float(tile["ceiling_height"]) * z_scale
                if vertex.roof
                else base_z + local_z + lift
            )
            vertices.append((local_x + center_x, local_y + center_y, z))
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


def _door_hinge(model, doordir: int) -> tuple[float, float]:
    """Hinge point in model-local space, chosen by the swing direction.

    The reference pivots on the same vertical edge either way, taking the front
    corner normally and the rear corner when ``doordir`` is set, which is what
    reverses the swing.
    """
    points = [
        model.local_position(vertex)
        for triangle in model.triangles
        for vertex in triangle.vertices
    ]
    hinge_x = min(point[0] for point in points)
    depths = [point[1] for point in points]
    return (hinge_x, max(depths) if doordir == 1 else min(depths))


def _rotate_about(
    x: float, y: float, hinge: tuple[float, float], radians: float
) -> tuple[float, float]:
    cosine, sine = math.cos(radians), math.sin(radians)
    dx, dy = x - hinge[0], y - hinge[1]
    return (
        hinge[0] + dx * cosine - dy * sine,
        hinge[1] + dx * sine + dy * cosine,
    )


def _oriented(
    model, local_x: float, local_y: float, local_z: float, heading: int, scale: float
) -> tuple[float, float, float]:
    """Apply the clockwise heading to an already model-local position."""
    angle = -(heading & 7) * math.tau / 8.0
    cosine, sine = math.cos(angle), math.sin(angle)
    return (
        (local_x * cosine - local_y * sine) * scale,
        (local_x * sine + local_y * cosine) * scale,
        local_z,
    )


def _build_sprite_object(
    scene, obj, tile, image, common_height, sprite_scale, z_scale=DEFAULT_Z_SCALE
):
    name = _object_name(obj, "sprite")
    material_key = f"sprite_slot_{int(obj['slot']):04d}"
    scene.materials[material_key] = SceneMaterial(
        material_key, image=image.convert("RGBA")
    )
    center_x = float(tile["x"]) + float(obj.get("in_tile_x", 4)) / 8.0
    center_y = float(tile["y"]) + float(obj.get("in_tile_y", 4)) / 8.0
    base_z = float(obj.get("zpos", tile["floor_height"])) * z_scale
    height = max(float(common_height) * z_scale, 0.25) * sprite_scale
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
