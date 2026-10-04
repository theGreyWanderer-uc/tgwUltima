"""Font rendering, interactive retries and safe archive output regressions."""

import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from titan.fonts import wizard
from titan.fonts.archive import read_font_archive
from titan.fonts.encoder import glyphs_to_shape
from titan.fonts.exult_cfg import ExultGamePaths, scan_font_archives, parse_exult_cfg
from titan.fonts.palette import (
    PaletteLUT,
    resolve_gradient_to_indices,
    resolve_game_palette,
)
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape


@pytest.fixture(autouse=True)
def isolate_profile(monkeypatch):
    monkeypatch.setattr(wizard, "game_paths", lambda game: None)
    monkeypatch.setattr(wizard, "_show_exult_info", lambda game: None)
    monkeypatch.setattr("titan.fonts.archive.game_paths", lambda game: None)
    monkeypatch.setattr("titan._config.get_config", lambda: {})
    monkeypatch.setattr("titan._config.exult_cfg", lambda key: None)


def write_archive(path, records, magic2=0xCC01):
    path.parent.mkdir(parents=True, exist_ok=True)
    archive = U7FlexArchive()
    archive.records = records
    archive.magic2 = magic2
    path.write_bytes(archive.to_bytes())


def font_record(ink=0):
    shape, _ = glyphs_to_shape(
        {65: np.ones((8, 4), dtype=np.uint8)},
        128,
        PaletteLUT.mono(ink),
        ink_index=ink,
        cell_height=8,
    )
    return shape.to_bytes()


def config(**overrides):
    return replace(
        wizard.WizardConfig(
            slot=2,
            h_lead=0,
            cell_height=8,
            ink_height=7,
            total_frames=127,
            ttf_key="dosVga437",
        ),
        **overrides,
    )


def recipe(
    path,
    extra_target="",
    rendering='method = "mono"',
    output='format = "shp"\npath = "out/font.shp"',
    source='font = "dosVga437"',
    palette="",
):
    path.write_text(
        f'[target]\ngame = "BG"\nslot = 2\n{extra_target}\n[source]\n{source}\n[rendering]\n{rendering}\n[palette]\n{palette}\n[output]\n{output}\n',
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("slot", -1),
        ("slot", 65536),
        ("slot", True),
        ("cell_height", 201),
        ("cell_height", 0),
        ("ink_height", 0),
        ("ink_height", 8),
        ("total_frames", 0),
        ("total_frames", 257),
        ("code_range", (32, 127)),
        ("ink_index", -1),
        ("ink_index", 255),
        ("threshold", 0),
        ("threshold", 256),
        ("stroke_width", -1),
        ("stroke_index", 255),
        ("gradient_indices", []),
        ("gradient_indices", [256]),
        ("gradient_steps", 0),
        ("h_lead", 3),
        ("transparent_index", 0),
        ("render_method", "mystery"),
        ("output_format", "mystery"),
    ],
)
def test_invalid_inputs_rejected_before_writing(tmp_path, field, value):
    output = tmp_path / "font.shp"
    cfg = config(output_path=str(output), **{field: value})
    with pytest.raises(ValueError):
        wizard._generate(cfg, {65: np.ones((8, 4), dtype=np.uint8)}, True)
    assert not output.exists()


def test_ink_height_affects_bitmap_and_encoded_baseline():
    cfg = config(code_range=(65, 65))
    original, mono, indexed = wizard._render(cfg)
    changed, _, _ = wizard._render(replace(cfg, ink_height=4))
    assert mono and not indexed
    assert not np.array_equal(original[65], changed[65])
    shape, _ = glyphs_to_shape(
        changed, 127, PaletteLUT.mono(), cell_height=8, ink_height=4
    )
    default, _ = glyphs_to_shape(original, 127, PaletteLUT.mono(), cell_height=8)
    assert shape.frames[65].origin_y != default.frames[65].origin_y


def test_threshold_uses_grayscale_cutoff(monkeypatch):
    gray = np.array([[0, 50, 127, 128, 200, 255]], dtype=np.uint8)
    monkeypatch.setattr(
        wizard, "render_all_glyphs_grayscale", lambda *args, **kwargs: ({65: gray}, 9)
    )
    low, mono, indexed = wizard._render(
        config(render_method="threshold", threshold=128)
    )
    high, _, _ = wizard._render(config(render_method="threshold", threshold=201))
    assert mono and not indexed
    assert low[65].tolist() == [[0, 0, 0, 1, 1, 1]]
    assert high[65].tolist() == [[0, 0, 0, 0, 0, 1]]


def test_render_warns_above_72_pixels(monkeypatch, capsys):
    monkeypatch.setattr(
        wizard,
        "render_all_glyphs_mono",
        lambda *args, **kwargs: ({65: np.ones((8, 73), dtype=np.uint8)}, 9),
    )
    wizard._render(config())
    assert "exceed 72x72" in capsys.readouterr().err


