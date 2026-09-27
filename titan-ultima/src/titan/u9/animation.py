"""
``static/anim.flx`` reader for Ultima 9: Ascension.

Each used FLX entry is one animation clip. The entry stores its original
LightWave scene path, a fixed-capacity part registry, one transform track per
animated part, and zero or more typed animation events::

    0x00  stored_animation_id  s32  -- matches the FLX entry index in retail data
    0x04  start_frame          s32  -- inclusive LightWave source-frame number
    0x08  end_frame            s32  -- inclusive
    0x0C  frame_count          s32  -- end_frame - start_frame + 1 in retail data
    0x10  source_fps           s32  -- 30 in every shipped entry
    0x14  frame_interval_ms    s32  -- 33 in every shipped entry
    0x18  source_name_length   s32
    0x1C  source_name        ASCII[source_name_length], not NUL-terminated
          registry_size      s32
          part_registry      s32[registry_size]
          part_count         s32
          parts              part[part_count]
          event_count        s32
          events             event[event_count]

A part is ``s32 part_id``, a length-prefixed ASCII name, ``s32 frame_count``,
then that many 44-byte frames. There is no extra word between ``frame_count``
and the first frame. A frame is::

    0x00  time_ms   s32
    0x04  rotation  float32[4]  -- quaternion W, X, Y, Z
    0x14  position  float32[3]
    0x20  scale     float32[3]

This order matters. Reading the first word as a float and the last as time
turns the real timestamps into denormals and reports the final ``1.0`` scale
component as the constant integer 1065353216.

An event is ``s32 time_ms, u32 type, u32 parameter``.  The type values are
``1=loop``, ``2=contact``, ``3=sound_effect``, ``4=footstep`` and
``8=end_of_animation`` in the shipped archive.

Verified against all 857 used entries in the shipped 4,000-slot archive:
every entry consumes exactly, all 1,310,139 frames are finite and carry a
unit quaternion, every part in a clip has the declared frame count and the
same timestamps, and every registry prefix exactly matches the stored part
IDs. Registry words after that prefix are retained as inactive writer residue.
The runtime loads the complete fixed-capacity array but only reads the active
prefix.

Example::

    from titan.u9.animation import U9Animations

    animations = U9Animations.from_file("static/anim.flx")
    clip = animations.animation(172)
    if clip is not None:
        print(clip.source_name, clip.frame_count, len(clip.parts))
"""

from __future__ import annotations

__all__ = [
    "U9Animation",
    "U9AnimationError",
    "U9AnimationEvent",
    "U9AnimationFrame",
    "U9AnimationPart",
    "U9AnimationSuffix",
    "U9Animations",
]

import math
import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

ENTRY_HEADER_STRUCT = "<7i"
ENTRY_HEADER_SIZE = struct.calcsize(ENTRY_HEADER_STRUCT)
FRAME_STRUCT = "<i10f"
FRAME_SIZE = struct.calcsize(FRAME_STRUCT)
SUFFIX_STRUCT = "<iII"
SUFFIX_SIZE = struct.calcsize(SUFFIX_STRUCT)
MAX_ANIMATION_RECORD_SIZE = 8 * 1024 * 1024

EVENT_TYPE_NAMES = {
    0: "none",
    1: "loop",
    2: "contact",
    3: "sound_effect",
    4: "footstep",
    5: "cycle_start",
    6: "cycle_ramp_up",
    7: "cycle_ramp_down",
    8: "end_of_animation",
}


class U9AnimationError(Exception):
    """Raised on malformed ``static/anim.flx`` data."""


@dataclass(frozen=True)
class U9AnimationFrame:
    """One part transform at ``time_ms`` from the start of the clip."""

    time_ms: int
    rotation: tuple[float, float, float, float]
    position: tuple[float, float, float]
    scale: tuple[float, float, float]


