"""
Ultima 7 — Music extraction helpers.

Ultima 7 stores music as standard MIDI files packed inside Flex archives
(``ADLIBMUS.DAT``, ``MT32MUS.DAT``).  The end-game score (``ENDSCORE.XMI``)
and intro music (``INTROADM.DAT``, ``INTRORDM.DAT``) are XMIDI or Flex
archives of MIDI tracks.

This module provides :func:`extract_music` for batch extraction from a
music archive and :func:`convert_xmidi_file` for standalone XMIDI files.

Example::

    from titan.u7.music import extract_music

    extract_music("MT32MUS.DAT", "music_mt32/")
"""

from __future__ import annotations

__all__ = [
    "extract_music",
    "convert_xmidi_file",
    "convert_midi_mt32_to_gm",
]

import os
import struct
from pathlib import Path

from titan.u7.flex import U7FlexArchive
from titan.music import XMIDIConverter

# Signature bytes
_MIDI_MAGIC = b"MThd"
_XMIDI_FORM = b"FORM"

# General MIDI reset SysEx.
_GM_RESET = b"\xF0\x7E\x7F\x09\x01\xF7"

# Empirical U7 MT-32/AdLib -> SC-55/SC-88 friendly program remaps.
# Keys and values are 0-based MIDI program numbers.
_U7_GM_PROGRAM_MAP: dict[int, int] = {
    16: 5,
    36: 97,
    38: 89,
    48: 50,
    50: 51,
    93: 60,
    117: 116,
    122: 55,
}


def _read_varlen(data: bytes, pos: int) -> tuple[int, int]:
    """Read a standard MIDI variable-length integer from *pos*."""
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise ValueError("Unexpected end of MIDI varlen")
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            return value, pos
    return value, pos


def _write_varlen(value: int) -> bytes:
    """Encode *value* as a standard MIDI variable-length integer."""
    if value <= 0:
        return b"\x00"

    chunks = [value & 0x7F]
    value >>= 7
    while value:
        chunks.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(chunks))


def _mt32_program_to_gm(program: int) -> int:
    """Map an MT-32 program number to a General MIDI program number.

    This starts with identity mapping for common instruments while still
    allowing targeted remaps where SC-55/SC-88 playback benefits.
    """
    program = max(0, min(127, program))
    return _U7_GM_PROGRAM_MAP.get(program, program)


def _parse_meta_event(track_data: bytes, pos: int, delta: int) -> tuple[bytes, int]:
    """Read and encode one MIDI meta event from *track_data* at *pos*."""
    if pos >= len(track_data):
        return b"", len(track_data)

    meta_type = track_data[pos]
    pos += 1
    meta_len, pos = _read_varlen(track_data, pos)
    end = min(pos + meta_len, len(track_data))
    meta_payload = track_data[pos:end]
    pos = end

    event = bytearray()
    event.extend(_write_varlen(delta))
    event.append(0xFF)
    event.append(meta_type)
    event.extend(_write_varlen(len(meta_payload)))
    event.extend(meta_payload)
    return bytes(event), pos


def _skip_sysex_event(track_data: bytes, pos: int) -> int:
    """Skip one SysEx payload and return the updated position."""
    syx_len, pos = _read_varlen(track_data, pos)
    return min(pos + syx_len, len(track_data))


def _inject_gm_reset(event: bytearray, delta: int) -> int:
    """Append GM reset SysEx and return the remaining delta for next event."""
    event.extend(_write_varlen(delta))
    event.append(0xF0)
    event.extend(_write_varlen(len(_GM_RESET) - 1))
    event.extend(_GM_RESET[1:])
    return 0


