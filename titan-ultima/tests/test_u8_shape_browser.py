"""U8 browser owner isolation, wire fixtures, sprite anchors and interactive flows."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from PIL import Image
from PIL.GifImagePlugin import GifImageFile
from typer.testing import CliRunner

from titan import _config, _wizard_ui as ui
from titan.u8 import shape_browser as browser
from titan.u8 import shape_browser_ui as menus
from titan.u8.cli import u8_app
from tests.test_u8_save_state import native_flex


def shape_bytes(frames: list[tuple[bytes, int, int]] | None = None) -> bytes:
    """Encode one-row literal frames independently of Titan's sprite writer."""
    frames = frames or [(bytes((5, 6, 255)), 0, 0), (bytes((7, 8)), 0, 1)]
    raw = bytearray(6 + 6 * len(frames))
    struct.pack_into("<3H", raw, 0, 11, 22, len(frames))
    for index, (pixels, xoff, yoff) in enumerate(frames):
        payload = struct.pack(
            "<4HH4hH", 99, index, 0x1234, 0x5678, 0, len(pixels), 1, xoff, yoff, 2
        )
        payload += bytes((0, len(pixels))) + pixels
        cell = 6 + 6 * index
        raw[cell : cell + 3] = len(raw).to_bytes(3, "little")
        raw[cell + 3] = index + 1
        struct.pack_into("<H", raw, cell + 4, len(payload))
        raw += payload
    return bytes(raw)


def anim_bytes(*, missing: bool = False, frame_count: int = 2) -> bytes:
    raw = bytearray(8192 + 256)
    struct.pack_into("<I", raw, 4, 8192)
    for action in (0, 7):
        struct.pack_into("<I", raw, 8192 + action * 4, len(raw))
        raw += bytes((frame_count, 4, 3, 0))
        for direction in range(8):
            for step in range(frame_count):
                if step % 2:
                    raw += struct.pack("<HbBH", 1, 3, 0, 0x2000 | (0x1FF & -4))
                else:
                    raw += struct.pack(
                        "<HbBH", 99 if missing else 0, -2, 12, 0x4000 | 3
                    )
    return bytes(raw)


def overlay_bytes() -> bytes:
    payload = b"".join(struct.pack("<bbH", -3, 2, 0) for _ in range(8 * 2))
    records = [b""] * 8
    records[0] = records[7] = payload
    return native_flex(records)


@pytest.fixture
def owner(tmp_path: Path, monkeypatch):
    root = tmp_path / "English" / "STATIC"
    root.mkdir(parents=True)
    records = [b""] * 242
    records[1] = shape_bytes()
    records[3] = shape_bytes([(bytes((9,)), 0, 0)])
    records[241] = shape_bytes([(bytes((10,)), 2, 3)])
    (root / "u8shapes.flx").write_bytes(native_flex(records))
    (root / "U8GUMPS.FLX").write_bytes(native_flex([shape_bytes()]))
    (root / "U8FONTS.FLX").write_bytes(native_flex([shape_bytes()]))
    palette = bytearray(772)
    for index in range(256):
        palette[4 + index * 3 : 7 + index * 3] = bytes(
            (index % 64, (index * 2) % 64, (index * 3) % 64)
        )
    (root / "u8pal.pal").write_bytes(palette)
    props = bytearray(8 * 242)
    props[8:16] = bytes((3, 0x60, 0x61, 0x24, 0, 0, 8, 9))
    props[24:32] = bytes((0, 0x0C, 0, 0, 1, 0, 0, 0))
    (root / "TYPEFLAG.DAT").write_bytes(props)
    (root / "ANIM.DAT").write_bytes(anim_bytes())
    (root / "WPNOVLAY.DAT").write_bytes(overlay_bytes())
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    monkeypatch.setattr(menus, "terminal_image", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        menus,
        "open_preview",
        lambda *args: pytest.fail("redirected browser launched a viewer"),
    )
    monkeypatch.setattr(_config, "_config", {})
    return root


def library(owner: Path, **kwargs):
    return browser.load_u8_shape_library(owner / "u8shapes.flx", **kwargs)


def test_sparse_native_slots_properties_class_search_and_source_ownership(owner: Path):
    lib = library(owner)
    lib.names = {1: "Avatar", 3: "Roof", 241: "Mace"}
    assert lib.ids == [1, 3, 241]
    assert browser.matching_u8_shapes(lib, "0xf1") == [241]
    assert browser.matching_u8_shapes(lib, "AVATAR") == [1]
    assert browser.matching_u8_shapes(lib, "2") == []
    prop = lib.properties[1]
    assert prop.is_container() and prop.footpad_world() == (192, 128, 16)
    assert prop.equip_name() == "shield"
    assert not lib.diagnostics and len(lib.source_paths) == 5
    assert lib.shape(1) is lib.shape(1)


@pytest.mark.parametrize(
    "filter_name,ids",
    [
        ("all", [1, 3, 241]),
        ("animated", [1, 3]),
        ("fixed", [1]),
        ("solid", [1]),
        ("container", [1]),
        ("equipment", [1]),
        ("roof", [3]),
        ("translucent", [3]),
    ],
)
def test_property_filters_intersect_id_search(
    owner: Path, filter_name: str, ids: list[int]
):
    lib = library(owner)
    lib.property_filter = filter_name
    assert browser.matching_u8_shapes(lib) == ids
    assert browser.matching_u8_shapes(lib, "241") == ([241] if 241 in ids else [])


def test_generic_libraries_do_not_borrow_world_metadata_and_explicit_paths_opt_in(
    owner: Path,
):
    gumps = browser.load_u8_shape_library(owner / "U8GUMPS.FLX")
    assert gumps.ids == [0] and not gumps.world_shapes
    assert (
        not gumps.properties
        and gumps.animations is None
        and gumps.overlays is None
        and not gumps.names
    )
    external = owner.parent / "Custom"
    external.mkdir()
    (external / "U8SHAPES.FLX").write_bytes(native_flex([b"", shape_bytes()]))
    with pytest.raises(ValueError, match="no owner"):
        browser.load_u8_shape_library(external / "U8SHAPES.FLX")
    independent = browser.load_u8_shape_library(
        external / "U8SHAPES.FLX", palette=owner / "u8pal.pal"
    )
    assert (
        independent.animations is None
        and not independent.properties
        and independent.overlays is None
    )
    opt_in = browser.load_u8_shape_library(
        external / "U8SHAPES.FLX", palette=owner / "u8pal.pal", anim=owner / "ANIM.DAT"
    )
    assert len(opt_in.actions(1)) == 2


def test_discovery_configuration_case_and_language_variants(owner: Path, monkeypatch):
    installation = owner.parent.parent
    french = installation / "FRENCH" / "static"
    french.mkdir(parents=True)
    assert [
        target.name for target in browser.discover_u8_shape_targets(installation)
    ] == ["English", "French"]
    assert browser.discover_u8_shape_targets(owner.parent)[0].static == owner
    assert browser.discover_u8_shape_targets(owner)[0].static == owner
    monkeypatch.setattr(_config, "_config", {"game": {"base": str(installation)}})
    assert len(browser.discover_u8_shape_targets()) == 2
    monkeypatch.setattr(
        _config, "_config", {"paths": {"u8shapes": str(owner / "u8shapes.flx")}}
    )
    assert browser.discover_u8_shape_targets()[0].static == owner


def test_optional_metadata_failure_keeps_browsing_and_explicit_failure_is_not_hidden(
    owner: Path,
):
    (owner / "ANIM.DAT").write_bytes(b"invalid")
    lib = library(owner)
    assert lib.animations is None and len(lib.diagnostics) == 2
    assert len(lib.shape(1).frames) == 2
    with pytest.raises(ValueError):
        library(owner, anim=owner / "ANIM.DAT")
    (owner / "TYPEFLAG.DAT").write_bytes(b"partial")
    assert not library(owner).properties
    with pytest.raises(ValueError, match="eight-byte"):
        library(owner, typeflag=owner / "TYPEFLAG.DAT")


@pytest.mark.parametrize(
    "case",
    [
        "shape-header",
        "frame-table",
        "frame-offset",
        "frame-size",
        "dimensions",
        "empty-slot",
    ],
)
def test_invalid_shape_records_fail_with_local_errors(owner: Path, case: str):
    lib = library(owner)
    raw = bytearray(lib.records[1])
    if case == "shape-header":
        raw = raw[:5]
    elif case == "frame-table":
        struct.pack_into("<H", raw, 4, 20000)
    elif case == "frame-offset":
        raw[6:9] = b"\xff\xff\xff"
    elif case == "frame-size":
        struct.pack_into("<H", raw, 10, 65535)
    elif case == "dimensions":
        struct.pack_into("<hh", raw, 18 + 10, 32000, 32000)
    else:
        with pytest.raises(ValueError, match="empty"):
            lib.shape(2)
        return
    lib.records[1] = bytes(raw)
    with pytest.raises(ValueError, match="U8 shape browser"):
        lib.shape(1)


def test_actor_flips_keep_anchors_and_preserve_node_details(owner: Path):
    lib = library(owner)
    frames, nodes = browser.aligned_u8_sequence(lib, 1, action=0, direction=7)
    assert [frame.size for frame in frames] == [(4, 2), (4, 2)]
    assert frames[0].getpixel((1, 1)) == (*lib.palette.colors[5], 255)
    transparent = frames[0].getpixel((3, 1))
    assert isinstance(transparent, tuple) and transparent[3] == 0
    assert frames[1].getpixel((0, 0)) == (*lib.palette.colors[8], 255)
    assert frames[1].getpixel((1, 0)) == (*lib.palette.colors[7], 255)
    assert nodes[0]["sfx"] == 12 and nodes[0]["call_usecode"]
    assert nodes[1]["flipped"] and nodes[1]["delta_dir"] == -4
    provider = browser.u8_playback_provider(frames, nodes)
    assert provider(3, 500)[0] is frames[1]


def test_weapon_screen_offsets_include_own_origin_without_actor_mirroring(owner: Path):
    lib = library(owner)
    frames, nodes = browser.aligned_u8_sequence(
        lib, 1, action=7, direction=2, overlay=0
    )
    assert frames[0].size == (8, 2)
    assert frames[0].getpixel((0, 0)) == (*lib.palette.colors[10], 255)
    assert frames[1].getpixel((0, 0)) == (*lib.palette.colors[10], 255)
    assert nodes[0]["overlay"] == {
        "type": 0,
        "name": "mace",
        "shape": 241,
        "frame": 0,
        "x_offset": -3,
        "y_offset": 2,
    }
    assert frames[1].getpixel((4, 0)) == (*lib.palette.colors[8], 255)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": 63},
        {"action": 0, "direction": 8},
        {"overlay": 0},
        {"action": 7, "overlay": 14},
    ],
)
def test_sequence_errors_are_explicit(owner: Path, kwargs):
    with pytest.raises(ValueError):
        browser.aligned_u8_sequence(library(owner), 1, **kwargs)


def test_missing_node_sprite_frame_is_not_silently_replaced(owner: Path):
    (owner / "ANIM.DAT").write_bytes(anim_bytes(missing=True))
    with pytest.raises(ValueError, match="missing frame 99"):
        browser.aligned_u8_sequence(library(owner), 1, action=0)


def test_png_gif_json_exports_preserve_indices_transparency_origins_and_sources(
    owner: Path, tmp_path: Path
):
    sources = {path: path.read_bytes() for path in owner.iterdir() if path.is_file()}
    lib = library(owner)
    paths = browser.export_u8_browser_pngs(lib, 1, tmp_path / "frames")
    assert [path.name for path in paths] == [
        "shape_0001_f0000.png",
        "shape_0001_f0001.png",
    ]
    with Image.open(paths[0]) as image:
        assert image.mode == "P" and [image.getpixel((x, 0)) for x in range(3)] == [
            5,
            6,
            255,
        ]
        assert image.info["transparency"] == 255
        transparent = image.convert("RGBA").getpixel((2, 0))
        assert isinstance(transparent, tuple) and transparent[3] == 0
    gif = browser.export_u8_browser_gif(
        lib, 1, tmp_path / "walk.gif", action=0, duration_ms=120
    )
    with Image.open(gif) as image:
        assert isinstance(image, GifImageFile)
        assert (
            image.n_frames == 2
            and image.size == (4, 2)
            and image.info["duration"] == 120
        )
        assert image.convert("RGBA").getpixel((1, 1)) == (*lib.palette.colors[5], 255)
        image.seek(1)
        assert image.convert("RGBA").getpixel((0, 0)) == (*lib.palette.colors[8], 255)
    report = browser.export_u8_browser_report(lib, 1, tmp_path / "shape.json")
    data = json.loads(report.read_text())
    assert data["frame_count"] == 2 and data["header0"] == 11
    assert data["frames"][1]["yoff"] == 1 and data["frames"][1]["table_unknown"] == 2
    assert data["properties"]["family_name"] == "container"
    assert len(data["animations"]) == 2 and len(data["animations"][0]["frames"]) == 16
    assert all(path.read_bytes() == raw for path, raw in sources.items())
    original = report.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        browser.export_u8_browser_report(lib, 1, report)
    assert report.read_bytes() == original
    with pytest.raises(ValueError, match="already exists"):
        browser.export_u8_browser_pngs(lib, 1, tmp_path / "frames")


