"""Shared constants, validation helpers and the common process header states."""

from __future__ import annotations

__all__ = [
    "U9ProcessDataError",
    "U9ProcessHeaderState",
    "U9ProcessWorldState",
    "U9ScriptedProcessState",
]

import math
import struct
from dataclasses import dataclass


CAMERA_VERSION = 2
MIN_PROCESS_TYPE = 1
MAX_PROCESS_TYPE = 0xE4
PROCESS_HEADER = struct.Struct("<9i100s")
PROCESS_WORLD_VERSION = 0
MAX_PROCESS_OBJECT_REFERENCES = 10
HANGING_OBJECT_PROCESS_TYPE = 61
SCRIPT_TIMER_PROCESS_TYPE = 62
PORTABLE_LIGHT_PROCESS_TYPE = 70
PLAYER_PROXIMITY_PROCESS_TYPE = 80
ANIMATION_CONTROLLER_PROCESS_TYPE = 98
# The Avatar's animation controller shares type 98's save and load routines
# (retail vtable slots 2/3: 0x0055C4F0 / 0x0055C7E0).
AVATAR_ANIMATION_CONTROLLER_PROCESS_TYPE = 213
ANIMATION_CONTROLLER_PROCESS_TYPES = frozenset(
    {ANIMATION_CONTROLLER_PROCESS_TYPE, AVATAR_ANIMATION_CONTROLLER_PROCESS_TYPE}
)
# Movement controllers whose retail save routine is the base movement save
# (0x00579B80) or the flying save (0x00494290), read from each type's vtable.
BASE_MOVEMENT_CONTROLLER_PROCESS_TYPES = frozenset(
    {
        82,
        84,
        88,
        89,
        90,
        156,
        164,
        167,
        172,
        175,
        177,
        183,
        184,
        185,
        186,
        199,
        200,
        201,
    }
)
FLYING_MOVEMENT_CONTROLLER_PROCESS_TYPES = frozenset({83, 91, 92, 93, 94, 102, 178})
EXTENDED_MOVEMENT_CONTROLLER_PROCESS_TYPES = frozenset(
    {85, 86, 87, 95, 96, 97, 155, 166, 168, 170, 171, 173, 174, 176, 211}
)
MOVEMENT_CONTROLLER_PROCESS_TYPES = (
    BASE_MOVEMENT_CONTROLLER_PROCESS_TYPES
    | FLYING_MOVEMENT_CONTROLLER_PROCESS_TYPES
    | EXTENDED_MOVEMENT_CONTROLLER_PROCESS_TYPES
)
SCRIPTED_PROCESS_VERSION = 0
SCRIPTED_PROCESS_STATE = struct.Struct("<iiiii128si")
# Processes whose retail save (0x0065D320) is the world state followed by the
# scripted-object state and nothing else.
SCRIPTED_OBJECT_PROCESS_TYPES = frozenset({50, 53, 54, 58, 202})
CLOCK_ANIMATION_PROCESS_TYPE = 57
# Processes that run an NPC's scheduled activity. All share one retail save
# routine (0x00402970): world state, then a fixed 300-byte block.
NPC_ACTIVITY_PROCESS_TYPES = frozenset(
    {
        6,
        24,
        27,
        28,
        29,
        30,
        31,
        32,
        34,
        36,
        75,
        78,
        99,
        157,
        159,
        160,
        179,
        180,
        187,
        188,
        189,
        190,
        196,
        198,
    }
)
# Processes that perform an NPC's current action (activity step). All share
# one retail save routine (0x004016D0): world state, then 396 bytes.
NPC_ACTION_PROCESS_TYPES = frozenset(
    {15, 22, 23, 25, 26, 33, 37, 51, 52, 76, 77, 79, 100, 158, 161, 162, 181, 182}
    | {191, 192, 193, 194}
)
DOOR_TIMER_PROCESS_TYPE = 197
PATHFINDER_PROCESS_TYPE = 1
SKELETON_REFORM_PROCESS_TYPE = 55
FLOATING_LANTERN_PROCESS_TYPE = 13
PARTICLE_ITEM_VARIANT_RECORD = struct.Struct("<Hi")
PARTICLE_FORCE_SLOT_COUNT = 4
PARTICLE_SLAVE_GENERATION_SLOT_COUNT = 10
PARTICLE_CHILD_SLOT_COUNT = 10


class U9ProcessDataError(Exception):
    """Raised when a deterministic process-data section is malformed."""


def _float32(value: float) -> float:
    """``value`` rounded to the nearest 32-bit float, as the game stores it."""
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


