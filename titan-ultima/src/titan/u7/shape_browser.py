"""Read-only U7 shape browsing, frame previews and approved image exports."""

from __future__ import annotations

import io
import math
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan._terminal_image import (
    FrameProvider,
    checkerboard,
    play_terminal,
    terminal_image,
)
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.install import existing_path
from titan.u7.names import U7FrameNames, U7ShapeNames
from titan.u7.palette import PaletteRecordEmptyError, U7Palette
from titan.u7.palette_semantics import CYCLE_RANGES
from titan.u7.shape import U7Shape
from titan.u7.shape_animation import TICK_MS, save_gif, simulate_frame_sequence
from titan.u7.shape_archive import U7ShapeArchive, find_archive
from titan.u7.shape_cycle_scan import ShapeCycleReport, scan_shape
from titan.u7.shapeinfo import U7Blends, U7Xforms
from titan.u7.target_picker import game_targets, select_target
from titan.u7.translucency import U7Translucency
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import WorldQueryParams, load_query_metadata

if TYPE_CHECKING:
    from titan.u7.shape_properties import ShapeProperties

ARCHIVES = (
    "SHAPES.VGA",
    "GUMPS.VGA",
    "FACES.VGA",
    "SPRITES.VGA",
    "FONTS.VGA",
    "PAPERDOL.VGA",
)
PAGE_SIZE = 30


def _menu(
    message: str, labels: dict[str, str], default: str, *, hotkeys: bool = True
) -> str:
    ui.legacy_menu(message, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ", list(labels), default, labels=labels, message=message, hotkeys=hotkeys
    )


def _integer(message: str, default: int, low: int, high: int) -> int:
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


def _path(message: str, default: str = "") -> Path:
    raw = (
        ui.path(f"  {message} [{default or 'enter path'}]: ", default)
        .strip()
        .strip('"')
    )
    return existing_path(Path(raw or default).expanduser())


def owner_file(target: ArchiveTarget, filename: str) -> Path | None:
    return find_archive(target.patch, filename) or (
        find_archive(target.static, filename) if target.static else None
    )


def load_palette(
    target: ArchiveTarget, index: int = 0, explicit: Path | None = None
) -> tuple[U7Palette, Path]:
    """Inherit absent/empty patch palette records from this owner's base."""
    if explicit is not None:
        return U7Palette.from_file(str(explicit), palette_index=index), explicit
    for directory in (target.patch, target.static):
        path = find_archive(directory, "PALETTES.FLX") if directory else None
        if path:
            slots = U7Palette.enumerate_slots(str(path))
            if index >= len(slots):
                continue
            if not slots[index].is_valid:
                raise ValueError(
                    f"Invalid palette record {index} in {path}: {slots[index].error}"
                )
            try:
                return U7Palette.from_file(str(path), palette_index=index), path
            except PaletteRecordEmptyError:
                continue
    raise ValueError(
        "No populated palette found for this world; choose PALETTES.FLX or a .pal file."
    )


