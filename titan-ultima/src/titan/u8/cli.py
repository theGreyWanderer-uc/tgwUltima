"""
Ultima 8: Pagan — CLI sub-app.

Registered as ``titan u8 <command>`` in the root CLI.
All U8-specific commands live here; game-agnostic commands (flex-*,
music-*, setup, config) remain in the root :mod:`titan.cli`.
"""

from __future__ import annotations

__all__ = ["u8_app"]

import copy
import os
import re
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer
from PIL import Image, ImageDraw

from titan._config import cfg as _cfg
from titan._version import TITAN_VERSION
from titan.flex import (
    FlexArchive,
    FLEX_HEADER_SIZE,
    get_extension_for_flex,
)
from titan.music import XMIDIConverter
from titan.palette import U8Palette
from titan.u8.shape import U8Shape
from titan.u8.sound import SonarcDecoder
from titan.u8.save import U8SaveArchive
from titan.u8.typeflag import U8TypeFlags
from titan.u8.map import U8MapRenderer, U8MapSampler
from titan.u8.credits import decrypt_credit_text
from titan.u8.xformpal import U8_XFORM_PALETTE as _U8_XFORM_PAL


# ============================================================================
# Typer sub-app
# ============================================================================

u8_app = typer.Typer(
    name="u8",
    help="Ultima 8: Pagan — shape, map, music, sound, save, and data commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — PALETTE
# ============================================================================

def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export a U8 palette as a PNG swatch image."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    pal = U8Palette.from_file(filepath)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}_palette.png")
    img = pal.to_pil_image(swatch_size=16)
    img.save(out_path)
    print(f"Palette swatch saved: {out_path}  (256 colors, 16x16 grid)")

    txt_path = os.path.join(outdir, f"{base}_palette.txt")
    with open(txt_path, "w") as f:
        f.write(f"# Palette from {filepath}\n")
        f.write("# Index  R    G    B    Hex\n")
        for i, (r, g, b) in enumerate(pal.colors):
            f.write(f"{i:3d}    {r:3d}  {g:3d}  {b:3d}  #{r:02X}{g:02X}{b:02X}\n")
    print(f"Palette text dump: {txt_path}")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SHAPE
# ============================================================================

def cmd_shape_export(args: SimpleNamespace) -> int:
    """Export frames from a single Shape file to PNG images."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    if args.palette and os.path.isfile(args.palette):
        pal = U8Palette.from_file(args.palette)
    else:
        print("WARNING: No palette specified, using greyscale fallback",
              file=sys.stderr)
        pal = U8Palette.default_palette()

    shape = U8Shape.from_file(filepath)
    if not shape.frames:
        print(f"ERROR: No frames found in {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    images = shape.to_pngs(pal, transparent=True)

    saved = 0
    for i, img in enumerate(images):
        if img.width <= 1 and img.height <= 1:
            continue
        out_path = os.path.join(outdir, f"{base}_f{i:04d}.png")
        img.save(out_path)
        saved += 1

    print(f"Exported {saved} frames from {os.path.basename(filepath)} "
          f"({len(shape.frames)} total) -> {outdir.rstrip('/\\')}/")
    return 0


def cmd_shape_batch(args: SimpleNamespace) -> int:
    """Batch-export all .shp files in a directory to PNG."""
    srcdir = args.directory
    if not os.path.isdir(srcdir):
        print(f"ERROR: Directory not found: {srcdir}", file=sys.stderr)
        return 1

    if args.palette and os.path.isfile(args.palette):
        pal = U8Palette.from_file(args.palette)
    else:
        print("WARNING: No palette specified, using greyscale fallback",
              file=sys.stderr)
        pal = U8Palette.default_palette()

    outdir = args.output or os.path.join(srcdir, "png")
    os.makedirs(outdir, exist_ok=True)

    shp_files = sorted(f for f in os.listdir(srcdir)
                       if f.lower().endswith(".shp"))
    if not shp_files:
        print(f"No .shp files found in {srcdir}")
        return 0

    total_frames = 0
    total_shapes = 0

    for shp_file in shp_files:
        shp_path = os.path.join(srcdir, shp_file)
        try:
            shape = U8Shape.from_file(shp_path)
            if not shape.frames:
                continue

            base = Path(shp_file).stem
            images = shape.to_pngs(pal, transparent=True)
            saved = 0
            for i, img in enumerate(images):
                if img.width <= 1 and img.height <= 1:
                    continue
                out_path = os.path.join(outdir, f"{base}_f{i:04d}.png")
                img.save(out_path)
                saved += 1

            if saved > 0:
                total_shapes += 1
                total_frames += saved
        except Exception as e:
            print(f"  WARNING: Failed {shp_file}: {e}", file=sys.stderr)

    print(f"Batch export complete: {total_frames} frames from "
          f"{total_shapes} shapes -> {outdir.rstrip('/\\')}/")
    return 0


def cmd_shape_import(args: SimpleNamespace) -> int:
    """Import PNG frames back into a U8 shape file."""
    png_dir = args.directory
    original_path = args.original
    output_path = args.output

    if not os.path.isdir(png_dir):
        print(f"ERROR: Directory not found: {png_dir}", file=sys.stderr)
        return 1
    if not os.path.isfile(original_path):
        print(f"ERROR: Original shape not found: {original_path}",
              file=sys.stderr)
        return 1

    if args.palette and os.path.isfile(args.palette):
        pal = U8Palette.from_file(args.palette)
    else:
        print("WARNING: No palette specified, using greyscale fallback",
              file=sys.stderr)
        pal = U8Palette.default_palette()

    original = U8Shape.from_file(original_path)
    if not original.frames:
        print(f"ERROR: Original shape has no frames: {original_path}",
              file=sys.stderr)
        return 1

    png_map: dict[int, str] = {}
    pattern = re.compile(r"_f(\d+)\.png$", re.IGNORECASE)
    for fname in sorted(os.listdir(png_dir)):
        m = pattern.search(fname)
        if m:
            idx = int(m.group(1))
            png_map[idx] = os.path.join(png_dir, fname)

    if not png_map:
        print(f"ERROR: No matching *_fNNNN.png files found in {png_dir}",
              file=sys.stderr)
        return 1

    new_shape = U8Shape()
    new_shape.header0 = original.header0
    new_shape.header1 = original.header1

    replaced = 0
    kept = 0

    for i, orig_frame in enumerate(original.frames):
        frame = U8Shape.Frame()
        frame.xoff = orig_frame.xoff
        frame.yoff = orig_frame.yoff
        frame.compressed = orig_frame.compressed
        frame.frame_unknown = orig_frame.frame_unknown
        frame.table_unknown = orig_frame.table_unknown

        if i in png_map:
            try:
                img = Image.open(png_map[i]).convert("RGBA")
            except Exception as e:
                print(f"  WARNING: Cannot read {png_map[i]}: {e}",
                      file=sys.stderr)
                frame.width = orig_frame.width
                frame.height = orig_frame.height
                frame.pixels = orig_frame.pixels
                new_shape.frames.append(frame)
                kept += 1
                continue

            frame.width = img.width
            frame.height = img.height
            frame.pixels = U8Shape.quantize_to_palette(img, pal)
            replaced += 1
        else:
            frame.width = orig_frame.width
            frame.height = orig_frame.height
            frame.pixels = orig_frame.pixels
            kept += 1

        new_shape.frames.append(frame)

    data = new_shape.to_bytes()

    if output_path is None:
        base = Path(original_path).stem
        output_path = os.path.join(png_dir, f"{base}_imported.shp")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(data)

    print(f"Shape imported: {replaced} frames replaced, {kept} kept from "
          f"original ({len(new_shape.frames)} total) -> {output_path}")
    print(f"  Output size: {len(data):,} bytes")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MUSIC (XMIDI)
# ============================================================================


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
                out_path = os.path.join(outdir, f"{idx:04d}_{base}.mid")
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


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SOUND (Sonarc)
# ============================================================================


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
        out_path = os.path.join(outdir, f"{idx:04d}_{base}.wav")
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
        print(f"ERROR: Failed to decode Sonarc audio: {filepath}",
              file=sys.stderr)
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
    print(f"Decoded: {out_path}  ({sample_rate} Hz, {duration:.2f}s, "
          f"{len(pcm)} samples)")
    return 0


def cmd_sound_batch(args: SimpleNamespace) -> int:
    """Batch-decode all Sonarc .raw files in a directory to WAV."""
    srcdir = args.directory
    if not os.path.isdir(srcdir):
        print(f"ERROR: Directory not found: {srcdir}", file=sys.stderr)
        return 1

    outdir = args.output or os.path.join(srcdir, "wav")
    os.makedirs(outdir, exist_ok=True)

    raw_files = sorted(f for f in os.listdir(srcdir)
                       if f.lower().endswith(".raw"))
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

    print(f"Batch decode complete: {decoded} WAVs created, "
          f"{failed} skipped -> {outdir.rstrip('/\\')}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — CREDITS / QUOTES
# ============================================================================

def cmd_credits_decrypt(args: SimpleNamespace) -> int:
    """Decrypt ECREDITS.DAT or QUOTES.DAT and write plain text."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        data = f.read()

    text = decrypt_credit_text(data)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Decrypted {len(data)} bytes -> {out_path}  ({len(text)} chars)")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — XFORMPAL
