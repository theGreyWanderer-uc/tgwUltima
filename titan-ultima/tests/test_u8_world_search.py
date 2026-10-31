"""World source authority, containment coordinates, native eggs and safe query exports."""

from __future__ import annotations

import csv
import json
import struct
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from titan.u8 import world_search_ui as browser
from titan.u8.cli import u8_app
from titan.u8.egg_search import (
    U8EggSearchFilters,
    describe_u8_egg_trigger,
    query_u8_egg_triggers,
)
from titan.u8.map_browser import load_u8_map_session
from titan.u8.shape_browser import load_u8_shape_library
from titan.u8.world_search import (
    U8WorldSearchFilters,
    build_u8_world_search_session,
    export_u8_world_search_bundle,
    format_u8_world_search_results,
    next_u8_world_search_export,
    query_u8_world_items,
)
from tests.test_u8_cached_state import state_flex
from tests.test_u8_map_browser import assets as assets
from tests.test_u8_map_render import _flex
from tests.test_u8_npc_animation_report import case as case


@pytest.fixture
def search_assets(assets):
    static, gamedat = assets
    flags = bytearray((static / "TYPEFLAG.DAT").read_bytes())
    flags[2 * 8 + 1] = 3 << 4
    (static / "TYPEFLAG.DAT").write_bytes(flags)
    from titan.flex import FlexArchive

    blocks = FlexArchive.from_file(str(gamedat / "itemcach.dat")).records
    arrays, metadata = bytearray(blocks[0]), bytearray(blocks[1])
    struct.pack_into("<h", metadata, 0, 3)
    struct.pack_into("<H", arrays, 2, 800)
    struct.pack_into("<H", arrays, 18432 + 2, 900)
    arrays[36864 + 1] = 12
    struct.pack_into("<H", arrays, 92160 + 2, 0)
    (gamedat / "itemcach.dat").write_bytes(state_flex([bytes(arrays), bytes(metadata)]))
    return static, gamedat


def session(assets, *, live=True, names=None):
    static, gamedat = assets
    return build_u8_world_search_session(
        load_u8_map_session(
            load_u8_shape_library(static / "U8SHAPES.FLX"),
            source=gamedat if live else None,
            names=names,
        )
    )


def test_loaded_map_cache_replaces_both_archives_and_registry(search_assets):
    data = session(search_assets)
    assert data.coverage["active_map"] == 3
    assert data.coverage["stored_records_replaced_by_cache"] == 7
    assert "CACHE:1" in data.by_identity and "CACHE:300" in data.by_identity
    assert not any(
        row["archive_kind"] != "cache" and row["map_id"] in {0, 3} for row in data.rows
    )
    assert "FIXED:5:0" in data.by_identity and "NONFIXED:8:0" in data.by_identity
    assert "CACHE:5" not in data.by_identity  # stale nonzero bytes in a free slot
    row = data.by_identity["CACHE:1"]
    assert row["world_x"] == 800 and row["map_id"] == 3
    assert (
        row["npc_num"] == 42 and row["owner_npc_id"] == 1
    )  # identity is slot, not npc byte


def test_contained_item_search_uses_owner_position_and_name(search_assets, tmp_path):
    names = tmp_path / "names.csv"
    names.write_text("npc_id,name\n1,Test Avatar\n", encoding="utf-8")
    data = session(search_assets, names=names)
    child = data.by_identity["CACHE:300"]
    assert (child["x"], child["y"], child["z"]) == (1, 0xABCD, 5)
    assert (child["world_x"], child["world_y"], child["world_z"]) == (800, 900, 12)
    assert child["owner_name"] == "Test Avatar"
    filters = U8WorldSearchFilters(
        scope="contained",
        query="test avatar",
        map_id=3,
        area=(790, 890, 810, 910),
        min_z=12,
        max_z=12,
    )
    assert [row["identity"] for row in query_u8_world_items(data, filters)] == [
        "CACHE:300"
    ]
    assert child not in query_u8_world_items(data)
    assert not query_u8_world_items(data, replace(filters, area=(0, 0, 10, 10)))


def test_static_identity_collisions_and_containment(search_assets):
    data = session(search_assets, live=False)
    assert {"FIXED:3:0", "FIXED:3:1", "FIXED:3:3"}.issubset(data.by_identity)
    child = data.by_identity["FIXED:3:1"]
    assert child["world_x"] == 512 and child["container_id"] == "FIXED:3:0"
    assert data.coverage["live_cache_items"] == 0
    assert not query_u8_world_items(data, U8WorldSearchFilters(map_id=0))


