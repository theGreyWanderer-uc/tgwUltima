"""Render and export shared UU2 3D map scenes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np

from titan.uw2.scene3d import (
    ScenePart,
    UW2Scene,
    UW2SceneError,
    build_map_scene,
    iter_scene_parts,
)


VIEWS = frozenset({"iso-ne", "iso-nw", "iso-se", "iso-sw", "top"})


def render_map_scene(
    source: str | Path,
    output: str | Path,
    *,
    slot: int,
    region: tuple[int, int, int, int],
    views: Iterable[str] = ("iso-ne", "top"),
    size: int = 1200,
    include_ceilings: bool = False,
    include_sprites: bool = True,
    model_scale: float = 1.0,
    sprite_scale: float = 1.0,
    tick: int = 0,
) -> list[Path]:
    """Build one scene and render requested camera views as PNG."""
    try:
        import pyvista as pv
    except ImportError as error:
        raise UW2SceneError(
            "pyvista and vtk are required for UU2 3D map rendering"
        ) from error
    requested = tuple(views)
    invalid = sorted(set(requested) - VIEWS)
    if invalid:
        raise UW2SceneError(f"unknown 3D map views: {invalid}")
    if size < 128:
        raise UW2SceneError("render size must be at least 128 pixels")
    scene = build_map_scene(
        source,
        slot=slot,
        region=region,
        include_ceilings=include_ceilings,
        include_sprites=include_sprites,
        model_scale=model_scale,
        sprite_scale=sprite_scale,
        tick=tick,
    )
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    stem = _scene_stem(scene)
    written = []
    for view in requested:
        path = destination / f"{stem}_{view}.png"
        _render_view(pv, scene, path, view=view, size=size)
        written.append(path)
    _write_manifest(scene, destination / f"{stem}_manifest.json", glb=None)
    return written


def export_map_scene(
    source: str | Path,
    output: str | Path,
    *,
    slot: int,
    region: tuple[int, int, int, int],
    include_ceilings: bool = False,
    include_sprites: bool = True,
    model_scale: float = 1.0,
    sprite_scale: float = 1.0,
    tick: int = 0,
) -> Path:
    """Build one scene and export GLB plus logical-object manifest."""
    try:
        import trimesh
    except ImportError as error:
        raise UW2SceneError("trimesh is required for UU2 GLB map export") from error
    scene = build_map_scene(
        source,
        slot=slot,
        region=region,
        include_ceilings=include_ceilings,
        include_sprites=include_sprites,
        model_scale=model_scale,
        sprite_scale=sprite_scale,
        tick=tick,
    )
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    stem = _scene_stem(scene)
    glb_path = destination / f"{stem}.glb"
    exported = trimesh.Scene(base_frame="uw2_map")
    material_cache: dict[str, object] = {}
    used_names: dict[str, int] = {}
    for part, owner in iter_scene_parts(scene):
        material = scene.materials[part.material_key]
        tm_material = material_cache.get(material.key)
        if tm_material is None:
            kwargs = {
                "name": material.key,
                "baseColorFactor": list(material.color),
                "metallicFactor": 0.0,
                "roughnessFactor": 0.9,
                "doubleSided": True,
            }
            if material.image is not None:
                kwargs.update(
                    baseColorTexture=material.image, alphaMode="MASK", alphaCutoff=0.1
                )
            tm_material = trimesh.visual.material.PBRMaterial(**kwargs)
            material_cache[material.key] = tm_material
        mesh = _trimesh_part(trimesh, part, tm_material)
        node_name = _unique_name(part.name, used_names)
        mesh.metadata.update(
            {
                "uw2_kind": "architecture" if owner is None else owner.kind,
                "uw2_object": None if owner is None else owner.name,
            }
        )
        exported.add_geometry(mesh, geom_name=node_name, node_name=node_name)
    glb_path.write_bytes(exported.export(file_type="glb"))
    _write_manifest(scene, destination / f"{stem}_manifest.json", glb=glb_path.name)
    return glb_path


def _part_arrays(part: ScenePart) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    points: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    uv: list[tuple[float, float]] = []
    for triangle in part.triangles:
        start = len(points)
        points.extend(triangle.vertices)
        uv.extend(triangle.uvs)
        faces.append((start, start + 1, start + 2))
    return (
        np.asarray(points, dtype=np.float64),
        np.asarray(faces, dtype=np.int64),
        np.asarray(uv),
    )


def _trimesh_part(trimesh, part, material):
    points, faces, uv = _part_arrays(part)
    mesh = trimesh.Trimesh(vertices=points, faces=faces, process=False)
    mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, material=material)
    return mesh


def _render_view(
    pv, scene: UW2Scene, destination: Path, *, view: str, size: int
) -> None:
    plotter = pv.Plotter(off_screen=True, window_size=(size, size))
    plotter.set_background("#0c1118", top="#526171")
    texture_cache: dict[str, object] = {}
    for part, owner in iter_scene_parts(scene):
        if owner is not None and owner.kind == "sprite":
            part = _camera_billboard_part(part, owner.metadata, view)
        material = scene.materials[part.material_key]
        points, faces, uv = _part_arrays(part)
        packed_faces = np.column_stack((np.full(len(faces), 3), faces)).ravel()
        mesh = pv.PolyData(points, packed_faces)
        options = dict(
            smooth_shading=False,
            show_edges=False,
            ambient=0.35,
            diffuse=0.75,
            specular=0.05,
        )
        if material.image is not None:
            texture = texture_cache.get(material.key)
            if texture is None:
                texture = pv.Texture(np.asarray(material.image.convert("RGBA")))
                texture.flip_y()
                texture.interpolate = not material.nearest
                texture_cache[material.key] = texture
            mesh.active_texture_coordinates = uv
            plotter.add_mesh(mesh, texture=texture, **options)
        else:
            plotter.add_mesh(
                mesh,
                color=material.color[:3],
                opacity=material.color[3] / 255.0,
                **options,
            )
    plotter.enable_lightkit()
    plotter.enable_anti_aliasing("ssaa")
    bounds = _scene_bounds(scene)
    center = (
        (bounds[0] + bounds[1]) / 2.0,
        (bounds[2] + bounds[3]) / 2.0,
        (bounds[4] + bounds[5]) / 2.0,
    )
    horizontal = max(bounds[1] - bounds[0], bounds[3] - bounds[2], 1.0)
    vertical = max(bounds[5] - bounds[4], 1.0)
    distance = max(horizontal, vertical) * 1.8
    offsets: dict[str, tuple[float, float, float]] = {
        "iso-ne": (1.0, 1.0, 0.8),
        "iso-nw": (-1.0, 1.0, 0.8),
        "iso-se": (1.0, -1.0, 0.8),
        "iso-sw": (-1.0, -1.0, 0.8),
        "top": (0.0, -0.001, 1.8),
    }
    offset = offsets[view]
    plotter.camera_position = [
        tuple(center[axis] + offset[axis] * distance for axis in range(3)),
        center,
        (0.0, 1.0, 0.0) if view == "top" else (0.0, 0.0, 1.0),
    ]
    plotter.reset_camera()
    plotter.camera.zoom(1.15)
    plotter.screenshot(destination)
    plotter.close()


def _camera_billboard_part(
    part: ScenePart, metadata: dict[str, object], view: str
) -> ScenePart:
    """Replace crossed export planes with one camera-facing render quad."""
    center = np.asarray(
        (
            _metadata_float(metadata, "center_x"),
            _metadata_float(metadata, "center_y"),
            _metadata_float(metadata, "base_z")
            + _metadata_float(metadata, "height") / 2.0,
        ),
        dtype=np.float64,
    )
    camera = np.asarray(
        {
            "iso-ne": (1.0, 1.0, 0.8),
            "iso-nw": (-1.0, 1.0, 0.8),
            "iso-se": (1.0, -1.0, 0.8),
            "iso-sw": (-1.0, -1.0, 0.8),
            "top": (0.0, -0.001, 1.8),
        }[view],
        dtype=np.float64,
    )
    forward = camera / np.linalg.norm(camera)
    screen_up = (
        np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
        if view == "top"
        else np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    )
    right = np.cross(screen_up, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    up /= np.linalg.norm(up)
    half_width = _metadata_float(metadata, "width") / 2.0
    half_height = _metadata_float(metadata, "height") / 2.0
    a = _vector_tuple(center - right * half_width - up * half_height)
    b = _vector_tuple(center + right * half_width - up * half_height)
    c = _vector_tuple(center + right * half_width + up * half_height)
    d = _vector_tuple(center - right * half_width + up * half_height)
    from titan.uw2.scene3d import SceneTriangle

    return ScenePart(
        name=part.name,
        material_key=part.material_key,
        triangles=[
            SceneTriangle((a, b, c), ((0, 1), (1, 1), (1, 0))),
            SceneTriangle((a, c, d), ((0, 1), (1, 0), (0, 0))),
        ],
    )


def _metadata_float(metadata: dict[str, object], key: str) -> float:
    value = metadata[key]
    if not isinstance(value, (int, float)):
        raise UW2SceneError(f"scene metadata {key} must be numeric")
    return float(value)


def _vector_tuple(vector: np.ndarray) -> tuple[float, float, float]:
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _scene_bounds(scene: UW2Scene) -> tuple[float, float, float, float, float, float]:
    vertices = [
        vertex
        for part, _owner in iter_scene_parts(scene)
        for triangle in part.triangles
        for vertex in triangle.vertices
    ]
    if not vertices:
        raise UW2SceneError("scene contains no triangles")
    return (
        min(vertex[0] for vertex in vertices),
        max(vertex[0] for vertex in vertices),
        min(vertex[1] for vertex in vertices),
        max(vertex[1] for vertex in vertices),
        min(vertex[2] for vertex in vertices),
        max(vertex[2] for vertex in vertices),
    )


def _scene_stem(scene: UW2Scene) -> str:
    x1, y1, x2, y2 = scene.region
    return f"uw2_slot_{scene.slot:03d}_x{x1}-{x2}_y{y1}-{y2}_3d"


def _unique_name(name: str, used: dict[str, int]) -> str:
    count = used.get(name, 0)
    used[name] = count + 1
    return name if count == 0 else f"{name}_{count + 1}"


def _write_manifest(scene: UW2Scene, destination: Path, *, glb: str | None) -> None:
    data = {
        "slot": scene.slot,
        "level_name": scene.level_name,
        "region": list(scene.region),
        "glb": glb,
        "architecture_parts": len(scene.architecture),
        "logical_object_count": len(scene.objects),
        "triangle_count": scene.triangle_count,
        "skipped": scene.skipped,
        "objects": [
            {
                "name": obj.name,
                "kind": obj.kind,
                "parts": [part.name for part in obj.parts],
                **obj.metadata,
            }
            for obj in scene.objects
        ],
    }
    destination.write_text(json.dumps(data, indent=2), encoding="utf-8")
