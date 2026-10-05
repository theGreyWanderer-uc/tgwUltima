"""Palette ownership, real slot numbering, colours, ramps and browser actions."""

from __future__ import annotations

import csv
import io
import json
import os
import struct
from dataclasses import replace

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.fonts.palette import resolve_gradient_to_indices
from titan.u7 import palette_browser as browser
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette
from titan.u7.palette_semantics import CYCLE_RANGES


def palette_bytes(value=10):
    return bytes([value] * 765 + [250, 64, 1])


def write_flex(path, records):
    archive = U7FlexArchive()
    archive.records = list(records)
    path.write_bytes(archive.to_bytes())


@pytest.fixture
def owner(tmp_path):
    root = tmp_path / "game"
    static, patch = root / "static", root / "patch"
    static.mkdir(parents=True)
    patch.mkdir()
    write_flex(
        static / "PALETTES.FLX",
        [palette_bytes(10), palette_bytes(20), b"", palette_bytes(30), b""],
    )
    write_flex(
        patch / "palettes.flx",
        [b"", palette_bytes(40), b"", b"short", b"", palette_bytes(50)],
    )
    return ArchiveTarget("Test mod", static, patch, root=root)


def actions(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr(ui, "choice", lambda *a, **k: next(iterator))
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)


def test_combines_records_without_renumbering_or_hiding_invalid_patch(owner):
    source = browser.load_source(owner)
    assert [r.index for r in source.records] == list(range(6))
    assert source.available == [0, 1, 5]
    assert source.records[0].origin == "base"
    assert source.records[0].load().colors[0] == (40, 40, 40)
    assert source.records[1].origin == "patch"
    assert source.records[1].load().colors[0] == (161, 161, 161)
    assert "empty" in source.records[2].label()
    assert "INVALID" in source.records[3].label()
    with pytest.raises(ValueError, match="too small"):
        source.records[3].load()
    assert source.records[5].origin == "patch"


def test_populated_truncated_patch_blocks_base(owner):
    path = owner.patch / "palettes.flx"
    data = bytearray(path.read_bytes())
    struct.pack_into("<II", data, 0x80, len(data) - 2, 768)
    path.write_bytes(data)
    source = browser.load_source(owner)
    assert "truncated" in source.records[0].label()
    with pytest.raises(ValueError, match="truncated"):
        source.records[0].load()


def test_overlapping_patch_is_invalid(owner):
    path = owner.patch / "palettes.flx"
    data = bytearray(path.read_bytes())
    offset, length = struct.unpack_from("<II", data, 0x88)
    struct.pack_into("<II", data, 0x80 + 5 * 8, offset, length)
    path.write_bytes(data)
    source = browser.load_source(owner)
    assert "overlaps" in source.records[5].label()


def test_patch_only_and_identical_directories(owner):
    source = browser.load_source(replace(owner, static=None))
    assert source.available == [1, 5]
    same = browser.load_source(replace(owner, patch=owner.static))
    assert len(same.paths) == 1
    assert same.available == [0, 1, 3]


def test_no_foreign_palette_fallback(tmp_path):
    target = ArchiveTarget("empty", tmp_path / "static", tmp_path / "patch")
    with pytest.raises(ValueError, match="No PALETTES.FLX"):
        browser.load_source(target)


def test_explicit_sparse_archive_stays_independent(owner):
    source = browser.load_source(owner, owner.patch / "palettes.flx")
    assert source.explicit
    assert source.available == [1, 5]
    assert not source.records[0].raw


def test_raw_and_headered_palettes_use_only_record_zero(owner, tmp_path):
    path = tmp_path / "custom.pal"
    path.write_bytes(b"HEAD" + palette_bytes())
    source = browser.load_source(owner, path)
    assert len(source.records) == 1
    palette = source.records[0].load()
    assert palette.colors[0] == (40, 40, 40)
    assert "(10, 10, 10)" in browser.colour_detail(source.records[0], palette, 0)
    assert browser.export_data(source.records[0], palette, "R") == path.read_bytes()