@dataclass(frozen=True)
class U9AnimationPart:
    """One named part and its transform track."""

    part_id: int
    name: str
    frames: tuple[U9AnimationFrame, ...]
    name_raw: bytes = b""

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def sample(self, time_ms: int) -> U9AnimationFrame | None:
        """Sample this track using the runtime's clamped interpolation rules.

        Rotation uses spherical interpolation and position uses linear
        interpolation. Scale is retained and interpolated for completeness,
        although the shipped runtime animation controller does not apply it.
        """
        if not self.frames:
            return None
        index = next(
            (
                frame_index
                for frame_index, frame in enumerate(self.frames)
                if frame.time_ms >= time_ms
            ),
            len(self.frames),
        )
        if index == 0:
            return self.frames[0]
        if index >= len(self.frames):
            return self.frames[-1]
        right = self.frames[index]
        left = self.frames[index - 1]
        span = right.time_ms - left.time_ms
        if span <= 0:
            return right
        amount = (time_ms - left.time_ms) / span
        return U9AnimationFrame(
            time_ms=time_ms,
            rotation=_slerp(left.rotation, right.rotation, amount),
            position=_lerp3(left.position, right.position, amount),
            scale=_lerp3(left.scale, right.scale, amount),
        )

    @property
    def timestamp_status(self) -> str:
        """Whether stored sample times are monotonic, as runtime sampling expects."""
        return (
            "monotonic"
            if all(
                left.time_ms <= right.time_ms
                for left, right in zip(self.frames, self.frames[1:])
            )
            else "out_of_order"
        )

    @property
    def transform_status(self) -> str:
        """Whether all stored transform components are finite."""
        return (
            "finite"
            if all(
                math.isfinite(value)
                for frame in self.frames
                for value in (*frame.rotation, *frame.position, *frame.scale)
            )
            else "nonfinite"
        )


@dataclass(frozen=True)
class U9AnimationSuffix:
    """One animation event after the part tracks.

    The historical class name is retained for API compatibility. New callers
    should use the :data:`U9AnimationEvent` alias or ``animation.events``.
    """

    values: tuple[int, int, int]

    @property
    def time_ms(self) -> int:
        return self.values[0]

    @property
    def event_type(self) -> int:
        return self.values[1]

    @property
    def parameter(self) -> int:
        return self.values[2]

    @property
    def event_name(self) -> str:
        return EVENT_TYPE_NAMES.get(self.event_type, f"unknown_{self.event_type}")


U9AnimationEvent = U9AnimationSuffix


