"""Map browser source joins, GLOB filters, container identity and preserving exports."""

from __future__ import annotations

import csv
import io
import json
import struct
from dataclasses import replace

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.u8 import map_browser_ui as browser
from titan.u8.cli import u8_app
from titan.u8.map_browser import (
    U8MapBrowserFilters,
    describe_u8_map_rows,
    describe_u8_map_summary,
    export_u8_map_bundle,
    filter_u8_map_rows,
    format_u8_map_csv,
    load_u8_map_session,
    map_npc_rows,
    render_u8_browser_map,
    u8_map_container_children,
    validate_u8_map_output,
)
from titan.u8.shape_browser import load_u8_shape_library
from tests.test_u8_cached_state import state_flex
from tests.test_u8_map_render import _flex, _save
from tests.test_u8_npc_animation_report import Links, case as case


def item(shape=1, *, x=512, y=512, z=0, status=0, quality=0, npc_num=0, frame=0):
    return struct.pack(
        "<HHBHBHHBBH", x, y, z, shape, frame, status, quality, npc_num, 3, 0
    )


@pytest.fixture
def assets(case):
    static, gamedat = case
    from titan.flex import FlexArchive

    sprites = FlexArchive.from_file(str(static / "U8SHAPES.FLX")).records[1]
    (static / "U8SHAPES.FLX").write_bytes(
        state_flex([b"", sprites, b"", sprites, sprites])
    )
    flags = bytearray(5 * 8)
    flags[3 * 8 + 1] = 4  # Roof flag.
    (static / "TYPEFLAG.DAT").write_bytes(flags)
    (static / "FIXED.DAT").write_bytes(
        _flex(
            {
                3: item()
                + item(4, x=1, y=0x0302, z=7, status=8)
                + item(3, x=600)
                + item(2, x=512, y=512, quality=7),
                5: item(1),
            }
        )
    )
    glob = (
        struct.pack("<H", 2)
        + struct.pack("<BBBHB", 4, 4, 10, 1, 0)
        + struct.pack("<BBBHB", 8, 8, 20, 3, 0)
    )
    (static / "GLOB.FLX").write_bytes(state_flex([b""] * 7 + [glob]))
    # Colliding indices across archives must retain separate container identities.
    (gamedat / "NONFIXED.DAT").write_bytes(
        _flex(
            {
                0: item(npc_num=7),
                3: item(x=700, npc_num=7) + item(4, x=1, status=8),
                8: item(),
            }
        )
    )
    return static, gamedat


def session(assets, *, source=True):
    static, gamedat = assets
    return load_u8_map_session(
        load_u8_shape_library(static / "U8SHAPES.FLX"),
        source=gamedat if source else None,
    )


def test_sources_keep_all_records_archive_identity_and_map_union(assets):
    data = session(assets)
    assert data.map_ids == [0, 3, 5, 8]
    summary = describe_u8_map_summary(data, 3)
    assert summary["fixed_records"] == 4 and summary["nonfixed_records"] == 2
    assert summary["world_records"] == 4 and summary["contained_records"] == 2
    assert summary["glob_records"] == 1
    rows = describe_u8_map_rows(data, 3)
    assert len(rows) == 6 and rows[0]["archive_kind"] == "fixed"
    for parent in (data.records(3)[0], data.records(3)[4]):
        children = u8_map_container_children(data, parent)
        assert len(children) == 1 and children[0].archive_kind == parent.archive_kind
        assert children[0].parent_record_index == 0
    assert describe_u8_map_summary(data, 0)["world_records"] == 0
    assert render_u8_browser_map(data, 0)[1]["visible_objects"] == 0


@pytest.mark.parametrize("kind", ["directory", "archive", "loose", "fixed"])
def test_supported_snapshot_kinds(assets, tmp_path, kind):
    static, gamedat = assets
    path = gamedat
    if kind == "archive":
        path = tmp_path / "U8SAVE.001"
        path.write_bytes(_save((gamedat / "NONFIXED.DAT").read_bytes()))
    elif kind == "loose":
        path = gamedat / "NONFIXED.DAT"
    data = load_u8_map_session(
        load_u8_shape_library(static / "U8SHAPES.FLX"),
        source=None if kind == "fixed" else path,
    )
    assert (data.nonfixed is None) == (kind == "fixed")
    assert (data.npc_session is not None) == (kind == "directory")


