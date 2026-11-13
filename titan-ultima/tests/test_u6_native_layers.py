"""Compare U6 stack decisions with goldens captured from original executable bytes."""

from __future__ import annotations

import json
import contextlib
import io
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from tests.test_u6_cli import _make_synthetic_gamedir
from titan.u6.cli import cmd_map_render
from titan.u6.map_layers import build_u6_object_stacks
from titan.u6.object import U6Object, pack_position
from titan.u6.tileflag import U6TileFlagEntry

_GOLDENS = json.loads(
    (Path(__file__).parent / "fixtures" / "u6_layer_cases.json").read_text()
)["cases"]


def test_u6_debug_visibility_reveals_hidden_egg_marker() -> None:
    bases = [0] * 1024
    bases[335] = 2047
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    egg = U6Object(2, 5, 5, 0, 335, 0, 1, 0)
    assert not build_u6_object_stacks([egg], bases, flags)
    shown = build_u6_object_stacks([egg], bases, flags, show_invisible=True)
    assert [cell.tile_num for cell in shown[(5, 5, 0)].overlays] == [2047]


@pytest.mark.parametrize("case", _GOLDENS, ids=lambda c: f"{c['name']}_{c['reverse']}")
def test_u6_cell_stacks_match_original_executable(case: dict) -> None:
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    for number, (flag, extra) in case["flags"].items():
        flags[int(number)].flags, flags[int(number)].extra = flag, extra
    bases = [0] * 1024
    bases[335] = 2047
    objects = []
    for i, (x, y, tile) in enumerate(case["placements"]):
        bases[i] = tile
        objects.append(U6Object(0, x, y, 0, i, 0, 1, 0))
    stacks = build_u6_object_stacks(objects, bases, flags, bounds=(0, 0, 11, 11))
    backgrounds = [16] * 121
    overlays = {}
    for (x, y, _z), stack in stacks.items():
        if stack.background is not None:
            backgrounds[y * 11 + x] = stack.background.tile_num
        if stack.overlays:
            overlays[str(y * 11 + x)] = [cell.tile_num for cell in stack.overlays]
    assert backgrounds == case["backgrounds"]
    assert overlays == case["overlays_bottom_to_top"]


@pytest.mark.parametrize("case", _GOLDENS, ids=lambda c: f"{c['name']}_{c['reverse']}")
def test_u6_cli_pixels_follow_original_cell_stacks(case: dict, tmp_path: Path) -> None:
    _make_synthetic_gamedir(str(tmp_path))
    bases = bytearray(2048)
    struct.pack_into("<H", bases, 335 * 2, 2047)
    records = []
    for i, (x, y, tile) in enumerate(case["placements"]):
        struct.pack_into("<H", bases, i * 2, tile)
        records.append(struct.pack("<8B", 0, *pack_position(x, y, 0), i, 0, 1, 0))
    (tmp_path / "BASETILE").write_bytes(bases)
    (tmp_path / "LZOBJBLK").write_bytes(
        struct.pack("<H", len(records)) + b"".join(records) + bytes(126)
    )
    flags = bytearray(7168)
    for number, (flag, extra) in case["flags"].items():
        flags[2048 + int(number)], flags[5120 + int(number)] = flag, extra
    (tmp_path / "TILEFLAG").write_bytes(flags)
    # Distinct striped synthetic sprites expose ordering through transparent holes.
    tile_numbers = sorted(
        {
            t
            for _x, _y, anchor in case["placements"]
            for t in range(anchor - 3, anchor + 1)
        }
    )
    art = bytearray((tmp_path / "OBJTILES.VGA").read_bytes())
    palette = bytearray(1024)
    sprites = {}
    for index, tile in enumerate(tile_numbers, 7):
        color = ((index * 7) % 64, (index * 13) % 64, (index * 23) % 64)
        palette[index * 3 : index * 3 + 3] = bytes(color)
        raw = bytes(index if (p + tile) % 3 else 255 for p in range(256))
        art[(tile - 512) * 256 : (tile - 511) * 256] = raw
        rgba = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        rgb = tuple(c * 255 // 63 for c in color)
        rgba.putdata([(*rgb, 255) if p != 255 else (0, 0, 0, 0) for p in raw])
        sprites[tile] = rgba
    (tmp_path / "OBJTILES.VGA").write_bytes(art)
    (tmp_path / "U6PAL").write_bytes(palette)
    output = tmp_path / "native_layers.png"
    with contextlib.redirect_stdout(io.StringIO()):
        assert (
            cmd_map_render(
                SimpleNamespace(
                    gamedir=str(tmp_path),
                    palette=None,
                    region="0,0,11,11",
                    dungeon=None,
                    full=False,
                    tick=0,
                    objects=True,
                    output=str(output),
                )
            )
            == 0
        )
    expected = Image.new("RGBA", (176, 176), (0, 0, 0, 255))
    for cell in range(121):
        xy = (cell % 11 * 16, cell // 11 * 16)
        background = case["backgrounds"][cell]
        if background != 16:
            selected = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
            selected.alpha_composite(sprites[background])
            expected.paste(selected, xy)
        for tile in case["overlays_bottom_to_top"].get(str(cell), []):
            expected.alpha_composite(sprites[tile], xy)
    with Image.open(output) as actual:
        assert actual.convert("RGBA").tobytes() == expected.tobytes()