def test_optional_glob_search_has_unique_child_ids_and_post_expansion_filters(
    search_assets,
):
    data = session(search_assets, live=False)
    filters = U8WorldSearchFilters(shapes=(3,), map_id=3, min_z=20, max_z=20)
    assert not query_u8_world_items(data, filters)
    rows = query_u8_world_items(data, replace(filters, expand_globs=True))
    assert len(rows) == 1
    assert rows[0]["identity"] == "GLOB:FIXED:3:3:1"
    assert (rows[0]["world_x"], rows[0]["world_y"], rows[0]["world_z"]) == (
        528,
        528,
        20,
    )
    assert rows[0]["quality"] is None and rows[0]["glob_parent"] == "FIXED:3:3"
    assert rows[0]["status"] == 0x82
    assert (
        query_u8_world_items(
            data, replace(filters, expand_globs=True, shape_flag_mask=0x400)
        )
        == rows
    )


@pytest.mark.parametrize(
    "change",
    [
        {"map_id": 256},
        {"shapes": (2048,)},
        {"scope": "oops"},
        {"storage": "oops"},
        {"min_z": 20, "max_z": 10},
        {"area": (-1, 0, 10, 10)},
        {"status_mask": 65536},
    ],
)
def test_invalid_world_filters_fail_before_search(change):
    with pytest.raises(ValueError):
        U8WorldSearchFilters(**change)


@pytest.fixture
def egg_assets(search_assets):
    static, gamedat = search_assets
    flags = bytearray(11 * 8)
    for shape, family in ((2, 3), (5, 4), (6, 8), (7, 7), (8, 3), (10, 8)):
        flags[shape * 8 + 1] = family << 4
    flags[9 * 8] = 0x80
    (static / "TYPEFLAG.DAT").write_bytes(flags)

    def egg(shape, *, frame=0, q=0, npc=0, map_byte=0, status=0, x=1024, y=1024):
        return struct.pack(
            "<HHBHBHHBBH", x, y, 40, shape, frame, status, q, npc, map_byte, 0
        )

    (static / "FIXED.DAT").write_bytes(
        _flex(
            {
                3: egg(6, frame=1, q=9),  # stale active-map target must not match
                5: egg(5, q=7, npc=0x23)
                + egg(6, q=0x0209, npc=0x11, map_byte=5)
                + egg(6, frame=1, q=9)
                + egg(7, q=(6 << 11) | 75, npc=5, map_byte=0x4B)
                + egg(8, q=7)
                + egg(9)
                + egg(10, frame=2, q=11),
            }
        )
    )
    return static, gamedat


def test_native_egg_payloads_and_cross_map_destination_links(egg_assets):
    data = session(egg_assets)
    rows = query_u8_egg_triggers(data)
    by_kind = {row["trigger_kind"]: row for row in rows}
    assert set(by_kind) == {
        "usecode",
        "teleport",
        "destination",
        "monster",
        "glob",
        "ambient",
        "teleport_other",
    }
    usecode = by_kind["usecode"]
    assert usecode["usecode_class"] == 0x486 and usecode["hatch_event"] == 7
    assert usecode["npc_num"] == 0x23 and not usecode["is_npc"]
    assert (
        usecode["range_x_units"],
        usecode["range_y_units"],
        usecode["z_tolerance"],
    ) == (64, 96, 48)
    assert usecode["trigger_bounds"] == [960, 928, 1088, 1120, -8, 88]
    teleport = by_kind["teleport"]
    assert teleport["map_id"] == 5 and teleport["destination_map"] == 5
    assert teleport["destination_id"] == 9 and teleport["teleport_fire_raw"] == 2
    assert teleport["destination_matches"] == ["FIXED:5:2"]
    monster = by_kind["monster"]
    assert (
        monster["monster_shape"],
        monster["monster_count"],
        monster["monster_id"],
        monster["monster_activity"],
        monster["probability_percent"],
    ) == (75, 5, 9, 3, 80)
    assert monster["range_x_units"] is None
    assert by_kind["ambient"]["ambient_events"] == [15, 16]
    assert by_kind["destination"]["range_x_units"] is None
    assert by_kind["teleport_other"]["destination_map"] is None
    selected = query_u8_egg_triggers(
        data, U8WorldSearchFilters(map_id=5), U8EggSearchFilters(usecode_class=0x486)
    )
    assert [row["identity"] for row in selected] == ["FIXED:5:0"]


def test_native_invalid_probability_and_glob_payload_are_not_guessed(egg_assets):
    data = session(egg_assets)
    row = dict(data.by_identity["FIXED:5:3"], quality=(15 << 11) | 75)
    result = describe_u8_egg_trigger(row)
    assert result["probability_percent"] is None and result["diagnostics"]
    row.update(
        archive_kind="glob", family=4, quality=None, npc_num=None, map_num_raw=None
    )
    result = describe_u8_egg_trigger(row)
    assert result["usecode_class"] is None and result["diagnostics"]


