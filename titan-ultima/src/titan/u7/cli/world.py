"""``titan u7 ireg-dump`` / ``world-query`` / ``container-browse`` / ``egg-query`` — world object query commands."""

from __future__ import annotations

__all__ = ["ireg_dump_cmd", "world_query_cmd", "container_browse_cmd", "egg_query_cmd"]

import json
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

import typer

from titan.u7 import install


def ireg_dump_cmd(
    file: Annotated[str, typer.Argument(help="Raw U7IREG stream to inspect")],
    static: Annotated[
        Optional[str],
        typer.Option("--static", help="Owner's STATIC for class metadata"),
    ] = None,
    patch_dir: Annotated[
        Optional[str], typer.Option("--patch-dir", help="Owner's sparse metadata patch")
    ] = None,
    game: Annotated[Literal["bg", "si"], typer.Option("--game")] = "bg",
    custom_game: Annotated[
        bool, typer.Option("--custom-game", help="Use custom STATIC text defaults")
    ] = False,
    superchunk: Annotated[
        int,
        typer.Option("--superchunk", min=0, max=143, help="World placement context"),
    ] = 0,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write a new JSON file (default: stdout)"),
    ] = None,
) -> None:
    """Inspect objects, saved slot IDs and specials, retaining the complete raw stream."""
    from dataclasses import asdict
    from titan.u7.map import U7MapRenderer
    from titan.u7.ireg_metadata import U7IregContext
    from titan.u7.world import WorldQueryParams, load_ireg_context, load_query_metadata

    try:
        context = U7IregContext(game=game)
        if static:
            params = WorldQueryParams(
                static_dir=static,
                base_static=static,
                patch_dir=patch_dir,
                game=game,
                custom_game=custom_game,
            )
            context = load_ireg_context(params, load_query_metadata(params)[0])
        elif patch_dir:
            raise ValueError("IREG --patch-dir requires --static")
        source = Path(file)
        stream = U7MapRenderer.parse_ireg_stream(
            source.read_bytes(), superchunk, context=context
        )
        report = {
            "file": str(source),
            "game": game,
            "superchunk": superchunk,
            "objects": [asdict(obj) for obj in stream.objects],
            "stream": asdict(stream.extras),
        }
        content = json.dumps(report, indent=2) + "\n"
        if output:
            destination = Path(output)
            if destination.resolve() == source.resolve():
                raise ValueError("IREG report output must differ from the source file")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as target:
                target.write(content)
        else:
            print(content, end="")
        for warning in stream.extras.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        if context is not None:
            for warning in context.warnings:
                print(f"WARNING: {warning}", file=sys.stderr)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


