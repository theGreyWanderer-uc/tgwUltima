"""Whole-facet isometric tile pyramids with an offline HTML viewer.

The finest level is the client's 1:1 isometric view in the global screen space
of :meth:`titan.uo.render.UOMapRenderer.render_window`. Each coarser level
halves it until the facet fits one tile. Tiles are ``{level}/{x}/{y}.jpg``;
all-black tiles are not written and the viewer shows black in their place.
"""

from __future__ import annotations

__all__ = ["FacetTileJob", "build_facet_tiles"]

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import time
from typing import Callable

import numpy as np
from PIL import Image

from titan.uo.map import UOMap
from titan.uo.render import (
    ART_PAD,
    HALF_TILE,
    SCREEN_TOP_PAD,
    UOMapRenderer,
    Z_PAD,
)

FACET_NAMES = {
    0: "Felucca",
    1: "Trammel",
    2: "Ilshenar",
    3: "Malas",
    4: "Tokuno",
    5: "Ter Mur",
}
_DONE_FILE = "chunks_done.txt"


@dataclass(frozen=True)
class FacetTileJob:
    """Everything a worker needs to rebuild the renderer and write tiles."""

    client: str
    facet: int
    output: str
    tile_size: int = 512
    chunk_tiles: int = 4
    quality: int = 85
    container: str = "auto"
    suffix: str = ""
    patches: bool = False
    statics: bool = True
    roofs: bool = True
    shading: bool = True
    hues: bool = True


def _load_renderer(job: FacetTileJob) -> UOMapRenderer:
    facet_map = UOMap.from_client(
        job.client,
        job.facet,
        container=job.container,
        suffix=job.suffix,
        patches=job.patches,
        mapped=True,
    )
    return UOMapRenderer.from_client(job.client, facet_map, hues=job.hues)


_worker_job: FacetTileJob | None = None
_worker_renderer: UOMapRenderer | None = None


def _init_worker(job: FacetTileJob) -> None:
    global _worker_job, _worker_renderer
    _worker_job = job
    _worker_renderer = _load_renderer(job)


