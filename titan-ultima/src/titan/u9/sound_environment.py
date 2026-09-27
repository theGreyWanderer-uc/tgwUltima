"""Lossless reader for ``sound/sfxenv.flx`` acoustic environment presets.

Each used FLX slot stores one fixed 80-byte listener-reverb preset: a 16-byte
property block followed by a 64-byte NUL-terminated display-name cell.  The
archive slot is the ID referenced by ``spaces.flx``; the first stored word is
the underlying standard acoustic profile code, not a duplicate record ID.
"""

from __future__ import annotations

__all__ = [
    "ENVIRONMENT_ARCHIVE_SLOT_COUNT",
    "ENVIRONMENT_RECORD_SIZE",
    "STANDARD_ACOUSTIC_PRESETS",
    "U9AcousticPreset",
    "U9AcousticPresetError",
    "U9AcousticPresets",
]

import math
import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

ENVIRONMENT_ARCHIVE_SLOT_COUNT = 512
ENVIRONMENT_RECORD_SIZE = 80
_PROPERTY_BLOCK = struct.Struct("<I3f")
_NAME_FIELD_OFFSET = _PROPERTY_BLOCK.size
_NAME_FIELD_SIZE = 64

# Public labels and factory values from the EAX 1 listener-reverb contract used
# by Ultima IX.  Packing these values to float32 reproduces the stored presets.
STANDARD_ACOUSTIC_PRESETS: tuple[tuple[str, float, float, float], ...] = (
    ("Generic", 0.5, 1.493, 0.5),
    ("Padded Cell", 0.25, 0.1, 0.0),
    ("Room", 0.417, 0.4, 0.666),
    ("Bathroom", 0.653, 1.499, 0.166),
    ("Living Room", 0.208, 0.478, 0.0),
    ("Stone Room", 0.5, 2.309, 0.888),
    ("Auditorium", 0.403, 4.279, 0.5),
    ("Concert Hall", 0.5, 3.961, 0.5),
    ("Cave", 0.5, 2.886, 1.304),
    ("Arena", 0.361, 7.284, 0.332),
    ("Hangar", 0.5, 10.0, 0.3),
    ("Carpeted Hallway", 0.153, 0.259, 2.0),
    ("Hallway", 0.361, 1.493, 0.0),
    ("Stone Corridor", 0.444, 2.697, 0.638),
    ("Alley", 0.25, 1.752, 0.776),
    ("Forest", 0.111, 3.145, 0.472),
    ("City", 0.111, 2.767, 0.224),
    ("Mountains", 0.194, 7.841, 0.472),
    ("Quarry", 1.0, 1.499, 0.5),
    ("Plain", 0.097, 2.767, 0.224),
    ("Parking Lot", 0.208, 1.652, 1.5),
    ("Sewer Pipe", 0.652, 2.886, 0.25),
    ("Under Water", 1.0, 1.499, 0.0),
    ("Drugged", 0.875, 8.392, 1.388),
    ("Dizzy", 0.139, 17.234, 0.666),
    ("Psychotic", 0.486, 7.563, 0.806),
)


class U9AcousticPresetError(Exception):
    """Raised when an acoustic environment archive or record is malformed."""


