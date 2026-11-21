"""Interactive and recipe-driven `titan u7 shape-create` (the terminal half of :mod:`titan.u7.shape_wizard`)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from titan._config import get_config
from titan.u7.archive_targets import ArchiveTarget, base_target, discover_targets
from titan.u7.target_picker import select_target
from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan.u7.shape import FIRST_OBJ_SHAPE
from titan.u7.shape_archive import (
    find_archive,
)
from titan.u7.shape_animation_flag import (
    choose_u7_shape_animation,
    prepare_u7_archive_animation,
    u7_animation_sidecar,
)

from titan.u7 import shape_wizard as core
from titan.u7.shape_wizard import (
    ConvertedShape,
    ShapeWizardConfig,
    _default_archive_output,
    _preview_sheet,
    _validate,
    convert,
    output_paths,
    prepare_archive,
    save,
)


def _open_preview(path: Path) -> bool:
    """Use the image viewer on Windows and the browser on other platforms."""
    return open_preview(path)


def show_preview(converted: ConvertedShape, *, open_image: bool = False) -> Path | None:
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
    if not open_image:
        return None
    # Keep this temporary PNG available after cancellation so a viewer can open
    # it asynchronously. Approved --preview outputs are still saved separately.
    with tempfile.NamedTemporaryFile(
        prefix="titan-u7-preview-", suffix=".png", delete=False
    ) as stream:
        _preview_sheet(converted).save(stream, format="PNG")
        preview = Path(stream.name)
    print(f"  Image preview (source left, U7 conversion right): {preview}")
    if not _open_preview(preview):
        print(
            "  Could not open the image viewer automatically; open the PNG above to inspect it."
        )
    if len(converted.shape.frames) > 6:
        print("  The image preview shows the first six frames.")
    return preview


def _choice(
    prompt: str,
    choices: str,
    default: str = "",
    *,
    labels: dict[str, str] | None = None,
    message: str | None = None,
) -> str:
    return ui.choice(
        prompt, choices.split(), default, labels=labels, message=message
    ).upper()


def _integer(prompt: str, default: int, low: int, high: int) -> int:
    while True:
        try:
            value = int(ui.text(prompt, str(default)).strip() or str(default))
            if low <= value <= high:
                return value
        except ValueError:
            print("  That is not a valid integer.")
        print(f"  Enter an integer within {low}-{high}.")


def _path(prompt: str, default: str | None = None) -> str | None:
    return ui.path(prompt, default or "").strip().strip('"').strip("'") or default


def _conversion_steps(config: ShapeWizardConfig) -> ConvertedShape:
    config.source = _path(
        f"  PNG file or frame directory [{config.source or 'enter path'}]: ",
        config.source,
    )
    print("\nPalette: record 0 is the U7 main palette.")
    if not config.palette_file:
        try:
            automatic_palette = core._palette(config)
            print(f"  Automatic palette: {automatic_palette.source}")
        except (OSError, ValueError) as error:
            print(f"  Automatic palette unavailable: {error}")
    while True:
        config.palette_file = _path(
            f"  Palette file (Enter = automatic; type a file path to override) [{config.palette_file or ''}]: ",
            config.palette_file,
        )
        if not config.palette_file or Path(config.palette_file).expanduser().is_file():
            break
        print(
            "  Enter an existing palette file path, or leave this blank for automatic selection."
        )
        print("  Palette record numbers such as 0 belong in the next prompt.")
        config.palette_file = None
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
    ui.legacy_menu("\nShape type: [1] RLE object  [2] Raw flat (all frames opaque 8x8)")
    config.flat = (
        _choice(
            "> ",
            "1 2",
            "2" if config.flat else "1",
            message="Shape type:",
            labels={"1": "RLE object", "2": "Raw flat (all frames opaque 8x8)"},
        )
        == "2"
    )
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


def _select_target(config: ShapeWizardConfig) -> None:
    static_value = core._static_path(config.game)
    static = Path(static_value) if static_value else None
    targets = discover_targets(
        config.game,
        get_config(),
        static,
        core._exult_paths(config.game),
        core.find_exult_cfg(),
    )
    base = base_target(
        config.game,
        get_config(),
        static,
        core._exult_paths(config.game),
        core.find_exult_cfg(),
    )
    target = select_target(base, targets)
    if target is not base:
        _apply_target(config, target)


def _apply_target(config: ShapeWizardConfig, target: ArchiveTarget) -> None:
    config.target_name = target.name
    config.target_static = str(target.static) if target.static else None
    config.target_patch = str(target.patch)
    config.standalone = target.standalone
    print(f"  Selected target: {target.name}")
    print(f"  Base archives: {target.static or '(none)'}")
    print(f"  Patch destination: {target.patch}")


def _archive_steps(
    config: ShapeWizardConfig,
    converted: ConvertedShape,
    output_override: str | None = None,
) -> None:
    libraries = {
        "1": "SHAPES.VGA",
        "2": "GUMPS.VGA",
        "3": "FACES.VGA",
        "4": "SPRITES.VGA",
    }
    if config.flat:
        print("  Raw flats use SHAPES.VGA (slots 0-149).")
        selection = "1"
    else:
        archive_labels = {
            "1": "SHAPES.VGA — world objects (slots 150+)",
            "2": "GUMPS.VGA — inventory and interface graphics",
            "3": "FACES.VGA — conversation portraits",
            "4": "SPRITES.VGA — effects and overlays",
            "5": "Other existing FLX/VGA archive",
            "6": "New shape library",
        }
        ui.legacy_menu(
            "\nChoose the archive to receive this image:",
            *(f"  [{key}] {value}" for key, value in archive_labels.items()),
        )
        current_name = (
            Path(config.archive_source).name.upper() if config.archive_source else None
        )
        default_selection = next(
            (key for key, name in libraries.items() if name == current_name),
            "5" if current_name else "1",
        )
        selection = _choice(
            "> ",
            "1 2 3 4 5 6",
            default_selection,
            message="Archive to receive this image:",
            labels=archive_labels,
        )
    if selection == "6":
        config.archive_source = None
        config.archive_kind = "generic"
        config.archive_mode = "patch"
        print("  Creating a new shape library; permitted slots start at 0.")
    else:
        filename = libraries.get(selection)
        default_source = config.archive_source
        if filename and (
            not default_source
            or (not config.flat and Path(default_source).name.upper() != filename)
        ):
            static = config.target_static or core._static_path(config.game)
            found = find_archive(Path(static), filename) if static else None
            if found is None and config.target_patch:
                found = find_archive(Path(config.target_patch), filename)
            default_source = str(found) if found else None
        config.archive_source = _path(
            f"  Base/source {filename or 'archive'} [{default_source or 'enter path'}]: ",
            default_source,
        )
        if not config.archive_source:
            raise ValueError(
                "Select an existing source archive, or choose New shape library"
            )
        config.archive_kind = (
            "shapes"
            if config.flat
            or filename == "SHAPES.VGA"
            or Path(config.archive_source).name.lower() == "shapes.vga"
            else "generic"
        )
        print(f"  Selected archive: {config.archive_source}")
        ui.legacy_menu(
            "  Archive output: [1] Sparse patch (keep base unchanged)  [2] Copy selected archive"
        )
        config.archive_mode = (
            "patch"
            if _choice(
                "> ",
                "1 2",
                "1",
                message="Archive output:",
                labels={
                    "1": "Sparse patch (keep base unchanged)",
                    "2": "Copy selected archive",
                },
            )
            == "1"
            else "copy"
        )
    if config.archive_mode == "copy" and not config.archive_source:
        raise ValueError("Copy output requires a selected source archive")
    slots = (
        "0-149" if config.flat else "150+" if config.archive_kind == "shapes" else "0+"
    )
    print(f"  Permitted shape slots: {slots}")
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
            "  [A] Use free slot  [S] Choose specific slot\n> ",
            "A S",
            "A",
            message="Shape slot:",
            labels={"A": f"Use free slot {candidate}", "S": "Choose a specific slot"},
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
    animated: bool | None = None,
) -> int:
    config = ShapeWizardConfig(
        source=source,
        game=game.upper(),
        force=force,
        allow_cycling=allow_cycling,
        base_archive=base_archive,
        preview_path=preview_path,
        in_place=in_place,
        animated=animated,
    )
    try:
        print("\nTitan U7 PNG → Shape → Archive Wizard")
        config.game = (
            "BG"
            if _choice(
                "  Game: [1] Black Gate  [2] Serpent Isle\n> ",
                "1 2",
                "1" if config.game == "BG" else "2",
                message="Game flavour:",
                labels={"1": "Black Gate", "2": "Serpent Isle"},
            )
            == "1"
            else "SI"
        )
        _select_target(config)
        while True:
            try:
                converted = _conversion_steps(config)
                show_preview(converted, open_image=True)
            except (OSError, ValueError) as error:
                print(f"  ERROR: {error}", file=sys.stderr)
                if (
                    _choice(
                        "  [R] Retry conversion  [Q] Quit\n> ",
                        "R Q",
                        message="Conversion failed:",
                        labels={"R": "Retry conversion", "Q": "Quit"},
                    )
                    == "Q"
                ):
                    return 1
                continue
            answer = _choice(
                "  [Y] Looks good  [R] Redo conversion  [Q] Quit\n> ",
                "Y R Q",
                message="Review the image preview:",
                labels={"Y": "Looks good", "R": "Redo conversion", "Q": "Quit"},
            )
            if answer == "Q":
                print("Cancelled.")
                return 0
            if answer == "Y":
                break
        config.animated = choose_u7_shape_animation(
            converted.shape, animated=config.animated
        )
        ui.legacy_menu("\nOutput: [1] Shape (.shp)  [2] Archive (.flx/.vga)  [3] Both")
        config.output_format = {"1": "shp", "2": "flex", "3": "both"}[
            _choice(
                "> ",
                "1 2 3",
                message="Output format:",
                labels={"1": "Shape (.shp)", "2": "Archive (.flx/.vga)", "3": "Both"},
            )
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
                        _choice(
                            "  [R] Retry archive settings  [Q] Quit\n> ",
                            "R Q",
                            message="Archive settings failed:",
                            labels={"R": "Retry archive settings", "Q": "Quit"},
                        )
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
        if config.target_name:
            print(f"  Target: {config.target_name} ({config.game} flavour)")
        for path in paths:
            print(f"  {path}")
        if config.animated is not None:
            print(f"  Frames animate: {'Yes' if config.animated else 'No'}")
            if config.output_format in {"shp", "both"}:
                print(f"  {u7_animation_sidecar(Path(config.output_path or ''))}")
        if config.output_format in {"flex", "both"}:
            plan = prepare_archive(config, converted.data)
            print(f"  Shape slot: {plan.slot}")
            if config.animated is not None:
                sources = tuple(
                    Path(value).expanduser()
                    for value in (
                        config.archive_source,
                        config.base_archive,
                        config.target_static,
                    )
                    if value
                )
                for path, _ in prepare_u7_archive_animation(
                    Path(config.archive_output or ""),
                    {plan.slot: (converted.data, config.animated)},
                    world_shapes=config.archive_kind == "shapes" and not config.flat,
                    sources=sources,
                ):
                    print(f"  {path}")
        if _choice("  Save these outputs? [y/N] ", "Y N", "N") != "Y":
            print("Cancelled.")
            return 0
        return save(config, converted)
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
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
    animated: bool | None = None,
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
            target_static=path(data.get("target", {}).get("static")),
            target_patch=path(data.get("target", {}).get("patch")),
            standalone=data.get("target", {}).get("standalone", False),
            animated=animated if animated is not None else conversion.get("animated"),
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
