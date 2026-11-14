"""``titan u7 typeflag-dump`` / ``wihh-dump`` / ``static-data-dump`` — static game data table commands."""

from __future__ import annotations

__all__ = ["typeflag_dump_cmd", "wihh_dump_cmd", "static_data_dump_cmd"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.u7 import install
from titan.u7.cli import _common


def cmd_typeflag_dump(args: SimpleNamespace) -> int:
    """Dump U7 type flag information."""
    from titan.u7.typeflag import U7TypeFlags

    static_dir = args.static
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    tfa = U7TypeFlags.from_dir(static_dir)
    print(f"Loaded {len(tfa)} shape entries from {static_dir}")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = tfa.dump_csv()
    elif fmt == "detail":
        content = tfa.dump_detail()
    else:
        content = tfa.dump_summary()

    if args.output:
        out_path = args.output
        with open(out_path, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {out_path}")
    else:
        # Print stats to terminal (always useful)
        stats = tfa._compute_stats()
        for label, count in stats:
            if label == "":
                print()
            elif label.startswith("---"):
                print(f"\n{label}")
            else:
                print(f"  {label:30s}: {count:5d}")

    return 0


def cmd_wihh_dump(args: SimpleNamespace) -> int:
    """Dump U7 weapon attachment coordinates from WIHH.DAT."""
    from titan.u7.names import U7ShapeNames
    from titan.u7.wihh import U7WeaponInHandOffsets

    static_dir = args.static
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not static_dir or not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    shape_count = _common._load_shape_count(args, fallback_static=static_dir)
    wihh = U7WeaponInHandOffsets.from_dir(static_dir, shape_count=shape_count)
    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        names = U7ShapeNames.from_static_dir(static_dir)
        content = wihh.dump_csv(
            names,
            include_empty=getattr(args, "include_empty", False),
        )
    else:
        content = wihh.dump_summary()

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"WIHH dump written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_static_data_dump(args: SimpleNamespace) -> int:
    """Dump U7 static metadata tables."""
    from titan.u7.gameplay_metadata import validate_gameplay_format
    from titan.u7.names import U7ShapeNames
    from titan.u7.shapeinfo import (
        U7Ammos,
        U7Armors,
        U7Blends,
        U7Containers,
        U7UsecodeIndex,
        U7Weapons,
        U7Xforms,
    )

    kind = args.kind.lower()
    try:
        data_format = validate_gameplay_format(getattr(args, "data_format", "exult"))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if data_format == "retail" and kind not in (
        "weapons",
        "weapon",
        "ammo",
        "ammos",
        "armor",
        "armors",
    ):
        print(
            "ERROR: --data-format retail supports weapon, ammo and armor dumps.",
            file=sys.stderr,
        )
        return 1
    source_file = getattr(args, "file", None)
    if source_file and kind not in (
        "container",
        "containers",
        "weapons",
        "weapon",
        "ammo",
        "ammos",
        "armor",
        "armors",
    ):
        print(
            "ERROR: --file is for explicit container/combat metadata inspection.",
            file=sys.stderr,
        )
        return 1
    static_dir = args.static or (str(Path(source_file).parent) if source_file else None)
    if not static_dir:
        static_dir, _ = install.resolve_u7_static_and_palette(
            getattr(args, "game", "bg")
        )
    if not static_dir or not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    names = U7ShapeNames.from_static_dir(static_dir)
    game = getattr(args, "game", "bg")
    exult_flx_path = getattr(args, "exult_flx", None) or install.resolve_u7_exult_flx(
        game
    )
    metadata_warnings: list[str] = []
    if kind in ("weapons", "weapon"):
        try:
            weapons = (
                U7Weapons.from_file(source_file, game=game, data_format=data_format)
                if source_file
                else U7Weapons.from_dir(
                    static_dir,
                    game=game,
                    patch_dir=getattr(args, "patch_dir", None),
                    data_format=data_format,
                )
            )
        except (OSError, ValueError) as error:
            print(f"ERROR: weapon metadata unavailable: {error}", file=sys.stderr)
            return 1
        content = weapons.dump_csv(names)
        label = f"{len(weapons.records)} weapon row(s)"
        metadata_warnings = weapons.warnings
    elif kind in ("ammo", "ammos"):
        try:
            ammos = (
                U7Ammos.from_file(source_file, data_format=data_format)
                if source_file
                else U7Ammos.from_dir(
                    static_dir,
                    patch_dir=getattr(args, "patch_dir", None),
                    data_format=data_format,
                )
            )
        except (OSError, ValueError) as error:
            print(f"ERROR: ammo metadata unavailable: {error}", file=sys.stderr)
            return 1
        content = ammos.dump_csv(names)
        label = f"{len(ammos.records)} ammo row(s)"
        metadata_warnings = ammos.warnings
    elif kind in ("armor", "armors"):
        try:
            armors = (
                U7Armors.from_file(source_file, data_format=data_format)
                if source_file
                else U7Armors.from_dir(
                    static_dir,
                    patch_dir=getattr(args, "patch_dir", None),
                    data_format=data_format,
                )
            )
        except (OSError, ValueError) as error:
            print(f"ERROR: armor metadata unavailable: {error}", file=sys.stderr)
            return 1
        content = armors.dump_csv(names)
        label = f"{len(armors.records)} armor row(s)"
        metadata_warnings = armors.warnings
    elif kind in ("container", "containers"):
        try:
            containers = (
                U7Containers.from_file(source_file)
                if source_file
                else U7Containers.from_dir(
                    static_dir,
                    game=game,
                    exult_flx_path=exult_flx_path,
                    patch_dir=getattr(args, "patch_dir", None),
                    custom_game=getattr(args, "custom_game", False),
                )
            )
        except (OSError, ValueError) as error:
            print(f"ERROR: container metadata unavailable: {error}", file=sys.stderr)
            return 1
        content = containers.dump_csv(names)
        label = f"{len(containers.records)} container row(s)"
        metadata_warnings = containers.warnings
    elif kind in ("gump", "gumps"):
        from titan.u7.gump_metadata import load_u7_gump_sources, read_u7_gump_metadata

        try:
            gumps = read_u7_gump_metadata(
                load_u7_gump_sources(
                    static_dir,
                    patch_dir=getattr(args, "patch_dir", None),
                    game=game,
                    exult_flx=exult_flx_path,
                    custom_game=getattr(args, "custom_game", False),
                )
            )
        except (OSError, ValueError) as error:
            print(f"ERROR: gump metadata unavailable: {error}", file=sys.stderr)
            return 1
        content = gumps.dump_csv()
        label = "gump layout/checkmark metadata"
        metadata_warnings = gumps.warnings
    elif kind in ("paperdoll", "paperdol"):
        from titan.u7.gump_metadata import load_u7_gump_sources
        from titan.u7.paperdoll_metadata import read_u7_paperdoll_metadata

        try:
            paperdoll = read_u7_paperdoll_metadata(
                load_u7_gump_sources(
                    static_dir,
                    patch_dir=getattr(args, "patch_dir", None),
                    game=game,
                    exult_flx=exult_flx_path,
                    custom_game=getattr(args, "custom_game", False),
                )
            )
        except (OSError, ValueError) as error:
            print(f"ERROR: paperdoll metadata unavailable: {error}", file=sys.stderr)
            return 1
        content = paperdoll.dump_csv()
        label = "paperdoll character/item/layout metadata"
        metadata_warnings = paperdoll.warnings
    elif kind in ("xform", "xforms"):
        xforms = U7Xforms.from_dir(static_dir)
        content = xforms.dump_csv()
        label = f"{len(xforms.tables)} xform table(s)"
    elif kind in ("blend", "blends"):
        blends = U7Blends.from_dir(
            static_dir,
            game=game,
            exult_flx_path=exult_flx_path,
        )
        content = blends.dump_csv()
        label = f"{len(blends.records)} blend row(s)"
    elif kind in ("usecode",):
        path = Path(static_dir) / "usecode"
        if not path.is_file():
            path = Path(static_dir) / "USECODE"
        if not path.is_file():
            print(f"ERROR: usecode file not found in {static_dir}", file=sys.stderr)
            return 1
        try:
            usecode = U7UsecodeIndex.from_file(str(path))
        except (OSError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        content = usecode.dump_csv()
        label = f"{len(usecode.functions)} usecode function row(s)"
        metadata_warnings = usecode.warnings
    else:
        print(
            "ERROR: kind must be weapons, ammo, armor, container, gumps, paperdoll, xforms, blends, or usecode",
            file=sys.stderr,
        )
        return 1

    for warning in metadata_warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"{kind} dump written to: {args.output} ({label})")
    else:
        if content:
            print(content, end="" if content.endswith("\n") else "\n")
        else:
            print(f"No data parsed ({label}).")
    return 0


def typeflag_dump_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory containing TFA.DAT (default: from titan.toml u7bg/u7si)"
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
    """Dump U7 type flag data (TFA.DAT, SHPDIMS.DAT, WGTVOL.DAT, OCCLUDE.DAT)."""
    raise SystemExit(
        cmd_typeflag_dump(
            SimpleNamespace(
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


def wihh_dump_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory containing WIHH.DAT (default: from titan.toml u7bg/u7si)"
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
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
    include_empty: Annotated[
        bool,
        typer.Option(
            "--include-empty",
            help="Include shapes with no WIHH record in CSV output",
        ),
    ] = False,
) -> None:
    """Dump U7 WIHH.DAT weapon attachment coordinates."""
    raise SystemExit(
        cmd_wihh_dump(
            SimpleNamespace(
                game=game,
                static=static,
                output=output,
                format=format,
                include_empty=include_empty,
            )
        )
    )


def static_data_dump_cmd(
    kind: Annotated[
        str,
        typer.Argument(
            help="Table to dump: weapons, ammo, armor, container, gumps, paperdoll, xforms, blends, usecode"
        ),
    ],
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write CSV dump to this file"),
    ] = None,
    exult_flx: Annotated[
        Optional[str],
        typer.Option(
            "--exult-flx",
            help="Path to exult_bg.flx/exult_si.flx for Exult bundled fallbacks",
        ),
    ] = None,
    patch_dir: Annotated[
        Optional[str],
        typer.Option(
            "--patch-dir", help="Combat/container/gump metadata patch directory"
        ),
    ] = None,
    custom_game: Annotated[
        bool,
        typer.Option(
            "--custom-game", help="Use custom-game STATIC container/gump defaults"
        ),
    ] = False,
    file: Annotated[
        Optional[str],
        typer.Option(
            "--file",
            help="Inspect an explicit container/combat file independently of world defaults",
        ),
    ] = None,
    data_format: Annotated[
        Literal["exult", "retail"],
        typer.Option(
            "--data-format",
            help="Weapon/ammo/armor count, removal and field interpretation",
        ),
    ] = "exult",
) -> None:
    """Dump U7 static metadata tables as CSV."""
    raise SystemExit(
        cmd_static_data_dump(
            SimpleNamespace(
                kind=kind,
                game=game,
                static=static,
                output=output,
                exult_flx=exult_flx,
                patch_dir=patch_dir,
                custom_game=custom_game,
                file=file,
                data_format=data_format,
            )
        )
    )
