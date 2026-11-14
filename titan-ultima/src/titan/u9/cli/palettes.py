"""``titan u9 palette-*`` / ``shade-*`` / ``color-cube-*`` — palette and colour table commands."""

from __future__ import annotations

__all__ = [
    "palette_info_cmd",
    "palette_export_cmd",
    "shade_info_cmd",
    "shade_csv_cmd",
    "color_cube_info_cmd",
    "color_cube_lookup_cmd",
    "color_cube_csv_cmd",
]

import csv
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.palette import (
    EXPECTED_SIZE as U9_PALETTE_SIZE,
    PALETTE_TRANSPARENCY_INDEX,
    U9Palette,
    U9PaletteError,
)
from titan.u9.shade_tables import (
    EDITOR_COLOR_TABLE_SIZE,
    RAMP_LENGTH,
    RAMP_NAMES,
    SHADE_LEVEL_COUNT,
    SHADE_LIT_LEVELS,
    SHADE_TABLE_SIZE,
    U9EditorColorTable,
    U9ShadeTable,
    U9ShadeTableError,
)
from titan.u9.color_cube import (
    METRICS as COLOR_CUBE_METRICS,
    U9ColorCube,
    U9ColorCubeError,
    metric_for_filename,
)


def cmd_palette_info(args: SimpleNamespace) -> int:
    """Inspect the layout and colour statistics of a U9 ankh.pal file."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    try:
        palette = U9Palette.from_file(args.file)
    except (OSError, U9PaletteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    file_size = os.path.getsize(args.file)
    distinct = len(set(palette.colors))
    duplicate_groups = palette.duplicate_groups()
    duplicate_entries = sum(len(indices) - 1 for _, indices in duplicate_groups)
    nonzero_reserved = sum(value != 0 for value in palette.reserved)
    transparency = palette.color_for(PALETTE_TRANSPARENCY_INDEX)

    print(f"{args.file} -- Ultima IX palette")
    print(f"  File size       : {file_size} bytes")
    print("  Layout          : 256 x 4 bytes (R, G, B, reserved)")
    print(f"  Colours         : 256 entries, {distinct} distinct")
    print(
        f"  Duplicates      : {duplicate_entries} repeated entries in "
        f"{len(duplicate_groups)} colour groups"
    )
    print(f"  Reserved bytes  : {nonzero_reserved} non-zero")
    print(
        f"  Transparency    : index {PALETTE_TRANSPARENCY_INDEX} "
        f"#{transparency[0]:02X}{transparency[1]:02X}{transparency[2]:02X}"
    )
    if file_size > U9_PALETTE_SIZE:
        print(f"  Trailing data   : {file_size - U9_PALETTE_SIZE} bytes")
    if args.duplicates:
        print("\nRepeated colours:")
        for color, indices in duplicate_groups:
            index_text = ", ".join(str(index) for index in indices)
            print(
                f"  #{color[0]:02X}{color[1]:02X}{color[2]:02X} "
                f"{color!s:<17} indices {index_text}"
            )
    return 0


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export a U9 palette as a PNG swatch and lossless text table."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1
    if args.swatch_size <= 0:
        print("ERROR: --swatch-size must be greater than zero", file=sys.stderr)
        return 1
    try:
        palette = U9Palette.from_file(args.file)
    except (OSError, U9PaletteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)
    base = Path(args.file).stem
    image_path = os.path.join(outdir, f"{base}_palette.png")
    text_path = os.path.join(outdir, f"{base}_palette.txt")

    palette.to_pil_image(args.swatch_size).save(image_path)
    with open(text_path, "w", encoding="utf-8", newline="\n") as file:
        file.write(f"# Ultima IX palette from {args.file}\n")
        file.write(
            "# The fourth byte is reserved, not alpha. Texture index 254 is transparent.\n"
        )
        file.write("# Index    R    G    B  Reserved  Alpha  Hex\n")
        for index, ((r, g, b), reserved) in enumerate(
            zip(palette.colors, palette.reserved)
        ):
            alpha = palette.rgba_for(index)[3]
            file.write(
                f"{index:3d}    {r:3d}  {g:3d}  {b:3d}      "
                f"{reserved:3d}    {alpha:3d}  #{r:02X}{g:02X}{b:02X}\n"
            )

    print(f"Palette swatch saved: {image_path}  (256 colors, 16x16 grid)")
    print(f"Palette text dump: {text_path}")
    return 0


_NOT_LOADED_NOTE = "authoring-tool file; the retail game never loads it"


def _load_optional_palette_colors(
    filepath: Optional[str],
) -> tuple[bool, Optional[tuple[tuple[int, int, int], ...]]]:
    """Read colours from an optional ankh.pal; False when one was given but failed."""
    if filepath is None:
        return True, None
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return False, None
    try:
        return True, U9Palette.from_file(filepath).colors
    except (OSError, U9PaletteError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return False, None


def _load_shade_file(
    filepath: str,
) -> U9ShadeTable | U9EditorColorTable | None:
    """Open shade.tbl or shadegry.tbl, told apart by their fixed sizes."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    size = os.path.getsize(filepath)
    try:
        if size == SHADE_TABLE_SIZE:
            return U9ShadeTable.from_file(filepath)
        if size == EDITOR_COLOR_TABLE_SIZE:
            return U9EditorColorTable.from_file(filepath)
    except U9ShadeTableError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None
    print(
        f"ERROR: {filepath} is {size} bytes; expected {SHADE_TABLE_SIZE} (shade.tbl) "
        f"or {EDITOR_COLOR_TABLE_SIZE} (shadegry.tbl)",
        file=sys.stderr,
    )
    return None


