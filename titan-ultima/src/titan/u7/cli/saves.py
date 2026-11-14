"""``titan u7 save-*`` / ``gamedat-info`` / ``gflag-dump`` — savegame and GAMEDAT commands."""

from __future__ import annotations

__all__ = [
    "save_browse_cmd",
    "gamedat_info_cmd",
    "save_list_cmd",
    "save_extract_cmd",
    "gflag_dump_cmd",
    "save_info_cmd",
    "save_npcs_cmd",
    "save_schedules_cmd",
]

import csv
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.u7 import install
from titan.u7.cli import _common


def cmd_gamedat_info(args: SimpleNamespace) -> int:
    """Inspect a loose Exult GAMEDAT directory or Exult archive."""
    from titan.u7.flex import U7FlexArchive
    from titan.u7.map import U7MapRenderer
    from titan.u7.save import (
        U7FrameFlags,
        U7GameState,
        U7GlobalFlags,
        U7Identity,
        U7Keyring,
        U7NPCData,
        U7Save,
        U7SaveInfo,
        U7Schedules,
        U7UsecodeData,
        U7UsecodeVars,
    )
    from titan.u7.shape import U7Shape

    source = getattr(args, "directory", None)
    mod = getattr(args, "mod", None)
    if not source:
        source = install.resolve_u7_mod_gamedat(getattr(args, "game", "bg"), mod)
    if not source:
        source = install.resolve_u7_mod_archive(getattr(args, "game", "bg"), mod)
    if not source:
        source = install.resolve_u7_gamedat(getattr(args, "game", "bg"))
    if not source:
        print(
            "ERROR: GAMEDAT source not supplied and no configured/default "
            f"[u7{getattr(args, 'game', 'bg')}] source was found.",
            file=sys.stderr,
        )
        return 1

    root = Path(source)
    archive: Optional[U7Save] = None
    initgame_flex_source = False
    initgame_entries: dict[str, bytes] = {}
    if root.is_file():
        initgame_flex_source = (
            root.name.lower() == "initgame.dat" and U7FlexArchive.is_u7_flex(str(root))
        )
        if initgame_flex_source:
            initgame = U7FlexArchive.from_file(str(root))
            for record in initgame.records:
                if len(record) <= 13:
                    continue
                entry = (
                    record[:13]
                    .split(b"\x00", 1)[0]
                    .decode("ascii", errors="replace")
                    .rstrip(".")
                    .lower()
                )
                initgame_entries[entry] = record[13:]
        if not initgame_flex_source:
            try:
                archive = U7Save.from_file(str(root))
            except ValueError as exc:
                print(
                    f"ERROR: GAMEDAT source is not a directory or Exult archive: {exc}",
                    file=sys.stderr,
                )
                return 1
    elif not root.is_dir():
        print(f"ERROR: GAMEDAT source not found: {root}", file=sys.stderr)
        return 1

    def data_for(name: str) -> Optional[bytes]:
        if initgame_flex_source:
            return initgame_entries.get(name.lower())
        if archive is not None:
            return archive.get_data(name)
        path = root / name
        return path.read_bytes() if path.is_file() else None

    def source_size(name: str) -> int:
        if initgame_flex_source:
            data = data_for(name)
            return len(data) if data is not None else 0
        if archive is not None:
            data = archive.get_data(name)
            return len(data) if data is not None else 0
        path = root / name
        return path.stat().st_size if path.exists() else 0

    def entry_names() -> list[str]:
        if initgame_flex_source:
            return sorted(initgame_entries)
        if archive is not None:
            return sorted(name for name, _ in archive.list_entries())
        return sorted(path.name for path in root.iterdir() if path.is_file())

    container_shapes = _common._load_container_shapes(
        args,
        fallback_static=(
            None
            if archive is not None
            else _common._infer_static_dir_for_data_file(str(root / "npc.dat"))
        ),
    )
    valid_shape_count = _common._load_shape_count(
        args,
        fallback_static=(
            None
            if archive is not None
            else _common._infer_static_dir_for_data_file(str(root / "npc.dat"))
        ),
    )

    rows: list[tuple[str, int, str, str]] = []

    def add_row(name: str, status: str, note: str = "") -> None:
        rows.append((name, source_size(name), status, note))

    def state_row(name: str, warnings: list[str], note: str) -> None:
        add_row(
            name,
            "parsed with warnings" if warnings else "parsed",
            "; ".join([note, *warnings]),
        )
        lines.extend(f"Warning: {warning}" for warning in warnings)

    source_kind = (
        "INITGAME.DAT Flex archive"
        if initgame_flex_source
        else (f"{archive.container_format.upper()} archive" if archive else "directory")
    )
    lines: list[str] = [
        "=== Loose GAMEDAT Info ===",
        f"Source: {root} ({source_kind})",
        "",
    ]

    identity_data = data_for("identity")
    if identity_data is not None:
        ident = U7Identity.from_bytes(identity_data)
        lines.append(f"Identity: {ident.game}")
        add_row("identity", "parsed", ident.game)

    for name in ("exult.ver", "newgame.ver"):
        data = data_for(name)
        if data is not None:
            first = data.decode("ascii", errors="replace").splitlines()[0]
            add_row(name, "parsed text", first)

    npc_names: dict[int, str] | None = None
    npc_data = data_for("npc.dat")
    if npc_data is not None:
        npcs = U7NPCData.from_bytes(
            npc_data,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            npc_flavor=("original-new-game" if initgame_flex_source else "runtime"),
        )
        npc_names = npcs.name_map()
        lines.append(npcs.dump_summary())
        female_count = sum(1 for npc in npcs.npcs if npc.is_female)
        male_count = sum(1 for npc in npcs.npcs if npc.is_female is False)
        if npcs.npc_flavor == "original-new-game":
            lines.append(
                "NPC sex: decoded from original new-game data "
                f"(raw bit 9 inverted; {female_count} female, {male_count} male)."
            )
        else:
            lines.append(
                "NPC sex: decoded from Exult runtime type_flags bit 9 "
                f"({female_count} female, {male_count} male)."
            )
        add_row(
            "npc.dat",
            "parsed",
            f"{len(npcs.npcs)} NPCs; {female_count} female, {male_count} male",
        )

    mon_data = data_for("monsnpcs.dat")
    if mon_data is not None:
        monsters = U7NPCData.from_monsnpcs_bytes(
            mon_data,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
        )
        lines.append(
            f"Monster NPCs: {len(monsters.npcs)} parsed ({monsters.num_npcs1} declared)"
        )
        add_row("monsnpcs.dat", "parsed", f"{len(monsters.npcs)} monsters")

    sched_data = data_for("schedule.dat")
    if sched_data is not None:
        sched = U7Schedules.from_bytes(sched_data)
        lines.append(sched.dump_summary(npc_names))
        total = sum(len(entries) for entries in sched.entries.values())
        add_row(
            "schedule.dat",
            "parsed_with_warnings" if sched.warnings else "parsed",
            f"{total} entries ({sched.format}); {'; '.join(sched.warnings)}",
        )

    flag_data = data_for("flaginit")
    if flag_data is not None:
        gflags = U7GlobalFlags.from_bytes(flag_data)
        lines.append(gflags.dump_summary())
        add_row("flaginit", "parsed", f"{gflags.nonzero_count} nonzero")

    saveinfo_data = data_for("saveinfo.dat")
    if saveinfo_data is not None:
        info = U7SaveInfo.from_bytes(saveinfo_data)
        lines.append(
            f"Save info: {info.real_year:04d}-{info.real_month:02d}-"
            f"{info.real_day:02d} {info.real_hour:02d}:"
            f"{info.real_minute:02d}:{info.real_second:02d}, "
            f"party size {info.party_size}"
        )
        state_row("saveinfo.dat", info.warnings, f"party size {info.party_size}")

    gwin_data = data_for("gamewin.dat")
    if gwin_data is not None:
        gwin = U7GameState.from_bytes(gwin_data)
        lines.append(
            f"Game window: camera=({gwin.scroll_tx},{gwin.scroll_ty}), "
            f"day {gwin.clock_day}, {gwin.clock_hour:02d}:"
            f"{gwin.clock_minute:02d}"
        )
        state_row("gamewin.dat", gwin.warnings, "camera/time state")

    usedat_data = data_for("usecode.dat")
    if usedat_data is not None:
        usedat = U7UsecodeData.from_bytes(usedat_data)
        nonzero = sum(1 for timer in usedat.timers if timer.value != 0)
        lines.append(
            f"Usecode runtime: party={usedat.party_members}, "
            f"timers={len(usedat.timers)} ({nonzero} nonzero)"
        )
        state_row("usecode.dat", usedat.warnings, "party/timers/saved pos")

    usevars_data = data_for("usecode.var")
    if usevars_data is not None:
        usevars = U7UsecodeVars.from_bytes(usevars_data)
        state_row(
            "usecode.var",
            usevars.warnings,
            f"{usevars.global_static_count} global statics, "
            f"{usevars.local_static_blocks} local blocks",
        )

    keyring_data = data_for("keyring.dat")
    if keyring_data is not None:
        keyring = U7Keyring.from_bytes(keyring_data)
        state_row(
            "keyring.dat",
            keyring.warnings,
            f"{len(keyring.unique_keys)} unique keys, {len(keyring.keys)} stored",
        )

    frames_data = data_for("frames.flg")
    if frames_data is not None:
        frames = U7FrameFlags.from_bytes(frames_data)
        add_row(
            "frames.flg",
            "parsed",
            f"{len(frames.values)} entries, {frames.non_default_count} set",
        )

    if archive is None:
        screenshot_path = root / "scrnshot.shp"
        if screenshot_path.is_file():
            shape = U7Shape.from_file(str(screenshot_path))
            if shape.frames:
                frame = shape.frames[0]
                add_row(
                    "scrnshot.shp",
                    "parsed",
                    f"{len(shape.frames)} frame(s), {frame.width}x{frame.height}",
                )
            else:
                add_row("scrnshot.shp", "parsed", "0 frames")

    ireg_names = [
        name
        for name in entry_names()
        if name.startswith("u7ireg") and len(Path(name).name) == 8
    ]
    if ireg_names:
        total_bytes = sum(source_size(name) for name in ireg_names)
        if archive is None:
            simple_objects = 0
            for name in ireg_names:
                path = root / name
                schunk = int(path.name[-2:], 16)
                simple_objects += len(U7MapRenderer.parse_ireg(str(path), schunk))
            note = f"{len(ireg_names)} files; {simple_objects} simple objects"
            lines.append(
                f"IREG: {len(ireg_names)} files, {simple_objects} simple "
                "objects parsed by current partial parser"
            )
        else:
            note = f"{len(ireg_names)} files; archive bytes counted"
            lines.append(
                f"IREG: {len(ireg_names)} files present; object parsing is "
                "available for loose files"
            )
        rows.append(("u7iregNN", total_bytes, "partially parsed", note))

    known = {name for name, _, _, _ in rows}
    known.add("u7iregNN")
    for name in entry_names():
        plain_name = Path(name).name
        if plain_name in known or name in known:
            continue
        if plain_name.startswith("u7ireg") and len(plain_name) == 8:
            continue
        if Path(plain_name).suffix.lower() in {".csv", ".md"}:
            rows.append((name, source_size(name), "generated artifact", ""))
        else:
            rows.append((name, source_size(name), "unrecognized", ""))

    fmt = getattr(args, "format", "summary") or "summary"
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["file", "size", "status", "note"])
        writer.writerows(rows)
        content = buf.getvalue()
    elif fmt == "detail":
        lines.append("")
        lines.append("--- File Coverage ---")
        for name, size, status, note in rows:
            suffix = f" - {note}" if note else ""
            lines.append(f"{name:<24} {size:>8}  {status}{suffix}")
        content = "\n".join(lines)
    else:
        content = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_save_list(args: SimpleNamespace) -> int:
    """List contents of an Exult U7 savegame file."""
    from titan.u7.save import U7Save

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        save = U7Save.from_file(filepath, strict=getattr(args, "strict", False))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in save.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if getattr(args, "json_output", False):
        import hashlib

        report = {
            "file": filepath,
            "source_sha256": hashlib.sha256(save.raw).hexdigest(),
            "format": save.container_format,
            "complete": save.complete,
            "warnings": save.warnings,
            "members": [
                {
                    "member_path": [member.index],
                    "name": member.name,
                    "source": member.source,
                    "size": len(member.data),
                    "sha256": hashlib.sha256(member.data).hexdigest(),
                    "complete": member.complete,
                    "is_directory": member.is_directory,
                }
                for member in save.members
            ],
        }
        print(json.dumps(report, indent=2))
        return 0
    entries = save.list_entries()

    print(f"U7 Save: {filepath}")
    print(f"Title:   {save.title}")
    print(f"Format:  {save.container_format.upper()}")
    print(f"Complete: {save.complete}")
    print(f"Entries: {len(entries)}")
    print()
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
    """Extract files from an Exult U7 savegame archive."""
    from titan.u7.save import U7Save
    from titan.u7.save_extraction import extract_u7_save_members

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or Path(filepath).stem
    entry_filter = getattr(args, "entry", None)
    try:
        save = U7Save.from_file(filepath, strict=getattr(args, "strict", True))
        for warning in save.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        plan, manifest = extract_u7_save_members(
            save.members, outdir, entry=entry_filter
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for member, path in plan:
        print(
            f"  [{member.index}] {member.name:<24} {len(member.data):>10,} bytes -> {path}"
        )
    if manifest is not None:
        print(f"Member mapping: {manifest}")
    print(
        f"\nExtracted {sum(not member.is_directory for member, _ in plan)} file(s) -> {outdir}/"
    )
    return 0


def cmd_gflag_dump(args: SimpleNamespace) -> int:
    """Dump global flags from a savegame or loose flaginit file."""
    from titan.u7.save import U7Save, U7GlobalFlags

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    # Determine whether this is a .sav archive or a loose flaginit file
    ext = os.path.splitext(filepath)[1].lower()
    basename = os.path.basename(filepath).lower()

    if ext == ".sav":
        save = U7Save.from_file(filepath)
        gflags = U7GlobalFlags.from_save(save)
        print(f"Source: {filepath} ({save.container_format.upper()} save)")
        print(f"Title:  {save.title}")
    elif basename == "flaginit":
        gflags = U7GlobalFlags.from_file(filepath)
        print(f"Source: {filepath} (loose flaginit file)")
    else:
        # Try as .sav first, fallback to raw flaginit
        try:
            save = U7Save.from_file(filepath)
            gflags = U7GlobalFlags.from_save(save)
            print(f"Source: {filepath} ({save.container_format.upper()} save)")
            print(f"Title:  {save.title}")
        except (ValueError, KeyError):
            gflags = U7GlobalFlags.from_file(filepath)
            print(f"Source: {filepath} (raw flaginit)")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = gflags.dump_csv()
    elif fmt == "detail":
        content = gflags.dump_detail()
    else:
        content = gflags.dump_summary()

    if args.output:
        out_path = args.output
        with open(out_path, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {out_path}")
    else:
        print()
        print(content)

    return 0


def cmd_save_info(args: SimpleNamespace) -> int:
    """Show identity, save metadata, party roster, and game state."""
    from titan.u7.save import (
        U7Save,
        U7Identity,
        U7SaveInfo,
        U7GameState,
        U7Schedules,
    )

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    lines: list[str] = []
    lines.append("=== U7 Save Info ===")
    lines.append(f"File:    {filepath}")
    lines.append(f"Title:   {save.title}")
    lines.append(f"Format:  {save.container_format.upper()}")
    lines.append(f"Complete: {save.complete}")
    lines.extend(f"Warning: {warning}" for warning in save.warnings)

    # Identity
    try:
        ident = U7Identity.from_save(save)
        lines.append(f"Game:    {ident.game}")
    except (ValueError, KeyError):
        pass

    lines.append("")

    # Save metadata
    try:
        info = U7SaveInfo.from_save(save)
        lines.append(info.dump())
    except (ValueError, KeyError) as exc:
        lines.append(f"(cannot read saveinfo.dat: {exc})")

    lines.append("")

    # Game state
    try:
        gs = U7GameState.from_save(save)
        lines.append(gs.dump())
    except (ValueError, KeyError) as exc:
        lines.append(f"(cannot read gamewin.dat: {exc})")

    lines.append("")

    # Schedule summary
    try:
        sched = U7Schedules.from_save(save)
        lines.append(sched.dump_summary())
    except (ValueError, KeyError):
        pass

    content = "\n".join(lines)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"Save info written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_save_npcs(args: SimpleNamespace) -> int:
    """Dump NPC data from a savegame."""
    from titan.u7.save import U7Save, U7NPCData

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    print(f"Source: {filepath} ({save.container_format.upper()} save)")
    print(f"Title:  {save.title}")

    container_shapes = _common._load_container_shapes(args)
    valid_shape_count = _common._load_shape_count(args)
    npcs = U7NPCData.from_save(
        save,
        game=getattr(args, "game", "bg"),
        container_shapes=container_shapes,
        valid_shape_count=valid_shape_count,
    )
    for warning in npcs.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = npcs.dump_csv()
    elif fmt == "detail":
        content = npcs.dump_detail()
    else:
        content = npcs.dump_summary()

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def cmd_save_schedules(args: SimpleNamespace) -> int:
    """Dump NPC schedules from a savegame."""
    from titan.u7.save import U7Save, U7NPCData, U7Schedules

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    print(f"Source: {filepath} ({save.container_format.upper()} save)")
    print(f"Title:  {save.title}")

    try:
        sched = U7Schedules.from_save(save, strict=True)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in sched.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    npc_names: dict[int, str] | None = None
    try:
        container_shapes = _common._load_container_shapes(args)
        valid_shape_count = _common._load_shape_count(args)
        npc_names = U7NPCData.npc_name_map(
            save,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
    except (ValueError, KeyError):
        pass

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = sched.dump_csv(npc_names)
    elif fmt == "detail":
        content = sched.dump_detail(npc_names)
    else:
        content = sched.dump_summary(npc_names)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def save_browse_cmd(
    source: Annotated[
        Optional[str], typer.Argument(help="Initial save file or GAMEDAT folder")
    ] = None,
    game: Annotated[
        Literal["bg", "si"], typer.Option("--game", help="Initial game flavour")
    ] = "bg",
) -> None:
    """Choose a world's save and browse metadata, party, files and NPCs."""
    from titan.u7.npc_browser_ui import run_browser

    raise SystemExit(run_browser(game=game, source=source, saves=True))


def gamedat_info_cmd(
    directory: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to a loose Exult GAMEDAT directory or archive (default: titan.toml/user profile)"
        ),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="Path to STATIC directory for npc.dat inventory parsing"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    mod: Annotated[
        Optional[str],
        typer.Option(
            "--mod", help="Resolve user-profile Exult runtime GAMEDAT for this mod"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Inspect loose Exult GAMEDAT files or archives."""
    raise SystemExit(
        cmd_gamedat_info(
            SimpleNamespace(
                directory=directory,
                game=game,
                mod=mod,
                static=static,
                output=output,
                format=format,
            )
        )
    )


def save_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    strict: Annotated[
        bool,
        typer.Option(
            "--strict/--permissive", help="Reject structural container errors"
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json", help="JSON occurrence paths and member hashes for repack plans"
        ),
    ] = False,
) -> None:
    """List contents of an Exult U7 savegame file (ZIP or FLEX)."""
    raise SystemExit(
        cmd_save_list(
            SimpleNamespace(file=file, strict=strict, json_output=json_output)
        )
    )


def save_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: save filename stem)"
        ),
    ] = None,
    entry: Annotated[
        Optional[str],
        typer.Option("-e", "--entry", help="Extract only this named entry"),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict/--permissive",
            help="Validate completely before extraction; permissive allows available partial payloads",
        ),
    ] = True,
) -> None:
    """Extract files from an Exult U7 savegame archive."""
    raise SystemExit(
        cmd_save_extract(
            SimpleNamespace(
                file=file,
                output=output,
                entry=entry,
                strict=strict,
            )
        )
    )


def gflag_dump_cmd(
    file: Annotated[str, typer.Argument(help="Exult .sav file or loose flaginit file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump global flags from a U7 savegame or flaginit file."""
    raise SystemExit(
        cmd_gflag_dump(
            SimpleNamespace(
                file=file,
                output=output,
                format=format,
            )
        )
    )


def save_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Show save metadata: identity, timestamp, party, game state."""
    raise SystemExit(
        cmd_save_info(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )


def save_npcs_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump NPC data from an Exult U7 savegame."""
    raise SystemExit(
        cmd_save_npcs(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


def save_schedules_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="Path to STATIC directory for npc.dat inventory parsing"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump NPC schedules from an Exult U7 savegame."""
    raise SystemExit(
        cmd_save_schedules(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )
