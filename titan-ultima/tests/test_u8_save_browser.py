"""Captured save views, interactive paths, embedded browsers and preserving exports."""

from __future__ import annotations

import csv
import io
import json

import pytest
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.u8.cli import u8_app
from titan.u8.flags import U8FlagSymbols
from titan.u8.npc_browser import describe_u8_npc_source_overview
from titan.u8.save_browser import (
    describe_u8_save_browser_view,
    export_u8_save_browser_bundle,
    extract_u8_save_browser_entry,
    filter_u8_save_browser_rows,
    format_u8_save_browser_view,
)
from titan.u8 import save_browser_ui as browser
from titan.u8.save_state import U8SaveSnapshot
from tests.test_u8_native_runtime_state import (
    avatar_bytes,
    container_bytes,
    gumps_bytes,
    kernel_records,
)
from tests.test_u8_npc_animation_report import Links, case as case
from tests.test_u8_save_state import native_flex, native_nonfixed, native_save, map_item


@pytest.fixture
def full_save(case, tmp_path):
    static, gamedat = case
    flags = bytearray(1024)
    flags[:3] = bytes((0x80, 0xAB, 1))
    for name, raw in (
        ("AVATAR.DAT", avatar_bytes()),
        ("FLAG.DAT", bytes(flags)),
        ("GUMPS.DAT", gumps_bytes([container_bytes()])),
        ("KERNEL.DAT", native_flex(kernel_records())),
        ("NONFIXED.DAT", native_nonfixed([map_item(1)])),
        ("OPAQUE.DAT", b"opaque\x00\xff"),
    ):
        (gamedat / name).write_bytes(raw)
    path = tmp_path / "U8SAVE.005"
    path.write_bytes(
        native_save([(file.name, file.read_bytes()) for file in gamedat.iterdir()])
    )
    return static, gamedat, path


def invoke(full_save, tmp_path, inputs, *options):
    _, _, source = full_save
    output = tmp_path / "exports"
    result = CliRunner().invoke(
        u8_app,
        ["save-browse", str(source), "-o", str(output), *map(str, options)],
        input=inputs,
    )
    assert result.exit_code == 0, result.output
    return result, output


@pytest.mark.parametrize("kind", ["archive", "directory"])
@pytest.mark.parametrize(
    "view",
    [
        "entries",
        "avatar",
        "npcs",
        "items",
        "regions",
        "flags",
        "maps",
        "map_items",
        "gumps",
        "rects",
        "kernel",
        "process",
    ],
)
def test_views_reuse_complete_native_layouts_for_both_sources(full_save, kind, view):
    _, gamedat, archive = full_save
    snapshot = U8SaveSnapshot.from_path(archive if kind == "archive" else gamedat)
    assert not snapshot.decode_errors
    selection = (
        {"map_id": 3}
        if view == "map_items"
        else {"slot": 0}
        if view == "process"
        else {}
    )
    report = describe_u8_save_browser_view(snapshot, view, **selection)
    assert report["view"] == view
    for output_format in ("text", "json", "csv"):
        assert format_u8_save_browser_view(report, output_format)
    if view == "npcs":
        assert {row["npc_label"] for row in report["rows"]} == {"Avé", "Mordea"}
    if view == "kernel":
        assert "partial" in report["metadata"]["coverage"]
    if view == "entries":
        opaque = next(row for row in report["rows"] if row["name"] == "OPAQUE.DAT")
        assert opaque["decode_status"] == "opaque"


def test_missing_invalid_and_zero_default_are_distinct(tmp_path):
    path = tmp_path / "U8SAVE.000"
    path.write_bytes(native_save([("OPAQUE.DAT", b"data")]))
    snapshot = U8SaveSnapshot.from_path(path)
    flags = describe_u8_save_browser_view(snapshot, "flags")
    assert flags["metadata"]["defaulted"] and flags["rows"] == []
    assert (
        len(describe_u8_save_browser_view(snapshot, "flags", all_slots=True)["rows"])
        == 8192
    )
    with pytest.raises(ValueError, match="unavailable"):
        describe_u8_save_browser_view(snapshot, "kernel")
    path.write_bytes(native_save([("FLAG.DAT", b"bad")]))
    snapshot = U8SaveSnapshot.from_path(path)
    assert (
        describe_u8_save_browser_view(snapshot, "entries")["rows"][0]["decode_status"]
        == "invalid"
    )
    with pytest.raises(ValueError, match="unavailable"):
        describe_u8_save_browser_view(snapshot, "flags")


