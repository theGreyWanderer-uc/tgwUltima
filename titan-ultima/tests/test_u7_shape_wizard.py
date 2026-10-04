"""Exercise the PNG wizard through conversion, approval and archive insertion."""

import struct
from functools import partial
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.u7 import shape_wizard as wizard
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape

_original_open_preview = wizard._open_preview


@pytest.fixture(autouse=True)
def isolate_profile(monkeypatch, tmp_path):
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    monkeypatch.setattr(wizard, "_exult_paths", lambda game: None)
    monkeypatch.setattr("titan._config.get_config", lambda: {})
    monkeypatch.setattr(wizard, "get_config", lambda: {})
    monkeypatch.setattr(wizard, "find_exult_cfg", lambda: None)
    monkeypatch.setattr(wizard, "_open_preview", lambda path: True)
    monkeypatch.setattr(
        wizard.tempfile,
        "NamedTemporaryFile",
        partial(wizard.tempfile.NamedTemporaryFile, dir=tmp_path),
    )


@pytest.fixture
def artwork(tmp_path):
    palette = tmp_path / "palette.pal"
    colors = np.zeros((256, 3), dtype=np.uint8)
    colors[1] = (255, 0, 0)
    colors[2] = (0, 255, 0)
    colors[3] = (0, 0, 255)
    colors[7] = (200, 200, 200)
    colors[224] = (255, 255, 255)
    palette.write_bytes(colors.tobytes())
    source = tmp_path / "art.png"
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(source)
    return wizard.ShapeWizardConfig(
        source=str(source),
        palette_file=str(palette),
        output_path=str(tmp_path / "out/art.shp"),
    )


def shape_data(ink=1):
    shape = U7Shape()
    frame = U7Shape.Frame()
    frame.width = frame.height = 2
    frame.pixels = np.full((2, 2), ink, dtype=np.uint8)
    shape.frames.append(frame)
    return shape.to_bytes()


def wizard_input(answers):
    """Select the base game target for existing retail wizard scenarios."""
    return "\n".join([answers[0], "1", *answers[1:]]) + "\n"


def write_archive(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    archive = U7FlexArchive()
    archive.records = records
    archive.magic2 = 0xCC01
    data = bytearray(archive.to_bytes())
    data[0x60:0x68] = b"reserved"
    path.write_bytes(data)


def write_recipe(
    path,
    source="art.png",
    archive="",
    output='format="shp"\npath="out/art.shp"',
    conversion="",
):
    path.write_text(
        f'[target]\ngame="BG"\n[source]\npath="{source}"\n[palette]\nfile="palette.pal"\nindex=0\n[conversion]\n{conversion}\n[archive]\n{archive}\n[output]\n{output}\n',
        encoding="utf-8",
    )


def test_single_png_matches_importer_and_roundtrips(artwork):
    result = wizard.convert(artwork)
    assert wizard.save(artwork, result) == 0
    shape = U7Shape.from_data(Path(artwork.output_path).read_bytes(), strict=True)
    assert len(shape.frames) == 1
    assert shape.frames[0].pixels[0, 0] == 255
    assert shape.frames[0].pixels[1, 1] == 1
    assert shape.frames[0].origin_x == shape.frames[0].origin_y == 0
    assert not shape.frames[0].is_tile


def test_folder_uses_windows_frame_order(tmp_path, artwork):
    folder = tmp_path / "frames"
    folder.mkdir()
    Image.new("RGB", (2, 2), (0, 255, 0)).save(folder / "frame10.png")
    Image.new("RGB", (2, 2), (255, 0, 0)).save(folder / "Frame2.PNG")
    converted = wizard.convert(replace(artwork, source=str(folder)))
    assert [p.name for p in converted.png_paths] == ["Frame2.PNG", "frame10.png"]
    assert [int(f.pixels[0, 0]) for f in converted.shape.frames] == [1, 2]


def test_cycling_opt_in_and_matching_indexed_intent(tmp_path, artwork):
    source = Path(artwork.source)
    Image.new("RGB", (2, 2), "white").save(source)
    assert wizard.convert(artwork).shape.frames[0].pixels[0, 0] == 7
    assert (
        wizard.convert(replace(artwork, allow_cycling=True))
        .shape.frames[0]
        .pixels[0, 0]
        == 224
    )
    image = Image.new("P", (2, 2), 224)
    image.putpalette(Path(artwork.palette_file).read_bytes())
    image.save(source)
    assert wizard.convert(artwork).shape.frames[0].pixels[0, 0] == 224


def test_exult_origin_is_encoded(artwork):
    converted = wizard.convert(replace(artwork, origin_x=3, origin_y=2))
    frame = U7Shape.from_data(converted.data, strict=True).frames[0]
    assert (frame.origin_x, frame.origin_y) == (3, 2)
    assert (frame.hotspot_x_from_left, frame.hotspot_y_from_top) == (4, 5)


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin_x", -32768),
        ("palette_index", -1),
        ("slot", -1),
        ("slot", True),
        ("flat", "yes"),
        ("archive_kind", "bad"),
    ],
)
def test_invalid_settings_write_nothing(artwork, field, value):
    with pytest.raises(ValueError):
        wizard.convert(replace(artwork, **{field: value}))
    assert not Path(artwork.output_path).exists()


