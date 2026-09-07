"""Readers for Ultima IX sound association and template FLX records.

``sfxassoc.flx`` maps an object type (the FLX entry index) to an SFX template
ID stored as one little-endian ``u32``.  ``SFXTMPL.FLX`` defines those
templates.  Its variable-length action records were validated by consuming all
491 used records in the shipped archive exactly, with no trailing bytes.
"""

from __future__ import annotations

__all__ = [
    "U9SfxAction",
    "U9SfxAssociation",
    "U9SfxSoundReference",
    "U9SfxTemplate",
    "U9SoundControlError",
    "parse_sfx_associations",
    "parse_sfx_template",
]

import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive

TEMPLATE_HEADER_SIZE = 0x38
ACTION_HEADER_SIZE = 0x28
SOUND_REFERENCE_SIZE = 0x10


class U9SoundControlError(Exception):
    """Raised when a sound-control record is structurally invalid."""


def _cstring(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")


@dataclass(frozen=True)
class U9SfxSoundReference:
    """One 16-byte sound reference within an SFX template action."""

    unknown_00: int
    sound_id: int
    unknown_08: int
    unknown_0c: int


@dataclass(frozen=True)
class U9SfxAction:
    """A named SFX-template action and the sound records it may select."""

    category_id: int
    name: str
    sound_references: tuple[U9SfxSoundReference, ...]


@dataclass(frozen=True)
class U9SfxTemplate:
    """One parsed entry from ``SFXTMPL.FLX``."""

    template_id: int
    name: str
    unknown_2c: int
    unknown_30: int
    unknown_34: bytes
    actions: tuple[U9SfxAction, ...]


@dataclass(frozen=True)
class U9SfxAssociation:
    """An object type ID to SFX-template ID mapping from ``sfxassoc.flx``."""

    type_id: int
    template_id: int


def parse_sfx_template(data: bytes) -> U9SfxTemplate:
    """Parse one complete ``SFXTMPL.FLX`` entry and reject trailing bytes."""
    if len(data) < TEMPLATE_HEADER_SIZE:
        raise U9SoundControlError(
            f"SFX template is {len(data)} bytes; need at least {TEMPLATE_HEADER_SIZE}"
        )

    template_id = struct.unpack_from("<I", data, 0x00)[0]
    name = _cstring(data[0x04:0x28])
    action_count, unknown_2c, unknown_30 = struct.unpack_from("<III", data, 0x28)
    unknown_34 = data[0x34:0x38]
    cursor = TEMPLATE_HEADER_SIZE
    actions: list[U9SfxAction] = []

    for action_index in range(action_count):
        if cursor + ACTION_HEADER_SIZE > len(data):
            raise U9SoundControlError(
                f"action {action_index} header exceeds {len(data)}-byte template"
            )
        category_id = data[cursor]
        action_name = _cstring(data[cursor + 1 : cursor + 0x24])
        reference_count = struct.unpack_from("<I", data, cursor + 0x24)[0]
        cursor += ACTION_HEADER_SIZE
        reference_bytes = reference_count * SOUND_REFERENCE_SIZE
        if cursor + reference_bytes > len(data):
            raise U9SoundControlError(
                f"action {action_index} declares {reference_count} sound references "
                f"past the {len(data)}-byte template"
            )
        references = tuple(
            U9SfxSoundReference(*struct.unpack_from("<4I", data, cursor + i * 0x10))
            for i in range(reference_count)
        )
        cursor += reference_bytes
        actions.append(U9SfxAction(category_id, action_name, references))

    if cursor != len(data):
        raise U9SoundControlError(
            f"SFX template has {len(data) - cursor} unexplained trailing byte(s)"
        )
    return U9SfxTemplate(
        template_id,
        name,
        unknown_2c,
        unknown_30,
        unknown_34,
        tuple(actions),
    )


def parse_sfx_associations(archive: U9FlxArchive) -> list[U9SfxAssociation]:
    """Parse every used four-byte entry in ``sfxassoc.flx``."""
    associations: list[U9SfxAssociation] = []
    for type_id in archive.used_entry_indices():
        data = archive.read_entry(type_id)
        if len(data) != 4:
            raise U9SoundControlError(
                f"sfxassoc entry {type_id} is {len(data)} bytes; expected 4"
            )
        associations.append(U9SfxAssociation(type_id, struct.unpack("<I", data)[0]))
    return associations
