"""Guided native U7 map rendering, with world ownership and image review."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.install import existing_path
from titan.u7.palette import PaletteRecordEmptyError, U7Palette
from titan.u7.shape_archive import discover_base_archive, find_archive
from titan.u7.target_picker import game_targets, select_map, select_target


def _menu(message: str, labels: dict[str, str], default: str) -> str:
    ui.legacy_menu(message, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice("> ", list(labels), default, message=message, labels=labels)


def _integer(label: str, default: int, low: int, high: int) -> int:
    while True:
        raw = ui.text(f"  {label} [{default}]: ", str(default)).strip() or str(default)
        try:
            value = int(raw, 0)
            if low <= value <= high:
                return value
        except ValueError:
            pass
        print(f"  Enter an integer within {low}-{high} (decimal or 0x hex).")


def _directory(label: str, default: str = "") -> str:
    if ui.menus_enabled():
        import questionary as q
        from titan.u7.target_picker import directory

        return directory(q, label, default)
    while True:
        value = (
            ui.path(f"  {label} [{default or 'enter path'}]: ", default)
            .strip()
            .strip('"')
            or default
        )
        path = existing_path(Path(value).expanduser())
        if value and path.is_dir():
            return str(path)
        print("  Enter an existing directory.")


def _world(args: SimpleNamespace, *, keep_supplied: bool) -> ArchiveTarget:
    initial_game = args.game
    supplied = vars(args).copy()
    game = _menu(
        "Game flavour:",
        {"1": "Black Gate", "2": "Serpent Isle"},
        "2" if args.game == "si" else "1",
    )
    args.game = "bg" if game == "1" else "si"
    base, targets = game_targets(args.game)
    current = None
    if keep_supplied and args.static:
        static = Path(args.static)
        patch = Path(args.patch_dir) if getattr(args, "patch_dir", None) else None
        if patch is None:
            inferred = discover_base_archive(
                static / "SHAPES.VGA", str(base.static) if base.static else None
            )
            if inferred:
                patch, static = static, inferred.parent
        current = ArchiveTarget(
            "Current supplied world",
            static,
            patch or static,
            gamedat=Path(args.gamedat) if args.gamedat else None,
        )
    target = select_target(base, targets, current=current)
    if target is not current:
        args.static = str(target.static) if target.static else ""
        args.patch_dir = str(target.patch) if target.patch.is_dir() else None
        args.gamedat = (
            str(target.gamedat) if target.gamedat and target.gamedat.is_dir() else None
        )
        args.map_root = None
        args.palette = None
        args.palette_index = 0
        args.map_num = 0
        # Overlays supplied for one world must not leak into another world.
        args.highlight_rects = []
        args.include_ireg = False
        if keep_supplied and target is base and initial_game == args.game:
            for name in ("map_root", "palette", "map_num", "highlight_rects"):
                setattr(args, name, supplied[name])
            if supplied.get("gamedat"):
                args.gamedat = supplied["gamedat"]
                args.include_ireg = True
    else:
        args.static = str(target.static)
        args.patch_dir = str(target.patch) if target.patch != target.static else None
    if not args.static or not Path(args.static).is_dir():
        args.static = _directory("Base STATIC directory", args.static or "")
    args.base_static = args.static  # Explicit ownership: never infer another game.
    print(f"  Selected target: {target.name}")
    print(f"  Base archives: {args.static}")
    print(f"  Patch overrides: {args.patch_dir or 'none'}")
    return target


def _choose_map(args: SimpleNamespace) -> None:
    source = _menu(
        "Map data:",
        {"1": "Selected world's base and patch", "2": "Other native map folder"},
        "2" if args.map_root else "1",
    )
    args.map_root = (
        _directory(
            "Native map root (U7CHUNKS and U7MAP/mapNN)", args.map_root or args.static
        )
        if source == "2"
        else None
    )
    q: Any = None
    if ui.menus_enabled():
        import questionary as q
    roots = [args.map_root] if args.map_root else [args.static, args.patch_dir]
    args.map_num = select_map(q, roots, args.map_num)


def _region(args: SimpleNamespace) -> None:
    while True:
        default = getattr(args, "wizard_scope", None) or (
            "1" if args.superchunk is not None or args.chunk_x1 is None else "2"
        )
        scope = _menu(
            "Render area:",
            {
                "1": "One superchunk (16 x 16 chunks)",
                "2": "Custom chunk rectangle",
                "3": "Full world (192 x 192 chunks)",
            },
            default,
        )
        args.wizard_scope = scope
        if scope == "1":
            args.superchunk = _integer(
                "Superchunk number (0-143)",
                args.superchunk if args.superchunk is not None else 0,
                0,
                143,
            )
            x = args.superchunk % 12 * 16
            y = args.superchunk // 12 * 16
            args.chunk_x0, args.chunk_y0, args.chunk_x1, args.chunk_y1 = (
                x,
                y,
                x + 15,
                y + 15,
            )
        elif scope == "2":
            args.superchunk = None
            print(
                "  Chunk coordinates are inclusive, 0-191; each chunk is 16 x 16 tiles."
            )
            args.chunk_x0 = _integer("Start chunk X", args.chunk_x0, 0, 191)
            args.chunk_y0 = _integer("Start chunk Y", args.chunk_y0, 0, 191)
            args.chunk_x1 = _integer(
                "End chunk X",
                max(
                    args.chunk_x0,
                    args.chunk_x1 if args.chunk_x1 is not None else args.chunk_x0,
                ),
                args.chunk_x0,
                191,
            )
            args.chunk_y1 = _integer(
                "End chunk Y",
                max(
                    args.chunk_y0,
                    args.chunk_y1 if args.chunk_y1 is not None else args.chunk_y0,
                ),
                args.chunk_y0,
                191,
            )
        else:
            args.superchunk = None
            args.chunk_x0, args.chunk_y0, args.chunk_x1, args.chunk_y1 = 0, 0, 191, 191
        width = (args.chunk_x1 - args.chunk_x0 + 1) * 128 + 128
        height = (args.chunk_y1 - args.chunk_y0 + 1) * 128 + 128
        print(f"  Image size: {width} x {height} pixels (includes border).")
        if width * height > 16_000_000:
            print(
                f"  Full render: the RGBA canvas alone needs about {width * height * 4 / 1024**3:.2f} GiB; rendering uses additional memory."
            )
        return


def _options(args: SimpleNamespace, target: ArchiveTarget) -> None:
    args.view = {"1": "classic", "2": "flat", "3": "steep"}[
        _menu(
            "Projection:",
            {
                "1": "Classic U7",
                "2": "Flat (ignore lift)",
                "3": "Steep (exaggerated lift)",
            },
            {"classic": "1", "flat": "2", "steep": "3"}.get(args.view, "1"),
        )
    ]
    include = (
        ui.choice(
            "  Include saved-game objects (IREG)? [y/N] ",
            ["Y", "N"],
            "Y" if args.include_ireg else "N",
        )
        == "Y"
    )
    args.include_ireg = include
    args.gamedat = (
        _directory(
            "GAMEDAT for the selected world", args.gamedat or str(target.gamedat or "")
        )
        if include
        else None
    )
    args.max_lift = (
        _integer(
            "Maximum lift", args.max_lift if args.max_lift is not None else 15, 0, 15
        )
        if ui.choice(
            "  Limit object lift (hide upper floors/roofs)? [y/N] ",
            ["Y", "N"],
            "Y" if args.max_lift is not None else "N",
        )
        == "Y"
        else None
    )
    args.grid = (
        ui.choice(
            "  Show chunk/superchunk grid? [y/N] ",
            ["Y", "N"],
            "Y" if args.grid else "N",
        )
        == "Y"
    )
    if args.grid:
        args.grid_size = _integer("Grid line width", args.grid_size, 1, 16)
    if (
        ui.choice(
            "  Advanced options (palette and shape filters)? [y/N] ",
            ["Y", "N"],
            "Y" if args.palette or args.exclude_flags else "N",
        )
        == "Y"
    ):
        print(
            "  Palette record 0 is the U7 main palette. Leave the file blank for the selected world."
        )
        args.palette = (
            ui.path(
                f"  Palette file [{args.palette or 'auto from selected world'}]: ",
                args.palette or "",
            )
            .strip()
            .strip('"')
            or None
        )
        args.palette_index = _integer("Palette record", args.palette_index, 0, 65535)
        from titan.u7.cli import _EXCLUDE_FLAG_CHOICES

        print(
            "  Exclusions hide shapes with the selected type flags; no_building hides building parts."
        )
        if ui.menus_enabled():
            import questionary as q
            from titan.u7.target_picker import ask

            args.exclude_flags = ask(
                q.checkbox(
                    "Hide shape types (Space: toggle, Enter: accept):",
                    choices=[
                        q.Choice(
                            flag.replace("no_", "Hide ").replace("_", " "),
                            value=flag,
                            checked=flag in (args.exclude_flags or []),
                        )
                        for flag in _EXCLUDE_FLAG_CHOICES
                    ],
                )
            )
        else:
            args.exclude_flags = [
                flag
                for flag in _EXCLUDE_FLAG_CHOICES
                if ui.choice(
                    f"  {flag.replace('no_', 'Hide ').replace('_', ' ')}? [y/N] ",
                    ["Y", "N"],
                    "Y" if flag in (args.exclude_flags or []) else "N",
                )
                == "Y"
            ]


def resolve_palette(args: SimpleNamespace) -> Path:
    """Select the requested populated palette record, patch first, then owner base."""
    if args.palette:
        path = existing_path(Path(args.palette).expanduser())
        U7Palette.from_file(str(path), palette_index=args.palette_index)
        return path
    for directory in (args.patch_dir, args.static):
        candidate = find_archive(Path(directory), "PALETTES.FLX") if directory else None
        if candidate:
            try:
                U7Palette.from_file(str(candidate), palette_index=args.palette_index)
                return candidate
            except PaletteRecordEmptyError:
                continue
    raise ValueError(
        "No palette found for this world; select its PALETTES.FLX in advanced options."
    )


def validate_sources(args: SimpleNamespace) -> None:
    """Fail before rendering instead of silently reusing another map's layout."""
    roots = [args.map_root] if args.map_root else [args.patch_dir, args.static]
    for filename in ("U7MAP", "U7CHUNKS"):
        candidates = []
        for root in roots:
            if root:
                directory = Path(root)
                if filename == "U7MAP" and args.map_num:
                    directory = existing_path(directory / f"map{args.map_num:02x}")
                candidates.append(find_archive(directory, filename))
        if not any(candidates):
            raise ValueError(
                f"{filename} not found for map {args.map_num} in the selected world/map folder"
            )
    if args.gamedat and args.map_num:
        directory = Path(args.gamedat)
        if directory.name.lower() != f"map{args.map_num:02x}":
            directory = existing_path(directory / f"map{args.map_num:02x}")
        if not directory.is_dir():
            raise ValueError(
                f"GAMEDAT has no map{args.map_num:02x} directory for this map"
            )
        args.gamedat = str(directory)


