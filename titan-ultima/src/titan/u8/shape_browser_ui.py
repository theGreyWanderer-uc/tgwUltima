"""Interactive U8 shape/animation menus using Titan's shared terminal controls."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from titan import _wizard_ui as ui
from titan._config import cfg
from titan._image_preview import open_preview
from titan._terminal_image import checkerboard, play_terminal, terminal_image
from titan.palette import U8Palette
from titan.u8.anim import DIRECTION_NAMES
from titan.u8.shape_browser import (
    U8_BROWSER_OUTPUT,
    U8_SHAPE_ARCHIVES,
    U8ShapeLibrary,
    U8ShapeTarget,
    aligned_u8_sequence,
    configured_u8_browser_file,
    describe_u8_browser_shape,
    discover_u8_shape_targets,
    export_u8_browser_contact_sheets,
    export_u8_browser_gif,
    export_u8_browser_pngs,
    export_u8_browser_report,
    find_u8_browser_file,
    load_u8_shape_library,
    matching_u8_shapes,
    u8_frame_sheet,
    u8_contact_sheet_groups,
    u8_playback_provider,
)

PAGE_SIZE = 30


def _menu(message: str, labels: dict[str, str], default: str) -> str:
    ui.legacy_menu(message, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ", list(labels), default, labels=labels, message=message, hotkeys=True
    )


def _integer(message: str, default: int, low: int, high: int) -> int:
    while True:
        raw = ui.text(f"  {message} [{default}]: ", str(default)).strip() or str(
            default
        )
        try:
            value = int(raw, 16 if raw.casefold().startswith("0x") else 10)
            if low <= value <= high:
                return value
        except ValueError:
            pass
        print(f"  Enter {low}-{high}, in decimal or 0x hexadecimal.")


def _path(message: str, default: str = "") -> Path:
    raw = (
        ui.path(f"  {message} [{default or 'enter path'}]: ", default)
        .strip()
        .strip('"')
    )
    return Path(raw or default).expanduser()


def choose_u8_shape_target(directory: Path | None) -> U8ShapeTarget | None:
    """Choose a U8 STATIC owner, shared by shape and NPC browsers."""
    while True:
        targets = discover_u8_shape_targets(directory)
        labels = {
            str(index + 1): f"{target.name} — {target.static}"
            for index, target in enumerate(targets)
        }
        labels.update(
            {"C": "Choose U8 installation/language/STATIC folder", "Q": "Quit"}
        )
        default = next(
            (
                str(index + 1)
                for index, target in enumerate(targets)
                if target.name.casefold()
                == str(cfg("language", "game") or "").casefold()
            ),
            "1" if targets else "C",
        )
        selected = _menu("U8 data source:", labels, default)
        if selected == "Q":
            return None
        if selected == "C":
            directory = _path(
                "U8 installation or STATIC directory", str(directory or "")
            )
            if not directory.is_dir():
                print(f"  Directory not found: {directory}")
            continue
        return targets[int(selected) - 1]


def _archive(target: U8ShapeTarget) -> Path | None:
    while True:
        paths = {
            str(index + 1): configured_u8_browser_file(
                target.static, filename.split(".")[0].lower()
            )
            or find_u8_browser_file(target.static, filename)
            for index, filename in enumerate(U8_SHAPE_ARCHIVES)
        }
        labels = {
            key: filename + (" — not found" if paths[key] is None else "")
            for key, filename in zip(paths, U8_SHAPE_ARCHIVES)
        }
        labels.update(
            {
                "C": "Other Flex archive or standalone .shp",
                "W": "Change data source",
                "Q": "Quit",
            }
        )
        selected = _menu("Shape library:", labels, "1")
        if selected == "Q":
            raise ui.PromptCancelled
        if selected == "W":
            return None
        path = _path("Archive or .shp file") if selected == "C" else paths[selected]
        if path is not None and path.is_file():
            return path
        print(f"  File not found: {path or labels[selected]}")


def _filter(library: U8ShapeLibrary) -> None:
    filters = ["all", "animated"]
    if library.properties:
        filters += ["fixed", "solid", "container", "equipment", "roof", "translucent"]
    labels = {str(index + 1): value.title() for index, value in enumerate(filters)}
    labels["B"] = "Back"
    selected = _menu(
        "Shape properties filter:",
        labels,
        str(filters.index(library.property_filter) + 1),
    )
    if selected != "B":
        library.property_filter = filters[int(selected) - 1]


def choose_u8_shape(library: U8ShapeLibrary, current: int | None = None) -> int | None:
    """Page/search native IDs and class labels, retaining the current filter."""
    search, page = "", 0
    ids = matching_u8_shapes(library)
    if current in ids:
        page = ids.index(current) // PAGE_SIZE
    while True:
        matches = matching_u8_shapes(library, search)
        pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages - 1)
        labels = {
            f"S{number}": f"{number:4d}  {library.names.get(number, '(unlabelled)')}"
            for number in matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        }
        if page:
            labels["B"] = "Previous page"
        if page + 1 < pages:
            labels["N"] = "Next page"
        labels.update(
            {
                "F": "Find by shape ID or class label",
                "O": "Filter by properties",
                "Q": "Back to libraries",
            }
        )
        if not matches:
            print("  No populated shapes match this search/filter.")
        default = f"S{current}" if f"S{current}" in labels else next(iter(labels))
        selected = _menu(
            f"Shapes — {len(matches)} matches; {library.property_filter}; page {page + 1}/{pages}:",
            labels,
            default,
        )
        if selected == "Q":
            return None
        if selected == "F":
            search = ui.text("  Shape ID or class label; blank lists all: ").strip()
            page = 0
        elif selected == "O":
            _filter(library)
            page = 0
        elif selected in {"N", "B"}:
            page += 1 if selected == "N" else -1
        else:
            return int(selected[1:])


def _choose_action(
    library: U8ShapeLibrary, number: int, current: int | None
) -> int | None:
    actions = library.actions(number)
    labels = {
        f"A{action.action_num}": f"{action.action_num}: {action.name}; {action.frame_count} steps; repeat {action.repeat}"
        for action in actions
    }
    labels.update({"R": "Raw sprite frames", "B": "Keep current view"})
    selected = _menu(
        "Actor animation action:",
        labels,
        f"A{current}" if f"A{current}" in labels else "R",
    )
    return (
        current if selected == "B" else None if selected == "R" else int(selected[1:])
    )


def _choose_overlay(
    library: U8ShapeLibrary, action: int, current: int | None
) -> int | None:
    entry = library.overlays.get_action(action) if library.overlays else None
    labels = (
        {
            str(slot.type_num): f"{slot.name} — sprite {slot.shape_num}"
            for slot in entry.overlays
            if slot.shape_num is not None
        }
        if entry
        else {}
    )
    labels.update({"N": "No weapon overlay", "B": "Keep current overlay"})
    selected = _menu(
        "Avatar weapon/glow overlay preview:",
        labels,
        str(current) if str(current) in labels else "N",
    )
    return current if selected == "B" else None if selected == "N" else int(selected)


def _view(path: Path) -> None:
    print(f"  Preview: {path}")
    if not ui.menus_enabled():
        print(
            "  Open this file in an image viewer; redirected sessions do not launch viewers."
        )
    elif not open_preview(path):
        print("  Could not launch the image viewer; open the preview path manually.")


def _exports(
    library: U8ShapeLibrary,
    number: int,
    frame: int,
    action: int | None,
    direction: int,
    overlay: int | None,
    output: Path,
) -> None:
    selected = _menu(
        "Export:",
        {
            "P": "PNG sprite frames",
            "G": "GIF of current frame/action sequence",
            "C": "Named contact sheet frame sets",
            "R": "JSON shape/properties/animation report",
            "B": "Back",
        },
        "P",
    )
    if selected == "B":
        return
    if selected == "P":
        scope = _menu(
            "PNG frames:",
            {"C": "Current sprite frame", "A": "All sprite frames", "B": "Back"},
            "C",
        )
        if scope == "B":
            return
        colours = _menu(
            "PNG colours:",
            {"1": "Indexed — original palette indices", "2": "RGBA — rendered colours"},
            "1",
        )
        directory = _path(
            "PNG output directory", str(output / f"shape_{number:04d}_png")
        )
        frames = [frame] if scope == "C" else None
        paths = export_u8_browser_pngs(
            library, number, directory, frames=frames, indexed=colours == "1"
        )
    elif selected == "G":
        suffix = (
            f"_action_{action:02d}_{DIRECTION_NAMES[direction].lower()}"
            if action is not None
            else "_frames"
        )
        if overlay is not None:
            suffix += f"_overlay_{overlay}"
        path = _path("GIF output", str(output / f"shape_{number:04d}{suffix}.gif"))
        duration = _integer("Preview milliseconds per step", 100, 20, 2000)
        paths = [
            export_u8_browser_gif(
                library,
                number,
                path,
                action=action,
                direction=direction,
                overlay=overlay,
                duration_ms=duration,
            )
        ]
    elif selected == "C":
        paths = _contact_sheet_exports(
            library, number, frame, action, direction, overlay, output
        )
    else:
        path = _path("JSON report output", str(output / f"shape_{number:04d}.json"))
        paths = [export_u8_browser_report(library, number, path)]
    for path in paths:
        print(f"  Saved: {path}")


def _contact_sheet_exports(
    library: U8ShapeLibrary,
    number: int,
    frame: int,
    action: int | None,
    direction: int,
    overlay: int | None,
    output: Path,
) -> list[Path]:
    labels = {"R": "Raw sprite frames, grouped by frame range"}
    if library.actions(number):
        labels["M"] = "Named ANIM action/direction sets"
    labels["B"] = "Back"
    mode = _menu("Contact sheet groups:", labels, "M" if action is not None else "R")
    if mode == "B":
        return []
    animated = mode == "M"
    groups = u8_contact_sheet_groups(
        library, number, animated=animated, overlay=overlay
    )
    current = next(
        (
            entry
            for entry in groups
            if (animated and entry.action == action and entry.direction == direction)
            or (not animated and entry.start <= frame < entry.start + entry.frame_count)
        ),
        None,
    )
    labels = {
        "S": "Choose one frame set",
        "A": "All frame sets for this shape",
        "B": "Back",
    }
    if current is not None:
        labels = {"C": f"Current set — {current.label}", **labels}
    scope = _menu("Contact sheets to save:", labels, "C" if current else "S")
    if scope == "B":
        return []
    group = current.key if scope == "C" and current else None
    if scope == "S":
        if animated:
            actions = library.actions(number)
            selected = _menu(
                "Animation frame set:",
                {
                    **{
                        f"A{entry.action_num}": f"{entry.action_num}: {entry.name}; {entry.frame_count} steps per direction"
                        for entry in actions
                    },
                    "B": "Back",
                },
                f"A{action}" if action is not None else f"A{actions[0].action_num}",
            )
            if selected == "B":
                return []
            selected_action = int(selected[1:])
            selected = _menu(
                "Frame set direction:",
                {
                    **{str(index): name for index, name in enumerate(DIRECTION_NAMES)},
                    "B": "Back",
                },
                str(direction),
            )
            if selected == "B":
                return []
            group = next(
                entry.key
                for entry in groups
                if entry.action == selected_action and entry.direction == int(selected)
            )
        else:
            selected = _menu(
                "Raw frame set:",
                {
                    **{f"G{index}": entry.label for index, entry in enumerate(groups)},
                    "B": "Back",
                },
                f"G{groups.index(current)}" if current else "G0",
            )
            if selected == "B":
                return []
            group = groups[int(selected[1:])].key
    if animated and overlay is not None:
        print(
            f"  Overlay {overlay} is included where matching action data exists; filenames identify it."
        )
    directory = _path(
        "Contact sheet output directory",
        str(
            output
            / f"shape_{number:04d}_contact_sheets"
            / ("animations" if animated else "raw_frames")
        ),
    )
    return export_u8_browser_contact_sheets(
        library, number, directory, animated=animated, group=group, overlay=overlay
    )


def _browse_library(
    library: U8ShapeLibrary,
    *,
    shape: int | None,
    frame: int,
    action: int | None,
    direction: int,
    overlay: int | None,
    output: Path,
    previews: Path,
    embedded: bool = False,
) -> str:
    if shape is not None and shape not in library.ids:
        raise ValueError(f"U8 shape browser: requested shape {shape} is not populated")
    current = shape if shape is not None else choose_u8_shape(library)
    while current is not None:
        try:
            decoded = library.shape(current)
        except ValueError as error:
            if embedded:
                raise
            print(f"  ERROR: {error}")
            current = choose_u8_shape(library, current)
            continue
        cached = None
        while True:
            if action is not None:
                key = (current, action, direction, overlay, str(library.palette_path))
                if cached is None or cached[0] != key:
                    images, rows = aligned_u8_sequence(
                        library,
                        current,
                        action=action,
                        direction=direction,
                        overlay=overlay,
                    )
                    cached = (key, images, rows)
                else:
                    _, images, rows = cached
                if not 0 <= frame < len(images):
                    raise ValueError(
                        "U8 shape browser: selected animation step is outside this action"
                    )
                sprite_frame = rows[frame]["frame"]
                image = images[frame]
                count = len(images)
            else:
                if not 0 <= frame < len(decoded.frames):
                    raise ValueError(
                        "U8 shape browser: requested frame is outside this shape"
                    )
                sprite_frame = frame
                image = library.image(current, frame)
                count = len(decoded.frames)
            item = decoded.frames[sprite_frame]
            print(
                f"\n  Shape {current} — {library.names.get(current, '(unlabelled)')}; sprite frame {sprite_frame}/{len(decoded.frames) - 1}"
            )
            print(
                f"  {item.width}x{item.height}; draw origin ({item.xoff}, {item.yoff}); palette: {library.palette_path}"
            )
            if action is not None:
                stream = (
                    library.animations.get_action(current, action)
                    if library.animations
                    else None
                )
                print(
                    f"  ANIM action {action}: {stream.name if stream else ''}; direction {DIRECTION_NAMES[direction]}; step {frame}/{count - 1}; overlay {overlay}"
                )
                print("  Sprite sequence preview; playback speed is a viewer setting.")
            terminal_image(
                image,
                reserved_rows=18,
                pixel_mode="solid-native",
                max_width_fraction=1.0,
            )
            labels = {
                "F": "Next frame/step",
                "B": "Previous frame/step",
                "N": "Choose frame/step number",
                "S": "Choose another shape",
                "J": "Next matching shape",
                "K": "Previous matching shape",
                "P": "Play sequence in terminal",
                "I": "Open current image",
                "V": "Open frame/step sheet",
                "T": "Properties and frame metadata",
                "O": "Filter shapes",
                "E": "Export PNG/GIF/contact sheets/JSON",
                "L": "Change palette",
                "A": "Change archive",
                "W": "Change data source",
                "Q": "Quit",
            }
            if embedded:
                for action_key in ("S", "J", "K", "O", "L", "A", "W"):
                    labels.pop(action_key)
                labels["Q"] = "Back to parent browser"
            if library.actions(current):
                labels["M"] = "Choose ANIM action / raw frames"
            if action is not None:
                labels["D"] = "Choose direction"
                labels["H"] = "ANIM node details"
                if current == 1 and library.overlays:
                    labels["U"] = "Weapon/glow overlay"
            selected = _menu("Browse shape:", labels, "F" if count > 1 else "S")
            try:
                if selected in {"F", "B"}:
                    frame = (frame + (1 if selected == "F" else -1)) % count
                elif selected == "N":
                    frame = _integer("Frame/step number", frame, 0, count - 1)
                elif selected == "M":
                    action = _choose_action(library, current, action)
                    frame, overlay = 0, None
                    if action is not None:
                        aligned_u8_sequence(
                            library, current, action=action, direction=direction
                        )
                elif selected == "D":
                    direction = int(
                        _menu(
                            "Animation direction:",
                            {str(i): name for i, name in enumerate(DIRECTION_NAMES)},
                            str(direction),
                        )
                    )
                    frame = 0
                    aligned_u8_sequence(
                        library,
                        current,
                        action=action,
                        direction=direction,
                        overlay=overlay,
                    )
                elif selected == "U" and action is not None:
                    overlay = _choose_overlay(library, action, overlay)
                    frame = 0
                    aligned_u8_sequence(
                        library,
                        current,
                        action=action,
                        direction=direction,
                        overlay=overlay,
                    )
                elif selected == "H":
                    print(json.dumps(rows[frame], indent=2))
                elif selected == "T":
                    report = describe_u8_browser_shape(library, current)
                    report["frames"] = [report["frames"][sprite_frame]]
                    report["animations"] = [
                        {key: value for key, value in row.items() if key != "frames"}
                        for row in report["animations"]
                    ]
                    print(json.dumps(report, indent=2))
                elif selected == "O":
                    _filter(library)
                    if current not in matching_u8_shapes(library):
                        selected = "S"
                        break
                elif selected == "P":
                    if not ui.menus_enabled():
                        print(
                            "  Live playback needs a desktop terminal; export a GIF with [E]."
                        )
                    else:
                        frames, nodes = aligned_u8_sequence(
                            library,
                            current,
                            action=action,
                            direction=direction,
                            overlay=overlay,
                        )
                        play_terminal(
                            u8_playback_provider(frames, nodes),
                            title=f"U8 shape {current}",
                            pixel_mode="solid-native",
                            max_width_fraction=1.0,
                        )
                elif selected in {"I", "V"}:
                    path = (
                        previews
                        / f"shape_{current}_{action}_{direction}_{overlay}_{frame}_{selected}.png"
                    )
                    if selected == "I":
                        canvas = checkerboard(image.size)
                        canvas.alpha_composite(image)
                        canvas.convert("RGB").save(path)
                    else:
                        start = frame // 12 * 12
                        sheet_images = (
                            images[start : start + 12]
                            if action is not None
                            else [
                                library.image(current, index)
                                for index in range(start, min(start + 12, count))
                            ]
                        )
                        u8_frame_sheet(sheet_images, label_offset=start).save(path)
                    _view(path)
                elif selected == "E":
                    _exports(
                        library,
                        current,
                        sprite_frame,
                        action,
                        direction,
                        overlay,
                        output,
                    )
                elif selected == "L":
                    path = _path("U8 palette", str(library.palette_path))
                    palette = U8Palette.from_file(str(path))
                    library.palette, library.palette_path = palette, path.resolve()
                    library.source_paths += (path.resolve(),)
                    cached = None
                else:
                    break
            except (ValueError, OSError) as error:
                print(f"  ERROR: {error}")
                if selected in {"M", "D", "U"}:
                    action, overlay, frame = None, None, 0
        if selected in {"Q", "A", "W"}:
            return selected
        if selected in {"J", "K"}:
            ids = matching_u8_shapes(library)
            current = ids[
                (ids.index(current) + (1 if selected == "J" else -1)) % len(ids)
            ]
        else:
            current = choose_u8_shape(library, current)
        frame, action, overlay = 0, None, None
    return "A"


def run_u8_shape_browser(
    *,
    game_dir: Path | None = None,
    archive: Path | None = None,
    palette: Path | None = None,
    shape: int | None = None,
    frame: int = 0,
    anim: Path | None = None,
    typeflag: Path | None = None,
    wpnovlay: Path | None = None,
    action: int | None = None,
    direction: int = 0,
    overlay: int | None = None,
    output: Path = U8_BROWSER_OUTPUT,
) -> int:
    """Browse U8 graphics with shared prompts; redirected input keeps line menus."""
    print("\nTitan U8 Shape / Animation Browser")
    previews = Path(tempfile.mkdtemp(prefix="titan-u8-shape-browser-"))
    try:
        target = (
            U8ShapeTarget(archive.parent.name, archive.parent)
            if archive
            else choose_u8_shape_target(game_dir)
        )
        while target is not None:
            path = archive or _archive(target)
            archive = None
            if path is None:
                target = choose_u8_shape_target(game_dir)
                palette, anim, typeflag, wpnovlay = None, None, None, None
                continue
            try:
                library = load_u8_shape_library(
                    path,
                    palette=palette,
                    typeflag=typeflag,
                    anim=anim,
                    wpnovlay=wpnovlay,
                    shape_id=shape,
                )
            except (ValueError, OSError) as error:
                print(f"  ERROR: {error}")
                selected = _menu(
                    "Cannot open library:",
                    {
                        "P": "Choose palette and retry",
                        "A": "Choose another archive",
                        "W": "Change data source",
                        "Q": "Quit",
                    },
                    "P" if "palette" in str(error).casefold() else "A",
                )
                if selected == "Q":
                    return 1
                if selected == "P":
                    palette, archive = _path("U8PAL.PAL palette"), path
                elif selected == "W":
                    target = choose_u8_shape_target(game_dir)
                    palette, anim, typeflag, wpnovlay = None, None, None, None
                else:
                    palette, anim, typeflag, wpnovlay = None, None, None, None
                    shape, frame, action, overlay = None, 0, None, None
                continue
            print(f"  Library: {library.path}; {len(library.ids)} populated shapes")
            for issue in library.diagnostics:
                print(f"  Optional metadata unavailable: {issue}")
            if not library.ids:
                print("  This library has no populated shapes.")
                continue
            if overlay is not None and (shape != 1 or action is None):
                raise ValueError(
                    "U8 shape browser: --overlay requires --shape 1 and --action"
                )
            selected = _browse_library(
                library,
                shape=shape,
                frame=frame,
                action=action,
                direction=direction,
                overlay=overlay,
                output=output,
                previews=previews,
            )
            shape, frame, action, overlay = None, 0, None, None
            palette, anim, typeflag, wpnovlay = None, None, None, None
            if selected == "Q":
                return 0
            if selected == "W":
                target = choose_u8_shape_target(game_dir)
        return 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {error}")
        return 1


def browse_u8_npc_shape(
    library: U8ShapeLibrary,
    number: int,
    *,
    frame: int = 0,
    action: int | None = None,
    direction: int = 0,
    output: Path = U8_BROWSER_OUTPUT,
) -> None:
    """Inspect this NPC's shape/actions using the existing browser; Q returns to the NPC."""
    with tempfile.TemporaryDirectory(prefix="titan-u8-npc-shape-") as temporary:
        _browse_library(
            library,
            shape=number,
            frame=frame,
            action=action,
            direction=direction,
            overlay=None,
            output=output,
            previews=Path(temporary),
            embedded=True,
        )


