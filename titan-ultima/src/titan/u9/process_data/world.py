"""Scripted object, clock, NPC activity/action, door timer and spell states."""

from __future__ import annotations

__all__ = [
    "U9ScriptedObjectProcessState",
    "U9ClockAnimationProcessState",
    "U9NpcActivityProcessState",
    "U9NpcActionProcessState",
    "U9DoorTimerProcessState",
    "U9SpellState",
]

import struct
from dataclasses import dataclass

from titan.u9.activity import U9ActivityActionKind, activity_action_kind
from titan.u9.process_data._base import (
    CLOCK_ANIMATION_PROCESS_TYPE,
    DOOR_TIMER_PROCESS_TYPE,
    NPC_ACTION_PROCESS_TYPES,
    NPC_ACTIVITY_PROCESS_TYPES,
    SCRIPTED_OBJECT_PROCESS_TYPES,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    U9ScriptedProcessState,
    _read_world_process_prefix,
    _require_bytes,
    _validate_finite,
    _validate_object_reference_index,
)


CLOCK_ANIMATION_PROCESS_VERSION = 0
CLOCK_ANIMATION_PROCESS_STATE = struct.Struct("<if")
NPC_ACTIVITY_PROCESS_VERSION = 2
NPC_ACTIVITY_VARIABLE_COUNT = 64
NPC_ACTIVITY_PROCESS_STATE = struct.Struct(f"<7i{NPC_ACTIVITY_VARIABLE_COUNT}i4I")
NPC_ACTION_PROCESS_VERSION = 4
NPC_ACTION_PROCESS_STATE = struct.Struct(
    f"<6ifi8if3i2ifi{NPC_ACTIVITY_VARIABLE_COUNT}ifi5i4I"
)
DOOR_TIMER_PROCESS_VERSION = 0
DOOR_TIMER_PROCESS_STATE = struct.Struct("<iif")
SPELL_STATE_VERSION = 4
SPELL_STATE = struct.Struct("<iiIiiiiiIii4I")


@dataclass(frozen=True)
class U9ScriptedObjectProcessState:
    """A process that saves only world state and scripted-object state.

    Types 50, 53, 54, 58 and 202 share this retail save (``0x0065D320``).
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    scripted_state: U9ScriptedProcessState
    offset: int

    @property
    def end_offset(self) -> int:
        return self.scripted_state.end_offset

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9ScriptedObjectProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            SCRIPTED_OBJECT_PROCESS_TYPES,
            "scripted-object",
            object_reference_count,
        )
        scripted_state = U9ScriptedProcessState.from_bytes(
            data, world_state.end_offset, object_reference_count=object_reference_count
        )
        return cls(header, world_state, scripted_state, offset)


@dataclass(frozen=True)
class U9ClockAnimationProcessState:
    """A type-57 clock animation: scripted-object state, version, loop time.

    ``loop_time_ms`` drives the pendulum swing (a sine over 1,000 ms
    periods). The game seeds it with a random value below 1,000 and keeps
    adding to it, so saved values grow with play time.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    scripted_state: U9ScriptedProcessState
    version: int
    loop_time_ms: float
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9ClockAnimationProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            frozenset({CLOCK_ANIMATION_PROCESS_TYPE}),
            "clock-animation",
            object_reference_count,
        )
        scripted_state = U9ScriptedProcessState.from_bytes(
            data, world_state.end_offset, object_reference_count=object_reference_count
        )
        payload_offset = scripted_state.end_offset
        _require_bytes(
            data,
            payload_offset,
            CLOCK_ANIMATION_PROCESS_STATE.size,
            "clock-animation process",
        )
        version, loop_time_ms = CLOCK_ANIMATION_PROCESS_STATE.unpack_from(
            data, payload_offset
        )
        if version != CLOCK_ANIMATION_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported clock-animation version {version} at 0x{payload_offset:X}"
            )
        _validate_finite((loop_time_ms,), "clock-animation loop time")
        return cls(
            header=header,
            world_state=world_state,
            scripted_state=scripted_state,
            version=version,
            loop_time_ms=loop_time_ms,
            offset=offset,
            end_offset=payload_offset + CLOCK_ANIMATION_PROCESS_STATE.size,
        )