def test_explicit_dark_8bit_and_bad_6bit_encoding(tmp_path):
    record = browser.Record(
        0, tmp_path / "dark.pal", "selected file", palette_bytes(10)
    )
    assert record.load("8bit").colors[0] == (10, 10, 10)
    bright = replace(record, raw=bytes([200] * 768))
    with pytest.raises(ValueError, match="exceed"):
        bright.load("6bit")


def test_double_palette_reads_both_components_preserves_raw_and_roles(tmp_path):
    first, second = palette_bytes(10), palette_bytes(20)
    raw = bytes(v for pair in zip(first, second) for v in pair)
    record = browser.Record(3, tmp_path / "double.pal", "selected file", raw)
    primary, secondary = record.load(), record.load(component=1)
    assert primary.colors[0] == (40, 40, 40)
    assert secondary.colors[0] == (80, 80, 80)
    assert primary.palette_index == 3
    assert "double palette" in record.label()
    assert "(20, 20, 20)" in browser.colour_detail(record, secondary, 0, 1)
    assert browser.export_data(record, secondary, "R", 1) == raw
    with pytest.raises(ValueError, match="secondary"):
        replace(record, raw=first).load(component=1)


def test_record_selector_keeps_invalid_visible_and_paged(owner, monkeypatch, capsys):
    source = browser.load_source(owner)
    source.records += [browser.Record(i, source.paths[0], "base") for i in range(6, 14)]
    actions(monkeypatch, ["3", "N", "B", "5"])
    assert browser.choose_record(source) == 5
    output = capsys.readouterr().out
    assert "INVALID" in output
    assert "page 2/2" in output
    assert "[5] 5:" in output


def test_empty_archive_selector_returns_without_loop(owner, monkeypatch):
    assert browser.choose_record(browser.PaletteSource(owner, [], [])) is None


def test_grid_uses_indexed_native_background_cells_and_adapts_width(monkeypatch):
    palette = U7Palette.default_palette()
    lines = []
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    monkeypatch.setattr(
        browser.shutil, "get_terminal_size", lambda *a: os.terminal_size((34, 25))
    )
    browser.show_grid(palette, 224, 32)
    assert len(lines) == 4
    cells = [f for line in lines for f in line if "bg:" in f[0]]
    assert [text for _, text in cells] == [f"{i:03d}" for i in range(224, 256)]
    assert "bg:#e0e0e0" in cells[0][0]
    assert "fg:#000000" in cells[0][0]


def test_redirected_grid_and_details_have_no_ansi(capsys):
    palette = U7Palette.default_palette()
    browser.show_grid(palette, 192)
    text = capsys.readouterr().out
    assert "192" in text and "255" in text
    assert "\x1b" not in text
    assert "stable" in browser.index_role(223)
    assert "magic" in browser.index_role(224)
    assert "RLE" in browser.index_role(255) and "opaque" in browser.index_role(255)


def test_cycle_provider_rotates_only_ranges_and_reuses_images():
    palette = U7Palette.default_palette()
    provider = browser.cycling_provider(palette)
    zero, _ = provider(0, 0)
    once, _ = provider(1, 100)
    for row, cycle in enumerate(CYCLE_RANGES):
        assert zero.getpixel((0, row)) == palette.colors[cycle.start]
        assert once.getpixel((0, row)) == palette.colors[cycle.end]
    assert provider(24, 2400)[0] is zero
    assert palette.colors[224] == (224, 224, 224)


def test_cycle_preview_fallback_and_step(monkeypatch, capsys):
    actions(monkeypatch, ["P", "N", "R", "Q"])
    monkeypatch.setattr(
        browser, "play_terminal", lambda *a, **k: pytest.fail("Playback must not run")
    )
    browser.cycle_preview(U7Palette.default_palette())
    output = capsys.readouterr().out
    assert "interactive terminal" in output and "step 1" in output
    assert "224-231" in output and "252-254" in output
    assert "\x1b" not in output


