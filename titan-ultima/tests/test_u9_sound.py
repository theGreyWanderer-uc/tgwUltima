"""Tests for titan.u9.sound's sound/*.flx record header decoder.

Fixtures are hand-built to match the corrected byte layout, validated
against real Speech.flx/sfx.flx/music.flx data (see titan.u9.sound's
module docstring): a 0x3C-byte header, with a 36-byte description field
(0x04..0x28) immediately followed by data_length at 0x28 -- not the
20-byte field a prior draft script used, which silently truncated any
description longer than 20 characters into what that draft treated as
an unexplained reserved gap.
"""

from __future__ import annotations

import struct
import unittest
import wave
import io

from titan.u9.sound import (
    ENCODING_ADPCM,
    ENCODING_EA_MICROTALK,
    ENCODING_PCM,
    U9SoundRecord,
    U9SoundRecordError,
)

HEADER_SIZE = 0x3C


def _build_record(
    sound_id: int,
    description: str,
    frequency: int,
    bits_per_sample: int,
    num_channels: int,
    encoding_type: int,
    payload: bytes,
) -> bytes:
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<I", header, 0x00, sound_id)
    desc_bytes = description.encode("ascii")
    assert len(desc_bytes) <= 36, "test description too long for the 36-byte field"
    header[0x04 : 0x04 + len(desc_bytes)] = desc_bytes
    struct.pack_into("<I", header, 0x28, len(payload))
    struct.pack_into("<I", header, 0x2C, frequency)
    struct.pack_into("<I", header, 0x30, bits_per_sample)
    struct.pack_into("<I", header, 0x34, num_channels)
    struct.pack_into("<I", header, 0x38, encoding_type)
    return bytes(header) + payload


class SoundRecordParseTests(unittest.TestCase):
    def test_parses_all_fields(self) -> None:
        data = _build_record(42, "Avatar_03920.umt", 22050, 16, 1, ENCODING_EA_MICROTALK, b"\x01\x02\x03\x04")
        record = U9SoundRecord.parse(data)
        self.assertEqual(record.sound_id, 42)
        self.assertEqual(record.description, "Avatar_03920.umt")
        self.assertEqual(record.frequency, 22050)
        self.assertEqual(record.bits_per_sample, 16)
        self.assertEqual(record.num_channels, 1)
        self.assertEqual(record.encoding_type, ENCODING_EA_MICROTALK)
        self.assertEqual(record.payload, b"\x01\x02\x03\x04")

    def test_long_description_not_truncated_at_20_bytes(self) -> None:
        # 33 bytes -- the longest real description observed in Speech.flx, well past
        # the 20-byte field a prior draft script used (which would have cut this off
        # mid-string and left the remainder misread as reserved/unknown bytes).
        long_desc = "Exferlem_ThisIsALongName_08602.um"  # 33 chars
        self.assertEqual(len(long_desc), 33)
        data = _build_record(1, long_desc, 22050, 16, 1, ENCODING_EA_MICROTALK, b"\x00")
        record = U9SoundRecord.parse(data)
        self.assertEqual(record.description, long_desc)

    def test_description_at_exactly_20_bytes_not_falsely_truncated(self) -> None:
        # A boundary case right at the old (buggy) field width, to make sure the
        # fix doesn't just coincidentally work for short strings.
        desc_20 = "12345678901234567890"[:20]
        data = _build_record(1, desc_20, 22050, 16, 1, ENCODING_PCM, b"\x00\x00")
        record = U9SoundRecord.parse(data)
        self.assertEqual(record.description, desc_20)

    def test_too_small_data_raises(self) -> None:
        with self.assertRaises(U9SoundRecordError):
            U9SoundRecord.parse(b"\x00" * 10)

    def test_payload_clipped_to_available_data(self) -> None:
        # data_length claims more than is actually present -- parse() must not
        # raise or read out of bounds, just return whatever's available.
        header = bytearray(HEADER_SIZE)
        struct.pack_into("<I", header, 0x28, 999)
        data = bytes(header) + b"\x01\x02"
        record = U9SoundRecord.parse(data)
        self.assertEqual(record.payload, b"\x01\x02")


