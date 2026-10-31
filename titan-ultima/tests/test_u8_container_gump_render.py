"""Verified storage indexing and native-pixel bounded inventory layouts."""

from dataclasses import asdict
import struct

import pytest
from PIL import Image

from titan.u8.container_gump_render import U8GumpItemSprite, compose_u8_container_gump
from titan.u8.gumpage import U8GumpAreas, U8GumpItemArea


def sprite(number, *, size=(3, 2), origin=(0, 0), saved=(0, 0), color="red"):
    return U8GumpItemSprite(
        number,
        76,
        number,
        Image.new("RGBA", size, color),
        *origin,
        *saved,
        editor=number == 5,
    )


def test_gumpage_shape_minus_one_index_and_signed_empty_records():
    raw = struct.pack("<12h", -3, -2, 10, 8, 0, 0, 0, 0, 10, 51, 137, 90)
    data = U8GumpAreas.from_bytes(raw)
    assert data.raw_data == raw
    assert asdict(data.get_area(1)) == dict(
        shape=1, left=-3, top=-2, right=10, bottom=8
    )
    assert data.get_area(2).width == data.get_area(2).height == 0
    assert (data.get_area(3).width, data.get_area(3).height) == (127, 39)
    for number in (0, -1, 4):
        with pytest.raises(ValueError, match="no storage rectangle"):
            data.get_area(number)


@pytest.mark.parametrize("raw", [b"", b"short", b"\x00" * 9])
def test_gumpage_rejects_partial_records(raw):
    with pytest.raises(ValueError, match="8-byte rectangles"):
        U8GumpAreas.from_bytes(raw)


def test_random_scatter_keeps_native_pixels_and_artwork_outside_area():
    art = Image.new("RGBA", (30, 20), (20, 30, 40, 255))
    original = art.tobytes()
    area = U8GumpItemArea(7, 4, 5, 26, 15)
    sprites = [sprite(number) for number in range(1, 6)]
    sprites[0].image.putpixel((1, 0), (90, 80, 70, 0))
    result = compose_u8_container_gump(art, area, sprites, seed=73)
    assert result.image.size == art.size
    assert art.tobytes() == original
    assert len(result.placements) == 5
    assert not result.diagnostics
    for item in result.placements:
        assert area.left <= item.left <= area.right - item.width
        assert area.top <= item.top <= area.bottom - item.height
        assert (item.width, item.height, item.clipped, item.overlap_area) == (
            3,
            2,
            False,
            0,
        )
        assert result.image.getpixel((item.left, item.top)) == (255, 0, 0, 255)
    first = result.placements[0]
    assert result.image.getpixel((first.left + 1, first.top)) == art.getpixel((0, 0))
    for y in range(art.height):
        for x in range(art.width):
            if not (area.left <= x < area.right and area.top <= y < area.bottom):
                assert result.image.getpixel((x, y)) == art.getpixel((x, y))
    assert result.placements[-1].editor
    repeat = compose_u8_container_gump(art, area, sprites, seed=73)
    assert (
        repeat.placements == result.placements
        and repeat.image.tobytes() == result.image.tobytes()
    )
    assert (
        compose_u8_container_gump(art, area, sprites, seed=74).placements
        != result.placements
    )


def test_saved_positions_use_both_draw_origins_and_native_signed_bytes():
    art = Image.new("RGBA", (50, 30))
    area = U8GumpItemArea(7, 4, 5, 40, 25)
    result = compose_u8_container_gump(
        art,
        area,
        [sprite(1, origin=(2, 1), saved=(8, 6))],
        gump_origin=(3, 2),
        layout="saved",
    )
    item = result.placements[0]
    assert (item.left, item.top, item.anchor_x, item.anchor_y) == (13, 12, 8, 6)
    assert item.position_source == "saved"
    result = compose_u8_container_gump(
        art,
        area,
        [sprite(1, saved=(254, 192)), sprite(2, saved=(191, 191)), sprite(3)],
        layout="saved",
    )
    assert (result.placements[0].left, result.placements[0].top) == (5, 6)
    assert (result.placements[1].left, result.placements[1].top) == (37, 23)
    assert result.placements[2].position_source == "random"


def test_crowded_and_oversized_items_are_bounded_without_resizing():
    art = Image.new("RGBA", (8, 8))
    area = U8GumpItemArea(7, 2, 2, 5, 5)
    big = sprite(1, size=(5, 5))
    big.image.putpixel((0, 0), (1, 2, 3, 255))
    big.image.putpixel((2, 2), (4, 5, 6, 255))
    result = compose_u8_container_gump(art, area, [big])
    assert result.placements[0].clipped
    assert result.image.getpixel((2, 2)) == (1, 2, 3, 255)
    assert result.image.getpixel((4, 4)) == (4, 5, 6, 255)
    result = compose_u8_container_gump(art, area, [big, sprite(2)])
    assert result.placements[1].overlap_area == 6
    assert len(result.diagnostics) == 2


@pytest.mark.parametrize(
    "area",
    [
        U8GumpItemArea(6, 0, 0, 0, 0),
        U8GumpItemArea(7, 8, 2, 4, 6),
        U8GumpItemArea(7, 50, 60, 80, 90),
    ],
)
def test_unusable_rectangles_are_rejected(area):
    with pytest.raises(ValueError, match="GUMPAGE"):
        compose_u8_container_gump(Image.new("RGBA", (10, 10)), area, [])


def test_partly_outside_rectangle_is_intersected_and_diagnosed():
    result = compose_u8_container_gump(
        Image.new("RGBA", (10, 10)), U8GumpItemArea(7, -3, -2, 8, 7), [sprite(1)]
    )
    assert result.pixel_area == (0, 0, 8, 7)
    assert "extends outside artwork" in result.diagnostics[0]


def test_unknown_layout_rejected():
    with pytest.raises(ValueError, match="random or saved"):
        compose_u8_container_gump(
            Image.new("RGBA", (10, 10)),
            U8GumpItemArea(7, 0, 0, 8, 8),
            [],
            layout="guess",
        )
