"""Read deterministic prefix sections from U9 ``processes.dat``."""

from __future__ import annotations

__all__ = [
    "OBJECT_REFERENCE_DATA_OFFSET",
    "U9CameraControlState",
    "U9CameraEffectState",
    "U9CameraState",
    "U9AnimationCallbackState",
    "U9AnimationControllerProcessState",
    "U9AnimationTrackState",
    "U9HangingObjectProcessState",
    "U9ObjectReferenceEntry",
    "U9ObjectReferenceTable",
    "U9ParticleCameraFilterTextureState",
    "U9ParticleForcePresetState",
    "U9ParticleForceState",
    "U9ParticleGenerationState",
    "U9ParticleInstanceState",
    "U9ParticleItemVariantState",
    "U9ParticlePresetState",
    "U9ParticleRampSlotState",
    "U9ParticleRecordCollection",
    "U9ParticleRecordCollections",
    "U9ParticleProcessState",
    "U9PlayerProximityProcessState",
    "U9PortableLightProcessState",
    "U9ProcessDataPrefix",
    "U9ProcessHeaderState",
    "U9ProcessRecordPrefix",
    "U9ProcessWorldState",
    "U9ScriptedProcessState",
    "U9ScriptTimerProcessState",
    "U9KinematicTrackState",
    "U9TargetingState",
    # Compatibility exports retained for callers using the earlier names.
    "HANDLE_DATA_OFFSET",
    "U9ItemHandleEntry",
    "U9ItemHandleTable",
    "U9ProcessDataError",
]

import math
import os
import struct
from dataclasses import dataclass

OBJECT_REFERENCE_DATA_OFFSET = 0x27F74
OBJECT_REFERENCE_VERSION = 1
CAMERA_VERSION = 2
CAMERA_HEADER = struct.Struct("<I3f3fiiB4fi")
CAMERA_EFFECT_VERSION_BITS = {
    0x3F800000: (1.0, 302),
    0x3F8CCCCD: (1.1, 310),
}
MAX_CAMERA_EFFECT_COUNT = 32
CAMERA_CONTROL_VERSIONS = {0, 1, 2}
CAMERA_CONTROL_BASE_SIZE = 28
CAMERA_CONTROL_EXTENDED_SIZE = 180
TARGETING_STATE = struct.Struct("<Iiii3f3fii")
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
WORLD_PROCESS_TYPES = frozenset(
    {
        HANGING_OBJECT_PROCESS_TYPE,
        SCRIPT_TIMER_PROCESS_TYPE,
        PORTABLE_LIGHT_PROCESS_TYPE,
        PLAYER_PROXIMITY_PROCESS_TYPE,
        104,
    }
)
SCRIPTED_PROCESS_VERSION = 0
SCRIPTED_PROCESS_STATE = struct.Struct("<iiiii128si")
HANGING_OBJECT_PROCESS_VERSION = 2
# Packed layout: setup values, five scalar/X/Y/Z quaternions, live motion
# state, two configuration words, facing vector, and four reserved words.
HANGING_OBJECT_PROCESS_STATE = struct.Struct(
    "<iiiifiiifI20f2fifiifiiifiifiiiffiIIi3f4I"
)
SCRIPT_TIMER_PROCESS_VERSION = 1
SCRIPT_TIMER_PROCESS_STATE = struct.Struct("<i12I")
PORTABLE_LIGHT_PROCESS_VERSION = 0
PORTABLE_LIGHT_PROCESS_STATE = struct.Struct("<iiHfIIII")
PLAYER_PROXIMITY_PROCESS_VERSION = 1
PLAYER_PROXIMITY_PROCESS_STATE = struct.Struct("<iffI3fiiii4I")
ANIMATION_CONTROLLER_VERSION_BITS = 0x3F99999A
ANIMATION_TRACK_VERSION_BITS = 0x3F800000
ANIMATION_TRACK_TIMING_STATE = struct.Struct("<fiiiififiiB")
ANIMATION_CALLBACK_STATE = struct.Struct("<iII")
ANIMATION_LOCK_SLOT_COUNT = 32
MAX_ANIMATION_LIMB_FILTER_COUNT = 1024
ANIMATION_TRACK_COUNT = 5
MAX_KINEMATIC_TRACK_COUNT = 1024
KINEMATIC_TRACK_VERSION_BITS = 0x3F800000
KINEMATIC_TRACK_STATE = struct.Struct("<fi3B10f3f3f12fB")
PARTICLE_PROCESS_TYPE = 104
PARTICLE_PROCESS_VERSIONS = frozenset({3, 5})
PARTICLE_PROCESS_STATE_SIZE = 33
PARTICLE_PRESET_RECORD_SIZES = {3: 1484, 5: 1490}
PARTICLE_FORCE_PRESET_RECORD_SIZE = 97
PARTICLE_FORCE_RECORD_SIZE = 24
PARTICLE_GENERATION_RECORD_SIZE = 124
PARTICLE_INSTANCE_RECORD_SIZE = 196
PARTICLE_FORCE_PRESET_RECORD = struct.Struct("<iBiii3ffii3fi3f3fiiii")
PARTICLE_FORCE_RECORD = struct.Struct("<ii3fi")
PARTICLE_GENERATION_RECORD = struct.Struct("<31i")
PARTICLE_INSTANCE_RECORD = struct.Struct("<3i10i2i3f3f3f3f4f4f2iBHI4iIB5i")
PARTICLE_ITEM_VARIANT_RECORD = struct.Struct("<Hi")
PARTICLE_CAMERA_FILTER_TEXTURE_RECORD = struct.Struct("<4H8BI")
PARTICLE_RAMP_SLOT_RECORD = struct.Struct("<4i3fi3fiBiBi3i3Bi4i3Bi2i")
PARTICLE_ITEM_VARIANT_COUNT = 10
PARTICLE_RAMP_SLOT_COUNT = 10
PARTICLE_PRESET_VERSION_5_ITEM_EXTENSION_SIZE = 2
PARTICLE_PRESET_VERSION_5_RAMP_EXTENSION_SIZE = 4
PARTICLE_FORCE_SLOT_COUNT = 4
PARTICLE_SLAVE_GENERATION_SLOT_COUNT = 10
PARTICLE_CHILD_SLOT_COUNT = 10
OBJECT_REFERENCE_RECORD = struct.Struct("<iii")
MIN_OBJECT_REFERENCE_COUNT = 2
MAX_OBJECT_REFERENCE_COUNT = 0x10000

# Deprecated compatibility constants. New code should use the format-oriented
# names above; values and serialized behavior are unchanged.
HANDLE_DATA_OFFSET = OBJECT_REFERENCE_DATA_OFFSET
HANDLE_VERSION = OBJECT_REFERENCE_VERSION
HANDLE_RECORD = OBJECT_REFERENCE_RECORD
MIN_HANDLE_COUNT = MIN_OBJECT_REFERENCE_COUNT
MAX_HANDLE_COUNT = MAX_OBJECT_REFERENCE_COUNT


class U9ProcessDataError(Exception):
    """Raised when a deterministic process-data section is malformed."""


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


@dataclass(frozen=True)
class U9HangingObjectProcessState:
    """A type-61 hanging-object process with swing and turn motion state."""

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    scripted_state: U9ScriptedProcessState
    version: int
    is_swingable: bool
    swing_period: int
    maximum_swing_angle: int
    swing_envelope_period: float
    turning_type: int
    turn_period: int
    maximum_turn_angle: int
    turn_envelope_period: float
    object_status_flags: int
    initial_orientation: tuple[float, float, float, float]
    new_orientation: tuple[float, float, float, float]
    old_orientation: tuple[float, float, float, float]
    pitch_orientation: tuple[float, float, float, float]
    yaw_orientation: tuple[float, float, float, float]
    pitch: float
    yaw: float
    is_swinging: bool
    swing_envelope_value: float
    swing_time_ms: int
    swing_envelope_time_ms: int
    swing_time_constant: float
    pitch_changed: bool
    last_direction: int
    is_turning: bool
    turn_envelope_value: float
    turn_time_ms: int
    turn_envelope_time_ms: int
    turn_time_constant: float
    yaw_changed: bool
    is_collided: bool
    hit_magnitude: int
    swing_magnitude_fraction: float
    turn_magnitude_fraction: float
    last_wind: int
    swing_configuration_bits: int
    turn_configuration_bits: int
    reversed: bool
    facing: tuple[float, float, float]
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9HangingObjectProcessState:
        header = U9ProcessHeaderState.from_bytes(data, offset)
        if header.process_type != HANGING_OBJECT_PROCESS_TYPE:
            raise U9ProcessDataError(
                f"expected hanging-object process type {HANGING_OBJECT_PROCESS_TYPE}, "
                f"found {header.process_type}"
            )
        world_state = U9ProcessWorldState.from_bytes(
            data,
            header.end_offset,
            object_reference_count=object_reference_count,
        )
        scripted_state = U9ScriptedProcessState.from_bytes(
            data,
            world_state.end_offset,
            object_reference_count=object_reference_count,
        )
        payload_offset = scripted_state.end_offset
        _require_bytes(
            data,
            payload_offset,
            HANGING_OBJECT_PROCESS_STATE.size,
            "hanging-object process",
        )
        values = HANGING_OBJECT_PROCESS_STATE.unpack_from(data, payload_offset)
        if values[0] != HANGING_OBJECT_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported hanging-object version {values[0]} at "
                f"0x{payload_offset:X}"
            )

        initial_orientation = tuple(values[10:14])
        new_orientation = tuple(values[14:18])
        old_orientation = tuple(values[18:22])
        pitch_orientation = tuple(values[22:26])
        yaw_orientation = tuple(values[26:30])
        facing = tuple(values[53:56])
        finite_values = (
            values[4],
            values[8],
            *initial_orientation,
            *new_orientation,
            *old_orientation,
            *pitch_orientation,
            *yaw_orientation,
            values[30],
            values[31],
            values[33],
            values[36],
            values[40],
            values[43],
            values[47],
            values[48],
            *facing,
        )
        _validate_finite(finite_values, "hanging-object motion state")
        return cls(
            header=header,
            world_state=world_state,
            scripted_state=scripted_state,
            version=values[0],
            is_swingable=bool(values[1]),
            swing_period=values[2],
            maximum_swing_angle=values[3],
            swing_envelope_period=values[4],
            turning_type=values[5],
            turn_period=values[6],
            maximum_turn_angle=values[7],
            turn_envelope_period=values[8],
            object_status_flags=values[9],
            initial_orientation=initial_orientation,
            new_orientation=new_orientation,
            old_orientation=old_orientation,
            pitch_orientation=pitch_orientation,
            yaw_orientation=yaw_orientation,
            pitch=values[30],
            yaw=values[31],
            is_swinging=bool(values[32]),
            swing_envelope_value=values[33],
            swing_time_ms=values[34],
            swing_envelope_time_ms=values[35],
            swing_time_constant=values[36],
            pitch_changed=bool(values[37]),
            last_direction=values[38],
            is_turning=bool(values[39]),
            turn_envelope_value=values[40],
            turn_time_ms=values[41],
            turn_envelope_time_ms=values[42],
            turn_time_constant=values[43],
            yaw_changed=bool(values[44]),
            is_collided=bool(values[45]),
            hit_magnitude=values[46],
            swing_magnitude_fraction=values[47],
            turn_magnitude_fraction=values[48],
            last_wind=values[49],
            swing_configuration_bits=values[50],
            turn_configuration_bits=values[51],
            reversed=bool(values[52]),
            facing=facing,
            reserved=(values[56], values[57], values[58], values[59]),
            offset=offset,
            end_offset=payload_offset + HANGING_OBJECT_PROCESS_STATE.size,
        )

    @property
    def configured_swingable(self) -> bool:
        return bool(self.swing_configuration_bits & 0x01)

    @property
    def configured_swing_period(self) -> int:
        return (self.swing_configuration_bits >> 1) & 0x3F

    @property
    def configured_maximum_swing_angle(self) -> int:
        return (self.swing_configuration_bits >> 7) & 0x3F

    @property
    def configured_swing_half_life(self) -> int:
        return (self.swing_configuration_bits >> 13) & 0x3F

    @property
    def configured_turning_type(self) -> int:
        return self.turn_configuration_bits & 0x07

    @property
    def configured_turn_period(self) -> int:
        return (self.turn_configuration_bits >> 3) & 0x3F

    @property
    def configured_turn_limit_is_degrees(self) -> bool:
        return bool(self.turn_configuration_bits & 0x200)

    @property
    def configured_turn_limit(self) -> int:
        return (self.turn_configuration_bits >> 10) & 0x3F

    @property
    def configured_turn_half_life(self) -> int:
        return (self.turn_configuration_bits >> 16) & 0x3F


