"""Native inventory links, corrupt ancestry, contextual fields and preserving reports."""

from __future__ import annotations

import csv
import json
import struct
from dataclasses import replace

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.flex import FlexArchive

from titan.u8 import container_browser_ui as browser
from titan.u8.cli import u8_app
from titan.u8.container_browser import (
    build_u8_container_session,
    export_u8_container_bundle,
    filter_u8_containers,
    u8_container_gump_images,
    u8_container_gump_composition,
    u8_container_item_image,
    u8_inventory_rows,
    validate_u8_container_output,
)
from titan.u8.itemcach import U8ItemCache
from titan.u8.container_gump import U8_CONTAINER_GUMP_SHAPES, U8ContainerGumpPreview
from titan.u8.gumpage import U8GumpAreas
from titan.u8.map_browser import load_u8_map_session
from titan.u8.save_state import U8SaveSnapshot
from titan.u8.shape_browser import load_u8_shape_library
from tests.test_u8_cached_state import item_blocks, save_bytes, state_flex
from tests.test_u8_map_browser import assets as assets
from tests.test_u8_native_runtime_state import container_bytes, gumps_bytes
from tests.test_u8_npc_animation_report import Links, case as case
from tests.test_u8_shape_browser import shape_bytes


def put_item(
    arrays, number, *, shape=3, parent=None, quality=0, next_item=0, status=0, frame=0
):
    values = (
        parent if parent is not None else 256,
        0x0705,
        6,
        shape,
        frame,
        status | (8 if parent is not None else 0),
        quality,
        0,
        3,
        next_item,
    )
    for offset, code, value in zip(
        (0, 18432, 36864, 46080, 64512, 73728, 92160, 110592, 119808, 129024),
        ("H", "H", "B", "H", "B", "H", "H", "B", "B", "H"),
        values,
    ):
        struct.pack_into(
            "<" + code, arrays, offset + number * struct.calcsize(code), value
        )


@pytest.fixture
def inventory(case):
    static, gamedat = case
    sprites = shape_bytes([(bytes((5, 6, 7)), 0, 0), (bytes((8, 9)), 0, 1)])
    (static / "U8SHAPES.FLX").write_bytes(state_flex([b""] + [sprites] * 5))
    flags = bytearray(6 * 8)
    for number, family in enumerate((0, 6, 2, 6, 0, 9)):
        flags[number * 8 + 1] = family << 4
    (static / "TYPEFLAG.DAT").write_bytes(flags)
    (static / "U8GUMPS.FLX").write_bytes(
        state_flex([b"", b"", shape_bytes([(bytes((10, 11, 12, 13)), 0, 0)])])
    )
    arrays, metadata = map(bytearray, item_blocks())
    put_item(arrays, 1, shape=1, quality=300, status=64, frame=1)
    put_item(arrays, 7, shape=1, quality=0, status=64)
    put_item(arrays, 300, shape=3, parent=1, quality=306, next_item=302, status=0x200)
    put_item(arrays, 301, shape=2, parent=300, quality=42)
    put_item(arrays, 302, shape=4, parent=1, quality=999, status=0x20)
    put_item(arrays, 303, shape=3)
    put_item(arrays, 304, shape=4, parent=65535)
    put_item(arrays, 305, shape=3, parent=300)  # stale free item must not appear
    put_item(arrays, 306, shape=5, parent=300, quality=17, next_item=301)
    free_items = [
        number
        for number in range(256, 9216)
        if number not in {300, 301, 302, 303, 304, 306}
    ]
    for index, number in enumerate(free_items):
        struct.pack_into(
            "<H",
            arrays,
            129024 + number * 2,
            free_items[index + 1] if index + 1 < len(free_items) else 0,
        )
    struct.pack_into("<h", metadata, 0, 3)
    struct.pack_into(
        "<h6Hh", metadata, 16394, len(free_items), 253, 256, 2, 9215, 255, 0, 0
    )
    (gamedat / "itemcach.dat").write_bytes(state_flex([bytes(arrays), bytes(metadata)]))
    raw = bytearray(256 * 49)
    (gamedat / "npcdata.dat").write_bytes(state_flex([bytes(raw)]))
    gump = bytearray(container_bytes(300, frame=0))
    struct.pack_into("<h", gump, 56, 2)
    (gamedat / "GUMPS.DAT").write_bytes(gumps_bytes([bytes(gump)]))
    return static, gamedat


