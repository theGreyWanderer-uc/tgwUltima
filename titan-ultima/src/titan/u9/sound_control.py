"""Readers for Ultima IX sound association and template FLX records.

``sfxassoc.flx`` maps an object type (the FLX entry index) to an SFX template
ID stored as one little-endian ``u32``.  ``SFXTMPL.FLX`` defines those
templates. Its variable-length action records expose spatial playback values,
world-hour windows, pitch variation, and weighted sound selection. All 491
used records in the shipped archive consume exactly, with no trailing bytes.

The runtime checks the object's direct association first, then checks the one
``TYPES.DAT`` base-type slot. :class:`U9SfxAssociations` exposes both the
physical records and that resolved view without materialising inherited links.
"""

from __future__ import annotations

__all__ = [
    "SFX_ASSOCIATION_RECORD_SIZE",
    "SFX_ASSOCIATION_REPRESENTATION",
    "SFX_ASSOCIATION_SLOT_COUNT",
    "SFX_TEMPLATE_RECORD_REPRESENTATION",
    "SFX_TEMPLATE_SLOT_COUNT",
    "U9SfxAction",
    "U9SfxAssociation",
    "U9SfxAssociationResolution",
    "U9SfxAssociations",
    "U9SfxSoundReference",
    "U9SfxTemplate",
    "U9SfxTemplates",
    "U9SoundControlError",
    "parse_sfx_associations",
    "parse_sfx_template",
]

import os
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from titan.u9.flx_archive import U9FlxArchive

if TYPE_CHECKING:
    from titan.u9.types_dat import U9TypesDat

TEMPLATE_HEADER_SIZE = 0x38
ACTION_HEADER_SIZE = 0x28
SOUND_REFERENCE_SIZE = 0x10
SFX_TEMPLATE_SLOT_COUNT = 8192
SFX_TEMPLATE_RECORD_REPRESENTATION = "nested_sound_template_record"
SFX_ASSOCIATION_RECORD_SIZE = 4
SFX_ASSOCIATION_SLOT_COUNT = 8192
SFX_ASSOCIATION_REPRESENTATION = "direct_object_sound_template_link"


class U9SoundControlError(Exception):
    """Raised when a sound-control record is structurally invalid."""


