"""Tests for UU2 door classification, state, and composed scene objects.

A doorway is two executable models: the fixed frame (`0x01`) whose roof
vertices reach the tile ceiling, and the moving panel (`0x0E`, or `0x0F` for a
secret door). Hinged doors swing about one vertical edge chosen by `doordir`;
portcullises rise instead. Rules follow UnderworldGodot's `door.cs` and are
checked against every door in the shipped levels.
"""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.exe_models import ModelTriangle, ModelVertex, UW2Model
from titan.uw2.instances import (
    DOOR_FRAME_MODEL,
    DOOR_PANEL_MODEL,
    DOORS,
    SECRET_DOOR_PANEL_MODEL,
    TERRAIN,
    door_animation_frames,
    door_animation_index,
    door_class,
    door_lift,
    door_panel_model,
    door_swing_radians,
    door_texture_id,
    door_texture_slot,
    is_door,
    is_open_door,
    is_portcullis,
    is_secret_door,
    object_material,
    portcullis_bar_model,
)
from titan.uw2.scene3d import build_level_scene

CLOSED_DOOR = 0x0140
CLOSED_PORTCULLIS = 0x0146
CLOSED_SECRET = 0x0147
OPEN_DOOR = 0x0148
OPEN_PORTCULLIS = 0x014E


class UW2DoorClassificationTests(unittest.TestCase):
    def test_the_door_range_is_recognised(self) -> None:
        self.assertTrue(is_door(0x0140))
        self.assertTrue(is_door(0x014F))
        self.assertFalse(is_door(0x013F))
        self.assertFalse(is_door(0x0150))

    def test_class_index_is_the_low_nibble(self) -> None:
        self.assertEqual(door_class(CLOSED_DOOR), 0)
        self.assertEqual(door_class(OPEN_PORTCULLIS), 14)

    def test_open_forms_start_at_class_eight(self) -> None:
        for item_id in range(0x0140, 0x0148):
            with self.subTest(item=item_id):
                self.assertFalse(is_open_door(item_id))
        for item_id in range(0x0148, 0x0150):
            with self.subTest(item=item_id):
                self.assertTrue(is_open_door(item_id))

    def test_portcullis_and_secret_door_are_paired_across_states(self) -> None:
        self.assertTrue(is_portcullis(CLOSED_PORTCULLIS))
        self.assertTrue(is_portcullis(OPEN_PORTCULLIS))
        self.assertTrue(is_secret_door(CLOSED_SECRET))
        self.assertTrue(is_secret_door(0x014F))
        self.assertFalse(is_portcullis(CLOSED_DOOR))
        self.assertFalse(is_secret_door(CLOSED_DOOR))

    def test_secret_doors_use_their_own_panel_model(self) -> None:
        self.assertEqual(door_panel_model(CLOSED_DOOR), DOOR_PANEL_MODEL)
        self.assertEqual(door_panel_model(CLOSED_SECRET), SECRET_DOOR_PANEL_MODEL)


class UW2DoorTextureTests(unittest.TestCase):
    def test_ordinary_doors_take_one_of_the_six_slots(self) -> None:
        for offset in range(6):
            with self.subTest(offset=offset):
                reference = object_material(0x0140 + offset)
                self.assertEqual(reference.source, DOORS)
                self.assertEqual(reference.index, offset)

    def test_open_forms_reuse_the_same_slots(self) -> None:
        self.assertEqual(door_texture_slot(OPEN_DOOR), door_texture_slot(CLOSED_DOOR))

    def test_portcullis_has_no_door_slot(self) -> None:
        # Only six door textures exist; the portcullis falls past them.
        self.assertIsNone(door_texture_slot(CLOSED_PORTCULLIS))
        self.assertIsNone(object_material(CLOSED_PORTCULLIS))

    def test_secret_door_wears_its_tile_wall(self) -> None:
        tile = {"wall_texture_index": 12}

        reference = object_material(CLOSED_SECRET, tile=tile)

        self.assertEqual(reference.source, TERRAIN)
        self.assertEqual(reference.index, 12)

    def test_secret_door_without_tile_context_resolves_to_nothing(self) -> None:
        self.assertIsNone(object_material(CLOSED_SECRET))

    def test_door_slot_resolves_through_the_level(self) -> None:
        level = {"texture_mapping": {"door_raw": [17, 18, 19, 20, 21, 22]}}

        reference = object_material(0x0142)

        self.assertEqual(door_texture_id(reference, level), 19)

    def test_out_of_range_slot_resolves_to_nothing(self) -> None:
        level = {"texture_mapping": {"door_raw": [17]}}

        self.assertIsNone(door_texture_id(object_material(0x0145), level))