def test_packed_flags_symbols_names_filters_and_csv_encoding(full_save):
    snapshot = U8SaveSnapshot.from_path(full_save[2])
    symbols = U8FlagSymbols.from_bytes(b"FIELD\x00\x07\x00\x10\x00")
    report = describe_u8_save_browser_view(snapshot, "flags", symbols=symbols)
    assert report["rows"] == [
        {"name": "FIELD", "index": 7, "width": 16, "value": 0x357}
    ]
    assert (
        describe_u8_save_browser_view(snapshot, "flags", index=7, width=16)["rows"][0][
            "value"
        ]
        == 0x357
    )
    named = describe_u8_save_browser_view(
        snapshot, "npcs", names={7: 'Lady <Mordea>, "ruler"'}
    )
    matches = filter_u8_save_browser_rows(named["rows"], "lady <mordea>")
    assert len(matches) == 1 and matches[0]["npc_id"] == 7
    csv_rows = list(
        csv.DictReader(
            io.StringIO(format_u8_save_browser_view({**named, "rows": matches}, "csv"))
        )
    )
    assert csv_rows[0]["npc_name"] == 'Lady <Mordea>, "ruler"'
    assert json.loads(csv_rows[0]["equipment"]) == [0] * 8
    assert (
        filter_u8_save_browser_rows(
            [{"raw_hex": "deadbeef", "name": "plain"}], "deadbeef"
        )
        == []
    )


def test_bundle_has_valid_local_links_and_preserves_existing_outputs(
    full_save, tmp_path
):
    snapshot = U8SaveSnapshot.from_path(full_save[2])
    source_before = full_save[2].read_bytes()
    output = tmp_path / "bundle"
    manifest = export_u8_save_browser_bundle(snapshot, output)
    assert {"overview", "entries", "npcs", "flags", "kernel"} <= set(manifest["views"])
    links = Links()
    links.feed((output / "index.html").read_text())
    assert links.urls and all((output / url).is_file() for url in links.urls)
    assert "Mordea" in (output / "npcs.csv").read_text()
    assert full_save[2].read_bytes() == source_before
    before = (output / "index.html").read_bytes()
    with pytest.raises(ValueError, match="new directory"):
        export_u8_save_browser_bundle(snapshot, output)
    assert (output / "index.html").read_bytes() == before


def test_extraction_uses_captured_bytes_sanitizes_names_and_never_overwrites(tmp_path):
    source = tmp_path / "U8SAVE.001"
    source.write_bytes(native_save([("EVIL<>?.DAT", b"original")]))
    snapshot = U8SaveSnapshot.from_path(source)
    source.write_bytes(native_save([("EVIL<>?.DAT", b"new")]))
    output = tmp_path / "extract"
    first = extract_u8_save_browser_entry(snapshot, "EVIL<>?.DAT", output)
    second = extract_u8_save_browser_entry(snapshot, "EVIL<>?.DAT", output)
    assert first.parent == output and first != second
    assert first.read_bytes() == second.read_bytes() == b"original"
    assert not (tmp_path / "EVIL.DAT").exists()
    assert "<" not in first.name and "?" not in first.name
    with pytest.raises(ValueError, match="absent"):
        extract_u8_save_browser_entry(snapshot, "NO.DAT", output)


