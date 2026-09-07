from __future__ import annotations

import io
import struct
import wave
from pathlib import Path

import pytest

from titan.u9.sound import ENCODING_ADPCM, ENCODING_EA_MICROTALK, U9SoundRecord
from titan.u9.sound_writer import (
    U9SoundWriteError,
    discover_sound_replacements,
    replace_sound_record_from_wav,
    replace_sound_record_payload,
)


def _record(encoding: int = ENCODING_ADPCM, channels: int = 1) -> bytes:
    header = bytearray(0x3C)
    struct.pack_into("<I", header, 0, 1322)
    header[4:12] = b"EASports"
    struct.pack_into("<5I", header, 0x28, 15, 22050, 16, channels, encoding)
    return bytes(header) + bytes(15)


def _wav(channels: int = 1, rate: int = 22050) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(struct.pack("<4h", 1, -1, 2, -2))
    return output.getvalue()


def test_wav_import_preserves_identity_and_writes_pcm() -> None:
    replacement = replace_sound_record_from_wav(_record(), _wav())
    parsed = U9SoundRecord.parse(replacement)
    assert parsed.sound_id == 1322
    assert parsed.description == "EASports"
    assert parsed.encoding_type == 0
    assert parsed.payload == struct.pack("<4h", 1, -1, 2, -2)


def test_wav_import_rejects_channel_mismatch_and_microtalk() -> None:
    with pytest.raises(U9SoundWriteError, match="target requires 1"):
        replace_sound_record_from_wav(_record(), _wav(channels=2))
    with pytest.raises(U9SoundWriteError, match="MicroTalk"):
        replace_sound_record_from_wav(_record(ENCODING_EA_MICROTALK), _wav())


def test_native_payload_import_preserves_codec() -> None:
    replacement = replace_sound_record_payload(_record(), b"native")
    parsed = U9SoundRecord.parse(replacement)
    assert parsed.encoding_type == ENCODING_ADPCM
    assert parsed.payload == b"native"


def test_batch_discovery_supports_all_source_types(tmp_path: Path) -> None:
    for name in ("7.wav", "8_label.payload.bin", "0009-x.record.bin"):
        (tmp_path / name).write_bytes(b"x")
    found = discover_sound_replacements(tmp_path)
    assert sorted(found) == [7, 8, 9]


def test_batch_discovery_rejects_duplicate_entry(tmp_path: Path) -> None:
    (tmp_path / "7.wav").write_bytes(b"x")
    (tmp_path / "0007-copy.record.bin").write_bytes(b"x")
    with pytest.raises(U9SoundWriteError, match="multiple"):
        discover_sound_replacements(tmp_path)
