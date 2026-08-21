"""Placement fixtures across heading, state, and material source.

The per-rule tests elsewhere check what a rule returns. These check that the
scene builder actually applies it: that a heading rotates placed geometry, that
a roof vertex pins to the tile ceiling however high the object sits, that every
material source the resolver can name reaches the scene, and that state
variants produce visibly different output.

Completion criteria from reference/uw2/uw2-3d-model-gaps.md, amended: the
wall-mounted classes only ever use headings 0, 2, 4 and 6 in the shipped maps,
so real fixtures cannot cover eight. The placement helper is general, so all
eight are exercised synthetically here instead.
"""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.exe_models import ITEM_MODEL_INDEX, ModelTriangle, ModelVertex, UW2Model
from titan.uw2.instances import (
    BRIDGE_ITEM,
    CONTROL_FIRST,
    DOORS,
    LEVER_ITEM,
    TERRAIN,
    THIN_WALL_ITEM,
    TMFLAT,
    TMOBJ,
    WRITING_ITEM,
)
from titan.uw2.scene3d import build_level_scene

TABLE = 0x0158
PILLAR = 0x0160
CEILING_HEIGHT = 128
Z_SCALE = 1.0 / 32.0
CEILING_Z = CEILING_HEIGHT * Z_SCALE

TERRAIN_IDS = (100, 101, 223, 240)


def _model(index: int, *, roof: bool = False) -> UW2Model:
    """One triangle reaching along +x, so a heading rotation is measurable."""
    return UW2Model(
        index=index,
        source_offset=0,
        extents=(1.0, 1.0, 1.0),
        triangles=(
            ModelTriangle(
                (
                    ModelVertex(0.0, 0.0, 0.0, 0.0, 0.0),
                    ModelVertex(0.5, 0.0, 0.0, 1.0, 0.0),
                    ModelVertex(0.0, 0.0, 0.25, 1.0, 1.0, roof),
                ),
                palette_index=27,
                texture_id=6,
                textured=True,
            ),
        ),
        origin=(0.0, 0.0, 0.0),
        collision_half_extents=(0.25, 0.25, 0.125),
    )


class _Models:
    def model_for_item(self, item_id: int):
        index = ITEM_MODEL_INDEX.get(item_id)
        if index is None:
            return None
        return _model(index, roof=item_id == PILLAR)

    def model(self, index: int) -> UW2Model:
        return _model(index)


def _assets() -> SimpleNamespace:
    image = Image.new("RGBA", (8, 8), (120, 90, 60, 255))
    return SimpleNamespace(
        terrain={texture: image for texture in TERRAIN_IDS},
        doors={17: image, 19: image},
        tmobj={index: image for index in range(64)},
        tmflat={index: image for index in range(16)},
        objects={},
        animo={},
        common_objects=SimpleNamespace(
            get=lambda item_id: SimpleNamespace(
                render_type=2, render_type_name="3d_model", height=32
            )
        ),
        animations=SimpleNamespace(get=lambda item_id: None),
        models=_Models(),
        palette=SimpleNamespace(colors=[(10, 20, 30)] * 256),
        strings=None,
    )


def _tile(x: int, y: int, type_name: str = "solid", floor: int = 32) -> dict:
    return {
        "x": x,
        "y": y,
        "display_y": 63 - y,
        "type_name": type_name,
        "floor_height": floor,
        "ceiling_height": CEILING_HEIGHT,
        "slope_height": 8,
        "texture_floor": 100,
        "texture_wall": 101,
        "wall_texture_index": 1,
        "texture_ceiling_runtime": 101,
        "texture_ceiling_ua": 101,
        "object_chain_start": 0,
    }


def _level(objects: list[dict], floor: int = 32) -> dict:
    tiles = [_tile(x, y, floor=floor) for y in range(64) for x in range(64)]
    tiles[5 * 64 + 4] = _tile(4, 5, "open", floor=floor)
    return {
        "slot_index": 0,
        "level_id_1based": 1,
        "level_name": "Matrix",
        "tiles": tiles,
        "objects": objects,
        "texture_mapping": {
            "entries": list(TERRAIN_IDS) + [0] * 60,
            "door_raw": [17, 18, 19, 20, 21, 22],
        },
    }


def _object(item_id: int, **fields) -> dict:
    record = {
        "slot": 700,
        "item_id": item_id,
        "flags": 0,
        "owner": 0,
        "heading": 0,
        "doordir": 0,
        "in_tile_x": 4,
        "in_tile_y": 4,
        "zpos": 32,
        "quality": 0,
        "hidden": False,
        "tile_refs": [{"x": 4, "y": 5}],
    }
    record.update(fields)
    return record


def _build(item_id: int, floor: int = 32, **fields):
    level = _level([_object(item_id, **fields)], floor=floor)
    scene = build_level_scene(level, _assets(), region=(0, 0, 63, 63))
    return scene, scene.objects[0]


def _vertices(placed):
    return [v for p in placed.parts for t in p.triangles for v in t.vertices]


