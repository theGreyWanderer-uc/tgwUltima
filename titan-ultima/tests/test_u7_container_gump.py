"""Native U7 gump mapping, saved draw anchors, direct contents and browser exports."""

import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.u7 import container_browser as browser
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.container_gump import (
    U7GumpArea,
    U7GumpItemSprite,
    compose_u7_container_gump,
    load_u7_container_gumps,
)
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape
from titan.u7.cli import u7_app
from tests import test_u7_container_browser as native_ireg_fixtures

world = native_ireg_fixtures.world


def table(*rows):
    return bytes([2, len(rows)]) + b"".join(
        struct.pack("<HHh", shape, gump & 65535, -1) for shape, gump in rows
    )


def flex(path, records):
    archive = U7FlexArchive()
    archive.records = records
    path.write_bytes(archive.to_bytes())


def shape_record(width, height, colour, anchor=(0, 0)):
    shape = U7Shape()
    frame = U7Shape.Frame()
    frame.width, frame.height = width, height
    frame.set_hotspot_from_top_left(*anchor)
    frame.pixels = np.full((height, width), colour, dtype=np.uint8)
    shape.frames = [frame]
    return shape.to_bytes()


@pytest.fixture
def native_session(world):
    static = Path(world.static_dir)
    (static / "CONTAINER.DAT").write_bytes(table((522, 22), (801, 9)))
    gumps = [b""] * 23
    gumps[9] = shape_record(140, 90, 20)
    gumps[22] = shape_record(130, 85, 20, (3, 4))
    flex(static / "GUMPS.VGA", gumps)
    shapes = [b""] * 802
    shapes[100] = bytes([30]) * 64
    shapes[522] = shape_record(5, 3, 10, (2, 1))
    shapes[801] = shape_record(7, 4, 30, (3, 2))
    flex(static / "SHAPES.VGA", shapes)
    flex(static / "PALETTES.FLX", [bytes([i // 3 % 64 for i in range(768)])])
    return browser.load_u7_container_session(world)


@pytest.mark.parametrize("game,chest,drawer", [("bg", 22, 27), ("si", 18, 22)])
def test_bg_si_bounds_are_keyed_by_gump_not_world_shape(tmp_path, game, chest, drawer):
    (tmp_path / "CONTAINER.DAT").write_bytes(table((522, chest), (777, drawer)))
    catalog = load_u7_container_gumps(ArchiveTarget("Game", tmp_path, tmp_path), game)
    assert catalog.resolve(522)[1] == U7GumpArea(40, 18, 60, 37)
    assert catalog.resolve(777)[1] == U7GumpArea(36, 12, 70, 26)


def test_sparse_patch_mapping_disable_and_custom_area_preserve_base(tmp_path):
    static, patch = tmp_path / "STATIC", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    (static / "CONTAINER.DAT").write_bytes(table((522, 22), (801, 9), (802, 10)))
    (patch / "container.dat").write_bytes(table((522, 100), (802, -1)))
    (patch / "gump_info.txt").write_text(
        "%%section container_area\n:100/-4/5/20/15/0\n%%endsection"
    )
    catalog = load_u7_container_gumps(ArchiveTarget("Mod", static, patch), "bg")
    gump, area, source = catalog.resolve(522)
    assert (gump, area.x, area.y, area.width, area.height) == (100, -4, 5, 20, 15)
    assert source.endswith("container.dat") and area.source.endswith("gump_info.txt")
    assert catalog.resolve(801)[0] == 9
    with pytest.raises(ValueError, match="no artwork mapping"):
        catalog.resolve(802)


def test_exult_bundle_fallback_and_owner_area_overlay(tmp_path):
    bundle = tmp_path / "exult_si.flx"
    records = [b""] * 21
    records[8] = table((522, 18))
    records[20] = b"%%section container_area\n:18/1/2/30/40\n%%endsection"
    flex(bundle, records)
    patch = tmp_path / "patch"
    patch.mkdir()
    (patch / "gump_info.txt").write_text(
        "%%section container_area\n:18/5/6/20/30\n%%endsection"
    )
    catalog = load_u7_container_gumps(
        ArchiveTarget("SI", tmp_path, patch), "si", exult_flx=str(bundle)
    )
    assert catalog.resolve(522)[1].x == 5
    assert bundle in catalog.source_files


def test_locked_chest_counterpart_honours_owner_mapping_and_explicit_disable(tmp_path):
    (tmp_path / "CONTAINER.DAT").write_bytes(table((800, 22)))
    (tmp_path / "SHAPE_INFO.TXT").write_text(
        "%%section locked_containers\n:522/1\n%%endsection"
    )
    catalog = load_u7_container_gumps(ArchiveTarget("BG", tmp_path, tmp_path), "bg")
    assert catalog.resolve(522)[0] == 22
    assert catalog.resolve(522)[2].startswith("Preview locked chest")
    (tmp_path / "CONTAINER.DAT").write_bytes(table((800, 22), (522, -1)))
    catalog = load_u7_container_gumps(ArchiveTarget("BG", tmp_path, tmp_path), "bg")
    with pytest.raises(ValueError, match="no artwork mapping"):
        catalog.resolve(522)
    (tmp_path / "CONTAINER.DAT").write_bytes(table((800, 22)))
    (tmp_path / "SHAPE_INFO.TXT").write_text(
        "%%section locked_containers\n:522/0\n%%endsection"
    )
    catalog = load_u7_container_gumps(ArchiveTarget("BG", tmp_path, tmp_path), "bg")
    with pytest.raises(ValueError, match="no artwork mapping"):
        catalog.resolve(522)


def test_old_si_bundle_uses_exult_locked_defaults_but_patch_can_clear_them(tmp_path):
    (tmp_path / "CONTAINER.DAT").write_bytes(table((800, 18)))
    target = ArchiveTarget("SI", tmp_path, tmp_path)
    assert load_u7_container_gumps(target, "si").resolve(522)[0] == 18
    (tmp_path / "SHAPE_INFO.TXT").write_text(
        "%%section locked_containers\n:522/0\n%%endsection"
    )
    with pytest.raises(ValueError, match="no artwork mapping"):
        load_u7_container_gumps(target, "si").resolve(522)


def test_si_bundled_negative_locked_mapping_can_preview_but_patch_disable_wins(
    tmp_path,
):
    records = [b""] * 9
    records[8] = table((800, 18), (522, -1))
    bundle = tmp_path / "exult_si.flx"
    flex(bundle, records)
    patch = tmp_path / "patch"
    patch.mkdir()
    target = ArchiveTarget("SI", tmp_path, patch)
    assert (
        load_u7_container_gumps(target, "si", exult_flx=str(bundle)).resolve(522)[0]
        == 18
    )
    (patch / "container.dat").write_bytes(table((522, -1)))
    with pytest.raises(ValueError, match="no artwork mapping"):
        load_u7_container_gumps(target, "si", exult_flx=str(bundle)).resolve(522)


@pytest.mark.parametrize(
    "text",
    [
        "%%section container_area\n:9/0/0\n%%endsection",
        "%%section special\n:invalid\n%%endsection",
    ],
)
def test_malformed_mod_area_does_not_silently_use_defaults(tmp_path, text):
    (tmp_path / "gump_info.txt").write_text(text)
    with pytest.raises(ValueError, match="malformed"):
        load_u7_container_gumps(ArchiveTarget("Mod", tmp_path, tmp_path), "bg")


def test_special_and_nonpositive_area_are_rejected(tmp_path):
    (tmp_path / "CONTAINER.DAT").write_bytes(table((522, 22), (801, 9)))
    (tmp_path / "gump_info.txt").write_text(
        "%%section container_area\n:9/0/0/0/1\n%%endsection\n%%section special\n:22\n%%endsection"
    )
    catalog = load_u7_container_gumps(ArchiveTarget("Mod", tmp_path, tmp_path), "bg")
    with pytest.raises(ValueError, match="not a container"):
        catalog.resolve(522)
    with pytest.raises(ValueError, match="invalid storage"):
        catalog.resolve(801)


def test_saved_positions_use_item_and_gump_draw_anchors_without_mutation():
    artwork = Image.new("RGBA", (20, 20), "blue")
    sprite = Image.new("RGBA", (3, 2), "red")
    sprite.putpixel((0, 0), (0, 0, 0, 0))
    child = U7GumpItemSprite("child", sprite, 1, 1, 4, 5)
    result = compose_u7_container_gump(
        artwork, U7GumpArea(2, 3, 10, 10), [child], gump_origin=(3, 2), layout="saved"
    )
    assert result.pixel_area == (5, 5, 15, 15)
    assert (result.placements[0]["left"], result.placements[0]["top"]) == (8, 9)
    assert result.placements[0]["position_source"] == "saved"
    assert result.image.getpixel((8, 9)) == (0, 0, 255, 255)
    assert result.image.getpixel((9, 9)) == (255, 0, 0, 255)
    assert artwork.getpixel((9, 9)) == (0, 0, 255, 255)
    assert child.saved_x == 4


def test_unopened_and_invalid_saved_positions_are_arranged_at_native_size():
    sprites = [
        U7GumpItemSprite(str(i), Image.new("RGBA", (3, 2), "red"), 1, 1, 255, 255)
        for i in range(2)
    ]
    result = compose_u7_container_gump(
        Image.new("RGBA", (20, 20)), U7GumpArea(1, 2, 10, 10), sprites, layout="saved"
    )
    assert [p["position_source"] for p in result.placements] == ["auto", "auto"]
    assert [(p["left"], p["top"]) for p in result.placements] == [(2, 3), (4, 3)]
    assert result.image.size == (20, 20)


def test_random_layout_rerolls_and_large_sprite_is_diagnosed():
    sprites = [U7GumpItemSprite("large", Image.new("RGBA", (30, 3), "red"), 0, 0, 0, 0)]
    artwork, area = Image.new("RGBA", (25, 25)), U7GumpArea(2, 3, 10, 10)
    first = compose_u7_container_gump(artwork, area, sprites, seed=3)
    again = compose_u7_container_gump(artwork, area, sprites, seed=3)
    other = compose_u7_container_gump(artwork, area, sprites, seed=8)
    assert first.placements == again.placements
    assert first.placements != other.placements
    assert first.placements[0]["clipped"] and first.placements[0]["width"] == 10
    assert first.diagnostics


def test_native_session_composes_only_direct_items_and_nested_bag_separately(
    native_session,
):
    root, bag, empty = native_session.containers
    _, composed, _ = browser.u7_container_gump_preview(native_session, root)
    assert {p["item_id"] for p in composed.placements} == {bag, empty}
    assert composed.pixel_area == (43, 22, 103, 59)
    _, inner, _ = browser.u7_container_gump_preview(native_session, bag)
    assert len(inner.placements) == 1
    _, empty_art, _ = browser.u7_container_gump_preview(native_session, empty)
    assert not empty_art.placements and empty_art.image.size == (140, 90)
    _, artwork, _ = browser.u7_container_gump_preview(
        native_session, root, contents=False
    )
    assert not artwork.placements


def test_reflected_item_swaps_pixels_and_draw_anchor(native_session):
    root = native_session.containers[0]
    normal = browser.u7_container_item_sprite(native_session, root, frame=0)
    reflected = browser.u7_container_item_sprite(native_session, root, frame=32)
    assert normal.image.size == (5, 3)
    assert reflected.image.size == (3, 5)
    assert (reflected.xleft, reflected.yabove) == (normal.yabove, normal.xleft)


def test_real_frame_32_is_not_reflected_for_shapes_with_over_32_frames(native_session):
    root = native_session.containers[0]
    shape = U7Shape.from_data(shape_record(5, 3, 10, (2, 1)))
    shape.frames *= 33
    path = Path(native_session.world.static_dir) / "SHAPES.VGA"
    archive = U7FlexArchive.from_file(str(path))
    archive.records[522] = shape.to_bytes()
    path.write_bytes(archive.to_bytes())
    sprite = browser.u7_container_item_sprite(native_session, root, frame=32)
    assert sprite.image.size == (5, 3)
    assert (sprite.xleft, sprite.yabove) == (2, 1)


def test_container_command_help_retains_game_owner_and_exult_options():
    result = CliRunner().invoke(u7_app, ["container-browse", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--gamedat",
        "--game",
        "--exult-flx",
        "--mod-data",
        "--map",
        "--format",
    ):
        assert flag in result.stdout


def test_patch_gump_archive_inherits_empty_records_and_palette(
    native_session, tmp_path
):
    patch = tmp_path / "patch"
    patch.mkdir()
    records = [b""] * 23
    records[22] = shape_record(110, 80, 40)
    flex(patch / "gumps.vga", records)
    native_session.target = ArchiveTarget("Patch", native_session.target.static, patch)
    root, bag, _ = native_session.containers
    _, chest, _ = browser.u7_container_gump_preview(native_session, root)
    _, sack, _ = browser.u7_container_gump_preview(native_session, bag)
    assert chest.image.size == (110, 80)
    assert sack.image.size == (140, 90)


def test_browser_g_h_l_and_fresh_reports_keep_game_inputs_and_old_reports(
    native_session, tmp_path, monkeypatch
):
    before = {
        p: hashlib.sha256(p.read_bytes()).digest() for p in native_session.source_files
    }
    output = tmp_path / "output"
    output.mkdir()
    old = output / "old.html"
    old.write_text("preserve")
    root = native_session.containers[0]
    answers = iter(["I", "G", "G", "H", "L", "S", "G", "E", "B", "Q"])
    monkeypatch.setattr(
        "titan._inventory_browser.ui.choice", lambda *a, **k: next(answers)
    )
    monkeypatch.setattr("titan._inventory_browser.ui.text", lambda *a, **k: str(root))
    opened = []
    monkeypatch.setattr(
        browser, "open_preview", lambda path: opened.append(path) or True
    )
    browser.browse_u7_container_session(native_session, output=output)
    assert len(opened) == 4 and len(set(opened)) == 4
    assert native_session.layout == "saved"
    report = next(output.glob("*/inventory.json"))
    data = json.loads(report.read_text(encoding="utf-8"))
    detail = data["gump_previews"][root]
    assert detail["gump_shape"] == 22 and detail["rendered_count"] == 2
    assert detail["layout"] == "saved"
    assert (report.parent / detail["image"]).is_file()
    html = next((report.parent / "containers").glob("*.html")).read_text(
        encoding="utf-8"
    )
    assert "Container gump with direct contents" in html
    assert old.read_text() == "preserve"
    assert all(
        hashlib.sha256(p.read_bytes()).digest() == digest
        for p, digest in before.items()
    )
