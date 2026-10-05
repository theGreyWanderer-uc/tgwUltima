"""Map wizard review, world isolation, reduced rendering, and safe outputs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.u7 import cli, map_wizard as wizard
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.flex import U7FlexArchive
from titan.u7.map import U7MapRenderer, U7TileRectOverlay
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape
from titan.u7.target_picker import select_map


def archive(path: Path, records: list[bytes]) -> None:
    flex = U7FlexArchive()
    flex.records = records
    path.write_bytes(flex.to_bytes())


def options(**changes) -> SimpleNamespace:
    defaults = dict(
        game="si",
        static=None,
        patch_dir=None,
        map_root=None,
        base_static=None,
        gamedat=None,
        map_num=0,
        palette=None,
        palette_index=0,
        output=None,
        superchunk=None,
        chunk_x0=0,
        chunk_y0=0,
        chunk_x1=None,
        chunk_y1=None,
        view="classic",
        grid=False,
        grid_size=1,
        exclude_flags=[],
        max_lift=None,
        highlight_rects=[],
        highlight_width=3,
        highlight_lift=0,
        highlight_fill_alpha=128,
        highlight_labels=True,
        include_ireg=False,
    )
    return SimpleNamespace(**(defaults | changes))


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "world"
    static, patch = root / "static", root / "patch"
    static.mkdir(parents=True)
    patch.mkdir()
    (static / "u7map").write_bytes(bytes(144 * 256 * 2))
    (static / "u7chunks").write_bytes(bytes(512))
    frame = U7Shape.Frame()
    frame.width = frame.height = 16
    frame.pixels = np.full((16, 16), 6, dtype=np.uint8)
    shape = U7Shape()
    shape.frames = [frame]
    archive(static / "shapes.vga", [bytes([5]) * 64, *([b""] * 149), shape.to_bytes()])
    palette = bytearray(768)
    palette[15:18] = bytes([63, 0, 0])
    palette[18:21] = bytes([0, 63, 0])
    archive(static / "palettes.flx", [bytes(palette)])
    tfa = bytearray(3 * 151)
    tfa[150 * 3 : 150 * 3 + 3] = bytes([8, 2, 0])  # Solid object.
    (static / "TFA.DAT").write_bytes(tfa)
    archive(static / "u7ifix00", [bytes([0x88, 3, 150, 0])])
    target = ArchiveTarget("Custom SI world", static, patch, standalone=True, root=root)
    monkeypatch.setattr(wizard, "game_targets", lambda game: (target, []))
    monkeypatch.setattr(
        cli, "_resolve_u7_paths", lambda game: (str(tmp_path / "wrong-retail"), None)
    )
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    monkeypatch.setattr(wizard, "open_preview", lambda path: True)
    return target


def answers(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(iterator))


def initial_prompts():
    # SI, owner, selected world map data, map 0, custom rectangle (one chunk),
    # classic, no IREG/lift/grid/advanced options.
    return ["2", "1", "1", "0", "2", "0", "0", "0", "0", "1", "n", "n", "n", "n"]


def test_bare_and_game_only_commands_open_wizard(monkeypatch):
    captured = []
    monkeypatch.setattr(wizard, "run_wizard", lambda args: captured.append(args) or 0)
    for argv in (["map-render"], ["map-render", "--game", "si"]):
        result = CliRunner().invoke(cli.u7_app, argv)
        assert result.exit_code == 0, result.output
    assert [args.game for args in captured] == ["bg", "si"]


def test_explicit_regions_remain_batch_and_interactive_keeps_defaults(monkeypatch):
    batch, guided = [], []
    monkeypatch.setattr(cli, "cmd_map_render", lambda args: batch.append(args) or 0)
    monkeypatch.setattr(wizard, "run_wizard", lambda args: guided.append(args) or 0)
    argv = ["map-render", "--game", "si", "--sc", "0x55", "--view", "flat", "--grid"]
    assert CliRunner().invoke(cli.u7_app, argv).exit_code == 0
    assert CliRunner().invoke(cli.u7_app, [*argv, "--interactive"]).exit_code == 0
    assert batch[0].superchunk == guided[0].superchunk == 85
    assert guided[0].view == "flat" and guided[0].grid
    result = CliRunner().invoke(cli.u7_app, ["map-render", "--output", "map.png"])
    assert result.exit_code == 1 and "Specify" in result.output


def test_cancel_after_reduced_preview_never_renders_full(world, monkeypatch, tmp_path):
    resolutions = []
    original = cli.cmd_map_render

    def render(args):
        resolutions.append(args.resolution)
        return original(args)

    monkeypatch.setattr(cli, "cmd_map_render", render)
    answers(monkeypatch, [*initial_prompts(), "q"])
    output = tmp_path / "never.png"
    assert wizard.run_wizard(options(output=str(output))) == 0
    assert resolutions == [0.2]
    assert not output.exists()


def test_acceptance_renders_full_only_after_output_confirmation(
    world, monkeypatch, tmp_path, capsys
):
    output = tmp_path / "approved.png"
    resolutions = []
    original = cli.cmd_map_render

    def render(args):
        assert not output.exists()
        resolutions.append(args.resolution)
        return original(args)

    monkeypatch.setattr(cli, "cmd_map_render", render)
    answers(monkeypatch, [*initial_prompts(), "y", str(output), "y"])
    assert wizard.run_wizard(options()) == 0
    assert resolutions == [0.2, 1.0]
    with Image.open(output) as image:
        assert image.size == (256, 256)
        assert image.getpixel((80, 80))[:3] == (255, 0, 0)
    text = capsys.readouterr().out
    assert "Is this the correct map?" in text
    assert "20% preview: 100%" in text and "Full render: 100%" in text


def test_declining_save_skips_full_render(world, monkeypatch, tmp_path):
    output = tmp_path / "declined.png"
    resolutions = []
    original = cli.cmd_map_render
    monkeypatch.setattr(
        cli,
        "cmd_map_render",
        lambda args: resolutions.append(args.resolution) or original(args),
    )
    answers(monkeypatch, [*initial_prompts(), "y", str(output), "n"])
    assert wizard.run_wizard(options()) == 0
    assert resolutions == [0.2] and not output.exists()


def test_reduced_render_allocates_only_reduced_canvas_and_retains_objects(
    world, monkeypatch
):
    sizes = []
    new = Image.new
    monkeypatch.setattr(
        Image,
        "new",
        lambda mode, size, *args, **kwargs: (
            sizes.append(size) or new(mode, size, *args, **kwargs)
        ),
    )
    renderer = U7MapRenderer(str(world.static), patch_dir=str(world.patch))
    palette = U7Palette.from_file(str(world.static / "palettes.flx"))
    events = []
    preview = renderer.render_region(
        0,
        0,
        31,
        31,
        palette,
        resolution=0.2,
        progress=lambda p, s: events.append((p, s)),
    )
    assert preview.size == (845, 845)
    assert (4224, 4224) not in sizes
    pixels = np.asarray(preview)
    assert np.any(pixels[:, :, 1] > 0)  # Fixed green sprite is in the preview.
    assert [p for p, _ in events] == sorted(p for p, _ in events)
    assert events[0][0] == 0 and events[-1][0] == 98
    hidden = renderer.render_region(0, 0, 0, 0, palette, resolution=0.2, max_lift=0)
    assert not np.any(np.asarray(hidden)[:, :, 1] > 0)
    excluded = renderer.render_region(
        0, 0, 0, 0, palette, resolution=0.2, exclude_shapes={150}
    )
    assert not np.any(np.asarray(excluded)[:, :, 1] > 0)


def test_reduced_terrain_has_no_rounding_gaps(world):
    renderer = U7MapRenderer(str(world.static), patch_dir=str(world.patch))
    palette = U7Palette.from_file(str(world.static / "palettes.flx"))
    preview = renderer.render_region(
        0, 0, 4, 0, palette, resolution=0.2, exclude_shapes={150}
    )
    pixels = np.asarray(preview)
    assert np.all(pixels[14:36, 14:140, 0] == 255)


@pytest.mark.parametrize("resolution", [0, -0.2, 1.1])
def test_invalid_resolution_is_rejected(world, resolution):
    with pytest.raises(ValueError, match="Resolution"):
        U7MapRenderer(str(world.static)).render_region(
            0, 0, 0, 0, U7Palette(), resolution=resolution
        )


def test_patch_map_shapes_metadata_and_palette_override_own_base(world):
    (world.patch / "u7map").write_bytes(bytes(144 * 256 * 2))
    (world.patch / "u7chunks").write_bytes(bytes([1, 0]) * 256)
    archive(world.patch / "shapes.vga", [b"", bytes([6]) * 64])
    (world.patch / "tfa.dat").write_bytes(bytes([0, 2, 0]) * 151)
    archive(world.patch / "u7ifix00", [])  # Explicit empty patch overrides IFIX.
    renderer = U7MapRenderer(str(world.static), patch_dir=str(world.patch))
    assert renderer.terrains[0][0] == (1, 0)
    assert renderer.shapes_vga.records[0] == bytes([5]) * 64
    assert renderer.shapes_vga.records[1] == bytes([6]) * 64
    assert renderer.tfa.get(0).shape_class == 2
    assert renderer._fixed_objects_for_superchunk(0) == []
    args = options(static=str(world.static), patch_dir=str(world.patch))
    archive(world.patch / "palettes.flx", [b""])
    assert wizard.resolve_palette(args) == world.static / "palettes.flx"
    archive(world.patch / "palettes.flx", [bytes([31]) * 768])
    assert wizard.resolve_palette(args) == world.patch / "palettes.flx"


def test_other_map_uses_matching_case_insensitive_base_and_patch(world):
    (world.static / "MAP04").mkdir()
    (world.static / "MAP04/u7map").write_bytes(bytes(144 * 256 * 2))
    (world.patch / "Map04").mkdir()
    archive(world.patch / "Map04/u7ifix00", [bytes([0x11, 0, 150, 0])])
    args = options(static=str(world.static), patch_dir=str(world.patch), map_num=4)
    wizard.validate_sources(args)
    renderer = U7MapRenderer(args.static, map_num=4, patch_dir=args.patch_dir)
    assert renderer.terrain_map[0][0] == 0
    assert renderer._fixed_objects_for_superchunk(0)[0].tx == 1
    args.map_num = 5
    with pytest.raises(ValueError, match="U7MAP not found for map 5"):
        wizard.validate_sources(args)


def test_separate_map_root_is_not_replaced_by_world_patch(world, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "u7map").write_bytes(bytes(144 * 256 * 2))
    (scratch / "u7chunks").write_bytes(bytes([1, 0]) * 256)
    (world.patch / "u7chunks").write_bytes(bytes([2, 0]) * 256)
    renderer = U7MapRenderer(
        str(world.static), patch_dir=str(world.patch), map_root=str(scratch)
    )
    assert renderer.terrains[0][0] == (1, 0)


def test_unknown_owner_palette_does_not_fall_back_to_retail(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No palette found for this world"):
        wizard.resolve_palette(options(static=str(empty)))


def test_world_switch_clears_previous_palette_map_and_save_data(world, monkeypatch):
    answers(monkeypatch, ["2", "1"])
    args = options(
        static="old-static",
        patch_dir="old-patch",
        map_root="old-map",
        map_num=4,
        palette="old-pal",
        gamedat="old-save",
        highlight_rects=["old-overlay"],
    )
    wizard._world(args, keep_supplied=False)
    assert args.static == args.base_static == str(world.static)
    assert args.patch_dir == str(world.patch)
    assert args.gamedat is args.palette is args.map_root is None
    assert args.map_num == 0 and args.highlight_rects == []


def test_plain_map_selector_discovers_hex_map_directories(world, monkeypatch):
    (world.patch / "MAP0A").mkdir()
    answers(monkeypatch, ["10"])
    assert select_map(None, [str(world.patch)]) == 10


def test_invalid_region_values_reprompt_without_clamping(monkeypatch):
    args = options()
    answers(monkeypatch, ["2", "192", "2", "3", "1", "4", "2", "5"])
    wizard._region(args)
    assert (args.chunk_x0, args.chunk_y0, args.chunk_x1, args.chunk_y1) == (2, 3, 4, 5)


def test_save_refuses_implicit_overwrite_and_non_png(tmp_path):
    preview, output = tmp_path / "preview.png", tmp_path / "map.png"
    preview.write_bytes(b"approved PNG")
    output.write_bytes(b"old PNG")
    with pytest.raises(FileExistsError):
        wizard.save_preview(preview, output)
    assert output.read_bytes() == b"old PNG"
    with pytest.raises(ValueError, match=".png"):
        wizard.save_preview(preview, tmp_path / "SHAPES.VGA", replace=True)
    wizard.save_preview(preview, output, replace=True)
    assert output.read_bytes() == preview.read_bytes()


def test_failed_replacement_preserves_previous_output(tmp_path, monkeypatch):
    preview, output = tmp_path / "preview.png", tmp_path / "map.png"
    preview.write_bytes(b"new PNG")
    output.write_bytes(b"old PNG")
    monkeypatch.setattr(
        wizard.shutil,
        "copyfile",
        lambda *args: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        wizard.save_preview(preview, output, replace=True)
    assert output.read_bytes() == b"old PNG"
    assert not list(tmp_path.glob(".titan-map-*"))


def test_reduced_overlays_and_grid_render_on_small_canvas(world):
    renderer = U7MapRenderer(str(world.static), patch_dir=str(world.patch))
    image = renderer.render_region(
        0,
        0,
        0,
        0,
        U7Palette(),
        resolution=0.2,
        grid=True,
        highlight_rects=[U7TileRectOverlay(0, 0, 15, 15, (0, 0, 255, 255), "area")],
    )
    assert image.size == (51, 51)
    assert np.any(np.asarray(image)[:, :, 2] > 0)


def test_save_retry_reuses_completed_full_render(world, monkeypatch, tmp_path):
    output = tmp_path / "retry.png"
    resolutions = []
    original_render = cli.cmd_map_render
    original_save = wizard.save_preview
    attempts = 0

    def save(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Output unavailable")
        original_save(*args, **kwargs)

    monkeypatch.setattr(
        cli,
        "cmd_map_render",
        lambda args: resolutions.append(args.resolution) or original_render(args),
    )
    monkeypatch.setattr(wizard, "save_preview", save)
    answers(
        monkeypatch, [*initial_prompts(), "y", str(output), "y", "r", str(output), "y"]
    )
    assert wizard.run_wizard(options()) == 0
    assert output.exists() and attempts == 2
    assert resolutions == [0.2, 1.0]


def test_exult_extended_tfa_is_not_parsed_as_retail_animation_tail(world):
    data = bytearray(3 * 1100)
    data[1024 * 3 : 1024 * 3 + 3] = bytes([0, 2, 0])
    (world.static / "TFA.DAT").unlink()
    (world.static / "tfa.dat").write_bytes(data)
    renderer = U7MapRenderer(str(world.static))
    assert renderer.tfa.get(1024).shape_class == 2
    assert renderer.tfa.get(0).anim_type == -1


def test_eof_cancels_cleanly_without_rendering(world, monkeypatch):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert wizard.run_wizard(options()) == 0


def test_ireg_never_falls_back_to_main_map_save_data(world, tmp_path):
    (world.static / "MAP04").mkdir()
    (world.static / "MAP04/u7map").write_bytes(bytes(144 * 256 * 2))
    gamedat = tmp_path / "gamedat"
    gamedat.mkdir()
    args = options(
        static=str(world.static),
        patch_dir=str(world.patch),
        map_num=4,
        gamedat=str(gamedat),
    )
    with pytest.raises(ValueError, match="GAMEDAT has no map04"):
        wizard.validate_sources(args)
    (gamedat / "MAP04").mkdir()
    wizard.validate_sources(args)
    assert args.gamedat == str(gamedat / "MAP04")
    # Validating an explicitly selected map folder is also supported.
    wizard.validate_sources(args)
    assert args.gamedat == str(gamedat / "MAP04")


def test_supplied_patch_defaults_keep_its_base_and_overrides(world, monkeypatch):
    # Supply the actual patch path, as accepted by the existing batch command.
    answers(monkeypatch, ["2", "1"])
    args = options(static=str(world.patch), palette="explicit.pal", map_num=4)
    target = wizard._world(args, keep_supplied=True)
    assert target.name == "Current supplied world"
    assert Path(args.static) == Path(args.base_static) == world.static
    assert args.patch_dir == str(world.patch)
    assert args.palette == "explicit.pal" and args.map_num == 4