# ============================================================================

def cmd_xformpal_export(args: SimpleNamespace) -> int:
    """Export the U8 transform palette as a labelled PNG swatch + text dump."""
    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    cell = 48
    img = Image.new("RGBA", (16 * cell, cell + 20), (32, 32, 32, 255))
    draw = ImageDraw.Draw(img)
    for i, (r, g, b, a) in enumerate(_U8_XFORM_PAL):
        x0 = i * cell
        if a > 0:
            draw.rectangle([x0, 0, x0 + cell - 1, cell - 1],
                           fill=(r, g, b, 255))
        else:
            draw.rectangle([x0, 0, x0 + cell - 1, cell - 1],
                           fill=(0, 0, 0, 255))
        draw.text((x0 + 2, cell + 2), str(i), fill=(200, 200, 200, 255))

    img_path = os.path.join(outdir, "xformpal_swatch.png")
    img.save(img_path)

    txt_path = os.path.join(outdir, "xformpal.txt")
    descriptions = {
        8: "green -> dark grey (standard ghost/translucent)",
        9: "black -> very dark grey (shadow)",
        10: "yellow tint (poison/acid)",
        11: "white -> grey (frost/ethereal)",
        12: "red -> orange (fire/damage)",
        13: "blue glow (magic/mana)",
        14: "dark blue glow (deep water)",
    }
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("U8 Transform Palette (from graphics/XFormBlend.cpp)\n")
        f.write("=" * 55 + "\n")
        f.write("Used for translucent shape rendering (SI_TRANSL flag).\n")
        f.write("Blend: dest*(255-A)/255 + RGB\n\n")
        f.write(f"{'Idx':<5}{'R':>4}{'G':>4}{'B':>4}{'A':>4}  Description\n")
        f.write("-" * 55 + "\n")
        for i, (r, g, b, a) in enumerate(_U8_XFORM_PAL):
            desc = descriptions.get(i, "unused" if a == 0 else "")
            f.write(f"{i:<5}{r:>4}{g:>4}{b:>4}{a:>4}  {desc}\n")

    print(f"Exported: {img_path}")
    print(f"Exported: {txt_path}")

    filepath = getattr(args, 'file', None)
    if filepath and os.path.isfile(filepath):
        try:
            flex = FlexArchive.from_file(filepath)
            print(f"\nXFORMPAL.DAT is a Flex archive with "
                  f"{len(flex.records)} entries:")
            for i, rec in enumerate(flex.records):
                print(f"  Entry {i}: {len(rec)} bytes")
            if len(flex.records) >= 2 and len(flex.records[1]) == 32:
                print("\nEntry 1 (32 bytes) — 8 RGBA xform blend colours:")
                rec = flex.records[1]
                for j in range(8):
                    r = rec[j * 4]
                    g = rec[j * 4 + 1]
                    b = rec[j * 4 + 2]
                    a = rec[j * 4 + 3]
                    print(f"  [{j+8}] R={r:3d} G={g:3d} B={b:3d} A={a:3d}")
        except Exception as e:
            print(f"  (Could not parse {filepath} as Flex: {e})")

    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — TYPEFLAG
# ============================================================================

