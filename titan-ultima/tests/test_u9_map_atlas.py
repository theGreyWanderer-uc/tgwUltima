"""Tests for Titan's labelled Ultima IX multi-region map atlas."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from titan.u9.map_atlas import (
    DEFAULT_ATLAS_PIXELS_PER_CELL,
    U9MapAtlasError,
    U9RegionFiles,
    _pack_legend_rows,
    _wrap_text,
    discover_region_files,
    render_map_atlas,
)
from titan.u9.terrain import POINTS_PER_CHUNK, U9Terrain, U9TerrainChunk, U9TerrainPoint


class RecordingTextureProvider:
    def tile_image(
        self,
        texture_id: int,
        frame: int,
        quarter_turns: int,
        pixels_per_cell: int,
    ) -> Image.Image:
        return Image.new(
            "RGBA",
            (pixels_per_cell, pixels_per_cell),
            (texture_id, frame, quarter_turns, 255),
        )


def _rgba_pixel(image: Image.Image, x: int, y: int) -> tuple[int, int, int, int]:
    return cast(tuple[int, int, int, int], image.getpixel((x, y)))


def _write_terrain(
    path: Path,
    *,
    name: str,
    texture: int,
    width: int = 16,
    height: int = 16,
    chunk_index: int = 0,
) -> None:
    point = U9TerrainPoint.build(texture=texture).value
    chunks = tuple(
        U9TerrainChunk(index, (point,) * POINTS_PER_CHUNK)
        for index in range(chunk_index + 1)
    )
    terrain = U9Terrain.build(
        width=width,
        height=height,
        tiles=(chunk_index,) * ((width // 16) * (height // 16)),
        chunks=chunks,
        name=name,
        water_level=-100,
    )
    path.write_bytes(terrain.to_bytes())


class MapAtlasDiscoveryTests(unittest.TestCase):
    def test_discovers_numeric_regions_and_pairs_case_insensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / "static"
            runtime = root / "runtime"
            static.mkdir()
            runtime.mkdir()
            for name in ("TERRAIN.10", "terrain.2", "FIXED.2", "fixed.10"):
                (static / name).write_bytes(b"")
            (runtime / "NONFIXED.2").write_bytes(b"")
            (static / "terrain.notes").write_bytes(b"")

            sources = discover_region_files(static, runtime_directory=runtime)

        self.assertEqual([item.region_id for item in sources], [2, 10])
        self.assertEqual(sources[0].terrain_path.name, "terrain.2")
        self.assertEqual(sources[0].fixed_path.name, "FIXED.2")  # type: ignore[union-attr]
        self.assertEqual(sources[0].nonfixed_path.name, "NONFIXED.2")  # type: ignore[union-attr]
        self.assertIsNone(sources[1].nonfixed_path)

    def test_rejects_duplicate_or_missing_requested_region_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            static = Path(directory)
            (static / "terrain.2").write_bytes(b"")
            (static / "terrain.02").write_bytes(b"")
            with self.assertRaisesRegex(U9MapAtlasError, "duplicate terrain region 2"):
                discover_region_files(static)

        with tempfile.TemporaryDirectory() as directory:
            static = Path(directory)
            (static / "terrain.2").write_bytes(b"")
            with self.assertRaisesRegex(U9MapAtlasError, "region 3"):
                discover_region_files(static, region_ids=(2, 3))


class MapAtlasRenderTests(unittest.TestCase):
    def test_contact_sheet_header_wraps_to_available_width(self) -> None:
        image = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        width = 216
        title_lines = _wrap_text(
            draw,
            "Ultima IX regions - numeric ID order, not geographic adjacency",
            width,
            font,
        )
        legend_rows = _pack_legend_rows(
            draw,
            [
                ("1-cell grid", (0, 0, 0, 0)),
                ("16x16 tile/chunk", (0, 0, 0, 0)),
                ("tile x,y", (0, 0, 0, 0)),
                ("stored chunk ID", (0, 0, 0, 0)),
            ],
            width,
            font,
        )

        self.assertGreater(len(title_lines), 1)
        self.assertGreater(len(legend_rows), 1)
        self.assertTrue(
            all(
                draw.textbbox((0, 0), line, font=font)[2] <= width
                for line in title_lines
            )
        )
        for row in legend_rows:
            row_width = sum(
                11 + draw.textbbox((0, 0), label, font=font)[2] for label, _color in row
            ) + 12 * (len(row) - 1)
            self.assertLessEqual(row_width, width)

    def test_rejects_invalid_batch_options_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terrain = root / "terrain.1"
            _write_terrain(terrain, name="Good", texture=1)
            with self.assertRaisesRegex(U9MapAtlasError, "source"):
                render_map_atlas(
                    (U9RegionFiles(1, terrain),),
                    RecordingTextureProvider(),
                    root / "output",
                    object_footprint_source="invalid",  # type: ignore[arg-type]
                )
            with self.assertRaisesRegex(U9MapAtlasError, "at least 4"):
                render_map_atlas(
                    (U9RegionFiles(1, terrain),),
                    RecordingTextureProvider(),
                    root / "output",
                    pixels_per_cell=1,
                    cell_grid=True,
                )
            with self.assertRaisesRegex(U9MapAtlasError, "at least 4"):
                render_map_atlas(
                    (U9RegionFiles(1, terrain),),
                    RecordingTextureProvider(),
                    root / "output",
                    pixels_per_cell=2,
                    tile_coordinates=True,
                )

    def test_default_scale_is_28_pixels_per_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terrain = root / "terrain.9"
            _write_terrain(terrain, name="Britannia scale fixture", texture=1)
            result = render_map_atlas(
                (U9RegionFiles(9, terrain),),
                RecordingTextureProvider(),
                root / "output",
                thumbnail_size=32,
                hillshade=False,
                water=False,
                fixed_markers=False,
                nonfixed_markers=False,
            )

            preview_path = cast(Path, result.regions[0].preview_path)
            with Image.open(preview_path) as preview:
                preview_size = preview.size

        self.assertEqual(DEFAULT_ATLAS_PIXELS_PER_CELL, 28)
        self.assertEqual(preview_size, (448, 448))
        self.assertEqual(result.manifest()["layout"]["pixels_per_cell"], 28)  # type: ignore[index]

    def test_optional_grid_layers_mark_cells_tiles_and_chunk_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terrain = root / "terrain.1"
            _write_terrain(
                terrain,
                name="Grid",
                texture=1,
                width=32,
                chunk_index=1,
            )
            result = render_map_atlas(
                (U9RegionFiles(1, terrain),),
                RecordingTextureProvider(),
                root / "output",
                thumbnail_size=64,
                pixels_per_cell=4,
                hillshade=False,
                water=False,
                fixed_markers=False,
                nonfixed_markers=False,
                cell_grid=True,
                tile_grid=True,
                tile_coordinates=True,
                chunk_labels=True,
            )

            preview_path = result.regions[0].preview_path
            self.assertIsNotNone(preview_path)
            with Image.open(cast(Path, preview_path)) as preview:
                image = preview.convert("RGBA")
                base = _rgba_pixel(image, 3, 15)
                cell_line = _rgba_pixel(image, 4, 15)
                tile_line = _rgba_pixel(image, 64, 15)
                has_gold_label = any(
                    red > 240 and green > 190 and blue < 100
                    for y in range(image.height)
                    for x in range(image.width)
                    for red, green, blue, _alpha in (_rgba_pixel(image, x, y),)
                )
                has_green_coordinate = any(
                    red < 120 and green > 220 and 90 < blue < 180
                    for y in range(image.height)
                    for x in range(image.width)
                    for red, green, blue, _alpha in (_rgba_pixel(image, x, y),)
                )

            overlays = cast(
                dict[str, dict[str, object]],
                result.manifest()["grid_overlays"],
            )

        self.assertEqual(base[:3], (1, 0, 0))
        self.assertGreater(cell_line[1], cell_line[0])
        self.assertGreater(cell_line[2], cell_line[0])
        self.assertGreater(tile_line[0], tile_line[1])
        self.assertGreater(tile_line[2], tile_line[1])
        self.assertTrue(has_gold_label)
        self.assertTrue(has_green_coordinate)
        self.assertTrue(overlays["cell_grid"]["enabled"])
        self.assertEqual(overlays["tile_grid"]["spacing_cells"], 16)
        self.assertTrue(overlays["tile_coordinates"]["enabled"])
        self.assertEqual(
            overlays["tile_coordinates"]["meaning"],
            (
                "stored terrain tile-grid coordinates and the first terrain "
                "cell covered by that 16x16-cell placement"
            ),
        )
        self.assertEqual(
            overlays["tile_coordinates"]["format"],
            "Ttile_x,tile_y / Ccell_origin_x,cell_origin_y",
        )
        self.assertTrue(overlays["chunk_labels"]["enabled"])

    def test_writes_numeric_contact_sheet_previews_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terrain_10 = root / "terrain.10"
            terrain_2 = root / "terrain.2"
            _write_terrain(terrain_10, name="Ten", texture=10)
            _write_terrain(terrain_2, name="Two", texture=2)
            result = render_map_atlas(
                (
                    U9RegionFiles(10, terrain_10),
                    U9RegionFiles(2, terrain_2),
                ),
                RecordingTextureProvider(),
                root / "output",
                thumbnail_size=32,
                columns=2,
                hillshade=False,
                water=False,
                fixed_markers=False,
                nonfixed_markers=False,
            )

            with Image.open(result.atlas_path) as atlas:
                atlas_mode = atlas.mode
            manifest = result.manifest()

            self.assertEqual(atlas_mode, "RGB")
            self.assertEqual([item.region_id for item in result.regions], [2, 10])
            self.assertTrue((root / "output" / "regions" / "region_002.png").is_file())
            self.assertTrue((root / "output" / "regions" / "region_010.png").is_file())
            self.assertEqual(manifest["format"], "titan-u9-map-atlas-v1")
            self.assertEqual(manifest["ordering"], "numeric region ID")
            self.assertFalse(manifest["spatial_adjacency_inferred"])
            self.assertEqual(manifest["summary"]["rendered_regions"], 2)  # type: ignore[index]
            self.assertEqual(manifest["regions"][0]["terrain_name"], "Two")  # type: ignore[index]
            self.assertEqual(manifest["regions"][0]["width"], 16)  # type: ignore[index]
            self.assertEqual(manifest["regions"][0]["tile_width"], 1)  # type: ignore[index]
            self.assertEqual(manifest["regions"][0]["tile_height"], 1)  # type: ignore[index]

    def test_records_bad_region_without_losing_successful_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "terrain.1"
            bad = root / "terrain.2"
            _write_terrain(good, name="Good", texture=1)
            bad.write_bytes(b"bad")

            result = render_map_atlas(
                (U9RegionFiles(1, good), U9RegionFiles(2, bad)),
                RecordingTextureProvider(),
                root / "output",
                thumbnail_size=32,
                hillshade=False,
                water=False,
                continue_on_error=True,
            )

        self.assertEqual(result.diagnostics.rendered_regions, 1)
        self.assertEqual(result.diagnostics.failed_regions, 1)
        self.assertIsNone(result.regions[1].preview_path)
        self.assertIn("too small", result.regions[1].error or "")


if __name__ == "__main__":
    unittest.main()
