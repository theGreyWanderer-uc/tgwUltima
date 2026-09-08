"""Tests for textured U9 terrain-region GLB export."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

import numpy as np
from PIL import Image

from titan.u9.map_render import U9MapRenderError, U9MapTextureSource
from titan.u9.model import (
    U9Limb,
    U9Material,
    U9Model,
    U9SubmeshLod,
    U9Triangle,
    U9TriangleCorner,
)
from titan.u9.nonfixed import U9Nonfixed
from titan.u9.object_placement import (
    U9ModelBounds,
    U9ModelBoundsLookup,
    U9ModelLookup,
    U9ObjectFootprintFilter,
)
from titan.u9.region_glb import (
    U9CellRegion,
    U9GlbExportError,
    export_region_glb,
)
from titan.u9.region_scene import U9RegionScene
from titan.u9.terrain import HEADER_SIZE, POINTS_PER_CHUNK, U9Terrain, U9TerrainPoint


def _terrain() -> U9Terrain:
    point = U9TerrainPoint.build(height=10, texture=1).value
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<II", head, 0, 32, 32)
    struct.pack_into("<i", head, 0x88, 30)
    struct.pack_into("<I", head, 0x94, 1)
    return U9Terrain(
        bytes(head)
        + struct.pack("<4H", 0, 0, 0, 0)
        + struct.pack(f"<{POINTS_PER_CHUNK}I", *([point] * POINTS_PER_CHUNK))
    )


def _nonfixed(*, placement_count: int = 1) -> U9Nonfixed:
    if placement_count not in {1, 2}:
        raise ValueError("fixture supports one or two placements")
    entity_offset = 0x60
    heads = [0, entity_offset] + [0] * 15
    page = struct.pack("<7I17I", 0, 0, 0, 0, 0, placement_count, 0, *heads)
    for index in range(placement_count):
        page += struct.pack(
            "<IHHHH4hIHHI",
            entity_offset + 0x20 if index == 0 and placement_count == 2 else 0,
            128 + index * 128,
            128,
            300,
            203,
            0,
            0,
            0,
            -32768,
            0,
            1210,
            0,
            0,
        )
    header = struct.pack("<5I", 0, 0, 0, len(page), 0x00C00000)
    header += struct.pack("<III", 1, 1, 1)
    header += struct.pack("<II", 1, 0)
    return U9Nonfixed(header + page)


def _material() -> U9Material:
    return U9Material(
        texture_id=5,
        flags_02=0,
        render_flags=0,
        flags_06=0,
        first_face=0,
        face_count=1,
        default_alpha=255,
        modified_alpha=255,
        anim_start=0,
        anim_end=0,
        cur_frame=0,
        anim_speed=0,
    )


def _model() -> U9Model:
    corners = (
        U9TriangleCorner(0, (0.0, 0.0, 1.0), (0.0, 0.0)),
        U9TriangleCorner(1, (0.0, 0.0, 1.0), (1.0, 0.0)),
        U9TriangleCorner(2, (0.0, 0.0, 1.0), (0.0, 1.0)),
    )
    triangle = U9Triangle(
        corners=corners,
        material_index=0,
        face_normal=(0.0, 0.0, 1.0),
        color=(255, 255, 255, 255),
    )
    lod = U9SubmeshLod(
        lod_index=0,
        vertices=((0.0, 0.0, 0.0), (40.0, 0.0, 0.0), (0.0, 40.0, 0.0)),
        triangles=(triangle,),
        materials=(_material(),),
        sphere_center=(0.0, 0.0, 0.0),
        sphere_radius=40.0,
        min_bounds=(0.0, 0.0, 0.0),
        max_bounds=(40.0, 40.0, 0.0),
    )
    limb = U9Limb(
        limb_id=0,
        parent_id=0,
        scale=(1.0, 1.0, 1.0),
        position=(0.0, 0.0, 0.0),
        rotation=(1.0, 0.0, 0.0, 0.0),
        lods=(lod,),
    )
    return U9Model(
        model_id=1210,
        cylinder_base_center=(0.0, 0.0, 0.0),
        cylinder_base_height=0.0,
        cylinder_base_radius=0.0,
        sphere_center=(0.0, 0.0, 0.0),
        sphere_radius=40.0,
        min_bounds=(0.0, 0.0, 0.0),
        max_bounds=(40.0, 40.0, 0.0),
        lod_thresholds=(0, 0, 0, 0),
        center_of_mass=(0.0, 0.0, 0.0),
        limbs=(limb,),
    )


class FakeTextureSource(U9MapTextureSource):
    def __init__(self, *, fail_texture: int | None = None) -> None:
        self.fail_texture = fail_texture
        self.calls: list[tuple[int, int]] = []

    def frame_image(self, texture_id: int, frame: int) -> Image.Image:
        self.calls.append((texture_id, frame))
        if texture_id == self.fail_texture:
            raise U9MapRenderError("missing fixture texture")
        return Image.new("RGBA", (4, 4), (texture_id, frame, 20, 255))


class FakeModelProvider:
    def __init__(self) -> None:
        self.parsed_model = _model()

    def model_bounds(self, model_id: int) -> U9ModelBoundsLookup:
        if model_id != 1210:
            return U9ModelBoundsLookup(model_id, "out_of_range")
        return U9ModelBoundsLookup(
            model_id,
            "resolved",
            U9ModelBounds(model_id, (0.0, 0.0, 0.0), (40.0, 40.0, 0.0)),
        )

    def model(self, model_id: int) -> U9ModelLookup:
        if model_id != 1210:
            return U9ModelLookup(model_id, "out_of_range")
        return U9ModelLookup(model_id, "resolved", self.parsed_model)


class RegionGlbTests(unittest.TestCase):
    def test_cell_region_parses_hex_and_rejects_invalid_bounds(self) -> None:
        region = U9CellRegion.parse("0x1,2,4,5")
        self.assertEqual(region, U9CellRegion(1, 2, 4, 5))
        self.assertEqual((region.width, region.height), (3, 3))
        with self.assertRaisesRegex(U9GlbExportError, "four integers"):
            U9CellRegion.parse("1,2,3")
        with self.assertRaisesRegex(U9GlbExportError, "X"):
            U9CellRegion(0, 0, 33, 4).validate(U9RegionScene(_terrain()))

    def test_exports_terrain_water_and_named_nonfixed_model(self) -> None:
        scene = U9RegionScene(_terrain(), nonfixed=_nonfixed())
        textures = FakeTextureSource()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "region.glb"
            result = export_region_glb(
                scene,
                textures,
                output,
                cell_region=U9CellRegion(0, 0, 4, 4),
                object_models=FakeModelProvider(),
            )

            self.assertEqual(output.read_bytes()[:4], b"glTF")
            self.assertEqual(result.diagnostics.terrain_cells_considered, 16)
            self.assertEqual(result.diagnostics.terrain_triangles, 32)
            self.assertEqual(result.diagnostics.water_triangles, 2)
            self.assertEqual(result.diagnostics.object_placements_exported, 1)
            self.assertEqual(result.diagnostics.object_triangles, 1)
            self.assertEqual(result.diagnostics.object_meshes_exported, 1)
            self.assertEqual(result.diagnostics.geometry_nodes, 3)
            self.assertEqual(result.diagnostics.geometry_meshes, 3)
            self.assertEqual(result.diagnostics.missing_texture_keys, ())
            self.assertEqual(len(result.objects[0].node_names), 1)
            self.assertIn("nonfixed", result.objects[0].node_names[0])
            self.assertEqual(
                result.manifest()["diagnostics"]["cell_region"],  # type: ignore[index]
                (0, 0, 4, 4),
            )

    def test_repeated_objects_share_mesh_with_distinct_placement_nodes(self) -> None:
        import trimesh

        scene = U9RegionScene(_terrain(), nonfixed=_nonfixed(placement_count=2))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "instanced.glb"
            result = export_region_glb(
                scene,
                FakeTextureSource(),
                output,
                cell_region=U9CellRegion(0, 0, 4, 4),
                include_terrain=False,
                include_water=False,
                object_models=FakeModelProvider(),
            )
            loaded = cast(Any, trimesh.load(output, force="scene"))

        self.assertEqual(result.diagnostics.object_placements_exported, 2)
        self.assertEqual(result.diagnostics.object_parts_exported, 2)
        self.assertEqual(result.diagnostics.object_meshes_exported, 1)
        self.assertEqual(result.diagnostics.object_triangles, 2)
        self.assertEqual(result.diagnostics.geometry_nodes, 2)
        self.assertEqual(result.diagnostics.geometry_meshes, 1)
        self.assertEqual(len(loaded.geometry), 1)
        self.assertEqual(len(loaded.graph.nodes_geometry), 2)
        np.testing.assert_allclose(
            loaded.bounds,
            ((3.2, 7.5, 8.6), (7.4, 7.5, 9.6)),
            atol=1e-6,
        )
        self.assertEqual(
            {loaded.graph[node][1] for node in loaded.graph.nodes_geometry},
            set(loaded.geometry),
        )
        self.assertEqual(len(result.objects[0].node_names), 1)
        self.assertEqual(len(result.objects[1].node_names), 1)
        self.assertNotEqual(
            result.objects[0].node_names[0], result.objects[1].node_names[0]
        )

    def test_object_filters_and_anchor_crop_preserve_resolution_counts(self) -> None:
        scene = U9RegionScene(_terrain(), nonfixed=_nonfixed())
        with tempfile.TemporaryDirectory() as directory:
            result = export_region_glb(
                scene,
                FakeTextureSource(),
                Path(directory) / "region.glb",
                cell_region=U9CellRegion(4, 4, 8, 8),
                object_models=FakeModelProvider(),
                object_filter=U9ObjectFootprintFilter(model_ids=frozenset({1210})),
            )

        self.assertEqual(result.diagnostics.object_footprints_resolved_total, 1)
        self.assertEqual(result.diagnostics.object_placements_matching_filter, 1)
        self.assertEqual(result.diagnostics.object_placements_in_region, 0)
        self.assertEqual(result.diagnostics.object_placements_exported, 0)
        self.assertEqual(result.diagnostics.geometry_nodes, 2)

    def test_missing_texture_uses_visible_fallback_and_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = export_region_glb(
                U9RegionScene(_terrain()),
                FakeTextureSource(fail_texture=1),
                Path(directory) / "region.glb",
                cell_region=U9CellRegion(0, 0, 1, 1),
                include_water=False,
            )
        self.assertEqual(result.diagnostics.missing_texture_keys, ("terrain:1:0:0",))

    def test_requires_glb_suffix_and_at_least_one_layer(self) -> None:
        scene = U9RegionScene(_terrain())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(U9GlbExportError, "no enabled"):
                export_region_glb(
                    scene,
                    FakeTextureSource(),
                    Path(directory) / "region.glb",
                    include_terrain=False,
                    include_water=False,
                )
            with self.assertRaisesRegex(U9GlbExportError, "end in .glb"):
                export_region_glb(
                    scene,
                    FakeTextureSource(),
                    Path(directory) / "region.obj",
                    include_water=False,
                )


if __name__ == "__main__":
    unittest.main()