@pytest.mark.parametrize(
    "value, expected",
    [
        ("6F263D,236192", ["#6f263d", "#236192"]),
        ("#6F263D 60324E; 513E5F", ["#6f263d", "#60324e", "#513e5f"]),
        ("000000", ["#000000"]),
    ],
)
def test_parse_custom_rgb(value, expected):
    assert browser.parse_hex_stops(value) == expected


@pytest.mark.parametrize(
    "value", ["", "22, 33", "#ggff00", "FFFFFF 12", "000000 " * 17]
)
def test_parse_custom_rgb_rejects_invalid(value):
    with pytest.raises(ValueError, match="RGB hex"):
        browser.parse_hex_stops(value)


def test_gradient_custom_uses_shared_ramp_and_excludes_cycles(monkeypatch, capsys):
    actions(monkeypatch, ["C", "N", "Q"])
    inputs = iter(["bad", "6F263D,236192", "6"])
    monkeypatch.setattr(ui, "text", lambda *a, **k: next(inputs))
    palette = U7Palette.default_palette()
    expected, _ = resolve_gradient_to_indices(["#6f263d", "#236192"], palette, 6)
    browser.gradient_test(palette)
    output = capsys.readouterr().out
    assert ", ".join(map(str, expected)) in output
    assert "RGB hex" in output
    assert "font wizard" in output
    assert all(index < 224 for index in expected)


def test_gradient_preset_menu_has_formatted_swatches(monkeypatch):
    captured = {}

    def choose(*args, **kwargs):
        captured.update(kwargs)
        return "Q"

    monkeypatch.setattr(ui, "choice", choose)
    browser.gradient_test(U7Palette.default_palette())
    preset_labels = [
        label for key, label in captured["labels"].items() if key.isdigit()
    ]
    assert len(preset_labels) == 30
    assert all(any("bg:#" in style for style, _ in label) for label in preset_labels)


def test_gradient_cycles_are_opt_in_but_transparent_is_excluded(monkeypatch, capsys):
    actions(monkeypatch, ["C", "Y", "Q"])
    inputs = iter(["e0e0e0", "1"])
    monkeypatch.setattr(ui, "text", lambda *a, **k: next(inputs))
    browser.gradient_test(U7Palette.default_palette())
    assert "font wizard): 224" in capsys.readouterr().out


def test_exports_png_csv_json_and_exact_raw(owner):
    source = browser.load_source(owner)
    record = source.records[0]
    palette = record.load()
    png = Image.open(io.BytesIO(browser.export_data(record, palette, "P")))
    assert png.size == (256, 256)
    assert png.getpixel((0, 0)) == palette.colors[0]
    assert png.getpixel((255, 255)) == (250, 64, 1)
    rows = list(
        csv.DictReader(io.StringIO(browser.export_data(record, palette, "C").decode()))
    )
    assert len(rows) == 256 and rows[224]["hex"] == browser.hex_colour(
        palette.colors[224]
    )
    report = json.loads(browser.export_data(record, palette, "J"))
    assert report["source"] == str(record.path)
    assert report["origin"] == "base" and report["encoding"] == "6bit"
    assert browser.export_data(record, palette, "R") == palette_bytes(10)


def test_exports_are_exclusive_and_protect_game_and_sources(owner, tmp_path):
    source = browser.load_source(owner)
    path = tmp_path / "output" / "palette.json"
    browser.safe_export(source, path, b"test")
    assert path.read_bytes() == b"test"
    with pytest.raises(FileExistsError):
        browser.safe_export(source, path, b"replacement")
    assert path.read_bytes() == b"test"
    for path in [
        owner.static / "new.csv",
        owner.patch / "new.png",
        source.paths[0],
        owner.root / "new.pal",
    ]:
        with pytest.raises(ValueError, match="outside"):
            browser.safe_export(source, path, b"replacement")
    assert browser.load_source(owner).available == [0, 1, 5]