def _render_chunk(chunk: tuple[int, int], level: int) -> tuple[tuple[int, int], int]:
    """Render one chunk of the finest level and write its non-black tiles."""
    job, renderer = _worker_job, _worker_renderer
    size = job.tile_size * job.chunk_tiles
    cx, cy = chunk
    image = renderer.render_window(
        cx * size,
        cy * size,
        size,
        size,
        statics=job.statics,
        roofs=job.roofs,
        shading=job.shading,
    )
    pixels = np.asarray(image)
    written = 0
    for ty in range(job.chunk_tiles):
        for tx in range(job.chunk_tiles):
            tile = pixels[
                ty * job.tile_size : (ty + 1) * job.tile_size,
                tx * job.tile_size : (tx + 1) * job.tile_size,
            ]
            if not tile.any():
                continue
            path = (
                Path(job.output)
                / str(level)
                / str(cx * job.chunk_tiles + tx)
                / f"{cy * job.chunk_tiles + ty}.jpg"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(tile).save(path, quality=job.quality)
            written += 1
    return chunk, written


def _reduce_tile(job: FacetTileJob, level: int, parent: tuple[int, int]) -> bool:
    """Build one tile of ``level`` from up to four tiles of ``level + 1``."""
    ts = job.tile_size
    out = Path(job.output)
    px, py = parent
    canvas = Image.new("RGB", (ts * 2, ts * 2))
    found = False
    for dy in (0, 1):
        for dx in (0, 1):
            child = out / str(level + 1) / str(px * 2 + dx) / f"{py * 2 + dy}.jpg"
            if child.is_file():
                with Image.open(child) as tile:
                    canvas.paste(tile, (dx * ts, dy * ts))
                found = True
    if not found:
        return False
    path = out / str(level) / str(px) / f"{py}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.reduce(2).save(path, quality=job.quality)
    return True


def _facet_chunks(renderer: UOMapRenderer, chunk_px: int) -> list[tuple[int, int]]:
    """Chunks whose padded window can touch a facet cell.

    A window maps to an axis-aligned range of ``s = x + y`` (rows) and
    ``d = x - y`` (columns); cells satisfy ``0 <= s + d <= 2W`` and
    ``0 <= s - d <= 2H``.
    """
    facet = renderer.map
    full_w, full_h = renderer.facet_screen_size()
    chunks = []
    pad = Z_PAD + ART_PAD + HALF_TILE * 2
    for cy in range(math.ceil(full_h / chunk_px)):
        s0 = (cy * chunk_px - SCREEN_TOP_PAD - pad) / HALF_TILE
        s1 = ((cy + 1) * chunk_px - SCREEN_TOP_PAD + pad) / HALF_TILE
        for cx in range(math.ceil(full_w / chunk_px)):
            d0 = (cx * chunk_px - pad) / HALF_TILE - facet.height
            d1 = ((cx + 1) * chunk_px + pad) / HALF_TILE - facet.height
            if s1 + d1 < 0 or s0 + d0 > 2 * facet.width:
                continue
            if s1 - d0 < 0 or s0 - d1 > 2 * facet.height:
                continue
            chunks.append((cx, cy))
    return chunks


def build_facet_tiles(
    job: FacetTileJob,
    *,
    workers: int = 1,
    progress: Callable[[str], None] = print,
) -> dict[str, object]:
    """Render the whole facet into a tile pyramid plus ``index.html``.

    Finished chunks are recorded in ``chunks_done.txt`` so an interrupted
    run resumes where it stopped.
    """
    out = Path(job.output)
    out.mkdir(parents=True, exist_ok=True)
    renderer = _load_renderer(job)
    full_w, full_h = renderer.facet_screen_size()
    max_level = max(0, math.ceil(math.log2(max(full_w, full_h) / job.tile_size)))
    chunk_px = job.tile_size * job.chunk_tiles

    done_path = out / _DONE_FILE
    done: set[tuple[int, int]] = set()
    if done_path.is_file():
        for line in done_path.read_text(encoding="utf-8").split():
            cx, cy = line.split(",")
            done.add((int(cx), int(cy)))
    chunks = [c for c in _facet_chunks(renderer, chunk_px) if c not in done]
    meta = {
        "facet": job.facet,
        "name": FACET_NAMES.get(job.facet, f"Facet {job.facet}"),
        "cells_wide": renderer.map.width,
        "cells_high": renderer.map.height,
        "width": full_w,
        "height": full_h,
        "tile_size": job.tile_size,
        "max_level": max_level,
        "half_tile": HALF_TILE,
        "top_pad": SCREEN_TOP_PAD,
        "job": asdict(job),
    }
    del renderer

    progress(
        f"{meta['name']}: {full_w}x{full_h} px, {max_level + 1} levels, "
        f"{len(chunks)} chunk(s) of {chunk_px}px to render "
        f"({len(done)} already done), {workers} worker(s)"
    )
    started = time.monotonic()
    tiles_written = 0
    if chunks:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker, initargs=(job,)
        ) as pool, done_path.open("a", encoding="utf-8") as done_log:
            futures = [pool.submit(_render_chunk, chunk, max_level) for chunk in chunks]
            for count, future in enumerate(as_completed(futures), 1):
                (cx, cy), written = future.result()
                tiles_written += written
                done_log.write(f"{cx},{cy}\n")
                done_log.flush()
                if count % 50 == 0 or count == len(chunks):
                    elapsed = time.monotonic() - started
                    remaining = elapsed / count * (len(chunks) - count)
                    progress(
                        f"  level {max_level}: {count}/{len(chunks)} chunks, "
                        f"{tiles_written} tiles, {elapsed / 60:.1f} min elapsed, "
                        f"~{remaining / 60:.1f} min left"
                    )

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for level in range(max_level - 1, -1, -1):
            child_dir = out / str(level + 1)
            parents = {
                (int(col.name) // 2, int(tile.stem) // 2)
                for col in child_dir.iterdir()
                if col.is_dir()
                for tile in col.glob("*.jpg")
            } if child_dir.is_dir() else set()
            futures = [pool.submit(_reduce_tile, job, level, p) for p in parents]
            built = sum(1 for f in as_completed(futures) if f.result())
            progress(f"  level {level}: {built} tiles")

    meta["elapsed_minutes"] = round((time.monotonic() - started) / 60, 1)
    (out / "tiles.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (out / "index.html").write_text(_viewer_html(meta), encoding="utf-8")
    progress(f"Wrote {out / 'index.html'}")
    return meta


def _viewer_html(meta: dict[str, object]) -> str:
    config = json.dumps(
        {
            key: meta[key]
            for key in (
                "name", "facet", "cells_wide", "cells_high", "width", "height",
                "tile_size", "max_level", "half_tile", "top_pad",
            )
        }
    )
    return _VIEWER_TEMPLATE.replace("__CONFIG__", config).replace(
        "__TITLE__", f"UO {meta['name']} map"
    )


_VIEWER_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg: #000; --panel: rgba(20, 20, 24, 0.82); --text: #e8e6e3; --muted: #a8a49c; --accent: #d9b56a; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; overflow: hidden; }
  #view { position: absolute; inset: 0; cursor: grab; touch-action: none; }
  #view.dragging { cursor: grabbing; }
  #view img { position: absolute; user-select: none; -webkit-user-drag: none; image-rendering: auto; }
  #view.pixelated img { image-rendering: pixelated; }
  .panel { position: absolute; background: var(--panel); border-radius: 6px; padding: 8px 10px;
    backdrop-filter: blur(4px); }
  #info { left: 12px; top: 12px; max-width: calc(100% - 48px); }
  #info h1 { font-size: 14px; margin: 0 0 4px; color: var(--accent); font-weight: 600; }
  #info .row { color: var(--muted); }
  #info form { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
  #info input { width: 110px; background: #111; color: var(--text); border: 1px solid #444;
    border-radius: 4px; padding: 3px 6px; font: inherit; }
  #info button, #zoom button { background: #222; color: var(--text); border: 1px solid #555;
    border-radius: 4px; padding: 3px 9px; font: inherit; cursor: pointer; }
  #zoom { right: 12px; bottom: 12px; display: flex; gap: 6px; }
