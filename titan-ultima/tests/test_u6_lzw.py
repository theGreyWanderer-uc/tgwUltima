"""Tests for titan.u6.lzw's variable-width LZW decoder.

No real game files are used here -- fixtures are hand-encoded with a
minimal from-scratch encoder that emits a CLEAR code before every <=64
byte chunk (the same recipe u6data/u6tech.txt describes as a valid way
to produce U6-readable LZW data): since each chunk only adds up to 64
dictionary entries on top of the 0x102 baseline, the codeword width
never needs to grow past 9 bits, keeping the encoder itself trivial to
verify by inspection. Round-tripping through this encoder exercises the
decoder's CLEAR/END handling and per-code dictionary bookkeeping without
needing an original compressed U6 asset on disk.
"""

from __future__ import annotations

import unittest

from titan.u6.lzw import U6Lzw, U6LzwError

CLEAR_CODE = 0x100
END_CODE = 0x101
CODE_SIZE = 9
CHUNK_SIZE = 64


def _pack_codes(codes: list[int], code_size: int = CODE_SIZE) -> bytes:
    bitbuf = 0
    bitcount = 0
    out = bytearray()
    for code in codes:
        bitbuf |= (code & ((1 << code_size) - 1)) << bitcount
        bitcount += code_size
        while bitcount >= 8:
            out.append(bitbuf & 0xFF)
            bitbuf >>= 8
            bitcount -= 8
    if bitcount:
        out.append(bitbuf & 0xFF)
    return bytes(out)


def _encode(data: bytes) -> bytes:
    codes: list[int] = []
    if not data:
        codes.append(CLEAR_CODE)  # a valid stream always opens with CLEAR, even when empty
    for start in range(0, len(data), CHUNK_SIZE):
        codes.append(CLEAR_CODE)
        codes.extend(data[start:start + CHUNK_SIZE])
    codes.append(END_CODE)
    header = len(data).to_bytes(4, "little")
    return header + _pack_codes(codes)


class RoundTripTests(unittest.TestCase):
    def test_empty_input(self):
        encoded = _encode(b"")
        self.assertEqual(U6Lzw.decompress_buffer(encoded), b"")

    def test_short_message_round_trips(self):
        message = b"Thou dost see a mouse."
        encoded = _encode(message)
        self.assertEqual(U6Lzw.decompress_buffer(encoded), message)

    def test_multi_chunk_message_round_trips(self):
        message = bytes(range(256)) * 3  # forces multiple 64-byte chunks
        encoded = _encode(message)
        self.assertEqual(U6Lzw.decompress_buffer(encoded), message)

    def test_decompress_dispatches_to_decompress_buffer(self):
        message = b"BluGlo"
        encoded = _encode(message)
        self.assertEqual(U6Lzw.decompress(encoded), message)

    def test_decompress_passes_through_non_lzw_data_unchanged(self):
        # Real U6 files that aren't compressed (e.g. ANIMDATA) are raw,
        # headerless structs -- verified against an actual ANIMDATA from a
        # GOG-style install (194 bytes, matching its documented struct
        # exactly with no wrapper of any kind).
        payload = b"\x1d\x00\x08\x00\x09\x00\x0a\x00not a clear code"
        self.assertEqual(U6Lzw.decompress(payload), payload)


class ValidationTests(unittest.TestCase):
    def test_is_valid_true_for_encoded_buffer(self):
        self.assertTrue(U6Lzw.is_valid(_encode(b"hello")))

    def test_is_valid_false_for_short_buffer(self):
        self.assertFalse(U6Lzw.is_valid(b"\x00\x00\x00"))

    def test_is_valid_false_when_size_header_too_large(self):
        bad = bytes([0, 0, 0, 1]) + b"\x00\x01"
        self.assertFalse(U6Lzw.is_valid(bad))

    def test_uncompressed_size_matches_header(self):
        message = b"a" * 130
        encoded = _encode(message)
        self.assertEqual(U6Lzw.uncompressed_size(encoded), 130)

    def test_uncompressed_size_raises_on_invalid_buffer(self):
        with self.assertRaises(U6LzwError):
            U6Lzw.uncompressed_size(b"not lzw!")


if __name__ == "__main__":
    unittest.main()
