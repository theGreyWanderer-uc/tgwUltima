"""Tests for direct OBJECTS.GR and ANIMO.GR map sprite composition."""

from types import SimpleNamespace

from PIL import Image

from titan.uw2.exe_models import ModelTriangle, ModelVertex, UW2Model
from titan.uw2.map_render import make_model_primitives, make_sprite_primitives
from titan.uw2.palette import UW2Palette


class CommonObjects:
    def get(self, _item_id: int) -> SimpleNamespace:
        return SimpleNamespace(render_type=0)


class ModelCommonObjects:
    def get(self, _item_id: int) -> SimpleNamespace:
        return SimpleNamespace(render_type=2)


class Animations:
    def get(self, item_id: int) -> SimpleNamespace:
        assert item_id == 457
        return SimpleNamespace(start_frame=5, frame_count=4)


class Models:
    def model_for_item(self, item_id: int) -> UW2Model | None:
        if item_id != 344:
            return None
        return UW2Model(
            index=0x18,
            source_offset=0,
            extents=(0.5, 0.5, 0.5),
            triangles=(
                ModelTriangle(
                    vertices=(
                        ModelVertex(-0.25, -0.25, 0.0),
                        ModelVertex(0.25, -0.25, 0.0),
                        ModelVertex(0.0, 0.25, 0.5),
                    ),
                    palette_index=1,
                ),
            ),
        )


def test_fountain_body_and_selected_animo_frame_share_anchor() -> None:
    tile = {
        "x": 31,
        "y": 41,
        "floor_height": 88,
        "object_chain_start": 926,
    }
    object_map = {
        926: {
            "slot": 926,
            "item_id": 302,
            "zpos": 88,
            "in_tile_x": 4,
            "in_tile_y": 4,
            "next": 925,
        },
        925: {
            "slot": 925,
            "item_id": 457,
            "zpos": 89,
            "in_tile_x": 4,
            "in_tile_y": 4,
            "next": 0,
        },
    }
    body = Image.new("RGBA", (18, 19), (80, 80, 80, 255))
    selected_water = Image.new("RGBA", (18, 24), (0, 100, 255, 255))
    args = SimpleNamespace(
        tick=1,
        object_scale=2.0,
        tile_size=64,
        orientation="display",
        floor_height_per_lift=8.0,
        lift_pixels=4.0,
    )

    sprites = make_sprite_primitives(
        tile,
        object_map,
        0,
        64,
        args,
        {302: body},
        {6: selected_water},
        CommonObjects(),  # type: ignore[arg-type]
        Animations(),  # type: ignore[arg-type]
    )

    assert [sprite.item_id for sprite in sprites] == [302, 457]
    assert sprites[0].x == sprites[1].x
    assert sprites[0].y == sprites[1].y
    assert sprites[0].image.size == (36, 38)
    assert sprites[1].image.size == (36, 48)
    assert sprites[1].image.getpixel((0, 0)) == (0, 100, 255, 255)


def test_projects_executable_table_triangle() -> None:
    tile = {
        "x": 28,
        "y": 34,
        "floor_height": 96,
        "object_chain_start": 514,
    }
    object_map = {
        514: {
            "slot": 514,
            "item_id": 344,
            "zpos": 96,
            "in_tile_x": 4,
            "in_tile_y": 4,
            "heading": 0,
            "next": 0,
        }
    }
    args = SimpleNamespace(
        model_scale=2.0,
        tile_size=64,
        orientation="display",
        floor_height_per_lift=8.0,
        lift_pixels=4.0,
    )
    palette = UW2Palette(colors=((0, 0, 0), (120, 80, 40)) + ((0, 0, 0),) * 254)

    triangles = make_model_primitives(
        tile,
        object_map,
        0,
        64,
        args,
        Models(),  # type: ignore[arg-type]
        palette,
    )

    assert len(triangles) == 1
    assert triangles[0].fill[3] == 255
    assert len(set(triangles[0].points)) == 3


def test_uses_table_inventory_icon_as_background_sprite() -> None:
    tile = {
        "x": 28,
        "y": 34,
        "floor_height": 96,
        "object_chain_start": 514,
    }
    object_map = {
        514: {
            "slot": 514,
            "item_id": 344,
            "zpos": 96,
            "in_tile_x": 7,
            "in_tile_y": 1,
            "next": 0,
        }
    }
    args = SimpleNamespace(
        model_style="icons",
        model_icon_scale=2.0,
        no_models=False,
        tile_size=64,
        orientation="display",
        floor_height_per_lift=8.0,
        lift_pixels=4.0,
    )
    table_icon = Image.new("RGBA", (16, 16), (120, 80, 40, 255))

    sprites = make_sprite_primitives(
        tile,
        object_map,
        0,
        64,
        args,
        {344: table_icon},
        {},
        ModelCommonObjects(),  # type: ignore[arg-type]
        None,
    )

    assert len(sprites) == 1
    assert sprites[0].item_id == 344
    assert sprites[0].background is True
    assert sprites[0].image.size == (32, 32)


def test_rejects_model_slot_that_is_not_a_verified_icon() -> None:
    tile = {
        "x": 10,
        "y": 10,
        "floor_height": 96,
        "object_chain_start": 1,
    }
    object_map = {
        1: {
            "slot": 1,
            "item_id": 359,
            "zpos": 96,
            "in_tile_x": 4,
            "in_tile_y": 4,
            "next": 0,
        }
    }
    args = SimpleNamespace(
        model_style="icons",
        no_models=False,
        tile_size=64,
        orientation="display",
        floor_height_per_lift=8.0,
        lift_pixels=4.0,
    )

    sprites = make_sprite_primitives(
        tile,
        object_map,
        0,
        64,
        args,
        {359: Image.new("RGBA", (16, 16))},
        {},
        ModelCommonObjects(),  # type: ignore[arg-type]
        None,
    )

    assert sprites == []
