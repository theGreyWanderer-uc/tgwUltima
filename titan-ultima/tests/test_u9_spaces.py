"""Tests for the lossless ``static/spaces.flx`` reader."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.cli import cmd_spaces_csv
from titan.u9.flx_archive import U9FlxArchive
from titan.u9.spaces import U9Spaces, U9SpacesError

DIR_OFFSET = 0x80


def _archive(entries: dict[int, bytes], count: int = 8) -> U9FlxArchive:
    header = bytearray(DIR_OFFSET + count * 8)
    payload = bytearray()
    for index in range(count):
        blob = entries.get(index)
        if blob is None:
            continue
        offset = len(header) + len(payload)
        struct.pack_into("<II", header, DIR_OFFSET + index * 8, offset, len(blob))
        payload += blob
    struct.pack_into("<I", header, 0x50, count)
    struct.pack_into("<I", header, 0x54, 2)
    struct.pack_into(
        "<II", header, 0x58, len(header) + len(payload), len(header) + len(payload)
    )
    return U9FlxArchive(bytes(header + payload))


def _opening(
    *,
    next_sentinel: int = 0,
    target: int = 3,
    range_limit: float = 20.0,
    reserved: int = 0,
    flags: int = 0,
) -> bytes:
    corners = tuple(float(value) for value in range(1, 13))
    return struct.pack(
        "<I12fifiI",
        next_sentinel,
        *corners,
        target,
        range_limit,
        reserved,
        flags,
    )


def _boundary(
    *,
    next_sentinel: int = 0,
    portal_sentinel: int = 0,
    reserved: int = 0,
) -> bytes:
    return struct.pack(
        "<I7fIi",
        next_sentinel,
        1.0,
        2.0,
        3.0,
        0.0,
        1.0,
        0.0,
        -4.0,
        portal_sentinel,
        reserved,
    )


def _space_header(
    *,
    name: str = "Test volume",
    world_map_id: int = 9,
    plane_sentinel: int = 0,
    audio_code: int = 0,
    draw_order_priority: int = 0,
    visibility_target_id: int = -1,
    reserved: int = 0,
    stored_space_number: int = 0,
    flags: int = 0,
) -> bytes:
    return struct.pack(
        "<32siIIihhhH",
        name.encode("ascii").ljust(32, b"\x00"),
        world_map_id,
        plane_sentinel,
        audio_code,
        draw_order_priority,
        visibility_target_id,
        reserved,
        stored_space_number,
        flags,
    )


class SpacesTests(unittest.TestCase):
    def test_follows_plane_and_portal_sentinels(self) -> None:
        entry = (
            _space_header(plane_sentinel=0x12345678, stored_space_number=7)
            + _boundary(next_sentinel=0x87654321, portal_sentinel=0x11111111)
            + _opening(next_sentinel=0x22222222, target=3)
            + _opening(target=-1, range_limit=0.0)
            + _boundary()
        )
        spaces = U9Spaces(_archive({2: entry, 3: _space_header()}))
        space = spaces.space(2)
        assert space is not None

        self.assertEqual(space.name, "Test volume")
        self.assertEqual(len(space.boundaries), 2)
        self.assertEqual(len(space.boundaries[0].openings), 2)
        self.assertEqual(space.boundaries[0].entry_offset, 56)
        self.assertEqual(space.boundaries[0].openings[0].entry_offset, 96)
        self.assertTrue(space.boundaries[0].openings[1].uses_runtime_maximum_range)
        self.assertEqual(space.portal_count, 2)
        self.assertEqual(space.to_bytes(), entry)
        self.assertEqual(spaces.missing_visibility_target_ids(), ())

    def test_decodes_audio_and_preserves_runtime_rebuilt_cells(self) -> None:
        audio_code = 0xC0000000 | (437 << 9) | 23 | 0x01000000
        entry = _space_header(
            audio_code=audio_code,
            stored_space_number=0,
            flags=0x8001,
        )
        space = U9Spaces(_archive({5: entry})).space(5)
        assert space is not None

        self.assertTrue(space.has_sound_template)
        self.assertEqual(space.sound_template_id, 437)
        self.assertTrue(space.has_acoustic_environment)
        self.assertEqual(space.acoustic_environment_id, 23)
        self.assertEqual(space.unclassified_audio_bits, 0x01000000)
        self.assertTrue(space.hide_outside)
        self.assertEqual(space.unclassified_flag_bits, 0x8000)
        self.assertEqual(space.runtime_space_id, 5)
        self.assertEqual(space.stored_space_number_status, "runtime_rebuilt")

    def test_exposes_stored_portal_flags_as_runtime_reset(self) -> None:
        entry = (
            _space_header(plane_sentinel=1)
            + _boundary(portal_sentinel=1)
            + _opening(flags=0x80000003, reserved=-42)
        )
        volume = U9Spaces(_archive({1: entry})).space(1)
        assert volume is not None
        stored_portal = volume.boundaries[0].openings[0]

        self.assertTrue(stored_portal.stored_blocked)
        self.assertTrue(stored_portal.stored_disabled)
        self.assertEqual(stored_portal.unclassified_flag_bits, 0x80000000)
        self.assertEqual(stored_portal.runtime_initial_flags, 0)
        self.assertEqual(stored_portal.stored_flags_status, "runtime_reset")
        self.assertEqual(stored_portal.reserved_link, -42)

    def test_rejects_truncated_and_unexplained_entry_data(self) -> None:
        with self.assertRaisesRegex(U9SpacesError, "truncates boundary plane"):
            U9Spaces(_archive({1: _space_header(plane_sentinel=1)}))

        with self.assertRaisesRegex(U9SpacesError, "unexplained"):
            U9Spaces(_archive({1: _space_header() + b"stale"}))

    def test_preserves_entire_archive(self) -> None:
        archive = _archive({1: _space_header(stored_space_number=1)})
        spaces = U9Spaces(archive)
        self.assertEqual(spaces.used_space_ids, (1,))
        self.assertIsNone(spaces.space(0))
        self.assertEqual(spaces.to_bytes(), archive.to_bytes())

    def test_csv_export_writes_three_related_tables(self) -> None:
        entry = (
            _space_header(plane_sentinel=1) + _boundary(portal_sentinel=1) + _opening()
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "spaces.flx"
            archive_path.write_bytes(_archive({1: entry}).to_bytes())
            output = root / "csv"

            result = cmd_spaces_csv(
                SimpleNamespace(file=str(archive_path), output=str(output))
            )

            self.assertEqual(result, 0)
            self.assertIn("world_map_id", (output / "u9_spaces.csv").read_text("utf-8"))
            self.assertIn(
                "reference_x",
                (output / "u9_space_planes.csv").read_text("utf-8"),
            )
            self.assertIn(
                "corner_0_x",
                (output / "u9_space_portals.csv").read_text("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
