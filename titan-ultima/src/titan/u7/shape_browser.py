"""Read-only U7 shape browsing, frame previews and approved image exports."""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from titan._terminal_image import (
    FrameProvider,
    checkerboard,
)
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.names import U7FrameNames, U7ShapeNames
from titan.u7.palette import PaletteRecordEmptyError, U7Palette
from titan.u7.palette_semantics import CYCLE_RANGES
from titan.u7.shape import U7Shape
from titan.u7.shape_animation import TICK_MS, simulate_frame_sequence
from titan.u7.shape_archive import U7ShapeArchive, find_archive
from titan.u7.shape_cycle_scan import ShapeCycleReport, scan_shape
from titan.u7.shapeinfo import U7Blends, U7Xforms
from titan.u7.translucency import U7Translucency
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import WorldQueryParams, load_query_metadata

if TYPE_CHECKING:
    from titan.u7.shape_properties import ShapeProperties


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


def frame_preview(image: Image.Image) -> Image.Image:
    """A viewer preview preserves every pixel, enlarged when the frame is small."""
    zoom = 3 if max(image.size) <= 320 else 1
    enlarged = image.convert("RGBA").resize(
        (image.width * zoom, image.height * zoom), Image.Resampling.NEAREST
    )
    preview = checkerboard(enlarged.size)
    preview.alpha_composite(enlarged)
    return preview.convert("RGB")