class UW2DoorStateTests(unittest.TestCase):
    def test_frame_counts_differ_for_portcullises(self) -> None:
        self.assertEqual(door_animation_frames(CLOSED_DOOR), 5)
        self.assertEqual(door_animation_frames(CLOSED_PORTCULLIS), 4)

    def test_closed_doors_sit_at_step_zero(self) -> None:
        self.assertEqual(door_animation_index(CLOSED_DOOR, 0), 0)
        self.assertEqual(door_swing_radians(CLOSED_DOOR, 0, 0), 0.0)

    def test_open_doors_are_fully_open_regardless_of_flags(self) -> None:
        # The shipped open forms carry flags well past the step count - 13 and
        # 12 against counts of 5 and 4 - so the item ID decides the state.
        self.assertEqual(door_animation_index(OPEN_DOOR, 13), 5)
        self.assertEqual(door_animation_index(OPEN_PORTCULLIS, 12), 4)
        self.assertAlmostEqual(door_swing_radians(OPEN_DOOR, 13, 0), math.pi / 2.0)

    def test_a_closed_door_caught_mid_swing_uses_its_step(self) -> None:
        self.assertEqual(door_animation_index(CLOSED_DOOR, 2), 2)
        self.assertAlmostEqual(
            door_swing_radians(CLOSED_DOOR, 2, 0), 2 * (math.pi / 2.0) / 5
        )

    def test_doordir_reverses_the_swing(self) -> None:
        forward = door_swing_radians(OPEN_DOOR, 13, 0)
        reverse = door_swing_radians(OPEN_DOOR, 13, 1)

        self.assertAlmostEqual(forward, -reverse)

    def test_portcullis_rises_instead_of_swinging(self) -> None:
        self.assertEqual(door_swing_radians(OPEN_PORTCULLIS, 12, 0), 0.0)
        self.assertAlmostEqual(door_lift(OPEN_PORTCULLIS, 12), 0.8)
        self.assertEqual(door_lift(CLOSED_PORTCULLIS, 0), 0.0)

    def test_hinged_doors_never_lift(self) -> None:
        self.assertEqual(door_lift(OPEN_DOOR, 13), 0.0)


def _model(index: int, width: float) -> UW2Model:
    a = ModelVertex(-width, 0.0, 0.0, 0.0, 0.0)
    b = ModelVertex(width, 0.0, 0.0, 1.0, 0.0)
    c = ModelVertex(width, 0.031, 0.8, 1.0, 1.0)
    return UW2Model(
        index=index,
        source_offset=0,
        extents=(width * 2, 0.8, 0.031),
        triangles=(
            ModelTriangle((a, b, c), palette_index=143, texture_id=1, textured=True),
        ),
        origin=(0.0, 0.0, 0.0),
        collision_half_extents=(width, 0.4, 0.015),
    )


class _Models:
    def model_for_item(self, item_id: int):
        return None

    def model(self, index: int) -> UW2Model:
        return _model(index, 0.5 if index == DOOR_FRAME_MODEL else 0.25)


