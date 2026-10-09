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


def u8_shape_export_stem(shape_num: int, fallback: str | None = None) -> str:
    """Keep native slot IDs in filenames, adding a sanitized bundled class label."""
    name = load_u8_shape_names().get(shape_num)
    if name:
        safe = FlexArchive._safe_filename(name)
        if safe:
            return f"{shape_num:04d}_{safe}"
    return fallback or f"{shape_num:04d}"


def u8_shape_stem_from_path(path: str) -> str:
    """Preserve standalone shape stems; label purely decimal native slot stems."""
    stem = Path(path).stem
    try:
        number = int(stem, 10)
    except ValueError:
        return stem
    return u8_shape_export_stem(number, fallback=stem)
