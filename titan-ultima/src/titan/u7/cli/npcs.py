"""``titan u7 npc-*`` / ``monster-*`` / ``schedule-dump`` — NPC, monster and schedule commands."""

from __future__ import annotations

__all__ = [
    "monster_browse_cmd",
    "npc_browse_cmd",
    "npc_dump_cmd",
    "schedule_dump_cmd",
    "monster_defs_cmd",
    "monster_dump_cmd",
    "monster_equipment_cmd",
    "monster_report_cmd",
    "npc_equipment_cmd",
]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.u7 import install
from titan.u7.cli import _common


def cmd_npc_dump(args: SimpleNamespace) -> int:
    """Dump NPC data from loose npc.dat, GAMEDAT, or INITGAME.DAT."""
    from titan.u7.flex import U7FlexArchive
    from titan.u7.save import U7NPCData, U7Save

    input_path = Path(args.file)
    looks_like_initgame = (
        input_path.is_file() and input_path.name.lower() == "initgame.dat"
    )
    initgame_source = looks_like_initgame and U7FlexArchive.is_u7_flex(str(input_path))
    archive_source = False
    archive: Optional[U7Save] = None
    if looks_like_initgame and not initgame_source:
        try:
            archive = U7Save.from_file(str(input_path))
            archive_source = archive.has_entry("npc.dat")
        except ValueError:
            archive_source = False
        if not archive_source:
            print(
                "ERROR: INITGAME.DAT is neither a U7 Flex archive nor an "
                f"Exult ZIP archive with npc.dat: {input_path}",
                file=sys.stderr,
            )
            return 1
    filepath = (
        str(input_path)
        if initgame_source
        else _common._resolve_loose_data_file(
            args.file,
            "npc.dat",
        )
    )
    if not archive_source and not os.path.isfile(filepath):
        print(
            f"ERROR: npc.dat or INITGAME.DAT not found: {filepath}",
            file=sys.stderr,
        )
        return 1

    if initgame_source:
        source_note = "INITGAME.DAT Flex:npc.dat"
    elif archive_source:
        source_note = "Exult archive:npc.dat"
        filepath = str(input_path)
    else:
        source_note = "loose npc.dat"
    print(f"Source: {filepath} ({source_note})")
    container_shapes = _common._load_container_shapes(
        args,
        fallback_static=(
            str(Path(filepath).resolve().parent)
            if initgame_source
            else _common._infer_static_dir_for_data_file(filepath)
        ),
    )
    valid_shape_count = _common._load_shape_count(
        args,
        fallback_static=(
            str(Path(filepath).resolve().parent)
            if initgame_source
            else _common._infer_static_dir_for_data_file(filepath)
        ),
    )
    if initgame_source:
        print("Sex:    decoded from original new-game data (raw bit 9 inverted)")
        npcs = U7NPCData.from_initgame_file(
            filepath,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
    elif archive_source and archive is not None:
        print("Sex:    decoded from Exult runtime type_flags bit 9")
        npcs = U7NPCData.from_save(
            archive,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
    else:
        npcs = U7NPCData.from_file(
            filepath,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            npc_flavor="auto",
        )
        if npcs.npc_flavor == "original-new-game":
            print("Sex:    auto-detected original new-game data (raw bit 9 inverted)")
        elif npcs.npc_flavor == "runtime":
            print("Sex:    auto-detected Exult runtime type_flags bit 9")
        else:
            print("Sex:    unknown; loose npc.dat has no reliable flavor marker")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = npcs.dump_csv()
    elif fmt == "detail":
        content = npcs.dump_detail()
    else:
        content = npcs.dump_summary()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def cmd_schedule_dump(args: SimpleNamespace) -> int:
    """Dump NPC schedules from a loose schedule.dat file or directory."""
    from titan.u7.save import U7NPCData, U7Save, U7Schedules

    filepath = _common._resolve_loose_data_file(args.file, "schedule.dat")
    if not os.path.isfile(filepath):
        print(f"ERROR: schedule.dat not found: {filepath}", file=sys.stderr)
        return 1

    print(f"Source: {filepath} (loose schedule.dat)")
    try:
        sched = U7Schedules.from_file(filepath, strict=True)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in sched.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    npc_names: dict[int, str] | None = None
    npc_file_arg = getattr(args, "npc_file", None)
    npc_file: Optional[str] = None
    npc_save: Optional[U7Save] = None
    if npc_file_arg:
        npc_path = Path(npc_file_arg)
        if (
            npc_path.is_file()
            and npc_path.suffix.lower() == ".dat"
            and npc_path.name.lower() != "npc.dat"
        ):
            try:
                npc_save = U7Save.from_file(str(npc_path))
                if not npc_save.has_entry("npc.dat"):
                    npc_save = None
            except ValueError:
                npc_save = None
        if npc_save is None:
            npc_file = _common._resolve_loose_data_file(npc_file_arg, "npc.dat")
    else:
        sibling = Path(filepath).with_name("npc.dat")
        npc_file = str(sibling) if sibling.is_file() else None

    if npc_save is not None or npc_file:
        try:
            container_shapes = _common._load_container_shapes(
                args, fallback_static=None
            )
            valid_shape_count = _common._load_shape_count(args, fallback_static=None)
            if npc_save is not None:
                npc_data = U7NPCData.from_save(
                    npc_save,
                    game=getattr(args, "game", "bg"),
                    container_shapes=container_shapes,
                    valid_shape_count=valid_shape_count,
                )
                print(
                    f"Names:  {len(npc_data.npcs)} NPC names loaded from {npc_file_arg}"
                )
            else:
                if npc_file is None:
                    raise ValueError("npc.dat path could not be resolved")
                npc_data = U7NPCData.from_file(
                    npc_file,
                    game=getattr(args, "game", "bg"),
                    container_shapes=container_shapes,
                    valid_shape_count=valid_shape_count,
                )
                print(f"Names:  {len(npc_data.npcs)} NPC names loaded from {npc_file}")
            npc_names = npc_data.name_map()
        except (OSError, ValueError) as exc:
            print(f"Names:  unavailable ({exc})")
    else:
        print("Names:  (no sibling npc.dat or --npc-file)")

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


def cmd_monster_defs(args: SimpleNamespace) -> int:
    """Dump static U7 MONSTERS.DAT monster definitions."""
    from titan.u7.monster import U7MonsterDefinitions
    from titan.u7.actor_flags import load_u7_actor_flags

    source = Path(args.file)
    if source.is_dir():
        defs = U7MonsterDefinitions.from_dir(str(source), game=args.game)
    else:
        defs = U7MonsterDefinitions.from_file(str(source), game=args.game)

    mod_file = getattr(args, "mod_file", None)
    if mod_file:
        mod_defs = U7MonsterDefinitions.from_file(mod_file, game=args.game)
        defs = U7MonsterDefinitions.merge(defs, mod_defs)

    patch_dirs = [Path(mod_file).parent] if mod_file else []
    source_dir = source if source.is_dir() else source.parent
    if source_dir.name.lower() != "static":
        patch_dirs.insert(0, source_dir)
    shape_info = getattr(args, "shape_info", None)
    try:
        actor_flags = load_u7_actor_flags(
            game=args.game,
            exult_flx_path=getattr(args, "exult_flx", None),
            patch_dirs=patch_dirs,
            patch_files=[shape_info] if shape_info is not None else (),
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: actor flag metadata unavailable: {error}", file=sys.stderr)
        return 1

    fmt = getattr(args, "format", "summary") or "summary"
    content = (
        defs.dump_csv(actor_flags) if fmt == "csv" else defs.dump_summary(actor_flags)
    )
    if fmt == "csv":
        for warning in [*defs.warnings, *defs.validate_semantics()]:
            print(f"Warning: {warning}", file=sys.stderr)
    for warning in actor_flags.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"Monster definitions written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_monster_dump(args: SimpleNamespace) -> int:
    """Dump live monster actors from monsnpcs.dat, GAMEDAT, or save archive."""
    from titan.u7.monster import live_monsters_csv, live_monsters_from_source

    input_path = Path(args.file)
    container_shapes = _common._load_container_shapes(
        args,
        fallback_static=(
            _common._infer_static_dir_for_data_file(str(input_path / "monsnpcs.dat"))
            if input_path.is_dir()
            else None
        ),
    )
    monsters, source_file = live_monsters_from_source(
        args.file,
        game=getattr(args, "game", "bg"),
        container_shapes=container_shapes,
    )
    fmt = getattr(args, "format", "summary") or "summary"
    if fmt == "csv":
        content = live_monsters_csv(monsters, source_file)
    else:
        lines = [
            f"Source: {source_file}",
            f"Live monsters: {len(monsters.npcs)} parsed",
        ]
        for idx, monster in enumerate(monsters.npcs[:30]):
            lines.append(
                f"  {idx:3d} shape={monster.shape:4d} "
                f"tile=({monster.tile_x},{monster.tile_y},{monster.lift}) "
                f"HP={monster.health:3d} sched={monster.schedule_name}"
            )
        if len(monsters.npcs) > 30:
            lines.append(f"  ... {len(monsters.npcs) - 30} more")
        content = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"Live monster dump written to: {args.output}")
    else:
        print(content)
    return 0


def _parse_int_list(value: str | None) -> set[int]:
    if not value:
        return set()
    parsed: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if token:
            parsed.add(int(token, 0))
    return parsed


def cmd_monster_equipment(args: SimpleNamespace) -> int:
    """Calculate possible monster equipment from MONSTERS.DAT + equip.dat."""
    from titan.u7.monster import monster_equipment_csv, monster_equipment_summary

    static = getattr(args, "static", None)
    if not static:
        static, _ = install.resolve_u7_static_and_palette(getattr(args, "game", "bg"))
    if not static:
        print("ERROR: STATIC directory not supplied or configured.", file=sys.stderr)
        return 1

    monster_shapes = _parse_int_list(getattr(args, "monster_shape", None))
    fmt = getattr(args, "format", "summary") or "summary"
    diagnostics: list[str] = []
    if fmt == "csv":
        content = monster_equipment_csv(
            static,
            game=getattr(args, "game", "bg"),
            mod_monsters=getattr(args, "mod_monsters", None),
            equip_file=getattr(args, "equip_file", None),
            monster_shapes=monster_shapes or None,
            diagnostics=diagnostics,
        )
    else:
        content = monster_equipment_summary(
            static,
            game=getattr(args, "game", "bg"),
            mod_monsters=getattr(args, "mod_monsters", None),
            equip_file=getattr(args, "equip_file", None),
            monster_shapes=monster_shapes or None,
            diagnostics=diagnostics,
        )

    for warning in diagnostics:
        print(f"Warning: {warning}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"Monster equipment calculation written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_monster_report(args: SimpleNamespace) -> int:
    """Write joined monster definitions, live actors, eggs, and placements."""
    from titan.u7.monster import monster_report

    static = getattr(args, "static", None)
    if not static:
        static, _ = install.resolve_u7_static_and_palette(getattr(args, "game", "bg"))
    if not static:
        print("ERROR: STATIC directory not supplied or configured.", file=sys.stderr)
        return 1

    gamedat = getattr(args, "gamedat", None)
    if not gamedat:
        gamedat = install.resolve_u7_mod_gamedat(
            getattr(args, "game", "bg"),
            getattr(args, "mod", None),
        )
    if not gamedat:
        gamedat = install.resolve_u7_gamedat(getattr(args, "game", "bg"))

    live_source = getattr(args, "live_source", None) or gamedat
    out_dir = getattr(args, "output_dir", None)
    outputs = monster_report(
        static_dir=static,
        gamedat_dir=gamedat,
        live_source=live_source,
        game=getattr(args, "game", "bg"),
        mod_monsters=getattr(args, "mod_monsters", None),
        mod_equip=getattr(args, "mod_equip", None),
        output_dir=out_dir,
    )
    if out_dir:
        print(f"Monster report written to: {out_dir}")
        for name in sorted(outputs):
            print(f"  {name}")
    else:
        print(outputs["manifest.txt"])
    return 0


def cmd_npc_equipment(args: SimpleNamespace) -> int:
    """Dump actual NPC inventory/equipment from save, GAMEDAT, or npc.dat."""
    from titan.u7.names import U7ShapeNames
    from titan.u7.save import U7NPCData, U7ReadyTypes, U7Save
    from titan.u7.world import WorldQueryParams, load_query_metadata, load_ireg_context
    from titan.u7.ready_metadata import U7ReadyMetadata

    source = Path(args.file)
    static = getattr(args, "static", None)
    if not static:
        static, _ = install.resolve_u7_static_and_palette(getattr(args, "game", "bg"))
    if not static:
        static = (
            _common._infer_static_dir_for_data_file(str(source / "npc.dat"))
            if source.is_dir()
            else _common._infer_static_dir_for_data_file(str(source))
        )
    if not static:
        print("ERROR: STATIC directory not supplied or inferred.", file=sys.stderr)
        return 1

    container_shapes = _common._load_container_shapes(args, fallback_static=static)
    valid_shape_count = _common._load_shape_count(args, fallback_static=static)
    metadata_params = WorldQueryParams(
        static_dir=static,
        base_static=static,
        patch_dir=getattr(args, "patch_dir", None),
        game=getattr(args, "game", "bg"),
        custom_game=getattr(args, "custom_game", False),
    )
    tfa, _, _, _ = load_query_metadata(metadata_params)
    ireg_context = load_ireg_context(metadata_params, tfa)
    if metadata_params.patch_dir:
        from titan.u7.shape_archive import find_archive
        from titan.u7.flex import U7FlexArchive

        patch_shapes = find_archive(Path(metadata_params.patch_dir), "SHAPES.VGA")
        if patch_shapes is not None:
            valid_shape_count = max(
                valid_shape_count or 0,
                len(U7FlexArchive.from_file(str(patch_shapes)).records),
            )
    if source.is_dir() or source.name.lower() == "npc.dat":
        npc_file = _common._resolve_loose_data_file(str(source), "npc.dat")
        npcs = U7NPCData.from_file(
            npc_file,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            npc_flavor="auto",
            ireg_context=ireg_context,
        )
        print(f"Source: {npc_file} (loose npc.dat)")
    else:
        save = U7Save.from_file(str(source))
        npcs = U7NPCData.from_save(
            save,
            game=getattr(args, "game", "bg"),
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            ireg_context=ireg_context,
        )
        print(f"Source: {source} ({save.container_format.upper()} save)")

    names = U7ShapeNames.from_static_dir(static)
    npc_nums = _parse_int_list(getattr(args, "npc", None))
    effective_ready = U7ReadyMetadata.from_dir(
        static,
        patch_dir=getattr(args, "patch_dir", None),
        game=getattr(args, "game", "bg"),
        custom_game=getattr(args, "custom_game", False),
    )
    ready_types = U7ReadyTypes(
        dict(effective_ready.preferred), list(effective_ready.records)
    )
    content = npcs.dump_inventory_csv(
        names,
        ready_types,
        npc_nums or None,
        effective_ready=effective_ready,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"NPC equipment dump written to: {args.output}")
    else:
        print(content)
    return 0


def monster_browse_cmd(
    source: Annotated[
        Optional[str],
        typer.Argument(
            help="Initial MONSTERS.DAT, save, GAMEDAT folder, or monsnpcs.dat"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"], typer.Option("--game", help="Initial game flavour")
    ] = "bg",
    shape: Annotated[
        Optional[int],
        typer.Option("--shape", help="Initial monster shape number", min=0),
    ] = None,
) -> None:
    """Browse a world's monster definitions, saved actors, equipment and spawns."""
    from titan.u7.monster_browser_ui import run_browser

    raise SystemExit(run_browser(game=game, source=source, shape=shape))


def npc_browse_cmd(
    source: Annotated[
        Optional[str],
        typer.Argument(help="Initial save, INITGAME.DAT, GAMEDAT folder, or npc.dat"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"], typer.Option("--game", help="Initial game flavour")
    ] = "bg",
    npc: Annotated[
        Optional[int], typer.Option("--npc", help="Initial NPC number", min=0)
    ] = None,
    have_si_shapes: Annotated[
        Optional[bool],
        typer.Option(
            "--si-shapes/--no-si-shapes",
            help="Explicit runtime availability of imported SI skin shapes",
        ),
    ] = None,
    avatar_skin: Annotated[
        Optional[int],
        typer.Option(
            "--avatar-skin", help="Explicit Exult Avatar skin override", min=0
        ),
    ] = None,
    avatar_sex: Annotated[
        Optional[Literal["male", "female"]],
        typer.Option("--avatar-sex", help="Explicit Exult Avatar sex override"),
    ] = None,
) -> None:
    """Browse a world's NPC stats, schedules and nested inventory interactively."""
    from titan.u7.npc_browser_ui import run_browser

    raise SystemExit(
        run_browser(
            game=game,
            source=source,
            npc=npc,
            have_si_shapes=have_si_shapes,
            avatar_skin=avatar_skin,
            avatar_female=None if avatar_sex is None else avatar_sex == "female",
        )
    )


def npc_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to npc.dat, a GAMEDAT directory, or STATIC/INITGAME.DAT"
        ),
    ],
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
    """Dump NPC data from loose Exult GAMEDAT npc.dat or INITGAME.DAT."""
    raise SystemExit(
        cmd_npc_dump(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


def schedule_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to schedule.dat or a directory containing schedule.dat"
        ),
    ],
    npc_file: Annotated[
        Optional[str],
        typer.Option(
            "--npc-file", help="Optional npc.dat file or directory for NPC names"
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
    """Dump NPC schedules from loose Exult schedule.dat."""
    raise SystemExit(
        cmd_schedule_dump(
            SimpleNamespace(
                file=file,
                npc_file=npc_file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


def monster_defs_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to MONSTERS.DAT or STATIC directory")
    ],
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI decoding rules"),
    ] = "bg",
    mod_file: Annotated[
        Optional[str],
        typer.Option("--mod-file", help="Optional mod MONSTERS.DAT to merge over base"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
    exult_flx: Annotated[
        Optional[str],
        typer.Option("--exult-flx", help="BG/SI Exult bundle for actor flag defaults"),
    ] = None,
    shape_info: Annotated[
        Optional[str],
        typer.Option("--shape-info", help="Additional shape_info.txt actor flag patch"),
    ] = None,
) -> None:
    """Dump decoded MONSTERS.DAT monster definitions."""
    raise SystemExit(
        cmd_monster_defs(
            SimpleNamespace(
                file=file,
                game=game,
                mod_file=mod_file,
                output=output,
                format=format,
                exult_flx=exult_flx,
                shape_info=shape_info,
            )
        )
    )


def monster_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to monsnpcs.dat, GAMEDAT directory, or Exult save archive"
        ),
    ],
    static: Annotated[
        Optional[str],
        typer.Option("--static", help="Path to STATIC directory for inventory parsing"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
) -> None:
    """Dump live monster actors from Exult monsnpcs.dat."""
    raise SystemExit(
        cmd_monster_dump(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


def monster_equipment_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(help="Path to STATIC directory (default: titan.toml)"),
    ] = None,
    monster_shape: Annotated[
        Optional[str],
        typer.Option(
            "--monster-shape",
            help="Monster shape filter, comma-separated; accepts decimal or 0xHEX",
        ),
    ] = None,
    mod_monsters: Annotated[
        Optional[str],
        typer.Option("--mod-monsters", help="Optional mod MONSTERS.DAT override file"),
    ] = None,
    equip_file: Annotated[
        Optional[str],
        typer.Option("--equip-file", help="Optional equip.dat file"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI decoding rules"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
) -> None:
    """Calculate possible monster equipment from MONSTERS.DAT + equip.dat."""
    raise SystemExit(
        cmd_monster_equipment(
            SimpleNamespace(
                static=static,
                monster_shape=monster_shape,
                mod_monsters=mod_monsters,
                equip_file=equip_file,
                game=game,
                output=output,
                format=format,
            )
        )
    )


def monster_report_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(help="Path to STATIC directory (default: titan.toml)"),
    ] = None,
    gamedat: Annotated[
        Optional[str],
        typer.Option("--gamedat", help="Path to Exult GAMEDAT directory"),
    ] = None,
    live_source: Annotated[
        Optional[str],
        typer.Option("--live-source", help="monsnpcs.dat, GAMEDAT, or save archive"),
    ] = None,
    mod_monsters: Annotated[
        Optional[str],
        typer.Option("--mod-monsters", help="Optional mod MONSTERS.DAT override file"),
    ] = None,
    mod_equip: Annotated[
        Optional[str],
        typer.Option("--mod-equip", help="Optional mod equip.dat override file"),
    ] = None,
    mod: Annotated[
        Optional[str],
        typer.Option(
            "--mod", help="Resolve user-profile Exult runtime GAMEDAT for this mod"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    output_dir: Annotated[
        Optional[str],
        typer.Option("-o", "--output-dir", help="Directory for joined CSV report"),
    ] = None,
) -> None:
    """Export monster definitions, live actors, spawn eggs, and placements."""
    raise SystemExit(
        cmd_monster_report(
            SimpleNamespace(
                static=static,
                gamedat=gamedat,
                live_source=live_source,
                mod_monsters=mod_monsters,
                mod_equip=mod_equip,
                mod=mod,
                game=game,
                output_dir=output_dir,
            )
        )
    )


def npc_equipment_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to save archive, GAMEDAT directory, or npc.dat"),
    ],
    static: Annotated[
        Optional[str],
        typer.Option("--static", help="Path to STATIC directory"),
    ] = None,
    npc: Annotated[
        Optional[str],
        typer.Option(
            "--npc",
            help="NPC number filter, comma-separated; accepts decimal or 0xHEX",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: csv"),
    ] = "csv",
    patch_dir: Annotated[
        Optional[str],
        typer.Option(
            "--patch-dir", help="Sparse mod READY and shape metadata overrides"
        ),
    ] = None,
    custom_game: Annotated[
        bool,
        typer.Option(
            "--custom-game", help="Use custom-game STATIC supplemental metadata"
        ),
    ] = False,
) -> None:
    """Dump actual NPC inventory/equipment with readied/backpack location split."""
    raise SystemExit(
        cmd_npc_equipment(
            SimpleNamespace(
                file=file,
                static=static,
                npc=npc,
                game=game,
                output=output,
                format=format,
                patch_dir=patch_dir,
                custom_game=custom_game,
            )
        )
    )