def session(inventory):
    static, gamedat = inventory
    library = load_u8_shape_library(static / "U8SHAPES.FLX")
    gumps = load_u8_shape_library(static / "U8GUMPS.FLX", palette=library.palette_path)
    return build_u8_container_session(
        U8SaveSnapshot.from_path(gamedat), library, gumps=gumps
    )


def changed_cache(data, mutate):
    blocks = list(FlexArchive.from_bytes(data.snapshot.item_cache.to_bytes()).records)
    arrays = bytearray(blocks[0])
    mutate(arrays)
    blocks[0] = bytes(arrays)
    snapshot = replace(
        data.snapshot, item_cache=U8ItemCache.from_bytes(state_flex(blocks))
    )
    return build_u8_container_session(snapshot, data.library, gumps=data.gumps)


def test_native_parent_links_order_quantity_and_empty_inventories(inventory):
    data = session(inventory)
    assert data.containers == [1, 7, 300, 303]
    assert data.children[1] == [300, 302]
    assert data.children[300] == [306, 301]
    assert 305 not in data.items
    rows = u8_inventory_rows(data, 1)
    assert [(row["item_id"], row["depth"]) for row in rows] == [
        (300, 1),
        (306, 2),
        (301, 2),
        (302, 1),
    ]
    assert data.items[301]["quantity"] == 42 and data.items[306]["quantity"] == 17
    assert (
        data.items[300]["quantity"] == 1
        and data.items[300]["quality_meaning"] == "contents_head"
    )
    assert data.items[302]["quantity"] == 1 and data.items[302]["quality"] == 999
    assert (
        data.items[300]["gump_x"],
        data.items[300]["gump_y"],
        data.items[300]["equipment_slot"],
    ) == (5, 7, 6)
    assert u8_inventory_rows(data, 303) == []


def test_names_are_slot_bound_and_owner_map_is_inherited(inventory):
    data = session(inventory)
    assert data.items[1]["npc_name"] == "Avatar"
    assert data.items[7]["npc_name"] == "Mordea"
    assert data.items[301]["owner_name"] == "Avatar"
    assert data.items[301]["owner_npc_id"] == 1
    assert data.items[301]["map_id"] == 3
    assert data.items[303]["map_id"] == 3
    assert data.items[304]["map_id"] is None


@pytest.mark.parametrize(
    "query,kind,expected",
    [
        ("Mordea", "all", [7]),
        ("", "npc", [1, 7]),
        ("", "container", [300, 303]),
        ("42", "all", [1, 300]),
    ],
)
def test_search_includes_nested_contents_and_kind(inventory, query, kind, expected):
    assert filter_u8_containers(session(inventory), query, kind=kind) == expected


@pytest.mark.parametrize("parent", [0, 305, 65535, 300])
def test_broken_parents_and_self_cycles_remain_inspectable(inventory, parent):
    data = changed_cache(
        session(inventory),
        lambda arrays: put_item(arrays, 300, parent=parent, quality=306),
    )
    assert data.items[300]["diagnostics"]
    assert data.items[300]["root_item_id"] is None
    assert len(u8_inventory_rows(data, 300)) == 2


def test_multi_item_cycle_is_bounded_and_head_disagreement_retains_children(inventory):
    def mutate(arrays):
        put_item(arrays, 300, parent=303, quality=65535)
        put_item(arrays, 303, parent=300, quality=300)

    data = changed_cache(session(inventory), mutate)
    assert {row["item_id"] for row in u8_inventory_rows(data, 300)} == {301, 306, 303}
    assert any("containment cycle" in issue for issue in data.diagnostics)
    assert any("absent from head list" in issue for issue in data.diagnostics)


def test_contents_next_cycle_is_reported_and_each_item_once(inventory):
    data = changed_cache(
        session(inventory),
        lambda arrays: put_item(
            arrays, 301, shape=2, parent=300, quality=42, next_item=306
        ),
    )
    assert data.children[300] == [306, 301]
    assert any("contents list cycle" in issue for issue in data.diagnostics)


def test_native_preview_flip_and_saved_gump_namespace(inventory):
    data = session(inventory)
    flipped = u8_container_item_image(data, 302)
    native = data.library.image(4, 0)
    assert flipped.size == native.size
    assert flipped.getpixel((0, 0)) == native.getpixel((native.width - 1, 0))
    saved = u8_container_gump_images(data, 300)
    assert len(saved) == 1 and saved[0][1].width == 4
    assert u8_container_gump_images(data, 303) == []


@pytest.mark.parametrize(
    "shape,gump",
    [
        (78, 7),
        (115, 4),
        (116, 10),
        (117, 7),
        (185, 14),
        (203, 13),
        (204, 13),
        (205, 13),
        (208, 13),
        (218, 12),
        (219, 12),
        (235, 12),
        (237, 12),
        (306, 13),
        (307, 13),
        (332, 12),
        (358, 12),
        (529, 2),
        (618, 7),
        (637, 3),
        (673, 7),
    ],
)
def test_closed_container_uses_verified_class_gump(inventory, shape, gump):
    data = session(inventory)
    data.library.properties[shape] = replace(
        data.library.properties[3], shape_num=shape
    )
    data.gumps.records[gump] = data.gumps.records[2]
    data.snapshot = replace(data.snapshot, gumps=None)
    data = changed_cache(
        data, lambda arrays: put_item(arrays, 300, shape=shape, parent=1, quality=306)
    )
    preview = data.items[300]["gump_previews"][0]
    assert preview == {
        "index": None,
        "shape": gump,
        "frame": 0,
        "source": "verified_usecode",
        "usecode_class": shape,
    }
    assert U8_CONTAINER_GUMP_SHAPES[shape] == gump
    assert u8_container_gump_images(data, 300)[0][1].size == (4, 1)


def test_saved_gump_overrides_closed_container_default(inventory):
    data = session(inventory)
    data.library.properties[673] = replace(data.library.properties[3], shape_num=673)
    data = changed_cache(
        data, lambda arrays: put_item(arrays, 300, shape=673, parent=1, quality=306)
    )
    assert data.items[300]["gump_previews"] == [
        {
            "index": 0,
            "shape": 2,
            "frame": 0,
            "source": "saved_gumps",
            "usecode_class": None,
        }
    ]
    assert u8_container_gump_images(data, 300)[0][1].size == (4, 1)


def test_avatar_dead_npc_and_unknown_living_npc_gump_selection(inventory):
    from titan.u8.npcdata import U8NpcData

    data = session(inventory)
    assert data.items[1]["gump_previews"][0]["shape"] == 1
    assert data.items[7]["gump_previews"][0]["source"] == "npc_backpack_fallback"
    assert data.items[7]["gump_previews"][0]["shape"] == 2
    raw = bytearray(256 * 49)
    struct.pack_into("<H", raw, 7 * 49 + 47, 0x10)
    snapshot = replace(
        data.snapshot, npc_data=U8NpcData.from_bytes(state_flex([bytes(raw)]))
    )
    result = build_u8_container_session(snapshot, data.library, gumps=data.gumps)
    assert result.items[7]["gump_previews"][0]["source"] == "native_dead_npc"
    assert result.items[7]["gump_previews"][0]["shape"] == 12
    missing_npcs = build_u8_container_session(
        replace(snapshot, npc_data=None), data.library
    )
    assert (
        missing_npcs.items[1]["gump_previews"][0]["source"] == "npc_backpack_fallback"
    )
    temporary = changed_cache(
        data, lambda arrays: put_item(arrays, 1, shape=1, status=0x80)
    )
    assert temporary.items[1]["gump_previews"][0]["source"] == "npc_backpack_fallback"
    disabled = build_u8_container_session(
        data.snapshot, data.library, npc_backpack=False
    )
    assert disabled.items[7]["gump_previews"] == []
    assert disabled.items[1]["gump_previews"][0]["shape"] == 1


def test_mapped_shape_needs_container_family_and_valid_gump_graphics(
    inventory, tmp_path
):
    data = session(inventory)
    data.snapshot = replace(data.snapshot, gumps=None)
    data.library.properties[673] = replace(
        data.library.properties[3], shape_num=673, family=0
    )
    generic = changed_cache(
        data, lambda arrays: put_item(arrays, 300, shape=673, parent=1, quality=306)
    )
    assert generic.items[300]["gump_previews"] == []
    data.library.properties[673] = replace(data.library.properties[3], shape_num=673)
    mapped = changed_cache(
        data, lambda arrays: put_item(arrays, 300, shape=673, parent=1, quality=306)
    )
    assert mapped.items[300]["gump_previews"][0]["shape"] == 7
    with pytest.raises(ValueError):
        u8_container_gump_images(mapped, 300)
    index = export_u8_container_bundle(mapped, tmp_path / "missing_gump", container=300)
    report = json.loads((index.parent / "inventory.json").read_text(encoding="utf-8"))
    assert any("gump preview unavailable" in issue for issue in report["diagnostics"])