def cmd_typeflag_dump(args: SimpleNamespace) -> int:
    """Parse TYPEFLAG.DAT and dump all shape info as a readable table."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    entries = U8TypeFlags.from_file(filepath)

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "typeflag_dump.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"TYPEFLAG.DAT — {len(entries)} shapes\n")
        f.write("=" * 120 + "\n\n")

        header = (f"{'Shape':>6}  {'Flags':>6}  {'FlagNames':<48} "
                  f"{'Family':<12} {'Equip':<8} "
                  f"{'X':>2} {'Y':>2} {'Z':>2}  "
                  f"{'Anim':>4} {'AData':>5}  "
                  f"{'Wt':>3} {'Vol':>3}  {'Unk':>3}\n")
        f.write(header)
        f.write("-" * 120 + "\n")

        for e in entries:
            if (e.flags == 0 and e.family == 0 and e.equiptype == 0
                    and e.x == 0 and e.y == 0 and e.z == 0
                    and e.weight == 0 and e.volume == 0):
                continue

            flag_str = ",".join(e.flag_names()) or "-"
            f.write(f"{e.shape_num:>6}  0x{e.flags:04X}  {flag_str:<48} "
                    f"{e.family_name():<12} {e.equip_name():<8} "
                    f"{e.x:>2} {e.y:>2} {e.z:>2}  "
                    f"{e.animtype:>4} {e.animdata:>5}  "
                    f"{e.weight:>3} {e.volume:>3}  {e.unknown:>3}\n")

    print(f"Dumped {len(entries)} shapes -> {out_path}")

    families: dict[str, int] = {}
    flagged: dict[str, int] = {}
    for e in entries:
        fn = e.family_name()
        families[fn] = families.get(fn, 0) + 1
        for name in e.flag_names():
            flagged[name] = flagged.get(name, 0) + 1

    print(f"\nFamily distribution:")
    for fn, count in sorted(families.items(), key=lambda x: -x[1]):
        if fn == "generic" and count > 1000:
            print(f"  {fn:<14} {count:5d}  (most shapes)")
        else:
            print(f"  {fn:<14} {count:5d}")

    print(f"\nFlag counts:")
    for name, count in sorted(flagged.items(), key=lambda x: -x[1]):
        print(f"  {name:<18} {count:5d}")

    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — GUMPINFO
# ============================================================================

def cmd_gumpinfo_dump(args: SimpleNamespace) -> int:
    """Dump GUMPAGE.DAT container gump UI layout rectangles."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        data = f.read()

    count = len(data) // 8

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "gumpinfo_dump.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"GUMPAGE.DAT — {count} container gump UI rectangles\n")
        f.write("=" * 60 + "\n")
        f.write("Item-area rectangles within each container gump shape.\n")
        f.write("Used by ContainerGump to position held items inside "
                "bags, chests, etc.\n\n")
        f.write(f"{'Gump#':>6}  {'X':>5} {'Y':>5} {'W':>5} {'H':>5}  "
                f"{'X2':>5} {'Y2':>5}\n")
        f.write("-" * 60 + "\n")

        non_empty = 0
        for i in range(count):
            off = i * 8
            x1 = struct.unpack_from("<h", data, off)[0]
            y1 = struct.unpack_from("<h", data, off + 2)[0]
            x2 = struct.unpack_from("<h", data, off + 4)[0]
            y2 = struct.unpack_from("<h", data, off + 6)[0]
            w = x2 - x1
            h = y2 - y1
            if w == 0 and h == 0:
                continue
            f.write(f"{i+1:>6}  {x1:>5} {y1:>5} {w:>5} {h:>5}  "
                    f"{x2:>5} {y2:>5}\n")
            non_empty += 1

    print(f"Wrote {non_empty}/{count} non-empty gump areas -> {out_path}")
    print(f"(GUMPAGE.DAT defines container gump UI layout, not map data)")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — UNKCOFF
# ============================================================================

def cmd_unkcoff_dump(args: SimpleNamespace) -> int:
    """Dump UNKCOFF.DAT code-offset table."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        data = f.read()

    count = len(data) // 4
    if count == 0:
        print("ERROR: File is empty or too small", file=sys.stderr)
        return 1

    lines: list[str] = []
    lines.append(f"UNKCOFF.DAT — {count} code-offset entries")
    lines.append("=" * 60)
    lines.append("UNKnown COde OFFsets table.  Dev leftover, ignored "
                 "at runtime.")
    lines.append("Entry 0 is a magic/version value.  Remaining entries are")
    lines.append("segment:offset pairs for usecode class entry points.")
    lines.append("")
    lines.append(f"{'Index':>6}  {'Hex Value':>12}  {'Segment':>8}  "
                 f"{'Offset':>8}  Note")
    lines.append("-" * 60)

    for i in range(count):
        val = struct.unpack_from("<I", data, i * 4)[0]
        seg = (val >> 16) & 0xFFFF
        off = val & 0xFFFF
        if i == 0:
            note = "magic / version / total size?"
            lines.append(f"{i:>6}  0x{val:08X}      {'\u2014':>8}      "
                         f"{'\u2014':>8}  {note}")
        else:
            note = ""
            lines.append(f"{i:>6}  0x{val:08X}    0x{seg:04X}    "
                         f"0x{off:04X}  {note}")

    lines.append("")

    out_path = getattr(args, 'output', None)
    if out_path:
        outdir = out_path
        os.makedirs(outdir, exist_ok=True)
        fpath = os.path.join(outdir, "unkcoff_dump.txt")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Dumped {count} entries -> {fpath}")
    else:
        print("\n".join(lines))

    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SAVE ARCHIVE
# ============================================================================

def cmd_save_list(args: SimpleNamespace) -> int:
    """List contents of a U8 save file."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U8SaveArchive.from_file(filepath)
    entries = save.list_entries()

    print(f"U8 Save Archive: {filepath}")
    print(f"Entries: {len(entries)}")
    print(f"{'Name':<24} {'Size':>10}")
    print("-" * 36)
    total = 0
    for name, size in entries:
        print(f"{name:<24} {size:>10,}")
        total += size
    print("-" * 36)
    print(f"{'Total':<24} {total:>10,}")
    return 0


