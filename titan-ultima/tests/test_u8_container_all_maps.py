"""All-map container coverage, separate record identities and NPC preview fallbacks."""

from __future__ import annotations

import csv
import json
import struct
from pathlib import Path
from dataclasses import replace

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.u8 import container_browser_ui as browser
from titan.u8.cli import u8_app
from titan.u8.container_browser import (
    build_u8_container_session,
    export_u8_container_bundle,
    filter_u8_containers,
    u8_container_gump_composition,
    u8_inventory_rows,
)
from titan.u8.container_gump import U8ContainerGumpPreview
from titan.u8.container_records import parse_u8_inventory_id, u8_inventory_file_stem
from titan.u8.save_state import U8SaveSnapshot
from titan.u8.shape_browser import load_u8_shape_library
from tests.test_u8_cached_state import state_flex
from tests.test_u8_container_browser import inventory as inventory
from tests.test_u8_map_items import item_bytes, map_flex
from tests.test_u8_npc_animation_report import Links, case as case
from tests.test_u8_shape_browser import shape_bytes


@pytest.fixture
def all_maps(inventory):
    static, gamedat = inventory
    library = load_u8_shape_library(static / "U8SHAPES.FLX")
    (static / "U8SHAPES.FLX").write_bytes(
        state_flex([b""] + [library.records[3]] * 673)
    )
    flags = bytearray((static / "TYPEFLAG.DAT").read_bytes())
    flags.extend(bytes(674 * 8 - len(flags)))
    flags[673 * 8 + 1] = 0x60
    (static / "TYPEFLAG.DAT").write_bytes(flags)
    art = shape_bytes([(bytes(range(10, 26)), 0, 0)])
    (static / "U8GUMPS.FLX").write_bytes(state_flex([b""] + [art] * 12))
    (static / "GUMPAGE.DAT").write_bytes(struct.pack("<4h", 1, 0, 15, 1) * 12)
    root = item_bytes(shape=673, frame=0, quality=65535, next_item=65000)
    child = item_bytes(x=1, y=0x0705, frame=0, shape=5, quality=17, status=8)
    nested = item_bytes(x=1, y=0x0705, frame=0, shape=673, status=8)
    grandchild = item_bytes(x=2, y=0x0705, frame=0, shape=2, quality=42, status=8)
    orphan = item_bytes(x=6, y=0x0705, shape=2, status=8)
    invalid = item_bytes(x=65535, shape=673)
    (static / "FIXED.DAT").write_bytes(
        map_flex(
            {
                0: root + child,
                3: root + child,
                4: root + child + nested + grandchild + orphan + invalid,
            }
        )
    )
    (gamedat / "NONFIXED.DAT").write_bytes(
        map_flex({0: root + child, 3: root + child, 4: root + child, 5: root})
    )
    return static, gamedat


def captured(all_maps, **kwargs):
    static, gamedat = all_maps
    library = load_u8_shape_library(static / "U8SHAPES.FLX")
    return build_u8_container_session(
        U8SaveSnapshot.from_path(gamedat),
        library,
        gumps=load_u8_shape_library(
            static / "U8GUMPS.FLX", palette=library.palette_path
        ),
        **kwargs,
    )


def test_all_maps_live_priority_record_namespaces_and_empty_containers(all_maps):
    data = captured(all_maps)
    assert data.stored_maps == (4, 5)
    assert data.containers == [
        1,
        7,
        300,
        303,
        "FIXED:4:0",
        "FIXED:4:2",
        "FIXED:4:5",
        "NONFIXED:4:0",
        "NONFIXED:5:0",
    ]
    assert not any(
        isinstance(key, str) and key.split(":")[1] in {"0", "3"} for key in data.items
    )
    assert data.children["FIXED:4:0"] == ["FIXED:4:1", "FIXED:4:2"]
    assert data.children["FIXED:4:2"] == ["FIXED:4:3"]
    assert data.children["NONFIXED:4:0"] == ["NONFIXED:4:1"]
    assert data.items["FIXED:4:0"]["cache_id"] is None
    assert data.items["FIXED:4:0"]["quality"] == 65535
    assert data.items["FIXED:4:0"]["contents_head"] is None
    assert data.items["FIXED:4:0"]["next_item"] == 65000
    assert data.items["FIXED:4:1"]["quantity"] == 17
    assert (
        data.items["FIXED:4:1"]["npc_name"] == ""
    )  # npc_num is not a stored NPC identity
    assert [
        (row["item_id"], row["depth"]) for row in u8_inventory_rows(data, "FIXED:4:0")
    ] == [("FIXED:4:1", 1), ("FIXED:4:2", 1), ("FIXED:4:3", 2)]
    assert u8_inventory_rows(data, "NONFIXED:5:0") == []
    assert data.items["FIXED:4:4"]["diagnostics"]
    assert data.items["FIXED:4:5"]["diagnostics"]


