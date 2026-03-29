"""
XMIDI to Standard MIDI converter.

Provides :class:`XMIDIConverter` for converting XMIDI (Extended MIDI, Miles
Sound System / AIL) to Standard MIDI Format 0 (single-track) or Format 1
(multi-track).

Example::

    from titan.music import XMIDIConverter

    with open("0044.xmi", "rb") as f:
        xmidi_data = f.read()

    midi = XMIDIConverter.convert(xmidi_data)
    if midi:
        with open("0044.mid", "wb") as f:
            f.write(midi)
"""

from __future__ import annotations

__all__ = ["XMIDIConverter"]

import struct
from typing import Optional


class XMIDIConverter:
    """
    Convert XMIDI (Extended MIDI) format to Standard MIDI Format 0 or 1.

    XMIDI is an IFF-based format used by Miles Sound System / AIL.
    Two layouts exist:

    * **Single-track** (``FORM XMID``) — one ``TIMB`` + one ``EVNT``.
      Converted to MIDI Format 0.
    * **Multi-track** (``FORM XDIR`` → ``CAT  XMID`` → N×``FORM XMID``) —
      each ``FORM XMID`` holds its own ``EVNT``.  Converted to MIDI Format 1.

    Key differences from standard MIDI:

    - Delays are encoded as note-count (number of intervals to skip),
      not as variable-length delta times.  In practice the EVNT data uses
      XMIDI delta encoding where byte < 0x80 is a literal delay value
      (ticks) and byte >= 0x80 is a MIDI event.
    - Tempo is fixed at 120 BPM with PPQN = 60 (one tick = one 1/120th note).
    - FOR/NEXT loop controllers (CC#116/117) for looping.
    """

    XMIDI_PPQN: int = 60  # Pulses per quarter note in XMIDI

    @classmethod
    def convert(cls, xmidi_data: bytes) -> Optional[bytes]:
        """
        Convert XMIDI to Standard MIDI (Format 0 for one track, Format 1 for
        multiple tracks).

        Walks the IFF tree to locate every ``EVNT`` chunk inside a
        ``FORM XMID`` container.  Single-track files produce Format 0;
        multi-track files (``FORM XDIR`` / ``CAT  XMID``) produce Format 1.

        Returns standard MIDI bytes or ``None`` on failure.
        """
        evnt_chunks = cls._collect_xmid_evnts(xmidi_data)
        if not evnt_chunks:
            return None

        tracks = []
        for evnt_data in evnt_chunks:
            track = cls._convert_evnt_to_track(evnt_data)
            if track:
                tracks.append(track)

        if not tracks:
            return None

        if len(tracks) == 1:
            return cls._build_midi_file(tracks[0])
        return cls._build_midi_file_format1(tracks)

    # ------------------------------------------------------------------
    # IFF tree walker
    # ------------------------------------------------------------------

    @classmethod
    def _collect_xmid_evnts(cls, data: bytes) -> list[bytes]:
        """Return a list of raw EVNT payloads from all FORM XMID containers."""
        evnts: list[bytes] = []
        cls._walk_iff(data, 0, len(data), evnts)
        return evnts

    @classmethod
    def _walk_iff(
        cls,
        data: bytes,
        start: int,
        end: int,
        evnts: list[bytes],
    ) -> None:
        """Recursively walk IFF chunks and collect EVNT from FORM XMID."""
        pos = start
        while pos + 8 <= min(end, len(data)):
            cid = data[pos:pos + 4]
            clen = struct.unpack_from(">I", data, pos + 4)[0]
            chunk_end = pos + 8 + clen
            if chunk_end > len(data):
                break

            if cid == b"FORM":
                sub_type = data[pos + 8:pos + 12]
                if sub_type == b"XMID":
                    # Leaf: find the EVNT within this FORM XMID
                    evnt_pos = cls._find_chunk_in_range(
                        data, b"EVNT", pos + 12, chunk_end
                    )
                    if evnt_pos is not None:
                        evnt_len = struct.unpack_from(">I", data, evnt_pos + 4)[0]
                        evnts.append(data[evnt_pos + 8:evnt_pos + 8 + evnt_len])
                else:
                    # FORM XDIR (or other) — recurse into body
                    cls._walk_iff(data, pos + 12, chunk_end, evnts)
            elif cid in (b"CAT ", b"LIST"):
                # Container — recurse past the 4-byte sub-type
                cls._walk_iff(data, pos + 12, chunk_end, evnts)

            # IFF chunks are 2-byte aligned
            pos = chunk_end + (clen & 1)

    @classmethod
    def _find_chunk_in_range(
        cls,
        data: bytes,
        chunk_id: bytes,
        start: int,
        end: int,
    ) -> Optional[int]:
        """Find the first IFF chunk with *chunk_id* within [start, end)."""
        pos = start
        while pos + 8 <= min(end, len(data)):
            cid = data[pos:pos + 4]
            clen = struct.unpack_from(">I", data, pos + 4)[0]
            if cid == chunk_id:
                return pos
            pos += 8 + clen + (clen & 1)
        return None

    @classmethod
    def _convert_evnt_to_track(cls, evnt: bytes) -> Optional[bytes]:
        """
        Convert XMIDI EVNT data to a standard MIDI track chunk.

        XMIDI note-on events embed a VLQ duration after the velocity byte.
        We schedule explicit note-off events at (current_tick + duration),
        collect all events with absolute tick stamps, sort by tick, then
        serialise with delta-time encoding.

        Faithful to Pentagram's XMidiFile::ConvertFiletoList:

        - Tempo meta events (0xFF 0x51) are skipped — XMIDI runs at a fixed
          120 Hz tick rate regardless of embedded tempo.  A fixed 120 BPM
          tempo is injected so that standard MIDI players reproduce the
          correct speed (PPQN 60 x 120 BPM = 120 ticks/sec).
        - XMIDI-specific controllers (CC 110–120) are stripped since standard
          MIDI players do not understand them and some may cause glitches.
        """
        # XMIDI-specific CC numbers (0x6E–0x78) that must be stripped
        XMIDI_CCS = set(range(0x6E, 0x79))  # 110–120 inclusive

        # Collect (absolute_tick, sort_priority, event_bytes | None)
        events: list[Optional[tuple[int, int, bytes]]] = []
        pos = 0
        current_tick = 0
        running_status = 0

        # Track pending note-off indices by (channel, note)
        pending_note_offs: dict[tuple[int, int], tuple[int, int]] = {}

        # Insert fixed tempo: 120 BPM = 500 000 us/beat
        events.append((0, -1, bytes([0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20])))

        while pos < len(evnt):
            # XMIDI delay: sum consecutive bytes < 0x80 (GetVLQ2)
            delay = 0
            while pos < len(evnt) and evnt[pos] < 0x80:
                delay += evnt[pos]
                pos += 1
            current_tick += delay

            if pos >= len(evnt):
                break

            status = evnt[pos]

            # Meta event
            if status == 0xFF:
                pos += 1
                if pos >= len(evnt):
                    break
                meta_type = evnt[pos]
                pos += 1
                meta_len, bytes_read = cls._read_vlq(evnt, pos)
                pos += bytes_read

                if meta_type == 0x2F:
                    pos += meta_len
                    break

                if meta_type == 0x51:
                    pos += meta_len
                    continue

                evt = bytes([0xFF, meta_type]) + cls._to_vlq(meta_len) + evnt[pos:pos + meta_len]
                pos += meta_len
                events.append((current_tick, 1, evt))
                continue

            # SysEx
            if status in (0xF0, 0xF7):
                pos += 1
                sysex_len, bytes_read = cls._read_vlq(evnt, pos)
                pos += bytes_read
                evt = bytes([status]) + cls._to_vlq(sysex_len) + evnt[pos:pos + sysex_len]
                pos += sysex_len
                events.append((current_tick, 1, evt))
                continue

            # Regular MIDI channel event
            if status & 0x80:
                running_status = status
                pos += 1

            event_type = running_status & 0xF0

            if event_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                if pos + 2 > len(evnt):
                    break
                data1 = evnt[pos]
                data2 = evnt[pos + 1]
                pos += 2

                if event_type == 0x90 and data2 > 0:
                    # XMIDI note-on: read VLQ duration, schedule note-off
                    channel = running_status & 0x0F
                    key = (channel, data1)

                    # Cancel stale note-off if this pitch is still active
                    if key in pending_note_offs:
                        old_off_tick, old_idx = pending_note_offs[key]
                        if old_off_tick > current_tick:
                            events[old_idx] = None

                    events.append((current_tick, 2,
                                   bytes([running_status, data1, data2])))
                    duration = 0
                    if pos < len(evnt):
                        duration, dur_bytes = cls._read_vlq(evnt, pos)
                        pos += dur_bytes
                    note_off_tick = current_tick + duration
                    note_off_idx = len(events)
                    events.append((note_off_tick, 0,
                                   bytes([running_status, data1, 0])))
                    pending_note_offs[key] = (note_off_tick, note_off_idx)
                elif event_type == 0x80:
                    events.append((current_tick, 0,
                                   bytes([running_status, data1, data2])))
                elif event_type == 0xB0 and data1 in XMIDI_CCS:
                    pass  # Strip XMIDI-specific controllers
                else:
                    events.append((current_tick, 1,
                                   bytes([running_status, data1, data2])))

            elif event_type in (0xC0, 0xD0):
                if pos >= len(evnt):
                    break
                data1 = evnt[pos]
                pos += 1
                events.append((current_tick, 1,
                               bytes([running_status, data1])))
            else:
                pos += 1  # skip unknown

        # Remove cancelled note-off entries, then sort by (tick, priority)
        live_events: list[tuple[int, int, bytes]] = [
            e for e in events if e is not None
        ]
        live_events.sort(key=lambda e: (e[0], e[1]))

        # Add all-notes-off on every channel used, then end-of-track
        max_tick = live_events[-1][0] if live_events else current_tick
        used_channels: set[int] = set()
        for _, _, ed in live_events:
            if len(ed) >= 1 and (ed[0] & 0x80) and ed[0] != 0xFF and ed[0] not in (0xF0, 0xF7):
                used_channels.add(ed[0] & 0x0F)
        for ch in sorted(used_channels):
            live_events.append((max_tick, 3, bytes([0xB0 | ch, 123, 0])))
        live_events.append((max_tick, 4, bytes([0xFF, 0x2F, 0x00])))

        # Re-sort to include cleanup events
        live_events.sort(key=lambda e: (e[0], e[1]))

        # Serialise with delta times
        out = bytearray()
        prev_tick = 0
        for tick, _, event_data in live_events:
            delta = max(0, tick - prev_tick)
            out.extend(cls._to_vlq(delta))
            out.extend(event_data)
            prev_tick = tick

        return bytes(out)

    @classmethod
    def _build_midi_file(cls, track_data: bytes) -> bytes:
        """Build a complete Standard MIDI Format 0 file."""
        out = bytearray()

        # MThd header
        out.extend(b"MThd")
        out.extend(struct.pack(">I", 6))       # Header length
        out.extend(struct.pack(">H", 0))       # Format 0
        out.extend(struct.pack(">H", 1))       # 1 track
        out.extend(struct.pack(">H", cls.XMIDI_PPQN))

        # MTrk
        out.extend(b"MTrk")
        out.extend(struct.pack(">I", len(track_data)))
        out.extend(track_data)

        return bytes(out)

    @classmethod
    def _build_midi_file_format1(cls, tracks: list[bytes]) -> bytes:
        """Build a Standard MIDI Format 1 file with multiple tracks."""
        out = bytearray()

        # MThd header
        out.extend(b"MThd")
        out.extend(struct.pack(">I", 6))
        out.extend(struct.pack(">H", 1))                  # Format 1
        out.extend(struct.pack(">H", len(tracks)))        # N tracks
        out.extend(struct.pack(">H", cls.XMIDI_PPQN))

        for track_data in tracks:
            out.extend(b"MTrk")
            out.extend(struct.pack(">I", len(track_data)))
            out.extend(track_data)

        return bytes(out)

    @staticmethod
    def _to_vlq(value: int) -> bytes:
        """Encode an integer as MIDI variable-length quantity."""
        if value < 0:
            value = 0
        result = bytearray()
        result.append(value & 0x7F)
        value >>= 7
        while value:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.reverse()
        return bytes(result)

    @staticmethod
    def _read_vlq(data: bytes, pos: int) -> tuple[int, int]:
        """Read a MIDI variable-length quantity. Returns ``(value, bytes_read)``."""
        value = 0
        bytes_read = 0
        while pos < len(data):
            b = data[pos]
            value = (value << 7) | (b & 0x7F)
            pos += 1
            bytes_read += 1
            if not (b & 0x80):
                break
        return value, bytes_read
