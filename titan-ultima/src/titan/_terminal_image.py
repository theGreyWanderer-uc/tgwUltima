"""Small Pillow images displayed through native coloured terminal output."""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal, cast

from PIL import Image, ImageDraw

from titan import _wizard_ui as ui

if TYPE_CHECKING:
    from prompt_toolkit.application import Application
    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

FrameProvider = Callable[[int, int], tuple[Image.Image, str]]
TerminalPixelMode = Literal["solid", "solid-native"]


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


def terminal_image_size(
    image: Image.Image,
    columns: int,
    rows: int,
    *,
    reserved_rows: int = 8,
    pixel_mode: TerminalPixelMode = "solid",
    fit_height: bool = True,
    max_width_fraction: float = 1.0,
) -> tuple[int, int]:
    """Fit solid pixels within a fraction of terminal width; never stretch the image."""
    if not 0 < max_width_fraction <= 1:
        raise ValueError(
            "Terminal preview width fraction must be greater than 0 and at most 1"
        )
    # Two blank character cells approximate a square pixel. Background colours
    # fill the cells without font-dependent half-block edges or foreground bleed.
    column_limit = max(1, int(columns * max_width_fraction))
    width = max(1, (column_limit - 4) // 2)
    height = max(1, rows - reserved_rows) if fit_height else image.height
    if pixel_mode == "solid":
        # Keep the established U7 preview size and small-sprite enlargement.
        height = min(32, height)
    enlarge = (
        pixel_mode == "solid"
        and max(image.size) <= 32
        and image.width * 2 <= width
        and image.height * 2 <= height
    )
    scale = min(
        2.0 if enlarge else 1.0,
        width / image.width,
        height / image.height,
    )
    return (max(1, round(image.width * scale)), max(1, round(image.height * scale)))


def image_lines(
    image: Image.Image,
    columns: int,
    rows: int,
    *,
    reserved_rows: int = 8,
    pixel_mode: TerminalPixelMode = "solid",
    fit_height: bool = True,
    max_width_fraction: float = 1.0,
) -> tuple[list[list[tuple[str, str]]], bool]:
    """Render pixels exclusively with blank background cells, preserving RGBA colours."""
    size = terminal_image_size(
        image,
        columns,
        rows,
        reserved_rows=reserved_rows,
        pixel_mode=pixel_mode,
        fit_height=fit_height,
        max_width_fraction=max_width_fraction,
    )
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
    return lines, size[0] < image.width or size[1] < image.height


def terminal_image(
    image: Image.Image,
    *,
    reserved_rows: int = 8,
    pixel_mode: TerminalPixelMode = "solid",
    max_width_fraction: float = 1.0,
) -> bool:
    """Show a colour preview; native mode uses scrollback instead of losing rows."""
    if not sys.stdout.isatty():
        return False
    columns, rows = shutil.get_terminal_size((80, 30))
    fit_height = pixel_mode != "solid-native"
    size = terminal_image_size(
        image,
        columns,
        rows,
        reserved_rows=reserved_rows,
        pixel_mode=pixel_mode,
        fit_height=fit_height,
        max_width_fraction=max_width_fraction,
    )
    lines, reduced = image_lines(
        image,
        columns,
        rows,
        reserved_rows=reserved_rows,
        pixel_mode=pixel_mode,
        fit_height=fit_height,
        max_width_fraction=max_width_fraction,
    )
    resolution = (
        f"{image.width}x{image.height} source; {size[0]}x{size[1]} rendered"
        if pixel_mode == "solid-native"
        else f"{image.width}x{image.height}"
    )
    print(f"  Colour preview ({resolution}; checkerboard = transparent):")
    for fragments in lines:
        ui.print_coloured(fragments)
    if reduced:
        print(
            "  Reduced to fit; widen the terminal or open the image viewer for full detail."
        )
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
    pixel_mode: TerminalPixelMode = "solid",
    max_width_fraction: float = 1.0,
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
            lines, _ = image_lines(
                image,
                size.columns,
                size.rows,
                reserved_rows=6,
                pixel_mode=pixel_mode,
                max_width_fraction=max_width_fraction,
            )
            cached = (image, size.columns, size.rows, lines)
        fragments = [("bold", f"{title} — {label}\n")]
        if pixel_mode == "solid-native":
            width, height = terminal_image_size(
                image,
                size.columns,
                size.rows,
                reserved_rows=6,
                pixel_mode=pixel_mode,
                max_width_fraction=max_width_fraction,
            )
            detail = (
                "native pixels"
                if (width, height) == image.size
                else "reduced to fit; enlarge terminal for full detail"
            )
            fragments.append(
                (
                    "",
                    f"{image.width}x{image.height} source; {width}x{height} rendered ({detail})\n",
                )
            )
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


def play_terminal(
    image_at: FrameProvider,
    *,
    title: str = "Shape playback",
    pixel_mode: TerminalPixelMode = "solid",
    max_width_fraction: float = 1.0,
) -> bool:
    """Play in place on Windows/Linux and return to the caller when stopped."""
    if not ui.menus_enabled():
        return False
    try:
        return playback_application(
            image_at,
            title=title,
            pixel_mode=pixel_mode,
            max_width_fraction=max_width_fraction,
        ).run()
    except (KeyboardInterrupt, EOFError):
        return True
