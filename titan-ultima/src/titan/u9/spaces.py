"""Lossless reader for Ultima IX ``static/spaces.flx``.

Each used FLX entry describes one enclosed visibility/acoustics volume.  The
entry begins with a fixed 56-byte header and is followed by two serialized
linked lists: 40-byte boundary planes, each of which may own a list of
68-byte visibility portals.  Stored pointer values are only zero/nonzero
sentinels on disk; the game replaces them with runtime allocations.

Titan therefore follows the sentinels but never interprets their numeric
values as addresses.  Every raw record is retained so :meth:`to_bytes`
reproduces the input exactly, including stale pointer values, reserved cells,
and portal flags that the runtime clears after loading.
"""

from __future__ import annotations

__all__ = [
    "BOUNDARY_PLANE_SIZE",
    "PORTAL_SIZE",
    "SPACE_HEADER_SIZE",
    "U9VisibilityOpening",
    "U9VisibilityVolume",
    "U9VolumeBoundary",
    "U9Spaces",
    "U9SpacesError",
]

import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

SPACE_HEADER_SIZE = 56
BOUNDARY_PLANE_SIZE = 40
PORTAL_SIZE = 68

_SPACE_HEADER = struct.Struct("<32siIIihhhH")
_BOUNDARY_PLANE = struct.Struct("<I7fIi")
_PORTAL = struct.Struct("<I12fifiI")

_HIDE_OUTSIDE_FLAG = 0x0001
_PORTAL_BLOCKED_FLAG = 0x00000001
_PORTAL_DISABLED_FLAG = 0x00000002
_AUDIO_TEMPLATE_FLAG = 0x80000000
_AUDIO_ENVIRONMENT_FLAG = 0x40000000
_AUDIO_TEMPLATE_MASK = 0x003FFE00
_AUDIO_ENVIRONMENT_MASK = 0x000001FF
_CLASSIFIED_AUDIO_BITS = (
    _AUDIO_TEMPLATE_FLAG
    | _AUDIO_ENVIRONMENT_FLAG
    | _AUDIO_TEMPLATE_MASK
    | _AUDIO_ENVIRONMENT_MASK
)


class U9SpacesError(Exception):
    """Raised when a used ``spaces.flx`` entry violates its fixed grammar."""


@dataclass(frozen=True)
class U9VisibilityOpening:
    """One stored portal quadrilateral and its target visibility space."""

    entry_offset: int
    next_portal_sentinel: int
    corners: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    visibility_target_id: int
    range_limit: float
    reserved_link: int
    stored_flags: int
    raw_data: bytes

    @property
    def has_next(self) -> bool:
        """Whether another serialized portal record follows this one."""
        return self.next_portal_sentinel != 0

    @property
    def uses_runtime_maximum_range(self) -> bool:
        """Whether a stored zero asks the runtime to use its maximum range."""
        return self.range_limit == 0.0

    @property
    def stored_blocked(self) -> bool:
        return bool(self.stored_flags & _PORTAL_BLOCKED_FLAG)

    @property
    def stored_disabled(self) -> bool:
        return bool(self.stored_flags & _PORTAL_DISABLED_FLAG)

    @property
    def unclassified_flag_bits(self) -> int:
        return self.stored_flags & ~(_PORTAL_BLOCKED_FLAG | _PORTAL_DISABLED_FLAG)

    @property
    def runtime_initial_flags(self) -> int:
        """Flags immediately after runtime initialization.

        The loader clears the complete stored flags cell.  Later gameplay may
        change the in-memory blocked state, but no such change modifies this
        archive record.
        """
        return 0

    @property
    def stored_flags_status(self) -> str:
        return "runtime_reset"

    def to_bytes(self) -> bytes:
        return bytes(self.raw_data)