def test_coverage_filters_and_cache_only(all_maps):
    data = captured(all_maps)
    assert filter_u8_containers(data, kind="cache") == [1, 7, 300, 303]
    assert filter_u8_containers(data, kind="npc") == [1, 7]
    assert filter_u8_containers(data, map_id=5) == ["NONFIXED:5:0"]
    assert filter_u8_containers(data, '"quantity": 42', kind="stored") == [
        "FIXED:4:0",
        "FIXED:4:2",
    ]
    assert "FIXED:4:5" in filter_u8_containers(data, kind="diagnostics")
    old = captured(all_maps, include_stored=False)
    assert old.containers == [1, 7, 300, 303] and old.fixed is None
    with pytest.raises(ValueError, match="--cache-only"):
        captured(all_maps, include_stored=False, fixed=all_maps[0] / "FIXED.DAT")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("300", 300),
        ("0x12c", 300),
        (" fixed:004:000 ", "FIXED:4:0"),
        ("NONFIXED:255:100000", "NONFIXED:255:100000"),
    ],
)
def test_inventory_selector_canonical_ids(raw, expected):
    assert parse_u8_inventory_id(raw) == expected
    assert ":" not in u8_inventory_file_stem(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "0",
        "9216",
        "FIXED:0:0",
        "FIXED:256:0",
        "FIXED:4:-1",
        "OTHER:4:0",
        "FIXED:4",
        "../../bad",
    ],
)
def test_inventory_selector_rejects_invalid_ids(raw):
    with pytest.raises(ValueError, match="U8 container browser"):
        parse_u8_inventory_id(raw)


def test_stored_composition_uses_direct_children_and_captured_bytes(all_maps):
    data = captured(all_maps)
    before = json.dumps(data.items, sort_keys=False)
    (all_maps[0] / "FIXED.DAT").write_bytes(b"changed after capture")
    (all_maps[1] / "NONFIXED.DAT").write_bytes(b"changed after capture")
    row = data.items["FIXED:4:0"]
    preview = U8ContainerGumpPreview(**row["gump_previews"][0])
    result = u8_container_gump_composition(data, "FIXED:4:0", preview)
    assert preview.shape == 7 and result.area.shape == 7
    assert [item.item_id for item in result.placements] == ["FIXED:4:1", "FIXED:4:2"]
    assert json.dumps(data.items, sort_keys=False) == before


def test_reports_have_unique_local_links_orphans_and_stored_metadata(
    all_maps, tmp_path
):
    data = captured(all_maps)
    index = export_u8_container_bundle(data, tmp_path / "report")
    for page in index.parent.rglob("*.html"):
        parser = Links()
        parser.feed(page.read_text(encoding="utf-8"))
        assert all((page.parent / url).is_file() for url in parser.urls)
    report = json.loads((index.parent / "inventory.json").read_text(encoding="utf-8"))
    assert report["coverage"]["active_map"] == 3
    assert report["coverage"]["stored_map_ids"] == [4, 5]
    assert "FIXED:4:4" in {row["item_id"] for row in report["orphaned_items"]}
    fixed_page = index.parent / "containers/fixed_m004_r000000.html"
    nonfixed_page = index.parent / "containers/nonfixed_m004_r000000.html"
    assert fixed_page.is_file() and nonfixed_page.is_file()
    assert "Map 4 · FIXED record 0" in fixed_page.read_text(encoding="utf-8")
    with (index.parent / "containers.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert (
        next(row for row in rows if row["item_id"] == "FIXED:4:0")["record_index"]
        == "0"
    )
    scope = export_u8_container_bundle(data, tmp_path / "one", container="FIXED:4:0")
    assert len(list((scope.parent / "containers").glob("*.html"))) == 2


