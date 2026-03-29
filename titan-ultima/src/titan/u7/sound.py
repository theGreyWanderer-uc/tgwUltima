"""
Ultima 7 — Creative Voice (VOC) decoder.

Decodes Creative Voice File format (.voc) to WAV, as used by Ultima 7
for speech and voice recordings (``INTROSND.DAT``, records inside
``U7SPEECH.SPC``).

Example::

    from titan.u7.sound import VocDecoder

    pcm, sample_rate = VocDecoder.decode_file("INTROSND.DAT")
    VocDecoder.to_wav("INTROSND.DAT", "output/introsnd.wav")
"""

from __future__ import annotations

__all__ = ["VocDecoder"]

import os
import struct
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# VOC header constants
# ---------------------------------------------------------------------------
VOC_MAGIC = b"Creative Voice File"
VOC_DATA_OFFSET = 0x1A        # blocks start at offset 26

# Block types
_BLOCK_TERM = 0x00
_BLOCK_SOUND = 0x01
_BLOCK_CONTINUE = 0x02
_BLOCK_SILENCE = 0x03

# ADPCM constants
_ADPCM_SCALE_MAP = [-2, -1, 0, 0, 1, 1, 1, 1]


def _fudge_rate(raw_rate: int) -> int:
    """Round non-standard VOC sample rates to standard WAV rates."""
    if 11000 <= raw_rate <= 11200:
        return 11025
    if 22000 <= raw_rate <= 22300:
        return 22050
    if 44000 <= raw_rate <= 44200:
        return 44100
    return raw_rate


