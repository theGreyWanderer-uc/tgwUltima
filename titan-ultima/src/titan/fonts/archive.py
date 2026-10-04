"""Resolve font templates using Exult's retail or bundled base plus patch."""

from __future__ import annotations

import os
import struct
from pathlib import Path

from titan.fonts.exult_cfg import ExultGamePaths, find_exult_cfg, parse_exult_cfg
from titan.u7.flex import U7FlexArchive
from titan.u7.shape_archive import (
    discover_base_archive,
    find_archive,
    is_patch_archive,
    overlay_shape_archives,
)

# exult/data/exult_flx.h; these live in the common EXULT.FLX, not a game bundle.
_BUNDLED_FONTS = {"fonts_original.vga": 29, "fonts_serif.vga": 30}


def game_paths(game: str) -> ExultGamePaths | None:
    cfg = find_exult_cfg()
    return parse_exult_cfg(cfg, game) if cfg else None


def _bundled_base(path: Path, paths: ExultGamePaths | None) -> U7FlexArchive:
    from titan._config import exult_cfg

    candidates: list[Path] = []
    configured = exult_cfg("flx")
    if configured:
        candidates.append(Path(configured).expanduser())
    if paths and paths.data_path:
        candidates.append(Path(paths.data_path).expanduser() / "exult.flx")
    for ancestor in path.resolve().parents:
        candidates.extend([ancestor / "exult.flx", ancestor / "data" / "exult.flx"])
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            install = Path(os.environ[variable]) / "Exult"
            candidates.extend([install / "exult.flx", install / "data" / "exult.flx"])
    candidates.extend(
        Path(directory) / "exult.flx"
        for directory in ("/usr/share/exult", "/usr/local/share/exult", "/opt/exult")
    )
    bundle_path = next((p for p in candidates if p.is_file()), None)
    if bundle_path is None:
        raise ValueError(
            f"Cannot resolve the Exult base for {path.name}. Set Exult's data_path "
            "or supply an extracted font VGA as source.base_archive."
        )
    bundle = U7FlexArchive.from_file(str(bundle_path), strict=True)
    index = _BUNDLED_FONTS[path.name.lower()]
    if index >= len(bundle.records):
        raise ValueError(f"Missing font record {index} in {bundle_path}")
    data = bundle.records[index]
    # Validate the nested Flex table before using the shared byte reader.
    if len(data) < 128:
        raise ValueError(f"Invalid bundled font in {bundle_path}")
    count = struct.unpack_from("<I", data, 84)[0]
    table_end = 128 + count * 8
    if table_end > len(data):
        raise ValueError("Truncated bundled font table")
    for i in range(count):
        offset, size = struct.unpack_from("<II", data, 128 + i * 8)
        if size and (offset < table_end or offset + size > len(data)):
            raise ValueError("Invalid bundled font record bounds")
    return U7FlexArchive.from_bytes(data)


def read_font_archive(
    path: str | Path,
    *,
    game: str = "BG",
    base_archive: str | None = None,
    paths: ExultGamePaths | None = None,
    infer_base: bool = True,
) -> U7FlexArchive:
    """Inspect effective slots without changing the sparse archive on disk."""
    selected_path = Path(path).expanduser()
    selected = U7FlexArchive.from_file(str(selected_path), strict=True)
    base = None
    base_path: Path | None
    if base_archive:
        base_path = Path(base_archive).expanduser()
        if base_path.resolve() == selected_path.resolve():
            raise ValueError("The base archive must be distinct from the patch archive")
        base = U7FlexArchive.from_file(str(base_path), strict=True)
    elif (
        paths
        and paths.static_path
        and (candidate := find_archive(Path(paths.static_path), selected_path.name))
        and candidate.resolve() != selected_path.resolve()
    ):
        base = U7FlexArchive.from_file(str(candidate), strict=True)
    elif infer_base and is_patch_archive(selected_path):
        paths = paths or game_paths(game)
        static = paths.static_path if paths else None
        if not static:
            from titan._config import get_config

            section = get_config().get("u7bg" if game == "BG" else "u7si", {})
            game_base = section.get("game", {}).get("base")
            if game_base:
                static = str(Path(game_base) / "STATIC")
        base_path = discover_base_archive(selected_path, static)
        if selected_path.name.lower() in _BUNDLED_FONTS:
            base = _bundled_base(selected_path, paths)
        elif base_path:
            base = U7FlexArchive.from_file(str(base_path), strict=True)
        elif selected_path.name.lower() == "fonts.vga":
            candidate = find_archive(Path(static), "fonts.vga") if static else None
            if candidate:
                base = U7FlexArchive.from_file(str(candidate), strict=True)
            else:
                raise ValueError(
                    "Cannot resolve FONTS.VGA base; supply source.base_archive"
                )
    effective, _ = overlay_shape_archives(selected, base)
    return effective
