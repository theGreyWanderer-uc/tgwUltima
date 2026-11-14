"""Loaders shared by more than one U7 command family.

Game, mod and Exult path resolution lives in :mod:`titan.u7.install`.
"""

from __future__ import annotations

__all__ = [
    "_infer_static_dir_for_data_file",
    "_load_container_shapes",
    "_load_shape_count",
    "_load_u7_shape_archive",
    "_resolve_loose_data_file",
]

import sys
from pathlib import Path
from types import SimpleNamespace

from titan.u7.shape_archive import U7ShapeArchive
from titan.u7 import install


def _load_u7_shape_archive(
    filepath: str, args: SimpleNamespace, *, strict: bool = False
) -> U7ShapeArchive | None:
    """Use the same patch inheritance for reading and allocating shapes."""
    configured_static, _ = install.resolve_u7_static_and_palette(
        getattr(args, "game", "bg")
    )
    try:
        resolved = U7ShapeArchive.from_file(
            filepath,
            base_archive=getattr(args, "base_archive", None),
            configured_static=getattr(args, "static", None) or configured_static,
            strict=strict,
            require_patch_base=True,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: Could not resolve U7 shape archive: {error}", file=sys.stderr)
        return None
    if resolved.base_fill_count:
        print(
            f"Sparse shape overlay: inherited {resolved.base_fill_count} base records"
        )
    return resolved


def _resolve_loose_data_file(path: str, filename: str) -> str:
    """Resolve either a direct file path or a directory containing *filename*."""
    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / filename
    return str(candidate)


def _infer_static_dir_for_data_file(filepath: str) -> str | None:
    """Infer a sibling STATIC directory from a loose GAMEDAT file path."""
    parent = Path(filepath).resolve().parent
    candidates = [
        parent.with_name("STATIC"),
        parent.parent / "STATIC",
    ]
    for candidate in candidates:
        if (candidate / "TFA.DAT").is_file() or (candidate / "tfa.dat").is_file():
            return str(candidate)
    return None


def _load_container_shapes(
    args: SimpleNamespace,
    fallback_static: str | None = None,
) -> set[int] | None:
    """Load TFA container shape IDs for reliable NPC inventory skipping."""
    static_dir = getattr(args, "static", None)
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not static_dir:
        static_dir = fallback_static
    if static_dir:
        from titan.u7.typeflag import U7TypeFlags

        tfa = U7TypeFlags.from_dir(static_dir)
        container_shapes = {
            entry.shape_num for entry in tfa.entries if entry.shape_class == 6
        }
        print(f"TFA:    {len(container_shapes)} container shapes loaded")
        return container_shapes

    print("TFA:    (no --static, using heuristic container detection)")
    return None


def _load_shape_count(
    args: SimpleNamespace,
    fallback_static: str | None = None,
) -> int | None:
    """Load SHAPES.VGA record count for filtering non-shape pseudo IDs."""
    static_dir = getattr(args, "static", None)
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not static_dir:
        static_dir = fallback_static
    if not static_dir:
        return None

    from titan.u7.flex import U7FlexArchive

    for name in ("SHAPES.VGA", "shapes.vga"):
        path = Path(static_dir) / name
        if path.is_file():
            return len(U7FlexArchive.from_file(str(path)).records)
    return None