def _rgb_text(colors, index: int) -> str:
    return "" if colors is None else "%d,%d,%d" % colors[index]


def cmd_shade_info(args: SimpleNamespace) -> int:
    """Summarize shade.tbl or shadegry.tbl."""
    table = _load_shade_file(args.file)
    if table is None:
        return 1
    ok, colors = _load_optional_palette_colors(args.palette)
    if not ok:
        return 1
    print(f"{args.file} -- {_NOT_LOADED_NOTE}")
    if isinstance(table, U9ShadeTable):
        anomalies = table.filler_anomalies()
        filler = table.filler_index
        print(
            f"  layout            : {SHADE_LEVEL_COUNT} light levels x 256 palette indices"
        )
        print(f"  filler index      : {filler} {_rgb_text(colors, filler)}".rstrip())
        print(
            f"  shaded levels     : {SHADE_LIT_LEVELS.start}..{SHADE_LIT_LEVELS.stop - 1}"
        )
        print(f"  filler anomalies  : {len(anomalies)}")
        return 0
    print(
        f"  layout            : {len(RAMP_NAMES)} ramps x {RAMP_LENGTH}, then a 256-entry red tint"
    )
    for name in RAMP_NAMES:
        print(f"  ramp {name:<6}       : {' '.join(str(i) for i in table.ramp(name))}")
    changed = sum(1 for index, value in enumerate(table.red_tint) if index != value)
    print(f"  red tint changes  : {changed} of 256 indices")
    return 0


def cmd_shade_csv(args: SimpleNamespace) -> int:
    """Export every cell of shade.tbl or shadegry.tbl to CSV."""
    table = _load_shade_file(args.file)
    if table is None:
        return 1
    ok, colors = _load_optional_palette_colors(args.palette)
    if not ok:
        return 1
    out_path = args.output or f"{Path(args.file).stem}_shade.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    rows = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "section",
                "position",
                "source_index",
                "output_index",
                "cell_kind",
                "source_rgb",
                "output_rgb",
            ]
        )
        if isinstance(table, U9ShadeTable):
            for level in range(SHADE_LEVEL_COUNT):
                for index, value in enumerate(table.level(level)):
                    writer.writerow(
                        [
                            f"level_{level}",
                            level,
                            index,
                            value,
                            "filler"
                            if table.is_filler_cell(level, index)
                            else "shaded",
                            _rgb_text(colors, index),
                            _rgb_text(colors, value),
                        ]
                    )
                    rows += 1
        else:
            for name in RAMP_NAMES:
                for position, value in enumerate(table.ramp(name)):
                    writer.writerow(
                        [
                            f"ramp_{name}",
                            position,
                            "",
                            value,
                            "ramp_step",
                            "",
                            _rgb_text(colors, value),
                        ]
                    )
                    rows += 1
            for index, value in enumerate(table.red_tint):
                writer.writerow(
                    [
                        "red_tint",
                        index,
                        index,
                        value,
                        "translation",
                        _rgb_text(colors, index),
                        _rgb_text(colors, value),
                    ]
                )
                rows += 1
    print(f"{args.file} -- wrote {rows} row(s) -> {out_path}")
    return 0


def _load_color_cube(filepath: str) -> Optional[U9ColorCube]:
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9ColorCube.from_file(filepath)
    except U9ColorCubeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def cmd_color_cube_info(args: SimpleNamespace) -> int:
    """Summarize a colour-cube cache and compare its palette with ankh.pal."""
    cube = _load_color_cube(args.file)
    if cube is None:
        return 1
    ok, colors = _load_optional_palette_colors(args.palette)
    if not ok:
        return 1
    leaves = cube.leaves
    candidates = [index for leaf in leaves for index in leaf.candidates]
    sizes = Counter(leaf.count for leaf in leaves)
    print(f"{args.file} -- {_NOT_LOADED_NOTE}")
    print(f"  nodes             : {len(cube.nodes)} ({len(leaves)} leaves)")
    print(f"  deepest leaf      : {cube.max_depth}")
    print(
        f"  candidates        : {len(candidates)}, indices {min(candidates)}..{max(candidates)}"
    )
    print(f"  largest leaf      : {max(sizes)}")
    print(f"  metric (by name)  : {metric_for_filename(args.file)}")
    if colors is not None:
        differing = [
            i for i, color in enumerate(cube.palette_colors) if color != colors[i]
        ]
        print(
            "  palette prefix    : "
            + (
                "matches the palette"
                if not differing
                else f"{len(differing)} colour(s) differ"
            )
        )
    return 0