def test_filters_roof_and_height_are_applied_after_glob_expansion(assets):
    data = session(assets)
    image, info = render_u8_browser_map(
        data, 3, filters=U8MapBrowserFilters(storage="fixed", min_z=10, max_z=15)
    )
    assert info["visible_objects"] == 1  # Stamp parent Z=0; child Z=10.
    assert image.width > 1 and image.height > 1
    _, full = render_u8_browser_map(data, 3)
    _, hidden = render_u8_browser_map(
        data, 3, filters=U8MapBrowserFilters(hide_roofs=True)
    )
    assert full["visible_objects"] == 5 and hidden["visible_objects"] == 3
    rows = describe_u8_map_rows(data, 3)
    contained = filter_u8_map_rows(
        data, rows, U8MapBrowserFilters(scope="contained", min_z=10, max_z=15)
    )
    assert len(contained) == 2  # Equipment/inventory Z is not world height.
    assert (
        len(
            filter_u8_map_rows(
                data, rows, U8MapBrowserFilters(shape=4, storage="fixed")
            )
        )
        == 1
    )
    assert (
        len(filter_u8_map_rows(data, rows, U8MapBrowserFilters(query="contained"))) == 2
    )


def test_missing_and_malformed_globs_are_reported_not_invented(assets):
    data = session(assets)
    data.globs.clear()
    _, info = render_u8_browser_map(data, 3)
    assert len(info["diagnostics"]) == 1 and "Missing GLOB 7" in info["diagnostics"][0]
    data.globs[7] = b"\x01\x00"
    _, info = render_u8_browser_map(data, 3)
    assert info["diagnostics"] == ["Malformed GLOB 7; not expanded"]
    data.library.properties.clear()
    with pytest.raises(ValueError, match="roof filtering"):
        render_u8_browser_map(data, 3, filters=U8MapBrowserFilters(hide_roofs=True))


def test_editor_markers_hidden_only_in_images_including_glob_children(assets):
    data = session(assets)
    data.library.properties[3].flags |= 0x1000
    rows = describe_u8_map_rows(data, 3)
    assert len(filter_u8_map_rows(data, rows, U8MapBrowserFilters())) == 6
    _, hidden = render_u8_browser_map(data, 3)
    _, shown = render_u8_browser_map(
        data, 3, filters=U8MapBrowserFilters(hide_editor=False)
    )
    assert hidden["visible_objects"] == 3 and shown["visible_objects"] == 5


def test_snapshot_is_captured_and_npc_links_do_not_use_world_npcnum(assets):
    data = session(assets)
    # World record npc_num=7 is not linked to Mordea; only captured cache map is used.
    assert all("npc_id" not in row for row in describe_u8_map_rows(data, 3))
    assert data.npc_session is not None
    mordea = next(row for row in data.npc_session.states if row["npc_id"] == 7)
    assert mordea["npc_label"] == "Mordea"
    assert 7 in [row["npc_id"] for row in map_npc_rows(data, mordea["item_map"])]
    before = describe_u8_map_rows(data, 3)
    (assets[1] / "NONFIXED.DAT").write_bytes(b"changed on disk")
    (assets[1] / "npcdata.dat").write_bytes(b"changed on disk")
    assert describe_u8_map_rows(data, 3) == before
    assert map_npc_rows(data, mordea["item_map"])[-1]["npc_label"] == "Mordea"


def test_exports_have_real_images_valid_offline_links_and_preserve_existing_files(
    assets, tmp_path
):
    data = session(assets)
    output = tmp_path / "exports"
    export_u8_map_bundle(data, 3, output)
    links = Links()
    links.feed((output / "index.html").read_text(encoding="utf-8"))
    assert all((output / url).is_file() for url in links.urls)
    report = json.loads((output / "report.json").read_text())
    assert len(report["items"]) == 6
    for key, filename in [("sample", "overview.png"), ("isometric", "isometric.png")]:
        with Image.open(output / filename) as image:
            info = report["rendering"][key]
            assert image.size == (info["width"], info["height"])
            assert image.width > 1
    rows = list(csv.DictReader(io.StringIO((output / "objects.csv").read_text())))
    assert len(rows) == 6 and json.loads(rows[1]["status_names"])
    previous = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(ValueError, match="new directory"):
        export_u8_map_bundle(data, 3, output)
    assert previous == {path.name: path.read_bytes() for path in output.iterdir()}
    assert format_u8_map_csv([]).startswith("archive_kind,map_id")