def _parse_channel_event(
    track_data: bytes,
    pos: int,
    status: int,
    delta: int,
    *,
    add_gm_reset: bool,
    injected_reset: bool,
) -> tuple[bytes, int, bool]:
    """Read and encode one channel voice event."""
    cmd = status & 0xF0
    ch = status & 0x0F

    event = bytearray()

    if cmd in (0xC0, 0xD0):
        if pos >= len(track_data):
            return b"", len(track_data), injected_reset

        d0 = track_data[pos]
        pos += 1

        if cmd == 0xC0 and ch != 9:
            d0 = _mt32_program_to_gm(d0)
            if add_gm_reset and not injected_reset:
                delta = _inject_gm_reset(event, delta)
                injected_reset = True

        event.extend(_write_varlen(delta))
        event.append(status)
        event.append(d0)
        return bytes(event), pos, injected_reset

    if pos + 1 >= len(track_data):
        return b"", len(track_data), injected_reset

    d0 = track_data[pos]
    d1 = track_data[pos + 1]
    pos += 2

    event.extend(_write_varlen(delta))
    event.append(status)
    event.append(d0)
    event.append(d1)
    return bytes(event), pos, injected_reset


def _read_event_status(
    track_data: bytes,
    pos: int,
    running_status: int | None,
) -> tuple[int, int, int | None]:
    """Read event status, handling explicit and running status forms."""
    raw_status = track_data[pos]

    if raw_status >= 0x80:
        pos += 1
        status = raw_status
        if status < 0xF0:
            running_status = status
        elif status in (0xF0, 0xF7):
            running_status = None
        return status, pos, running_status

    if running_status is None:
        raise ValueError("Invalid running status in MIDI track")
    return running_status, pos, running_status


def _rewrite_track_to_gm(track_data: bytes, *, add_gm_reset: bool) -> bytes:
    """Rewrite one MIDI track for General MIDI playback compatibility."""
    pos = 0
    out = bytearray()
    running_status = None
    pending_delta = 0
    injected_reset = False

    while pos < len(track_data):
        delta, pos = _read_varlen(track_data, pos)
        delta += pending_delta
        pending_delta = 0

        if pos >= len(track_data):
            break

        status, pos, running_status = _read_event_status(
            track_data,
            pos,
            running_status,
        )

        if status == 0xFF:
            meta_event, pos = _parse_meta_event(track_data, pos, delta)
            out.extend(meta_event)
            continue

        if status in (0xF0, 0xF7):
            pos = _skip_sysex_event(track_data, pos)

            # Drop source SysEx. U7 MT-32 tracks commonly contain MT-32-
            # specific SysEx that sounds poor on SC-55/SC-88.
            pending_delta += delta
            continue

        channel_event, pos, injected_reset = _parse_channel_event(
            track_data,
            pos,
            status,
            delta,
            add_gm_reset=add_gm_reset,
            injected_reset=injected_reset,
        )
        out.extend(channel_event)

    return bytes(out)


def convert_midi_mt32_to_gm(midi_bytes: bytes) -> bytes | None:
    """Rewrite a standard MIDI file for better SC-55/SC-88 playback.

    The conversion preserves timing/structure, removes source SysEx, injects
    a General MIDI reset in the first track, and remaps program changes using
    the MT-32->GM mapping policy.
    """
    if len(midi_bytes) < 14 or midi_bytes[:4] != _MIDI_MAGIC:
        return None

    header_len = struct.unpack_from(">I", midi_bytes, 4)[0]
    if header_len < 6 or len(midi_bytes) < 8 + header_len:
        return None

    fmt, ntrks, division = struct.unpack_from(">HHH", midi_bytes, 8)
    cursor = 8 + header_len
    tracks: list[bytes] = []

    for track_idx in range(ntrks):
        if cursor + 8 > len(midi_bytes) or midi_bytes[cursor:cursor + 4] != b"MTrk":
            return None
        track_len = struct.unpack_from(">I", midi_bytes, cursor + 4)[0]
        start = cursor + 8
        end = start + track_len
        if end > len(midi_bytes):
            return None

        raw_track = midi_bytes[start:end]
        converted = _rewrite_track_to_gm(
            raw_track,
            add_gm_reset=(track_idx == 0),
        )
        tracks.append(converted)
        cursor = end

    out = bytearray()
    out.extend(_MIDI_MAGIC)
    out.extend(struct.pack(">I", 6))
    out.extend(struct.pack(">HHH", fmt, len(tracks), division))
    for trk in tracks:
        out.extend(b"MTrk")
        out.extend(struct.pack(">I", len(trk)))
        out.extend(trk)

    return bytes(out)


