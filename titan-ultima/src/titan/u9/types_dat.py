"""Lossless reader for Ultima IX ``static/TYPES.DAT``.

The file has an eight-byte count header followed by capacity for 8,192
fixed-size records. Only the header-declared prefix participates in runtime
lookups; the remaining slots are retained so a read/write cycle is exact.

Field names in this module are Titan terminology. The two runtime-owned cells
at offsets ``0x00`` and ``0x0E`` are persisted but rebuilt by the game while
loading, so Titan reports rather than interprets them.
"""

from __future__ import annotations

__all__ = ["U9TypeRecord", "U9TypesDat", "U9TypesDatError", "U9TypesHeader"]

import os
import struct
from dataclasses import dataclass

HEADER_SIZE = 8
RECORD_SIZE = 16
HEADER_STRUCT = "<II"
RECORD_STRUCT = "<IHHHBBBBH"
MAX_RECORDS = 8192
MAX_NPC_RECORDS = 352
EXPECTED_SIZE = HEADER_SIZE + RECORD_SIZE * MAX_RECORDS

_DEBUG_FILL_POINTER = 0xCDCDCDCD
_KNOWN_OBJECT_FLAGS = {
    0x0001: "visibility_override",
    0x0002: "actor_only_collision",
    0x0004: "partial_collision",
    0x0008: "non_camera_blocker",
    0x0010: "portal_blocker",
    0x0020: "art_finalized",
    0x0040: "optional_detail",
    0x0080: "container",
    0x0100: "mesh_collision",
}
_KNOWN_OBJECT_FLAG_MASK = sum(_KNOWN_OBJECT_FLAGS)


class U9TypesDatError(Exception):
    """Raised on malformed ``static/TYPES.DAT`` data."""


@dataclass(frozen=True)
class U9TypesHeader:
    """The count header which selects the runtime-visible record prefix."""

    active_type_count: int
    npc_type_count: int
    raw: bytes


@dataclass(frozen=True)
class U9TypeRecord:
    """One losslessly retained 16-byte physical type slot."""

    type_id: int
    is_active: bool
    runtime_handler_pointer_cell: int
    base_type_id: int
    default_model_id: int
    object_flags: int
    mass_code: int
    volume_code: int
    legacy_document_code: int
    durability_points: int
    runtime_handler_mask_cell: int
    raw: bytes
    warnings: tuple[str, ...] = ()

    @property
    def record_representation(self) -> str:
        """Stable representation label used by forensic exports."""
        return "fixed_16_byte_record"

    @property
    def object_flag_names(self) -> tuple[str, ...]:
        """Names of the source-supported low object-flag bits that are set."""
        return tuple(
            name for bit, name in _KNOWN_OBJECT_FLAGS.items() if self.object_flags & bit
        )

    @property
    def unmapped_object_flag_bits(self) -> int:
        """Set flag bits whose meaning has not yet been established."""
        return self.object_flags & ~_KNOWN_OBJECT_FLAG_MASK

    @property
    def runtime_pointer_state(self) -> str:
        """Classify the persisted cell that the loader replaces at runtime."""
        if self.runtime_handler_pointer_cell == 0:
            return "zero"
        if self.runtime_handler_pointer_cell == _DEBUG_FILL_POINTER:
            return "debug_fill"
        return "unexpected_stored_value"

    @property
    def can_drag(self) -> bool:
        """Whether the stored mass code passes the game's drag threshold."""
        return self.mass_code < 255

    @property
    def can_inventory(self) -> bool:
        """Whether the stored mass code passes the game's inventory threshold."""
        return self.mass_code < 254


