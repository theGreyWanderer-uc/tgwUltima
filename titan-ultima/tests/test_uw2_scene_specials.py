"""Tests that specially handled UU2 classes reach the 3D scene.

Before the shared instance rules existed, bridges, special texture-map walls,
wall controls, levers, switches, and writing all fell through the scene
builder's model -> sprite -> skip chain and were counted in
``scene.skipped["render_type_3d_model"]``. These tests pin that they are now
placed, carry the material their instance selects, and keep the instance fields
an exporter needs.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.exe_models import (
    ITEM_MODEL_INDEX,
    ModelTriangle,
    ModelVertex,
    UW2Model,
)
from titan.uw2.instances import (
    BRIDGE_ITEM,
    LEVER_ITEM,
    REMOVABLE_WALL_ITEM,
    THIN_WALL_ITEM,
    WRITING_ITEM,
)
from titan.uw2.scene3d import build_level_scene

TERRAIN_IDS = (100, 101, 223, 240)


def _quad_model(index: int) -> UW2Model:
    """A minimal textured two-triangle model, like the shared 0x10 quad."""
    a = ModelVertex(-0.125, 0.0, 0.0, 0.0, 0.0)
    b = ModelVertex(0.125, 0.0, 0.0, 1.0, 0.0)
    c = ModelVertex(0.125, 0.0, 0.25, 1.0, 1.0)
    return UW2Model(
        index=index,
        source_offset=0,
        extents=(0.25, 0.0, 0.25),
        triangles=(
            ModelTriangle((a, b, c), palette_index=27, texture_id=6, textured=True),
        ),
        origin=(0.0, 0.0, 0.0),
        collision_half_extents=(0.125, 0.125, 0.031),
    )


class _Models:
    """Serves the real item->slot mapping so ordinary items still resolve."""

    def model_for_item(self, item_id: int):
        index = ITEM_MODEL_INDEX.get(item_id)
        return None if index is None else _quad_model(index)

    def model(self, index: int) -> UW2Model:
        return _quad_model(index)


class _Strings:
    def get(self, block: int, index: int, default: str = "") -> str:
        return {368: "The plaque reads: ", 70: "LIBRARY "}.get(index, default)


def _assets() -> SimpleNamespace:
    image = Image.new("RGBA", (8, 8), (120, 90, 60, 255))
    return SimpleNamespace(
        terrain={texture: image for texture in TERRAIN_IDS},
        tmobj={index: image for index in range(64)},
        tmflat={index: image for index in range(16)},
        doors={},
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
        strings=_Strings(),
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
        "texture_floor": 100,
        "texture_wall": 101,
        "texture_ceiling_runtime": 101,
        "texture_ceiling_ua": 101,
        "object_chain_start": 0,
    }


def _level(objects: list[dict]) -> dict:
    """A full 64x64 grid of solid tiles with one open tile holding the object.

    Terrain generation walks a tile's neighbours, so the grid has to be
    complete; solid tiles emit no triangles, which keeps the fixture cheap.
    """
    tiles = [_tile(x, y) for y in range(64) for x in range(64)]
    tiles[5 * 64 + 4] = _tile(4, 5, "open")
    return {
        "slot_index": 3,
        "level_id_1based": 4,
        "level_name": "Test Level",
        "tiles": tiles,
        "objects": objects,
        "texture_mapping": {"entries": list(TERRAIN_IDS) + [0] * 60},
    }


def _object(item_id: int, **fields) -> dict:
    record = {
        "slot": 700,
        "item_id": item_id,
        "flags": 0,
        "owner": 0,
        "heading": 2,
        "in_tile_x": 4,
        "in_tile_y": 4,
        "zpos": 32,
        "quality": 0,
        "hidden": False,
        "tile_refs": [{"x": 4, "y": 5}],
    }
    record.update(fields)
    return record


def _build(objects: list[dict]):
    return build_level_scene(_level(objects), _assets(), region=(0, 0, 63, 63))


def _only(scene):
    return scene.objects[0]


class UW2SpecialDispatchTests(unittest.TestCase):
    def test_bridge_is_placed_instead_of_skipped(self) -> None:
        scene = _build([_object(BRIDGE_ITEM, flags=0)])

        self.assertEqual(len(scene.objects), 1)
        self.assertNotIn("render_type_3d_model", scene.skipped)
        self.assertEqual(_only(scene).metadata["texture_source"], "tmobj")
        self.assertEqual(_only(scene).metadata["texture_index"], 30)

    def test_architectural_bridge_uses_a_level_floor_texture(self) -> None:
        # flags 5 -> floor mapping entry 3 -> texture 240.
        scene = _build([_object(BRIDGE_ITEM, flags=5)])

        metadata = _only(scene).metadata
        self.assertEqual(metadata["texture_source"], "terrain")
        self.assertEqual(metadata["texture_role"], "floor")
        self.assertIn("terrain_240", scene.materials)
        self.assertEqual(_only(scene).parts[0].material_key, "terrain_240")

    def test_special_wall_uses_the_owner_named_mapping_entry(self) -> None:
        # owner 2 -> mapping entry 2 -> texture 223.
        scene = _build([_object(THIN_WALL_ITEM, owner=2)])

        metadata = _only(scene).metadata
        self.assertEqual(metadata["texture_source"], "terrain")
        self.assertEqual(metadata["texture_role"], "wall")
        self.assertEqual(_only(scene).parts[0].material_key, "terrain_223")

    def test_removable_wall_is_marked_for_exporters(self) -> None:
        scene = _build([_object(REMOVABLE_WALL_ITEM, owner=1)])

        self.assertTrue(_only(scene).metadata["removable_wall"])
        self.assertTrue(_only(scene).metadata["wall_mounted"])

    def test_control_uses_the_flat_archive(self) -> None:
        scene = _build([_object(0x0175)])

        metadata = _only(scene).metadata
        self.assertEqual(metadata["texture_source"], "tmflat")
        self.assertEqual(metadata["texture_index"], 5)
        self.assertEqual(_only(scene).parts[0].material_key, "tmflat_005")

    def test_lever_position_selects_its_image(self) -> None:
        scene = _build([_object(LEVER_ITEM, flags=3)])

        self.assertEqual(_only(scene).metadata["texture_index"], 7)

    def test_writing_carries_its_readable_text(self) -> None:
        scene = _build([_object(WRITING_ITEM, flags=0, special_property_value=70)])

        metadata = _only(scene).metadata
        self.assertEqual(metadata["writing_prefix_index"], 368)
        self.assertEqual(metadata["writing_message_index"], 70)
        self.assertEqual(metadata["writing_prefix"], "The plaque reads: ")
        self.assertEqual(metadata["writing_text"], "LIBRARY")

    def test_bed_records_owner_colours_without_applying_them(self) -> None:
        scene = _build([_object(0x0167, owner=5)])

        metadata = _only(scene).metadata
        self.assertEqual(metadata["bed_sheet_palette_index"], 25)
        self.assertEqual(metadata["bed_pillow_palette_index"], 20)

    def test_enchantment_bit_is_preserved_as_metadata(self) -> None:
        scene = _build([_object(WRITING_ITEM, flags=8, enchanted=True)])

        self.assertTrue(_only(scene).metadata["enchanted"])
        # ...but does not change the texture the sign selects.
        self.assertEqual(_only(scene).metadata["texture_index"], 20)

    def test_unresolvable_material_still_places_the_object(self) -> None:
        # An owner past the mapping should not drop the object entirely.
        scene = _build([_object(THIN_WALL_ITEM, owner=200)])

        self.assertEqual(len(scene.objects), 1)


if __name__ == "__main__":
    unittest.main()
