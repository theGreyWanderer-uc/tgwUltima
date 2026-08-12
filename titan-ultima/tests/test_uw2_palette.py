"""Tests for Ultima Underworld II PALS.DAT decoding."""

from __future__ import annotations

import unittest

from titan.uw2.palette import PALETTE_BYTE_SIZE, UW2Palette, UW2PaletteError


class UW2PaletteTests(unittest.TestCase):
    def test_decodes_selected_6_bit_vga_palette(self) -> None:
        first = bytes(PALETTE_BYTE_SIZE)
        second = bytearray(PALETTE_BYTE_SIZE)
        second[3:6] = bytes((1, 31, 63))

        palette = UW2Palette.from_data(first + second, index=1)

        self.assertEqual(palette.colors[1], (4, 124, 252))
        self.assertEqual(len(palette.flattened_rgb()), 768)

    def test_rejects_out_of_range_palette(self) -> None:
        with self.assertRaisesRegex(UW2PaletteError, "outside source"):
            UW2Palette.from_data(bytes(PALETTE_BYTE_SIZE), index=1)

    def test_renders_16_by_16_swatch_grid(self) -> None:
        palette = UW2Palette.from_data(bytes(PALETTE_BYTE_SIZE))
        self.assertEqual(palette.to_swatch_image(swatch_size=2).size, (32, 32))


if __name__ == "__main__":
    unittest.main()