class SoundRecordEncodingTests(unittest.TestCase):
    def test_is_pcm_true_for_encoding_0(self) -> None:
        data = _build_record(1, "x", 11025, 8, 1, ENCODING_PCM, b"\x01")
        self.assertTrue(U9SoundRecord.parse(data).is_pcm)

    def test_is_pcm_false_for_adpcm_and_microtalk(self) -> None:
        for enc in (ENCODING_ADPCM, ENCODING_EA_MICROTALK):
            data = _build_record(1, "x", 11025, 8, 1, enc, b"\x01")
            self.assertFalse(U9SoundRecord.parse(data).is_pcm)

    def test_encoding_name_known_and_unknown(self) -> None:
        pcm = U9SoundRecord.parse(_build_record(1, "x", 11025, 8, 1, ENCODING_PCM, b"\x01"))
        self.assertEqual(pcm.encoding_name, "PCM")
        weird = U9SoundRecord.parse(_build_record(1, "x", 11025, 8, 1, 99, b"\x01"))
        self.assertIn("99", weird.encoding_name)


class ToWavBytesTests(unittest.TestCase):
    def test_pcm_round_trips_through_wave_module(self) -> None:
        pcm_payload = struct.pack("<4h", 100, -100, 200, -200)  # 4 samples, 16-bit mono
        data = _build_record(1, "x", 22050, 16, 1, ENCODING_PCM, pcm_payload)
        record = U9SoundRecord.parse(data)

        wav_bytes = record.to_wav_bytes()
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 22050)
            self.assertEqual(wf.readframes(4), pcm_payload)

    def test_stereo_microtalk_raises_instead_of_producing_noise(self) -> None:
        # no real 2-channel MicroTalk entry has ever been observed (Speech.flx
        # is 100% mono) and the ported decoder only implements the mono path --
        # see titan.u9.microtalk's module docstring.
        payload = struct.pack("<I", 0)
        data = _build_record(1, "x", 22050, 16, 2, ENCODING_EA_MICROTALK, payload)
        record = U9SoundRecord.parse(data)
        self.assertFalse(record.is_decodable_microtalk)
        with self.assertRaises(U9SoundRecordError):
            record.to_wav_bytes()

    def test_mono_adpcm_is_decoded_not_raised(self) -> None:
        # mono ADPCM (some sfx.flx entries) uses a separate, smaller block
        # shape than stereo -- see titan.u9.adpcm's module docstring for the
        # real-data (vgmstream cross-checked) validation.
        adpcm_block = bytes([0x00]) + bytes([0x11] * 14)  # 15-byte mono block
        data = _build_record(1, "x", 22050, 16, 1, ENCODING_ADPCM, adpcm_block)
        record = U9SoundRecord.parse(data)
        self.assertTrue(record.is_decodable_adpcm)

        wav_bytes = record.to_wav_bytes()
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getnframes(), 28)

    def test_mono_microtalk_is_decoded_not_raised(self) -> None:
        # a zero-total-samples payload is trivially valid (see test_u9_microtalk.py
        # for the deeper "silence in, silence out" trace) -- just confirm to_wav_bytes()
        # routes mono EA MicroTalk through the decoder instead of raising.
        payload = struct.pack("<I", 0)
        data = _build_record(1, "x", 22050, 16, 1, ENCODING_EA_MICROTALK, payload)
        record = U9SoundRecord.parse(data)
        self.assertTrue(record.is_decodable_microtalk)

        wav_bytes = record.to_wav_bytes()
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getnframes(), 0)

    def test_stereo_adpcm_is_decoded_not_raised(self) -> None:
        # coeff_idx=0 block (see test_u9_adpcm.py): nibble 0x1 in every position
        # decodes to sample +4096 on both channels, hand-verifiable independent
        # of the recursive filter state.
        adpcm_block = bytes([0x00, 0x00]) + bytes([0x11] * 28)
        data = _build_record(1, "x", 22050, 16, 2, ENCODING_ADPCM, adpcm_block)
        record = U9SoundRecord.parse(data)
        self.assertTrue(record.is_decodable_adpcm)

        wav_bytes = record.to_wav_bytes()
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getframerate(), 22050)
            pcm = wf.readframes(wf.getnframes())
        samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
        self.assertTrue(all(s == 4096 for s in samples))


if __name__ == "__main__":
    unittest.main()
