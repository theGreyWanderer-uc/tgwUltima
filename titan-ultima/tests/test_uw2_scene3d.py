"""Tests for UU2 renderer/exporter-neutral 3D scenes."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from titan.uw2.exe_models import ModelTriangle, ModelVertex, UW2Model
from titan.uw2.instances import sub_tile_fraction
from titan.uw2.scene3d import (
    UW2Scene,
    UW2SceneError,
    _build_model_object,
    parse_tile_region,
)


class UW2Scene3DTests(unittest.TestCase):
    def test_parse_tile_region_is_inclusive(self) -> None:
        self.assertEqual(parse_tile_region("17,46,22,52"), (17, 46, 22, 52))
        self.assertEqual(parse_tile_region(None), (0, 0, 63, 63))

    def test_parse_tile_region_rejects_reversed_bounds(self) -> None:
        with self.assertRaises(UW2SceneError):
            parse_tile_region("22,46,17,52")

    def test_model_xy_scale_does_not_double_map_height(self) -> None:
        scene = UW2Scene(slot=0, level_name=None, region=(0, 0, 0, 0))
        vertex_a = ModelVertex(0.0, 0.0, 0.0)
        vertex_b = ModelVertex(0.5, 0.0, 0.0)
        vertex_c = ModelVertex(0.0, 0.0, 0.3125)
        model = UW2Model(
            index=24,
            source_offset=0,
            extents=(0.5, 0.5, 0.5),
            triangles=(ModelTriangle((vertex_a, vertex_b, vertex_c), 7),),
        )
        palette = SimpleNamespace(
            colors=tuple((index, index, index) for index in range(256))
        )
        assets = SimpleNamespace(tmobj={}, palette=palette)
        obj = {
            "slot": 708,
            "item_id": 0x158,
            "in_tile_x": 4,
            "in_tile_y": 4,
            "zpos": 96,
            "heading": 0,
            "flags": 0,
            "quality": 0,
            "owner": 0,
        }
        tile = {"x": 18, "y": 47, "floor_height": 96, "ceiling_height": 128}

        placed = _build_model_object(scene, obj, tile, model, assets, model_scale=2.0)

        vertices = [
            vertex
            for part in placed.parts
            for triangle in part.triangles
            for vertex in triangle.vertices
        ]
        centre_x = 18 + sub_tile_fraction(4)
        self.assertEqual(max(vertex[0] for vertex in vertices), centre_x + 1.0)
        self.assertEqual(max(vertex[2] for vertex in vertices), 3.3125)

    def test_model_origin_and_clockwise_heading_are_applied_before_placement(
        self,
    ) -> None:
        scene = UW2Scene(slot=0, level_name=None, region=(0, 0, 0, 0))
        model = UW2Model(
            index=29,
            source_offset=0,
            extents=(1.0, 2.0, 1.0),
            triangles=(
                ModelTriangle(
                    (
                        ModelVertex(1.25, -0.5, 0.5),
                        ModelVertex(0.25, 0.5, 0.5),
                        ModelVertex(0.25, -0.5, 1.5),
                    ),
                    7,
                ),
            ),
            origin=(0.25, -0.5, 1.0),
        )
        palette = SimpleNamespace(
            colors=tuple((index, index, index) for index in range(256))
        )
        assets = SimpleNamespace(tmobj={}, palette=palette)
        obj = {
            "slot": 1,
            "item_id": 0x167,
            "in_tile_x": 4,
            "in_tile_y": 4,
            "zpos": 32,
            "heading": 2,
            "flags": 0,
            "quality": 0,
            "owner": 0,
        }
        tile = {"x": 10, "y": 20, "floor_height": 32, "ceiling_height": 128}

        placed = _build_model_object(scene, obj, tile, model, assets, model_scale=1.0)

        first = placed.parts[0].triangles[0].vertices[0]
        self.assertAlmostEqual(first[0], 10 + sub_tile_fraction(4))
        self.assertAlmostEqual(first[1], 20 + sub_tile_fraction(4) - 1.0)
        self.assertAlmostEqual(first[2], 1.5)


if __name__ == "__main__":
    unittest.main()
