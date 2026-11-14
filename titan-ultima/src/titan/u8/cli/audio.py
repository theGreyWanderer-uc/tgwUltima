"""``titan u8 music-export`` / ``sound-*`` — music and sound commands."""

from __future__ import annotations

__all__ = [
    "music_export_cmd",
    "sound_export_all_cmd",
    "sound_export_cmd",
    "sound_batch_cmd",
]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.flex import FlexArchive
from titan.music import XMIDIConverter
from titan.u8.sound import SonarcDecoder


def cmd_music_export(args: SimpleNamespace) -> int:
    """Extract and convert music from MUSIC.FLX or a standalone XMIDI file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        magic = f.read(4)

    outdir = args.output or f"{Path(filepath).stem}_midi"
    os.makedirs(outdir, exist_ok=True)

    # Standalone XMIDI file
    if magic == b"FORM":
        with open(filepath, "rb") as f:
            data = f.read()
        midi_data = XMIDIConverter.convert(data)
        if not midi_data:
            print("ERROR: Failed to convert XMIDI file", file=sys.stderr)
            return 1
        base = Path(filepath).stem
        out_path = os.path.join(outdir, f"{base}.mid")
        with open(out_path, "wb") as f:
            f.write(midi_data)
        print(f"Converted XMIDI to MIDI: {out_path}")
        return 0

    # Flex archive (MUSIC.FLX)
    archive = FlexArchive.from_file(filepath)
    base = Path(filepath).stem
    converted = 0
    skipped = 0

    for idx, rec in enumerate(archive.records):
        if not rec:
            continue
        if rec[:4] == b"FORM":
            midi_data = XMIDIConverter.convert(rec)
            if midi_data:
                name = archive.get_record_name(idx)
                safe = FlexArchive._safe_filename(name) if name else ""
                stem = f"{idx:04d}_{safe}" if safe else f"{idx:04d}_{base}"
                out_path = os.path.join(outdir, f"{stem}.mid")
                with open(out_path, "wb") as f:
                    f.write(midi_data)
                converted += 1
            else:
                skipped += 1
        else:
            skipped += 1

    print(f"Extracted {converted} music track(s) to {outdir}/")
    if skipped:
        print(f"  ({skipped} non-XMIDI record(s) skipped)")
    return 0


def cmd_sound_export_all(args: SimpleNamespace) -> int:
    """Extract and decode all sound effects from SOUND.FLX to WAV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_wav"
    os.makedirs(outdir, exist_ok=True)

    archive = FlexArchive.from_file(filepath)
    base = Path(filepath).stem
    decoded = 0
    skipped = 0

    for idx, rec in enumerate(archive.records):
        if not rec:
            continue
        result = SonarcDecoder.decode_file(rec)
        if result is None:
            skipped += 1
            continue

        pcm, sample_rate = result
        wav_data = SonarcDecoder.pcm_to_wav(pcm, sample_rate)
        name = archive.get_record_name(idx)
        safe = FlexArchive._safe_filename(name) if name else ""
        stem = f"{idx:04d}_{safe}" if safe else f"{idx:04d}_{base}"
        out_path = os.path.join(outdir, f"{stem}.wav")
        with open(out_path, "wb") as f:
            f.write(wav_data)
        decoded += 1

    print(f"Decoded {decoded} sound effect(s) to WAV in {outdir}/")
    if skipped:
        print(f"  ({skipped} non-audio record(s) skipped)")
    return 0


def cmd_sound_export(args: SimpleNamespace) -> int:
    """Decode a Sonarc audio file to WAV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        data = f.read()

    result = SonarcDecoder.decode_file(data)
    if result is None:
        print(f"ERROR: Failed to decode Sonarc audio: {filepath}", file=sys.stderr)
        return 1

    pcm, sample_rate = result
    wav_data = SonarcDecoder.pcm_to_wav(pcm, sample_rate)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}.wav")
    with open(out_path, "wb") as f:
        f.write(wav_data)

    duration = len(pcm) / sample_rate
    print(
        f"Decoded: {out_path}  ({sample_rate} Hz, {duration:.2f}s, {len(pcm)} samples)"
    )
    return 0


def cmd_sound_batch(args: SimpleNamespace) -> int:
    """Batch-decode all Sonarc .raw files in a directory to WAV."""
    srcdir = args.directory
    if not os.path.isdir(srcdir):
        print(f"ERROR: Directory not found: {srcdir}", file=sys.stderr)
        return 1

    outdir = args.output or os.path.join(srcdir, "wav")
    os.makedirs(outdir, exist_ok=True)

    raw_files = sorted(f for f in os.listdir(srcdir) if f.lower().endswith(".raw"))
    if not raw_files:
        print(f"No .raw files found in {srcdir}")
        return 0

    decoded = 0
    failed = 0

    for raw_file in raw_files:
        raw_path = os.path.join(srcdir, raw_file)
        try:
            with open(raw_path, "rb") as f:
                data = f.read()

            result = SonarcDecoder.decode_file(data)
            if result is None:
                print(f"  SKIP: {raw_file} (not valid Sonarc data)")
                failed += 1
                continue

            pcm, sample_rate = result
            wav_data = SonarcDecoder.pcm_to_wav(pcm, sample_rate)

            base = Path(raw_file).stem
            out_path = os.path.join(outdir, f"{base}.wav")
            with open(out_path, "wb") as f:
                f.write(wav_data)
            decoded += 1
        except Exception as e:
            print(f"  WARNING: Failed {raw_file}: {e}", file=sys.stderr)
            failed += 1

        outdir_display = outdir.rstrip("/\\") + "/"
        print(
            f"Batch decode complete: {decoded} WAVs created, "
            f"{failed} skipped -> {outdir_display}"
        )
    return 0


def music_export_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to MUSIC.FLX (Flex archive) or standalone XMIDI file"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and convert music from MUSIC.FLX to MIDI files."""
    raise SystemExit(cmd_music_export(SimpleNamespace(file=file, output=output)))


def sound_export_all_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to SOUND.FLX (Flex archive of Sonarc audio)")
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and decode all sound effects from SOUND.FLX to WAV."""
    raise SystemExit(
        cmd_sound_export_all(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )


def sound_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .raw Sonarc audio file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decode a Sonarc audio file (.raw) to WAV."""
    raise SystemExit(cmd_sound_export(SimpleNamespace(file=file, output=output)))


def sound_batch_cmd(
    directory: Annotated[str, typer.Argument(help="Directory containing .raw files")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <dir>/wav/)"),
    ] = None,
) -> None:
    """Batch-decode all Sonarc .raw files in a directory to WAV."""
    raise SystemExit(
        cmd_sound_batch(
            SimpleNamespace(
                directory=directory,
                output=output,
            )
        )
    )
