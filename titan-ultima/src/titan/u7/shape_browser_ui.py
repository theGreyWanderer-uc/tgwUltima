"""Interactive U7 shape browser menus, previews and exports."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import numpy as np

from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan._terminal_image import play_terminal, terminal_image
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.install import existing_path
from titan.u7.shape import U7Shape
from titan.u7.shape_animation import TICK_MS, save_gif
from titan.u7.target_picker import game_targets, select_target
from titan.u7.shape_browser import (
    ShapeLibrary,
    animation_frames,
    frame_preview,
    frame_sheet,
    load_library,
    load_palette,
    matching_shapes,
    owner_file,
    playback_provider,
    save_bytes,
)


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
