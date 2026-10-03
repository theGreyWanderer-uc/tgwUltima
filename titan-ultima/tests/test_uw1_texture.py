"""Tests for native Ultima Underworld 1 texture support."""

from __future__ import annotations

import csv
import json
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from titan.cli import app
from titan.uw1.palette import PALETTE_BYTE_SIZE, UW1Palette
from titan.uw1.texture import (
    UW1TextureArchive,
    UW1TextureError,
    export_all_textures,
)


def _palette_bytes() -> bytes:
    palette = bytearray(PALETTE_BYTE_SIZE)
    palette[3:6] = bytes((1, 31, 63))
    return bytes(palette)


def _texture_archive_bytes(prefix: bytes, resolution: int, count: int) -> bytes:
    data_offset = 4 + count * 4 + 4
    offsets = [data_offset + index * resolution * resolution for index in range(count)]
    header = struct.pack("<BBH", 2, resolution, count)
    table = struct.pack(f"<{count}I", *offsets)
    pixels = b"".join(
        bytes([index + 1]) * (resolution * resolution) for index in range(count)
    )
    return header + table + prefix + pixels


class UW1TextureTests(unittest.TestCase):
    def test_palette_decodes_six_bit_vga_components(self) -> None:
        palette = UW1Palette.from_data(_palette_bytes())
        self.assertEqual(palette.colors[1], (4, 124, 252))

    def test_archive_preserves_texture_ids_and_offsets(self) -> None:
        archive = UW1TextureArchive.from_data(
            _texture_archive_bytes(b"PAD!", resolution=2, count=2),
            path="F2.TR",
        )
        self.assertEqual(archive.resolution, 2)
        self.assertEqual([texture.index for texture in archive.textures], [0, 1])
        self.assertEqual(archive.textures[0].offset, 16)
        self.assertEqual(archive.textures[1].pixels, bytes([2]) * 4)

    def test_archive_rejects_out_of_range_texture(self) -> None:
        data = struct.pack("<BBHI", 2, 4, 1, 999)
        with self.assertRaisesRegex(UW1TextureError, "outside"):
            UW1TextureArchive.from_data(data)


class UW1TextureExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "DATA"
        self.data.mkdir()
        (self.data / "PALS.DAT").write_bytes(_palette_bytes())
        (self.data / "F2.TR").write_bytes(
            _texture_archive_bytes(b"PAD!", resolution=2, count=2)
        )
        (self.data / "W4.TR").write_bytes(
            _texture_archive_bytes(b"PAD!", resolution=4, count=3)
        )
        self.output = self.root / "output"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exports_every_texture_and_manifests(self) -> None:
        result = export_all_textures(self.root, self.output, scale=2)

        self.assertEqual(result["archive_count"], 2)
        self.assertEqual(result["texture_count"], 5)
        png = self.output / "textures" / "w4" / "w4_002.png"
        with Image.open(png) as image:
            self.assertEqual(image.size, (8, 8))

        with (self.output / "textures_manifest.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]["texture_kind"], "wall")
        manifest = json.loads(
            (self.output / "textures_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["textures"]), 5)

    def test_contact_sheets_are_optional(self) -> None:
        export_all_textures(self.root, self.output, contact_sheets=True)
        self.assertTrue(
            (self.output / "textures" / "f2" / "f2_contact_sheet.png").is_file()
        )

    def test_cli_exports_textures(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "uw1",
                "texture-export",
                "--gamedir",
                str(self.root),
                "--output",
                str(self.output),
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Exported 5 UW1 textures", result.output)


if __name__ == "__main__":
    unittest.main()