def _require_bytes(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or offset + size > len(data):
        raise U9ProcessDataError(
            f"truncated {label}: needs bytes 0x{offset:X}..0x{offset + size:X}, "
            f"file has 0x{len(data):X}"
        )


@dataclass(frozen=True)
class U9ProcessHeaderState:
    """Common fixed header at the start of a typed process payload."""

    process_type: int
    process_id: int
    category: int
    paused_frames: int
    timeout_frames: int
    run_count: int
    next_process_id: int
    previous_process_id: int
    execution_mask: int
    state_flags: int
    name: str
    raw_name: bytes
    offset: int
    serialized_prefix_size: int = 4

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ProcessHeaderState:
        return cls.from_prefixed_bytes(data, offset, prefix_size=4)

    @classmethod
    def from_prefixed_bytes(
        cls, data: bytes, offset: int, *, prefix_size: int
    ) -> U9ProcessHeaderState:
        """Read a common process header after its type and subtype prefix."""
        _require_bytes(data, offset, 4, "process type")
        (process_type,) = struct.unpack_from("<i", data, offset)
        if not MIN_PROCESS_TYPE <= process_type <= MAX_PROCESS_TYPE:
            raise U9ProcessDataError(
                f"invalid process type {process_type} at 0x{offset:X}"
            )
        if prefix_size < 4:
            raise U9ProcessDataError(
                f"invalid process header prefix size {prefix_size} at 0x{offset:X}"
            )

        header_offset = offset + prefix_size
        _require_bytes(data, header_offset, PROCESS_HEADER.size, "process header")
        values = PROCESS_HEADER.unpack_from(data, header_offset)
        raw_name = values[9]
        name = raw_name.split(b"\0", 1)[0].decode("cp1252")
        return cls(
            process_type=process_type,
            process_id=values[0],
            category=values[1],
            paused_frames=values[2],
            timeout_frames=values[3],
            run_count=values[4],
            next_process_id=values[5],
            previous_process_id=values[6],
            execution_mask=values[7],
            state_flags=values[8],
            name=name,
            raw_name=raw_name,
            offset=offset,
            serialized_prefix_size=prefix_size,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + self.serialized_prefix_size + PROCESS_HEADER.size


@dataclass(frozen=True)
class U9ProcessWorldState:
    """Shared map and object associations used by world-facing processes."""

    version: int
    object_reference_indices: tuple[int, ...]
    map_number: int
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9ProcessWorldState:
        _require_bytes(data, offset, 8, "process world-state header")
        version, association_count = struct.unpack_from("<ii", data, offset)
        if version != PROCESS_WORLD_VERSION:
            raise U9ProcessDataError(
                f"unsupported process world-state version {version} at 0x{offset:X}"
            )
        if not 0 <= association_count <= MAX_PROCESS_OBJECT_REFERENCES:
            raise U9ProcessDataError(
                f"implausible process object-association count {association_count}"
            )

        record_size = 12 + association_count * 4
        _require_bytes(data, offset, record_size, "process world state")
        indices = struct.unpack_from(f"<{association_count}i", data, offset + 8)
        for index in indices:
            if not 0 <= index < object_reference_count:
                raise U9ProcessDataError(
                    f"process object-reference index {index} is outside "
                    f"0..{object_reference_count - 1}"
                )
        (map_number,) = struct.unpack_from(
            "<i", data, offset + 8 + association_count * 4
        )
        if not -1 <= map_number <= 255:
            raise U9ProcessDataError(f"invalid process map number {map_number}")
        return cls(
            version=version,
            object_reference_indices=tuple(indices),
            map_number=map_number,
            offset=offset,
            end_offset=offset + record_size,
        )


def _validate_object_reference_index(
    index: int, object_reference_count: int, label: str
) -> None:
    if not 0 <= index < object_reference_count:
        raise U9ProcessDataError(
            f"{label} object-reference index {index} is outside "
            f"0..{object_reference_count - 1}"
        )


def _validate_finite(values: tuple[float, ...], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise U9ProcessDataError(f"{label} contains a non-finite value")


def _validate_byte_boolean(value: int, label: str) -> None:
    if value not in (0, 1):
        raise U9ProcessDataError(f"invalid {label} boolean byte {value}")


@dataclass(frozen=True)
class U9ScriptedProcessState:
    """Shared state for a process that invokes object scripting."""

    version: int
    primary_object_reference_index: int
    user_object_reference_index: int
    argument_1: int
    argument_2: int
    temporary_buffer: bytes
    state: int
    offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9ScriptedProcessState:
        _require_bytes(
            data, offset, SCRIPTED_PROCESS_STATE.size, "scripted-process state"
        )
        values = SCRIPTED_PROCESS_STATE.unpack_from(data, offset)
        if values[0] != SCRIPTED_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported scripted-process version {values[0]} at 0x{offset:X}"
            )
        _validate_object_reference_index(
            values[1], object_reference_count, "scripted-process primary"
        )
        _validate_object_reference_index(
            values[2], object_reference_count, "scripted-process user"
        )
        return cls(
            version=values[0],
            primary_object_reference_index=values[1],
            user_object_reference_index=values[2],
            argument_1=values[3],
            argument_2=values[4],
            temporary_buffer=values[5],
            state=values[6],
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + SCRIPTED_PROCESS_STATE.size


def _read_world_process_prefix(
    data: bytes,
    offset: int,
    process_types: frozenset[int],
    label: str,
    object_reference_count: int,
) -> tuple[U9ProcessHeaderState, U9ProcessWorldState]:
    header = U9ProcessHeaderState.from_bytes(data, offset)
    if header.process_type not in process_types:
        raise U9ProcessDataError(
            f"process type {header.process_type} is not a {label} process"
        )
    world_state = U9ProcessWorldState.from_bytes(
        data, header.end_offset, object_reference_count=object_reference_count
    )
    return header, world_state
