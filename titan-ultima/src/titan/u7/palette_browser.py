"""Read-only U7 palette browsing, cycling and palette-aware ramp experiments."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from titan import _wizard_ui as ui
from titan._terminal_image import FrameProvider, play_terminal
from titan.fonts.palette import (
    get_gradient_preset,
    list_gradient_presets,
    resolve_gradient_to_indices,
)
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.install import existing_path
from titan.u7.palette import PaletteEncoding, U7Palette
from titan.u7.palette_cycle import DEFAULT_CYCLE_MS
from titan.u7.palette_semantics import CYCLE_RANGES, palette_slot_name
from titan.u7.shape_archive import find_archive
from titan.u7.shape_browser import save_bytes
from titan.u7.target_picker import game_targets, select_target

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


def hex_colour(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def index_role(index: int) -> str:
    if index == 255:
        return "transparent in RLE objects; opaque in raw flats (stored RGB shown)"
    for cycle in CYCLE_RANGES:
        if cycle.start <= index <= cycle.end:
            return f"cycling: {cycle.name} ({cycle.start}-{cycle.end})"
    return "stable colour"


@dataclass(frozen=True)
class Record:
    index: int
    path: Path
    origin: str
    raw: bytes = b""
    error: str | None = None

    def load(self, encoding: PaletteEncoding = "auto", component: int = 0) -> U7Palette:
        if self.error:
            raise ValueError(self.error)
        if not self.raw:
            raise ValueError(f"Palette record {self.index} is empty")
        palettes: tuple[U7Palette, ...]
        if len(self.raw) >= 1536:
            palettes = U7Palette.from_double_bytes(self.raw, encoding=encoding)
        else:
            palettes = (U7Palette.from_raw_bytes(self.raw, encoding=encoding),)
        if not 0 <= component < len(palettes):
            raise ValueError("This record has no secondary palette")
        palette = palettes[component]
        if any(not 0 <= value <= 255 for rgb in palette.colors for value in rgb):
            raise ValueError(
                "Components exceed the selected encoding; try auto or 8-bit"
            )
        palette.palette_index = self.index
        palette.source = str(self.path)
        return palette

    def label(self) -> str:
        state = "empty" if not self.raw and not self.error else self.origin
        try:
            palette = self.load()
            state += f", {palette.encoding}"
            if len(self.raw) >= 1536:
                state += ", double palette"
        except ValueError as error:
            if self.raw or self.error:
                state = f"INVALID: {error} ({self.origin})"
        name = palette_slot_name(self.index) or "custom/unnamed"
        return f"{self.index}: {name} — {state}"


@dataclass
class PaletteSource:
    target: ArchiveTarget
    records: list[Record]
    paths: list[Path]
    explicit: bool = False

    @property
    def available(self) -> list[int]:
        result = []
        for record in self.records:
            try:
                record.load()
            except ValueError:
                continue
            result.append(record.index)
        return result


def read_records(path: Path, origin: str) -> list[Record]:
    slots = U7Palette.enumerate_slots(str(path))
    data = path.read_bytes()
    return [
        Record(
            slot.index,
            path,
            origin,
            data[slot.offset : slot.offset + slot.length]
            if not slot.is_empty and slot.is_valid
            else b"",
            slot.error,
        )
        for slot in slots
    ]


def load_source(target: ArchiveTarget, explicit: Path | None = None) -> PaletteSource:
    """Resolve each patch slot against its owner's base, keeping real slot IDs."""
    if explicit is not None:
        explicit = existing_path(explicit.expanduser())
        return PaletteSource(
            target, read_records(explicit, "selected file"), [explicit], True
        )
    paths: list[Path] = []
    layers: list[list[Record]] = []
    for directory, origin in ((target.static, "base"), (target.patch, "patch")):
        path = find_archive(directory, "PALETTES.FLX") if directory else None
        if path and path.resolve() not in {item.resolve() for item in paths}:
            paths.append(path)
            layers.append(read_records(path, origin))
    if not layers:
        raise ValueError("No PALETTES.FLX found for this world; choose a palette file.")
    combined: list[Record] = []
    for layer in layers:
        for record in layer:
            if record.index >= len(combined):
                combined.append(record)
            elif record.raw or record.error:
                # Empty patch slots inherit. Invalid populated patch slots block
                # inheritance, so a broken mod is never silently displayed as base.
                combined[record.index] = record
    return PaletteSource(target, combined, paths)


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