def test_browser_page_and_record_hotkeys_skip_broken_records(
    owner, monkeypatch, capsys
):
    actions(monkeypatch, ["N", "B", "J", "J", "K", "Q"])
    assert browser.browse(browser.load_source(owner)) == "Q"
    output = capsys.readouterr().out
    assert "Colours 64-127" in output
    assert "Palette 1:" in output and "Palette 5:" in output
    assert "Palette 3:" not in output


def test_browser_invalid_initial_record_recovers(owner, monkeypatch, capsys):
    actions(monkeypatch, ["5", "W"])
    assert browser.browse(browser.load_source(owner), index=99) == "W"
    assert "outside this source" in capsys.readouterr().out


def test_browser_colour_inspection_and_bad_encoding_keep_current(
    owner, monkeypatch, capsys
):
    actions(monkeypatch, ["I", "Q", "U", "8", "Q"])
    monkeypatch.setattr(ui, "text", lambda *a, **k: "0xff")
    assert browser.browse(browser.load_source(owner)) == "Q"
    output = capsys.readouterr().out
    assert "Index 255 (0xff)" in output
    assert "Colours 192-255" in output
    assert "8bit" in output


def test_browser_switches_double_components(owner, tmp_path, monkeypatch, capsys):
    path = tmp_path / "double.pal"
    path.write_bytes(
        bytes(v for pair in zip(palette_bytes(10), palette_bytes(20)) for v in pair)
    )
    actions(monkeypatch, ["R", "Q"])
    assert browser.browse(browser.load_source(owner, path)) == "Q"
    output = capsys.readouterr().out
    assert "primary component" in output and "secondary component" in output


def test_failed_encoding_and_export_return_to_current_palette(
    owner, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "bright.pal"
    path.write_bytes(bytes([200] * 768))
    source = browser.load_source(owner, path)
    actions(monkeypatch, ["U", "6", "E", "R", "Q"])
    monkeypatch.setattr(ui, "path", lambda *a, **k: str(path))
    assert browser.browse(source) == "Q"
    output = capsys.readouterr().out
    assert "Components exceed" in output
    assert "Choose an output outside" in output
    assert output.count("Palette 0:") == 3
    assert path.read_bytes() == bytes([200] * 768)


def test_broken_record_table_reports_error(owner):
    path = owner.patch / "palettes.flx"
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, 0x54, 1000)
    path.write_bytes(data)
    with pytest.raises(ValueError, match="table truncated"):
        browser.load_source(owner)


def test_palette_browser_cancel_is_clean(monkeypatch, capsys):
    def cancel(*a, **k):
        raise ui.PromptCancelled

    monkeypatch.setattr(ui, "choice", cancel)
    assert browser.run_browser() == 0
    assert "Cancelled" in capsys.readouterr().out


def test_run_browser_source_recovery_and_quit(owner, monkeypatch, capsys):
    actions(monkeypatch, ["2", "C", "Q"])
    monkeypatch.setattr(browser, "game_targets", lambda game: (owner, []))
    monkeypatch.setattr(browser, "select_target", lambda *a: owner)
    monkeypatch.setattr(ui, "path", lambda *a, **k: str(owner.static / "PALETTES.FLX"))
    assert browser.run_browser(game="si", file="missing.pal") == 0
    output = capsys.readouterr().out
    assert "ERROR" in output and "Palette 0:" in output


def test_cli_forwards_initial_options_and_validates_index(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        browser, "run_browser", lambda **kwargs: captured.update(kwargs) or 0
    )
    result = CliRunner().invoke(
        u7_app,
        [
            "palette-browse",
            "custom.pal",
            "--game",
            "si",
            "--index",
            "2",
            "--encoding",
            "8bit",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "game": "si",
        "file": "custom.pal",
        "index": 2,
        "encoding": "8bit",
    }
    assert (
        CliRunner().invoke(u7_app, ["palette-browse", "--index", "-1"]).exit_code != 0
    )
    help_result = CliRunner().invoke(u7_app, ["palette-browse", "--help"])
    assert help_result.exit_code == 0 and "gradient" in help_result.output