def shape_browse_cmd(
    game_dir: Annotated[
        Path | None,
        typer.Option(
            "--game-dir", help="U8 installation, language or STATIC directory"
        ),
    ] = None,
    archive: Annotated[
        Path | None,
        typer.Option("--archive", help="Initial Flex archive or standalone .shp"),
    ] = None,
    shape: Annotated[
        int | None, typer.Option("--shape", min=0, help="Initial native shape slot")
    ] = None,
    frame: Annotated[
        int, typer.Option("--frame", min=0, help="Initial raw frame or ANIM step")
    ] = 0,
    palette: Annotated[
        Path | None,
        typer.Option(
            "-p",
            "--palette",
            help="Initial U8PAL.PAL; otherwise selected archive owner",
        ),
    ] = None,
    typeflag: Annotated[
        Path | None,
        typer.Option("--typeflag", help="Explicit TYPEFLAG.DAT for this archive"),
    ] = None,
    anim: Annotated[
        Path | None, typer.Option("--anim", help="Explicit ANIM.DAT for this archive")
    ] = None,
    wpnovlay: Annotated[
        Path | None,
        typer.Option("--wpnovlay", help="Explicit WPNOVLAY.DAT paired with ANIM"),
    ] = None,
    action: Annotated[
        int | None,
        typer.Option("--action", min=0, max=63, help="Initial ANIM actor action"),
    ] = None,
    direction: Annotated[
        int,
        typer.Option(
            "--direction", min=0, max=7, help="ANIM direction: 0=N through 7=NW"
        ),
    ] = 0,
    overlay: Annotated[
        int | None,
        typer.Option(
            "--overlay", min=0, help="Avatar overlay slot; requires shape 1 and action"
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o", "--output", help="Default export folder; existing files are preserved"
        ),
    ] = U8_BROWSER_OUTPUT,
) -> None:
    """Browse U8 shapes/actions and export frames, contact sheets, GIFs and reports."""
    raise SystemExit(
        run_u8_shape_browser(
            game_dir=game_dir,
            archive=archive,
            shape=shape,
            frame=frame,
            palette=palette,
            typeflag=typeflag,
            anim=anim,
            wpnovlay=wpnovlay,
            action=action,
            direction=direction,
            overlay=overlay,
            output=output,
        )
    )


def register_u8_shape_browser(app: typer.Typer) -> None:
    """Register the flat shape-browse command without importing the parent CLI."""
    app.command("shape-browse")(shape_browse_cmd)
