"""Safe replacement helpers for Ultima IX FLX sound records.

Editable WAV input is deliberately conservative: PCM, 16-bit little-endian,
and the target record's existing sample rate and channel count.  The resulting
U9 record uses encoding type 0 (PCM).  Native ADPCM and MicroTalk encoders are
not currently available; exact encoded payloads can still be replaced through
``.payload.bin`` or complete ``.record.bin`` files.
"""

from __future__ import annotations

__all__ = [
    "U9SoundWriteError",
    "discover_sound_replacements",
    "replace_sound_record_from_source",
    "replace_sound_record_from_wav",
    "replace_sound_record_payload",
    "serialize_sound_record",
]

import io
import re
import struct
import wave
from pathlib import Path

from titan.u9.sound import (
    DESCRIPTION_SIZE,
    ENCODING_EA_MICROTALK,
    ENCODING_PCM,
    HEADER_SIZE,
    U9SoundRecord,
    U9SoundRecordError,
)

MAX_U32 = 0xFFFFFFFF
_SOURCE_PATTERN = re.compile(
    r"^(?P<entry>\d+)(?:[_ -].*)?\.(?P<kind>wav|payload\.bin|record\.bin)$",
    re.IGNORECASE,
)


class U9SoundWriteError(Exception):
    """Raised when source audio cannot safely replace a U9 sound record."""


def serialize_sound_record(record: U9SoundRecord) -> bytes:
    """Serialize a sound record with a validated 60-byte header."""
    try:
        description = record.description.encode("ascii")
    except UnicodeEncodeError as error:
        raise U9SoundWriteError("description must contain ASCII characters") from error
    if len(description) > DESCRIPTION_SIZE:
        raise U9SoundWriteError(
            f"description is {len(description)} bytes; maximum is {DESCRIPTION_SIZE}"
        )
    if len(record.payload) > MAX_U32:
        raise U9SoundWriteError("audio payload exceeds the FLX record's u32 length")
    for label, value in (
        ("sound ID", record.sound_id),
        ("frequency", record.frequency),
        ("bits per sample", record.bits_per_sample),
        ("channel count", record.num_channels),
        ("encoding type", record.encoding_type),
    ):
        if not 0 <= value <= MAX_U32:
            raise U9SoundWriteError(f"{label} {value} does not fit an unsigned u32")

    header = bytearray(HEADER_SIZE)
    struct.pack_into("<I", header, 0x00, record.sound_id)
    header[0x04 : 0x04 + len(description)] = description
    struct.pack_into(
        "<5I",
        header,
        0x28,
        len(record.payload),
        record.frequency,
        record.bits_per_sample,
        record.num_channels,
        record.encoding_type,
    )
    return bytes(header) + record.payload


def _parse_target(data: bytes) -> U9SoundRecord:
    try:
        record = U9SoundRecord.parse(data)
    except U9SoundRecordError as error:
        raise U9SoundWriteError(str(error)) from error
    declared = struct.unpack_from("<I", data, 0x28)[0]
    if len(data) != HEADER_SIZE + declared:
        raise U9SoundWriteError(
            f"target record length is {len(data)}, but its header declares "
            f"{HEADER_SIZE + declared}"
        )
    return record


def replace_sound_record_payload(data: bytes, payload: bytes) -> bytes:
    """Replace native encoded payload bytes while preserving all header fields."""
    record = _parse_target(data)
    return serialize_sound_record(
        U9SoundRecord(
            record.sound_id,
            record.description,
            record.frequency,
            record.bits_per_sample,
            record.num_channels,
            record.encoding_type,
            bytes(payload),
        )
    )


def replace_sound_record_from_wav(
    data: bytes, wav_data: bytes, *, description: str | None = None
) -> bytes:
    """Convert a compatible uncompressed PCM WAV into a type-0 U9 record."""
    target = _parse_target(data)
    if target.encoding_type == ENCODING_EA_MICROTALK:
        raise U9SoundWriteError(
            "WAV import into a MicroTalk speech slot is disabled because Titan "
            "cannot encode the native speech codec; use .payload.bin or .record.bin"
        )
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as source:
            if source.getcomptype() != "NONE":
                raise U9SoundWriteError("source WAV must be uncompressed PCM")
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            frequency = source.getframerate()
            frames = source.readframes(source.getnframes())
    except (EOFError, wave.Error) as error:
        raise U9SoundWriteError(f"invalid WAV source: {error}") from error

    if sample_width != 2:
        raise U9SoundWriteError(
            f"source WAV is {sample_width * 8}-bit; U9 import requires 16-bit PCM"
        )
    if channels != target.num_channels:
        raise U9SoundWriteError(
            f"source WAV has {channels} channel(s); target requires {target.num_channels}"
        )
    if frequency != target.frequency:
        raise U9SoundWriteError(
            f"source WAV is {frequency} Hz; target requires {target.frequency} Hz"
        )
    replacement = U9SoundRecord(
        target.sound_id,
        target.description if description is None else description,
        frequency,
        16,
        channels,
        ENCODING_PCM,
        frames,
    )
    return serialize_sound_record(replacement)


def replace_sound_record_from_source(
    data: bytes,
    source: str | Path,
    *,
    expected_entry_id: int,
    description: str | None = None,
) -> bytes:
    """Build a replacement from ``.wav``, ``.payload.bin``, or ``.record.bin``."""
    path = Path(source)
    lower_name = path.name.casefold()
    try:
        source_data = path.read_bytes()
    except OSError as error:
        raise U9SoundWriteError(f"could not read {path}: {error}") from error
    target = _parse_target(data)
    if target.sound_id != expected_entry_id:
        raise U9SoundWriteError(
            f"target slot {expected_entry_id} contains sound ID {target.sound_id}"
        )
    if lower_name.endswith(".record.bin"):
        replacement = _parse_target(source_data)
        if replacement.sound_id != expected_entry_id:
            raise U9SoundWriteError(
                f"replacement record has sound ID {replacement.sound_id}; "
                f"target slot is {expected_entry_id}"
            )
        return source_data
    if lower_name.endswith(".payload.bin"):
        return replace_sound_record_payload(data, source_data)
    if lower_name.endswith(".wav"):
        return replace_sound_record_from_wav(data, source_data, description=description)
    raise U9SoundWriteError("source must end in .wav, .payload.bin, or .record.bin")


def discover_sound_replacements(directory: str | Path) -> dict[int, Path]:
    """Find batch sources named ``<entry>[_label].<supported extension>``."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise U9SoundWriteError(f"replacement directory not found: {root}")
    replacements: dict[int, Path] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        match = _SOURCE_PATTERN.match(path.name)
        if not match:
            continue
        entry_id = int(match.group("entry"))
        if entry_id in replacements:
            raise U9SoundWriteError(
                f"multiple replacement files select entry {entry_id}: "
                f"{replacements[entry_id].name}, {path.name}"
            )
        replacements[entry_id] = path
    if not replacements:
        raise U9SoundWriteError(
            f"no <entry>.wav, <entry>.payload.bin, or <entry>.record.bin files in {root}"
        )
    return replacements