class UW2HeadingPlacementTests(unittest.TestCase):
    """All eight headings, though shipped maps only use four."""

    REACH = 0.5
    """The fixture model's far vertex sits this far along +x when unrotated."""

    def _offset(self, heading: int) -> tuple[float, float]:
        _scene, placed = _build(TABLE, heading=heading)
        centre_x = 4 + 4 / 8.0
        centre_y = 5 + 4 / 8.0
        far = max(
            _vertices(placed),
            key=lambda v: (v[0] - centre_x) ** 2 + (v[1] - centre_y) ** 2,
        )
        return (far[0] - centre_x, far[1] - centre_y)

    def test_each_heading_places_geometry_somewhere_distinct(self) -> None:
        seen = {
            (round(dx, 6), round(dy, 6))
            for dx, dy in (self._offset(h) for h in range(8))
        }

        self.assertEqual(len(seen), 8)

    def test_headings_step_clockwise_by_45_degrees(self) -> None:
        for heading in range(8):
            with self.subTest(heading=heading):
                angle = -heading * math.tau / 8.0
                dx, dy = self._offset(heading)
                self.assertAlmostEqual(dx, self.REACH * math.cos(angle))
                self.assertAlmostEqual(dy, self.REACH * math.sin(angle))

    def test_rotation_preserves_distance_from_the_object_centre(self) -> None:
        for heading in range(8):
            with self.subTest(heading=heading):
                self.assertAlmostEqual(math.hypot(*self._offset(heading)), self.REACH)

    def test_heading_does_not_change_height(self) -> None:
        tops = {
            round(max(v[2] for v in _vertices(_build(TABLE, heading=h)[1])), 6)
            for h in range(8)
        }

        self.assertEqual(len(tops), 1)


class UW2RoofVertexTests(unittest.TestCase):
    """A roof vertex pins to the tile ceiling, whatever the object's base."""

    @staticmethod
    def _roof_z(placed) -> float:
        """The fixture model marks its third vertex as the roof one."""
        return placed.parts[0].triangles[0].vertices[2][2]

    def test_roof_vertex_reaches_the_ceiling(self) -> None:
        _scene, placed = _build(PILLAR)

        self.assertAlmostEqual(self._roof_z(placed), CEILING_Z)

    def test_roof_height_ignores_the_object_base(self) -> None:
        heights = set()
        for zpos in (0, 32, 96, 120):
            _scene, placed = _build(PILLAR, zpos=zpos)
            heights.add(round(self._roof_z(placed), 6))

        self.assertEqual(heights, {round(CEILING_Z, 6)})

    def test_non_roof_vertices_still_ride_the_base(self) -> None:
        # Only the marked vertex pins; the rest of a pillar rises with zpos,
        # which is why a high-set model can reach past the ceiling.
        bases = {
            round(_build(PILLAR, zpos=z)[1].parts[0].triangles[0].vertices[0][2], 6)
            for z in (0, 64)
        }

        self.assertEqual(len(bases), 2)

    def test_a_model_without_roof_vertices_rides_its_base(self) -> None:
        tops = {
            round(max(v[2] for v in _vertices(_build(TABLE, zpos=z)[1])), 6)
            for z in (0, 64)
        }

        self.assertEqual(len(tops), 2)


class UW2MaterialSourceTests(unittest.TestCase):
    """Every source the resolver can name must reach the scene."""

    CASES = (
        (TMOBJ, TABLE, {}, "tmobj_032"),
        (TMFLAT, CONTROL_FIRST + 5, {}, "tmflat_005"),
        (TMOBJ, LEVER_ITEM, {"flags": 3}, "tmobj_007"),
        (TMOBJ, WRITING_ITEM, {"flags": 0}, "tmobj_020"),
        (TMOBJ, BRIDGE_ITEM, {"flags": 0}, "tmobj_030"),
        (TERRAIN, BRIDGE_ITEM, {"flags": 5}, "terrain_240"),
        (TERRAIN, THIN_WALL_ITEM, {"owner": 2}, "terrain_223"),
        (DOORS, 0x0142, {}, "doors_019"),
    )

    def test_every_source_registers_its_material(self) -> None:
        for source, item_id, fields, key in self.CASES:
            with self.subTest(source=source, item=item_id):
                scene, placed = _build(item_id, **fields)
                self.assertIn(key, scene.materials)
                self.assertIn(key, {p.material_key for p in placed.parts})

    def test_all_five_sources_are_exercised(self) -> None:
        self.assertEqual(
            {source for source, _i, _f, _k in self.CASES},
            {TMOBJ, TMFLAT, TERRAIN, DOORS},
        )


class UW2StateVariantTests(unittest.TestCase):
    """State changes must produce visibly different output."""

    def test_each_lever_position_selects_a_different_image(self) -> None:
        keys = set()
        for flags in range(8):
            _scene, placed = _build(LEVER_ITEM, flags=flags)
            keys |= {p.material_key for p in placed.parts}

        self.assertEqual(len(keys), 8)

    def test_a_control_pair_differs_across_its_eight_offset(self) -> None:
        _s1, closed = _build(CONTROL_FIRST + 1)
        _s2, opened = _build(CONTROL_FIRST + 9)

        self.assertNotEqual(
            {p.material_key for p in closed.parts},
            {p.material_key for p in opened.parts},
        )

    def test_an_open_door_differs_from_a_closed_one(self) -> None:
        _s1, closed = _build(0x0140)
        _s2, opened = _build(0x0148, flags=13)

        self.assertNotEqual(
            closed.metadata["door_swing_degrees"],
            opened.metadata["door_swing_degrees"],
        )

    def test_a_raised_portcullis_sits_higher_from_zpos_alone(self) -> None:
        # The raise lives in zpos, not in an added lift.
        _s1, closed = _build(0x0146, zpos=32)
        _s2, opened = _build(0x014E, zpos=56)

        self.assertEqual(opened.metadata["door_lift"], 0.0)
        self.assertGreater(
            max(v[2] for v in _vertices(opened)),
            max(v[2] for v in _vertices(closed)),
        )

    def test_bridge_flags_switch_between_object_and_level_texture(self) -> None:
        _s1, object_textured = _build(BRIDGE_ITEM, flags=0)
        _s2, level_textured = _build(BRIDGE_ITEM, flags=5)

        self.assertEqual(object_textured.metadata["texture_source"], TMOBJ)
        self.assertEqual(level_textured.metadata["texture_source"], TERRAIN)


if __name__ == "__main__":
    unittest.main()
