"""Interactive U7 palette browser menus, previews and exports."""

from __future__ import annotations

from pathlib import Path

from titan import _wizard_ui as ui
from titan._palette_browser_ui import show_palette_colour_grid
from titan._terminal_image import play_terminal
from titan.fonts.palette import (
    get_gradient_preset,
    list_gradient_presets,
    resolve_gradient_to_indices,
)
from titan.u7.install import existing_path
from titan.u7.palette import PaletteEncoding, U7Palette
from titan.u7.palette_cycle import DEFAULT_CYCLE_MS
from titan.u7.palette_semantics import CYCLE_RANGES, palette_slot_name
from titan.u7.target_picker import game_targets, select_target
from titan.u7.palette_browser import (
    PaletteSource,
    Record,
    colour_detail,
    cycling_provider,
    export_data,
    hex_colour,
    load_source,
    parse_hex_stops,
    safe_export,
    swatches,
)


COLOURS_PER_PAGE = 64
RECORDS_PER_PAGE = 12
READ_ERRORS = (OSError, ValueError)


def menu(message: str, labels: dict[str, str], default: str) -> str:
    ui.legacy_menu(message, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ", list(labels), default, labels=labels, message=message, hotkeys=True
    )


def integer(message: str, default: int, low: int, high: int) -> int:
    while True:
        raw = ui.text(f"  {message} [{default}]: ", str(default)).strip() or str(
            default
        )
        try:
            number = int(raw, 16 if raw.lower().startswith("0x") else 10)
            if low <= number <= high:
                return number
        except ValueError:
            pass
        print(f"  Enter a number within {low}-{high} (decimal or 0x hex).")


def path_input(message: str, default: str = "") -> Path:
    raw = ui.path(f"  {message} [{default or 'enter path'}]: ", default)
    return existing_path(Path(raw.strip().strip('"') or default).expanduser())


def choose_record(source: PaletteSource, current: int = 0) -> int | None:
    if not source.records:
        print("  This archive declares no palette records.")
        return None
    page = min(
        max(current, 0) // RECORDS_PER_PAGE,
        (len(source.records) - 1) // RECORDS_PER_PAGE,
    )
    while True:
        last = (len(source.records) - 1) // RECORDS_PER_PAGE
        labels = {
            str(record.index): record.label()
            for record in source.records[
                page * RECORDS_PER_PAGE : (page + 1) * RECORDS_PER_PAGE
            ]
        }
        if page < last:
            labels["N"] = "Next page"
        if page:
            labels["B"] = "Previous page"
        labels["Q"] = "Back"
        default = str(current) if str(current) in labels else next(iter(labels))
        selected = menu(
            f"Palette records — page {page + 1}/{last + 1}:", labels, default
        )
        if selected == "Q":
            return None
        if selected in {"N", "B"}:
            page += 1 if selected == "N" else -1
            continue
        number = int(selected)
        try:
            source.records[number].load()
            return number
        except ValueError as error:
            print(f"  ERROR: {error}")


def show_grid(
    palette: U7Palette, start: int = 0, count: int = COLOURS_PER_PAGE
) -> None:
    """Numbers remain readable without colour and avoid raw ANSI on Windows."""
    show_palette_colour_grid(palette.colors, start, count)


def cycle_preview(palette: U7Palette) -> None:
    phase = 0
    while True:
        cycled = palette.at_cycle_phase(phase * DEFAULT_CYCLE_MS)
        print(
            f"\nExult colour cycling — step {phase}; one step every {DEFAULT_CYCLE_MS} ms:"
        )
        for cycle in CYCLE_RANGES:
            colours = [
                hex_colour(rgb) for rgb in cycled.colors[cycle.start : cycle.end + 1]
            ]
            ui.print_coloured(
                swatches(f"  {cycle.name:8s} {cycle.start}-{cycle.end}: ", colours)
            )
            print("    " + " ".join(colours))
        action = menu(
            "Cycling preview:",
            {
                "P": "Play in terminal",
                "N": "Next cycle step",
                "R": "Reset",
                "Q": "Back",
            },
            "P",
        )
        if action == "Q":
            return
        if action == "N":
            phase += 1
        elif action == "R":
            phase = 0
        elif not ui.menus_enabled():
            print("  Live playback needs an interactive terminal; use Next cycle step.")
        else:
            play_terminal(cycling_provider(palette), title="U7 cycling colours")


