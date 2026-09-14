"""Render an exported Ultima IX region GLB through VTK/OpenGL.

The U9 GLB exporter is the canonical scene builder: it decodes terrain,
water, fixed objects, nonfixed objects, model transforms, materials, and
textures.  This module deliberately starts at that boundary so a camera
renderer cannot acquire a second, subtly different copy of those rules.

``south-high`` is a due-south view at roughly 48 degrees elevation.  It uses
parallel projection, preserving one scale across Britannia while still
showing vertical model faces that collapse in the plan renderer.
"""

from __future__ import annotations

__all__ = [
    "ANTI_ALIASING_MODES",
    "MAX_VTK_RENDER_EDGE",
    "SOUTH_HIGH_CAMERA_OFFSET",
    "TEXTURE_FILTERS",
    "VTK_RESOLUTION_PRESETS",
    "U9OrthographicCamera",
    "U9VtkRenderDiagnostics",
    "U9VtkRenderError",
    "U9VtkRenderResult",
    "U9VtkUnavailableError",
    "fit_south_high_orthographic_camera",
    "render_region_glb",
    "resolve_vtk_render_size",
]

from dataclasses import asdict, dataclass
from itertools import product
from math import isfinite
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

SOUTH_HIGH_CAMERA_OFFSET = (0.0, 1.1, 1.0)
"""South camera offset in GLB X/elevation/presentation-Z axes.

Region GLBs use ``presentation_z = far_u9_y - u9_y``.  Native U9 Y increases
northward in the established plan-map orientation, so positive presentation Z
is the south side of the converted scene.
"""

MAX_VTK_RENDER_EDGE = 16_384
VTK_RESOLUTION_PRESETS = {
    "full": MAX_VTK_RENDER_EDGE,
    "half": MAX_VTK_RENDER_EDGE // 2,
}
ANTI_ALIASING_MODES = ("none", "fxaa", "ssaa")
TEXTURE_FILTERS = ("nearest", "linear")


class U9VtkRenderError(Exception):
    """Raised when a U9 GLB cannot be rendered as requested."""


class U9VtkUnavailableError(U9VtkRenderError):
    """Raised when optional PyVista/VTK rendering packages are unavailable."""


def resolve_vtk_render_size(
    resolution: str = "full",
    width: int | None = None,
    height: int | None = None,
) -> tuple[int, int]:
    """Resolve full/half square presets, with optional explicit dimensions."""
    try:
        preset_edge = VTK_RESOLUTION_PRESETS[resolution]
    except KeyError as error:
        choices = ", ".join(VTK_RESOLUTION_PRESETS)
        raise U9VtkRenderError(
            f"3D resolution must be one of {choices}, got {resolution!r}"
        ) from error
    if width is None and height is None:
        width = height = preset_edge
    elif width is None:
        width = height
    elif height is None:
        height = width
    if width is None or height is None:  # pragma: no cover - narrowed above
        raise U9VtkRenderError("could not resolve render dimensions")
    if not (1 <= width <= MAX_VTK_RENDER_EDGE):
        raise U9VtkRenderError(
            f"render width must be from 1 to {MAX_VTK_RENDER_EDGE} pixels"
        )
    if not (1 <= height <= MAX_VTK_RENDER_EDGE):
        raise U9VtkRenderError(
            f"render height must be from 1 to {MAX_VTK_RENDER_EDGE} pixels"
        )
    return width, height


@dataclass(frozen=True)
class U9OrthographicCamera:
    """Fully fitted VTK camera values for a south-high orthographic view."""

    position: tuple[float, float, float]
    focal_point: tuple[float, float, float]
    view_up: tuple[float, float, float]
    parallel_scale: float
    clipping_range: tuple[float, float]
    projected_width: float
    projected_height: float


