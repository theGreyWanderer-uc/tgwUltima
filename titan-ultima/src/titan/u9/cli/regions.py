"""``titan u9 fixed-*`` / ``nonfixed-*`` / ``terrain-*`` — per-region world data commands."""

from __future__ import annotations

__all__ = [
    "nonfixed_info_cmd",
    "nonfixed_chunks_cmd",
    "nonfixed_entities_cmd",
    "nonfixed_diff_cmd",
    "fixed_info_cmd",
    "fixed_chunks_cmd",
    "fixed_objects_cmd",
    "fixed_types_cmd",
    "terrain_info_cmd",
    "terrain_tiles_cmd",
    "terrain_chunk_cmd",
    "terrain_textures_cmd",
    "terrain_heightmap_cmd",
    "terrain_export_cmd",
]

import csv
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer
from PIL import Image

from titan.u9.flx_archive import U9FlxArchiveError
from titan.u9.fixed import U9Fixed, U9FixedError
from titan.u9.nonfixed import U9Nonfixed, U9NonfixedError
from titan.u9.terrain import U9Terrain, U9TerrainError
from titan.u9.typename import U9TypeNames
from titan.u9.cli import _common


def _load_region(filepath: str) -> Optional[U9Nonfixed]:
    """Open a nonfixed region file, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Nonfixed.from_file(filepath)
    except U9NonfixedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def _load_typenames(path: Optional[str]) -> Optional[U9TypeNames]:
    if not path:
        return None
    try:
        return U9TypeNames.from_file(path)
    except (U9FlxArchiveError, OSError) as e:
        print(f"WARNING: could not read type names from {path}: {e}", file=sys.stderr)
        return None


def cmd_nonfixed_info(args: SimpleNamespace) -> int:
    """Summarize a runtime region's pages, entities, and shared allocator."""
    region = _load_region(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    pages = sum(len(c.pages) for c in chunks)
    indexed = sum(len(c.entities) for c in chunks)
    allocated = sum(len(c.allocated_entities) for c in chunks)
    unlinked = sum(len(c.unlinked_entities) for c in chunks)
    extras = sum(len(c.extra_data_records) for c in chunks)
    referenced_extras = len(
        {
            e.extra_data_offset
            for c in chunks
            for e in c.allocated_entities
            if e.extra_data_offset
        }
    )
    incomplete = [c for c in chunks if not c.allocation_is_complete]

    print(f"{args.file} -- {region.width}x{region.height} chunk region")
    print(f"  Header          : {region.header_size} bytes")
    print(
        f"  Payload         : {region.payload_size} bytes (watermark {region.declared_payload_size})"
    )
    print(f"  Populated chunks: {len(chunks)} of {region.num_chunks}")
    print(f"  Pages           : {pages}")
    print(f"  Entities        : {indexed} spatially indexed, {allocated} allocated")
    print(f"  Unlinked records: {unlinked}")
    print(f"  Extra-data      : {extras} allocated, {referenced_extras} referenced")
    print(f"  Allocator       : {'complete' if not incomplete else 'incomplete'}")
    if incomplete:
        print(
            f"  NOTE: {len(incomplete)} chunk(s) contain truncated or inconsistent "
            "allocator data."
        )
    return 0


def cmd_nonfixed_chunks(args: SimpleNamespace) -> int:
    """List every populated chunk in a region with its page and entity counts."""
    region = _load_region(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    print(f"{args.file} -- {len(chunks)} populated chunk(s) of {region.num_chunks}")
    print(
        f"{'Idx':>5}  {'Grid':<9}  {'Base (x,y)':<15}  {'Pages':>5}  "
        f"{'Index':>6}  {'Alloc':>6}  {'Loose':>5}  {'Extra':>5}  Full"
    )
    print("-" * 88)
    for c in chunks:
        grid = f"{c.chunk_x},{c.chunk_y}"
        base = f"{c.base_x},{c.base_y}"
        flag = "yes" if c.allocation_is_complete else "no"
        print(
            f"{c.index:>5}  {grid:<9}  {base:<15}  {len(c.pages):>5}  "
            f"{len(c.entities):>6}  {len(c.allocated_entities):>6}  "
            f"{len(c.unlinked_entities):>5}  {len(c.extra_data_records):>5}  {flag}"
        )
    return 0


def cmd_nonfixed_entities(args: SimpleNamespace) -> int:
    """List dynamic objects in a region, optionally restricted to one chunk."""
    region = _load_region(args.file)
    if region is None:
        return 1

    if args.chunk is not None:
        try:
            cx, cy = (int(v) for v in args.chunk.split(",", 1))
        except ValueError:
            print(f"ERROR: --chunk expects 'X,Y', got {args.chunk!r}", file=sys.stderr)
            return 1
        try:
            chunk = region.chunk(cx, cy)
        except U9NonfixedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if chunk is None:
            print(f"Chunk ({cx}, {cy}) holds no pages.")
            return 0
        chunks = [chunk]
    else:
        chunks = region.chunks()

    names = _load_typenames(args.typenames)
    include_unlinked = getattr(args, "include_unlinked", False)
    rows = []
    for chunk in chunks:
        unlinked_offsets = {entity.offset for entity in chunk.unlinked_entities}
        selected = chunk.allocated_entities if include_unlinked else chunk.entities
        rows.extend(
            (
                chunk,
                entity,
                "unlinked" if entity.offset in unlinked_offsets else "indexed",
            )
            for entity in selected
        )
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} entit{'y' if len(rows) == 1 else 'ies'}")
    header = (
        f"{'Offset':>8}  {'Chunk':<7}  {'State':<8}  {'World (x,y,z)':<20}  "
        f"{'Type':>5}  {'Mesh':>5}  {'Link':>5}  {'Extra':>7}  {'Triggers':<23}"
    )
    if names:
        header += "  Name"
    print(header)
    print("-" * (len(header) + 8))
    for c, e, state in shown:
        grid = f"{c.chunk_x},{c.chunk_y}"
        pos = f"{e.world_x},{e.world_y},{e.z}"
        extra = f"{e.extra_data_offset:#07x}" if e.has_extra_data else "-"
        phases = region.entity_triggers(e).by_phase
        triggers = "/".join(str(tid) for tid in phases) if any(phases) else "-"
        line = (
            f"{e.offset:>#8x}  {grid:<7}  {state:<8}  {pos:<20}  {e.type_index:>5}  "
            f"{e.mesh_index:>5}  {e.link:>5}  {extra:>7}  {triggers:<23}"
        )
        if names:
            line += f"  {names.name_for(e.type_index) or ''}"
        print(line)
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def _entity_fields(entity) -> dict:
    return {
        "x": entity.offset_x,
        "y": entity.offset_y,
        "z": entity.z,
        "type": entity.type_index,
        "rotation": entity.rotation,
        "flags": entity.flags,
        "mesh": entity.mesh_index,
        "link": entity.link,
        "extra": entity.extra_data_offset,
    }


def cmd_nonfixed_diff(args: SimpleNamespace) -> int:
    """Compare two region files entity by entity -- e.g. a patched region against its original."""
    left = _load_region(args.left)
    right = _load_region(args.right)
    if left is None or right is None:
        return 1

    if (left.width, left.height) != (right.width, right.height):
        print(
            f"Region grids differ: {left.width}x{left.height} vs {right.width}x{right.height}",
            file=sys.stderr,
        )
        return 1

    names = _load_typenames(args.typenames)

    def index(region):
        return {
            (c.index, e.offset): (c, e) for c in region.chunks() for e in c.entities
        }

    a, b = index(left), index(right)
    only_left = sorted(set(a) - set(b))
    only_right = sorted(set(b) - set(a))
    changed = []
    for key in sorted(set(a) & set(b)):
        fa, fb = _entity_fields(a[key][1]), _entity_fields(b[key][1])
        delta = {k: (fa[k], fb[k]) for k in fa if fa[k] != fb[k]}
        if delta:
            changed.append((key, delta))

    print(args.left)
    print(args.right)
    print(
        f"  {len(a)} vs {len(b)} entities  |  "
        f"{len(changed)} changed, {len(only_left)} removed, {len(only_right)} added"
    )
    if not (changed or only_left or only_right):
        print("  No entity-level differences.")
        return 0

    def label(entry):
        chunk, entity = entry
        name = f" {names.name_for(entity.type_index)}" if names else ""
        return f"chunk {chunk.chunk_x},{chunk.chunk_y} @{entity.offset:#08x} type {entity.type_index}{name}"

    if changed:
        print("")
        print("Changed:")
        for key, delta in changed:
            print(f"  {label(a[key])}")
            for field, (old, new) in delta.items():
                print(f"      {field}: {old} -> {new}")
    if only_left:
        print("")
        print(f"Only in {args.left}:")
        for key in only_left:
            print(f"  {label(a[key])}")
    if only_right:
        print("")
        print(f"Only in {args.right}:")
        for key in only_right:
            print(f"  {label(b[key])}")
    return 0


def _load_fixed(filepath: str) -> Optional[U9Fixed]:
    """Open a static/fixed.<map> file, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Fixed.from_file(filepath)
    except U9FixedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_fixed_info(args: SimpleNamespace) -> int:
    """Summarize one static map: region grid, pages and object totals."""
    region = _load_fixed(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    pages = sum(len(c.pages) for c in chunks)
    objects = sum(len(c.objects) for c in chunks)
    chained = sum(1 for c in chunks if len(c.pages) > 1)

    print(f"{args.file} -- {region.width}x{region.height} region map")
    print(f"  Header          : {region.header_size} bytes (0x20 + 4*w*h)")
    print(
        f"  Heap            : {region.heap_size} bytes "
        f"({region.trailing_size} trailing)"
    )
    print(f"  Populated regions: {len(chunks)} of {region.num_chunks}")
    print(f"  Pages           : {pages} ({chained} region(s) span more than one)")
    print(f"  Objects         : {objects}")
    print("  Region table    : row-major at +0x1C")
    return 0


def cmd_fixed_chunks(args: SimpleNamespace) -> int:
    """List populated chunks with their grid position and object counts."""
    region = _load_fixed(args.file)
    if region is None:
        return 1

    chunks = region.chunks()
    if args.by_grid:
        chunks.sort(key=lambda c: (c.chunk_y, c.chunk_x))
    shown = chunks[: args.limit] if args.limit else chunks

    print(f"{args.file} -- {len(chunks)} populated chunk(s) of {region.num_chunks}")
    print(f"{'Slot':>5}  {'Grid':<9}  {'Base (x,y)':<15}  {'Pages':>5}  {'Objects':>7}")
    print("-" * 54)
    for c in shown:
        print(
            f"{c.table_index:>5}  {f'{c.chunk_x},{c.chunk_y}':<9}  "
            f"{f'{c.base_x},{c.base_y}':<15}  {len(c.pages):>5}  {len(c.objects):>7}"
        )
    if args.limit and len(chunks) > args.limit:
        print(f"... ({len(chunks) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_fixed_objects(args: SimpleNamespace) -> int:
    """List immovable objects, optionally restricted to one chunk."""
    region = _load_fixed(args.file)
    if region is None:
        return 1

    if args.chunk is not None:
        try:
            cx, cy = (int(v) for v in args.chunk.split(",", 1))
        except ValueError:
            print(f"ERROR: --chunk expects 'X,Y', got {args.chunk!r}", file=sys.stderr)
            return 1
        try:
            chunk = region.chunk(cx, cy)
        except U9FixedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if chunk is None:
            print(f"Chunk ({cx}, {cy}) holds no pages.")
            return 0
        chunks = [chunk]
    else:
        chunks = region.chunks()

    names = _load_typenames(args.typenames)
    rows = [(c, o) for c in chunks for o in c.objects]
    if args.type is not None:
        rows = [(c, o) for c, o in rows if o.type_index == args.type]
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} object(s)")
    header = (
        f"{'Offset':>8}  {'Chunk':<7}  {'World (x,y,z)':<20}  {'Type':>5}  "
        f"{'Flags':>10}"
    )
    if names:
        header += "  Name"
    print(header)
    print("-" * (len(header) + 8))
    for c, o in shown:
        line = (
            f"{o.offset:>#8x}  {f'{c.chunk_x},{c.chunk_y}':<7}  "
            f"{f'{o.world_x},{o.world_y},{o.z}':<20}  {o.type_index:>5}  "
            f"{o.flags:>#10x}"
        )
        if names:
            line += f"  {names.name_for(o.type_index) or ''}"
        print(line)
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_fixed_types(args: SimpleNamespace) -> int:
    """Report which object types a static region uses, most common first."""
    region = _load_fixed(args.file)
    if region is None:
        return 1
    names = _load_typenames(args.typenames)
    histogram = Counter(o.type_index for o in region.objects())
    total = sum(histogram.values())
    print(f"{args.file} -- {total} object(s), {len(histogram)} distinct type(s)")
    print(f"{'Type':>6}  {'Count':>7}  {'Share':>7}  Name")
    print("-" * 46)
    for type_index, count in histogram.most_common(args.limit or None):
        label = (names.name_for(type_index) or "") if names else ""
        print(f"{type_index:>6}  {count:>7}  {100 * count / total:>6.2f}%  {label}")
    if args.limit and len(histogram) > args.limit:
        print(f"... ({len(histogram) - args.limit} more; raise --limit to see more)")
    return 0


def _load_terrain(filepath: str) -> Optional[U9Terrain]:
    """Open a static/terrain.<region> file, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Terrain.from_file(filepath)
    except U9TerrainError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_terrain_info(args: SimpleNamespace) -> int:
    """Summarize one region height map, including its environment header."""
    region = _load_terrain(args.file)
    if region is None:
        return 1

    print(f"{args.file} -- {region.name or '(unnamed)'}")
    print(f"  Water level     : {region.water_level}")
    print(f"  Wave amplitude  : {region.wave_amplitude:g}")
    print(f"  Region flags    : 0x{region.flags:08x}")
    if region.is_empty:
        print("  Unused region slot: a bare header, no tile grid and no chunks.")
        print(f"  Header still declares {region.declared_chunk_count} chunk(s).")
        return 0

    low, high = region.height_range()
    unused = len(region.unused_chunks())
    duplicates = region.duplicate_tile_reference_count()
    shared = region.tiles_using_shared_chunks()
    print(f"  Points          : {region.width}x{region.height}")
    print(f"  World coords    : {region.world_width}x{region.world_height}")
    print(
        f"  Tiles           : {region.tile_width}x{region.tile_height} "
        f"({region.tile_count} total, {shared} use shared chunks, "
        f"{duplicates} duplicate references)"
    )
    print(
        f"  Chunks          : {region.chunk_count} "
        f"(declared {region.declared_chunk_count}, {unused} referenced by no tile)"
    )
    print(f"  Height range    : {low}..{high}")
    if region.slack_bytes:
        print(f"  Trailing slack  : {region.slack_bytes} bytes past the last chunk")
    return 0


def cmd_terrain_tiles(args: SimpleNamespace) -> int:
    """Print the tile grid as the chunk index each tile refers to."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, no tile grid.")
        return 0

    print(
        f"{args.file} -- {region.tile_width}x{region.tile_height} tiles "
        f"over {region.chunk_count} chunk(s)"
    )
    width = max(3, len(str(max(region.tiles))))
    for tile_y in range(region.tile_height):
        base = tile_y * region.tile_width
        row = region.tiles[base : base + region.tile_width]
        print(f"{tile_y:>4}  " + " ".join(f"{v:>{width}}" for v in row))
    return 0


def cmd_terrain_chunk(args: SimpleNamespace) -> int:
    """Dump one decoded field from a chunk's 16x16 points."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    try:
        if args.tile is not None:
            try:
                tile_x, tile_y = (int(v) for v in args.tile.split(",", 1))
            except ValueError:
                print(
                    f"ERROR: --tile expects 'X,Y', got {args.tile!r}", file=sys.stderr
                )
                return 1
            index = region.tile(tile_x, tile_y)
        else:
            index = args.index or 0
        chunk = region.chunk(index)
    except U9TerrainError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    field = args.field
    pick = {
        "height": lambda p: p.height,
        "texture": lambda p: p.texture,
        "frame": lambda p: p.frame,
        "hole": lambda p: int(p.is_hole),
        "swap": lambda p: int(p.swap_uv),
        "mirror": lambda p: int(p.mirror_uv),
        "uv-rotation": lambda p: p.uv_rotation_degrees,
        "split": lambda p: int(p.is_split),
        "spare": lambda p: int(p.spare_bit_set),
        "raw": lambda p: p.value,
    }[field]
    points = chunk.points()
    values = [pick(p) for p in points]
    holes = sum(1 for p in points if p.is_hole)

    print(
        f"{args.file} -- chunk {index}, {field} "
        f"({'flat' if chunk.is_flat else 'varied'}, {holes} hole point(s))"
    )
    width = max(2, len(str(max(values))))
    for y in range(16):
        row = values[y * 16 : (y + 1) * 16]
        print(f"{y:>4}  " + " ".join(f"{v:>{width}}" for v in row))
    return 0


def cmd_terrain_textures(args: SimpleNamespace) -> int:
    """Report which ground textures a region paints with, most used first."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, no chunks.")
        return 0

    histogram = region.texture_histogram()
    total = sum(histogram.values())

    info = None
    if args.sdinfo:
        info = _common._load_sdinfo(args.sdinfo)
        if info is None:
            return 1
        records = {r.index: r for r in info.records()}

    print(f"{args.file} -- {total} point(s), {len(histogram)} distinct texture(s)")
    header = f"{'Texture':>8}  {'Points':>9}  {'Share':>7}"
    if info:
        header += f"  {'Size':>9}  {'Frames':>6}"
    print(header)
    print("-" * len(header))
    for texture, count in histogram.most_common(args.limit or None):
        line = f"{texture:>8}  {count:>9}  {100 * count / total:>6.2f}%"
        if info:
            record = records.get(texture)
            line += (
                f"  {f'{record.width}x{record.height}':>9}  {record.frame_count:>6}"
                if record
                else f"  {'--':>9}  {'--':>6}"
            )
        print(line)
    if args.limit and len(histogram) > args.limit:
        print(f"... ({len(histogram) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_terrain_heightmap(args: SimpleNamespace) -> int:
    """Render a region's height map to a greyscale PNG."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, nothing to render.")
        return 1

    rows = region.heightmap()
    low, high = region.height_range()
    span = max(1, high - low)
    image = Image.new("L", (region.width, region.height))
    image.putdata([(value - low) * 255 // span for row in rows for value in row])
    if args.scale and args.scale > 1:
        image = image.resize(
            (region.width * args.scale, region.height * args.scale), Image.NEAREST
        )

    out_path = args.output or f"{Path(args.file).name.replace('.', '_')}_height.png"
    directory = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(directory, exist_ok=True)
    image.save(out_path)
    print(
        f"{args.file} -- {region.width}x{region.height}, heights {low}..{high} "
        f"-> {out_path}"
    )
    return 0


def cmd_terrain_export(args: SimpleNamespace) -> int:
    """Export every point of a region to CSV."""
    region = _load_terrain(args.file)
    if region is None:
        return 1
    if region.is_empty:
        print(f"{args.file} -- unused region slot, nothing to export.")
        return 1

    out_path = args.output or f"{Path(args.file).name.replace('.', '_')}_points.csv"
    directory = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(directory, exist_ok=True)
    written = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "x",
                "y",
                "tile_x",
                "tile_y",
                "chunk",
                "height",
                "hole",
                "swap_uv",
                "mirror_uv",
                "uv_rotation_degrees",
                "split",
                "frame",
                "texture",
                "spare",
                "raw",
            ]
        )
        for tile_y in range(region.tile_height):
            for tile_x in range(region.tile_width):
                index = region.tile(tile_x, tile_y)
                for point in region.chunk(index).points():
                    writer.writerow(
                        [
                            tile_x * 16 + point.x,
                            tile_y * 16 + point.y,
                            tile_x,
                            tile_y,
                            index,
                            point.height,
                            int(point.is_hole),
                            int(point.swap_uv),
                            int(point.mirror_uv),
                            point.uv_rotation_degrees,
                            int(point.is_split),
                            point.frame,
                            point.texture,
                            int(point.spare_bit_set),
                            point.value,
                        ]
                    )
                    written += 1
    print(f"{args.file} -- wrote {written} point(s) -> {out_path}")
    return 0


def nonfixed_info_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")
    ],
) -> None:
    """Summarize a U9 runtime region and its page allocator."""
    raise SystemExit(cmd_nonfixed_info(SimpleNamespace(file=file)))


