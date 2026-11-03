"""Batch-export U9 texture frames with matched palettes and format tables."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image

from titan.u9.cli_paths import paired_u9_texture_key, resolve_u9_input
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.install import existing_u9_path
from titan.u9.palette import U9Palette, U9PaletteError
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError
from titan.u9.texture import U9TextureError, decode_frame, parse_texture_set
from titan.u9.texture_writer import U9TextureWriteError, frame_encoding

TextureProgress = Callable[[str, int, int, int], None]
_BITMAP_TIERS = (
    ("bitmap16", "bitmap16"),
    ("bitmapc", "bitmapC"),
    ("bitmapsh", "bitmapsh"),
)


class U9TextureExportError(ValueError):
    """Raised when batch texture export cannot find or read its inputs."""


@dataclass
class U9TextureExportResult:
    """Batch PNG count, per-archive manifests and recoverable decode failures."""

    images_written: int = 0
    manifests: list[Path] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)


def _texture_sources(source: Path, all_tiers: bool) -> list[tuple[Path, str]]:
    if source.is_file():
        if all_tiers:
            raise U9TextureExportError(
                "--all-tiers requires a STATIC directory or installation root"
            )
        folder = source.stem if source.suffix.casefold() == ".flx" else source.name
        return [(source, folder)]
    if not source.is_dir():
        raise U9TextureExportError(f"Texture source not found: {source}")
    static = existing_u9_path(source / "static")
    if static.is_dir() and not any(
        existing_u9_path(source / f"{name}.flx").is_file() for _, name in _BITMAP_TIERS
    ):
        source = static
    sources = []
    for key, folder in _BITMAP_TIERS:
        path = resolve_u9_input(None, key, owner=str(source))
        if path is not None:
            archive = Path(path)
            if not archive.is_file():
                raise U9TextureExportError(f"Texture archive not found: {archive}")
            sources.append((archive, folder))
            if not all_tiers:
                break
    if not sources:
        raise U9TextureExportError(
            f"No bitmap16.flx, bitmapC.flx or bitmapsh.flx found in {source}"
        )
    return sources if all_tiers else sources[:1]


def print_texture_export_progress(
    name: str, completed: int, total: int, images: int
) -> None:
    """Show per-archive progress using standard-library terminal output only."""
    if completed not in (0, total) and completed % max(1, total // 100):
        return
    fraction = completed / total if total else 1.0
    filled = int(24 * fraction)
    line = (
        f"{name}: [{'#' * filled}{'-' * (24 - filled)}] "
        f"{fraction:4.0%} {completed}/{total} entries | {images} PNGs"
    )
    if sys.stdout.isatty():
        print(f"\r{line}", end="\n" if completed == total else "", flush=True)
    else:
        print(line, flush=True)


def export_texture_archives(
    source: str | Path,
    output: str | Path,
    *,
    palette_path: str | Path | None = None,
    all_mips: bool = False,
    all_tiers: bool = False,
    entry_id: int | None = None,
    progress: TextureProgress | None = None,
) -> U9TextureExportResult:
    """Export every frame from one FLX or a directory's highest available tier.

    Game roots also select their STATIC folder. Base images are exported unless
    all_mips is requested. Tier preference is bitmap16, bitmapC, then bitmapsh;
    all_tiers explicitly exports every available tier. Matching PNGs are replaced;
    source files are read only.
    Missing palettes are errors for paletted frames, never grey fallback images.
    """
    sources = _texture_sources(Path(source).expanduser().resolve(), all_tiers)
    output = Path(output).expanduser().resolve()
    if palette_path is not None and not Path(palette_path).expanduser().is_file():
        raise U9TextureExportError(f"Palette not found: {palette_path}")
    result = U9TextureExportResult()
    for archive_path, folder_name in sources:
        folder = output / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        errors: list[dict[str, object]] = []
        empty_entries: list[int] = []
        entries_exported = 0
        frames_written = 0
        images_written = 0
        palette_file = (
            str(Path(palette_path).expanduser())
            if palette_path is not None
            else resolve_u9_input(None, "palette", owner=str(archive_path))
        )
        table_key = paired_u9_texture_key(str(archive_path))
        table_file = (
            resolve_u9_input(None, table_key, owner=str(archive_path))
            if table_key and table_key.startswith("sdinfo")
            else None
        )
        try:
            archive = U9FlxArchive.from_file(archive_path)
            palette = U9Palette.from_file(palette_file) if palette_file else None
            selectors = (
                {
                    record.index: record.format_selector
                    for record in U9SdInfo.from_file(table_file).records()
                }
                if table_file
                else {}
            )
            indices = archive.used_entry_indices()
            if entry_id is not None:
                if entry_id not in indices:
                    raise U9TextureExportError(
                        f"Entry {entry_id} is missing or unused in {archive_path}"
                    )
                indices = [entry_id]
        except (
            OSError,
            U9FlxArchiveError,
            U9PaletteError,
            U9SdInfoError,
            U9TextureExportError,
        ) as error:
            errors.append({"error": str(error)})
            indices = []
        if progress:
            progress(archive_path.name, 0, len(indices), 0)
        for ordinal, index in enumerate(indices, 1):
            blob = archive.read_entry(index)
            try:
                texture = parse_texture_set(blob)
            except U9TextureError as error:
                errors.append({"entry": index, "error": str(error)})
                if progress:
                    progress(archive_path.name, ordinal, len(indices), images_written)
                continue
            if not texture.frame_count:
                empty_entries.append(index)
            entry_written = False
            for frame in texture.frames:
                selector = selectors.get(index)
                try:
                    encoding = frame_encoding(blob, frame.index, selector=selector)
                    if encoding == "paletted" and palette is None:
                        raise U9TextureExportError(
                            "Paletted frame needs ankh.pal; supply --palette or configure u9.paths.palette"
                        )
                except (U9TextureWriteError, U9TextureExportError) as error:
                    errors.append(
                        {"entry": index, "frame": frame.index, "error": str(error)}
                    )
                    continue
                levels = range(texture.mip_count + 1) if all_mips else range(1)
                frame_written = False
                for mip in levels:
                    try:
                        surface = decode_frame(
                            blob,
                            frame.index,
                            palette=palette,
                            selector=selector,
                            mip_level=mip,
                        )
                    except U9TextureError as error:
                        errors.append(
                            {
                                "entry": index,
                                "frame": frame.index,
                                "mip": mip,
                                "error": str(error),
                            }
                        )
                        continue
                    filename = (
                        f"texture_{index:05d}_frame_{frame.index:03d}_mip_{mip:02d}.png"
                    )
                    with Image.frombytes(
                        "RGBA", (surface.width, surface.height), surface.pixels_rgba
                    ) as image:
                        image.save(folder / filename)
                    images_written += 1
                    frame_written = True
                frames_written += int(frame_written)
                entry_written = entry_written or frame_written
            entries_exported += int(entry_written)
            if progress:
                progress(archive_path.name, ordinal, len(indices), images_written)
        manifest = folder / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "archive": str(archive_path),
                    "palette": palette_file,
                    "format_table": table_file,
                    "all_mips": all_mips,
                    "entry_filter": entry_id,
                    "entries_processed": len(indices),
                    "entries_exported": entries_exported,
                    "frames_written": frames_written,
                    "images_written": images_written,
                    "entries_without_frames": empty_entries,
                    "errors": errors,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result.manifests.append(manifest)
        result.images_written += images_written
        result.errors.extend(
            {"archive": str(archive_path), **error} for error in errors
        )
    return result
