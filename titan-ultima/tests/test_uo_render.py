"""Tests for UO isometric map rendering helpers."""

from __future__ import annotations

import struct

import numpy as np

from titan.uo.hue import UOHue, UOHuesFile
from titan.uo.map import UOMap
from titan.uo.render import (
    UOArtSource,
    UOHueTable,
    UOMapRenderer,
    _Draw,
    _CELL_ORDER,
    _rasterize_quad,
    _vertex_normal,
)
from titan.uo.tiledata import UOLandTile, UOStaticTile, UOTileData


def _static_art(width: int, height: int, color: int) -> bytes:
    """Encode a solid static: one run per row."""
    rows = b"".join(struct.pack("<HH", 0, width) + struct.pack("<H", color) * width + b"\0\0\0\0" for _ in range(height))
    row_words = 2 + width + 2
    table = b"".join(struct.pack("<H", y * row_words) for y in range(height))
    return struct.pack("<Ihh", 0, width, height) + table + rows


def _static_tile(tile_id, flags=0, height=0, name="thing"):
    return UOStaticTile(tile_id, flags, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, height, name)


def test_land_art_fills_the_diamond():
    data = struct.pack("<1012H", *([0x7C00] * 1012))
    pixels = UOArtSource._decode_land(data)
    assert pixels.shape == (44, 44)
    assert int((pixels != 0).sum()) == 1012
    assert pixels[0, 21] and pixels[0, 22] and not pixels[0, 20]
    assert pixels[21, 0] and pixels[22, 0] and pixels[43, 21] and not pixels[43, 20]


def test_static_art_runs():
    pixels = UOArtSource._decode_static(_static_art(3, 2, 0x001F))
    assert pixels.shape == (2, 3)
    assert (pixels == 0x001F).all()


def test_hue_uses_entry_minus_one_and_partial_hits_grey_only():
    ramp = tuple(range(0x100, 0x120))
    hues = UOHuesFile(
        [
            UOHue(0, 0, 0, tuple([0x1234] * 32), 0, 0, "first"),
            UOHue(1, 0, 1, ramp, 0, 0, "second"),
        ]
    )
    table = UOHueTable(hues)
    grey = (5 << 10) | (5 << 5) | 5
    red = 5 << 10
    pixels = np.array([[grey, red, 0]], dtype=np.uint16)

    full = table.apply(pixels, 2, partial=False)
    assert list(full[0]) == [0x105, 0x105, 0]
    partial = table.apply(pixels, 2, partial=True)
    assert list(partial[0]) == [0x105, red, 0]


def test_cell_order_land_first_on_tie_then_shorter_then_foliage_last():
    blank = dict(pixels=None, mask=None, dx=0, dy=0)
    land = _Draw(z=0, priority=True, **blank)
    floor = _Draw(z=0, priority=False, height=0, **blank)
    table = _Draw(z=0, priority=False, height=6, **blank)
    canopy = _Draw(z=-5, priority=False, foliage=True, **blank)
    high = _Draw(z=10, priority=False, **blank)
    ordered = sorted([canopy, high, table, floor, land], key=_CELL_ORDER)
    assert ordered == [land, floor, table, high, canopy]

    wall = _Draw(z=0, priority=False, occluder=True, height=20, **blank)
    upper = _Draw(z=10, priority=False, surface=True, **blank)
    assert sorted([wall, upper], key=_CELL_ORDER) == [upper, wall]


def test_flat_quad_covers_the_diamond_and_flat_normal_is_up():
    texture = np.full((64, 64), 0x7FFF, dtype=np.uint16)
    rgb, mask, ox, oy = _rasterize_quad(texture, False, 0, 0, 0, ((0, 0), (63, 0), (63, 63), (0, 63)))
    assert (ox, oy) == (-22, 0)
    assert mask.shape == (45, 45)
    assert mask[22, 22] and mask[0, 22] and mask[22, 0] and not mask[0, 0]
    assert (rgb[mask] == 255).all()
    assert _vertex_normal(3, 3, 3, 3, 3) == (0.0, 0.0, 1.0)
    nx, ny, nz = _vertex_normal(0, 4, 0, 0, 0)
    assert nz > 0 and abs(nx * nx + ny * ny + nz * nz - 1) < 1e-9


