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

from titan.u9.palette import (
    EXPECTED_SIZE,
    PALETTE_TRANSPARENCY_INDEX,
    U9Palette,
    U9PaletteError,
)


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
        self.assertEqual(palette.reserved[0], 0xFF)

    def test_len_is_256(self) -> None:
        palette = U9Palette(_build_palette([]))
        self.assertEqual(len(palette), 256)

    def test_too_small_data_raises(self) -> None:
        with self.assertRaises(U9PaletteError):
            U9Palette(b"\x00" * 100)

    def test_exact_binary_round_trip_preserves_reserved_bytes(self) -> None:
        data = bytearray(_build_palette([(10, 20, 30), (40, 50, 60)]))
        data[3] = 0x7F
        data[7] = 0xA5
        palette = U9Palette.parse(bytes(data))
        self.assertEqual(palette.to_bytes(), data)

    def test_trailing_data_is_exposed_but_not_serialized_as_palette(self) -> None:
        palette = U9Palette(_build_palette([]) + b"TRAIL")
        self.assertEqual(palette.trailing_data, b"TRAIL")
        self.assertEqual(len(palette.to_bytes()), EXPECTED_SIZE)

    def test_from_colors_defaults_reserved_bytes_to_zero(self) -> None:
        colors = [(index, index, index) for index in range(256)]
        palette = U9Palette.from_colors(colors)
        self.assertEqual(palette.colors, tuple(colors))
        self.assertEqual(set(palette.reserved), {0})
        self.assertEqual(len(palette.to_bytes()), EXPECTED_SIZE)

    def test_from_colors_rejects_wrong_count_or_component(self) -> None:
        with self.assertRaises(U9PaletteError):
            U9Palette.from_colors([(0, 0, 0)] * 255)
        invalid = [(0, 0, 0)] * 256
        invalid[8] = (0, 0, 256)
        with self.assertRaises(U9PaletteError):
            U9Palette.from_colors(invalid)

    def test_rgba_uses_exact_transparency_index(self) -> None:
        colors = [(0, 0, 0)] * 256
        colors[247] = (128, 128, 128)
        colors[PALETTE_TRANSPARENCY_INDEX] = (128, 128, 128)
        palette = U9Palette.from_colors(colors)
        self.assertEqual(palette.rgba_for(247), (128, 128, 128, 255))
        self.assertEqual(
            palette.rgba_for(PALETTE_TRANSPARENCY_INDEX),
            (128, 128, 128, 0),
        )

    def test_nearest_color_uses_first_duplicate_and_honors_exclusion(self) -> None:
        colors = [(0, 0, 0)] * 256
        colors[10] = colors[20] = (12, 34, 56)
        palette = U9Palette.from_colors(colors)
        self.assertEqual(palette.nearest_color_index((12, 34, 56)), 10)
        self.assertEqual(
            palette.nearest_color_index((12, 34, 56), exclude=(10,)),
            20,
        )

    def test_nearest_color_rejects_invalid_exclusions(self) -> None:
        palette = U9Palette(_build_palette([]))
        with self.assertRaises(U9PaletteError):
            palette.nearest_color_index((0, 0, 0), exclude=(-1,))
        with self.assertRaises(U9PaletteError):
            palette.nearest_color_index((0, 0, 0), exclude=range(256))

    def test_duplicate_groups_report_indices_in_order(self) -> None:
        colors = [(index, 0, 0) for index in range(256)]
        colors[20] = colors[10]
        colors[30] = colors[10]
        palette = U9Palette.from_colors(colors)
        self.assertIn(((10, 0, 0), (10, 20, 30)), palette.duplicate_groups())

    def test_flat_rgb_and_swatch_rendering(self) -> None:
        colors = [(index, 255 - index, index // 2) for index in range(256)]
        palette = U9Palette.from_colors(colors)
        self.assertEqual(palette.to_flat_rgb()[:6], bytes((*colors[0], *colors[1])))
        image = palette.to_pil_image(swatch_size=2)
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (32, 32))
        self.assertEqual(image.getpixel((0, 0)), colors[0])
        self.assertEqual(image.getpixel((31, 31)), colors[255])

    def test_invalid_index_and_swatch_size_raise(self) -> None:
        palette = U9Palette(_build_palette([]))
        with self.assertRaises(IndexError):
            palette.color_for(-1)
        with self.assertRaises(IndexError):
            palette.color_for(256)
        with self.assertRaises(U9PaletteError):
            palette.to_pil_image(0)


if __name__ == "__main__":
    unittest.main()
