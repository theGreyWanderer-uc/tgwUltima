"""MD background overlaps verified against original compositor decisions, without retail art."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from tests.md_fixtures import object_block, resource_library
from tests.md_fixtures import md_game as md_game
from titan.md.game_profile import MD_PROFILE
from titan.md.map_render import MartianMapRenderer
from titan.u6.map_objects import overlay_map_objects
from titan.u6.object import U6Object
from titan.u6.palette import U6Palette
from titan.u6.tile import U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlagEntry

_NATIVE_CASES = json.loads(
    (Path(__file__).parent / "fixtures/md_background_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("transparent", [False, True])
@pytest.mark.parametrize(
    "case",
    _NATIVE_CASES,
    ids=[f"{c['name']}-reverse-{c['reverse']}" for c in _NATIVE_CASES],
)
def test_md_background_pixels_match_original_compositor(
    case: dict, transparent: bool
) -> None:
    colors = [(i, i, i) for i in range(256)]
    palette = U6Palette()
    palette.colors = colors
    raw_tiles = [bytes([i % 251]) * 256 for i in range(2048)]
    if transparent:
        raw_tiles[600] = bytes([600 % 251]) + bytes([255]) * 255
    tiles = U6Tiles(raw_tiles)
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    for tile, (flag, extra) in case["flags"].items():
        flags[int(tile)].flags, flags[int(tile)].extra = flag, extra
    bases = [0] * 1024
    objects = []
    for alias, (x, y, tile) in enumerate(case["placements"], 1):
        bases[alias] = tile
        objects.append(U6Object(0, x, y, 0, alias, 0, 0, 0))
    actual = Image.new("RGB", (176, 176), colors[16])
    overlay_map_objects(
        actual, objects, tiles, palette, flags, tuple(bases), U6AnimData([]), MD_PROFILE
    )
    expected = Image.new("RGB", actual.size)
    for cell, background in enumerate(case["backgrounds"]):
        x, y = cell % 11 * 16, cell // 11 * 16
        expected.paste(tiles.to_pil_image(background, palette), (x, y))
        overlays = case["overlays_head_first"].get(str(cell), [])
        # These controlled cases intentionally have at most one overlay per
        # cell, making native background/overlay classification unambiguous.
        assert len(overlays) <= 1
        for tile in overlays:
            sprite = tiles.to_pil_image(tile, palette, transparent=True)
            expected.paste(sprite, (x, y), sprite)
    assert actual.tobytes() == expected.tobytes(), case["name"]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("lighting", [False, True])
@pytest.mark.parametrize(
    "invisible,show_invisible", [(False, False), (True, False), (True, True)]
)
def test_md_renderer_background_order_and_visibility(
    md_game: Path, reverse: bool, lighting: bool, invisible: bool, show_invisible: bool
) -> None:
    bases = bytearray((md_game / "BASETILE").read_bytes())
    struct.pack_into("<H", bases, 22, 601)
    (md_game / "BASETILE").write_bytes(bases)
    flags = bytearray(7168)
    flags[2048 + 601] = 16  # Background classification overrides this foreground bit.
    flags[5120 + 601] = 32
    (md_game / "TILEFLAG").write_bytes(flags)
    raw = bytearray((md_game / "OBJTILES.VGA").read_bytes())
    offset = (600 - 512) * 256
    raw[offset : offset + 256] = bytes([24]) + bytes([255]) * 255
    (md_game / "OBJTILES.VGA").write_bytes(raw)
    ordinary = object_block(10, 10)[2:]
    background = bytearray(ordinary)
    background[4] = 11
    background[0] = 2 if invisible else 0
    records = [ordinary, bytes(background)]
    if reverse:
        records.reverse()
    (md_game / "LZOBJBLK").write_bytes(
        resource_library(struct.pack("<H", 2) + b"".join(records) + bytes(126))
    )
    renderer = MartianMapRenderer.from_directory(md_game)
    image = renderer.render_map(
        region=(10, 10, 1, 1),
        objects=True,
        lighting=lighting,
        show_invisible=show_invisible,
    )
    assert image.getpixel((0, 0)) == (24 * 255 // 63, 0, 0)
    underlying = 32 if invisible and not show_invisible else 25
    assert image.getpixel((8, 8)) == (underlying * 255 // 63, 0, 0)