@dataclass(frozen=True)
class U9AcousticPreset:
    """One fixed listener-reverb preset, identified by its FLX archive slot."""

    archive_index: int
    acoustic_profile_code: int
    reverb_volume: float
    decay_time_seconds: float
    high_frequency_damping: float
    display_name: str
    name_field: bytes
    raw: bytes

    @property
    def record_representation(self) -> str:
        """Titan label for the single fixed record representation."""
        return "listener_reverb_preset"

    @property
    def acoustic_profile_name(self) -> str | None:
        """Return the standard acoustic profile label, when the code is known."""
        if self.acoustic_profile_code >= len(STANDARD_ACOUSTIC_PRESETS):
            return None
        return STANDARD_ACOUSTIC_PRESETS[self.acoustic_profile_code][0]

    @property
    def name_is_terminated(self) -> bool:
        """Whether the fixed display-name cell contains a NUL terminator."""
        return b"\x00" in self.name_field

    @property
    def name_residue_bytes(self) -> bytes:
        """Return inactive bytes after the first display-name terminator."""
        _, separator, residue = self.name_field.partition(b"\x00")
        return residue if separator else b""

    @property
    def value_status(self) -> str:
        """Validate the authoring ranges used for the four acoustic values."""
        values = (
            self.reverb_volume,
            self.decay_time_seconds,
            self.high_frequency_damping,
        )
        if not all(math.isfinite(value) for value in values):
            return "nonfinite"
        if self.acoustic_profile_name is None:
            return "profile_code_out_of_range"
        if not 0.0 <= self.reverb_volume <= 1.0:
            return "reverb_volume_out_of_range"
        if not 0.1 <= self.decay_time_seconds <= 20.0:
            return "decay_time_out_of_range"
        if not 0.0 <= self.high_frequency_damping <= 2.0:
            return "damping_out_of_range"
        return "valid"

    @property
    def standard_preset_status(self) -> str:
        """Compare a ``Standard -`` record with the factory preset for its slot."""
        if not self.display_name.startswith("Standard - "):
            return "not_applicable"
        if self.archive_index >= len(STANDARD_ACOUSTIC_PRESETS):
            return "slot_out_of_standard_range"
        _, volume, decay, damping = STANDARD_ACOUSTIC_PRESETS[self.archive_index]
        expected = _PROPERTY_BLOCK.pack(
            self.archive_index,
            volume,
            decay,
            damping,
        )
        if self.raw[: _PROPERTY_BLOCK.size] == expected:
            return "matches_factory_preset"
        expected_parameters = struct.pack("<3f", volume, decay, damping)
        if self.raw[4 : _PROPERTY_BLOCK.size] == expected_parameters:
            return "profile_code_mismatch"
        return "parameter_mismatch"

    @property
    def warnings(self) -> tuple[str, ...]:
        """Return semantic anomalies without rejecting or rewriting the record."""
        warnings: list[str] = []
        if not self.name_is_terminated:
            warnings.append("unterminated_display_name")
        if self.value_status != "valid":
            warnings.append(self.value_status)
        if self.standard_preset_status not in (
            "matches_factory_preset",
            "not_applicable",
        ):
            warnings.append(self.standard_preset_status)
        return tuple(warnings)

    def to_bytes(self) -> bytes:
        """Return the exact source record, including inactive name-cell residue."""
        return bytes(self.raw)


def _parse_acoustic_preset(archive_index: int, data: bytes) -> U9AcousticPreset:
    if len(data) != ENVIRONMENT_RECORD_SIZE:
        raise U9AcousticPresetError(
            f"sfxenv.flx entry {archive_index} is {len(data)} bytes; "
            f"expected exactly {ENVIRONMENT_RECORD_SIZE}"
        )

    profile_code, volume, decay, damping = _PROPERTY_BLOCK.unpack_from(data)
    name_field = bytes(data[_NAME_FIELD_OFFSET : _NAME_FIELD_OFFSET + _NAME_FIELD_SIZE])
    display_name = name_field.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return U9AcousticPreset(
        archive_index=archive_index,
        acoustic_profile_code=profile_code,
        reverb_volume=volume,
        decay_time_seconds=decay,
        high_frequency_damping=damping,
        display_name=display_name,
        name_field=name_field,
        raw=bytes(data),
    )


class U9AcousticPresets:
    """Lossless acoustic environment table decoded from ``sound/sfxenv.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive = archive
        self.archive_slot_count = archive.num_entries
        self.presets = tuple(
            _parse_acoustic_preset(entry.index, data)
            for entry in archive.entries
            if (data := archive.read_entry(entry.index))
        )
        self._by_archive_index = {
            preset.archive_index: preset for preset in self.presets
        }

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9AcousticPresets:
        """Read the acoustic environment table from a U9 FLX archive."""
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as error:
            raise U9AcousticPresetError(str(error)) from error

    @property
    def archive_warnings(self) -> tuple[str, ...]:
        """Report archive-level differences from the shipped table capacity."""
        if self.archive_slot_count == ENVIRONMENT_ARCHIVE_SLOT_COUNT:
            return ()
        return ("unexpected_archive_slot_count",)

    def preset(self, environment_id: int) -> U9AcousticPreset | None:
        """Return the preset referenced by a ``spaces.flx`` environment ID."""
        return self._by_archive_index.get(environment_id)

    def to_bytes(self) -> bytes:
        """Return the complete source FLX archive byte for byte."""
        return self.archive.to_bytes()

    def __len__(self) -> int:
        return len(self.presets)

    def __iter__(self):
        return iter(self.presets)