def _cstring(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")


@dataclass(frozen=True)
class U9SfxSoundReference:
    """One weighted, time-gated sound choice within a template action."""

    choice_id: int
    sound_id: int
    full_volume_percent: int
    off_axis_volume_percent: int
    active_hour_start: int
    active_hour_stop: int
    pitch_variation_percent: int
    selection_weight: int
    leading_alignment_bytes: bytes
    trailing_alignment_bytes: bytes
    raw: bytes

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report values outside the limits imposed by the original editor."""
        warnings: list[str] = []
        if not 0 <= self.full_volume_percent <= 100:
            warnings.append("full_volume_percent_out_of_range")
        if not 0 <= self.off_axis_volume_percent <= 100:
            warnings.append("off_axis_volume_percent_out_of_range")
        if not 0 <= self.active_hour_start <= 23:
            warnings.append("active_hour_start_out_of_range")
        if not 0 <= self.active_hour_stop <= 23:
            warnings.append("active_hour_stop_out_of_range")
        if not 0 <= self.pitch_variation_percent <= 30:
            warnings.append("pitch_variation_percent_out_of_range")
        if not 1 <= self.selection_weight <= 255:
            warnings.append("selection_weight_out_of_range")
        return tuple(warnings)


@dataclass(frozen=True)
class U9SfxAction:
    """A named action and the sound choices it may select."""

    category_id: int
    name: str
    name_field: bytes
    alignment_bytes: bytes
    sound_references: tuple[U9SfxSoundReference, ...]
    raw: bytes

    @property
    def name_is_terminated(self) -> bool:
        """Whether the fixed action-name cell contains a NUL terminator."""
        return b"\x00" in self.name_field

    @property
    def name_padding_bytes(self) -> bytes:
        """Return retained bytes after the action name's first terminator."""
        _, separator, padding = self.name_field.partition(b"\x00")
        return padding if separator else b""

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report malformed names or ambiguous choice identifiers."""
        warnings: list[str] = []
        if not self.name_is_terminated:
            warnings.append("unterminated_action_name")
        if any(self.name_padding_bytes):
            warnings.append("nonzero_action_name_padding")
        if any(self.alignment_bytes):
            warnings.append("nonzero_action_alignment_bytes")
        choice_ids = [reference.choice_id for reference in self.sound_references]
        if len(choice_ids) != len(set(choice_ids)):
            warnings.append("duplicate_choice_id")
        return tuple(warnings)


@dataclass(frozen=True)
class U9SfxTemplate:
    """One losslessly parsed entry from ``SFXTMPL.FLX``."""

    archive_index: int
    template_id: int
    name: str
    name_field: bytes
    name_alignment_bytes: bytes
    action_count: int
    inner_cone_angle_degrees: int
    outer_cone_angle_degrees: int
    near_distance: int
    far_distance: int
    trailing_alignment_bytes: bytes
    actions: tuple[U9SfxAction, ...]
    raw: bytes

    @property
    def record_representation(self) -> str:
        """Titan label for the nested variable-length template record."""
        return SFX_TEMPLATE_RECORD_REPRESENTATION

    @property
    def id_matches_index(self) -> bool:
        """Whether the stored template ID agrees with its FLX slot."""
        return self.template_id == self.archive_index

    @property
    def name_is_terminated(self) -> bool:
        """Whether the fixed template-name cell contains a NUL terminator."""
        return b"\x00" in self.name_field

    @property
    def name_padding_bytes(self) -> bytes:
        """Return retained bytes after the template name's first terminator."""
        _, separator, padding = self.name_field.partition(b"\x00")
        return padding if separator else b""

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report unusual stored values without changing or rejecting them."""
        warnings: list[str] = []
        if not self.id_matches_index:
            warnings.append("stored_id_differs_from_archive_index")
        if not self.name_is_terminated:
            warnings.append("unterminated_template_name")
        if any(self.name_padding_bytes):
            warnings.append("nonzero_template_name_padding")
        if any(self.name_alignment_bytes):
            warnings.append("nonzero_template_name_alignment_bytes")
        if not 0 <= self.inner_cone_angle_degrees <= 360:
            warnings.append("inner_cone_angle_out_of_range")
        if not 0 <= self.outer_cone_angle_degrees <= 360:
            warnings.append("outer_cone_angle_out_of_range")
        if self.outer_cone_angle_degrees < self.inner_cone_angle_degrees:
            warnings.append("outer_cone_smaller_than_inner_cone")
        if not 1 <= self.near_distance <= 25:
            warnings.append("near_distance_out_of_editor_range")
        if not 1 <= self.far_distance <= 25:
            warnings.append("far_distance_out_of_editor_range")
        if self.far_distance < self.near_distance:
            warnings.append("far_distance_smaller_than_near_distance")
        return tuple(warnings)


class U9SfxTemplates:
    """Lossless sound-template library from ``sound/SFXTMPL.FLX``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive_slot_count = archive.num_entries
        self.raw = archive.to_bytes()
        self.templates = tuple(
            parse_sfx_template(archive.read_entry(index), archive_index=index)
            for index in archive.used_entry_indices()
        )
        self._by_archive_index = {
            template.archive_index: template for template in self.templates
        }

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9SfxTemplates:
        """Read every used sound-template slot from a U9 FLX archive."""
        return cls(U9FlxArchive.from_file(filepath))

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report archive-level deviations without rejecting valid data."""
        if self.archive_slot_count != SFX_TEMPLATE_SLOT_COUNT:
            return ("unexpected_archive_slot_count",)
        return ()

    def template(self, archive_index: int) -> U9SfxTemplate | None:
        """Return one template by its physical FLX slot, or ``None``."""
        return self._by_archive_index.get(archive_index)

    def to_bytes(self) -> bytes:
        """Return the original archive exactly, including empty slots."""
        return self.raw

    def __len__(self) -> int:
        return len(self.templates)

    def __iter__(self):
        return iter(self.templates)


@dataclass(frozen=True)
class U9SfxAssociation:
    """One direct object-type to sound-template link from ``sfxassoc.flx``."""

    object_type_id: int
    sound_template_id: int
    raw: bytes

    @property
    def record_representation(self) -> str:
        """Titan label for the fixed four-byte direct-link record."""
        return SFX_ASSOCIATION_REPRESENTATION


@dataclass(frozen=True)
class U9SfxAssociationResolution:
    """The direct-or-base sound-template lookup result used by the game."""

    requested_object_type_id: int
    matched_object_type_id: int | None
    sound_template_id: int | None
    link_source: Literal["direct", "base_type", "unmapped"]
    association: U9SfxAssociation | None


class U9SfxAssociations:
    """Lossless object-type sound-template links from ``sound/sfxassoc.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive_slot_count = archive.num_entries
        self.raw = archive.to_bytes()
        self.records = tuple(
            _parse_sfx_association(archive, object_type_id)
            for object_type_id in archive.used_entry_indices()
        )
        self._by_object_type = {
            record.object_type_id: record for record in self.records
        }

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9SfxAssociations:
        """Read all direct sound-template links from a U9 FLX archive."""
        return cls(U9FlxArchive.from_file(filepath))

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report archive-level deviations without rejecting valid FLX data."""
        if self.archive_slot_count != SFX_ASSOCIATION_SLOT_COUNT:
            return ("unexpected_archive_slot_count",)
        return ()

    def direct_for(self, object_type_id: int) -> U9SfxAssociation | None:
        """Return an object's direct stored association, if one exists."""
        return self._by_object_type.get(object_type_id)

    def resolve(
        self, object_type_id: int, types: U9TypesDat | None = None
    ) -> U9SfxAssociationResolution:
        """Resolve the direct link, then the object's one-step base-type fallback."""
        direct = self.direct_for(object_type_id)
        if direct is not None:
            return U9SfxAssociationResolution(
                object_type_id,
                direct.object_type_id,
                direct.sound_template_id,
                "direct",
                direct,
            )

        type_record = types.record_for(object_type_id) if types is not None else None
        inherited = (
            self.direct_for(type_record.base_type_id)
            if type_record is not None
            else None
        )
        if inherited is not None:
            return U9SfxAssociationResolution(
                object_type_id,
                inherited.object_type_id,
                inherited.sound_template_id,
                "base_type",
                inherited,
            )
        return U9SfxAssociationResolution(object_type_id, None, None, "unmapped", None)

    def to_bytes(self) -> bytes:
        """Return the original archive exactly, including every empty slot."""
        return self.raw

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)


