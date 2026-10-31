"""U8 solid preview resolution, font-independent colours and resize-aware playback."""

from __future__ import annotations

import pytest
from PIL import Image
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from titan import _terminal_image as terminal
from titan import _wizard_ui as ui
from titan.u8 import npc_browser_ui, shape_browser_ui
from titan.u8.npc_browser import load_u8_npc_session
from titan.u8.shape_browser import load_u8_shape_library
from tests.test_u8_npc_animation_report import case as case
from tests.test_u8_shape_browser import owner as owner


def unpack_solid_pixels(lines: list[list[tuple[str, str]]]) -> Image.Image:
    """Reconstruct background pixels and reject glyphs that can cause font tearing."""
    result = Image.new("RGB", (len(lines[0]) - 1, len(lines)))
    for y, line in enumerate(lines):
        for x, (style, text) in enumerate(line[1:]):
            assert text == "  "
            assert style.startswith("bg:") and "fg:" not in style
            result.putpixel((x, y), tuple(bytes.fromhex(style.removeprefix("bg:#"))))
    return result


@pytest.mark.parametrize("size", [(78, 54), (92, 55), (128, 102)])
def test_solid_native_preview_preserves_every_pixel_of_larger_u8_images(size):
    image = Image.new("RGBA", size)
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256, 255))
    original = image.tobytes()
    lines, reduced = terminal.image_lines(
        image, size[0] * 2 + 4, size[1] + 8, pixel_mode="solid-native"
    )
    assert not reduced
    assert len(lines) == size[1]
    reconstructed = unpack_solid_pixels(lines)
    assert reconstructed.tobytes() == image.convert("RGB").tobytes()
    assert image.tobytes() == original


def test_solid_native_preview_composites_alpha_and_preserves_an_odd_height():
    image = Image.new("RGBA", (5, 3), (255, 0, 0, 255))
    image.putpixel((0, 0), (0, 255, 0, 0))
    image.putpixel((0, 1), (0, 0, 255, 128))
    lines, reduced = terminal.image_lines(image, 14, 11, pixel_mode="solid-native")
    expected = terminal.checkerboard((5, 3))
    expected.alpha_composite(image)
    assert not reduced
    assert len(lines) == 3
    assert unpack_solid_pixels(lines).tobytes() == expected.convert("RGB").tobytes()


def test_static_u8_preview_keeps_rows_in_scrollback_and_reports_actual_resolution(
    monkeypatch, capsys
):
    lines = []
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(terminal.shutil, "get_terminal_size", lambda *_: (260, 30))
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    image = Image.new("RGBA", (128, 102), (128, 0, 0, 255))
    assert terminal.terminal_image(image, reserved_rows=18, pixel_mode="solid-native")
    assert len(lines) == 102
    assert "128x102 source; 128x102 rendered" in capsys.readouterr().out
    assert unpack_solid_pixels(lines).tobytes() == image.convert("RGB").tobytes()


def test_narrow_preview_reports_width_reduction(monkeypatch, capsys):
    lines = []
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(terminal.shutil, "get_terminal_size", lambda *_: (132, 30))
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    image = Image.new("RGBA", (128, 102), (128, 0, 0, 255))
    assert terminal.terminal_image(image, reserved_rows=18, pixel_mode="solid-native")
    caption = capsys.readouterr().out
    assert "128x102 source; 64x51 rendered" in caption
    assert "widen the terminal" in caption
    assert len(lines) == 51
    assert all(len("".join(text for _, text in line)) <= 132 for line in lines)


@pytest.mark.parametrize("columns,rows", [(1, 1), (132, 20), (260, 120)])
def test_solid_native_playback_fits_actual_window_without_a_32_pixel_row_limit(
    columns, rows
):
    image = Image.new("RGBA", (128, 102))
    lines, reduced = terminal.image_lines(
        image, columns, rows, reserved_rows=6, pixel_mode="solid-native"
    )
    assert len(lines) <= max(1, rows - 6)
    assert len(lines[0]) - 1 <= max(1, (columns - 4) // 2)
    if (columns, rows) == (260, 120):
        assert not reduced
        assert len(lines) == 102


def test_solid_native_player_rebuilds_pixels_and_resolution_label_on_resize():
    class ResizableOutput(DummyOutput):
        columns = 260
        rows = 108

        def get_size(self):
            from prompt_toolkit.data_structures import Size

            return Size(rows=self.rows, columns=self.columns)

    output = ResizableOutput()
    image = Image.new("RGBA", (128, 102), (255, 0, 0, 255))
    image.putpixel((0, 1), (0, 255, 0, 255))
    with create_pipe_input() as pipe:
        app = terminal.playback_application(
            lambda *_: (image, "Frame 0"),
            input=pipe,
            output=output,
            pixel_mode="solid-native",
        )
        fragments = app.layout.current_control.text()
        assert ("bg:#ff0000", "  ") in fragments
        assert ("bg:#00ff00", "  ") in fragments
        assert all("▀" not in text and "fg:" not in style for style, text in fragments)
        assert "128x102 rendered (native pixels)" in "".join(
            text for _, text in fragments
        )
        output.columns, output.rows = 132, 60
        fragments = app.layout.current_control.text()
        assert "64x51 rendered (reduced to fit" in "".join(
            text for _, text in fragments
        )
        pipe.send_text("q")
        assert app.run() is True


def test_redirected_solid_native_preview_is_quiet(monkeypatch, capsys):
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: False)
    assert not terminal.terminal_image(
        Image.new("RGBA", (128, 102)), pixel_mode="solid-native"
    )
    assert capsys.readouterr().out == ""


