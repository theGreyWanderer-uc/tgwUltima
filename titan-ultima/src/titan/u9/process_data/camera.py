"""Camera, camera-effect, targeting and camera-control states."""

from __future__ import annotations

__all__ = [
    "U9CameraEffectState",
    "U9CameraState",
    "U9TargetingState",
    "U9TemporaryCameraState",
    "U9CameraControlState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import (
    CAMERA_VERSION,
    U9ProcessDataError,
    _require_bytes,
)


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
# Temporary camera: version, word, object reference, word, then float
# triples and words as the retail writer emits them, a byte, four zero words.
TEMPORARY_CAMERA_STATE = struct.Struct("<iiii3f3i3f3i3f4i2i3f4i3i3fiB4I")
TEMPORARY_CAMERA_VERSION = 5


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
class U9TemporaryCameraState:
    """The optional 173-byte temporary-camera record (version 5).

    Written after the camera control when its presence marker is non-zero,
    and followed by the targeting state. The layout comes from the retail
    save and load routines; no retail save containing one has been checked,
    so ``boundary_confirmed`` is ``False``. Field meanings are not
    established: ``vectors`` are the five float triples and ``words`` the
    remaining 32-bit fields, each in stream order. Titan requires version 5
    and the four trailing zero words before accepting the boundary.
    """

    version: int
    object_reference_index: int
    vectors: tuple[tuple[float, float, float], ...]
    words: tuple[int, ...]
    flag: int
    reserved: tuple[int, int, int, int]
    offset: int
    boundary_confirmed: bool = False

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9TemporaryCameraState:
        _require_bytes(data, offset, TEMPORARY_CAMERA_STATE.size, "temporary camera")
        v = TEMPORARY_CAMERA_STATE.unpack_from(data, offset)
        if v[0] != TEMPORARY_CAMERA_VERSION:
            raise U9ProcessDataError(
                f"unsupported temporary-camera version {v[0]} at 0x{offset:X}"
            )
        reserved = v[40:44]
        if any(reserved):
            raise U9ProcessDataError(
                f"temporary camera at 0x{offset:X} has non-zero closing words"
            )
        return cls(
            version=v[0],
            object_reference_index=v[2],
            vectors=(v[4:7], v[10:13], v[16:19], v[25:28], v[35:38]),
            words=(v[1], v[3], *v[7:10], *v[13:16], *v[19:25], *v[28:35], v[38]),
            flag=v[39],
            reserved=reserved,
            offset=offset,
        )

    @property
    def end_offset(self) -> int:
        return self.offset + TEMPORARY_CAMERA_STATE.size


@dataclass(frozen=True)
class U9CameraControlState:
    """Saved camera targeting, distance, shake, and targeting-cursor state."""

    version: int
    target_position: tuple[float, float, float]
    target_yaw: float
    target_pitch: float
    no_target_range_limit: bool | None
    target_fov: float | None
    current_distance: float | None
    maximum_distance: float | None
    maximum_target_distance: float | None
    aim_line_radius: float | None
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
    shock_rise_time: float | None
    shock_remaining_build_time: float | None
    shock_fall_time: float | None
    shock_remaining_decay_time: float | None
    shock_peak: int | None
    target_lock_rectangle: tuple[int, int, int, int] | None
    far_npcs_active: bool | None
    far_objects_active: bool | None
    has_temporary_camera: bool
    targeting: U9TargetingState | None
    offset: int
    end_offset: int | None
    temporary_camera: U9TemporaryCameraState | None = None

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
            no_target_range_limit = None
            target_fov = None
            current_distance = None
            maximum_distance = None
            maximum_target_distance = None
            aim_line_radius = None
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
            shock_rise_time = None
            shock_remaining_build_time = None
            shock_fall_time = None
            shock_remaining_decay_time = None
            shock_peak = None
            target_lock_rectangle = None
            far_npcs_active = None
            far_objects_active = None
        else:
            _require_bytes(data, offset, CAMERA_CONTROL_EXTENDED_SIZE, "camera control")
            values = struct.unpack_from("<I3f2f", data, offset)
            marker_offset = offset + 176
            no_target_range_limit = bool(struct.unpack_from("<I", data, offset + 24)[0])
            target_fov, current_distance, maximum_distance = struct.unpack_from(
                "<3f", data, offset + 28
            )
            maximum_target_distance, aim_line_radius = struct.unpack_from(
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
                shock_rise_time,
                shock_remaining_build_time,
                shock_fall_time,
                shock_remaining_decay_time,
            ) = struct.unpack_from("<4f", data, offset + 132)
            (shock_peak,) = struct.unpack_from("<i", data, offset + 148)
            target_lock_rectangle = struct.unpack_from("<4i", data, offset + 152)
            far_npcs_active, far_objects_active = (
                bool(value) for value in struct.unpack_from("<2I", data, offset + 168)
            )

        (temporary_marker,) = struct.unpack_from("<I", data, marker_offset)
        has_temporary_camera = temporary_marker != 0
        targeting = None
        temporary_camera = None
        end_offset: int | None = marker_offset + 4
        if version == 2:
            # The marker is the saved pointer to the temporary camera; its
            # record (fixed 173 bytes) comes before the targeting state,
            # which version 2 always writes.
            cursor = marker_offset + 4
            if has_temporary_camera:
                temporary_camera = U9TemporaryCameraState.from_bytes(data, cursor)
                cursor = temporary_camera.end_offset
            targeting = U9TargetingState.from_bytes(data, cursor)
            end_offset = targeting.end_offset
        elif has_temporary_camera:
            # Only version 2 is written by retail; an older stream with a
            # temporary camera has no known layout.
            end_offset = None

        return cls(
            version=version,
            target_position=(values[1], values[2], values[3]),
            target_yaw=values[4],
            target_pitch=values[5],
            no_target_range_limit=no_target_range_limit,
            target_fov=target_fov,
            current_distance=current_distance,
            maximum_distance=maximum_distance,
            maximum_target_distance=maximum_target_distance,
            aim_line_radius=aim_line_radius,
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
            shock_rise_time=shock_rise_time,
            shock_remaining_build_time=shock_remaining_build_time,
            shock_fall_time=shock_fall_time,
            shock_remaining_decay_time=shock_remaining_decay_time,
            shock_peak=shock_peak,
            target_lock_rectangle=target_lock_rectangle,
            far_npcs_active=far_npcs_active,
            far_objects_active=far_objects_active,
            has_temporary_camera=has_temporary_camera,
            targeting=targeting,
            offset=offset,
            end_offset=end_offset,
            temporary_camera=temporary_camera,
        )