def save_preview(preview: Path, output: Path, *, replace: bool = False) -> None:
    """Copy approved pixels; stage replacements so a failed save preserves output."""
    if output.suffix.lower() != ".png":
        raise ValueError("Choose a .png output filename")
    if output.resolve() == preview.resolve():
        raise ValueError("Choose an output filename outside the temporary preview")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not replace:
        # Exclusive creation also handles files appearing after the prompt.
        with output.open("xb") as destination:
            try:
                with preview.open("rb") as source:
                    shutil.copyfileobj(source, destination)
            except BaseException:
                destination.close()
                output.unlink(missing_ok=True)
                raise
        return
    handle, name = tempfile.mkstemp(
        prefix=".titan-map-", suffix=".png", dir=output.parent
    )
    os.close(handle)
    staged = Path(name)
    try:
        shutil.copyfile(preview, staged)
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)


def render_map(
    args: SimpleNamespace, output: Path, *, resolution: float, label: str
) -> None:
    """Use the existing renderer at the requested resolution with visible progress."""
    from rich.progress import (
        BarColumn,
        Progress,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from titan.u7.cli import cmd_map_render

    render_args = SimpleNamespace(**vars(args))
    validate_sources(render_args)
    render_args.palette = str(resolve_palette(render_args))
    render_args.output = str(output)
    render_args.resolution = resolution
    # The region renderer shares drawing and progress for all wizard areas.
    render_args.superchunk = None
    print(f"  Palette: {render_args.palette} (record {args.palette_index})")
    last_bucket = -1
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        disable=not sys.stdout.isatty(),
    ) as display:
        task = display.add_task(label, total=100)

        def report(percent: float, stage: str) -> None:
            nonlocal last_bucket
            display.update(task, completed=percent, description=f"{label}: {stage}")
            value = int(percent)
            bucket = value // 10
            if not sys.stdout.isatty() and bucket > last_bucket:
                print(f"  {label}: {value}% — {stage}", flush=True)
                last_bucket = bucket

        render_args.progress = report
        if cmd_map_render(render_args):
            raise ValueError(
                "Map rendering failed; check the selected assets and settings"
            )