def test_missing_graphics_and_npcdata_keep_inventory_links(inventory):
    data = session(inventory)
    snapshot = replace(data.snapshot, npc_data=None)
    plain = build_u8_container_session(snapshot)
    assert plain.containers == [1, 7, 300]
    assert plain.items[301]["quantity"] is None
    assert len(u8_inventory_rows(plain, 1)) == 4
    with pytest.raises(ValueError, match="graphics unavailable"):
        u8_container_item_image(plain, 300)


def test_full_npc_frames_are_retained_in_inventory_rows(inventory):
    data = session(inventory)
    from titan.u8.npcdata import U8NpcData

    raw = bytearray(256 * 49)
    raw[49 + 7] = 1
    snapshot = replace(
        data.snapshot, npc_data=U8NpcData.from_bytes(state_flex([bytes(raw)]))
    )
    result = build_u8_container_session(snapshot, data.library)
    assert result.items[1]["frame"] == 257


def test_fresh_reports_have_resolving_links_pixels_names_and_membership(
    inventory, tmp_path
):
    data = session(inventory)
    names = tmp_path / "names.csv"
    names.write_text("npc_id,name\n1,<Avatar & friends>\n", encoding="utf-8")
    data = build_u8_container_session(
        data.snapshot, data.library, gumps=data.gumps, names=names
    )
    output = tmp_path / "report"
    index = export_u8_container_bundle(data, output, container=1)
    assert index.exists()
    assert "&lt;Avatar &amp; friends&gt;" in index.read_text(encoding="utf-8")
    report = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
    assert [row["item_id"] for row in report["containers"]] == [1, 300]
    assert report["inventories"]["1"][1]["owner_name"] == "<Avatar & friends>"
    with (output / "contents.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert b"\r\r\n" not in (output / "contents.csv").read_bytes()
    assert len(rows) == 6  # Each inventory has its own membership rows.
    assert {row["inventory_id"] for row in rows} == {"1", "300"}
    assert len(list((output / "containers").glob("*.html"))) == 2
    for path in output.rglob("*.html"):
        links = Links()
        links.feed(path.read_text(encoding="utf-8"))
        assert all((path.parent / url).is_file() for url in links.urls)
    assert (
        Image.open(output / "images/item_0302.png").tobytes()
        == u8_container_item_image(data, 302).tobytes()
    )
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="new directory"):
        export_u8_container_bundle(data, output)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_preview_errors_are_in_json_and_html(inventory, tmp_path):
    data = changed_cache(
        session(inventory),
        lambda arrays: put_item(
            arrays, 301, shape=2, parent=300, quality=42, frame=255
        ),
    )
    index = export_u8_container_bundle(data, tmp_path / "broken")
    report = json.loads((index.parent / "inventory.json").read_text(encoding="utf-8"))
    assert any("sprite preview unavailable" in issue for issue in report["diagnostics"])
    assert "sprite preview unavailable" in index.read_text(encoding="utf-8")


