"""Tests for the lossless ``static/areas.flx`` reader."""

from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.cli import cmd_areas_csv
from titan.u9.flx_archive import U9FlxArchive
from titan.u9.gameplay_zones import (
    U9Areas,
    U9AreasError,
    U9GameplayZone,
    U9UnknownZone,
)

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


def _position(x: int, y: int, z: int, padding: bytes = b"\x00\x00") -> bytes:
    return struct.pack("<iih2s", x, y, z, padding)


def _box(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    first_padding: bytes = b"\x00\x00",
    second_padding: bytes = b"\x00\x00",
) -> bytes:
    return _position(*first, first_padding) + _position(*second, second_padding)


def _encounter_table(
    choices: tuple[tuple[int, int], ...],
    *,
    declared_count: int | None = None,
    reserved_prefix: int = 0,
    reserved_suffix: int = 0,
    flags: int = 0,
) -> bytes:
    slots = list(choices)
    slots.extend([(0, 0)] * (12 - len(slots)))
    return (
        struct.pack(
            "<ii", reserved_prefix, len(choices) if declared_count is None else declared_count
        )
        + b"".join(struct.pack("<HH", *choice) for choice in slots)
        + struct.pack("<iH", reserved_suffix, flags)
    )


def _zone(
    zone_id: int,
    boxes: tuple[bytes, ...],
    *,
    flags: int = 0,
    chance: int = 0,
    table: bytes | None = None,
    total_weight: int = 0,
    map_id: int = 9,
    marker_padding: bytes = b"\x00\x00",
) -> bytes:
    prefix = (
        struct.pack("<ii", 1, zone_id)
        + _position(10, 20, 30, marker_padding)
        + struct.pack("<Ii", flags, chance)
    )
    return (
        prefix
        + (b"" if table is None else table)
        + struct.pack("<iii", total_weight, map_id, len(boxes))
        + b"".join(boxes)
    )


class GameplayZoneTests(unittest.TestCase):
    def test_decodes_box_zone_and_preserves_position_padding(self) -> None:
        entry = _zone(
            2,
            (
                _box((30, 40, 5), (10, 20, 7), b"AB", b"CD"),
                _box((100, 200, 9), (110, 210, 9)),
            ),
            flags=1,
            marker_padding=b"XY",
        )
        areas = U9Areas(_archive({2: entry}))
        record = areas.record(2)
        self.assertIsInstance(record, U9GameplayZone)
        assert isinstance(record, U9GameplayZone)

        self.assertEqual(record.world_map_id, 9)
        self.assertTrue(record.trigger_enabled)
        self.assertFalse(record.has_encounter_table)
        self.assertEqual(record.path_marker_position.padding, b"XY")
        self.assertEqual(record.boxes[0].minimum, (10, 20, 5))
        self.assertEqual(record.boxes[0].maximum, (30, 40, 7))
        self.assertTrue(record.boxes[0].uses_unbounded_height)
        self.assertEqual(record.boxes[0].corners[0].padding, b"AB")
        self.assertEqual(record.structural_warnings(), ())
        self.assertEqual(record.to_bytes(), entry)

    def test_decodes_active_and_inactive_encounter_slots(self) -> None:
        table = _encounter_table(
            ((192, 2), (198, 1), (777, 99)),
            declared_count=2,
            reserved_prefix=0x12345678,
            reserved_suffix=-42,
            flags=0xABCD,
        )
        entry = _zone(
            3,
            (_box((0, 0, 0), (100, 100, 20)),),
            flags=3,
            chance=50,
            table=table,
            total_weight=3,
        )
        record = U9Areas(_archive({3: entry})).record(3)
        assert isinstance(record, U9GameplayZone)
        encounter = record.encounter_table
        assert encounter is not None

        self.assertEqual(encounter.declared_choice_count, 2)
        self.assertEqual(len(encounter.choice_slots), 12)
        self.assertEqual([choice.object_type_id for choice in encounter.active_choices], [192, 198])
        self.assertEqual(encounter.choice_slots[2].object_type_id, 777)
        self.assertEqual(encounter.active_weight_total, 3)
        self.assertEqual(encounter.reserved_prefix, 0x12345678)
        self.assertEqual(encounter.reserved_suffix, -42)
        self.assertEqual(encounter.stored_flags, 0xABCD)
        self.assertEqual(record.structural_warnings(), ())

    def test_reports_counts_and_totals_without_rewriting(self) -> None:
        table = _encounter_table(((100, 4),), declared_count=13)
        entry = _zone(
            1,
            (),
            flags=2,
            chance=101,
            table=table,
            total_weight=99,
        ) + b"tail"
        record = U9Areas(_archive({1: entry})).record(1)
        assert isinstance(record, U9GameplayZone)

        self.assertEqual(
            record.structural_warnings(),
            (
                "declared_box_count_out_of_range",
                "encounter_choice_count_out_of_range",
                "encounter_weight_total_mismatch",
                "encounter_chance_out_of_range",
                "trailing_data",
            ),
        )
        self.assertEqual(record.to_bytes(), entry)

    def test_retains_unsupported_kind_as_opaque_record(self) -> None:
        entry = struct.pack("<i", 7) + b"future layout"
        record = U9Areas(_archive({4: entry})).record(4)
        self.assertIsInstance(record, U9UnknownZone)
        assert isinstance(record, U9UnknownZone)
        self.assertEqual(record.record_kind, 7)
        self.assertEqual(record.structural_warnings(), ("unsupported_record_kind",))
        self.assertEqual(record.to_bytes(), entry)

    def test_rejects_truncated_and_negative_box_arrays(self) -> None:
        with self.assertRaisesRegex(U9AreasError, "truncates zone header"):
            U9Areas(_archive({1: struct.pack("<i", 1)}))

        negative_count = (
            struct.pack("<ii", 1, 1)
            + _position(0, 0, 0)
            + struct.pack("<Iiiii", 0, 0, 0, 9, -1)
        )
        with self.assertRaisesRegex(U9AreasError, "negative box count"):
            U9Areas(_archive({1: negative_count}))

    def test_preserves_entire_archive(self) -> None:
        archive = _archive({1: _zone(1, (_box((0, 0, 0), (1, 1, 1)),))})
        areas = U9Areas(archive)
        self.assertEqual(areas.used_zone_ids, (1,))
        self.assertIsNone(areas.record(0))
        self.assertEqual(areas.to_bytes(), archive.to_bytes())

    def test_csv_export_writes_three_related_tables(self) -> None:
        table = _encounter_table(((192, 2),), declared_count=1)
        entry = _zone(
            1,
            (_box((0, 0, 0), (10, 10, 10)),),
            flags=2,
            chance=40,
            table=table,
            total_weight=2,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "areas.flx"
            archive_path.write_bytes(_archive({1: entry}).to_bytes())
            output = root / "csv"

            result = cmd_areas_csv(
                SimpleNamespace(file=str(archive_path), output=str(output))
            )

            self.assertEqual(result, 0)
            with (output / "u9_areas.csv").open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(rows[0]["record_kind_name"], "box_zone")
            self.assertEqual(rows[0]["stored_zone_id_status"], "matches_entry_index")
            self.assertIn(
                "uses_unbounded_height",
                (output / "u9_area_boxes.csv").read_text("utf-8"),
            )
            self.assertIn(
                "selection_weight",
                (output / "u9_area_encounter_choices.csv").read_text("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
