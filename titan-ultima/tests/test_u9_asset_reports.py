"""Tests for dynamic U9 texture-frame and model-material reports."""

from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path

from titan.u9.asset_reports import (
    TEXTURE_REPORT_COLUMNS,
    U9AssetReportError,
    build_model_material_report,
    build_texture_frame_report,
    write_dynamic_report,
)

DIR_OFFSET = 0x80
MODEL_HEADER_SIZE = 0x90
LIMB_HEADER_SIZE = 0x30
LOD_HEADER_SIZE = 0x7C


def _build_flx(entries: list[bytes | None]) -> bytes:
    header = bytearray(DIR_OFFSET)
    struct.pack_into("<I", header, 0x50, len(entries))
    struct.pack_into("<I", header, 0x54, 2)
    cursor = DIR_OFFSET + len(entries) * 8
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


def _texture_entry(frame_count: int = 2) -> bytes:
    """A one-pixel RGB565 texture with independently addressable frames."""
    directory_size = frame_count * 8
    cursor = 0x10 + directory_size
    directory = bytearray()
    payload = bytearray()
    for index in range(frame_count):
        frame = struct.pack("<2H4I", 0, 0x6000, 1, 1, 0, 0)
        frame += struct.pack("<I", 24)
        frame += struct.pack("<H", index)
        directory += struct.pack("<II", cursor, len(frame))
        payload += frame
        cursor += len(frame)
    header = struct.pack("<4H2I", 1, 0, 1, 0, frame_count, 0)
    return header + directory + payload


def _sdinfo_entry(frame_count: int = 2) -> bytes:
    fields = [0] * 12
    fields[2] = 0
    fields[5] = 1
    fields[6] = 1
    fields[9] = 1
    fields[10] = 1
    fields[11] = frame_count
    return struct.pack("<12I", *fields)


def _model_header() -> bytes:
    data = (
        struct.pack("<II", 1, 1)
        + struct.pack("<3f", 0, 0, 0)
        + struct.pack("<2f", 0, 0)
        + struct.pack("<3f", 0, 0, 0)
        + struct.pack("<f", 1)
        + struct.pack("<f", 0)
        + struct.pack("<3f", -1, -1, -1)
        + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<4I", 100, 200, 300, 400)
        + struct.pack("<3f", 0, 0, 0)
    )
    return data + b"\x00" * (MODEL_HEADER_SIZE - len(data))


def _limb_header() -> bytes:
    return (
        struct.pack("<II", 1, 1)
        + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<3f", 0, 0, 0)
        + struct.pack("<4f", 1, 0, 0, 0)
    )


def _corner(vertex_index: int, uv: tuple[float, float] = (0.0, 0.0)) -> bytes:
    return (
        struct.pack("<II", vertex_index, 0)
        + struct.pack("<3f", 0, 0, 1)
        + struct.pack("<2f", *uv)
    )


def _face(*, nonfinite_uv: bool = False) -> bytes:
    data = b"".join(
        _corner(index, (float("nan"), float("nan")) if nonfinite_uv else (0.0, 0.0))
        for index in range(3)
    )
    data += struct.pack("<II3ffI", 0, 0, 0, 0, 1, 0, 0)
    data += bytes((255, 255, 255, 255)) + b"\x00" * 8
    return data


def _animated_model(texture_id: int, *, nonfinite_uv: bool = False) -> bytes:
    face = _face(nonfinite_uv=nonfinite_uv)
    vertices = b"".join(
        struct.pack("<3f", *vertex)
        for vertex in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    )
    material = struct.pack("<6H", texture_id, 0, 0, 0, 0, 1)
    material += bytes((255, 255, 0, 1, 0, 5, 3, 0)) + struct.pack("<I", 0)
    face_offset = LOD_HEADER_SIZE
    vertex_offset = face_offset + len(face)
    material_offset = vertex_offset + len(vertices)
    mesh_size = LOD_HEADER_SIZE + len(face) + len(vertices) + len(material)
    lod = (
        struct.pack("<III", mesh_size, 0, 0)
        + struct.pack("<3ff", 0, 0, 0, 1)
        + struct.pack("<3f", -1, -1, -1)
        + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<II", 0, 0)
        + struct.pack("<6I", 1, 0, 3, 0, 1, 1)
        + struct.pack("<5I", face_offset, 0, vertex_offset, 0, material_offset)
        + struct.pack("<4I", 0, 0, 0, 0)
        + struct.pack("<I", 0)
        + b"\x00" * 4
        + face
        + vertices
        + material
    )
    limb_offset = MODEL_HEADER_SIZE + 8
    lod_offset = limb_offset + LIMB_HEADER_SIZE
    return (
        _model_header()
        + struct.pack("<II", limb_offset, lod_offset)
        + _limb_header()
        + lod
    )


class DynamicReportTests(unittest.TestCase):
    def test_csv_unions_columns_from_later_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.csv"
            write_dynamic_report(
                [{"entry_id": 1, "first_helper": 2}, {"entry_id": 2, "later": 3}],
                output,
                "csv",
                preferred_columns=TEXTURE_REPORT_COLUMNS,
            )
            with output.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                self.assertEqual(
                    reader.fieldnames, ["entry_id", "first_helper", "later"]
                )
            self.assertEqual(rows[1]["later"], "3")


class AssetReportIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.static = Path(self.temp.name)
        (self.static / "bitmap16.flx").write_bytes(_build_flx([None, _texture_entry()]))
        (self.static / "sdInfo16.flx").write_bytes(_build_flx([None, _sdinfo_entry()]))
        (self.static / "sappear.flx").write_bytes(
            _build_flx([_animated_model(texture_id=1)])
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_texture_report_confirms_model_backed_animation(self) -> None:
        rows, warnings = build_texture_frame_report(self.static, entry_id=1)
        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["animation_status"] for row in rows}, {"confirmed"})
        self.assertEqual(rows[0]["referencing_model_ids"], [0])
        self.assertEqual(rows[0]["sdinfo_frame_count"], 2)
        self.assertEqual(rows[0]["encoding"], "rgb565")

    def test_invalid_filter_fails_even_if_it_would_select_no_rows(self) -> None:
        with self.assertRaises(U9AssetReportError):
            build_texture_frame_report(self.static, only="not-a-filter")

    def test_model_report_adds_columns_for_discovered_texture_tier(self) -> None:
        rows, warnings = build_model_material_report(self.static, model_id=0)
        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["material_animation_status"], "confirmed")
        self.assertEqual(row["texture_16_frame_count"], 2)
        self.assertEqual(row["texture_16_encodings"], ["rgb565"])
        self.assertNotIn("texture_sh_frame_count", row)
        self.assertEqual(row["nonfinite_uv_corner_count"], 0)
        self.assertNotIn("has_changing_animation_range", row)
        self.assertNotIn("texture_tier_frame_counts", row)

        animated_rows, _ = build_model_material_report(
            self.static,
            model_id=0,
            only="animated",
        )
        self.assertEqual(len(animated_rows), 1)

    def test_model_report_counts_nonfinite_uvs_for_material_row(self) -> None:
        (self.static / "sappear.flx").write_bytes(
            _build_flx([_animated_model(texture_id=1, nonfinite_uv=True)])
        )

        rows, warnings = build_model_material_report(
            self.static,
            model_id=0,
            only="errors",
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["nonfinite_uv_corner_count"], 3)


if __name__ == "__main__":
    unittest.main()