def test_all_export_retains_unreachable_orphaned_items(inventory, tmp_path):
    index = export_u8_container_bundle(session(inventory), tmp_path / "all")
    report = json.loads((index.parent / "inventory.json").read_text(encoding="utf-8"))
    assert [row["item_id"] for row in report["orphaned_items"]] == [304]
    assert 304 in {row["item_id"] for row in report["items"]}
    with (index.parent / "orphaned_items.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert next(csv.DictReader(stream))["item_id"] == "304"


@pytest.mark.parametrize("destination", ["state", "graphics", "input"])
def test_rejects_live_source_destinations(inventory, destination):
    static, gamedat = inventory
    target = {
        "state": gamedat / "report",
        "graphics": static / "report",
        "input": gamedat / "itemcach.dat",
    }[destination]
    with pytest.raises(ValueError):
        validate_u8_container_output(session(inventory), target)


def test_native_archive_and_missing_cache(inventory, tmp_path):
    static, gamedat = inventory
    path = tmp_path / "U8SAVE.001"
    path.write_bytes(
        save_bytes(
            [(file.name.upper(), file.read_bytes()) for file in gamedat.iterdir()]
        )
    )
    data = build_u8_container_session(
        U8SaveSnapshot.from_path(path), load_u8_shape_library(static / "U8SHAPES.FLX")
    )
    assert data.containers == [1, 7, 300, 303]
    with pytest.raises(ValueError, match="ITEMCACH"):
        build_u8_container_session(replace(data.snapshot, item_cache=None))


def test_map_link_reuses_captured_snapshot_after_source_changes(assets):
    static, gamedat = assets
    snapshot = U8SaveSnapshot.from_path(gamedat)
    (gamedat / "NONFIXED.DAT").write_bytes(b"changed after capture")
    maps = load_u8_map_session(
        load_u8_shape_library(static / "U8SHAPES.FLX"), snapshot=snapshot
    )
    assert maps.snapshot is snapshot and maps.nonfixed is snapshot.nonfixed
    assert maps.npc_session.source.cache is snapshot.item_cache


def test_help_and_repeatable_cli_exports(inventory, tmp_path):
    help_result = CliRunner().invoke(u8_app, ["container-browse", "--help"])
    assert help_result.exit_code == 0
    assert all(
        option in help_result.stdout
        for option in ("--container", "--names", "--shapes", "--data-only", "--export")
    )
    static, gamedat = inventory
    command = [
        "container-browse",
        str(gamedat),
        "--shapes",
        str(static / "U8SHAPES.FLX"),
        "--container",
        "1",
        "--export",
        "-o",
        str(tmp_path / "exports"),
    ]
    for _ in range(2):
        result = CliRunner().invoke(u8_app, command)
        assert result.exit_code == 0, result.stdout
    assert len(list((tmp_path / "exports").glob("*/index.html"))) == 2
    result = CliRunner().invoke(
        u8_app,
        [
            "container-browse",
            str(gamedat),
            "--data-only",
            "--export",
            "-o",
            str(tmp_path / "data"),
        ],
    )
    assert result.exit_code == 0, result.stdout


def test_browser_navigation_previews_nested_contents_and_npc_return(
    inventory, tmp_path, monkeypatch
):
    data = session(inventory)
    answers = iter(["300", "V", "G", "P", "N", "B", "Q"])
    monkeypatch.setattr(
        browser, "_container_menu", lambda *args, **kwargs: next(answers)
    )
    previews = []
    monkeypatch.setattr(
        browser, "open_preview", lambda path: previews.append(Image.open(path).size)
    )
    calls = []
    monkeypatch.setattr(
        browser,
        "browse_u8_npc_session",
        lambda session, **kwargs: calls.append(kwargs["npc"]),
    )
    browser.browse_u8_container_session(data, output=tmp_path / "exports")
    assert previews == [(3, 1), (4, 1)]
    assert calls == [1]


def test_redirected_menus_and_cancellation(inventory, tmp_path):
    static, gamedat = inventory
    result = CliRunner().invoke(
        u8_app,
        [
            "container-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "-o",
            str(tmp_path / "exports"),
        ],
        input="1\n300\nB\nQ\n",
    )
    assert result.exit_code == 0, result.stdout
    assert "Inventory / item" in result.stdout
    result = CliRunner().invoke(
        u8_app, ["container-browse", str(gamedat), "--data-only"], input=""
    )
    assert result.exit_code == 0


def composition_session(inventory):
    static, _ = inventory
    # Twelve native pixels in a synthetic one-row gump; four are storable.
    data = session(inventory)
    data.gumps.records[2] = shape_bytes([(bytes(range(10, 22)), 0, 0)])
    (static / "GUMPAGE.DAT").write_bytes(struct.pack("<8h", 0, 0, 0, 0, 2, 0, 6, 1))
    data = build_u8_container_session(data.snapshot, data.library, gumps=data.gumps)
    data.library.properties[5] = replace(
        data.library.properties[5], flags=data.library.properties[5].flags | 0x1000
    )
    return data


def test_composition_captures_owner_area_and_only_direct_children(inventory):
    data = composition_session(inventory)
    before = json.dumps(data.items, sort_keys=True)
    path = data.gumpage_path
    path.write_bytes(b"changed after capture")
    result = u8_container_gump_composition(
        data, 300, U8ContainerGumpPreview(**data.items[300]["gump_previews"][0])
    )
    assert result.pixel_area == (2, 0, 6, 1)
    assert [item.item_id for item in result.placements] == [306, 301]
    assert result.placements[0].editor
    assert json.dumps(data.items, sort_keys=True) == before
    assert path in data.sources
    # Grandchildren of the Avatar must never spill out of their bag into its gump.
    result = u8_container_gump_composition(
        data, 1, U8ContainerGumpPreview(None, 2, 0, "test")
    )
    assert [item.item_id for item in result.placements] == [300, 302]


def test_saved_composition_applies_horizontal_flip_draw_origin(inventory):
    data = composition_session(inventory)
    data.gump_layout = "saved"
    data.items[302]["gump_x"] = 2
    result = u8_container_gump_composition(
        data, 1, U8ContainerGumpPreview(None, 2, 0, "test")
    )
    flipped = next(item for item in result.placements if item.item_id == 302)
    assert flipped.anchor_x == flipped.left + 2 - 2
    native = u8_container_item_image(data, 302)
    assert result.image.getpixel((flipped.left, flipped.top)) == native.getpixel((0, 0))


def test_missing_invalid_area_and_bad_sprite_fallbacks(inventory, tmp_path):
    data = session(inventory)
    preview = U8ContainerGumpPreview(**data.items[300]["gump_previews"][0])
    result = u8_container_gump_composition(data, 300, preview)
    assert result.image.tobytes() == data.gumps.image(2, 0).tobytes()
    assert result.area is None and not result.placements and result.diagnostics
    data = composition_session(inventory)
    data.items[306]["frame"] = 123
    result = u8_container_gump_composition(data, 300, preview)
    assert [item.item_id for item in result.placements] == [301]
    assert "cache ID 306: inventory sprite unavailable" in result.diagnostics[-1]
    data.gumpage = U8GumpAreas.from_bytes(bytes(16))
    result = u8_container_gump_composition(data, 300, preview)
    assert result.area is None and not result.placements
    bad = tmp_path / "bad.dat"
    bad.write_bytes(b"short")
    with pytest.raises(ValueError, match="8-byte rectangles"):
        build_u8_container_session(
            data.snapshot, data.library, gumps=data.gumps, gumpage=bad
        )
    data.gumpage_path.write_bytes(b"short")
    implicit = build_u8_container_session(data.snapshot, data.library, gumps=data.gumps)
    assert implicit.gumpage is None
    assert any(
        "Gump storage bounds unavailable" in issue for issue in implicit.diagnostics
    )


def test_composition_reports_include_placement_evidence(inventory, tmp_path):
    data = composition_session(inventory)
    index = export_u8_container_bundle(data, tmp_path / "composed", container=300)
    report = json.loads((index.parent / "inventory.json").read_text())
    entry = report["gump_compositions"][0]
    assert entry["area"]["shape"] == 2
    assert [item["item_id"] for item in entry["placements"]] == [306, 301]
    assert (index.parent / entry["image"]).is_file()
    assert (index.parent / entry["artwork"]).is_file()
    page = (index.parent / "containers/0300.html").read_text()
    assert "2/2 direct items placed" in page and "Storage area:" in page
    with (index.parent / "gump_placements.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert [row["item_id"] for row in csv.DictReader(stream)] == ["306", "301"]


def test_g_opens_composition_rerolls_and_h_retains_empty_artwork(
    inventory, tmp_path, monkeypatch
):
    data = composition_session(inventory)
    # Give both native-size item sprites room for independent random layouts.
    data.gumpage = U8GumpAreas.from_bytes(struct.pack("<8h", 0, 0, 0, 0, 0, 0, 12, 1))
    answers = iter(["G", "G", "H", "L", "S", "G", "B", "Q"])
    monkeypatch.setattr(
        browser, "_container_menu", lambda *args, **kwargs: next(answers)
    )
    previews = []
    monkeypatch.setattr(
        browser,
        "open_preview",
        lambda path: previews.append(Image.open(path).tobytes()),
    )
    browser.browse_u8_container_session(
        data, container=300, output=tmp_path / "exports"
    )
    assert previews[0] != previews[1]
    assert previews[2] == data.gumps.image(2, 0).tobytes()
    assert data.gump_layout == "saved"


def test_composition_cli_options_and_invalid_layout(inventory, tmp_path):
    result = CliRunner().invoke(u8_app, ["container-browse", "--help"])
    assert all(
        option in result.stdout for option in ("--gumpage", "--layout", "--seed")
    )
    static, gamedat = inventory
    result = CliRunner().invoke(
        u8_app,
        [
            "container-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--export",
            "--layout",
            "guess",
            "-o",
            str(tmp_path / "exports"),
        ],
    )
    assert result.exit_code == 1 and "random or saved" in result.stdout
    assert not (tmp_path / "exports").exists()