</style>
</head>
<body>
<div id="view"></div>
<div id="info" class="panel">
  <h1 id="title"></h1>
  <div class="row">Cell <span id="cell">-</span> &middot; zoom <span id="zoomText">-</span></div>
  <form id="goto"><input id="gotoInput" placeholder="x, y" aria-label="Go to cell x, y"><button>Go</button></form>
</div>
<div id="zoom" class="panel">
  <button id="zoomOut" aria-label="Zoom out">&minus;</button>
  <button id="zoomFit">Fit</button>
  <button id="zoomIn" aria-label="Zoom in">+</button>
</div>
<script>
const C = __CONFIG__;
const view = document.getElementById("view");
const tiles = new Map();
const minScale = Math.min(innerWidth / C.width, innerHeight / C.height) * 0.9;
const maxScale = 4;
let scale = minScale, cx = C.width / 2, cy = C.height / 2;

document.getElementById("title").textContent = C.name + " (" + C.cells_wide + " \\u00d7 " + C.cells_high + ")";

function cellToPx(x, y) {
  return [(x - y + C.cells_high) * C.half_tile, (x + y + 1) * C.half_tile + C.top_pad];
}
function pxToCell(px, py) {
  const d = px / C.half_tile - C.cells_high, s = (py - C.top_pad) / C.half_tile - 1;
  return [Math.floor((s + d) / 2), Math.floor((s - d) / 2)];
}