@dataclass(frozen=True)
class U9Animation:
    """One animation clip, keyed by its FLX entry index."""

    animation_id: int
    start_frame: int
    end_frame: int
    frame_count: int
    source_fps: int
    frame_interval_ms: int
    source_name: str
    header_words: tuple[int, ...]
    parts: tuple[U9AnimationPart, ...]
    suffixes: tuple[U9AnimationSuffix, ...]
    stored_animation_id: int | None = None
    source_name_raw: bytes = b""
    trailing_data: bytes = b""
    _raw_data: bytes = b""

    @property
    def part_ids(self) -> tuple[int, ...]:
        return tuple(part.part_id for part in self.parts)

    @property
    def duration_ms(self) -> int:
        """Compatibility view of :attr:`last_sample_time_ms`."""
        return self.last_sample_time_ms

    @property
    def last_sample_time_ms(self) -> int:
        """Latest stored transform timestamp, or zero for an empty clip."""
        return max(
            (frame.time_ms for part in self.parts for frame in part.frames),
            default=0,
        )

    @property
    def runtime_length_ms(self) -> int | None:
        """Controller playback length, using integer ``1000 * frames / fps``."""
        if self.source_fps <= 0 or self.frame_count < 0:
            return None
        return 1000 * self.frame_count // self.source_fps

    @property
    def part_registry(self) -> tuple[int, ...]:
        """Compatibility view of the complete registry storage array."""
        return self.header_words

    @property
    def part_registry_storage(self) -> tuple[int, ...]:
        """Complete stored registry array, including inactive residue."""
        return self.header_words

    @property
    def active_part_registry(self) -> tuple[int, ...]:
        """Registry prefix consulted for the stored number of part tracks."""
        return self.header_words[: len(self.parts)]

    @property
    def part_registry_residue(self) -> tuple[int, ...]:
        """Inactive capacity words retained but not consulted by the runtime."""
        return self.header_words[len(self.parts) :]

    @property
    def stored_id_status(self) -> str:
        """Compare the stored clip ID with the FLX directory slot used to load it."""
        if self.stored_animation_id is None:
            return "unavailable"
        return (
            "matches_entry"
            if self.stored_animation_id == self.animation_id
            else "mismatch"
        )

    @property
    def frame_range_status(self) -> str:
        """Compare the inclusive authoring range with the stored frame count."""
        return (
            "matches_count"
            if self.end_frame >= self.start_frame
            and self.end_frame - self.start_frame + 1 == self.frame_count
            else "mismatch"
        )

    @property
    def runtime_timing_status(self) -> str:
        """Validate cells needed for controller playback-length calculation."""
        if self.source_fps <= 0:
            return "invalid_source_fps"
        if self.frame_count < 0:
            return "negative_frame_count"
        if self.frame_interval_ms < 0:
            return "negative_nominal_interval"
        return "valid"

    @property
    def part_frame_count_status(self) -> str:
        """Report whether every track carries the header-declared sample count."""
        return (
            "matches_clip"
            if all(part.frame_count == self.frame_count for part in self.parts)
            else "mismatch"
        )

    @property
    def part_registry_status(self) -> str:
        """Compare the active registry prefix with the following part IDs."""
        if len(self.header_words) < len(self.parts):
            return "shorter_than_parts"
        return (
            "matches_parts"
            if self.active_part_registry == self.part_ids
            else "mismatch"
        )

    @property
    def timestamp_status(self) -> str:
        """Summarize transform timestamp ordering across all part tracks."""
        return (
            "monotonic"
            if all(part.timestamp_status == "monotonic" for part in self.parts)
            else "out_of_order"
        )

    @property
    def transform_status(self) -> str:
        """Summarize finite transform storage across all part tracks."""
        return (
            "finite"
            if all(part.transform_status == "finite" for part in self.parts)
            else "nonfinite"
        )

    @property
    def event_order_status(self) -> str:
        """Report whether event timestamps are in runtime dispatch order."""
        return (
            "monotonic"
            if all(
                left.time_ms <= right.time_ms
                for left, right in zip(self.events, self.events[1:])
            )
            else "out_of_order"
        )

    @property
    def events(self) -> tuple[U9AnimationEvent, ...]:
        """Typed animation events (historically exposed as ``suffixes``)."""
        return self.suffixes

    def part(self, part_id: int) -> U9AnimationPart | None:
        """Return the part with this ID, or ``None`` when it is absent."""
        return next((part for part in self.parts if part.part_id == part_id), None)

    def to_bytes(self) -> bytes:
        """Return the exact source record, including inactive and trailing bytes."""
        if not self._raw_data:
            raise U9AnimationError(
                "animation was constructed in memory and has no source bytes"
            )
        return self._raw_data

    @classmethod
    def parse(cls, data: bytes, animation_id: int) -> U9Animation:
        """Parse one raw ``anim.flx`` entry."""
        if len(data) < ENTRY_HEADER_SIZE:
            raise U9AnimationError(
                f"animation {animation_id}: {len(data)} bytes is too small for "
                f"the {ENTRY_HEADER_SIZE}-byte header"
            )

        (
            record_index,
            start_frame,
            end_frame,
            frame_count,
            source_fps,
            frame_interval_ms,
            source_name_length,
        ) = struct.unpack_from(ENTRY_HEADER_STRUCT, data)
        if source_name_length < 0:
            raise U9AnimationError(
                f"animation {animation_id}: negative source-name length "
                f"{source_name_length}"
            )

        pos = ENTRY_HEADER_SIZE
        source_raw, pos = _read_bytes(
            data,
            pos,
            source_name_length,
            animation_id,
            "source name",
        )
        source_name = source_raw.decode("ascii", errors="replace")

        registry_size, pos = _read_count(data, pos, animation_id, "part-registry size")
        registry_bytes = registry_size * 4
        registry_raw, pos = _read_bytes(
            data,
            pos,
            registry_bytes,
            animation_id,
            "part-registry block",
        )
        header_words = (
            struct.unpack(f"<{registry_size}i", registry_raw) if registry_size else ()
        )

        part_count, pos = _read_count(data, pos, animation_id, "part count")
        parts: list[U9AnimationPart] = []
        for part_index in range(part_count):
            part, pos = _read_part(
                data,
                pos,
                animation_id,
                part_index,
            )
            parts.append(part)

        event_count, pos = _read_count(data, pos, animation_id, "event count")
        event_bytes = event_count * SUFFIX_SIZE
        event_raw, pos = _read_bytes(
            data,
            pos,
            event_bytes,
            animation_id,
            "animation events",
        )
        suffixes = tuple(
            U9AnimationSuffix(values=values)
            for values in struct.iter_unpack(SUFFIX_STRUCT, event_raw)
        )

        return cls(
            animation_id=animation_id,
            start_frame=start_frame,
            end_frame=end_frame,
            frame_count=frame_count,
            source_fps=source_fps,
            frame_interval_ms=frame_interval_ms,
            source_name=source_name,
            header_words=header_words,
            parts=tuple(parts),
            suffixes=suffixes,
            stored_animation_id=record_index,
            source_name_raw=source_raw,
            trailing_data=data[pos:],
            _raw_data=data,
        )