class VocDecoder:
    """Decode Creative Voice File (.voc) to raw unsigned 8-bit PCM."""

    # ------------------------------------------------------------------
    # ADPCM 4-bit decoder (matches Exult VocAudioSample.cc)
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_adpcm_sample(
        nibble: int, reference: int, scale: int
    ) -> tuple[int, int, int]:
        """Decode one 4-bit ADPCM sample, returning (sample, ref, scale)."""
        delta = (nibble & 0x07) << scale
        if nibble & 0x08:
            reference = max(0x00, reference - delta)
        else:
            reference = min(0xFF, reference + delta)
        scale += _ADPCM_SCALE_MAP[nibble & 0x07]
        scale = max(2, min(6, scale))
        return reference, reference, scale

    @classmethod
    def _decode_adpcm_block(
        cls,
        data: bytes,
        reference: int,
        scale: int,
    ) -> tuple[bytearray, int, int]:
        """Decode a block of 4-bit ADPCM data to unsigned 8-bit PCM.

        If *reference* is -1, the first byte of *data* is consumed as the
        initial reference value.

        Returns ``(pcm_bytes, final_reference, final_scale)``.
        """
        out = bytearray()
        offset = 0

        if reference < 0:
            if not data:
                return out, 0, 2
            reference = data[0]
            offset = 1

        for i in range(offset, len(data)):
            byte = data[i]
            # High nibble first, then low nibble
            sample, reference, scale = cls._decode_adpcm_sample(
                byte >> 4, reference, scale
            )
            out.append(sample)
            sample, reference, scale = cls._decode_adpcm_sample(
                byte & 0x0F, reference, scale
            )
            out.append(sample)

        return out, reference, scale

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @classmethod
    def decode(cls, data: bytes) -> tuple[bytes, int]:
        """Decode a VOC buffer to raw unsigned 8-bit PCM.

        Returns ``(pcm_bytes, sample_rate_hz)``.

        Raises :class:`ValueError` if the data does not start with the
        Creative Voice File magic string.
        """
        if not data or len(data) < VOC_DATA_OFFSET:
            raise ValueError("Data too short for a VOC file")

        if not data[:len(VOC_MAGIC)] == VOC_MAGIC:
            raise ValueError(
                "Not a Creative Voice File (missing magic header)")

        pcm = bytearray()
        pos = VOC_DATA_OFFSET
        sample_rate = 11025  # sensible default

        # ADPCM state persists across type-2 continuation blocks
        compression = 0
        adpcm_ref = -1
        adpcm_scale = 2

        while pos < len(data):
            block_type = data[pos]
            pos += 1

            if block_type == _BLOCK_TERM:
                break

            if pos + 3 > len(data):
                break

            # 3-byte little-endian block length
            block_len = data[pos] | (data[pos + 1] << 8) | (data[pos + 2] << 16)
            pos += 3

            if block_type == _BLOCK_SOUND:
                if block_len < 2 or pos + block_len > len(data):
                    break
                rate_byte = data[pos]
                compression = data[pos + 1]
                raw_rate = 1000000 // (256 - rate_byte) if rate_byte < 256 else 11025
                sample_rate = _fudge_rate(raw_rate)
                audio_data = data[pos + 2:pos + block_len]

                # Reset ADPCM state for new sound block
                adpcm_ref = -1
                adpcm_scale = 2

                if compression == 0:
                    # Uncompressed 8-bit unsigned PCM
                    pcm.extend(audio_data)
                elif compression == 1:
                    # 4-bit ADPCM
                    decoded, adpcm_ref, adpcm_scale = cls._decode_adpcm_block(
                        audio_data, adpcm_ref, adpcm_scale
                    )
                    pcm.extend(decoded)
                else:
                    # Unknown compression — output silence
                    pcm.extend(b'\x80' * len(audio_data))

                pos += block_len

            elif block_type == _BLOCK_CONTINUE:
                if pos + block_len > len(data):
                    break
                audio_data = data[pos:pos + block_len]

                if compression == 0:
                    pcm.extend(audio_data)
                elif compression == 1:
                    decoded, adpcm_ref, adpcm_scale = cls._decode_adpcm_block(
                        audio_data, adpcm_ref, adpcm_scale
                    )
                    pcm.extend(decoded)

                pos += block_len

            elif block_type == _BLOCK_SILENCE:
                if pos + 3 > len(data):
                    break
                duration = (data[pos] | (data[pos + 1] << 8)) + 1
                # Byte 3 is sample rate byte for this silence period
                pos += 3
                pcm.extend(b'\x80' * duration)

            else:
                # Unknown block type — skip
                pos += block_len

        return bytes(pcm), sample_rate

    @classmethod
    def decode_file(cls, filepath: str) -> tuple[bytes, int]:
        """Decode a VOC file from disk.

        Returns ``(pcm_bytes, sample_rate_hz)``.
        """
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.decode(data)

    @classmethod
    def is_voc(cls, data: bytes) -> bool:
        """Return ``True`` if *data* begins with the VOC magic string."""
        return (
            len(data) >= VOC_DATA_OFFSET
            and data[:len(VOC_MAGIC)] == VOC_MAGIC
        )

    # ------------------------------------------------------------------
    # WAV output
    # ------------------------------------------------------------------

    @classmethod
    def to_wav(
        cls,
        src: str,
        dst: str,
        *,
        data: Optional[bytes] = None,
    ) -> str:
        """Decode a VOC file (or raw VOC bytes) and write a WAV file.

        Parameters
        ----------
        src:
            Source VOC file path (used if *data* is ``None``).
        dst:
            Destination WAV file path.
        data:
            Optional raw VOC bytes. If provided, *src* is only used
            for display / naming and not read from disk.

        Returns the path to the written WAV file.
        """
        if data is None:
            pcm, rate = cls.decode_file(src)
        else:
            pcm, rate = cls.decode(data)

        cls._write_wav(dst, pcm, rate)
        return dst

    @staticmethod
    def _write_wav(path: str, pcm: bytes, sample_rate: int) -> None:
        """Write unsigned 8-bit mono PCM data as a WAV file."""
        num_samples = len(pcm)
        data_size = num_samples
        # WAV header: 44 bytes
        #   RIFF header (12) + fmt chunk (24) + data chunk header (8)
        file_size = 36 + data_size

        header = bytearray(44)
        # RIFF header
        header[0:4] = b'RIFF'
        struct.pack_into('<I', header, 4, file_size)
        header[8:12] = b'WAVE'
        # fmt chunk
        header[12:16] = b'fmt '
        struct.pack_into('<I', header, 16, 16)          # chunk size
        struct.pack_into('<H', header, 20, 1)            # PCM format
        struct.pack_into('<H', header, 22, 1)            # mono
        struct.pack_into('<I', header, 24, sample_rate)  # sample rate
        struct.pack_into('<I', header, 28, sample_rate)  # byte rate (8-bit mono)
        struct.pack_into('<H', header, 32, 1)            # block align
        struct.pack_into('<H', header, 34, 8)            # bits per sample
        # data chunk
        header[36:40] = b'data'
        struct.pack_into('<I', header, 40, data_size)

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(header)
            f.write(pcm)