@pytest.mark.parametrize("action", ["bundle", "extract"])
def test_exports_reject_live_gamedat_and_input_file_targets(full_save, action):
    _, gamedat, _ = full_save
    snapshot = U8SaveSnapshot.from_path(gamedat)
    target = gamedat / "new_export"
    with pytest.raises(ValueError, match="outside"):
        if action == "bundle":
            export_u8_save_browser_bundle(snapshot, target)
        else:
            extract_u8_save_browser_entry(snapshot, "NPCDATA.DAT", target)
    assert not target.exists()


def test_help_contract():
    result = CliRunner().invoke(u8_app, ["save-browse", "--help"])
    assert result.exit_code == 0, result.output
    for option in (
        "--game-dir",
        "--compare",
        "--shapes",
        "--palette",
        "--anim",
        "--symbols",
        "--names",
        "--output",
    ):
        assert option in result.output


def test_scripted_state_navigation_and_numbered_export_preservation(
    full_save, tmp_path
):
    result, output = invoke(
        full_save,
        tmp_path,
        "O\nA\n0\nJ\nB\nC\nQ\nN\nF\nMordea\nC\nQ\nG\nI\n7\n16\nC\nJ\nQ\nE\nE\nQ\n",
    )
    assert "Avé" in result.output and "Mordea" in result.output
    assert (output / "avatar_record.json").is_file()
    assert next(csv.DictReader((output / "flags.csv").read_text().splitlines()))[
        "value"
    ] == str(0x357)
    assert (output / "save_report/index.html").exists()
    assert (output / "save_report_002/index.html").exists()


def test_entry_search_hex_extraction_and_decoded_navigation(full_save, tmp_path):
    result, output = invoke(
        full_save, tmp_path, "F\nF\nOPAQUE\n0\nH\nI\n0\nX\nB\nQ\nQ\n"
    )
    assert "00000000" in result.output
    assert next(output.glob("entry_*OPAQUE.DAT")).read_bytes() == b"opaque\x00\xff"


def test_maps_and_kernel_drilldowns_export_full_records(full_save, tmp_path):
    _, output = invoke(
        full_save,
        tmp_path,
        "M\n0\nD\n0\nJ\nB\nC\nQ\nB\nQ\nK\n0\nD\n0\nJ\nB\nQ\nB\nQ\nQ\n",
    )
    assert json.loads((output / "map_items_record.json").read_text())["rows"][0][
        "raw_hex"
    ]
    assert json.loads((output / "process_record.json").read_text())["rows"][0][
        "object_hex"
    ]


def test_embedded_npc_and_shape_browsers_return_to_captured_snapshot(
    full_save, tmp_path, monkeypatch
):
    static, _, source = full_save
    result, output = invoke(
        full_save,
        tmp_path,
        "N\nF\nMordea\n0\nN\nT\nA\nQ\nE\nJ\nB\nQ\nB\nQ\nQ\n",
        "--shapes",
        static / "U8SHAPES.FLX",
    )
    assert "Back to parent browser" in result.output
    assert "Choose another snapshot" not in result.output
    assert json.loads((output / "npc_007.json").read_text())["npc_name"] == "Mordea"
    snapshot = U8SaveSnapshot.from_path(source)
    session = browser.U8SaveBrowserSession(
        snapshot, output, shapes=static / "U8SHAPES.FLX"
    )
    source.write_bytes(native_save([("OPAQUE.DAT", b"different")]))
    captured = []
    monkeypatch.setattr(
        browser,
        "browse_u8_npc_session",
        lambda session, **kwargs: captured.append(session),
    )
    browser._npcs(session, 7)
    assert captured[0].states[7]["npc_name"] == "Mordea"
    assert captured[0].source.npcs is snapshot.npc_data
    assert "NPCDATA.DAT" in describe_u8_npc_source_overview(captured[0])


def test_comparison_exports_all_rows_and_is_directional(full_save, tmp_path):
    _, _, source = full_save
    comparison = tmp_path / "U8SAVE.001"
    comparison.write_bytes(native_save([("OPAQUE.DAT", b"old")]))
    result, output = invoke(
        full_save, tmp_path, "C\nJ\nT\nB\nQ\n", "--compare", comparison
    )
    report = json.loads((output / "save_diff.json").read_text())
    assert report["changed_entry_count"] and "Before:" in result.output
    assert all(section["omitted_count"] == 0 for section in report["sections"].values())
    assert (output / "save_diff.txt").exists()


