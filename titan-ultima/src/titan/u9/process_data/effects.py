"""Acid rain, skeleton reform and floating lantern processes."""

from __future__ import annotations

__all__ = [
    "U9AcidRainProcessState",
    "U9SkeletonBoneState",
    "U9SkeletonReformProcessState",
    "U9FloatingLanternProcessState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import (
    FLOATING_LANTERN_PROCESS_TYPE,
    SKELETON_REFORM_PROCESS_TYPE,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    _read_world_process_prefix,
    _require_bytes,
    _validate_byte_boolean,
    _validate_object_reference_index,
)
from titan.u9.process_data.pathfinding import U9PathManagerState
from titan.u9.process_data.world import U9SpellState


SKELETON_REFORM_PROCESS_VERSION = 2
SKELETON_BONE_COUNT = 11
SKELETON_BONE = struct.Struct("<i3f3f4f4f3ff3fB")
SKELETON_REFORM_TAIL = struct.Struct("<iBBii3ff")
FLOATING_LANTERN_PROCESS_VERSION = 1
FLOATING_LANTERN_TAIL = struct.Struct("<fi3i3ii4I")
ACID_RAIN_PROCESS_TYPE = 142
ACID_RAIN_MAXIMUM_TARGETS = 32  # the in-memory array holds 32 references
ACID_RAIN_HEAD = struct.Struct("<iIIi")
ACID_RAIN_TAIL = struct.Struct("<I3I4I")


@dataclass(frozen=True)
class U9AcidRainProcessState:
    """The acid-rain spell (type 142): the shared spell block, then version
    1, two words, a counted list of target object references, a word, three
    words and four reserved words (48 bytes plus 4 per target).

    Read from the retail save routine; no saved example has been checked.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    spell_state: U9SpellState
    version: int
    word_1: int
    word_2: int
    target_object_reference_indices: tuple[int, ...]
    word_3: int
    words: tuple[int, int, int]
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9AcidRainProcessState:
        header = U9ProcessHeaderState.from_bytes(data, offset)
        world_state = U9ProcessWorldState.from_bytes(
            data, header.end_offset, object_reference_count=object_reference_count
        )
        spell_state = U9SpellState.from_bytes(
            data, world_state.end_offset, object_reference_count=object_reference_count
        )
        cursor = spell_state.end_offset
        _require_bytes(data, cursor, ACID_RAIN_HEAD.size, "acid-rain process")
        version, word_1, word_2, count = ACID_RAIN_HEAD.unpack_from(data, cursor)
        if version != 1:
            raise U9ProcessDataError(
                f"unsupported acid-rain process version {version} at 0x{cursor:X}"
            )
        if not 0 <= count <= ACID_RAIN_MAXIMUM_TARGETS:
            raise U9ProcessDataError(
                f"invalid acid-rain target count {count} at 0x{cursor + 12:X}"
            )
        cursor += ACID_RAIN_HEAD.size
        _require_bytes(data, cursor, 4 * count, "acid-rain targets")
        targets = struct.unpack_from(f"<{count}i", data, cursor)
        for index in targets:
            _validate_object_reference_index(
                index, object_reference_count, "acid-rain target"
            )
        cursor += 4 * count
        _require_bytes(data, cursor, ACID_RAIN_TAIL.size, "acid-rain process")
        tail = ACID_RAIN_TAIL.unpack_from(data, cursor)
        return cls(
            header=header,
            world_state=world_state,
            spell_state=spell_state,
            version=version,
            word_1=word_1,
            word_2=word_2,
            target_object_reference_indices=targets,
            word_3=tail[0],
            words=tail[1:4],
            reserved=tail[4:8],
            offset=offset,
            end_offset=cursor + ACID_RAIN_TAIL.size,
        )


@dataclass(frozen=True)
class U9SkeletonBoneState:
    """One of the 11 bones a skeleton-reform process gathers (89 bytes)."""

    bone_object_reference_index: int
    final_position: tuple[float, float, float]
    ground_position: tuple[float, float, float]
    final_orientation: tuple[float, float, float, float]
    ground_orientation: tuple[float, float, float, float]
    move_orientation_axis: tuple[float, float, float]
    move_orientation_rate: float
    current_destination: tuple[float, float, float]
    moving_to_final: bool


@dataclass(frozen=True)
class U9SkeletonReformProcessState:
    """A type-55 process that reassembles a skeleton from its bones.

    World state, then version 2, eleven bone records, and the search and
    skeleton state. Floats are not range-checked: bones not yet found keep
    whatever their slots held.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    bones: tuple[U9SkeletonBoneState, ...]
    find_delay: int
    found_all_bones: bool
    bones_ready: bool
    bone_key_object_reference_index: int
    skeleton_object_reference_index: int
    skeleton_position: tuple[float, float, float]
    move_rate: float
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9SkeletonReformProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            frozenset({SKELETON_REFORM_PROCESS_TYPE}),
            "skeleton-reform",
            object_reference_count,
        )
        cursor = world_state.end_offset
        size = 4 + SKELETON_BONE_COUNT * SKELETON_BONE.size + SKELETON_REFORM_TAIL.size
        _require_bytes(data, cursor, size, "skeleton-reform process")
        (version,) = struct.unpack_from("<i", data, cursor)
        if version != SKELETON_REFORM_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported skeleton-reform version {version} at 0x{cursor:X}"
            )
        cursor += 4
        bones = []
        for _ in range(SKELETON_BONE_COUNT):
            b = SKELETON_BONE.unpack_from(data, cursor)
            cursor += SKELETON_BONE.size
            _validate_object_reference_index(
                b[0], object_reference_count, "skeleton-reform bone"
            )
            _validate_byte_boolean(b[22], "skeleton-reform moving-to-final")
            bones.append(
                U9SkeletonBoneState(
                    bone_object_reference_index=b[0],
                    final_position=b[1:4],
                    ground_position=b[4:7],
                    final_orientation=b[7:11],
                    ground_orientation=b[11:15],
                    move_orientation_axis=b[15:18],
                    move_orientation_rate=b[18],
                    current_destination=b[19:22],
                    moving_to_final=bool(b[22]),
                )
            )
        t = SKELETON_REFORM_TAIL.unpack_from(data, cursor)
        _validate_byte_boolean(t[1], "skeleton-reform found-all-bones")
        _validate_byte_boolean(t[2], "skeleton-reform bones-ready")
        for index, label in ((3, "bone key"), (4, "skeleton")):
            _validate_object_reference_index(
                t[index], object_reference_count, f"skeleton-reform {label}"
            )
        return cls(
            header=header,
            world_state=world_state,
            version=version,
            bones=tuple(bones),
            find_delay=t[0],
            found_all_bones=bool(t[1]),
            bones_ready=bool(t[2]),
            bone_key_object_reference_index=t[3],
            skeleton_object_reference_index=t[4],
            skeleton_position=t[5:8],
            move_rate=t[8],
            offset=offset,
            end_offset=cursor + SKELETON_REFORM_TAIL.size,
        )


