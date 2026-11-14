"""Small file helpers shared across games: lookups, digests and CSV output."""

from __future__ import annotations

__all__ = ["case_insensitive_child", "rows_to_csv", "sha256_file", "write_csv"]

import csv
import hashlib
import io
import os
from pathlib import Path


def case_insensitive_child(directory: Path, filename: str) -> Path | None:
    """Find *filename* in *directory* without assuming the host's filename casing."""
    wanted = filename.casefold()
    try:
        return next(
            (child for child in directory.iterdir() if child.name.casefold() == wanted),
            None,
        )
    except OSError:
        return None


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Hash a file in one-megabyte blocks."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows_to_csv(rows: list[dict[str, object]]) -> str:
    """Render rows as CSV text using the first row's keys as the header."""
    buf = io.StringIO()
    if not rows:
        return ""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def write_csv(path: Path, records: list[dict]) -> None:
    """Write records to a UTF-8 CSV file; no records writes an empty file."""
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
