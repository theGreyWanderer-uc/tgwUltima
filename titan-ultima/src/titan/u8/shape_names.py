"""Bundled U8 usecode class labels shared by shape exports and browsing."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from titan.flex import FlexArchive

U8_USECODE_CLASS_NAMES_FILE = (
    Path(__file__).resolve().parent.parent
    / "dialogue/pipeline/resources/usecode_classes.csv"
)


@lru_cache(maxsize=1)
def load_u8_shape_names() -> dict[int, str]:
    """Return bundled usecode class labels by ID, not inferred object names."""
    path = U8_USECODE_CLASS_NAMES_FILE
    mapping: dict[int, str] = {}
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                try:
                    number = int((row.get("ID") or "").strip())
                except ValueError:
                    continue
                name = (row.get("Name") or "").strip()
                if name:
                    mapping[number] = name
    return mapping


U8_SHAPES_FLEX = "U8SHAPES.FLX"
"""The only archive whose slot numbers are usecode class IDs."""


def u8_flex_has_class_names(flex_path: str | Path) -> bool:
    """Whether slot *N* of this archive is usecode class *N* (U8SHAPES.FLX only).

    Gumps, fonts, mouse cursors and other Flex archives number their records
    from 0 too, but those numbers have nothing to do with usecode classes.
    """
    return Path(flex_path).name.upper() == U8_SHAPES_FLEX


def _sidecar_flex_source(shape_path: Path) -> str | None:
    """The ``Flex source:`` an ``extract_all`` sidecar records for *shape_path*."""
    sidecar = shape_path.with_name(f"{shape_path.stem}.meta.txt")
    try:
        with sidecar.open(encoding="utf-8") as stream:
            for line in stream:
                key, sep, value = line.partition(":")
                if sep and key.strip() == "Flex source":
                    value = value.strip()
                    return None if not value or value == "(unknown)" else value
    except OSError:
        return None
    return None


def u8_shape_export_stem(shape_num: int, fallback: str | None = None) -> str:
    """Keep native slot IDs in filenames, adding a sanitized bundled class label."""
    name = load_u8_shape_names().get(shape_num)
    if name:
        safe = FlexArchive._safe_filename(name)
        if safe:
            return f"{shape_num:04d}_{safe}"
    return fallback or f"{shape_num:04d}"


def u8_shape_stem_from_path(path: str) -> str:
    """Preserve standalone shape stems; label purely decimal native slot stems.

    A file whose ``.meta.txt`` sidecar names an archive other than U8SHAPES.FLX
    (e.g. ``0037.shp`` extracted from U8GUMPS.FLX) keeps its plain number.
    """
    p = Path(path)
    stem = p.stem
    try:
        number = int(stem, 10)
    except ValueError:
        return stem
    source = _sidecar_flex_source(p)
    if source is not None and not u8_flex_has_class_names(source):
        return stem
    return u8_shape_export_stem(number, fallback=stem)