def test_map_filtered_exports_and_missing_archives_are_explicit(all_maps, tmp_path):
    data = captured(all_maps, map_id=5)
    index = export_u8_container_bundle(data, tmp_path / "map5")
    report = json.loads((index.parent / "inventory.json").read_text(encoding="utf-8"))
    assert [row["item_id"] for row in report["containers"]] == ["NONFIXED:5:0"]
    (all_maps[0] / "FIXED.DAT").unlink()
    data = captured(all_maps)
    assert data.fixed is None and "NONFIXED:5:0" in data.containers
    assert any("FIXED.DAT unavailable" in issue for issue in data.diagnostics)
    snapshot = replace(data.snapshot, nonfixed=None)
    data = build_u8_container_session(snapshot, data.library)
    assert any("NONFIXED.DAT unavailable" in issue for issue in data.diagnostics)


def test_npc_backpack_fallback_saved_gump_priority_and_disable(all_maps):
    data = captured(all_maps)
    row = data.items[7]
    preview = U8ContainerGumpPreview(**row["gump_previews"][0])
    assert preview.source == "npc_backpack_fallback" and preview.shape == 2
    assert "fallback" in preview.description
    assert data.items[1]["gump_previews"][0]["shape"] == 1
    assert captured(all_maps, npc_backpack=False).items[7]["gump_previews"] == []
    # The fixture's saved open gump for cache 300 retains shape 2 despite unknown class 3.
    assert data.items[300]["gump_previews"][0]["source"] == "saved_gumps"


def test_stored_ui_nested_navigation_gump_and_npc_fallback(
    all_maps, tmp_path, monkeypatch
):
    data = captured(all_maps)
    answers = iter(["G", "FIXED:4:2", "G", "P", "B", "7", "G", "B", "Q"])
    monkeypatch.setattr(
        browser, "_container_menu", lambda *args, **kwargs: next(answers)
    )
    opened = []
    monkeypatch.setattr(
        browser,
        "open_preview",
        lambda path: opened.append((Path(path).name, Image.open(path).size)),
    )
    browser.browse_u8_container_session(
        data, container="FIXED:4:0", output=tmp_path / "exports"
    )
    assert len(opened) == 3 and all(size == (16, 1) for _, size in opened)
    assert "fixed_m004_r000000" in opened[0][0]
    assert "fixed_m004_r000002" in opened[1][0]


def test_all_map_cli_help_selectors_map_filter_and_cache_mode(all_maps, tmp_path):
    result = CliRunner().invoke(u8_app, ["container-browse", "--help"])
    assert result.exit_code == 0
    assert all(
        option in result.stdout
        for option in ("--fixed", "--map", "--cache-only", "--npc-backpack")
    )
    static, gamedat = all_maps
    common = [
        "container-browse",
        str(gamedat),
        "--shapes",
        str(static / "U8SHAPES.FLX"),
        "--export",
    ]
    for label, extra, count in [
        ("stored", ["--container", "fixed:4:0"], 2),
        ("map5", ["--map", "5"], 1),
        ("cache", ["--cache-only", "--no-npc-backpack"], 4),
    ]:
        output = tmp_path / label
        result = CliRunner().invoke(u8_app, [*common, *extra, "-o", str(output)])
        assert result.exit_code == 0, result.stdout
        index = next(output.glob("*/index.html"))
        report = json.loads(
            (index.parent / "inventory.json").read_text(encoding="utf-8")
        )
        assert len(report["containers"]) == count
    result = CliRunner().invoke(u8_app, [*common, "--container", "fixed:4:-1"])
    assert result.exit_code == 2


def test_explicit_bad_fixed_fails_and_implicit_bad_fixed_is_diagnosed(all_maps):
    path = all_maps[0] / "FIXED.DAT"
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="FIXED.DAT"):
        captured(all_maps, fixed=path)
    data = captured(all_maps)
    assert data.fixed is None
    assert any(
        "Stored FIXED inventories unavailable" in issue for issue in data.diagnostics
    )