def test_u8_shape_menu_uses_detailed_pixels_for_static_and_live_previews(
    owner, tmp_path, monkeypatch
):
    frames, players = [], []
    choices = iter(["P", "Q"])
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    monkeypatch.setattr(shape_browser_ui, "_menu", lambda *args: next(choices))
    monkeypatch.setattr(
        shape_browser_ui,
        "terminal_image",
        lambda image, **kwargs: frames.append(kwargs),
    )
    monkeypatch.setattr(
        shape_browser_ui,
        "play_terminal",
        lambda provider, **kwargs: players.append(kwargs),
    )
    library = load_u8_shape_library(owner / "u8shapes.flx")
    shape_browser_ui._browse_library(
        library,
        shape=1,
        frame=0,
        action=0,
        direction=0,
        overlay=None,
        output=tmp_path,
        previews=tmp_path,
    )
    assert frames and players
    assert all(
        options["pixel_mode"] == "solid-native" for options in [*frames, *players]
    )
    assert all(options["max_width_fraction"] == 1.0 for options in [*frames, *players])


def test_u8_npc_preview_uses_detailed_pixels_and_keeps_native_item_flip(
    case, monkeypatch
):
    static, gamedat = case
    library = load_u8_shape_library(static / "U8SHAPES.FLX")
    session = load_u8_npc_session(gamedat, library)
    rendered = []
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    monkeypatch.setattr(
        npc_browser_ui,
        "terminal_image",
        lambda image, **kwargs: rendered.append((image, kwargs)),
    )
    state = dict(session.states[1], item_status=0x20)
    npc_browser_ui.preview_u8_npc_sprite(session, state)
    image, options = rendered[0]
    expected = library.image(state["item_shape"], state["item_frame"]).transpose(
        Image.Transpose.FLIP_LEFT_RIGHT
    )
    assert image.tobytes() == expected.tobytes()
    assert options["pixel_mode"] == "solid-native"
    assert options["max_width_fraction"] == 1.0


def test_terminal_width_cap_scales_large_images_and_does_not_enlarge_small_ones(
    monkeypatch, capsys
):
    lines = []
    monkeypatch.setattr(terminal.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(terminal.shutil, "get_terminal_size", lambda *_: (260, 30))
    monkeypatch.setattr(ui, "print_coloured", lines.append)
    image = Image.new("RGBA", (128, 102), (128, 0, 0, 255))
    original = image.tobytes()
    terminal.terminal_image(image, pixel_mode="solid-native", max_width_fraction=0.5)
    assert "128x102 source; 63x50 rendered" in capsys.readouterr().out
    assert len(lines) == 50
    assert all(len("".join(text for _, text in line)) <= 130 for line in lines)
    assert all(text.isspace() for line in lines for _, text in line)
    assert image.tobytes() == original
    lines.clear()
    terminal.terminal_image(
        Image.new("RGBA", (8, 6)), pixel_mode="solid-native", max_width_fraction=0.5
    )
    assert len(lines) == 6
    assert len(lines[0]) - 1 == 8


def test_terminal_width_cap_player_updates_its_limit_on_resize():
    class ResizableOutput(DummyOutput):
        columns = 260

        def get_size(self):
            from prompt_toolkit.data_structures import Size

            return Size(rows=120, columns=self.columns)

    output = ResizableOutput()
    image = Image.new("RGBA", (128, 102))
    with create_pipe_input() as pipe:
        app = terminal.playback_application(
            lambda *_: (image, "Frame 0"),
            input=pipe,
            output=output,
            pixel_mode="solid-native",
            max_width_fraction=0.5,
        )
        text = "".join(value for _, value in app.layout.current_control.text())
        assert "63x50 rendered" in text
        output.columns = 132
        text = "".join(value for _, value in app.layout.current_control.text())
        assert "31x25 rendered" in text
        pipe.send_text("q")
        assert app.run() is True
