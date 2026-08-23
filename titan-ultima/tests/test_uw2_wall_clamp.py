"""Objects should not hang over the wall tiles beside them.

Two separate causes, fixed separately.

A bridge deck and a doorway span a whole tile, so the tile is their position;
centring them on the object's sub-tile cell left the whole span about 1/16 of a
tile off. UW2 places both from the tile - ``RenderBridge`` in underworldexporter
overrides the computed position with ``ObjectTileX * 1.2f + 1.2f / 2f``, and its
door case never reads ``xpos``/``ypos``. That is a correctness fix and is baked
into the geometry.

Loose scenery is a different matter: it is drawn centred on its sub-tile cell at
true size, and UW2 puts a fifth of all sub-tile coordinates hard against a tile
edge, so half the object lands inside the wall. Nothing is wrong with the data -
the game is only ever seen from inside the room. That one is presentation, so
the offset is recorded and applied when drawing, leaving an export the raw
placement.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.instances import (
    BRIDGE_ITEM,
    DECAL_FACE_DEPTH,
    DECAL_WALL_EDGE,
    DOOR_FIRST,
    PAINTING_ITEM,
    SHELF_ITEM,
    WRITING_ITEM,
    is_tile_aligned,
    is_wall_clamped,
    object_centre,
    sub_tile_fraction,
    wall_clamp_offset,
)
from titan.uw2.scene3d import build_level_scene

SOLID = {"type_name": "solid"}
LOOSE = 0x00BB  # a bottle of ale: ordinary scenery, nothing special about it
TERRAIN_IDS = (100, 101)


def _tile(x: int, y: int) -> dict:
    return {"x": x, "y": y, "type_name": "open"}


def _grid(**overrides: dict) -> dict:
    """5x5 of open tiles; name a coordinate as tile_X_Y to override it."""
    grid = {(x, y): dict(_tile(x, y)) for x in range(5) for y in range(5)}
    for key, value in overrides.items():
        x, y = (int(part) for part in key.split("_")[1:])
        grid[(x, y)] = {"x": x, "y": y, **value}
    return grid


def _offset(bounds, grid, item_id=LOOSE, kind="sprite"):
    return wall_clamp_offset(bounds, _tile(2, 2), grid, item_id, kind)


class ClampGeometryTests(unittest.TestCase):
    def test_no_solid_neighbour_leaves_the_object_alone(self) -> None:
        # Straddles the 2.0 boundary, but tile (1,2) is open - a legitimate spot.
        self.assertEqual(_offset((1.9, 2.15, 2.4, 2.6), _grid()), (0.0, 0.0))

    def test_pushed_off_a_solid_neighbour_to_the_west(self) -> None:
        dx, dy = _offset((1.9, 2.15, 2.4, 2.6), _grid(tile_1_2=SOLID))
        self.assertAlmostEqual(dx, 0.1)
        self.assertEqual(dy, 0.0)

    def test_pushed_off_a_solid_neighbour_to_the_east(self) -> None:
        dx, dy = _offset((2.85, 3.1, 2.4, 2.6), _grid(tile_3_2=SOLID))
        self.assertAlmostEqual(dx, -0.1)
        self.assertEqual(dy, 0.0)

    def test_both_axes_clamp_independently(self) -> None:
        dx, dy = _offset((1.9, 2.15, 2.4, 3.05), _grid(tile_1_2=SOLID, tile_2_3=SOLID))
        self.assertAlmostEqual(dx, 0.1)
        self.assertAlmostEqual(dy, -0.05)

    def test_shift_is_the_smallest_that_clears_the_wall(self) -> None:
        dx, _dy = _offset((1.98, 2.2, 2.4, 2.6), _grid(tile_1_2=SOLID))
        self.assertAlmostEqual(dx, 0.02)

    def test_object_wider_than_its_gap_is_centred(self) -> None:
        # 1.4 tiles across with walls both sides: it cannot fit, so centre it
        # rather than pinning one arbitrary edge to a wall.
        walled = _grid(tile_1_2=SOLID, tile_3_2=SOLID)
        dx, _dy = _offset((1.8, 3.2, 2.4, 2.6), walled)
        self.assertAlmostEqual(dx, 0.0)
        dx, _dy = _offset((1.6, 3.0, 2.4, 2.6), walled)
        self.assertAlmostEqual(dx, 0.2)

    def test_off_map_counts_as_solid(self) -> None:
        grid = {(x, y): dict(_tile(x, y)) for x in range(5) for y in range(5)}
        grid.pop((1, 2))
        dx, _dy = _offset((1.9, 2.15, 2.4, 2.6), grid)
        self.assertAlmostEqual(dx, 0.1)

    def test_a_diagonal_neighbour_does_not_block(self) -> None:
        """A diagonal still has floor; treating it as wall evicts corner items."""
        grid = _grid(tile_1_2={"type_name": "diagonal_se"})
        self.assertEqual(_offset((1.9, 2.15, 2.4, 2.6), grid), (0.0, 0.0))


class ClampExemptionTests(unittest.TestCase):
    def test_loose_scenery_is_clamped(self) -> None:
        self.assertTrue(is_wall_clamped(LOOSE, "sprite"))

    def test_exempt_classes(self) -> None:
        """Only a door: its leaf stands in the opening, so it must not move."""
        for label, item_id, kind in (
            ("door", DOOR_FIRST, "door"),
            ("bridge", BRIDGE_ITEM, "model"),
        ):
            with self.subTest(label):
                self.assertFalse(is_wall_clamped(item_id, kind))
                self.assertEqual(
                    wall_clamp_offset(
                        (1.9, 2.15, 2.4, 2.6),
                        _tile(2, 2),
                        _grid(tile_1_2=SOLID),
                        item_id,
                        kind,
                    ),
                    (0.0, 0.0),
                )

    def test_wall_fixtures_are_clamped_flush_not_exempted(self) -> None:
        """A shelf left unclamped pokes through while its crockery moves clear.

        The shift is exactly the overhang, so a fixture ends up against the wall
        face rather than pushed off it, and whatever stands on it keeps station.
        """
        for label, item_id in (
            ("shelf", SHELF_ITEM),
            ("painting", PAINTING_ITEM),
            ("writing decal", WRITING_ITEM),
        ):
            with self.subTest(label):
                self.assertTrue(is_wall_clamped(item_id, "model"))
                # 0.06 of the fixture has crossed into the rock to the west
                dx, _dy = wall_clamp_offset(
                    (1.94, 2.19, 2.4, 2.6),
                    _tile(2, 2),
                    _grid(tile_1_2=SOLID),
                    item_id,
                    "model",
                )
                self.assertAlmostEqual(dx, 0.06)

    def test_a_fixture_already_flush_is_not_pushed_off_the_wall(self) -> None:
        for item_id in (SHELF_ITEM, PAINTING_ITEM, WRITING_ITEM):
            with self.subTest(hex(item_id)):
                self.assertEqual(
                    wall_clamp_offset(
                        (2.0, 2.25, 2.4, 2.6),
                        _tile(2, 2),
                        _grid(tile_1_2=SOLID),
                        item_id,
                        "model",
                    ),
                    (0.0, 0.0),
                )


class DecalWallFaceTests(unittest.TestCase):
    """A decal hangs on a wall face, so that coordinate comes from the tile.

    UA's ``RenderDecal`` sets the across-wall coordinate from the tile edge and
    reads ``xpos``/``ypos`` only for the position along the wall. The heading to
    wall mapping is confirmed against the shipped levels: for each heading the
    matching neighbour is solid far more often than any other.
    """

    def _centre(self, heading: int, in_tile: int = 4):
        obj = {
            "item_id": WRITING_ITEM,
            "in_tile_x": in_tile,
            "in_tile_y": in_tile,
            "heading": heading,
        }
        return object_centre(obj, _tile(10, 20))

    def test_each_square_heading_names_one_wall(self) -> None:
        self.assertEqual(
            DECAL_WALL_EDGE,
            {0: ("y", 1.0), 2: ("x", 1.0), 4: ("y", 0.0), 6: ("x", 0.0)},
        )

    def test_the_face_lands_on_the_wall_not_the_centre(self) -> None:
        """The quad stands DECAL_FACE_DEPTH outward, so the centre is set back."""
        for heading, axis, wall, sign in (
            (0, 1, 21.0, -1),
            (2, 0, 11.0, -1),
            (4, 1, 20.0, +1),
            (6, 0, 10.0, +1),
        ):
            with self.subTest(heading=heading):
                centre = self._centre(heading)
                self.assertAlmostEqual(centre[axis], wall + sign * DECAL_FACE_DEPTH)
                # the face itself, standing outward from the centre
                self.assertAlmostEqual(centre[axis] - sign * DECAL_FACE_DEPTH, wall)

    def test_the_along_wall_axis_still_uses_the_sub_tile_cell(self) -> None:
        for heading, free_axis, base in ((0, 0, 10), (2, 1, 20)):
            for in_tile in range(8):
                with self.subTest(heading=heading, in_tile=in_tile):
                    centre = self._centre(heading, in_tile)
                    self.assertAlmostEqual(
                        centre[free_axis], base + sub_tile_fraction(in_tile)
                    )

    def test_a_diagonal_heading_keeps_both_sub_tile_cells(self) -> None:
        """Seven objects in the game sit on one; they name no single wall."""
        for heading in (1, 3, 5, 7):
            with self.subTest(heading=heading):
                self.assertEqual(
                    self._centre(heading, 3),
                    (10 + sub_tile_fraction(3), 20 + sub_tile_fraction(3)),
                )

    def test_ordinary_furniture_is_not_pinned_to_a_wall(self) -> None:
        obj = {"item_id": SHELF_ITEM, "in_tile_x": 7, "in_tile_y": 7, "heading": 2}
        self.assertEqual(
            object_centre(obj, _tile(10, 20)),
            (10 + sub_tile_fraction(7), 20 + sub_tile_fraction(7)),
        )


class TileAlignmentTests(unittest.TestCase):
    def test_bridges_and_doors_take_the_tile_centre(self) -> None:
        tile = _tile(10, 20)
        for item_id in (BRIDGE_ITEM, DOOR_FIRST):
            for in_tile in (0, 3, 4, 7):
                with self.subTest(item=hex(item_id), in_tile=in_tile):
                    self.assertTrue(is_tile_aligned(item_id))
                    obj = {
                        "item_id": item_id,
                        "in_tile_x": in_tile,
                        "in_tile_y": in_tile,
                    }
                    self.assertEqual(object_centre(obj, tile), (10.5, 20.5))

    def test_everything_else_keeps_its_sub_tile_cell(self) -> None:
        tile = _tile(10, 20)
        for in_tile in range(8):
            with self.subTest(in_tile=in_tile):
                obj = {"item_id": LOOSE, "in_tile_x": in_tile, "in_tile_y": in_tile}
                expected = 10 + sub_tile_fraction(in_tile)
                self.assertAlmostEqual(object_centre(obj, tile)[0], expected)


def _assets() -> SimpleNamespace:
    image = Image.new("RGBA", (8, 8), (120, 90, 60, 255))
    return SimpleNamespace(
        terrain={texture: image for texture in TERRAIN_IDS},
        tmobj={},
        tmflat={},
        doors={},
        animo={},
        objects={LOOSE: image},
        common_objects=SimpleNamespace(
            get=lambda item_id: SimpleNamespace(
                # Quarter-tile, like most UU2 scenery, so a centred placement
                # genuinely clears the wall and only an edge one does not.
                render_type=0,
                render_type_name="sprite",
                height=8,
            )
        ),
        animations=SimpleNamespace(get=lambda item_id: None),
        models=None,
        palette=SimpleNamespace(colors=[(10, 20, 30)] * 256),
        strings=None,
    )


def _scene_tile(x: int, y: int, type_name: str) -> dict:
    return {
        "x": x,
        "y": y,
        "display_y": 63 - y,
        "type_name": type_name,
        "floor_height": 32,
        "ceiling_height": 128,
        "slope_height": 8,
        "texture_floor": 100,
        "texture_wall": 101,
        "texture_ceiling_runtime": 101,
        "texture_ceiling_ua": 101,
        "object_chain_start": 0,
    }


class SceneRecordsButDoesNotApplyTests(unittest.TestCase):
    """The offset must reach the renderer without moving the exported geometry."""

    def _sprite(self, in_tile_x: int):
        tiles = [_scene_tile(x, y, "solid") for y in range(64) for x in range(64)]
        # One open tile, so every neighbour of it is solid rock.
        tiles[5 * 64 + 4] = _scene_tile(4, 5, "open")
        level = {
            "slot_index": 3,
            "level_id_1based": 4,
            "level_name": "Test Level",
            "tiles": tiles,
            "objects": [
                {
                    "slot": 700,
                    "item_id": LOOSE,
                    "flags": 0,
                    "owner": 0,
                    "heading": 0,
                    "in_tile_x": in_tile_x,
                    "in_tile_y": 4,
                    "zpos": 32,
                    "quality": 0,
                    "hidden": False,
                    "tile_refs": [{"x": 4, "y": 5}],
                }
            ],
            "texture_mapping": {"entries": list(TERRAIN_IDS) + [0] * 62},
        }
        scene = build_level_scene(level, _assets(), region=(3, 4, 5, 6))
        return next(obj for obj in scene.objects if obj.kind == "sprite")

    def _xs(self, sprite) -> list[float]:
        return [
            vertex[0]
            for part in sprite.parts
            for triangle in part.triangles
            for vertex in triangle.vertices
        ]

    def test_an_edge_object_records_an_offset(self) -> None:
        sprite = self._sprite(0)
        self.assertIn("wall_clamp", sprite.metadata)
        self.assertGreater(sprite.metadata["wall_clamp"][0], 0.0)

    def test_the_offset_would_clear_the_wall(self) -> None:
        sprite = self._sprite(0)
        dx = sprite.metadata["wall_clamp"][0]
        xs = self._xs(sprite)
        self.assertLess(min(xs), 4.0)  # raw geometry pokes into the wall
        self.assertGreaterEqual(min(xs) + dx, 4.0 - 1e-9)

    def test_vertices_stay_where_the_level_data_puts_them(self) -> None:
        """An export must reproduce the placement, not the presentation."""
        xs = self._xs(self._sprite(0))
        self.assertAlmostEqual((min(xs) + max(xs)) / 2.0, 4 + sub_tile_fraction(0))

    def test_an_object_clear_of_the_wall_records_nothing(self) -> None:
        self.assertNotIn("wall_clamp", self._sprite(4).metadata)


if __name__ == "__main__":
    unittest.main()