@dataclass
class ShapeLibrary:
    target: ArchiveTarget
    path: Path
    archive: U7ShapeArchive
    palette: U7Palette
    palette_path: Path
    palette_index: int
    tfa: U7TypeFlags
    names: U7ShapeNames | None
    frame_names: U7FrameNames | None
    translucency: U7Translucency
    base_path: Path | None = None
    game: str = "bg"
    property_filter: str = "all"
    properties: ShapeProperties | None = None

    @property
    def is_shapes(self) -> bool:
        return self.path.name.lower() == "shapes.vga"

    @property
    def ids(self) -> list[int]:
        return [i for i, record in enumerate(self.archive.effective.records) if record]

    def name(self, number: int) -> str:
        return self.names.get(number) if self.names else ""

    def shape(self, number: int) -> U7Shape:
        records = self.archive.effective.records
        if not 0 <= number < len(records) or not records[number]:
            raise ValueError(f"Shape {number} is empty or outside this library")
        return U7Shape.from_data(
            records[number], is_tile=self.is_shapes and number < 150, strict=True
        )

    def report(self, shape: U7Shape, number: int) -> ShapeCycleReport:
        return scan_shape(
            shape,
            number,
            self.tfa,
            xfstart=self.translucency.xfstart,
            name=self.name(number),
        )

    def images(
        self, shape: U7Shape, number: int, *, indexed: bool = False, phase: int = 0
    ) -> list[Image.Image]:
        entry = self.tfa.get(number)
        images = shape.to_pngs(
            self.palette,
            indexed=indexed,
            cycle_phase_ms=phase,
            has_translucency=bool(entry and entry.has_translucency),
            translucency=self.translucency,
        )
        for frame, image in zip(shape.frames, images):
            if indexed and not frame.is_tile:
                image.info["transparency"] = 255
            elif not indexed and frame.is_tile:
                # Ground tiles have no transparent index, including index 255.
                image.putalpha(255)
        return images


def load_library(
    target: ArchiveTarget,
    game: str,
    path: Path,
    *,
    palette_index: int = 0,
    palette_file: Path | None = None,
    base_archive: Path | None = None,
) -> ShapeLibrary:
    base = base_archive
    # Infer inheritance only for an archive actually in the selected patch.
    if (
        base is None
        and path.parent.resolve() == target.patch.resolve()
        and target.static
    ):
        base = find_archive(target.static, path.name)
        if base and base.resolve() == path.resolve():
            base = None
    archive = U7ShapeArchive.from_file(
        str(path),
        base_archive=str(base) if base else None,
        infer_base=False,
        strict=True,
    )
    palette, palette_path = load_palette(target, palette_index, palette_file)
    tfa = U7TypeFlags.parse(b"")
    names: U7ShapeNames | None = None
    frames: U7FrameNames | None = None
    if path.name.lower() == "shapes.vga" and target.static and target.static.is_dir():
        patch = (
            target.patch
            if target.patch.is_dir()
            and target.patch.resolve() != target.static.resolve()
            else None
        )
        tfa, names, frames, _ = load_query_metadata(
            WorldQueryParams(
                static_dir=str(target.static),
                base_static=str(target.static),
                patch_dir=str(patch) if patch else None,
                game=game,
            )
        )
    xforms = owner_file(target, "XFORM.TBL")
    blends = owner_file(target, "BLENDS.DAT")
    translucency = U7Translucency(
        U7Xforms.from_file(str(xforms)) if xforms else U7Xforms([]),
        U7Blends.from_file(str(blends)) if blends else U7Blends.from_exult_hardcoded(),
    )
    return ShapeLibrary(
        target,
        path,
        archive,
        palette,
        palette_path,
        palette_index,
        tfa,
        names,
        frames,
        translucency,
        base,
        game=game,
    )


def matching_shapes(library: ShapeLibrary, search: str) -> list[int]:
    from titan.u7.shape_properties import filtered_ids

    ids = filtered_ids(library, library.property_filter)
    search = search.strip()
    if not search:
        return ids
    try:
        number = int(search, 16 if search.lower().startswith("0x") else 10)
    except ValueError:
        return [
            number
            for number in ids
            if search.casefold() in library.name(number).casefold()
        ]
    return [number] if number in ids else []


