"""Animation prompts and actual TFA flags across PNG, wizard and Flex import flows."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.cli import app
from titan.u7 import shape_wizard as wizard
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape
from titan.u7.shape_animation_flag import (
    choose_u7_shape_animation,
    prepare_u7_archive_animation,
    read_u7_shape_animation,
    u7_animation_sidecar,
    u7_shape_animation_payload,
)


def shape_bytes(count=2):
    shape = U7Shape()
    for ink in range(1, count + 1):
        frame = U7Shape.Frame()
        frame.width = frame.height = 2
        frame.pixels = np.full((2, 2), ink, dtype=np.uint8)
        shape.frames.append(frame)
    return shape.to_bytes()


@pytest.fixture
def assets(tmp_path, monkeypatch):
    monkeypatch.setattr("titan._config.get_config", lambda: {})
    monkeypatch.setattr(wizard, "get_config", lambda: {})
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    source = tmp_path / "source"
    source.mkdir()
    archive = U7FlexArchive()
    archive.records = [b""] * 151
    archive.save(str(source / "SHAPES.VGA"))
    raw = bytes((index * 17) % 256 for index in range(3584))
    (source / "TFA.DAT").write_bytes(raw)
    (source / "actor.shp").write_bytes(shape_bytes())
    frames = tmp_path / "frames"
    frames.mkdir()
    palette = U7Palette.default_palette()
    (tmp_path / "palette.pal").write_bytes(
        bytes(value for color in palette.colors for value in color)
    )
    for index in range(2):
        image = Image.new("P", (2, 2), index + 1)
        image.putpalette([value for color in palette.colors for value in color])
        image.save(frames / f"{index:04d}.png")
    return source, tmp_path, raw


@pytest.mark.parametrize("answer,enabled", [("Y", True), ("N", False)])
def test_flex_add_prompts_and_changes_only_the_animated_flag(assets, answer, enabled):
    source, root, raw = assets
    output = root / "result/SHAPES.VGA"
    result = CliRunner().invoke(
        u7_app,
        [
            "flex-add-shape",
            str(source / "SHAPES.VGA"),
            str(source / "actor.shp"),
            "-o",
            str(output),
            "--index",
            "150",
        ],
        input=answer + "\n",
    )
    assert result.exit_code == 0, result.output
    assert "Should these 2 frames animate?" in result.output
    expected = bytearray(raw)
    expected[450] = expected[450] | 4 if enabled else expected[450] & ~4
    assert (output.parent / "TFA.DAT").read_bytes() == expected
    assert (source / "TFA.DAT").read_bytes() == raw
    assert U7FlexArchive.from_file(str(source / "SHAPES.VGA")).records[150] == b""


@pytest.mark.parametrize("command", ["shape-import", "shape-create"])
def test_standalone_creation_carries_yes_choice_to_archive_import(
    assets, command, monkeypatch
):
    source, root, _ = assets
    output = root / "actor.shp"
    if command == "shape-import":
        result = CliRunner().invoke(
            u7_app,
            [
                command,
                str(root / "frames"),
                "--palette",
                str(root / "palette.pal"),
                "-o",
                str(output),
            ],
            input="Y\n",
        )
        assert result.exit_code == 0, result.output
    else:
        config = wizard.ShapeWizardConfig(
            source=str(root / "frames"),
            palette_file=str(root / "palette.pal"),
            output_path=str(output),
            animated=True,
        )
        assert wizard.save(config, wizard.convert(config)) == 0
    raw = output.read_bytes()
    assert read_u7_shape_animation(output, raw) is True
    result = CliRunner().invoke(
        u7_app,
        [
            "flex-add-shape",
            str(source / "SHAPES.VGA"),
            str(output),
            "-o",
            str(root / "result/SHAPES.VGA"),
            "--index",
            "150",
        ],
        input="\n",
    )
    assert result.exit_code == 0, result.output
    assert (root / "result/TFA.DAT").read_bytes()[450] & 4


def test_wizard_prompt_for_multiple_frames_and_recipe_setting(assets, monkeypatch):
    _, root, _ = assets
    monkeypatch.setattr(wizard, "_select_target", lambda config: None)
    monkeypatch.setattr(wizard, "show_preview", lambda *args, **kwargs: None)
    config = wizard.ShapeWizardConfig(
        source=str(root / "frames"), palette_file=str(root / "palette.pal")
    )
    converted = wizard.convert(config)
    monkeypatch.setattr(wizard, "_conversion_steps", lambda config: converted)
    result = CliRunner().invoke(
        u7_app,
        ["shape-create", str(root / "frames"), "-o", str(root / "created.shp")],
        input="1\nY\nY\n1\nY\n",
    )
    assert result.exit_code == 0, result.output
    assert "Should these 2 frames animate?" in result.output
    assert (
        read_u7_shape_animation(
            root / "created.shp", (root / "created.shp").read_bytes()
        )
        is True
    )
    recipe = root / "recipe.toml"
    recipe.write_text(
        '[source]\npath="frames"\n[palette]\nfile="palette.pal"\n[conversion]\nanimated=true\n[archive]\nkind="shapes"\nslot=150\n[output]\nformat="flex"\narchive="recipe/SHAPES.VGA"\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(u7_app, ["shape-create", "--config", str(recipe)])
    assert result.exit_code == 0, result.output
    assert "Should these" not in result.output
    assert (root / "recipe/TFA.DAT").read_bytes()[450] & 4


@pytest.mark.parametrize("command", ["flex-update", "flex-create"])
def test_generic_flex_import_of_u7_shape_updates_world_flag(assets, command):
    source, root, raw = assets
    output = root / "result/SHAPES.VGA"
    if command == "flex-update":
        arguments = [
            command,
            str(source / "SHAPES.VGA"),
            "--data",
            str(source / "actor.shp"),
            "--index",
            "150",
            "-o",
            str(output),
        ]
    else:
        (source / "0150_ACTOR.shp").write_bytes(shape_bytes())
        u7_animation_sidecar(source / "0150_ACTOR.shp").write_bytes(
            u7_shape_animation_payload(shape_bytes(), True)
        )
        arguments = [command, str(source), "--archive-format", "u7", "-o", str(output)]
    result = CliRunner().invoke(app, arguments, input="Y\n")
    assert result.exit_code == 0, result.output
    assert "Should these 2 frames animate?" in result.output
    assert (output.parent / "TFA.DAT").read_bytes()[450] & 4
    assert U7FlexArchive.from_file(str(output)).records[150] == shape_bytes()
    assert (source / "TFA.DAT").read_bytes() == raw


def test_no_animate_clears_flag_and_preserves_unrelated_bits(assets):
    source, root, raw = assets
    source_table = bytearray(raw)
    source_table[450] |= 4
    (source / "TFA.DAT").write_bytes(source_table)
    result = CliRunner().invoke(
        u7_app,
        [
            "flex-add-shape",
            str(source / "SHAPES.VGA"),
            str(source / "actor.shp"),
            "-o",
            str(root / "result/SHAPES.VGA"),
            "--index",
            "150",
            "--no-animate",
        ],
    )
    assert result.exit_code == 0, result.output
    expected = bytearray(source_table)
    expected[450] &= ~4
    assert (root / "result/TFA.DAT").read_bytes() == expected
    assert "Should these" not in result.output


def test_extended_patch_table_does_not_treat_retail_animation_nibbles_as_entries(
    assets,
):
    source, root, raw = assets
    output = root / "patch/SHAPES.VGA"
    payloads = prepare_u7_archive_animation(
        output,
        {1024: (shape_bytes(), True)},
        world_shapes=True,
        sources=(source / "SHAPES.VGA",),
    )
    table = next(data for path, data in payloads if path.name == "TFA.DAT")
    assert table[:3072] == raw[:3072] and table[3072:] == bytes((4, 0, 0))
    with pytest.raises(ValueError, match="separate patch"):
        prepare_u7_archive_animation(
            source / "SHAPES.VGA", {1024: (shape_bytes(), True)}, world_shapes=True
        )


def test_generic_library_has_choice_without_mutating_world_tfa(assets):
    source, root, raw = assets
    output = source / "GUMPS.VGA"
    payloads = prepare_u7_archive_animation(
        output, {0: (shape_bytes(), True)}, world_shapes=False, sources=(source,)
    )
    assert len(payloads) == 1 and payloads[0][0] == u7_animation_sidecar(output)
    assert json.loads(payloads[0][1])["shapes"]["0"]["animated"] is True
    assert (source / "TFA.DAT").read_bytes() == raw


def test_stale_sidecar_is_not_applied_to_changed_shape(tmp_path):
    path = tmp_path / "shape.shp"
    raw = shape_bytes()
    u7_animation_sidecar(path).write_bytes(u7_shape_animation_payload(raw, True))
    assert read_u7_shape_animation(path, raw) is True
    assert read_u7_shape_animation(path, shape_bytes(3)) is None


def test_cancelled_animation_prompt_does_not_write_any_output(assets, monkeypatch):
    from titan import _wizard_ui as ui

    source, root, _ = assets

    def cancel(*args, **kwargs):
        raise ui.PromptCancelled

    monkeypatch.setattr(ui, "choice", cancel)
    output = root / "cancel/SHAPES.VGA"
    result = CliRunner().invoke(
        u7_app,
        [
            "flex-add-shape",
            str(source / "SHAPES.VGA"),
            str(source / "actor.shp"),
            "--index",
            "150",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0 and "Cancelled" in result.output
    assert not output.parent.exists()


def test_malformed_tfa_rejected_before_archive_write(assets):
    source, root, _ = assets
    (source / "TFA.DAT").write_bytes(b"bad table!")
    output = root / "invalid/SHAPES.VGA"
    result = CliRunner().invoke(
        u7_app,
        [
            "flex-add-shape",
            str(source / "SHAPES.VGA"),
            str(source / "actor.shp"),
            "--index",
            "150",
            "-o",
            str(output),
            "--animate",
        ],
    )
    assert result.exit_code == 1 and "incomplete TFA" in result.output
    assert not output.parent.exists()


def test_single_frame_and_raw_flats_do_not_prompt(monkeypatch):
    monkeypatch.setattr(
        "titan._wizard_ui.choice",
        lambda *args, **kwargs: pytest.fail("Unexpected animation prompt"),
    )
    assert (
        choose_u7_shape_animation(U7Shape.from_data(shape_bytes(1), strict=True))
        is None
    )
    flat = U7Shape.from_data(bytes(range(64)) * 2, strict=True)
    assert choose_u7_shape_animation(flat) is None
    with pytest.raises(ValueError, match="more than one RLE"):
        choose_u7_shape_animation(flat, animated=True)


@pytest.mark.parametrize("command", ["shape-import", "shape-create", "flex-add-shape"])
def test_u7_help_animation_options(command):
    result = CliRunner().invoke(u7_app, [command, "--help"])
    assert result.exit_code == 0
    assert "--animate" in result.output and "--no-animate" in result.output
