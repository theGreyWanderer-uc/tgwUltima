"""Ultima III NES CLI sub-app."""

from __future__ import annotations

__all__ = ["u3_app"]

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u3.u3_nes_map_create import create_u3_nes_sosaria_map


u3_app = typer.Typer(
    name="u3",
    help="Ultima III NES map conversion commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _is_interactive_terminal() -> bool:
    """Return whether asking a post-create question is safe."""
    return bool(sys.stdin.isatty())


def _render_created_map(args: SimpleNamespace) -> int:
    """Render a newly created native map through Titan's U7 renderer."""
    from titan.u7.cli import cmd_map_render

    output = args.render_output or str(
        Path(args.output_root).resolve()
        / f"u3_sosaria_map{args.map_num:02x}_classic.png"
    )
    return cmd_map_render(
        SimpleNamespace(
            game="si",
            static=args.static,
            map_root=args.output_root,
            superchunk=None,
            chunk_x0=0,
            chunk_y0=0,
            chunk_x1=191,
            chunk_y1=191,
            palette=args.palette,
            output=output,
            view="classic",
            gamedat=args.gamedat_root,
            grid=False,
            grid_size=1,
            exclude_flags=None,
            max_lift=None,
            map_num=args.map_num,
            highlight_rects=[],
            highlight_width=3,
            highlight_lift=0,
            highlight_fill_alpha=128,
            highlight_labels=True,
        )
    )


def cmd_map_create(args: SimpleNamespace) -> int:
    """Generate U3 Sosaria, materialize native U7 data, then offer a render."""
    from titan.u7.map_json import U7MapJsonError
    from titan.u7.native_map_create import U7NativeMapCreateError

    if args.render is True and (args.json_only or args.dry_run):
        print(
            "ERROR: --render requires native map creation; "
            "remove --json-only/--dry-run",
            file=sys.stderr,
        )
        return 1

    try:
        result = create_u3_nes_sosaria_map(
            args.si_source_json,
            args.output_root,
            map_number=args.map_num,
            seed=args.seed,
            json_output=args.json_output,
            json_only=args.json_only,
            pretty_json=args.pretty,
            gamedat_root=args.gamedat_root,
            overwrite_map=args.overwrite_map,
            update_chunks=args.update_chunks,
            dry_run=args.dry_run,
        )
    except (OSError, U7MapJsonError, U7NativeMapCreateError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if result.json_path is not None:
        print(f"Universal JSON: {result.json_path}")
    if result.json_only:
        print(
            f"Built U3 Sosaria JSON at seed {result.seed}; native map creation skipped."
        )
        return 0

    native = result.native_map
    if native is None:
        print("ERROR: U3 map create produced no native-map result", file=sys.stderr)
        return 1
    action = "Would create" if native.dry_run else "Created"
    print(f"{action} native U7 map {native.map_number:02x}: {native.map_directory}")
    print(
        f"U7MAP: {native.u7map_bytes} bytes; "
        f"IFIX: {native.ifix_files} files / {native.fixed_objects} objects"
    )
    print(
        f"U7CHUNKS: {native.chunks_action}; "
        f"{native.definitions_written} definitions "
        f"({native.definitions_appended} appended)"
    )
    if native.dry_run:
        return 0

    render = args.render
    if render is None and _is_interactive_terminal():
        print(
            "Full classic render is about 24704x24704 pixels and may use "
            "significant time and memory."
        )
        render = typer.confirm(
            "Would you also like to render it in classic isometric format?",
            default=False,
        )
    if not render:
        return 0
    return _render_created_map(args)


@u3_app.command("map-create")
def map_create_cmd(
    si_source_json: Annotated[
        str,
        typer.Argument(help="Universal JSON export of the original Serpent Isle map"),
    ],
    output_root: Annotated[
        str,
        typer.Option(
            "--output-root",
            help="Required PATCH-like root where mapNN and shared u7chunks are written",
        ),
    ],
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help="Secondary U7 map number; 4 becomes map04",
        ),
    ] = 4,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Deterministic U3 map-generation seed"),
    ] = 42,
    json_output: Annotated[
        Optional[str],
        typer.Option(
            "--json-output",
            help="Optionally preserve generated universal U7 JSON",
        ),
    ] = None,
    json_only: Annotated[
        bool,
        typer.Option(
            "--json-only",
            help="Write --json-output without creating native map files",
        ),
    ] = False,
    pretty: Annotated[
        bool,
        typer.Option("--pretty/--compact", help="Pretty or compact optional JSON"),
    ] = False,
    gamedat_root: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat-root",
            help="Optional GAMEDAT-like root for matching empty mapNN namespace",
        ),
    ] = None,
    overwrite_map: Annotated[
        bool,
        typer.Option(
            "--overwrite-map",
            help="Explicitly permit replacement of an existing mapNN namespace",
        ),
    ] = False,
    update_chunks: Annotated[
        bool,
        typer.Option(
            "--update-chunks",
            help="Explicitly permit appending definitions to existing u7chunks",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Validate and report native files without writing them",
        ),
    ] = False,
    render: Annotated[
        Optional[bool],
        typer.Option(
            "--render/--no-render",
            help="Render classic world now, skip it, or prompt on an interactive terminal",
        ),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="U7 STATIC graphics for rendering; defaults to configured SI STATIC",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="PALETTES.FLX for rendering; defaults to configured SI palette",
        ),
    ] = None,
    render_output: Annotated[
        Optional[str],
        typer.Option(
            "--render-output",
            help="Classic PNG path; defaults beside generated mapNN",
        ),
    ] = None,
) -> None:
    """Create SI-sized native U7 map data from embedded U3 NES Sosaria."""
    raise SystemExit(
        cmd_map_create(
            SimpleNamespace(
                si_source_json=si_source_json,
                output_root=output_root,
                map_num=map_num,
                seed=seed,
                json_output=json_output,
                json_only=json_only,
                pretty=pretty,
                gamedat_root=gamedat_root,
                overwrite_map=overwrite_map,
                update_chunks=update_chunks,
                dry_run=dry_run,
                render=render,
                static=static,
                palette=palette,
                render_output=render_output,
            )
        )
    )
