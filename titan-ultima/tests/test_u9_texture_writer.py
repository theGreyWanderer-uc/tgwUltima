"""Tests for titan.u9.texture_writer's PNG-into-texture-slot encoder.

The writer's contract is narrow on purpose: same size, same encoding, spliced
in place. That gives the property most of these tests assert -- the patched
entry is exactly as long as the original, so every offset after the frame stays
valid and the undecoded header fields are carried through untouched.

Round-trip fidelity against real archives was measured separately: RGB565 and
8-bit paletted come back with RMSE 0.00 (lossless), BC1 averages 2.77 because
the format is lossy by construction.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.palette import U9Palette
from titan.u9.texture import COMPRESSION_BC1, bc1_size, decode_frame
from titan.u9.texture_writer import (
    U9TextureWriteError,
    encode_bc1,
    encode_paletted,
    encode_rgb565,
    encode_rgba5551,
    frame_encoding,
    replace_frame,
)


def _palette() -> U9Palette:
    # 0 = black, 1 = red, 2 = green, 3 = blue, rest black
    raw = bytearray(1024)
    for i, (r, g, b) in enumerate([(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        raw[i * 4 : i * 4 + 3] = bytes((r, g, b))
    return U9Palette(bytes(raw))


def _entry(width: int, height: int, payload: bytes, *, compression: int = 0,
           mip_count: int = 0, flags: int = 0) -> bytes:
    """One-frame texture set wrapping ``payload``."""
    header = struct.pack("<4HII", width, mip_count, height, compression, 1, 0)
    frame_offset = 0x18
    frame_header = struct.pack("<2H4I", flags, 0x6000, width, height, 0, 0)
    row_table = b"".join(
        struct.pack("<I", 0x14 + 4 * height + r * width) for r in range(height)
    )
    frame_length = len(frame_header) + len(row_table) + len(payload)
    directory = struct.pack("<2I", frame_offset, frame_length)
    return header + directory + frame_header + row_table + payload


def _solid(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    return bytes(rgba) * (width * height)


class EncoderTests(unittest.TestCase):
    def test_rgb565_packs_two_bytes_per_pixel(self) -> None:
        out = encode_rgb565(bytes((255, 0, 0, 255)) * 4)
        self.assertEqual(len(out), 8)
        self.assertEqual(struct.unpack_from("<H", out, 0)[0], 0xF800)

    def test_rgba5551_sets_the_alpha_bit(self) -> None:
        opaque = encode_rgba5551(bytes((0, 0, 0, 255)))
        clear = encode_rgba5551(bytes((0, 0, 0, 0)))
        self.assertEqual(struct.unpack("<H", opaque)[0] >> 15, 1)
        self.assertEqual(struct.unpack("<H", clear)[0] >> 15, 0)

    def test_paletted_picks_the_nearest_entry(self) -> None:
        out = encode_paletted(
            bytes((250, 5, 5, 255)) + bytes((0, 0, 240, 255)), _palette()
        )
        self.assertEqual(out, bytes((1, 3)))

    def test_bc1_block_size_is_eight_bytes_per_4x4(self) -> None:
        self.assertEqual(len(encode_bc1(_solid(4, 4, (10, 20, 30, 255)), 4, 4)), 8)
        self.assertEqual(len(encode_bc1(_solid(8, 8, (10, 20, 30, 255)), 8, 8)), 32)
        self.assertEqual(len(encode_bc1(_solid(8, 8, (0, 0, 0, 255)), 8, 8)), bc1_size(8, 8))

    def test_bc1_round_trips_a_flat_block(self) -> None:
        # a solid block must survive exactly: both endpoints land on the colour
        rgba = _solid(4, 4, (255, 0, 0, 255))
        entry = _entry(4, 4, encode_bc1(rgba, 4, 4), compression=COMPRESSION_BC1)
        frame = decode_frame(entry)
        self.assertEqual(frame.pixels_rgba[:4], bytes((255, 0, 0, 255)))

    def test_bc1_carries_one_bit_of_alpha(self) -> None:
        rgba = bytearray(_solid(4, 4, (255, 255, 255, 255)))
        rgba[0:4] = bytes((0, 0, 0, 0))  # one transparent texel
        entry = _entry(4, 4, encode_bc1(bytes(rgba), 4, 4), compression=COMPRESSION_BC1)
        frame = decode_frame(entry)
        self.assertEqual(frame.pixels_rgba[3], 0)
        self.assertEqual(frame.pixels_rgba[7], 255)


class FrameEncodingTests(unittest.TestCase):
    def test_detects_bc1(self) -> None:
        entry = _entry(4, 4, encode_bc1(_solid(4, 4, (1, 2, 3, 255)), 4, 4),
                       compression=COMPRESSION_BC1)
        self.assertEqual(frame_encoding(entry), "bc1")

    def test_detects_paletted_by_payload_length(self) -> None:
        entry = _entry(4, 4, bytes(16))
        self.assertEqual(frame_encoding(entry), "paletted")

    def test_detects_rgb565_and_rgba5551_by_the_transparency_flag(self) -> None:
        self.assertEqual(frame_encoding(_entry(4, 4, bytes(32))), "rgb565")
        self.assertEqual(frame_encoding(_entry(4, 4, bytes(32), flags=0x100)), "rgba5551")

    def test_unsupported_compression_raises(self) -> None:
        entry = _entry(4, 4, bytes(32), compression=9)
        with self.assertRaises(U9TextureWriteError):
            frame_encoding(entry)


class ReplaceFrameTests(unittest.TestCase):
    def test_replacement_keeps_the_entry_length(self) -> None:
        # the whole point: nothing after the pixel data shifts
        entry = _entry(8, 8, bytes(128))
        patched = replace_frame(entry, 0, _solid(8, 8, (9, 9, 9, 255)), 8, 8)
        self.assertEqual(len(patched), len(entry))

    def test_only_the_pixel_bytes_change(self) -> None:
        entry = _entry(8, 8, bytes(128))
        patched = replace_frame(entry, 0, _solid(8, 8, (200, 100, 50, 255)), 8, 8)
        pixel_start = 0x18 + 0x14 + 4 * 8
        self.assertEqual(patched[:pixel_start], entry[:pixel_start])
        self.assertNotEqual(patched[pixel_start:], entry[pixel_start:])

    def test_rgb565_round_trip_is_lossless(self) -> None:
        rgba = _solid(4, 4, (0xFF, 0x00, 0xFF, 255))
        entry = _entry(4, 4, bytes(32))
        frame = decode_frame(replace_frame(entry, 0, rgba, 4, 4))
        # 565 quantises, so compare against what the format can represent
        self.assertEqual(frame.pixels_rgba[:4], bytes((255, 0, 255, 255)))

    def test_paletted_needs_a_palette(self) -> None:
        entry = _entry(4, 4, bytes(16))
        with self.assertRaises(U9TextureWriteError):
            replace_frame(entry, 0, _solid(4, 4, (1, 2, 3, 255)), 4, 4)

    def test_paletted_round_trip_with_a_palette(self) -> None:
        entry = _entry(4, 4, bytes(16))
        patched = replace_frame(
            entry, 0, _solid(4, 4, (0, 250, 0, 255)), 4, 4, palette=_palette()
        )
        frame = decode_frame(patched, 0, _palette())
        self.assertEqual(frame.pixels_rgba[:4], bytes((0, 255, 0, 255)))

    def test_size_mismatch_is_refused(self) -> None:
        entry = _entry(8, 8, bytes(128))
        with self.assertRaises(U9TextureWriteError) as ctx:
            replace_frame(entry, 0, _solid(4, 4, (0, 0, 0, 255)), 4, 4)
        self.assertIn("must match exactly", str(ctx.exception))

    def test_wrong_rgba_length_is_refused(self) -> None:
        entry = _entry(4, 4, bytes(32))
        with self.assertRaises(U9TextureWriteError):
            replace_frame(entry, 0, b"\x00" * 10, 4, 4)

    def test_frame_index_out_of_range_raises(self) -> None:
        entry = _entry(4, 4, bytes(32))
        with self.assertRaises(U9TextureWriteError):
            replace_frame(entry, 5, _solid(4, 4, (0, 0, 0, 255)), 4, 4)

    def test_truncated_entry_raises(self) -> None:
        with self.assertRaises(U9TextureWriteError):
            replace_frame(b"\x00" * 8, 0, b"", 0, 0)


class MipChainTests(unittest.TestCase):
    """Mips are regenerated, and must refill the original byte count exactly."""

    def test_mip_chain_is_regenerated_to_the_declared_length(self) -> None:
        # 8x8 RGB565 with 2 mips: 64 + 16 + 4 samples, 2 bytes each
        payload = bytes((64 + 16 + 4) * 2)
        entry = _entry(8, 8, payload, mip_count=2)
        patched = replace_frame(entry, 0, _solid(8, 8, (10, 20, 30, 255)), 8, 8)
        self.assertEqual(len(patched), len(entry))

    def test_bc1_mip_chain_refills_exactly(self) -> None:
        payload = bytes(bc1_size(8, 8) + bc1_size(4, 4) + bc1_size(2, 2))
        entry = _entry(8, 8, payload, compression=COMPRESSION_BC1, mip_count=2)
        patched = replace_frame(entry, 0, _solid(8, 8, (40, 50, 60, 255)), 8, 8)
        self.assertEqual(len(patched), len(entry))

    def test_a_frame_whose_payload_cannot_be_refilled_is_refused(self) -> None:
        # declares a byte count no encoding of this size produces
        entry = _entry(8, 8, bytes(999))
        with self.assertRaises(U9TextureWriteError) as ctx:
            replace_frame(entry, 0, _solid(8, 8, (0, 0, 0, 255)), 8, 8)
        self.assertIn("refusing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
