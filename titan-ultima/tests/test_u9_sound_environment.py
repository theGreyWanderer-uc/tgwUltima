"""Tests for the lossless ``sfxenv.flx`` acoustic environment decoder."""

from __future__ import annotations

import struct
import unittest
from typing import cast

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.sound_environment import (
    ENVIRONMENT_RECORD_SIZE,
    U9AcousticPreset,
    U9AcousticPresetError,
    U9AcousticPresets,
)

DIRECTORY_OFFSET = 0x80


def _environment_record(
    profile_code: int,
    volume: float,
    decay: float,
    damping: float,
    name: str,
    *,
    name_residue: bytes = b"",
) -> bytes:
    name_field = bytearray(64)
    encoded = name.encode("ascii")
    name_field[: len(encoded)] = encoded
    residue_start = len(encoded) + 1
    name_field[residue_start : residue_start + len(name_residue)] = name_residue
    return struct.pack("<I3f", profile_code, volume, decay, damping) + bytes(name_field)


def _build_flx(entries: list[bytes | None], *, slots: int | None = None) -> bytes:
    if slots is not None:
        entries = entries + [None] * (slots - len(entries))
    header = bytearray(DIRECTORY_OFFSET)
    header[:10] = b"sfxenv.flx"
    struct.pack_into("<I", header, 0x50, len(entries))
    struct.pack_into("<I", header, 0x54, 2)
    cursor = DIRECTORY_OFFSET + len(entries) * 8
    directory = bytearray()
    payload = bytearray()
    for entry in entries:
        if entry is None:
            directory += struct.pack("<II", 0, 0)
            continue
        directory += struct.pack("<II", cursor, len(entry))
        payload += entry
        cursor += len(entry)
    return bytes(header + directory + payload)


class AcousticPresetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room_record = _environment_record(
            2,
            0.417,
            0.4,
            0.666,
            "Standard - Room",
            name_residue=b"RESIDUE",
        )
        self.archive_bytes = _build_flx(
            [None, None, self.room_record],
            slots=512,
        )
        self.environments = U9AcousticPresets(U9FlxArchive(self.archive_bytes))

    def test_decodes_every_fixed_field(self) -> None:
        environment = cast(U9AcousticPreset, self.environments.preset(2))
        self.assertEqual(environment.archive_index, 2)
        self.assertEqual(environment.acoustic_profile_code, 2)
        self.assertEqual(environment.acoustic_profile_name, "Room")
        self.assertAlmostEqual(environment.reverb_volume, 0.417)
        self.assertAlmostEqual(environment.decay_time_seconds, 0.4)
        self.assertAlmostEqual(environment.high_frequency_damping, 0.666)
        self.assertEqual(environment.display_name, "Standard - Room")
        self.assertEqual(environment.record_representation, "listener_reverb_preset")
        self.assertEqual(environment.value_status, "valid")
        self.assertEqual(environment.standard_preset_status, "matches_factory_preset")

    def test_preserves_name_residue_and_round_trips_exactly(self) -> None:
        environment = cast(U9AcousticPreset, self.environments.preset(2))
        self.assertTrue(environment.name_is_terminated)
        self.assertTrue(environment.name_residue_bytes.startswith(b"RESIDUE"))
        self.assertEqual(environment.to_bytes(), self.room_record)
        self.assertEqual(self.environments.to_bytes(), self.archive_bytes)

    def test_reports_the_shipped_style_profile_code_mismatch(self) -> None:
        record = _environment_record(
            0,
            0.444,
            2.697,
            0.638,
            "Standard - Stone Corridor",
        )
        archive = U9AcousticPresets(
            U9FlxArchive(_build_flx([None] * 13 + [record], slots=512))
        )
        environment = cast(U9AcousticPreset, archive.preset(13))
        self.assertEqual(environment.value_status, "valid")
        self.assertEqual(
            environment.standard_preset_status,
            "profile_code_mismatch",
        )
        self.assertEqual(environment.warnings, ("profile_code_mismatch",))

    def test_flags_invalid_values_without_rewriting_them(self) -> None:
        record = _environment_record(99, 2.0, 0.0, -1.0, "Custom")
        environment = next(iter(U9AcousticPresets(U9FlxArchive(_build_flx([record])))))
        self.assertEqual(environment.value_status, "profile_code_out_of_range")
        self.assertEqual(environment.to_bytes(), record)

    def test_reports_nonstandard_archive_capacity(self) -> None:
        archive = U9AcousticPresets(U9FlxArchive(_build_flx([self.room_record])))
        self.assertEqual(archive.archive_warnings, ("unexpected_archive_slot_count",))

    def test_rejects_a_non_80_byte_record(self) -> None:
        self.assertEqual(len(self.room_record), ENVIRONMENT_RECORD_SIZE)
        with self.assertRaises(U9AcousticPresetError):
            U9AcousticPresets(U9FlxArchive(_build_flx([self.room_record[:-1]])))


if __name__ == "__main__":
    unittest.main()