def test_export_preflight_preserves_sources_and_does_not_partially_write_batch(
    owner: Path, tmp_path: Path
):
    lib = library(owner)
    target = tmp_path / "frames"
    target.mkdir()
    (target / "shape_0001_f0001.png").write_bytes(b"keep")
    with pytest.raises(ValueError):
        browser.export_u8_browser_pngs(lib, 1, target)
    assert not (target / "shape_0001_f0000.png").exists()
    assert (target / "shape_0001_f0001.png").read_bytes() == b"keep"
    # A caller-supplied report filename must never replace a loaded source.
    source = tmp_path / "palette.json"
    source.write_bytes((owner / "u8pal.pal").read_bytes())
    protected = library(owner, palette=source)
    with pytest.raises(ValueError):
        browser.export_u8_browser_report(protected, 1, source)


def test_frame_sheets_have_bounded_size_and_preserve_colour(owner: Path):
    lib = library(owner)
    frames, _ = browser.aligned_u8_sequence(lib, 1, action=0)
    sheet = browser.u8_frame_sheet(frames * 9)
    assert sheet.size == (880, 600)
    with pytest.raises(ValueError):
        browser.u8_frame_sheet([])


def test_contact_sheet_sets_keep_action_direction_and_overlay_names(owner: Path):
    lib = library(owner)
    groups = browser.u8_contact_sheet_groups(lib, 1, animated=True)
    assert len(groups) == 16
    assert groups[0].key == "shape_0001_action_00_walk_n"
    assert groups[10].key == "shape_0001_action_07_attack_e"
    assert groups[10].frame_count == 2 and groups[10].direction == 2
    weapon_groups = browser.u8_contact_sheet_groups(lib, 1, animated=True, overlay=0)
    assert weapon_groups[10].key.endswith("attack_e_overlay_0_mace")


def test_selected_animation_set_exports_every_step_across_multiple_sheets(
    owner: Path, tmp_path: Path
):
    (owner / "ANIM.DAT").write_bytes(anim_bytes(frame_count=13))
    (owner / "WPNOVLAY.DAT").unlink()
    lib = library(owner)
    paths = browser.export_u8_browser_contact_sheets(
        lib,
        1,
        tmp_path / "sheets",
        animated=True,
        group="shape_0001_action_07_attack_e",
    )
    assert [path.name for path in paths] == [
        "shape_0001_action_07_attack_e_steps_0000_0011.png",
        "shape_0001_action_07_attack_e_steps_0012_0012.png",
    ]
    with Image.open(paths[0]) as sheet:
        assert sheet.size == (880, 632)
        assert sheet.getpixel((9, 61)) == lib.palette.colors[5]
    with Image.open(paths[1]) as sheet:
        assert sheet.size == (220, 232)
        assert sheet.getpixel((9, 61)) == lib.palette.colors[5]
    assert not any("walk" in path.name for path in paths)


def test_raw_frame_sets_export_one_or_all_pages_including_last_frame(
    owner: Path, tmp_path: Path
):
    lib = library(owner)
    lib.records[3] = shape_bytes(
        [(bytes((5 + index % 20,)), 0, 0) for index in range(25)]
    )
    groups = browser.u8_contact_sheet_groups(lib, 3)
    assert [entry.frame_count for entry in groups] == [12, 12, 1]
    one = browser.export_u8_browser_contact_sheets(
        lib, 3, tmp_path / "one", group=groups[1].key
    )
    assert [path.name for path in one] == ["shape_0003_frames_0012_0023.png"]
    all_paths = browser.export_u8_browser_contact_sheets(lib, 3, tmp_path / "all")
    assert (
        len(all_paths) == 3 and all_paths[-1].name == "shape_0003_frames_0024_0024.png"
    )
    with Image.open(all_paths[-1]) as sheet:
        assert sheet.getpixel((6, 58)) == lib.palette.colors[9]


