"""Visible wall and overlay decisions captured from original MD code on synthetic inputs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tests.md_fixtures import object_block, resource_library
from tests.md_fixtures import md_game as md_game
from titan.md.lighting import MartianLightField
from titan.md.map_render import MartianMapRenderer
from titan.md.viewport import MartianViewport, resolve_martian_view_tiles
from titan.u6.object import U6Object
from titan.u6.tileflag import U6TileFlagEntry

_GOLDENS = json.loads(
    (Path(__file__).parent / "fixtures/md_viewport_cases.json").read_text(
        encoding="utf-8"
    )
)


def _tile_flags() -> list[U6TileFlagEntry]:
    return [
        U6TileFlagEntry(i, int(_GOLDENS["terrain_flags"].get(str(i), 0)), 0, 0, 0)
        for i in range(2048)
    ]


def _wall_field(
    tile: int,
    mask: int,
    diagonal: bool,
    neighbors: int,
    visible: bool = True,
    light: int = 4,
) -> MartianLightField:
    terrain = np.full((40, 40), 16, dtype=np.uint8)
    flags = np.full((40, 40), 128, dtype=np.uint8)
    levels = np.full((40, 40), 4, dtype=np.uint8)
    terrain[20, 20] = tile
    if neighbors == 1:
        terrain[19, 20] = terrain[20, 19] = 40
    for y, x, bit in ((19, 20, 8), (20, 21, 4), (21, 20, 2), (20, 19, 1)):
        if not mask & bit:
            flags[y, x] = 0
    if neighbors == 2:
        flags[19, 20] |= 8
        flags[20, 19] |= 8
    if not diagonal:
        flags[21, 21] &= 127
    if not visible:
        flags[20, 20] &= 127
    levels[20, 20] = light
    return MartianLightField(terrain, flags, levels, (15, 15, 11, 11))


@pytest.mark.parametrize("tile", sorted({row[0] for row in _GOLDENS["wall_rows"]}))
def test_md_wall_choices_match_original_code(tile: int) -> None:
    tileflags = _tile_flags()
    for value, mask, diagonal, neighbors, expected in _GOLDENS["wall_rows"]:
        if value != tile:
            continue
        field = _wall_field(value, mask, bool(diagonal), neighbors)
        original = field.terrain.copy()
        result = resolve_martian_view_tiles(field, tileflags)
        assert result.dtype == np.uint16
        assert result[5, 5] == expected, (value, mask, diagonal, neighbors)
        assert np.array_equal(field.terrain, original)


def test_md_unseen_and_unlit_tiles_match_original_code() -> None:
    for tile, visible, light, expected in _GOLDENS["dark_rows"]:
        field = _wall_field(tile, 15, True, 1, bool(visible), light)
        assert resolve_martian_view_tiles(field, _tile_flags())[5, 5] == expected


@pytest.mark.parametrize("case", _GOLDENS["grid_cases"])
def test_md_complete_view_matches_original_selector(case: dict) -> None:
    neighbors = ("floor", "walls", "object_walls").index(case["neighbors"])
    field = _wall_field(case["tile"], case["mask"], case["southeast"], neighbors)
    assert (
        resolve_martian_view_tiles(field, _tile_flags()).ravel().tolist()
        == case["grid"]
    )


def test_md_object_wall_corners_and_lower_tiles_match_original_compositor() -> None:
    tileflags = _tile_flags()
    for background, mask, kind, tile, expected_base, expected_drawn in _GOLDENS[
        "object_rows"
    ]:
        field = _wall_field(16, 15, True, 0)
        for y, x, bit in ((20, 21, 4), (21, 20, 2), (21, 21, 1)):
            if not mask & bit:
                field.flags[y, x] &= 127
        terrain = np.full((11, 11), 16, dtype=np.uint16)
        terrain[5, 5] = background
        viewport = MartianViewport(terrain, field, (95, 95), tileflags)
        tileflags[tile].extra = 32 if kind == 2 else 0
        basetile = [0] * 1024
        basetile[10] = tile
        obj = U6Object(0, 100, 100, 0, 10, 0, 0, 0)
        viewport.restore_lower_terrain([obj], tuple(basetile), 0)
        assert viewport.terrain[5, 5] == expected_base
        assert (viewport.allows_cell(100, 100) and tile < 2041) == bool(expected_drawn)
        assert obj.obj_n == 10 and obj.frame_n == 0


def test_md_brown_vision_keeps_stored_wall_art() -> None:
    field = _wall_field(160, 0, False, 0)
    field.bypass_visibility = True
    assert resolve_martian_view_tiles(field, _tile_flags())[5, 5] == 160
    field.flags.fill(3)
    view = MartianViewport(
        resolve_martian_view_tiles(field, _tile_flags()), field, (95, 95), _tile_flags()
    )
    assert not view.allows_cell(100, 100)
    assert view.allows_cell(99, 100)


def test_md_revealed_lower_cell_is_applied_before_wall_clipping() -> None:
    field = _wall_field(160, 0, False, 0)
    field.flags[20, 20] = 128
    flags = _tile_flags()
    flags[601].extra = 32
    flags[601].terrain = 0
    view = MartianViewport(
        np.full((11, 11), 160, dtype=np.uint16), field, (95, 95), flags
    )
    bases = [0] * 1024
    bases[10] = 601
    obj = U6Object(2, 100, 100, 0, 10, 0, 0, 0)
    view.restore_lower_terrain([obj], tuple(bases), 0)
    assert not view.allows_cell(100, 100)
    view.restore_lower_terrain([obj], tuple(bases), 0, show_invisible=True)
    assert view.terrain[5, 5] == 601
    assert view.allows_cell(100, 100)


@pytest.mark.parametrize("anchor,width,double", [(4, 7, False), (5, 5, True)])
def test_md_renderer_hides_object_cells_on_unseen_wall_corners(
    md_game: Path, anchor: int, width: int, double: bool
) -> None:
    chunks = bytearray([16] * 64)
    for y in range(8):
        chunks[y * 8 + 4] = 160
    (md_game / "CHUNKS").write_bytes(chunks)
    flags = bytearray((md_game / "TILEFLAG").read_bytes())
    for tile in (160, *range(336, 342)):
        flags[tile], flags[2048 + tile] = 0xF6, 4
    if double:
        flags[2048 + 600] = 0x80
    (md_game / "TILEFLAG").write_bytes(flags)
    (md_game / "LZOBJBLK").write_bytes(
        resource_library(object_block(anchor, 5) + bytes(126))
    )
    renderer = MartianMapRenderer.from_directory(md_game)
    atlas = renderer.render_map(region=(0, 0, width, 11), objects=True)
    view = renderer.render_map(region=(0, 0, width, 11), objects=True, lighting=True)
    assert atlas.getpixel((64, 80)) == (((600 - int(double)) % 64) * 255 // 63, 0, 0)
    assert view.getpixel((64, 80)) == (19 * 255 // 63, 0, 0)