def test_changing_primary_snapshot_clears_comparison(full_save, monkeypatch, tmp_path):
    _, gamedat, source = full_save
    selections = iter([gamedat])
    monkeypatch.setattr(
        browser,
        "choose_u8_save_browser_source",
        lambda *args, **kwargs: next(selections),
    )
    captured = []

    def visit(session):
        captured.append(session)
        return "D" if len(captured) == 1 else "Q"

    monkeypatch.setattr(browser, "_browse_snapshot", visit)
    assert (
        browser.run_u8_save_browser(
            source=source, compare=source, output=tmp_path / "out"
        )
        == 0
    )
    assert captured[0].comparison is not None and captured[1].comparison is None


def test_no_graphics_are_required_for_state_browsing(full_save, tmp_path, monkeypatch):
    monkeypatch.setattr(
        browser, "_graphics", lambda *args: pytest.fail("Unexpected graphics load")
    )
    result, output = invoke(full_save, tmp_path, "N\nC\nQ\nE\nQ\n")
    assert result.exit_code == 0 and (output / "npcs.csv").exists()


def test_no_source_argument_uses_discovery_and_returns_from_data_views(
    full_save, tmp_path
):
    static, _, _ = full_save
    result = CliRunner().invoke(
        u8_app,
        ["save-browse", "--game-dir", str(static.parent), "-o", str(tmp_path / "out")],
        input="1\nN\nF\nMordea\nC\nQ\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "Choose save snapshot" in result.output
    assert "Mordea" in (tmp_path / "out/npcs.csv").read_text()


def test_exports_protect_comparison_gamedat_directory(full_save, tmp_path):
    _, gamedat, source = full_save
    session = browser.U8SaveBrowserSession(
        U8SaveSnapshot.from_path(source),
        gamedat / "new_exports",
        comparison=U8SaveSnapshot.from_path(gamedat),
    )
    report = describe_u8_save_browser_view(session.snapshot, "entries")
    with pytest.raises(ValueError, match="outside"):
        browser._export(session, report, "csv", "entries")
    assert not (gamedat / "new_exports").exists()


def test_source_discovery_stays_with_selected_installation(tmp_path, monkeypatch):
    root = tmp_path / "selected"
    static = root / "ENGLISH/STATIC"
    static.mkdir(parents=True)
    save = root / "cloud_saves/SAVEGAME/U8SAVE.001"
    save.parent.mkdir(parents=True)
    save.write_bytes(native_save([]))
    other = tmp_path / "unrelated/SAVEGAME"
    other.mkdir(parents=True)
    (other / "U8SAVE.002").write_bytes(native_save([]))
    menus = []

    def choose(title, labels, default):
        menus.append(labels)
        return "1"

    monkeypatch.setattr(browser, "_menu", choose)
    assert browser.choose_u8_save_browser_source(root) == save
    assert all("unrelated" not in value for value in menus[0].values())


@pytest.mark.parametrize("exception", [EOFError, KeyboardInterrupt, ui.PromptCancelled])
def test_cancellation_exits_cleanly_without_exports(
    full_save, tmp_path, monkeypatch, exception
):
    monkeypatch.setattr(
        browser, "_menu", lambda *args, **kwargs: (_ for _ in ()).throw(exception())
    )
    output = tmp_path / "out"
    assert browser.run_u8_save_browser(source=full_save[2], output=output) == 0
    assert not output.exists()


def test_invalid_source_and_optional_inputs_have_controlled_errors(tmp_path):
    bad = tmp_path / "bad"
    bad.write_bytes(b"bad")
    for options in ([], ["--symbols", str(bad)], ["--names", str(bad)]):
        result = CliRunner().invoke(
            u8_app, ["save-browse", str(bad), *options], input="Q\n"
        )
        assert result.exit_code == 1 and "Traceback" not in result.output