def nonfixed_chunks_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")
    ],
) -> None:
    """List every populated chunk in a U9 runtime region with its counts."""
    raise SystemExit(cmd_nonfixed_chunks(SimpleNamespace(file=file)))


def nonfixed_entities_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to a runtime/nonfixed.<region> file")
    ],
    chunk: Annotated[
        Optional[str],
        typer.Option("-c", "--chunk", help="Restrict to one chunk, as 'X,Y'"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
    include_unlinked: Annotated[
        bool,
        typer.Option(
            "--include-unlinked",
            help="Include allocated records absent from the live spatial index",
        ),
    ] = False,
) -> None:
    """List the dynamic objects stored in a U9 runtime region."""
    raise SystemExit(
        cmd_nonfixed_entities(
            SimpleNamespace(
                file=file,
                chunk=chunk,
                typenames=typenames,
                limit=limit,
                include_unlinked=include_unlinked,
            )
        )
    )


def nonfixed_diff_cmd(
    left: Annotated[str, typer.Argument(help="First runtime/nonfixed.<region> file")],
    right: Annotated[str, typer.Argument(help="Second runtime/nonfixed.<region> file")],
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
) -> None:
    """Compare two U9 runtime regions entity by entity (e.g. patched vs original)."""
    raise SystemExit(
        cmd_nonfixed_diff(SimpleNamespace(left=left, right=right, typenames=typenames))
    )


def fixed_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
) -> None:
    """Summarize a U9 static region: chunk grid, pages and object totals."""
    raise SystemExit(cmd_fixed_info(SimpleNamespace(file=file)))


