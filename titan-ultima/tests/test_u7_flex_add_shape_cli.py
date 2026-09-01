"""Tests for adding a standalone U7 shape to the first free Flex record."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from titan.u7.cli import cmd_u7_flex_add_shape
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape


def _write_test_shape(path: Path, palette_index: int = 7) -> bytes:
    shape = U7Shape()
    frame = U7Shape.Frame()
    frame.width = 2
    frame.height = 2
    frame.origin_x = 0
    frame.origin_y = 0
    frame.pixels = np.array(
        [[0xFF, palette_index], [palette_index, palette_index]], dtype=np.uint8
    )
    shape.frames.append(frame)
    data = shape.to_bytes()
    path.write_bytes(data)
    return data


class U7FlexAddShapeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.archive_path = self.root / "source.VGA"
        self.shape_path = self.root / "actor.shp"
        self.output_path = self.root / "output.VGA"
        self.shape_data = _write_test_shape(self.shape_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_archive(self, records: list[bytes]) -> None:
        archive = U7FlexArchive()
        archive.title = "Test shape archive"
        archive.records = records
        archive.save(str(self.archive_path))

    def _run(
        self,
        *,
        output: str | None = None,
        in_place: bool = False,
        force: bool = False,
        index: int | None = None,
        replace: bool = False,
    ) -> int:
        return cmd_u7_flex_add_shape(
            SimpleNamespace(
                archive=str(self.archive_path),
                shape=str(self.shape_path),
                output=output,
                in_place=in_place,
                force=force,
                index=index,
                replace=replace,
            )
        )

    def test_adds_to_record_zero_of_empty_archive_without_mutating_source(self) -> None:
        self._write_archive([])

        self.assertEqual(self._run(output=str(self.output_path)), 0)

        source = U7FlexArchive.from_file(str(self.archive_path))
        result = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(source.records, [])
        self.assertEqual(result.records, [self.shape_data])

    def test_in_place_uses_lowest_empty_record(self) -> None:
        self._write_archive([b"occupied zero", b"", b"occupied two"])

        self.assertEqual(self._run(in_place=True), 0)

        result = U7FlexArchive.from_file(str(self.archive_path))
        self.assertEqual(
            result.records, [b"occupied zero", self.shape_data, b"occupied two"]
        )

    def test_appends_when_archive_has_no_empty_record(self) -> None:
        self._write_archive([b"occupied"])

        self.assertEqual(self._run(output=str(self.output_path)), 0)

        result = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(result.records, [b"occupied", self.shape_data])

    def test_shapes_vga_automatic_allocation_starts_at_record_150(self) -> None:
        self.archive_path = self.root / "SHAPES.VGA"
        self._write_archive([])

        self.assertEqual(self._run(output=str(self.output_path)), 0)

        result = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(len(result.records), 151)
        self.assertEqual(result.records[:150], [b""] * 150)
        self.assertEqual(result.records[150], self.shape_data)

    def test_shapes_vga_uses_lowest_empty_record_after_record_149(self) -> None:
        self.archive_path = self.root / "shapes.vga"
        records = [b""] * 153
        records[150] = b"occupied 150"
        records[152] = b"occupied 152"
        self._write_archive(records)

        self.assertEqual(self._run(in_place=True), 0)

        result = U7FlexArchive.from_file(str(self.archive_path))
        self.assertEqual(result.records[150], b"occupied 150")
        self.assertEqual(result.records[151], self.shape_data)
        self.assertEqual(result.records[152], b"occupied 152")

    def test_requires_exactly_one_output_mode(self) -> None:
        self._write_archive([])

        self.assertEqual(self._run(), 1)
        self.assertEqual(
            self._run(output=str(self.output_path), in_place=True),
            1,
        )
        self.assertFalse(self.output_path.exists())

    def test_refuses_to_replace_output_without_force(self) -> None:
        self._write_archive([])
        self.output_path.write_bytes(b"existing")

        self.assertEqual(self._run(output=str(self.output_path)), 1)
        self.assertEqual(self.output_path.read_bytes(), b"existing")

    def test_specific_index_grows_archive_with_empty_records(self) -> None:
        self._write_archive([b"occupied zero"])

        self.assertEqual(self._run(output=str(self.output_path), index=4), 0)

        result = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(
            result.records,
            [b"occupied zero", b"", b"", b"", self.shape_data],
        )

    def test_specific_index_refuses_to_replace_occupied_record(self) -> None:
        self._write_archive([b"occupied zero"])

        self.assertEqual(self._run(output=str(self.output_path), index=0), 1)
        self.assertFalse(self.output_path.exists())

    def test_specific_index_replaces_occupied_record_when_explicit(self) -> None:
        self._write_archive([b"occupied zero"])

        self.assertEqual(
            self._run(output=str(self.output_path), index=0, replace=True),
            0,
        )

        result = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(result.records, [self.shape_data])

    def test_rejects_negative_record_index(self) -> None:
        self._write_archive([])

        self.assertEqual(self._run(output=str(self.output_path), index=-1), 1)
        self.assertFalse(self.output_path.exists())

    def test_replace_requires_specific_index(self) -> None:
        self._write_archive([])

        self.assertEqual(self._run(output=str(self.output_path), replace=True), 1)
        self.assertFalse(self.output_path.exists())


if __name__ == "__main__":
    unittest.main()
