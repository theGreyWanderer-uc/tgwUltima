"""Exercise the real terminal player without opening a desktop image viewer."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from titan import _terminal_image as terminal
from titan import _wizard_ui as ui


def test_clock_pauses_frames_and_palette_and_speed_changes_keep_position(monkeypatch):
    clock = terminal.PlaybackClock(previous=0)
    assert clock.sample(0.25) == (2, 250)
    monkeypatch.setattr(terminal.time, "monotonic", lambda: 0.25)
    clock.toggle_pause()
    assert clock.sample(0.75) == (2, 250)
    monkeypatch.setattr(terminal.time, "monotonic", lambda: 0.75)
    clock.speed(True)
    assert clock.duration_ms == 50
    clock.toggle_pause()
    assert clock.sample(1.0) == (7, 750)
    monkeypatch.setattr(terminal.time, "monotonic", lambda: 1.0)
    clock.speed(False)
    assert clock.sample(1.25) == (10, 1000)


def test_clock_speed_bounds_and_paused_changes(monkeypatch):
    clock = terminal.PlaybackClock(previous=0, paused=True)
    monkeypatch.setattr(terminal.time, "monotonic", lambda: 0)
    for _ in range(10):
        clock.speed(True)
    assert clock.duration_ms == 20
    for _ in range(10):
        clock.speed(False)
    assert clock.duration_ms == 2000
    assert clock.sample(10) == (0, 0)


@pytest.mark.parametrize("key", ["q", "Q", "\r", "\x03", "\x1b"])
def test_real_player_stop_keys_return_and_erase_player(key):
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    with create_pipe_input() as pipe:
        app = terminal.playback_application(
            lambda step, phase: (image, f"Frame {step}"),
            input=pipe,
            output=DummyOutput(),
        )
        pipe.send_text(key)
        assert app.run() is True
        assert app.erase_when_done
        assert not app.full_screen


def test_player_repaints_colours_pauses_resumes_and_changes_speed(monkeypatch):
    # Playback time comes from a fake clock that only moves when the script
    # says so, and each key is sent once the previous one is visible on
    # screen, so the result does not depend on how fast the machine renders.
    now = [0.0]
    monkeypatch.setattr(terminal, "time", SimpleNamespace(monotonic=lambda: now[0]))
    with create_pipe_input() as pipe:
        frames = [
            Image.new("RGBA", (8, 8), colour)
            for colour in [(255, 0, 0, 255), (0, 0, 255, 255)]
        ]
        texts = []
        app = terminal.playback_application(
            lambda step, phase: (frames[step % 2], f"Frame {step % 2}"),
            input=pipe,
            output=DummyOutput(),
            duration_ms=20,
        )
        control = app.layout.current_control

        def advance(seconds):
            now[0] += seconds

        # (condition on the rendered text, action once it is seen)
        script = [
            (lambda t: "Playing" in t and "Frame 0" in t, lambda: advance(0.025)),
            (lambda t: "Playing" in t and "Frame 1" in t, lambda: pipe.send_text(" ")),
            # Time passing while paused must not move the frame.
            (lambda t: "Paused" in t, lambda: (advance(0.5), pipe.send_text("-"))),
            (lambda t: "Paused" in t and "40 ms/step" in t, lambda: pipe.send_text(" +")),
            (lambda t: "Playing" in t and "20 ms/step" in t, lambda: pipe.send_text("q")),
        ]

        def after_render(application):
            fragments = control.text()
            text = "".join(value for _, value in fragments)
            texts.append((text, fragments))
            if script and script[0][0](text):
                script.pop(0)[1]()

        app.after_render += after_render

        async def watchdog():
            await asyncio.sleep(10)
            if app.is_running:
                app.exit(result=False)

        assert app.run(pre_run=lambda: app.create_background_task(watchdog()))
        assert not script, f"player stalled before step {5 - len(script)}"
        playing_labels = {
            text.split("\n", 1)[0] for text, _ in texts if "Playing" in text
        }
        assert len(playing_labels) == 2
        paused_labels = {
            text.split("\n", 1)[0] for text, _ in texts if "Paused" in text
        }
        assert paused_labels == {"Shape playback — Frame 1"}
        assert any(
            "bg:#ff0000" in style for _, fragments in texts for style, _ in fragments
        )
        assert any(
            "bg:#0000ff" in style for _, fragments in texts for style, _ in fragments
        )


def test_player_redirected_output_does_not_start_or_render(monkeypatch):
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    assert (
        terminal.play_terminal(
            lambda *_: pytest.fail("rendered in a redirected terminal")
        )
        is False
    )


def test_player_resize_rebuilds_fitted_artwork(monkeypatch):
    class ResizableOutput(DummyOutput):
        columns = 80

        def get_size(self):
            from prompt_toolkit.data_structures import Size

            return Size(rows=24, columns=self.columns)

    output = ResizableOutput()
    image = Image.new("RGBA", (100, 100))
    with create_pipe_input() as pipe:
        app = terminal.playback_application(
            lambda *_: (image, "Frame 0"), input=pipe, output=output
        )
        control = app.layout.current_control
        before = control.text()
        output.columns = 15
        after = control.text()
        assert sum(
            len(value) for style, value in after if style.startswith("bg:")
        ) < sum(len(value) for style, value in before if style.startswith("bg:"))


def test_live_preview_uses_same_pixel_colours_as_static_preview():
    image = Image.new("RGBA", (33, 2), (255, 0, 0, 255))
    image.putpixel((0, 1), (0, 255, 0, 255))
    with create_pipe_input() as pipe:
        app = terminal.playback_application(
            lambda *_: (image, "Frame 0"), input=pipe, output=DummyOutput()
        )
        text = app.layout.current_control.text()
    rows, reduced = terminal.image_lines(image, 80, 40, reserved_rows=6)
    assert not reduced
    assert all(fragment in text for row in rows for fragment in row)
    assert rows[0][1] == ("bg:#ff0000", "  ")
    assert rows[1][1] == ("bg:#00ff00", "  ")
