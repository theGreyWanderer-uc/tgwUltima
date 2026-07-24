"""Tests for titan.u6.font's U6.CH glyph decoder.

No real game files are used here -- fixtures are hand-built to match the
confirmed layout (2048 bytes = two 128-glyph, 8-bytes-per-glyph fonts),
ported from and validated against Nuvie's FontManager.cpp/U6Font.cpp.
See titan/u6/font.py's module docstring for the real-data validation:
the English and runic/gargoyle halves decode to visibly different glyph
shapes, and rendered sample text is legible in both.
"""

from __future__ import annotations

import unittest

from titan.u6.font import FILE_SIZE, FONT_BYTES, GLYPH_DIM, U6Font, U6FontError, U6Fonts


def _make_glyph_bytes(rows: list[int]) -> bytes:
    """rows: 8 bytes, each an 8-bit MSB-first row pattern."""
    assert len(rows) == GLYPH_DIM
    return bytes(rows)


class GlyphDecodeTests(unittest.TestCase):
    def test_all_zero_glyph_is_blank(self):
        data = bytes(FONT_BYTES)
        font = U6Font(data)
        arr = font.glyph_array(0)
        self.assertEqual(arr.shape, (8, 8))
        self.assertEqual(arr.sum(), 0)

    def test_msb_first_bit_order(self):
        # Row 0 = 0b10000000 -> only column 0 set.
        glyph = _make_glyph_bytes([0b10000000] + [0] * 7)
        data = glyph + bytes(FONT_BYTES - len(glyph))
        font = U6Font(data)
        arr = font.glyph_array(0)
        self.assertEqual(arr[0, 0], 1)
        self.assertEqual(arr[0, 1:].sum(), 0)

    def test_lsb_of_row_is_last_column(self):
        glyph = _make_glyph_bytes([0b00000001] + [0] * 7)
        data = glyph + bytes(FONT_BYTES - len(glyph))
        font = U6Font(data)
        arr = font.glyph_array(0)
        self.assertEqual(arr[0, 7], 1)
        self.assertEqual(arr[0, :7].sum(), 0)

    def test_second_glyph_reads_from_correct_offset(self):
        glyph0 = _make_glyph_bytes([0xFF] * 8)
        glyph1 = _make_glyph_bytes([0x00] * 8)
        data = glyph0 + glyph1 + bytes(FONT_BYTES - 16)
        font = U6Font(data)
        self.assertEqual(font.glyph_array(0).sum(), 64)
        self.assertEqual(font.glyph_array(1).sum(), 0)

    def test_out_of_range_char_code_raises(self):
        font = U6Font(bytes(FONT_BYTES))
        with self.assertRaises(U6FontError):
            font.glyph_array(128)

    def test_rejects_short_data(self):
        with self.assertRaises(U6FontError):
            U6Font(bytes(100))


class RenderingTests(unittest.TestCase):
    def setUp(self):
        glyph_a = _make_glyph_bytes([0xFF] * 8)  # char 'A' = 0x41
        data = bytearray(FONT_BYTES)
        data[ord("A") * 8: ord("A") * 8 + 8] = glyph_a
        self.font = U6Font(bytes(data))

    def test_to_pil_image_transparent_background(self):
        img = self.font.to_pil_image(ord("A"))
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(img.size, (8, 8))

    def test_to_pil_image_opaque_background(self):
        img = self.font.to_pil_image(ord("A"), bg=(0, 0, 0))
        self.assertEqual(img.mode, "RGB")

    def test_render_text_width_matches_string_length(self):
        img = self.font.render_text("AAA")
        self.assertEqual(img.size, (24, 8))

    def test_render_text_scale(self):
        img = self.font.render_text("A", scale=3)
        self.assertEqual(img.size, (24, 24))

    def test_contact_sheet_dimensions(self):
        sheet = self.font.to_contact_sheet(cols=16, scale=1)
        self.assertEqual(sheet.size, (16 * 8, 8 * 8))


class U6FontsTests(unittest.TestCase):
    def test_splits_into_two_fonts(self):
        english_marker = _make_glyph_bytes([0xAA] * 8)
        runic_marker = _make_glyph_bytes([0x55] * 8)
        data = bytearray(FILE_SIZE)
        data[0:8] = english_marker
        data[FONT_BYTES:FONT_BYTES + 8] = runic_marker
        fonts = U6Fonts.parse(bytes(data))
        self.assertEqual(fonts.english.glyph_array(0)[0, 0], 1)  # 0xAA = 10101010
        self.assertEqual(fonts.runic.glyph_array(0)[0, 0], 0)   # 0x55 = 01010101

    def test_rejects_short_data(self):
        with self.assertRaises(U6FontError):
            U6Fonts.parse(bytes(100))


if __name__ == "__main__":
    unittest.main()