def choose_shape(library: ShapeLibrary, current: int | None = None) -> int | None:
    search, page = "", 0
    ids = library.ids
    if current in ids:
        page = ids.index(current) // PAGE_SIZE
    while True:
        matches = matching_shapes(library, search)
        pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages - 1)
        labels = {
            f"S{number}": f"{number:4d}  {library.name(number) or '(unnamed)'}"
            for number in matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        }
        if page:
            labels["B"] = "Previous page"
        if page + 1 < pages:
            labels["N"] = "Next page"
        if library.is_shapes:
            labels["O"] = "Filter by shape properties"
        labels.update({"F": "Find by shape ID or name", "Q": "Back to archives"})
        if not matches:
            print(f"  No populated shapes match {search!r}.")
        default = f"S{current}" if f"S{current}" in labels else next(iter(labels))
        selected = _menu(
            f"Shapes — {len(matches)} matches, filter {library.property_filter}, page {page + 1}/{pages}:",
            labels,
            default,
        )
        if selected == "Q":
            return None
        if selected == "O":
            from titan.u7.shape_properties import choose_filter

            choose_filter(library)
            page = 0
            continue
        if selected == "F":
            search = ui.text(
                "  Shape ID (decimal/0x hex) or name; blank lists all: "
            ).strip()
            page = 0
        elif selected in {"B", "N"}:
            page += 1 if selected == "N" else -1
        else:
            return int(selected[1:])


