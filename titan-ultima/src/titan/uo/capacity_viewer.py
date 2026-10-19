"""Offline top-down viewer for house-capacity results.

Writes ``index.html`` and ``data.js`` into a folder. The page draws the radar
base map with switchable layers:
- legal ground (cells some legal placement covers);
- why each centre fails (one colour per rule);
- emulator regions;
- packed houses with their yards.

Hovering reports the cell, its failing rule, its region and the house
covering it.

All data is embedded as data URIs inside ``data.js``, so the page works from
``file://`` and can read pixels back for the hover readout (pixels of local
image files would be blocked as cross-origin).
"""

from __future__ import annotations

__all__ = ["write_capacity_viewer"]

import base64
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from titan.uo.placement import REASONS, PlacementResult

COVERED_BIT = 0x80

REASON_LABELS = {
    "centre_region": ("Centre in a no-housing region or T2A", "#b04ec8"),
    "region": ("Region forbids housing (town, dungeon…)", "#7c5cff"),
    "road": ("Road under the house", "#e0a040"),
    "impassable_ground": ("Over water or impassable land", "#3a6ea5"),
    "not_level": ("Ground not level", "#c8b46a"),
    "land_above": ("Land rises above a house tile", "#a0703a"),
    "static": ("Object in the way", "#d0473c"),
    "dense_statics": ("Too many objects in a cell", "#902020"),
    "border_land": ("Border: impassable or road land", "#e07a2c"),
    "border_static": ("Border: object in the way", "#f0a0a0"),
}


