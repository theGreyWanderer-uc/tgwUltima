"""Counted U7 gameplay tables with explicit Exult extensions and partial-read diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

U7GameplayFormat = Literal["exult", "retail"]


def validate_gameplay_format(data_format: str) -> U7GameplayFormat:
    """Select a known gameplay format explicitly; never infer retail from file names or length."""
    if data_format == "exult":
        return "exult"
    if data_format == "retail":
        return "retail"
    raise ValueError(
        f"U7 gameplay metadata: data_format must be retail or exult: {data_format!r}"
    )


def gameplay_count_prefix(
    count: int, data_format: U7GameplayFormat, *, extended: bool = False
) -> bytes:
    """Encode a retail u8 count or Exult extended count without changing dialect."""
    validate_gameplay_format(data_format)
    limit = 255 if data_format == "retail" else 65535
    if not 0 <= count <= limit:
        raise ValueError(f"U7 gameplay metadata: {data_format} count exceeds {limit}")
    if data_format == "exult" and (extended or count >= 255):
        return b"\xff" + count.to_bytes(2, "little")
    return bytes([count])


@dataclass
class U7GameplayTable:
    """Retain raw counted-table bytes and distinguish complete records from short tails."""

    filename: str
    raw: bytes
    record_width: int
    declared_count: int | None
    header_size: int
    records: tuple[bytes, ...]
    partial_record: bytes = b""
    trailing_data: bytes = b""
    headerless: bool = False
    data_format: U7GameplayFormat = "exult"

    @property
    def parsed_count(self) -> int:
        """Count complete stored records, including later-skipped removal entries."""
        return len(self.records)

    @property
    def consumed_bytes(self) -> int:
        """Return the header plus complete records, excluding incomplete/trailing data."""
        return self.header_size + self.parsed_count * self.record_width

    @property
    def warnings(self) -> list[str]:
        """Report incomplete count headers/records and bytes beyond the declared table."""
        warnings = []
        if self.declared_count is None and not self.headerless:
            warnings.append(f"{self.filename} count header is incomplete.")
        elif (
            self.declared_count is not None and self.parsed_count < self.declared_count
        ):
            warnings.append(
                f"{self.filename} records are incomplete: declares {self.declared_count}, "
                f"parsed {self.parsed_count} complete records; "
                f"{len(self.partial_record)} bytes of the next record remain."
            )
        elif self.partial_record:
            warnings.append(f"{self.filename} has an incomplete headerless record.")
        if self.trailing_data:
            warnings.append(
                f"{self.filename} has {len(self.trailing_data)} trailing bytes."
            )
        return warnings


def read_gameplay_table(
    data: bytes,
    record_width: int,
    filename: str,
    *,
    headerless: bool = False,
    data_format: U7GameplayFormat = "exult",
) -> U7GameplayTable:
    """Read an original u8 count or Exult FF/u16 count without guessing a version header."""
    data_format = validate_gameplay_format(data_format)
    if record_width <= 0:
        raise ValueError("Gameplay table record width must be positive")
    count: int | None = None
    header = 0
    if not headerless:
        if not data or (data_format == "exult" and data[0] == 255 and len(data) < 3):
            return U7GameplayTable(
                filename,
                data,
                record_width,
                None,
                len(data),
                (),
                data_format=data_format,
            )
        header = 3 if data_format == "exult" and data[0] == 255 else 1
        count = int.from_bytes(data[1:3], "little") if header == 3 else data[0]
    available = (len(data) - header) // record_width
    parsed = available if count is None else min(count, available)
    end = header + parsed * record_width
    incomplete = headerless or (count is not None and parsed < count)
    return U7GameplayTable(
        filename,
        data,
        record_width,
        count,
        header,
        tuple(data[p : p + record_width] for p in range(header, end, record_width)),
        partial_record=data[end:] if incomplete else b"",
        trailing_data=b"" if incomplete else data[end:],
        headerless=headerless,
        data_format=data_format,
    )


class U7GameplayMetadata:
    """Expose counted-table diagnostics on gameplay readers without discarding partial input."""

    def __init__(
        self,
        table: U7GameplayTable | None = None,
        *,
        data_format: U7GameplayFormat = "exult",
    ) -> None:
        self.table = table
        self._data_format = (
            table.data_format
            if table is not None
            else validate_gameplay_format(data_format)
        )
        self._source_warnings: list[str] = []

    @property
    def declared_count(self) -> int | None:
        """Return the stored count, or None for absent/explicitly headerless sources."""
        return self.table.declared_count if self.table else None

    @property
    def data_format(self) -> U7GameplayFormat:
        """The selected serialization dialect; defaults remain Exult for compatibility."""
        return self._data_format

    @property
    def warnings(self) -> list[str]:
        """Include table-boundary diagnostics and any inherited source warnings."""
        return [*(self.table.warnings if self.table else []), *self._source_warnings]