@pytest.mark.parametrize("width,height", [(321, 8), (8, 201)])
def test_font_output_enforces_fullscreen_size_cap(tmp_path, width, height):
    output = tmp_path / "font.shp"
    with pytest.raises(ValueError, match="maximum permitted"):
        wizard._generate(
            config(output_path=str(output)),
            {65: np.ones((height, width), dtype=np.uint8)},
            True,
        )
    assert not output.exists()


def test_invalid_exult_config_has_clear_error(tmp_path):
    path = tmp_path / "exult.cfg"
    path.write_text("<config><disk>", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Exult configuration"):
        parse_exult_cfg(path)


def test_preview_maps_black_ink_and_transparency():
    assert wizard._preview_glyph(
        np.array([[255, 0, 185]], dtype=np.uint8), is_mono=False, is_indexed=True
    ) == ["·██"]


def test_interactive_redo_invalid_preview_and_output_override(tmp_path):
    output = tmp_path / "font.shp"
    answers = (
        "\n".join(
            [
                "1",
                "",
                "2",
                "1",
                "1",
                "n",
                "0",
                "r",
                "1",
                "3",
                "n",
                "0",
                "128",
                "MAYBE",
                "y",
                "",
                "1",
            ]
        )
        + "\n"
    )
    result = CliRunner().invoke(
        u7_app, ["font-create", "-o", str(output)], input=answers
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Source TrueType font:") == 2
    assert "Please enter one of" in result.output
    assert "Output .shp filename" not in result.output
    shape = U7Shape.from_data(output.read_bytes(), strict=True)
    assert len(shape.frames) == 127


def test_quit_preview_writes_nothing(tmp_path):
    output = tmp_path / "font.shp"
    result = CliRunner().invoke(
        u7_app, ["font-create", "-o", str(output)], input="1\n\n2\n1\n1\nn\n0\nq\n"
    )
    assert result.exit_code == 0, result.output
    assert not output.exists()


def test_template_is_not_default_destination(tmp_path, monkeypatch):
    source = tmp_path / "STATIC/FONTS.VGA"
    write_archive(source, [font_record()])
    cfg = config(template_archive=str(source))
    paths = ExultGamePaths(
        game="BG", patch_path=str(tmp_path / "patch"), font_config="original"
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "a")
    wizard._step_resolve_flex_target(cfg, paths)
    assert Path(cfg.flex_source) == tmp_path / "patch/fonts_original.vga"
    assert cfg.template_archive == str(source)


def test_sparse_template_inherits_retail_slots_without_mutation(tmp_path):
    base = tmp_path / "game/STATIC/FONTS.VGA"
    patch = tmp_path / "game/mods/example/patch/fonts.vga"
    write_archive(base, [font_record(7), font_record(8), font_record(9)])
    write_archive(patch, [b"", font_record(10)])
    before = patch.read_bytes()
    archive = read_font_archive(patch)
    assert archive.records == [font_record(7), font_record(10), font_record(9)]
    assert set(wizard._read_archive_slots(patch)) == {0, 1, 2}
    assert patch.read_bytes() == before


@pytest.mark.parametrize(
    "filename,record_index", [("fonts_original.vga", 29), ("fonts_serif.vga", 30)]
)
def test_exult_bundled_font_base(tmp_path, filename, record_index):
    patch = tmp_path / "game/patch" / filename
    bundle = tmp_path / "data/exult.flx"
    nested = U7FlexArchive()
    nested.records = [font_record(12), font_record(13)]
    records = [b""] * 31
    records[record_index] = nested.to_bytes()
    write_archive(bundle, records)
    write_archive(patch, [b"", font_record(14)])
    # Exult uses its common bundle even when a similarly named STATIC file exists.
    write_archive(tmp_path / "game/STATIC" / filename, [font_record(99)])
    paths = ExultGamePaths(game="BG", data_path=str(bundle.parent))
    assert read_font_archive(patch, paths=paths).records == [
        font_record(12),
        font_record(14),
    ]


def test_recipe_paths_relative_to_recipe_and_never_prompt(tmp_path, monkeypatch):
    path = tmp_path / "recipe.toml"
    lut = tmp_path / "ink.toml"
    lut.write_text('[mapping]\n"0-0"=255\n"1-255"=15\n', encoding="utf-8")
    recipe(path, rendering='method="lut"\nlut="ink.toml"')
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("recipe prompted"))
    assert wizard.run_from_config(str(path)) == 0
    shape = U7Shape.from_data((tmp_path / "out/font.shp").read_bytes(), strict=True)
    assert set(np.unique(shape.frames[65].pixels)) == {15, 255}


def test_flex_recipe_output_override_is_archive(tmp_path, monkeypatch):
    path = tmp_path / "recipe.toml"
    destination = tmp_path / "out/fonts_original.vga"
    recipe(path, output='format="flex"\nflex_source="ignored.vga"')
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("recipe prompted"))
    assert wizard.run_from_config(str(path), str(destination)) == 0
    assert len(U7FlexArchive.from_file(str(destination), strict=True).records) == 3
    assert not (tmp_path / "ignored.vga").exists()