def fixed_chunks_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    by_grid: Annotated[
        bool,
        typer.Option("-g", "--by-grid", help="Order by grid position, not table slot"),
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List the populated chunks in a U9 static region."""
    raise SystemExit(
        cmd_fixed_chunks(SimpleNamespace(file=file, by_grid=by_grid, limit=limit))
    )


def fixed_objects_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    chunk: Annotated[
        Optional[str],
        typer.Option("-c", "--chunk", help="Restrict to one chunk, as 'X,Y'"),
    ] = None,
    type: Annotated[
        Optional[int],
        typer.Option("-t", "--type", help="Only objects of this type index"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List the immovable objects in a U9 static region."""
    raise SystemExit(
        cmd_fixed_objects(
            SimpleNamespace(
                file=file, chunk=chunk, type=type, typenames=typenames, limit=limit
            )
        )
    )


def fixed_types_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/fixed.<region> file")],
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames", help="Path to static/TYPENAME.FLX for object names"
        ),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum types to print")
    ] = None,
) -> None:
    """Report which object types a U9 static region uses."""
    raise SystemExit(
        cmd_fixed_types(SimpleNamespace(file=file, typenames=typenames, limit=limit))
    )


def terrain_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
) -> None:
    """Summarize a U9 region height map."""
    raise SystemExit(cmd_terrain_info(SimpleNamespace(file=file)))