def world_query_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Optional[Literal["bg", "si"]],
        typer.Option("--game", help="Use config section for BG or SI (default: bg)"),
    ] = None,
    config: Annotated[
        Optional[str],
        typer.Option(
            "-c", "--config", help="Run a world-query TOML recipe without prompts"
        ),
    ] = None,
    base_static: Annotated[
        Optional[str],
        typer.Option("--base-static", help="Original STATIC for a mod patch"),
    ] = None,
    patch: Annotated[
        Optional[str],
        typer.Option("--patch", help="Mod patch overriding the base STATIC"),
    ] = None,
    mod_data: Annotated[
        Optional[str],
        typer.Option("--mod-data", help="Mod textmsg.txt and shape_info.txt directory"),
    ] = None,
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat", help="Path to gamedat/ directory for IREG dynamic objects"
        ),
    ] = None,
    text: Annotated[
        Optional[str],
        typer.Option("--text", help="Path to TEXT.FLX for shape name lookup"),
    ] = None,
    # ── Non-interactive filters ──────────────────────────────────────────────
    shape_class: Annotated[
        Optional[list[str]],
        typer.Option(
            "--class",
            help="Shape class filter (repeatable): container, human, monster, …",
        ),
    ] = None,
    shape_num: Annotated[
        Optional[list[str]],
        typer.Option(
            "--shape",
            help="Shape number filter, hex or decimal (repeatable): 522, 0x20A",
        ),
    ] = None,
    frame: Annotated[
        Optional[list[str]],
        typer.Option("--frame", help="Frame filter, decimal or hex (repeatable)"),
    ] = None,
    name: Annotated[
        Optional[str],
        typer.Option("--name", help="Shape name substring filter (case-insensitive)"),
    ] = None,
    flag: Annotated[
        Optional[list[str]],
        typer.Option(
            "--flag", help="TFA flag filter (repeatable): solid, animated, door, …"
        ),
    ] = None,
    tile_rect: Annotated[
        Optional[str],
        typer.Option("--tile-rect", help="Tile rectangle filter: tx0,ty0,tx1,ty1"),
    ] = None,
    sc: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Superchunk number filter, hex or decimal (repeatable): 0x55"
        ),
    ] = None,
    ireg: Annotated[
        Optional[bool],
        typer.Option(
            "--ireg/--no-ireg", help="Include IREG dynamic objects (default: auto)"
        ),
    ] = None,
    ifix: Annotated[
        Optional[bool],
        typer.Option("--ifix/--no-ifix", help="Include fixed objects (default: yes)"),
    ] = None,
    map_num: Annotated[
        Optional[int],
        typer.Option(
            "--map-num",
            help="Map number: 0 = default world map, 1+ = mapNN/ subdirectory inside STATIC and gamedat (default: 0)",
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), full_text, csv"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing results file"),
    ] = False,
) -> None:
    """Query world object placements from IFIX and IREG.

    With no filter flags, launches an interactive wizard (requires questionary).
    Supply any filter flag to run non-interactively.

    \\b
    Non-interactive examples:
      titan u7 world-query STATIC/ --gamedat gamedat/ --class container --tile-rect 512,512,2048,2048
      titan u7 world-query STATIC/ --name "locked chest" --ireg --gamedat gamedat/ -f csv -o out.csv
      titan u7 world-query STATIC/ --shape 522 --ireg --gamedat gamedat/ -f full_text
    """
    from titan.u7.world import (
        run_wizard as _world_wizard,
        WorldQueryParams,
        run_query,
        format_result,
        parse_numbers,
        parse_rectangle,
        validate_params,
    )
    from titan.u7.world_workflow import load_recipe, report_warnings, write_results
    from titan.u7.typeflag import U7TypeFlags

    try:
        params = load_recipe(config) if config else WorldQueryParams(static_dir="")
        params.game = game or params.game
        configured_static, _ = install.resolve_u7_static_and_palette(params.game)
        params.static_dir = (
            static or params.static_dir or base_static or configured_static or ""
        )
        params.base_static = base_static or params.base_static
        params.patch_dir = patch or params.patch_dir
        params.mod_data_dir = mod_data or params.mod_data_dir
        params.gamedat_dir = (
            gamedat or params.gamedat_dir or install.resolve_u7_gamedat(params.game)
        )
        params.text_flx_path = text or params.text_flx_path
        if (
            not config
            and not static
            and not params.patch_dir
            and not params.text_flx_path
            and not any(
                part.lower() in {"patch", "mods"}
                for part in Path(params.static_dir).parts
            )
        ):
            params.text_flx_path = install.resolve_u7_text_flx(
                params.game, params.static_dir
            )
        if not params.base_static and params.static_dir and not params.patch_dir:
            selected_path = Path(params.static_dir)
            if any(part.lower() in {"patch", "mods"} for part in selected_path.parts):
                params.base_static = install.resolve_u7_patch_base_static(
                    params.static_dir, configured_static
                )
        if map_num is not None:
            params.map_num = map_num
        non_interactive = (
            config is not None
            or any(
                value is not None
                for value in (
                    shape_class,
                    shape_num,
                    frame,
                    name,
                    flag,
                    tile_rect,
                    sc,
                    format,
                    output,
                    ireg,
                    ifix,
                )
            )
            or force
        )
        if not non_interactive:
            raise SystemExit(
                _world_wizard(
                    static_dir=params.static_dir,
                    gamedat_dir=params.gamedat_dir,
                    text_flx=params.text_flx_path,
                    game=params.game,
                    map_num=params.map_num,
                    base_static=params.base_static,
                    patch_dir=params.patch_dir,
                    mod_data_dir=params.mod_data_dir,
                )
            )

        if shape_class is not None:
            class_map = {v: k for k, v in U7TypeFlags.SHAPE_CLASS_NAMES.items()}
            params.shape_classes = []
            for cls_name in shape_class:
                cid = class_map.get(cls_name.lower())
                if cid is None:
                    raise ValueError(
                        f"Unknown shape class: {cls_name!r}. Valid: {', '.join(class_map)}"
                    )
                params.shape_classes.append(cid)
        for tokens, field_name, maximum, label in (
            (shape_num, "shape_nums", 65535, "Shape number"),
            (frame, "frames", 255, "Frame number"),
            (sc, "superchunks", 143, "Superchunk"),
        ):
            if tokens is not None:
                if any(not token.strip() for token in tokens):
                    raise ValueError(f"{label} must not be blank")
                setattr(
                    params, field_name, parse_numbers(",".join(tokens), maximum, label)
                )
        if name is not None:
            params.name_filter = name
        if flag is not None:
            params.tfa_flags = list(flag)
        if tile_rect is not None:
            params.tile_rect = parse_rectangle(tile_rect)
        if ireg is not None:
            params.include_ireg = ireg
        elif not config:
            params.include_ireg = bool(
                params.gamedat_dir
                and any(c in (6, 7, 12, 13) for c in params.shape_classes)
            )
        if ifix is not None:
            params.include_ifix = ifix
        if format is not None:
            params.output_format = format
        if output is not None:
            params.output_path = output
        validate_params(params)
        result = run_query(params)
        report_warnings(result)
        if params.output_path:
            write_results(result, params.output_path, overwrite=force)
            typer.echo(f"Wrote {result.count} result(s) to {params.output_path}")
        else:
            typer.echo(format_result(result))
    except (OSError, ValueError) as error:
        typer.echo(f"World query failed: {error}", err=True)
        raise SystemExit(1) from error