def test_all_animation_sets_and_contact_sheet_preflight_preserve_files(
    owner: Path, tmp_path: Path
):
    lib = library(owner)
    directory = tmp_path / "sheets"
    paths = browser.export_u8_browser_contact_sheets(
        lib, 1, directory, animated=True, overlay=0
    )
    assert len(paths) == 16 and len({path.name for path in paths}) == 16
    assert all("overlay_0_mace" in path.name for path in paths)
    target = tmp_path / "collision"
    target.mkdir()
    (target / paths[-1].name).write_bytes(b"keep")
    with pytest.raises(ValueError, match="already exists"):
        browser.export_u8_browser_contact_sheets(
            lib, 1, target, animated=True, overlay=0
        )
    assert list(target.iterdir()) == [target / paths[-1].name]
    assert (target / paths[-1].name).read_bytes() == b"keep"
    with pytest.raises(ValueError, match="no matching"):
        browser.export_u8_browser_contact_sheets(
            lib, 3, tmp_path / "empty", animated=True
        )
    assert not (tmp_path / "empty").exists()


@pytest.mark.parametrize("scope", ["C", "S", "A"])
def test_browser_exports_current_selected_or_all_named_contact_sets(
    owner: Path, tmp_path: Path, scope: str
):
    choose = "A7\n2\n" if scope == "S" else ""
    result = CliRunner().invoke(
        u8_app,
        [
            "shape-browse",
            "--archive",
            str(owner / "u8shapes.flx"),
            "--shape",
            "1",
            "--action",
            "0",
            "-o",
            str(tmp_path / scope),
        ],
        input=f"E\nC\nM\n{scope}\n{choose}\nQ\n",
    )
    assert result.exit_code == 0, result.output
    paths = list(
        (tmp_path / scope / "shape_0001_contact_sheets/animations").glob("*.png")
    )
    assert len(paths) == (16 if scope == "A" else 1)
    if scope == "C":
        assert paths[0].name == "shape_0001_action_00_walk_n_steps_0000_0001.png"
    if scope == "S":
        assert paths[0].name == "shape_0001_action_07_attack_e_steps_0000_0001.png"
    assert "Named contact sheet frame sets" in result.output


def test_browser_can_choose_a_raw_contact_page_without_changing_view(
    owner: Path, tmp_path: Path
):
    raw = shape_bytes([(bytes((5,)), 0, 0) for _ in range(13)])
    (owner / "U8GUMPS.FLX").write_bytes(native_flex([raw]))
    result = CliRunner().invoke(
        u8_app,
        [
            "shape-browse",
            "--archive",
            str(owner / "U8GUMPS.FLX"),
            "--shape",
            "0",
            "-o",
            str(tmp_path / "raw"),
        ],
        input="E\nC\nR\nS\nG1\n\nQ\n",
    )
    assert result.exit_code == 0, result.output
    paths = list((tmp_path / "raw/shape_0000_contact_sheets/raw_frames").glob("*.png"))
    assert len(paths) == 1 and paths[0].name == "shape_0000_frames_0012_0012.png"


