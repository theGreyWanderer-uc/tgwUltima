"""Tests for the lossless ``static/dimension.dat`` reader."""

from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.cli import cmd_dimension_csv
from titan.u9.model_geometry import (
    COMPLETE_STORED_BOUND_COUNT,
    EXPECTED_SIZE,
    MODEL_SLOT_COUNT,
    PARTIAL_STORED_BOUND_ID,
    U9ModelGeometryTable,
    U9ModelGeometryTableError,
)

SCALAR_BLOCK_SIZE = MODEL_SLOT_COUNT * 4
VECTOR_BLOCK_SIZE = MODEL_SLOT_COUNT * 12
CENTER_OFFSET = SCALAR_BLOCK_SIZE
MINIMUM_OFFSET = CENTER_OFFSET + VECTOR_BLOCK_SIZE
MAXIMUM_OFFSET = MINIMUM_OFFSET + SCALAR_BLOCK_SIZE


def _table_bytes() -> bytes:
    data = bytearray(EXPECTED_SIZE)
    struct.pack_into("<f", data, 0, -1.0)
    struct.pack_into("<f", data, 4, -2.0)
    struct.pack_into("<3f", data, CENTER_OFFSET + 12, 1.0, 2.0, float("inf"))
    struct.pack_into("<3f", data, MINIMUM_OFFSET + 24, 4.0, -2.0, -3.0)
    struct.pack_into("<3f", data, MAXIMUM_OFFSET + 24, 3.0, 2.0, 3.0)
    struct.pack_into(
        "<3f",
        data,
        MINIMUM_OFFSET + (COMPLETE_STORED_BOUND_COUNT - 1) * 12,
        -7.0,
        -8.0,
        -9.0,
    )
    struct.pack_into(
        "<3f",
        data,
        MAXIMUM_OFFSET + (COMPLETE_STORED_BOUND_COUNT - 1) * 12,
        7.0,
        8.0,
        9.0,
    )
    struct.pack_into(
        "<2f",
        data,
        MINIMUM_OFFSET + PARTIAL_STORED_BOUND_ID * 12,
        -10.0,
        -11.0,
    )
    struct.pack_into(
        "<2f",
        data,
        MAXIMUM_OFFSET + PARTIAL_STORED_BOUND_ID * 12,
        10.0,
        11.0,
    )
    return bytes(data)


class ModelGeometryTableTests(unittest.TestCase):
    def test_parses_all_four_blocks_and_round_trips(self) -> None:
        data = _table_bytes()
        table = U9ModelGeometryTable(data)

        self.assertEqual(len(table.records), MODEL_SLOT_COUNT)
        self.assertEqual(table.record(0).culling_radius, -1.0)
        self.assertEqual(table.record(0).culling_radius_status, "unavailable_sentinel")
        self.assertEqual(table.record(1).culling_radius_status, "unexpected_negative")
        self.assertEqual(table.record(1).culling_center[:2], (1.0, 2.0))
        self.assertEqual(table.to_bytes(), data)

    def test_maps_short_bound_blocks_as_prefixes_not_scalar_arrays(self) -> None:
        table = U9ModelGeometryTable(_table_bytes())
        complete = table.record(COMPLETE_STORED_BOUND_COUNT - 1)
        partial = table.record(PARTIAL_STORED_BOUND_ID)
        absent = table.record(PARTIAL_STORED_BOUND_ID + 1)

        self.assertEqual(complete.bounds_storage_status, "complete")
        self.assertEqual(complete.bounds_minimum, (-7.0, -8.0, -9.0))
        self.assertEqual(partial.bounds_storage_status, "xy_only")
        self.assertEqual(partial.bounds_minimum, (-10.0, -11.0, None))
        self.assertEqual(len(partial.minimum_raw_data), 8)
        self.assertEqual(absent.bounds_storage_status, "absent")
        self.assertEqual(absent.bounds_maximum, (None, None, None))
        self.assertEqual(absent.maximum_raw_data, b"")

    def test_reports_numeric_anomalies_without_rejecting_them(self) -> None:
        table = U9ModelGeometryTable(_table_bytes())

        self.assertEqual(
            table.record(1).structural_warnings(),
            ("culling_radius_unexpected_negative", "culling_center_nonfinite"),
        )
        self.assertEqual(
            table.record(2).structural_warnings(), ("bounds_axis_0_reversed",)
        )

    def test_rejects_wrong_extent_and_out_of_range_ids(self) -> None:
        with self.assertRaisesRegex(U9ModelGeometryTableError, "exactly 192000"):
            U9ModelGeometryTable(b"short")
        table = U9ModelGeometryTable(_table_bytes())
        with self.assertRaisesRegex(IndexError, "outside"):
            table.record(MODEL_SLOT_COUNT)

    def test_csv_export_keeps_partial_and_raw_fragments_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "dimension.dat"
            source.write_bytes(_table_bytes())
            output = root / "csv"

            result = cmd_dimension_csv(
                SimpleNamespace(file=str(source), output=str(output), models=None)
            )

            self.assertEqual(result, 0)
            with (output / "u9_dimensions.csv").open(
                encoding="utf-8", newline=""
            ) as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), MODEL_SLOT_COUNT)
            self.assertEqual(
                rows[PARTIAL_STORED_BOUND_ID]["bounds_storage_status"], "xy_only"
            )
            self.assertEqual(rows[PARTIAL_STORED_BOUND_ID]["bounds_minimum_z"], "")
            self.assertTrue(rows[0]["radius_raw_hex"].startswith("0x"))


if __name__ == "__main__":
    unittest.main()
