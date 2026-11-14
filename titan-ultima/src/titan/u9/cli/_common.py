"""Loaders and lookups shared by more than one U9 command family."""

from __future__ import annotations

__all__ = [
    "PALETTE_FILENAME",
    "SDINFO_FOR_ARCHIVE",
    "_find_case_insensitive_file",
    "_find_palette",
    "_generate_preview",
    "_load_model",
    "_load_palette",
    "_load_sdinfo",
    "_load_selectors",
    "_make_texture_resolver",
    "_read_import_csv",
    "_validate_model_export_args",
]

import csv
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import typer

from titan.u9.cli_paths import paired_u9_texture_key, resolve_u9_input
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.model import U9Model, U9ModelError
from titan.u9.palette import U9Palette, U9PaletteError
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError
from titan.u9.texture import U9TextureError, decode_frame


def _load_model(sappear_file: str, model_id: int) -> U9Model:
    archive = U9FlxArchive.from_file(sappear_file)
    if model_id < 0 or model_id >= archive.num_entries:
        raise U9ModelError(
            f"model_id {model_id} out of range (0..{archive.num_entries - 1})"
        )
    blob = archive.read_entry(model_id)
    if not blob:
        raise U9ModelError(f"model_id {model_id} is an empty/unused archive slot")
    return U9Model.parse(blob, model_id=model_id)


PALETTE_FILENAME = "ankh.pal"


def _find_case_insensitive_file(directory: Path, filename: str) -> Optional[Path]:
    """Find one adjacent U9 data file without assuming Windows casing."""
    if not directory.is_dir():
        return None
    wanted = filename.casefold()
    return next(
        (path for path in directory.iterdir() if path.name.casefold() == wanted),
        None,
    )


def _find_palette(
    explicit: Optional[str], beside: Optional[str]
) -> tuple[Optional[str], bool]:
    """Resolve which palette file to use.

    Returns ``(path, was_auto_discovered)``. An explicit ``-p`` always wins.
    Otherwise ``ankh.pal`` is looked for next to the archive being read, which
    is where the game keeps it -- decoding an 8-bit frame without it silently
    produces a scrambled greyscale image rather than an error, so finding it is
    worth doing automatically.
    """
    if explicit:
        return explicit, False
    configured = resolve_u9_input(None, "palette", owner=beside)
    if configured:
        return configured, True
    if not beside:
        return None, False
    directory = os.path.dirname(os.path.abspath(beside))
    try:
        entries = os.listdir(directory)
    except OSError:
        return None, False
    for name in entries:
        if name.lower() == PALETTE_FILENAME:
            return os.path.join(directory, name), True
    return None, False


def _load_palette(
    explicit: Optional[str], beside: Optional[str], *, quiet: bool = False
):
    """Load the palette for a decode, reporting where it came from."""
    path, auto = _find_palette(explicit, beside)
    if path is None:
        if not quiet:
            print(
                f"  NOTE: no {PALETTE_FILENAME} found next to the archive; 8-bit frames "
                f"will decode as scrambled greyscale. Pass -p to supply one."
            )
        return None
    try:
        palette = U9Palette.from_file(path)
    except (U9PaletteError, OSError) as e:
        print(f"ERROR: could not read palette {path}: {e}", file=sys.stderr)
        return None
    if auto and not quiet:
        print(f"  Palette         : {path} (found automatically)")
    return palette


SDINFO_FOR_ARCHIVE = {
    "bitmapsh.flx": "sdInfo.flx",
    "bitmap16.flx": "sdInfo16.flx",
    "bitmapc.flx": "sdInfoC.flx",
}


