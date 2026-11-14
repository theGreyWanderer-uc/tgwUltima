"""``titan u8 *-dump`` / ``credits-decrypt`` — game data table commands."""

from __future__ import annotations

__all__ = [
    "credits_decrypt_cmd",
    "anim_dump_cmd",
    "wpnovlay_dump_cmd",
    "itemcach_dump_cmd",
    "npcdata_dump_cmd",
    "map_items_dump_cmd",
    "typeflag_dump_cmd",
    "gumpinfo_dump_cmd",
    "unkcoff_dump_cmd",
]

import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u8.save import U8SaveArchive
from titan.u8.typeflag import U8TypeFlags
from titan.u8.credits import decrypt_credit_text


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

        header = (
            f"{'Shape':>6}  {'Flags':>6}  {'FlagNames':<48} "
            f"{'Family':<12} {'Equip':<8} "
            f"{'X':>2} {'Y':>2} {'Z':>2}  "
            f"{'Anim':>4} {'AData':>5}  "
            f"{'Wt':>3} {'Vol':>3}  {'Unk':>3}\n"
        )
        f.write(header)
        f.write("-" * 120 + "\n")

        for e in entries:
            if (
                e.flags == 0
                and e.family == 0
                and e.equiptype == 0
                and e.x == 0
                and e.y == 0
                and e.z == 0
                and e.weight == 0
                and e.volume == 0
            ):
                continue

            flag_str = ",".join(e.flag_names()) or "-"
            f.write(
                f"{e.shape_num:>6}  0x{e.flags:04X}  {flag_str:<48} "
                f"{e.family_name():<12} {e.equip_name():<8} "
                f"{e.x:>2} {e.y:>2} {e.z:>2}  "
                f"{e.animtype:>4} {e.animdata:>5}  "
                f"{e.weight:>3} {e.volume:>3}  {e.unknown:>3}\n"
            )

    print(f"Dumped {len(entries)} shapes -> {out_path}")

    families: dict[str, int] = {}
    flagged: dict[str, int] = {}
    for e in entries:
        fn = e.family_name()
        families[fn] = families.get(fn, 0) + 1
        for name in e.flag_names():
            flagged[name] = flagged.get(name, 0) + 1

    print("\nFamily distribution:")
    for fn, count in sorted(families.items(), key=lambda x: -x[1]):
        if fn == "generic" and count > 1000:
            print(f"  {fn:<14} {count:5d}  (most shapes)")
        else:
            print(f"  {fn:<14} {count:5d}")

    print("\nFlag counts:")
    for name, count in sorted(flagged.items(), key=lambda x: -x[1]):
        print(f"  {name:<18} {count:5d}")

    return 0


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
        f.write(
            "Used by ContainerGump to position held items inside bags, chests, etc.\n\n"
        )
        f.write(
            f"{'Gump#':>6}  {'X':>5} {'Y':>5} {'W':>5} {'H':>5}  {'X2':>5} {'Y2':>5}\n"
        )
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
            f.write(f"{i + 1:>6}  {x1:>5} {y1:>5} {w:>5} {h:>5}  {x2:>5} {y2:>5}\n")
            non_empty += 1

    print(f"Wrote {non_empty}/{count} non-empty gump areas -> {out_path}")
    print("(GUMPAGE.DAT defines container gump UI layout, not map data)")
    return 0


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
    lines.append("UNKnown COde OFFsets table.  Dev leftover, ignored at runtime.")
    lines.append("Entry 0 is a magic/version value.  Remaining entries are")
    lines.append("segment:offset pairs for usecode class entry points.")
    lines.append("")
    lines.append(
        f"{'Index':>6}  {'Hex Value':>12}  {'Segment':>8}  {'Offset':>8}  Note"
    )
    lines.append("-" * 60)

    for i in range(count):
        val = struct.unpack_from("<I", data, i * 4)[0]
        seg = (val >> 16) & 0xFFFF
        off = val & 0xFFFF
        if i == 0:
            note = "magic / version / total size?"
            em_dash = "-"
            lines.append(
                f"{i:>6}  0x{val:08X}      {em_dash:>8}      {em_dash:>8}  {note}"
            )
        else:
            note = ""
            lines.append(f"{i:>6}  0x{val:08X}    0x{seg:04X}    0x{off:04X}  {note}")

    lines.append("")

    out_path = getattr(args, "output", None)
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


def credits_decrypt_cmd(
    file: Annotated[str, typer.Argument(help="Path to encrypted .dat file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decrypt ECREDITS.DAT or QUOTES.DAT to plain text."""
    raise SystemExit(cmd_credits_decrypt(SimpleNamespace(file=file, output=output)))


def anim_dump_cmd(
    file: Annotated[Path, typer.Argument(help="Path to U8 ANIM.DAT")],
    shape: Annotated[
        Optional[int],
        typer.Option("--shape", min=0, max=2047, help="Shape ID (0-2047)"),
    ] = None,
    action: Annotated[
        Optional[int],
        typer.Option("--action", min=0, max=63, help="Actor action number (0-63)"),
    ] = None,
    direction: Annotated[
        Optional[int],
        typer.Option(
            "--direction",
            min=0,
            max=7,
            help="0=N, 1=NE, ... 7=NW; includes frame details",
        ),
    ] = None,
    frames: Annotated[
        bool,
        typer.Option(
            "--frames", help="Include packed frame nodes for all selected directions"
        ),
    ] = False,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help="New report file (default: stdout); existing files are preserved",
        ),
    ] = None,
) -> None:
    """Inspect U8 actor actions, directions, movement, sound and animation flags."""
    from titan.u8.anim import U8AnimData
    from titan.u8.anim_report import format_u8_anim_report

    try:
        report = format_u8_anim_report(
            U8AnimData.from_file(file),
            shape=shape,
            action=action,
            direction=direction,
            frames=frames,
            output_format=output_format,
        )
        if output is None:
            print(report, end="")
        else:
            if output.resolve() == file.resolve():
                raise ValueError(
                    "ANIM.DAT report: output must differ from the source file"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="") as destination:
                destination.write(report)
            print(f"Animation report written to: {output}")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def wpnovlay_dump_cmd(
    file: Annotated[Path, typer.Argument(help="Path to U8 WPNOVLAY.DAT")],
    anim: Annotated[
        Optional[Path],
        typer.Option("--anim", help="Matching ANIM.DAT (default: beside WPNOVLAY.DAT)"),
    ] = None,
    action: Annotated[
        Optional[int],
        typer.Option("--action", min=0, max=63, help="Avatar action ID (0-63)"),
    ] = None,
    overlay_type: Annotated[
        Optional[int],
        typer.Option(
            "--overlay-type",
            min=0,
            help="Overlay slot: 0=mace, 1=sword, 2=axe, 3=dagger; further slots retained",
        ),
    ] = None,
    direction: Annotated[
        Optional[int],
        typer.Option(
            "--direction",
            min=0,
            max=7,
            help="0=N, 1=NE, ... 7=NW; includes frame details",
        ),
    ] = None,
    frames: Annotated[
        bool,
        typer.Option(
            "--frames", help="Include overlay frames for all selected directions"
        ),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Report format: text, json or csv"),
    ] = "text",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help="New report file (default: stdout); existing files are preserved",
        ),
    ] = None,
) -> None:
    """Inspect weapon overlay sprite frames and screen offsets paired with ANIM.DAT."""
    from titan.u8.anim import U8AnimData
    from titan.u8.wpnovlay import U8WeaponOverlayData
    from titan.u8.wpnovlay_report import format_u8_wpnovlay_report

    anim_file = anim if anim is not None else file.with_name("ANIM.DAT")
    try:
        report = format_u8_wpnovlay_report(
            U8WeaponOverlayData.from_file(file, U8AnimData.from_file(anim_file)),
            action=action,
            overlay_type=overlay_type,
            direction=direction,
            frames=frames,
            output_format=output_format,
        )
        if output is None:
            print(report, end="")
        else:
            if output.resolve() in {file.resolve(), anim_file.resolve()}:
                raise ValueError(
                    "WPNOVLAY.DAT report: output must differ from both source files"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="") as destination:
                destination.write(report)
            print(f"Weapon overlay report written to: {output}")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def itemcach_dump_cmd(
    file: Annotated[Path, typer.Argument(help="ITEMCACH.DAT or native U8SAVE archive")],
    item: Annotated[
        Optional[int],
        typer.Option(
            "--item", min=0, max=9215, help="Exact item slot, including free/null data"
        ),
    ] = None,
    shape: Annotated[
        Optional[int], typer.Option("--shape", min=0, max=65535, help="Stored shape ID")
    ] = None,
    view: Annotated[
        str, typer.Option("--view", help="View: items or regions")
    ] = "items",
    all_slots: Annotated[
        bool,
        typer.Option(
            "--all-slots", help="Include null/free items or empty region cells"
        ),
    ] = False,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help="New report file (default: stdout); existing files are preserved",
        ),
    ] = None,
) -> None:
    """Inspect cached item fields, allocation lists, regions and native cache metadata."""
    from titan.u8.itemcach import U8ItemCache
    from titan.u8.state_io import write_u8_state_report
    from titan.u8.state_report import format_u8_itemcach_report

    try:
        report = format_u8_itemcach_report(
            U8ItemCache.from_file(file),
            item_id=item,
            shape=shape,
            view=view,
            all_slots=all_slots,
            output_format=output_format,
        )
        write_u8_state_report(report, output, (file,), "Item cache")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def npcdata_dump_cmd(
    file: Annotated[Path, typer.Argument(help="NPCDATA.DAT or native U8SAVE archive")],
    itemcach: Annotated[
        Optional[Path],
        typer.Option(
            "--itemcach", help="Matching ITEMCACH.DAT or save; saves pair automatically"
        ),
    ] = None,
    npc: Annotated[
        Optional[int],
        typer.Option(
            "--npc", min=0, max=255, help="Exact NPC slot, including unused data"
        ),
    ] = None,
    map_num: Annotated[
        Optional[int],
        typer.Option(
            "--map", min=0, max=255, help="NPC map ID; requires matching ITEMCACH"
        ),
    ] = None,
    all_slots: Annotated[
        bool,
        typer.Option(
            "--all-slots", help="Include all 256 slots, including unused/null records"
        ),
    ] = False,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help="New report file (default: stdout); existing files are preserved",
        ),
    ] = None,
) -> None:
    """Inspect NPC stats, animation, flags and equipment; optionally join cached items."""
    from titan.u8.itemcach import U8ItemCache
    from titan.u8.npcdata import U8NpcData
    from titan.u8.state_io import write_u8_state_report
    from titan.u8.state_report import format_u8_npcdata_report

    try:
        # A native save contains the paired snapshot; loose NPC files need an explicit path.
        cache_file = itemcach
        if cache_file is None:
            with file.open("rb") as source:
                if U8SaveArchive.is_save_file(
                    source.read(len(U8SaveArchive.SIGNATURE))
                ):
                    cache_file = file
        item_cache = (
            U8ItemCache.from_file(cache_file) if cache_file is not None else None
        )
        report = format_u8_npcdata_report(
            U8NpcData.from_file(file),
            item_cache=item_cache,
            npc_id=npc,
            map_num=map_num,
            all_slots=all_slots,
            output_format=output_format,
        )
        sources = (file, cache_file) if cache_file is not None else (file,)
        write_u8_state_report(report, output, sources, "NPC data")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def map_items_dump_cmd(
    ctx: typer.Context,
    file: Annotated[
        Path,
        typer.Argument(help="FIXED.DAT, NONFIXED.DAT, or native U8SAVE (nonfixed)"),
    ],
    map_num: Annotated[
        Optional[int],
        typer.Option(
            "--map",
            min=0,
            max=255,
            help="Flex map slot (0 is the NONFIXED NPC registry)",
        ),
    ] = None,
    record: Annotated[
        Optional[int],
        typer.Option(
            "--record",
            min=0,
            help="Map-local record index; requires --map and selects items view",
        ),
    ] = None,
    shape: Annotated[
        Optional[int], typer.Option("--shape", min=0, max=65535, help="Stored shape ID")
    ] = None,
    view: Annotated[
        str,
        typer.Option(
            "--view", help="View: summary (all slots) or items (complete records)"
        ),
    ] = "summary",
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Scope: all, world, contained or npc (NONFIXED registry roots)",
        ),
    ] = "all",
    typeflag: Annotated[
        Optional[Path],
        typer.Option(
            "--typeflag", help="Optional TYPEFLAG.DAT shape-family/equipment enrichment"
        ),
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "-o",
            "--output",
            help="New report file (default stdout); existing files are preserved",
        ),
    ] = None,
) -> None:
    """Inspect full 16-byte map items, container hierarchy and NPC registry records."""
    from titan.u8.map_item_report import format_u8_map_item_report
    from titan.u8.map_items import U8MapItems
    from titan.u8.state_io import write_u8_state_report

    kind = "nonfixed" if ctx.info_name == "nonfixed-dump" else "fixed"
    try:
        report = format_u8_map_item_report(
            U8MapItems.from_file(file, kind=kind),
            map_id=map_num,
            record_index=record,
            shape=shape,
            view=view,
            scope=scope,
            typeflag_data=typeflag.read_bytes() if typeflag is not None else None,
            output_format=output_format,
        )
        sources = (file, typeflag) if typeflag is not None else (file,)
        write_u8_state_report(report, output, sources, f"{kind.upper()} items")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def typeflag_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to TYPEFLAG.DAT")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Parse TYPEFLAG.DAT and dump all shape info."""
    raise SystemExit(cmd_typeflag_dump(SimpleNamespace(file=file, output=output)))


def gumpinfo_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to GUMPAGE.DAT")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Dump GUMPAGE.DAT container gump UI layout data."""
    raise SystemExit(cmd_gumpinfo_dump(SimpleNamespace(file=file, output=output)))


def unkcoff_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to UNKCOFF.DAT")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: print to stdout)"
        ),
    ] = None,
) -> None:
    """Dump UNKCOFF.DAT code-offset table (dev leftover)."""
    raise SystemExit(cmd_unkcoff_dump(SimpleNamespace(file=file, output=output)))