def test_browser_help_and_scripted_frame_action_direction_overlay_exports(
    owner: Path, tmp_path: Path
):
    help_result = CliRunner().invoke(u8_app, ["shape-browse", "--help"])
    assert help_result.exit_code == 0
    assert "contact sheets" in help_result.output
    for option in (
        "--game-dir",
        "--archive",
        "--shape",
        "--frame",
        "--palette",
        "--anim",
        "--typeflag",
        "--action",
        "--direction",
        "--overlay",
        "--output",
    ):
        assert option in help_result.output
    output = tmp_path / "exports"
    result = CliRunner().invoke(
        u8_app,
        [
            "shape-browse",
            "--archive",
            str(owner / "u8shapes.flx"),
            "--shape",
            "1",
            "-o",
            str(output),
        ],
        input="F\nB\nM\nA7\nD\n2\nU\n0\nH\nE\nG\n\n120\nE\nP\nC\n1\n\nE\nR\n\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "direction E" in result.output and '"x_offset": -3' in result.output
    assert (output / "shape_0001_action_07_e_overlay_0.gif").exists()
    assert (output / "shape_0001_png/shape_0001_f0000.png").exists()
    assert (output / "shape_0001.json").exists()


def test_next_previous_shapes_follow_filter_and_live_playback_has_redirected_fallback(
    owner: Path,
):
    result = CliRunner().invoke(
        u8_app,
        ["shape-browse", "--archive", str(owner / "u8shapes.flx"), "--shape", "1"],
        input="O\n2\nJ\nP\nK\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "Shape 3" in result.output and "Shape 241" not in result.output
    assert "Live playback needs" in result.output
    assert result.output.count("Shape 1") >= 2


def test_cancellation_at_initial_source_prompt_is_clean(owner: Path):
    result = CliRunner().invoke(u8_app, ["shape-browse"])
    assert result.exit_code == 0 and "Cancelled" in result.output


def test_invalid_explicit_frame_returns_command_error(owner: Path):
    result = CliRunner().invoke(
        u8_app,
        [
            "shape-browse",
            "--archive",
            str(owner / "u8shapes.flx"),
            "--shape",
            "1",
            "--frame",
            "99",
        ],
    )
    assert result.exit_code == 1 and "requested frame" in result.output


def test_invalid_explicit_shape_fails_before_shape_prompt(owner: Path):
    result = CliRunner().invoke(
        u8_app,
        ["shape-browse", "--archive", str(owner / "u8shapes.flx"), "--shape", "2"],
    )
    assert (
        result.exit_code == 1 and "requested shape 2 is not populated" in result.output
    )
    assert "Shapes —" not in result.output


def test_interface_frame_lengths_excluding_eight_byte_prefix(
    owner: Path, tmp_path: Path
):
    raw = bytearray(shape_bytes([(bytes((5, 6)), 0, 0)]))
    struct.pack_into("<H", raw, 10, struct.unpack_from("<H", raw, 10)[0] - 8)
    path = tmp_path / "0007_interface.shp"
    path.write_bytes(raw)
    lib = browser.load_u8_shape_library(path, palette=owner / "u8pal.pal")
    assert lib.image(7, 0).getpixel((1, 0)) == (*lib.palette.colors[6], 255)
    assert browser.describe_u8_browser_shape(lib, 7)["frame_length_adjustment"] == 8
    assert path.read_bytes() == raw


def test_menu_action_with_missing_sprite_recovers_to_raw_frames(owner: Path):
    (owner / "ANIM.DAT").write_bytes(anim_bytes(missing=True))
    result = CliRunner().invoke(
        u8_app,
        ["shape-browse", "--archive", str(owner / "u8shapes.flx"), "--shape", "1"],
        input="M\nA7\nF\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "missing frame 99" in result.output and "sprite frame 1/1" in result.output


def test_choose_another_archive_after_load_failure_clears_initial_overrides(
    owner: Path, tmp_path: Path
):
    bad_palette = tmp_path / "bad.pal"
    bad_palette.write_bytes(b"invalid")
    result = CliRunner().invoke(
        u8_app,
        [
            "shape-browse",
            "--archive",
            str(owner / "u8shapes.flx"),
            "--shape",
            "1",
            "--palette",
            str(bad_palette),
            "--anim",
            str(owner / "ANIM.DAT"),
        ],
        input="A\n2\nS0\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "Palette file too small" in result.output
    assert "Shape 0" in result.output and "ANIM action" not in result.output


def test_configured_custom_assets_belong_only_to_the_selected_owner(
    owner: Path, monkeypatch
):
    custom = owner / "sprites.flx"
    custom.write_bytes((owner / "u8shapes.flx").read_bytes())
    colours = owner / "colours.pal"
    colours.write_bytes((owner / "u8pal.pal").read_bytes())
    props = owner / "properties.dat"
    props.write_bytes((owner / "TYPEFLAG.DAT").read_bytes())
    monkeypatch.setattr(
        _config,
        "_config",
        {
            "paths": {
                "u8shapes": str(custom),
                "palette": str(colours),
                "typeflag": str(props),
            }
        },
    )
    lib = browser.load_u8_shape_library(custom)
    assert (
        lib.world_shapes and lib.palette_path == colours and props in lib.source_paths
    )
    monkeypatch.setattr(menus, "_menu", lambda *args: "1")
    assert menus._archive(browser.U8ShapeTarget("English", owner)) == custom
    other = owner.parent / "other"
    other.mkdir()
    foreign = other / "U8SHAPES.FLX"
    foreign.write_bytes(custom.read_bytes())
    with pytest.raises(ValueError, match="no owner"):
        browser.load_u8_shape_library(foreign)


def test_u8_sequence_runs_in_the_real_terminal_player(owner: Path):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from titan._terminal_image import playback_application

    images, rows = browser.aligned_u8_sequence(
        library(owner), 1, action=7, direction=2, overlay=0
    )
    with create_pipe_input() as pipe:
        app = playback_application(
            browser.u8_playback_provider(images, rows), input=pipe, output=DummyOutput()
        )
        pipe.send_text("q")
        assert app.run() is True
