"""A stored sub-tile coordinate names one eighth of a tile, taken at its near edge.

An object's ``xpos``/``ypos`` is three bits: the full world coordinate, which
runs 256 units to the tile, truncated to one of eight 32-unit cells. It is
tempting to add the ``0xF`` the game itself adds - ``ObjectCreator.cs``,
``motion_projectile.cs`` and ``spellcasting_class_11.cs`` in UnderworldGodot all
expand ``tile`` and ``xpos`` into a live coordinate that way - but that path
exists to give a *mobile* object somewhere to collide from, not to say where
static scenery is drawn, and adding it pushes wall furniture through the wall.

The shipped levels are laid out on the plain eighth grid. In Castle Britannia a
bed runs 25.25 to 25.75, the shelf at its head 25.75 to 26.00, and the wall face
is at 26.00: each piece meets the next exactly, and only with no bias applied.
UnderworldGodot's ``GetCoordinate`` treats static objects the same way.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.instances import (
    MOBILE_SUB_TILE_BIAS,
    SUB_TILE_CELL,
    SUB_TILE_STEPS,
    SUB_TILE_UNITS,
    sub_tile_fraction,
)
from titan.uw2.scene3d import build_level_scene

SPRITE_ITEM = 0x00A0
TERRAIN_IDS = (100, 101)


class SubTileFractionTests(unittest.TestCase):
    def test_a_step_lands_on_its_cell_edge(self) -> None:
        for step in range(SUB_TILE_STEPS):
            with self.subTest(step=step):
                self.assertEqual(sub_tile_fraction(step), step / 8.0)

    def test_steps_are_evenly_spaced_and_within_the_tile(self) -> None:
        values = [sub_tile_fraction(step) for step in range(SUB_TILE_STEPS)]
        gaps = {round(b - a, 12) for a, b in zip(values, values[1:])}
        self.assertEqual(gaps, {round(SUB_TILE_CELL / SUB_TILE_UNITS, 12)})
        self.assertEqual(values[0], 0.0)
        self.assertLess(values[-1], 1.0)

    def test_out_of_range_input_is_clamped(self) -> None:
        self.assertEqual(sub_tile_fraction(-3), sub_tile_fraction(0))
        self.assertEqual(sub_tile_fraction(99), sub_tile_fraction(SUB_TILE_STEPS - 1))

    def test_the_engines_mobile_bias_is_recorded_but_not_applied(self) -> None:
        """0xF belongs to collision, and putting it here buried shelves in walls."""
        self.assertEqual(MOBILE_SUB_TILE_BIAS, 15)
        self.assertNotEqual(
            sub_tile_fraction(7),
            (7 * SUB_TILE_CELL + MOBILE_SUB_TILE_BIAS) / SUB_TILE_UNITS,
        )

    def test_a_quarter_tile_fixture_at_the_far_cell_reaches_the_wall_exactly(
        self,
    ) -> None:
        """The shelf case: half a quarter-tile model, centred on cell 7."""
        self.assertEqual(sub_tile_fraction(7) + 0.125, 1.0)


def _assets() -> SimpleNamespace:
    image = Image.new("RGBA", (8, 8), (120, 90, 60, 255))
    return SimpleNamespace(
        terrain={texture: image for texture in TERRAIN_IDS},
        tmobj={},
        tmflat={},
        doors={},
        animo={},
        objects={SPRITE_ITEM: image},
        common_objects=SimpleNamespace(
            get=lambda item_id: SimpleNamespace(
                render_type=0, render_type_name="sprite", height=8
            )
        ),
        animations=SimpleNamespace(get=lambda item_id: None),
        models=None,
        palette=SimpleNamespace(colors=[(10, 20, 30)] * 256),
        strings=None,
    )


def _tile(x: int, y: int, type_name: str = "open") -> dict:
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


class ScenePlacementUsesTheFractionTests(unittest.TestCase):
    """The scene builder must route through the helper, not its own arithmetic."""

    def _centre(self, in_tile_x: int, in_tile_y: int) -> tuple[float, float]:
        # A 3x3 of open tiles, so nothing here is clamped away from a wall.
        tiles = [_tile(x, y, "solid") for y in range(64) for x in range(64)]
        for y in range(4, 7):
            for x in range(3, 6):
                tiles[y * 64 + x] = _tile(x, y)
        level = {
            "slot_index": 3,
            "level_id_1based": 4,
            "level_name": "Test Level",
            "tiles": tiles,
            "objects": [
                {
                    "slot": 700,
                    "item_id": SPRITE_ITEM,
                    "flags": 0,
                    "owner": 0,
                    "heading": 0,
                    "in_tile_x": in_tile_x,
                    "in_tile_y": in_tile_y,
                    "zpos": 32,
                    "quality": 0,
                    "hidden": False,
                    "tile_refs": [{"x": 4, "y": 5}],
                }
            ],
            "texture_mapping": {"entries": list(TERRAIN_IDS) + [0] * 62},
        }
        scene = build_level_scene(level, _assets(), region=(2, 3, 6, 7))
        sprite = next(obj for obj in scene.objects if obj.kind == "sprite")
        self.assertNotIn("wall_clamp", sprite.metadata)
        points = [
            vertex
            for part in sprite.parts
            for triangle in part.triangles
            for vertex in triangle.vertices
        ]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

    def test_sprite_centre_follows_the_sub_tile_cell(self) -> None:
        for step in range(SUB_TILE_STEPS):
            with self.subTest(step=step):
                centre_x, centre_y = self._centre(step, step)
                self.assertAlmostEqual(centre_x, 4 + sub_tile_fraction(step))
                self.assertAlmostEqual(centre_y, 5 + sub_tile_fraction(step))


if __name__ == "__main__":
    unittest.main()