def cmd_save_extract(args: SimpleNamespace) -> int:
    """Extract files from a U8 save archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U8SaveArchive.from_file(filepath)
    entries = save.list_entries()

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    entry_filter = getattr(args, 'entry', None)
    extracted = 0
    for name, size in entries:
        if entry_filter and name != entry_filter:
            continue
        data = save.get_data(name)
        if data is None:
            continue
        out_path = os.path.join(outdir, name)
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"  {name:<24} {size:>10,} bytes")
        extracted += 1

    if entry_filter and extracted == 0:
        print(f"ERROR: Entry '{entry_filter}' not found in archive",
              file=sys.stderr)
        return 1

    print(f"\nExtracted {extracted} file(s) -> {outdir.rstrip('/\\')}/")
    return 0


# ============================================================================
# MAP HELPERS
# ============================================================================

def _get_exclude_flags(args: SimpleNamespace) -> dict[str, bool]:
    """Extract all exclude flags from argparse Namespace."""
    _exclude: dict[str, bool] = {}
    _exclude_names = [
        'no_fixed', 'no_solid', 'no_sea', 'no_land', 'no_occl', 'no_bag',
        'no_damaging', 'no_noisy', 'no_draw', 'no_ignore', 'no_roof',
        'no_transl', 'no_editor', 'no_explode', 'no_unk46', 'no_unk47',
    ]
    for _name in _exclude_names:
        _exclude[_name] = getattr(args, _name, False)
    return _exclude


def _dir_manifest(dir_path: str, ext: str) -> dict[str, int]:
    """Return ``{filename: filesize}`` for all *ext* files in *dir_path*."""
    if not os.path.isdir(dir_path):
        return {}
    result: dict[str, int] = {}
    for name in sorted(os.listdir(dir_path)):
        if name.lower().endswith(ext.lower()):
            result[name] = os.path.getsize(os.path.join(dir_path, name))
    return result


def _verify_dir_against_flex(
    dir_path: str,
    ext: str,
    flx_path: str,
) -> tuple[list[int], list[int]]:
    """Compare extracted files against FLX records."""
    archive = FlexArchive.from_file(flx_path)
    missing: list[int] = []
    changed: list[int] = []
    for i, record in enumerate(archive.records):
        if not record:
            continue
        filename = f"{i:04d}{ext}"
        filepath = os.path.join(dir_path, filename)
        if not os.path.isfile(filepath):
            missing.append(i)
        elif os.path.getsize(filepath) != len(record):
            changed.append(i)
    return missing, changed


def _resolve_typeflag(args: SimpleNamespace) -> Optional[str]:
    """Return a path to TYPEFLAG.DAT for dimension-aware depth sorting."""
    tf = getattr(args, 'typeflag', None)
    if tf and os.path.isfile(tf):
        return tf

    fixed = getattr(args, 'fixed', None)
    if fixed:
        candidate = os.path.join(os.path.dirname(fixed) or ".", "TYPEFLAG.DAT")
        if os.path.isfile(candidate):
            return candidate

    if os.path.isfile("TYPEFLAG.DAT"):
        return "TYPEFLAG.DAT"

    return None


def _ensure_asset_dir(
    dir_path: str,
    ext: str,
    label: str,
    flx_hint: str,
) -> bool:
    """Verify that *dir_path* contains extracted *ext* files."""
    manifest = _dir_manifest(dir_path, ext)
    if manifest:
        total_bytes = sum(manifest.values())
        print(f"  {label}: {len(manifest)} {ext} files ({total_bytes:,} bytes)")
        return True

    if not os.path.isdir(dir_path):
        print(f"\n[MISSING] {label} directory not found: {dir_path}")
    else:
        print(
            f"\n[EMPTY] {label} directory exists but contains no "
            f"{ext} files: {dir_path}"
        )
    print(
        f"  Map rendering needs individual {ext} files extracted from "
        f"{flx_hint}."
    )
    clean_dir = dir_path.rstrip("/\\")
    print(
        f"  You can do this manually with: "
        f"titan flex-extract {flx_hint} -o {clean_dir}/"
    )
    print()

    answer = ""
    while answer not in ("y", "yes", "n", "no", ""):
        answer = input(
            f"  Extract {flx_hint} into '{dir_path}' now? [y/N] "
        ).strip().lower()

    if answer not in ("y", "yes"):
        print(f"  Aborting.  Re-run after extracting {flx_hint} manually.")
        return False

    flx_path = ""
    while not flx_path or not os.path.isfile(flx_path):
        flx_path = input(f"  Enter path to {flx_hint}: ").strip()
        if not flx_path:
            continue
        if not os.path.isfile(flx_path):
            print(f"  Not found: {flx_path}")
            flx_path = ""

    print(f"\n  Loading {flx_path} ...")
    try:
        archive = FlexArchive.from_file(flx_path)
    except Exception as exc:
        print(f"  ERROR: Could not read FLX: {exc}", file=sys.stderr)
        return False

    non_empty = sum(1 for r in archive.records if r)
    print(f"  Extracting {non_empty} non-empty records to {dir_path}/ ...")
    os.makedirs(dir_path, exist_ok=True)
    extracted = archive.extract_all(dir_path)

    missing_idx, changed_idx = _verify_dir_against_flex(dir_path, ext, flx_path)
    new_manifest = _dir_manifest(dir_path, ext)
    total_bytes = sum(new_manifest.values())
    print(
        f"  Extracted {extracted} files -> {dir_path}/  "
        f"({total_bytes:,} bytes total)"
    )

    if missing_idx:
        indices_preview = missing_idx[:10]
        ellipsis = "..." if len(missing_idx) > 10 else ""
        print(
            f"  WARNING: {len(missing_idx)} records still missing after "
            f"extraction: {indices_preview}{ellipsis}",
            file=sys.stderr,
        )
    if changed_idx:
        indices_preview = changed_idx[:10]
        ellipsis = "..." if len(changed_idx) > 10 else ""
        print(
            f"  WARNING: {len(changed_idx)} files differ in size from FLX "
            f"records: {indices_preview}{ellipsis}",
            file=sys.stderr,
        )
    if not missing_idx and not changed_idx:
        print(f"  Verification OK: all {non_empty} records match disk files.")

    return bool(new_manifest)


def _apply_map_config(
    fixed: Optional[str],
    shapes: Optional[str],
    globs: Optional[str],
    palette: Optional[str],
    typeflag: Optional[str],
    nonfixed: Optional[str],
) -> tuple[str, str, str, str, Optional[str], Optional[str]]:
    """Apply titan.toml defaults to map command paths."""
    fixed = fixed or _cfg("fixed")
    shapes = shapes or _cfg("shapes")
    globs = globs or _cfg("globs")
    palette = palette or _cfg("palette")
    typeflag = typeflag or _cfg("typeflag")
    nonfixed = nonfixed or _cfg("nonfixed")
    missing = [
        k for k, v in [("fixed", fixed), ("shapes", shapes),
                        ("globs", globs), ("palette", palette)]
        if not v
    ]
    if missing:
        print(
            f"Missing required argument(s): --{', --'.join(missing)}\n"
            "Supply them on the command line, or run `titan setup` to "
            "create a titan.toml config file.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    assert fixed is not None and shapes is not None
    assert globs is not None and palette is not None
    return fixed, shapes, globs, palette, typeflag, nonfixed


def _build_map_namespace(**kw: object) -> SimpleNamespace:
    """Build a SimpleNamespace for map commands with config-aware defaults."""
    fixed, shapes, globs, palette, typeflag, nonfixed = _apply_map_config(
        kw.get("fixed"),   # type: ignore[arg-type]
        kw.get("shapes"),  # type: ignore[arg-type]
        kw.get("globs"),   # type: ignore[arg-type]
        kw.get("palette"), # type: ignore[arg-type]
        kw.get("typeflag"),# type: ignore[arg-type]
        kw.get("nonfixed"),# type: ignore[arg-type]
    )
    kw.update(fixed=fixed, shapes=shapes, globs=globs,
              palette=palette, typeflag=typeflag, nonfixed=nonfixed)
    return SimpleNamespace(**kw)


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MAP SAMPLE
# ============================================================================

def cmd_map_sample(args: SimpleNamespace) -> int:
    """Render a colour-sampled top-down map (minimap-style) to PNG."""
    if not os.path.isfile(args.fixed):
        print(f"ERROR: FIXED.DAT not found: {args.fixed}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(args.shapes, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(args.globs, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(args.palette):
        print(f"ERROR: Palette not found: {args.palette}", file=sys.stderr)
        return 1

    scale = args.scale
    map_num = args.map

    with open(args.fixed, "rb") as f:
        fixed_data = f.read()
    all_maps = U8MapRenderer.parse_fixed_dat(fixed_data)
    if map_num not in all_maps:
        print(f"ERROR: Map {map_num} not found or empty.", file=sys.stderr)
        print(f"  Available: {sorted(all_maps.keys())}", file=sys.stderr)
        return 1

    pal = U8Palette.from_file(args.palette)
    raw_objects = all_maps[map_num]
    print(f"Map {map_num}: {len(raw_objects)} objects")

    glob_count = sum(1 for o in raw_objects if o.type_num == 2)
    objects = U8MapRenderer.expand_globs(raw_objects, args.globs)
    print(f"After GLOB expansion: {len(objects)} objects  ({glob_count} GLOBs)")

    nf_path = getattr(args, 'nonfixed', None)
    if nf_path:
        if not os.path.isfile(nf_path):
            print(f"ERROR: Nonfixed file not found: {nf_path}",
                  file=sys.stderr)
            return 1
        tf = getattr(args, 'typeflag', None)
        nf_maps = U8MapRenderer.load_nonfixed(nf_path, tf)
        if map_num in nf_maps:
            nf_objs = nf_maps[map_num]
            objects.extend(nf_objs)
            print(f"Merged {len(nf_objs)} nonfixed objects "
                  f"(total: {len(objects)})")

    tf = getattr(args, 'typeflag', None)
    _exclude_flags = _get_exclude_flags(args)
    if any(_exclude_flags.values()):
        if not tf:
            print("ERROR: Typeflag filtering requires "
                  "--typeflag <typeflag.dat>", file=sys.stderr)
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        before = len(objects)
        objects = [o for o in objects if o.type_num not in exclude_set]
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(f"Typeflags filter: {', '.join(active_filters)} -> "
              f"removed {before - len(objects)}, {len(objects)} remain")

    print(f"Sampling at {scale} world-units/pixel ...")

    img = U8MapSampler.sample_map(objects, args.shapes, pal, scale=scale,
                                  grid=getattr(args, 'grid', False),
                                  grid_size=getattr(args, 'grid_size', 2))
    print(f"Output size: {img.width} x {img.height}")

    out_path = args.output or f"map_{map_num:03d}_sample_{scale}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Saved: {out_path}")
    return 0


def cmd_map_sample_all(args: SimpleNamespace) -> int:
    """Colour-sample all (or selected) maps at one or more scales."""
    if not os.path.isfile(args.fixed):
        print(f"ERROR: FIXED.DAT not found: {args.fixed}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(args.shapes, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(args.globs, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(args.palette):
        print(f"ERROR: Palette not found: {args.palette}", file=sys.stderr)
        return 1

    pal = U8Palette.from_file(args.palette)
    with open(args.fixed, "rb") as f:
        fixed_data = f.read()

    print(f"Parsing {args.fixed} ...")
    all_maps = U8MapRenderer.parse_fixed_dat(fixed_data)

    targets = sorted(args.maps) if args.maps else sorted(all_maps.keys())
    missing = [m for m in targets if m not in all_maps]
    if missing:
        print(f"WARNING: Maps not found / empty, skipping: {missing}",
              file=sys.stderr)
    targets = [m for m in targets if m in all_maps]
    if not targets:
        print("No maps to sample.", file=sys.stderr)
        return 1

    scales: list[int] = args.scales or [args.scale]
    os.makedirs(args.output, exist_ok=True)

    total = len(targets) * len(scales)
    done = 0

    tf = getattr(args, 'typeflag', None)
    _exclude_flags = _get_exclude_flags(args)
    exclude_set: set[int] = set()
    if any(_exclude_flags.values()):
        if not tf:
            print("ERROR: Typeflag filtering requires "
                  "--typeflag <typeflag.dat>", file=sys.stderr)
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(f"Typeflag filters active: {', '.join(active_filters)} "
              f"({len(exclude_set)} shapes excluded)")

    nonfixed_maps: Optional[dict] = None
    nf_path = getattr(args, 'nonfixed', None)
    if nf_path:
        if not os.path.isfile(nf_path):
            print(f"ERROR: Nonfixed file not found: {nf_path}",
                  file=sys.stderr)
            return 1
        nonfixed_maps = U8MapRenderer.load_nonfixed(nf_path, tf)
        nf_total = sum(len(v) for v in nonfixed_maps.values())
        print(f"Loaded {nf_total} nonfixed objects across "
              f"{len(nonfixed_maps)} maps")

    for map_num in targets:
        raw_objects = all_maps[map_num]
        objects = U8MapRenderer.expand_globs(raw_objects, args.globs)
        if nonfixed_maps and map_num in nonfixed_maps:
            objects.extend(nonfixed_maps[map_num])
        if exclude_set:
            objects = [o for o in objects if o.type_num not in exclude_set]
        nf_info = ""
        if nonfixed_maps and map_num in nonfixed_maps:
            nf_info = f" +{len(nonfixed_maps[map_num])} nonfixed"
        print(f"[{targets.index(map_num)+1}/{len(targets)}] "
              f"Map {map_num:3d}: {len(raw_objects):5d} raw -> "
              f"{len(objects):5d} expanded{nf_info}")

        for scale in scales:
            img = U8MapSampler.sample_map(
                objects, args.shapes, pal, scale=scale,
                grid=getattr(args, 'grid', False),
                grid_size=getattr(args, 'grid_size', 2),
            )
            out_name = f"map_{map_num:03d}_sample_{scale}.png"
            img.save(os.path.join(args.output, out_name))
            done += 1
            print(f"  [{done}/{total}] {out_name}  "
                  f"({img.width}x{img.height})")

    print(f"\nDone.  {done} images saved to {args.output}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MAP RENDER
# ============================================================================

def cmd_map_render(args: SimpleNamespace) -> int:
    """Render an Ultima 8 map to a PNG image."""
    fixed_path = args.fixed
    shapes_dir = args.shapes
    glob_dir = args.globs
    palette_path = args.palette
    map_num = args.map
    out_path = args.output
    view = getattr(args, "view", U8MapRenderer.DEFAULT_VIEW)

    if not os.path.isfile(fixed_path):
        print(f"ERROR: FIXED.DAT not found: {fixed_path}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(shapes_dir, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(glob_dir, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette file not found: {palette_path}", file=sys.stderr)
        return 1
    if view not in U8MapRenderer.PROJECTIONS:
        print(f"ERROR: Unknown view '{view}'. "
              f"Choose from: {', '.join(U8MapRenderer.PROJECTIONS)}",
              file=sys.stderr)
        return 1

    pal = U8Palette.from_file(palette_path)

    with open(fixed_path, "rb") as f:
        fixed_data = f.read()

    print(f"Parsing {fixed_path} ...")
    all_maps = U8MapRenderer.parse_fixed_dat(fixed_data)

    if map_num not in all_maps:
        available = sorted(all_maps.keys())
        print(f"ERROR: Map {map_num} not found or empty.", file=sys.stderr)
        print(f"  Available non-empty maps: {available}", file=sys.stderr)
        return 1

    objects = all_maps[map_num]
    print(f"Map {map_num}: {len(objects)} objects")

    glob_count = sum(1 for o in objects if o.type_num == 2)
    if glob_count > 0:
        print(f"Expanding {glob_count} GLOB references ...")
    objects = U8MapRenderer.expand_globs(objects, glob_dir)
    print(f"After GLOB expansion: {len(objects)} objects")

    nf_path = getattr(args, 'nonfixed', None)
    if nf_path:
        if not os.path.isfile(nf_path):
            print(f"ERROR: Nonfixed file not found: {nf_path}",
                  file=sys.stderr)
            return 1
        tf = getattr(args, 'typeflag', None)
        nf_maps = U8MapRenderer.load_nonfixed(nf_path, tf)
        if map_num in nf_maps:
            nf_objs = nf_maps[map_num]
            objects.extend(nf_objs)
            print(f"Merged {len(nf_objs)} nonfixed objects "
                  f"(total: {len(objects)})")
        else:
            print(f"No nonfixed objects for map {map_num}")

    tf = getattr(args, 'typeflag', None)
    _exclude_flags = _get_exclude_flags(args)
    if any(_exclude_flags.values()):
        if not tf:
            print("ERROR: Typeflag filtering requires "
                  "--typeflag <typeflag.dat>", file=sys.stderr)
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        before = len(objects)
        objects = [o for o in objects if o.type_num not in exclude_set]
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(f"Typeflags filter: {', '.join(active_filters)} -> "
              f"removed {before - len(objects)}, {len(objects)} remain")

    typeflag_sort = _resolve_typeflag(args)
    if typeflag_sort:
        print(f"Using TYPEFLAG for depth sort: {typeflag_sort}")

    print(f"Rendering view='{view}' (this may take a moment) ...")
    img = U8MapRenderer.render_map(objects, shapes_dir, pal, view=view,
                                   grid=getattr(args, 'grid', False),
                                   grid_size=getattr(args, 'grid_size', 2),
                                   typeflag_path=typeflag_sort)
    print(f"Canvas size: {img.width} x {img.height}")

    if out_path is None:
        out_path = f"map_{map_num:03d}_{view}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Saved: {out_path}")
    return 0


def _render_all_shared(
    fixed_path: str,
    shapes_dir: str,
    glob_dir: str,
    palette_path: str,
    out_dir: str,
    views: list[str],
    map_nums: Optional[list[int]],
    *,
    exclude_set: set[int] | None = None,
    nonfixed_maps: Optional[dict] = None,
    grid: bool = False,
    grid_size: int = 2,
    typeflag_path: Optional[str] = None,
) -> int:
    """Shared logic for rendering multiple maps and/or views."""
    pal = U8Palette.from_file(palette_path)

    with open(fixed_path, "rb") as f:
        fixed_data = f.read()

    print(f"Parsing {fixed_path} ...")
    all_maps = U8MapRenderer.parse_fixed_dat(fixed_data)

    targets = sorted(map_nums) if map_nums else sorted(all_maps.keys())
    missing = [m for m in targets if m not in all_maps]
    if missing:
        print(f"WARNING: Maps not found / empty, skipping: {missing}",
              file=sys.stderr)
    targets = [m for m in targets if m in all_maps]

    if not targets:
        print("No maps to render.", file=sys.stderr)
        return 1

    if exclude_set is None:
        exclude_set = set()

    os.makedirs(out_dir, exist_ok=True)
    total = len(targets) * len(views)
    done = 0

    for map_num in targets:
        raw_objects = all_maps[map_num]
        glob_count = sum(1 for o in raw_objects if o.type_num == 2)
        objects = U8MapRenderer.expand_globs(raw_objects, glob_dir)
        if nonfixed_maps and map_num in nonfixed_maps:
            nf_objs = nonfixed_maps[map_num]
            objects.extend(nf_objs)
        if exclude_set:
            objects = [o for o in objects if o.type_num not in exclude_set]
        nf_info = ""
        if nonfixed_maps and map_num in nonfixed_maps:
            nf_info = f" +{len(nonfixed_maps[map_num])} nonfixed"
        print(f"[{done // len(views) + 1}/{len(targets)}] "
              f"Map {map_num:3d}: {len(raw_objects):5d} raw -> "
              f"{len(objects):5d} expanded  ({glob_count} GLOBs{nf_info})")

        for view in views:
            view_objects = copy.deepcopy(objects)
            img = U8MapRenderer.render_map(view_objects, shapes_dir, pal,
                                           view=view, grid=grid,
                                           grid_size=grid_size,
                                           typeflag_path=typeflag_path)
            out_name = f"map_{map_num:03d}_{view}.png"
            img.save(os.path.join(out_dir, out_name))
            done += 1
            print(f"  [{done}/{total}] {out_name}  "
                  f"({img.width}x{img.height})")

    print(f"\nDone.  {done} images saved to {out_dir}/")
    return 0


def cmd_map_render_all(args: SimpleNamespace) -> int:
    """Render all non-empty maps in all requested projection views."""
    if not os.path.isfile(args.fixed):
        print(f"ERROR: FIXED.DAT not found: {args.fixed}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(args.shapes, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(args.globs, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(args.palette):
        print(f"ERROR: Palette not found: {args.palette}", file=sys.stderr)
        return 1

    views = getattr(args, "views", None) or list(U8MapRenderer.PROJECTIONS)
    bad = [v for v in views if v not in U8MapRenderer.PROJECTIONS]
    if bad:
        print(f"ERROR: Unknown view(s): {bad}. "
              f"Choose from: {', '.join(U8MapRenderer.PROJECTIONS)}",
              file=sys.stderr)
        return 1

    map_nums: Optional[list[int]] = getattr(args, "maps", None) or None

    tf = getattr(args, 'typeflag', None)
    _exclude_flags = _get_exclude_flags(args)
    exclude_set: set[int] = set()
    if any(_exclude_flags.values()):
        if not tf:
            print("ERROR: Typeflag filtering requires "
                  "--typeflag <typeflag.dat>", file=sys.stderr)
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(f"Typeflag filters: {', '.join(active_filters)} "
              f"({len(exclude_set)} shapes excluded)")

    nonfixed_maps: Optional[dict] = None
    nf_path = getattr(args, 'nonfixed', None)
    if nf_path:
        if not os.path.isfile(nf_path):
            print(f"ERROR: Nonfixed file not found: {nf_path}",
                  file=sys.stderr)
            return 1
        nonfixed_maps = U8MapRenderer.load_nonfixed(nf_path, tf)
        nf_total = sum(len(v) for v in nonfixed_maps.values())
        print(f"Loaded {nf_total} nonfixed objects across "
              f"{len(nonfixed_maps)} maps")

    typeflag_sort = _resolve_typeflag(args)
    if typeflag_sort:
        print(f"Using TYPEFLAG for depth sort: {typeflag_sort}")

    return _render_all_shared(
        fixed_path=args.fixed,
        shapes_dir=args.shapes,
        glob_dir=args.globs,
        palette_path=args.palette,
        out_dir=args.output,
        views=views,
        map_nums=map_nums,
        exclude_set=exclude_set,
        nonfixed_maps=nonfixed_maps,
        grid=getattr(args, 'grid', False),
        grid_size=getattr(args, 'grid_size', 2),
        typeflag_path=typeflag_sort,
    )


# ============================================================================
# Typer command wrappers — U8 sub-app
# ============================================================================


@u8_app.command("palette-export")
def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .pal file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Export a U8 palette (.pal) as PNG swatch + text dump."""
    raise SystemExit(cmd_palette_export(SimpleNamespace(file=file, output=output)))


@u8_app.command("shape-export")
def shape_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .shp file")],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to .pal palette file"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Export frames from a Shape (.shp) file to PNG."""
    raise SystemExit(cmd_shape_export(SimpleNamespace(
        file=file, palette=palette, output=output,
    )))


@u8_app.command("shape-batch")
def shape_batch_cmd(
    directory: Annotated[str, typer.Argument(help="Directory containing .shp files")],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to .pal palette file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <dir>/png/)"),
    ] = None,
) -> None:
    """Batch-export all .shp files in a directory to PNG."""
    raise SystemExit(cmd_shape_batch(SimpleNamespace(
        directory=directory, palette=palette, output=output,
    )))


@u8_app.command("shape-import")
def shape_import_cmd(
    directory: Annotated[
        str, typer.Argument(help="Directory containing *_fNNNN.png frame images"),
    ],
    original: Annotated[
        str,
        typer.Option("--original", help="Path to the original .shp file (metadata reference)"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to .pal palette file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output .shp path"),
    ] = None,
) -> None:
    """Import PNG frames back into a U8 shape (.shp) file."""
    raise SystemExit(cmd_shape_import(SimpleNamespace(
        directory=directory, original=original, palette=palette, output=output,
    )))


# ---- music / sound ---------------------------------------------------------


@u8_app.command("music-export")
def music_export_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to MUSIC.FLX (Flex archive) or standalone XMIDI file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and convert music from MUSIC.FLX to MIDI files."""
    raise SystemExit(cmd_music_export(SimpleNamespace(file=file, output=output)))


