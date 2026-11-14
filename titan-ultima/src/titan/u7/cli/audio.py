"""``titan u7 music-export`` / ``voc-export`` / ``speech-export`` — music, sound and speech commands."""

from __future__ import annotations

__all__ = ["music_export_cmd", "voc_export_cmd", "speech_export_cmd"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer


def cmd_music_export(args: SimpleNamespace) -> int:
    """Extract music tracks from a U7 music Flex archive to MIDI."""
    from titan.u7.music import extract_music, convert_xmidi_file

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_midi"
    os.makedirs(outdir, exist_ok=True)
    target = (args.target or "mt32").lower()

    # Check if this is a standalone XMIDI file (e.g. ENDSCORE.XMI)
    with open(filepath, "rb") as f:
        magic = f.read(4)

    if magic == b"FORM":
        ok = convert_xmidi_file(filepath, outdir, target=target)
        if ok:
            flavor = "General MIDI" if target == "gm" else "MT-32 MIDI"
            print(f"Converted XMIDI to {flavor} in {outdir}/")
            return 0
        else:
            print("ERROR: Failed to convert XMIDI file", file=sys.stderr)
            return 1

    # Otherwise treat as a Flex archive containing MIDI / XMIDI records
    count = extract_music(filepath, outdir, target=target)
    ext = ".MID"
    flavor = "General MIDI" if target == "gm" else "MT-32 MIDI"
    print(f"Extracted {count} {flavor} track(s) as {ext} to {outdir}/")
    return 0


def cmd_voc_export(args: SimpleNamespace) -> int:
    """Decode a Creative Voice (.voc) file to WAV."""
    from titan.u7.sound import VocDecoder

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}.wav")
    VocDecoder.to_wav(filepath, out_path)

    with open(filepath, "rb") as f:
        data = f.read()
    pcm, rate = VocDecoder.decode(data)
    duration = len(pcm) / rate if rate else 0

    print(f"Decoded VOC to WAV: {out_path}")
    print(
        f"  Sample rate: {rate} Hz, duration: {duration:.1f}s, size: {len(pcm):,} bytes"
    )
    return 0


def cmd_speech_export(args: SimpleNamespace) -> int:
    """Extract and decode all speech from a U7 speech Flex archive."""
    from titan.u7.sound import VocDecoder
    from titan.u7.flex import U7FlexArchive

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_wav"

    # Check if this is a single VOC file or a Flex archive
    with open(filepath, "rb") as f:
        header = f.read(max(VOC_HEADER_CHECK, 0x60))

    if VocDecoder.is_voc(header):
        # Single VOC file
        os.makedirs(outdir, exist_ok=True)
        base = Path(filepath).stem
        out_path = os.path.join(outdir, f"{base}.wav")
        VocDecoder.to_wav(filepath, out_path)
        print(f"Decoded 1 VOC file to {outdir}/")
        return 0

    # Flex archive — extract and decode each VOC record
    archive = U7FlexArchive.from_file(filepath)
    os.makedirs(outdir, exist_ok=True)

    decoded = 0
    skipped = 0

    for idx, rec in enumerate(archive.records):
        if not rec:
            continue

        if VocDecoder.is_voc(rec):
            out_path = os.path.join(outdir, f"{idx:04d}.wav")
            VocDecoder.to_wav(filepath, out_path, data=rec)
            decoded += 1
        else:
            # Non-VOC record — save raw (might be text transcripts etc.)
            ext = ".txt" if _looks_like_text(rec) else ".dat"
            out_path = os.path.join(outdir, f"{idx:04d}{ext}")
            with open(out_path, "wb") as f:
                f.write(rec)
            skipped += 1

    print(f"Decoded {decoded} VOC file(s) to WAV in {outdir}/")
    if skipped:
        print(f"  ({skipped} non-VOC record(s) saved as raw)")
    return 0


# 26 bytes needed to check VOC magic
VOC_HEADER_CHECK = 26


def _looks_like_text(data: bytes) -> bool:
    """Heuristic: check if data is likely ASCII text."""
    if not data:
        return False
    # Check first 64 bytes for printable ASCII
    sample = data[:64]
    return all((0x20 <= b <= 0x7E) or b in (0x0A, 0x0D, 0x09) for b in sample)


def music_export_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to a U7 music archive (ADLIBMUS.DAT, MT32MUS.DAT) "
            "or standalone XMIDI file (ENDSCORE.XMI)"
        ),
    ],
    target: Annotated[
        Literal["mt32", "gm"],
        typer.Option(
            "--target",
            help="Export target: original MT-32 MIDI (.MID) or "
            "General MIDI rewrite (.MID)",
            case_sensitive=False,
        ),
    ] = "mt32",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract U7 music tracks from a Flex archive to MIDI files."""
    raise SystemExit(
        cmd_music_export(
            SimpleNamespace(
                file=file,
                output=output,
                target=target,
            )
        )
    )


def voc_export_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to a Creative Voice (.voc) file (e.g. INTROSND.DAT)"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decode a Creative Voice (.voc) file to WAV."""
    raise SystemExit(
        cmd_voc_export(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )


def speech_export_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to U7SPEECH.SPC (Flex of VOC records) or a single VOC file"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and decode U7 speech from a Flex archive of VOC files to WAV."""
    raise SystemExit(
        cmd_speech_export(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )
