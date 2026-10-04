"""Exercise the PNG wizard through conversion, approval and archive insertion."""

import struct
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


@pytest.fixture(autouse=True)
def isolate_profile(monkeypatch):
    monkeypatch.setattr(wizard, "get_config", lambda: {})
    monkeypatch.setattr(wizard, "_exult_paths", lambda game: None)
    monkeypatch.setattr("titan._config.get_config", lambda: {})


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
        input="\n".join(answers) + "\n",
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Converted 1 frame(s)") == 2
    assert "Choose one of: Y R Q" in result.output
    assert "Shape filename" not in result.output
    assert output.is_file()


@pytest.mark.parametrize("answer", ["q", "y\n1\nn"])
def test_interactive_cancel_never_writes(tmp_path, artwork, answer):
    output = tmp_path / "wizard.shp"
    answers = ["1", "", artwork.palette_file, "", "n", "1", "", "", answer]
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", artwork.source, "-o", str(output)],
        input="\n".join(answers) + "\n",
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
        str(source),
        "1",
        "1",
        "a",
        "y",
    ]
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", artwork.source, "-o", str(target)],
        input="\n".join(answers) + "\n",
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
        input="\n".join(answers) + "\n",
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
