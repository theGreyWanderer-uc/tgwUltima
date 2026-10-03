"""Lossless reader for Ultima IX ``static/areas.flx``.

Each used entry begins with a signed 32-bit kind.  Kind 1 stores one gameplay
zone as a common header, an optional fixed-capacity encounter table, and one or
more axis-aligned world boxes.  The shipped archive uses no other kind.

Titan decodes kind 1 according to the retail loader and retains unknown kinds
as opaque records.  Every entry and the enclosing FLX archive can therefore be
written back byte for byte without normalizing inactive slots, structure
padding, reserved cells, or stale editor-era values.
"""

from __future__ import annotations

__all__ = [
    "BOX_ZONE_KIND",
    "ENCOUNTER_SLOT_COUNT",
    "U9Areas",
    "U9AreasError",
    "U9EncounterChoice",
    "U9EncounterTable",
    "U9GameplayZone",
    "U9StoredPosition",
    "U9UnknownZone",
    "U9ZoneBox",
]

import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

BOX_ZONE_KIND = 1
ENCOUNTER_SLOT_COUNT = 12
MAX_ZONE_BOXES = 8

_ZONE_TRIGGER_FLAG = 0x00000001
_ZONE_ENCOUNTER_FLAG = 0x00000002
_KNOWN_ZONE_FLAGS = _ZONE_TRIGGER_FLAG | _ZONE_ENCOUNTER_FLAG

_POSITION = struct.Struct("<iih2s")
_ENCOUNTER_CHOICE = struct.Struct("<HH")
_BOX_SIZE = _POSITION.size * 2
_ENCOUNTER_TABLE_SIZE = 62
_ZONE_PREFIX_SIZE = 28
_ZONE_SUFFIX_SIZE = 12


class U9AreasError(Exception):
    """Raised when an ``areas.flx`` entry cannot be framed safely."""


@dataclass(frozen=True)
class U9StoredPosition:
    """One 12-byte integer XYZ position, including its retained padding."""

    x: int
    y: int
    z: int
    padding: bytes
    raw_data: bytes

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9EncounterChoice:
    """One fixed encounter-table slot containing an object type and weight."""

    slot_index: int
    object_type_id: int
    selection_weight: int
    raw_data: bytes

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9EncounterTable:
    """The optional 62-byte, twelve-slot encounter selection table."""

    reserved_prefix: int
    declared_choice_count: int
    choice_slots: tuple[U9EncounterChoice, ...]
    reserved_suffix: int
    stored_flags: int
    raw_data: bytes

    @property
    def active_choices(self) -> tuple[U9EncounterChoice, ...]:
        if not 0 <= self.declared_choice_count <= len(self.choice_slots):
            return ()
        return self.choice_slots[: self.declared_choice_count]

    @property
    def active_weight_total(self) -> int | None:
        if not 0 <= self.declared_choice_count <= len(self.choice_slots):
            return None
        return sum(choice.selection_weight for choice in self.active_choices)

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9ZoneBox:
    """One 24-byte axis-aligned box stored as two integer XYZ corners."""

    box_index: int
    entry_offset: int
    corners: tuple[U9StoredPosition, U9StoredPosition]
    raw_data: bytes

    @property
    def minimum(self) -> tuple[int, int, int]:
        first, second = self.corners
        return (min(first.x, second.x), min(first.y, second.y), min(first.z, second.z))

    @property
    def maximum(self) -> tuple[int, int, int]:
        first, second = self.corners
        return (max(first.x, second.x), max(first.y, second.y), max(first.z, second.z))

    @property
    def uses_unbounded_height(self) -> bool:
        """Whether the runtime expands the stored Z interval to full height."""
        return abs(self.corners[0].z - self.corners[1].z) <= 5

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9GameplayZone:
    """One decoded kind-1 gameplay zone from ``areas.flx``."""

    zone_id: int
    record_kind: int
    stored_zone_id: int
    path_marker_position: U9StoredPosition
    stored_flags: int
    encounter_chance_percent: int
    encounter_table: U9EncounterTable | None
    stored_total_weight: int
    world_map_id: int
    declared_box_count: int
    boxes: tuple[U9ZoneBox, ...]
    trailing_data: bytes
    raw_data: bytes

    @property
    def trigger_enabled(self) -> bool:
        return bool(self.stored_flags & _ZONE_TRIGGER_FLAG)

    @property
    def has_encounter_table(self) -> bool:
        return bool(self.stored_flags & _ZONE_ENCOUNTER_FLAG)

    @property
    def unclassified_flag_bits(self) -> int:
        return self.stored_flags & ~_KNOWN_ZONE_FLAGS

    @property
    def stored_zone_id_status(self) -> str:
        return "matches_entry_index" if self.stored_zone_id == self.zone_id else "mismatch"

    @property
    def path_marker_position_status(self) -> str:
        return "loaded" if self.trigger_enabled else "inactive_retained"

    @property
    def encounter_chance_status(self) -> str:
        return "active" if self.has_encounter_table else "inactive_retained"

    def structural_warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        if self.stored_zone_id != self.zone_id:
            warnings.append("stored_zone_id_mismatch")
        if not 1 <= self.declared_box_count <= MAX_ZONE_BOXES:
            warnings.append("declared_box_count_out_of_range")
        if self.declared_box_count != len(self.boxes):
            warnings.append("declared_box_count_mismatch")
        if self.has_encounter_table:
            table = self.encounter_table
            if table is None:
                warnings.append("missing_encounter_table")
            else:
                if not 0 <= table.declared_choice_count <= ENCOUNTER_SLOT_COUNT:
                    warnings.append("encounter_choice_count_out_of_range")
                if table.active_weight_total != self.stored_total_weight:
                    warnings.append("encounter_weight_total_mismatch")
            if not 0 <= self.encounter_chance_percent <= 100:
                warnings.append("encounter_chance_out_of_range")
        if self.trailing_data:
            warnings.append("trailing_data")
        return tuple(warnings)

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9UnknownZone:
    """An opaque entry whose leading kind is unsupported by the retail game."""

    zone_id: int
    record_kind: int
    raw_data: bytes

    def structural_warnings(self) -> tuple[str, ...]:
        return ("unsupported_record_kind",)

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