@dataclass(frozen=True)
class U9ScriptTimerProcessState:
    """A type-62 scripted timer with two-phase timing state."""

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    scripted_state: U9ScriptedProcessState
    version: int
    timer_flags: int
    phase_1_duration: int
    dual_mode: int
    time_system: int
    phase_2_duration: int
    accumulated_time: int
    has_started: bool
    phase: int
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9ScriptTimerProcessState:
        header = U9ProcessHeaderState.from_bytes(data, offset)
        if header.process_type != SCRIPT_TIMER_PROCESS_TYPE:
            raise U9ProcessDataError(
                f"expected script-timer process type {SCRIPT_TIMER_PROCESS_TYPE}, "
                f"found {header.process_type}"
            )
        world_state = U9ProcessWorldState.from_bytes(
            data,
            header.end_offset,
            object_reference_count=object_reference_count,
        )
        scripted_state = U9ScriptedProcessState.from_bytes(
            data,
            world_state.end_offset,
            object_reference_count=object_reference_count,
        )
        payload_offset = scripted_state.end_offset
        _require_bytes(
            data,
            payload_offset,
            SCRIPT_TIMER_PROCESS_STATE.size,
            "script-timer process",
        )
        values = SCRIPT_TIMER_PROCESS_STATE.unpack_from(data, payload_offset)
        if values[0] != SCRIPT_TIMER_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported script-timer version {values[0]} at 0x{payload_offset:X}"
            )
        return cls(
            header=header,
            world_state=world_state,
            scripted_state=scripted_state,
            version=values[0],
            timer_flags=values[1],
            phase_1_duration=values[2],
            dual_mode=values[3],
            time_system=values[4],
            phase_2_duration=values[5],
            accumulated_time=values[6],
            has_started=bool(values[7]),
            phase=values[8],
            reserved=(values[9], values[10], values[11], values[12]),
            offset=offset,
            end_offset=payload_offset + SCRIPT_TIMER_PROCESS_STATE.size,
        )

    @property
    def runs_continuously(self) -> bool:
        return bool(self.timer_flags & 0x01)

    @property
    def starts_in_fast_area(self) -> bool:
        return bool(self.timer_flags & 0x02)

    @property
    def fast_area_stop_flag(self) -> bool:
        return bool(self.timer_flags & 0x04)

    @property
    def is_quiet_outside_fast_area(self) -> bool:
        return bool(self.timer_flags & 0x08)

    @property
    def configured_dual_percentage(self) -> int:
        return ((self.timer_flags >> 4) & 0x0F) * 10

    @property
    def configured_time_system(self) -> int:
        return (self.timer_flags >> 8) & 0x07

    @property
    def configured_duration(self) -> int:
        return self.timer_flags >> 16


