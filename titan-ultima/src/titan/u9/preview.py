"""
Render a preview image of a ``titan u9 model-export`` output folder.

Optional feature -- requires ``pyvista`` (and its ``vtk`` dependency),
which is **not** a core ``titan-ultima`` dependency (it's large and
only needed for this one visualization feature). Install it yourself
(``pip install pyvista``) before calling :func:`render_preview`;
:class:`PreviewUnavailableError` is raised with that same instruction
if it's missing, rather than making the whole package depend on it.

**Why this loads the OBJ via ``vtkOBJImporter``, not ``pyvista.read()``**:
a naive ``pyvista.read(obj_path)`` (or a plain ``vtkOBJReader``) loads
geometry and material *metadata* for a multi-material OBJ, but not each
material's actual texture image -- rendering it with a single
``texture=`` override then shows only one material's image applied
correctly and leaves every other material flat gray (confirmed on a
real 16-material export: only the material whose PNG happened to be
picked rendered with any texture at all). ``vtkOBJImporter`` is VTK's
full scene importer -- it creates one correctly-textured actor per
``usemtl`` group, matching every ``map_Kd`` PNG to its own material.
Its actors are then transplanted into a plain :class:`pyvista.Plotter`
(``plotter.renderer.AddActor(...)``) purely to reuse PyVista's
convenient camera-fit/lighting/screenshot helpers -- confirmed this
combination renders every material correctly on the same real
16-material model that the naive approach got wrong.

**Why textures are explicitly set to mipmap + interpolate**: VTK's
default imported texture has both off, which is fine for large flat
regions but produces heavy shimmering/rainbow moire noise on any
high-frequency texture (e.g. a fur/hair photo texture) once it's
minified below native resolution -- confirmed on a real model (an
arctic wolf) whose body is covered in fine fur detail: the default
settings rendered it as streaky rainbow noise, and enabling
``MipmapOn()`` + ``InterpolateOn()`` (plus 8x anisotropic filtering)
on every actor's texture produced a clean, coherent fur pattern
instead, with no code/data changes on the model side.
"""

from __future__ import annotations

__all__ = ["render_preview", "PreviewError", "PreviewUnavailableError"]

import glob
import os


class PreviewError(Exception):
    """Raised when a model-export folder has no renderable OBJ."""


class PreviewUnavailableError(PreviewError):
    """Raised when ``pyvista`` (an optional dependency) isn't installed."""


def render_preview(model_dir: str, output_path: "str | None" = None) -> list[str]:
    """
    Render ``<model_dir>``'s ``.obj`` (+ its ``.mtl``/PNG textures, if
    any) to two PNGs -- PyVista's default isometric angle, then the
    same view rotated 180 degrees around (camera azimuth), each
    independently auto-fit to the model's bounds. There's no reliable
    way to know a model's actual "front" direction from the exported
    data alone, but the default isometric angle consistently turned
    out to be a rear-ish view for the humanoid models checked, so the
    rotated shot reliably ends up front-ish instead -- hence the
    naming. Returns both paths written, in that order (default:
    ``<model_dir>/preview.png`` and ``<model_dir>/preview_front.png``).
    """
    obj_paths = glob.glob(os.path.join(model_dir, "*.obj"))
    if not obj_paths:
        raise PreviewError(f"no .obj file found in {model_dir}")
    obj_path = obj_paths[0]
    mtl_path = os.path.splitext(obj_path)[0] + ".mtl"

    try:
        import pyvista as pv
        import vtk
    except ImportError as e:
        raise PreviewUnavailableError(
            "pyvista is required for preview rendering but isn't installed -- run `pip install pyvista`"
        ) from e

    importer = vtk.vtkOBJImporter()
    importer.SetFileName(obj_path)
    if os.path.isfile(mtl_path):
        importer.SetFileNameMTL(mtl_path)
        importer.SetTexturePath(model_dir)

    import_window = vtk.vtkRenderWindow()
    import_window.SetOffScreenRendering(1)
    importer.SetRenderWindow(import_window)
    importer.Update()

    plotter = pv.Plotter(off_screen=True, window_size=[900, 900])
    plotter.set_background("gray", top="white")

    actors = importer.GetRenderer().GetActors()
    actors.InitTraversal()
    for _ in range(actors.GetNumberOfItems()):
        actor = actors.GetNextActor()
        texture = actor.GetTexture()
        if texture is not None:
            texture.MipmapOn()
            texture.InterpolateOn()
            texture.SetMaximumAnisotropicFiltering(8)
        plotter.renderer.AddActor(actor)

    plotter.enable_lightkit()

    if output_path:
        base, ext = os.path.splitext(output_path)
        out_path_1, out_path_2 = output_path, f"{base}_front{ext}"
    else:
        out_path_1 = os.path.join(model_dir, "preview.png")
        out_path_2 = os.path.join(model_dir, "preview_front.png")

    plotter.view_isometric()
    plotter.reset_camera()
    plotter.camera.zoom(1.2)
    plotter.screenshot(out_path_1)

    plotter.camera.azimuth = 180
    plotter.reset_camera()
    plotter.camera.zoom(1.2)
    plotter.screenshot(out_path_2)

    plotter.close()
    return [out_path_1, out_path_2]
