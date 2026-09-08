"""Export an Ultima IX terrain region and placed models as textured GLB.

The exporter consumes :class:`titan.u9.region_scene.U9RegionScene`, so terrain
and object coordinates use the same validated native units as the 2D map.
GLB uses Y-up axes; native ``(x, y, z)`` becomes ``(x, z, -y)`` after a local
crop origin and the established 1/40 model-export scale are applied.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_U9_GLB_SCALE",
    "U9CellRegion",
    "U9GlbExportDiagnostics",
    "U9GlbExportError",
    "U9GlbObjectRecord",
    "U9RegionGlbResult",
    "export_region_glb",
]

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
from PIL import Image

from titan.u9.map_render import (
    U9_WATER_TEXTURE_ID,
    U9MapRenderError,
    U9MapTextureSource,
)
from titan.u9.mesh_export import U9ModelMeshTriangle, flatten_model_triangles
from titan.u9.model import MATERIAL_ALPHA_NONE, U9Material
from titan.u9.object_placement import (
    U9ModelProvider,
    U9ObjectFootprintFilter,
    U9ObjectPlacementResolution,
    resolve_region_object_placements,
)
from titan.u9.region_scene import TERRAIN_POINT_WORLD_XY, U9RegionScene
from titan.u9.transform import mat4_trs
from titan.u9.types_dat import U9TypesDat

DEFAULT_U9_GLB_SCALE = 1.0 / 40.0
"""GLB units per native U9 unit, matching Titan's standalone model exports."""


class U9GlbExportError(Exception):
    """Raised when a U9 region cannot be represented as the requested GLB."""


@dataclass(frozen=True)
class U9CellRegion:
    """Half-open terrain-cell rectangle ``x0,y0,x1,y1`` for a GLB export."""

    x0: int
    y0: int
    x1: int
    y1: int

    @classmethod
    def parse(cls, value: str) -> U9CellRegion:
        """Parse a comma-separated half-open terrain-cell rectangle."""
        try:
            values = tuple(int(part.strip(), 0) for part in value.split(","))
        except ValueError as error:
            raise U9GlbExportError(
                "cell region must be four integers: x0,y0,x1,y1"
            ) from error
        if len(values) != 4:
            raise U9GlbExportError("cell region must be four integers: x0,y0,x1,y1")
        return cls(*values)

    @classmethod
    def full_scene(cls, scene: U9RegionScene) -> U9CellRegion:
        """Return the complete terrain extent as a cell rectangle."""
        return cls(0, 0, scene.terrain.width, scene.terrain.height)

    def validate(self, scene: U9RegionScene) -> None:
        """Reject empty or out-of-bounds cell rectangles."""
        if not (0 <= self.x0 < self.x1 <= scene.terrain.width):
            raise U9GlbExportError(
                f"cell region X must satisfy 0 <= x0 < x1 <= {scene.terrain.width}"
            )
        if not (0 <= self.y0 < self.y1 <= scene.terrain.height):
            raise U9GlbExportError(
                f"cell region Y must satisfy 0 <= y0 < y1 <= {scene.terrain.height}"
            )

    @property
    def width(self) -> int:
        """Rectangle width in terrain cells."""
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        """Rectangle height in terrain cells."""
        return self.y1 - self.y0

    def contains_anchor(self, placement: U9ObjectPlacementResolution) -> bool:
        """Whether a placement anchor lies inside this half-open rectangle."""
        return (
            self.x0 * TERRAIN_POINT_WORLD_XY
            <= placement.position.x
            < self.x1 * TERRAIN_POINT_WORLD_XY
            and self.y0 * TERRAIN_POINT_WORLD_XY
            <= placement.position.y
            < self.y1 * TERRAIN_POINT_WORLD_XY
        )