@dataclass(frozen=True)
class U9VtkRenderDiagnostics:
    """Machine-readable details of one VTK/OpenGL region render."""

    view: str
    projection: str
    width: int
    height: int
    actor_count: int
    textured_actor_count: int
    scene_bounds: tuple[float, float, float, float, float, float]
    camera: U9OrthographicCamera
    anti_aliasing: str
    texture_filter: str
    lighting: bool
    ambient_strength: float
    headlight_intensity: float
    vtk_version: str
    pyvista_version: str
    render_window_class: str
    open_gl_capabilities: str

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready render diagnostics."""
        result = asdict(self)
        result["camera"] = asdict(self.camera)
        return result


@dataclass(frozen=True)
class U9VtkRenderResult:
    """Written image path and diagnostics for a VTK region render."""

    image_path: Path
    diagnostics: U9VtkRenderDiagnostics

    def manifest(self) -> dict[str, object]:
        """Return a JSON-ready render manifest."""
        return {
            "format": "titan-u9-vtk-region-render-v1",
            "image": self.image_path.name,
            "diagnostics": self.diagnostics.to_dict(),
        }


def _validated_bounds(
    bounds: tuple[float, float, float, float, float, float] | list[float],
) -> tuple[float, float, float, float, float, float]:
    if len(bounds) != 6 or not all(isfinite(float(value)) for value in bounds):
        raise U9VtkRenderError("scene has no finite visible bounds")
    result = (
        float(bounds[0]),
        float(bounds[1]),
        float(bounds[2]),
        float(bounds[3]),
        float(bounds[4]),
        float(bounds[5]),
    )
    if result[0] > result[1] or result[2] > result[3] or result[4] > result[5]:
        raise U9VtkRenderError("scene has invalid visible bounds")
    return result


def fit_south_high_orthographic_camera(
    bounds: tuple[float, float, float, float, float, float] | list[float],
    *,
    width: int,
    height: int,
    fit_margin: float = 1.04,
) -> U9OrthographicCamera:
    """Fit all eight corners of ``bounds`` into a south-high parallel view."""
    scene_bounds = _validated_bounds(bounds)
    if width < 1 or height < 1:
        raise U9VtkRenderError("render dimensions must be positive")
    if fit_margin < 1.0 or not isfinite(fit_margin):
        raise U9VtkRenderError("fit margin must be finite and at least 1.0")

    lower = np.asarray(
        (scene_bounds[0], scene_bounds[2], scene_bounds[4]), dtype=np.float64
    )
    upper = np.asarray(
        (scene_bounds[1], scene_bounds[3], scene_bounds[5]), dtype=np.float64
    )
    center = (lower + upper) / 2.0
    diagonal = max(float(np.linalg.norm(upper - lower)), 1.0)
    offset = np.asarray(SOUTH_HIGH_CAMERA_OFFSET, dtype=np.float64)
    offset /= np.linalg.norm(offset)
    position = center + offset * diagonal * 2.0
    forward = center - position
    forward /= np.linalg.norm(forward)

    view_up_hint = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
    right = np.cross(forward, view_up_hint)
    right /= np.linalg.norm(right)
    camera_up = np.cross(right, forward)
    camera_up /= np.linalg.norm(camera_up)

    corners = np.asarray(tuple(product(*zip(lower, upper))), dtype=np.float64)
    centered = corners - center
    projected_x = centered @ right
    projected_y = centered @ camera_up
    projected_width = float(projected_x.max() - projected_x.min())
    projected_height = float(projected_y.max() - projected_y.min())
    aspect = width / height
    parallel_scale = (
        max(
            projected_height / 2.0,
            projected_width / (2.0 * aspect),
            0.5,
        )
        * fit_margin
    )

    depths = (corners - position) @ forward
    depth_padding = max(diagonal * 0.05, 1.0)
    near = max(0.001, float(depths.min()) - depth_padding)
    far = max(near + 1.0, float(depths.max()) + depth_padding)
    return U9OrthographicCamera(
        position=(float(position[0]), float(position[1]), float(position[2])),
        focal_point=(float(center[0]), float(center[1]), float(center[2])),
        view_up=(
            float(camera_up[0]),
            float(camera_up[1]),
            float(camera_up[2]),
        ),
        parallel_scale=parallel_scale,
        clipping_range=(near, far),
        projected_width=projected_width,
        projected_height=projected_height,
    )


def _configure_actor_textures(actor: Any, *, interpolate: bool) -> int:
    """Enable stable minification on every glTF texture attached to an actor."""
    textures: list[Any] = []
    direct = actor.GetTexture()
    if direct is not None:
        textures.append(direct)
    prop = actor.GetProperty()
    for name in ("albedoTex", "emissiveTex", "normalTex", "materialTex", "ormTex"):
        texture = prop.GetTexture(name)
        if texture is not None and texture not in textures:
            textures.append(texture)
    for texture in textures:
        texture.MipmapOn()
        if interpolate:
            texture.InterpolateOn()
        else:
            texture.InterpolateOff()
        texture.SetMaximumAnisotropicFiltering(8)
    return int(bool(textures))


def _capabilities(render_window: Any) -> str:
    try:
        return str(render_window.ReportCapabilities()).strip()
    except Exception:  # pragma: no cover - backend-specific diagnostic only
        return ""


def render_region_glb(
    scene_path: str | Path,
    output_path: str | Path,
    *,
    width: int = 4096,
    height: int = 4096,
    fit_margin: float = 1.04,
    anti_aliasing: Literal["none", "fxaa", "ssaa"] = "fxaa",
    texture_filter: Literal["nearest", "linear"] = "linear",
    lighting: bool = True,
    ambient_strength: float = 0.3,
    headlight_intensity: float = 1.25,
    background: str = "#0c1118",
    background_top: str = "#526171",
) -> U9VtkRenderResult:
    """Render one Titan U9 region GLB from the south using VTK/OpenGL."""
    scene = Path(scene_path)
    output = Path(output_path)
    if not scene.is_file():
        raise U9VtkRenderError(f"scene GLB not found: {scene}")
    if scene.suffix.lower() != ".glb":
        raise U9VtkRenderError("scene input must be a .glb file")
    if not (1 <= width <= MAX_VTK_RENDER_EDGE):
        raise U9VtkRenderError(
            f"render width must be from 1 to {MAX_VTK_RENDER_EDGE} pixels"
        )
    if not (1 <= height <= MAX_VTK_RENDER_EDGE):
        raise U9VtkRenderError(
            f"render height must be from 1 to {MAX_VTK_RENDER_EDGE} pixels"
        )
    if anti_aliasing not in ANTI_ALIASING_MODES:
        raise U9VtkRenderError(
            f"anti-aliasing must be one of {', '.join(ANTI_ALIASING_MODES)}"
        )
    if texture_filter not in TEXTURE_FILTERS:
        raise U9VtkRenderError(
            f"texture filter must be one of {', '.join(TEXTURE_FILTERS)}"
        )
    if not (0.0 <= ambient_strength <= 1.0) or not isfinite(ambient_strength):
        raise U9VtkRenderError("ambient strength must be finite and from 0.0 to 1.0")
    if headlight_intensity < 0.0 or not isfinite(headlight_intensity):
        raise U9VtkRenderError("headlight intensity must be finite and non-negative")
    try:
        import pyvista as pv
        import vtk  # type: ignore[import-untyped]
    except ImportError as error:
        raise U9VtkUnavailableError(
            "pyvista and vtk are required for U9 3D map rendering"
        ) from error

    output.parent.mkdir(parents=True, exist_ok=True)
    import_window = vtk.vtkRenderWindow()
    import_window.SetOffScreenRendering(1)
    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(scene))
    importer.SetRenderWindow(import_window)
    plotter = None
    try:
        importer.Update()
        imported_renderer = importer.GetRenderer()
        actors = imported_renderer.GetActors()
        actor_count = actors.GetNumberOfItems()
        if actor_count == 0:
            raise U9VtkRenderError("scene GLB contains no visible actors")

        plotter = pv.Plotter(off_screen=True, window_size=[width, height])
        plotter = cast(Any, plotter)
        plotter.set_background(background, top=background_top)
        actors.InitTraversal()
        textured_actor_count = 0
        for _ in range(actor_count):
            actor = actors.GetNextActor()
            textured_actor_count += _configure_actor_textures(
                actor, interpolate=texture_filter == "linear"
            )
            if lighting:
                actor.GetProperty().SetAmbient(ambient_strength)
            plotter.renderer.AddActor(actor)

        if lighting:
            plotter.enable_lightkit()
            headlight = vtk.vtkLight()
            headlight.SetLightTypeToHeadlight()
            headlight.SetColor(1.0, 1.0, 1.0)
            headlight.SetIntensity(headlight_intensity)
            plotter.renderer.AddLight(headlight)
        if anti_aliasing != "none":
            plotter.enable_anti_aliasing(anti_aliasing)

        scene_bounds = _validated_bounds(plotter.renderer.ComputeVisiblePropBounds())
        camera = fit_south_high_orthographic_camera(
            scene_bounds,
            width=width,
            height=height,
            fit_margin=fit_margin,
        )
        plotter.camera_position = [
            camera.position,
            camera.focal_point,
            camera.view_up,
        ]
        plotter.camera.enable_parallel_projection()
        plotter.camera.parallel_scale = camera.parallel_scale
        plotter.camera.clipping_range = camera.clipping_range
        plotter.screenshot(str(output), return_img=False)
        render_window = plotter.render_window
        diagnostics = U9VtkRenderDiagnostics(
            view="south-high",
            projection="orthographic",
            width=width,
            height=height,
            actor_count=actor_count,
            textured_actor_count=textured_actor_count,
            scene_bounds=scene_bounds,
            camera=camera,
            anti_aliasing=anti_aliasing,
            texture_filter=texture_filter,
            lighting=lighting,
            ambient_strength=ambient_strength,
            headlight_intensity=headlight_intensity,
            vtk_version=vtk.vtkVersion.GetVTKVersion(),
            pyvista_version=pv.__version__,
            render_window_class=render_window.GetClassName(),
            open_gl_capabilities=_capabilities(render_window),
        )
    except U9VtkRenderError:
        raise
    except Exception as error:
        raise U9VtkRenderError(f"VTK could not render {scene}: {error}") from error
    finally:
        if plotter is not None:
            plotter.close()
        import_window.Finalize()
    return U9VtkRenderResult(image_path=output, diagnostics=diagnostics)
