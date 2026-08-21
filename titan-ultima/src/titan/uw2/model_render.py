"""Standalone rendering for polygon models embedded in ``UW2.EXE``."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

from titan.uw2.exe_models import ITEM_MODEL_INDEX, ModelTriangle, UW2ModelArchive
from titan.uw2.gr import UW2GRArchive
from titan.uw2.instances import TMOBJ, object_material
from titan.uw2.palette import UW2Palette


ITEM_MODEL_NAMES = {
    0x0150: "bench",
    0x0151: "arrow",
    0x0153: "large_boulder",
    0x0154: "large_boulder",
    0x0155: "boulder",
    0x0156: "small_boulder",
    0x0157: "shrine",
    0x0158: "table",
    0x0159: "beam",
    0x015A: "moongate",
    0x015B: "barrel",
    0x015C: "chair",
    0x015D: "chest",
    0x015E: "nightstand",
    0x015F: "lotus_esprit",
    0x0160: "pillar",
    0x0163: "painting",
    0x0165: "gravestone",
    0x0167: "bed",
    0x0168: "blackrock_gem",
    0x0169: "shelf",
}


class UW2ModelRenderError(ValueError):
    """Raised when a standalone model cannot be rendered."""


class UW2ModelRenderUnavailableError(UW2ModelRenderError):
    """Raised when optional PyVista/VTK rendering packages are absent."""


def model_texture_index(item_id: int, flags: int = 0) -> int | None:
    """Resolve item-selected ``TMOBJ.GR`` image for textured model faces.

    Standalone model tools have no level context, so only object-texture rules
    apply here; classes that borrow a level architectural texture resolve to
    ``None``. See :mod:`titan.uw2.instances` for the shared rule set.
    """
    reference = object_material(item_id, flags)
    if reference is None or reference.source != TMOBJ:
        return None
    return reference.index


def render_object_models(
    source: str | Path,
    output: str | Path,
    *,
    item_ids: Iterable[int],
    flags: int = 0,
    size: int = 900,
    views: Iterable[str] = ("iso", "front"),
) -> list[Path]:
    """Read original UU2 files and render selected built-in models to PNG."""
    try:
        import pyvista as pv
    except ImportError as error:
        raise UW2ModelRenderUnavailableError(
            "pyvista and vtk are required for UW2 model rendering"
        ) from error

    if size < 128:
        raise UW2ModelRenderError("render size must be at least 128 pixels")
    requested_views = tuple(views)
    invalid_views = sorted(set(requested_views) - {"iso", "front", "side", "top"})
    if invalid_views:
        raise UW2ModelRenderError(f"unknown model views: {invalid_views}")

    source_path = Path(source).expanduser()
    data_dir = (
        source_path if source_path.name.upper() == "DATA" else source_path / "DATA"
    )
    install_dir = data_dir.parent
    executable = install_dir / "UW2.EXE"
    palette_path = data_dir / "PALS.DAT"
    tmobj_path = data_dir / "TMOBJ.GR"
    for path, label in (
        (executable, "UW2.EXE"),
        (palette_path, "PALS.DAT"),
        (tmobj_path, "TMOBJ.GR"),
    ):
        if not path.is_file():
            raise UW2ModelRenderError(f"UU2 {label} not found: {path}")

    palette = UW2Palette.from_file(palette_path)
    allpals = data_dir / "ALLPALS.DAT"
    tmobj = UW2GRArchive.from_file(tmobj_path, allpals if allpals.is_file() else None)
    models = UW2ModelArchive.from_file(executable)
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for item_id in item_ids:
        model_index = ITEM_MODEL_INDEX.get(item_id)
        if model_index is None:
            raise UW2ModelRenderError(
                f"UU2 item {item_id:#06x} has no decoded built-in model"
            )
        model = models.model(model_index)
        texture_index = model_texture_index(item_id, flags)
        texture = None
        if texture_index is not None and any(
            triangle.textured for triangle in model.triangles
        ):
            image = tmobj.image(texture_index).to_image(palette)
            texture = pv.Texture(np.asarray(image))
            texture.flip_y()
            texture.interpolate = False

        stem = f"{ITEM_MODEL_NAMES.get(item_id, 'object')}_item_{item_id:03d}_model_{model.index:02d}"
        for view in requested_views:
            destination = output_path / f"{stem}_{view}.png"
            _render_one_view(
                pv,
                model.triangles,
                palette,
                texture,
                destination,
                label=f"{ITEM_MODEL_NAMES.get(item_id, 'object')}  item {item_id:#06x}  model {model.index:#04x}",
                view=view,
                size=size,
            )
            written.append(destination)
    return written


def _render_one_view(
    pv,
    triangles: tuple[ModelTriangle, ...],
    palette: UW2Palette,
    texture,
    destination: Path,
    *,
    label: str,
    view: str,
    size: int,
) -> None:
    plotter = pv.Plotter(off_screen=True, window_size=(size, size))
    plotter.set_background("#111820", top="#526171")

    colored: dict[int, list[ModelTriangle]] = defaultdict(list)
    textured: list[ModelTriangle] = []
    for triangle in triangles:
        if triangle.textured and texture is not None:
            textured.append(triangle)
        else:
            colored[triangle.palette_index].append(triangle)

    for palette_index, group in colored.items():
        mesh = _triangle_mesh(pv, group, with_uv=False)
        plotter.add_mesh(
            mesh,
            color=palette.colors[palette_index],
            smooth_shading=False,
            show_edges=False,
            ambient=0.25,
            diffuse=0.8,
            specular=0.05,
        )
    if textured:
        mesh = _triangle_mesh(pv, textured, with_uv=True)
        plotter.add_mesh(
            mesh,
            texture=texture,
            smooth_shading=False,
            show_edges=False,
            ambient=0.3,
            diffuse=0.8,
        )

    plotter.add_text(label, position="upper_left", font_size=11, color="white")
    plotter.enable_lightkit()
    plotter.enable_anti_aliasing("ssaa")
    bounds = _model_bounds(triangles)
    center = (
        (bounds[0] + bounds[1]) / 2.0,
        (bounds[2] + bounds[3]) / 2.0,
        (bounds[4] + bounds[5]) / 2.0,
    )
    span = max(
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
        0.1,
    )
    camera_offsets = {
        "iso": (1.8, -2.2, 1.5),
        "front": (0.0, -3.0, 0.8),
        "side": (3.0, 0.0, 0.8),
        "top": (0.0, -0.01, 3.2),
    }
    offset = camera_offsets[view]
    plotter.camera_position = [
        tuple(center[axis] + offset[axis] * span for axis in range(3)),
        center,
        (0.0, 1.0, 0.0) if view == "top" else (0.0, 0.0, 1.0),
    ]
    plotter.reset_camera()
    plotter.camera.zoom(1.25)
    plotter.screenshot(destination)
    plotter.close()


def _triangle_mesh(pv, triangles: list[ModelTriangle], *, with_uv: bool):
    points: list[tuple[float, float, float]] = []
    faces: list[int] = []
    uv: list[tuple[float, float]] = []
    for triangle in triangles:
        start = len(points)
        faces.extend((3, start, start + 1, start + 2))
        for vertex in triangle.vertices:
            points.append((vertex.x, vertex.y, vertex.z))
            if with_uv:
                uv.append((vertex.u, vertex.v))
    mesh = pv.PolyData(np.asarray(points), np.asarray(faces))
    if with_uv:
        mesh.active_texture_coordinates = np.asarray(uv)
    return mesh


def _model_bounds(triangles: tuple[ModelTriangle, ...]) -> tuple[float, ...]:
    if not triangles:
        raise UW2ModelRenderError("decoded model contains no triangles")
    vertices = [vertex for triangle in triangles for vertex in triangle.vertices]
    return (
        min(vertex.x for vertex in vertices),
        max(vertex.x for vertex in vertices),
        min(vertex.y for vertex in vertices),
        max(vertex.y for vertex in vertices),
        min(vertex.z for vertex in vertices),
        max(vertex.z for vertex in vertices),
    )