@pytest.mark.parametrize("size", [(321, 8), (8, 201)])
def test_hard_cap_applies_before_output(artwork, size):
    Image.new("RGB", size, "red").save(artwork.source)
    with pytest.raises(ValueError, match="maximum permitted"):
        wizard.convert(artwork)
    assert not Path(artwork.output_path).exists()


def test_warning_threshold_preserves_size(artwork, capsys):
    Image.new("RGB", (73, 72), "red").save(artwork.source)
    converted = wizard.convert(artwork)
    assert converted.shape.frames[0].width == 73
    assert "72x72 warning" in capsys.readouterr().err


@pytest.mark.parametrize("size,alpha", [((9, 8), 255), ((8, 8), 127)])
def test_flat_requires_opaque_8x8(artwork, size, alpha):
    Image.new("RGBA", size, (255, 0, 0, alpha)).save(artwork.source)
    with pytest.raises(ValueError):
        wizard.convert(replace(artwork, flat=True))


def test_flat_allocates_only_below_150(tmp_path, artwork):
    Image.new("RGB", (8, 8), "red").save(artwork.source)
    cfg = replace(
        artwork,
        flat=True,
        output_format="flex",
        archive_output=str(tmp_path / "new.vga"),
    )
    converted = wizard.convert(cfg)
    assert len(converted.data) == 64
    assert wizard.prepare_archive(cfg, converted.data).slot == 0
    with pytest.raises(ValueError, match="0-149"):
        wizard.prepare_archive(replace(cfg, slot=150), converted.data)


def test_flat_full_reserved_range_does_not_append(tmp_path, artwork):
    Image.new("RGB", (8, 8), "red").save(artwork.source)
    archive = tmp_path / "flat.vga"
    write_archive(archive, [bytes([1]) * 64] * 150)
    cfg = replace(
        artwork,
        flat=True,
        output_format="flex",
        archive_source=str(archive),
        archive_output=str(tmp_path / "out.vga"),
    )
    with pytest.raises(ValueError, match="No free"):
        wizard.prepare_archive(cfg, wizard.convert(cfg).data)


def test_objects_do_not_use_flat_slots_even_for_8x8(tmp_path, artwork):
    cfg = replace(
        artwork, output_format="flex", archive_output=str(tmp_path / "new.vga")
    )
    converted = wizard.convert(cfg)
    assert wizard.prepare_archive(cfg, converted.data).slot == 150
    with pytest.raises(ValueError, match="150-65535"):
        wizard.prepare_archive(replace(cfg, slot=149), converted.data)


def test_other_libraries_can_start_at_zero(tmp_path, artwork):
    cfg = replace(
        artwork,
        output_format="flex",
        archive_kind="generic",
        archive_output=str(tmp_path / "sprites.flx"),
    )
    converted = wizard.convert(cfg)
    assert wizard.prepare_archive(cfg, converted.data).slot == 0


def test_shape_archive_name_cannot_bypass_flat_guard(tmp_path, artwork):
    cfg = replace(
        artwork,
        output_format="flex",
        archive_kind="generic",
        archive_output=str(tmp_path / "shapes.vga"),
    )
    with pytest.raises(ValueError, match="flat-slot rules"):
        wizard.prepare_archive(cfg, wizard.convert(cfg).data)


def test_sparse_destination_uses_combined_occupancy(tmp_path, artwork):
    base = tmp_path / "game/STATIC/SHAPES.VGA"
    patch = tmp_path / "game/mods/test/patch/shapes.vga"
    target = tmp_path / "game/patch/shapes.vga"
    write_archive(base, [b""] * 150 + [shape_data(1), b"", shape_data(2)])
    write_archive(patch, [b""] * 150 + [shape_data(3)])
    write_archive(target, [b""] * 151 + [shape_data(4)])
    cfg = replace(
        artwork,
        output_format="flex",
        archive_source=str(patch),
        archive_output=str(target),
        force=True,
    )
    before = base.read_bytes(), patch.read_bytes()
    converted = wizard.convert(cfg)
    assert wizard.prepare_archive(cfg, converted.data).slot == 153
    assert wizard.save(cfg, converted) == 0
    saved = U7FlexArchive.from_file(str(target), strict=True)
    assert saved.records[150] == b""
    assert saved.records[151] == shape_data(4)
    assert saved.records[152] == b""
    assert saved.records[153] == converted.data
    assert (base.read_bytes(), patch.read_bytes()) == before
    assert target.read_bytes()[0x60:0x68] == b"reserved"
    assert saved.magic2 == 0xCC01


@pytest.mark.parametrize("mode", ["patch", "copy"])
def test_patch_or_copy_selected_archive(tmp_path, artwork, mode):
    source = tmp_path / "STATIC/SHAPES.VGA"
    target = tmp_path / "patch/shapes.vga"
    write_archive(source, [b""] * 150 + [shape_data(), b"", shape_data(2)])
    cfg = replace(
        artwork,
        output_format="both",
        archive_source=str(source),
        archive_output=str(target),
        archive_mode=mode,
    )
    converted = wizard.convert(cfg)
    assert wizard.save(cfg, converted) == 0
    saved = U7FlexArchive.from_file(str(target), strict=True)
    assert saved.records[151] == converted.data
    assert saved.records[150] == (shape_data() if mode == "copy" else b"")
    assert target.read_bytes()[0x60:0x68] == b"reserved"
    assert Path(cfg.output_path).read_bytes() == converted.data


def test_occupied_slot_needs_explicit_replace(tmp_path, artwork):
    source = tmp_path / "base.vga"
    write_archive(source, [b""] * 150 + [shape_data()])
    cfg = replace(
        artwork,
        output_format="flex",
        archive_source=str(source),
        archive_output=str(tmp_path / "out.vga"),
        slot=150,
        force=True,
    )
    converted = wizard.convert(cfg)
    with pytest.raises(FileExistsError, match="occupied"):
        wizard.prepare_archive(cfg, converted.data)
    assert (
        wizard.prepare_archive(replace(cfg, replace=True), converted.data).slot == 150
    )


def test_in_place_is_explicit_and_atomic(tmp_path, artwork, monkeypatch):
    source = tmp_path / "base.vga"
    write_archive(source, [b""] * 150)
    cfg = replace(
        artwork,
        output_format="flex",
        archive_source=str(source),
        archive_output=str(source),
        force=True,
    )
    converted = wizard.convert(cfg)
    with pytest.raises(ValueError, match="in-place"):
        wizard.save(cfg, converted)
    before = source.read_bytes()
    monkeypatch.setattr(
        wizard.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        wizard.save(replace(cfg, in_place=True), converted)
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))


def test_corrupt_archive_prevents_all_output(tmp_path, artwork):
    source = tmp_path / "bad.vga"
    write_archive(source, [shape_data()])
    data = bytearray(source.read_bytes())
    struct.pack_into("<I", data, 132, 999999)
    source.write_bytes(data)
    cfg = replace(
        artwork,
        output_format="both",
        archive_source=str(source),
        archive_output=str(tmp_path / "out.vga"),
    )
    with pytest.raises(ValueError):
        wizard.save(cfg, wizard.convert(cfg))
    assert not Path(cfg.output_path).exists()
    assert source.read_bytes() == data


