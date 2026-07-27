"""
Sound record header reader for Ultima 9: Ascension.

Every entry in ``sound/*.flx`` (Speech.flx, sfx.flx, music.flx) carries a
fixed 60-byte (0x3C) header before its raw audio payload, byte-for-byte::

    0x00  sound_id          u32
    0x04  description       36 bytes, NUL-terminated ASCII (source asset
                             filename, e.g. "Avatar_03920.umt")
    0x28  data_length       u32  -- length of the payload that follows
    0x2C  frequency         u32  -- sample rate in Hz
    0x30  bits_per_sample   u32
    0x34  num_channels      u32
    0x38  encoding_type     u32  -- 0=PCM, 1=ADPCM, 2=EA MicroTalk
    0x3C  payload           data_length bytes

Reverse-engineered from a partial draft found in this project's own
prior exploration (``u9data/scripts/speech/u9_speech.py``), then
corrected and validated here against real archives: the draft's
``description`` field was only 20 bytes (0x4..0x18), leaving the next
16 bytes (0x18..0x28) treated as an unexplained gap -- that gap is
really the tail of longer filenames, silently truncated by the 20-byte
read. Confirmed by scanning 7,010 real Speech.flx entries: the longest
actual description is 33 bytes, fitting the corrected 36-byte field
with room to spare, with ``data_length`` (0x28) always immediately
following it with zero gap -- and ``0x3C + data_length`` matched the
real entry length exactly across every entry checked (Speech.flx,
sfx.flx, music.flx).

``encoding_type`` in practice, scanned across real archives:

- Speech.flx: 100% type 2 (EA MicroTalk) in every sample checked, always
  mono. Per vgmstream's ``flx.c`` (the reference .FLX parser), type-2
  entries carry an extra 4-byte total-sample-count field right at the
  start of what this module treats as :attr:`payload`, with the real
  MicroTalk bitstream starting 4 bytes later -- :func:`titan.u9.microtalk.decode_mono`
  expects and strips that prefix itself, so :attr:`payload` is left
  untouched here (matching every other encoding_type, whose payload is
  also the raw, unmodified slice from the archive).
- sfx.flx: a mix of type 0 (PCM) and type 1 (ADPCM, both mono and
  stereo -- mono and stereo entries use different block shapes, see
  :mod:`titan.u9.adpcm`).
- music.flx: 100% type 1 (ADPCM, stereo) in every sample checked.

Type 0 (PCM), type 1 (ADPCM, mono or stereo), and mono type 2 (EA
MicroTalk) can all be decoded to a playable WAV -- see
:meth:`U9SoundRecord.to_wav_bytes`.

Example::

    from titan.u9.flx_archive import U9FlxArchive
    from titan.u9.sound import U9SoundRecord

    archive = U9FlxArchive.from_file("sound/sfx.flx")
    record = U9SoundRecord.parse(archive.read_entry(0))
    if record.is_pcm:
        with open("out.wav", "wb") as f:
            f.write(record.to_wav_bytes())
"""

from __future__ import annotations

__all__ = [
    "U9SoundRecord",
    "U9SoundRecordError",
    "ENCODING_PCM",
    "ENCODING_ADPCM",
    "ENCODING_EA_MICROTALK",
    "ENCODING_NAMES",
]

import io
import struct
import wave
from dataclasses import dataclass

from titan.u9.adpcm import AdpcmDecodeError, decode_mono as decode_adpcm_mono, decode_stereo
from titan.u9.microtalk import MicroTalkDecodeError, decode_mono as decode_microtalk_mono

HEADER_SIZE = 0x3C
DESCRIPTION_OFFSET = 0x04
DESCRIPTION_SIZE = 0x24  # 36 bytes, 0x04..0x28 -- see module docstring
DATA_LENGTH_OFFSET = 0x28
FREQUENCY_OFFSET = 0x2C
BITS_PER_SAMPLE_OFFSET = 0x30
NUM_CHANNELS_OFFSET = 0x34
ENCODING_TYPE_OFFSET = 0x38

ENCODING_PCM = 0
ENCODING_ADPCM = 1
ENCODING_EA_MICROTALK = 2

ENCODING_NAMES = {
    ENCODING_PCM: "PCM",
    ENCODING_ADPCM: "ADPCM",
    ENCODING_EA_MICROTALK: "EA MicroTalk",
}


class U9SoundRecordError(Exception):
    """Raised when a sound record's header doesn't fit, or an unsupported op is requested."""


