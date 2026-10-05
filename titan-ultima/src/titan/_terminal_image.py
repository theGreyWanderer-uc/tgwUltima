"""Small Pillow images displayed through native coloured terminal output."""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, cast

from PIL import Image, ImageDraw

from titan import _wizard_ui as ui

if TYPE_CHECKING:
    from prompt_toolkit.application import Application
    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

FrameProvider = Callable[[int, int], tuple[Image.Image, str]]


def checkerboard(size: tuple[int, int], square: int = 4) -> Image.Image:
    image = Image.new("RGBA", size, (48, 48, 48, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], square):
        for x in range(0, size[0], square):
            if (x // square + y // square) % 2:
                draw.rectangle(
                    (x, y, x + square - 1, y + square - 1), fill=(72, 72, 72, 255)
                )
    return image


def image_lines(
    image: Image.Image, columns: int, rows: int, *, reserved_rows: int = 8
) -> tuple[list[list[tuple[str, str]]], bool]:
    """Paint square pixels with cell backgrounds, independent of font glyphs."""
    # Two character columns approximate one square pixel. Half-block glyphs can
    # leave seams or bleed the other pixel's colour with some terminal fonts.
    width, height = max(1, (columns - 4) // 2), max(1, min(32, rows - reserved_rows))
    enlarge = (
        max(image.size) <= 32
        and image.width * 2 <= width
        and image.height * 2 <= height
    )
    scale = min(
        2.0 if enlarge else 1.0,
        width / image.width,
        height / image.height,
    )
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    pixels = image.convert("RGBA").resize(size, Image.Resampling.NEAREST)
    background = checkerboard(size)
    background.alpha_composite(pixels)
    rgb = background.convert("RGB")
    lines = []
    for y in range(rgb.height):
        fragments = [("", "  ")]
        for x in range(rgb.width):
            colour = cast(tuple[int, int, int], rgb.getpixel((x, y)))
            bg = "#%02x%02x%02x" % colour
            fragments.append((f"bg:{bg}", "  "))
        lines.append(fragments)
    return lines, scale < 1


def terminal_image(image: Image.Image, *, reserved_rows: int = 8) -> bool:
    """Show solid background-colour pixels; redirected output stays quiet."""
    if not sys.stdout.isatty():
        return False
    columns, rows = shutil.get_terminal_size((80, 30))
    lines, reduced = image_lines(image, columns, rows, reserved_rows=reserved_rows)
    print(
        f"  Colour preview ({image.width}x{image.height}; checkerboard = transparent):"
    )
    for fragments in lines:
        ui.print_coloured(fragments)
    if reduced:
        print("  Reduced to fit; open the image viewer for full detail.")
    return True


@dataclass
class PlaybackClock:
    """Pause both frame time and palette time; speed changes keep the position."""

    duration_ms: int = 100
    paused: bool = False
    frame_time: float = 0.0
    palette_time: float = 0.0
    previous: float = field(default_factory=time.monotonic)

    def sample(self, now: float | None = None) -> tuple[int, int]:
        now = time.monotonic() if now is None else now
        elapsed = max(0.0, now - self.previous) * 1000
        self.previous = now
        if not self.paused:
            self.frame_time += elapsed / self.duration_ms
            # One speed adjustment applies equally to frames and colour cycling.
            self.palette_time += elapsed * 100 / self.duration_ms
        return int(self.frame_time), int(self.palette_time)

    def toggle_pause(self) -> None:
        self.sample()
        self.paused = not self.paused

    def speed(self, faster: bool) -> None:
        self.sample()
        self.duration_ms = max(
            20, min(2000, self.duration_ms // 2 if faster else self.duration_ms * 2)
        )


def playback_application(
    image_at: FrameProvider,
    *,
    title: str = "Shape playback",
    duration_ms: int = 100,
    input: Input | None = None,
    output: Output | None = None,
) -> Application[bool]:
    """Build a repainting player; its input/output can also be exercised headlessly."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.output import ColorDepth

    clock = PlaybackClock(duration_ms=duration_ms)
    bindings = KeyBindings()

    @bindings.add("q")
    @bindings.add("Q")
    @bindings.add("escape")
    @bindings.add("enter")
    @bindings.add("c-c")
    def stop(event):
        event.app.exit(result=True)

    @bindings.add(" ")
    def pause(event):
        clock.toggle_pause()

    @bindings.add("+")
    @bindings.add("=")
    def faster(event):
        clock.speed(True)

    @bindings.add("-")
    def slower(event):
        clock.speed(False)

    cached: tuple[Image.Image, int, int, list[list[tuple[str, str]]]] | None = None

    def content() -> FormattedText:
        nonlocal cached
        step, phase = clock.sample()
        image, label = image_at(step, phase)
        size = application.output.get_size()
        if (
            cached is None
            or cached[0] is not image
            or cached[1:3] != (size.columns, size.rows)
        ):
            lines, _ = image_lines(image, size.columns, size.rows, reserved_rows=6)
            cached = (image, size.columns, size.rows, lines)
        fragments = [("bold", f"{title} — {label}\n")]
        for line in cached[3]:
            fragments.extend(line)
            fragments.append(("", "\n"))
        status = "Paused" if clock.paused else "Playing"
        fragments.append(
            (
                "",
                f"{status}; {clock.duration_ms} ms/step. Space: pause/resume  +/-: speed  Q/Esc: back",
            )
        )
        return FormattedText(fragments)

    application: Application[bool] = Application(
        layout=Layout(
            Window(
                FormattedTextControl(content, focusable=True, show_cursor=False),
                wrap_lines=False,
            )
        ),
        key_bindings=bindings,
        full_screen=False,
        erase_when_done=True,
        refresh_interval=0.02,
        color_depth=ColorDepth.TRUE_COLOR,
        input=input,
        output=output,
    )
    # Start timing when rendering starts, rather than when the object is built.
    application.pre_run_callables.append(
        lambda: setattr(clock, "previous", time.monotonic())
    )
    return application


def play_terminal(image_at: FrameProvider, *, title: str = "Shape playback") -> bool:
    """Play in place on Windows/Linux and return to the caller when stopped."""
    if not ui.menus_enabled():
        return False
    try:
        return playback_application(image_at, title=title).run()
    except (KeyboardInterrupt, EOFError):
        return True
