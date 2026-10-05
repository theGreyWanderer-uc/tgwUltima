"""Browser ownership, frame rendering, navigation and approved exports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from titan import _terminal_image as terminal
from titan import _wizard_ui as ui
from titan.u7 import shape_browser as browser
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import PaletteRecordEmptyError
from titan.u7.shape import U7Shape
from titan.u7.shape_animation import AnimationInfo, AniType, save_gif


def write_archive(path: Path, records: list[bytes], magic: int = 0xCC) -> None:
    archive = U7FlexArchive()
    archive.records, archive.magic2 = records, magic
    path.write_bytes(archive.to_bytes())


def shape_bytes(colours=(5, 6), transparent=False) -> bytes:
    shape = U7Shape()
    for colour in colours:
        frame = U7Shape.Frame()
        frame.width, frame.height = 3, 2
        frame.pixels = np.full((2, 3), colour, dtype=np.uint8)
        if transparent:
            frame.pixels[0, 0] = 255
        shape.frames.append(frame)
    return shape.to_bytes()


@pytest.fixture
def owner(tmp_path, monkeypatch):
    static, patch = tmp_path / "static", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    write_archive(
        static / "gumps.vga", [shape_bytes(transparent=True), b"", shape_bytes((7,))]
    )
    write_archive(patch / "GUMPS.VGA", [b"", shape_bytes((8,))], 0xCC01)
    write_archive(
        static / "shapes.vga", [bytes([255]) * 64, *([b""] * 149), shape_bytes((9,))]
    )
    write_archive(static / "text.flx", [b"ground", *([b""] * 149), b"a/chest//s\x00"])
    colours = bytearray(768)
    colours[5 * 3 : 5 * 3 + 3] = bytes([63, 0, 0])
    colours[6 * 3 : 6 * 3 + 3] = bytes([0, 63, 0])
    write_archive(static / "palettes.flx", [bytes(colours), bytes([20]) * 768])
    write_archive(patch / "PALETTES.FLX", [b"", bytes([30]) * 768])
    target = ArchiveTarget("Standalone SI", static, patch, standalone=True)
    monkeypatch.setattr(browser, "game_targets", lambda game: (target, []))
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    monkeypatch.setattr(browser, "terminal_image", lambda image, **kwargs: False)
    monkeypatch.setattr(browser, "open_preview", lambda path: True)
    return target


def library(owner, name="GUMPS.VGA", **kwargs):
    return browser.load_library(owner, "si", browser.owner_file(owner, name), **kwargs)


def answers(monkeypatch, values):
    pending = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(pending))


def test_combines_exult_patch_with_owner_base_and_preserves_sources(owner):
    sources = {
        p: p.read_bytes()
        for root in (owner.static, owner.patch)
        for p in root.iterdir()
    }
    lib = library(owner)
    assert lib.ids == [0, 1, 2]
    assert lib.archive.base_fill_count == 2
    assert lib.archive.selected.magic2 == 0xCC01
    assert lib.shape(0).frames[0].width == 3
    assert lib.shape(1).frames[0].pixels[0, 0] == 8
    assert lib.shape(2).frames[0].pixels[0, 0] == 7
    assert all(path.read_bytes() == content for path, content in sources.items())


def test_custom_file_outside_patch_does_not_inherit_a_foreign_base(owner, tmp_path):
    path = tmp_path / "elsewhere" / "GUMPS.VGA"
    path.parent.mkdir()
    write_archive(path, [shape_bytes((10,))])
    lib = browser.load_library(owner, "si", path)
    assert lib.ids == [0]
    assert lib.archive.base is None
    explicit = browser.load_library(
        owner, "si", path, base_archive=owner.static / "gumps.vga"
    )
    assert explicit.ids == [0, 2]


def test_automatic_palette_empty_patch_record_uses_same_owner_base(owner):
    lib = library(owner)
    assert lib.palette_path == owner.static / "palettes.flx"
    assert lib.palette.colors[5] == (255, 0, 0)
    alternate = library(owner, palette_index=1)
    assert alternate.palette_path == owner.patch / "PALETTES.FLX"
    with pytest.raises(PaletteRecordEmptyError):
        library(owner, palette_file=owner.patch / "PALETTES.FLX")


def test_missing_patch_palette_slot_inherits_and_corrupt_slot_is_reported(owner):
    patch = owner.patch / "PALETTES.FLX"
    write_archive(patch, [b""])
    lib = library(owner, palette_index=1)
    assert lib.palette_path == owner.static / "palettes.flx"
    write_archive(patch, [b"too short"])
    with pytest.raises(ValueError, match="too small"):
        library(owner)


def test_generic_slot_zero_is_rle_and_has_no_shapes_names_or_flags(owner):
    (owner.static / "TFA.DAT").write_bytes(bytes([4, 0, 128]) * 151)
    lib = library(owner)
    shape = lib.shape(0)
    assert not shape.frames[0].is_tile
    assert lib.name(0) == ""
    assert not lib.report(shape, 0).is_translucent
    assert lib.report(shape, 0).resolved_animation is None
    image = lib.images(shape, 0)[0]
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((1, 0)) == (255, 0, 0, 255)


def test_shapes_flats_remain_opaque_and_names_are_searchable(owner):
    lib = library(owner, "SHAPES.VGA")
    shape = lib.shape(0)
    assert shape.frames[0].is_tile
    assert lib.images(shape, 0)[0].getpixel((0, 0))[3] == 255
    indexed = lib.images(shape, 0, indexed=True)[0]
    assert "transparency" not in indexed.info
    assert indexed.getpixel((0, 0)) == 255
    assert browser.matching_shapes(lib, "CHEST") == [150]
    assert browser.matching_shapes(lib, "0x96") == [150]
    assert browser.matching_shapes(lib, "149") == []
    assert browser.matching_shapes(lib, "") == [0, 150]


def test_shapes_patch_typeflags_and_names_override_base(owner):
    (owner.static / "TFA.DAT").write_bytes(bytes(3 * 151))
    tfa = bytearray(3 * 151)
    tfa[450:453] = bytes([4, 0, 128])
    (owner.patch / "TFA.DAT").write_bytes(tfa)
    (owner.patch / "textmsg.txt").write_text(
        "%%section shapes\n0x96:Magic chest\n%%endsection\n"
    )
    lib = library(owner, "SHAPES.VGA")
    report = lib.report(lib.shape(150), 150)
    assert report.is_animated
    assert report.is_translucent
    assert lib.name(150) == "Magic chest"


def test_indexed_export_roundtrips_indices_transparency_and_order(
    owner, tmp_path, monkeypatch
):
    lib = library(owner)
    output = tmp_path / "frames"
    answers(monkeypatch, ["2", "1", str(output), "Y"])
    browser._png_export(lib, lib.shape(0), 0, 0)
    paths = sorted(output.glob("*.png"))
    assert [p.name for p in paths] == ["shape_0000_f0000.png", "shape_0000_f0001.png"]
    with Image.open(paths[0]) as image:
        assert image.mode == "P"
        assert image.getpixel((0, 0)) == 255
        assert image.getpixel((1, 0)) == 5
        assert image.info["transparency"] == 255
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0
    with Image.open(paths[1]) as image:
        assert image.getpixel((1, 0)) == 6


@pytest.mark.parametrize("decline", ["save", "overwrite"])
def test_export_decline_does_not_create_or_replace_files(
    owner, tmp_path, monkeypatch, decline
):
    lib = library(owner)
    output = tmp_path / "out"
    existing = output / "shape_0000_f0000.png"
    if decline == "overwrite":
        output.mkdir()
        existing.write_bytes(b"keep me")
    answers(
        monkeypatch,
        ["1", "2", str(output), *(["Y", "N"] if decline == "overwrite" else ["N"])],
    )
    browser._png_export(lib, lib.shape(0), 0, 0)
    assert (
        existing.read_bytes() == b"keep me"
        if decline == "overwrite"
        else not output.exists()
    )


def test_new_export_will_not_overwrite_a_file_appearing_after_confirmation(tmp_path):
    path = tmp_path / "out.png"
    path.write_bytes(b"other user's file")
    with pytest.raises(FileExistsError):
        browser.save_bytes(path, b"new pixels")
    assert path.read_bytes() == b"other user's file"
    browser.save_bytes(path, b"approved pixels", replace=True)
    assert path.read_bytes() == b"approved pixels"
    assert list(tmp_path.iterdir()) == [path]


def test_alignment_keeps_origins_stationary_with_different_frame_dimensions():
    shape = U7Shape()
    frames = []
    for width, height, x, y in [(3, 2, 1, 0), (5, 4, 3, 2)]:
        frame = U7Shape.Frame()
        frame.width, frame.height = width, height
        frame.set_hotspot_from_top_left(x, y)
        frame.pixels = np.full((height, width), 255, dtype=np.uint8)
        frame.pixels[y, x] = 5
        shape.frames.append(frame)
        image = Image.new("RGBA", (width, height))
        image.putpixel((x, y), (255, 0, 0, 255))
        frames.append(image)
    aligned = browser.aligned_frames(shape, frames)
    assert aligned[0].size == aligned[1].size == (5, 4)
    assert (
        aligned[0].getpixel((3, 2)) == aligned[1].getpixel((3, 2)) == (255, 0, 0, 255)
    )


def test_gif_preview_uses_every_generic_frame_and_preserves_transparency(
    owner, tmp_path
):
    lib = library(owner)
    shape = lib.shape(0)
    frames = browser.animation_frames(lib, shape, 0, 1, "F", 2)
    output = tmp_path / "preview.gif"
    save_gif(frames, str(output), duration_ms=200)
    with Image.open(output) as gif:
        assert gif.n_frames == 2
        assert gif.info["duration"] == 200
        assert gif.convert("RGBA").getpixel((0, 0))[3] == 0
        assert gif.convert("RGB").getpixel((1, 0)) == (255, 0, 0)
        gif.seek(1)
        assert gif.convert("RGB").getpixel((1, 0)) == (0, 255, 0)


def test_engine_animation_starts_at_zero_even_when_browsing_last_frame(
    owner, monkeypatch
):
    lib = library(owner)
    shape = lib.shape(0)
    report = lib.report(shape, 0)
    report.resolved_animation = AnimationInfo(AniType.TIMESYNCHED, 2)
    monkeypatch.setattr(lib, "report", lambda *_: report)
    frames = browser.animation_frames(lib, shape, 0, 1, "E", 3)
    assert [image.getpixel((1, 0))[:3] for image in frames] == [
        (255, 0, 0),
        (0, 255, 0),
        (255, 0, 0),
    ]


def test_palette_cycle_preview_uses_selected_timing(owner):
    write_archive(owner.patch / "GUMPS.VGA", [shape_bytes((224,))])
    lib = library(owner)
    calls = []
    original = lib.images

    def recording(shape, number, **kwargs):
        calls.append(kwargs.get("phase", 0))
        return original(shape, number, **kwargs)

    lib.images = recording
    browser.animation_frames(lib, lib.shape(0), 0, 0, "C", 3, duration_ms=250)
    assert calls == [0, 250, 500]


def test_frame_sheet_contains_current_page_and_handles_large_frames():
    images = [
        Image.new("RGBA", (320, 200), (number, 0, 0, 255)) for number in range(15)
    ]
    sheet = browser.frame_sheet(images, 12)
    assert sheet.size == (780, 230)
    assert sheet.getpixel((8, 28)) == (12, 0, 0)
    assert sheet.getpixel((268, 28)) == (13, 0, 0)


def test_viewer_current_frame_keeps_full_detail_and_transparency():
    image = Image.new("RGBA", (320, 200))
    image.putpixel((319, 199), (255, 0, 0, 255))
    preview = browser.frame_preview(image)
    assert preview.size == (960, 600)
    assert preview.getpixel((959, 599)) == (255, 0, 0)
    assert preview.getpixel((0, 0)) == (48, 48, 48)


def test_plain_navigation_frame_export_and_quit(owner, monkeypatch, tmp_path):
    output = tmp_path / "pngs"
    answers(
        monkeypatch, ["2", "1", "2", "S0", "F", "E", "1", "2", str(output), "Y", "Q"]
    )
    result = CliRunner().invoke(u7_app, ["shape-browse", "--game", "si"])
    assert result.exit_code == 0, result.output
    assert "frame 1/1" in result.output
    assert "Standalone SI" in result.output
    with Image.open(output / "shape_0000_f0001.png") as image:
        assert image.getpixel((1, 0)) == (0, 255, 0, 255)


def test_next_shape_navigation_skips_empty_and_inherits_base(owner, monkeypatch):
    answers(monkeypatch, ["2", "1", "2", "S1", "J", "Q"])
    result = CliRunner().invoke(u7_app, ["shape-browse"])
    assert result.exit_code == 0, result.output
    assert "Shape 1" in result.output and "Shape 2" in result.output
    assert "Source: base archive" in result.output


def test_questionary_uses_shared_menus_and_path_tab_hints(owner, monkeypatch, tmp_path):
    import questionary

    pending = iter(
        ["2", owner, "2", "S0", "E", "1", "1", str(tmp_path / "no-save"), False, "Q"]
    )
    prompts = []

    def factory(message, **kwargs):
        prompts.append((message, kwargs))

        class Prompt:
            def ask(self):
                return next(pending)

        return Prompt()

    for name in ("select", "confirm", "path", "text"):
        monkeypatch.setattr(questionary, name, factory)
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("fell back to plain input")
    )
    result = CliRunner().invoke(u7_app, ["shape-browse"])
    assert result.exit_code == 0, result.output
    assert any("Output directory (Tab:" in message for message, _ in prompts)
    assert any(message == "Choose game/world target:" for message, _ in prompts)
    browse = next(kwargs for message, kwargs in prompts if message == "Browse shape:")
    titles = {choice.value: choice.title for choice in browse["choices"]}
    assert titles["F"] == "[F] Next frame"
    assert titles["S"] == "[S] Choose another shape"
    assert titles["P"] == "[P] Play frames in terminal"
    assert not (tmp_path / "no-save").exists()


def test_cancel_and_malformed_shape_return_to_browser_without_writes(
    owner, monkeypatch
):
    write_archive(owner.patch / "GUMPS.VGA", [b"broken"])
    answers(monkeypatch, ["2", "1", "2", "S0", "Q", "Q"])
    result = CliRunner().invoke(u7_app, ["shape-browse"])
    assert result.exit_code == 0, result.output
    assert "ERROR:" in result.output


def test_change_world_resets_explicit_palette(owner, monkeypatch):
    answers(monkeypatch, ["2", "1", "2", "W", "1", "1", "2", "S0", "Q"])
    result = CliRunner().invoke(
        u7_app,
        [
            "shape-browse",
            "--shape",
            "0",
            "--palette-index",
            "1",
            "-p",
            str(owner.patch / "PALETTES.FLX"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "record 1" in result.output
    assert "record 0" in result.output


def test_menu_paging_and_name_search(owner, monkeypatch):
    lib = library(owner)
    lib.archive.effective.records = [shape_bytes((5,)) for _ in range(65)]
    answers(monkeypatch, ["N", "N", "S64"])
    assert browser.choose_shape(lib) == 64
    answers(monkeypatch, ["N", "B", "S0"])
    assert browser.choose_shape(lib) == 0
    lib = library(owner, "SHAPES.VGA")
    answers(monkeypatch, ["F", "chest", "S150"])
    assert browser.choose_shape(lib) == 150


def test_viewer_failure_reports_saved_preview_path(
    owner, monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(browser, "open_preview", lambda _: False)
    browser._view(tmp_path / "preview.png")
    assert "open the preview file manually" in capsys.readouterr().out


@pytest.mark.parametrize("save", [True, False])
def test_gif_workflow_reviews_before_saving(owner, monkeypatch, tmp_path, save):
    lib = library(owner)
    output = tmp_path / "approved.gif"
    previews = tmp_path / "previews"
    previews.mkdir()
    opened = []
    monkeypatch.setattr(
        browser, "open_preview", lambda path: opened.append(path) or True
    )
    answers(
        monkeypatch, ["F", "2", "200", *(["Y", str(output), "Y"] if save else ["N"])]
    )
    browser._animation(lib, lib.shape(0), 0, 0, previews)
    assert len(opened) == 1 and opened[0].is_file()
    assert output.exists() is save
    if save:
        assert output.read_bytes() == opened[0].read_bytes()


def test_missing_palette_can_be_selected_and_retry_keeps_archive(
    owner, monkeypatch, tmp_path
):
    explicit = tmp_path / "chosen.pal"
    explicit.write_bytes(
        U7FlexArchive.from_file(str(owner.static / "palettes.flx")).records[0]
    )
    (owner.static / "palettes.flx").unlink()
    (owner.patch / "PALETTES.FLX").unlink()
    answers(monkeypatch, ["2", "1", "2", "P", str(explicit), "0", "S0", "Q"])
    result = CliRunner().invoke(u7_app, ["shape-browse"])
    assert result.exit_code == 0, result.output
    assert "No populated palette found" in result.output
    assert f"Palette: {explicit}, record 0" in result.output


def test_inline_preview_uses_solid_cells_with_native_colours(monkeypatch):
    lines = []
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    monkeypatch.setattr(terminal.shutil, "get_terminal_size", lambda *_: (100, 30))
    image = Image.new("RGBA", (40, 2), (255, 0, 0, 255))
    ImageDraw.Draw(image).line((0, 1, 39, 1), fill=(0, 0, 255, 255))
    assert terminal.terminal_image(image)
    assert lines[0][1:] == [("bg:#ff0000", "  ")] * 40
    assert lines[1][1:] == [("bg:#0000ff", "  ")] * 40
    assert not any("\x1b" in value for line in lines for _, value in line)


def test_inline_preview_redirected_output_is_quiet(monkeypatch, capsys):
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: False)
    assert not terminal.terminal_image(Image.new("RGBA", (8, 8)))
    assert capsys.readouterr().out == ""


def test_inline_preview_bounds_large_image_and_composites_transparency(monkeypatch):
    lines = []
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(terminal.shutil, "get_terminal_size", lambda *_: (60, 20))
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    assert terminal.terminal_image(Image.new("RGBA", (320, 200)))
    assert len(lines) <= 12
    assert max(len(line) - 1 for line in lines) <= 56
    assert "#303030" in lines[0][1][0]


def test_inline_preview_reserves_space_for_browser_menu(monkeypatch):
    lines = []
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(terminal.shutil, "get_terminal_size", lambda *_: (80, 30))
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    assert terminal.terminal_image(Image.new("RGBA", (32, 32)), reserved_rows=20)
    assert len(lines) <= 10


def test_solid_preview_preserves_pixel_rows_and_transparency_without_padding():
    image = Image.new("RGBA", (3, 3), (255, 0, 0, 255))
    image.putpixel((1, 1), (0, 0, 0, 255))
    image.putpixel((1, 2), (255, 255, 255, 255))
    image.putpixel((0, 0), (255, 255, 255, 0))
    original = image.tobytes()
    # Exactly enough room for the source: no scaling, including its odd height.
    lines, reduced = terminal.image_lines(image, 10, 11)
    assert not reduced
    assert len(lines) == 3
    assert [line[1:] for line in lines] == [
        [("bg:#303030", "  "), ("bg:#ff0000", "  "), ("bg:#ff0000", "  ")],
        [("bg:#ff0000", "  "), ("bg:#000000", "  "), ("bg:#ff0000", "  ")],
        [("bg:#ff0000", "  "), ("bg:#ffffff", "  "), ("bg:#ff0000", "  ")],
    ]
    assert image.tobytes() == original


def test_solid_preview_fits_character_width_and_available_rows():
    lines, reduced = terminal.image_lines(Image.new("RGBA", (29, 26)), 18, 14)
    assert reduced
    assert len(lines) <= 6
    assert all(len("".join(text for _, text in line)) <= 16 for line in lines)
    assert all(text.isspace() for line in lines for _, text in line)


def test_npc_sized_preview_retains_native_pixels_when_terminal_has_room():
    lines, reduced = terminal.image_lines(
        Image.new("RGBA", (29, 26)), 100, 50, reserved_rows=20
    )
    assert not reduced
    assert len(lines) == 26
    assert all(len(line) - 1 == 29 for line in lines)


def test_live_frame_playback_keeps_palette_time_running_across_frame_loops(owner):
    colours = bytearray(768)
    for index in range(224, 232):
        colours[index * 3 : index * 3 + 3] = bytes([index - 220, 0, 0])
    write_archive(owner.static / "palettes.flx", [bytes(colours)])
    write_archive(owner.patch / "GUMPS.VGA", [shape_bytes((224, 224, 224))])
    lib = library(owner)
    image_at = browser.playback_provider(lib, lib.shape(0), 0, 0, "F")
    original, label = image_at(0, 0)
    looped, loop_label = image_at(3, 300)
    assert label == loop_label == "Frame 0/2"
    assert original.getpixel((0, 0)) != looped.getpixel((0, 0))
    assert image_at(24, 2400)[0].getpixel((0, 0)) == original.getpixel((0, 0))


def test_live_palette_mode_keeps_current_frame(owner):
    write_archive(owner.patch / "GUMPS.VGA", [shape_bytes((5, 6))])
    lib = library(owner)
    image_at = browser.playback_provider(lib, lib.shape(0), 0, 1, "C")
    image, label = image_at(100, 1000)
    assert label == "Frame 1/1 — palette cycling"
    assert image.getpixel((0, 0)) == (0, 255, 0, 255)


def test_live_playback_does_not_cycle_tfa_translucency_indices(owner):
    write_archive(owner.static / "shapes.vga", [b""] * 150 + [shape_bytes((238, 224))])
    tfa = bytearray(3 * 151)
    tfa[452] = 128
    (owner.static / "TFA.DAT").write_bytes(tfa)
    lib = library(owner, "SHAPES.VGA")
    decoded = lib.shape(150)
    report = lib.report(decoded, 150)
    assert report.cycle_frame_indices == [1]
    provider = browser.playback_provider(lib, decoded, 150, 0, "C")
    assert provider(0, 0)[0] is provider(20, 2000)[0]
    assert provider(0, 0)[0].getpixel((0, 0))[3] < 255


def test_actions_show_hotkeys_and_only_offer_cycles_on_affected_frame(
    owner, monkeypatch
):
    lib = library(owner)
    options = []

    def choice(prompt, choices, default, **kwargs):
        options.append(kwargs)
        return "Q"

    monkeypatch.setattr(ui, "choice", choice)
    assert browser._actions(lib, lib.shape(0), 0, 0) == "Q"
    assert options[0]["hotkeys"] is True
    assert options[0]["labels"]["F"] == "Next frame"
    assert options[0]["labels"]["P"] == "Play frames in terminal"
    assert options[0]["labels"]["S"] == "Choose another shape"
    assert "C" not in options[0]["labels"]
    write_archive(owner.patch / "GUMPS.VGA", [shape_bytes((224,))])
    lib = library(owner)
    browser._actions(lib, lib.shape(0), 0, 0)
    assert "C" in options[1]["labels"]


def test_playback_returns_to_same_shape_and_frame_without_saving(owner, monkeypatch):
    import questionary

    pending = iter(["2", owner, "2", "S0", "F", "P", "Q"])
    played = []

    def factory(message, **kwargs):
        class Prompt:
            def ask(self):
                return next(pending)

        return Prompt()

    for name in ("select", "confirm", "path", "text"):
        monkeypatch.setattr(questionary, name, factory)
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    monkeypatch.setattr(
        browser,
        "play_terminal",
        lambda provider, **kwargs: played.append(provider(0, 0)) or True,
    )
    result = CliRunner().invoke(u7_app, ["shape-browse"])
    assert result.exit_code == 0, result.output
    assert result.output.count("frame 1/1") == 2
    assert len(played) == 1


def test_plain_previous_and_number_keys_and_live_fallback(owner, monkeypatch):
    answers(monkeypatch, ["2", "1", "2", "S0", "B", "N", "0", "P", "Q"])
    result = CliRunner().invoke(u7_app, ["shape-browse"])
    assert result.exit_code == 0, result.output
    assert "frame 1/1" in result.output
    assert "Live playback needs an interactive terminal" in result.output
