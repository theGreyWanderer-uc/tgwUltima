"""Palette-limited font ramps retain shade progression and safe indices."""

from itertools import product

import pytest

from titan.fonts import wizard
from titan.fonts.palette import (
    GRADIENT_PRESETS,
    GradientPreset,
    resolve_gradient_to_indices,
)
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape


@pytest.fixture
def main_palette_sample():
    """Representative stable warm/cool shades and greys from U7 palette 0."""
    palette = U7Palette()
    for index, colour in {
        20: (255, 89, 101),
        21: (255, 56, 76),
        22: (255, 28, 52),
        23: (222, 20, 40),
        24: (194, 12, 28),
        25: (165, 8, 20),
        26: (137, 4, 12),
        35: (255, 174, 93),
        36: (255, 157, 60),
        37: (255, 141, 28),
        38: (255, 125, 0),
        39: (226, 109, 0),
        40: (194, 97, 0),
        41: (165, 80, 0),
        74: (186, 186, 255),
        75: (153, 153, 255),
        76: (125, 125, 255),
        77: (93, 93, 255),
        91: (178, 72, 178),
        92: (161, 40, 161),
        93: (141, 16, 141),
        94: (125, 0, 125),
        95: (109, 0, 109),
        120: (206, 206, 206),
        121: (190, 190, 190),
        122: (174, 174, 174),
        123: (157, 157, 157),
        124: (141, 141, 141),
        125: (125, 125, 125),
        184: (141, 60, 12),
        185: (125, 44, 0),
        195: (206, 206, 255),
        196: (194, 194, 255),
        197: (182, 182, 255),
        198: (170, 170, 255),
        199: (157, 157, 255),
    }.items():
        palette.colors[index] = colour
    return palette


def test_sunrise_uses_a_ramp_instead_of_five_identical_orange_steps(
    main_palette_sample,
):
    indices, stroke = resolve_gradient_to_indices(
        GRADIENT_PRESETS["sunrise"], main_palette_sample
    )
    colours = [main_palette_sample.colors[i] for i in indices]
    assert len(set(colours)) >= 4
    assert colours[0][0] > 200 and colours[0][1] < 100
    assert colours[-1][0] > 200 and colours[-1][1] > 100
    assert all(r > g and r > b for r, g, b in colours)
    assert stroke == 0


@pytest.mark.parametrize("key", ["blood_red", "sin_city_red", "firewatch"])
def test_short_red_ramps_do_not_alternate_shades(key, main_palette_sample):
    indices, _ = resolve_gradient_to_indices(GRADIENT_PRESETS[key], main_palette_sample)
    runs = [
        index for i, index in enumerate(indices) if i == 0 or index != indices[i - 1]
    ]
    assert len(runs) == len(set(runs))
    assert len(runs) >= 2


@pytest.mark.parametrize("key", ["cool_sky", "sexy_blue", "reef"])
def test_blue_presets_keep_blue_shades_despite_nearby_greys(key, main_palette_sample):
    indices, _ = resolve_gradient_to_indices(GRADIENT_PRESETS[key], main_palette_sample)
    colours = [main_palette_sample.colors[i] for i in indices]
    assert all(b > r and b > g for r, g, b in colours)
    assert len(set(colours)) >= 3


@pytest.mark.parametrize("key", list(GRADIENT_PRESETS))
@pytest.mark.parametrize("allow_cycling", [False, True])
def test_every_preset_uses_the_supplied_palette_and_is_deterministic(
    key, allow_cycling
):
    palette = U7Palette()
    palette.colors[:216] = list(product(range(0, 256, 51), repeat=3))
    palette.colors[224:255] = [(50, 100, 150)] * 31
    original = list(palette.colors)
    first = resolve_gradient_to_indices(
        GRADIENT_PRESETS[key], palette, 8, allow_cycling=allow_cycling
    )
    assert first == resolve_gradient_to_indices(
        GRADIENT_PRESETS[key], palette, 8, allow_cycling=allow_cycling
    )
    indices, stroke = first
    assert len(indices) == 8
    assert all(
        0 <= index < (255 if allow_cycling else 224) for index in indices + [stroke]
    )
    assert palette.colors == original


def test_gradient_can_turn_at_an_explicit_middle_stop():
    palette = U7Palette()
    palette.colors[:6] = [
        (value, value, value) for value in (0, 51, 102, 153, 204, 255)
    ]
    indices, _ = resolve_gradient_to_indices(
        ["#000000", "#ffffff", "#000000"], palette, 11
    )
    brightness = [palette.colors[i][0] for i in indices]
    assert brightness[0] == brightness[-1] == 0
    assert brightness[5] == 255
    assert brightness[:6] == sorted(brightness[:6])
    assert brightness[5:] == sorted(brightness[5:], reverse=True)


