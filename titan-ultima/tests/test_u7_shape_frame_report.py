"""Combined U7 shape frame, origin/hotspot, and WIHH report tests."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from titan.u7.cli import cmd_shape_frame_report
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape
from titan.u7.shape_frame_report import build_u7_shape_frame_report
from titan.u7.wihh import U7WeaponInHandOffsets


def _rle_shape_record(origin_x: int = -2, origin_y: int = 0) -> bytes:
    shape = U7Shape()
    frame = U7Shape.Frame()
    frame.width = 3
    frame.height = 2
    frame.origin_x = origin_x
    frame.origin_y = origin_y
    frame.pixels = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
    shape.frames.append(frame)
    return shape.to_bytes()


def _wihh_data(shape_index: int, x: int = 5, y: int = 14) -> bytes:
    data = bytearray(2048 + 64)
    data[shape_index * 2 : shape_index * 2 + 2] = (2048).to_bytes(2, "little")
    data[2048:2050] = bytes([x, y])
    return bytes(data)


class U7ShapeFrameReportTests(unittest.TestCase):
    def test_combines_tile_rle_origin_hotspot_and_wihh_rows(self) -> None:
        archive = U7FlexArchive()
        archive.title = "Synthetic shapes"
        archive.records = [bytes(range(64))] + [b""] * 149 + [_rle_shape_record()]
        wihh = U7WeaponInHandOffsets.from_bytes(
            _wihh_data(150), shape_count=len(archive.records)
        )

        report = build_u7_shape_frame_report(archive, wihh=wihh)

        tile_row = report.rows[0]
        self.assertEqual((tile_row.shape, tile_row.frame), (0, 0))
        self.assertTrue(tile_row.is_tile)
        self.assertIsNone(tile_row.origin_x)
        self.assertIsNone(tile_row.hotspot_x_from_left)

        empty_row = report.rows[1]
        self.assertEqual(empty_row.shape_status, "empty")
        self.assertIsNone(empty_row.frame)

        sprite_row = report.rows[-1]
        self.assertEqual((sprite_row.shape, sprite_row.frame), (150, 0))
        self.assertFalse(sprite_row.is_tile)
        self.assertEqual((sprite_row.origin_x, sprite_row.origin_y), (-2, 0))
        self.assertEqual(
            (sprite_row.hotspot_x_from_left, sprite_row.hotspot_y_from_top),
            (4, 1),
        )
        self.assertEqual((sprite_row.attachment_x, sprite_row.attachment_y), (5, 14))
        self.assertTrue(sprite_row.draw_weapon)
        self.assertEqual(report.shape_count, 151)
        self.assertEqual(report.frame_count, 2)

    def test_json_preserves_nulls_when_no_wihh_is_available(self) -> None:
        archive = U7FlexArchive()
        archive.records = [bytes(range(64))]

        payload = json.loads(build_u7_shape_frame_report(archive).to_json())

        self.assertIsNone(payload["wihh_path"])
        self.assertIsNone(payload["rows"][0]["origin_x"])
        self.assertIsNone(payload["rows"][0]["attachment_x"])

    def test_custom_archive_allows_rle_shape_at_low_record_index(self) -> None:
        archive = U7FlexArchive()
        archive.records = [_rle_shape_record(1, -1)]

        report = build_u7_shape_frame_report(
            archive,
            archive_path="C:/mods/U7O.VGA",
        )

        row = report.rows[0]
        self.assertFalse(row.is_tile)
        self.assertEqual((row.origin_x, row.origin_y), (1, -1))
        self.assertEqual((row.hotspot_x_from_left, row.hotspot_y_from_top), (1, 2))

    def test_cli_auto_discovers_sibling_wihh_and_writes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "SHAPES.VGA"
            output_path = temp_path / "combined.csv"

            archive = U7FlexArchive()
            archive.records = [b""] * 150 + [_rle_shape_record(0, 0)]
            archive.save(str(archive_path))
            (temp_path / "WIHH.DAT").write_bytes(_wihh_data(150, 7, 9))

            result = cmd_shape_frame_report(
                SimpleNamespace(
                    file=str(archive_path),
                    output=str(output_path),
                    wihh=None,
                    format="csv",
                )
            )

            self.assertEqual(result, 0)
            with output_path.open(encoding="utf-8", newline="") as report_file:
                rows = list(csv.DictReader(report_file))
            sprite_row = rows[-1]
            self.assertEqual(sprite_row["shape"], "150")
            self.assertEqual(sprite_row["origin_x"], "0")
            self.assertEqual(sprite_row["hotspot_x_from_left"], "2")
            self.assertEqual(sprite_row["attachment_x"], "7")
            self.assertEqual(sprite_row["attachment_y"], "9")

    def test_cli_rejects_missing_explicit_wihh_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "SHAPES.VGA"
            archive = U7FlexArchive()
            archive.save(str(archive_path))

            result = cmd_shape_frame_report(
                SimpleNamespace(
                    file=str(archive_path),
                    output=str(temp_path / "report.csv"),
                    wihh=str(temp_path / "missing.dat"),
                    format="csv",
                )
            )

            self.assertEqual(result, 1)
            self.assertFalse((temp_path / "report.csv").exists())


if __name__ == "__main__":
    unittest.main()
