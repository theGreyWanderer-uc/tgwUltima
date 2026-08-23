"""Sprite billboards must keep the source image's top edge at the top.

Both consumers of a sprite quad flip v before sampling: the PyVista renderer
calls ``texture.flip_y()`` on every material, and the GLB export inherits
trimesh's glTF conversion, which flips v on write. Scene-space UVs therefore
have to put v=1 on the upper edge. They previously put v=0 there, so every
sprite in every rendered view and every exported GLB was drawn upside down.

Architecture and executable models are unaffected: terrain UVs come from the
geometry and model UVs are written as ``1.0 - v``, so both already match the
flipped convention.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from PIL import Image

from titan.uw2.map3d import _camera_billboard_part, _camera_basis
from titan.uw2.scene3d import build_level_scene

SPRITE_ITEM = 0x00A0
TERRAIN_IDS = (100, 101)


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
                render_type=0, render_type_name="sprite", height=32
            )
        ),
        animations=SimpleNamespace(get=lambda item_id: None),
        models=None,
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
        "texture_floor": 100,
        "texture_wall": 101,
        "texture_ceiling_runtime": 101,
        "texture_ceiling_ua": 101,
        "object_chain_start": 0,
    }


def _sprite_parts():
    tiles = [_tile(x, y) for y in range(64) for x in range(64)]
    tiles[5 * 64 + 4] = _tile(4, 5, "open")
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
                "heading": 2,
                "in_tile_x": 4,
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
    placed = [obj for obj in scene.objects if obj.kind == "sprite"]
    assert len(placed) == 1, f"expected one sprite, got {len(placed)}"
    return placed[0]


class SpriteExportOrientationTest(unittest.TestCase):
    """The crossed export planes feed the GLB, where trimesh flips v."""

    def test_upper_vertices_carry_v_one(self) -> None:
        sprite = _sprite_parts()
        pairs = [
            (vertex[2], uv[1])
            for part in sprite.parts
            for triangle in part.triangles
            for vertex, uv in zip(triangle.vertices, triangle.uvs)
        ]
        self.assertTrue(pairs)
        top_z = max(z for z, _v in pairs)
        bottom_z = min(z for z, _v in pairs)
        self.assertGreater(top_z, bottom_z, "sprite quad has no height")
        self.assertEqual({v for z, v in pairs if z == top_z}, {1.0})
        self.assertEqual({v for z, v in pairs if z == bottom_z}, {0.0})


class SpriteBillboardOrientationTest(unittest.TestCase):
    """The render quad replaces those planes, and flip_y applies the same way."""

    def _metadata(self) -> dict[str, object]:
        return {
            "center_x": 4.5,
            "center_y": 5.5,
            "base_z": 1.0,
            "width": 0.5,
            "height": 0.5,
        }

    def test_upper_corner_carries_v_one_in_every_view(self) -> None:
        sprite = _sprite_parts()
        part = sprite.parts[0]
        metadata = self._metadata()
        centre_z = metadata["base_z"] + metadata["height"] / 2.0
        for view in ("top", "iso-ne", "iso-sw", "low-ne"):
            with self.subTest(view=view):
                quad = _camera_billboard_part(part, metadata, view)
                _forward, _right, up = _camera_basis(view)
                pairs = [
                    (
                        (vertex[0] - metadata["center_x"]) * up[0]
                        + (vertex[1] - metadata["center_y"]) * up[1]
                        + (vertex[2] - centre_z) * up[2],
                        uv[1],
                    )
                    for triangle in quad.triangles
                    for vertex, uv in zip(triangle.vertices, triangle.uvs)
                ]
                upper = [v for height, v in pairs if height > 1e-9]
                lower = [v for height, v in pairs if height < -1e-9]
                self.assertTrue(upper and lower, f"{view}: degenerate quad")
                self.assertEqual(set(upper), {1.0})
                self.assertEqual(set(lower), {0.0})


if __name__ == "__main__":
    unittest.main()
