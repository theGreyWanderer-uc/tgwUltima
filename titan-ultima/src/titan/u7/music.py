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

__all__ = ["extract_music", "convert_xmidi_file"]

import os
from pathlib import Path

from titan.u7.flex import U7FlexArchive
from titan.music import XMIDIConverter

# Signature bytes
_MIDI_MAGIC = b"MThd"
_XMIDI_FORM = b"FORM"


def extract_music(
    filepath: str,
    outdir: str,
    *,
    convert_xmidi: bool = True,
) -> int:
    """Extract music tracks from a U7 music Flex archive.

    Records that start with ``MThd`` are saved as ``.mid``.  Records that
    start with ``FORM`` (XMIDI) are converted to standard MIDI when
    *convert_xmidi* is ``True``, otherwise saved as ``.xmi``.

    Returns the number of tracks written.
    """
    archive = U7FlexArchive.from_file(filepath)
    base = Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    written = 0
    for idx, rec in enumerate(archive.records):
        if not rec:
            continue

        tag = f"{idx:04d}"
        if rec[:4] == _MIDI_MAGIC:
            out_path = os.path.join(outdir, f"{tag}_{base}.mid")
            with open(out_path, "wb") as f:
                f.write(rec)
            written += 1
        elif rec[:4] == _XMIDI_FORM and convert_xmidi:
            midi_bytes = XMIDIConverter.convert(rec)
            if midi_bytes:
                out_path = os.path.join(outdir, f"{tag}_{base}.mid")
                with open(out_path, "wb") as f:
                    f.write(midi_bytes)
                written += 1
        elif rec[:4] == _XMIDI_FORM:
            out_path = os.path.join(outdir, f"{tag}_{base}.xmi")
            with open(out_path, "wb") as f:
                f.write(rec)
            written += 1

    return written


def convert_xmidi_file(filepath: str, outdir: str) -> bool:
    """Convert a standalone XMIDI file (e.g. ``ENDSCORE.XMI``) to MIDI.

    Returns ``True`` on success.
    """
    with open(filepath, "rb") as f:
        data = f.read()

    midi_bytes = XMIDIConverter.convert(data)
    if not midi_bytes:
        return False

    base = Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{base}.mid")
    with open(out_path, "wb") as f:
        f.write(midi_bytes)
    return True
