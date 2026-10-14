"""U8 shape import quantising never uses index 255, titan's "no pixel" marker."""

import numpy as np
from PIL import Image

from titan.palette import U8Palette
from titan.u8.shape import U8Shape
from titan.u8.u7_shape_convert import _quantize_to_palette


def _palette():
    pal = U8Palette()
    pal.colors = [(i, i, i) for i in range(256)]
    pal.colors[255] = (24, 125, 125)   # retail U8 index 255 (teal)
    pal.colors[200] = (30, 120, 120)   # nearest other teal
    pal.colors[217] = (72, 36, 12)     # a dirt brown
    return pal


def _image(pixels):
    img = Image.new("RGBA", (len(pixels), 1))
    img.putdata(pixels)
    return img


def test_index_255_colour_maps_to_nearest_other_index():
    result = U8Shape.quantize_to_palette(
        _image([(24, 125, 125, 255)]), _palette())
    assert result[0, 0] == 200


def test_exact_colours_map_exactly_and_alpha_still_means_transparent():
    result = U8Shape.quantize_to_palette(
        _image([(72, 36, 12, 255), (72, 36, 12, 0)]), _palette())
    assert result[0, 0] == 217
    assert result[0, 1] == 0xFF


def test_index_255_coloured_pixel_survives_encode_and_decode():
    frame = U8Shape.Frame()
    frame.width, frame.height = 3, 1
    frame.pixels = U8Shape.quantize_to_palette(
        _image([(24, 125, 125, 255), (0, 0, 0, 0), (72, 36, 12, 255)]),
        _palette())
    shape = U8Shape()
    shape.frames = [frame]
    decoded = U8Shape.from_data(shape.to_bytes()).frames[0].pixels
    assert decoded.tolist() == [[200, 0xFF, 217]]


def test_u7_conversion_quantiser_never_returns_255_for_opaque_pixels():
    result = _quantize_to_palette(
        _image([(24, 125, 125, 255), (0, 0, 0, 0)]), _palette())
    assert result[0, 0] == 200
    assert result[0, 1] == 0xFF
