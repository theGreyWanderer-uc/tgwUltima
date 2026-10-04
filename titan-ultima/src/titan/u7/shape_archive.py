"""Resolve U7 shape archives against the original game's sparse patch base."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from titan.u7.flex import U7FlexArchive

# Custom libraries (for example MINIMAPS.VGA) need not have a retail base.
RETAIL_SHAPE_ARCHIVES = {
    "shapes.vga",
    "faces.vga",
    "gumps.vga",
    "sprites.vga",
    "paperdol.vga",
    "fonts.vga",
    "mainshp.flx",
    "endshape.flx",
}


def find_archive(directory: Path, filename: str) -> Path | None:
    """Find an archive without depending on filename case."""
    if directory.is_dir():
        return next(
            (
                p
                for p in directory.iterdir()
                if p.is_file() and p.name.lower() == filename.lower()
            ),
            None,
        )
    return None


def is_patch_archive(path: Path) -> bool:
    """Recognize archives inside Exult's patch/mod directory structure."""
    return any(part.lower() in {"patch", "mods"} for part in path.parent.parts)


def discover_base_archive(
    path: Path, configured_static: str | None = None
) -> Path | None:
    """Infer the matching retail archive for a file inside an Exult patch."""
    if not is_patch_archive(path):
        return None
    for ancestor in path.resolve().parents:
        for dirname in ("STATIC", "static"):
            candidate = find_archive(ancestor / dirname, path.name)
            if candidate is not None and candidate.resolve() != path.resolve():
                return candidate
    if configured_static:
        candidate = find_archive(Path(configured_static).expanduser(), path.name)
        if candidate is not None and candidate.resolve() != path.resolve():
            return candidate
    return None


def overlay_shape_archives(
    selected: U7FlexArchive, base: U7FlexArchive | None
) -> tuple[U7FlexArchive, int]:
    """Fill absent/empty patch records in memory; never change either source."""
    if base is None:
        return selected, 0
    records: list[bytes] = []
    filled = 0
    for index in range(max(len(selected.records), len(base.records))):
        patch_record = selected.records[index] if index < len(selected.records) else b""
        base_record = base.records[index] if index < len(base.records) else b""
        records.append(patch_record or base_record)
        filled += bool(base_record and not patch_record)
    if not filled and len(records) == len(selected.records):
        return selected, 0
    effective = U7FlexArchive()
    effective.title = selected.title
    effective.magic2 = selected.magic2
    effective.records = records
    return effective, filled


@dataclass
class U7ShapeArchive:
    """Keep the writable patch separate from its effective shape inventory."""

    selected: U7FlexArchive
    base: U7FlexArchive | None
    effective: U7FlexArchive
    base_fill_count: int

    @classmethod
    def from_file(
        cls,
        filepath: str,
        *,
        base_archive: str | None = None,
        configured_static: str | None = None,
        strict: bool = False,
        require_patch_base: bool = False,
        infer_base: bool = True,
    ) -> U7ShapeArchive:
        path = Path(filepath).expanduser()
        base_path = (
            Path(base_archive).expanduser()
            if base_archive
            else discover_base_archive(path, configured_static)
            if infer_base
            else None
        )
        if base_path is not None and base_path.resolve() == path.resolve():
            raise ValueError("The base archive must be distinct from the patch archive")
        if (
            require_patch_base
            and is_patch_archive(path)
            and path.name.lower() in RETAIL_SHAPE_ARCHIVES
            and base_path is None
        ):
            raise ValueError(
                "Cannot resolve this patch's base archive; supply --base-archive "
                "before allocating or replacing shapes"
            )
        selected = U7FlexArchive.from_file(str(path), strict=strict)
        base = (
            U7FlexArchive.from_file(str(base_path), strict=strict)
            if base_path is not None
            else None
        )
        effective, filled = overlay_shape_archives(selected, base)
        return cls(selected, base, effective, filled)
