"""Map inventory for Ultima VII: every ground tile and object the world uses.

Counts each shape and frame placed on a map, from every place the world is
stored:

- **terrain**: flat ground cells (shapes below 150) from the chunk
  templates in ``U7CHUNKS``, multiplied by how often ``U7MAP`` uses each
  template;
- **chunk**: objects stored inside chunk templates (shapes 150 and up), one
  placement per template cell, likewise multiplied by template use. A
  multi-tile shape appears once, at its anchor cell;
- **ifix**: fixed objects (``U7IFIXnn``);
- **ireg**: the starting world's movable objects, top level only
  (``u7iregNN`` from ``INITGAME.DAT`` or a GAMEDAT folder);
- **contents**: objects inside containers and bodies in those ``u7iregNN``
  files (optional).

Each row carries the shape's name, TFA class, flags, footprint and height,
lift range, how widely it is spread (superchunks), a sample location and,
optionally, a sprite preview. Rows are ranked by placements, with
cumulative coverage, so the list doubles as a to-do list for work that
handles one shape at a time, such as converting the map to another game's
tiles.

An ``area`` (tile rectangles, e.g. superchunks or chunk ranges) limits the
inventory to part of the map and also lists every placement in it. An
object counts when its footprint overlaps the area; U7 anchors objects at
their south-east tile, so a footprint reaches west and north of the anchor.

Built on the same sources and metadata as ``u7 world-query``
(:mod:`titan.u7.world`) and the map readers in :mod:`titan.u7.map`.
"""

from __future__ import annotations

__all__ = [
    "U7InventoryRow",
    "U7MapInventory",
    "U7Placement",
    "chunk_rect",
    "superchunk_rect",
    "build_u7_map_inventory",
    "write_u7_map_inventory",
]

import csv
import html
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from titan.u7.map import (
    C_CHUNKS_PER_SCHUNK,
    C_NUM_CHUNKS,
    C_NUM_SCHUNKS,
    C_TILES_PER_CHUNK,
    U7MapObject,
    U7MapRenderer,
    _frame_to_rgba,
)
from titan.u7.shape import FIRST_OBJ_SHAPE
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import (
    WorldQueryParams,
    _world_file,
    load_query_metadata,
    resolve_world_sources,
)

SOURCES = ("terrain", "chunk", "ifix", "ireg", "contents")
OBJECT_SOURCES = ("chunk", "ifix", "ireg")  # placements that make up the map


@dataclass
class U7InventoryRow:
    """One shape and frame and everything known about its use."""

    shape: int
    frame: int
    counts: Counter = field(default_factory=Counter)
    lifts: Counter = field(default_factory=Counter)
    superchunks: set[int] = field(default_factory=set)
    sample: Optional[tuple[int, int, int]] = None

    @property
    def is_flat(self) -> bool:
        return self.shape < FIRST_OBJ_SHAPE

    @property
    def placements(self) -> int:
        """Map placements: ground cells for flats, objects otherwise."""
        if self.is_flat:
            return self.counts["terrain"]
        return sum(self.counts[s] for s in OBJECT_SOURCES)

    def add(self, source: str, count: int, superchunk: int, where: tuple[int, int, int]) -> None:
        self.counts[source] += count
        if source != "terrain":
            self.lifts[where[2]] += count
        self.superchunks.add(superchunk)
        if self.sample is None:
            self.sample = where


@dataclass(frozen=True)
class U7Placement:
    """One placement inside an inventory area."""

    source: str
    shape: int
    frame: int
    tx: int
    ty: int
    tz: int


Rect = tuple[int, int, int, int]  # tx0, ty0, tx1, ty1, inclusive