U9ZoneRecord = U9GameplayZone | U9UnknownZone


class U9Areas:
    """Lossless entry-indexed view of ``static/areas.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive = archive
        self._records: dict[int, U9ZoneRecord] = {}
        for zone_id in archive.used_entry_indices():
            self._records[zone_id] = _parse_record(
                zone_id, archive.read_entry(zone_id)
            )

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Areas:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as error:
            raise U9AreasError(str(error)) from error

    @property
    def num_entries(self) -> int:
        return self.archive.num_entries

    @property
    def used_zone_ids(self) -> tuple[int, ...]:
        return tuple(self._records)

    def record(self, zone_id: int) -> U9ZoneRecord | None:
        return self._records.get(zone_id)

    def records(self) -> tuple[U9ZoneRecord, ...]:
        return tuple(self._records.values())

    def zones(self) -> tuple[U9GameplayZone, ...]:
        return tuple(
            record
            for record in self._records.values()
            if isinstance(record, U9GameplayZone)
        )

    def unsupported_records(self) -> tuple[U9UnknownZone, ...]:
        return tuple(
            record
            for record in self._records.values()
            if isinstance(record, U9UnknownZone)
        )

    def to_bytes(self) -> bytes:
        """Return the complete original FLX archive byte for byte."""
        return self.archive.to_bytes()


def _take(data: bytes, offset: int, size: int, label: str, zone_id: int) -> bytes:
    end = offset + size
    if end > len(data):
        raise U9AreasError(
            f"areas.flx entry {zone_id} truncates {label} at {offset:#x}: "
            f"needs {size} bytes, only {len(data) - offset} remain"
        )
    return data[offset:end]


def _parse_position(data: bytes, offset: int, label: str, zone_id: int) -> U9StoredPosition:
    raw = _take(data, offset, _POSITION.size, label, zone_id)
    x, y, z, padding = _POSITION.unpack(raw)
    return U9StoredPosition(x=x, y=y, z=z, padding=padding, raw_data=raw)


def _parse_encounter_table(
    data: bytes, offset: int, zone_id: int
) -> tuple[U9EncounterTable, int]:
    start = offset
    raw = _take(data, offset, _ENCOUNTER_TABLE_SIZE, "encounter table", zone_id)
    reserved_prefix, declared_choice_count = struct.unpack_from("<ii", raw, 0)
    slots: list[U9EncounterChoice] = []
    slot_offset = 8
    for slot_index in range(ENCOUNTER_SLOT_COUNT):
        slot_raw = raw[slot_offset : slot_offset + _ENCOUNTER_CHOICE.size]
        object_type_id, selection_weight = _ENCOUNTER_CHOICE.unpack(slot_raw)
        slots.append(
            U9EncounterChoice(
                slot_index=slot_index,
                object_type_id=object_type_id,
                selection_weight=selection_weight,
                raw_data=slot_raw,
            )
        )
        slot_offset += _ENCOUNTER_CHOICE.size
    reserved_suffix, stored_flags = struct.unpack_from("<iH", raw, slot_offset)
    return (
        U9EncounterTable(
            reserved_prefix=reserved_prefix,
            declared_choice_count=declared_choice_count,
            choice_slots=tuple(slots),
            reserved_suffix=reserved_suffix,
            stored_flags=stored_flags,
            raw_data=raw,
        ),
        start + _ENCOUNTER_TABLE_SIZE,
    )


def _parse_box(data: bytes, offset: int, box_index: int, zone_id: int) -> U9ZoneBox:
    raw = _take(data, offset, _BOX_SIZE, "zone box", zone_id)
    first = _parse_position(raw, 0, "first box corner", zone_id)
    second = _parse_position(raw, _POSITION.size, "second box corner", zone_id)
    return U9ZoneBox(
        box_index=box_index,
        entry_offset=offset,
        corners=(first, second),
        raw_data=raw,
    )


def _parse_known_zone(zone_id: int, data: bytes) -> U9GameplayZone:
    _take(data, 0, _ZONE_PREFIX_SIZE + _ZONE_SUFFIX_SIZE, "zone header", zone_id)
    record_kind, stored_zone_id = struct.unpack_from("<ii", data, 0)
    path_marker_position = _parse_position(data, 8, "path marker position", zone_id)
    stored_flags, encounter_chance_percent = struct.unpack_from("<Ii", data, 20)
    offset = _ZONE_PREFIX_SIZE

    encounter_table = None
    if stored_flags & _ZONE_ENCOUNTER_FLAG:
        encounter_table, offset = _parse_encounter_table(data, offset, zone_id)

    suffix = _take(data, offset, _ZONE_SUFFIX_SIZE, "zone suffix", zone_id)
    stored_total_weight, world_map_id, declared_box_count = struct.unpack("<iii", suffix)
    offset += _ZONE_SUFFIX_SIZE
    if declared_box_count < 0:
        raise U9AreasError(
            f"areas.flx entry {zone_id} has negative box count {declared_box_count}"
        )
    required = declared_box_count * _BOX_SIZE
    _take(data, offset, required, "zone box array", zone_id)
    boxes = tuple(
        _parse_box(data, offset + box_index * _BOX_SIZE, box_index, zone_id)
        for box_index in range(declared_box_count)
    )
    offset += required
    return U9GameplayZone(
        zone_id=zone_id,
        record_kind=record_kind,
        stored_zone_id=stored_zone_id,
        path_marker_position=path_marker_position,
        stored_flags=stored_flags,
        encounter_chance_percent=encounter_chance_percent,
        encounter_table=encounter_table,
        stored_total_weight=stored_total_weight,
        world_map_id=world_map_id,
        declared_box_count=declared_box_count,
        boxes=boxes,
        trailing_data=data[offset:],
        raw_data=data,
    )


def _parse_record(zone_id: int, data: bytes) -> U9ZoneRecord:
    if len(data) < 4:
        raise U9AreasError(
            f"areas.flx entry {zone_id} is {len(data)} byte(s); needs a 4-byte kind"
        )
    record_kind = struct.unpack_from("<i", data, 0)[0]
    if record_kind != BOX_ZONE_KIND:
        return U9UnknownZone(
            zone_id=zone_id, record_kind=record_kind, raw_data=data
        )
    return _parse_known_zone(zone_id, data)