@dataclass(frozen=True)
class U9VolumeBoundary:
    """One plane equation and the portal chain attached to that plane."""

    entry_offset: int
    next_plane_sentinel: int
    reference_point: tuple[float, float, float]
    normal: tuple[float, float, float]
    plane_w: float
    portal_head_sentinel: int
    plane_reserved: int
    openings: tuple[U9VisibilityOpening, ...]
    raw_data: bytes

    @property
    def has_next(self) -> bool:
        return self.next_plane_sentinel != 0

    @property
    def has_portals(self) -> bool:
        return self.portal_head_sentinel != 0

    def to_bytes(self) -> bytes:
        return self.raw_data + b"".join(opening.to_bytes() for opening in self.openings)


@dataclass(frozen=True)
class U9VisibilityVolume:
    """One complete used ``spaces.flx`` entry."""

    space_id: int
    name: str
    name_field: bytes
    world_map_id: int
    boundary_head_sentinel: int
    audio_code: int
    draw_order_priority: int
    visibility_target_id: int
    header_reserved: int
    stored_space_number: int
    stored_flags: int
    boundaries: tuple[U9VolumeBoundary, ...]
    trailing_data: bytes
    raw_data: bytes

    @property
    def runtime_space_id(self) -> int:
        """Authoritative ID rebuilt by the runtime from the FLX entry index."""
        return self.space_id

    @property
    def stored_space_number_matches_runtime(self) -> bool:
        return self.stored_space_number == self.runtime_space_id

    @property
    def stored_space_number_status(self) -> str:
        return (
            "matches_entry_index"
            if self.stored_space_number_matches_runtime
            else "runtime_rebuilt"
        )

    @property
    def hide_outside(self) -> bool:
        return bool(self.stored_flags & _HIDE_OUTSIDE_FLAG)

    @property
    def unclassified_flag_bits(self) -> int:
        return self.stored_flags & ~_HIDE_OUTSIDE_FLAG

    @property
    def has_sound_template(self) -> bool:
        return bool(self.audio_code & _AUDIO_TEMPLATE_FLAG)

    @property
    def sound_template_id(self) -> int | None:
        if not self.has_sound_template:
            return None
        return (self.audio_code & _AUDIO_TEMPLATE_MASK) >> 9

    @property
    def has_acoustic_environment(self) -> bool:
        return bool(self.audio_code & _AUDIO_ENVIRONMENT_FLAG)

    @property
    def acoustic_environment_id(self) -> int | None:
        if not self.has_acoustic_environment:
            return None
        return self.audio_code & _AUDIO_ENVIRONMENT_MASK

    @property
    def unclassified_audio_bits(self) -> int:
        return self.audio_code & ~_CLASSIFIED_AUDIO_BITS

    @property
    def portal_count(self) -> int:
        return sum(len(boundary.openings) for boundary in self.boundaries)

    @property
    def is_complete(self) -> bool:
        return not self.trailing_data

    def to_bytes(self) -> bytes:
        """Return the original entry exactly, including forensic-only cells."""
        return bytes(self.raw_data)


