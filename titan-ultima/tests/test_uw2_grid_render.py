"""Tests for the flat top-down diagnostic grid renderer.

This view exists precisely because it applies no projection: a tile's screen
box is a pure function of its coordinates, so anything drawn out of place is a
data problem rather than a projection artefact. These tests pin that mapping,
the display-orientation flip, and the marker passes.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.grid_render import (
    MAP_TILES,
    SOLID_FILL,
    default_options,
    edge_screen_points,
    render_grid_level,
    _tile_origin,
)


def _args(**overrides) -> SimpleNamespace:
    options = default_options()
    options.update(overrides)
    return SimpleNamespace(**options)


def _tile(x: int, y: int, type_name: str = "open", **extra) -> dict:
    tile = {
        "x": x,
        "y": y,
        "display_y": MAP_TILES - 1 - y,
        "type_name": type_name,
        "texture_floor": 5,
        "texture_wall": 6,
        "floor_height": 0,
        "ceiling_height": 128,
        "object_chain_start": 0,
    }
    tile.update(extra)
    return tile


def _full_level(**overrides) -> dict:
    tiles = [_tile(x, y, "solid") for y in range(MAP_TILES) for x in range(MAP_TILES)]
    level = {"slot_index": 0, "level_id_1based": 1, "tiles": tiles, "objects": []}
    level.update(overrides)
    return level


def _textures() -> dict[int, Image.Image]:
    return {5: Image.new("RGBA", (64, 64), (10, 200, 30, 255))}


class UW2GridGeometryTests(unittest.TestCase):
    def test_tile_origin_flips_rows_into_display_orientation(self) -> None:
        # Raw y=0 is the bottom row on screen, so it lands at the largest top.
        margin, tile_size = 56, 64
        self.assertEqual(
            _tile_origin(_tile(0, 0), margin, tile_size),
            (56, 56 + 63 * 64),
        )
        self.assertEqual(
            _tile_origin(_tile(0, 63), margin, tile_size),
            (56, 56),
        )

    def test_tile_origin_scales_with_x(self) -> None:
        self.assertEqual(_tile_origin(_tile(3, 63), 0, 10)[0], 30)

    def test_edge_points_bound_the_tile_box(self) -> None:
        for side in ("left", "right", "back", "front"):
            with self.subTest(side=side):
                x1, y1, x2, y2 = edge_screen_points(side, 100, 200, 64)
                self.assertTrue(100 <= x1 <= 164 and 100 <= x2 <= 164)
                self.assertTrue(200 <= y1 <= 264 and 200 <= y2 <= 264)

    def test_opposite_sides_do_not_share_a_line(self) -> None:
        self.assertNotEqual(
            edge_screen_points("left", 0, 0, 64),
            edge_screen_points("right", 0, 0, 64),
        )
        self.assertNotEqual(
            edge_screen_points("front", 0, 0, 64),
            edge_screen_points("back", 0, 0, 64),
        )


class UW2GridRenderTests(unittest.TestCase):
    def test_canvas_covers_the_whole_map_plus_margin(self) -> None:
        image = render_grid_level(
            _full_level(), _textures(), _args(tile_size=16, margin=8)
        )

        self.assertEqual(image.size, (8 + 16 * MAP_TILES, 8 + 16 * MAP_TILES))

    def test_solid_tiles_render_as_the_solid_fill(self) -> None:
        image = render_grid_level(
            _full_level(),
            _textures(),
            _args(tile_size=16, margin=8, grid_label_step=64),
        )

        # Middle of tile (1,1) in display space, clear of grid lines and labels.
        self.assertEqual(image.getpixel((8 + 16 + 8, 8 + 16 + 8)), SOLID_FILL)

    def test_open_tiles_composite_their_floor_texture(self) -> None:
        tiles = [
            _tile(x, y, "solid") for y in range(MAP_TILES) for x in range(MAP_TILES)
        ]
        tiles[MAP_TILES * 62 + 1] = _tile(1, 62, "open")
        level = _full_level(tiles=tiles)

        image = render_grid_level(
            level, _textures(), _args(tile_size=16, margin=8, grid_label_step=64)
        )

        # Raw y=62 -> display row 1.
        self.assertEqual(image.getpixel((8 + 16 + 8, 8 + 16 + 8)), (10, 200, 30, 255))

    def test_rejects_an_unknown_coordinate_mode(self) -> None:
        with self.assertRaises(ValueError):
            render_grid_level(
                _full_level(), _textures(), _args(coordinate_mode="sideways")
            )

    def test_missing_floor_texture_falls_back_to_a_flat_fill(self) -> None:
        tiles = [
            _tile(x, y, "solid") for y in range(MAP_TILES) for x in range(MAP_TILES)
        ]
        tiles[MAP_TILES * 62 + 1] = _tile(1, 62, "open", texture_floor=200)
        level = _full_level(tiles=tiles)

        image = render_grid_level(
            level, _textures(), _args(tile_size=16, margin=8, grid_label_step=64)
        )

        self.assertEqual(image.getpixel((8 + 16 + 8, 8 + 16 + 8)), (44, 44, 44, 255))


class UW2GridDefaultTests(unittest.TestCase):
    def test_defaults_are_independent_of_the_cutaway_renderer(self) -> None:
        # The grid has no wall height at all, so it must not inherit or
        # influence map-render's tuned projection options.
        options = default_options()

        self.assertNotIn("max_wall_height", options)
        self.assertNotIn("wall_height_scale", options)
        self.assertNotIn("lift_pixels", options)
        self.assertEqual(options["margin"], 56)


if __name__ == "__main__":
    unittest.main()
