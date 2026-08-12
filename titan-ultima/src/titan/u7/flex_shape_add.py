"""Add standalone U7 shapes to the first available record in a U7 Flex archive."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from titan.u7.flex import U7FlexArchive


def add_shape_to_first_available_record(
    archive: U7FlexArchive,
    shape_data: bytes,
) -> int:
    """Store shape bytes in the lowest empty record, appending when no gap exists."""
    try:
        record_index = archive.records.index(b"")
        archive.records[record_index] = shape_data
    except ValueError:
        record_index = len(archive.records)
        archive.records.append(shape_data)
    return record_index


def add_shape_at_record_index(
    archive: U7FlexArchive,
    shape_data: bytes,
    record_index: int,
    *,
    replace: bool = False,
) -> int:
    """Store shape bytes at one record index, growing gaps and guarding replacement."""
    if record_index < 0:
        raise ValueError(
            f"U7 Flex shape record index must be non-negative: {record_index}"
        )

    missing_records = record_index + 1 - len(archive.records)
    if missing_records > 0:
        archive.records.extend([b""] * missing_records)
    elif archive.records[record_index] and not replace:
        raise FileExistsError(
            f"U7 Flex shape record {record_index} is occupied; use --replace to overwrite it"
        )

    archive.records[record_index] = shape_data
    return record_index


def save_u7_flex_atomically(archive: U7FlexArchive, output: str | Path) -> None:
    """Atomically replace a U7 Flex output after its complete bytes are written."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    archive_data = archive.to_bytes()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(archive_data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