class U9Spaces:
    """Lossless view of all used records in ``static/spaces.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive = archive
        self._spaces: dict[int, U9VisibilityVolume] = {}
        for space_id in archive.used_entry_indices():
            self._spaces[space_id] = _parse_space(
                space_id, archive.read_entry(space_id)
            )

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Spaces:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as error:
            raise U9SpacesError(str(error)) from error

    @property
    def num_entries(self) -> int:
        return self.archive.num_entries

    @property
    def used_space_ids(self) -> tuple[int, ...]:
        return tuple(self._spaces)

    def space(self, space_id: int) -> U9VisibilityVolume | None:
        return self._spaces.get(space_id)

    def spaces(self) -> tuple[U9VisibilityVolume, ...]:
        return tuple(self._spaces.values())

    def missing_visibility_target_ids(self) -> tuple[int, ...]:
        """Return referenced nonnegative IDs which have no used archive slot."""
        missing: set[int] = set()
        for space in self._spaces.values():
            references = [space.visibility_target_id]
            references.extend(
                opening.visibility_target_id
                for boundary in space.boundaries
                for opening in boundary.openings
            )
            missing.update(
                reference
                for reference in references
                if reference >= 0 and reference not in self._spaces
            )
        return tuple(sorted(missing))

    def to_bytes(self) -> bytes:
        """Return the complete original FLX archive byte for byte."""
        return self.archive.to_bytes()


def _take_record(
    data: bytes, offset: int, size: int, label: str, space_id: int
) -> bytes:
    end = offset + size
    if end > len(data):
        raise U9SpacesError(
            f"spaces.flx entry {space_id} truncates {label} at {offset:#x}: "
            f"needs {size} bytes, only {len(data) - offset} remain"
        )
    return data[offset:end]


def _parse_portal(
    data: bytes, offset: int, space_id: int
) -> tuple[U9VisibilityOpening, int]:
    raw = _take_record(data, offset, PORTAL_SIZE, "portal", space_id)
    values = _PORTAL.unpack(raw)
    corners = tuple(
        (values[1 + index], values[2 + index], values[3 + index])
        for index in range(0, 12, 3)
    )
    opening = U9VisibilityOpening(
        entry_offset=offset,
        next_portal_sentinel=values[0],
        corners=corners,  # type: ignore[arg-type]
        visibility_target_id=values[13],
        range_limit=values[14],
        reserved_link=values[15],
        stored_flags=values[16],
        raw_data=raw,
    )
    return opening, offset + PORTAL_SIZE


def _parse_plane(
    data: bytes, offset: int, space_id: int
) -> tuple[U9VolumeBoundary, int]:
    raw = _take_record(data, offset, BOUNDARY_PLANE_SIZE, "boundary plane", space_id)
    values = _BOUNDARY_PLANE.unpack(raw)
    offset += BOUNDARY_PLANE_SIZE
    openings: list[U9VisibilityOpening] = []
    portal_sentinel = values[8]
    while portal_sentinel != 0:
        opening, offset = _parse_portal(data, offset, space_id)
        openings.append(opening)
        portal_sentinel = opening.next_portal_sentinel
    return (
        U9VolumeBoundary(
            entry_offset=offset - BOUNDARY_PLANE_SIZE - len(openings) * PORTAL_SIZE,
            next_plane_sentinel=values[0],
            reference_point=(values[1], values[2], values[3]),
            normal=(values[4], values[5], values[6]),
            plane_w=values[7],
            portal_head_sentinel=values[8],
            plane_reserved=values[9],
            openings=tuple(openings),
            raw_data=raw,
        ),
        offset,
    )


def _parse_space(space_id: int, data: bytes) -> U9VisibilityVolume:
    raw_header = _take_record(data, 0, SPACE_HEADER_SIZE, "header", space_id)
    (
        name_field,
        world_map_id,
        boundary_head_sentinel,
        audio_code,
        draw_order_priority,
        visibility_target_id,
        header_reserved,
        stored_space_number,
        stored_flags,
    ) = _SPACE_HEADER.unpack(raw_header)

    offset = SPACE_HEADER_SIZE
    planes: list[U9VolumeBoundary] = []
    plane_sentinel = boundary_head_sentinel
    while plane_sentinel != 0:
        plane, offset = _parse_plane(data, offset, space_id)
        planes.append(plane)
        plane_sentinel = plane.next_plane_sentinel

    trailing_data = data[offset:]
    if trailing_data:
        raise U9SpacesError(
            f"spaces.flx entry {space_id} has {len(trailing_data)} unexplained "
            f"byte(s) after its serialized lists"
        )

    return U9VisibilityVolume(
        space_id=space_id,
        name=name_field.split(b"\x00", 1)[0].decode("cp1252", errors="replace"),
        name_field=name_field,
        world_map_id=world_map_id,
        boundary_head_sentinel=boundary_head_sentinel,
        audio_code=audio_code,
        draw_order_priority=draw_order_priority,
        visibility_target_id=visibility_target_id,
        header_reserved=header_reserved,
        stored_space_number=stored_space_number,
        stored_flags=stored_flags,
        boundaries=tuple(planes),
        trailing_data=trailing_data,
        raw_data=data,
    )