@dataclass(frozen=True)
class U9SoundRecord:
    """One decoded ``sound/*.flx`` entry header, plus its (possibly still-compressed) payload."""

    sound_id: int
    description: str
    frequency: int
    bits_per_sample: int
    num_channels: int
    encoding_type: int
    payload: bytes

    @classmethod
    def parse(cls, data: bytes) -> U9SoundRecord:
        if len(data) < HEADER_SIZE:
            raise U9SoundRecordError(
                f"data too small for a sound record header: {len(data)} bytes (need {HEADER_SIZE})"
            )

        sound_id = struct.unpack_from("<I", data, 0)[0]

        raw_desc = data[DESCRIPTION_OFFSET : DESCRIPTION_OFFSET + DESCRIPTION_SIZE]
        nul = raw_desc.find(b"\x00")
        if nul != -1:
            raw_desc = raw_desc[:nul]
        description = raw_desc.decode("ascii", errors="replace")

        data_length = struct.unpack_from("<I", data, DATA_LENGTH_OFFSET)[0]
        frequency = struct.unpack_from("<I", data, FREQUENCY_OFFSET)[0]
        bits_per_sample = struct.unpack_from("<I", data, BITS_PER_SAMPLE_OFFSET)[0]
        num_channels = struct.unpack_from("<I", data, NUM_CHANNELS_OFFSET)[0]
        encoding_type = struct.unpack_from("<I", data, ENCODING_TYPE_OFFSET)[0]

        payload = data[HEADER_SIZE : HEADER_SIZE + data_length]

        return cls(
            sound_id=sound_id,
            description=description,
            frequency=frequency,
            bits_per_sample=bits_per_sample,
            num_channels=num_channels,
            encoding_type=encoding_type,
            payload=payload,
        )

    @property
    def is_pcm(self) -> bool:
        return self.encoding_type == ENCODING_PCM

    @property
    def is_decodable_adpcm(self) -> bool:
        """True for ADPCM entries this project can decode: mono or stereo.

        Stereo entries (``music.flx``) use :func:`titan.u9.adpcm.decode_stereo`;
        mono entries (some ``sfx.flx`` entries) use the separate, smaller
        block shape decoded by :func:`titan.u9.adpcm.decode_mono` -- see
        that module's docstring for why they need distinct decoders.
        """
        return self.encoding_type == ENCODING_ADPCM and self.num_channels in (1, 2)

    @property
    def is_decodable_microtalk(self) -> bool:
        """True for EA MicroTalk entries this project can decode: mono only.

        Every real MicroTalk entry observed (Speech.flx) is mono; the
        ported decoder (:mod:`titan.u9.microtalk`) only implements the
        single-channel ``UTK_EA`` path.
        """
        return self.encoding_type == ENCODING_EA_MICROTALK and self.num_channels == 1

    @property
    def encoding_name(self) -> str:
        return ENCODING_NAMES.get(self.encoding_type, f"unknown ({self.encoding_type})")

    def to_wav_bytes(self) -> bytes:
        """
        Decode this record to a playable WAV file.

        Supported today: PCM (:data:`ENCODING_PCM`, repackaged directly),
        mono/stereo ADPCM (:data:`ENCODING_ADPCM`, decoded via
        :func:`titan.u9.adpcm.decode_mono`/:func:`titan.u9.adpcm.decode_stereo`),
        and mono EA MicroTalk (:data:`ENCODING_EA_MICROTALK`, decoded via
        :func:`titan.u9.microtalk.decode_mono`). Anything else raises
        rather than silently producing noise.
        """
        if self.is_pcm:
            pcm_bytes = self.payload
        elif self.is_decodable_adpcm:
            try:
                pcm_bytes = decode_stereo(self.payload) if self.num_channels == 2 else decode_adpcm_mono(self.payload)
            except AdpcmDecodeError as e:
                raise U9SoundRecordError(f"ADPCM decode failed: {e}") from e
        elif self.is_decodable_microtalk:
            try:
                pcm_bytes = decode_microtalk_mono(self.payload)
            except MicroTalkDecodeError as e:
                raise U9SoundRecordError(f"MicroTalk decode failed: {e}") from e
        else:
            raise U9SoundRecordError(
                f"cannot decode encoding_type={self.encoding_type} ({self.encoding_name}) "
                f"with {self.num_channels} channel(s) -- only PCM, mono/stereo ADPCM, and "
                f"mono EA MicroTalk are supported"
            )

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(max(1, self.num_channels))
            wf.setsampwidth(max(1, self.bits_per_sample // 8))
            wf.setframerate(max(1, self.frequency))
            wf.writeframes(pcm_bytes)
        return buf.getvalue()