def _save(preview: Path, args: SimpleNamespace) -> bool:
    default = (
        args.output
        or f"u7_{args.game}_map{args.map_num:02x}_c{args.chunk_x0}-{args.chunk_y0}_{args.view}.png"
    )
    while True:
        output = Path(
            ui.path(f"  Output PNG [{default}]: ", default).strip().strip('"')
            or default
        ).expanduser()
        try:
            if output.suffix.lower() != ".png":
                raise ValueError("Choose a .png output filename")
            replace = output.exists()
            if (
                replace
                and ui.choice(
                    f"  Replace existing output {output}? [y/N] ", ["Y", "N"], "N"
                )
                != "Y"
            ):
                continue
            if (
                ui.choice(
                    f"  Render at full resolution and save to {output}? [y/N] ",
                    ["Y", "N"],
                    "N",
                )
                != "Y"
            ):
                return False
            full = preview.parent / "full.png"
            if not full.exists():
                try:
                    render_map(args, full, resolution=1.0, label="Full render")
                except BaseException:
                    full.unlink(missing_ok=True)
                    raise
            save_preview(full, output, replace=replace)
            print(f"  Saved map: {output.resolve()}")
            return True
        except (OSError, ValueError, MemoryError) as error:
            print(f"  ERROR: {error}", file=sys.stderr)
            if (
                _menu(
                    "Save failed:",
                    {"R": "Choose another output path", "Q": "Quit"},
                    "R",
                )
                == "Q"
            ):
                return False
        default = str(output)


