"""Tests for titan.u9.palette's ankh.pal color table reader.

Format (256 entries * 4 bytes RGB+unused) and R,G,B byte order were
both confirmed against real data -- see the module docstring for the
cross-check (the same "default" placeholder texture decoded correctly
through this palette, matching its independently-confirmed 16-bit
counterpart's color family). Not re-derived here; fixtures below are
hand-built and only check the documented byte layout is read correctly.
"""

from __future__ import annotations

import unittest

from titan.u9.palette import U9Palette, U9PaletteError


def _build_palette(colors: list[tuple[int, int, int]]) -> bytes:
    data = bytearray()
    for r, g, b in colors:
        data += bytes([r, g, b, 0])
    # pad out to 256 entries with black
    while len(data) < 256 * 4:
        data += bytes([0, 0, 0, 0])
    return bytes(data)


class PaletteTests(unittest.TestCase):
    def test_color_for_reads_rgb_in_order(self) -> None:
        data = _build_palette([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        palette = U9Palette(data)
        self.assertEqual(palette.color_for(0), (255, 0, 0))
        self.assertEqual(palette.color_for(1), (0, 255, 0))
        self.assertEqual(palette.color_for(2), (0, 0, 255))

    def test_fourth_byte_ignored(self) -> None:
        data = bytearray(_build_palette([(10, 20, 30)]))
        data[3] = 0xFF  # the "unused" 4th byte of entry 0
        palette = U9Palette(bytes(data))
        self.assertEqual(palette.color_for(0), (10, 20, 30))

    def test_len_is_256(self) -> None:
        palette = U9Palette(_build_palette([]))
        self.assertEqual(len(palette), 256)

    def test_too_small_data_raises(self) -> None:
        with self.assertRaises(U9PaletteError):
            U9Palette(b"\x00" * 100)


if __name__ == "__main__":
    unittest.main()
