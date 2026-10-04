"""Guided PNG-to-U7-shape conversion and safe Flex/VGA insertion."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from titan._config import get_config
from titan.fonts.exult_cfg import ExultGamePaths, find_exult_cfg, parse_exult_cfg
from titan.fonts.palette import resolve_game_palette
from titan.u7.flex import U7FlexArchive
from titan.u7.flex_shape_add import (
    add_shape_at_record_index,
    add_shape_to_first_available_record,
)
from titan.u7.palette import U7Palette
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
    for name in ("allow_cycling", "flat", "replace", "in_place", "force"):
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
    section = get_config().get("u7bg" if game == "BG" else "u7si", {})
    base = section.get("game", {}).get("base")
    static = section.get("paths", {}).get("static")
    if static:
        path = Path(static).expanduser()
        return str(Path(base) / path if base and not path.is_absolute() else path)
    if base:
        return str(Path(base).expanduser() / "STATIC")
    paths = _exult_paths(game)
    return paths.static_path if paths else None


def _palette(config: ShapeWizardConfig) -> U7Palette:
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
    static = _static_path(config.game)
    source = (
        U7ShapeArchive.from_file(
            config.archive_source,
            base_archive=config.base_archive,
            configured_static=static,
            strict=True,
            require_patch_base=True,
        )
        if config.archive_source
        else None
    )
    destination = (
        U7ShapeArchive.from_file(
            str(target),
            base_archive=config.base_archive,
            configured_static=static,
            strict=True,
            require_patch_base=source is None,
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
        base = (
            Path(config.base_archive).expanduser()
            if config.base_archive
            else discover_base_archive(target, static)
        )
        if base:
            inherited = U7FlexArchive.from_file(str(base), strict=True)
        elif is_patch_archive(target) and target.name.lower() in RETAIL_SHAPE_ARCHIVES:
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
    sheet = Image.new("RGB", (352, 112 * count), (48, 48, 48))
    draw = ImageDraw.Draw(sheet)
    images = converted.shape.to_pngs(
        converted.palette, transparent=not converted.shape.frames[0].is_tile
    )
    for index in range(count):
        with Image.open(converted.png_paths[index]) as source:
            pairs = (source.convert("RGBA"), images[index])
        for column, image in enumerate(pairs):
            image.thumbnail((160, 88), Image.Resampling.NEAREST)
            if max(image.size) < 40:
                scale = min(3, 160 // image.width, 88 // image.height)
                image = image.resize(
                    (image.width * scale, image.height * scale),
                    Image.Resampling.NEAREST,
                )
            x, y = column * 176 + 8, index * 112 + 20
            for cy in range(y, y + 88, 8):
                for cx in range(x, x + 160, 8):
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


def show_preview(converted: ConvertedShape) -> None:
    print(
        f"\nConverted {len(converted.shape.frames)} frame(s); PNGs in Windows A-Z filename order:"
    )
    for index, (path, frame) in enumerate(
        zip(converted.png_paths, converted.shape.frames)
    ):
        pixels = frame.pixels
        indices = np.unique(pixels) if pixels is not None else np.array([])
        print(
            f"  {index}: {path.name} — {frame.width}x{frame.height}, origin ({frame.origin_x}, {frame.origin_y}), {len(indices)} indices"
        )
        if index < 3 and pixels is not None:
            mask = np.ones(pixels.shape, dtype=bool) if frame.is_tile else pixels != 255
            thumb = Image.fromarray(mask).resize(
                (min(frame.width, 40), min(frame.height, 16)), Image.Resampling.NEAREST
            )
            for row in np.asarray(thumb):
                print("    " + "".join("█" if pixel else "·" for pixel in row))
            if sys.stdout.isatty():
                rgb = np.asarray(converted.palette.colors, dtype=np.uint8)[pixels]
                image = Image.fromarray(rgb).resize(
                    thumb.size, Image.Resampling.NEAREST
                )
                for row, visible in zip(np.asarray(image), np.asarray(thumb)):
                    print(
                        "    "
                        + "".join(
                            f"\033[48;2;{r};{g};{b}m  " if ink else "\033[0m··"
                            for (r, g, b), ink in zip(row, visible)
                        )
                        + "\033[0m"
                    )
        if np.any((indices >= 224) & (indices < 255)):
            print(
                "    Uses cycling/effect indices 224-254 (indexed PNG choices are preserved)."
            )
    if converted.shape.frames[0].is_tile:
        print(
            "  Raw flats are fully opaque 8x8 frames; no transparency or editable origin."
        )
    else:
        print(
            "  Transparency: index 255; alpha below 128 becomes transparent for objects."
        )


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
    for path, data in payloads:
        _atomic_write(path, data)
        print(f"  Written: {path} ({len(data):,} bytes)")
    if plan:
        print(
            f"  Shape inserted at slot {plan.slot}; {len(plan.archive.records)} archive records."
        )
    return 0


def _choice(prompt: str, choices: str, default: str = "") -> str:
    while True:
        value = input(prompt).strip().upper() or default
        if value in choices.split():
            return value
        print(f"  Choose one of: {choices}")


def _integer(prompt: str, default: int, low: int, high: int) -> int:
    while True:
        try:
            value = int(input(prompt).strip() or str(default))
            if low <= value <= high:
                return value
        except ValueError:
            print("  That is not a valid integer.")
        print(f"  Enter an integer within {low}-{high}.")


def _path(prompt: str, default: str | None = None) -> str | None:
    return input(prompt).strip().strip('"').strip("'") or default


def _conversion_steps(config: ShapeWizardConfig) -> ConvertedShape:
    config.source = _path(
        f"  PNG file or frame directory [{config.source or 'enter path'}]: ",
        config.source,
    )
    print("\nPalette: record 0 is the U7 main palette.")
    config.palette_file = _path(
        f"  Palette file [{config.palette_file or 'auto from game config'}]: ",
        config.palette_file,
    )
    config.palette_index = _integer(
        f"  Palette record [{config.palette_index}]: ", config.palette_index, 0, 65535
    )
    config.allow_cycling = (
        _choice(
            f"  Allow RGB matching to use cycling colours 224-254? [{'Y' if config.allow_cycling else 'N'}] ",
            "Y N",
            "Y" if config.allow_cycling else "N",
        )
        == "Y"
    )
    print("\nShape type: [1] RLE object  [2] Raw flat (all frames opaque 8x8)")
    config.flat = _choice("> ", "1 2", "2" if config.flat else "1") == "2"
    if config.flat:
        config.origin_x = config.origin_y = 0
    else:
        print(
            "  Origin X/Y use Exult Studio's right/bottom extents; 0,0 anchors at bottom-right."
        )
        config.origin_x = _integer(
            f"  Origin X [{config.origin_x}]: ", config.origin_x, -32768, 32767
        )
        config.origin_y = _integer(
            f"  Origin Y [{config.origin_y}]: ", config.origin_y, -32768, 32767
        )
    return convert(config)


def _archive_steps(
    config: ShapeWizardConfig,
    converted: ConvertedShape,
    output_override: str | None = None,
) -> None:
    if not config.archive_source:
        static = _static_path(config.game)
        default = find_archive(Path(static), "shapes.vga") if static else None
        config.archive_source = str(default) if default else None
    config.archive_source = _path(
        f"  Source/base archive [{config.archive_source or 'Enter for new library'}] (N for new library): ",
        config.archive_source,
    )
    if config.archive_source and config.archive_source.upper() == "N":
        config.archive_source = None
    if not config.flat:
        print(
            "  Archive kind: [1] SHAPES.VGA objects (slots 150+)  [2] Other shape library (slots 0+)"
        )
        config.archive_kind = (
            "shapes" if _choice("> ", "1 2", "1") == "1" else "generic"
        )
    else:
        config.archive_kind = "shapes"
    print("  Archive output: [1] Sparse patch  [2] Copy selected archive")
    config.archive_mode = "patch" if _choice("> ", "1 2", "1") == "1" else "copy"
    if config.archive_mode == "copy" and not config.archive_source:
        raise ValueError("Copy output requires a selected source archive")
    default_output = config.archive_output or _default_archive_output(config)
    config.archive_output = output_override or _path(
        f"  Destination archive [{default_output}]: ", default_output
    )
    if (
        config.archive_source
        and Path(config.archive_source).expanduser().resolve()
        == Path(config.archive_output or "").expanduser().resolve()
        and not config.in_place
    ):
        if (
            _choice("  Update the selected source archive in place? [y/N] ", "Y N", "N")
            != "Y"
        ):
            raise ValueError("Select a separate destination archive")
        config.in_place = True
    # Find the free slot using exactly the same plan as the eventual save.
    config.slot, config.replace = None, False
    minimum = (
        FIRST_OBJ_SHAPE if config.archive_kind == "shapes" and not config.flat else 0
    )
    maximum = FIRST_OBJ_SHAPE - 1 if config.flat else 65535
    try:
        plan = prepare_archive(config, converted.data)
        candidate = plan.slot
        print(f"  First free permitted slot in base + patch: {candidate}")
        selection = _choice(
            "  [A] Use free slot  [S] Choose specific slot\n> ", "A S", "A"
        )
    except ValueError as error:
        if not str(error).startswith("No free U7 Flex shape record"):
            raise
        print(f"  {error}; choose an existing slot for explicit replacement.")
        candidate, selection = minimum, "S"
    if selection == "S":
        config.slot = _integer(
            f"  Shape slot [{candidate}]: ", candidate, minimum, maximum
        )
        try:
            prepare_archive(config, converted.data)
        except FileExistsError:
            if (
                _choice(
                    f"  Slot {config.slot} is occupied. Replace it? [y/N] ", "Y N", "N"
                )
                != "Y"
            ):
                raise ValueError("Occupied slot was not approved for replacement")
            config.replace = True
            prepare_archive(config, converted.data)
    else:
        config.slot = candidate


def run_wizard(
    source: str | None = None,
    *,
    game: str = "BG",
    output_override: str | None = None,
    force: bool = False,
    allow_cycling: bool = False,
    base_archive: str | None = None,
    preview_path: str | None = None,
    in_place: bool = False,
) -> int:
    config = ShapeWizardConfig(
        source=source,
        game=game.upper(),
        force=force,
        allow_cycling=allow_cycling,
        base_archive=base_archive,
        preview_path=preview_path,
        in_place=in_place,
    )
    try:
        print("\nTitan U7 PNG → Shape → Archive Wizard")
        config.game = (
            "BG"
            if _choice(
                "  Game: [1] Black Gate  [2] Serpent Isle\n> ",
                "1 2",
                "1" if config.game == "BG" else "2",
            )
            == "1"
            else "SI"
        )
        while True:
            try:
                converted = _conversion_steps(config)
                show_preview(converted)
            except (OSError, ValueError) as error:
                print(f"  ERROR: {error}", file=sys.stderr)
                if _choice("  [R] Retry conversion  [Q] Quit\n> ", "R Q") == "Q":
                    return 1
                continue
            answer = _choice(
                "  [Y] Looks good  [R] Redo conversion  [Q] Quit\n> ", "Y R Q"
            )
            if answer == "Q":
                print("Cancelled.")
                return 0
            if answer == "Y":
                break
        print("\nOutput: [1] Shape (.shp)  [2] Archive (.flx/.vga)  [3] Both")
        config.output_format = {"1": "shp", "2": "flex", "3": "both"}[
            _choice("> ", "1 2 3")
        ]
        if config.output_format in {"shp", "both"}:
            default = output_override or f"{Path(config.source or 'shape').stem}.shp"
            config.output_path = output_override or _path(
                f"  Shape filename [{default}]: ", default
            )
        if config.output_format in {"flex", "both"}:
            if config.output_format == "flex":
                config.archive_output = output_override
            while True:
                try:
                    _archive_steps(
                        config,
                        converted,
                        output_override if config.output_format == "flex" else None,
                    )
                    break
                except (OSError, ValueError) as error:
                    print(f"  ERROR: {error}", file=sys.stderr)
                    if (
                        _choice("  [R] Retry archive settings  [Q] Quit\n> ", "R Q")
                        == "Q"
                    ):
                        return 1
        paths = output_paths(config)
        if not config.force:
            for path in paths:
                if (
                    path.exists()
                    and _choice(f"  Replace output {path}? [y/N] ", "Y N", "N") != "Y"
                ):
                    print("Cancelled.")
                    return 0
            config.force = True
        print("\nReady to save:")
        for path in paths:
            print(f"  {path}")
        if config.output_format in {"flex", "both"}:
            print(f"  Shape slot: {prepare_archive(config, converted.data).slot}")
        if _choice("  Save these outputs? [y/N] ", "Y N", "N") != "Y":
            print("Cancelled.")
            return 0
        return save(config, converted)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


def run_from_config(
    config_path: str,
    *,
    output_override: str | None = None,
    force: bool = False,
    allow_cycling: bool = False,
    base_archive: str | None = None,
    preview_path: str | None = None,
    in_place: bool = False,
) -> int:
    """Recipes never prompt and resolve their paths relative to the recipe file."""
    try:
        recipe = Path(config_path).expanduser().resolve()
        with recipe.open("rb") as stream:
            data = tomllib.load(stream)

        def path(value: str | None) -> str | None:
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Paths must be non-empty strings")
            result = Path(value).expanduser()
            return str(result if result.is_absolute() else recipe.parent / result)

        source, palette = data.get("source", {}), data.get("palette", {})
        conversion, archive, output = (
            data.get("conversion", {}),
            data.get("archive", {}),
            data.get("output", {}),
        )
        config = ShapeWizardConfig(
            game=data.get("target", {}).get("game", "BG").upper(),
            source=path(source.get("path")),
            palette_file=path(palette.get("file")),
            palette_index=palette.get("index", 0),
            flat=conversion.get("flat", False),
            allow_cycling=allow_cycling or conversion.get("allow_cycling", False),
            origin_x=conversion.get("origin_x", 0),
            origin_y=conversion.get("origin_y", 0),
            archive_source=path(archive.get("source")),
            base_archive=base_archive or path(archive.get("base")),
            archive_kind=archive.get("kind", "shapes"),
            archive_mode=archive.get("mode", "patch"),
            slot=archive.get("slot"),
            replace=archive.get("replace", False),
            output_format=output.get("format", "shp"),
            output_path=path(output.get("path")),
            archive_output=path(output.get("archive")),
            preview_path=preview_path or path(output.get("preview")),
            force=force or output.get("force", False),
            in_place=in_place or output.get("in_place", False),
        )
        if output_override:
            if config.output_format == "flex":
                config.archive_output = output_override
            else:
                config.output_path = output_override
        elif config.output_format == "flex" and not config.archive_output:
            config.archive_output = config.output_path
        _validate(config)
        output_paths(config)
        converted = convert(config)
        show_preview(converted)
        return save(config, converted)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