def test_existing_outputs_require_force(artwork):
    converted = wizard.convert(artwork)
    wizard.save(artwork, converted)
    with pytest.raises(FileExistsError):
        wizard.save(artwork, converted)
    assert wizard.save(replace(artwork, force=True), converted) == 0


def test_preview_png_keeps_sources_safe_and_compares_both(tmp_path, artwork):
    before = Path(artwork.source).read_bytes()
    converted = wizard.convert(artwork)
    with pytest.raises(ValueError, match="separate from source PNGs"):
        wizard.save(
            replace(artwork, preview_path=artwork.source, force=True), converted
        )
    assert Path(artwork.source).read_bytes() == before
    preview = tmp_path / "preview.png"
    assert wizard.save(replace(artwork, preview_path=str(preview)), converted) == 0
    with Image.open(preview) as image:
        assert image.size == (352, 112)
        assert image.getpixel((15, 40)) == (255, 0, 0)
        assert image.getpixel((191, 40)) == (255, 0, 0)


def test_recipe_paths_and_archive_override_are_noninteractive(
    tmp_path, artwork, monkeypatch
):
    path = tmp_path / "recipe.toml"
    source = tmp_path / "base.vga"
    write_archive(source, [b""] * 150)
    write_recipe(
        path, archive='source="base.vga"', output='format="flex"\narchive="ignored.vga"'
    )
    output = tmp_path / "destination.vga"
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("recipe prompted"))
    monkeypatch.setattr(
        wizard, "_open_preview", lambda path: pytest.fail("recipe opened viewer")
    )
    result = CliRunner().invoke(
        u7_app, ["shape-create", "--config", str(path), "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert U7FlexArchive.from_file(str(output), strict=True).records[150]
    assert not (tmp_path / "ignored.vga").exists()


def test_recipe_missing_base_fails_without_prompt(tmp_path, artwork, monkeypatch):
    path = tmp_path / "recipe.toml"
    write_recipe(path, output='format="flex"\narchive="patch/shapes.vga"')
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("recipe prompted"))
    assert wizard.run_from_config(str(path)) == 1
    assert not (tmp_path / "patch/shapes.vga").exists()


def test_interactive_redo_invalid_answer_and_output_override(tmp_path, artwork):
    output = tmp_path / "wizard.shp"
    answers = [
        "1",
        "",
        artwork.palette_file,
        "",
        "n",
        "1",
        "",
        "",
        "r",
        "",
        "",
        "",
        "n",
        "1",
        "",
        "",
        "MAYBE",
        "y",
        "1",
        "y",
    ]
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", artwork.source, "-o", str(output)],
        input=wizard_input(answers),
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Converted 1 frame(s)") == 2
    assert "Please enter one of: Y, R, Q" in result.output
    assert "Shape filename" not in result.output
    assert output.is_file()


@pytest.mark.parametrize("answer", ["q", "y\n1\nn"])
def test_interactive_cancel_never_writes(tmp_path, artwork, answer):
    output = tmp_path / "wizard.shp"
    answers = ["1", "", artwork.palette_file, "", "n", "1", "", "", answer]
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", artwork.source, "-o", str(output)],
        input=wizard_input(answers),
    )
    assert result.exit_code == 0, result.output
    assert not output.exists()


def test_interactive_archive_selects_combined_free_slot(tmp_path, artwork):
    source = tmp_path / "STATIC/SHAPES.VGA"
    target = tmp_path / "patch/shapes.vga"
    write_archive(source, [b""] * 150 + [shape_data(), b"", shape_data(2)])
    answers = [
        "1",
        "",
        artwork.palette_file,
        "",
        "n",
        "1",
        "",
        "",
        "y",
        "2",
        "1",
        str(source),
        "1",
        "a",
        "y",
    ]
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", artwork.source, "-o", str(target)],
        input=wizard_input(answers),
    )
    assert result.exit_code == 0, result.output
    assert "First free permitted slot in base + patch: 151" in result.output
    assert U7FlexArchive.from_file(str(target), strict=True).records[151]


