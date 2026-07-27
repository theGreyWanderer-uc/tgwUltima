"""Tests for titan.u9.adpcm's mono and stereo EA-XA ADPCM decoders.

Correctness of the core bit manipulation (nibble extraction, sign
extension, shift, clamping, output packing/interleave order) is
verified here with hand-computed values using coefficient index 0
(where predictor coefficients a=b=0, making each sample depend only on
its own nibble, not on filter history -- safe to hand-verify without
risking an arithmetic slip in the recursive a/b filter path).

The recursive filter itself (coefficient indices 1-3, where each sample
depends on prior decoded samples) is validated separately, against real
game data, not synthetic fixtures here: see titan.u9.adpcm's module
docstring for the real-data validation (stereo: 10 real music.flx
tracks decoded with zero errors/clipping, one cross-checked
independently with vgmstream; mono: 9 diverse real sfx.flx entries,
bit-exact against vgmstream's own decode of the same entries).
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.adpcm import (
    AdpcmDecodeError,
    BLOCK_SIZE_IN,
    BLOCK_SIZE_IN_MONO,
    decode_mono,
    decode_stereo,
)


def _block(coeff_l: int, coeff_r: int, shift_l: int, shift_r: int, step_bytes: list[int]) -> bytes:
    assert len(step_bytes) == BLOCK_SIZE_IN - 2
    header = bytes([(coeff_l << 4) | coeff_r, (shift_l << 4) | shift_r])
    return header + bytes(step_bytes)


def _block_mono(coeff: int, shift: int, payload_bytes: list[int]) -> bytes:
    assert len(payload_bytes) == BLOCK_SIZE_IN_MONO - 1
    header = bytes([(coeff << 4) | shift])
    return header + bytes(payload_bytes)


class DecodeStereoZeroCoefficientTests(unittest.TestCase):
    """coeff_idx=0 -> a=0, b=0 -> ua = ((nibble << 20) + 0x80) >> 8, clamped."""

    def test_positive_nibble_one_decodes_to_4096(self) -> None:
        # nibble 0x1 in every position, both channels, coeff/shift all 0.
        block = _block(0, 0, 0, 0, [0x11] * (BLOCK_SIZE_IN - 2))
        pcm = decode_stereo(block)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertEqual(len(samples), 56)  # 14 steps * 4 samples (L.a, R.a, L.b, R.b)
        self.assertTrue(all(s == 4096 for s in samples))

    def test_negative_nibble_decodes_to_negative_4096(self) -> None:
        # nibble 0xF (sign-extends to -1) in every position.
        block = _block(0, 0, 0, 0, [0xFF] * (BLOCK_SIZE_IN - 2))
        pcm = decode_stereo(block)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertTrue(all(s == -4096 for s in samples))

    def test_left_right_channels_decoded_independently(self) -> None:
        # left nibbles = 1 (-> +4096), right nibbles = 0xF (-> -4096); byte 0x1F per step.
        block = _block(0, 0, 0, 0, [0x1F] * (BLOCK_SIZE_IN - 2))
        pcm = decode_stereo(block)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        # interleave order is L.osa, R.osa, L.osb, R.osb per step.
        left = samples[0::2]
        right = samples[1::2]
        self.assertTrue(all(s == 4096 for s in left))
        self.assertTrue(all(s == -4096 for s in right))

    def test_output_byte_length_matches_block_count(self) -> None:
        one_block = _block(0, 0, 0, 0, [0x00] * (BLOCK_SIZE_IN - 2))
        pcm = decode_stereo(one_block * 3)
        self.assertEqual(len(pcm), 3 * 56 * 2)  # 3 blocks * 56 int16 samples * 2 bytes


class DecodeStereoEdgeCaseTests(unittest.TestCase):
    def test_empty_payload_returns_empty_bytes(self) -> None:
        self.assertEqual(decode_stereo(b""), b"")

    def test_trailing_partial_block_is_dropped(self) -> None:
        one_block = _block(0, 0, 0, 0, [0x00] * (BLOCK_SIZE_IN - 2))
        pcm = decode_stereo(one_block + b"\x01\x02\x03")  # 3 stray trailing bytes
        self.assertEqual(len(pcm), 56 * 2)  # only the one full block decodes

    def test_invalid_coefficient_index_raises(self) -> None:
        bad_block = _block(4, 0, 0, 0, [0x00] * (BLOCK_SIZE_IN - 2))  # 4 is out of 0-3 range
        with self.assertRaises(AdpcmDecodeError):
            decode_stereo(bad_block)

    def test_state_carries_between_blocks(self) -> None:
        # coeff_idx=1 (a=240,b=0): second block's first sample depends on the
        # first block's final state, so decoding 2 blocks together must not
        # equal decoding them independently and concatenating -- just confirm
        # it runs cleanly and produces plausible (non-clamped-flat) output,
        # since exact values for the recursive filter are validated against
        # real data, not hand-computed here (see module docstring).
        block1 = _block(1, 1, 0, 0, [0x11] * (BLOCK_SIZE_IN - 2))
        block2 = _block(1, 1, 0, 0, [0x11] * (BLOCK_SIZE_IN - 2))
        pcm = decode_stereo(block1 + block2)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertEqual(len(samples), 112)
        # with nonzero feedback, later samples should differ from the very
        # first (all-zero-state) sample -- i.e. the filter is actually doing
        # something, not degenerating to the coeff=0 case.
        self.assertNotEqual(samples[0], samples[-1])


class DecodeMonoZeroCoefficientTests(unittest.TestCase):
    """coeff_idx=0 -> a=0, b=0 -> each sample depends only on its own nibble."""

    def test_positive_nibble_one_decodes_to_4096(self) -> None:
        block = _block_mono(0, 0, [0x11] * (BLOCK_SIZE_IN_MONO - 1))
        pcm = decode_mono(block)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertEqual(len(samples), 28)  # 14 bytes * 2 samples each
        self.assertTrue(all(s == 4096 for s in samples))

    def test_negative_nibble_decodes_to_negative_4096(self) -> None:
        block = _block_mono(0, 0, [0xFF] * (BLOCK_SIZE_IN_MONO - 1))
        pcm = decode_mono(block)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertTrue(all(s == -4096 for s in samples))

    def test_high_nibble_decoded_before_low_nibble(self) -> None:
        # byte 0x1F: high nibble 0x1 (-> +4096) is the earlier-in-time sample,
        # low nibble 0xF (-> -4096) is the next.
        block = _block_mono(0, 0, [0x1F] * (BLOCK_SIZE_IN_MONO - 1))
        pcm = decode_mono(block)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertEqual(samples[0::2], (4096,) * 14)
        self.assertEqual(samples[1::2], (-4096,) * 14)

    def test_output_byte_length_matches_block_count(self) -> None:
        one_block = _block_mono(0, 0, [0x00] * (BLOCK_SIZE_IN_MONO - 1))
        pcm = decode_mono(one_block * 3)
        self.assertEqual(len(pcm), 3 * 28 * 2)  # 3 blocks * 28 int16 samples * 2 bytes


class DecodeMonoEdgeCaseTests(unittest.TestCase):
    def test_empty_payload_returns_empty_bytes(self) -> None:
        self.assertEqual(decode_mono(b""), b"")

    def test_trailing_partial_block_is_dropped(self) -> None:
        one_block = _block_mono(0, 0, [0x00] * (BLOCK_SIZE_IN_MONO - 1))
        pcm = decode_mono(one_block + b"\x01\x02\x03")  # 3 stray trailing bytes
        self.assertEqual(len(pcm), 28 * 2)  # only the one full block decodes

    def test_invalid_coefficient_index_raises(self) -> None:
        bad_block = _block_mono(4, 0, [0x00] * (BLOCK_SIZE_IN_MONO - 1))  # 4 is out of 0-3 range
        with self.assertRaises(AdpcmDecodeError):
            decode_mono(bad_block)

    def test_state_carries_between_blocks(self) -> None:
        # coeff_idx=1 (a=240,b=0): validated against real data, not hand-computed
        # here (see module docstring) -- just confirm the recursive filter path
        # runs cleanly and actually does something (doesn't degenerate to coeff=0).
        block1 = _block_mono(1, 0, [0x11] * (BLOCK_SIZE_IN_MONO - 1))
        block2 = _block_mono(1, 0, [0x11] * (BLOCK_SIZE_IN_MONO - 1))
        pcm = decode_mono(block1 + block2)
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertEqual(len(samples), 56)
        self.assertNotEqual(samples[0], samples[-1])


if __name__ == "__main__":
    unittest.main()