def cmd_color_cube_lookup(args: SimpleNamespace) -> int:
    """Show which palette index the authoring tool's colour match picks."""
    cube = _load_color_cube(args.file)
    if cube is None:
        return 1
    metric = args.metric or metric_for_filename(args.file)
    color = (args.red, args.green, args.blue)
    try:
        leaf = cube.leaf_for(color)
        index = cube.closest_index(color, metric)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"{args.file} -- colour {color}, metric {metric}")
    print(
        f"  leaf at 0x{leaf.offset:x}, depth {leaf.depth}, cube "
        f"{leaf.cube_origin} size {leaf.cube_size}"
    )
    print(f"  candidates: {' '.join(str(i) for i in leaf.candidates)}")
    print(f"  chosen index {index} = {cube.palette_colors[index]}")
    return 0


def cmd_color_cube_csv(args: SimpleNamespace) -> int:
    """Export every colour-cube tree node, in stored order, to CSV."""
    cube = _load_color_cube(args.file)
    if cube is None:
        return 1
    out_path = args.output or f"{Path(args.file).stem}_nodes.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "order",
                "offset",
                "depth",
                "path",
                "kind",
                "cube_red",
                "cube_green",
                "cube_blue",
                "cube_size",
                "count",
                "candidates",
            ]
        )
        for order, node in enumerate(cube.nodes):
            red, green, blue = node.cube_origin
            writer.writerow(
                [
                    order,
                    node.offset,
                    node.depth,
                    "/".join(map(str, node.path)),
                    "leaf" if node.is_leaf else "internal",
                    red,
                    green,
                    blue,
                    node.cube_size,
                    node.count,
                    " ".join(map(str, node.candidates)),
                ]
            )
    print(f"{args.file} -- wrote {len(cube.nodes)} node row(s) -> {out_path}")
    return 0


def palette_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/ankh.pal")],
    duplicates: Annotated[
        bool,
        typer.Option(
            "-d", "--duplicates", help="List every repeated colour and its indices"
        ),
    ] = False,
) -> None:
    """Inspect a U9 ankh.pal colour table and its duplicate entries."""
    raise SystemExit(
        cmd_palette_info(SimpleNamespace(file=file, duplicates=duplicates))
    )


def palette_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/ankh.pal")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: current directory)"
        ),
    ] = None,
    swatch_size: Annotated[
        int,
        typer.Option("--swatch-size", help="Pixel size of each colour square"),
    ] = 16,
) -> None:
    """Export a U9 palette as a 16x16 PNG swatch and text table."""
    raise SystemExit(
        cmd_palette_export(
            SimpleNamespace(file=file, output=output, swatch_size=swatch_size)
        )
    )


def shade_info_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/shade.tbl or static/shadegry.tbl")
    ],
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette", help="Path to static/ankh.pal, to show colours"
        ),
    ] = None,
) -> None:
    """Summarize a U9 shade table (authoring-tool file; the game never loads it)."""
    raise SystemExit(cmd_shade_info(SimpleNamespace(file=file, palette=palette)))


def shade_csv_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/shade.tbl or static/shadegry.tbl")
    ],
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette", help="Path to static/ankh.pal, to add RGB columns"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output CSV path (default: <file>_shade.csv)"
        ),
    ] = None,
) -> None:
    """Export every cell of a U9 shade table to CSV (authoring-tool file; the game never loads it)."""
    raise SystemExit(
        cmd_shade_csv(SimpleNamespace(file=file, palette=palette, output=output))
    )


def color_cube_info_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/rgbccube.dat or static/yiqccube.dat")
    ],
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal, to compare the stored palette",
        ),
    ] = None,
) -> None:
    """Summarize a U9 colour-cube cache (authoring-tool file; the game never loads it)."""
    raise SystemExit(cmd_color_cube_info(SimpleNamespace(file=file, palette=palette)))


def color_cube_lookup_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/rgbccube.dat or static/yiqccube.dat")
    ],
    red: Annotated[int, typer.Argument(help="Red, 0-255")],
    green: Annotated[int, typer.Argument(help="Green, 0-255")],
    blue: Annotated[int, typer.Argument(help="Blue, 0-255")],
    metric: Annotated[
        Optional[str],
        typer.Option(
            "-m",
            "--metric",
            help=f"Distance metric, one of {', '.join(COLOR_CUBE_METRICS)} "
            "(default: yiq when the file name contains 'yiq', else rgb)",
        ),
    ] = None,
) -> None:
    """Show the palette index a U9 colour cube picks for a colour (authoring-tool file; the game never loads it)."""
    raise SystemExit(
        cmd_color_cube_lookup(
            SimpleNamespace(file=file, red=red, green=green, blue=blue, metric=metric)
        )
    )


def color_cube_csv_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to static/rgbccube.dat or static/yiqccube.dat")
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output CSV path (default: <file>_nodes.csv)"
        ),
    ] = None,
) -> None:
    """Export every U9 colour-cube tree node to CSV (authoring-tool file; the game never loads it)."""
    raise SystemExit(cmd_color_cube_csv(SimpleNamespace(file=file, output=output)))
