"""Read-only U7 palette browsing, cycling and palette-aware ramp experiments."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from titan._terminal_image import FrameProvider
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.install import existing_path
from titan.u7.palette import PaletteEncoding, U7Palette
from titan.u7.palette_cycle import DEFAULT_CYCLE_MS
from titan.u7.palette_semantics import CYCLE_RANGES, palette_slot_name
from titan.u7.shape_archive import find_archive
from titan.u7.shape_browser import save_bytes


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


def swatches(label: str, colours: list[str]) -> list[tuple[str, str]]:
    fragments = [("class:choice-label", label)]
    for colour in colours:
        fragments.extend([(f"bg:{colour}", "  "), ("", " ")])
    return fragments


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


def parse_hex_stops(value: str) -> list[str]:
    stops = re.split(r"[\s,;]+", value.strip())
    if not 1 <= len(stops) <= 16 or any(
        not re.fullmatch(r"#?[0-9a-fA-F]{6}", stop) for stop in stops
    ):
        raise ValueError("Enter 1-16 RGB hex colours, such as #6F263D, #236192.")
    return ["#" + stop.lstrip("#").lower() for stop in stops]


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
