"""
EA-XA ADPCM decoders for Ultima 9: Ascension's ``music/*.flx`` and
``sfx.flx`` entries.

``U9SoundRecord.encoding_type == 1`` ("ADPCM") entries are a differential
predictive codec (EA-XA / EA ADPCM v1, per vgmstream's naming) built on
the same predictor coefficient table for both channel layouts, but with
two genuinely different block shapes depending on channel count:

- **Stereo** (:func:`decode_stereo`, ``music.flx``): 30 input bytes ->
  112 bytes (56 int16 samples) of interleaved stereo PCM per block.
  Reverse-engineered from this project's own
  ``u9decode_python_reimplementation_guide.md`` (a companion guide to
  the ``u9decode`` C tool's music decoder), then corrected and validated
  directly against real ``music.flx`` data:

  - The guide's claimed payload layout (a 4-byte field + 56-byte
    filename, audio starting immediately after at +0x3C) does not match
    this game copy's actual container: real
    ``music.flx``/``sfx.flx``/``Speech.flx`` entries all share the same
    0x3C-byte sound-record header documented in :mod:`titan.u9.sound`
    (with explicit ``data_length``/``frequency``/``bits``/``channels``/
    ``encoding_type`` fields, cross-validated with zero mismatches
    across hundreds of real entries). The block decode *algorithm* the
    guide describes, however, is correct once paired with that header:
    tested against 10 real ``music.flx`` tracks, every one decoded with
    zero coefficient errors, zero payload misalignment, zero sample
    clipping, and sample ranges consistent with real audio --
    independently re-verified by decoding one output WAV with
    vgmstream (matched expected sample rate/channels/duration exactly).

- **Mono** (:func:`decode_mono`, ``sfx.flx``): 15 input bytes -> 56
  bytes (28 int16 samples) per block -- a separate, simpler block shape
  that :func:`decode_stereo` cannot handle (applying the stereo
  algorithm to mono data produces frequent invalid-coefficient errors
  and heavy clipping, confirmed by testing before this function
  existed). Validated bit-exact (zero sample difference, matching
  sample counts) against 9 diverse real ``sfx.flx`` entries independently
  decoded with vgmstream (which identifies the format as "Electronic
  Arts EA-XA 4-bit ADPCM v1 (mono/interleave)").

Predictor coefficients (fixed-point, applied per :func:`_decode_pair`,
shared by both block shapes)::

    COEFF_A = [0, 240, 460, 392]
    COEFF_B = [0, 0, -208, -220]

Per-block layout, stereo (30 bytes in)::

    byte 0: high nibble = left coeff_idx (0-3), low nibble = right coeff_idx
    byte 1: high nibble = left shift,           low nibble = right shift
    bytes 2..29: 14 steps of (left_byte, right_byte), each byte's high/low
                 nibble giving 2 samples per channel per step

Per-block layout, mono (15 bytes in)::

    byte 0: high nibble = coeff_idx (0-3), low nibble = shift
    bytes 1..14: 14 bytes, each byte's high nibble = one sample, low
                 nibble = the next sample (2 samples per byte, 28 total)

Example::

    from titan.u9.adpcm import decode_stereo, decode_mono

    pcm16_bytes = decode_stereo(record.payload)  # interleaved L/R int16 LE
    pcm16_bytes = decode_mono(record.payload)    # mono int16 LE
"""

from __future__ import annotations

__all__ = [
    "decode_stereo",
    "decode_mono",
    "AdpcmDecodeError",
    "BLOCK_SIZE_IN",
    "BLOCK_SIZE_OUT_SAMPLES",
    "BLOCK_SIZE_IN_MONO",
    "BLOCK_SIZE_OUT_SAMPLES_MONO",
]

import struct

BLOCK_SIZE_IN = 30
BLOCK_SIZE_OUT_SAMPLES = 56  # 28 stereo frames per block

BLOCK_SIZE_IN_MONO = 15
BLOCK_SIZE_OUT_SAMPLES_MONO = 28

COEFF_A = (0, 240, 460, 392)
COEFF_B = (0, 0, -208, -220)


class AdpcmDecodeError(Exception):
    """Raised when a block's coefficient index is out of the valid 0-3 range."""


def _clamp16(x: int) -> int:
    if x > 32767:
        return 32767
    if x < -32768:
        return -32768
    return x


