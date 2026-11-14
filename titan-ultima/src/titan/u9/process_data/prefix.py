"""The ``processes.dat`` prefix reader that walks every decodable section."""

from __future__ import annotations

__all__ = ["U9ProcessRecordPrefix", "U9FollowingProcessState", "U9ProcessDataPrefix"]

import os
import struct
from dataclasses import dataclass
from typing import Union

from titan.u9.process_data._base import (
    ANIMATION_CONTROLLER_PROCESS_TYPES,
    CLOCK_ANIMATION_PROCESS_TYPE,
    DOOR_TIMER_PROCESS_TYPE,
    FLOATING_LANTERN_PROCESS_TYPE,
    HANGING_OBJECT_PROCESS_TYPE,
    MAX_PROCESS_TYPE,
    MIN_PROCESS_TYPE,
    MOVEMENT_CONTROLLER_PROCESS_TYPES,
    NPC_ACTION_PROCESS_TYPES,
    NPC_ACTIVITY_PROCESS_TYPES,
    PATHFINDER_PROCESS_TYPE,
    PLAYER_PROXIMITY_PROCESS_TYPE,
    PORTABLE_LIGHT_PROCESS_TYPE,
    SCRIPTED_OBJECT_PROCESS_TYPES,
    SCRIPT_TIMER_PROCESS_TYPE,
    SKELETON_REFORM_PROCESS_TYPE,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    _require_bytes,
)
from titan.u9.process_data.animation import U9AnimationControllerProcessState
from titan.u9.process_data.camera import U9CameraControlState, U9CameraState
from titan.u9.process_data.effects import (
    ACID_RAIN_PROCESS_TYPE,
    U9AcidRainProcessState,
    U9FloatingLanternProcessState,
    U9SkeletonReformProcessState,
)
from titan.u9.process_data.movement import U9MovementControllerProcessState
from titan.u9.process_data.objects import (
    U9HangingObjectProcessState,
    U9PlayerProximityProcessState,
    U9PortableLightProcessState,
    U9ScriptTimerProcessState,
)
from titan.u9.process_data.particles import U9ParticleProcessState
from titan.u9.process_data.pathfinding import U9PathfinderProcessState
from titan.u9.process_data.references import U9ObjectReferenceTable
from titan.u9.process_data.simple import (
    HEADERLESS_PROCESS_LAYOUTS,
    SIMPLE_PROCESS_LAYOUTS,
    U9HeaderlessProcessState,
    U9SimpleProcessState,
)
from titan.u9.process_data.world import (
    U9ClockAnimationProcessState,
    U9DoorTimerProcessState,
    U9NpcActionProcessState,
    U9NpcActivityProcessState,
    U9ScriptedObjectProcessState,
)


WORLD_PROCESS_TYPES = frozenset(
    {
        HANGING_OBJECT_PROCESS_TYPE,
        SCRIPT_TIMER_PROCESS_TYPE,
        PORTABLE_LIGHT_PROCESS_TYPE,
        PLAYER_PROXIMITY_PROCESS_TYPE,
        104,
    }
)
PARTICLE_PROCESS_TYPE = 104


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


U9FollowingProcessState = Union[
    U9AcidRainProcessState,
    U9HeaderlessProcessState,
    U9AnimationControllerProcessState,
    U9HangingObjectProcessState,
    U9ScriptTimerProcessState,
    U9PortableLightProcessState,
    U9PlayerProximityProcessState,
    U9MovementControllerProcessState,
    U9ScriptedObjectProcessState,
    U9ClockAnimationProcessState,
    U9NpcActivityProcessState,
    U9NpcActionProcessState,
    U9DoorTimerProcessState,
    U9SimpleProcessState,
    U9PathfinderProcessState,
    U9SkeletonReformProcessState,
    U9FloatingLanternProcessState,
]
# Decoder for each process type the traversal reads after the first process.
_FOLLOWING_PROCESS_DECODERS: dict[int, type[U9FollowingProcessState]] = {
    HANGING_OBJECT_PROCESS_TYPE: U9HangingObjectProcessState,
    SCRIPT_TIMER_PROCESS_TYPE: U9ScriptTimerProcessState,
    PORTABLE_LIGHT_PROCESS_TYPE: U9PortableLightProcessState,
    PLAYER_PROXIMITY_PROCESS_TYPE: U9PlayerProximityProcessState,
    CLOCK_ANIMATION_PROCESS_TYPE: U9ClockAnimationProcessState,
    DOOR_TIMER_PROCESS_TYPE: U9DoorTimerProcessState,
    PATHFINDER_PROCESS_TYPE: U9PathfinderProcessState,
    SKELETON_REFORM_PROCESS_TYPE: U9SkeletonReformProcessState,
    FLOATING_LANTERN_PROCESS_TYPE: U9FloatingLanternProcessState,
    **dict.fromkeys(
        ANIMATION_CONTROLLER_PROCESS_TYPES, U9AnimationControllerProcessState
    ),
    **dict.fromkeys(
        MOVEMENT_CONTROLLER_PROCESS_TYPES, U9MovementControllerProcessState
    ),
    **dict.fromkeys(SCRIPTED_OBJECT_PROCESS_TYPES, U9ScriptedObjectProcessState),
    **dict.fromkeys(NPC_ACTIVITY_PROCESS_TYPES, U9NpcActivityProcessState),
    **dict.fromkeys(NPC_ACTION_PROCESS_TYPES, U9NpcActionProcessState),
    **dict.fromkeys(SIMPLE_PROCESS_LAYOUTS, U9SimpleProcessState),
    **dict.fromkeys(HEADERLESS_PROCESS_LAYOUTS, U9HeaderlessProcessState),
    ACID_RAIN_PROCESS_TYPE: U9AcidRainProcessState,
}


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
    following_processes: tuple[U9FollowingProcessState, ...]
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
        temporary_camera = camera_control.temporary_camera
        if temporary_camera is not None and not (
            0 <= temporary_camera.object_reference_index < object_references.count
        ):
            raise U9ProcessDataError(
                "temporary-camera object-reference index "
                f"{temporary_camera.object_reference_index} is outside "
                f"0..{object_references.count - 1}"
            )
        process_list_offset = camera_control.end_offset
        first_process_type = None
        first_process = None
        next_process_offset = None
        next_process_type = None
        next_process_header = None
        following_processes: list[U9FollowingProcessState] = []
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
                        decoder = _FOLLOWING_PROCESS_DECODERS.get(process_type)
                        if decoder is None:
                            blocked_process_offset = cursor
                            blocked_process_type = process_type
                            break
                        process = decoder.from_bytes(
                            data,
                            cursor,
                            object_reference_count=object_references.count,
                        )
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
