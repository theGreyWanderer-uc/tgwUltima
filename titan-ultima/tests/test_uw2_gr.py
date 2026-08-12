"""Tests for Ultima Underworld II GR shape archives."""

from __future__ import annotations

import struct
import unittest

from titan.uw2.gr import UW2GRArchive, UW2GRError
from titan.uw2.palette import PALETTE_BYTE_SIZE, UW2Palette


def _raw_gr_archive(width: int, height: int, pixels: bytes) -> bytes:
    record = bytes((0x04, width, height)) + struct.pack("<H", len(pixels)) + pixels
    return bytes((1, 1, 0)) + struct.pack("<I", 7) + record


class UW2GRArchiveTests(unittest.TestCase):
    def test_decodes_raw_bitmap_and_transparency(self) -> None:
        archive = UW2GRArchive.from_data(_raw_gr_archive(2, 2, b"\x00\x01\x02\x03"))
        palette_data = bytearray(PALETTE_BYTE_SIZE)
        palette_data[3:6] = bytes((63, 0, 0))
        palette = UW2Palette.from_data(bytes(palette_data))

        image = archive.image(0).to_image(palette)

        self.assertEqual(image.size, (2, 2))
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        red_pixel = image.getpixel((1, 0))
        self.assertIsInstance(red_pixel, tuple)
        self.assertEqual(red_pixel, (252, 0, 0, 255))

    def test_preserves_sparse_declared_indices(self) -> None:
        record = bytes((0x04, 1, 1)) + struct.pack("<H", 1) + b"\x05"
        data = bytes((1, 2, 0)) + struct.pack("<II", 0, 11) + record
        archive = UW2GRArchive.from_data(data)

        self.assertEqual(archive.declared_image_count, 2)
        self.assertEqual([image.index for image in archive.images], [1])

    def test_rejects_unknown_bitmap_type(self) -> None:
        data = bytes((1, 1, 0)) + struct.pack("<I", 7) + bytes((0xFF, 1, 1))
        with self.assertRaisesRegex(UW2GRError, "unsupported bitmap type"):
            UW2GRArchive.from_data(data)


if __name__ == "__main__":
    unittest.main()