def frame_sheet(images: list[Image.Image], start: int = 0) -> Image.Image:
    """Bound a contact sheet to twelve frames without cropping their artwork."""
    items = images[start : start + 12]
    columns = min(4, len(items))
    sheet = Image.new(
        "RGB",
        (columns * 260, ((len(items) + columns - 1) // columns) * 230),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(items):
        x, y = index % columns * 260, index // columns * 230
        draw.text(
            (x + 8, y + 6),
            f"Frame {start + index}: {image.width}x{image.height}",
            fill="white",
        )
        scale = min(3, 244 / image.width, 196 / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        cell = checkerboard(size)
        cell.alpha_composite(
            image.convert("RGBA").resize(size, Image.Resampling.NEAREST)
        )
        sheet.paste(cell.convert("RGB"), (x + 8, y + 28))
    return sheet


def _frame_bounds(shape: U7Shape) -> tuple[int, int, int, int]:
    left = min(-f.hotspot_x_from_left for f in shape.frames)
    top = min(-f.hotspot_y_from_top for f in shape.frames)
    right = max(f.width - f.hotspot_x_from_left for f in shape.frames)
    bottom = max(f.height - f.hotspot_y_from_top for f in shape.frames)
    return left, top, right, bottom


def _align_image(
    frame: U7Shape.Frame, image: Image.Image, bounds: tuple[int, int, int, int]
) -> Image.Image:
    left, top, right, bottom = bounds
    canvas = Image.new("RGBA", (right - left, bottom - top))
    canvas.alpha_composite(
        image.convert("RGBA"),
        (-frame.hotspot_x_from_left - left, -frame.hotspot_y_from_top - top),
    )
    return canvas


def aligned_frames(shape: U7Shape, images: list[Image.Image]) -> list[Image.Image]:
    """Keep Exult drawing anchors stationary when differently sized frames animate."""
    bounds = _frame_bounds(shape)
    return [
        _align_image(frame, image, bounds) for frame, image in zip(shape.frames, images)
    ]


def playback_provider(
    library: ShapeLibrary, shape: U7Shape, number: int, frame: int, mode: str
) -> FrameProvider:
    """Advance palette time independently of a repeating frame sequence."""
    report = library.report(shape, number)
    cycle_frames = report.cycle_frame_indices
    bounds = _frame_bounds(shape)
    static = aligned_frames(shape, library.images(shape, number))
    cycle_ticks = math.lcm(*(rng.length for rng in CYCLE_RANGES))

    @lru_cache(maxsize=2)
    def cycled(index: int, tick: int) -> Image.Image:
        single = U7Shape()
        single.frames = [shape.frames[index]]
        image = library.images(single, number, phase=tick * TICK_MS)[0]
        return _align_image(shape.frames[index], image, bounds)

    def image_at(step: int, elapsed_ms: int) -> tuple[Image.Image, str]:
        index = frame if mode == "C" else step % len(shape.frames)
        tick = elapsed_ms // TICK_MS % cycle_ticks
        image = cycled(index, tick) if index in cycle_frames and tick else static[index]
        label = f"Frame {index}/{len(shape.frames) - 1}"
        if mode == "C":
            label += " — palette cycling"
        return image, label

    return image_at


def _play(
    library: ShapeLibrary, shape: U7Shape, number: int, frame: int, mode: str
) -> None:
    if not ui.menus_enabled():
        print(
            "  Live playback needs an interactive terminal; use [G] for a GIF preview."
        )
        return
    if mode == "C" and frame not in library.report(shape, number).cycle_frame_indices:
        print("  This frame has no cycling palette colours.")
        return
    play_terminal(
        playback_provider(library, shape, number, frame, mode), title=f"Shape {number}"
    )


def _actions(library: ShapeLibrary, shape: U7Shape, number: int, frame: int) -> str:
    labels = {
        "F": "Next frame",
        "B": "Previous frame",
        "N": "Choose frame number",
        "S": "Choose another shape",
        "J": "Next shape",
        "K": "Previous shape",
        "P": "Play frames in terminal",
    }
    if frame in library.report(shape, number).cycle_frame_indices:
        labels["C"] = "Cycle palette colours in terminal"
    labels.update(
        {
            "I": "Open current frame at full detail",
            "V": "Open colour frame sheet",
            "E": "Export PNG frame(s)",
            "G": "Preview/export GIF animation",
            "L": "Change palette",
            "T": "Shape properties / physics / equipment",
            "A": "Change archive",
            "W": "Change game/world",
            "Q": "Quit",
        }
    )
    if library.is_shapes:
        labels["O"] = "Filter by shape properties"
    return _menu(
        "Browse shape:", labels, "F" if len(shape.frames) > 1 else "S", hotkeys=True
    )


def animation_frames(
    library: ShapeLibrary,
    shape: U7Shape,
    number: int,
    frame: int,
    mode: str,
    steps: int,
    *,
    duration_ms: int = TICK_MS,
) -> list[Image.Image]:
    report = library.report(shape, number)
    if mode == "E":
        if report.resolved_animation is None:
            raise ValueError("This shape has no TFA frame animation")
        sequence = simulate_frame_sequence(report.resolved_animation, 0, steps)
    elif mode == "C":
        sequence = [frame] * steps
    else:
        sequence = [i % len(shape.frames) for i in range(steps)]
    frames = []
    original = aligned_frames(shape, library.images(shape, number))
    for tick, index in enumerate(sequence):
        rendered = (
            aligned_frames(
                shape, library.images(shape, number, phase=tick * duration_ms)
            )
            if report.has_any_cycle and tick
            else original
        )
        frames.append(rendered[index])
    return frames


def save_bytes(path: Path, data: bytes, *, replace: bool = False) -> None:
    """Exclusive new files and atomic replacements after overwrite confirmation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace:
        with path.open("xb") as stream:
            try:
                stream.write(data)
            except BaseException:
                stream.close()
                path.unlink(missing_ok=True)
                raise
        return
    handle, name = tempfile.mkstemp(prefix=".titan-shape-", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def _approved(paths: list[Path]) -> set[Path] | None:
    if (
        _menu(
            f"Save {len(paths)} file(s) to {paths[0].parent}?",
            {"Y": "Save", "N": "Cancel export"},
            "Y",
        )
        != "Y"
    ):
        return None
    existing = {path for path in paths if path.exists()}
    if existing:
        print("  Existing files:")
        for path in sorted(existing):
            print(f"    {path}")
        if (
            _menu(
                "Replace these files?",
                {"Y": "Replace", "N": "Keep existing files"},
                "N",
            )
            != "Y"
        ):
            return None
    return existing


def _png_export(library: ShapeLibrary, shape: U7Shape, number: int, frame: int) -> None:
    scope = _menu(
        "Export PNG frames:",
        {"1": "Current frame", "2": "All frames", "B": "Back"},
        "1",
    )
    if scope == "B":
        return
    indexed = (
        _menu(
            "PNG colours:",
            {
                "1": "Indexed — preserve original U7 indices",
                "2": "RGBA — rendered colours",
            },
            "1",
        )
        == "1"
    )
    directory = _path("Output directory", f"{library.path.stem.lower()}_{number}")
    images = library.images(shape, number, indexed=indexed)
    selected = [frame] if scope == "1" else list(range(len(images)))
    paths = [directory / f"shape_{number:04d}_f{index:04d}.png" for index in selected]
    approved = _approved(paths)
    if approved is None:
        return
    payloads = []
    for index in selected:
        buffer = io.BytesIO()
        images[index].save(buffer, format="PNG")
        payloads.append(buffer.getvalue())
    for path, payload in zip(paths, payloads):
        save_bytes(path, payload, replace=path in approved)
        print(f"  Saved: {path}")


def _view(path: Path) -> None:
    print(f"  Preview: {path}")
    if not open_preview(path):
        print("  Could not open the image viewer; open the preview file manually.")


def frame_preview(image: Image.Image) -> Image.Image:
    """A viewer preview preserves every pixel, enlarged when the frame is small."""
    zoom = 3 if max(image.size) <= 320 else 1
    enlarged = image.convert("RGBA").resize(
        (image.width * zoom, image.height * zoom), Image.Resampling.NEAREST
    )
    preview = checkerboard(enlarged.size)
    preview.alpha_composite(enlarged)
    return preview.convert("RGB")


def _animation(
    library: ShapeLibrary, shape: U7Shape, number: int, frame: int, previews: Path
) -> None:
    report = library.report(shape, number)
    labels = {"F": "Play every frame in archive order"}
    if report.resolved_animation:
        labels["E"] = "Use the shape's TFA animation sequence (from frame 0)"
    if frame in report.cycle_frame_indices:
        labels["C"] = "Palette cycling on current frame"
    labels["B"] = "Back"
    mode = _menu("Animation preview:", labels, "E" if "E" in labels else "F")
    if mode == "B":
        return
    count = (
        report.resolved_animation.nframes
        if mode == "E" and report.resolved_animation
        else len(shape.frames)
    )
    steps = _integer("Preview steps", 24 if mode == "C" else min(240, count), 1, 240)
    delay = (
        TICK_MS * report.resolved_animation.frame_delay
        if mode == "E" and report.resolved_animation
        else TICK_MS
    )
    duration = _integer("Milliseconds per frame", delay, 20, 2000)
    gif = previews / f"{library.path.stem}_{number}_{frame}.gif"
    if mode == "E":
        print(
            "  Engine preview uses deterministic frame advances; hourly animation advances one game hour per step."
        )
    save_gif(
        animation_frames(
            library, shape, number, frame, mode, steps, duration_ms=duration
        ),
        str(gif),
        duration_ms=duration,
    )
    _view(gif)
    if (
        _menu("Review animation:", {"Y": "Save GIF", "N": "Return to shape"}, "N")
        != "Y"
    ):
        return
    destination = _path("GIF output", f"shape_{number:04d}.gif")
    if destination.suffix.lower() != ".gif":
        raise ValueError("Choose a .gif output filename")
    approved = _approved([destination])
    if approved is not None:
        save_bytes(destination, gif.read_bytes(), replace=destination in approved)
        print(f"  Saved: {destination}")


def _describe(library: ShapeLibrary, shape: U7Shape, number: int, frame: int) -> None:
    item = shape.frames[frame]
    report = library.report(shape, number)
    name = (
        library.frame_names.label(number, frame, library.names)
        if library.frame_names
        else library.name(number)
    )
    patch_record = library.archive.selected.records
    source = (
        library.path
        if number < len(patch_record) and patch_record[number]
        else f"base archive: {library.base_path}"
    )
    print(
        f"\n  Shape {number}{' — ' + name if name else ''}; frame {frame}/{len(shape.frames) - 1}"
    )
    print(f"  Source: {source}")
    print(
        f"  {'Raw flat' if item.is_tile else 'RLE object'}; {item.width}x{item.height}; origin ({item.origin_x}, {item.origin_y})"
    )
    print(f"  Palette: {library.palette_path}, record {library.palette_index}")
    if item.pixels is not None:
        print(
            f"  {len(np.unique(item.pixels))} palette indices; index 255 is {'opaque' if item.is_tile else 'transparent'}"
        )
    entry = library.tfa.get(number)
    if entry:
        print(
            f"  Class: {entry.shape_class_name}; animated: {report.is_animated}; translucent: {report.is_translucent}"
        )
    if report.has_any_cycle:
        print(
            f"  Cycling indices across frames: {', '.join(map(str, sorted(report.all_cycle_indices)))}"
        )
    if report.has_any_translucency:
        print(
            "  Translucent colours use an approximate RGBA preview over the checkerboard."
        )
    terminal_image(library.images(shape, number)[frame], reserved_rows=20)


def _palette_prompt(
    target: ArchiveTarget, index: int = 0, path: Path | None = None
) -> tuple[int, Path | None]:
    while True:
        default = str(path) if path else ""
        raw = (
            ui.path(
                f"  Palette file [{default or 'auto from selected world'}]: ", default
            )
            .strip()
            .strip('"')
            or default
        )
        explicit = existing_path(Path(raw).expanduser()) if raw else None
        index = _integer("Palette record (0 = U7 main palette)", index, 0, 255)
        try:
            load_palette(target, index, explicit)
            return index, explicit
        except (ValueError, OSError) as error:
            print(f"  ERROR: {error}")


def _choose_archive(target: ArchiveTarget, supplied: Path | None = None) -> Path | None:
    path: Path | None
    labels = {
        str(i): filename
        + (" — not found" if owner_file(target, filename) is None else "")
        for i, filename in enumerate(ARCHIVES, 1)
    }
    labels.update(
        {"C": "Other VGA/Flex archive", "W": "Change game/world", "Q": "Quit"}
    )
    while True:
        if supplied is not None:
            path, supplied = supplied, None
        else:
            selection = _menu("Shape library:", labels, "1")
            if selection == "Q":
                raise ui.PromptCancelled
            if selection == "W":
                return None
            path = (
                _path("VGA/Flex archive")
                if selection == "C"
                else owner_file(target, ARCHIVES[int(selection) - 1])
            )
        if path is not None and path.is_file():
            return path
        print("  Archive not found; choose an existing library.")


def run_browser(
    *,
    game: str = "bg",
    archive: str | None = None,
    shape: int | None = None,
    palette: str | None = None,
    palette_index: int = 0,
    base_archive: str | None = None,
) -> int:
    print("\nTitan U7 Shape Browser")
    # Retain previews because local image viewers may load them asynchronously.
    previews = Path(tempfile.mkdtemp(prefix="titan-u7-shape-browser-"))
    try:
        while True:
            flavour = _menu(
                "Game flavour:",
                {"1": "Black Gate", "2": "Serpent Isle"},
                "2" if game == "si" else "1",
            )
            game = "si" if flavour == "2" else "bg"
            base, targets = game_targets(game)
            target = select_target(base, targets)
            print(f"  Selected target: {target.name}")
            print(f"  Base archives: {target.static or 'none'}; patch: {target.patch}")
            change_world = False
            while not change_world:
                path = _choose_archive(
                    target,
                    existing_path(Path(archive).expanduser()) if archive else None,
                )
                archive = None
                if path is None:
                    break
                try:
                    library = load_library(
                        target,
                        game,
                        path,
                        palette_index=palette_index,
                        palette_file=existing_path(Path(palette).expanduser())
                        if palette
                        else None,
                        base_archive=existing_path(Path(base_archive).expanduser())
                        if base_archive
                        else None,
                    )
                except (ValueError, OSError) as error:
                    print(f"  ERROR: {error}")
                    action = _menu(
                        "Cannot open library:",
                        {
                            "R": "Retry this library",
                            "P": "Choose palette and retry",
                            "A": "Choose another archive",
                            "W": "Change world",
                            "Q": "Quit",
                        },
                        "P" if "palette" in str(error).lower() else "A",
                    )
                    if action == "Q":
                        return 0
                    if action == "W":
                        break
                    if action == "P":
                        palette_index, explicit = _palette_prompt(target, palette_index)
                        palette, archive = (
                            str(explicit) if explicit else None,
                            str(path),
                        )
                    elif action == "R":
                        archive = str(path)
                    else:
                        base_archive = None
                    continue
                base_archive = None  # An explicit base belongs to this library only.
                print(
                    f"  Library: {path}; {len(library.ids)} populated shapes; {library.archive.base_fill_count} inherited base records"
                )
                if not library.ids:
                    print("  This library contains no shapes.")
                    continue
                current = shape if shape in library.ids else choose_shape(library)
                shape = None
                while current is not None:
                    try:
                        decoded = library.shape(current)
                        if not decoded.frames:
                            raise ValueError("Shape contains no frames")
                    except ValueError as error:
                        print(f"  ERROR: {error}")
                        current = choose_shape(library, current)
                        continue
                    frame = 0
                    while True:
                        _describe(library, decoded, current, frame)
                        action = _actions(library, decoded, current, frame)
                        try:
                            if action in {"F", "B"}:
                                frame = (frame + (1 if action == "F" else -1)) % len(
                                    decoded.frames
                                )
                            elif action == "N":
                                frame = _integer(
                                    "Frame number", frame, 0, len(decoded.frames) - 1
                                )
                            elif action == "I":
                                preview = (
                                    previews
                                    / f"{library.path.stem}_{current}_frame_{frame}.png"
                                )
                                frame_preview(
                                    library.images(decoded, current)[frame]
                                ).save(preview)
                                _view(preview)
                            elif action == "V":
                                preview = (
                                    previews
                                    / f"{library.path.stem}_{current}_{frame // 12}.png"
                                )
                                frame_sheet(
                                    library.images(decoded, current), frame // 12 * 12
                                ).save(preview)
                                _view(preview)
                            elif action == "E":
                                _png_export(library, decoded, current, frame)
                            elif action == "G":
                                _animation(library, decoded, current, frame, previews)
                            elif action == "T":
                                from titan.u7.shape_properties import show_properties

                                show_properties(library, decoded, current, frame)
                            elif action == "O":
                                from titan.u7.shape_properties import choose_filter

                                choose_filter(library)
                                if current not in matching_shapes(library, ""):
                                    action = "S"
                                    break
                            elif action in {"P", "C"}:
                                _play(
                                    library,
                                    decoded,
                                    current,
                                    frame,
                                    "C" if action == "C" else "F",
                                )
                            elif action == "L":
                                index, explicit = _palette_prompt(
                                    target, library.palette_index
                                )
                                library.palette, library.palette_path = load_palette(
                                    target, index, explicit
                                )
                                library.palette_index = index
                                palette_index, palette = (
                                    index,
                                    str(explicit) if explicit else None,
                                )
                            elif action == "Q":
                                return 0
                            else:
                                break
                        except (ValueError, OSError) as error:
                            print(f"  ERROR: {error}")
                    if action in {"J", "K"}:
                        ids = matching_shapes(library, "")
                        current = ids[
                            (ids.index(current) + (1 if action == "J" else -1))
                            % len(ids)
                        ]
                    elif action == "S":
                        current = choose_shape(library, current)
                    else:
                        change_world = action == "W"
                        break
            # Palette and archive selections must never leak into another owner.
            palette, base_archive, shape, palette_index = None, None, None, 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
