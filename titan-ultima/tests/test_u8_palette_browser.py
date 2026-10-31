"""Native palette layouts, DOS effects, desktop navigation and exclusive reports."""

import csv
import json
import struct

import pytest
import questionary
from PIL import Image
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.u8.cli import u8_app
from titan.u8.palette_browser import (
    U8PaletteSource,
    export_u8_palette_bundle,
    nearest_u8_palette_indices,
    next_u8_palette_export,
    resolve_u8_palette_source,
    u8_palette_role,
    u8_palette_sheet,
)
from titan.u8.palette_browser_ui import run_u8_palette_browser


@pytest.fixture
def native_source(tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    path = directory / "U8PAL.PAL"
    raw = b"\x00\x00\x00\x01" + bytes((60, 16, 4)) * 256
    path.write_bytes(raw)
    return U8PaletteSource.load(path)


@pytest.mark.parametrize("wide", [False, True])
def test_both_native_layouts_preserve_components_and_bytes(tmp_path, wide):
    path = tmp_path / "palette.pal"
    raw = (
        struct.pack("<768H", *([60, 16, 4] * 256))
        if wide
        else b"HEAD" + bytes((60, 16, 4)) * 256
    )
    path.write_bytes(raw)
    source = U8PaletteSource.load(path)
    assert source.raw == raw
    assert source.components == ((60, 16, 4),) * 256
    assert source.palette().colors[0] == (242, 64, 16)
    assert source.palette().transparent_index == 255


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        bytes(768),
        bytes(771),
        bytes(773),
        bytes(1535),
        b"HEAD" + bytes([64]) * 768,
        struct.pack("<768H", *([256] * 768)),
    ],
)
def test_invalid_native_palette_is_rejected(tmp_path, raw):
    path = tmp_path / "bad.pal"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        U8PaletteSource.load(path)


@pytest.mark.parametrize(
    "effect,expected",
    [
        (0, (60, 16, 4)),
        (1, (32, 32, 32)),
        (2, (0, 16, 4)),
        (3, (35, 24, 21)),
        (4, (58, 16, 2)),
        (5, (63, 0, 0)),
        (6, (16, 4, 60)),
        (7, (4, 60, 16)),
    ],
)
def test_dos_effects_use_six_bit_rounding_before_scaling(
    native_source, effect, expected
):
    assert native_source.palette(effect).colors[0] == tuple(
        value * 255 // 63 for value in expected
    )
    assert native_source.components[0] == (60, 16, 4)


def test_white_grey_saturates_at_native_limit(tmp_path):
    path = tmp_path / "white.pal"
    path.write_bytes(b"HEAD" + bytes([63]) * 768)
    source = U8PaletteSource.load(path)
    for effect in range(8):
        assert all(
            0 <= value <= 255 for rgb in source.palette(effect).colors for value in rgb
        )
    assert source.palette(1).colors[0] == (255, 255, 255)


def test_owner_palette_config_does_not_mix_languages(tmp_path, monkeypatch):
    english, french = tmp_path / "English", tmp_path / "French"
    english.mkdir()
    french.mkdir()
    configured = english / "custom.pal"
    configured.write_bytes(bytes(772))
    local = french / "u8pal.pal"
    local.write_bytes(bytes(772))
    monkeypatch.setattr(
        "titan.u8.shape_browser.cfg",
        lambda key: str(configured) if key == "palette" else None,
    )
    assert resolve_u8_palette_source(english) == configured.resolve()
    assert resolve_u8_palette_source(french) == local
    local.unlink()
    with pytest.raises(FileNotFoundError):
        resolve_u8_palette_source(french)


def test_transparency_and_blend_roles_do_not_inherit_u7_cycle_bands(native_source):
    assert "transparent" in u8_palette_role(255)
    assert "translucent" in u8_palette_role(8)
    assert (
        u8_palette_role(0) == u8_palette_role(224) == u8_palette_role(254) == "colour"
    )
    palette = native_source.palette()
    palette.colors[255] = (0, 255, 0)
    palette.colors[254] = (0, 254, 0)
    assert nearest_u8_palette_indices(palette, (0, 255, 0), 1) == [254]
    assert native_source.rows()[8]["pentagram_blend_rgba"] == "48,48,48,80"


