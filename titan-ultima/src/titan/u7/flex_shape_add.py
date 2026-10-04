"""Add standalone U7 shapes to an available record in a U7 Flex archive."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from titan.u7.flex import U7FlexArchive


def add_shape_to_first_available_record(
    archive: U7FlexArchive,
    shape_data: bytes,
    *,
    minimum_record_index: int = 0,
    maximum_record_index: int | None = None,
    base_archive: U7FlexArchive | None = None,
) -> int:
    """Store shape bytes in the lowest permitted empty record, or append them."""
    if minimum_record_index < 0:
        raise ValueError(
            "Minimum U7 Flex shape record index must be non-negative: "
            f"{minimum_record_index}"
        )

    if maximum_record_index is not None and maximum_record_index < minimum_record_index:
        raise ValueError("U7 Flex shape record range is empty")
    stop_index = max(
        len(archive.records), len(base_archive.records) if base_archive else 0
    )
    if maximum_record_index is not None:
        stop_index = min(stop_index, maximum_record_index + 1)
    for record_index in range(minimum_record_index, stop_index):
        selected_record = (
            archive.records[record_index]
            if record_index < len(archive.records)
            else b""
        )
        base_record = (
            base_archive.records[record_index]
            if base_archive and record_index < len(base_archive.records)
            else b""
        )
        if not selected_record and not base_record:
            archive.records.extend([b""] * (record_index + 1 - len(archive.records)))
            archive.records[record_index] = shape_data
            return record_index

    record_index = max(
        minimum_record_index,
        len(archive.records),
        len(base_archive.records) if base_archive else 0,
    )
    if maximum_record_index is not None and record_index > maximum_record_index:
        raise ValueError(
            f"No free U7 Flex shape record in slots "
            f"{minimum_record_index} through {maximum_record_index}"
        )
    archive.records.extend([b""] * (record_index - len(archive.records)))
    archive.records.append(shape_data)
    return record_index


def add_shape_at_record_index(
    archive: U7FlexArchive,
    shape_data: bytes,
    record_index: int,
    *,
    replace: bool = False,
    base_archive: U7FlexArchive | None = None,
) -> int:
    """Store shape bytes at one record index, growing gaps and guarding replacement."""
    if record_index < 0:
        raise ValueError(
            f"U7 Flex shape record index must be non-negative: {record_index}"
        )

    selected_record = (
        archive.records[record_index] if record_index < len(archive.records) else b""
    )
    base_record = (
        base_archive.records[record_index]
        if base_archive and record_index < len(base_archive.records)
        else b""
    )
    if (selected_record or base_record) and not replace:
        raise FileExistsError(
            f"U7 Flex shape record {record_index} is occupied; use --replace to overwrite it"
        )
    missing_records = record_index + 1 - len(archive.records)
    if missing_records > 0:
        archive.records.extend([b""] * missing_records)

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