def run_wizard(defaults: SimpleNamespace) -> int:
    args = SimpleNamespace(**vars(defaults))
    args.palette_index = 0
    args.include_ireg = bool(args.gamedat)
    if getattr(args, "wizard_scope", None) == "2":
        if args.chunk_x1 is None:
            args.chunk_x1 = min(191, args.chunk_x0 + 15)
        if args.chunk_y1 is None:
            args.chunk_y1 = min(191, args.chunk_y0 + 15)
    preview_dir = Path(tempfile.mkdtemp(prefix="titan-u7-map-preview-"))
    try:
        print("\nTitan U7 Map Render Wizard")
        target = _world(args, keep_supplied=True)
        while True:
            _choose_map(args)
            _region(args)
            _options(args, target)
            try:
                print(
                    f"\n  World: {target.name} | {args.game.upper()} | Map {args.map_num}"
                )
                print(
                    f"  Objects: fixed + IREG from {args.gamedat}"
                    if args.gamedat
                    else "  Objects: fixed (IFIX)"
                )
                preview = preview_dir / "preview.png"
                render_map(args, preview, resolution=0.2, label="20% preview")
                print(f"  Preview: {preview} (20% of full width and height)")
                if not open_preview(preview):
                    print(
                        "  Could not open an image viewer; open the preview PNG above manually."
                    )
            except (OSError, ValueError, MemoryError) as error:
                print(f"  ERROR: {error}", file=sys.stderr)
                action = _menu(
                    "Render failed:",
                    {
                        "R": "Change render settings",
                        "W": "Change game/world",
                        "Q": "Quit",
                    },
                    "R",
                )
                if action == "Q":
                    return 1
            else:
                action = _menu(
                    "Is this the correct map?",
                    {
                        "Y": "Yes — continue to full render",
                        "R": "Change render settings",
                        "W": "Change game/world",
                        "Q": "Quit",
                    },
                    "Y",
                )
                if action == "Q":
                    print("Cancelled.")
                    return 0
                if action == "Y":
                    if not _save(preview, args):
                        print("Cancelled.")
                    return 0
            if action == "W":
                target = _world(args, keep_supplied=False)
    except (ui.PromptCancelled, EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(preview_dir, ignore_errors=True)