@dataclass(frozen=True)
class U9NpcActivityProcessState:
    """A process that runs one NPC's scheduled activity.

    All 24 activity process types share one retail save (``0x00402970``):
    world state, then 300 bytes -- version 2, the NPC number, the action kind
    (a value of ``titan.u9.activity.ACTION_KIND_CATALOGUE``, e.g. 2 = loiter),
    the NPC's object reference, the activity's state, two flags, 64 activity
    variables and four reserved words. While it runs, the NPC's current step
    is a separate :class:`U9NpcActionProcessState` record.
    The activity variables are scratch words; some activities keep float
    bit patterns (such as positions) in them, so they are left as integers.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    npc_number: int
    action_kind: int
    npc_object_reference_index: int
    state: int
    activity_started: bool
    clears_hands_on_exit: bool
    activity_variables: tuple[int, ...]
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9NpcActivityProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            NPC_ACTIVITY_PROCESS_TYPES,
            "NPC-activity",
            object_reference_count,
        )
        payload_offset = world_state.end_offset
        _require_bytes(
            data,
            payload_offset,
            NPC_ACTIVITY_PROCESS_STATE.size,
            "NPC-activity process",
        )
        values = NPC_ACTIVITY_PROCESS_STATE.unpack_from(data, payload_offset)
        if values[0] != NPC_ACTIVITY_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported NPC-activity version {values[0]} at 0x{payload_offset:X}"
            )
        _validate_object_reference_index(
            values[3], object_reference_count, "NPC-activity"
        )
        for value, label in (
            (values[5], "activity-started"),
            (values[6], "clear-hands"),
        ):
            if value not in (0, 1):
                raise U9ProcessDataError(f"invalid {label} flag {value}")
        variables_end = 7 + NPC_ACTIVITY_VARIABLE_COUNT
        return cls(
            header=header,
            world_state=world_state,
            version=values[0],
            npc_number=values[1],
            action_kind=values[2],
            npc_object_reference_index=values[3],
            state=values[4],
            activity_started=bool(values[5]),
            clears_hands_on_exit=bool(values[6]),
            activity_variables=tuple(values[7:variables_end]),
            reserved=tuple(values[variables_end:]),  # type: ignore[arg-type]
            offset=offset,
            end_offset=payload_offset + NPC_ACTIVITY_PROCESS_STATE.size,
        )

    @property
    def action(self) -> U9ActivityActionKind:
        """The catalogued action kind (name and whether it is performed)."""
        return activity_action_kind(self.action_kind)


@dataclass(frozen=True)
class U9NpcActionProcessState:
    """A process that performs one NPC's current action (activity step).

    All 22 action process types share one retail save (``0x004016D0``):
    world state, then 396 bytes of navigation, timing, animation and
    collision state around the same 64 activity variables the activity
    process keeps. ``exit_timer`` is a raw timer word. ``careful_walk`` is an
    integer flag (the action code writes only 0 or 1 and never reads it as a
    float); retail saves often hold float-like values there, most likely
    leftover memory in action kinds that never set it, so the stored word is
    kept as is.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    npc_number: int
    action_kind: int
    pathfinding: bool
    pathfind_x: int
    pathfind_y: int
    error_tolerance: float
    npc_object_reference_index: int
    point_count: int
    state: int
    wants_to_exit: bool
    exit_timer: int
    target_x: int
    target_y: int
    careful_walk: int
    current_link: int
    target_angle: float
    origin_x: int
    origin_y: int
    stand_time: int
    queued_animation_id: int
    previous_animation_id: int
    animation_speed: float
    clears_hands_on_exit: bool
    activity_variables: tuple[int, ...]
    maximum_step_height: float
    extra_object_reference_index: int
    probes_per_frame: int
    probe_limit: int
    idle_animation_id: int
    needs_idle_animation: bool
    exits_next_frame: bool
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9NpcActionProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            NPC_ACTION_PROCESS_TYPES,
            "NPC-action",
            object_reference_count,
        )
        payload_offset = world_state.end_offset
        _require_bytes(
            data, payload_offset, NPC_ACTION_PROCESS_STATE.size, "NPC-action process"
        )
        v = NPC_ACTION_PROCESS_STATE.unpack_from(data, payload_offset)
        if v[0] != NPC_ACTION_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported NPC-action version {v[0]} at 0x{payload_offset:X}"
            )
        variables_end = 24 + NPC_ACTIVITY_VARIABLE_COUNT
        tail = v[variables_end:]
        _validate_object_reference_index(v[7], object_reference_count, "NPC-action")
        _validate_object_reference_index(
            tail[1], object_reference_count, "NPC-action extra"
        )
        for value, label in (
            (v[3], "pathfinding"),
            (v[10], "wants-to-exit"),
            (v[23], "clear-hands"),
            (tail[5], "needs-idle-animation"),
            (tail[6], "exit-next-frame"),
        ):
            if value not in (0, 1):
                raise U9ProcessDataError(f"invalid {label} flag {value}")
        _validate_finite((v[6], v[16], v[22], tail[0]), "NPC-action state")
        return cls(
            header=header,
            world_state=world_state,
            version=v[0],
            npc_number=v[1],
            action_kind=v[2],
            pathfinding=bool(v[3]),
            pathfind_x=v[4],
            pathfind_y=v[5],
            error_tolerance=v[6],
            npc_object_reference_index=v[7],
            point_count=v[8],
            state=v[9],
            wants_to_exit=bool(v[10]),
            exit_timer=v[11],
            target_x=v[12],
            target_y=v[13],
            careful_walk=v[14],
            current_link=v[15],
            target_angle=v[16],
            origin_x=v[17],
            origin_y=v[18],
            stand_time=v[19],
            queued_animation_id=v[20],
            previous_animation_id=v[21],
            animation_speed=v[22],
            clears_hands_on_exit=bool(v[23]),
            activity_variables=tuple(v[24:variables_end]),
            maximum_step_height=tail[0],
            extra_object_reference_index=tail[1],
            probes_per_frame=tail[2],
            probe_limit=tail[3],
            idle_animation_id=tail[4],
            needs_idle_animation=bool(tail[5]),
            exits_next_frame=bool(tail[6]),
            reserved=tuple(tail[7:]),  # type: ignore[arg-type]
            offset=offset,
            end_offset=payload_offset + NPC_ACTION_PROCESS_STATE.size,
        )

    @property
    def action(self) -> U9ActivityActionKind:
        """The catalogued action kind (name and whether it is performed)."""
        return activity_action_kind(self.action_kind)