def test_duplicate_entries_are_not_additional_shades():
    palette = U7Palette()
    palette.colors = [(255, 141, 28)] * 256
    indices, _ = resolve_gradient_to_indices(GRADIENT_PRESETS["sunrise"], palette, 12)
    assert indices == [0] * 12


def test_flat_colour_does_not_become_an_artificial_gradient(main_palette_sample):
    indices, _ = resolve_gradient_to_indices(["#ff8d1c"], main_palette_sample, 6)
    assert indices == [37] * 6


def test_cycling_and_transparent_colours_remain_excluded_unless_requested():
    palette = U7Palette()
    palette.colors[5] = (150, 150, 150)
    palette.colors[224] = (255, 255, 255)
    palette.colors[255] = (255, 0, 0)
    assert resolve_gradient_to_indices(["#ffffff"], palette, 1)[0] == [5]
    assert resolve_gradient_to_indices(["#ffffff"], palette, 1, allow_cycling=True)[
        0
    ] == [224]
    assert (
        255
        not in resolve_gradient_to_indices(["#ff0000"], palette, 4, allow_cycling=True)[
            0
        ]
    )


def test_maximum_step_count_remains_usable_in_a_sparse_palette():
    palette = U7Palette()
    palette.colors[1] = (255, 255, 255)
    indices, _ = resolve_gradient_to_indices(["#000000", "#ffffff"], palette, 256)
    assert len(indices) == 256
    assert indices[0] == 0 and indices[-1] == 1
    assert indices == sorted(indices)


def test_empty_gradient_is_rejected():
    with pytest.raises(ValueError, match="at least one colour stop"):
        resolve_gradient_to_indices([], U7Palette())


def test_wizard_reports_a_palette_limited_ramp(monkeypatch, capsys):
    palette = U7Palette()
    palette.colors[1] = (255, 141, 28)
    monkeypatch.setattr(wizard, "resolve_game_palette", lambda *args, **kwargs: palette)
    monkeypatch.setattr(wizard.ui, "menus_enabled", lambda: False)
    config = wizard.WizardConfig(gradient_preset="sunrise")
    wizard._resolve_gradient_config(config, 6)
    output = capsys.readouterr().out
    distinct = len({palette.colors[i] for i in config.gradient_indices})
    assert f"{distinct} distinct colours across 6 steps" in output
    assert "some steps repeat" in output
    if distinct == 1:
        assert "resolves to a single colour" in output
    assert "\x1b[" not in output


def test_wizard_does_not_warn_when_all_requested_shades_are_distinct(
    monkeypatch, capsys
):
    palette = U7Palette()
    palette.colors[:6] = [
        (value, value, value) for value in (0, 51, 102, 153, 204, 255)
    ]
    monkeypatch.setattr(wizard, "resolve_game_palette", lambda *args, **kwargs: palette)
    monkeypatch.setattr(
        wizard,
        "get_gradient_preset",
        lambda key: GradientPreset("test", "Test", ["#000000", "#ffffff"]),
    )
    config = wizard.WizardConfig(gradient_preset="test")
    wizard._resolve_gradient_config(config, 6)
    assert len(set(config.gradient_indices)) == 6
    assert "some steps repeat" not in capsys.readouterr().out


@pytest.mark.parametrize("preset", ["sunrise", "", "deep_purple"])
def test_font_recipe_encodes_the_resolved_ramp_or_explicit_indices(
    tmp_path, main_palette_sample, preset
):
    palette_path = tmp_path / "palette.pal"
    palette_path.write_bytes(
        bytes(channel for colour in main_palette_sample.colors for channel in colour)
    )
    gradient = (
        f'gradient_preset = "{preset}"\ngradient_steps = 6'
        if preset
        else "gradient_indices = [21, 37, 40]"
    )
    recipe = tmp_path / "font.toml"
    recipe.write_text(
        '[target]\ngame = "SI"\nslot = 2\ncell_height = 32\n'
        "code_range = [65, 87]\n"
        '[source]\nfont = "dosVga437"\n'
        f'[rendering]\nmethod = "hollow_gradient"\n{gradient}\n'
        '[palette]\nfile = "palette.pal"\n'
        '[output]\nformat = "shp"\npath = "font.shp"\n',
        encoding="utf-8",
    )
    assert wizard.run_from_config(str(recipe)) == 0
    shape = U7Shape.from_file(str(tmp_path / "font.shp"))
    used = {
        int(pixel)
        for frame in shape.frames
        if frame is not None and frame.pixels is not None
        for pixel in frame.pixels.flat
    } - {0, 255}
    expected = (
        set(
            resolve_gradient_to_indices(GRADIENT_PRESETS[preset], main_palette_sample)[
                0
            ]
        )
        if preset
        else {21, 37, 40}
    )
    assert used <= expected
    assert len(used) >= (3 if not preset else 4)