def test_render_draws_land_then_static_on_top():
    width = height = 16
    land = bytearray()
    for _ in range(4):
        land += struct.pack("<I", 0) + struct.pack("<Hb", 3, 0) * 64
    index = struct.pack("<III", 0, 7, 0) + struct.pack("<III", 0xFFFFFFFF, 0, 0) * 3
    statics = struct.pack("<HBBbH", 0x10, 4, 4, 0, 0)
    facet = UOMap(bytes(land), index, statics, width, height)

    land_art = struct.pack("<1012H", *([0x03E0] * 1012))
    static_art = _static_art(4, 4, 0x7C00)
    art = UOArtSource(lambda idx: land_art if idx == 3 else static_art if idx == 0x4010 else None)
    tiledata = UOTileData(
        is_new_format=True,
        land=[UOLandTile(i, 0, 0, "grass") for i in range(4)],
        statics=[_static_tile(i) for i in range(0x20)],
    )
    image = UOMapRenderer(facet, art, tiledata).render(4, 4, 200, 160)
    pixels = np.asarray(image)

    assert image.size == (200, 160)
    green = (pixels == (0, 255, 0)).all(axis=2).sum()
    red = (pixels == (255, 0, 0)).all(axis=2).sum()
    assert green > 1000
    # Static is bottom-anchored on its cell's diamond, centred on its column.
    # Its lowest rows sit in the diamond's tip, where the nearer (5,4)/(4,5)
    # land diamonds are drawn later and overlap it, as in the client.
    bottom = 160 // 2 - 22 + 44
    assert (pixels[bottom - 4, 98:102] == (255, 0, 0)).all()
    assert 0 < red < 16
    ys, xs = np.nonzero((pixels == (255, 0, 0)).all(axis=2))
    assert set(xs) <= {98, 99, 100, 101}
    assert ys.min() == bottom - 4 and ys.max() < bottom


def _flat_facet_renderer(width=16, height=16):
    blocks = (width // 8) * (height // 8)
    land = (struct.pack("<I", 0) + struct.pack("<Hb", 3, 0) * 64) * blocks
    index = struct.pack("<III", 0xFFFFFFFF, 0, 0) * blocks
    facet = UOMap(land, index, b"", width, height)
    land_art = struct.pack("<1012H", *([0x03E0] * 1012))
    art = UOArtSource(lambda idx: land_art if idx == 3 else None)
    tiledata = UOTileData(
        is_new_format=True,
        land=[UOLandTile(i, 0, 0, "grass") for i in range(4)],
        statics=[],
    )
    return UOMapRenderer(facet, art, tiledata)


def test_render_window_uses_global_screen_space():
    from titan.uo.render import SCREEN_TOP_PAD

    renderer = _flat_facet_renderer()
    full_w, full_h = renderer.facet_screen_size()
    assert full_w == 32 * 22

    # Cell (0, 0)'s north vertex is at ((0 - 0 + 16) * 22, SCREEN_TOP_PAD).
    image = np.asarray(renderer.render_window(16 * 22 - 22, SCREEN_TOP_PAD, 44, 44))
    assert (image[21, 0] == (0, 255, 0)).all() and (image[0, 21] == (0, 255, 0)).all()
    assert not image[0, 0].any()

    # Above the facet is empty.
    assert not np.asarray(renderer.render_window(0, 0, 64, 64)).any()


def test_facet_chunks_cover_only_the_diamond():
    from titan.uo.tiles import _facet_chunks

    renderer = _flat_facet_renderer(64, 64)
    full_w, full_h = renderer.facet_screen_size()
    chunk = 256
    chunks = set(_facet_chunks(renderer, chunk))
    all_chunks = {
        (cx, cy)
        for cx in range(-(-full_w // chunk))
        for cy in range(-(-full_h // chunk))
    }
    assert chunks <= all_chunks
    for cx, cy in all_chunks - chunks:
        assert not np.asarray(
            renderer.render_window(cx * chunk, cy * chunk, chunk, chunk)
        ).any()


def test_translucent_draw_blends_at_client_alpha():
    from titan.uo.render import TRANSLUCENT_ALPHA, _blit

    canvas = np.zeros((1, 2, 3), dtype=np.uint8)
    canvas[:] = (0, 0, 200)
    pixels = np.full((1, 2, 3), 255, dtype=np.uint8)
    mask = np.array([[True, False]])
    _blit(canvas, _Draw(z=0, priority=False, pixels=pixels, mask=mask, dx=0, dy=0, alpha=TRANSLUCENT_ALPHA))

    expected = [round(c + (255 - c) * 178 / 255) for c in (0, 0, 200)]
    assert list(canvas[0, 0]) == expected
    assert list(canvas[0, 1]) == [0, 0, 200]
