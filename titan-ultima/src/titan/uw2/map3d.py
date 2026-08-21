"""Render and export shared UU2 3D map scenes."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

from titan.uw2.map_pipeline import MAP_SLOT_COUNT, load_levels, load_render_assets
from titan.uw2.render_common import slugify
from titan.uw2.scene3d import (
    CEILING_SOURCES,
    DEFAULT_Z_SCALE,
    SceneObject,
    ScenePart,
    SceneTriangle,
    UW2Scene,
    UW2SceneError,
    build_level_scene,
    build_map_scene,
    iter_scene_parts,
)


VIEW_OFFSETS: dict[str, tuple[float, float, float]] = {
    "iso-ne": (1.0, 1.0, 0.8),
    "iso-nw": (-1.0, 1.0, 0.8),
    "iso-se": (1.0, -1.0, 0.8),
    "iso-sw": (-1.0, -1.0, 0.8),
    "top": (0.0, -0.001, 1.8),
    # Low-angle eye-level views: same bearings, camera dropped towards the
    # floor so wall faces and ceiling clearance read instead of the plan.
    "low-ne": (1.0, 1.0, 0.28),
    "low-nw": (-1.0, 1.0, 0.28),
}

VIEWS = frozenset(VIEW_OFFSETS)

TEXTURE_FILTERS = ("linear", "nearest")

DOWNSAMPLE_FILTERS = {
    "lanczos": Image.Resampling.LANCZOS,
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
}

BACKENDS = ("pyvista", "software", "auto")

DEFAULT_ZOOM = 1.15
"""Framing the existing camera presets were tuned against."""

BACKGROUND_RGBA = (12, 17, 24, 255)


def render_map_scene(
    source: str | Path,
    output: str | Path,
    *,
    slot: int,
    region: tuple[int, int, int, int],
    views: Iterable[str] = ("iso-ne", "top"),
    size: int = 1200,
    width: int | None = None,
    height: int | None = None,
    include_ceilings: bool = False,
    include_sprites: bool = True,
    model_scale: float = 1.0,
    sprite_scale: float = 1.0,
    tick: int = 0,
    ceiling_source: str = "runtime",
    z_scale: float = DEFAULT_Z_SCALE,
    zoom: float = DEFAULT_ZOOM,
    fit_margin: float = 1.0,
    supersample: int = 1,
    downsample_filter: str = "lanczos",
    texture_filter: str = "linear",
    texture_scale: int = 1,
    backend: str = "auto",
    name_files: bool = False,
) -> list[Path]:
    """Build one scene and render requested camera views as PNG."""
    options = _validate_render_options(
        views=views,
        size=size,
        width=width,
        height=height,
        ceiling_source=ceiling_source,
        zoom=zoom,
        fit_margin=fit_margin,
        supersample=supersample,
        downsample_filter=downsample_filter,
        texture_filter=texture_filter,
        texture_scale=texture_scale,
        backend=backend,
    )
    scene = build_map_scene(
        source,
        slot=slot,
        region=region,
        include_ceilings=include_ceilings,
        include_sprites=include_sprites,
        model_scale=model_scale,
        sprite_scale=sprite_scale,
        tick=tick,
        ceiling_source=ceiling_source,
        z_scale=z_scale,
    )
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    stem = _scene_stem(scene, name_files=name_files)
    written = render_scene_views(scene, destination, stem=stem, **options)
    _write_manifest(scene, destination / f"{stem}_manifest.json", glb=None)
    return written


def render_scene_views(
    scene: UW2Scene,
    destination: Path,
    *,
    stem: str,
    views: tuple[str, ...],
    width: int,
    height: int,
    zoom: float,
    fit_margin: float,
    supersample: int,
    downsample_filter: str,
    texture_filter: str,
    texture_scale: int,
    backend: str,
) -> list[Path]:
    """Render an already-built scene from each requested camera preset."""
    plotter_module = None
    if backend in ("pyvista", "auto"):
        try:
            import pyvista as pv

            plotter_module = pv
        except ImportError as error:
            if backend == "pyvista":
                raise UW2SceneError(
                    "pyvista and vtk are required for UU2 3D map rendering"
                ) from error
            # Falling back silently would hand back flat-shaded previews that
            # look like a rendering bug rather than a missing dependency.
            warnings.warn(
                "pyvista is not installed; rendering UU2 3D maps with the "
                "flat-shaded software fallback. Install pyvista and vtk for "
                "textured output, or pass backend='software' to silence this.",
                RuntimeWarning,
                stacklevel=2,
            )

    written: list[Path] = []
    for view in views:
        path = destination / f"{stem}_{view}.png"
        render_width = width * supersample
        render_height = height * supersample
        rendered: Image.Image | None = None
        if plotter_module is not None:
            try:
                rendered = _render_view(
                    plotter_module,
                    scene,
                    view=view,
                    width=render_width,
                    height=render_height,
                    zoom=zoom,
                    fit_margin=fit_margin,
                    texture_filter=texture_filter,
                    texture_scale=texture_scale,
                )
            except Exception as error:  # noqa: BLE001 - GPU/driver failures vary
                if backend == "pyvista":
                    raise UW2SceneError(f"pyvista render failed: {error}") from error
                path.with_suffix(".render_warning.txt").write_text(
                    f"pyvista failed for {view}; wrote software fallback.\n"
                    f"{type(error).__name__}: {error}\n",
                    encoding="utf-8",
                )
        if rendered is None:
            rendered = _render_software(
                scene,
                view=view,
                width=render_width,
                height=render_height,
                zoom=zoom,
                fit_margin=fit_margin,
            )
        if supersample > 1:
            rendered = rendered.resize(
                (width, height), DOWNSAMPLE_FILTERS[downsample_filter]
            )
        rendered.save(path)
        written.append(path)
    return written


def _validate_render_options(
    *,
    views: Iterable[str],
    size: int,
    width: int | None,
    height: int | None,
    ceiling_source: str,
    zoom: float,
    fit_margin: float,
    supersample: int,
    downsample_filter: str,
    texture_filter: str,
    texture_scale: int,
    backend: str,
) -> dict[str, object]:
    requested = tuple(views)
    invalid = sorted(set(requested) - VIEWS)
    if invalid:
        raise UW2SceneError(f"unknown 3D map views: {invalid}")
    if not requested:
        raise UW2SceneError("at least one 3D map view is required")
    effective_width = size if width is None else width
    effective_height = size if height is None else height
    if effective_width < 128 or effective_height < 128:
        raise UW2SceneError("render size must be at least 128 pixels")
    if ceiling_source not in CEILING_SOURCES:
        raise UW2SceneError(f"ceiling source must be one of {CEILING_SOURCES}")
    if zoom <= 0:
        raise UW2SceneError("zoom must be positive")
    if fit_margin <= 0:
        raise UW2SceneError("fit margin must be positive")
    if supersample < 1:
        raise UW2SceneError("supersample must be at least 1")
    if downsample_filter not in DOWNSAMPLE_FILTERS:
        raise UW2SceneError(
            f"downsample filter must be one of {tuple(DOWNSAMPLE_FILTERS)}"
        )
    if texture_filter not in TEXTURE_FILTERS:
        raise UW2SceneError(f"texture filter must be one of {TEXTURE_FILTERS}")
    if texture_scale < 1:
        raise UW2SceneError("texture scale must be at least 1")
    if backend not in BACKENDS:
        raise UW2SceneError(f"backend must be one of {BACKENDS}")
    return {
        "views": requested,
        "width": effective_width,
        "height": effective_height,
        "zoom": zoom,
        "fit_margin": fit_margin,
        "supersample": supersample,
        "downsample_filter": downsample_filter,
        "texture_filter": texture_filter,
        "texture_scale": texture_scale,
        "backend": backend,
    }


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
    ceiling_source: str = "runtime",
    z_scale: float = DEFAULT_Z_SCALE,
    name_files: bool = False,
) -> Path:
    """Build one scene and export GLB plus logical-object manifest."""
    try:
        import trimesh
    except ImportError as error:
        raise UW2SceneError("trimesh is required for UU2 GLB map export") from error
    if ceiling_source not in CEILING_SOURCES:
        raise UW2SceneError(f"ceiling source must be one of {CEILING_SOURCES}")
    scene = build_map_scene(
        source,
        slot=slot,
        region=region,
        include_ceilings=include_ceilings,
        include_sprites=include_sprites,
        model_scale=model_scale,
        sprite_scale=sprite_scale,
        tick=tick,
        ceiling_source=ceiling_source,
        z_scale=z_scale,
    )
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    stem = _scene_stem(scene, name_files=name_files)
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


def render_stacked_worlds(
    source: str | Path,
    output: str | Path,
    *,
    worlds: Iterable[str] | None = None,
    max_levels: int | None = None,
    views: Iterable[str] = ("iso-ne",),
    size: int = 2400,
    width: int | None = None,
    height: int | None = None,
    include_ceilings: bool = False,
    include_sprites: bool = False,
    stack_gap: float = 7.0,
    stagger_x: float = 0.0,
    stagger_y: float = 0.0,
    ceiling_source: str = "runtime",
    z_scale: float = DEFAULT_Z_SCALE,
    zoom: float = DEFAULT_ZOOM,
    fit_margin: float = 1.15,
    supersample: int = 1,
    downsample_filter: str = "lanczos",
    texture_filter: str = "nearest",
    texture_scale: int = 4,
    backend: str = "auto",
    tick: int = 0,
) -> list[Path]:
    """Render each world's levels as one vertically stacked cutaway.

    Levels descend in slot order, so the first available level of a world sits
    on top and each lower level is dropped by ``stack_gap``.
    """
    options = _validate_render_options(
        views=views,
        size=size,
        width=width,
        height=height,
        ceiling_source=ceiling_source,
        zoom=zoom,
        fit_margin=fit_margin,
        supersample=supersample,
        downsample_filter=downsample_filter,
        texture_filter=texture_filter,
        texture_scale=texture_scale,
        backend=backend,
    )
    if stack_gap <= 0:
        raise UW2SceneError("stack gap must be positive")

    levels = load_levels(source, range(MAP_SLOT_COUNT))
    if not levels:
        raise UW2SceneError("no populated UU2 map slots found")
    wanted = {slugify(value) for value in worlds or []}
    grouped: dict[str, list[dict]] = {}
    for level in sorted(levels, key=lambda item: int(item["slot_index"])):
        grouped.setdefault(level.get("world_name") or "Unknown", []).append(level)

    assets = load_render_assets(source)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for world_name, group in grouped.items():
        world_slug = slugify(world_name)
        if wanted and world_slug not in wanted:
            continue
        selected = group[:max_levels] if max_levels else group
        if not selected:
            continue

        scene = _stack_level_scenes(
            selected,
            assets,
            include_ceilings=include_ceilings,
            include_sprites=include_sprites,
            ceiling_source=ceiling_source,
            z_scale=z_scale,
            tick=tick,
            stack_gap=stack_gap,
            stagger_x=stagger_x,
            stagger_y=stagger_y,
        )
        first_slot = int(selected[0]["slot_index"])
        last_slot = int(selected[-1]["slot_index"])
        stem = f"stack_{world_slug}_{first_slot:03d}_{last_slot:03d}"
        written.extend(render_scene_views(scene, destination, stem=stem, **options))
    if not written:
        raise UW2SceneError(f"no UU2 worlds matched: {sorted(wanted)}")
    return written


def _stack_level_scenes(
    levels: list[dict],
    assets,
    *,
    include_ceilings: bool,
    include_sprites: bool,
    ceiling_source: str,
    z_scale: float,
    tick: int,
    stack_gap: float,
    stagger_x: float,
    stagger_y: float,
) -> UW2Scene:
    """Merge one scene per level into a single vertically offset scene."""
    combined = UW2Scene(
        slot=int(levels[0]["slot_index"]),
        level_name=levels[0].get("world_name"),
        region=(0, 0, 63, 63),
    )
    for depth, level in enumerate(levels):
        scene = build_level_scene(
            level,
            assets,
            include_ceilings=include_ceilings,
            include_sprites=include_sprites,
            ceiling_source=ceiling_source,
            z_scale=z_scale,
            tick=tick,
        )
        offset = (stagger_x * depth, stagger_y * depth, -stack_gap * depth)
        prefix = f"slot{int(level['slot_index']):03d}"
        for key, material in scene.materials.items():
            combined.materials.setdefault(key, material)
        for part in scene.architecture:
            combined.architecture.append(_offset_part(part, prefix, offset))
        for obj in scene.objects:
            combined.objects.append(
                SceneObject(
                    name=f"{prefix}_{obj.name}",
                    kind=obj.kind,
                    metadata=_offset_metadata(obj.metadata, offset),
                    parts=[_offset_part(part, prefix, offset) for part in obj.parts],
                )
            )
        for key, count in scene.skipped.items():
            combined.skipped[key] = combined.skipped.get(key, 0) + count
    return combined


def _offset_part(
    part: ScenePart, prefix: str, offset: tuple[float, float, float]
) -> ScenePart:
    dx, dy, dz = offset
    return ScenePart(
        name=f"{prefix}_{part.name}",
        material_key=part.material_key,
        triangles=[
            SceneTriangle(
                vertices=tuple(
                    (vertex[0] + dx, vertex[1] + dy, vertex[2] + dz)
                    for vertex in triangle.vertices
                ),
                uvs=triangle.uvs,
            )
            for triangle in part.triangles
        ],
    )


def _offset_metadata(
    metadata: dict[str, object], offset: tuple[float, float, float]
) -> dict[str, object]:
    """Keep billboard anchors aligned with their offset geometry."""
    moved = dict(metadata)
    for key, delta in (("center_x", offset[0]), ("center_y", offset[1])):
        if isinstance(moved.get(key), (int, float)):
            moved[key] = float(moved[key]) + delta
    if isinstance(moved.get("base_z"), (int, float)):
        moved["base_z"] = float(moved["base_z"]) + offset[2]
    return moved


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
    pv,
    scene: UW2Scene,
    *,
    view: str,
    width: int,
    height: int,
    zoom: float,
    fit_margin: float,
    texture_filter: str,
    texture_scale: int,
) -> Image.Image:
    plotter = pv.Plotter(off_screen=True, window_size=(width, height))
    plotter.set_background("#0c1118", top="#526171")
    texture_cache: dict[str, object] = {}
    nearest = texture_filter == "nearest"
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
                source = _scaled_texture_image(material.image, texture_scale)
                texture = pv.Texture(np.asarray(source))
                texture.flip_y()
                texture.interpolate = not (material.nearest or nearest)
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
    offset = VIEW_OFFSETS[view]
    plotter.camera_position = [
        tuple(center[axis] + offset[axis] * distance for axis in range(3)),
        center,
        _view_up(view),
    ]
    plotter.reset_camera()
    plotter.camera.zoom(zoom / fit_margin)
    array = plotter.screenshot(None, return_img=True)
    plotter.close()
    # Keep PyVista's native RGB so saved PNGs match the previous output format;
    # only the software fallback carries an alpha channel.
    return Image.fromarray(np.asarray(array))


def _render_software(
    scene: UW2Scene,
    *,
    view: str,
    width: int,
    height: int,
    zoom: float,
    fit_margin: float,
) -> Image.Image:
    """Painter's-algorithm preview using each material's average colour.

    No OpenGL, no depth buffer: triangles are sorted back to front along the
    camera axis. It exists so a headless machine still gets a usable image.
    """
    from PIL import ImageDraw

    forward, right, up = _camera_basis(view)
    bounds = _scene_bounds(scene)
    center = np.asarray(
        (
            (bounds[0] + bounds[1]) / 2.0,
            (bounds[2] + bounds[3]) / 2.0,
            (bounds[4] + bounds[5]) / 2.0,
        ),
        dtype=np.float64,
    )

    faces: list[tuple[float, np.ndarray, tuple[int, int, int, int]]] = []
    color_cache: dict[str, tuple[int, int, int, int]] = {}
    for part, owner in iter_scene_parts(scene):
        if owner is not None and owner.kind == "sprite":
            part = _camera_billboard_part(part, owner.metadata, view)
        material = scene.materials[part.material_key]
        color = color_cache.get(material.key)
        if color is None:
            color = _average_material_color(material)
            color_cache[material.key] = color
        for triangle in part.triangles:
            relative = np.asarray(triangle.vertices, dtype=np.float64) - center
            projected = np.column_stack(
                (relative @ right, relative @ up, relative @ forward)
            )
            faces.append((float(projected[:, 2].mean()), projected, color))

    image = Image.new("RGBA", (width, height), BACKGROUND_RGBA)
    everything = np.concatenate([projected for _d, projected, _c in faces])
    min_xy = everything[:, :2].min(axis=0)
    max_xy = everything[:, :2].max(axis=0)
    span = np.maximum(max_xy - min_xy, 1e-6)
    scale = min(width / (span[0] * fit_margin), height / (span[1] * fit_margin)) * zoom
    offset = (
        np.asarray((width, height), dtype=np.float64) / 2.0
        - ((min_xy + max_xy) / 2.0) * scale
    )

    draw = ImageDraw.Draw(image, "RGBA")
    for _depth, projected, color in sorted(faces, key=lambda item: item[0]):
        screen = projected[:, :2] * scale + offset
        screen[:, 1] = height - screen[:, 1]
        draw.polygon([tuple(point) for point in screen], fill=color)
    return image


def _average_material_color(material) -> tuple[int, int, int, int]:
    if material.image is None:
        return tuple(int(component) for component in material.color)
    pixels = np.asarray(material.image.convert("RGBA"), dtype=np.float32)
    alpha = pixels[:, :, 3]
    opaque = pixels[alpha > 0]
    if opaque.size == 0:
        return (0, 0, 0, 0)
    mean = opaque[:, :3].mean(axis=0)
    return (int(mean[0]), int(mean[1]), int(mean[2]), 255)


def _camera_basis(view: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Orthonormal camera basis for a view preset, matching the PyVista setup."""
    offset = np.asarray(VIEW_OFFSETS[view], dtype=np.float64)
    forward = offset / np.linalg.norm(offset)
    screen_up = np.asarray(_view_up(view), dtype=np.float64)
    right = np.cross(screen_up, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    up /= np.linalg.norm(up)
    return forward, right, up


def _view_up(view: str) -> tuple[float, float, float]:
    return (0.0, 1.0, 0.0) if view == "top" else (0.0, 0.0, 1.0)


def _scaled_texture_image(image: Image.Image, texture_scale: int) -> Image.Image:
    source = image.convert("RGBA")
    if texture_scale <= 1:
        return source
    return source.resize(
        (source.width * texture_scale, source.height * texture_scale),
        Image.Resampling.NEAREST,
    )


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
    _forward, right, up = _camera_basis(view)
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


def _scene_stem(scene: UW2Scene, *, name_files: bool = False) -> str:
    x1, y1, x2, y2 = scene.region
    stem = f"uw2_slot_{scene.slot:03d}"
    if name_files and scene.level_name:
        stem = f"{stem}_{slugify(scene.level_name)}"
    return f"{stem}_x{x1}-{x2}_y{y1}-{y2}_3d"


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
