"""Animation controller processes and their track states."""

from __future__ import annotations

__all__ = [
    "U9AnimationCallbackState",
    "U9AnimationTrackState",
    "U9KinematicTrackState",
    "U9AnimationControllerProcessState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import (
    ANIMATION_CONTROLLER_PROCESS_TYPE,
    ANIMATION_CONTROLLER_PROCESS_TYPES,
    AVATAR_ANIMATION_CONTROLLER_PROCESS_TYPE,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    _require_bytes,
    _validate_byte_boolean,
    _validate_finite,
    _validate_object_reference_index,
)


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
    """A layered animation controller with five playback tracks.

    Type 98 is the general controller; type 213 is the Avatar's, which the
    retail executable saves and loads with the same routines.
    """

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
        if process_type not in ANIMATION_CONTROLLER_PROCESS_TYPES:
            raise U9ProcessDataError(
                f"expected animation-controller process type "
                f"{ANIMATION_CONTROLLER_PROCESS_TYPE} or "
                f"{AVATAR_ANIMATION_CONTROLLER_PROCESS_TYPE}, found {process_type}"
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