def _sign_extend_nibble(n: int) -> int:
    n &= 0xF
    return n - 0x10 if n & 0x8 else n


def _decode_pair(osa: int, osb: int, a: int, b: int, shift: int, n1: int, n2: int) -> tuple[int, int]:
    d1 = _sign_extend_nibble(n1)
    d2 = _sign_extend_nibble(n2)
    ua = _clamp16(((d1 << (20 - shift)) + osb * a + osa * b + 0x80) >> 8)
    ub = _clamp16(((d2 << (20 - shift)) + ua * a + osb * b + 0x80) >> 8)
    return ua, ub


def _decode_block(block: bytes, state_l: list[int], state_r: list[int]) -> list[int]:
    """``state_l``/``state_r`` are ``[osa, osb]``, mutated in place across blocks."""
    c_l = (block[0] >> 4) & 0xF
    c_r = block[0] & 0xF
    if c_l > 3 or c_r > 3:
        raise AdpcmDecodeError(f"invalid coefficient index: left={c_l} right={c_r}")
    sh_l = (block[1] >> 4) & 0xF
    sh_r = block[1] & 0xF
    a_l, b_l = COEFF_A[c_l], COEFF_B[c_l]
    a_r, b_r = COEFF_A[c_r], COEFF_B[c_r]

    osa_l, osb_l = state_l
    osa_r, osb_r = state_r
    out: list[int] = []
    for i in range(2, BLOCK_SIZE_IN, 2):
        left_byte, right_byte = block[i], block[i + 1]
        osa_l, osb_l = _decode_pair(osa_l, osb_l, a_l, b_l, sh_l, (left_byte >> 4) & 0xF, (right_byte >> 4) & 0xF)
        osa_r, osb_r = _decode_pair(osa_r, osb_r, a_r, b_r, sh_r, left_byte & 0xF, right_byte & 0xF)
        out.extend((osa_l, osa_r, osb_l, osb_r))

    state_l[0], state_l[1] = osa_l, osb_l
    state_r[0], state_r[1] = osa_r, osb_r
    return out


def decode_stereo(payload: bytes) -> bytes:
    """
    Decode a stereo ADPCM payload (``encoding_type == 1``, 2 channels) to
    interleaved 16-bit little-endian PCM bytes.

    Any trailing bytes that don't form a complete 30-byte block are
    silently dropped (every real ``music.flx`` entry checked divided
    evenly; see the module docstring).
    """
    state_l = [0, 0]
    state_r = [0, 0]
    samples: list[int] = []
    num_blocks = len(payload) // BLOCK_SIZE_IN
    for i in range(num_blocks):
        block = payload[i * BLOCK_SIZE_IN : (i + 1) * BLOCK_SIZE_IN]
        samples.extend(_decode_block(block, state_l, state_r))
    return struct.pack(f"<{len(samples)}h", *samples)


def _decode_block_mono(block: bytes, state: list[int]) -> list[int]:
    """``state`` is ``[osa, osb]``, mutated in place across blocks."""
    c = (block[0] >> 4) & 0xF
    if c > 3:
        raise AdpcmDecodeError(f"invalid coefficient index: {c}")
    shift = block[0] & 0xF
    a, b = COEFF_A[c], COEFF_B[c]

    osa, osb = state
    out: list[int] = []
    for i in range(1, BLOCK_SIZE_IN_MONO):
        byte = block[i]
        osa, osb = _decode_pair(osa, osb, a, b, shift, (byte >> 4) & 0xF, byte & 0xF)
        out.extend((osa, osb))

    state[0], state[1] = osa, osb
    return out


def decode_mono(payload: bytes) -> bytes:
    """
    Decode a mono ADPCM payload (``encoding_type == 1``, 1 channel) to
    16-bit little-endian PCM bytes.

    Any trailing bytes that don't form a complete 15-byte block are
    silently dropped (every real ``sfx.flx`` mono entry checked divided
    evenly; see the module docstring).
    """
    state = [0, 0]
    samples: list[int] = []
    num_blocks = len(payload) // BLOCK_SIZE_IN_MONO
    for i in range(num_blocks):
        block = payload[i * BLOCK_SIZE_IN_MONO : (i + 1) * BLOCK_SIZE_IN_MONO]
        samples.extend(_decode_block_mono(block, state))
    return struct.pack(f"<{len(samples)}h", *samples)