@u8_app.command("sound-export-all")
def sound_export_all_cmd(
    file: Annotated[str, typer.Argument(
        help="Path to SOUND.FLX (Flex archive of Sonarc audio)")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and decode all sound effects from SOUND.FLX to WAV."""
    raise SystemExit(cmd_sound_export_all(SimpleNamespace(
        file=file, output=output,
    )))


@u8_app.command("sound-export")
def sound_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .raw Sonarc audio file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decode a Sonarc audio file (.raw) to WAV."""
    raise SystemExit(cmd_sound_export(SimpleNamespace(file=file, output=output)))


@u8_app.command("sound-batch")
def sound_batch_cmd(
    directory: Annotated[str, typer.Argument(help="Directory containing .raw files")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <dir>/wav/)"),
    ] = None,
) -> None:
    """Batch-decode all Sonarc .raw files in a directory to WAV."""
    raise SystemExit(cmd_sound_batch(SimpleNamespace(
        directory=directory, output=output,
    )))


@u8_app.command("credits-decrypt")
def credits_decrypt_cmd(
    file: Annotated[str, typer.Argument(help="Path to encrypted .dat file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decrypt ECREDITS.DAT or QUOTES.DAT to plain text."""
    raise SystemExit(cmd_credits_decrypt(SimpleNamespace(file=file, output=output)))


@u8_app.command("xformpal-export")
def xformpal_export_cmd(
    file: Annotated[
        Optional[str], typer.Argument(help="Path to XFORMPAL.DAT (optional)"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Export U8 transform palette as PNG swatch + text dump."""
    raise SystemExit(cmd_xformpal_export(SimpleNamespace(file=file, output=output)))


@u8_app.command("typeflag-dump")
def typeflag_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to TYPEFLAG.DAT")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Parse TYPEFLAG.DAT and dump all shape info."""
    raise SystemExit(cmd_typeflag_dump(SimpleNamespace(file=file, output=output)))


@u8_app.command("gumpinfo-dump")
def gumpinfo_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to GUMPAGE.DAT")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Dump GUMPAGE.DAT container gump UI layout data."""
    raise SystemExit(cmd_gumpinfo_dump(SimpleNamespace(file=file, output=output)))


@u8_app.command("unkcoff-dump")
def unkcoff_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to UNKCOFF.DAT")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: print to stdout)"),
    ] = None,
) -> None:
    """Dump UNKCOFF.DAT code-offset table (dev leftover)."""
    raise SystemExit(cmd_unkcoff_dump(SimpleNamespace(file=file, output=output)))


@u8_app.command("save-list")
def save_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to U8 save file")],
) -> None:
    """List contents of a U8 save file (U8SAVE.000, etc.)."""
    raise SystemExit(cmd_save_list(SimpleNamespace(file=file)))


@u8_app.command("save-extract")
def save_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to U8 save file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    entry: Annotated[
        Optional[str],
        typer.Option("--entry", help="Extract only this named entry"),
    ] = None,
) -> None:
    """Extract files from a U8 save archive."""
    raise SystemExit(cmd_save_extract(SimpleNamespace(
        file=file, output=output, entry=entry,
    )))


# ── map commands (config-aware with shared exclude/grid flags) ───


@u8_app.command("map-render")
def map_render_cmd(
    map_num: Annotated[int, typer.Option("--map", "-m", help="Map number to render (0\u2013255)")],
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[Optional[str], typer.Option(help="Directory of extracted .shp shape files")] = None,
    globs: Annotated[Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")] = None,
    palette: Annotated[Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")] = None,
    view: Annotated[str, typer.Option("--view", "-V", help="Projection view")] = "iso_classic",
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output PNG path")] = None,
    typeflag: Annotated[Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")] = None,
    nonfixed: Annotated[Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")] = None,
    no_fixed: Annotated[bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")] = False,
    no_solid: Annotated[bool, typer.Option("--no-solid", help="Exclude SI_SOLID")] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")] = False,
    no_noisy: Annotated[bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")] = False,
    no_editor: Annotated[bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")] = False,
    no_explode: Annotated[bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")] = False,
    no_unk46: Annotated[bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")] = False,
    no_unk47: Annotated[bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")] = False,
    grid: Annotated[bool, typer.Option("--grid", help="Overlay chunk grid lines")] = False,
    grid_size: Annotated[int, typer.Option("--grid-size", help="Grid line thickness in pixels")] = 2,
) -> None:
    """Render a single U8 map to PNG."""
    args = _build_map_namespace(
        map=map_num, fixed=fixed, shapes=shapes, globs=globs,
        palette=palette, view=view, output=output,
        typeflag=typeflag, nonfixed=nonfixed,
        no_fixed=no_fixed, no_solid=no_solid, no_sea=no_sea, no_land=no_land,
        no_occl=no_occl, no_bag=no_bag, no_damaging=no_damaging,
        no_noisy=no_noisy, no_draw=no_draw, no_ignore=no_ignore,
        no_roof=no_roof, no_transl=no_transl, no_editor=no_editor,
        no_explode=no_explode, no_unk46=no_unk46, no_unk47=no_unk47,
        grid=grid, grid_size=grid_size, config=None,
    )
    raise SystemExit(cmd_map_render(args))


@u8_app.command("map-render-all")
def map_render_all_cmd(
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[Optional[str], typer.Option(help="Directory of extracted .shp shape files")] = None,
    globs: Annotated[Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")] = None,
    palette: Annotated[Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")] = None,
    output: Annotated[str, typer.Option("-o", "--output", help="Output directory")] = "map_renders",
    views: Annotated[Optional[list[str]], typer.Option("--views", help="Views to render (default: all)")] = None,
    maps: Annotated[Optional[list[int]], typer.Option("--maps", help="Map numbers to render")] = None,
    typeflag: Annotated[Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")] = None,
    nonfixed: Annotated[Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")] = None,
    no_fixed: Annotated[bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")] = False,
    no_solid: Annotated[bool, typer.Option("--no-solid", help="Exclude SI_SOLID")] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")] = False,
    no_noisy: Annotated[bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")] = False,
    no_editor: Annotated[bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")] = False,
    no_explode: Annotated[bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")] = False,
    no_unk46: Annotated[bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")] = False,
    no_unk47: Annotated[bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")] = False,
    grid: Annotated[bool, typer.Option("--grid", help="Overlay chunk grid lines")] = False,
    grid_size: Annotated[int, typer.Option("--grid-size", help="Grid line thickness in pixels")] = 2,
) -> None:
    """Render all non-empty maps in all (or selected) projection views."""
    args = _build_map_namespace(
        fixed=fixed, shapes=shapes, globs=globs,
        palette=palette, output=output, views=views, maps=maps,
        typeflag=typeflag, nonfixed=nonfixed,
        no_fixed=no_fixed, no_solid=no_solid, no_sea=no_sea, no_land=no_land,
        no_occl=no_occl, no_bag=no_bag, no_damaging=no_damaging,
        no_noisy=no_noisy, no_draw=no_draw, no_ignore=no_ignore,
        no_roof=no_roof, no_transl=no_transl, no_editor=no_editor,
        no_explode=no_explode, no_unk46=no_unk46, no_unk47=no_unk47,
        grid=grid, grid_size=grid_size, config=None,
    )
    raise SystemExit(cmd_map_render_all(args))


@u8_app.command("map-sample")
def map_sample_cmd(
    map_num: Annotated[int, typer.Option("--map", "-m", help="Map number to sample (0\u2013255)")],
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[Optional[str], typer.Option(help="Directory of extracted .shp shape files")] = None,
    globs: Annotated[Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")] = None,
    palette: Annotated[Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")] = None,
    scale: Annotated[int, typer.Option("--scale", "-s", help="World units per output pixel")] = 64,
    output: Annotated[Optional[str], typer.Option("-o", "--output", help="Output PNG path")] = None,
    typeflag: Annotated[Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")] = None,
    nonfixed: Annotated[Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")] = None,
    no_fixed: Annotated[bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")] = False,
    no_solid: Annotated[bool, typer.Option("--no-solid", help="Exclude SI_SOLID")] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")] = False,
    no_noisy: Annotated[bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")] = False,
    no_editor: Annotated[bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")] = False,
    no_explode: Annotated[bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")] = False,
    no_unk46: Annotated[bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")] = False,
    no_unk47: Annotated[bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")] = False,
    grid: Annotated[bool, typer.Option("--grid", help="Overlay chunk grid lines")] = False,
    grid_size: Annotated[int, typer.Option("--grid-size", help="Grid line thickness in pixels")] = 2,
) -> None:
    """Colour-sample a map top-down (minimap / MiniMapGump style)."""
    args = _build_map_namespace(
        map=map_num, fixed=fixed, shapes=shapes, globs=globs,
        palette=palette, scale=scale, output=output,
        typeflag=typeflag, nonfixed=nonfixed,
        no_fixed=no_fixed, no_solid=no_solid, no_sea=no_sea, no_land=no_land,
        no_occl=no_occl, no_bag=no_bag, no_damaging=no_damaging,
        no_noisy=no_noisy, no_draw=no_draw, no_ignore=no_ignore,
        no_roof=no_roof, no_transl=no_transl, no_editor=no_editor,
        no_explode=no_explode, no_unk46=no_unk46, no_unk47=no_unk47,
        grid=grid, grid_size=grid_size, config=None,
    )
    raise SystemExit(cmd_map_sample(args))


@u8_app.command("map-sample-all")
def map_sample_all_cmd(
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[Optional[str], typer.Option(help="Directory of extracted .shp shape files")] = None,
    globs: Annotated[Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")] = None,
    palette: Annotated[Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")] = None,
    output: Annotated[str, typer.Option("-o", "--output", help="Output directory")] = "map_samples",
    scale: Annotated[int, typer.Option("--scale", "-s", help="Default scale when --scales not given")] = 64,
    scales: Annotated[Optional[list[int]], typer.Option("--scales", help="One or more scales")] = None,
    maps: Annotated[Optional[list[int]], typer.Option("--maps", help="Map numbers to sample")] = None,
    typeflag: Annotated[Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")] = None,
    nonfixed: Annotated[Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")] = None,
    no_fixed: Annotated[bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")] = False,
    no_solid: Annotated[bool, typer.Option("--no-solid", help="Exclude SI_SOLID")] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")] = False,
    no_noisy: Annotated[bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")] = False,
    no_editor: Annotated[bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")] = False,
    no_explode: Annotated[bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")] = False,
    no_unk46: Annotated[bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")] = False,
    no_unk47: Annotated[bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")] = False,
    grid: Annotated[bool, typer.Option("--grid", help="Overlay chunk grid lines")] = False,
    grid_size: Annotated[int, typer.Option("--grid-size", help="Grid line thickness in pixels")] = 2,
) -> None:
    """Colour-sample all (or selected) maps at one or more scales."""
    args = _build_map_namespace(
        fixed=fixed, shapes=shapes, globs=globs,
        palette=palette, output=output, scale=scale, scales=scales, maps=maps,
        typeflag=typeflag, nonfixed=nonfixed,
        no_fixed=no_fixed, no_solid=no_solid, no_sea=no_sea, no_land=no_land,
        no_occl=no_occl, no_bag=no_bag, no_damaging=no_damaging,
        no_noisy=no_noisy, no_draw=no_draw, no_ignore=no_ignore,
        no_roof=no_roof, no_transl=no_transl, no_editor=no_editor,
        no_explode=no_explode, no_unk46=no_unk46, no_unk47=no_unk47,
        grid=grid, grid_size=grid_size, config=None,
    )
    raise SystemExit(cmd_map_sample_all(args))