def container_browse_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    custom_game: Annotated[
        bool,
        typer.Option(
            "--custom-game", help="Use custom-game STATIC container/gump defaults"
        ),
    ] = False,
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat", help="Path to gamedat/ directory (required for IREG)"
        ),
    ] = None,
    text: Annotated[
        Optional[str],
        typer.Option("--text", help="Path to TEXT.FLX for shape name lookup"),
    ] = None,
    exult_flx: Annotated[
        Optional[str],
        typer.Option(
            "--exult-flx",
            help="Path to exult_bg.flx (or exult_si.flx) for per-frame item names",
        ),
    ] = None,
    mod_data: Annotated[
        Optional[str],
        typer.Option(
            "--mod-data",
            help="Path to mod patch/data directory (textmsg.txt + shape_info.txt for mod-specific names)",
        ),
    ] = None,
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help="Map number to query: 0 = default world map, 1+ = mod map subdirectory (mapNN/)",
        ),
    ] = 0,
    # ── Container identity filters ───────────────────────────────────────────
    container_shape: Annotated[
        Optional[list[str]],
        typer.Option(
            "--container-shape",
            help="Container shape number(s), hex or decimal (repeatable)",
        ),
    ] = None,
    container_name: Annotated[
        Optional[str],
        typer.Option(
            "--container-name",
            help="Container name substring filter (case-insensitive)",
        ),
    ] = None,
    # ── Contents filters ─────────────────────────────────────────────────────
    contains_shape: Annotated[
        Optional[list[str]],
        typer.Option(
            "--contains-shape",
            help="Only show containers holding item with this shape (repeatable)",
        ),
    ] = None,
    contains_name: Annotated[
        Optional[str],
        typer.Option(
            "--contains-name",
            help="Only show containers holding item matching name substring",
        ),
    ] = None,
    # ── Area filters ─────────────────────────────────────────────────────────
    tile_rect: Annotated[
        Optional[str],
        typer.Option("--tile-rect", help="Tile rectangle filter: tx0,ty0,tx1,ty1"),
    ] = None,
    sc: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Superchunk number filter, hex or decimal (repeatable)"
        ),
    ] = None,
    # ── Output ───────────────────────────────────────────────────────────────
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: tree (default), csv"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Browse container contents from IREG, with full nesting support.

    With no filter flags, launches an interactive wizard (requires questionary).
    Supply any filter flag to run non-interactively.

    \\b
    Non-interactive examples:
      titan u7 container-browse STATIC/ --gamedat gamedat/
      titan u7 container-browse STATIC/ --gamedat gamedat/ --container-name chest
      titan u7 container-browse STATIC/ --gamedat gamedat/ --container-shape 522
      titan u7 container-browse STATIC/ --gamedat gamedat/ --contains-name sword -f csv -o containers.csv
      titan u7 container-browse STATIC/ --gamedat gamedat/ --tile-rect 512,512,2048,2048 -f tree
    """
    from titan.u7.container import (
        browse_containers,
        ContainerQueryParams,
        format_results,
        run_wizard as _container_wizard,
    )
    from titan.u7.text_names import load_u7_text_names
    from titan.u7.typeflag import U7TypeFlags
    from titan._config import exult_cfg

    static_dir = static
    if not static_dir:
        resolved, _ = install.resolve_u7_static_and_palette(game)
        static_dir = resolved

    gamedat_dir = gamedat
    if not gamedat_dir:
        gamedat_dir = install.resolve_u7_gamedat(game)

    _non_interactive = any(
        [
            container_shape,
            container_name,
            contains_shape,
            contains_name,
            tile_rect,
            sc,
            format,
            output,
        ]
    )

    _exult_flx = exult_flx or exult_cfg(f"{game}_flx") or None

    if not _non_interactive:
        raise SystemExit(
            _container_wizard(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
                text_flx=text,
                exult_flx_path=_exult_flx,
                mod_data_dir=mod_data,
                map_num=map_num,
                game=game,
                custom_game=custom_game,
            )
        )

    # ── Parse filters ────────────────────────────────────────────────────────
    container_shape_nums: list[int] = []
    if container_shape:
        for token in container_shape:
            try:
                container_shape_nums.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid shape number: {token!r}", err=True)
                raise SystemExit(1)

    contains_shape_nums: list[int] = []
    if contains_shape:
        for token in contains_shape:
            try:
                contains_shape_nums.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid shape number: {token!r}", err=True)
                raise SystemExit(1)

    superchunks: list[int] = []
    if sc:
        for token in sc:
            try:
                superchunks.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid superchunk number: {token!r}", err=True)
                raise SystemExit(1)

    parsed_rect: Optional[tuple[int, int, int, int]] = None
    if tile_rect:
        parts = tile_rect.split(",")
        if len(parts) != 4:
            typer.echo("--tile-rect must be tx0,ty0,tx1,ty1", err=True)
            raise SystemExit(1)
        try:
            tx0, ty0, tx1, ty1 = (int(p.strip(), 0) for p in parts)
            parsed_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
        except ValueError:
            typer.echo("--tile-rect values must be integers", err=True)
            raise SystemExit(1)

    if not gamedat_dir:
        typer.echo(
            "Error: --gamedat is required for container-browse (containers live in IREG)",
            err=True,
        )
        raise SystemExit(1)

    selected_names = load_u7_text_names(
        static_dir,
        patch_dirs=[mod_data] if mod_data else (),
        text_flx_path=text,
        exult_flx_path=_exult_flx or install.resolve_u7_exult_flx(game),
        game=game,
    )
    names, frame_names = selected_names.names, selected_names.frames

    params = ContainerQueryParams(
        static_dir=static_dir or "",
        gamedat_dir=gamedat_dir,
        container_shape_nums=container_shape_nums,
        container_name_filter=container_name or "",
        contains_shape_nums=contains_shape_nums,
        contains_name_filter=contains_name or "",
        superchunks=superchunks,
        tile_rect=parsed_rect,
        text_flx_path=text,
        exult_flx_path=_exult_flx,
        game=game,
        custom_game=custom_game,
        map_num=map_num,
        output_format=format or "tree",
        output_path=output,
    )

    tfa: Optional[U7TypeFlags] = None
    try:
        tfa = U7TypeFlags.from_dir(static_dir) if static_dir else None
    except (FileNotFoundError, OSError):
        pass

    results = browse_containers(params)
    out = format_results(results, params, names, frame_names, tfa)

    if output:
        from pathlib import Path as _Path

        _Path(output).write_text(out, encoding="utf-8")
        typer.echo(f"Wrote {len(results)} container(s) to {output}")
    else:
        typer.echo(out)


def egg_query_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    gamedat: Annotated[
        Optional[str],
        typer.Option("--gamedat", help="Path to gamedat/ directory (required)"),
    ] = None,
    egg_type: Annotated[
        Optional[list[str]],
        typer.Option(
            "--type", help="Egg type filter (repeatable): usecode, monster, teleport, …"
        ),
    ] = None,
    fn: Annotated[
        Optional[str],
        typer.Option(
            "--fn", help="Usecode function number filter, hex or decimal: 0x06BC"
        ),
    ] = None,
    tile_rect: Annotated[
        Optional[str],
        typer.Option("--tile-rect", help="Tile rectangle filter: tx0,ty0,tx1,ty1"),
    ] = None,
    sc: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Superchunk number filter, hex or decimal (repeatable)"
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: table (default), csv"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Query egg trigger objects from IREG, showing type, function, and location.

    With no filter flags, launches an interactive wizard (requires questionary).
    Supply any filter flag to run non-interactively.

    \\b
    Non-interactive examples:
      titan u7 egg-query STATIC/ --gamedat gamedat/
      titan u7 egg-query STATIC/ --gamedat gamedat/ --type usecode
      titan u7 egg-query STATIC/ --gamedat gamedat/ --fn 0x06BC
      titan u7 egg-query STATIC/ --gamedat gamedat/ --type monster --tile-rect 512,512,2048,2048
      titan u7 egg-query STATIC/ --gamedat gamedat/ --type usecode -f csv -o eggs.csv
    """
    from titan.u7.eggs import (
        query_eggs,
        EggQueryParams,
        format_results,
        run_wizard as _egg_wizard,
    )

    static_dir = static
    if not static_dir:
        resolved, _ = install.resolve_u7_static_and_palette(game)
        static_dir = resolved

    gamedat_dir = gamedat
    if not gamedat_dir:
        gamedat_dir = install.resolve_u7_gamedat(game)

    _non_interactive = any([egg_type, fn, tile_rect, sc, format, output])

    if not _non_interactive:
        raise SystemExit(
            _egg_wizard(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
                game=game,
            )
        )

    # ── Validate --type values ───────────────────────────────────────────────
    from titan.u7.map import EGG_TYPE_NAMES as _ETN

    _valid_types = set(_ETN.values())
    for t in egg_type or []:
        if t not in _valid_types:
            typer.echo(
                f"Unknown egg type: {t!r}. Valid: {', '.join(sorted(_valid_types))}",
                err=True,
            )
            raise SystemExit(1)

    # ── Parse --fn ───────────────────────────────────────────────────────────
    fn_filter: Optional[int] = None
    if fn:
        try:
            fn_filter = int(fn, 0)
        except ValueError:
            typer.echo(f"Invalid function number: {fn!r}", err=True)
            raise SystemExit(1)

    # ── Parse --sc ───────────────────────────────────────────────────────────
    superchunks: list[int] = []
    if sc:
        for token in sc:
            try:
                superchunks.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid superchunk number: {token!r}", err=True)
                raise SystemExit(1)

    # ── Parse --tile-rect ────────────────────────────────────────────────────
    parsed_rect: Optional[tuple[int, int, int, int]] = None
    if tile_rect:
        parts = tile_rect.split(",")
        if len(parts) != 4:
            typer.echo("--tile-rect must be tx0,ty0,tx1,ty1", err=True)
            raise SystemExit(1)
        try:
            tx0, ty0, tx1, ty1 = (int(p.strip(), 0) for p in parts)
            parsed_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
        except ValueError:
            typer.echo("--tile-rect values must be integers", err=True)
            raise SystemExit(1)

    if not gamedat_dir:
        typer.echo(
            "Error: --gamedat is required for egg-query (eggs live in IREG)", err=True
        )
        raise SystemExit(1)

    params = EggQueryParams(
        static_dir=static_dir or "",
        gamedat_dir=gamedat_dir,
        egg_types=list(egg_type) if egg_type else [],
        fn_filter=fn_filter,
        superchunks=superchunks,
        tile_rect=parsed_rect,
        output_format=format or "table",
        output_path=output,
    )

    results = query_eggs(params)
    out = format_results(results, params)

    if output:
        from pathlib import Path as _Path

        _Path(output).write_text(out, encoding="utf-8")
        typer.echo(f"Wrote {len(results)} egg(s) to {output}")
    else:
        typer.echo(out)