def swatches(label: str, colours: list[str]) -> list[tuple[str, str]]:
    fragments = [("class:choice-label", label)]
    for colour in colours:
        fragments.extend([(f"bg:{colour}", "  "), ("", " ")])
    return fragments


def show_grid(
    palette: U7Palette, start: int = 0, count: int = COLOURS_PER_PAGE
) -> None:
    """Numbers remain readable without colour and avoid raw ANSI on Windows."""
    columns = max(1, min(16, (shutil.get_terminal_size((80, 30)).columns - 2) // 4))
    end = min(256, start + count)
    for row in range(start, end, columns):
        fragments = [("", "  ")]
        for index in range(row, min(row + columns, end)):
            rgb = palette.colors[index]
            text_colour = (
                "#000000"
                if sum(a * b for a, b in zip(rgb, (299, 587, 114))) >= 128000
                else "#ffffff"
            )
            fragments.extend(
                [(f"bg:{hex_colour(rgb)} fg:{text_colour}", f"{index:03d}"), ("", " ")]
            )
        ui.print_coloured(fragments)


def colour_detail(
    record: Record, palette: U7Palette, index: int, component: int = 0
) -> str:
    raw = record.raw
    if len(raw) >= 1536:
        raw = raw[component:1536:2]
    elif 772 <= len(raw) < 1536:
        raw = raw[4:772]
    triplet = tuple(raw[index * 3 : index * 3 + 3])
    return (
        f"Index {index} (0x{index:02x}): {hex_colour(palette.colors[index])}, RGB {palette.colors[index]}\n"
        f"  Stored components ({palette.encoding}): {triplet}\n"
        f"  {index_role(index)}"
    )


def cycling_provider(palette: U7Palette) -> FrameProvider:
    images: dict[int, Image.Image] = {}

    def image_at(step: int, phase: int) -> tuple[Image.Image, str]:
        tick = (phase // DEFAULT_CYCLE_MS) % 24
        if tick not in images:
            cycled = palette.at_cycle_phase(tick * DEFAULT_CYCLE_MS)
            image = Image.new("RGB", (8, len(CYCLE_RANGES)), (48, 48, 48))
            for row, cycle in enumerate(CYCLE_RANGES):
                for col in range(cycle.length):
                    image.putpixel((col, row), cycled.colors[cycle.start + col])
            images[tick] = image
        return images[
            tick
        ], f"cycle step {tick}; rows: magic, fire, green, magenta, yellow, ryb"

    return image_at


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


def parse_hex_stops(value: str) -> list[str]:
    stops = re.split(r"[\s,;]+", value.strip())
    if not 1 <= len(stops) <= 16 or any(
        not re.fullmatch(r"#?[0-9a-fA-F]{6}", stop) for stop in stops
    ):
        raise ValueError("Enter 1-16 RGB hex colours, such as #6F263D, #236192.")
    return ["#" + stop.lstrip("#").lower() for stop in stops]


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


def export_data(
    record: Record, palette: U7Palette, kind: str, component: int = 0
) -> bytes:
    if kind == "R":
        return record.raw
    if kind == "P":
        buffer = io.BytesIO()
        palette.to_pil_image().save(buffer, format="PNG")
        return buffer.getvalue()
    rows = [
        {
            "index": index,
            "hex": hex_colour(rgb),
            "r": rgb[0],
            "g": rgb[1],
            "b": rgb[2],
            "role": index_role(index),
        }
        for index, rgb in enumerate(palette.colors)
    ]
    if kind == "J":
        return (
            json.dumps(
                {
                    "source": str(record.path),
                    "origin": record.origin,
                    "record": record.index,
                    "component": component,
                    "encoding": palette.encoding,
                    "colours": rows,
                },
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    if kind == "C":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8")
    raise ValueError("Unknown palette export format")


def safe_export(source: PaletteSource, path: Path, data: bytes) -> None:
    resolved = path.resolve()
    protected = [
        directory.resolve()
        for directory in (
            source.target.static,
            source.target.patch,
            source.target.root,
            source.target.gamedat,
            source.target.save_root,
        )
        if directory
    ]
    if resolved in {item.resolve() for item in source.paths} or any(
        resolved == directory or directory in resolved.parents
        for directory in protected
    ):
        raise ValueError(
            "Choose an output outside the game/mod folders and source archives."
        )
    save_bytes(path, data)


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
