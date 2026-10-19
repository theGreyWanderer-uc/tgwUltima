"""Inventory of what a UO facet is made of: every land and static tile it uses.

The Ultima Online counterpart of :mod:`titan.u7.map_inventory`. Land is one
tile per cell (``mapN``); statics are the fixed objects in ``staticsN``
(walls, floors, roofs, trees, rocks...). Each tile ID is ranked by
placements, with its tiledata name, flags, height, altitude range, spread
over 8x8 blocks and a sample cell. Tiledata names are material names shared
by many IDs (every orientation and piece of a ``plaster wall`` is its own
ID), so ``names.csv`` rolls the statics up by name.
"""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from titan.uo.map import UOMap
from titan.uo.render import _COLOR16_RGB, UOArtSource
from titan.uo.tiledata import UOTileData, flag_names

COVERAGE_TOPS = (10, 25, 50, 100, 200, 400)

# Checked in order; the first that applies names the row's category.
_FLAG_CATEGORIES = (
    ("door", lambda flags, name: "door" in flags),
    ("window", lambda flags, name: "window" in flags or "window" in name),
    ("roof", lambda flags, name: "roof" in flags),
    ("wall", lambda flags, name: "wall" in flags),
    ("stairs", lambda flags, name: "stair" in name or "step" in name),
    ("floor", lambda flags, name: "surface" in flags and "floor" in name),
    ("water", lambda flags, name: "wet" in flags),
    ("foliage", lambda flags, name: "foliage" in flags),
    ("surface", lambda flags, name: "surface" in flags),
    ("obstacle", lambda flags, name: "impassable" in flags),
    ("other", lambda flags, name: True),
)


def tile_category(flags: tuple[str, ...], name: str) -> str:
    """A coarse category from tiledata flags and name (door, wall, roof, floor...)."""
    lowered = name.lower()
    return next(label for label, test in _FLAG_CATEGORIES if test(flags, lowered))


@dataclass
class UOInventoryRow:
    kind: str  # "static" or "land"
    tile_id: int
    placements: int
    z_min: int
    z_max: int
    z_common: int
    blocks: int
    sample: tuple[int, int, int]
    hued: int = 0
    hues: int = 0


@dataclass
class UOMapInventory:
    facet: int
    client: str
    width: int
    height: int
    tiledata: UOTileData
    statics: list[UOInventoryRow] = field(default_factory=list)
    land: list[UOInventoryRow] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def name(self, row: UOInventoryRow) -> str:
        table = self.tiledata.statics if row.kind == "static" else self.tiledata.land
        return table[row.tile_id].name if row.tile_id < len(table) else ""

    def flags(self, row: UOInventoryRow) -> tuple[str, ...]:
        table = self.tiledata.statics if row.kind == "static" else self.tiledata.land
        return flag_names(table[row.tile_id].flags) if row.tile_id < len(table) else ()


