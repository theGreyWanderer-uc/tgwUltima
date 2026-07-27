"""Tests for titan.u9.microtalk's EA MicroTalk (UTK) speech decoder.

The full multipulse/RELP CELP decode pipeline is genuinely hard to
hand-construct valid bitstreams for (variable-length entropy-coded
excitation, recursive LPC synthesis state) -- so the one deep case
tested here by hand is an all-zero-byte payload. Tracing the algorithm
confirms this is a legitimate, fully-decodable bitstream (multipulse
mode, codebook[NORMAL][0] always selects the "insert one 0.0 pulse"
command since peek_bits(8) is always 0), and since excitation and the
initial adaptive-codebook/synthesis-history state are all zero, every
stage of the pipeline (excitation decode, pitch prediction, LPC
synthesis filter) reduces to the identity 0 -> 0 regardless of what the
derived LPC coefficients or gains happen to be -- giving an unambiguous,
fully hand-verifiable "silence in, silence out" trace through the
entire decoder.

The real, entropy-coded case is validated separately against real game
data, not synthetic fixtures here: see titan.u9.microtalk's module
docstring for the real-data validation (104 known-good compressed
payload -> WAV pairs from Speech.flx, matching to within +/-1 LSB on
99.7% of samples -- see that docstring for why exact bit-identity isn't
expected).
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.microtalk import FRAME_SAMPLES, MicroTalkDecodeError, decode_mono


class DecodeMonoSilenceTests(unittest.TestCase):
    """An all-zero-byte bitstream decodes cleanly to all-zero PCM -- see module docstring."""

    def test_single_frame_of_zero_bytes_decodes_to_silence(self) -> None:
        payload = struct.pack("<I", FRAME_SAMPLES) + b"\x00" * 200
        pcm = decode_mono(payload)
        self.assertEqual(pcm, b"\x00" * (FRAME_SAMPLES * 2))

    def test_multi_frame_zero_bytes_decodes_to_silence(self) -> None:
        total_samples = FRAME_SAMPLES * 2 + 50  # spans a partial third frame
        payload = struct.pack("<I", total_samples) + b"\x00" * 600
        pcm = decode_mono(payload)
        self.assertEqual(pcm, b"\x00" * (total_samples * 2))

    def test_zero_total_samples_returns_empty_bytes(self) -> None:
        payload = struct.pack("<I", 0) + b"\x00" * 50
        self.assertEqual(decode_mono(payload), b"")

    def test_final_frame_is_trimmed_to_total_samples(self) -> None:
        # not a multiple of FRAME_SAMPLES -- output must be trimmed, not padded to a frame boundary.
        total_samples = 50
        payload = struct.pack("<I", total_samples) + b"\x00" * 200
        pcm = decode_mono(payload)
        self.assertEqual(len(pcm), total_samples * 2)


class DecodeMonoEdgeCaseTests(unittest.TestCase):
    def test_payload_too_small_for_sample_count_field_raises(self) -> None:
        with self.assertRaises(MicroTalkDecodeError):
            decode_mono(b"\x01\x02\x03")  # only 3 bytes, need >= 4

    def test_empty_payload_raises(self) -> None:
        with self.assertRaises(MicroTalkDecodeError):
            decode_mono(b"")


if __name__ == "__main__":
    unittest.main()