def gradient_test(palette: U7Palette) -> None:
    labels: dict[str, str | list[tuple[str, str]]] = {}
    keys = list_gradient_presets()
    for number, key in enumerate(keys, 1):
        preset = get_gradient_preset(key)
        labels[str(number)] = swatches(preset.name + " ", preset.colors)
    labels.update({"C": "Custom RGB hex colours", "Q": "Back"})
    ui.legacy_menu(
        "Gradient presets:",
        *(
            f"  [{number}] {get_gradient_preset(key).name} — {get_gradient_preset(key).description}"
            for number, key in enumerate(keys, 1)
        ),
        "  [C] Custom RGB hex colours",
        "  [Q] Back",
    )
    selected = ui.choice(
        "> ", list(labels), "1", labels=labels, message="Test gradient:"
    )
    if selected == "Q":
        return
    if selected == "C":
        while True:
            try:
                stops = parse_hex_stops(
                    ui.text("  RGB hex colours (comma or space separated): ")
                )
                break
            except ValueError as error:
                print(f"  {error}")
        name = "Custom"
    else:
        preset = get_gradient_preset(keys[int(selected) - 1])
        name, stops = preset.name, preset.colors
    steps = integer("Gradient steps", 6, 1, 256)
    allow_cycling = (
        menu("Allow cycling colours 224-254 in matching?", {"Y": "Yes", "N": "No"}, "N")
        == "Y"
    )
    indices, _ = resolve_gradient_to_indices(
        stops, palette, steps, allow_cycling=allow_cycling
    )
    ui.print_coloured(swatches(f"  {name} requested: ", stops))
    print("  " + " → ".join(stops))
    print("  Resolved indices (copy into font wizard): " + ", ".join(map(str, indices)))
    for start in range(0, len(indices), 16):
        colours = [
            hex_colour(palette.colors[index]) for index in indices[start : start + 16]
        ]
        ui.print_coloured(swatches("  Resolved colours: ", colours))
        print("  " + " → ".join(colours))
    distinct = len({palette.colors[index] for index in indices})
    print(f"  {distinct} distinct palette colours for {steps} steps.")
    if distinct < steps:
        print(
            "  Some steps repeat: this palette has too few suitable shades for the requested ramp."
        )
    menu("Gradient result:", {"Q": "Back to palette"}, "Q")


def export_palette(
    source: PaletteSource, record: Record, palette: U7Palette, component: int
) -> None:
    kind = menu(
        "Export palette:",
        {
            "P": "PNG swatch sheet (16×16, indices in row order)",
            "C": "CSV colour table",
            "J": "JSON colour table and source details",
            "R": "Original record bytes (.pal; includes both double-palette components)",
            "Q": "Back",
        },
        "P",
    )
    if kind == "Q":
        return
    extension = {"P": "png", "C": "csv", "J": "json", "R": "pal"}[kind]
    path = path_input(
        "Output file (new file)", f"palette_{record.index:02d}_{component}.{extension}"
    )
    safe_export(source, path, export_data(record, palette, kind, component))
    print(f"  Saved: {path}")


