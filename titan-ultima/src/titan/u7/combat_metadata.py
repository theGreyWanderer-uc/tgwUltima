"""Raw combat-table authoring and ordered effective-world weapon/ammo/armor resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from titan.u7.gameplay_metadata import (
    U7GameplayTable,
    U7GameplayFormat,
    read_gameplay_table,
    gameplay_count_prefix,
    validate_gameplay_format,
)
from titan.u7.shape_archive import find_archive

COMBAT_RECORD_WIDTHS = {"weapon": 21, "ammo": 13, "armor": 10}
COMBAT_FILENAMES = {"weapon": "WEAPONS.DAT", "ammo": "AMMO.DAT", "armor": "ARMOR.DAT"}


@dataclass(frozen=True)
class U7CombatRecord:
    """A shape-keyed complete record; a final FF byte explicitly removes its definition."""

    raw: bytes
    source: str
    offset: int
    data_format: U7GameplayFormat = "exult"

    @property
    def shape(self) -> int:
        return int.from_bytes(self.raw[:2], "little")

    @property
    def deleted(self) -> bool:
        return self.data_format == "exult" and self.raw[-1] == 255


@dataclass(frozen=True)
class U7CombatLayer:
    """One original counted stream, retaining superseded rows, headers and trailing bytes."""

    kind: str
    table: U7GameplayTable
    source: str = ""

    @classmethod
    def from_bytes(
        cls,
        kind: str,
        data: bytes,
        *,
        source: str = "",
        strict: bool = False,
        data_format: U7GameplayFormat = "exult",
    ) -> U7CombatLayer:
        if kind not in COMBAT_RECORD_WIDTHS:
            raise ValueError(f"U7 combat metadata: unknown table kind {kind}")
        table = read_gameplay_table(
            data,
            COMBAT_RECORD_WIDTHS[kind],
            COMBAT_FILENAMES[kind],
            data_format=data_format,
        )
        if strict and (
            table.declared_count is None or table.parsed_count != table.declared_count
        ):
            raise ValueError(
                f"U7 combat metadata: incomplete {kind} table in {source}: {'; '.join(table.warnings)}"
            )
        return cls(kind, table, source)

    @property
    def records(self) -> tuple[U7CombatRecord, ...]:
        return tuple(
            U7CombatRecord(
                raw,
                self.source,
                self.table.header_size + index * self.table.record_width,
                self.table.data_format,
            )
            for index, raw in enumerate(self.table.records)
        )

    def to_bytes(self) -> bytes:
        """Return the original stream byte for byte, including unknown and trailing bytes."""
        return self.table.raw

    def replace_record(self, index: int, raw: bytes) -> U7CombatLayer:
        """Return an edited copy of one complete row; preserve header and every other byte."""
        self._check_edit(raw)
        if not 0 <= index < self.table.parsed_count:
            raise IndexError(
                "U7 combat metadata: replacement record index out of bounds"
            )
        start = self.table.header_size + index * self.table.record_width
        return self.from_bytes(
            self.kind,
            self.table.raw[:start] + raw + self.table.raw[start + len(raw) :],
            source=self.source,
            strict=True,
            data_format=self.table.data_format,
        )

    def append_record(self, raw: bytes) -> U7CombatLayer:
        """Append an override/removal before retained trailing data; expand the count only as needed."""
        self._check_edit(raw)
        count = self.table.parsed_count + 1
        prefix = gameplay_count_prefix(
            count,
            self.table.data_format,
            extended=self.table.header_size == 3,
        )
        data = prefix + b"".join(self.table.records) + raw + self.table.trailing_data
        return self.from_bytes(
            self.kind,
            data,
            source=self.source,
            strict=True,
            data_format=self.table.data_format,
        )

    def removal_record(self, shape: int) -> bytes:
        """Construct an Exult removal row without changing any source stream."""
        if self.table.data_format != "exult":
            raise ValueError("U7 combat metadata: removal records require Exult format")
        if not 0 <= shape <= 65535:
            raise ValueError("U7 combat metadata: removal shape outside u16")
        return (
            shape.to_bytes(2, "little") + bytes(self.table.record_width - 3) + b"\xff"
        )

    def _check_edit(self, raw: bytes) -> None:
        if (
            self.table.declared_count is None
            or self.table.parsed_count != self.table.declared_count
        ):
            raise ValueError(
                "U7 combat metadata: cannot edit an incomplete source table"
            )
        if len(raw) != self.table.record_width:
            raise ValueError(
                f"U7 combat metadata: expected {self.table.record_width} record bytes"
            )


@dataclass(frozen=True)
class U7CombatMetadata:
    """Effective world definitions resolved from ordered raw layers; sources remain independently editable."""

    kind: str
    layers: tuple[U7CombatLayer, ...] = ()
    data_format: U7GameplayFormat = "exult"

    def __post_init__(self) -> None:
        validate_gameplay_format(self.data_format)
        if any(layer.table.data_format != self.data_format for layer in self.layers):
            raise ValueError("U7 combat metadata: cannot mix retail and Exult layers")

    @classmethod
    def from_dir(
        cls,
        kind: str,
        static_dir: str | Path,
        *,
        patch_dir: str | Path | None = None,
        strict: bool = True,
        data_format: U7GameplayFormat = "exult",
    ) -> U7CombatMetadata:
        if kind not in COMBAT_FILENAMES:
            raise ValueError(f"U7 combat metadata: unknown table kind {kind}")
        paths: list[Path] = []
        for directory in (static_dir, patch_dir):
            path = (
                find_archive(Path(directory), COMBAT_FILENAMES[kind])
                if directory is not None
                else None
            )
            if path is not None and path.resolve() not in {p.resolve() for p in paths}:
                paths.append(path)
        return cls(
            kind,
            tuple(
                U7CombatLayer.from_bytes(
                    kind,
                    path.read_bytes(),
                    source=str(path),
                    strict=strict,
                    data_format=data_format,
                )
                for path in paths
            ),
            data_format,
        )

    @property
    def records(self) -> dict[int, U7CombatRecord]:
        result: dict[int, U7CombatRecord] = {}
        for layer in self.layers:
            if layer.kind != self.kind:
                raise ValueError(
                    "U7 combat metadata: cannot overlay different table kinds"
                )
            for record in layer.records:
                if record.deleted:
                    result.pop(record.shape, None)
                else:
                    result[record.shape] = record
        return result

    @property
    def warnings(self) -> list[str]:
        return [
            f"{layer.source}: {warning}"
            for layer in self.layers
            for warning in layer.table.warnings
        ]

    def resolved_bytes(self) -> bytes:
        """Serialize the effective inspection view; use layer.to_bytes for lossless source round-trips."""
        records = self.records
        count = len(records)
        prefix = gameplay_count_prefix(count, self.data_format)
        return prefix + b"".join(record.raw for record in records.values())