@pytest.mark.parametrize("destination", ["static", "gamedat", "input", "loose"])
def test_output_rejects_source_directories_and_files(assets, destination):
    static, gamedat = assets
    data = session(assets)
    path = {
        "static": static / "output",
        "gamedat": gamedat / "output",
        "input": static / "FIXED.DAT",
        "loose": gamedat / "output",
    }[destination]
    if destination == "loose":
        data = load_u8_map_session(data.library, source=gamedat / "NONFIXED.DAT")
    with pytest.raises(ValueError, match="export outside|must differ"):
        validate_u8_map_output(data, path)


def invoke(assets, tmp_path, inputs, *options):
    static, gamedat = assets
    return CliRunner().invoke(
        u8_app,
        [
            "map-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--map",
            "3",
            "-o",
            str(tmp_path / "reports"),
            *options,
        ],
        input=inputs,
    )


def test_help_contract_and_noninteractive_export(assets, tmp_path):
    result = CliRunner().invoke(u8_app, ["map-browse", "--help"])
    assert result.exit_code == 0
    assert all(
        option in result.output
        for option in [
            "--map",
            "--shapes",
            "--fixed",
            "--globs",
            "--static-only",
            "--export",
        ]
    )
    result = invoke(assets, tmp_path, "", "--export")
    assert result.exit_code == 0, result.output
    old = (tmp_path / "reports/map_003_report/index.html").read_bytes()
    result = invoke(assets, tmp_path, "", "--export")
    assert (
        result.exit_code == 0
        and (tmp_path / "reports/map_003_report_002/index.html").exists()
    )
    assert (tmp_path / "reports/map_003_report/index.html").read_bytes() == old


def test_redirected_objects_containers_and_embedded_shape(
    assets, tmp_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        browser,
        "browse_u8_npc_shape",
        lambda library, number, **options: opened.append((number, options)),
    )
    result = invoke(assets, tmp_path, "O\n1\nC\n1\nS\nB\nB\nB\nB\nQ\n")
    assert result.exit_code == 0, result.output
    assert opened[0][0] == 4 and opened[0][1]["frame"] == 0
    assert "gump_x" in result.output and "parent_record_index" in result.output


def test_preview_uses_png_viewer_and_returns_to_map(assets, tmp_path, monkeypatch):
    opened = []

    def preview(path):
        with Image.open(path) as image:
            opened.append(image.size)
        return True

    monkeypatch.setattr(browser, "open_preview", preview)
    result = invoke(assets, tmp_path, "T\nI\nQ\n")
    assert result.exit_code == 0, result.output
    assert len(opened) == 2 and all(width > 1 for width, height in opened)


def test_named_npc_menu_opens_captured_slot_and_returns(assets, tmp_path, monkeypatch):
    data = session(assets)
    assert data.npc_session is not None
    mordea = next(row for row in data.npc_session.states if row["npc_id"] == 7)
    mordea["item_map"] = 3
    monkeypatch.setattr(browser, "load_u8_map_session", lambda *args, **kwargs: data)
    opened = []
    monkeypatch.setattr(
        browser,
        "browse_u8_npc_session",
        lambda captured, **options: opened.append((captured, options)),
    )
    result = invoke(assets, tmp_path, "N\n7\nB\nQ\n")
    assert result.exit_code == 0, result.output
    assert "Mordea" in result.output and len(opened) == 1
    assert opened[0][0] is data.npc_session and opened[0][1]["npc"] == 7


def test_empty_map_and_static_only_cli(assets, tmp_path):
    static, _ = assets
    result = CliRunner().invoke(
        u8_app,
        [
            "map-browse",
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--static-only",
            "--map",
            "2",
        ],
        input="O\nB\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "0 object records" in result.output and "FIXED only" in result.output


def test_filter_editing_returns_and_does_not_render_contained_records(assets, tmp_path):
    result = invoke(assets, tmp_path, "F\nV\nC\nB\nO\nB\nQ\n")
    assert result.exit_code == 0, result.output
    assert "2 object records" in result.output
    data = session(assets)
    _, info = render_u8_browser_map(
        data, 3, filters=U8MapBrowserFilters(scope="contained")
    )
    assert info["visible_objects"] == 0


def test_bad_snapshot_and_invalid_options_fail_clearly(assets, tmp_path):
    static, gamedat = assets
    (gamedat / "NONFIXED.DAT").write_bytes(b"broken")
    result = invoke(assets, tmp_path, "Q\n")
    assert result.exit_code == 1 and "ERROR" in result.output
    assert browser.run_u8_map_browser(export=True) == 1
    assert browser.run_u8_map_browser(map_id=256) == 1
    with pytest.raises(ValueError):
        replace(U8MapBrowserFilters(), min_z=40, max_z=20)
