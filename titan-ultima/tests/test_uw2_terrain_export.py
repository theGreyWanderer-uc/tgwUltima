"""Tests for T64.TR terrain export and GR/terrain contact sheets.

``T64.TR`` textures are uniformly sized, but GR archives such as ``TMOBJ.GR``
mix small decals with tall door panels and wide banners, so contact-sheet cells
are sized to the largest image and smaller ones centred.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from titan.uw2.map_pipeline import export_terrain_textures
from titan.uw2.terrain import make_contact_sheet


def _palette_bytes() -> bytes:
    palette = bytearray(768)
    for index in range(256):
        palette[index * 3] = index % 64
        palette[index * 3 + 1] = (index * 2) % 64
        palette[index * 3 + 2] = (index * 3) % 64
    return bytes(palette)


def _t64_bytes(count: int = 4, resolution: int = 8) -> bytes:
    """One minimal T64.TR: format byte, resolution byte, count word, offsets."""
    header = bytearray((2, resolution))
    header.extend(struct.pack("<H", count))
    table_start = 4 + count * 4
    body = bytearray()
    offsets = []
    for index in range(count):
        offsets.append(table_start + len(body))
        body.extend(bytes([index] * (resolution * resolution)))
    for offset in offsets:
        header.extend(struct.pack("<I", offset))
    return bytes(header) + bytes(body)


class UW2ContactSheetTests(unittest.TestCase):
    def test_uniform_images_tile_as_a_fixed_cell_grid(self) -> None:
        images = [Image.new("RGBA", (8, 8), (200, 10, 10, 255)) for _ in range(4)]

        sheet = make_contact_sheet(images, columns=2, padding=1)

        self.assertEqual(sheet.size, (2 * 8 + 3, 2 * 8 + 3))
        self.assertEqual(sheet.getpixel((1, 1)), (200, 10, 10, 255))

    def test_ragged_images_are_centred_in_max_sized_cells(self) -> None:
        images = [
            Image.new("RGBA", (10, 4), (10, 200, 10, 255)),
            Image.new("RGBA", (4, 10), (10, 10, 200, 255)),
        ]

        sheet = make_contact_sheet(images, columns=2, padding=0)

        # Cells are 10x10, so the whole sheet is 20x10 with nothing clipped.
        self.assertEqual(sheet.size, (20, 10))
        # The 10x4 image is centred vertically inside its 10-tall cell.
        self.assertEqual(sheet.getpixel((0, 3)), (10, 200, 10, 255))
        # The 4x10 image is centred horizontally inside its 10-wide cell.
        self.assertEqual(sheet.getpixel((13, 0)), (10, 10, 200, 255))

    def test_rejects_empty_input_and_bad_columns(self) -> None:
        with self.assertRaises(ValueError):
            make_contact_sheet([])
        with self.assertRaises(ValueError):
            make_contact_sheet([Image.new("RGBA", (4, 4))], columns=0)


class UW2TerrainExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "DATA"
        self.data.mkdir()
        (self.data / "PALS.DAT").write_bytes(_palette_bytes())
        (self.data / "T64.TR").write_bytes(_t64_bytes())
        self.output = self.root / "textures"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_one_png_per_texture_plus_a_summary(self) -> None:
        result = export_terrain_textures(self.root, self.output)

        self.assertEqual(result["count"], 4)
        self.assertEqual(result["resolution"], 8)
        self.assertIsNone(result["contact_sheet"])
        self.assertTrue((self.output / "t64_000.png").is_file())
        self.assertTrue((self.output / "t64_003.png").is_file())
        self.assertTrue((self.output / "t64_summary.json").is_file())

    def test_contact_sheet_is_opt_in(self) -> None:
        result = export_terrain_textures(self.root, self.output, contact_sheet=True)

        sheet = self.output / "t64_contact_sheet.png"
        self.assertEqual(result["contact_sheet"], str(sheet))
        self.assertTrue(sheet.is_file())

    def test_scale_upsamples_with_nearest_neighbour(self) -> None:
        export_terrain_textures(self.root, self.output, scale=4)

        with Image.open(self.output / "t64_000.png") as image:
            self.assertEqual(image.size, (32, 32))

    def test_rejects_a_scale_below_one(self) -> None:
        with self.assertRaises(ValueError):
            export_terrain_textures(self.root, self.output, scale=0)

    def test_exported_names_match_what_the_catalog_references(self) -> None:
        # texture_catalog entries point at textures/t64_###.png.
        export_terrain_textures(self.root, self.output)

        self.assertTrue((self.output / "t64_002.png").is_file())


if __name__ == "__main__":
    unittest.main()