class U9Animations:
    """Reader for the clips in ``static/anim.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self._archive = archive

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Animations:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as e:
            raise U9AnimationError(f"not a readable FLX archive: {e}") from e

    @property
    def num_entries(self) -> int:
        return self._archive.num_entries

    def used_animation_ids(self) -> list[int]:
        """FLX entry indices that hold animation clips."""
        return self._archive.used_entry_indices()

    def animation(self, animation_id: int) -> U9Animation | None:
        """Return one clip, or ``None`` if that FLX slot is unused."""
        if animation_id < 0 or animation_id >= self.num_entries:
            raise U9AnimationError(
                f"animation ID {animation_id} out of range (0..{self.num_entries - 1})"
            )
        data = self._archive.read_entry(animation_id)
        if not data:
            return None
        if len(data) > MAX_ANIMATION_RECORD_SIZE:
            raise U9AnimationError(
                f"animation {animation_id}: {len(data)}-byte record exceeds the "
                f"retail {MAX_ANIMATION_RECORD_SIZE}-byte limit"
            )
        return U9Animation.parse(data, animation_id)

    def animations(self) -> list[U9Animation]:
        """Parse every used clip, in animation-ID order."""
        result = []
        for animation_id in self.used_animation_ids():
            animation = self.animation(animation_id)
            if animation is not None:
                result.append(animation)
        return result


def _read_i32(
    data: bytes,
    pos: int,
    animation_id: int,
    description: str,
) -> tuple[int, int]:
    if pos + 4 > len(data):
        raise U9AnimationError(
            f"animation {animation_id}: truncated before {description} at offset {pos:#x}"
        )
    return struct.unpack_from("<i", data, pos)[0], pos + 4


def _read_count(
    data: bytes,
    pos: int,
    animation_id: int,
    description: str,
) -> tuple[int, int]:
    value, pos = _read_i32(data, pos, animation_id, description)
    if value < 0:
        raise U9AnimationError(
            f"animation {animation_id}: negative {description} {value}"
        )
    return value, pos


def _read_bytes(
    data: bytes,
    pos: int,
    size: int,
    animation_id: int,
    description: str,
) -> tuple[bytes, int]:
    end = pos + size
    if end > len(data):
        raise U9AnimationError(
            f"animation {animation_id}: {description} needs {size} byte(s) at "
            f"offset {pos:#x}, only {len(data) - pos} remain"
        )
    return data[pos:end], end


def _read_part(
    data: bytes,
    pos: int,
    animation_id: int,
    part_index: int,
) -> tuple[U9AnimationPart, int]:
    part_id, pos = _read_i32(data, pos, animation_id, f"part {part_index} ID")
    name_length, pos = _read_count(
        data, pos, animation_id, f"part {part_index} name length"
    )
    name_raw, pos = _read_bytes(
        data,
        pos,
        name_length,
        animation_id,
        f"part {part_index} name",
    )
    name = name_raw.decode("ascii", errors="replace")
    frame_count, pos = _read_count(
        data, pos, animation_id, f"part {part_index} frame count"
    )

    frame_raw, pos = _read_bytes(
        data,
        pos,
        frame_count * FRAME_SIZE,
        animation_id,
        f"part {part_index} frame array",
    )
    frames: list[U9AnimationFrame] = []
    for values in struct.iter_unpack(FRAME_STRUCT, frame_raw):
        time_ms = values[0]
        floats = values[1:]
        frames.append(
            U9AnimationFrame(
                time_ms=time_ms,
                rotation=tuple(floats[0:4]),
                position=tuple(floats[4:7]),
                scale=tuple(floats[7:10]),
            )
        )

    return U9AnimationPart(
        part_id=part_id,
        name=name,
        frames=tuple(frames),
        name_raw=name_raw,
    ), pos


def _lerp3(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    amount: float,
) -> tuple[float, float, float]:
    return (
        left[0] + (right[0] - left[0]) * amount,
        left[1] + (right[1] - left[1]) * amount,
        left[2] + (right[2] - left[2]) * amount,
    )


def _slerp(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    amount: float,
) -> tuple[float, float, float, float]:
    """Apply the retail WXYZ spherical interpolation branches exactly.

    The game does not negate a negative-dot destination or normalize the
    result. Its near-opposite branch also retains the temporary quaternion's
    scalar directly. No adjacent retail samples reach that fallback.
    """
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    if dot + 1.0 > 1e-5:
        if 1.0 - dot > 1e-5:
            angle = math.acos(dot)
            sine = math.sin(angle)
            source_weight = math.sin((1.0 - amount) * angle) / sine
            target_weight = math.sin(amount * angle) / sine
        else:
            source_weight = 1.0 - amount
            target_weight = amount
        return tuple(
            a * source_weight + b * target_weight
            for a, b in zip(left, right, strict=True)
        )  # type: ignore[return-value]

    temporary = (left[3], -left[2], left[1], -left[0])
    source_weight = math.sin((1.0 - amount) * math.pi / 2.0)
    target_weight = math.sin(amount * math.pi / 2.0)
    return (
        temporary[0],
        left[1] * source_weight + temporary[1] * target_weight,
        left[2] * source_weight + temporary[2] * target_weight,
        left[3] * source_weight + temporary[3] * target_weight,
    )
