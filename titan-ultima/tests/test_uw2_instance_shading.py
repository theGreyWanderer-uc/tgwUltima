"""Shading has to follow the colour a face actually wears, not the model's.

An instance can replace a model face's colour: bedding is picked from the bed's
owner, a moongate's tint comes off its link. The Gouraud work shades a face
across its corners, and taking those corners from the model's own colour while
the face wore another turned every owner-coloured bed in Castle Britannia blue -
the bed model's third colour is ``0x4D``, a light blue - and drew blue moongates
with a red gradient, because the model's stand-in colour is the red ``0x21``.

Where the replacement is a point on a ramp, as a moongate's is, the shading
works on it. Where it is an exact entry, as an owner's is, there is no ramp to
step down and the face stays flat.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.exe_models import ITEM_MODEL_INDEX, ModelTriangle, ModelVertex, UW2Model
from titan.uw2.instances import BED_ITEM, MOONGATE_ITEM, bed_palette_indices
from titan.uw2.scene3d import build_level_scene

BED_LINEN = 77  # the model colour bed_face_palette swaps for an owner's
TERRAIN_IDS = (100, 101)

# a blue ramp and a brown one, far enough apart that a mix-up is obvious
PALETTE = [(0, 0, 0)] * 256
for step in range(6):
    PALETTE[BED_LINEN + step] = (92 - step * 15, 92 - step * 15, 252 - step * 20)
    PALETTE[0x21 + step] = (212 - step * 30, 16, 36 - step * 5)
    PALETTE[0x4F + step] = (0, 0, 252 - step * 30)
    PALETTE[0x31 + step] = (136 - step * 20, 68 - step * 10, 0)


def _model(index: int, palette_index: int, corner_shades) -> UW2Model:
    a = ModelVertex(-0.2, 0.0, 0.0)
    b = ModelVertex(0.2, 0.0, 0.0)
    c = ModelVertex(0.2, 0.0, 0.3)
    return UW2Model(
        index=index,
        source_offset=0,
        extents=(0.4, 0.0, 0.3),
        triangles=(
            ModelTriangle(
                (a, b, c), palette_index=palette_index, corner_shades=corner_shades
            ),
        ),
        origin=(0.0, 0.0, 0.0),
        collision_half_extents=(0.2, 0.2, 0.15),
    )


class _Models:
    def __init__(self, model: UW2Model) -> None:
        self._model = model

    def model_for_item(self, item_id: int):
        return self._model if item_id in ITEM_MODEL_INDEX else None

    def model(self, index: int) -> UW2Model:
        return self._model


def _assets(model: UW2Model) -> SimpleNamespace:
    image = Image.new("RGBA", (8, 8), (120, 90, 60, 255))
    return SimpleNamespace(
        terrain={texture: image for texture in TERRAIN_IDS},
        tmobj={index: image for index in range(64)},
        tmflat={},
        doors={},
        objects={},
        animo={},
        common_objects=SimpleNamespace(
            get=lambda item_id: SimpleNamespace(
                render_type=2, render_type_name="3d_model", height=32
            )
        ),
        animations=SimpleNamespace(get=lambda item_id: None),
        models=_Models(model),
        palette=SimpleNamespace(colors=PALETTE),
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
        "texture_floor": 100,
        "texture_wall": 101,
        "wall_texture_index": 1,
        "texture_ceiling_runtime": 101,
        "texture_ceiling_ua": 101,
        "object_chain_start": 0,
    }


def _corner_colors(item_id: int, model: UW2Model, **fields):
    tiles = [_tile(x, y) for y in range(64) for x in range(64)]
    tiles[5 * 64 + 4] = _tile(4, 5, "open")
    obj = {
        "slot": 700,
        "item_id": item_id,
        "flags": 0,
        "owner": 0,
        "heading": 0,
        "in_tile_x": 4,
        "in_tile_y": 4,
        "zpos": 32,
        "quality": 0,
        "hidden": False,
        "tile_refs": [{"x": 4, "y": 5}],
    }
    obj.update(fields)
    level = {
        "slot_index": 3,
        "level_id_1based": 4,
        "level_name": "Test Level",
        "tiles": tiles,
        "objects": [obj],
        "texture_mapping": {"entries": list(TERRAIN_IDS) + [0] * 62},
    }
    scene = build_level_scene(level, _assets(model), region=(3, 4, 5, 6))
    placed = next(o for o in scene.objects if o.kind == "model")
    triangle = placed.parts[0].triangles[0]
    material = scene.materials[placed.parts[0].material_key]
    return triangle.colors, material.color


class BedShadingTests(unittest.TestCase):
    """Bedding takes an exact owner colour, so it is not shaded at all."""

    def test_owner_bedding_is_not_left_wearing_the_model_colour(self) -> None:
        colors, material = _corner_colors(
            BED_ITEM, _model(0x1D, BED_LINEN, (0, 2, 5)), owner=3
        )
        sheet, _pillow = bed_palette_indices(3)
        self.assertIsNone(colors, "an exact owner colour has no ramp to shade")
        self.assertEqual(material[:3], tuple(PALETTE[sheet]))

    def test_the_frame_keeps_the_model_colour_and_its_shading(self) -> None:
        """Only the linen face is owner-coloured; the rest still shades."""
        colors, _material = _corner_colors(
            BED_ITEM, _model(0x1D, 0x31, (0, 2, 5)), owner=3
        )
        self.assertIsNotNone(colors)
        self.assertEqual(colors[0][:3], tuple(PALETTE[0x31]))
        self.assertEqual(colors[2][:3], tuple(PALETTE[0x31 + 5]))


class MoongateShadingTests(unittest.TestCase):
    """A gate's link colour is a ramp base, so the gradient works on it."""

    def test_the_gradient_follows_the_link_colour(self) -> None:
        colors, _material = _corner_colors(
            MOONGATE_ITEM,
            _model(0x17, 0x21, (0, 1, 3)),
            quantity_or_link=512 + 0x4F,
        )
        self.assertIsNotNone(colors)
        for corner, step in zip(colors, (0, 1, 3)):
            self.assertEqual(corner[:3], tuple(PALETTE[0x4F + step]))

    def test_it_does_not_keep_the_models_stand_in_colour(self) -> None:
        colors, _material = _corner_colors(
            MOONGATE_ITEM,
            _model(0x17, 0x21, (0, 1, 3)),
            quantity_or_link=512 + 0x4F,
        )
        reds = {tuple(PALETTE[0x21 + step]) for step in range(6)}
        self.assertFalse({corner[:3] for corner in colors} & reds)


if __name__ == "__main__":
    unittest.main()
