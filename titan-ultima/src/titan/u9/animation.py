"""
``static/anim.flx`` reader for Ultima 9: Ascension.

Each used FLX entry is one animation clip. The entry stores its original
LightWave scene path, an opaque header-word block whose prefix is a part-ID
manifest, one transform track per animated part, and zero or more opaque
suffix triples::

    0x00  animation_id       u32  -- same as the FLX entry index
    0x04  start_frame        u32  -- inclusive LightWave source-frame number
    0x08  end_frame          u32  -- inclusive
    0x0C  frame_count        u32  -- end_frame - start_frame + 1
    0x10  source_fps         u32  -- 30 in every shipped entry
    0x14  frame_interval_ms  u32  -- 33 in every shipped entry
    0x18  source_name_length u32
    0x1C  source_name        ASCII[source_name_length], not NUL-terminated
          header_word_count  u32
          header_words       u32[header_word_count]
          part_count         u32
          parts              part[part_count]
          suffix_count       u32
          suffixes           u32[3][suffix_count]

A part is ``u32 part_id``, a length-prefixed ASCII name, ``u32 frame_count``,
then that many 44-byte frames. There is no extra word between ``frame_count``
and the first frame. A frame is::

    0x00  time_ms   u32
    0x04  rotation  float32[4]  -- quaternion W, X, Y, Z
    0x14  position  float32[3]
    0x20  scale     float32[3]

This order matters. Reading the first word as a float and the last as time
turns the real timestamps into denormals and reports the final ``1.0`` scale
component as the constant integer 1065353216.

Verified against all 857 used entries in the shipped 4,000-slot archive:
every entry consumes exactly, all 1,310,139 frames are finite and carry a
unit quaternion, every part in a clip has the declared frame count and the
same timestamps, and every header manifest prefix exactly matches the stored
part IDs. Header words after that prefix and suffix-triple semantics remain
unknown, so both are preserved without speculative names.

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

ENTRY_HEADER_STRUCT = "<7I"
ENTRY_HEADER_SIZE = struct.calcsize(ENTRY_HEADER_STRUCT)
FRAME_STRUCT = "<I10f"
FRAME_SIZE = struct.calcsize(FRAME_STRUCT)
SUFFIX_STRUCT = "<III"
SUFFIX_SIZE = struct.calcsize(SUFFIX_STRUCT)


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

    @property
    def frame_count(self) -> int:
        return len(self.frames)


@dataclass(frozen=True)
class U9AnimationSuffix:
    """One still-undecoded three-word record after the part tracks."""

    values: tuple[int, int, int]


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

    @property
    def part_ids(self) -> tuple[int, ...]:
        return tuple(part.part_id for part in self.parts)

    @property
    def duration_ms(self) -> int:
        """Latest timestamp carried by any part, or zero for an empty clip."""
        return max(
            (frame.time_ms for part in self.parts for frame in part.frames),
            default=0,
        )

    def part(self, part_id: int) -> U9AnimationPart | None:
        """Return the part with this ID, or ``None`` when it is absent."""
        return next((part for part in self.parts if part.part_id == part_id), None)

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
        if record_index != animation_id:
            raise U9AnimationError(
                f"animation {animation_id}: record index is {record_index}, "
                "expected the FLX entry index"
            )
        if end_frame < start_frame or end_frame - start_frame + 1 != frame_count:
            raise U9AnimationError(
                f"animation {animation_id}: frame range {start_frame}..{end_frame} "
                f"does not match declared count {frame_count}"
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

        header_word_count, pos = _read_u32(data, pos, animation_id, "header-word count")
        header_size = header_word_count * 4
        header_raw, pos = _read_bytes(
            data,
            pos,
            header_size,
            animation_id,
            "header-word block",
        )
        header_words = (
            struct.unpack(f"<{header_word_count}I", header_raw)
            if header_word_count
            else ()
        )

        part_count, pos = _read_u32(data, pos, animation_id, "part count")
        parts: list[U9AnimationPart] = []
        for part_index in range(part_count):
            part, pos = _read_part(
                data,
                pos,
                animation_id,
                part_index,
                frame_count,
            )
            parts.append(part)

        part_ids = tuple(part.part_id for part in parts)
        if len(header_words) < part_count or header_words[:part_count] != part_ids:
            raise U9AnimationError(
                f"animation {animation_id}: part ID manifest {header_words[:part_count]} "
                f"does not match parsed parts {part_ids}"
            )

        suffix_count, pos = _read_u32(data, pos, animation_id, "suffix count")
        suffix_bytes = suffix_count * SUFFIX_SIZE
        suffix_raw, pos = _read_bytes(
            data,
            pos,
            suffix_bytes,
            animation_id,
            "suffix records",
        )
        if pos != len(data):
            raise U9AnimationError(
                f"animation {animation_id}: {len(data) - pos} trailing byte(s) "
                "after the suffix records"
            )
        suffixes = tuple(
            U9AnimationSuffix(values=values)
            for values in struct.iter_unpack(SUFFIX_STRUCT, suffix_raw)
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
        return U9Animation.parse(data, animation_id)

    def animations(self) -> list[U9Animation]:
        """Parse every used clip, in animation-ID order."""
        result = []
        for animation_id in self.used_animation_ids():
            animation = self.animation(animation_id)
            if animation is not None:
                result.append(animation)
        return result


def _read_u32(
    data: bytes,
    pos: int,
    animation_id: int,
    description: str,
) -> tuple[int, int]:
    if pos + 4 > len(data):
        raise U9AnimationError(
            f"animation {animation_id}: truncated before {description} at offset {pos:#x}"
        )
    return struct.unpack_from("<I", data, pos)[0], pos + 4


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
    clip_frame_count: int,
) -> tuple[U9AnimationPart, int]:
    part_id, pos = _read_u32(data, pos, animation_id, f"part {part_index} ID")
    name_length, pos = _read_u32(
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
    frame_count, pos = _read_u32(
        data, pos, animation_id, f"part {part_index} frame count"
    )
    if frame_count != clip_frame_count:
        raise U9AnimationError(
            f"animation {animation_id}: part {part_index} ({name!r}) has "
            f"{frame_count} frame(s), clip declares {clip_frame_count}"
        )

    frame_raw, pos = _read_bytes(
        data,
        pos,
        frame_count * FRAME_SIZE,
        animation_id,
        f"part {part_index} frame array",
    )
    frames: list[U9AnimationFrame] = []
    previous_time = -1
    for frame_index, values in enumerate(struct.iter_unpack(FRAME_STRUCT, frame_raw)):
        time_ms = values[0]
        floats = values[1:]
        if not all(math.isfinite(value) for value in floats):
            raise U9AnimationError(
                f"animation {animation_id}: part {part_index} frame {frame_index} "
                "contains a non-finite transform value"
            )
        if time_ms < previous_time:
            raise U9AnimationError(
                f"animation {animation_id}: part {part_index} frame {frame_index} "
                f"timestamp {time_ms} precedes {previous_time}"
            )
        previous_time = time_ms
        frames.append(
            U9AnimationFrame(
                time_ms=time_ms,
                rotation=tuple(floats[0:4]),
                position=tuple(floats[4:7]),
                scale=tuple(floats[7:10]),
            )
        )

    return U9AnimationPart(part_id=part_id, name=name, frames=tuple(frames)), pos