def test_destination_resolution_precedes_map_type_and_area_filters(egg_assets):
    data = session(egg_assets)
    rows = query_u8_egg_triggers(
        data,
        U8WorldSearchFilters(shapes=(6,), map_id=5),
        U8EggSearchFilters(kinds=("teleport",), destination_map=5, destination_id=9),
    )
    assert len(rows) == 1 and rows[0]["destination_matches"] == ["FIXED:5:2"]
    data.by_identity["FIXED:5:2"]["quality"] = 10
    rows = query_u8_egg_triggers(
        data, egg_filters=U8EggSearchFilters(kinds=("teleport",))
    )
    assert (
        rows[0]["destination_matches"] == []
        and "0 captured" in rows[0]["diagnostics"][-1]
    )


def test_metadata_missing_is_not_silently_treated_as_no_eggs(egg_assets):
    data = session(egg_assets)
    data.maps.library.properties.clear()
    with pytest.raises(ValueError, match="TYPEFLAG"):
        query_u8_egg_triggers(data)


@pytest.mark.parametrize("command", ["world-query", "egg-query"])
def test_cli_help_contract(command):
    result = CliRunner().invoke(u8_app, [command, "--help"])
    assert result.exit_code == 0
    for option in (
        "--shapes",
        "--map",
        "--scope",
        "--area",
        "--expand-globs",
        "--export",
        "--format",
        "--output",
    ):
        assert option in result.stdout
    if command == "egg-query":
        assert "--class" in result.stdout and "--destination-id" in result.stdout


def test_cli_machine_json_and_validation(egg_assets):
    static, gamedat = egg_assets
    runner = CliRunner()
    arguments = [str(gamedat), "--shapes", str(static / "U8SHAPES.FLX")]
    result = runner.invoke(
        u8_app, ["egg-query", *arguments, "--class", "0x486", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["usecode_class"] == 0x486
    for options in (
        ["--shape", "bad"],
        ["--min-z", "20", "--max-z", "10"],
        ["--storage", "oops"],
        ["--type", "usecode"],
    ):
        result = runner.invoke(
            u8_app, ["world-query", *arguments, *options, "--format", "json"]
        )
        assert result.exit_code == 1
    assert browser.parse_u8_search_number("0076") == 76
    assert browser.parse_u8_search_area("20,30,10,5") == (10, 5, 20, 30)


def test_exports_preserve_sources_and_old_reports_with_empty_headers(
    search_assets, tmp_path
):
    data = session(search_assets)
    data.maps.library.names[1] = "</script><img src=x onerror=alert(1)>"
    filters = U8WorldSearchFilters(shapes=(1,))
    rows = query_u8_world_items(data, filters)
    for row in rows:
        row["shape_name"] = data.maps.library.names[1]
    root = tmp_path / "reports"
    first = next_u8_world_search_export(root)
    export_u8_world_search_bundle(data, rows, first, filters=filters)
    before = {path: path.read_bytes() for path in first.rglob("*") if path.is_file()}
    page = (first / "index.html").read_text(encoding="utf-8")
    assert "\\u003c/script>" in page and "onerror=alert" in page
    assert 'id="previous"' in page and 'id="search"' in page
    report = json.loads((first / "report.json").read_text())
    assert report["result_count"] == len(rows) and report["sprite_preview_count"] >= 1
    with (first / "results.csv").open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == len(rows)
    second = next_u8_world_search_export(root)
    export_u8_world_search_bundle(
        data, [], second, filters=replace(filters, query="no matches")
    )
    assert "identity" in (second / "results.csv").read_text()
    assert all(path.read_bytes() == content for path, content in before.items())
    for bad in (
        first,
        data.maps.library.path.parent / "report",
        search_assets[1] / "report",
    ):
        with pytest.raises(ValueError):
            export_u8_world_search_bundle(data, rows, bad, filters=filters)
    assert json.loads(format_u8_world_search_results([], "json")) == []


def test_menu_long_ids_and_shape_link_retain_frame(
    search_assets, tmp_path, monkeypatch
):
    data = session(search_assets)
    selected = iter(["S", "B"])
    monkeypatch.setattr(browser, "_search_menu", lambda *args, **kwargs: next(selected))
    from titan.u8 import shape_browser_ui

    calls = []
    monkeypatch.setattr(
        shape_browser_ui,
        "browse_u8_npc_shape",
        lambda library, shape, *, frame=0, output=None: calls.append((shape, frame)),
    )
    browser._inspect_u8_search_result(
        data,
        data.by_identity["CACHE:1"],
        tmp_path,
        U8WorldSearchFilters(),
        U8EggSearchFilters(),
        False,
    )
    assert calls == [(1, 1)]
    choices = iter(["FIXED:5:0", "Q"])
    monkeypatch.setattr(browser, "_search_menu", lambda *args, **kwargs: next(choices))
    details = []
    monkeypatch.setattr(
        browser,
        "_inspect_u8_search_result",
        lambda session, row, *args: details.append(row["identity"]),
    )
    browser.browse_u8_world_search(
        data, filters=U8WorldSearchFilters(map_id=5), output=tmp_path
    )
    assert details == ["FIXED:5:0"]
