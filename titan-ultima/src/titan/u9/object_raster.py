"""Top-down software rasterization of placed Ultima IX model geometry."""

from __future__ import annotations

__all__ = [
    "U9ObjectRasterDiagnostics",
    "U9ObjectRasterError",
    "U9ObjectTextureProvider",
    "rasterize_object_meshes",
]

from dataclasses import dataclass

import numpy as np
from PIL import Image

from titan.u9.map_render import U9MapRenderError, U9ObjectTextureProvider
from titan.u9.mesh_export import flatten_model_triangles
from titan.u9.model import MATERIAL_ALPHA_NONE, U9Material
from titan.u9.object_placement import (
    U9ModelProvider,
    U9ObjectPlacementResolution,
)
from titan.u9.region_scene import TERRAIN_POINT_WORLD_XY, U9RegionScene
from titan.u9.transform import mat4_trs


class U9ObjectRasterError(Exception):
    """Raised when placed model meshes cannot be rasterized faithfully."""


@dataclass(frozen=True)
class U9ObjectRasterDiagnostics:
    """Coverage evidence for one object-mesh raster pass."""

    placements_selected: int
    placements_drawn: int
    models_drawn: int
    triangles_considered: int
    triangles_drawn: int
    pixels_drawn: int
    missing_texture_keys: tuple[str, ...]


@dataclass(frozen=True)
class _ModelRasterGeometry:
    positions: np.ndarray
    uvs: np.ndarray
    materials: tuple[U9Material | None, ...]


@dataclass(frozen=True)
class _RasterMaterial:
    pixels: np.ndarray
    alpha: int
    additive: bool
    clamp_s: bool
    clamp_t: bool


def _model_geometry(
    models: U9ModelProvider, model_id: int, lod: int
) -> _ModelRasterGeometry:
    lookup = models.model(model_id)
    if lookup.model is None:
        return _ModelRasterGeometry(
            np.empty((0, 3, 3), dtype=np.float64),
            np.empty((0, 3, 2), dtype=np.float64),
            (),
        )
    triangles = flatten_model_triangles(lookup.model, lod)
    return _ModelRasterGeometry(
        np.asarray(
            [[corner.position for corner in triangle] for triangle in triangles],
            dtype=np.float64,
        ).reshape((-1, 3, 3)),
        np.asarray(
            [[corner.uv for corner in triangle] for triangle in triangles],
            dtype=np.float64,
        ).reshape((-1, 3, 2)),
        tuple(triangle[0].material for triangle in triangles),
    )


def _material_alpha(material: U9Material | None) -> int:
    if material is None:
        return 255
    if material.modified_alpha != MATERIAL_ALPHA_NONE:
        return material.modified_alpha
    return material.default_alpha


def _raster_material(
    textures: U9ObjectTextureProvider,
    material: U9Material | None,
    cache: dict[tuple[int, int, int], _RasterMaterial],
    missing: set[str],
) -> _RasterMaterial:
    if material is None:
        key = (-1, 0, 255)
        cached = cache.get(key)
        if cached is None:
            cached = _RasterMaterial(
                np.full((1, 1, 4), (200, 200, 200, 255), dtype=np.uint8),
                255,
                False,
                True,
                True,
            )
            cache[key] = cached
        return cached

    alpha = _material_alpha(material)
    key = (material.texture_id, material.cur_frame, material.render_flags | alpha << 16)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        image = textures.frame_image(material.texture_id, material.cur_frame)
        pixels = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except U9MapRenderError:
        pixels = np.asarray(
            Image.new("RGBA", (2, 2), (255, 0, 255, 255)), dtype=np.uint8
        )
        missing.add(f"{material.texture_id}:{material.cur_frame}")
    result = _RasterMaterial(
        pixels,
        alpha,
        material.is_additive,
        material.clamps_s,
        material.clamps_t,
    )
    cache[key] = result
    return result