def test_export_bundle_links_colour_values_and_original_bytes(native_source, tmp_path):
    output = tmp_path / "reports" / "first"
    report = export_u8_palette_bundle(native_source, output, 4)
    assert report.is_file()
    with (output / "palette.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 256
    assert rows[0]["effect"] == "Fire storm"
    assert rows[0]["r"] == "234"
    assert rows[0]["raw_r"] == "60"
    assert (output / "original.pal").read_bytes() == native_source.raw
    metadata = json.loads((output / "palette.json").read_text())
    assert len(metadata["all_effects"]) == 8
    assert all(len(rows) == 256 for rows in metadata["all_effects"])
    assert len(list((output / "effects").glob("*.png"))) == 8
    with Image.open(output / "palette.png") as image:
        assert image.size == (768, 512)
        assert image.getpixel((0, 0)) == native_source.palette(4).colors[0]
    assert 'href="palette.csv"' in report.read_text()
    assert 'type="application/json"' in report.read_text()


def test_repeat_exports_and_input_protection(native_source, tmp_path):
    root = tmp_path / "reports"
    first = next_u8_palette_export(native_source, root, 0)
    export_u8_palette_bundle(native_source, first)
    before = {path: path.read_bytes() for path in first.rglob("*") if path.is_file()}
    second = next_u8_palette_export(native_source, root, 0)
    assert second != first
    export_u8_palette_bundle(native_source, second)
    with pytest.raises(FileExistsError):
        export_u8_palette_bundle(native_source, first)
    with pytest.raises(ValueError):
        export_u8_palette_bundle(native_source, native_source.path.parent / "report")
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert native_source.path.read_bytes() == native_source.raw


def test_whole_game_directory_is_protected_for_static_palette(tmp_path):
    static = tmp_path / "game" / "ENGLISH" / "STATIC"
    static.mkdir(parents=True)
    path = static / "U8PAL.PAL"
    path.write_bytes(bytes(772))
    source = U8PaletteSource.load(path)
    with pytest.raises(ValueError):
        next_u8_palette_export(source, tmp_path / "game" / "reports", 0)


def test_numbered_sheet_keeps_opaque_stored_rgb_at_255(native_source):
    image = u8_palette_sheet(native_source.palette())
    assert image.mode == "RGB"
    assert image.getpixel((767, 511)) == native_source.palette().colors[255]


def test_cli_help_export_and_invalid_effect(native_source, tmp_path):
    runner = CliRunner()
    help_result = runner.invoke(u8_app, ["palette-browse", "--help"])
    assert help_result.exit_code == 0
    for option in ("--game-dir", "--index", "--effect", "--export", "--output"):
        assert option in help_result.stdout
    result = runner.invoke(
        u8_app,
        [
            "palette-browse",
            str(native_source.path),
            "--export",
            "--effect",
            "7",
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "cli").glob("*/index.html"))) == 1
    assert (
        runner.invoke(
            u8_app, ["palette-browse", str(native_source.path), "--effect", "8"]
        ).exit_code
        != 0
    )


def test_real_desktop_selects_u8_effect_then_returns_and_quits(
    native_source, monkeypatch, capsys
):
    original = questionary.select
    prompts = []
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    with create_pipe_input() as pipe:

        def select(*args, **kwargs):
            prompts.append(kwargs)
            return original(*args, input=pipe, output=DummyOutput(), **kwargs)

        monkeypatch.setattr(questionary, "select", select)
        pipe.send_text("c" + "\x1b[B" * 4 + "\r" + "u" + "q")
        assert run_u8_palette_browser(native_source.path) == 0
    output = capsys.readouterr().out
    assert "Fire storm" in output
    assert "Header (uninterpreted)" in output
    assert prompts[1]["choices"][4].value == "4"
    assert "Fire storm" in prompts[1]["choices"][4].title


def test_redirected_navigation_inspect_match_and_gradient(
    native_source, monkeypatch, capsys
):
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    answers = iter(
        [
            "N",
            "B",
            "I",
            "0xff",
            "F",
            "#f24010",
            "G",
            "C",
            "#000000 #ffffff",
            "4",
            "V",
            "Q",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    assert run_u8_palette_browser(native_source.path) == 0
    output = capsys.readouterr().out
    assert '"index": 255' in output
    assert "Nearest RGB indices" in output
    assert "index 255 is excluded" in output
