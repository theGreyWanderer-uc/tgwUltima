"""Tests for titan.u9.texture's bitmap FLX texture decoder.

Fixtures are hand-built minimal texture-set entries (no mip chain,
1-2 pixels) so the exact expected RGBA bytes can be computed by hand
from the known 565/5551/monochrome bit layouts -- see each test's
comment for the arithmetic. Broader validation against real game
archives (correct dimensions, and a visually-confirmed "default"
placeholder texture, a fire sprite with correct alpha, and a
grayscale variant) is cited in the module docstring, not repeated here
as synthetic fixtures.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.palette import U9Palette
from titan.u9.texture import U9TextureError, decode_frame

TEXTURE_SET_HEADER_SIZE = 0x10
FRAME_HEADER_SIZE = 0x14


def _build_entry(width: int, height: int, mip_count: int, unknown1: int, pixel_bytes: bytes) -> bytes:
    frame_header = struct.pack("<HH", unknown1, 0x6000) + struct.pack("<IIII", width, height, 0, 0)
    frame_header += b"\x00" * (4 * height)  # row-offset table, unused by the decoder
    frame_data = frame_header + pixel_bytes

    frame_count = 1
    frame_offset = TEXTURE_SET_HEADER_SIZE + frame_count * 8  # directly follows the frame directory
    frame_dir = struct.pack("<II", frame_offset, len(frame_data))
    header = struct.pack("<HHHH", width, mip_count, height, 0) + struct.pack("<II", frame_count, 0)
    return header + frame_dir + frame_data


class DecodeFrame565Tests(unittest.TestCase):
    def test_pure_red_green_blue_pixels(self) -> None:
        # 565: bits [15:11]=R(5), [10:5]=G(6), [4:0]=B(5). unknown1 bit 8 = 0 -> not transparent -> 565 path.
        red = 0b1111100000000000  # R=31
        green = 0b0000011111100000  # G=63
        blue = 0b0000000000011111  # B=31
        pixels = struct.pack("<3H", red, green, blue)
        entry = _build_entry(width=3, height=1, mip_count=0, unknown1=0x0000, pixel_bytes=pixels)

        frame = decode_frame(entry)
        self.assertFalse(frame.is_transparent)
        self.assertEqual(frame.width, 3)
        self.assertEqual(frame.height, 1)
        self.assertEqual(
            frame.pixels_rgba,
            bytes([255, 0, 0, 255]) + bytes([0, 255, 0, 255]) + bytes([0, 0, 255, 255]),
        )


class DecodeFrame5551Tests(unittest.TestCase):
    def test_alpha_bit_and_color_channels(self) -> None:
        # 5551: bit 15 = alpha, bits [14:10]=R(5), [9:5]=G(5), [4:0]=B(5).
        # unknown1 bit 8 = 1 -> transparent -> 5551 path.
        opaque_red = 0b1_11111_00000_00000  # a=1, R=31
        transparent_blue = 0b0_00000_00000_11111  # a=0, B=31
        pixels = struct.pack("<2H", opaque_red, transparent_blue)
        entry = _build_entry(width=2, height=1, mip_count=0, unknown1=0x0100, pixel_bytes=pixels)

        frame = decode_frame(entry)
        self.assertTrue(frame.is_transparent)
        self.assertEqual(frame.pixels_rgba, bytes([255, 0, 0, 255]) + bytes([0, 0, 255, 0]))


class DecodeFrameMonochromeTests(unittest.TestCase):
    def test_single_byte_becomes_gray_opaque_pixel(self) -> None:
        # is_8bit is inferred: frame_length - header_size must equal width*height exactly (1 byte/pixel).
        pixels = bytes([128])
        entry = _build_entry(width=1, height=1, mip_count=0, unknown1=0x0000, pixel_bytes=pixels)

        frame = decode_frame(entry)
        self.assertEqual(frame.pixels_rgba, bytes([128, 128, 128, 255]))


class DecodeFramePalettedTests(unittest.TestCase):
    def test_byte_used_as_palette_index_when_palette_given(self) -> None:
        # same is_8bit fixture as the grayscale test above, but with a palette this
        # time -- the raw byte (128) must be used as an *index*, not an intensity.
        palette_data = bytearray(256 * 4)
        palette_data[128 * 4 : 128 * 4 + 4] = bytes([200, 100, 50, 0])  # index 128 -> a distinct color
        palette = U9Palette(bytes(palette_data))

        pixels = bytes([128])
        entry = _build_entry(width=1, height=1, mip_count=0, unknown1=0x0000, pixel_bytes=pixels)

        frame = decode_frame(entry, palette=palette)
        self.assertEqual(frame.pixels_rgba, bytes([200, 100, 50, 255]))

    def test_no_palette_falls_back_to_grayscale(self) -> None:
        pixels = bytes([64])
        entry = _build_entry(width=1, height=1, mip_count=0, unknown1=0x0000, pixel_bytes=pixels)

        frame = decode_frame(entry)
        self.assertEqual(frame.pixels_rgba, bytes([64, 64, 64, 255]))


class DecodeFrameEdgeCaseTests(unittest.TestCase):
    def test_frame_index_out_of_range_raises(self) -> None:
        entry = _build_entry(width=1, height=1, mip_count=0, unknown1=0, pixel_bytes=bytes([0, 0]))
        with self.assertRaises(U9TextureError):
            decode_frame(entry, frame_index=5)

    def test_too_small_entry_raises(self) -> None:
        with self.assertRaises(U9TextureError):
            decode_frame(b"\x00" * 4)

    def test_nonzero_compression_raises_instead_of_misdecoding(self) -> None:
        # real bitmapC.flx entries with compression=1 are not raw pixel data at all;
        # decoding them as if they were would silently produce garbage on some sizes
        # (confirmed against real data -- see module docstring) rather than erroring,
        # so compression is checked explicitly instead of inferred from buffer size.
        entry = bytearray(_build_entry(width=1, height=1, mip_count=0, unknown1=0, pixel_bytes=bytes([0, 0])))
        struct.pack_into("<H", entry, 0x06, 1)  # set compression = 1
        with self.assertRaises(U9TextureError):
            decode_frame(bytes(entry))


class TruncatedPixelDataRegressionTests(unittest.TestCase):
    """8-bit frames must not leak IndexError past the U9TextureError contract.

    The 8-bit decode paths index bytes directly rather than going through
    ``struct.unpack_from``, so a short buffer raised a bare ``IndexError``
    while the 16-bit paths raised ``U9TextureError``. ``bitmapsh.flx`` is
    entirely 8-bit, so this was the common path: a caller catching
    ``U9TextureError`` to skip a bad entry crashed instead.
    """

    @staticmethod
    def _entry(width: int, height: int, payload: bytes, declared_length: int) -> bytes:
        return (
            struct.pack("<4HII", width, 0, height, 0, 1, 0)
            + struct.pack("<2I", 0x18, declared_length)
            + struct.pack("<2H4I", 0, 0x6000, width, height, 0, 0)
            + b"\x00" * (4 * height)
            + payload
        )

    def _truncated_8bit(self) -> bytes:
        # declares a full 8-bit frame, supplies half the pixels
        width = height = 4
        declared = 0x14 + 4 * height + width * height
        return self._entry(width, height, b"\x01" * (width * height // 2), declared)

    def test_truncated_8bit_without_palette_raises_texture_error(self) -> None:
        with self.assertRaises(U9TextureError):
            decode_frame(self._truncated_8bit())

    def test_truncated_8bit_with_palette_raises_texture_error(self) -> None:
        with self.assertRaises(U9TextureError):
            decode_frame(self._truncated_8bit(), 0, U9Palette(bytes(1024)))

    def test_truncated_16bit_still_raises_texture_error(self) -> None:
        width = height = 4
        declared = 0x14 + 4 * height + width * height * 2
        entry = self._entry(width, height, b"\x01" * (width * height), declared)
        with self.assertRaises(U9TextureError):
            decode_frame(entry)

    def test_complete_8bit_frame_still_decodes(self) -> None:
        width = height = 2
        declared = 0x14 + 4 * height + width * height
        entry = self._entry(width, height, b"\x7f" * (width * height), declared)
        frame = decode_frame(entry)
        self.assertEqual((frame.width, frame.height), (2, 2))
        self.assertEqual(len(frame.pixels_rgba), 2 * 2 * 4)
        self.assertEqual(frame.pixels_rgba[:4], b"\x7f\x7f\x7f\xff")


if __name__ == "__main__":
    unittest.main()
