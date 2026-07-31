"""Ultima Online sound support."""

from __future__ import annotations

__all__ = ["UOSound", "UOSoundDecoder"]

from dataclasses import dataclass
import io
import wave

from titan.uo.indexed import UOIndexEntry

_SAMPLE_RATE = 22050
_CHANNELS = 1
_SAMPLE_WIDTH = 2
_HEADER_LENGTH = 40


@dataclass(frozen=True)
class UOSound:
    """Decoded UO sound payload."""

    index: int
    name: str
    pcm: bytes

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (_SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH)

    def to_wav(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(_CHANNELS)
            wav.setsampwidth(_SAMPLE_WIDTH)
            wav.setframerate(_SAMPLE_RATE)
            wav.writeframes(self.pcm)
        return buffer.getvalue()


class UOSoundDecoder:
    """Decode sound.mul or soundLegacyMUL.uop entries."""

    @staticmethod
    def decode(entry: UOIndexEntry) -> UOSound | None:
        if len(entry.data) <= _HEADER_LENGTH:
            return None

        raw_name = entry.data[:_HEADER_LENGTH]
        name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="replace").strip()
        pcm = entry.data[_HEADER_LENGTH:]
        if len(pcm) % _SAMPLE_WIDTH:
            pcm = pcm[:-1]
        if not pcm:
            return None

        return UOSound(entry.index, name, pcm)
