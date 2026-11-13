"""MD rendering contracts from DOS palette writes and synthetic native light scenes."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from tests.md_fixtures import initial_martian_objlist, resource_library
from tests.md_fixtures import md_game as md_game
from titan.md.cli import md_app
from titan.md.game_profile import MD_PROFILE
from titan.md.gamestate import MartianGameState
from titan.md.lighting import (
    build_martian_light_field,
    build_martian_lightmap,
    martian_light_strength,
    martian_readied_light,
    restore_martian_lamp_posts,
)
from titan.md.map_render import MartianMapRenderer
from titan.md.palette import build_martian_palette
from titan.u6.object import U6Object
from titan.u6.palette import U6Palette
from titan.u6.tileflag import U6TileFlagEntry

_GOLDENS = json.loads(
    (Path(__file__).parent / "fixtures/md_lighting_scenes.json").read_text(
        encoding="utf-8"
    )
)["cases"]

_COORDINATE_GOLDENS = json.loads(
    (Path(__file__).parent / "fixtures/md_lighting_coordinate_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize(
    "case",
    _COORDINATE_GOLDENS,
    ids=[f"terrain-{c['side']}-lamp-{c['lamp_x']}" for c in _COORDINATE_GOLDENS],
)
def test_md_light_objects_keep_ten_bit_coordinates_at_terrain_boundaries(
    case: dict,
) -> None:
    data = initial_martian_objlist()
    data[0x1CF4] = 23
    state = MartianGameState.parse(bytes(data))
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    flags[600].flags = 3
    bases = [0] * 1024
    bases[10] = 600
    level = int(case["side"] == 256)
    field = build_martian_light_field(
        np.full((case["side"], case["side"]), 16, dtype=np.uint8),
        [U6Object(0, case["lamp_x"], 5, level, 10, 0, 0, 0)],
        flags,
        tuple(bases),
        state,
        (0, 0, 11, 11),
        level,
    )
    assert field.levels.ravel().tolist() == case["levels"]
    assert (field.flags & 191).ravel().tolist() == case["flags"]


@pytest.mark.parametrize(
    "case", _GOLDENS, ids=[f"{c['pattern']}-{c['strength']}" for c in _GOLDENS]
)
def test_md_light_field_matches_original_executable_scenes(case: dict) -> None:
    grid = np.full((256, 256), 16, dtype=np.uint8)
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    flags[17].flags, flags[17].terrain = 4, 4
    flags[600].flags = 3 | (4 if case["pattern"] == "opaque_lamp" else 0)
    if case["pattern"] in ("wall", "hidden_lamp"):
        grid[92:109, 102] = 17
    bases = [0] * 1024
    bases[100] = 600
    state = MartianGameState.parse(bytes(initial_martian_objlist()))
    state.in_dream_mode, state.saved_light_level = True, case["strength"]
    objects = [U6Object(0, case["lamp_x"], 100, 0, 100, 0, 0, 0)]
    actual = build_martian_lightmap(
        grid, objects, flags, tuple(bases), state, (95, 95, 11, 11), 0
    )
    assert ["".join(str(v) for v in row) for row in actual] == case["rows"]


@pytest.mark.parametrize(
    "minute,expected",
    [
        (399, 0),
        (400, 2),
        (409, 2),
        (410, 3),
        (420, 4),
        (430, 5),
        (439, 5),
        (440, 7),
        (1040, 7),
        (1041, 5),
        (1050, 5),
        (1060, 4),
        (1070, 3),
        (1080, 2),
        (1081, 0),
    ],
)
def test_md_dawn_and_dusk_use_dos_thresholds(minute: int, expected: int) -> None:
    state = MartianGameState.parse(bytes(initial_martian_objlist()))
    state.clock = replace(state.clock, hour=minute // 60, minute=minute % 60)
    assert martian_light_strength(state, 0) == expected
    assert martian_light_strength(state, 1) == 0
    assert martian_light_strength(state, 1, 3) == 3
    assert martian_light_strength(state, 0, 1) == (1 if expected < 4 else expected)
    state.in_dream_mode, state.saved_light_level = True, 6
    assert martian_light_strength(state, 1, 3) == 6


@pytest.mark.parametrize(
    "hour,powered,frame",
    [(5, True, 7), (6, True, 3), (17, True, 3), (18, True, 7), (23, False, 3)],
)
def test_md_street_lights_use_separate_power_flag_and_night_hours(
    hour: int, powered: bool, frame: int
) -> None:
    data = initial_martian_objlist()
    data[0x1964] = 16 if powered else 4
    data[0x1CFA] = 7
    state = MartianGameState.parse(bytes(data))
    state.clock = replace(state.clock, hour=hour)
    lamp = U6Object(0, 10, 10, 0, 228, 0, 0, 0)
    result = restore_martian_lamp_posts([lamp], state)
    assert result[0].frame_n == frame
    assert lamp.frame_n == 0 and result[0] is not lamp
    assert state.street_lights_active is powered
    assert state.saved_light_level == 7


def test_md_readied_light_excludes_inventory_and_unlit_types() -> None:
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    bases = tuple(range(1024))
    flags[110].flags, flags[112].flags, flags[109].flags = 3, 1, 3
    carried = U6Object(0x10, 1, 0, 0, 110, 0, 0, 0)
    readied = U6Object(0x18, 1, 0, 0, 112, 0, 0, 0)
    unlit = U6Object(0x18, 1, 0, 0, 109, 0, 0, 0)
    assert martian_readied_light([carried, readied, unlit], flags, bases) == 1
    carried.status = 0x18
    assert martian_readied_light([carried, readied], flags, bases) == 3


@pytest.mark.parametrize(
    "selected,first,second,bright",
    [(0, 1, 0, True), (1, 1, 0, False), (1, 0, 1, True), (0, 16, 0, False)],
)
def test_md_brown_berry_vision_follows_selected_actor(
    selected: int, first: int, second: int, bright: bool
) -> None:
    data = initial_martian_objlist()
    data[0x1CF9] = selected
    data[0x1D32], data[0x1D34] = first, second
    data[0x1CF4] = 23
    state = MartianGameState.parse(bytes(data))
    assert state.brown_berry_vision is bright
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(2048)]
    levels = build_martian_lightmap(
        np.full((256, 256), 16, dtype=np.uint8),
        [],
        flags,
        tuple(range(1024)),
        state,
        (95, 95, 11, 11),
        0,
    )
    assert bool(np.all(levels == 4)) is bright


@pytest.mark.parametrize(
    "phase,sources,gray",
    [
        (1, (230, 238, 243, 247, 251), 12),
        (2, (229, 237, 242, 246, 250), 13),
        (8, (231, 239, 243, 247, 251), 19),
        (256, (231, 239, 243, 247, 251), 12),
    ],
)
def test_md_palette_matches_dac_phase_and_gray_pulse(
    phase: int, sources: tuple[int, ...], gray: int
) -> None:
    base = U6Palette()
    base.colors = [(i, 255 - i, i * 7 % 256) for i in range(256)]
    original = list(base.colors)
    result = build_martian_palette(base, phase)
    assert [result.colors[i] for i in (224, 232, 240, 244, 248)] == [
        base.colors[i] for i in sources
    ]
    assert result.colors[255] == (gray * 255 // 63,) * 3
    assert base.colors == original
    assert all(result.colors[i] == base.colors[i] for i in (*range(224), 252, 253, 254))
    assert (
        build_martian_palette(base, 257).colors == build_martian_palette(base, 1).colors
    )
    assert build_martian_palette(base).colors == original


def _install_synthetic_darkness_tiles(game: Path) -> None:
    raw = bytearray(MD_PROFILE.read_resource(game, "MAPTILES.VGA"))
    for level in range(4):
        pixels = bytes(
            255 if level and x % 4 < level else 0 for y in range(16) for x in range(16)
        )
        raw[(268 + level) * 256 : (269 + level) * 256] = pixels
    (game / "MAPTILES.VGA").write_bytes(resource_library(bytes(raw)))


def test_md_lighting_renders_real_mask_tiles_and_isolates_saved_states(
    md_game: Path, tmp_path: Path
) -> None:
    _install_synthetic_darkness_tiles(md_game)
    snapshot = tmp_path / "night"
    snapshot.mkdir()
    # Lighting reads all object blocks even when their visual overlay is disabled.
    for row in range(8):
        for col in range(8):
            (snapshot / f"OBJBLK{chr(65 + col)}{chr(65 + row)}").write_bytes(bytes(2))
    for level in range(5):
        (snapshot / f"OBJBLK{chr(65 + level)}I").write_bytes(bytes(2))
    data = initial_martian_objlist()
    data[0x1CF4] = 23
    (snapshot / "OBJLIST").write_bytes(data)
    renderer = MartianMapRenderer.from_directory(md_game)
    region = (40, 40, 11, 11)
    night = renderer.render_map(region=region, lighting=True, savegame=snapshot)
    assert night.getpixel((0, 0)) == (0, 0, 0)
    assert night.getpixel((5 * 16, 5 * 16)) == (32 * 255 // 63, 0, 0)
    # At a partial-light cell, loaded mask pixels cover black and retain terrain.
    assert night.getpixel((5 * 16, 3 * 16)) == (32 * 255 // 63, 0, 0)
    assert night.getpixel((5 * 16 + 3, 3 * 16)) == (0, 0, 0)
    atlas = renderer.render_map(region=region, savegame=snapshot)
    day = renderer.render_map(region=region, lighting=True)
    assert atlas.getpixel((0, 0)) == day.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    assert (snapshot / "OBJLIST").read_bytes() == data


def test_md_palette_tick_affects_terrain_and_preserves_base_palette(
    md_game: Path,
) -> None:
    raw = bytearray(MD_PROFILE.read_resource(md_game, "MAPTILES.VGA"))
    raw[32 * 256 : 33 * 256] = bytes([224]) * 256
    (md_game / "MAPTILES.VGA").write_bytes(resource_library(bytes(raw)))
    renderer = MartianMapRenderer.from_directory(md_game)
    base = renderer.render_map(region=(0, 0, 1, 1))
    cycled = renderer.render_map(region=(0, 0, 1, 1), palette_tick=1)
    assert base.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    assert cycled.getpixel((0, 0)) == (38 * 255 // 63, 0, 0)
    assert renderer.render_map(region=(0, 0, 1, 1)).tobytes() == base.tobytes()


@pytest.mark.parametrize(
    "arguments",
    [
        {"lighting": True},
        {"lighting": True, "region": (0, 0, 12, 11)},
        {"palette_tick": -1, "region": (0, 0, 1, 1)},
    ],
)
def test_md_invalid_lighting_or_palette_requests_fail(
    md_game: Path, arguments: dict
) -> None:
    with pytest.raises(ValueError, match="Martian Dreams"):
        MartianMapRenderer.from_directory(md_game).render_map(**arguments)


def test_md_cli_lighting_and_palette_render_png(md_game: Path, tmp_path: Path) -> None:
    _install_synthetic_darkness_tiles(md_game)
    output = tmp_path / "lit.png"
    result = CliRunner().invoke(
        md_app,
        [
            "map-render",
            "-g",
            str(md_game),
            "--region",
            "40,40,11,11",
            "--lighting",
            "--palette-tick",
            "3",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.is_file()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--lighting", "--full"],
        ["--lighting", "--region", "0,0,12,11"],
        ["--palette-tick", "-1", "--region", "0,0,1,1"],
    ],
)
def test_md_cli_rejects_invalid_lighting_and_palette_options(
    md_game: Path, arguments: list[str]
) -> None:
    result = CliRunner().invoke(md_app, ["map-render", "-g", str(md_game), *arguments])
    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output
