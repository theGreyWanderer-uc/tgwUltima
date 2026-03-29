"""
Sonarc audio decompressor for Ultima 8.

Provides :class:`SonarcDecoder` for decoding Sonarc-compressed audio from
Ultima 8's SOUND.FLX into PCM or WAV.

Example::

    from titan.sound import SonarcDecoder

    with open("0001.raw", "rb") as f:
        data = f.read()

    result = SonarcDecoder.decode_file(data)
    if result:
        pcm, sample_rate = result
        wav = SonarcDecoder.pcm_to_wav(pcm, sample_rate)
        with open("0001.wav", "wb") as f:
            f.write(wav)
"""

from __future__ import annotations

__all__ = ["SonarcDecoder"]

import io
import struct
import wave
from typing import Optional


class SonarcDecoder:
    """
    Decoder for Sonarc-compressed audio from Ultima 8's SOUND.FLX.

    Ported directly from Pentagram's SonarcAudioSample.cpp.

    File header (at buffer start)::

        Offset 0, 4 bytes: uint32 LE – decompressed sample count (length)
        Offset 4, 2 bytes: uint16 LE – sample rate (e.g. 11111 Hz)
        Offset 6..0x1F:    reserved/padding

    At offset 0x20 (src_offset): sequence of Sonarc frames.
    If the first frame's frame_bytes == 0x20 and length > 32767,
    src_offset advances by 0x100 (skip an extended header table).

    Each Sonarc frame::

        Offset 0, 2 bytes: uint16 LE – frame byte size (including this header)
        Offset 2, 2 bytes: uint16 LE – number of samples in this frame
        Offset 4, 2 bytes: uint16 LE – checksum validation area start
        Offset 6, 1 byte:  mode + 8
        Offset 7, 1 byte:  LPC order
        Offset 8, order*2: LPC factors (sint16 LE each)
        After factors:      entropy coded (EC) audio data
    """

    # One-count table: OneTable[x] = number of consecutive 1-bits on low side
    _one_table: Optional[list[int]] = None

    @classmethod
    def _ensure_one_table(cls) -> list[int]:
        """Generate the OneTable if not already cached."""
        if cls._one_table is not None:
            return cls._one_table

        table = [0] * 256
        power = 2
        while power < 32:
            col = power - 1
            while col < 16:
                for row in range(16):
                    table[row * 16 + col] += 1
                col += power
            power *= 2

        for i in range(16):
            table[i * 16 + 15] += table[i]

        cls._one_table = table
        return table

    @staticmethod
    def _decode_ec(mode: int, samplecount: int,
                   source: bytes, sourcesize: int,
                   dest: bytearray) -> None:
        """
        Entropy-coding decompression.

        Ported from SonarcAudioSample::decode_EC.
        """
        one_table = SonarcDecoder._ensure_one_table()
        zerospecial = False
        data = 0
        inputbits = 0
        src_idx = 0
        dest_idx = 0

        if mode >= 7:
            mode -= 7
            zerospecial = True

        while samplecount > 0:
            # Fill data window
            while src_idx < sourcesize and inputbits <= 24:
                data |= source[src_idx] << inputbits
                src_idx += 1
                inputbits += 8

            if zerospecial and not (data & 0x1):
                dest[dest_idx] = 0x80
                dest_idx += 1
                data >>= 1
                inputbits -= 1
            else:
                if zerospecial:
                    data >>= 1
                    inputbits -= 1

                low_byte = data & 0xFF
                ones = one_table[low_byte]

                if ones == 0:
                    data >>= 1  # strip zero
                    sample = data & 0xFF
                    # Sign extend: mode+1 bits
                    sample = sample & ((1 << (mode + 1)) - 1)
                    if sample & (1 << mode):
                        sample -= (1 << (mode + 1))
                    dest[dest_idx] = (sample + 0x80) & 0xFF
                    dest_idx += 1
                    data >>= (mode + 1)
                    inputbits -= (mode + 2)
                elif ones < 7 - mode:
                    data >>= (ones + 1)  # strip ones and zero
                    sample = data & 0xFF
                    # Extract mode+ones bits
                    nbits = mode + ones
                    sample = sample & ((1 << nbits) - 1)
                    sample <<= (7 - mode - ones)
                    sample &= 0x7F
                    if not (sample & 0x40):
                        sample |= 0x80
                    # Sign extend from 8-bit
                    sample = (sample << (7 - mode - ones)) & 0xFF
                    # Re-derive correctly per Pentagram logic
                    sample_raw = data & 0xFF
                    sample_raw <<= (7 - nbits)
                    sample_raw &= 0x7F
                    if not (sample_raw & 0x40):
                        sample_raw |= 0x80
                    # sint8 sign extend
                    if sample_raw & 0x80:
                        sample_raw = sample_raw - 256
                    sample_raw >>= (7 - nbits)
                    dest[dest_idx] = (sample_raw + 0x80) & 0xFF
                    dest_idx += 1
                    data >>= nbits
                    inputbits -= (mode + 2 * ones + 1)
                else:
                    data >>= (7 - mode)  # strip ones
                    sample = data & 0xFF
                    sample &= 0x7F
                    if not (sample & 0x40):
                        sample |= 0x80
                    # sint8
                    if sample & 0x80:
                        sample = sample - 256
                    dest[dest_idx] = (sample + 0x80) & 0xFF
                    dest_idx += 1
                    data >>= 7
                    inputbits -= (2 * 7 - mode)

            # Mask data to prevent overflow
            data &= 0xFFFFFFFF
            samplecount -= 1

    @staticmethod
    def _decode_lpc(order: int, nsamples: int,
                    dest: bytearray, dest_start: int,
                    factors: bytes) -> None:
        """
        Linear Predictive Coding pass.

        Ported from SonarcAudioSample::decode_LPC.
        """
        for i in range(nsamples):
            accum = 0
            for j in range(order - 1, -1, -1):
                pos = dest_start + i - 1 - j
                if pos < dest_start:
                    val1 = 0
                else:
                    val1 = dest[pos]
                # XOR happens unconditionally (outside the ternary in C++)
                val1 = (val1 ^ 0x80) & 0xFF
                if val1 > 127:
                    val1 -= 256  # interpret as sint8

                val2 = struct.unpack_from("<h", factors, j * 2)[0]
                accum += val1 * val2

            accum += 0x800
            correction = (accum >> 12) & 0xFF
            idx = dest_start + i
            dest[idx] = (dest[idx] - correction) & 0xFF

    @staticmethod
    def _audio_decode(source: bytes) -> Optional[bytearray]:
        """
        Decode a single Sonarc audio frame.

        Returns decompressed unsigned 8-bit PCM samples.
        """
        if len(source) < 8:
            return None

        size = source[0] | (source[1] << 8)

        # Checksum validation
        checksum = 0
        for i in range(size // 2):
            val = source[2 * i] | (source[2 * i + 1] << 8)
            checksum ^= val
        checksum &= 0xFFFF

        if checksum != 0xACED:
            return None

        order = source[7]
        mode = source[6] - 8
        samplecount = source[2] | (source[3] << 8)

        dest = bytearray(samplecount)

        ec_offset = 8 + 2 * order
        ec_size = size - ec_offset
        if ec_size < 0:
            return None

        SonarcDecoder._decode_ec(
            mode, samplecount,
            source[ec_offset:ec_offset + ec_size], ec_size,
            dest
        )

        SonarcDecoder._decode_lpc(
            order, samplecount,
            dest, 0,
            source[8:8 + 2 * order]
        )

        # Fix clipped samples
        for i in range(1, samplecount):
            if dest[i] == 0 and dest[i - 1] > 192:
                dest[i] = 0xFF

        return dest

    @classmethod
    def decode_file(cls, data: bytes) -> Optional[tuple[bytes, int]]:
        """
        Decode a full Sonarc audio file (as extracted from SOUND.FLX).

        Returns:
            ``(pcm_bytes, sample_rate)`` or ``None`` on failure.
            PCM is unsigned 8-bit mono.
        """
        if len(data) < 0x24:
            return None

        # File header
        total_length = struct.unpack_from("<I", data, 0)[0]
        sample_rate = struct.unpack_from("<H", data, 4)[0]

        src_offset = 0x20

        # Check for extended header
        if src_offset + 4 <= len(data):
            frame_bytes = data[src_offset] | (data[src_offset + 1] << 8)
            if frame_bytes == 0x20 and total_length > 32767:
                src_offset += 0x100

        # Decode frames
        output = bytearray()
        pos = src_offset
        sample_pos = 0

        while pos < len(data) and sample_pos < total_length:
            if pos + 4 > len(data):
                break

            frame_bytes = data[pos] | (data[pos + 1] << 8)
            frame_samples = data[pos + 2] | (data[pos + 3] << 8)

            if frame_bytes == 0 or frame_bytes > len(data) - pos:
                break

            frame_data = data[pos:pos + frame_bytes]
            decoded = cls._audio_decode(frame_data)

            if decoded is not None:
                output.extend(decoded)
            else:
                # Silence on decode failure
                output.extend(b'\x80' * frame_samples)

            pos += frame_bytes
            sample_pos += frame_samples

        return bytes(output), sample_rate

    @staticmethod
    def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        """Package unsigned 8-bit PCM into a WAV file."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)  # 8-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()
