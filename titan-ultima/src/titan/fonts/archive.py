"""Resolve font templates using Exult's retail or bundled base plus patch."""

from __future__ import annotations

import os
import struct
from typing import Any
from pathlib import Path

from titan.fonts.exult_cfg import ExultGamePaths, find_exult_cfg, parse_exult_cfg
from titan.u7.flex import U7FlexArchive
from titan.u7.shape_archive import (
    discover_base_archive,
    find_archive,
    is_patch_archive,
    overlay_shape_archives,
)
from titan.errors import InvalidDataError

# exult/data/exult_flx.h; these live in the common EXULT.FLX, not a game bundle.
_BUNDLED_FONTS = {"fonts_original.vga": 29, "fonts_serif.vga": 30}


def game_paths(game: str) -> ExultGamePaths | None:
    cfg = find_exult_cfg()
    return parse_exult_cfg(cfg, game) if cfg else None


def _bundled_base(
    path: Path, paths: ExultGamePaths | None, install: Any = None
) -> U7FlexArchive:
    candidates: list[Path] = []
    configured = install.resources.get("exult_common_flx") if install else None
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
        raise InvalidDataError(f"Missing font record {index} in {bundle_path}")
    data = bundle.records[index]
    # Validate the nested Flex table before using the shared byte reader.
    if len(data) < 128:
        raise InvalidDataError(f"Invalid bundled font in {bundle_path}")
    count = struct.unpack_from("<I", data, 84)[0]
    table_end = 128 + count * 8
    if table_end > len(data):
        raise InvalidDataError("Truncated bundled font table")
    for i in range(count):
        offset, size = struct.unpack_from("<II", data, 128 + i * 8)
        if size and (offset < table_end or offset + size > len(data)):
            raise InvalidDataError("Invalid bundled font record bounds")
    return U7FlexArchive.from_bytes(data)


def read_font_archive(
    path: str | Path,
    *,
    game: str = "BG",
    base_archive: str | None = None,
    paths: ExultGamePaths | None = None,
    infer_base: bool = True,
    install: Any = None,
) -> U7FlexArchive:
    """Inspect effective slots without changing the sparse archive on disk.

    A patch archive's base is looked for in Exult's STATIC, else *install*'s
    (``titan._meta.configured_install``); Exult's own font slots come from
    *install*'s ``exult_common_flx``, else a standard Exult install's.
    """
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
        if not static and install is not None and install.resources.get("static"):
            static = str(install.resources["static"])
        base_path = discover_base_archive(selected_path, static)
        if selected_path.name.lower() in _BUNDLED_FONTS:
            base = _bundled_base(selected_path, paths, install)
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
