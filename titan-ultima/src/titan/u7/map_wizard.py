"""Guided native U7 map rendering, with world ownership and image review."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

from titan.u7.install import existing_path
from titan.u7.palette import PaletteRecordEmptyError, U7Palette
from titan.u7.shape_archive import find_archive


# ``--resolution`` choices -> factor; re-exported for map_wizard_ui.
from titan._resolution import RESOLUTIONS as RESOLUTIONS

FULL_WORLD = (0, 0, 191, 191)


def default_resolution(full_world: bool) -> str:
    """A full world is about 25000 px square at full size, so it defaults to 25%."""
    return "25" if full_world else "full"


def render_file_name(
    game: str,
    map_num: int,
    view: str,
    chunks: tuple[int, int, int, int],
    *,
    superchunk: int | None = None,
    resolution: float = 1.0,
) -> str:
    """The default PNG name: game, map number (hex, as ``mapNN``), area, view, size."""
    if superchunk is not None:
        area = f"sc{superchunk:02X}"
    elif tuple(chunks) == FULL_WORLD:
        area = "full"
    else:
        cx0, cy0, cx1, cy1 = chunks
        area = f"c{cx0}-{cy0}_c{cx1}-{cy1}"
    size = "" if resolution == 1.0 else f"_{round(resolution * 100)}pct"
    return f"u7_{game}_map{map_num:02x}_{area}_{view}{size}.png"


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
