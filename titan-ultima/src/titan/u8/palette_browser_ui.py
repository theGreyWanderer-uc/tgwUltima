"""Interactive Pagan palette menus using Titan's shared desktop controls."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan._palette_browser_ui import show_palette_colour_grid
from titan.fonts.palette import get_gradient_preset, list_gradient_presets
from titan.palette import U8Palette
from titan.u8.palette_browser import (
    U8_PALETTE_BROWSER_OUTPUT,
    U8_PALETTE_EFFECTS,
    U8PaletteSource,
    export_u8_palette_bundle,
    nearest_u8_palette_indices,
    next_u8_palette_export,
    resolve_u8_palette_source,
    u8_palette_sheet,
)
from titan.u8.shape_browser_ui import choose_u8_shape_target


def _menu(message: str, labels: dict[str, str], default: str) -> str:
    ui.legacy_menu(message, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ", list(labels), default, labels=labels, message=message, hotkeys=True
    )


def _integer(message: str, default: int, maximum: int) -> int:
    while True:
        raw = ui.text(f"  {message} [{default}]: ", str(default)).strip() or str(
            default
        )
        try:
            value = int(raw, 16 if raw.casefold().startswith("0x") else 10)
            if 0 <= value <= maximum:
                return value
        except ValueError:
            pass
        print(f"  Enter 0-{maximum}, in decimal or 0x hexadecimal.")


def _path(default: str = "") -> Path:
    return Path(ui.path("  U8 palette file: ", default).strip().strip('"')).expanduser()


def show_u8_palette_grid(palette: U8Palette, start: int = 0, count: int = 64) -> None:
    show_palette_colour_grid(palette.colors, start, count)


def _hex_rgb(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value.strip()):
        raise ValueError("Enter an RGB hex colour, such as #6f263d")
    raw = value.strip().lstrip("#")
    return int(raw[:2], 16), int(raw[2:4], 16), int(raw[4:], 16)


def _matches(palette: U8Palette) -> None:
    rgb = _hex_rgb(ui.text("  RGB hex colour: "))
    for index in nearest_u8_palette_indices(palette, rgb):
        matched = palette.colors[index]
        colour = "#{:02x}{:02x}{:02x}".format(*matched)
        ui.print_coloured(
            [(f"bg:{colour}", "    "), ("", f"  {index:03d}: {colour}; RGB {matched}")]
        )
    print("  Sorted by RGB distance; index 255 is excluded.")


def _gradient(palette: U8Palette) -> None:
    presets = list_gradient_presets()
    labels = {
        str(i + 1): get_gradient_preset(key).name for i, key in enumerate(presets)
    }
    labels.update({"C": "Custom RGB hex stops", "Q": "Back"})
    choice = _menu("Match a gradient to the current U8 effect:", labels, "1")
    if choice == "Q":
        return
    stops = (
        re.split(r"[\s,;]+", ui.text("  1-16 RGB hex stops: ").strip())
        if choice == "C"
        else get_gradient_preset(presets[int(choice) - 1]).colors
    )
    if not 1 <= len(stops) <= 16:
        raise ValueError("Enter 1-16 RGB stops")
    colours = [_hex_rgb(stop) for stop in stops]
    steps = _integer("Gradient steps (1-64; 0 returns)", 6, 64)
    if steps == 0:
        return
    indices = []
    for step in range(steps):
        position = step * (len(colours) - 1) / max(1, steps - 1)
        lo, hi = int(position), min(int(position) + 1, len(colours) - 1)
        fraction = position - lo
        values = [
            round(a + fraction * (b - a)) for a, b in zip(colours[lo], colours[hi])
        ]
        rgb = (values[0], values[1], values[2])
        indices.append(nearest_u8_palette_indices(palette, rgb, 1)[0])
    print("  Nearest RGB indices: " + ", ".join(map(str, indices)))
    print(
        "  RGB matching excludes sprite transparency 255; repeated shades are possible."
    )
    fragments = [("", "  ")]
    for index in indices:
        colour = "#{:02x}{:02x}{:02x}".format(*palette.colors[index])
        fragments.append((f"bg:{colour}", "    "))
    ui.print_coloured(fragments)


def run_u8_palette_browser(
    source: Path | None = None,
    *,
    game_dir: Path | None = None,
    index: int = 0,
    effect: int = 0,
    output: Path = U8_PALETTE_BROWSER_OUTPUT,
    export: bool = False,
) -> int:
    """Inspect one native palette, retaining its selected owner on source changes."""
    print("Titan U8 Palette Browser")
    if not 0 <= index <= 255 or not 0 <= effect <= 7:
        print("  ERROR: index must be 0-255 and effect 0-7")
        return 1
    try:
        protected = (game_dir,) if game_dir else ()
        if source is None:
            target = choose_u8_shape_target(game_dir)
            if target is None:
                return 0
            source = resolve_u8_palette_source(target.static)
            protected = (*protected, target.static)
        loaded = U8PaletteSource.load(source, protected=protected)
        if export:
            report = export_u8_palette_bundle(
                loaded, next_u8_palette_export(loaded, output, effect), effect
            )
            print(
                f"  Exported 256 colours, eight effect sheets and original palette: {report}"
            )
            return 0
        page = index // 64
        with tempfile.TemporaryDirectory(prefix="titan-u8-palette-") as preview_dir:
            while True:
                palette = loaded.palette(effect)
                print(
                    f"\nU8 {loaded.path}; {U8_PALETTE_EFFECTS[effect]}; indices {page * 64}-{page * 64 + 63}"
                )
                show_u8_palette_grid(palette, page * 64)
                action = _menu(
                    "Palette:",
                    {
                        "N": "Next colour page",
                        "B": "Previous colour page",
                        "I": "Inspect colour index",
                        "V": "Show all 256 colours",
                        "P": "Preview numbered sheet in image viewer",
                        "C": "Choose U8 palette effect",
                        "F": "Find nearest RGB colour",
                        "G": "Match RGB gradient",
                        "U": "Source and format details",
                        "E": "Export HTML + CSV + JSON + PNG + original PAL",
                        "A": "Choose another palette file",
                        "W": "Change U8 data source",
                        "Q": "Quit",
                    },
                    "I",
                )
                try:
                    if action == "Q":
                        return 0
                    if action == "N":
                        page = (page + 1) % 4
                    elif action == "B":
                        page = (page - 1) % 4
                    elif action == "I":
                        index = _integer("Colour index", index, 255)
                        page = index // 64
                        print(json.dumps(loaded.rows(effect)[index], indent=2))
                    elif action == "V":
                        show_u8_palette_grid(palette, 0, 256)
                    elif action == "P":
                        path = Path(preview_dir) / f"effect_{effect}.png"
                        u8_palette_sheet(palette).save(path)
                        if not open_preview(path):
                            print(f"  Viewer could not open {path}")
                    elif action == "C":
                        selected = _menu(
                            "U8 effect (DOS target palette):",
                            {
                                **{
                                    str(i): name
                                    for i, name in enumerate(U8_PALETTE_EFFECTS)
                                },
                                "Q": "Back",
                            },
                            str(effect),
                        )
                        if selected != "Q":
                            effect = int(selected)
                    elif action == "F":
                        _matches(palette)
                    elif action == "G":
                        _gradient(palette)
                    elif action == "U":
                        print(f"  {loaded.encoding}; {len(loaded.raw)} bytes")
                        if len(loaded.raw) == 772:
                            print(
                                f"  Header (uninterpreted): {loaded.raw[:4].hex(' ')}"
                            )
                        print(
                            "  Display RGB = stored component * 255 // 63. Sprite transparency = 255."
                        )
                        print(
                            "  Effects: decoded U8_SRC/source/U8/PAL.C; blend slots: Pentagram XFormBlend.cpp."
                        )
                    elif action == "E":
                        report = export_u8_palette_bundle(
                            loaded,
                            next_u8_palette_export(loaded, output, effect),
                            effect,
                        )
                        print(f"  Exported: {report}")
                    elif action == "A":
                        loaded = U8PaletteSource.load(
                            _path(str(loaded.path)), protected=protected
                        )
                        page, index, effect = 0, 0, 0
                    elif action == "W":
                        target = choose_u8_shape_target(game_dir)
                        if target:
                            loaded = U8PaletteSource.load(
                                resolve_u8_palette_source(target.static),
                                protected=(*protected, target.static),
                            )
                            page, index, effect = 0, 0, 0
                except (OSError, ValueError) as error:
                    print(f"  ERROR: {error}")
    except ui.PromptCancelled:
        return 0
    except (OSError, ValueError) as error:
        print(f"  ERROR: {error}")
        return 1


def palette_browse_cmd(
    source: Annotated[
        Path | None,
        typer.Argument(help="Native U8PAL.PAL; otherwise choose U8 data source"),
    ] = None,
    game_dir: Annotated[
        Path | None,
        typer.Option("--game-dir", help="U8 installation/language/STATIC owner"),
    ] = None,
    index: Annotated[
        int, typer.Option("--index", min=0, max=255, help="Initial colour index/page")
    ] = 0,
    effect: Annotated[
        int,
        typer.Option(
            "--effect", min=0, max=7, help="DOS target palette effect 0-7; 0 is normal"
        ),
    ] = 0,
    export: Annotated[
        bool, typer.Option("--export", help="Write a fresh report bundle and exit")
    ] = False,
    output: Annotated[
        Path,
        typer.Option("-o", "--output", help="Export root; older reports are preserved"),
    ] = U8_PALETTE_BROWSER_OUTPUT,
) -> None:
    """Browse U8 palette swatches, stored RGB, sprite roles and native effects."""
    raise SystemExit(
        run_u8_palette_browser(
            source,
            game_dir=game_dir,
            index=index,
            effect=effect,
            output=output,
            export=export,
        )
    )


def register_u8_palette_browser(app: typer.Typer) -> None:
    app.command("palette-browse")(palette_browse_cmd)
