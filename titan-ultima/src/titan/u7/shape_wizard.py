"""Guided PNG-to-U7-shape conversion and safe Flex/VGA insertion."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

if sys.version_info >= (3, 11):
    pass
else:
    pass

from titan.fonts.exult_cfg import ExultGamePaths, find_exult_cfg, parse_exult_cfg
from titan.fonts.palette import resolve_game_palette
from titan.u7.flex import U7FlexArchive
from titan.u7.flex_shape_add import (
    add_shape_at_record_index,
    add_shape_to_first_available_record,
)
from titan.u7.palette import PaletteRecordEmptyError, U7Palette
from titan.u7.install import resolve_u7_path
from titan.u7.shape import FIRST_OBJ_SHAPE, U7Shape
from titan.u7.shape_archive import (
    RETAIL_SHAPE_ARCHIVES,
    U7ShapeArchive,
    discover_base_archive,
    find_archive,
    is_patch_archive,
    overlay_shape_archives,
)
from titan.u7.shape_import import create_u7_shape_from_pngs, sorted_png_frame_paths
from titan.u7.shape_validation import validate_u7_shape_data
from titan.u7.shape_animation_flag import (
    choose_u7_shape_animation,
    prepare_u7_archive_animation,
    u7_animation_sidecar,
    u7_shape_animation_payload,
)


log = logging.getLogger(__name__)


@dataclass
class ShapeWizardConfig:
    game: str = "BG"
    source: str | None = None
    palette_file: str | None = None
    palette_index: int = 0
    allow_cycling: bool = False
    flat: bool = False
    origin_x: int = 0
    origin_y: int = 0
    output_format: str = "shp"
    output_path: str | None = None
    archive_source: str | None = None
    archive_output: str | None = None
    base_archive: str | None = None
    archive_kind: str = "shapes"
    archive_mode: str = "patch"
    slot: int | None = None
    replace: bool = False
    in_place: bool = False
    force: bool = False
    preview_path: str | None = None
    target_static: str | None = None
    target_patch: str | None = None
    target_name: str | None = None
    standalone: bool = False
    animated: bool | None = None


@dataclass
class ConvertedShape:
    shape: U7Shape
    palette: U7Palette
    png_paths: list[Path]
    data: bytes


@dataclass
class ArchivePlan:
    archive: U7FlexArchive
    slot: int
    header_source: Path | None


def _validate(config: ShapeWizardConfig) -> None:
    if config.animated is not None and type(config.animated) is not bool:
        raise ValueError("conversion.animated must be true or false")
    if config.game not in {"BG", "SI"}:
        raise ValueError("Game must be BG or SI")
    if config.output_format not in {"shp", "flex", "both"}:
        raise ValueError("Output format must be shp, flex or both")
    if config.archive_kind not in {"shapes", "generic"}:
        raise ValueError("Archive kind must be shapes or generic")
    if config.archive_mode not in {"patch", "copy"}:
        raise ValueError("Archive mode must be patch or copy")
    if (
        config.output_format in {"flex", "both"}
        and config.archive_mode == "copy"
        and not config.archive_source
    ):
        raise ValueError("Copy output requires a selected source archive")
    for name in ("allow_cycling", "flat", "replace", "in_place", "force", "standalone"):
        if type(getattr(config, name)) is not bool:
            raise ValueError(f"{name} must be a boolean")
    if type(config.palette_index) is not int or not 0 <= config.palette_index <= 65535:
        raise ValueError("Palette index must be within 0-65535")
    if config.slot is not None and (
        type(config.slot) is not int or not 0 <= config.slot <= 65535
    ):
        raise ValueError("Shape slot must be within 0-65535")
    if config.replace and config.slot is None:
        raise ValueError("Replacing an occupied record requires an explicit slot")
    if config.standalone and not config.target_static:
        raise ValueError("A standalone Exult target requires its own STATIC path")
    if config.flat and config.archive_kind != "shapes":
        raise ValueError("Flats require archive kind shapes")
    for name in ("origin_x", "origin_y"):
        value = getattr(config, name)
        if type(value) is not int or not -32768 <= value <= 32767:
            raise ValueError(f"{name} must fit a signed 16-bit value")
    if config.flat and (config.origin_x or config.origin_y):
        raise ValueError("Raw flats have no editable origin")


def _exult_paths(game: str) -> ExultGamePaths | None:
    cfg = find_exult_cfg()
    return parse_exult_cfg(cfg, game) if cfg else None


def _static_path(game: str) -> str | None:
    path = resolve_u7_path(game, "static")
    return str(path) if path else None


def _palette(config: ShapeWizardConfig) -> U7Palette:
    if not config.palette_file:
        for directory in (config.target_patch, config.target_static):
            path = find_archive(Path(directory), "palettes.flx") if directory else None
            if path:
                try:
                    return U7Palette.from_file(
                        str(path), palette_index=config.palette_index
                    )
                except PaletteRecordEmptyError:
                    continue
        if config.standalone:
            raise ValueError(
                "No palette found in the selected Exult game; select its PALETTES.FLX explicitly"
            )
    palette = resolve_game_palette(
        config.game, config.palette_file, config.palette_index
    )
    if palette is None:
        static = _static_path(config.game)
        path = find_archive(Path(static), "palettes.flx") if static else None
        if path:
            palette = U7Palette.from_file(str(path), palette_index=config.palette_index)
    if palette is None:
        raise ValueError(
            "No game palette found; select PALETTES.FLX or set palette.file in the recipe"
        )
    return palette


def convert(config: ShapeWizardConfig) -> ConvertedShape:
    """Use the same importer as shape-import; never alter or resize source PNGs."""
    _validate(config)
    if not config.source:
        raise ValueError("Select a PNG file or a directory of PNG frames")
    source = Path(config.source).expanduser()
    if source.is_dir():
        png_paths = sorted_png_frame_paths(source)
    elif source.is_file() and source.suffix.lower() == ".png":
        png_paths = [source]
    else:
        raise ValueError(f"PNG source not found: {source}")
    if not png_paths:
        raise ValueError(f"No PNG frames found in {source}")
    palette = _palette(config)
    shape = create_u7_shape_from_pngs(
        png_paths, palette, allow_cycling=config.allow_cycling, flat=config.flat
    )
    if not config.flat:
        for frame in shape.frames:
            left = frame.width - config.origin_x - 1
            above = frame.height - config.origin_y - 1
            if not (-32768 <= left <= 32767 and -32768 <= above <= 32767):
                raise ValueError(
                    "Origin and frame dimensions exceed the shape's signed 16-bit extents"
                )
            frame.origin_x, frame.origin_y = config.origin_x, config.origin_y
    data = shape.to_bytes()
    validate_u7_shape_data(data, is_tile=config.flat)
    return ConvertedShape(shape, palette, png_paths, data)


def _default_archive_output(config: ShapeWizardConfig) -> str:
    filename = (
        Path(config.archive_source).name if config.archive_source else "library.vga"
    )
    if config.target_patch:
        return str(Path(config.target_patch) / filename)
    paths = _exult_paths(config.game)
    if paths and paths.patch_path:
        return str(Path(paths.patch_path) / filename)
    return str(Path.cwd() / "patch" / filename)


def output_paths(config: ShapeWizardConfig) -> list[Path]:
    paths: list[Path] = []
    if config.output_format in {"shp", "both"}:
        if not config.output_path:
            stem = Path(config.source or "shape").stem
            config.output_path = f"{stem}.shp"
        path = Path(config.output_path).expanduser()
        if path.suffix.lower() != ".shp":
            raise ValueError("Shape output must end in .shp")
        paths.append(path)
    if config.output_format in {"flex", "both"}:
        if not config.archive_output:
            config.archive_output = _default_archive_output(config)
        path = Path(config.archive_output).expanduser()
        if path.suffix.lower() not in {".flx", ".vga"}:
            raise ValueError("Archive output must end in .flx or .vga")
        if (
            config.archive_source
            and path.resolve() == Path(config.archive_source).expanduser().resolve()
            and not config.in_place
        ):
            raise ValueError(
                "Updating the selected source archive requires --in-place or output.in_place = true"
            )
        if (
            config.base_archive
            and path.resolve() == Path(config.base_archive).expanduser().resolve()
        ):
            raise ValueError(
                "The archive output must be separate from its base archive"
            )
        if config.archive_kind == "generic" and any(
            Path(value).name.lower() == "shapes.vga"
            for value in (config.archive_source, config.archive_output)
            if value
        ):
            raise ValueError(
                "SHAPES.VGA requires archive kind shapes and its flat-slot rules"
            )
        paths.append(path)
    if config.preview_path:
        path = Path(config.preview_path).expanduser()
        if path.suffix.lower() != ".png":
            raise ValueError("Preview output must end in .png")
        paths.append(path)
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Shape, archive and preview outputs must use different paths")
    return paths


def prepare_archive(config: ShapeWizardConfig, data: bytes) -> ArchivePlan:
    """Allocate using combined occupancy, while keeping inherited records off disk."""
    _validate(config)
    validate_u7_shape_data(data, is_tile=config.flat)
    output_paths(config)
    if not config.archive_output:
        raise ValueError("Archive destination is required")
    target = Path(config.archive_output).expanduser()
    static = config.target_static or _static_path(config.game)

    def selected_base(path: Path) -> str | None:
        if config.base_archive:
            return config.base_archive
        if not config.target_static and not config.standalone:
            return None
        # Exult mods can name their patch folder "data" or keep it elsewhere.
        # The selected target establishes inheritance independently of its name.
        own_base = find_archive(Path(static), path.name) if static else None
        return (
            str(own_base) if own_base and own_base.resolve() != path.resolve() else None
        )

    source = (
        U7ShapeArchive.from_file(
            config.archive_source,
            base_archive=selected_base(Path(config.archive_source).expanduser()),
            configured_static=static,
            strict=True,
            require_patch_base=not config.standalone,
            infer_base=not config.standalone,
        )
        if config.archive_source
        else None
    )
    destination = (
        U7ShapeArchive.from_file(
            str(target),
            base_archive=selected_base(target),
            configured_static=static,
            strict=True,
            require_patch_base=source is None and not config.standalone,
            infer_base=not config.standalone,
        )
        if target.is_file()
        else None
    )
    header_source = (
        target
        if destination
        else Path(config.archive_source).expanduser()
        if config.archive_source
        else None
    )
    archive = U7FlexArchive()
    if destination:
        archive = destination.selected
    elif source:
        archive.title, archive.magic2 = source.selected.title, source.selected.magic2
        if config.archive_mode == "copy":
            archive.records = source.selected.records.copy()
    else:
        archive.title = "Created with Titan shape-create"
    inherited = source.effective if source else None
    if destination and destination.base:
        inherited = overlay_shape_archives(
            inherited or U7FlexArchive(), destination.base
        )[0]
    if inherited is None:
        base_value = selected_base(target)
        base = Path(base_value).expanduser() if base_value else None
        if base is None and not config.standalone:
            base = discover_base_archive(target, static)
        if base:
            inherited = U7FlexArchive.from_file(str(base), strict=True)
        elif (
            not config.standalone
            and is_patch_archive(target)
            and target.name.lower() in RETAIL_SHAPE_ARCHIVES
        ):
            raise ValueError(
                "Cannot resolve this patch's base archive; select the original archive or use --base-archive"
            )
    if config.flat:
        minimum, maximum = 0, FIRST_OBJ_SHAPE - 1
    elif config.archive_kind == "shapes":
        minimum, maximum = FIRST_OBJ_SHAPE, 65535
    else:
        minimum, maximum = 0, 65535
    if config.slot is not None:
        if not minimum <= config.slot <= maximum:
            raise ValueError(f"This shape requires a slot within {minimum}-{maximum}")
        slot = add_shape_at_record_index(
            archive, data, config.slot, replace=config.replace, base_archive=inherited
        )
    else:
        slot = add_shape_to_first_available_record(
            archive,
            data,
            minimum_record_index=minimum,
            maximum_record_index=maximum,
            base_archive=inherited,
        )
    return ArchivePlan(archive, slot, header_source)


def _archive_bytes(plan: ArchivePlan) -> bytes:
    if plan.header_source:
        from titan.flex import FlexArchive

        archive = FlexArchive.from_file(str(plan.header_source), strict=True)
        if archive.archive_format != "u7":
            raise ValueError("U7 shape output requires a U7/Exult Flex archive")
        archive.records = plan.archive.records
        return archive.to_bytes()
    return plan.archive.to_bytes()


def _preview_sheet(converted: ConvertedShape) -> Image.Image:
    from PIL import ImageDraw

    count = min(len(converted.shape.frames), 6)
    images = converted.shape.to_pngs(
        converted.palette, transparent=not converted.shape.frames[0].is_tile
    )
    max_width = max(image.width for image in images[:count])
    max_height = max(image.height for image in images[:count])
    scale = max(1, min(4, 640 // max_width, 400 // max_height))
    panel_width, panel_height = max(160, max_width * scale), max(88, max_height * scale)
    column_width, row_height = panel_width + 16, panel_height + 24
    sheet = Image.new("RGB", (column_width * 2, row_height * count), (48, 48, 48))
    draw = ImageDraw.Draw(sheet)
    for index in range(count):
        with Image.open(converted.png_paths[index]) as source:
            pairs = (source.convert("RGBA"), images[index])
        for column, image in enumerate(pairs):
            image = image.resize(
                (image.width * scale, image.height * scale), Image.Resampling.NEAREST
            )
            x, y = column * column_width + 8, index * row_height + 20
            for cy in range(y, y + panel_height, 8):
                for cx in range(x, x + panel_width, 8):
                    color = (
                        (96, 96, 96)
                        if ((cx - x) // 8 + (cy - y) // 8) % 2
                        else (160, 160, 160)
                    )
                    draw.rectangle((cx, cy, cx + 7, cy + 7), fill=color)
            sheet.paste(image, (x, y), image)
            draw.text(
                (x, y - 16),
                f"{index}: {'Source' if column == 0 else 'U7 palette'}",
                fill="white",
            )
    return sheet


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def save(config: ShapeWizardConfig, converted: ConvertedShape) -> int:
    _validate(config)
    paths = output_paths(config)
    for path in paths:
        if path.exists() and not config.force:
            raise FileExistsError(
                f"Output exists: {path}; use --force or output.force = true"
            )
        if path.exists() and not path.is_file():
            raise ValueError(f"Output is not a file: {path}")
        if path.resolve() in {p.resolve() for p in converted.png_paths}:
            raise ValueError("Preview output must be separate from source PNGs")
    # Prepare every payload before writing any file, including strict archive reads.
    payloads: list[tuple[Path, bytes]] = []
    if config.output_format in {"shp", "both"}:
        payloads.append((Path(config.output_path or "").expanduser(), converted.data))
    plan = None
    if config.output_format in {"flex", "both"}:
        plan = prepare_archive(config, converted.data)
        payloads.append(
            (Path(config.archive_output or "").expanduser(), _archive_bytes(plan))
        )
    if config.preview_path:
        import io

        buffer = io.BytesIO()
        _preview_sheet(converted).save(buffer, format="PNG")
        payloads.append((Path(config.preview_path).expanduser(), buffer.getvalue()))
    if config.animated is not None:
        animated = choose_u7_shape_animation(converted.shape, animated=config.animated)
        if animated is not None:
            if config.output_format in {"shp", "both"}:
                payloads.append(
                    (
                        u7_animation_sidecar(
                            Path(config.output_path or "").expanduser()
                        ),
                        u7_shape_animation_payload(converted.data, animated),
                    )
                )
            if plan:
                sources = tuple(
                    Path(value).expanduser()
                    for value in (
                        config.archive_source,
                        config.base_archive,
                        config.target_static,
                    )
                    if value
                )
                payloads.extend(
                    prepare_u7_archive_animation(
                        Path(config.archive_output or "").expanduser(),
                        {plan.slot: (converted.data, animated)},
                        world_shapes=config.archive_kind == "shapes"
                        and not config.flat,
                        sources=sources,
                    )
                )
    for path, _ in payloads:
        if path.resolve() in {p.resolve() for p in converted.png_paths}:
            raise ValueError("Animation metadata output must differ from source PNGs")
        if path.exists() and not path.is_file():
            raise ValueError(f"Output is not a file: {path}")
    for path, data in payloads:
        _atomic_write(path, data)
        log.info("  Written: %s (%s bytes)", path, f"{len(data):,}")
    if plan:
        log.info(
            "  Shape inserted at slot %s; %s archive records.",
            plan.slot,
            len(plan.archive.records),
        )
    return 0
