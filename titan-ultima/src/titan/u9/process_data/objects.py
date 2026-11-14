"""World-object processes: hanging objects, script timers, portable lights, proximity."""

from __future__ import annotations

__all__ = [
    "U9HangingObjectProcessState",
    "U9ScriptTimerProcessState",
    "U9PortableLightProcessState",
    "U9PlayerProximityProcessState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import (
    HANGING_OBJECT_PROCESS_TYPE,
    PLAYER_PROXIMITY_PROCESS_TYPE,
    PORTABLE_LIGHT_PROCESS_TYPE,
    SCRIPT_TIMER_PROCESS_TYPE,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    U9ScriptedProcessState,
    _require_bytes,
    _validate_finite,
    _validate_object_reference_index,
)


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
    turn_mode: int
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
    in_collision: bool
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
            turn_mode=values[5],
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
            in_collision=bool(values[45]),
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
    def configured_turn_mode(self) -> int:
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
    two_phase: int
    clock_kind: int
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
            two_phase=values[3],
            clock_kind=values[4],
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
    def configured_clock_kind(self) -> int:
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
