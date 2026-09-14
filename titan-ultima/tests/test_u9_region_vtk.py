"""Tests for U9 south-high orthographic VTK rendering."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from math import atan2, degrees
from pathlib import Path

from PIL import Image

from titan.u9.region_vtk import (
    SOUTH_HIGH_CAMERA_OFFSET,
    VTK_RESOLUTION_PRESETS,
    U9VtkRenderError,
    fit_south_high_orthographic_camera,
    render_region_glb,
    resolve_vtk_render_size,
)


class SouthHighCameraTests(unittest.TestCase):
    def test_full_and_half_resolution_presets_use_the_vtk_edge_limit(self) -> None:
        self.assertEqual(VTK_RESOLUTION_PRESETS, {"full": 16384, "half": 8192})
        self.assertEqual(resolve_vtk_render_size(), (16384, 16384))
        self.assertEqual(resolve_vtk_render_size("half"), (8192, 8192))

    def test_explicit_dimension_overrides_make_a_square_when_only_one_is_set(
        self,
    ) -> None:
        self.assertEqual(resolve_vtk_render_size("full", width=1200), (1200, 1200))
        self.assertEqual(resolve_vtk_render_size("full", height=900), (900, 900))
        self.assertEqual(
            resolve_vtk_render_size("half", width=1200, height=800),
            (1200, 800),
        )
        with self.assertRaises(U9VtkRenderError):
            resolve_vtk_render_size("quarter")

    def test_preset_is_due_south_at_about_48_degrees(self) -> None:
        east, elevation, presentation_z = SOUTH_HIGH_CAMERA_OFFSET

        self.assertEqual(east, 0.0)
        self.assertGreater(elevation, 0.0)
        # Region GLB Z is far_u9_y - u9_y, so its positive edge is south.
        self.assertGreater(presentation_z, 0.0)
        angle = degrees(atan2(elevation, presentation_z))
        self.assertAlmostEqual(angle, 48.0, delta=1.0)

    def test_fit_contains_projected_bounds_at_requested_aspect(self) -> None:
        camera = fit_south_high_orthographic_camera(
            (0.0, 100.0, -20.0, 80.0, 0.0, 200.0),
            width=1600,
            height=900,
            fit_margin=1.0,
        )

        visible_height = camera.parallel_scale * 2.0
        visible_width = visible_height * (1600 / 900)
        self.assertGreaterEqual(visible_width, camera.projected_width)
        self.assertGreaterEqual(visible_height, camera.projected_height)
        self.assertGreater(camera.clipping_range[0], 0.0)
        self.assertGreater(camera.clipping_range[1], camera.clipping_range[0])

    def test_fit_rejects_invalid_bounds_and_options(self) -> None:
        with self.assertRaisesRegex(U9VtkRenderError, "invalid visible bounds"):
            fit_south_high_orthographic_camera(
                (10.0, 0.0, 0.0, 1.0, 0.0, 1.0), width=100, height=100
            )
        with self.assertRaisesRegex(U9VtkRenderError, "dimensions"):
            fit_south_high_orthographic_camera(
                (0.0, 1.0, 0.0, 1.0, 0.0, 1.0), width=0, height=100
            )
        with self.assertRaisesRegex(U9VtkRenderError, "fit margin"):
            fit_south_high_orthographic_camera(
                (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
                width=100,
                height=100,
                fit_margin=0.99,
            )


@unittest.skipUnless(
    all(
        importlib.util.find_spec(name) is not None
        for name in ("pyvista", "vtk", "trimesh")
    ),
    "optional PyVista/VTK/trimesh rendering stack is unavailable",
)
class VtkRenderIntegrationTests(unittest.TestCase):
    def test_renders_glb_with_parallel_camera(self) -> None:
        import trimesh

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "box.glb"
            output = root / "box.png"
            trimesh.creation.box(extents=(2.0, 4.0, 3.0)).export(scene)

            result = render_region_glb(
                scene,
                output,
                width=160,
                height=120,
                anti_aliasing="none",
            )

            self.assertEqual(Image.open(output).size, (160, 120))
            self.assertEqual(result.diagnostics.view, "south-high")
            self.assertEqual(result.diagnostics.projection, "orthographic")
            self.assertGreater(result.diagnostics.actor_count, 0)
            self.assertIn("OpenGL", result.diagnostics.render_window_class)
            self.assertEqual(result.diagnostics.ambient_strength, 0.3)
            self.assertEqual(result.diagnostics.headlight_intensity, 1.25)


if __name__ == "__main__":
    unittest.main()
