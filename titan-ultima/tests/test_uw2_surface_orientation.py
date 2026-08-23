"""Which way up a terrain texture goes on a floor, a ceiling and a wall.

Both consumers of a scene turn ``v`` over before sampling - the renderer through
``texture.flip_y``, the GLB export through trimesh's glTF conversion - so a
surface's ``v`` has to be written in that flipped sense. Neither floors nor walls
were, and on the noise-like stonework that fills most of UU2 it does not show.

Two things made it visible. A pentagram is inlaid across four floor tiles in the
Ethereal Void and again in Scintillus Academy, textures 236 to 239, and only
resolves into one figure with the floor turned over. Ice wall 51 carries its
ground detail along the foot of the image, which hung from the ceiling.

The 2.5D renderers had always turned floor textures over
(``map_render.transform_floor_texture`` defaults to ``flip-y``,
``grid_render`` does it directly), so this also settles a disagreement between
the two pipelines. Executable models were already right: they write ``1.0 - v``
when the model is placed.
"""

from __future__ import annotations

import unittest

from titan.uw2.geometry import generate_tile_triangles

CEILING = 128
FLOOR = 32


def _tile(x: int, y: int, type_name: str = "open") -> dict:
    return {
        "x": x,
        "y": y,
        "display_y": 63 - y,
        "type_name": type_name,
        "floor_height": FLOOR,
        "ceiling_height": CEILING,
        "slope_height": 8,
        "texture_floor": 100,
        "texture_wall": 101,
        "wall_texture_index": 1,
        "texture_ceiling_runtime": 102,
        "texture_ceiling_ua": 102,
        "object_chain_start": 0,
    }


def _triangles(include_ceilings: bool = False, neighbours: bool = True):
    """One open tile, optionally walled in, with a 1.0 z scale for readability."""
    tile_map = {(4, 5): _tile(4, 5)}
    if neighbours:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            tile_map[(4 + dx, 5 + dy)] = _tile(4 + dx, 5 + dy, "solid")
    return list(
        generate_tile_triangles(
            tile_map[(4, 5)],
            tile_map,
            z_scale=1.0,
            ceiling_source="runtime",
            include_ceilings=include_ceilings,
        )
    )


class FloorOrientationTests(unittest.TestCase):
    """Image row 0 belongs to the south edge of the tile, not the north."""

    def _floor_pairs(self):
        return [
            (vertex[1], uv[1])
            for triangle in _triangles()
            if triangle.texture_id == 100
            for vertex, uv in zip(triangle.vertices, triangle.uvs)
        ]

    def test_the_south_edge_takes_v_one(self) -> None:
        pairs = self._floor_pairs()
        self.assertTrue(pairs)
        south = {v for y, v in pairs if y == 5.0}
        north = {v for y, v in pairs if y == 6.0}
        self.assertEqual(south, {1.0})
        self.assertEqual(north, {0.0})

    def test_v_decreases_going_north(self) -> None:
        """The flip both consumers apply then puts image row 0 to the south."""
        pairs = self._floor_pairs()
        for y, v in pairs:
            with self.subTest(y=y):
                self.assertAlmostEqual(v, 6.0 - y)

    def test_u_still_runs_west_to_east(self) -> None:
        pairs = [
            (vertex[0], uv[0])
            for triangle in _triangles()
            if triangle.texture_id == 100
            for vertex, uv in zip(triangle.vertices, triangle.uvs)
        ]
        for x, u in pairs:
            with self.subTest(x=x):
                self.assertAlmostEqual(u, x - 4.0)


class CeilingOrientationTests(unittest.TestCase):
    def test_the_ceiling_matches_the_floor(self) -> None:
        pairs = [
            (vertex[1], uv[1])
            for triangle in _triangles(include_ceilings=True)
            if triangle.texture_id == 102
            for vertex, uv in zip(triangle.vertices, triangle.uvs)
        ]
        self.assertTrue(pairs)
        self.assertEqual({v for y, v in pairs if y == 5.0}, {1.0})
        self.assertEqual({v for y, v in pairs if y == 6.0}, {0.0})


class WallOrientationTests(unittest.TestCase):
    """The top of the image meets the ceiling, and repeats downwards."""

    def _wall_pairs(self):
        return [
            (vertex[2], uv[1])
            for triangle in _triangles()
            if triangle.texture_id == 101
            for vertex, uv in zip(triangle.vertices, triangle.uvs)
        ]

    def test_the_ceiling_edge_takes_v_one(self) -> None:
        pairs = self._wall_pairs()
        self.assertTrue(pairs)
        self.assertEqual({v for z, v in pairs if z == float(CEILING)}, {1.0})

    def test_v_is_one_texture_height_per_32_units_below_the_ceiling(self) -> None:
        for z, v in self._wall_pairs():
            with self.subTest(z=z):
                self.assertAlmostEqual(v, 1.0 - (CEILING - z) / 32.0)

    def test_the_floor_edge_sits_a_whole_number_of_heights_down(self) -> None:
        """A 96-unit wall is exactly three texture heights, so it tiles cleanly."""
        pairs = self._wall_pairs()
        floor_v = {v for z, v in pairs if z == float(FLOOR)}
        self.assertEqual(floor_v, {1.0 - (CEILING - FLOOR) / 32.0})
        self.assertEqual(floor_v, {-2.0})


if __name__ == "__main__":
    unittest.main()
