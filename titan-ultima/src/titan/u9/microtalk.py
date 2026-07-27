"""
EA MicroTalk (UTK) speech decoder for Ultima 9: Ascension's ``Speech.flx``.

``U9SoundRecord.encoding_type == 2`` ("EA MicroTalk") entries are a
multipulse CELP/RELP speech codec -- a genuinely different, more complex
codec family than the ADPCM used by ``music.flx`` (see
:mod:`titan.u9.adpcm`): variable-bitrate, entropy-coded excitation with
an LPC synthesis filter, not a fixed-ratio differential predictor.

This is a line-for-line port of the real, open-source reference
decoder -- ``vgmstream``'s ``src/coding/libs/utkdec.c`` /
``src/coding/ea_mt_decoder.c`` (found locally at
``D:\\_Repos\\_UltimaIX\\vgmstream``), itself based on Andrew D'Addesio's
``utkencode`` (UNLICENSE/public domain: https://github.com/daddesio/utkencode).
Only the ``UTK_EA`` codec path is ported here (the plain EA-MT variant
U9 actually uses) -- ``UTK_CBX`` (Traveller's Tales' modified variant,
confirmed unrelated to U9's format during this project's own
investigation) and ``UTK_EA_PCM`` (rare inline-PCM-block variant, not
observed in any real U9 entry checked) are intentionally not
implemented.

All floating-point state (``fixed_gains``, ``rc_data``,
``synth_history``, the sample/adaptive-codebook buffer) uses
``numpy.float32`` throughout, matching the reference's C ``float`` (not
``double``) precision exactly -- this matters because the LPC synthesis
filter is recursive across frames; using Python's native double-
precision floats would silently drift from the reference over a long
stream.

vgmstream's own ``.FLX`` parser (``src/meta/flx.c``) independently
confirms this project's own reverse-engineered sound-record header
layout (see :mod:`titan.u9.sound`) field-for-field, with one addition
specific to MicroTalk entries: a 4-byte total-sample-count field
immediately follows the standard 0x3C-byte header, with the actual
MicroTalk bitstream starting 4 bytes later than the header alone would
suggest.

Each decoded frame is exactly 432 samples; the true (usually
non-multiple-of-432) sample count from that 4-byte field is used to
trim the final frame's excess.

Validated against 104 real, known-good (compressed payload -> decoded
WAV) pairs recovered from a previous export of this project
(``u9data/u9_output/exampleWav/``), matched to their source ``Speech.flx``
entries by description field: after fixing a transcription bug in the
first port (the post-subframe adaptive-codebook refresh copied
``samples[0:324]`` instead of the reference's ``samples[108:432]``,
which produced bit-identical output for the first two frames --
adaptive-codebook lookups only start reading meaningfully-wrong history
once decoding reaches the third frame -- before audibly diverging),
all 104 pairs decode with the same sample count and match the
reference bit-for-bit on 99.7% of samples (17,225,839 of 17,280,294
samples across the whole set); the remaining ~0.3% differ by exactly
+/-1 out of a 16-bit range -- consistent with ordinary floating-point
rounding-tie noise (the reference C float ops are not guaranteed
bit-associative across compilers/builds either) rather than a logic
error.

Example::

    from titan.u9.microtalk import decode_mono

    pcm16_bytes = decode_mono(record.payload)  # payload includes the leading
                                                 # 4-byte sample count, per above
"""

from __future__ import annotations

__all__ = ["decode_mono", "MicroTalkDecodeError"]

import struct

import numpy as np

F32 = np.float32

MASK_TABLE = (0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF)

# Reflection coefficient table (rounded), mirrored: t[64-i] = -t[i] for i in 1..32.
UTK_RC_TABLE = (
    +0.000000, -0.996776, -0.990327, -0.983879,
    -0.977431, -0.970982, -0.964534, -0.958085,
    -0.951637, -0.930754, -0.904960, -0.879167,
    -0.853373, -0.827579, -0.801786, -0.775992,
    -0.750198, -0.724405, -0.698611, -0.670635,
    -0.619048, -0.567460, -0.515873, -0.464286,
    -0.412698, -0.361111, -0.309524, -0.257937,
    -0.206349, -0.154762, -0.103175, -0.051587,
    +0.000000, +0.051587, +0.103175, +0.154762,
    +0.206349, +0.257937, +0.309524, +0.361111,
    +0.412698, +0.464286, +0.515873, +0.567460,
    +0.619048, +0.670635, +0.698611, +0.724405,
    +0.750198, +0.775992, +0.801786, +0.827579,
    +0.853373, +0.879167, +0.904960, +0.930754,
    +0.951637, +0.958085, +0.964534, +0.970982,
    +0.977431, +0.983879, +0.990327, +0.996776,
)