@dataclass(frozen=True)
class U9GlbObjectRecord:
    """Manifest entry for one exported fixed or nonfixed object placement."""

    source_kind: str
    source_offset: int
    type_index: int
    model_id: int
    position_xyz: tuple[int, int, int]
    scale_xyz: tuple[float, float, float]
    is_spatially_indexed: bool
    node_names: tuple[str, ...]


@dataclass(frozen=True)
class U9GlbExportDiagnostics:
    """Machine-readable geometry, material, and selection coverage."""

    terrain_name: str
    cell_region: tuple[int, int, int, int]
    coordinate_scale: float
    terrain_enabled: bool
    terrain_cells_considered: int
    terrain_cells_exported: int
    terrain_holes_skipped: int
    terrain_triangles: int
    terrain_materials: int
    water_enabled: bool
    water_level: int
    water_triangles: int
    objects_enabled: bool
    object_footprints_resolved_total: int
    object_placements_matching_filter: int
    object_placements_in_region: int
    object_placements_exported: int
    object_parts_exported: int
    object_meshes_exported: int
    object_triangles: int
    objects_without_visible_geometry: int
    object_model_ids_exported: tuple[int, ...]
    object_model_ids_without_visible_geometry: tuple[int, ...]
    fixed_objects_resolved: int
    fixed_objects_without_model: int
    fixed_objects_unresolved: int
    nonfixed_objects_resolved: int
    nonfixed_objects_unresolved: int
    missing_object_model_ids: tuple[int, ...]
    malformed_object_model_ids: tuple[int, ...]
    missing_texture_keys: tuple[str, ...]
    geometry_nodes: int
    geometry_meshes: int

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready GLB diagnostics."""
        return asdict(self)


@dataclass(frozen=True)
class U9RegionGlbResult:
    """Written GLB path plus diagnostics and per-object manifest records."""

    glb_path: Path
    diagnostics: U9GlbExportDiagnostics
    objects: tuple[U9GlbObjectRecord, ...]

    def manifest(self) -> dict[str, object]:
        """Return a JSON-ready manifest including every named object node."""
        return {
            "glb": self.glb_path.name,
            "diagnostics": self.diagnostics.to_dict(),
            "objects": [asdict(item) for item in self.objects],
        }


@dataclass
class _MeshBuffers:
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)

    def add_triangle(
        self,
        positions: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ],
        uvs: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
        normals: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
        | None = None,
    ) -> None:
        base = len(self.positions)
        self.positions.extend(positions)
        self.uvs.extend(uvs)
        self.faces.append((base, base + 1, base + 2))
        if normals is not None:
            self.normals.extend(normals)


def _glb_position(
    point: tuple[float, float, float], region: U9CellRegion, scale: float
) -> tuple[float, float, float]:
    origin_x = region.x0 * TERRAIN_POINT_WORLD_XY
    far_y = region.y1 * TERRAIN_POINT_WORLD_XY
    return (
        (point[0] - origin_x) * scale,
        point[2] * scale,
        (far_y - point[1]) * scale,
    )


def _oriented_texture_image(
    textures: U9MapTextureSource,
    texture_id: int,
    frame: int,
    quarter_turns: int,
) -> Image.Image:
    image = textures.frame_image(texture_id, frame)
    transforms = (
        None,
        Image.Transpose.ROTATE_90,
        Image.Transpose.ROTATE_180,
        Image.Transpose.ROTATE_270,
    )
    transform = transforms[quarter_turns & 3]
    return image if transform is None else image.transpose(transform)


def _missing_texture_image() -> Image.Image:
    return Image.new("RGBA", (2, 2), (255, 0, 255, 255))


def _image_has_alpha(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    alpha_extrema = cast(tuple[float, float], rgba.getchannel("A").getextrema())
    return alpha_extrema[0] < 255


def _pbr_material(
    trimesh: Any,
    *,
    name: str,
    image: Image.Image | None,
    alpha: int = 255,
    chromakey: bool = False,
    additive: bool = False,
) -> Any:
    alpha_mode = "OPAQUE"
    if alpha < 255 or additive:
        alpha_mode = "BLEND"
    elif chromakey or (image is not None and _image_has_alpha(image)):
        alpha_mode = "MASK"
    kwargs: dict[str, object] = {
        "name": name,
        "baseColorFactor": [255, 255, 255, alpha],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.9,
        "doubleSided": True,
        "alphaMode": alpha_mode,
    }
    if alpha_mode == "MASK":
        kwargs["alphaCutoff"] = 0.1
    if image is not None:
        kwargs["baseColorTexture"] = image.convert("RGBA")
    if additive:
        # Core glTF has no additive blend mode; emissive colour preserves the
        # intent without claiming exact U9 renderer compositing.
        kwargs["emissiveFactor"] = [1.0, 1.0, 1.0]
    return trimesh.visual.material.PBRMaterial(**kwargs)


def _trimesh_geometry(trimesh: Any, buffers: _MeshBuffers, material: object) -> Any:
    mesh = trimesh.Trimesh(
        vertices=np.asarray(buffers.positions, dtype=np.float32),
        faces=np.asarray(buffers.faces, dtype=np.int64),
        process=False,
        validate=False,
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=np.asarray(buffers.uvs, dtype=np.float32), material=material
    )
    if buffers.normals:
        mesh.vertex_normals = np.asarray(buffers.normals, dtype=np.float32)
    return mesh


def _unique_node_name(name: str, used: dict[str, int]) -> str:
    count = used.get(name, 0)
    used[name] = count + 1
    return name if count == 0 else f"{name}_{count + 1}"


def _add_terrain_geometry(
    trimesh: Any,
    exported: Any,
    scene: U9RegionScene,
    textures: U9MapTextureSource,
    region: U9CellRegion,
    scale: float,
    missing_textures: set[str],
    used_names: dict[str, int],
) -> tuple[int, int, int, int]:
    groups: dict[tuple[int, int, int], _MeshBuffers] = defaultdict(_MeshBuffers)
    holes = 0
    exported_cells = 0
    for y in range(region.y0, region.y1):
        for x in range(region.x0, region.x1):
            cell = scene.terrain_cell(x, y)
            if cell.point.is_hole:
                holes += 1
                continue
            key = (
                cell.point.texture,
                cell.point.frame,
                cell.point.uv_rotation_quarter_turns,
            )
            buffer = groups[key]
            positions = tuple(
                _glb_position(
                    (float(corner.x), float(corner.y), float(corner.z)),
                    region,
                    scale,
                )
                for corner in cell.corners
            )
            uvs = ((0.0, 1.0), (1.0, 1.0), (0.0, 0.0), (1.0, 0.0))
            for a, b, c in cell.triangle_corner_indices:
                buffer.add_triangle(
                    (positions[a], positions[b], positions[c]),
                    (uvs[a], uvs[b], uvs[c]),
                )
            exported_cells += 1

    triangle_count = 0
    for texture_id, frame, rotation in sorted(groups):
        texture_key = f"{texture_id}:{frame}:{rotation}"
        try:
            image = _oriented_texture_image(textures, texture_id, frame, rotation)
        except U9MapRenderError:
            image = _missing_texture_image()
            missing_textures.add(f"terrain:{texture_key}")
        material = _pbr_material(
            trimesh,
            name=f"terrain_tex_{texture_id}_f{frame}_r{rotation}",
            image=image,
        )
        buffer = groups[(texture_id, frame, rotation)]
        node_name = _unique_node_name(
            f"terrain_tex_{texture_id}_f{frame}_r{rotation}", used_names
        )
        mesh = _trimesh_geometry(trimesh, buffer, material)
        mesh.metadata["u9_kind"] = "terrain"
        exported.add_geometry(mesh, geom_name=node_name, node_name=node_name)
        triangle_count += len(buffer.faces)
    return exported_cells, holes, triangle_count, len(groups)


def _add_water_geometry(
    trimesh: Any,
    exported: Any,
    scene: U9RegionScene,
    textures: U9MapTextureSource,
    region: U9CellRegion,
    scale: float,
    water_frame: int,
    missing_textures: set[str],
    used_names: dict[str, int],
) -> int:
    x0 = region.x0 * TERRAIN_POINT_WORLD_XY
    x1 = region.x1 * TERRAIN_POINT_WORLD_XY
    y0 = region.y0 * TERRAIN_POINT_WORLD_XY
    y1 = region.y1 * TERRAIN_POINT_WORLD_XY
    height = float(scene.terrain.water_level)
    positions = tuple(
        _glb_position(point, region, scale)
        for point in (
            (float(x0), float(y0), height),
            (float(x1), float(y0), height),
            (float(x0), float(y1), height),
            (float(x1), float(y1), height),
        )
    )
    uvs = (
        (0.0, float(region.height)),
        (float(region.width), float(region.height)),
        (0.0, 0.0),
        (float(region.width), 0.0),
    )
    buffer = _MeshBuffers()
    buffer.add_triangle(
        (positions[0], positions[1], positions[2]), (uvs[0], uvs[1], uvs[2])
    )
    buffer.add_triangle(
        (positions[2], positions[1], positions[3]), (uvs[2], uvs[1], uvs[3])
    )
    try:
        image = textures.frame_image(U9_WATER_TEXTURE_ID, water_frame)
    except U9MapRenderError:
        image = _missing_texture_image()
        missing_textures.add(f"water:{U9_WATER_TEXTURE_ID}:{water_frame}")
    material = _pbr_material(
        trimesh,
        name=f"water_tex_{U9_WATER_TEXTURE_ID}_f{water_frame}",
        image=image,
        chromakey=True,
    )
    node_name = _unique_node_name("water_surface", used_names)
    mesh = _trimesh_geometry(trimesh, buffer, material)
    mesh.metadata["u9_kind"] = "water"
    exported.add_geometry(mesh, geom_name=node_name, node_name=node_name)
    return 2


def _material_alpha(material: U9Material | None) -> int:
    if material is None:
        return 255
    if material.modified_alpha != MATERIAL_ALPHA_NONE:
        return material.modified_alpha
    return material.default_alpha


def _object_material_key(material: U9Material | None) -> tuple[object, ...]:
    if material is None:
        return ("untextured",)
    return (
        material.texture_id,
        material.cur_frame,
        material.render_flags,
        _material_alpha(material),
    )


def _object_material(
    trimesh: Any,
    textures: U9MapTextureSource,
    material: U9Material | None,
    cache: dict[tuple[object, ...], object],
    missing_textures: set[str],
) -> object:
    key = _object_material_key(material)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if material is None:
        result = _pbr_material(trimesh, name="object_untextured", image=None, alpha=255)
    else:
        try:
            image = textures.frame_image(material.texture_id, material.cur_frame)
        except U9MapRenderError:
            image = _missing_texture_image()
            missing_textures.add(f"object:{material.texture_id}:{material.cur_frame}")
        result = _pbr_material(
            trimesh,
            name=(
                f"object_tex_{material.texture_id}_f{material.cur_frame}_"
                f"flags{material.render_flags:04x}"
            ),
            image=image,
            alpha=_material_alpha(material),
            chromakey=material.is_chromakey,
            additive=material.is_additive,
        )
    cache[key] = result
    return result


def _object_buffers(
    triangles: tuple[U9ModelMeshTriangle, ...],
) -> dict[tuple[object, ...], tuple[U9Material | None, _MeshBuffers]]:
    groups: dict[tuple[object, ...], tuple[U9Material | None, _MeshBuffers]] = {}
    for triangle in triangles:
        material = triangle[0].material
        first, second, third = triangle
        positions = tuple(corner.position for corner in (first, second, third))
        normals = tuple(corner.normal for corner in (first, second, third))
        uvs = tuple(
            (corner.uv[0], 1.0 - corner.uv[1]) for corner in (first, second, third)
        )
        material_key = _object_material_key(material)
        group = groups.get(material_key)
        if group is None:
            group = (material, _MeshBuffers())
            groups[material_key] = group
        group[1].add_triangle(
            (positions[0], positions[1], positions[2]),
            (uvs[0], uvs[1], uvs[2]),
            (normals[0], normals[1], normals[2]),
        )
    return groups


def _object_node_transform(
    placement: U9ObjectPlacementResolution,
    region: U9CellRegion,
    scale: float,
) -> np.ndarray:
    """Compose native placement TRS with the crop-local Y-up conversion."""
    origin_x = region.x0 * TERRAIN_POINT_WORLD_XY
    far_y = region.y1 * TERRAIN_POINT_WORLD_XY
    native_to_glb = np.asarray(
        (
            (scale, 0.0, 0.0, -origin_x * scale),
            (0.0, 0.0, scale, 0.0),
            (0.0, -scale, 0.0, far_y * scale),
            (0.0, 0.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    )
    placement_matrix = np.asarray(
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
    return native_to_glb @ placement_matrix


def _add_object_geometry(
    trimesh: Any,
    exported: Any,
    textures: U9MapTextureSource,
    models: U9ModelProvider,
    placements: tuple[U9ObjectPlacementResolution, ...],
    region: U9CellRegion,
    scale: float,
    lod_level: int,
    missing_textures: set[str],
    used_names: dict[str, int],
) -> tuple[tuple[U9GlbObjectRecord, ...], int, int, int, int, tuple[int, ...]]:
    model_group_cache: dict[
        int,
        tuple[tuple[tuple[object, ...], U9Material | None, _MeshBuffers], ...],
    ] = {}
    geometry_cache: dict[tuple[object, ...], str] = {}
    material_cache: dict[tuple[object, ...], object] = {}
    records: list[U9GlbObjectRecord] = []
    no_geometry = 0
    no_geometry_ids: set[int] = set()
    part_count = 0
    triangle_count = 0
    for placement in placements:
        if placement.model_id is None:
            continue
        groups = model_group_cache.get(placement.model_id)
        if groups is None:
            lookup = models.model(placement.model_id)
            triangles = (
                flatten_model_triangles(lookup.model, lod_level)
                if lookup.model is not None
                else ()
            )
            buffers = _object_buffers(triangles)
            groups = tuple(
                (material_key, material, buffer)
                for material_key, (material, buffer) in buffers.items()
            )
            model_group_cache[placement.model_id] = groups
        if not groups:
            no_geometry += 1
            no_geometry_ids.add(placement.model_id)
            continue
        node_names: list[str] = []
        node_transform = _object_node_transform(placement, region, scale)
        for part_index, (material_key, material, buffer) in enumerate(groups):
            texture_id = material.texture_id if material is not None else 0xFFFF
            node_name = _unique_node_name(
                f"{placement.source_kind}_off_{placement.source_offset:08x}_"
                f"type_{placement.type_index}_model_{placement.model_id}_"
                f"part_{part_index}_tex_{texture_id}",
                used_names,
            )
            geometry_key = (placement.model_id, lod_level, material_key)
            geometry_name = geometry_cache.get(geometry_key)
            if geometry_name is None:
                geometry_name = (
                    f"object_model_{placement.model_id}_lod_{lod_level}_"
                    f"part_{part_index}_tex_{texture_id}"
                )
                glb_material = _object_material(
                    trimesh, textures, material, material_cache, missing_textures
                )
                mesh = _trimesh_geometry(trimesh, buffer, glb_material)
                mesh.metadata.update(
                    {
                        "u9_kind": "object_mesh",
                        "u9_model_id": placement.model_id,
                        "u9_lod": lod_level,
                    }
                )
                exported.geometry[geometry_name] = mesh
                geometry_cache[geometry_key] = geometry_name
            exported.graph.update(
                frame_to=node_name,
                frame_from=exported.graph.base_frame,
                matrix=node_transform,
                geometry=geometry_name,
                geometry_flags={"visible": True},
                metadata={
                    "u9_kind": placement.source_kind,
                    "u9_source_offset": placement.source_offset,
                    "u9_type_index": placement.type_index,
                    "u9_model_id": placement.model_id,
                },
            )
            node_names.append(node_name)
            part_count += 1
            triangle_count += len(buffer.faces)
        records.append(
            U9GlbObjectRecord(
                source_kind=placement.source_kind,
                source_offset=placement.source_offset,
                type_index=placement.type_index,
                model_id=placement.model_id,
                position_xyz=(
                    placement.position.x,
                    placement.position.y,
                    placement.position.z,
                ),
                scale_xyz=placement.scale_xyz,
                is_spatially_indexed=placement.is_spatially_indexed,
                node_names=tuple(node_names),
            )
        )
    return (
        tuple(records),
        no_geometry,
        part_count,
        len(geometry_cache),
        triangle_count,
        tuple(sorted(no_geometry_ids)),
    )


def export_region_glb(
    scene: U9RegionScene,
    textures: U9MapTextureSource,
    output_path: str | Path,
    *,
    cell_region: U9CellRegion | None = None,
    include_terrain: bool = True,
    include_water: bool = True,
    water_frame: int = 0,
    include_objects: bool = True,
    object_models: U9ModelProvider | None = None,
    object_types: U9TypesDat | None = None,
    object_filter: U9ObjectFootprintFilter | None = None,
    include_unlinked_nonfixed: bool = False,
    lod_level: int = 0,
    coordinate_scale: float = DEFAULT_U9_GLB_SCALE,
) -> U9RegionGlbResult:
    """Write a textured Y-up GLB for one half-open terrain-cell rectangle."""
    try:
        import trimesh
    except ImportError as error:
        raise U9GlbExportError("trimesh is required for U9 GLB export") from error
    if coordinate_scale <= 0:
        raise U9GlbExportError("coordinate scale must be positive")
    if lod_level < 0:
        raise U9GlbExportError("LOD level cannot be negative")
    if water_frame < 0:
        raise U9GlbExportError("water frame cannot be negative")
    region = cell_region or U9CellRegion.full_scene(scene)
    region.validate(scene)
    has_object_input = scene.fixed is not None or scene.nonfixed is not None
    if include_objects and has_object_input and object_models is None:
        raise U9GlbExportError(
            "object export requires a sappear.flx full-model provider"
        )
    if (
        not include_terrain
        and not include_water
        and not (include_objects and has_object_input)
    ):
        raise U9GlbExportError("GLB export has no enabled geometry layer")

    exported = trimesh.Scene(base_frame="u9_region")
    used_names: dict[str, int] = {}
    missing_textures: set[str] = set()
    terrain_cells = 0
    holes = 0
    terrain_triangles = 0
    terrain_materials = 0
    if include_terrain:
        terrain_cells, holes, terrain_triangles, terrain_materials = (
            _add_terrain_geometry(
                trimesh,
                exported,
                scene,
                textures,
                region,
                coordinate_scale,
                missing_textures,
                used_names,
            )
        )

    water_triangles = 0
    if include_water:
        water_triangles = _add_water_geometry(
            trimesh,
            exported,
            scene,
            textures,
            region,
            coordinate_scale,
            water_frame,
            missing_textures,
            used_names,
        )

    resolved_total = 0
    matching_filter = 0
    in_region: tuple[U9ObjectPlacementResolution, ...] = ()
    object_records: tuple[U9GlbObjectRecord, ...] = ()
    no_geometry = 0
    object_parts = 0
    object_meshes = 0
    object_triangles = 0
    no_geometry_ids: tuple[int, ...] = ()
    resolution_diagnostics = None
    if include_objects and has_object_input and object_models is not None:
        resolutions = resolve_region_object_placements(
            scene,
            object_models,
            types=object_types,
            include_unlinked_nonfixed=include_unlinked_nonfixed,
        )
        resolution_diagnostics = resolutions.diagnostics
        resolved_total = len(resolutions.footprints)
        selected = (object_filter or U9ObjectFootprintFilter()).select(resolutions)
        matching_filter = len(selected)
        in_region = tuple(item for item in selected if region.contains_anchor(item))
        (
            object_records,
            no_geometry,
            object_parts,
            object_meshes,
            object_triangles,
            no_geometry_ids,
        ) = _add_object_geometry(
            trimesh,
            exported,
            textures,
            object_models,
            in_region,
            region,
            coordinate_scale,
            lod_level,
            missing_textures,
            used_names,
        )

    if not exported.geometry:
        raise U9GlbExportError("GLB export produced no geometry")
    destination = Path(output_path)
    if destination.suffix.casefold() != ".glb":
        raise U9GlbExportError("output path must end in .glb")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = exported.export(file_type="glb")
    except Exception as error:  # noqa: BLE001 - trimesh exporter failures vary
        raise U9GlbExportError(f"trimesh GLB export failed: {error}") from error
    if not isinstance(payload, bytes):
        raise U9GlbExportError("trimesh GLB export did not return binary data")
    destination.write_bytes(payload)

    diagnostics = U9GlbExportDiagnostics(
        terrain_name=scene.terrain.name,
        cell_region=(region.x0, region.y0, region.x1, region.y1),
        coordinate_scale=coordinate_scale,
        terrain_enabled=include_terrain,
        terrain_cells_considered=region.width * region.height,
        terrain_cells_exported=terrain_cells,
        terrain_holes_skipped=holes,
        terrain_triangles=terrain_triangles,
        terrain_materials=terrain_materials,
        water_enabled=include_water,
        water_level=scene.terrain.water_level,
        water_triangles=water_triangles,
        objects_enabled=include_objects and has_object_input,
        object_footprints_resolved_total=resolved_total,
        object_placements_matching_filter=matching_filter,
        object_placements_in_region=len(in_region),
        object_placements_exported=len(object_records),
        object_parts_exported=object_parts,
        object_meshes_exported=object_meshes,
        object_triangles=object_triangles,
        objects_without_visible_geometry=no_geometry,
        object_model_ids_exported=tuple(
            sorted({item.model_id for item in object_records})
        ),
        object_model_ids_without_visible_geometry=no_geometry_ids,
        fixed_objects_resolved=(
            resolution_diagnostics.fixed_resolved if resolution_diagnostics else 0
        ),
        fixed_objects_without_model=(
            resolution_diagnostics.fixed_without_model if resolution_diagnostics else 0
        ),
        fixed_objects_unresolved=(
            resolution_diagnostics.fixed_unresolved if resolution_diagnostics else 0
        ),
        nonfixed_objects_resolved=(
            resolution_diagnostics.nonfixed_resolved if resolution_diagnostics else 0
        ),
        nonfixed_objects_unresolved=(
            resolution_diagnostics.nonfixed_unresolved if resolution_diagnostics else 0
        ),
        missing_object_model_ids=(
            resolution_diagnostics.missing_model_ids if resolution_diagnostics else ()
        ),
        malformed_object_model_ids=(
            resolution_diagnostics.malformed_model_ids if resolution_diagnostics else ()
        ),
        missing_texture_keys=tuple(sorted(missing_textures)),
        geometry_nodes=len(exported.graph.nodes_geometry),
        geometry_meshes=len(exported.geometry),
    )
    return U9RegionGlbResult(destination, diagnostics, object_records)