def terrain_tiles_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
) -> None:
    """Print a U9 region's tile grid as chunk indices."""
    raise SystemExit(cmd_terrain_tiles(SimpleNamespace(file=file)))


def terrain_chunk_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    index: Annotated[
        Optional[int], typer.Option("-i", "--index", help="Chunk index to dump")
    ] = None,
    tile: Annotated[
        Optional[str],
        typer.Option("-t", "--tile", help="Dump the chunk a tile uses, as 'X,Y'"),
    ] = None,
    field: Annotated[
        str,
        typer.Option(
            "-f",
            "--field",
            help=(
                "Field: height, texture, frame, hole, swap, mirror, "
                "uv-rotation, split, spare or raw"
            ),
        ),
    ] = "height",
) -> None:
    """Dump one 16x16 chunk of a U9 region height map."""
    choices = (
        "height",
        "texture",
        "frame",
        "hole",
        "swap",
        "mirror",
        "uv-rotation",
        "split",
        "spare",
        "raw",
    )
    if field not in choices:
        print(
            f"ERROR: --field must be {', '.join(choices)}, got {field!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(
        cmd_terrain_chunk(
            SimpleNamespace(file=file, index=index, tile=tile, field=field)
        )
    )


def terrain_textures_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    sdinfo: Annotated[
        Optional[str],
        typer.Option(
            "--sdinfo", help="Path to a matching static/sdInfo*.flx for sizes"
        ),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum textures to print")
    ] = None,
) -> None:
    """Report which ground textures a U9 region paints with."""
    raise SystemExit(
        cmd_terrain_textures(SimpleNamespace(file=file, sdinfo=sdinfo, limit=limit))
    )


def terrain_heightmap_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    scale: Annotated[
        int, typer.Option("-s", "--scale", help="Nearest-neighbour magnification")
    ] = 1,
) -> None:
    """Render a U9 region height map to a greyscale PNG."""
    raise SystemExit(
        cmd_terrain_heightmap(SimpleNamespace(file=file, output=output, scale=scale))
    )


def terrain_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to a static/terrain.<region> file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output CSV path"),
    ] = None,
) -> None:
    """Export every point of a U9 region height map to CSV."""
    raise SystemExit(cmd_terrain_export(SimpleNamespace(file=file, output=output)))