def _group_stats(ids, z, x, y, blocks, *, kind, hues=None) -> list[UOInventoryRow]:
    """One row per tile ID, ranked by placements (ties by ID)."""
    if ids.size == 0:
        return []
    order = np.argsort(ids, kind="stable")
    ids, z, x, y, blocks = ids[order], z[order], x[order], y[order], blocks[order]
    unique, starts, counts = np.unique(ids, return_index=True, return_counts=True)
    z_min = np.minimum.reduceat(z, starts)
    z_max = np.maximum.reduceat(z, starts)

    # Most common altitude per ID: count (id, z) pairs and keep the largest.
    pair = ids.astype(np.int64) * 256 + (z.astype(np.int64) + 128)
    pair_values, pair_counts = np.unique(pair, return_counts=True)
    pair_ids = pair_values // 256
    best = np.lexsort((-pair_counts, pair_ids))
    first = np.unique(pair_ids[best], return_index=True)[1]
    z_common = (pair_values[best][first] % 256) - 128

    block_pairs = np.unique(ids.astype(np.int64) * (1 << 32) + blocks.astype(np.int64))
    block_counts = np.unique(block_pairs >> 32, return_counts=True)[1]

    hued = hue_kinds = np.zeros(len(unique), dtype=np.int64)
    if hues is not None:
        hues = hues[order]
        hued = np.add.reduceat((hues != 0).astype(np.int64), starts)
        hue_pairs = np.unique(ids[hues != 0].astype(np.int64) * 65536 + hues[hues != 0])
        hue_ids, hue_counts = np.unique(hue_pairs // 65536, return_counts=True)
        hue_kinds = np.zeros(len(unique), dtype=np.int64)
        hue_kinds[np.searchsorted(unique, hue_ids)] = hue_counts

    rows = [
        UOInventoryRow(
            kind=kind,
            tile_id=int(unique[i]),
            placements=int(counts[i]),
            z_min=int(z_min[i]),
            z_max=int(z_max[i]),
            z_common=int(z_common[i]),
            blocks=int(block_counts[i]),
            sample=(int(x[starts[i]]), int(y[starts[i]]), int(z[starts[i]])),
            hued=int(hued[i]),
            hues=int(hue_kinds[i]),
        )
        for i in range(len(unique))
    ]
    rows.sort(key=lambda r: (-r.placements, r.tile_id))
    return rows


def build_uo_map_inventory(
    client: str | Path,
    facet: int = 0,
    *,
    container: str = "auto",
    suffix: str = "",
    patches: bool = False,
    tiledata: UOTileData | None = None,
    facet_map: UOMap | None = None,
) -> UOMapInventory:
    """Count every land and static tile a facet uses.

    ``facet_map`` skips loading the facet from ``client``.
    """
    client = Path(client)
    if facet_map is None:
        facet_map = UOMap.from_client(client, facet, container=container, suffix=suffix, patches=patches)
    tiledata = tiledata or UOTileData.from_file(client / "tiledata.mul")
    inv = UOMapInventory(facet, str(client), facet_map.width, facet_map.height, tiledata)

    statics = facet_map.static_records()
    inv.statics = _group_stats(
        statics["tile_id"], statics["z"], statics["x"], statics["y"], statics["block"],
        kind="static", hues=statics["hue"],
    )

    land_ids, land_z = facet_map.land_arrays()
    ys, xs = np.indices(land_ids.shape, dtype=np.int32)
    land_blocks = (xs // 8) * facet_map.blocks_high + (ys // 8)
    inv.land = _group_stats(
        land_ids.ravel(), land_z.ravel(), xs.ravel(), ys.ravel(), land_blocks.ravel(), kind="land"
    )

    source = facet_map.source
    land_file = Path(source.land_path).name if source else f"map{facet}{suffix}"
    inv.sources = {
        "land": f"{land_file} ({facet_map.width}x{facet_map.height})",
        "statics": f"staidx{facet}{suffix}.mul / statics{facet}{suffix}.mul ({len(statics):,} records)",
        "tiledata": "tiledata.mul",
    }
    if source and (source.land_patch_blocks or source.static_patch_blocks):
        inv.sources["patches"] = (
            f"{source.land_patch_blocks} land / {source.static_patch_blocks} static blocks"
        )
    return inv


def _row_record(inv: UOMapInventory, row: UOInventoryRow, rank: int, total: int, cumulative: int):
    flags = inv.flags(row)
    name = inv.name(row)
    record: dict[str, object] = {
        "rank": rank,
        "tile_id": row.tile_id,
        "tile_hex": f"0x{row.tile_id:04X}",
        "name": name,
        "category": tile_category(flags, name),
        "flags": "|".join(flags),
    }
    if row.kind == "static":
        tile = inv.tiledata.statics[row.tile_id]
        record["height"] = tile.height
    else:
        record["texture_id"] = inv.tiledata.land[row.tile_id].texture_id
    record.update(
        placements=row.placements,
        share_pct=round(100 * row.placements / total, 3) if total else 0,
        cumulative_pct=round(100 * cumulative / total, 2) if total else 0,
        z_min=row.z_min,
        z_max=row.z_max,
        z_common=row.z_common,
        blocks=row.blocks,
    )
    if row.kind == "static":
        record.update(hued=row.hued, hues=row.hues)
    record.update(sample_x=row.sample[0], sample_y=row.sample[1], sample_z=row.sample[2], preview="")
    return record


def _ranked_records(inv: UOMapInventory, rows: list[UOInventoryRow]) -> list[dict]:
    total = sum(r.placements for r in rows)
    out, cumulative = [], 0
    for rank, row in enumerate(rows, 1):
        cumulative += row.placements
        out.append(_row_record(inv, row, rank, total, cumulative))
    return out


def _name_records(records: list[dict]) -> list[dict]:
    """Statics rolled up by tiledata name, ranked by placements."""
    groups: dict[str, dict] = {}
    for r in records:
        key = r["name"] or "(unnamed)"
        g = groups.setdefault(
            key,
            {"name": key, "categories": {}, "tile_ids": 0, "placements": 0, "z_min": r["z_min"],
             "z_max": r["z_max"], "top_tile": r["tile_hex"], "ids": []},
        )
        g["tile_ids"] += 1
        g["placements"] += r["placements"]
        g["categories"][r["category"]] = g["categories"].get(r["category"], 0) + r["placements"]
        g["z_min"] = min(g["z_min"], r["z_min"])
        g["z_max"] = max(g["z_max"], r["z_max"])
        g["ids"].append(r["tile_hex"])
    total = sum(g["placements"] for g in groups.values())
    out, cumulative = [], 0
    for rank, g in enumerate(sorted(groups.values(), key=lambda g: (-g["placements"], g["name"])), 1):
        cumulative += g["placements"]
        out.append(
            {
                "rank": rank,
                "name": g["name"],
                "category": max(g["categories"], key=g["categories"].get),
                "tile_ids": g["tile_ids"],
                "placements": g["placements"],
                "share_pct": round(100 * g["placements"] / total, 3) if total else 0,
                "cumulative_pct": round(100 * cumulative / total, 2) if total else 0,
                "z_min": g["z_min"],
                "z_max": g["z_max"],
                "top_tile": g["top_tile"],
                "ids": " ".join(g["ids"]),
            }
        )
    return out


def _coverage(records: list[dict]) -> dict[str, float]:
    total = sum(r["placements"] for r in records)
    return {
        f"top_{n}": round(100 * sum(r["placements"] for r in records[:n]) / total, 2) if total else 0
        for n in COVERAGE_TOPS
    }


def _counts_by(records: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        counts[r[key]] = counts.get(r[key], 0) + r["placements"]
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def write_uo_map_inventory(
    inv: UOMapInventory, outdir: str | Path, *, previews: bool = True, art: UOArtSource | None = None
) -> dict[str, object]:
    """Write ``statics.csv``, ``land.csv``, ``names.csv``, ``summary.json``
    and, with ``previews``, art PNGs plus ``index.html``."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    statics = _ranked_records(inv, inv.statics)
    land = _ranked_records(inv, inv.land)
    names = _name_records(statics)

    if previews:
        art = art or UOArtSource.from_client(inv.client)
        _write_previews(art, statics, land, outdir / "sprites")

    for name, records in (("statics.csv", statics), ("land.csv", land), ("names.csv", names)):
        _write_csv(outdir / name, records)

    summary = {
        "facet": inv.facet,
        "client": inv.client,
        "size": [inv.width, inv.height],
        "sources": inv.sources,
        "statics": {
            "placements": sum(r["placements"] for r in statics),
            "tile_ids": len(statics),
            "names": len(names),
            "by_category": _counts_by(statics, "category"),
            "coverage_by_top_names_pct": _coverage(names),
            "coverage_by_top_tile_ids_pct": _coverage(statics),
        },
        "land": {
            "cells": sum(r["placements"] for r in land),
            "tile_ids": len(land),
            "names": len({r["name"] for r in land}),
            "coverage_by_top_tile_ids_pct": _coverage(land),
        },
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if previews:
        (outdir / "index.html").write_text(_html(inv, summary, statics, land, names), encoding="utf-8")
    return summary


def _write_csv(path: Path, records: list[dict]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _to_image(pixels: np.ndarray) -> Image.Image:
    rgba = np.zeros((*pixels.shape, 4), dtype=np.uint8)
    rgba[..., :3] = _COLOR16_RGB[pixels]
    rgba[..., 3] = np.where(pixels != 0, 255, 0)
    return Image.fromarray(rgba)


def _write_previews(art: UOArtSource, statics, land, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for records, prefix, decode in ((statics, "static", art.static), (land, "land", art.land)):
        for record in records:
            pixels = decode(record["tile_id"])
            if pixels is None or not pixels.any():
                continue
            name = f"{prefix}_{record['tile_id']:05d}.png"
            _to_image(pixels).save(folder / name)
            record["preview"] = f"sprites/{name}"


def _z_range(r: dict) -> str:
    return str(r["z_min"]) if r["z_min"] == r["z_max"] else f'{r["z_min"]} to {r["z_max"]}'


def _html(inv: UOMapInventory, summary: dict, statics, land, names) -> str:
    def tile_table(records: list[dict], kind: str) -> str:
        rows = []
        for r in records:
            img = f'<img src="{html.escape(r["preview"])}" alt="" loading="lazy">' if r["preview"] else ""
            z = _z_range(r)
            extra = (
                f'<td class="n">{r["height"]}</td><td class="n">{r["hued"]:,}</td>'
                if kind == "static" else f'<td class="n">{r["texture_id"]}</td>'
            )
            rows.append(
                f'<tr data-text="{html.escape((r["tile_hex"] + " " + str(r["tile_id"]) + " " + r["name"] + " " + r["category"] + " " + r["flags"]).lower())}">'
                f'<td class="n">{r["rank"]}</td><td class="pic">{img}</td>'
                f'<td><b>{r["tile_hex"]}</b> <span class="muted">{r["tile_id"]}</span></td>'
                f'<td>{html.escape(r["name"])}</td><td>{r["category"]}</td>'
                f'<td class="flags">{html.escape(r["flags"].replace("|", " "))}</td>{extra}'
                f'<td class="n">{z}</td><td class="n">{r["placements"]:,}</td>'
                f'<td class="n">{r["cumulative_pct"]}%</td><td class="n">{r["blocks"]:,}</td>'
                f'<td class="n">{r["sample_x"]},{r["sample_y"]},{r["sample_z"]}</td></tr>'
            )
        extra_head = "<th>Height</th><th>Hued</th>" if kind == "static" else "<th>Texture</th>"
        return (
            f'<table><thead><tr><th>#</th><th></th><th>Tile</th><th>Name</th><th>Category</th>'
            f"<th>Flags</th>{extra_head}<th>Z</th><th>Placements</th><th>Cumulative</th>"
            "<th>Blocks</th><th>Sample x,y,z</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )

    def name_table() -> str:
        previews = {r["tile_hex"]: r["preview"] for r in statics}
        rows = []
        for g in names:
            src = previews.get(g["top_tile"], "")
            img = f'<img src="{html.escape(src)}" alt="" loading="lazy">' if src else ""
            z = _z_range(g)
            ids = g["ids"].split()
            shown = " ".join(ids[:12]) + (f" +{len(ids) - 12} more" if len(ids) > 12 else "")
            rows.append(
                f'<tr data-text="{html.escape((g["name"] + " " + g["category"] + " " + g["ids"]).lower())}">'
                f'<td class="n">{g["rank"]}</td><td class="pic">{img}</td><td><b>{html.escape(g["name"])}</b></td>'
                f'<td>{g["category"]}</td><td class="n">{g["tile_ids"]}</td><td class="n">{z}</td>'
                f'<td class="n">{g["placements"]:,}</td><td class="n">{g["cumulative_pct"]}%</td>'
                f'<td class="ids">{html.escape(shown)}</td></tr>'
            )
        return (
            "<table><thead><tr><th>#</th><th></th><th>Name</th><th>Category</th><th>Tile IDs</th>"
            "<th>Z</th><th>Placements</th><th>Cumulative</th><th>IDs (most placed first)</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>"
        )

    s, l = summary["statics"], summary["land"]
    title = f"UO map inventory: facet {inv.facet}"
    cov = ", ".join(f"{k.replace('top_', 'top ')} names {v}%" for k, v in s["coverage_by_top_names_pct"].items())
    cats = ", ".join(f"{k} {v:,}" for k, v in s["by_category"].items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#22211f; --muted:#6c675f; --line:#e3dfd6; --head:#f1eee7; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#e8e4dc; --muted:#a29d93; --line:#2c2c31; --head:#1d1d21; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:13px/1.4 system-ui, sans-serif; }}
h1 {{ font-size:18px; margin:0 0 4px; }} .muted {{ color:var(--muted); }}
.bar {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:12px 0; position:sticky; top:0; background:var(--bg); padding:6px 0; z-index:1; }}
input {{ padding:5px 8px; border:1px solid var(--line); border-radius:5px; background:var(--bg); color:var(--fg); min-width:240px; }}
button {{ padding:5px 10px; border:1px solid var(--line); border-radius:5px; background:var(--head); color:var(--fg); cursor:pointer; }}
button.on {{ outline:2px solid #c99a3a; }}
.wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:middle; }}
th {{ background:var(--head); }}
td.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
td.flags, td.ids {{ color:var(--muted); font-size:12px; }} td.ids {{ max-width:420px; }}
td.pic img {{ max-width:96px; max-height:96px; min-height:22px; image-rendering:pixelated; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="muted">{inv.width}×{inv.height} cells. {s["placements"]:,} statics over {s["tile_ids"]:,} tile IDs and {s["names"]:,} tiledata names: {html.escape(cov)}.
By category: {html.escape(cats)}. {l["cells"]:,} land cells over {l["tile_ids"]:,} land tile IDs.
Sources: {html.escape("; ".join(f"{k}: {v}" for k, v in summary["sources"].items()))}.</div>
<div class="bar"><button data-view="names" class="on">Statics by name</button><button data-view="statics">Statics by tile ID</button><button data-view="land">Land</button>
<input id="q" type="search" placeholder="Filter by name, category, flag or ID" aria-label="Filter rows"><span id="cnt" class="muted"></span></div>
<div class="wrap view" id="names">{name_table()}</div>
<div class="wrap view" id="statics" hidden>{tile_table(statics, "static")}</div>
<div class="wrap view" id="land" hidden>{tile_table(land, "land")}</div>
<script>
const q = document.getElementById("q"), cnt = document.getElementById("cnt");
let current = "names";
function filter() {{
  const term = q.value.trim().toLowerCase(); let n = 0;
  for (const tr of document.querySelectorAll(`#${{current}} tbody tr`)) {{
    const show = !term || tr.dataset.text.includes(term); tr.hidden = !show; if (show) n++;
  }}
  cnt.textContent = `${{n.toLocaleString()}} rows`;
}}
for (const b of document.querySelectorAll("button[data-view]")) {{
  b.onclick = () => {{
    current = b.dataset.view;
    for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== current;
    for (const o of document.querySelectorAll("button[data-view]")) o.classList.toggle("on", o === b);
    filter();
  }};
}}
q.oninput = filter; filter();
</script></body></html>
"""
