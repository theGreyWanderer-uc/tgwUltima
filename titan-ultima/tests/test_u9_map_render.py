"""Tests for Titan's textured U9 bird's-eye region renderer."""

from __future__ import annotations

import struct
import unittest

from PIL import Image

from titan.u9.map_render import (
    U9MapRenderError,
    _format_legend_ids,
    render_region_map,
)
from titan.u9.nonfixed import U9Nonfixed
from titan.u9.object_placement import U9ModelBounds, U9ModelBoundsLookup
from titan.u9.region_scene import U9RegionScene
from titan.u9.terrain import HEADER_SIZE, POINTS_PER_CHUNK, U9Terrain, U9TerrainPoint


def _terrain(
    values: list[int],
    *,
    width: int = 16,
    height: int = 16,
    water_level: int = 0,
    wave_amplitude: float = 0.0,
) -> U9Terrain:
    words = values + [values[-1]] * (POINTS_PER_CHUNK - len(values))
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<II", head, 0, width, height)
    struct.pack_into("<i", head, 0x88, water_level)
    struct.pack_into("<f", head, 0x8C, wave_amplitude)
    struct.pack_into("<I", head, 0x94, 1)
    tile_count = (width // 16) * (height // 16)
    return U9Terrain(
        bytes(head)
        + struct.pack(f"<{tile_count}H", *([0] * tile_count))
        + struct.pack(f"<{POINTS_PER_CHUNK}I", *words)
    )


def _nonfixed() -> U9Nonfixed:
    entity_offset = 0x60
    heads = [0, entity_offset] + [0] * 15
    page = struct.pack("<7I17I", 0, 0, 0, 0, 0, 1, 0, *heads)
    page += struct.pack(
        "<IHHHH4hIHHI",
        0,
        128,
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


class RecordingTextureProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[int, int, int, int]] = []
        self.fail = fail

    def tile_image(
        self,
        texture_id: int,
        frame: int,
        quarter_turns: int,
        pixels_per_cell: int,
    ) -> Image.Image:
        self.calls.append((texture_id, frame, quarter_turns, pixels_per_cell))
        if self.fail:
            raise U9MapRenderError("fixture has no texture")
        color = (texture_id, frame * 10, quarter_turns * 20, 255)
        return Image.new("RGBA", (pixels_per_cell, pixels_per_cell), color)


class RecordingModelBoundsProvider:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def model_bounds(self, model_id: int) -> U9ModelBoundsLookup:
        self.calls.append(model_id)
        return U9ModelBoundsLookup(
            model_id,
            "resolved",
            U9ModelBounds(model_id, (-128.0, -128.0, 0.0), (128.0, 128.0, 64.0)),
        )


class MapRenderTests(unittest.TestCase):
    def test_legend_id_summary_handles_short_and_long_filters(self) -> None:
        self.assertEqual(_format_legend_ids(()), "all")
        self.assertEqual(_format_legend_ids((561,)), "561")
        self.assertEqual(
            _format_legend_ids((1, 2, 3, 4, 5, 6, 7)),
            "1,2,3,4,5,6 (+1)",
        )

    def test_uses_texture_frame_rotation_and_complete_cell_size(self) -> None:
        point = U9TerrainPoint.build(
            height=10, texture=7, frame=3, swap_uv=True, mirror_uv=True
        ).value
        provider = RecordingTextureProvider()
        result = render_region_map(
            U9RegionScene(_terrain([point])),
            provider,
            pixels_per_cell=2,
            hillshade=False,
            water=False,
            flip_y=False,
        )
        self.assertEqual(result.image.size, (32, 32))
        self.assertEqual(provider.calls, [(7, 3, 3, 2)])
        self.assertEqual(result.image.getpixel((0, 0)), (7, 30, 60, 255))
        self.assertEqual(result.diagnostics.texture_keys, 1)

    def test_hole_bit_makes_only_that_cell_transparent(self) -> None:
        hole = U9TerrainPoint.build(texture=4, is_hole=True).value
        ground = U9TerrainPoint.build(texture=4).value
        result = render_region_map(
            U9RegionScene(_terrain([hole, ground])),
            RecordingTextureProvider(),
            hillshade=False,
            water=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(result.image.getpixel((1, 0)), (4, 0, 0, 255))
        self.assertEqual(result.diagnostics.hole_cells, 1)

    def test_missing_texture_is_visible_and_reported(self) -> None:
        point = U9TerrainPoint.build(texture=12, frame=2).value
        result = render_region_map(
            U9RegionScene(_terrain([point])),
            RecordingTextureProvider(fail=True),
            hillshade=False,
            water=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((0, 0)), (255, 0, 255, 255))
        self.assertEqual(result.diagnostics.missing_texture_keys, ("12:2:0",))
        self.assertEqual(result.diagnostics.missing_texture_cells, 256)

    def test_flat_terrain_hillshade_preserves_texture_color(self) -> None:
        point = U9TerrainPoint.build(height=100, texture=9).value
        result = render_region_map(
            U9RegionScene(_terrain([point])),
            RecordingTextureProvider(),
            hillshade=True,
            water=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((4, 4)), (9, 0, 0, 255))

    def test_rejects_unbounded_output_scale(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        with self.assertRaises(U9MapRenderError):
            render_region_map(
                U9RegionScene(_terrain([point])),
                RecordingTextureProvider(),
                pixels_per_cell=33,
                water=False,
            )

    def test_accepts_28_pixels_per_cell_for_large_atlas_previews(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        result = render_region_map(
            U9RegionScene(_terrain([point])),
            RecordingTextureProvider(),
            pixels_per_cell=28,
            hillshade=False,
            water=False,
        )
        self.assertEqual(result.image.size, (448, 448))

    def test_draws_nonfixed_authored_placement_and_reports_coverage(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        scene = U9RegionScene(
            _terrain([point], width=32, height=32), nonfixed=_nonfixed()
        )
        result = render_region_map(
            scene,
            RecordingTextureProvider(),
            hillshade=False,
            water=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((1, 1)), (24, 224, 255, 176))
        self.assertEqual(result.diagnostics.nonfixed_indexed_entities, 1)
        self.assertEqual(result.diagnostics.nonfixed_markers_drawn, 1)
        self.assertEqual(result.diagnostics.nonfixed_entities_in_bounds, 1)

    def test_draws_nonfixed_transformed_model_footprint(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        scene = U9RegionScene(
            _terrain([point], width=32, height=32), nonfixed=_nonfixed()
        )
        models = RecordingModelBoundsProvider()
        result = render_region_map(
            scene,
            RecordingTextureProvider(),
            pixels_per_cell=2,
            hillshade=False,
            water=False,
            nonfixed_markers=False,
            object_footprints=True,
            object_models=models,
            object_legend=False,
            flip_y=False,
        )
        self.assertEqual(models.calls, [1210])
        self.assertNotEqual(result.image.getpixel((0, 0)), (1, 0, 0, 255))
        self.assertTrue(result.diagnostics.object_footprints_enabled)
        self.assertEqual(result.diagnostics.object_footprints_drawn, 1)
        self.assertEqual(result.diagnostics.nonfixed_footprints_resolved, 1)
        self.assertEqual(result.diagnostics.object_model_ids_resolved, (1210,))

    def test_filters_footprints_and_reports_raw_and_display_counts(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        scene = U9RegionScene(
            _terrain([point], width=32, height=32), nonfixed=_nonfixed()
        )
        result = render_region_map(
            scene,
            RecordingTextureProvider(),
            pixels_per_cell=2,
            hillshade=False,
            water=False,
            nonfixed_markers=False,
            object_footprints=True,
            object_models=RecordingModelBoundsProvider(),
            object_model_ids=(999,),
            object_legend=False,
            flip_y=False,
        )

        self.assertEqual(result.image.getpixel((2, 2)), (1, 0, 0, 255))
        self.assertEqual(result.diagnostics.object_footprints_resolved_total, 1)
        self.assertEqual(result.diagnostics.object_footprints_drawn, 0)
        self.assertEqual(result.diagnostics.object_footprints_filtered_out, 1)
        self.assertEqual(result.diagnostics.object_footprint_model_filter, (999,))
        self.assertEqual(result.diagnostics.object_model_ids_resolved, (1210,))
        self.assertEqual(result.diagnostics.object_model_ids_drawn, ())

    def test_outline_fill_and_legend_are_independently_selectable(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        scene = U9RegionScene(
            _terrain([point], width=32, height=32), nonfixed=_nonfixed()
        )
        outline = render_region_map(
            scene,
            RecordingTextureProvider(),
            pixels_per_cell=2,
            hillshade=False,
            water=False,
            nonfixed_markers=False,
            object_footprints=True,
            object_models=RecordingModelBoundsProvider(),
            object_footprint_style="outline",
            object_legend=False,
            flip_y=False,
        )
        filled = render_region_map(
            scene,
            RecordingTextureProvider(),
            pixels_per_cell=2,
            hillshade=False,
            water=False,
            nonfixed_markers=False,
            object_footprints=True,
            object_models=RecordingModelBoundsProvider(),
            object_footprint_style="fill",
            object_legend=False,
            flip_y=False,
        )
        with_legend = render_region_map(
            scene,
            RecordingTextureProvider(),
            pixels_per_cell=2,
            hillshade=False,
            water=False,
            nonfixed_markers=False,
            object_footprints=True,
            object_models=RecordingModelBoundsProvider(),
            object_legend=True,
            flip_y=False,
        )

        self.assertEqual(outline.image.getpixel((2, 2)), (1, 0, 0, 255))
        self.assertNotEqual(filled.image.getpixel((2, 2)), (1, 0, 0, 255))
        self.assertNotEqual(with_legend.image.getpixel((8, 8)), (1, 0, 0, 255))
        self.assertEqual(filled.diagnostics.object_footprint_style, "fill")
        self.assertTrue(with_legend.diagnostics.object_footprint_legend_enabled)

    def test_rejects_invalid_footprint_presentation_options(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        with self.assertRaisesRegex(U9MapRenderError, "style"):
            render_region_map(
                U9RegionScene(_terrain([point])),
                RecordingTextureProvider(),
                object_footprint_style="solid",  # type: ignore[arg-type]
                water=False,
            )
        with self.assertRaisesRegex(U9MapRenderError, "source"):
            render_region_map(
                U9RegionScene(_terrain([point])),
                RecordingTextureProvider(),
                object_footprint_source="dynamic",  # type: ignore[arg-type]
                water=False,
            )

    def test_object_footprints_require_model_bounds_provider(self) -> None:
        point = U9TerrainPoint.build(texture=1).value
        with self.assertRaisesRegex(U9MapRenderError, "sappear.flx"):
            render_region_map(
                U9RegionScene(_terrain([point])),
                RecordingTextureProvider(),
                object_footprints=True,
                water=False,
            )

    def test_global_water_uses_header_level_texture_49_and_selected_frame(self) -> None:
        point = U9TerrainPoint.build(height=100, texture=1).value
        provider = RecordingTextureProvider()
        result = render_region_map(
            U9RegionScene(_terrain([point], water_level=500, wave_amplitude=10.0)),
            provider,
            water_frame=3,
            hillshade=False,
            flip_y=False,
        )
        self.assertIn((49, 3, 0, 1), provider.calls)
        self.assertEqual(result.image.getpixel((0, 0)), (49, 30, 0, 255))
        self.assertEqual(result.diagnostics.water_level, 500)
        self.assertEqual(result.diagnostics.wave_amplitude, 10.0)
        self.assertEqual(result.diagnostics.water_visible_cells, 256)
        self.assertEqual(result.diagnostics.water_visible_pixels, 256)
        self.assertFalse(result.diagnostics.water_texture_missing)

    def test_global_water_depth_tests_each_subpixel_against_cell_triangles(
        self,
    ) -> None:
        low = U9TerrainPoint.build(height=0, texture=1).value
        high = U9TerrainPoint.build(height=1000, texture=1).value
        result = render_region_map(
            U9RegionScene(_terrain([low, high], water_level=2000)),
            RecordingTextureProvider(),
            pixels_per_cell=2,
            hillshade=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((0, 0)), (49, 0, 0, 255))
        self.assertEqual(result.image.getpixel((1, 0)), (1, 0, 0, 255))
        self.assertEqual(result.image.getpixel((0, 1)), (1, 0, 0, 255))
        self.assertEqual(result.image.getpixel((1, 1)), (1, 0, 0, 255))

    def test_terrain_hole_exposes_water_below_high_ground(self) -> None:
        hole = U9TerrainPoint.build(height=1000, texture=1, is_hole=True).value
        result = render_region_map(
            U9RegionScene(_terrain([hole], water_level=10)),
            RecordingTextureProvider(),
            hillshade=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((0, 0)), (49, 0, 0, 255))

    def test_water_can_be_disabled_for_ground_only_output(self) -> None:
        point = U9TerrainPoint.build(height=0, texture=1).value
        result = render_region_map(
            U9RegionScene(_terrain([point], water_level=500)),
            RecordingTextureProvider(),
            hillshade=False,
            water=False,
            flip_y=False,
        )
        self.assertEqual(result.image.getpixel((0, 0)), (1, 0, 0, 255))
        self.assertFalse(result.diagnostics.water_enabled)
        self.assertEqual(result.diagnostics.water_visible_pixels, 0)


if __name__ == "__main__":
    unittest.main()