def browse(
    source: PaletteSource, index: int = 0, encoding: PaletteEncoding = "auto"
) -> str:
    page, component, colour = 0, 0, 0
    while True:
        try:
            if not 0 <= index < len(source.records):
                raise ValueError(f"Palette record {index} is outside this source")
            record = source.records[index]
            palette = record.load(encoding, component)
        except ValueError as error:
            print(f"  ERROR: {error}")
            selected = choose_record(source, index)
            if selected is None:
                return "A"
            index, page, component, encoding = selected, 0, 0, "auto"
            continue
        print(
            f"\nPalette {index}: {palette_slot_name(index) or 'custom/unnamed'} — {record.origin}; {palette.encoding}"
        )
        print(
            f"  Source: {record.path}; {len(record.raw)} record bytes; {'secondary' if component else 'primary'} component"
        )
        print(
            f"  Colours {page * COLOURS_PER_PAGE}-{(page + 1) * COLOURS_PER_PAGE - 1} — page {page + 1}/4"
        )
        show_grid(palette, page * COLOURS_PER_PAGE)
        print(
            "  0-223: stable; 224-254: cycling; 255: RLE transparency / opaque flat colour."
        )
        labels = {
            "N": "Next colour page",
            "B": "Previous colour page",
            "I": "Inspect colour index / RGB / hex",
            "L": "Choose palette record",
            "J": "Next populated record",
            "K": "Previous populated record",
            "V": "Show all 256 colours",
            "C": "Preview cycling colours",
            "G": "Test gradient / custom RGB colours",
            "U": "Change component encoding",
            "E": "Export palette",
            "A": "Different palette source",
            "W": "Change game/world",
            "Q": "Quit",
        }
        if len(record.raw) >= 1536:
            labels["R"] = "Switch primary/secondary palette"
        action = menu("Palette actions:", labels, "N")
        if action in {"A", "W", "Q"}:
            return action
        try:
            if action in {"N", "B"}:
                page = (page + (1 if action == "N" else -1)) % 4
            elif action == "I":
                colour = integer("Colour index", colour, 0, 255)
                print("\n" + colour_detail(record, palette, colour, component))
                ui.print_coloured(
                    swatches("  Swatch: ", [hex_colour(palette.colors[colour])])
                )
                menu("Colour details:", {"Q": "Back to palette"}, "Q")
                page = colour // COLOURS_PER_PAGE
            elif action == "L":
                selected = choose_record(source, index)
                if selected is not None:
                    index, page, component = selected, 0, 0
                    encoding = "auto"
            elif action in {"J", "K"}:
                ids = source.available
                position = ids.index(index)
                index = ids[(position + (1 if action == "J" else -1)) % len(ids)]
                page, component, encoding = 0, 0, "auto"
                if len(ids) == 1:
                    print("  This source has one populated, valid palette record.")
            elif action == "V":
                show_grid(palette, count=256)
                menu("All colours:", {"Q": "Back to palette"}, "Q")
            elif action == "C":
                cycle_preview(palette)
            elif action == "G":
                gradient_test(palette)
            elif action == "R":
                component = 1 - component
            elif action == "U":
                encodings: dict[str, PaletteEncoding] = {
                    "A": "auto",
                    "6": "6bit",
                    "8": "8bit",
                }
                selected_encoding = encodings[
                    menu(
                        "Component encoding:",
                        {"A": "Auto-detect", "6": "6-bit VGA", "8": "8-bit RGB"},
                        {"auto": "A", "6bit": "6", "8bit": "8"}[encoding],
                    )
                ]
                record.load(selected_encoding, component)
                encoding = selected_encoding
            elif action == "E":
                export_palette(source, record, palette, component)
        except READ_ERRORS as error:
            print(f"  ERROR: {error}")


def run_browser(
    *,
    game: str = "bg",
    file: str | None = None,
    index: int = 0,
    encoding: PaletteEncoding = "auto",
) -> int:
    print("\nTitan U7 Palette Browser")
    try:
        while True:
            game = (
                "si"
                if menu(
                    "Game flavour:",
                    {"1": "Black Gate", "2": "Serpent Isle"},
                    "2" if game == "si" else "1",
                )
                == "2"
                else "bg"
            )
            base, targets = game_targets(game)
            target = select_target(base, targets)
            print(f"  Selected target: {target.name}")
            print(f"  Base: {target.static or 'not found'}; patch: {target.patch}")
            # Start with the selected world's palettes, or the supplied file.
            automatic = True
            while True:
                try:
                    explicit: Path | None = None
                    if file:
                        explicit, file = Path(file), None
                    elif not automatic:
                        action = menu(
                            "Palette source:",
                            {
                                "A": "Selected world (base + patch)",
                                "C": "Choose PALETTES.FLX / .pal file",
                                "W": "Change world",
                                "Q": "Quit",
                            },
                            "A",
                        )
                        if action == "Q":
                            return 0
                        if action == "W":
                            break
                        if action == "C":
                            explicit = path_input("Palette file")
                    automatic = False
                    source = load_source(target, explicit)
                    print(
                        f"  {len(source.available)} usable / {len(source.records)} declared palette records."
                    )
                    action = browse(source, index, encoding)
                    index, encoding = 0, "auto"
                    if action == "Q":
                        return 0
                    if action == "W":
                        break
                except READ_ERRORS as error:
                    automatic = False
                    print(f"  ERROR: {error}")
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