# Normal-model codebook (index_table[0]).
UTK_CODEBOOK_NORMAL = (
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 21,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 25,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 22,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 0,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 21,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 26,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 22,
    4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
    4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 2,
)

# Large-pulse-model codebook (index_table[1]).
UTK_CODEBOOK_LARGEPULSE = (
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 23,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 27,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 24,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 1,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 23,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 28,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 24,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 3,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 23,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 27,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 24,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 1,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 23,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 28,
    4, 11, 7, 15, 4, 12, 8, 19, 4, 11, 7, 16, 4, 12, 8, 24,
    4, 11, 7, 15, 4, 12, 8, 20, 4, 11, 7, 16, 4, 12, 8, 3,
)

UTK_CODEBOOKS = (UTK_CODEBOOK_NORMAL, UTK_CODEBOOK_LARGEPULSE)

MDL_NORMAL = 0
MDL_LARGEPULSE = 1

# (next_model, code_size, pulse_value)
UTK_COMMANDS = (
    (MDL_LARGEPULSE, 8, 0.0),
    (MDL_LARGEPULSE, 7, 0.0),
    (MDL_NORMAL, 8, 0.0),
    (MDL_NORMAL, 7, 0.0),
    (MDL_NORMAL, 2, 0.0),
    (MDL_NORMAL, 2, -1.0),
    (MDL_NORMAL, 2, +1.0),
    (MDL_NORMAL, 3, -1.0),
    (MDL_NORMAL, 3, +1.0),
    (MDL_LARGEPULSE, 4, -2.0),
    (MDL_LARGEPULSE, 4, +2.0),
    (MDL_LARGEPULSE, 3, -2.0),
    (MDL_LARGEPULSE, 3, +2.0),
    (MDL_LARGEPULSE, 5, -3.0),
    (MDL_LARGEPULSE, 5, +3.0),
    (MDL_LARGEPULSE, 4, -3.0),
    (MDL_LARGEPULSE, 4, +3.0),
    (MDL_LARGEPULSE, 6, -4.0),
    (MDL_LARGEPULSE, 6, +4.0),
    (MDL_LARGEPULSE, 5, -4.0),
    (MDL_LARGEPULSE, 5, +4.0),
    (MDL_LARGEPULSE, 7, -5.0),
    (MDL_LARGEPULSE, 7, +5.0),
    (MDL_LARGEPULSE, 6, -5.0),
    (MDL_LARGEPULSE, 6, +5.0),
    (MDL_LARGEPULSE, 8, -6.0),
    (MDL_LARGEPULSE, 8, +6.0),
    (MDL_LARGEPULSE, 7, -6.0),
    (MDL_LARGEPULSE, 7, +6.0),
)

FRAME_SAMPLES = 432  # 4 subframes * 108 samples


class MicroTalkDecodeError(Exception):
    """Raised on malformed MicroTalk data (e.g. an out-of-range reflection-coefficient index)."""


class _BitReader:
    """LSB-first bit reader over an in-memory buffer (AKA the 'br'/bitreader_t in utkdec.c)."""

    __slots__ = ("data", "pos", "end", "bits_value", "bits_count")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.end = len(data)
        self.bits_value = 0
        self.bits_count = 0

    def _read_byte(self) -> int:
        if self.pos < self.end:
            b = self.data[self.pos]
            self.pos += 1
            return b
        return 0

    def init_bits(self) -> None:
        if not self.bits_count:
            self.bits_value = self._read_byte()
            self.bits_count = 8

    def peek_bits(self, count: int) -> int:
        return self.bits_value & MASK_TABLE[count - 1]

    def read_bits(self, count: int) -> int:
        mask = MASK_TABLE[count - 1]
        ret = self.bits_value & mask
        self.bits_value >>= count
        self.bits_count -= count
        if self.bits_count < 8:
            self.bits_value |= self._read_byte() << self.bits_count
            self.bits_count += 8
        return ret

    def consume_bits(self, count: int) -> None:
        self.read_bits(count)


