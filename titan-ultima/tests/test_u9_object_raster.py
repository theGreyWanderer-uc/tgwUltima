"""Tests for top-down rasterization of placed Ultima IX model meshes."""

from __future__ import annotations

import unittest

import numpy as np

from tests.test_u9_region_glb import (
    FakeModelProvider,
    FakeTextureSource,
    _terrain,
)
from titan.u9.object_placement import U9ObjectPlacementResolution
from titan.u9.object_raster import (
    U9ObjectRasterError,
    rasterize_object_meshes,
)
from titan.u9.region_scene import U9RegionScene, U9WorldPosition


def _placement() -> U9ObjectPlacementResolution:
    return U9ObjectPlacementResolution(
        source_kind="nonfixed",
        source_offset=0x60,
        type_index=203,
        model_id=1210,
        status="resolved",
        position=U9WorldPosition(128, 128, 300),
        rotation_xyzw=(0, 0, 0, -32768),
        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
        scale_xyz=(4.0, 4.0, 4.0),
        footprint_xy=((128.0, 128.0),),
        flags=0,
        trigger_id=None,
    )


class ObjectRasterTests(unittest.TestCase):
    def test_rasterizes_textured_triangle_over_lower_terrain(self) -> None:
        scene = U9RegionScene(_terrain())
        pixels = np.zeros((256, 256, 4), dtype=np.uint8)
        pixels[:, :] = (1, 2, 3, 255)
        depth = np.full((256, 256), 40.0, dtype=np.float32)

        diagnostics = rasterize_object_meshes(
            pixels,
            depth,
            scene,
            FakeModelProvider(),
            FakeTextureSource(),
            (_placement(),),
            pixels_per_cell=8,
        )

        self.assertEqual(diagnostics.placements_selected, 1)
        self.assertEqual(diagnostics.placements_drawn, 1)
        self.assertEqual(diagnostics.models_drawn, 1)
        self.assertEqual(diagnostics.triangles_considered, 1)
        self.assertEqual(diagnostics.triangles_drawn, 1)
        self.assertGreater(diagnostics.pixels_drawn, 0)
        self.assertEqual(diagnostics.missing_texture_keys, ())
        self.assertTrue(np.any(np.all(pixels[:, :, :3] == (5, 0, 20), axis=2)))

    def test_surface_depth_occludes_lower_model(self) -> None:
        scene = U9RegionScene(_terrain())
        pixels = np.zeros((256, 256, 4), dtype=np.uint8)
        depth = np.full((256, 256), 400.0, dtype=np.float32)

        diagnostics = rasterize_object_meshes(
            pixels,
            depth,
            scene,
            FakeModelProvider(),
            FakeTextureSource(),
            (_placement(),),
            pixels_per_cell=8,
        )

        self.assertEqual(diagnostics.placements_drawn, 0)
        self.assertEqual(diagnostics.triangles_drawn, 0)
        self.assertEqual(diagnostics.pixels_drawn, 0)

    def test_reports_missing_material_texture_and_validates_depth_size(self) -> None:
        scene = U9RegionScene(_terrain())
        pixels = np.zeros((256, 256, 4), dtype=np.uint8)
        depth = np.zeros((256, 256), dtype=np.float32)
        diagnostics = rasterize_object_meshes(
            pixels,
            depth,
            scene,
            FakeModelProvider(),
            FakeTextureSource(fail_texture=5),
            (_placement(),),
            pixels_per_cell=8,
        )
        self.assertEqual(diagnostics.missing_texture_keys, ("5:0",))
        self.assertTrue(np.any(np.all(pixels[:, :, :3] == (255, 0, 255), axis=2)))

        with self.assertRaisesRegex(U9ObjectRasterError, "dimensions"):
            rasterize_object_meshes(
                pixels,
                np.zeros((1, 1), dtype=np.float32),
                scene,
                FakeModelProvider(),
                FakeTextureSource(),
                (_placement(),),
                pixels_per_cell=8,
            )


if __name__ == "__main__":
    unittest.main()