def parse_sfx_template(
    data: bytes, *, archive_index: int | None = None
) -> U9SfxTemplate:
    """Parse one complete ``SFXTMPL.FLX`` entry and reject trailing bytes."""
    if len(data) < TEMPLATE_HEADER_SIZE:
        raise U9SoundControlError(
            f"SFX template is {len(data)} bytes; need at least {TEMPLATE_HEADER_SIZE}"
        )

    template_id = struct.unpack_from("<I", data, 0x00)[0]
    physical_index = template_id if archive_index is None else archive_index
    name_field = bytes(data[0x04:0x25])
    name = _cstring(name_field)
    name_alignment_bytes = bytes(data[0x25:0x28])
    action_count, inner_angle, outer_angle = struct.unpack_from("<III", data, 0x28)
    near_distance = data[0x34]
    far_distance = data[0x35]
    trailing_alignment_bytes = bytes(data[0x36:0x38])
    cursor = TEMPLATE_HEADER_SIZE
    actions: list[U9SfxAction] = []

    for action_index in range(action_count):
        if cursor + ACTION_HEADER_SIZE > len(data):
            raise U9SoundControlError(
                f"action {action_index} header exceeds {len(data)}-byte template"
            )
        action_start = cursor
        category_id = data[cursor]
        action_name_field = bytes(data[cursor + 1 : cursor + 0x22])
        action_name = _cstring(action_name_field)
        action_alignment_bytes = bytes(data[cursor + 0x22 : cursor + 0x24])
        reference_count = struct.unpack_from("<I", data, cursor + 0x24)[0]
        cursor += ACTION_HEADER_SIZE
        reference_bytes = reference_count * SOUND_REFERENCE_SIZE
        if cursor + reference_bytes > len(data):
            raise U9SoundControlError(
                f"action {action_index} declares {reference_count} sound references "
                f"past the {len(data)}-byte template"
            )
        references: list[U9SfxSoundReference] = []
        for reference_index in range(reference_count):
            reference_start = cursor + reference_index * SOUND_REFERENCE_SIZE
            reference_raw = bytes(
                data[reference_start : reference_start + SOUND_REFERENCE_SIZE]
            )
            references.append(
                U9SfxSoundReference(
                    choice_id=reference_raw[0],
                    sound_id=struct.unpack_from("<I", reference_raw, 0x04)[0],
                    full_volume_percent=reference_raw[0x08],
                    off_axis_volume_percent=reference_raw[0x09],
                    active_hour_start=reference_raw[0x0A],
                    active_hour_stop=reference_raw[0x0B],
                    pitch_variation_percent=reference_raw[0x0C],
                    selection_weight=reference_raw[0x0D],
                    leading_alignment_bytes=reference_raw[0x01:0x04],
                    trailing_alignment_bytes=reference_raw[0x0E:0x10],
                    raw=reference_raw,
                )
            )
        cursor += reference_bytes
        actions.append(
            U9SfxAction(
                category_id=category_id,
                name=action_name,
                name_field=action_name_field,
                alignment_bytes=action_alignment_bytes,
                sound_references=tuple(references),
                raw=bytes(data[action_start:cursor]),
            )
        )

    if cursor != len(data):
        raise U9SoundControlError(
            f"SFX template has {len(data) - cursor} unexplained trailing byte(s)"
        )
    return U9SfxTemplate(
        archive_index=physical_index,
        template_id=template_id,
        name=name,
        name_field=name_field,
        name_alignment_bytes=name_alignment_bytes,
        action_count=action_count,
        inner_cone_angle_degrees=inner_angle,
        outer_cone_angle_degrees=outer_angle,
        near_distance=near_distance,
        far_distance=far_distance,
        trailing_alignment_bytes=trailing_alignment_bytes,
        actions=tuple(actions),
        raw=bytes(data),
    )


def _parse_sfx_association(
    archive: U9FlxArchive, object_type_id: int
) -> U9SfxAssociation:
    data = archive.read_entry(object_type_id)
    if len(data) != SFX_ASSOCIATION_RECORD_SIZE:
        raise U9SoundControlError(
            f"sfxassoc.flx entry {object_type_id} is {len(data)} bytes; "
            f"expected exactly {SFX_ASSOCIATION_RECORD_SIZE}"
        )
    return U9SfxAssociation(
        object_type_id=object_type_id,
        sound_template_id=struct.unpack("<I", data)[0],
        raw=bytes(data),
    )


def parse_sfx_associations(archive: U9FlxArchive) -> list[U9SfxAssociation]:
    """Parse every used four-byte entry in ``sfxassoc.flx``."""
    return list(U9SfxAssociations(archive).records)