def _load_selectors(textures_path: Optional[str], *, quiet: bool = False) -> dict:
    """Map entry index -> the engine's pixel-format selector, from sdInfo.

    The selector is the only thing separating the two one-byte-per-texel
    formats, so decoding without it silently renders 42 ALPHA_INTENSITY_44
    frames as plain masks. The matching sdInfo archive sits beside the bitmap
    archive, so it is found the same way ankh.pal is.
    """
    if not textures_path:
        return {}
    partner = SDINFO_FOR_ARCHIVE.get(os.path.basename(textures_path).lower())
    configured_key = paired_u9_texture_key(textures_path)
    if partner is None and configured_key in {"sdinfo", "sdinfo16", "sdinfoc"}:
        partner = {
            "sdinfo": "sdInfo.flx",
            "sdinfo16": "sdInfo16.flx",
            "sdinfoc": "sdInfoC.flx",
        }[configured_key]
    if partner is None:
        return {}
    key = {
        "sdinfo.flx": "sdinfo",
        "sdinfo16.flx": "sdinfo16",
        "sdinfoc.flx": "sdinfoc",
    }[partner.casefold()]
    configured = resolve_u9_input(None, key, owner=textures_path)
    if configured:
        try:
            return {
                record.index: record.format_selector
                for record in U9SdInfo.from_file(configured).records()
            }
        except (U9SdInfoError, OSError) as error:
            raise typer.BadParameter(
                f"Could not read format table {configured}: {error}"
            ) from error
    directory = os.path.dirname(os.path.abspath(textures_path))
    try:
        entries = os.listdir(directory)
    except OSError:
        return {}
    match = next((n for n in entries if n.lower() == partner.lower()), None)
    if match is None:
        if not quiet:
            print(
                f"  NOTE: no {partner} beside the archive; ALPHA_INTENSITY_44 frames "
                f"will decode as plain masks."
            )
        return {}
    try:
        info = U9SdInfo.from_file(os.path.join(directory, match))
    except (U9SdInfoError, OSError):
        return {}
    if not quiet:
        print(
            f"  Format table    : {os.path.join(directory, match)} (found automatically)"
        )
    return {r.index: r.format_selector for r in info.records()}


def _make_texture_resolver(textures_path: Optional[str], palette_path: Optional[str]):
    if not textures_path:
        return None
    texture_archive = U9FlxArchive.from_file(textures_path)
    palette = _load_palette(palette_path, textures_path)
    selectors = _load_selectors(textures_path)

    def resolver(texture_id: int, frame: int):
        try:
            blob = texture_archive.read_entry(texture_id)
            return decode_frame(
                blob, frame, palette=palette, selector=selectors.get(texture_id)
            )
        except (U9FlxArchiveError, U9TextureError):
            return None

    return resolver


def _validate_model_export_args(args: SimpleNamespace) -> Optional[str]:
    """Returns an error message if args are invalid, else None."""
    if args.format not in ("obj", "stl", "both"):
        return f"--format must be one of obj, stl, both (got {args.format!r})"
    if not os.path.isfile(args.file):
        return f"File not found: {args.file}"
    if args.textures and not os.path.isfile(args.textures):
        return f"Texture file not found: {args.textures}"
    if args.palette and not os.path.isfile(args.palette):
        return f"Palette file not found: {args.palette}"
    if args.types and not os.path.isfile(args.types):
        return f"Types file not found: {args.types}"
    if args.typenames and not os.path.isfile(args.typenames):
        return f"Typenames file not found: {args.typenames}"
    return None


def _generate_preview(outdir: str) -> None:
    from titan.u9.preview import PreviewError, PreviewUnavailableError, render_preview

    try:
        for preview_path in render_preview(outdir):
            print(f"  {preview_path}")
    except PreviewUnavailableError as e:
        print(f"  (skipped preview: {e})")
    except PreviewError as e:
        print(f"  (skipped preview: {e})")


def _load_sdinfo(filepath: str) -> Optional[U9SdInfo]:
    """Open a static/sdInfo*.flx table, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9SdInfo.from_file(filepath)
    except U9SdInfoError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def _read_import_csv(
    path: str, key_column: str, value_column: str
) -> Optional[dict[int, str]]:
    """Read ``{key: value}`` rows from an edited export CSV.

    Accepts UTF-8 with or without a byte-order mark (as spreadsheet programs
    often add). Other columns are ignored; a repeated key is an error.
    """
    if not os.path.isfile(path):
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        return None
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = {key_column, value_column} - set(reader.fieldnames or ())
            if missing:
                print(
                    f"ERROR: {path} lacks column(s) {', '.join(sorted(missing))}",
                    file=sys.stderr,
                )
                return None
            rows: dict[int, str] = {}
            for line, row in enumerate(reader, start=2):
                try:
                    key = int(row[key_column])
                except (TypeError, ValueError):
                    print(
                        f"ERROR: {path} line {line}: {key_column} "
                        f"{row[key_column]!r} is not a number",
                        file=sys.stderr,
                    )
                    return None
                if key in rows:
                    print(
                        f"ERROR: {path} line {line}: {key_column} {key} repeats",
                        file=sys.stderr,
                    )
                    return None
                rows[key] = row[value_column] or ""
    except UnicodeDecodeError as e:
        print(f"ERROR: {path} is not UTF-8 text ({e})", file=sys.stderr)
        return None
    return rows