def _png_data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def write_capacity_viewer(
    outdir: str | Path,
    *,
    title: str,
    window: tuple[int, int, int, int],
    base_rgb: np.ndarray,
    houses: list[dict[str, object]],
    regions: list[dict[str, object]] | None = None,
    notes: list[str] | None = None,
    packings: list[dict[str, object]] | None = None,
) -> Path:
    """Write the viewer and return the path of ``index.html``.

    Each ``houses`` item needs ``label``, ``result`` (:class:`PlacementResult`),
    ``coverage`` (bool grid aligned with the window) and ``placed`` (list of
    world ``(x, y)`` centres). ``regions`` comes from ``region_outlines``.
    Each ``packings`` item (for example the mixed packing) has ``label``,
    ``kinds`` (``label``, ``multi``, ``class``, ``footprint``) and ``placed``
    (``(x, y, kind index)``); every house's own packing is listed too.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = window

    house_data = []
    for house in houses:
        result: PlacementResult = house["result"]  # type: ignore[assignment]
        coverage: np.ndarray = house["coverage"]  # type: ignore[assignment]
        codes = result.reason_grid.astype(np.uint8).copy()
        codes[coverage] |= COVERED_BIT
        fp = result.footprint
        house_data.append(
            {
                "label": house["label"],
                "multi": f"0x{result.multi_id:04X}",
                "codes": _png_data_uri(Image.fromarray(codes)),
                "legal": result.legal_count,
                "covered": int(coverage.sum()),
                "reasons": result.reasons,
                "placed": [[int(x), int(y)] for x, y in house["placed"]],
                "occupied": sorted([int(x), int(y)] for x, y in fp.occupied),
                "yard": sorted([int(x), int(y)] for x, y in fp.yard - fp.occupied),
            }
        )

    region_data = [
        r for r in (regions or [])
        if r["x"] < x1 and r["x"] + r["w"] > x0 and r["y"] < y1 and r["y"] + r["h"] > y0
    ]
    payload = {
        "title": title,
        "window": [x0, y0, x1, y1],
        "base": _png_data_uri(Image.fromarray(base_rgb.astype(np.uint8))),
        "reasons": [
            {"key": key, "label": REASON_LABELS[key][0], "color": REASON_LABELS[key][1]}
            for key in REASONS
        ],
        "covered_bit": COVERED_BIT,
        "houses": house_data,
        "regions": region_data,
        "notes": notes or [],
        "packings": [
            {
                "label": packing["label"],
                "summary": packing.get("summary", {}),
                "kinds": [
                    {
                        "label": kind["label"],
                        "multi": kind["multi"],
                        "cls": kind["class"],
                        "occupied": sorted([int(x), int(y)] for x, y in kind["footprint"].occupied),
                        "yard": sorted(
                            [int(x), int(y)]
                            for x, y in kind["footprint"].yard - kind["footprint"].occupied
                        ),
                    }
                    for kind in packing["kinds"]
                ],
                "placed": [[int(x), int(y), int(k)] for x, y, k in packing["placed"]],
            }
            for packing in packings or []
        ],
    }
    (outdir / "data.js").write_text(
        "window.CAPACITY = " + json.dumps(payload, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    page = outdir / "index.html"
    page.write_text(_PAGE.replace("__TITLE__", _html_escape(title)), encoding="utf-8")
    return page


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #101114; --panel: rgba(22, 23, 28, 0.92); --line: #34363f;
    --text: #e9e6df; --muted: #a6a29a; --accent: #d9b56a;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; overflow: hidden; }
  #map { position: absolute; inset: 0; width: 100%; height: 100%; cursor: grab; touch-action: none; }
  #map.dragging { cursor: grabbing; }
  .panel { position: absolute; background: var(--panel); border: 1px solid var(--line);
    border-radius: 8px; padding: 10px 12px; backdrop-filter: blur(4px); }
  #side { left: 12px; top: 12px; width: 300px; max-height: calc(100% - 24px); overflow: auto; }
  h1 { font-size: 14px; margin: 0 0 2px; color: var(--accent); font-weight: 600; }
  h2 { font-size: 11px; margin: 12px 0 6px; color: var(--muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: .06em; }
  .sub { color: var(--muted); font-size: 12px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 2px 0; cursor: pointer; }
  .sw { width: 12px; height: 12px; border-radius: 2px; flex: none; border: 1px solid rgba(255,255,255,.15); }
  .num { margin-left: auto; color: var(--muted); font-variant-numeric: tabular-nums; }
  select, input[type=text] { width: 100%; background: #16171c; color: var(--text);
    border: 1px solid var(--line); border-radius: 5px; padding: 4px 6px; font: inherit; }
  .stats { display: grid; grid-template-columns: auto auto; gap: 2px 10px; }
  .stats div:nth-child(even) { text-align: right; font-variant-numeric: tabular-nums; }
  #info { right: 12px; bottom: 12px; min-width: 240px; max-width: min(360px, calc(100% - 24px)); }
  #info .k { color: var(--muted); }
  #zoom { right: 12px; top: 12px; display: flex; gap: 6px; padding: 6px; }
  #zoom button { background: #1d1e24; color: var(--text); border: 1px solid var(--line);
    border-radius: 5px; padding: 3px 10px; font: inherit; cursor: pointer; }
  .note { color: var(--muted); font-size: 12px; margin: 4px 0 0; }
  @media (max-width: 640px) { #side { width: calc(100% - 24px); max-height: 45%; } }
</style>
</head>
<body>
<canvas id="map" aria-label="House placement map"></canvas>
<div id="side" class="panel">
  <h1 id="title"></h1>
  <div class="sub" id="window"></div>
  <h2>House</h2>
  <select id="house" aria-label="House type"></select>
  <div class="stats" id="stats" style="margin-top:8px"></div>
  <h2>Packing</h2>
  <select id="packing" aria-label="Packing"></select>
  <div class="stats" id="packStats" style="margin-top:8px"></div>
  <h2>Layers</h2>
  <label class="row"><input type="checkbox" id="lyBase" checked> Base map</label>
  <label class="row"><input type="checkbox" id="lyCover" checked><span class="sw" style="background:#3cc86a"></span> Legal ground</label>
  <label class="row"><input type="checkbox" id="lyReasons"> Why not (centres)</label>
  <div id="reasonList" style="padding-left:22px"></div>
  <label class="row"><input type="checkbox" id="lyRegions"><span class="sw" style="background:transparent;border-color:#ffffff"></span> Regions</label>
  <label class="row"><input type="checkbox" id="lyHouses" checked><span class="sw" style="background:#f0c83c"></span> Packed houses</label>
  <div id="classLegend" style="padding-left:22px"></div>
  <label class="row"><input type="checkbox" id="lyYards"><span class="sw" style="background:rgba(240,200,60,.35)"></span> Yards (zoom in)</label>
  <h2>Go to</h2>
  <input type="text" id="goto" placeholder="x, y" aria-label="Go to cell x, y">
  <div id="notes"></div>
</div>
<div id="zoom" class="panel">
  <button id="zoomOut" aria-label="Zoom out">&minus;</button>
  <button id="zoomFit">Fit</button>
  <button id="zoomIn" aria-label="Zoom in">+</button>
</div>
<div id="info" class="panel"><span class="k">Hover the map for details.</span></div>
<script src="data.js"></script>
<script>
"use strict";
const D = window.CAPACITY;
const [WX0, WY0, WX1, WY1] = D.window;
const W = WX1 - WX0, H = WY1 - WY0;
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const COVERED = D.covered_bit;
const hidden = new Set(["impassable_ground"]);

let scale = 1, cx = W / 2, cy = H / 2;           // cells per pixel inverse; view centre in window cells
let houseIndex = 0, codes = null, coverCanvas = null, reasonCanvas = null, cellToHouse = new Map();
const CLASS_COLOURS = { small: "#f0c83c", medium: "#f08a3c", large: "#e0503c", forge: "#6fa8dc" };
const CLASS_LABELS = { small: "Small", medium: "Medium", large: "Large", forge: "Forge (workshop)" };
const PACKINGS = D.houses.map((h) => ({
  label: `Small: ${h.label}`,
  kinds: [{ label: h.label, multi: h.multi, cls: "small", occupied: h.occupied, yard: h.yard }],
  placed: h.placed.map(([x, y]) => [x, y, 0]),
})).concat(D.packings);
let packingIndex = D.packings.length ? D.houses.length : 0;
for (const pk of PACKINGS) {
  for (const k of pk.kinds) {
    let a = 0, b = 0, c = 0, d = 0;
    for (const [dx, dy] of k.occupied) { a = Math.min(a, dx); b = Math.max(b, dx); c = Math.min(c, dy); d = Math.max(d, dy); }
    k.box = [a, b, c, d];
  }
}
const base = new Image();

document.getElementById("title").textContent = D.title;
document.getElementById("window").textContent =
  `Window x ${WX0}–${WX1 - 1}, y ${WY0}–${WY1 - 1} · ${W.toLocaleString()} × ${H.toLocaleString()} cells`;
const notes = document.getElementById("notes");
for (const n of D.notes) { const p = document.createElement("p"); p.className = "note"; p.textContent = n; notes.appendChild(p); }

const sel = document.getElementById("house");
D.houses.forEach((h, i) => { const o = document.createElement("option"); o.value = i; o.textContent = `${h.label} (${h.multi})`; sel.appendChild(o); });
sel.onchange = () => loadHouse(+sel.value);
const psel = document.getElementById("packing");
PACKINGS.forEach((pk, i) => { const o = document.createElement("option"); o.value = i; o.textContent = pk.label; psel.appendChild(o); });
psel.value = packingIndex;
psel.onchange = () => { packingIndex = +psel.value; indexHouses(); showPacking(); draw(); };

function showPacking() {
  const pk = PACKINGS[packingIndex];
  const byClass = {};
  for (const [, , k] of pk.placed) { const c = pk.kinds[k].cls; byClass[c] = (byClass[c] || 0) + 1; }
  const rows = [["Houses placed", pk.placed.length]].concat(
    Object.keys(CLASS_LABELS).filter((c) => byClass[c]).map((c) => [CLASS_LABELS[c], byClass[c]]));
  document.getElementById("packStats").innerHTML = rows.map(([k, v]) => `<div class="k">${k}</div><div>${v.toLocaleString()}</div>`).join("");
  const legend = document.getElementById("classLegend");
  legend.innerHTML = "";
  if (pk.kinds.length > 1) {
    for (const c of Object.keys(CLASS_LABELS)) {
      if (!byClass[c]) continue;
      const row = document.createElement("div"); row.className = "row";
      row.innerHTML = `<span class="sw" style="background:${CLASS_COLOURS[c]}"></span> ${CLASS_LABELS[c]}`;
      legend.appendChild(row);
    }
  }
}

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
function hexRgb(hex) { const v = parseInt(hex.slice(1), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }

function buildReasonList() {
  const h = D.houses[houseIndex], box = document.getElementById("reasonList");
  box.innerHTML = "";
  D.reasons.forEach((r) => {
    const row = document.createElement("label"); row.className = "row";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !hidden.has(r.key);
    cb.onchange = () => { cb.checked ? hidden.delete(r.key) : hidden.add(r.key); paintReasons(); draw(); };
    const sw = document.createElement("span"); sw.className = "sw"; sw.style.background = r.color;
    const t = document.createElement("span"); t.textContent = r.label;
    const n = document.createElement("span"); n.className = "num"; n.textContent = (h.reasons[r.key] || 0).toLocaleString();
    row.append(cb, sw, t, n); box.appendChild(row);
  });
}

function showStats() {
  const h = D.houses[houseIndex];
  const rows = [["Legal centres", h.legal], ["Coverable cells", h.covered], ["Tiles per house", h.occupied.length]];
  document.getElementById("stats").innerHTML = rows.map(([k, v]) => `<div class="k">${k}</div><div>${v.toLocaleString()}</div>`).join("");
}

function loadHouse(i) {
  houseIndex = i;
  const h = D.houses[i];
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas"); c.width = W; c.height = H;
    const g = c.getContext("2d"); g.drawImage(img, 0, 0);
    const rgba = g.getImageData(0, 0, W, H).data;
    codes = new Uint8Array(W * H);
    for (let p = 0, q = 0; p < codes.length; p++, q += 4) codes[p] = rgba[q];
    paintCover(); paintReasons(); indexHouses(); buildReasonList(); showStats(); showPacking(); draw();
  };
  img.src = h.codes;
}

function paintCover() {
  coverCanvas = document.createElement("canvas"); coverCanvas.width = W; coverCanvas.height = H;
  const g = coverCanvas.getContext("2d"), im = g.createImageData(W, H), d = im.data;
  for (let p = 0, q = 0; p < codes.length; p++, q += 4) {
    if (codes[p] & COVERED) { d[q] = 60; d[q + 1] = 200; d[q + 2] = 106; d[q + 3] = 150; }
  }
  g.putImageData(im, 0, 0);
}

function paintReasons() {
  reasonCanvas = document.createElement("canvas"); reasonCanvas.width = W; reasonCanvas.height = H;
  const g = reasonCanvas.getContext("2d"), im = g.createImageData(W, H), d = im.data;
  const pal = D.reasons.map((r) => hidden.has(r.key) ? null : hexRgb(r.color));
  for (let p = 0, q = 0; p < codes.length; p++, q += 4) {
    const c = codes[p] & 0x7f;
    if (c === 0) continue;
    const col = pal[c - 1];
    if (!col) continue;
    d[q] = col[0]; d[q + 1] = col[1]; d[q + 2] = col[2]; d[q + 3] = 170;
  }
  g.putImageData(im, 0, 0);
}

function indexHouses() {
  cellToHouse = new Map();
  const pk = PACKINGS[packingIndex];
  pk.placed.forEach(([x, y, k], i) => { for (const [dx, dy] of pk.kinds[k].occupied) cellToHouse.set((x + dx) * 8192 + (y + dy), i); });
}

function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(innerWidth * dpr); canvas.height = Math.round(innerHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function fitScale() { return Math.min(innerWidth / W, innerHeight / H) * 0.95; }

function draw() {
  ctx.fillStyle = "#101114"; ctx.fillRect(0, 0, innerWidth, innerHeight);
  if (!base.complete) return;
  const left = cx - innerWidth / 2 / scale, top = cy - innerHeight / 2 / scale;
  ctx.save();
  ctx.imageSmoothingEnabled = scale < 1;
  ctx.setTransform(ctx.getTransform().multiply(new DOMMatrix([scale, 0, 0, scale, -left * scale, -top * scale])));
  if (document.getElementById("lyBase").checked) ctx.drawImage(base, 0, 0);
  if (coverCanvas && document.getElementById("lyCover").checked) ctx.drawImage(coverCanvas, 0, 0);
  if (reasonCanvas && document.getElementById("lyReasons").checked) ctx.drawImage(reasonCanvas, 0, 0);
  ctx.restore();

  const toX = (x) => (x - WX0 - left) * scale, toY = (y) => (y - WY0 - top) * scale;
  const visible = (x, y, w, h) => toX(x + w) >= 0 && toX(x) <= innerWidth && toY(y + h) >= 0 && toY(y) <= innerHeight;

  if (document.getElementById("lyRegions").checked) {
    ctx.lineWidth = 1; ctx.font = "11px system-ui, sans-serif";
    for (const r of D.regions) {
      if (!visible(r.x, r.y, r.w, r.h)) continue;
      ctx.strokeStyle = r.allow ? "rgba(255,255,255,.35)" : "rgba(255,120,120,.85)";
      ctx.strokeRect(toX(r.x) + .5, toY(r.y) + .5, r.w * scale, r.h * scale);
      if (r.w * scale > 60 && r.h * scale > 14) {
        ctx.fillStyle = r.allow ? "rgba(255,255,255,.7)" : "rgba(255,170,170,.95)";
        ctx.fillText(r.name, toX(r.x) + 4, toY(r.y) + 12);
      }
    }
  }

  const pk = PACKINGS[packingIndex];
  if (pk && document.getElementById("lyHouses").checked) {
    const showYards = document.getElementById("lyYards").checked && scale >= 3;
    const detailed = scale >= 3;
    for (const [x, y, k] of pk.placed) {
      const kind = pk.kinds[k], [minX, maxX, minY, maxY] = kind.box, colour = CLASS_COLOURS[kind.cls];
      if (!visible(x + minX - 6, y + minY - 6, maxX - minX + 13, maxY - minY + 13)) continue;
      if (showYards) {
        ctx.fillStyle = colour + "2e";
        for (const [dx, dy] of kind.yard) ctx.fillRect(toX(x + dx), toY(y + dy), scale, scale);
      }
      if (detailed) {
        ctx.fillStyle = colour + "c0";
        for (const [dx, dy] of kind.occupied) ctx.fillRect(toX(x + dx), toY(y + dy), scale, scale);
        ctx.strokeStyle = "#1a1408"; ctx.lineWidth = 1;
        ctx.strokeRect(toX(x + minX) + .5, toY(y + minY) + .5, (maxX - minX + 1) * scale, (maxY - minY + 1) * scale);
      } else {
        ctx.fillStyle = colour;
        ctx.fillRect(toX(x + minX), toY(y + minY), Math.max(1, (maxX - minX + 1) * scale), Math.max(1, (maxY - minY + 1) * scale));
      }
    }
  }
  const [x, y] = [Math.floor(cx) + WX0, Math.floor(cy) + WY0];
  history.replaceState(null, "", `#${houseIndex},${x},${y},${scale.toFixed(3)},${packingIndex}`);
}

function cellAt(sx, sy) {
  const left = cx - innerWidth / 2 / scale, top = cy - innerHeight / 2 / scale;
  return [Math.floor(left + sx / scale), Math.floor(top + sy / scale)];
}

function describe(wx, wy) {
  const info = document.getElementById("info");
  if (wx < 0 || wy < 0 || wx >= W || wy >= H || !codes) { info.innerHTML = '<span class="k">Outside the window.</span>'; return; }
  const X = wx + WX0, Y = wy + WY0, c = codes[wy * W + wx], code = c & 0x7f;
  const lines = [`<b>${X}, ${Y}</b>`];
  lines.push(code === 0 ? "A house can be centred here." : `<span class="k">Centre fails:</span> ${D.reasons[code - 1].label}`);
  lines.push(c & COVERED ? "Some legal house can cover this cell." : '<span class="k">No legal house covers this cell.</span>');
  let region = null;
  for (let i = D.regions.length - 1; i >= 0; i--) {
    const r = D.regions[i];
    if (X >= r.x && X < r.x + r.w && Y >= r.y && Y < r.y + r.h) { region = r; break; }
  }
  if (region) lines.push(`<span class="k">Region:</span> ${esc(region.name)} (${esc(region.type)}${region.allow ? "" : ", no housing"})`);
  const hi = cellToHouse.get(X * 8192 + Y);
  if (hi !== undefined) {
    const pk = PACKINGS[packingIndex], [hx, hy, k] = pk.placed[hi], kind = pk.kinds[k];
    lines.push(`<span class="k">Packed house #${hi + 1}:</span> ${esc(kind.label)} (${kind.multi}, ${CLASS_LABELS[kind.cls].toLowerCase()}), centred at ${hx}, ${hy}`);
  }
  info.innerHTML = lines.join("<br>");
}

function zoomAt(f, sx, sy) {
  const next = Math.min(40, Math.max(fitScale() * 0.8, scale * f));
  const left = cx - innerWidth / 2 / scale, top = cy - innerHeight / 2 / scale;
  const wx = left + sx / scale, wy = top + sy / scale;
  cx = wx - (sx - innerWidth / 2) / next; cy = wy - (sy - innerHeight / 2) / next;
  scale = next; draw();
}

canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(Math.pow(2, -e.deltaY / 300), e.clientX, e.clientY); }, { passive: false });
let drag = null;
canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx, cy }; canvas.setPointerCapture(e.pointerId); canvas.classList.add("dragging"); });
canvas.addEventListener("pointermove", (e) => {
  if (drag) { cx = drag.cx - (e.clientX - drag.x) / scale; cy = drag.cy - (e.clientY - drag.y) / scale; draw(); }
  const [wx, wy] = cellAt(e.clientX, e.clientY); describe(wx, wy);
});
canvas.addEventListener("pointerup", () => { drag = null; canvas.classList.remove("dragging"); });
canvas.addEventListener("dblclick", (e) => zoomAt(2, e.clientX, e.clientY));
document.getElementById("zoomIn").onclick = () => zoomAt(2, innerWidth / 2, innerHeight / 2);
document.getElementById("zoomOut").onclick = () => zoomAt(0.5, innerWidth / 2, innerHeight / 2);
document.getElementById("zoomFit").onclick = () => { scale = fitScale(); cx = W / 2; cy = H / 2; draw(); };
for (const id of ["lyBase", "lyCover", "lyReasons", "lyRegions", "lyHouses", "lyYards"]) document.getElementById(id).onchange = draw;
document.getElementById("goto").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const p = e.target.value.split(/[ ,]+/).map(Number);
  if (p.length >= 2 && p.every(Number.isFinite)) { cx = p[0] - WX0 + .5; cy = p[1] - WY0 + .5; scale = Math.max(scale, 8); draw(); describe(p[0] - WX0, p[1] - WY0); }
});
addEventListener("resize", resize);

const hash = location.hash.slice(1).split(",").map(Number);
base.onload = () => {
  scale = fitScale();
  if (hash.length >= 4 && hash.every(Number.isFinite)) {
    houseIndex = Math.min(Math.max(0, hash[0]), D.houses.length - 1); sel.value = houseIndex;
    cx = hash[1] - WX0; cy = hash[2] - WY0; scale = hash[3];
    if (hash.length >= 5) { packingIndex = Math.min(Math.max(0, hash[4]), PACKINGS.length - 1); psel.value = packingIndex; }
  }
  resize(); loadHouse(houseIndex);
};
base.src = D.base;
</script>
</body>
</html>
"""