def _assets() -> SimpleNamespace:
    image = Image.new("RGBA", (8, 8), (120, 90, 60, 255))
    return SimpleNamespace(
        terrain={200: image, 201: image},
        doors={17: image, 19: image},
        tmobj={},
        tmflat={},
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


def _tile(x: int, y: int, type_name: str = "solid") -> dict:
    return {
        "x": x,
        "y": y,
        "display_y": 63 - y,
        "type_name": type_name,
        "floor_height": 32,
        "ceiling_height": 128,
        "slope_height": 8,
        "texture_floor": 200,
        "texture_wall": 201,
        "wall_texture_index": 1,
        "texture_ceiling_runtime": 201,
        "texture_ceiling_ua": 201,
        "object_chain_start": 0,
    }


def _level(objects: list[dict]) -> dict:
    tiles = [_tile(x, y) for y in range(64) for x in range(64)]
    tiles[5 * 64 + 4] = _tile(4, 5, "open")
    return {
        "slot_index": 0,
        "level_id_1based": 1,
        "level_name": "Test",
        "tiles": tiles,
        "objects": objects,
        "texture_mapping": {
            "entries": [200, 201] + [0] * 62,
            "door_raw": [17, 18, 19, 20, 21, 22],
        },
    }


def _door(item_id: int, **fields) -> dict:
    record = {
        "slot": 700,
        "item_id": item_id,
        "flags": 0,
        "owner": 0,
        "heading": 2,
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


def _build(item_id: int, **fields):
    scene = build_level_scene(_level([_door(item_id, **fields)]), _assets())
    return scene, scene.objects[0]


class UW2PortcullisGeometryTests(unittest.TestCase):
    """The bar grid is reconstructed; UW2.EXE has no portcullis model.

    Slot 0x0E decodes to an eight-vertex solid box - the ordinary door panel -
    so drawing it for a portcullis gives a slab across the doorway.
    """

    def setUp(self) -> None:
        self.panel = _model(DOOR_PANEL_MODEL, 0.25)
        self.bars = portcullis_bar_model(self.panel)

    def _bounds(self, model):
        points = [(v.x, v.y, v.z) for t in model.triangles for v in t.vertices]
        return tuple(
            (min(p[axis] for p in points), max(p[axis] for p in points))
            for axis in range(3)
        )

    def test_three_vertical_and_four_cross_bars_are_closed_boxes(self) -> None:
        self.assertEqual(len(self.bars.triangles), 7 * 12)

    def test_the_grid_fills_the_panel_bounding_box(self) -> None:
        self.assertEqual(self._bounds(self.bars), self._bounds(self.panel))

    def test_the_grid_is_not_a_solid_slab(self) -> None:
        # A solid box has two distinct x planes; a barred grid has many more.
        panel_x = {round(v.x, 4) for t in self.panel.triangles for v in t.vertices}
        bars_x = {round(v.x, 4) for t in self.bars.triangles for v in t.vertices}

        self.assertEqual(len(panel_x), 2)
        self.assertGreater(len(bars_x), len(panel_x))

    def test_model_identity_is_preserved(self) -> None:
        self.assertEqual(self.bars.index, self.panel.index)
        self.assertEqual(self.bars.extents, self.panel.extents)
        self.assertEqual(self.bars.origin, self.panel.origin)

    def test_bars_inherit_the_panel_colour(self) -> None:
        self.assertEqual(
            {t.palette_index for t in self.bars.triangles},
            {self.panel.triangles[0].palette_index},
        )

    def test_an_empty_panel_is_returned_untouched(self) -> None:
        empty = UW2Model(
            index=DOOR_PANEL_MODEL,
            source_offset=0,
            extents=(0.0, 0.0, 0.0),
            triangles=(),
        )

        self.assertIs(portcullis_bar_model(empty), empty)


class UW2DoorSceneTests(unittest.TestCase):
    def test_a_door_is_one_object_with_frame_and_panel_parts(self) -> None:
        scene, door = _build(CLOSED_DOOR)

        self.assertEqual(door.kind, "door")
        self.assertNotIn("render_type_3d_model", scene.skipped)
        names = " ".join(part.name for part in door.parts)
        self.assertIn("_frame_", names)
        self.assertIn("_panel_", names)

    def test_frame_and_panel_models_are_both_recorded(self) -> None:
        _scene, door = _build(CLOSED_DOOR)

        self.assertEqual(door.metadata["model_index"], DOOR_FRAME_MODEL)
        self.assertEqual(door.metadata["panel_model_index"], DOOR_PANEL_MODEL)

    def test_panel_uses_the_level_door_texture(self) -> None:
        scene, _door = _build(0x0142)

        # slot 2 -> door_raw[2] = 19
        self.assertIn("doors_019", scene.materials)

    def test_secret_door_panel_uses_the_wall_texture(self) -> None:
        scene, door = _build(CLOSED_SECRET)

        self.assertTrue(door.metadata["door_secret"])
        self.assertEqual(door.metadata["panel_model_index"], SECRET_DOOR_PANEL_MODEL)
        self.assertNotIn("doors_017", scene.materials)
        self.assertIn("terrain_201", scene.materials)

    def test_state_is_recorded_for_exporters(self) -> None:
        _scene, door = _build(OPEN_PORTCULLIS, flags=12)

        self.assertTrue(door.metadata["door_open"])
        self.assertTrue(door.metadata["door_portcullis"])
        self.assertEqual(door.metadata["door_swing_degrees"], 0.0)
        self.assertAlmostEqual(door.metadata["door_lift"], 0.8)

    def test_reconstructed_geometry_is_declared(self) -> None:
        # An exporter must be able to tell rebuilt bars from decoded geometry.
        _scene, portcullis = _build(CLOSED_PORTCULLIS)
        _scene2, ordinary = _build(CLOSED_DOOR)

        self.assertEqual(portcullis.metadata["door_geometry"], "reconstructed")
        self.assertEqual(ordinary.metadata["door_geometry"], "decoded")

    def test_a_portcullis_is_barred_rather_than_solid(self) -> None:
        _scene, portcullis = _build(CLOSED_PORTCULLIS)
        _scene2, ordinary = _build(CLOSED_DOOR)

        self.assertGreater(
            portcullis.metadata["triangle_count"],
            ordinary.metadata["triangle_count"],
        )

    def test_an_open_door_records_its_swing(self) -> None:
        _scene, door = _build(OPEN_DOOR, flags=13)

        self.assertAlmostEqual(door.metadata["door_swing_degrees"], 90.0)

    def test_swinging_moves_the_panel_but_not_the_frame(self) -> None:
        _closed_scene, closed = _build(CLOSED_DOOR)
        _open_scene, opened = _build(OPEN_DOOR, flags=13)

        def part_named(door, fragment):
            return next(p for p in door.parts if fragment in p.name)

        self.assertEqual(
            part_named(closed, "_frame_").triangles[0].vertices,
            part_named(opened, "_frame_").triangles[0].vertices,
        )
        self.assertNotEqual(
            part_named(closed, "_panel_").triangles[0].vertices,
            part_named(opened, "_panel_").triangles[0].vertices,
        )


if __name__ == "__main__":
    unittest.main()