def _write_midi_export(
    outdir: str,
    base: str,
    tag: str,
    payload: bytes,
    *,
    gm_mode: bool,
    out_ext: str,
) -> bool:
    """Write one exported MIDI file after optional GM conversion."""
    out_path = os.path.join(outdir, f"{tag}_{base}{out_ext}")
    out_bytes = convert_midi_mt32_to_gm(payload) if gm_mode else payload
    if not out_bytes:
        return False
    with open(out_path, "wb") as f:
        f.write(out_bytes)
    return True


def _process_music_record(
    rec: bytes,
    *,
    idx: int,
    outdir: str,
    base: str,
    gm_mode: bool,
    out_ext: str,
    convert_xmidi: bool,
) -> int:
    """Handle a single U7 music archive record and return files written."""
    if not rec:
        return 0

    tag = f"{idx:04d}"

    if rec[:4] == _MIDI_MAGIC:
        return 1 if _write_midi_export(
            outdir,
            base,
            tag,
            rec,
            gm_mode=gm_mode,
            out_ext=out_ext,
        ) else 0

    if rec[:4] != _XMIDI_FORM:
        return 0

    if not convert_xmidi:
        out_path = os.path.join(outdir, f"{tag}_{base}.xmi")
        with open(out_path, "wb") as f:
            f.write(rec)
        return 1

    midi_bytes = XMIDIConverter.convert(rec)
    if not midi_bytes:
        return 0

    return 1 if _write_midi_export(
        outdir,
        base,
        tag,
        midi_bytes,
        gm_mode=gm_mode,
        out_ext=out_ext,
    ) else 0


def extract_music(
    filepath: str,
    outdir: str,
    *,
    convert_xmidi: bool = True,
    target: str = "mt32",
) -> int:
    """Extract music tracks from a U7 music Flex archive.

    Records that start with ``MThd`` are saved as ``.MID``.  Records that
    start with ``FORM`` (XMIDI) are converted to standard MIDI when
    *convert_xmidi* is ``True``, otherwise saved as ``.xmi``.

    ``target`` controls export style:

    - ``"mt32"``: preserve original track data, write ``.MID``
    - ``"gm"``: rewrite for General MIDI compatibility, write ``.MID``

    Returns the number of tracks written.
    """
    archive = U7FlexArchive.from_file(filepath)
    base = Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)
    gm_mode = target.lower() == "gm"
    out_ext = ".MID"

    written = 0

    for idx, rec in enumerate(archive.records):
        written += _process_music_record(
            rec,
            idx=idx,
            outdir=outdir,
            base=base,
            gm_mode=gm_mode,
            out_ext=out_ext,
            convert_xmidi=convert_xmidi,
        )

    return written


def convert_xmidi_file(filepath: str, outdir: str, *, target: str = "mt32") -> bool:
    """Convert a standalone XMIDI file (e.g. ``ENDSCORE.XMI``) to MIDI.

    Returns ``True`` on success.
    """
    with open(filepath, "rb") as f:
        data = f.read()

    midi_bytes = XMIDIConverter.convert(data)
    if not midi_bytes:
        return False

    gm_mode = target.lower() == "gm"
    out_ext = ".MID"
    out_bytes = convert_midi_mt32_to_gm(midi_bytes) if gm_mode else midi_bytes
    if not out_bytes:
        return False

    base = Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{base}{out_ext}")
    with open(out_path, "wb") as f:
        f.write(out_bytes)
    return True