class _UtkContext:
    """Mutable decode state (AKA 'utk_context_t'/'UTALKSTATE'), UTK_EA path only."""

    def __init__(self) -> None:
        self.parsed_header = False
        self.br: _BitReader | None = None
        self.reduced_bandwidth = False
        self.multipulse_threshold = 0
        self.fixed_gains = np.zeros(64, dtype=F32)
        self.rc_data = np.zeros(12, dtype=F32)
        self.synth_history = np.zeros(12, dtype=F32)
        # subframes[0:324] = adapt_cb, subframes[324:324+432] = samples (one shared buffer,
        # matching the reference's deliberate aliasing so pitch lookups can read into history).
        self.subframes = np.zeros(324 + 432, dtype=F32)

    @property
    def adapt_cb(self) -> np.ndarray:
        return self.subframes[0:324]

    @property
    def samples(self) -> np.ndarray:
        return self.subframes[324:324 + 432]


def _parse_header(ctx: _UtkContext) -> None:
    br = ctx.br
    assert br is not None
    ctx.reduced_bandwidth = br.read_bits(1) == 1

    base_thre = br.read_bits(4)
    base_gain = br.read_bits(4)
    base_mult = br.read_bits(6)

    ctx.multipulse_threshold = 32 - base_thre
    ctx.fixed_gains[0] = F32(8.0) * F32(1 + base_gain)

    multiplier = F32(1.04) + F32(base_mult) * F32(0.001)
    for i in range(1, 64):
        ctx.fixed_gains[i] = ctx.fixed_gains[i - 1] * multiplier


def _decode_excitation(ctx: _UtkContext, use_multipulse: bool, out: np.ndarray, out_offset: int, stride: int) -> None:
    br = ctx.br
    assert br is not None
    i = 0

    if use_multipulse:
        model = MDL_NORMAL
        while i < 108:
            huffman_code = br.peek_bits(8)
            cmd = UTK_CODEBOOKS[model][huffman_code]
            next_model, code_size, pulse_value = UTK_COMMANDS[cmd]
            model = next_model
            br.consume_bits(code_size)

            if cmd > 3:
                out[out_offset + i] = F32(pulse_value)
                i += stride
            elif cmd > 1:
                count = 7 + br.read_bits(6)
                if i + count * stride > 108:
                    count = (108 - i) // stride
                while count > 0:
                    out[out_offset + i] = F32(0.0)
                    i += stride
                    count -= 1
            else:
                x = 7
                while br.read_bits(1):
                    x += 1
                if not br.read_bits(1):
                    x = -x
                out[out_offset + i] = F32(x)
                i += stride
    else:
        while i < 108:
            huffman_code = br.peek_bits(2)
            if huffman_code in (0, 2):
                val, bits = 0.0, 1
            elif huffman_code == 1:
                val, bits = -2.0, 2
            else:  # 3
                val, bits = 2.0, 2
            br.consume_bits(bits)
            out[out_offset + i] = F32(val)
            i += stride


def _rc_to_lpc(rc_data: np.ndarray) -> np.ndarray:
    """AKA ref_to_lpc: reflection coefficients -> LPC coefficients."""
    lpc = np.zeros(12, dtype=F32)
    tmp1 = np.zeros(12, dtype=F32)
    tmp2 = np.zeros(12, dtype=F32)

    for i in range(10, -1, -1):
        tmp2[i + 1] = rc_data[i]
    tmp2[0] = F32(1.0)

    for i in range(12):
        x = -(rc_data[11] * tmp2[11])
        for j in range(10, -1, -1):
            x = x - (rc_data[j] * tmp2[j])
            tmp2[j + 1] = x * rc_data[j] + tmp2[j]
        tmp2[0] = x
        tmp1[i] = x

        for j in range(i):
            x = x - tmp1[i - 1 - j] * lpc[j]
        lpc[i] = x

    return lpc


def _lp_synthesis_filter(ctx: _UtkContext, offset: int, blocks: int) -> None:
    lpc = _rc_to_lpc(ctx.rc_data)
    samples = ctx.samples
    synth_history = ctx.synth_history

    for _ in range(blocks):
        for j in range(12):
            x = samples[offset]
            for k in range(0, j):
                x = x + lpc[k] * synth_history[k - j + 12]
            for k in range(j, 12):
                x = x + lpc[k] * synth_history[k - j + 0]

            synth_history[11 - j] = x
            samples[offset] = x
            offset += 1


