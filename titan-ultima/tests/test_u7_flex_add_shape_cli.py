"""Tests for adding a standalone U7 shape to the first free Flex record."""

from __future__ import annotations

import tempfile
import unittest
import struct
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
        archive_kind: str = "generic",
        flat: bool = False,
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
                archive_kind=archive_kind,
                flat=flat,
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

        self.assertEqual(
            self._run(output=str(self.output_path), archive_kind="shapes"), 0
        )

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

        self.assertEqual(self._run(in_place=True, archive_kind="shapes"), 0)

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

    def test_rejects_damaged_archives_without_changing_source_or_output(self) -> None:
        for mode in (
            "truncated-table",
            "past-eof",
            "partial-record",
            "in-header",
            "zero-offset",
        ):
            with self.subTest(mode=mode):
                self._write_archive([b"occupied"])
                data = bytearray(self.archive_path.read_bytes())
                if mode == "truncated-table":
                    struct.pack_into("<I", data, 0x54, 10)
                else:
                    offset, size = {
                        "past-eof": (len(data) + 1, 8),
                        "partial-record": (len(data) - 2, 8),
                        "in-header": (16, 8),
                        "zero-offset": (0, 8),
                    }[mode]
                    struct.pack_into("<II", data, 128, offset, size)
                self.archive_path.write_bytes(data)
                self.output_path.write_bytes(b"existing output")

                self.assertEqual(self._run(in_place=True), 1)
                self.assertEqual(self.archive_path.read_bytes(), data)
                self.assertEqual(self._run(output=str(self.output_path), force=True), 1)
                self.assertEqual(self.output_path.read_bytes(), b"existing output")
                self.assertEqual(self.archive_path.read_bytes(), data)

    def test_rejects_invalid_shapes_without_writing(self) -> None:
        extents = struct.pack("<hhhh", 0, 1, 1, 0)
        invalid_frames = [
            b"",  # Frame table points exactly to EOF.
            extents[:7],  # Incomplete extents.
            struct.pack("<hhhhH", -1, 0, 0, 0, 0),  # Zero width.
            extents + struct.pack("<Hhh", 4, -1, -1) + b"\x07",  # Truncated raw span.
            extents
            + struct.pack("<Hhh", 5, -1, -1)
            + b"\x00\x07\x00\x00",  # Zero RLE block.
            extents
            + struct.pack("<Hhh", 5, -1, -1)
            + b"\x07\x07\x00\x00",  # RLE overrun.
            extents
            + struct.pack("<Hhh", 4, 1, 0)
            + b"\x07\x07\x00\x00",  # Span outside frame.
        ]
        bad_shapes = [
            struct.pack("<II", 8 + len(frame), 8) + frame for frame in invalid_frames
        ]
        bad_shapes.extend([b"", b"\x00", struct.pack("<II", 8, 100)])
        for data in bad_shapes:
            with self.subTest(data=data):
                self._write_archive([b"occupied"])
                source = self.archive_path.read_bytes()
                self.shape_path.write_bytes(data)
                self.assertEqual(self._run(in_place=True), 1)
                self.assertEqual(self.archive_path.read_bytes(), source)
                self.assertFalse(self.output_path.exists())

    def test_accepts_complete_tile_and_transparent_rle_frames(self) -> None:
        tile = bytes([7] * 64)
        transparent_frame = struct.pack("<hhhhH", 0, 1, 1, 0, 0)
        transparent_shape = (
            struct.pack("<II", 8 + len(transparent_frame), 8) + transparent_frame
        )
        extents_only_shape = struct.pack("<IIhhhh", 16, 8, 0, 1, 1, 0)
        for data in (tile, transparent_shape, extents_only_shape, self.shape_data):
            with self.subTest(data=data):
                self._write_archive([])
                self.shape_path.write_bytes(data)
                self.assertEqual(self._run(output=str(self.output_path), force=True), 0)
                self.assertEqual(
                    U7FlexArchive.from_file(str(self.output_path)).records, [data]
                )

    def test_accepts_word_aligned_rle_record_with_declared_size_one_byte_shorter(
        self,
    ) -> None:
        frame = struct.pack("<hhhhHhh", 0, 0, 0, 0, 2, 0, 0) + b"\x07\x00\x00"
        data = struct.pack("<II", 8 + len(frame), 8) + frame + b"\x00"
        self._write_archive([])
        self.shape_path.write_bytes(data)

        self.assertEqual(self._run(output=str(self.output_path)), 0)
        pixels = U7Shape.from_data(data, strict=True).frames[0].pixels
        np.testing.assert_array_equal(pixels, [[7]])

    def test_default_rules_protect_renamed_shapes_archive(self) -> None:
        self._write_archive([b""] * 151)
        args = SimpleNamespace(
            archive=str(self.archive_path),
            shape=str(self.shape_path),
            output=str(self.output_path),
            in_place=False,
            force=False,
        )
        self.assertEqual(cmd_u7_flex_add_shape(args), 0)
        archive = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(archive.records[:150], [b""] * 150)
        self.assertEqual(archive.records[150], self.shape_data)

    def test_object_cannot_use_flat_slots_even_with_replace(self) -> None:
        for index in (0, 149):
            with self.subTest(index=index):
                self._write_archive([b"occupied"] * 151)
                before = self.archive_path.read_bytes()
                self.assertEqual(
                    self._run(
                        in_place=True, index=index, replace=True, archive_kind="shapes"
                    ),
                    1,
                )
                self.assertEqual(self.archive_path.read_bytes(), before)

    def test_flat_auto_allocation_stays_below_slot_150(self) -> None:
        self.shape_path.write_bytes(bytes([7] * 64))
        records = [bytes([8] * 64)] * 151
        records[149] = b""
        self._write_archive(records)
        self.assertEqual(self._run(in_place=True, archive_kind="shapes", flat=True), 0)
        archive = U7FlexArchive.from_file(str(self.archive_path))
        self.assertEqual(archive.records[149], bytes([7] * 64))
        self.assertEqual(archive.records[150], records[150])

    def test_full_flat_range_does_not_append_an_object_slot(self) -> None:
        self.shape_path.write_bytes(bytes([7] * 64))
        self._write_archive([bytes([8] * 64)] * 150)
        before = self.archive_path.read_bytes()
        self.assertEqual(self._run(in_place=True, archive_kind="shapes", flat=True), 1)
        self.assertEqual(self.archive_path.read_bytes(), before)

    def test_flat_can_populate_slot_zero_of_an_empty_shapes_archive(self) -> None:
        self.shape_path.write_bytes(bytes([7] * 64))
        self._write_archive([])
        self.assertEqual(self._run(in_place=True, archive_kind="shapes", flat=True), 0)
        self.assertEqual(
            U7FlexArchive.from_file(str(self.archive_path)).records, [bytes([7] * 64)]
        )

    def test_rejects_flat_flag_for_rle_objects_and_flat_object_slot(self) -> None:
        self._write_archive([])
        self.assertEqual(
            self._run(output=str(self.output_path), archive_kind="shapes", flat=True), 1
        )
        self.shape_path.write_bytes(bytes([7] * 64))
        self.assertEqual(
            self._run(
                output=str(self.output_path),
                index=150,
                archive_kind="shapes",
                flat=True,
            ),
            1,
        )
        self.assertEqual(
            self._run(output=str(self.output_path), archive_kind="shapes"), 1
        )
        self.assertEqual(self._run(output=str(self.output_path), flat=True), 1)
        self.assertFalse(self.output_path.exists())

    def test_rejects_oversized_standalone_shape_before_writing_archive(self) -> None:
        for width, height in ((321, 1), (1, 201)):
            with self.subTest(size=(width, height)):
                shape = U7Shape()
                frame = U7Shape.Frame()
                frame.width, frame.height = width, height
                frame.pixels = np.full((height, width), 7, dtype=np.uint8)
                shape.frames.append(frame)
                self.shape_path.write_bytes(shape.to_bytes())
                self._write_archive([b"occupied"])
                before = self.archive_path.read_bytes()
                self.assertEqual(self._run(in_place=True), 1)
                self.assertEqual(self.archive_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