def test_interactive_full_flat_range_allows_explicit_replacement(tmp_path, artwork):
    Image.new("RGB", (8, 8), "red").save(artwork.source)
    source, target = tmp_path / "flat.vga", tmp_path / "patch/flat.vga"
    write_archive(source, [bytes([2]) * 64] * 150)
    answers = [
        "1",
        "",
        artwork.palette_file,
        "",
        "n",
        "2",
        "y",
        "2",
        str(source),
        "1",
        "12",
        "y",
        "y",
    ]
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", artwork.source, "-o", str(target)],
        input=wizard_input(answers),
    )
    assert result.exit_code == 0, result.output
    assert "No free U7 Flex shape record" in result.output
    saved = U7FlexArchive.from_file(str(target), strict=True)
    assert len(saved.records) == 13
    assert saved.records[12] == bytes([1]) * 64
    assert saved.records[11] == b""


def test_help_describes_workflow_and_recipe_options():
    result = CliRunner().invoke(u7_app, ["shape-create", "--help"])
    assert result.exit_code == 0
    for option in (
        "--config",
        "--preview",
        "--base-archive",
        "--allow-cycling",
        "--in-place",
    ):
        assert option in result.output


def test_image_preview_shows_large_source_and_quantized_pixels(
    artwork, monkeypatch, capsys
):
    image = Image.new("RGBA", (192, 192), (220, 20, 10, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(artwork.source)
    before = Path(artwork.source).read_bytes()
    opened = []
    monkeypatch.setattr(
        wizard, "_open_preview", lambda path: opened.append(path) or True
    )
    converted = wizard.convert(artwork)
    path = wizard.show_preview(converted, open_image=True)
    assert opened == [path]
    with Image.open(path) as preview:
        assert preview.size == (800, 408)
        assert preview.getpixel((208, 220)) == (220, 20, 10)
        assert preview.getpixel((608, 220)) == (255, 0, 0)
        assert (
            preview.getpixel((8, 20)) == preview.getpixel((408, 20)) == (160, 160, 160)
        )
    assert Path(artwork.source).read_bytes() == before
    output = capsys.readouterr().out
    assert "Image preview" in output
    assert "\x1b[" not in output
    assert "██" not in output
    assert not Path(artwork.output_path).exists()


def test_preview_remains_available_when_viewer_cannot_open(
    artwork, monkeypatch, capsys
):
    monkeypatch.setattr(wizard, "_open_preview", lambda path: False)
    path = wizard.show_preview(wizard.convert(artwork), open_image=True)
    assert path.is_file()
    assert "Could not open the image viewer" in capsys.readouterr().out


@pytest.mark.parametrize("fails", [False, True])
def test_windows_preview_opens_only_the_generated_png(tmp_path, monkeypatch, fails):
    preview = tmp_path / "preview.png"
    opened = []

    def startfile(path):
        if fails:
            raise OSError("no viewer")
        opened.append(path)

    monkeypatch.setattr(wizard.sys, "platform", "win32")
    monkeypatch.setattr(wizard.os, "startfile", startfile, raising=False)
    # The fixture isolates real viewer launches; exercise the actual launcher here.
    assert _original_open_preview(preview) is (not fails)
    assert opened == ([] if fails else [str(preview)])


@pytest.mark.parametrize("existing_patch", [False, True])
def test_interactive_gumps_selection_uses_gumps_base_and_patch_slots(
    tmp_path, artwork, monkeypatch, existing_patch
):
    static = tmp_path / "STATIC"
    base = static / "GUMPS.VGA"
    target = tmp_path / "patch/GUMPS.VGA"
    write_archive(base, [shape_data(2), b"", shape_data(3)])
    if existing_patch:
        write_archive(target, [b"", shape_data(4)])
    before = base.read_bytes()
    monkeypatch.setattr(wizard, "_static_path", lambda game: str(static))
    paths = wizard.ExultGamePaths(
        game="SI", static_path=str(static), patch_path=str(target.parent)
    )
    monkeypatch.setattr(wizard, "_exult_paths", lambda game: paths)
    answers = [
        "2",
        "",
        artwork.palette_file,
        "",
        "n",
        "1",
        "",
        "",
        "y",
        "2",
        "2",
        "",
        "1",
        "",
        "a",
    ]
    if existing_patch:
        answers.append("y")
    answers.append("y")
    result = CliRunner().invoke(
        u7_app, ["shape-create", artwork.source], input=wizard_input(answers)
    )
    assert result.exit_code == 0, result.output
    assert "GUMPS.VGA — inventory" in result.output
    assert f"Destination archive [{target}]" in result.output
    assert "Permitted shape slots: 0+" in result.output
    slot = 3 if existing_patch else 1
    assert f"Shape slot: {slot}" in result.output
    archive = U7FlexArchive.from_file(str(target), strict=True)
    assert archive.records[slot] == wizard.convert(artwork).data
    if existing_patch:
        assert archive.records[1] == shape_data(4)
    assert archive.records[0] == b""
    assert base.read_bytes() == before


def test_interactive_new_library_needs_no_source_archive(tmp_path, artwork):
    target = tmp_path / "new.vga"
    answers = [
        "1",
        "",
        artwork.palette_file,
        "",
        "n",
        "1",
        "",
        "",
        "y",
        "2",
        "6",
        str(target),
        "a",
        "y",
    ]
    result = CliRunner().invoke(
        u7_app, ["shape-create", artwork.source], input=wizard_input(answers)
    )
    assert result.exit_code == 0, result.output
    assert "Base/source" not in result.output
    assert (
        U7FlexArchive.from_file(str(target), strict=True).records[0]
        == wizard.convert(artwork).data
    )


@pytest.mark.parametrize("standalone", [False, True])
def test_interactive_mod_target_uses_own_patch_and_correct_base(
    tmp_path, artwork, monkeypatch, standalone
):
    retail = tmp_path / "retail/STATIC"
    mod = tmp_path / "retail/mods/custom"
    own_static = mod / "STATIC"
    patch = mod / "patch/GUMPS.VGA"
    write_archive(retail / "GUMPS.VGA", [shape_data(2)] * 5)
    if standalone:
        write_archive(own_static / "GUMPS.VGA", [b"", shape_data(3)])
    write_archive(patch, [shape_data(4)])
    before = patch.read_bytes()
    monkeypatch.setattr(wizard, "_static_path", lambda game: str(retail))
    # Select the manual folder; discovery is isolated from the machine profile.
    answers = [
        "2",
        "2",
        str(mod),
        "",
        artwork.palette_file,
        "",
        "n",
        "1",
        "",
        "",
        "y",
        "2",
        "2",
        "",
        "1",
        "",
        "a",
        "y",
        "y",
    ]
    result = CliRunner().invoke(
        u7_app, ["shape-create", artwork.source], input="\n".join(answers) + "\n"
    )
    assert result.exit_code == 0, result.output
    slot = 2 if standalone else 5
    assert f"Shape slot: {slot}" in result.output
    assert f"Destination archive [{patch}]" in result.output
    saved = U7FlexArchive.from_file(str(patch), strict=True)
    assert saved.records[0] == shape_data(4)
    assert saved.records[slot] == wizard.convert(artwork).data
    assert patch.read_bytes()[0x58:0x80] == before[0x58:0x80]
    assert "Target: custom (SI flavour)" in result.output


def test_standalone_patch_without_matching_static_does_not_inherit_retail(
    tmp_path, artwork, monkeypatch
):
    retail = tmp_path / "retail/STATIC"
    own_static = tmp_path / "retail/mods/custom/STATIC"
    own_static.mkdir(parents=True)
    patch = own_static.parent / "patch/GUMPS.VGA"
    write_archive(retail / "GUMPS.VGA", [shape_data(2)] * 5)
    write_archive(patch, [b"", shape_data(3)])
    monkeypatch.setattr(wizard, "_static_path", lambda game: str(retail))
    config = replace(
        artwork,
        output_format="flex",
        archive_kind="generic",
        archive_source=str(patch),
        archive_output=str(patch),
        in_place=True,
        target_static=str(own_static),
        standalone=True,
    )
    plan = wizard.prepare_archive(config, wizard.convert(config).data)
    assert plan.slot == 0
    assert len(plan.archive.records) == 2


def test_mod_source_in_custom_patch_folder_inherits_selected_retail_base(
    tmp_path, artwork
):
    static = tmp_path / "retail/STATIC"
    source = tmp_path / "elsewhere/data/GUMPS.VGA"
    write_archive(static / "GUMPS.VGA", [shape_data(2)] * 5)
    write_archive(source, [b"", shape_data(3)])
    config = replace(
        artwork,
        output_format="flex",
        archive_kind="generic",
        archive_source=str(source),
        archive_output=str(source),
        in_place=True,
        target_static=str(static),
        target_patch=str(source.parent),
    )
    before = source.read_bytes()
    plan = wizard.prepare_archive(config, wizard.convert(config).data)
    assert plan.slot == 5
    assert plan.archive.records[0] == b""
    assert plan.archive.records[1] == shape_data(3)
    assert source.read_bytes() == before


@pytest.mark.parametrize("patch_record", [False, True])
def test_selected_target_palette_uses_patch_then_own_static(
    tmp_path, artwork, monkeypatch, patch_record
):
    static, patch = tmp_path / "custom/STATIC", tmp_path / "custom/patch"
    write_archive(static / "PALETTES.FLX", [bytes([10]) * 768])
    write_archive(patch / "PALETTES.FLX", [bytes([20]) * 768 if patch_record else b""])
    monkeypatch.setattr(
        wizard,
        "resolve_game_palette",
        lambda *args: pytest.fail("retail palette selected"),
    )
    config = replace(
        artwork,
        palette_file=None,
        target_static=str(static),
        target_patch=str(patch),
        standalone=True,
    )
    assert wizard._palette(config).colors[1] == tuple([80 if patch_record else 40] * 3)


def test_standalone_missing_palette_requires_explicit_selection(artwork, tmp_path):
    config = replace(
        artwork,
        palette_file=None,
        target_static=str(tmp_path / "missing"),
        standalone=True,
    )
    with pytest.raises(ValueError, match="selected Exult game"):
        wizard.convert(config)


def test_recipe_custom_target_resolves_paths_and_preserves_exult_header(
    tmp_path, artwork
):
    source = tmp_path / "custom/STATIC/GUMPS.VGA"
    target = tmp_path / "custom/patch/GUMPS.VGA"
    write_archive(source, [b"", shape_data(2)])
    before = source.read_bytes()
    recipe = tmp_path / "custom.toml"
    recipe.write_text("""[target]
game = "SI"
static = "custom/STATIC"
patch = "custom/patch"
standalone = true
[source]
path = "art.png"
[palette]
file = "palette.pal"
[archive]
source = "custom/STATIC/GUMPS.VGA"
kind = "generic"
[output]
format = "flex"
""")
    result = CliRunner().invoke(u7_app, ["shape-create", "--config", str(recipe)])
    assert result.exit_code == 0, result.output
    assert "Shape inserted at slot 0" in result.output
    assert target.read_bytes()[0x58:0x80] == before[0x58:0x80]
    assert source.read_bytes() == before


def test_picker_discovers_registered_exult_game(tmp_path, monkeypatch, capsys):
    custom = tmp_path / "my-game"
    custom.mkdir()
    cfg = tmp_path / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><custom><path>{custom}</path><title>My Game</title></custom></game></disk></config>"
    )
    monkeypatch.setattr(wizard, "find_exult_cfg", lambda: cfg)
    monkeypatch.setattr("builtins.input", lambda prompt: "2")
    config = wizard.ShapeWizardConfig(game="SI")
    wizard._select_target(config)
    assert config.target_static == str(custom / "static")
    assert config.target_patch == str(custom / "patch")
    assert config.standalone
    assert "My Game (Exult game)" in capsys.readouterr().out