class U9TypesDat:
    """Header-selected type records plus every retained physical slot."""

    def __init__(self, data: bytes) -> None:
        self._validate_size(data)
        active_type_count, npc_type_count = struct.unpack_from(HEADER_STRUCT, data)
        if active_type_count > MAX_RECORDS:
            raise U9TypesDatError(
                f"active type count {active_type_count} exceeds capacity {MAX_RECORDS}"
            )
        if npc_type_count > MAX_NPC_RECORDS:
            raise U9TypesDatError(
                f"NPC type count {npc_type_count} exceeds supported maximum "
                f"{MAX_NPC_RECORDS}"
            )

        self.raw = bytes(data)
        self.header = U9TypesHeader(
            active_type_count=active_type_count,
            npc_type_count=npc_type_count,
            raw=bytes(data[:HEADER_SIZE]),
        )

        slots: list[U9TypeRecord] = []
        for type_id in range(MAX_RECORDS):
            offset = HEADER_SIZE + type_id * RECORD_SIZE
            raw = bytes(data[offset : offset + RECORD_SIZE])
            values = struct.unpack(RECORD_STRUCT, raw)
            warnings = self._warnings_for(type_id, active_type_count, values)
            slots.append(
                U9TypeRecord(
                    type_id=type_id,
                    is_active=type_id < active_type_count,
                    runtime_handler_pointer_cell=values[0],
                    base_type_id=values[1],
                    default_model_id=values[2],
                    object_flags=values[3],
                    mass_code=values[4],
                    volume_code=values[5],
                    legacy_document_code=values[6],
                    durability_points=values[7],
                    runtime_handler_mask_cell=values[8],
                    raw=raw,
                    warnings=warnings,
                )
            )

        self.slots = tuple(slots)
        self.records = self.slots[:active_type_count]
        self.inactive_slots = self.slots[active_type_count:]
        self._model_to_types: dict[int, list[int]] = {}
        for record in self.records:
            if record.default_model_id:
                self._model_to_types.setdefault(record.default_model_id, []).append(
                    record.type_id
                )

    @staticmethod
    def _validate_size(data: bytes) -> None:
        if len(data) < HEADER_SIZE:
            raise U9TypesDatError(
                f"data too small to contain an 8-byte header: {len(data)} bytes"
            )
        payload = len(data) - HEADER_SIZE
        if payload % RECORD_SIZE:
            raise U9TypesDatError(
                f"{payload} bytes after the header is not a whole number of "
                f"{RECORD_SIZE}-byte records ({payload % RECORD_SIZE} left over)"
            )
        if len(data) != EXPECTED_SIZE:
            raise U9TypesDatError(
                f"expected {EXPECTED_SIZE} bytes "
                f"({HEADER_SIZE} + {RECORD_SIZE}*{MAX_RECORDS}), got {len(data)}"
            )

    @staticmethod
    def _warnings_for(
        type_id: int, active_type_count: int, values: tuple[int, ...]
    ) -> tuple[str, ...]:
        pointer_cell, base_type_id, _, object_flags, *_, handler_mask = values
        warnings: list[str] = []
        if type_id < active_type_count and base_type_id >= active_type_count:
            warnings.append("base_type_id_out_of_active_range")
        if object_flags & ~_KNOWN_OBJECT_FLAG_MASK:
            warnings.append("unmapped_object_flag_bits")
        if pointer_cell not in (0, _DEBUG_FILL_POINTER):
            warnings.append("unexpected_runtime_pointer_cell")
        if handler_mask:
            warnings.append("stored_runtime_handler_mask")
        return tuple(warnings)

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9TypesDat:
        """Read and decode a ``TYPES.DAT`` file."""
        with open(filepath, "rb") as file:
            return cls(file.read())

    def to_bytes(self) -> bytes:
        """Return the original file exactly, including inactive capacity slots."""
        return self.raw

    def type_ids_for_model(self, model_id: int) -> list[int]:
        """Return active type IDs that use ``model_id`` as their default model."""
        return list(self._model_to_types.get(model_id, ()))

    def record_for(self, type_id: int) -> U9TypeRecord | None:
        """Return an active record, or ``None`` for an inactive/out-of-range ID."""
        if 0 <= type_id < len(self.records):
            return self.records[type_id]
        return None

    def slot_for(self, type_id: int) -> U9TypeRecord | None:
        """Return a physical slot, including inactive capacity, when present."""
        if 0 <= type_id < len(self.slots):
            return self.slots[type_id]
        return None

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)