def test_flex_recipe_path_is_archive(tmp_path):
    path = tmp_path / "recipe.toml"
    recipe(path, output='format="flex"\npath="out/fonts.vga"')
    assert wizard.run_from_config(str(path)) == 0
    assert (tmp_path / "out/fonts.vga").is_file()


def test_flex_recipe_auto_resolves_exult_without_prompt(tmp_path, monkeypatch):
    path = tmp_path / "recipe.toml"
    destination = tmp_path / "patch/fonts_serif.vga"
    recipe(path, output='format="flex"')
    monkeypatch.setattr(
        wizard, "resolve_font_vga_path", lambda game: (None, str(destination))
    )
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("recipe prompted"))
    assert wizard.run_from_config(str(path)) == 0
    assert destination.is_file()


def test_recipe_existing_outputs_require_force(tmp_path):
    path = tmp_path / "recipe.toml"
    recipe(path)
    assert wizard.run_from_config(str(path)) == 0
    output = tmp_path / "out/font.shp"
    before = output.read_bytes()
    assert wizard.run_from_config(str(path)) == 1
    assert output.read_bytes() == before
    assert wizard.run_from_config(str(path), force=True) == 0


def test_corrupt_archive_aborts_before_either_output(tmp_path):
    destination = tmp_path / "fonts.vga"
    write_archive(destination, [font_record()])
    broken = bytearray(destination.read_bytes())
    struct.pack_into("<I", broken, 132, 999999)
    destination.write_bytes(broken)
    path = tmp_path / "recipe.toml"
    recipe(
        path,
        output='format="both"\npath="out/font.shp"\nflex_source="fonts.vga"\nforce=true',
    )
    assert wizard.run_from_config(str(path)) == 1
    assert destination.read_bytes() == broken
    assert not (tmp_path / "out/font.shp").exists()


def test_archive_save_preserves_other_slots_holes_and_format(tmp_path):
    destination = tmp_path / "fonts.vga"
    write_archive(destination, [font_record(7), b"", font_record(8), font_record(9)])
    path = tmp_path / "recipe.toml"
    recipe(path, output='format="flex"\nflex_source="fonts.vga"\nforce=true')
    assert wizard.run_from_config(str(path)) == 0
    archive = U7FlexArchive.from_file(str(destination), strict=True)
    assert archive.magic2 == 0xCC01
    assert archive.records[0] == font_record(7)
    assert archive.records[1] == b""
    assert archive.records[3] == font_record(9)


def test_failed_atomic_shape_replace_preserves_destination(tmp_path, monkeypatch):
    output = tmp_path / "font.shp"
    output.write_bytes(b"original")
    monkeypatch.setattr(
        wizard.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        wizard._write_outputs(
            config(output_path=str(output), force=True), font_record()
        )
    assert output.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [output]


def test_palette_path_relative_to_base_without_duplicate_static(tmp_path, monkeypatch):
    palette = tmp_path / "STATIC/PALETTES.FLX"
    write_archive(palette, [bytes([20, 30, 40]) * 256])
    monkeypatch.setattr(
        "titan._config.get_config",
        lambda: {
            "u7bg": {
                "game": {"base": str(tmp_path)},
                "paths": {"palette": "STATIC/PALETTES.FLX"},
            }
        },
    )
    assert resolve_game_palette("BG").colors[0] == (80, 121, 161)


def test_gradient_matching_excludes_cycling_unless_enabled():
    palette = U7Palette()
    palette.colors = [(0, 0, 0)] * 256
    palette.colors[3] = (200, 200, 200)
    palette.colors[224] = (255, 255, 255)
    assert resolve_gradient_to_indices(["#ffffff"], palette, 1)[0] == [3]
    assert resolve_gradient_to_indices(["#ffffff"], palette, 1, allow_cycling=True)[
        0
    ] == [224]


@pytest.mark.parametrize(
    "mapping", [[(-1, 255, 0)], [(0, 256, 0)], [(0, 255, 256)], [(8, 2, 0)]]
)
def test_invalid_lut_ranges_rejected(mapping):
    with pytest.raises(ValueError):
        PaletteLUT("invalid", mapping=mapping)


def test_font_scanner_finds_uppercase_vga(tmp_path):
    archive = tmp_path / "FONTS.VGA"
    archive.touch()
    assert scan_font_archives(tmp_path) == [archive]


def test_help_lists_new_options():
    result = CliRunner().invoke(u7_app, ["font-create", "--help"])
    assert result.exit_code == 0
    for option in ("--force", "--allow-cycling", "--base-archive"):
        assert option in result.output
