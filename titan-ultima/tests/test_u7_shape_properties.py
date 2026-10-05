"""Properties, sparse combat metadata, owner isolation and browser navigation."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from titan import _wizard_ui as ui
from titan.u7 import shape_browser as browser
from titan.u7 import shape_properties as props
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape


def flex(path, records):
    archive = U7FlexArchive()
    archive.records = list(records)
    path.write_bytes(archive.to_bytes())


def sprite(frames=1):
    shape = U7Shape()
    for _ in range(frames):
        frame = U7Shape.Frame()
        frame.width, frame.height = 2, 3
        frame.pixels = np.full((3, 2), 5, dtype=np.uint8)
        shape.frames.append(frame)
    return shape.to_bytes()


def combat(number, size, value=4, deleted=False):
    raw = bytearray(size)
    struct.pack_into("<H", raw, 0, number)
    raw[2] = value
    raw[-1] = 255 if deleted else 0
    return bytes(raw)


@pytest.fixture
def library(tmp_path, monkeypatch):
    static, patch = tmp_path / "game" / "static", tmp_path / "game" / "patch"
    static.mkdir(parents=True)
    patch.mkdir()
    target = ArchiveTarget("Test SI", static, patch, root=static.parent)
    flex(
        static / "SHAPES.VGA", [bytes(64), *([b""] * 149), sprite(), sprite(), sprite()]
    )
    flex(static / "PALETTES.FLX", [bytes([10] * 768)])
    tfa = bytearray(153 * 3)
    tfa[450:453] = bytes([0x88, 0x26, 17])
    tfa[453:456] = bytes([0x10, 3, 0])
    tfa[456:459] = bytes([0, 2, 0])
    (static / "TFA.DAT").write_bytes(tfa)
    (static / "SHPDIMS.DAT").write_bytes(bytes([5, 7, 0, 0, 0, 0]))
    wgtvol = bytearray(153 * 2)
    wgtvol[300:302] = bytes([7, 8])
    (static / "WGTVOL.DAT").write_bytes(wgtvol)
    for name, size in [("WEAPONS.DAT", 21), ("AMMO.DAT", 13), ("ARMOR.DAT", 10)]:
        (static / name).write_bytes(b"\x02" + combat(150, size) + combat(151, size))
        (patch / name).write_bytes(
            b"\x02" + combat(150, size, deleted=True) + combat(152, size, value=9)
        )
    (static / "READY.DAT").write_bytes(
        b"\x02" + combat(150, 9, value=1 << 3) + combat(151, 9, value=1 << 3)
    )
    (patch / "READY.DAT").write_bytes(b"\x01" + combat(151, 9, value=(22 << 3) | 1))
    (static / "CONTAINER.DAT").write_bytes(
        b"\x02\x01" + struct.pack("<HHh", 150, 10, 1)
    )
    (patch / "CONTAINER.DAT").write_bytes(b"\x02\x01" + struct.pack("<HHh", 151, 20, 2))
    (static / "shape_info.txt").write_text(
        "%%section field_type\n:150/0\n%%endsection\n%%section mountain_tops\n:151/1\n%%endsection\n"
    )
    (patch / "shape_info.txt").write_text(
        "%%section field_type\n:150/-1\n%%endsection\n%%section barge_type\n:150/3\n%%endsection\n"
    )
    monkeypatch.setattr("titan.u7.cli._resolve_u7_exult_flx", lambda game: None)
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    return browser.load_library(target, "si", static / "SHAPES.VGA")


def actions(monkeypatch, values):
    answers = iter(values)
    monkeypatch.setattr(ui, "choice", lambda *a, **k: next(answers))


def report(library, number=150):
    return props.property_report(library, library.shape(number), number, 0)


def test_physics_auxiliary_units_and_sources(library):
    result = report(library)
    assert result["physics"]["class"] == "container"
    assert result["physics"]["tile_dimensions"] == [2, 3, 4]
    assert "solid" in result["physics"]["flags"]
    assert result["weight_volume"] == {
        "weight": 7,
        "volume": 8,
        "units": "stored game units",
    }
    assert result["obstacle_dimensions"] == {
        "x": 3,
        "y": 2,
        "x_obstacle": True,
        "y_obstacle": True,
    }
    assert Path(result["metadata_sources"]["TFA.DAT"]).parent == library.target.static
    assert result["pixel_size"] == [2, 3]
    assert result["index_255"] == "transparent"
    assert report(library, 0)["index_255"] == "opaque"


def test_sparse_combat_override_and_deletion(library):
    catalog = props.properties_for(library)
    for kind in ["weapon", "ammo", "armor"]:
        assert set(catalog.tables[kind]) == {151, 152}
        assert "static" in catalog.tables[kind][151]["source"]
        assert "patch" in catalog.tables[kind][152]["source"]
    assert "weapon" not in report(library)
    assert "weapon" in report(library, 151)
    assert "armor" in report(library, 152)


def test_ready_sparse_slots_spell_flag_and_container_sources(library):
    catalog = props.properties_for(library)
    assert catalog.tables["ready"][150]["slot_name"] == "left_hand"
    assert catalog.tables["ready"][151]["slot_name"] == "neck"
    assert catalog.tables["ready"][151]["spell_flag"] is True
    assert catalog.tables["container"][150]["gump_shape"] == 10
    assert "static" in catalog.tables["container"][150]["source"]
    assert catalog.tables["container"][151]["gump_font"] == 2
    assert "patch" in catalog.tables["container"][151]["source"]


def test_extra_patch_overrides_one_field_and_keeps_other_sections(library):
    first, second = report(library), report(library, 151)
    assert first["exult_extra"]["field_type"]["value"] == -1
    assert first["exult_extra"]["field_type"]["name"] == "none"
    assert first["exult_extra"]["barge_type"]["value"] == 3
    assert second["exult_extra"]["mountain_tops"]["value"] == 1


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("all", [0, 150, 151, 152]),
        ("class:6", [150]),
        ("flag:solid", [150]),
        ("flag:water", [151]),
        ("flag:x_obstacle", [150]),
        ("weapon", [151, 152]),
        ("ready", [150, 151]),
        ("container", [150, 151]),
    ],
)
def test_property_filters(library, mode, expected):
    assert props.filtered_ids(library, mode) == expected


def test_search_obeys_active_filter_and_can_clear_it(library, monkeypatch):
    library.property_filter = "class:6"
    assert browser.matching_shapes(library, "") == [150]
    assert browser.matching_shapes(library, "151") == []
    actions(monkeypatch, ["A"])
    props.choose_filter(library)
    assert browser.matching_shapes(library, "151") == [151]


def test_selector_can_change_empty_filter(library, monkeypatch):
    library.property_filter = "class:12"
    actions(monkeypatch, ["O", "A", "S150"])
    assert browser.choose_shape(library) == 150


def test_generic_and_unowned_libraries_do_not_receive_world_properties(
    library, tmp_path
):
    for path in [library.target.static / "GUMPS.VGA", tmp_path / "SHAPES.VGA"]:
        flex(path, [bytes(64) if path.name == "SHAPES.VGA" else sprite()])
        custom = browser.load_library(library.target, "si", path)
        result = report(custom, 0)
        assert result["physics"] == "Unknown / unavailable"
        assert "weapon" not in result
        assert "frame properties only" in result["warnings"][0]


def test_truncated_patch_is_reported_without_base_combat_fallback(library):
    (library.target.patch / "WEAPONS.DAT").write_bytes(b"\x01short")
    catalog = props.properties_for(library)
    assert catalog.tables["weapon"] == {}
    assert any("Incomplete weapon" in message for message in catalog.warnings)
    assert catalog.tables["armor"]


def test_missing_tfa_is_unknown_and_auxiliary_values_still_available(library):
    (library.target.static / "TFA.DAT").unlink()
    loaded = browser.load_library(library.target, "si", library.path)
    result = report(loaded)
    assert result["physics"] == "Unknown / unavailable"
    assert result["weight_volume"]["weight"] == 7
    assert props.filtered_ids(loaded, "unknown") == loaded.ids


def test_broken_container_patch_does_not_show_base_mapping(library):
    (library.target.patch / "CONTAINER.DAT").write_bytes(b"\x02\x01short")
    catalog = props.properties_for(library)
    assert catalog.tables["container"] == {}
    assert any("Incomplete container" in message for message in catalog.warnings)
    assert catalog.extra["field_type"][150] == -1


@pytest.mark.parametrize("tfa_layer", ["static", "patch"])
def test_extended_tfa_auxiliary_metadata_and_frame_reflection(library, tfa_layer):
    patch = library.target.patch
    flex(patch / "SHAPES.VGA", [*([b""] * 1025), sprite(34)])
    tfa = bytearray(1026 * 3)
    tfa[1025 * 3 : 1026 * 3] = bytes([8, 6, 17])
    (getattr(library.target, tfa_layer) / "TFA.DAT").write_bytes(tfa)
    dims = bytearray((1026 - 150) * 2)
    dims[-2:] = bytes([5, 7])
    (patch / "SHPDIMS.DAT").write_bytes(dims)
    wgtvol = bytearray(1026 * 2)
    wgtvol[-2:] = bytes([9, 11])
    (patch / "WGTVOL.DAT").write_bytes(wgtvol)
    occlude = bytearray(129)
    occlude[128] = 2
    (patch / "OCCLUDE.DAT").write_bytes(occlude)
    loaded = browser.load_library(library.target, "si", patch / "SHAPES.VGA")
    result = report(loaded, 1025)
    assert result["physics"]["class"] == "container"
    assert result["physics"]["frame_bit5_reflection"] is False
    assert "occludes" in result["physics"]["flags"]
    assert "x_obstacle" in result["physics"]["flags"]
    assert result["weight_volume"]["weight"] == 9
    assert result["obstacle_dimensions"]["x"] == 3
    assert 1025 in props.filtered_ids(loaded, "flag:occludes")


def test_report_paging_and_export_are_read_only(library, tmp_path, monkeypatch, capsys):
    before = {
        path: path.read_bytes()
        for root in [library.target.static, library.target.patch]
        for path in root.iterdir()
    }
    output = tmp_path / "report.json"
    actions(monkeypatch, ["N", "B", "E", "Q"])
    monkeypatch.setattr(ui, "path", lambda *a, **k: str(output))
    props.show_properties(library, library.shape(150), 150, 0)
    assert "page 2/" in capsys.readouterr().out
    assert json.loads(output.read_text())["shape"] == 150
    assert all(path.read_bytes() == data for path, data in before.items())
    with pytest.raises(FileExistsError):
        props.export_report(library, report(library))
    monkeypatch.setattr(
        ui, "path", lambda *a, **k: str(library.target.patch / "report.json")
    )
    with pytest.raises(ValueError, match="outside"):
        props.export_report(library, report(library))


def test_browser_properties_and_filtered_next_shape(library, monkeypatch, capsys):
    monkeypatch.setattr(browser, "game_targets", lambda game: (library.target, []))
    monkeypatch.setattr(browser, "select_target", lambda *a: library.target)
    monkeypatch.setattr(browser, "terminal_image", lambda *a, **k: False)
    actions(monkeypatch, ["2", "T", "Q", "O", "W", "S151", "J", "Q"])
    assert browser.run_browser(game="si", archive=str(library.path), shape=150) == 0
    output = capsys.readouterr().out
    assert "Shape 150 properties" in output
    assert "Shape 151" in output and "Shape 152" in output