function draw() {
  const level = Math.max(0, Math.min(C.max_level, C.max_level + Math.ceil(Math.log2(scale) - 1e-9)));
  const levelScale = Math.pow(2, level - C.max_level);
  const shown = C.tile_size * scale / levelScale;
  const left = cx - innerWidth / 2 / scale, top = cy - innerHeight / 2 / scale;
  const tx0 = Math.max(0, Math.floor(left * levelScale / C.tile_size));
  const ty0 = Math.max(0, Math.floor(top * levelScale / C.tile_size));
  const tx1 = Math.floor((left + innerWidth / scale) * levelScale / C.tile_size);
  const ty1 = Math.floor((top + innerHeight / scale) * levelScale / C.tile_size);
  const wanted = new Set();
  for (let ty = ty0; ty <= ty1; ty++) {
    for (let tx = tx0; tx <= tx1; tx++) {
      if (tx * C.tile_size >= C.width * levelScale || ty * C.tile_size >= C.height * levelScale) continue;
      const key = level + "/" + tx + "/" + ty;
      wanted.add(key);
      let img = tiles.get(key);
      if (!img) {
        img = new Image();
        img.onerror = () => { img.style.visibility = "hidden"; };
        img.src = key + ".jpg";
        img.draggable = false;
        view.appendChild(img);
        tiles.set(key, img);
      }
      img.style.left = Math.round((tx * C.tile_size / levelScale - left) * scale) + "px";
      img.style.top = Math.round((ty * C.tile_size / levelScale - top) * scale) + "px";
      img.style.width = img.style.height = Math.ceil(shown) + 1 + "px";
    }
  }
  for (const [key, img] of tiles) {
    if (!wanted.has(key)) { img.remove(); tiles.delete(key); }
  }
  view.classList.toggle("pixelated", scale > 1);
  document.getElementById("zoomText").textContent = scale >= 1 ? scale.toFixed(1) + "\\u00d7" : "1/" + (1 / scale).toFixed(1);
  const [x, y] = pxToCell(cx, cy);
  history.replaceState(null, "", "#" + x + "," + y + "," + scale.toFixed(4));
}

function zoomAt(factor, sx, sy) {
  const next = Math.min(maxScale, Math.max(minScale, scale * factor));
  const wx = cx + (sx - innerWidth / 2) / scale, wy = cy + (sy - innerHeight / 2) / scale;
  cx = wx - (sx - innerWidth / 2) / next;
  cy = wy - (sy - innerHeight / 2) / next;
  scale = next;
  draw();
}

view.addEventListener("wheel", (e) => {
  e.preventDefault();
  zoomAt(Math.pow(2, -e.deltaY / 400), e.clientX, e.clientY);
}, { passive: false });

let drag = null;
view.addEventListener("pointerdown", (e) => {
  drag = { x: e.clientX, y: e.clientY, cx, cy };
  view.setPointerCapture(e.pointerId);
  view.classList.add("dragging");
});
view.addEventListener("pointermove", (e) => {
  const [x, y] = pxToCell(cx + (e.clientX - innerWidth / 2) / scale, cy + (e.clientY - innerHeight / 2) / scale);
  document.getElementById("cell").textContent =
    x >= 0 && y >= 0 && x < C.cells_wide && y < C.cells_high ? x + ", " + y : "-";
  if (!drag) return;
  cx = drag.cx - (e.clientX - drag.x) / scale;
  cy = drag.cy - (e.clientY - drag.y) / scale;
  draw();
});
view.addEventListener("pointerup", () => { drag = null; view.classList.remove("dragging"); });
view.addEventListener("dblclick", (e) => zoomAt(2, e.clientX, e.clientY));

document.getElementById("zoomIn").onclick = () => zoomAt(2, innerWidth / 2, innerHeight / 2);
document.getElementById("zoomOut").onclick = () => zoomAt(0.5, innerWidth / 2, innerHeight / 2);
document.getElementById("zoomFit").onclick = () => { scale = minScale; cx = C.width / 2; cy = C.height / 2; draw(); };
document.getElementById("goto").onsubmit = (e) => {
  e.preventDefault();
  const parts = document.getElementById("gotoInput").value.split(/[ ,]+/).map(Number);
  if (parts.length >= 2 && parts.every(Number.isFinite)) {
    [cx, cy] = cellToPx(parts[0], parts[1]);
    scale = Math.max(scale, 1);
    draw();
  }
};
addEventListener("resize", draw);

const hash = location.hash.slice(1).split(",").map(Number);
if (hash.length === 3 && hash.every(Number.isFinite)) {
  [cx, cy] = cellToPx(hash[0], hash[1]);
  scale = Math.min(maxScale, Math.max(minScale, hash[2]));
}
draw();
</script>
</body>
</html>
"""