def superchunk_rect(sc: int) -> Rect:
    """Tile rectangle of superchunk ``sc`` (0-143)."""
    span = C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK
    x0, y0 = (sc % C_NUM_SCHUNKS) * span, (sc // C_NUM_SCHUNKS) * span
    return x0, y0, x0 + span - 1, y0 + span - 1


def chunk_rect(cx0: int, cy0: int, cx1: int, cy1: int) -> Rect:
    """Tile rectangle covering chunks ``cx0..cx1`` by ``cy0..cy1`` inclusive."""
    cx0, cx1 = sorted((cx0, cx1))
    cy0, cy1 = sorted((cy0, cy1))
    return (
        cx0 * C_TILES_PER_CHUNK,
        cy0 * C_TILES_PER_CHUNK,
        (cx1 + 1) * C_TILES_PER_CHUNK - 1,
        (cy1 + 1) * C_TILES_PER_CHUNK - 1,
    )


def _overlaps(area: list[Rect], tx: int, ty: int, dx: int = 1, dy: int = 1) -> bool:
    """Whether a footprint anchored at its south-east tile touches ``area``."""
    return any(
        tx >= x0 and tx - dx + 1 <= x1 and ty >= y0 and ty - dy + 1 <= y1
        for x0, y0, x1, y1 in area
    )


# Largest footprint looked for beyond the area's east and south edges.
_REACH = C_TILES_PER_CHUNK


@dataclass
class U7MapInventory:
    """Everything a map uses, with the metadata needed to describe it."""

    game: str
    map_num: int
    static_dir: str
    rows: dict[tuple[int, int], U7InventoryRow]
    tfa: U7TypeFlags
    shape_names: object
    frame_names: object
    sources: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    area: list[Rect] = field(default_factory=list)
    placements: list[U7Placement] = field(default_factory=list)

    def name(self, shape: int, frame: int) -> str:
        if self.frame_names is not None:
            return self.frame_names.label(shape, frame, self.shape_names) or ""
        if self.shape_names is not None:
            return self.shape_names.get(shape) or ""
        return ""

    def shape_name(self, shape: int) -> str:
        return (self.shape_names.get(shape) or "") if self.shape_names is not None else ""

    def ranked(self, kind: str) -> list[U7InventoryRow]:
        """Rows of ``kind`` (``flat`` or ``object``), most placed first."""
        want_flat = kind == "flat"
        rows = [r for r in self.rows.values() if r.is_flat == want_flat and r.placements]
        return sorted(rows, key=lambda r: (-r.placements, r.shape, r.frame))


def _superchunk_of(tx: int, ty: int) -> int:
    span = C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK
    return (ty // span) * C_NUM_SCHUNKS + (tx // span)


def build_u7_map_inventory(
    static_dir: str,
    *,
    game: str = "bg",
    map_num: int = 0,
    gamedat_dir: Optional[str] = None,
    initgame: Optional[str] = None,
    include_ireg: bool = True,
    include_contents: bool = False,
    base_static: Optional[str] = None,
    patch_dir: Optional[str] = None,
    mod_data_dir: Optional[str] = None,
    text_flx_path: Optional[str] = None,
    area: Optional[list[Rect]] = None,
) -> U7MapInventory:
    """Scan one U7 map and return its inventory.

    Movable objects come from ``gamedat_dir`` (a saved or running world)
    when given, else from ``initgame`` (default ``STATIC/INITGAME.DAT``, the
    starting world). ``area`` limits the scan to those tile rectangles and
    records each placement in ``placements``.
    """
    params = WorldQueryParams(
        static_dir=static_dir,
        game=game,
        map_num=map_num,
        base_static=base_static,
        patch_dir=patch_dir,
        mod_data_dir=mod_data_dir,
        text_flx_path=text_flx_path,
    )
    base, patch = resolve_world_sources(params)
    tfa, shape_names, frame_names, _count = load_query_metadata(params)
    renderer = U7MapRenderer(
        str(base), map_num=map_num, patch_dir=str(patch) if patch else None, game=game
    )
    rows: dict[tuple[int, int], U7InventoryRow] = {}
    warnings: list[str] = []
    sources: dict[str, str] = {}
    area = [tuple(r) for r in area] if area else []
    placements: list[U7Placement] = []

    def dims(shape: int) -> tuple[int, int]:
        entry = tfa.get(shape) if tfa else None
        return (max(entry.dims_x, 1), max(entry.dims_y, 1)) if entry else (1, 1)

    def wanted(shape: int, tx: int, ty: int) -> bool:
        if not area:
            return True
        if shape < FIRST_OBJ_SHAPE:
            return _overlaps(area, tx, ty)
        return _overlaps(area, tx, ty, *dims(shape))

    def place(source: str, shape: int, frame: int, sc: int, where: tuple[int, int, int]) -> None:
        row(shape, frame).add(source, 1, sc, where)
        placements.append(U7Placement(source, shape, frame, *where))

    span = C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK
    area_superchunks = {
        sy * C_NUM_SCHUNKS + sx
        for x0, y0, x1, y1 in area
        for sx in range(x0 // span, min(x1 + _REACH, C_NUM_CHUNKS * C_TILES_PER_CHUNK - 1) // span + 1)
        for sy in range(y0 // span, min(y1 + _REACH, C_NUM_CHUNKS * C_TILES_PER_CHUNK - 1) // span + 1)
    }

    def row(shape: int, frame: int) -> U7InventoryRow:
        key = (shape, frame)
        if key not in rows:
            rows[key] = U7InventoryRow(shape, frame)
        return rows[key]

    # Chunk templates, multiplied by how often the map uses each one.
    terrains = renderer.terrains
    terrain_map = renderer.terrain_map
    uses: dict[int, list[tuple[int, int]]] = {}
    for cx in range(C_NUM_CHUNKS):
        for cy in range(C_NUM_CHUNKS):
            uses.setdefault(terrain_map[cx][cy], []).append((cx, cy))
    sources["terrain"] = f"U7CHUNKS ({len(terrains)} templates, {len(uses)} used) via U7MAP"
    if area:
        chunks = {
            (cx, cy)
            for x0, y0, x1, y1 in area
            for cx in range(x0 // C_TILES_PER_CHUNK, min((x1 + _REACH) // C_TILES_PER_CHUNK, C_NUM_CHUNKS - 1) + 1)
            for cy in range(y0 // C_TILES_PER_CHUNK, min((y1 + _REACH) // C_TILES_PER_CHUNK, C_NUM_CHUNKS - 1) + 1)
        }
        uses = {}
        for cx, cy in sorted(chunks):
            template = terrain_map[cx][cy]
            if template >= len(terrains):
                warnings.append(f"U7MAP references missing chunk template {template}")
                continue
            sc = (cy // C_CHUNKS_PER_SCHUNK) * C_NUM_SCHUNKS + cx // C_CHUNKS_PER_SCHUNK
            for index, (shape, frame) in enumerate(terrains[template]):
                tx = cx * C_TILES_PER_CHUNK + index % C_TILES_PER_CHUNK
                ty = cy * C_TILES_PER_CHUNK + index // C_TILES_PER_CHUNK
                if wanted(shape, tx, ty):
                    source = "terrain" if shape < FIRST_OBJ_SHAPE else "chunk"
                    place(source, shape, frame, sc, (tx, ty, 0))
    for template, places in uses.items():
        if template >= len(terrains):
            warnings.append(f"U7MAP references missing chunk template {template}")
            continue
        superchunks = {
            (cy // C_CHUNKS_PER_SCHUNK) * C_NUM_SCHUNKS + cx // C_CHUNKS_PER_SCHUNK
            for cx, cy in places
        }
        first_cx, first_cy = places[0]
        for index, (shape, frame) in enumerate(terrains[template]):
            tx = first_cx * C_TILES_PER_CHUNK + index % C_TILES_PER_CHUNK
            ty = first_cy * C_TILES_PER_CHUNK + index // C_TILES_PER_CHUNK
            entry = row(shape, frame)
            source = "terrain" if shape < FIRST_OBJ_SHAPE else "chunk"
            entry.add(source, len(places), next(iter(superchunks)), (tx, ty, 0))
            entry.superchunks.update(superchunks)

    # Fixed objects.
    ifix_files = 0
    for sc in range(C_NUM_SCHUNKS * C_NUM_SCHUNKS):
        if area and sc not in area_superchunks:
            continue
        name = f"U7IFIX{sc:02X}"
        path = (_world_file(patch, name, map_num) if patch else None) or _world_file(
            base, name, map_num
        )
        if path is None:
            continue
        ifix_files += 1
        for obj in U7MapRenderer.parse_ifix(str(path), sc):
            if wanted(obj.shape, obj.tx, obj.ty):
                place("ifix", obj.shape, obj.frame, sc, (obj.tx, obj.ty, obj.tz))
    sources["ifix"] = f"{ifix_files} U7IFIX files"

    # Movable objects of the starting (or saved) world.
    if include_ireg:
        ireg_data = _ireg_entries(base, map_num, gamedat_dir, initgame, sources, warnings)
        for sc, (label, data) in ireg_data.items():
            if area and sc not in area_superchunks:
                continue
            for obj in U7MapRenderer.parse_ireg_deep(label, sc, tfa, data=data):
                if not wanted(obj.shape, obj.tx, obj.ty):
                    continue
                place("ireg", obj.shape, obj.frame, sc, (obj.tx, obj.ty, obj.tz))
                if include_contents:
                    _add_contents(obj, sc, row, placements if area else None)

    if shape_names is None:
        warnings.append("Shape names are unavailable (no TEXT.FLX); numeric IDs only.")
    return U7MapInventory(
        game=game,
        map_num=map_num,
        static_dir=str(base),
        rows=rows,
        tfa=tfa,
        shape_names=shape_names,
        frame_names=frame_names,
        sources=sources,
        warnings=warnings,
        area=area,
        placements=placements if area else [],
    )


def _add_contents(obj: U7MapObject, sc: int, row, placements=None) -> None:
    for child in obj.children:
        where = (obj.tx, obj.ty, obj.tz)
        row(child.shape, child.frame).add("contents", 1, sc, where)
        if placements is not None:
            placements.append(U7Placement("contents", child.shape, child.frame, *where))
        _add_contents(child, sc, row, placements)


def _ireg_entries(base: Path, map_num, gamedat_dir, initgame, sources, warnings):
    """``{superchunk: (label, bytes)}`` from a GAMEDAT folder or INITGAME.DAT."""
    found: dict[int, tuple[str, bytes]] = {}
    names = {sc: f"u7ireg{sc:02x}" for sc in range(C_NUM_SCHUNKS * C_NUM_SCHUNKS)}
    if gamedat_dir:
        gamedat = Path(gamedat_dir)
        for sc, name in names.items():
            path = _world_file(gamedat, name, map_num)
            if path is None and map_num == 0:
                path = _world_file(gamedat / "map00", name, 0) if (gamedat / "map00").is_dir() else None
            if path is not None:
                found[sc] = (str(path), path.read_bytes())
        sources["ireg"] = f"GAMEDAT {gamedat} ({len(found)} u7ireg files)"
        return found

    from titan.u7.save import U7Save

    archive_path = Path(initgame) if initgame else _world_file(base, "INITGAME.DAT", 0)
    if archive_path is None or not Path(archive_path).is_file():
        warnings.append("No INITGAME.DAT or GAMEDAT given; movable objects (ireg) are not counted.")
        return found
    archive = U7Save.from_file(str(archive_path))
    prefix = f"map{map_num:02x}/" if map_num else ""
    entries = {n.lower(): n for n in archive.entry_names()}
    for sc, name in names.items():
        actual = entries.get(prefix + name)
        if actual is not None:
            data = archive.get_data(actual)
            if data:
                found[sc] = (f"{archive_path}:{actual}", data)
    sources["ireg"] = f"{archive_path} ({len(found)} u7ireg entries)"
    if map_num and not found:
        warnings.append(f"INITGAME.DAT has no u7ireg entries for map {map_num}.")
    return found


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _row_record(inv: U7MapInventory, r: U7InventoryRow, rank: int, total: int, cumulative: int):
    entry = inv.tfa.get(r.shape) if inv.tfa else None
    lifts = sorted(r.lifts)
    return {
        "rank": rank,
        "shape": r.shape,
        "frame": r.frame,
        "name": inv.name(r.shape, r.frame),
        "shape_name": inv.shape_name(r.shape),
        "kind": "flat" if r.is_flat else "object",
        "class": U7TypeFlags.SHAPE_CLASS_NAMES.get(entry.shape_class, entry.shape_class) if entry else "",
        "flags": "|".join(entry.flag_names()) if entry else "",
        "dims_x": entry.dims_x if entry else "",
        "dims_y": entry.dims_y if entry else "",
        "dims_z": entry.dims_z if entry else "",
        "placements": r.placements,
        "share_pct": round(100 * r.placements / total, 3) if total else 0,
        "cumulative_pct": round(100 * cumulative / total, 2) if total else 0,
        **{f"{s}_count": r.counts[s] for s in SOURCES},
        "lift_min": lifts[0] if lifts else "",
        "lift_max": lifts[-1] if lifts else "",
        "lift_common": r.lifts.most_common(1)[0][0] if r.lifts else "",
        "superchunks": len(r.superchunks),
        "sample_tx": r.sample[0] if r.sample else "",
        "sample_ty": r.sample[1] if r.sample else "",
        "sample_tz": r.sample[2] if r.sample else "",
    }


def _ranked_records(inv: U7MapInventory, kind: str) -> list[dict]:
    rows = inv.ranked(kind)
    total = sum(r.placements for r in rows)
    records, cumulative = [], 0
    for rank, r in enumerate(rows, 1):
        cumulative += r.placements
        records.append(_row_record(inv, r, rank, total, cumulative))
    return records


def _shape_records(inv: U7MapInventory) -> list[dict]:
    by_shape: dict[int, list[U7InventoryRow]] = {}
    for r in inv.rows.values():
        if r.placements or r.counts["contents"]:
            by_shape.setdefault(r.shape, []).append(r)
    records = []
    for shape, rows in by_shape.items():
        entry = inv.tfa.get(shape) if inv.tfa else None
        counts = Counter()
        for r in rows:
            counts.update(r.counts)
        records.append({
            "shape": shape,
            "name": inv.shape_name(shape),
            "kind": "flat" if shape < FIRST_OBJ_SHAPE else "object",
            "class": U7TypeFlags.SHAPE_CLASS_NAMES.get(entry.shape_class, entry.shape_class) if entry else "",
            "flags": "|".join(entry.flag_names()) if entry else "",
            "dims": f"{entry.dims_x}x{entry.dims_y}x{entry.dims_z}" if entry else "",
            "frames_used": len(rows),
            "frames": " ".join(str(r.frame) for r in sorted(rows, key=lambda r: r.frame)),
            "placements": sum(r.placements for r in rows),
            **{f"{s}_count": counts[s] for s in SOURCES},
            "superchunks": len(set().union(*(r.superchunks for r in rows))),
        })
    records.sort(key=lambda r: (r["kind"] != "flat", -r["placements"], r["shape"]))
    return records


def _coverage(records: list[dict]) -> dict[str, float]:
    total = sum(r["placements"] for r in records)
    out, cumulative = {}, 0
    for index, r in enumerate(records, 1):
        cumulative += r["placements"]
        if index in (10, 25, 50, 100, 200, 400):
            out[f"top_{index}"] = round(100 * cumulative / total, 2) if total else 0
    return out


def write_u7_map_inventory(
    inv: U7MapInventory,
    outdir: str | Path,
    *,
    previews: bool = True,
    palette_index: int = 0,
) -> dict[str, object]:
    """Write ``objects.csv``, ``flats.csv``, ``shapes.csv``, ``summary.json``
    and, with ``previews``, sprite PNGs plus ``index.html``."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    objects = _ranked_records(inv, "object")
    flats = _ranked_records(inv, "flat")
    shapes = _shape_records(inv)

    preview_paths: dict[tuple[int, int], str] = {}
    if previews:
        preview_paths = _write_previews(inv, objects + flats, outdir / "sprites", palette_index)
        for record in objects + flats:
            record["preview"] = preview_paths.get((record["shape"], record["frame"]), "")

    for name, records in (("objects.csv", objects), ("flats.csv", flats), ("shapes.csv", shapes)):
        _write_csv(outdir / name, records)
    if inv.area:
        _write_csv(outdir / "placements.csv", _placement_records(inv, preview_paths))

    object_shapes = [s for s in shapes if s["kind"] == "object" and s["placements"]]
    summary = {
        "game": inv.game,
        "map_num": inv.map_num,
        "static_dir": inv.static_dir,
        "area": [list(r) for r in inv.area],
        "sources": inv.sources,
        "warnings": inv.warnings,
        "objects": {
            "placements": sum(r["placements"] for r in objects),
            "by_source": {s: sum(r[f"{s}_count"] for r in objects) for s in OBJECT_SOURCES},
            "shape_frames": len(objects),
            "shapes": len(object_shapes),
            "coverage_by_top_shapes_pct": _coverage(object_shapes),
            "coverage_by_top_shape_frames_pct": _coverage(objects),
        },
        "flats": {
            "cells": sum(r["placements"] for r in flats),
            "shape_frames": len(flats),
            "shapes": len({r["shape"] for r in flats}),
            "coverage_by_top_shape_frames_pct": _coverage(flats),
        },
        "contents": sum(r["contents_count"] for r in shapes),
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if previews:
        (outdir / "index.html").write_text(_html(inv, summary, objects, flats), encoding="utf-8")
    return summary


def _placement_records(inv: U7MapInventory, previews: dict) -> list[dict]:
    """Every placement in the area, bottom lift first, then north to south."""
    order = {s: i for i, s in enumerate(SOURCES)}
    records = []
    for p in sorted(inv.placements, key=lambda p: (p.tz, p.ty, p.tx, order[p.source], p.shape, p.frame)):
        entry = inv.tfa.get(p.shape) if inv.tfa else None
        records.append(
            {
                "source": p.source,
                "shape": p.shape,
                "frame": p.frame,
                "name": inv.name(p.shape, p.frame),
                "kind": "flat" if p.shape < FIRST_OBJ_SHAPE else "object",
                "class": U7TypeFlags.SHAPE_CLASS_NAMES.get(entry.shape_class, entry.shape_class) if entry else "",
                "tx": p.tx,
                "ty": p.ty,
                "tz": p.tz,
                "dims_x": entry.dims_x if entry else "",
                "dims_y": entry.dims_y if entry else "",
                "dims_z": entry.dims_z if entry else "",
                "preview": previews.get((p.shape, p.frame), ""),
            }
        )
    return records


def _area_label(area: list[Rect]) -> str:
    return "; ".join(f"tiles {x0},{y0} to {x1},{y1}" for x0, y0, x1, y1 in area)


def _write_csv(path: Path, records: list[dict]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _write_previews(inv: U7MapInventory, records, folder: Path, palette_index: int):
    from titan.u7.palette import U7Palette
    from titan.u7.shape import U7Shape

    folder.mkdir(parents=True, exist_ok=True)
    renderer = U7MapRenderer(inv.static_dir, map_num=inv.map_num, game=inv.game)
    palettes = Path(inv.static_dir) / "PALETTES.FLX"
    if not palettes.is_file():
        palettes = next((p for p in Path(inv.static_dir).iterdir() if p.name.lower() == "palettes.flx"), None)
    if palettes is None:
        inv.warnings.append("PALETTES.FLX not found; sprite previews skipped.")
        return {}
    flat_rgb = U7Palette.from_file(str(palettes), palette_index=palette_index).to_flat_rgb()
    shapes_vga = renderer.shapes_vga.records
    decoded: dict[int, object] = {}
    paths: dict[tuple[int, int], str] = {}
    for record in records:
        shape, frame = record["shape"], record["frame"]
        if shape >= len(shapes_vga) or not shapes_vga[shape]:
            continue
        if shape not in decoded:
            try:
                decoded[shape] = U7Shape.from_data(shapes_vga[shape], is_tile=shape < FIRST_OBJ_SHAPE)
            except (ValueError, IndexError):
                decoded[shape] = None
        data = decoded[shape]
        if data is None or frame >= len(data.frames):
            continue
        image, _ax, _ay = _frame_to_rgba(data.frames[frame], flat_rgb)
        name = f"{shape:04d}_{frame:03d}.png"
        image.save(folder / name)
        paths[(shape, frame)] = f"sprites/{name}"
    return paths


def _html(inv: U7MapInventory, summary: dict, objects: list[dict], flats: list[dict]) -> str:
    def table(records: list[dict], kind: str) -> str:
        rows = []
        for r in records:
            img = f'<img src="{html.escape(r["preview"])}" alt="" loading="lazy">' if r.get("preview") else ""
            dims = f'{r["dims_x"]}×{r["dims_y"]}×{r["dims_z"]}' if r["dims_x"] != "" else ""
            sources = ", ".join(
                f"{s} {r[f'{s}_count']:,}" for s in SOURCES if r[f"{s}_count"]
            )
            lift = (f'{r["lift_min"]}–{r["lift_max"]}' if r["lift_min"] != r["lift_max"] else str(r["lift_min"])) if r["lift_min"] != "" else ""
            rows.append(
                f'<tr data-text="{html.escape((r["name"] + " " + r["class"] + " " + r["flags"]).lower())}">'
                f'<td class="n">{r["rank"]}</td><td class="pic">{img}</td>'
                f'<td><b>{r["shape"]}</b>:{r["frame"]}</td><td>{html.escape(r["name"])}</td>'
                f'<td>{html.escape(str(r["class"]))}</td><td>{dims}</td><td class="n">{lift}</td>'
                f'<td class="n">{r["placements"]:,}</td><td class="n">{r["cumulative_pct"]}%</td>'
                f'<td>{sources}</td><td class="n">{r["superchunks"]}</td>'
                f'<td class="n">{r["sample_tx"]},{r["sample_ty"]}</td></tr>'
            )
        return (
            f'<table data-kind="{kind}"><thead><tr><th>#</th><th></th><th>Shape:frame</th><th>Name</th>'
            "<th>Class</th><th>Footprint</th><th>Lift</th><th>Placements</th><th>Cumulative</th>"
            "<th>Sources</th><th>Superchunks</th><th>Sample tile</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>"
        )

    o, f = summary["objects"], summary["flats"]
    title = f"U7 map inventory: {inv.game.upper()} map {inv.map_num}"
    if inv.area:
        title += f" ({_area_label(inv.area)})"
    cov = ", ".join(f"{k.replace('top_', 'top ')} shapes {v}%" for k, v in o["coverage_by_top_shapes_pct"].items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#22211f; --muted:#6c675f; --line:#e3dfd6; --head:#f1eee7; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#e8e4dc; --muted:#a29d93; --line:#2c2c31; --head:#1d1d21; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:13px/1.4 system-ui, sans-serif; }}
h1 {{ font-size:18px; margin:0 0 4px; }} .muted {{ color:var(--muted); }}
.bar {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:12px 0; position:sticky; top:0; background:var(--bg); padding:6px 0; }}
input {{ padding:5px 8px; border:1px solid var(--line); border-radius:5px; background:var(--bg); color:var(--fg); min-width:240px; }}
button {{ padding:5px 10px; border:1px solid var(--line); border-radius:5px; background:var(--head); color:var(--fg); cursor:pointer; }}
button.on {{ outline:2px solid #c99a3a; }}
.wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:middle; }}
th {{ background:var(--head); }}
td.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
td.pic img {{ max-width:96px; max-height:72px; min-height:24px; image-rendering:pixelated; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="muted">{o["placements"]:,} object placements over {o["shapes"]} shapes ({o["shape_frames"]} shape:frames): {html.escape(cov)}.
{f["cells"]:,} ground cells over {f["shape_frames"]} flat shape:frames. Sources: {html.escape("; ".join(f"{k}: {v}" for k, v in summary["sources"].items()))}.</div>
<div class="bar"><button id="bo" class="on">Objects</button><button id="bf">Ground (flats)</button>
<input id="q" type="search" placeholder="Filter by name, class or flag" aria-label="Filter rows"><span id="cnt" class="muted"></span></div>
<div class="wrap" id="objects">{table(objects, "object")}</div>
<div class="wrap" id="flats" hidden>{table(flats, "flat")}</div>
<script>
const q = document.getElementById("q"), cnt = document.getElementById("cnt");
function visible() {{ return document.getElementById("objects").hidden ? "flats" : "objects"; }}
function filter() {{
  const term = q.value.trim().toLowerCase(); let n = 0;
  for (const tr of document.querySelectorAll(`#${{visible()}} tbody tr`)) {{
    const show = !term || tr.dataset.text.includes(term); tr.hidden = !show; if (show) n++;
  }}
  cnt.textContent = `${{n}} rows`;
}}
function show(which) {{
  document.getElementById("objects").hidden = which !== "objects";
  document.getElementById("flats").hidden = which !== "flats";
  document.getElementById("bo").classList.toggle("on", which === "objects");
  document.getElementById("bf").classList.toggle("on", which === "flats");
  filter();
}}
document.getElementById("bo").onclick = () => show("objects");
document.getElementById("bf").onclick = () => show("flats");
q.oninput = filter; filter();
</script></body></html>
"""