def _edge(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    px: np.ndarray,
    py: np.ndarray,
) -> np.ndarray:
    return (px - ax) * (by - ay) - (py - ay) * (bx - ax)


def _texture_indices(values: np.ndarray, length: int, clamp: bool) -> np.ndarray:
    if clamp:
        normalized = np.clip(values, 0.0, 1.0)
    else:
        normalized = np.mod(values, 1.0)
    indices = np.floor(normalized * length).astype(np.int64)
    # Very large UVs can round a wrapped value back to exactly 1.0.
    return np.clip(indices, 0, length - 1)


def _rasterize_triangle(
    target: np.ndarray,
    depth: np.ndarray,
    screen: np.ndarray,
    world: np.ndarray,
    uvs: np.ndarray,
    material: _RasterMaterial,
) -> int:
    image_height, image_width = depth.shape
    min_x = max(0, int(np.floor(np.min(screen[:, 0]))))
    max_x = min(image_width - 1, int(np.ceil(np.max(screen[:, 0]))))
    min_y = max(0, int(np.floor(np.min(screen[:, 1]))))
    max_y = min(image_height - 1, int(np.ceil(np.max(screen[:, 1]))))
    if min_x > max_x or min_y > max_y:
        return 0

    x0, y0, _z0 = screen[0]
    x1, y1, _z1 = screen[1]
    x2, y2, _z2 = screen[2]
    area = float(_edge(x0, y0, x1, y1, np.asarray(x2), np.asarray(y2)))
    if not np.isfinite(area) or abs(area) < 1e-8:
        return 0

    yy, xx = np.ogrid[min_y : max_y + 1, min_x : max_x + 1]
    sample_x = xx.astype(np.float64) + 0.5
    sample_y = yy.astype(np.float64) + 0.5
    weight0 = _edge(x1, y1, x2, y2, sample_x, sample_y) / area
    weight1 = _edge(x2, y2, x0, y0, sample_x, sample_y) / area
    weight2 = 1.0 - weight0 - weight1
    inside = (weight0 >= -1e-7) & (weight1 >= -1e-7) & (weight2 >= -1e-7)
    if not np.any(inside):
        return 0

    interpolated_z = (
        weight0 * screen[0, 2] + weight1 * screen[1, 2] + weight2 * screen[2, 2]
    )
    depth_view = depth[min_y : max_y + 1, min_x : max_x + 1]
    visible = inside & (interpolated_z > depth_view)
    if not np.any(visible):
        return 0

    interpolated_u = weight0 * uvs[0, 0] + weight1 * uvs[1, 0] + weight2 * uvs[2, 0]
    interpolated_v = weight0 * uvs[0, 1] + weight1 * uvs[1, 1] + weight2 * uvs[2, 1]
    texture_height, texture_width = material.pixels.shape[:2]
    texture_x = _texture_indices(interpolated_u, texture_width, material.clamp_s)
    texture_y = _texture_indices(interpolated_v, texture_height, material.clamp_t)
    source = material.pixels[texture_y, texture_x]
    effective_alpha = (
        source[:, :, 3].astype(np.uint16) * material.alpha // 255
    ).astype(np.uint8)
    visible &= effective_alpha > 0
    if not np.any(visible):
        return 0

    world_a, world_b, world_c = world
    normal = np.cross(world_b - world_a, world_c - world_a)
    normal_length = float(np.linalg.norm(normal))
    facing = abs(float(normal[2])) / normal_length if normal_length else 0.0
    shade = 0.62 + 0.38 * facing
    source_rgb = np.clip(source[:, :, :3].astype(np.float32) * shade, 0, 255)

    target_view = target[min_y : max_y + 1, min_x : max_x + 1]
    alpha = effective_alpha.astype(np.float32) / 255.0
    if material.additive:
        blended = np.minimum(
            255.0,
            target_view[:, :, :3].astype(np.float32) + source_rgb * alpha[:, :, None],
        )
    else:
        blended = source_rgb * alpha[:, :, None] + target_view[:, :, :3].astype(
            np.float32
        ) * (1.0 - alpha[:, :, None])
    target_view[:, :, :3][visible] = blended[visible].astype(np.uint8)
    target_view[:, :, 3][visible] = np.maximum(
        target_view[:, :, 3][visible], effective_alpha[visible]
    )
    depth_view[visible] = interpolated_z[visible]
    return int(np.count_nonzero(visible))