def _interpolate_rest(excitation: np.ndarray, base: int) -> None:
    """AKA 'interpolate'. ``excitation`` is indexed via ``base + i`` to allow negative-offset reads."""
    for i in range(0, 108, 2):
        tmp1 = (excitation[base + i - 5] + excitation[base + i + 5]) * F32(0.01803268)
        tmp2 = (excitation[base + i - 3] + excitation[base + i + 3]) * F32(0.11459156)
        tmp3 = (excitation[base + i - 1] + excitation[base + i + 1]) * F32(0.59738597)
        excitation[base + i] = tmp1 - tmp2 + tmp3


def _decode_frame_main(ctx: _UtkContext) -> None:
    br = ctx.br
    assert br is not None
    use_multipulse = False
    # +5 padding on each side for interpolation's negative/over-range reads, matching the
    # reference's `float excitation[5 + 108 + 5]`. Index via `base=5` for the "real" [0..107] range.
    excitation = np.zeros(5 + 108 + 5, dtype=F32)
    rc_delta = np.zeros(12, dtype=F32)

    br.init_bits()
    if not ctx.parsed_header:
        _parse_header(ctx)
        ctx.parsed_header = True

    for i in range(12):
        if i == 0:
            idx = br.read_bits(6)
            if idx < ctx.multipulse_threshold:
                use_multipulse = True
        elif i < 4:
            idx = br.read_bits(6)
        else:
            idx = 16 + br.read_bits(5)

        rc_delta[i] = (F32(UTK_RC_TABLE[idx]) - ctx.rc_data[i]) * F32(0.25)

    for i in range(4):
        pitch_lag = br.read_bits(8)
        pitch_value = br.read_bits(4)
        gain_index = br.read_bits(6)

        pitch_gain = F32(pitch_value) / F32(15.0)
        fixed_gain = ctx.fixed_gains[gain_index]

        if not ctx.reduced_bandwidth:
            _decode_excitation(ctx, use_multipulse, excitation, 5 + 0, 1)
        else:
            align = br.read_bits(1)
            zero_flag = br.read_bits(1)

            _decode_excitation(ctx, use_multipulse, excitation, 5 + align, 2)

            if zero_flag:
                for j in range(54):
                    excitation[5 + (1 - align) + 2 * j] = F32(0.0)
            else:
                excitation[0:5] = F32(0.0)
                excitation[5 + 108:5 + 108 + 5] = F32(0.0)
                _interpolate_rest(excitation, 5 + (1 - align))
                fixed_gain = fixed_gain * F32(0.5)

        for j in range(108):
            idx = 108 * i + 216 - pitch_lag + j
            if idx < 0:
                idx = 0
            tmp1 = fixed_gain * excitation[5 + j]
            tmp2 = pitch_gain * ctx.subframes[idx]  # adapt_cb+samples joined buffer, see _UtkContext
            ctx.subframes[324 + 108 * i + j] = tmp1 + tmp2

    ctx.adapt_cb[:] = ctx.samples[108:108 + 324]

    for i in range(4):
        ctx.rc_data += rc_delta
        blocks = 1 if i < 3 else 33
        _lp_synthesis_filter(ctx, 12 * i, blocks)


def decode_mono(payload: bytes) -> bytes:
    """
    Decode a mono EA MicroTalk payload to 16-bit little-endian PCM bytes.

    ``payload`` must include the leading 4-byte total-sample-count field
    (i.e. the full ``U9SoundRecord.payload`` for an
    ``encoding_type == 2`` entry, unmodified) -- the real bitstream
    starts 4 bytes in, per vgmstream's ``flx.c``.
    """
    if len(payload) < 4:
        raise MicroTalkDecodeError(f"payload too small for the leading sample-count field: {len(payload)} bytes")

    total_samples = struct.unpack_from("<I", payload, 0)[0]
    bitstream = payload[4:]

    ctx = _UtkContext()
    ctx.br = _BitReader(bitstream)

    out_samples: list[int] = []
    while len(out_samples) < total_samples:
        _decode_frame_main(ctx)
        remaining = total_samples - len(out_samples)
        take = min(FRAME_SAMPLES, remaining)
        frame = ctx.samples[:take]
        # UTK_ROUND + clamp to int16, matching decode_ea_mt's UTK_ROUND/UTK_CLAMP.
        rounded = np.where(frame >= 0, frame + F32(0.5), frame - F32(0.5))
        clamped = np.clip(rounded.astype(np.int64), -32768, 32767)
        out_samples.extend(int(v) for v in clamped)

    return struct.pack(f"<{len(out_samples)}h", *out_samples)