@dataclass(frozen=True)
class U9FloatingLanternProcessState:
    """A type-13 floating lantern following a path.

    World state, version 1, the lantern object, its path manager, then
    timing, the target and offset words, end-condition flags and four
    reserved words. ``target_position_words`` and ``accumulated_offset_words``
    are kept as the stored 32-bit words: the one retail record seen holds
    integer-looking values there, so their element type is not settled.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    lantern_object_reference_index: int
    path: U9PathManagerState
    accumulated_time: float
    returning_to_path: int
    target_position_words: tuple[int, int, int]
    accumulated_offset_words: tuple[int, int, int]
    stop_flags: int
    reserved: tuple[int, int, int, int]
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9FloatingLanternProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            frozenset({FLOATING_LANTERN_PROCESS_TYPE}),
            "floating-lantern",
            object_reference_count,
        )
        cursor = world_state.end_offset
        _require_bytes(data, cursor, 8, "floating-lantern process")
        version, lantern = struct.unpack_from("<ii", data, cursor)
        if version != FLOATING_LANTERN_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported floating-lantern version {version} at 0x{cursor:X}"
            )
        _validate_object_reference_index(
            lantern, object_reference_count, "floating-lantern"
        )
        path = U9PathManagerState.from_bytes(
            data, cursor + 8, object_reference_count=object_reference_count
        )
        cursor = path.end_offset
        _require_bytes(
            data, cursor, FLOATING_LANTERN_TAIL.size, "floating-lantern tail"
        )
        t = FLOATING_LANTERN_TAIL.unpack_from(data, cursor)
        return cls(
            header=header,
            world_state=world_state,
            version=version,
            lantern_object_reference_index=lantern,
            path=path,
            accumulated_time=t[0],
            returning_to_path=t[1],
            target_position_words=t[2:5],
            accumulated_offset_words=t[5:8],
            stop_flags=t[8],
            reserved=t[9:13],
            offset=offset,
            end_offset=cursor + FLOATING_LANTERN_TAIL.size,
        )