def rasterize_object_meshes(
    pixels: np.ndarray,
    surface_depth: np.ndarray,
    scene: U9RegionScene,
    models: U9ModelProvider,
    textures: U9ObjectTextureProvider,
    placements: tuple[U9ObjectPlacementResolution, ...],
    *,
    pixels_per_cell: int,
    lod: int = 0,
    flip_y: bool = True,
) -> U9ObjectRasterDiagnostics:
    """Rasterize transformed placed meshes over terrain with a top-down z-buffer."""
    if pixels.shape[:2] != surface_depth.shape:
        raise U9ObjectRasterError("surface depth dimensions must match map pixels")
    if lod < 0:
        raise U9ObjectRasterError("object LOD cannot be negative")

    depth = surface_depth
    geometry_cache: dict[int, _ModelRasterGeometry] = {}
    material_cache: dict[tuple[int, int, int], _RasterMaterial] = {}
    missing: set[str] = set()
    placements_drawn = 0
    triangles_considered = 0
    triangles_drawn = 0
    pixels_drawn = 0
    model_ids_drawn: set[int] = set()

    for placement in placements:
        if placement.model_id is None:
            continue
        geometry = geometry_cache.get(placement.model_id)
        if geometry is None:
            geometry = _model_geometry(models, placement.model_id, lod)
            geometry_cache[placement.model_id] = geometry
        if not len(geometry.positions):
            continue

        matrix = np.asarray(
            mat4_trs(
                (
                    float(placement.position.x),
                    float(placement.position.y),
                    float(placement.position.z),
                ),
                placement.quaternion_wxyz,
                placement.scale_xyz,
            ),
            dtype=np.float64,
        ).reshape((4, 4))
        local = geometry.positions.reshape((-1, 3))
        world = local @ matrix[:3, :3].T + matrix[:3, 3]
        screen = world.copy()
        screen[:, 0] = world[:, 0] / TERRAIN_POINT_WORLD_XY * pixels_per_cell
        terrain_y = world[:, 1] / TERRAIN_POINT_WORLD_XY
        screen[:, 1] = (
            (scene.terrain.height - terrain_y) * pixels_per_cell
            if flip_y
            else terrain_y * pixels_per_cell
        )
        screen = screen.reshape((-1, 3, 3))
        world = world.reshape((-1, 3, 3))

        placement_drawn = False
        for triangle_index, triangle_screen in enumerate(screen):
            triangles_considered += 1
            if not np.all(np.isfinite(triangle_screen)):
                continue
            material = _raster_material(
                textures,
                geometry.materials[triangle_index],
                material_cache,
                missing,
            )
            count = _rasterize_triangle(
                pixels,
                depth,
                triangle_screen,
                world[triangle_index],
                geometry.uvs[triangle_index],
                material,
            )
            if count:
                triangles_drawn += 1
                pixels_drawn += count
                placement_drawn = True
        if placement_drawn:
            placements_drawn += 1
            model_ids_drawn.add(placement.model_id)

    return U9ObjectRasterDiagnostics(
        placements_selected=len(placements),
        placements_drawn=placements_drawn,
        models_drawn=len(model_ids_drawn),
        triangles_considered=triangles_considered,
        triangles_drawn=triangles_drawn,
        pixels_drawn=pixels_drawn,
        missing_texture_keys=tuple(sorted(missing)),
    )
