"""Read native U8 saved-state Flex files loose or inside U8SAVE archives."""

from __future__ import annotations

import struct
from pathlib import Path

from titan.flex import FLEX_COUNT_OFFSET, FLEX_HEADER_SIZE, FlexArchive
from titan.u8.save import U8SaveArchive
from titan.errors import InvalidDataError


def read_u8_state_bytes(filepath: str | Path, entry_name: str) -> bytes:
    """Read one state file using the shared strict native save archive reader."""
    data = Path(filepath).read_bytes()
    if not U8SaveArchive.is_save_file(data):
        return data
    archive = U8SaveArchive.from_bytes(data)
    payload = archive.get_data(entry_name)
    if payload is not None:
        return payload
    raise InvalidDataError(f"U8 saved state: save archive has no {entry_name}")


def parse_u8_state_flex(data: bytes, label: str, record_count: int) -> FlexArchive:
    """Validate an expected native state directory and every nonempty record's bounds."""
    if len(data) < FLEX_HEADER_SIZE:
        raise InvalidDataError(f"{label}: truncated Flex header")
    count = struct.unpack_from("<I", data, FLEX_COUNT_OFFSET)[0]
    if count != record_count:
        raise InvalidDataError(
            f"{label}: expected {record_count} Flex records, found {count}"
        )
    table_end = FLEX_HEADER_SIZE + count * 8
    if table_end > len(data):
        raise InvalidDataError(f"{label}: truncated Flex record table")
    for index in range(count):
        offset, size = struct.unpack_from("<II", data, FLEX_HEADER_SIZE + index * 8)
        if size and (offset < table_end or offset + size > len(data)):
            raise InvalidDataError(f"{label}: record {index} has invalid bounds")
    try:
        return FlexArchive.from_bytes(data)
    except ValueError as error:
        raise InvalidDataError(f"{label}: {error}") from error


def save_u8_state_report(report: str, output: Path, sources: tuple[Path, ...]) -> Path:
    """Write *report* to a new file *output*; never a source file or an existing file."""
    if output.resolve() in {source.resolve() for source in sources}:
        raise ValueError("U8 saved state report: output must differ from source files")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as destination:
        destination.write(report)
    return output