@dataclass(frozen=True)
class U9DoorTimerProcessState:
    """A type-197 automatic-door timer: version, the door, elapsed time."""

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    door_object_reference_index: int
    elapsed_time: float
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9DoorTimerProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            frozenset({DOOR_TIMER_PROCESS_TYPE}),
            "door-timer",
            object_reference_count,
        )
        payload_offset = world_state.end_offset
        _require_bytes(
            data, payload_offset, DOOR_TIMER_PROCESS_STATE.size, "door-timer process"
        )
        version, door, elapsed = DOOR_TIMER_PROCESS_STATE.unpack_from(
            data, payload_offset
        )
        if version != DOOR_TIMER_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported door-timer version {version} at 0x{payload_offset:X}"
            )
        _validate_object_reference_index(door, object_reference_count, "door-timer")
        _validate_finite((elapsed,), "door-timer elapsed time")
        return cls(
            header=header,
            world_state=world_state,
            version=version,
            door_object_reference_index=door,
            elapsed_time=elapsed,
            offset=offset,
            end_offset=payload_offset + DOOR_TIMER_PROCESS_STATE.size,
        )


@dataclass(frozen=True)
class U9SpellState:
    """The 60-byte block every spell process saves after its world state.

    Written by the shared spell save (``0x005F23B0``): version 4, the caster,
    flags, the spell's particle effect, animation ID, event, spell number,
    stage, timer, the target, a callback number and four reserved words.
    """

    version: int
    caster_object_reference_index: int
    flags: int
    effect_object_reference_index: int
    animation_id: int
    event: int
    spell_number: int
    stage: int
    timer: int
    target_object_reference_index: int
    callback: int
    reserved: tuple[int, int, int, int]
    offset: int

    @property
    def end_offset(self) -> int:
        return self.offset + SPELL_STATE.size

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9SpellState:
        _require_bytes(data, offset, SPELL_STATE.size, "spell state")
        v = SPELL_STATE.unpack_from(data, offset)
        if v[0] != SPELL_STATE_VERSION:
            raise U9ProcessDataError(
                f"unsupported spell-state version {v[0]} at 0x{offset:X}"
            )
        for index, label in ((1, "caster"), (3, "effect"), (9, "target")):
            _validate_object_reference_index(
                v[index], object_reference_count, f"spell {label}"
            )
        return cls(
            version=v[0],
            caster_object_reference_index=v[1],
            flags=v[2],
            effect_object_reference_index=v[3],
            animation_id=v[4],
            event=v[5],
            spell_number=v[6],
            stage=v[7],
            timer=v[8],
            target_object_reference_index=v[9],
            callback=v[10],
            reserved=v[11:15],
            offset=offset,
        )