@dataclass(frozen=True)
class U9PortableLightProcessState:
    """A type-70 portable-light process and its fuel/flare state."""

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    light_object_reference_index: int
    maximum_fuel: int
    current_fuel: float
    update_elapsed: int
    flare_elapsed: int
    flare_duration: int
    flags: int
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9PortableLightProcessState:
        header = U9ProcessHeaderState.from_bytes(data, offset)
        if header.process_type != PORTABLE_LIGHT_PROCESS_TYPE:
            raise U9ProcessDataError(
                f"expected portable-light process type {PORTABLE_LIGHT_PROCESS_TYPE}, "
                f"found {header.process_type}"
            )
        world_state = U9ProcessWorldState.from_bytes(
            data,
            header.end_offset,
            object_reference_count=object_reference_count,
        )
        payload_offset = world_state.end_offset
        _require_bytes(
            data,
            payload_offset,
            PORTABLE_LIGHT_PROCESS_STATE.size,
            "portable-light process",
        )
        values = PORTABLE_LIGHT_PROCESS_STATE.unpack_from(data, payload_offset)
        if values[0] != PORTABLE_LIGHT_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported portable-light version {values[0]} at "
                f"0x{payload_offset:X}"
            )
        _validate_object_reference_index(
            values[1], object_reference_count, "portable-light"
        )
        _validate_finite((values[3],), "portable-light fuel")
        return cls(
            header=header,
            world_state=world_state,
            version=values[0],
            light_object_reference_index=values[1],
            maximum_fuel=values[2],
            current_fuel=values[3],
            update_elapsed=values[4],
            flare_elapsed=values[5],
            flare_duration=values[6],
            flags=values[7],
            offset=offset,
            end_offset=payload_offset + PORTABLE_LIGHT_PROCESS_STATE.size,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def uses_skeletal_flame(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def is_flaring(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def is_automatic(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def has_manual_override(self) -> bool:
        return bool(self.flags & 0x10)


@dataclass(frozen=True)
class U9PlayerProximityProcessState:
    """A type-80 player-proximity process with scripted-object state."""

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    scripted_state: U9ScriptedProcessState
    version: int
    enter_distance_squared: float
    exit_distance_squared: float
    uses_double_threshold: bool
    location: tuple[float, float, float]
    x: int
    y: int
    idle_count: int
    enabled: bool
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9PlayerProximityProcessState:
        header = U9ProcessHeaderState.from_bytes(data, offset)
        if header.process_type != PLAYER_PROXIMITY_PROCESS_TYPE:
            raise U9ProcessDataError(
                f"expected player-proximity process type "
                f"{PLAYER_PROXIMITY_PROCESS_TYPE}, found {header.process_type}"
            )
        world_state = U9ProcessWorldState.from_bytes(
            data,
            header.end_offset,
            object_reference_count=object_reference_count,
        )
        scripted_state = U9ScriptedProcessState.from_bytes(
            data,
            world_state.end_offset,
            object_reference_count=object_reference_count,
        )
        payload_offset = scripted_state.end_offset
        _require_bytes(
            data,
            payload_offset,
            PLAYER_PROXIMITY_PROCESS_STATE.size,
            "player-proximity process",
        )
        values = PLAYER_PROXIMITY_PROCESS_STATE.unpack_from(data, payload_offset)
        if values[0] != PLAYER_PROXIMITY_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported player-proximity version {values[0]} at "
                f"0x{payload_offset:X}"
            )
        location = (values[4], values[5], values[6])
        _validate_finite(
            (values[1], values[2], *location), "player-proximity distances/location"
        )
        return cls(
            header=header,
            world_state=world_state,
            scripted_state=scripted_state,
            version=values[0],
            enter_distance_squared=values[1],
            exit_distance_squared=values[2],
            uses_double_threshold=bool(values[3]),
            location=location,
            x=values[7],
            y=values[8],
            idle_count=values[9],
            enabled=bool(values[10]),
            reserved=(values[11], values[12], values[13], values[14]),
            offset=offset,
            end_offset=payload_offset + PLAYER_PROXIMITY_PROCESS_STATE.size,
        )


@dataclass(frozen=True)
class U9AnimationCallbackState:
    """One callback selector and its two stored animation-event parameters."""

    callback_id: int
    parameter_1: int
    parameter_2: int


@dataclass(frozen=True)
class U9AnimationTrackState:
    """One optional active animation track in a type-98 controller."""

    version: float
    animation_id: int
    rate_scale: float | None
    current_time_ms: int | None
    previous_event_time_ms: int | None
    frame_time_ms: int | None
    length_ms: int | None
    rotation_blend_amount: float | None
    rotation_blend_duration_ms: int | None
    translation_blend_amount: float | None
    translation_blend_duration_ms: int | None
    blend_time_ms: int | None
    reverse: bool | None
    event_mask: int | None
    callbacks: tuple[U9AnimationCallbackState, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9AnimationTrackState:
        _require_bytes(data, offset, 8, "animation track header")
        version_bits, animation_id = struct.unpack_from("<Ii", data, offset)
        if version_bits != ANIMATION_TRACK_VERSION_BITS:
            version = struct.unpack_from("<f", data, offset)[0]
            raise U9ProcessDataError(
                f"unsupported animation-track version {version} at 0x{offset:X}"
            )
        version = struct.unpack_from("<f", data, offset)[0]
        cursor = offset + 8
        if animation_id == -1:
            return cls(
                version=version,
                animation_id=animation_id,
                rate_scale=None,
                current_time_ms=None,
                previous_event_time_ms=None,
                frame_time_ms=None,
                length_ms=None,
                rotation_blend_amount=None,
                rotation_blend_duration_ms=None,
                translation_blend_amount=None,
                translation_blend_duration_ms=None,
                blend_time_ms=None,
                reverse=None,
                event_mask=None,
                callbacks=(),
                offset=offset,
                end_offset=cursor,
            )

        _require_bytes(
            data,
            cursor,
            ANIMATION_TRACK_TIMING_STATE.size + 4 + 4 * ANIMATION_CALLBACK_STATE.size,
            "active animation track",
        )
        timing = ANIMATION_TRACK_TIMING_STATE.unpack_from(data, cursor)
        _validate_byte_boolean(timing[10], "animation-track reverse")
        cursor += ANIMATION_TRACK_TIMING_STATE.size
        (event_mask,) = struct.unpack_from("<i", data, cursor)
        cursor += 4
        callbacks: list[U9AnimationCallbackState] = []
        for _ in range(4):
            callback = ANIMATION_CALLBACK_STATE.unpack_from(data, cursor)
            callbacks.append(U9AnimationCallbackState(*callback))
            cursor += ANIMATION_CALLBACK_STATE.size
        _validate_finite(
            (timing[0], timing[5], timing[7]), "animation-track blend state"
        )
        return cls(
            version=version,
            animation_id=animation_id,
            rate_scale=timing[0],
            current_time_ms=timing[1],
            previous_event_time_ms=timing[2],
            frame_time_ms=timing[3],
            length_ms=timing[4],
            rotation_blend_amount=timing[5],
            rotation_blend_duration_ms=timing[6],
            translation_blend_amount=timing[7],
            translation_blend_duration_ms=timing[8],
            blend_time_ms=timing[9],
            reverse=bool(timing[10]),
            event_mask=event_mask,
            callbacks=tuple(callbacks),
            offset=offset,
            end_offset=cursor,
        )

    @property
    def active(self) -> bool:
        return self.animation_id != -1


@dataclass(frozen=True)
class U9KinematicTrackState:
    """One fixed 124-byte limb-orientation controller record."""

    version: float
    limb_id: int
    constrain_pitch: bool
    constrain_roll: bool
    constrain_yaw: bool
    pitch_range: tuple[float, float]
    roll_range: tuple[float, float]
    yaw_range: tuple[float, float]
    rotation_rates: tuple[float, float, float]
    notice_range: float
    look_point: tuple[float, float, float]
    current_angles: tuple[float, float, float]
    reference_transform: tuple[float, ...]
    shutting_down: bool
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9KinematicTrackState:
        _require_bytes(
            data, offset, KINEMATIC_TRACK_STATE.size, "kinematic animation track"
        )
        values = KINEMATIC_TRACK_STATE.unpack_from(data, offset)
        version_bits = struct.unpack_from("<I", data, offset)[0]
        if version_bits != KINEMATIC_TRACK_VERSION_BITS:
            raise U9ProcessDataError(
                f"unsupported kinematic-track version {values[0]} at 0x{offset:X}"
            )
        for index, label in enumerate(
            ("constrain-pitch", "constrain-roll", "constrain-yaw"), start=2
        ):
            _validate_byte_boolean(values[index], f"kinematic-track {label}")
        _validate_byte_boolean(values[33], "kinematic-track shutting-down")
        _validate_finite(tuple(values[5:33]), "kinematic animation track")
        return cls(
            version=values[0],
            limb_id=values[1],
            constrain_pitch=bool(values[2]),
            constrain_roll=bool(values[3]),
            constrain_yaw=bool(values[4]),
            pitch_range=(values[5], values[6]),
            roll_range=(values[7], values[8]),
            yaw_range=(values[9], values[10]),
            rotation_rates=(values[11], values[12], values[13]),
            notice_range=values[14],
            look_point=(values[15], values[16], values[17]),
            current_angles=(values[18], values[19], values[20]),
            reference_transform=tuple(values[21:33]),
            shutting_down=bool(values[33]),
            offset=offset,
            end_offset=offset + KINEMATIC_TRACK_STATE.size,
        )


@dataclass(frozen=True)
class U9AnimationControllerProcessState:
    """A type-98 layered animation controller with five playback tracks."""

    header: U9ProcessHeaderState
    version: float
    world_state: U9ProcessWorldState
    object_reference_index: int
    initial_position: tuple[float, float, float]
    calculates_transforms: bool
    shutting_down: bool
    last_animation_id: int
    animation_root_position: tuple[float, float, float]
    translation_scale: tuple[float, float, float]
    scales_translation: bool
    upper_lock_count: int
    upper_lock_slots: tuple[int, ...]
    lower_lock_count: int
    lower_lock_slots: tuple[int, ...]
    current_translation: tuple[float, float, float]
    applies_events: bool
    forces_animations_to_stop: bool
    attached_element_id: int
    parent_process_id: int
    child_process_id: int
    included_limb_ids: tuple[int, ...]
    excluded_limb_ids: tuple[int, ...]
    animation_tracks: tuple[U9AnimationTrackState, ...]
    kinematic_tracks: tuple[U9KinematicTrackState, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9AnimationControllerProcessState:
        _require_bytes(data, offset, 8, "animation-controller type/version")
        process_type, version_bits = struct.unpack_from("<iI", data, offset)
        if process_type != ANIMATION_CONTROLLER_PROCESS_TYPE:
            raise U9ProcessDataError(
                f"expected animation-controller process type "
                f"{ANIMATION_CONTROLLER_PROCESS_TYPE}, found {process_type}"
            )
        version = struct.unpack_from("<f", data, offset + 4)[0]
        if version_bits != ANIMATION_CONTROLLER_VERSION_BITS:
            raise U9ProcessDataError(
                f"unsupported animation-controller version {version} at "
                f"0x{offset + 4:X}"
            )
        header = U9ProcessHeaderState.from_prefixed_bytes(data, offset, prefix_size=8)
        world_state = U9ProcessWorldState.from_bytes(
            data,
            header.end_offset,
            object_reference_count=object_reference_count,
        )
        cursor = world_state.end_offset
        _require_bytes(
            data, cursor, 4 + 12 + 2 + 4 + 12 + 12 + 1, "animation controller"
        )
        (object_reference_index,) = struct.unpack_from("<i", data, cursor)
        _validate_object_reference_index(
            object_reference_index, object_reference_count, "animation-controller"
        )
        cursor += 4
        initial_position = struct.unpack_from("<3f", data, cursor)
        cursor += 12
        calculates_transforms, shutting_down = struct.unpack_from("<2B", data, cursor)
        _validate_byte_boolean(calculates_transforms, "calculate-transforms")
        _validate_byte_boolean(shutting_down, "animation-controller shutting-down")
        cursor += 2
        (last_animation_id,) = struct.unpack_from("<i", data, cursor)
        cursor += 4
        animation_root_position = struct.unpack_from("<3f", data, cursor)
        cursor += 12
        translation_scale = struct.unpack_from("<3f", data, cursor)
        cursor += 12
        (scales_translation,) = struct.unpack_from("<B", data, cursor)
        _validate_byte_boolean(scales_translation, "scale-translation")
        cursor += 1

        upper_lock_count, upper_lock_slots, cursor = cls._read_lock_set(
            data, cursor, "upper"
        )
        lower_lock_count, lower_lock_slots, cursor = cls._read_lock_set(
            data, cursor, "lower"
        )
        _require_bytes(data, cursor, 26, "animation-controller runtime state")
        current_translation = struct.unpack_from("<3f", data, cursor)
        cursor += 12
        applies_events, forces_animations_to_stop = struct.unpack_from(
            "<2B", data, cursor
        )
        _validate_byte_boolean(applies_events, "apply-events")
        _validate_byte_boolean(forces_animations_to_stop, "force-animation-stop")
        cursor += 2
        attached_element_id, parent_process_id, child_process_id = struct.unpack_from(
            "<Iii", data, cursor
        )
        cursor += 12
        included_limb_ids, cursor = cls._read_limb_filter(data, cursor, "included")
        excluded_limb_ids, cursor = cls._read_limb_filter(data, cursor, "excluded")

        animation_tracks: list[U9AnimationTrackState] = []
        for _ in range(ANIMATION_TRACK_COUNT):
            track = U9AnimationTrackState.from_bytes(data, cursor)
            animation_tracks.append(track)
            cursor = track.end_offset

        _require_bytes(data, cursor, 4, "kinematic-track count")
        (kinematic_track_count,) = struct.unpack_from("<i", data, cursor)
        cursor += 4
        if not 0 <= kinematic_track_count <= MAX_KINEMATIC_TRACK_COUNT:
            raise U9ProcessDataError(
                f"implausible kinematic-track count {kinematic_track_count}"
            )
        kinematic_tracks: list[U9KinematicTrackState] = []
        for _ in range(kinematic_track_count):
            kinematic_track = U9KinematicTrackState.from_bytes(data, cursor)
            kinematic_tracks.append(kinematic_track)
            cursor = kinematic_track.end_offset

        _validate_finite(
            (
                *initial_position,
                *animation_root_position,
                *translation_scale,
                *current_translation,
            ),
            "animation-controller vectors",
        )
        return cls(
            header=header,
            version=version,
            world_state=world_state,
            object_reference_index=object_reference_index,
            initial_position=initial_position,
            calculates_transforms=bool(calculates_transforms),
            shutting_down=bool(shutting_down),
            last_animation_id=last_animation_id,
            animation_root_position=animation_root_position,
            translation_scale=translation_scale,
            scales_translation=bool(scales_translation),
            upper_lock_count=upper_lock_count,
            upper_lock_slots=upper_lock_slots,
            lower_lock_count=lower_lock_count,
            lower_lock_slots=lower_lock_slots,
            current_translation=current_translation,
            applies_events=bool(applies_events),
            forces_animations_to_stop=bool(forces_animations_to_stop),
            attached_element_id=attached_element_id,
            parent_process_id=parent_process_id,
            child_process_id=child_process_id,
            included_limb_ids=included_limb_ids,
            excluded_limb_ids=excluded_limb_ids,
            animation_tracks=tuple(animation_tracks),
            kinematic_tracks=tuple(kinematic_tracks),
            offset=offset,
            end_offset=cursor,
        )

    @staticmethod
    def _read_lock_set(
        data: bytes, offset: int, label: str
    ) -> tuple[int, tuple[int, ...], int]:
        record_size = 4 + ANIMATION_LOCK_SLOT_COUNT * 4
        _require_bytes(data, offset, record_size, f"{label} animation lock set")
        (count,) = struct.unpack_from("<i", data, offset)
        if not 0 <= count <= ANIMATION_LOCK_SLOT_COUNT:
            raise U9ProcessDataError(f"invalid {label} animation-lock count {count}")
        slots = struct.unpack_from(f"<{ANIMATION_LOCK_SLOT_COUNT}i", data, offset + 4)
        return count, tuple(slots), offset + record_size

    @staticmethod
    def _read_limb_filter(
        data: bytes, offset: int, label: str
    ) -> tuple[tuple[int, ...], int]:
        _require_bytes(data, offset, 4, f"{label} limb-filter count")
        (count,) = struct.unpack_from("<i", data, offset)
        if not 0 <= count <= MAX_ANIMATION_LIMB_FILTER_COUNT:
            raise U9ProcessDataError(f"implausible {label} limb-filter count {count}")
        _require_bytes(data, offset + 4, count * 4, f"{label} limb-filter values")
        values = struct.unpack_from(f"<{count}i", data, offset + 4)
        return tuple(values), offset + 4 + count * 4

    @property
    def upper_limb_ids(self) -> tuple[int, ...]:
        return self.upper_lock_slots[: self.upper_lock_count]

    @property
    def lower_limb_ids(self) -> tuple[int, ...]:
        return self.lower_lock_slots[: self.lower_lock_count]


@dataclass(frozen=True)
class U9ParticleItemVariantState:
    """One object type and frame delay in a particle preset's display list."""

    object_type_id: int
    swap_time_frames: int


@dataclass(frozen=True)
class U9ParticleCameraFilterTextureState:
    """The fixed 20-byte texture state used by a particle camera filter."""

    texture_id: int
    flags: int
    first_face_index: int
    face_count: int
    default_alpha: int
    current_alpha: int
    start_frame: int
    end_frame: int
    current_frame: int
    animation_rate: int
    animation_type: int
    animation_direction: int
    animation_time: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleCameraFilterTextureState:
        _require_bytes(
            data,
            offset,
            PARTICLE_CAMERA_FILTER_TEXTURE_RECORD.size,
            "particle camera-filter texture",
        )
        values = PARTICLE_CAMERA_FILTER_TEXTURE_RECORD.unpack_from(data, offset)
        return cls(
            texture_id=values[0],
            flags=values[1],
            first_face_index=values[2],
            face_count=values[3],
            default_alpha=values[4],
            current_alpha=values[5],
            start_frame=values[6],
            end_frame=values[7],
            current_frame=values[8],
            animation_rate=values[9],
            animation_type=values[10],
            animation_direction=values[11],
            animation_time=values[12],
        )


@dataclass(frozen=True)
class U9ParticleRampSlotState:
    """One aligned key slot shared by all particle-preset ramp tracks."""

    spawn_mean_value: int
    spawn_mean_frame: int
    lifetime_value: int
    lifetime_frame: int
    object_scale: tuple[float, float, float]
    object_scale_frame: int
    object_color: tuple[float, float, float]
    object_color_frame: int
    object_translucency: int
    object_translucency_frame: int
    object_luminance: int
    object_luminance_frame: int
    skeletal_animation_id: int
    skeletal_blend_duration: int
    skeletal_animation_frame: int
    light_color: tuple[int, int, int]
    light_color_frame: int
    light_range: int
    light_range_frame: int
    light_diffusion: int
    light_diffusion_frame: int
    camera_filter_color: tuple[int, int, int]
    camera_filter_color_frame: int
    camera_filter_translucency: int
    camera_filter_translucency_frame: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleRampSlotState:
        _require_bytes(
            data,
            offset,
            PARTICLE_RAMP_SLOT_RECORD.size,
            "particle ramp slot",
        )
        values = PARTICLE_RAMP_SLOT_RECORD.unpack_from(data, offset)
        return cls(
            spawn_mean_value=values[0],
            spawn_mean_frame=values[1],
            lifetime_value=values[2],
            lifetime_frame=values[3],
            object_scale=tuple(values[4:7]),
            object_scale_frame=values[7],
            object_color=tuple(values[8:11]),
            object_color_frame=values[11],
            object_translucency=values[12],
            object_translucency_frame=values[13],
            object_luminance=values[14],
            object_luminance_frame=values[15],
            skeletal_animation_id=values[16],
            skeletal_blend_duration=values[17],
            skeletal_animation_frame=values[18],
            light_color=tuple(values[19:22]),
            light_color_frame=values[22],
            light_range=values[23],
            light_range_frame=values[24],
            light_diffusion=values[25],
            light_diffusion_frame=values[26],
            camera_filter_color=tuple(values[27:30]),
            camera_filter_color_frame=values[30],
            camera_filter_translucency=values[31],
            camera_filter_translucency_frame=values[32],
        )


@dataclass(frozen=True)
class U9ParticlePresetState:
    """One complete versioned particle appearance and behavior preset."""

    version: int
    record_id: int
    particle_id: int
    critical_flag: int
    lifetime: int
    lifetime_variation: int
    initial_age: int
    spawn_shape: int
    use_transforms_flag: int
    location: tuple[float, float, float]
    offset_vector: tuple[float, float, float]
    location_inherit_flag: int
    location_slave_flag: int
    linear_maximum: tuple[float, float, float]
    minimum_radius: float
    maximum_radius: float
    scale: tuple[float, float, float]
    uniform_scale_variation: float
    scale_distortion_variation: tuple[float, float, float]
    scale_inherit_flag: int
    scale_slave_flag: int
    linear_speed: tuple[float, float, float]
    radial_speed: float
    speed_variation: float
    speed_inherit_flag: int
    minimum_angle: int
    maximum_angle: int
    use_orientation_flag: int
    orientation_quaternion: tuple[float, float, float, float]
    orientation_variation_quaternion: tuple[float, float, float, float]
    orientation_inherit_flag: int
    orientation_slave_flag: int
    rotation_quaternion: tuple[float, float, float, float]
    rotation_variation_quaternion: tuple[float, float, float, float]
    rotation_inherit_flag: int
    spawn_mean_birth: int
    spawn_mean_lifetime: int
    spawn_pulse_flag: int
    spawn_pulse_on_frames: int
    spawn_pulse_off_frames: int
    spawn_mean_death: int
    distribute_spawn_flag: int
    use_assigned_object_flag: int
    appearance_inherit_flag: int
    object_type_count: int
    swap_enabled_flag: int
    random_selection_flag: int
    sequence_index: int
    solid_flag: int
    ignore_collisions_flag: int
    no_kill_flag: int
    object_color: tuple[int, int, int]
    object_translucency: int
    object_luminance: int
    version_5_item_extension: bytes
    camera_space_flag: int
    item_variants: tuple[U9ParticleItemVariantState, ...]
    use_light_flag: int
    light_color: tuple[int, int, int]
    light_diffusion: int
    light_range: int
    negative_light_flag: int
    overbright_light_flag: int
    sound_template_id: int
    sound_category_id: int
    global_sound_flag: int
    loop_sound_flag: int
    link_number: int
    camera_shock_build: float
    camera_shock_decay: float
    camera_shock_intensity: int
    calculate_ramps_by_lifespan_flag: int
    spawn_mean_ramp_count: int
    lifespan_ramp_count: int
    object_scale_ramp_count: int
    object_color_ramp_count: int
    object_translucency_ramp_count: int
    object_luminance_ramp_count: int
    skeletal_animation_count: int
    random_skeletal_animation_flag: int
    light_color_ramp_count: int
    light_range_ramp_count: int
    light_diffusion_ramp_count: int
    camera_filter_layer: int
    camera_filter_texture: U9ParticleCameraFilterTextureState
    camera_filter_edge_color: tuple[int, int, int]
    camera_filter_center_color: tuple[int, int, int]
    camera_filter_additive_flag: int
    camera_filter_color_ramp_count: int
    camera_filter_translucency_ramp_count: int
    version_5_ramp_extension: bytes
    ramp_slots: tuple[U9ParticleRampSlotState, ...]
    use_parent_skeleton_flag: int
    skeleton_appearance_id: int
    skeleton_limb_id: int
    skeleton_attachment_id: int
    source_object_reference_index: int
    skeleton_object_reference_index: int
    offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, version: int
    ) -> U9ParticlePresetState:
        if version not in PARTICLE_PRESET_RECORD_SIZES:
            raise U9ProcessDataError(f"unsupported particle-preset version {version}")
        record_size = PARTICLE_PRESET_RECORD_SIZES[version]
        _require_bytes(data, offset, record_size, "particle preset record")
        cursor = offset

        def read(format_string: str) -> tuple[int | float, ...]:
            nonlocal cursor
            record = struct.Struct("<" + format_string)
            values = record.unpack_from(data, cursor)
            cursor += record.size
            return values

        def read_bytes(size: int) -> bytes:
            nonlocal cursor
            value = data[cursor : cursor + size]
            cursor += size
            return value

        record_id, particle_id = read("2i")
        (critical_flag,) = read("B")
        lifetime, lifetime_variation, initial_age = read("3i")
        spawn_shape, use_transforms_flag = read("2B")
        location = read("3f")
        offset_vector = read("3f")
        location_inherit_flag, location_slave_flag = read("2B")
        linear_maximum = read("3f")
        minimum_radius, maximum_radius = read("2f")
        scale = read("3f")
        (uniform_scale_variation,) = read("f")
        scale_distortion_variation = read("3f")
        scale_inherit_flag, scale_slave_flag = read("2B")
        linear_speed = read("3f")
        radial_speed, speed_variation = read("2f")
        (speed_inherit_flag,) = read("B")
        minimum_angle, maximum_angle = read("2i")
        (use_orientation_flag,) = read("B")
        orientation_quaternion = read("4f")
        orientation_variation_quaternion = read("4f")
        orientation_inherit_flag, orientation_slave_flag = read("2B")
        rotation_quaternion = read("4f")
        rotation_variation_quaternion = read("4f")
        (rotation_inherit_flag,) = read("B")
        spawn_mean_birth, spawn_mean_lifetime = read("2i")
        (spawn_pulse_flag,) = read("B")
        spawn_pulse_on_frames, spawn_pulse_off_frames, spawn_mean_death = read("3i")
        distribute_spawn_flag, use_assigned_object_flag, appearance_inherit_flag = read(
            "3B"
        )
        (object_type_count,) = read("i")
        swap_enabled_flag, random_selection_flag = read("2B")
        (sequence_index,) = read("i")
        solid_flag, ignore_collisions_flag, no_kill_flag = read("3B")
        object_color = read("3B")
        object_translucency, object_luminance = read("2i")
        version_5_item_extension = (
            read_bytes(PARTICLE_PRESET_VERSION_5_ITEM_EXTENSION_SIZE)
            if version == 5
            else b""
        )
        (camera_space_flag,) = read("B")
        item_variants = tuple(
            U9ParticleItemVariantState(*read("Hi"))
            for _ in range(PARTICLE_ITEM_VARIANT_COUNT)
        )
        (use_light_flag,) = read("B")
        light_color = read("3B")
        light_diffusion, light_range = read("2i")
        negative_light_flag, overbright_light_flag = read("2B")
        (sound_template_id,) = read("I")
        sound_category_id, global_sound_flag, loop_sound_flag = read("3B")
        (link_number,) = read("H")
        camera_shock_build, camera_shock_decay = read("2f")
        (camera_shock_intensity,) = read("i")
        (calculate_ramps_by_lifespan_flag,) = read("B")
        ramp_counts = read("7B")
        (random_skeletal_animation_flag,) = read("B")
        light_ramp_counts = read("3B")
        (camera_filter_layer,) = read("i")
        camera_filter_texture = U9ParticleCameraFilterTextureState.from_bytes(
            data, cursor
        )
        cursor += PARTICLE_CAMERA_FILTER_TEXTURE_RECORD.size
        camera_filter_edge_color = read("3B")
        camera_filter_center_color = read("3B")
        (camera_filter_additive_flag,) = read("B")
        (
            camera_filter_color_ramp_count,
            camera_filter_translucency_ramp_count,
        ) = read("2B")
        version_5_ramp_extension = (
            read_bytes(PARTICLE_PRESET_VERSION_5_RAMP_EXTENSION_SIZE)
            if version == 5
            else b""
        )
        ramp_slots = tuple(
            U9ParticleRampSlotState.from_bytes(
                data, cursor + index * PARTICLE_RAMP_SLOT_RECORD.size
            )
            for index in range(PARTICLE_RAMP_SLOT_COUNT)
        )
        cursor += PARTICLE_RAMP_SLOT_COUNT * PARTICLE_RAMP_SLOT_RECORD.size
        (use_parent_skeleton_flag,) = read("B")
        (skeleton_appearance_id,) = read("H")
        skeleton_limb_id, skeleton_attachment_id = read("2i")
        source_object_reference_index, skeleton_object_reference_index = read("2i")
        if cursor != offset + record_size:
            raise U9ProcessDataError(
                f"particle preset parser ended at 0x{cursor:X}; "
                f"expected 0x{offset + record_size:X}"
            )
        if not 0 <= object_type_count <= PARTICLE_ITEM_VARIANT_COUNT:
            raise U9ProcessDataError(
                f"particle preset {record_id} has object-type count "
                f"{object_type_count}; expected 0..{PARTICLE_ITEM_VARIANT_COUNT}"
            )
        all_ramp_counts = (
            *ramp_counts,
            *light_ramp_counts,
            camera_filter_color_ramp_count,
            camera_filter_translucency_ramp_count,
        )
        if any(count > PARTICLE_RAMP_SLOT_COUNT for count in all_ramp_counts):
            raise U9ProcessDataError(
                f"particle preset {record_id} has a ramp count above "
                f"{PARTICLE_RAMP_SLOT_COUNT}"
            )
        return cls(
            version=version,
            record_id=int(record_id),
            particle_id=int(particle_id),
            critical_flag=int(critical_flag),
            lifetime=int(lifetime),
            lifetime_variation=int(lifetime_variation),
            initial_age=int(initial_age),
            spawn_shape=int(spawn_shape),
            use_transforms_flag=int(use_transforms_flag),
            location=tuple(float(value) for value in location),
            offset_vector=tuple(float(value) for value in offset_vector),
            location_inherit_flag=int(location_inherit_flag),
            location_slave_flag=int(location_slave_flag),
            linear_maximum=tuple(float(value) for value in linear_maximum),
            minimum_radius=float(minimum_radius),
            maximum_radius=float(maximum_radius),
            scale=tuple(float(value) for value in scale),
            uniform_scale_variation=float(uniform_scale_variation),
            scale_distortion_variation=tuple(
                float(value) for value in scale_distortion_variation
            ),
            scale_inherit_flag=int(scale_inherit_flag),
            scale_slave_flag=int(scale_slave_flag),
            linear_speed=tuple(float(value) for value in linear_speed),
            radial_speed=float(radial_speed),
            speed_variation=float(speed_variation),
            speed_inherit_flag=int(speed_inherit_flag),
            minimum_angle=int(minimum_angle),
            maximum_angle=int(maximum_angle),
            use_orientation_flag=int(use_orientation_flag),
            orientation_quaternion=tuple(
                float(value) for value in orientation_quaternion
            ),
            orientation_variation_quaternion=tuple(
                float(value) for value in orientation_variation_quaternion
            ),
            orientation_inherit_flag=int(orientation_inherit_flag),
            orientation_slave_flag=int(orientation_slave_flag),
            rotation_quaternion=tuple(float(value) for value in rotation_quaternion),
            rotation_variation_quaternion=tuple(
                float(value) for value in rotation_variation_quaternion
            ),
            rotation_inherit_flag=int(rotation_inherit_flag),
            spawn_mean_birth=int(spawn_mean_birth),
            spawn_mean_lifetime=int(spawn_mean_lifetime),
            spawn_pulse_flag=int(spawn_pulse_flag),
            spawn_pulse_on_frames=int(spawn_pulse_on_frames),
            spawn_pulse_off_frames=int(spawn_pulse_off_frames),
            spawn_mean_death=int(spawn_mean_death),
            distribute_spawn_flag=int(distribute_spawn_flag),
            use_assigned_object_flag=int(use_assigned_object_flag),
            appearance_inherit_flag=int(appearance_inherit_flag),
            object_type_count=int(object_type_count),
            swap_enabled_flag=int(swap_enabled_flag),
            random_selection_flag=int(random_selection_flag),
            sequence_index=int(sequence_index),
            solid_flag=int(solid_flag),
            ignore_collisions_flag=int(ignore_collisions_flag),
            no_kill_flag=int(no_kill_flag),
            object_color=tuple(int(value) for value in object_color),
            object_translucency=int(object_translucency),
            object_luminance=int(object_luminance),
            version_5_item_extension=version_5_item_extension,
            camera_space_flag=int(camera_space_flag),
            item_variants=item_variants,
            use_light_flag=int(use_light_flag),
            light_color=tuple(int(value) for value in light_color),
            light_diffusion=int(light_diffusion),
            light_range=int(light_range),
            negative_light_flag=int(negative_light_flag),
            overbright_light_flag=int(overbright_light_flag),
            sound_template_id=int(sound_template_id),
            sound_category_id=int(sound_category_id),
            global_sound_flag=int(global_sound_flag),
            loop_sound_flag=int(loop_sound_flag),
            link_number=int(link_number),
            camera_shock_build=float(camera_shock_build),
            camera_shock_decay=float(camera_shock_decay),
            camera_shock_intensity=int(camera_shock_intensity),
            calculate_ramps_by_lifespan_flag=int(calculate_ramps_by_lifespan_flag),
            spawn_mean_ramp_count=int(ramp_counts[0]),
            lifespan_ramp_count=int(ramp_counts[1]),
            object_scale_ramp_count=int(ramp_counts[2]),
            object_color_ramp_count=int(ramp_counts[3]),
            object_translucency_ramp_count=int(ramp_counts[4]),
            object_luminance_ramp_count=int(ramp_counts[5]),
            skeletal_animation_count=int(ramp_counts[6]),
            random_skeletal_animation_flag=int(random_skeletal_animation_flag),
            light_color_ramp_count=int(light_ramp_counts[0]),
            light_range_ramp_count=int(light_ramp_counts[1]),
            light_diffusion_ramp_count=int(light_ramp_counts[2]),
            camera_filter_layer=int(camera_filter_layer),
            camera_filter_texture=camera_filter_texture,
            camera_filter_edge_color=tuple(
                int(value) for value in camera_filter_edge_color
            ),
            camera_filter_center_color=tuple(
                int(value) for value in camera_filter_center_color
            ),
            camera_filter_additive_flag=int(camera_filter_additive_flag),
            camera_filter_color_ramp_count=int(camera_filter_color_ramp_count),
            camera_filter_translucency_ramp_count=int(
                camera_filter_translucency_ramp_count
            ),
            version_5_ramp_extension=version_5_ramp_extension,
            ramp_slots=ramp_slots,
            use_parent_skeleton_flag=int(use_parent_skeleton_flag),
            skeleton_appearance_id=int(skeleton_appearance_id),
            skeleton_limb_id=int(skeleton_limb_id),
            skeleton_attachment_id=int(skeleton_attachment_id),
            source_object_reference_index=int(source_object_reference_index),
            skeleton_object_reference_index=int(skeleton_object_reference_index),
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_PRESET_RECORD_SIZES[self.version]


@dataclass(frozen=True)
class U9ParticleForcePresetState:
    """One particle force preset, including its object attachment reference."""

    record_id: int
    force_type: int
    lifetime: int
    initial_age: int
    trigger_age: int
    location: tuple[float, float, float]
    strength: float
    influence_distance: int
    inner_radius: int
    scale: tuple[float, float, float]
    speed_limit: int
    twist_velocity: tuple[float, float, float]
    offset_vector: tuple[float, float, float]
    element_id: int
    hard_point_id: int
    numeric_type: int
    object_reference_index: int
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleForcePresetState:
        _require_bytes(
            data,
            offset,
            PARTICLE_FORCE_PRESET_RECORD.size,
            "particle force preset record",
        )
        values = PARTICLE_FORCE_PRESET_RECORD.unpack_from(data, offset)
        return cls(
            record_id=values[0],
            force_type=values[1],
            lifetime=values[2],
            initial_age=values[3],
            trigger_age=values[4],
            location=tuple(values[5:8]),
            strength=values[8],
            influence_distance=values[9],
            inner_radius=values[10],
            scale=tuple(values[11:14]),
            speed_limit=values[14],
            twist_velocity=tuple(values[15:18]),
            offset_vector=tuple(values[18:21]),
            element_id=values[21],
            hard_point_id=values[22],
            numeric_type=values[23],
            object_reference_index=values[24],
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_FORCE_PRESET_RECORD.size


@dataclass(frozen=True)
class U9ParticleForceState:
    """One active particle force and its link to a force preset."""

    record_id: int
    age: int
    location: tuple[float, float, float]
    preset_id: int
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleForceState:
        _require_bytes(
            data, offset, PARTICLE_FORCE_RECORD.size, "particle force record"
        )
        values = PARTICLE_FORCE_RECORD.unpack_from(data, offset)
        return cls(
            record_id=values[0],
            age=values[1],
            location=(values[2], values[3], values[4]),
            preset_id=values[5],
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_FORCE_RECORD.size


@dataclass(frozen=True)
class U9ParticleGenerationState:
    """One particle-generation record and its linked effects."""

    record_id: int
    particle_preset_id: int
    birth_generation_id: int
    lifetime_generation_id: int
    death_generation_id: int
    birth_force_ids: tuple[int, ...]
    lifetime_force_ids: tuple[int, ...]
    death_force_ids: tuple[int, ...]
    slave_force_ids: tuple[int, ...]
    slave_generation_ids: tuple[int, ...]
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleGenerationState:
        _require_bytes(
            data,
            offset,
            PARTICLE_GENERATION_RECORD.size,
            "particle generation record",
        )
        values = PARTICLE_GENERATION_RECORD.unpack_from(data, offset)
        force_ids = values[5:21]
        return cls(
            record_id=values[0],
            particle_preset_id=values[1],
            birth_generation_id=values[2],
            lifetime_generation_id=values[3],
            death_generation_id=values[4],
            birth_force_ids=tuple(force_ids[0::4]),
            lifetime_force_ids=tuple(force_ids[1::4]),
            death_force_ids=tuple(force_ids[2::4]),
            slave_force_ids=tuple(force_ids[3::4]),
            slave_generation_ids=tuple(values[21:31]),
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_GENERATION_RECORD.size


@dataclass(frozen=True)
class U9ParticleInstanceState:
    """One active particle instance and its runtime object relationships."""

    record_id: int
    generation_id: int
    parent_particle_id: int
    child_particle_ids: tuple[int, ...]
    lifetime: int
    age: int
    location: tuple[float, float, float]
    velocity: tuple[float, float, float]
    snap_velocity: tuple[float, float, float]
    scale: tuple[float, float, float]
    orientation_quaternion: tuple[float, float, float, float]
    rotation_quaternion: tuple[float, float, float, float]
    spawn_mean_lifetime: int
    spawn_pulse_count: int
    spawn_pulse_count_byte: int
    object_type_id: int
    object_status_flags: int
    swap_sequence: int
    sequence_index: int
    swap_elapsed_frames: int
    attached_element_id: int
    sound_id: int
    light_source_flag: int
    callback_id: int
    callback_effect_id: int
    callback_magic_type: int
    callback_caster_reference_index: int
    object_reference_index: int
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9ParticleInstanceState:
        _require_bytes(
            data,
            offset,
            PARTICLE_INSTANCE_RECORD.size,
            "particle instance record",
        )
        values = PARTICLE_INSTANCE_RECORD.unpack_from(data, offset)
        return cls(
            record_id=values[0],
            generation_id=values[1],
            parent_particle_id=values[2],
            child_particle_ids=tuple(values[3:13]),
            lifetime=values[13],
            age=values[14],
            location=tuple(values[15:18]),
            velocity=tuple(values[18:21]),
            snap_velocity=tuple(values[21:24]),
            scale=tuple(values[24:27]),
            orientation_quaternion=tuple(values[27:31]),
            rotation_quaternion=tuple(values[31:35]),
            spawn_mean_lifetime=values[35],
            spawn_pulse_count=values[36],
            spawn_pulse_count_byte=values[37],
            object_type_id=values[38],
            object_status_flags=values[39],
            swap_sequence=values[40],
            sequence_index=values[41],
            swap_elapsed_frames=values[42],
            attached_element_id=values[43],
            sound_id=values[44],
            light_source_flag=values[45],
            callback_id=values[46],
            callback_effect_id=values[47],
            callback_magic_type=values[48],
            callback_caster_reference_index=values[49],
            object_reference_index=values[50],
            offset=offset,
        )

    @property
    def pulse_count_byte_matches(self) -> bool:
        """Whether the redundant byte matches the pulse counter's low byte."""
        return self.spawn_pulse_count_byte == (self.spawn_pulse_count & 0xFF)

    @property
    def has_light_source(self) -> bool:
        return bool(self.light_source_flag)

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_INSTANCE_RECORD.size


@dataclass(frozen=True)
class U9ParticleRecordCollection:
    """One counted, fixed-stride particle-system record collection."""

    name: str
    record_size: int
    record_ids: tuple[int, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        name: str,
        count: int,
        record_size: int,
    ) -> U9ParticleRecordCollection:
        byte_count = count * record_size
        _require_bytes(data, offset, byte_count, name)
        record_ids = tuple(
            struct.unpack_from("<i", data, offset + index * record_size)[0]
            for index in range(count)
        )
        for index, record_id in enumerate(record_ids, start=1):
            if record_id != index:
                raise U9ProcessDataError(
                    f"{name} record {index} has ID {record_id}; expected {index}"
                )
        return cls(
            name=name,
            record_size=record_size,
            record_ids=record_ids,
            offset=offset,
            end_offset=offset + byte_count,
        )

    @property
    def count(self) -> int:
        return len(self.record_ids)


@dataclass(frozen=True)
class U9ParticleRecordCollections:
    """The five serialized particle-system collections in stream order."""

    particle_presets: U9ParticleRecordCollection
    force_presets: U9ParticleRecordCollection
    forces: U9ParticleRecordCollection
    generations: U9ParticleRecordCollection
    particles: U9ParticleRecordCollection
    particle_preset_records: tuple[U9ParticlePresetState, ...]
    force_preset_records: tuple[U9ParticleForcePresetState, ...]
    force_records: tuple[U9ParticleForceState, ...]
    generation_records: tuple[U9ParticleGenerationState, ...]
    particle_records: tuple[U9ParticleInstanceState, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        version: int,
        particle_preset_count: int,
        generation_count: int,
        particle_count: int,
        force_preset_count: int,
        force_count: int,
        object_reference_count: int | None = None,
    ) -> U9ParticleRecordCollections:
        cursor = offset

        def read_collection(
            name: str, count: int, record_size: int
        ) -> U9ParticleRecordCollection:
            nonlocal cursor
            collection = U9ParticleRecordCollection.from_bytes(
                data,
                cursor,
                name=name,
                count=count,
                record_size=record_size,
            )
            cursor = collection.end_offset
            return collection

        particle_presets = read_collection(
            "particle presets",
            particle_preset_count,
            PARTICLE_PRESET_RECORD_SIZES[version],
        )
        force_presets = read_collection(
            "particle force presets",
            force_preset_count,
            PARTICLE_FORCE_PRESET_RECORD_SIZE,
        )
        forces = read_collection(
            "particle forces", force_count, PARTICLE_FORCE_RECORD_SIZE
        )
        generations = read_collection(
            "particle generations",
            generation_count,
            PARTICLE_GENERATION_RECORD_SIZE,
        )
        particles = read_collection(
            "particle instances", particle_count, PARTICLE_INSTANCE_RECORD_SIZE
        )
        particle_preset_records = tuple(
            U9ParticlePresetState.from_bytes(
                data,
                particle_presets.offset + index * PARTICLE_PRESET_RECORD_SIZES[version],
                version=version,
            )
            for index in range(particle_preset_count)
        )
        force_preset_records = tuple(
            U9ParticleForcePresetState.from_bytes(
                data,
                force_presets.offset + index * PARTICLE_FORCE_PRESET_RECORD_SIZE,
            )
            for index in range(force_preset_count)
        )
        force_records = tuple(
            U9ParticleForceState.from_bytes(
                data, forces.offset + index * PARTICLE_FORCE_RECORD_SIZE
            )
            for index in range(force_count)
        )
        generation_records = tuple(
            U9ParticleGenerationState.from_bytes(
                data, generations.offset + index * PARTICLE_GENERATION_RECORD_SIZE
            )
            for index in range(generation_count)
        )
        particle_records = tuple(
            U9ParticleInstanceState.from_bytes(
                data, particles.offset + index * PARTICLE_INSTANCE_RECORD_SIZE
            )
            for index in range(particle_count)
        )
        if object_reference_count is not None:
            for record in particle_preset_records:
                cls._validate_index_reference(
                    record.source_object_reference_index,
                    object_reference_count,
                    f"particle preset {record.record_id} source object",
                )
                cls._validate_index_reference(
                    record.skeleton_object_reference_index,
                    object_reference_count,
                    f"particle preset {record.record_id} skeleton object",
                )
            for record in force_preset_records:
                cls._validate_index_reference(
                    record.object_reference_index,
                    object_reference_count,
                    f"particle force preset {record.record_id} object",
                )
        for record in force_records:
            cls._validate_reference(
                record.preset_id,
                force_preset_count,
                f"particle force {record.record_id} force preset",
            )
        for record in generation_records:
            cls._validate_reference(
                record.particle_preset_id,
                particle_preset_count,
                f"particle generation {record.record_id} particle preset",
            )
            for label, references, count in (
                (
                    "birth generation",
                    (record.birth_generation_id,),
                    generation_count,
                ),
                (
                    "lifetime generation",
                    (record.lifetime_generation_id,),
                    generation_count,
                ),
                (
                    "death generation",
                    (record.death_generation_id,),
                    generation_count,
                ),
                ("slave generation", record.slave_generation_ids, generation_count),
                ("birth force", record.birth_force_ids, force_count),
                ("lifetime force", record.lifetime_force_ids, force_count),
                ("death force", record.death_force_ids, force_count),
                ("slave force", record.slave_force_ids, force_count),
            ):
                for reference in references:
                    cls._validate_reference(
                        reference,
                        count,
                        f"particle generation {record.record_id} {label}",
                        allow_null=True,
                    )
        for record in particle_records:
            cls._validate_reference(
                record.generation_id,
                generation_count,
                f"particle instance {record.record_id} generation",
            )
            cls._validate_reference(
                record.parent_particle_id,
                particle_count,
                f"particle instance {record.record_id} parent particle",
                allow_null=True,
            )
            for child_id in record.child_particle_ids:
                cls._validate_reference(
                    child_id,
                    particle_count,
                    f"particle instance {record.record_id} child particle",
                    allow_null=True,
                )
            if object_reference_count is not None:
                cls._validate_index_reference(
                    record.callback_caster_reference_index,
                    object_reference_count,
                    f"particle instance {record.record_id} callback caster",
                )
                cls._validate_index_reference(
                    record.object_reference_index,
                    object_reference_count,
                    f"particle instance {record.record_id} object",
                )
        return cls(
            particle_presets=particle_presets,
            force_presets=force_presets,
            forces=forces,
            generations=generations,
            particles=particles,
            particle_preset_records=particle_preset_records,
            force_preset_records=force_preset_records,
            force_records=force_records,
            generation_records=generation_records,
            particle_records=particle_records,
            offset=offset,
            end_offset=cursor,
        )

    @staticmethod
    def _validate_reference(
        reference: int,
        count: int,
        label: str,
        *,
        allow_null: bool = False,
    ) -> None:
        if allow_null and reference == -1:
            return
        if not 1 <= reference <= count:
            null_note = " or -1" if allow_null else ""
            raise U9ProcessDataError(
                f"{label} reference {reference} is outside 1..{count}{null_note}"
            )

    @staticmethod
    def _validate_index_reference(reference: int, count: int, label: str) -> None:
        if not 0 <= reference < count:
            raise U9ProcessDataError(
                f"{label} reference {reference} is outside 0..{count - 1}"
            )


@dataclass(frozen=True)
class U9ParticleProcessState:
    """Global counters preceding the first process's particle records."""

    version: int
    animation_time: int
    translation_flag: int
    next_particle_id: int
    particle_preset_count: int
    generation_count: int
    particle_count: int
    force_preset_count: int
    force_count: int
    offset: int
    records: U9ParticleRecordCollections

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int | None = None,
    ) -> U9ParticleProcessState:
        _require_bytes(data, offset, PARTICLE_PROCESS_STATE_SIZE, "particle state")
        version, animation_time = struct.unpack_from("<iI", data, offset)
        if version not in PARTICLE_PROCESS_VERSIONS:
            raise U9ProcessDataError(
                f"unsupported particle-state version {version} at 0x{offset:X}"
            )
        translation_flag = data[offset + 8]
        next_particle_id = struct.unpack_from("<i", data, offset + 9)[0]
        counts = struct.unpack_from("<5i", data, offset + 13)
        if any(count < 0 for count in counts):
            raise U9ProcessDataError(f"negative particle-state record count {counts}")
        records = U9ParticleRecordCollections.from_bytes(
            data,
            offset + PARTICLE_PROCESS_STATE_SIZE,
            version=version,
            particle_preset_count=counts[0],
            generation_count=counts[1],
            particle_count=counts[2],
            force_preset_count=counts[3],
            force_count=counts[4],
            object_reference_count=object_reference_count,
        )
        return cls(
            version=version,
            animation_time=animation_time,
            translation_flag=translation_flag,
            next_particle_id=next_particle_id,
            particle_preset_count=counts[0],
            generation_count=counts[1],
            particle_count=counts[2],
            force_preset_count=counts[3],
            force_count=counts[4],
            offset=offset,
            records=records,
        )

    @property
    def translation_pending(self) -> bool:
        return bool(self.translation_flag)

    @property
    def end_offset(self) -> int:
        return self.offset + PARTICLE_PROCESS_STATE_SIZE


@dataclass(frozen=True)
class U9ProcessRecordPrefix:
    """Decoded common fields before one process's type-specific payload."""

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState | None
    particle_state: U9ParticleProcessState | None

    @property
    def payload_offset(self) -> int:
        if self.world_state is not None:
            return self.world_state.end_offset
        return self.header.end_offset

    @property
    def decoded_prefix_end_offset(self) -> int:
        if self.particle_state is not None:
            return self.particle_state.records.end_offset
        return self.payload_offset


@dataclass(frozen=True)
class U9CameraEffectState:
    """One versioned, fixed-size screen-effect record saved with the camera."""

    index: int
    version: float
    serialized_data: bytes
    offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, index: int = 0
    ) -> U9CameraEffectState:
        _require_bytes(data, offset, 4, "camera-effect version")
        (version_bits,) = struct.unpack_from("<I", data, offset)
        version_and_size = CAMERA_EFFECT_VERSION_BITS.get(version_bits)
        if version_and_size is None:
            (version,) = struct.unpack_from("<f", data, offset)
            raise U9ProcessDataError(
                f"unsupported camera-effect version {version:g} at 0x{offset:X}"
            )
        version, size = version_and_size
        _require_bytes(data, offset, size, "camera-effect record")
        return cls(index, version, data[offset : offset + size], offset)

    @property
    def size(self) -> int:
        return len(self.serialized_data)

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class U9CameraState:
    """Saved view position, orientation, clipping distances, and effects."""

    version: int
    focus_position: tuple[float, float, float]
    yaw: float
    pitch: float
    roll: float
    focus_distance: int
    mode: int
    exclusive_interface: bool
    horizontal_fov: float
    near_distance: float
    far_distance: float
    middle_distance: float
    effects: tuple[U9CameraEffectState, ...]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9CameraState:
        _require_bytes(data, offset, CAMERA_HEADER.size, "camera header")
        values = CAMERA_HEADER.unpack_from(data, offset)
        version = values[0]
        if version != CAMERA_VERSION:
            raise U9ProcessDataError(
                f"unsupported camera version {version}; expected {CAMERA_VERSION}"
            )
        effect_count = values[-1]
        if not 0 <= effect_count <= MAX_CAMERA_EFFECT_COUNT:
            raise U9ProcessDataError(f"implausible camera-effect count {effect_count}")

        cursor = offset + CAMERA_HEADER.size
        effects: list[U9CameraEffectState] = []
        for index in range(effect_count):
            effect = U9CameraEffectState.from_bytes(data, cursor, index=index)
            effects.append(effect)
            cursor = effect.end_offset

        _require_bytes(data, cursor, 4, "camera-control version")
        (control_version,) = struct.unpack_from("<I", data, cursor)
        if control_version not in CAMERA_CONTROL_VERSIONS:
            raise U9ProcessDataError(
                "camera effects do not end at a supported camera-control version "
                f"(found {control_version} at 0x{cursor:X})"
            )
        return cls(
            version=version,
            focus_position=(values[1], values[2], values[3]),
            yaw=values[4],
            pitch=values[5],
            roll=values[6],
            focus_distance=values[7],
            mode=values[8],
            exclusive_interface=bool(values[9]),
            horizontal_fov=values[10],
            near_distance=values[11],
            far_distance=values[12],
            middle_distance=values[13],
            effects=tuple(effects),
            offset=offset,
            end_offset=cursor,
        )


@dataclass(frozen=True)
class U9TargetingState:
    """Saved targeting-cursor modes, distance bands, and position."""

    version: int
    movement_mode: int
    visual_mode: int
    visibility: int
    ranges: tuple[float, float, float]
    position: tuple[float, float, float]
    screen_position: tuple[int, int]
    offset: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9TargetingState:
        _require_bytes(data, offset, TARGETING_STATE.size, "targeting state")
        values = TARGETING_STATE.unpack_from(data, offset)
        if values[0] != 0:
            raise U9ProcessDataError(
                f"unsupported targeting-state version {values[0]} at 0x{offset:X}"
            )
        return cls(
            version=values[0],
            movement_mode=values[1],
            visual_mode=values[2],
            visibility=values[3],
            ranges=(values[4], values[5], values[6]),
            position=(values[7], values[8], values[9]),
            screen_position=(values[10], values[11]),
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + TARGETING_STATE.size


@dataclass(frozen=True)
class U9CameraControlState:
    """Saved camera targeting, distance, shake, and targeting-cursor state."""

    version: int
    target_position: tuple[float, float, float]
    target_yaw: float
    target_pitch: float
    unlimited_target_range: bool | None
    target_fov: float | None
    current_distance: float | None
    maximum_distance: float | None
    maximum_target_distance: float | None
    target_line_radius: float | None
    underground: bool | None
    underwater: bool | None
    on_moon: bool | None
    target_mode: bool | None
    quake_offset: tuple[float, float, float] | None
    quake_velocity: tuple[float, float, float] | None
    quake_intensity: int | None
    tremor: int | None
    quake_total_time_to_peak: float | None
    quake_remaining_time_to_peak: float | None
    quake_total_time_to_decay: float | None
    quake_remaining_time_to_decay: float | None
    quake_initial_intensity: int | None
    quake_peak_intensity: int | None
    shock_offset: tuple[float, float, float] | None
    shock_build_time: float | None
    shock_remaining_build_time: float | None
    shock_decay_time: float | None
    shock_remaining_decay_time: float | None
    shock_peak_intensity: int | None
    target_lock_rectangle: tuple[int, int, int, int] | None
    distant_npcs_can_move: bool | None
    distant_items_can_move: bool | None
    has_temporary_camera: bool
    targeting: U9TargetingState | None
    offset: int
    end_offset: int | None

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9CameraControlState:
        _require_bytes(data, offset, 4, "camera-control version")
        (version,) = struct.unpack_from("<I", data, offset)
        if version not in CAMERA_CONTROL_VERSIONS:
            raise U9ProcessDataError(
                f"unsupported camera-control version {version} at 0x{offset:X}"
            )

        if version == 0:
            _require_bytes(data, offset, CAMERA_CONTROL_BASE_SIZE, "camera control")
            values = struct.unpack_from("<I3f2fI", data, offset)
            marker_offset = offset + 24
            unlimited_target_range = None
            target_fov = None
            current_distance = None
            maximum_distance = None
            maximum_target_distance = None
            target_line_radius = None
            underground = None
            underwater = None
            on_moon = None
            target_mode = None
            quake_offset = None
            quake_velocity = None
            quake_intensity = None
            tremor = None
            quake_total_time_to_peak = None
            quake_remaining_time_to_peak = None
            quake_total_time_to_decay = None
            quake_remaining_time_to_decay = None
            quake_initial_intensity = None
            quake_peak_intensity = None
            shock_offset = None
            shock_build_time = None
            shock_remaining_build_time = None
            shock_decay_time = None
            shock_remaining_decay_time = None
            shock_peak_intensity = None
            target_lock_rectangle = None
            distant_npcs_can_move = None
            distant_items_can_move = None
        else:
            _require_bytes(data, offset, CAMERA_CONTROL_EXTENDED_SIZE, "camera control")
            values = struct.unpack_from("<I3f2f", data, offset)
            marker_offset = offset + 176
            unlimited_target_range = bool(
                struct.unpack_from("<I", data, offset + 24)[0]
            )
            target_fov, current_distance, maximum_distance = struct.unpack_from(
                "<3f", data, offset + 28
            )
            maximum_target_distance, target_line_radius = struct.unpack_from(
                "<2f", data, offset + 40
            )
            underground, underwater, on_moon, target_mode = (
                bool(value) for value in struct.unpack_from("<4I", data, offset + 48)
            )
            quake_offset = struct.unpack_from("<3f", data, offset + 64)
            quake_velocity = struct.unpack_from("<3f", data, offset + 76)
            quake_intensity, tremor = struct.unpack_from("<2i", data, offset + 88)
            (
                quake_total_time_to_peak,
                quake_remaining_time_to_peak,
                quake_total_time_to_decay,
                quake_remaining_time_to_decay,
            ) = struct.unpack_from("<4f", data, offset + 96)
            quake_initial_intensity, quake_peak_intensity = struct.unpack_from(
                "<2i", data, offset + 112
            )
            shock_offset = struct.unpack_from("<3f", data, offset + 120)
            (
                shock_build_time,
                shock_remaining_build_time,
                shock_decay_time,
                shock_remaining_decay_time,
            ) = struct.unpack_from("<4f", data, offset + 132)
            (shock_peak_intensity,) = struct.unpack_from("<i", data, offset + 148)
            target_lock_rectangle = struct.unpack_from("<4i", data, offset + 152)
            distant_npcs_can_move, distant_items_can_move = (
                bool(value) for value in struct.unpack_from("<2I", data, offset + 168)
            )

        (temporary_marker,) = struct.unpack_from("<I", data, marker_offset)
        has_temporary_camera = temporary_marker != 0
        targeting = None
        end_offset: int | None = marker_offset + 4
        if has_temporary_camera:
            # This optional record has no length field and has not yet been
            # verified against a saved retail example, so the next boundary
            # intentionally remains unknown.
            end_offset = None
        elif version == 2:
            targeting = U9TargetingState.from_bytes(data, marker_offset + 4)
            end_offset = targeting.end_offset

        return cls(
            version=version,
            target_position=(values[1], values[2], values[3]),
            target_yaw=values[4],
            target_pitch=values[5],
            unlimited_target_range=unlimited_target_range,
            target_fov=target_fov,
            current_distance=current_distance,
            maximum_distance=maximum_distance,
            maximum_target_distance=maximum_target_distance,
            target_line_radius=target_line_radius,
            underground=underground,
            underwater=underwater,
            on_moon=on_moon,
            target_mode=target_mode,
            quake_offset=quake_offset,
            quake_velocity=quake_velocity,
            quake_intensity=quake_intensity,
            tremor=tremor,
            quake_total_time_to_peak=quake_total_time_to_peak,
            quake_remaining_time_to_peak=quake_remaining_time_to_peak,
            quake_total_time_to_decay=quake_total_time_to_decay,
            quake_remaining_time_to_decay=quake_remaining_time_to_decay,
            quake_initial_intensity=quake_initial_intensity,
            quake_peak_intensity=quake_peak_intensity,
            shock_offset=shock_offset,
            shock_build_time=shock_build_time,
            shock_remaining_build_time=shock_remaining_build_time,
            shock_decay_time=shock_decay_time,
            shock_remaining_decay_time=shock_remaining_decay_time,
            shock_peak_intensity=shock_peak_intensity,
            target_lock_rectangle=target_lock_rectangle,
            distant_npcs_can_move=distant_npcs_can_move,
            distant_items_can_move=distant_items_can_move,
            has_temporary_camera=has_temporary_camera,
            targeting=targeting,
            offset=offset,
            end_offset=end_offset,
        )


@dataclass(frozen=True, init=False)
class U9ObjectReferenceEntry:
    """One serialized reference from a process to a fixed or runtime object."""

    index: int
    link_or_reference_count: int
    map_number: int
    encoded_object_offset: int

    def __init__(
        self,
        index: int,
        link_or_reference_count: int | None = None,
        map_number: int | None = None,
        encoded_object_offset: int | None = None,
        *,
        usage_count: int | None = None,
        encoded_item_offset: int | None = None,
    ) -> None:
        """Create an entry, accepting the earlier keyword names as aliases."""
        if link_or_reference_count is None:
            link_or_reference_count = usage_count
        elif usage_count is not None and usage_count != link_or_reference_count:
            raise TypeError("conflicting reference-count values")
        if encoded_object_offset is None:
            encoded_object_offset = encoded_item_offset
        elif (
            encoded_item_offset is not None
            and encoded_item_offset != encoded_object_offset
        ):
            raise TypeError("conflicting encoded-offset values")
        if link_or_reference_count is None:
            raise TypeError("missing link_or_reference_count")
        if map_number is None:
            raise TypeError("missing map_number")
        if encoded_object_offset is None:
            raise TypeError("missing encoded_object_offset")
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "link_or_reference_count", link_or_reference_count)
        object.__setattr__(self, "map_number", map_number)
        object.__setattr__(self, "encoded_object_offset", encoded_object_offset)

    @property
    def reference_count(self) -> int:
        """Live-reference count; free entries reuse this field as the next link."""
        return self.link_or_reference_count

    @property
    def next_free_index(self) -> int:
        """Next free table index when this entry is unallocated."""
        return self.link_or_reference_count

    @property
    def is_free(self) -> bool:
        return self.map_number == -1

    @property
    def is_live(self) -> bool:
        return self.map_number >= 0 and self.encoded_object_offset != 0

    @property
    def is_fixed(self) -> bool:
        return self.is_live and self.encoded_object_offset < 0

    @property
    def object_offset(self) -> int:
        """Absolute heap offset of the referenced object slot."""
        return abs(self.encoded_object_offset)

    # Compatibility properties retained for callers using the earlier field
    # vocabulary. They intentionally mirror the generalized properties.
    @property
    def usage_count(self) -> int:
        return self.link_or_reference_count

    @property
    def encoded_item_offset(self) -> int:
        return self.encoded_object_offset

    @property
    def item_offset(self) -> int:
        return self.object_offset


@dataclass(frozen=True)
class U9ObjectReferenceTable:
    """Serialized object-reference entries plus their free-index chain."""

    version: int
    count: int
    free_head: int
    entries: tuple[U9ObjectReferenceEntry, ...]
    offset: int = OBJECT_REFERENCE_DATA_OFFSET

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9ObjectReferenceTable:
        with open(filepath, "rb") as file:
            return cls.from_bytes(file.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> U9ObjectReferenceTable:
        if len(data) < OBJECT_REFERENCE_DATA_OFFSET + 12:
            raise U9ProcessDataError(
                "process data is too short for the object-reference table at "
                f"0x{OBJECT_REFERENCE_DATA_OFFSET:X}"
            )
        main_version, state_version = struct.unpack_from("<II", data, 0)
        if (main_version, state_version) != (8, 2):
            raise U9ProcessDataError(
                f"unsupported process versions {main_version}/{state_version}; expected 8/2"
            )
        version, count, free_head = struct.unpack_from(
            "<III", data, OBJECT_REFERENCE_DATA_OFFSET
        )
        if version != OBJECT_REFERENCE_VERSION:
            raise U9ProcessDataError(
                f"unsupported object-reference version {version}; "
                f"expected {OBJECT_REFERENCE_VERSION}"
            )
        if not MIN_OBJECT_REFERENCE_COUNT <= count <= MAX_OBJECT_REFERENCE_COUNT:
            raise U9ProcessDataError(f"implausible object-reference count {count}")
        table_end = (
            OBJECT_REFERENCE_DATA_OFFSET + 12 + count * OBJECT_REFERENCE_RECORD.size
        )
        if table_end + 4 > len(data):
            raise U9ProcessDataError(
                "truncated object-reference table: needs "
                f"{table_end + 4} bytes, got {len(data)}"
            )
        (camera_version,) = struct.unpack_from("<I", data, table_end)
        if camera_version != CAMERA_VERSION:
            raise U9ProcessDataError(
                "object-reference table does not end at camera version "
                f"{CAMERA_VERSION} "
                f"(found {camera_version})"
            )
        entries = tuple(
            U9ObjectReferenceEntry(
                index,
                *OBJECT_REFERENCE_RECORD.unpack_from(
                    data, OBJECT_REFERENCE_DATA_OFFSET + 12 + index * 12
                ),
            )
            for index in range(count)
        )
        invalid_maps = [entry.index for entry in entries if entry.map_number < -1]
        if invalid_maps:
            raise U9ProcessDataError(
                f"{len(invalid_maps)} object-reference entries have map numbers below -1"
            )
        if free_head >= count:
            raise U9ProcessDataError(
                f"object-reference free head {free_head} is outside 0..{count - 1}"
            )
        return cls(version, count, free_head, entries)

    @property
    def end_offset(self) -> int:
        return self.offset + 12 + self.count * OBJECT_REFERENCE_RECORD.size

    @property
    def live_entries(self) -> tuple[U9ObjectReferenceEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_live)

    @property
    def fixed_entries(self) -> tuple[U9ObjectReferenceEntry, ...]:
        return tuple(entry for entry in self.live_entries if entry.is_fixed)

    @property
    def nonfixed_entries(self) -> tuple[U9ObjectReferenceEntry, ...]:
        return tuple(entry for entry in self.live_entries if not entry.is_fixed)

    def walk_free_chain(self) -> tuple[int, ...]:
        """Return free indices, excluding reserved entry zero, or raise on damage."""
        chain: list[int] = []
        seen: set[int] = set()
        current = self.free_head
        while current:
            if current < 0 or current >= self.count:
                raise U9ProcessDataError(f"free chain leaves table at entry {current}")
            if current in seen:
                raise U9ProcessDataError(f"free chain cycles at entry {current}")
            entry = self.entries[current]
            if not entry.is_free:
                raise U9ProcessDataError(f"free chain enters live entry {current}")
            seen.add(current)
            chain.append(current)
            current = entry.next_free_index
        expected = {entry.index for entry in self.entries[1:] if entry.is_free}
        if seen != expected:
            raise U9ProcessDataError(
                f"free chain covers {len(seen)} of {len(expected)} free entries"
            )
        return tuple(chain)


@dataclass(frozen=True)
class U9ProcessDataPrefix:
    """Deterministic stream through type 104 and supported later processes."""

    object_references: U9ObjectReferenceTable
    camera: U9CameraState
    camera_control: U9CameraControlState
    process_list_offset: int | None
    first_process_type: int | None
    first_process: U9ProcessRecordPrefix | None
    next_process_offset: int | None
    next_process_type: int | None
    next_process_header: U9ProcessHeaderState | None
    following_processes: tuple[
        U9AnimationControllerProcessState
        | U9HangingObjectProcessState
        | U9ScriptTimerProcessState
        | U9PortableLightProcessState
        | U9PlayerProximityProcessState,
        ...,
    ]
    blocked_process_offset: int | None
    blocked_process_type: int | None
    terminator_offset: int | None

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9ProcessDataPrefix:
        with open(filepath, "rb") as file:
            return cls.from_bytes(file.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> U9ProcessDataPrefix:
        object_references = U9ObjectReferenceTable.from_bytes(data)
        camera = U9CameraState.from_bytes(data, object_references.end_offset)
        camera_control = U9CameraControlState.from_bytes(data, camera.end_offset)
        process_list_offset = camera_control.end_offset
        first_process_type = None
        first_process = None
        next_process_offset = None
        next_process_type = None
        next_process_header = None
        following_processes: list[
            U9AnimationControllerProcessState
            | U9HangingObjectProcessState
            | U9ScriptTimerProcessState
            | U9PortableLightProcessState
            | U9PlayerProximityProcessState
        ] = []
        blocked_process_offset = None
        blocked_process_type = None
        terminator_offset = None
        if process_list_offset is not None:
            _require_bytes(data, process_list_offset, 4, "first process type")
            (first_process_type,) = struct.unpack_from("<i", data, process_list_offset)
            if not (
                first_process_type == -1
                or MIN_PROCESS_TYPE <= first_process_type <= MAX_PROCESS_TYPE
            ):
                raise U9ProcessDataError(
                    f"invalid first process type {first_process_type} at "
                    f"0x{process_list_offset:X}"
                )
            if first_process_type != -1:
                header = U9ProcessHeaderState.from_bytes(data, process_list_offset)
                world_state = None
                if first_process_type in WORLD_PROCESS_TYPES:
                    world_state = U9ProcessWorldState.from_bytes(
                        data,
                        header.end_offset,
                        object_reference_count=object_references.count,
                    )
                particle_state = None
                if first_process_type == PARTICLE_PROCESS_TYPE:
                    if world_state is None:
                        raise U9ProcessDataError(
                            "particle process is missing its world-state prefix"
                        )
                    particle_state = U9ParticleProcessState.from_bytes(
                        data,
                        world_state.end_offset,
                        object_reference_count=object_references.count,
                    )
                first_process = U9ProcessRecordPrefix(
                    header, world_state, particle_state
                )
                if particle_state is not None:
                    next_process_offset = particle_state.records.end_offset
                    cursor = next_process_offset
                    while True:
                        _require_bytes(data, cursor, 4, "next process type")
                        (process_type,) = struct.unpack_from("<i", data, cursor)
                        if next_process_type is None:
                            next_process_type = process_type
                        if process_type == -1:
                            terminator_offset = cursor
                            break
                        if not MIN_PROCESS_TYPE <= process_type <= MAX_PROCESS_TYPE:
                            raise U9ProcessDataError(
                                f"invalid next process type {process_type} at "
                                f"0x{cursor:X}"
                            )
                        process: (
                            U9AnimationControllerProcessState
                            | U9HangingObjectProcessState
                            | U9ScriptTimerProcessState
                            | U9PortableLightProcessState
                            | U9PlayerProximityProcessState
                        )
                        if process_type == HANGING_OBJECT_PROCESS_TYPE:
                            process = U9HangingObjectProcessState.from_bytes(
                                data,
                                cursor,
                                object_reference_count=object_references.count,
                            )
                        elif process_type == SCRIPT_TIMER_PROCESS_TYPE:
                            process = U9ScriptTimerProcessState.from_bytes(
                                data,
                                cursor,
                                object_reference_count=object_references.count,
                            )
                        elif process_type == PORTABLE_LIGHT_PROCESS_TYPE:
                            process = U9PortableLightProcessState.from_bytes(
                                data,
                                cursor,
                                object_reference_count=object_references.count,
                            )
                        elif process_type == PLAYER_PROXIMITY_PROCESS_TYPE:
                            process = U9PlayerProximityProcessState.from_bytes(
                                data,
                                cursor,
                                object_reference_count=object_references.count,
                            )
                        elif process_type == ANIMATION_CONTROLLER_PROCESS_TYPE:
                            process = U9AnimationControllerProcessState.from_bytes(
                                data,
                                cursor,
                                object_reference_count=object_references.count,
                            )
                        else:
                            blocked_process_offset = cursor
                            blocked_process_type = process_type
                            break
                        if next_process_header is None:
                            next_process_header = process.header
                        following_processes.append(process)
                        cursor = process.end_offset
        return cls(
            object_references=object_references,
            camera=camera,
            camera_control=camera_control,
            process_list_offset=process_list_offset,
            first_process_type=first_process_type,
            first_process=first_process,
            next_process_offset=next_process_offset,
            next_process_type=next_process_type,
            next_process_header=next_process_header,
            following_processes=tuple(following_processes),
            blocked_process_offset=blocked_process_offset,
            blocked_process_type=blocked_process_type,
            terminator_offset=terminator_offset,
        )


# Deprecated compatibility aliases. Keeping identity, rather than subclasses,
# preserves ``isinstance`` behavior and existing imports without duplicating
# the parser implementation.
U9ItemHandleEntry = U9ObjectReferenceEntry
U9ItemHandleTable = U9ObjectReferenceTable
