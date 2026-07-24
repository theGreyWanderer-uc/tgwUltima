"""Tests for titan.u6.palette's U6PAL reader.

No real game files are used here -- fixtures are hand-built 1024-byte
buffers (768 bytes of 6-bit RGB triplets + 256 trailing bytes), matching
the layout confirmed against a real U6PAL (1024 bytes exactly, no header).
"""

from __future__ import annotations

import unittest

from titan.u6.palette import U6Palette, U6PaletteError


def _make_palette_bytes(colors: dict[int, tuple[int, int, int]] | None = None) -> bytes:
    data = bytearray(1024)
    for i, (r, g, b) in (colors or {}).items():
        data[i * 3:i * 3 + 3] = (r, g, b)
    return bytes(data)


class ParseTests(unittest.TestCase):
    def test_rejects_short_data(self):
        with self.assertRaises(U6PaletteError):
            U6Palette.parse(b"\x00" * 100)

    def test_black_at_index_zero_by_default(self):
        pal = U6Palette.parse(_make_palette_bytes())
        self.assertEqual(pal.colors[0], (0, 0, 0))

    def test_6bit_to_8bit_scaling_full_white(self):
        # 63 (max 6-bit value) must scale to exactly 255, not 252 (<<2).
        pal = U6Palette.parse(_make_palette_bytes({1: (63, 63, 63)}))
        self.assertEqual(pal.colors[1], (255, 255, 255))

    def test_6bit_to_8bit_scaling_midpoint(self):
        pal = U6Palette.parse(_make_palette_bytes({2: (32, 0, 63)}))
        r, g, b = pal.colors[2]
        self.assertEqual(r, (32 * 255) // 63)
        self.assertEqual(g, 0)
        self.assertEqual(b, 255)

    def test_trailing_bytes_preserved(self):
        data = bytearray(_make_palette_bytes())
        data[768:1024] = bytes(range(256))
        pal = U6Palette.parse(bytes(data))
        self.assertEqual(pal.trailing, bytes(range(256)))


class RoundTripTests(unittest.TestCase):
    def test_to_flat_rgb_matches_colors(self):
        pal = U6Palette.parse(_make_palette_bytes({5: (10, 20, 30)}))
        flat = pal.to_flat_rgb()
        self.assertEqual(len(flat), 768)
        self.assertEqual(tuple(flat[15:18]), pal.colors[5])

    def test_to_pil_image_size(self):
        pal = U6Palette.parse(_make_palette_bytes())
        img = pal.to_pil_image(swatch_size=4)
        self.assertEqual(img.size, (64, 64))


if __name__ == "__main__":
    unittest.main()
