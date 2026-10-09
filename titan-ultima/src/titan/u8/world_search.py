"""U8 world search: captured live items, unloaded maps and optional GLOB children."""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from titan.u8.container_browser import U8ContainerSession, build_u8_container_session
from titan.u8.container_records import build_u8_stored_inventories
from titan.u8.map import U8MapRenderer
from titan.u8.map_browser import (
    U8MapBrowserSession,
    describe_u8_map_rows,
    validate_u8_map_output,
)
from titan.u8.save_browser import next_u8_save_browser_export
from titan.u8.shape_browser import find_u8_browser_file, load_u8_shape_library

U8_WORLD_SEARCH_OUTPUT = Path("titan-out/u8_world_query_export")
U8_EGG_SEARCH_OUTPUT = Path("titan-out/u8_egg_query_export")


@dataclass(frozen=True)
class U8WorldSearchFilters:
    """Area filters use resolved world units, never inventory X/Y or egg map bytes."""

    query: str = ""
    shapes: tuple[int, ...] = ()
    map_id: int | None = None
    family: int | None = None
    storage: str = "all"
    scope: str = "world"
    area: tuple[int, int, int, int] | None = None
    min_z: int = 0
    max_z: int = 250
    status_mask: int = 0
    shape_flag_mask: int = 0
    expand_globs: bool = False

    def __post_init__(self) -> None:
        if any(not 0 <= shape < 2048 for shape in self.shapes):
            raise ValueError("U8 world search: shapes must be 0–2047")
        if self.map_id is not None and not 0 <= self.map_id <= 255:
            raise ValueError("U8 world search: map must be 0–255")
        if self.family is not None and not 0 <= self.family <= 15:
            raise ValueError("U8 world search: family must be 0–15")
        if self.storage not in {"all", "cache", "fixed", "nonfixed", "glob"}:
            raise ValueError("U8 world search: unknown storage filter")
        if self.scope not in {"world", "all", "contained", "diagnostics"}:
            raise ValueError("U8 world search: unknown location scope")
        if not 0 <= self.min_z <= self.max_z <= 250:
            raise ValueError("U8 world search: Z range must be 0–250")
        if self.area and not (
            0 <= self.area[0] <= self.area[2] <= 32767
            and 0 <= self.area[1] <= self.area[3] <= 32767
        ):
            raise ValueError("U8 world search: area must be x0,y0,x1,y1 within 0–32767")
        if not 0 <= self.status_mask <= 65535 or not 0 <= self.shape_flag_mask <= 65535:
            raise ValueError("U8 world search: flag masks must be 0–65535")


@dataclass
class U8WorldSearchSession:
    """One captured source index; cache IDs and map record identities never collide."""

    maps: U8MapBrowserSession
    rows: list[dict[str, Any]]
    by_identity: dict[str, dict[str, Any]]
    inventory: U8ContainerSession | None
    coverage: dict[str, Any]
    diagnostics: list[str]


def _world_search_properties(maps: U8MapBrowserSession, row: dict[str, Any]) -> None:
    props = maps.library.properties.get(row["shape"])
    row.update(
        shape_name=maps.library.names.get(row["shape"], ""),
        family=props.family if props else None,
        family_name=props.family_name() if props else "unknown",
        shape_flags=props.flag_names() if props else [],
        shape_flags_raw=props.flags if props else 0,
    )


def build_u8_world_search_session(maps: U8MapBrowserSession) -> U8WorldSearchSession:
    """Replace the active map and stored NPC registry with captured allocated cache slots."""
    inventory = None
    active_map = None
    diagnostics = list(maps.library.diagnostics)
    if maps.snapshot and maps.snapshot.item_cache:
        gumps = None
        gump_path = find_u8_browser_file(maps.library.path.parent, "U8GUMPS.FLX")
        if gump_path:
            try:
                gumps = load_u8_shape_library(
                    gump_path, palette=maps.library.palette_path
                )
            except (ValueError, OSError) as error:
                diagnostics.append(f"Inventory gump artwork unavailable: {error}")
        inventory = build_u8_container_session(
            maps.snapshot,
            maps.library,
            include_stored=False,
            gumps=gumps,
            names=maps.npc_session.names_file if maps.npc_session else None,
        )
        candidate = maps.snapshot.item_cache.metadata.map_in
        if 1 <= candidate <= 255:
            active_map = candidate
        else:
            diagnostics.append(
                "Invalid/zero active map: stored maps retained; cache world positions unresolved"
            )
        stored = build_u8_stored_inventories(
            [archive for archive in (maps.fixed, maps.nonfixed) if archive is not None],
            active_map=active_map if active_map is not None else -1,
            properties=maps.library.properties,
            names=maps.library.names,
        )
        inventory.items.update(stored.items)
        inventory.children.update(stored.children)
        inventory.containers.extend(stored.containers)
        inventory.fixed, inventory.fixed_path = maps.fixed, maps.fixed_path
        inventory.stored_maps = tuple(stored.map_ids)
        inventory.include_stored = True
        diagnostics.extend(inventory.diagnostics + stored.diagnostics)
    elif maps.snapshot:
        diagnostics.append(
            "ITEMCACH.DAT unavailable: stored maps only; loaded-map changes and live NPC inventories unavailable"
        )

    rows: list[dict[str, Any]] = []
    skipped = 0
    for map_id in maps.map_ids:
        if inventory is not None and (map_id == 0 or map_id == active_map):
            skipped += len(maps.records(map_id))
            continue
        for row in describe_u8_map_rows(maps, map_id):
            identity = f"{row['archive_kind'].upper()}:{map_id}:{row['record_index']}"
            row.update(
                identity=identity,
                item_id=identity,
                cache_id=None,
                container_id=f"{row['archive_kind'].upper()}:{map_id}:{row['parent_record_index']}"
                if row["parent_record_index"] is not None
                else None,
                root_item_id=f"{row['archive_kind'].upper()}:{map_id}:{row['root_record_index']}"
                if row["root_record_index"] is not None
                else None,
                npc_name="",
                npc_label="",
                owner_name="",
                owner_npc_id=None,
                is_npc=False,
                flag_names=row["status_names"],
                glob_parent=None,
            )
            _world_search_properties(maps, row)
            rows.append(row)
    if inventory:
        for number, original in inventory.items.items():
            if not isinstance(number, int):
                continue
            row = dict(original)
            row["diagnostics"] = list(original["diagnostics"])
            row.update(identity=f"CACHE:{number}", glob_parent=None)
            if row["location_kind"] == "world_stored" and (
                row["x"] >= 32768 or row["y"] >= 32768
            ):
                row["diagnostics"].append(
                    "Signed-negative cache X/Y cannot be used as a world position"
                )
            if not row["is_npc"] and active_map is None:
                row["map_id"] = None
            _world_search_properties(maps, row)
            rows.append(row)
    by_identity = {row["identity"]: row for row in rows}
    for row in rows:
        anchor = row
        if row["location_kind"] == "contained":
            root = row.get("root_item_id")
            anchor = by_identity.get(
                f"CACHE:{root}" if isinstance(root, int) else str(root), {}
            )
        positioned = (
            anchor.get("location_kind") == "world_stored"
            and anchor.get("map_id") not in {None, 0}
            and not anchor.get("diagnostics")
        )
        row.update(
            world_x=anchor["x"] if positioned else None,
            world_y=anchor["y"] if positioned else None,
            world_z=anchor["z"] if positioned else None,
        )
    if maps.snapshot:
        diagnostics.extend(
            f"{name}: {issue}" for name, issue in maps.snapshot.decode_errors.items()
        )
    coverage = {
        "source": str(maps.snapshot.source)
        if maps.snapshot
        else "stored FIXED/NONFIXED",
        "active_map": active_map,
        "live_cache_items": sum(row["archive_kind"] == "cache" for row in rows),
        "stored_records": sum(row["archive_kind"] != "cache" for row in rows),
        "map_ids": sorted({row["map_id"] for row in rows if row["map_id"] is not None}),
        "stored_records_replaced_by_cache": skipped,
        "glob_markers": sum(row["family"] == 3 for row in rows),
        "glob_children": "searched only with --expand-globs; derived identities, not saved item IDs",
    }
    for row in rows:
        if row["family"] == 3 and row["world_x"] is not None:
            raw = maps.globs.get(row["quality"])
            if (
                raw is None
                or len(raw) < 2
                or len(raw) != 2 + int.from_bytes(raw[:2], "little") * 6
            ):
                diagnostics.append(
                    f"{row['identity']}: missing/malformed GLOB {row['quality']}; children cannot be searched"
                )
    return U8WorldSearchSession(
        maps, rows, by_identity, inventory, coverage, sorted(set(diagnostics))
    )


def iter_u8_world_search_rows(
    session: U8WorldSearchSession, *, expand_globs: bool = False
) -> Iterator[dict[str, Any]]:
    """Yield optional GLOB children lazily, retaining their stamp identity and native positions."""
    yield from session.rows
    if not expand_globs:
        return
    for parent in session.rows:
        if (
            parent["family"] != 3
            or parent["location_kind"] != "world_stored"
            or parent["world_x"] is None
        ):
            continue
        raw = session.maps.globs.get(parent["quality"])
        if (
            raw is None
            or len(raw) < 2
            or len(raw) != 2 + int.from_bytes(raw[:2], "little") * 6
        ):
            continue
        for index, child in enumerate(U8MapRenderer.load_glob(raw)):
            row = {
                "identity": f"GLOB:{parent['identity']}:{index}",
                "item_id": None,
                "archive_kind": "glob",
                "record_index": index,
                "cache_id": None,
                "map_id": parent["map_id"],
                "shape": child.type_num,
                "frame": child.frame,
                "x": child.x * 2 + (parent["x"] & ~511),
                "y": child.y * 2 + (parent["y"] & ~511),
                "z": child.z + parent["z"],
                "status": 0x82,
                "quality": None,
                "npc_num": None,
                "map_num_raw": None,
                "container_id": None,
                "root_item_id": None,
                "is_npc": False,
                "npc_name": "",
                "npc_label": "",
                "owner_name": "",
                "owner_npc_id": None,
                "location_kind": "world_stored",
                "flag_names": ["disposable", "fast_only"],
                "diagnostics": [],
                "glob_parent": parent["identity"],
                "glob_num": parent["quality"],
            }
            row.update(world_x=row["x"], world_y=row["y"], world_z=row["z"])
            if (
                not 0 <= row["x"] < 32768
                or not 0 <= row["y"] < 32768
                or row["z"] >= 251
            ):
                row["diagnostics"].append(
                    "Expanded GLOB position outside native world bounds"
                )
                row.update(world_x=None, world_y=None, world_z=None)
            _world_search_properties(session.maps, row)
            yield row


def match_u8_world_search_row(
    row: dict[str, Any], filters: U8WorldSearchFilters
) -> bool:
    """Match masks with all requested bits, and containment against its resolved root position."""
    if filters.map_id is not None and row["map_id"] != filters.map_id:
        return False
    if filters.storage != "all" and row["archive_kind"] != filters.storage:
        return False
    if filters.shapes and row["shape"] not in filters.shapes:
        return False
    if filters.family is not None and row["family"] != filters.family:
        return False
    if filters.scope == "world" and (
        row["location_kind"] != "world_stored" or row["world_x"] is None
    ):
        return False
    if filters.scope == "contained" and row["location_kind"] != "contained":
        return False
    if filters.scope == "diagnostics" and not row["diagnostics"]:
        return False
    if (
        row["world_z"] is not None
        and not filters.min_z <= row["world_z"] <= filters.max_z
    ):
        return False
    if row["world_z"] is None and (filters.min_z != 0 or filters.max_z != 250):
        return False
    if filters.area:
        x, y = row["world_x"], row["world_y"]
        if (
            x is None
            or y is None
            or not (
                filters.area[0] <= x <= filters.area[2]
                and filters.area[1] <= y <= filters.area[3]
            )
        ):
            return False
    if row["status"] & filters.status_mask != filters.status_mask:
        return False
    if row["shape_flags_raw"] & filters.shape_flag_mask != filters.shape_flag_mask:
        return False
    text = " ".join(
        str(row.get(key, ""))
        for key in (
            "identity",
            "shape_name",
            "npc_name",
            "npc_label",
            "owner_name",
            "family_name",
            "flag_names",
            "shape_flags",
            "diagnostics",
            "trigger_kind",
            "usecode_name",
            "monster_shape_name",
        )
    ).casefold()
    return filters.query.strip().casefold() in text


def query_u8_world_items(
    session: U8WorldSearchSession,
    filters: U8WorldSearchFilters = U8WorldSearchFilters(),
) -> list[dict[str, Any]]:
    """Search all captured maps with optional lazy GLOB expansion."""
    return [
        row
        for row in iter_u8_world_search_rows(session, expand_globs=filters.expand_globs)
        if match_u8_world_search_row(row, filters)
    ]


def format_u8_world_search_results(
    rows: list[dict[str, Any]], output_format: str = "table"
) -> str:
    """Emit complete JSON/CSV data or a concise identity/location table, including empty results."""
    if output_format == "json":
        return json.dumps(rows, indent=2) + "\n"
    if output_format == "csv":
        fields = list(dict.fromkeys(key for row in rows for key in row)) or [
            "identity",
            "map_id",
            "shape",
            "shape_name",
            "frame",
            "world_x",
            "world_y",
            "world_z",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict, tuple))
                    else value
                    for key, value in row.items()
                }
            )
        return stream.getvalue()
    if output_format != "table":
        raise ValueError("U8 world search: format must be table, csv or json")
    return (
        "\n".join(
            [
                f"U8 search: {len(rows):,} results",
                "Identity | Map | Shape/frame | Name | World X,Y,Z | Trigger",
            ]
            + [
                f"{row['identity']} | {row['map_id']} | {row['shape']}/{row['frame']} | {row.get('npc_label') or row['shape_name']} | {row['world_x']},{row['world_y']},{row['world_z']} | {row.get('trigger_kind', '')}"
                for row in rows
            ]
        )
        + "\n"
    )


def export_u8_world_search_bundle(
    session: U8WorldSearchSession,
    rows: list[dict[str, Any]],
    output: Path,
    *,
    filters: U8WorldSearchFilters,
    eggs: bool = False,
    egg_filters: dict[str, Any] | None = None,
) -> Path:
    """Create a new offline paged report with complete CSV/JSON and up to 64 native sprite previews."""
    validate_u8_map_output(session.maps, output)
    if output.exists():
        raise ValueError("U8 world search: report destination must be a new directory")
    title = "U8 egg / trigger search" if eggs else "U8 world search"
    report: dict[str, Any] = {
        "title": title,
        "coverage": session.coverage,
        "filters": asdict(filters),
        "egg_filters": egg_filters,
        "diagnostics": session.diagnostics,
        "sources": [
            str(path)
            for path in dict.fromkeys(
                session.maps.sources
                + (session.inventory.sources if session.inventory else ())
            )
        ],
        "result_count": len(rows),
        "items": rows,
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "images").mkdir()
    previews: dict[tuple[int, int, bool], str] = {}
    for row in rows:
        key = (row["shape"], row["frame"], bool(row["status"] & 0x20))
        if key in previews or len(previews) >= 64:
            continue
        try:
            image = session.maps.library.image(key[0], key[1])
            if key[2]:
                from PIL import Image

                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            filename = f"images/s{key[0]:04d}_f{key[1]:04d}_{int(key[2])}.png"
            with (output / filename).open("xb") as stream:
                image.save(stream, format="PNG")
            previews[key] = filename
        except (ValueError, IndexError) as error:
            report["diagnostics"] = [*report["diagnostics"], f"Sprite {key}: {error}"]
    report["sprite_preview_count"] = len(previews)
    for filename, text in (
        ("results.csv", format_u8_world_search_results(rows, "csv")),
        ("report.json", json.dumps(report, indent=2) + "\n"),
    ):
        with (output / filename).open("x", encoding="utf-8", newline="") as stream:
            stream.write(text)
    columns = [
        "identity",
        "map_id",
        "shape",
        "frame",
        "shape_name",
        "npc_label",
        "owner_name",
        "world_x",
        "world_y",
        "world_z",
        "location_kind",
    ]
    if eggs:
        columns += [
            "trigger_kind",
            "usecode_class",
            "usecode_name",
            "range_x_units",
            "range_y_units",
            "destination_map",
            "destination_id",
            "monster_shape",
            "monster_count",
            "probability_percent",
        ]
    compact = [
        {
            **{key: row.get(key) for key in columns},
            "image": previews.get(
                (row["shape"], row["frame"], bool(row["status"] & 0x20))
            ),
            "diagnostics": row["diagnostics"],
        }
        for row in rows
    ]
    embedded = json.dumps(compact, ensure_ascii=True).replace("<", "\\u003c")
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>
<style>body{{background:#202124;color:#eee;font:15px system-ui;margin:2em}}a{{color:#9dd5ff}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.4em;border-bottom:1px solid #555;text-align:left}}img{{image-rendering:pixelated;max-width:128px}}pre{{white-space:pre-wrap}}button,input,select{{font:inherit;margin:.4em}}.table{{overflow:auto}}</style>
<h1>{title}</h1><p>{len(rows):,} results. <a href="results.csv">Complete CSV</a> · <a href="report.json">Complete JSON</a></p>
<p>Search and map selection below filter this exported result set. Native sprite previews cover the first 64 distinct shape/frame/flip combinations. World coordinates of contained items refer to their top-level owner. Trigger definitions do not establish whether an egg has already fired.</p>
<input id="search" placeholder="Search exported results" aria-label="Search exported results"><select id="map" aria-label="Map"><option value="">All maps</option></select><button id="previous">Previous</button><button id="next">Next</button><span id="count"></span>
<div class="table"><table><thead><tr><th>Sprite</th>{"".join(f"<th>{html.escape(key)}</th>" for key in columns)}</tr></thead><tbody id="rows"></tbody></table></div>
<h2>Coverage and filters</h2><pre>{html.escape(json.dumps({"coverage": session.coverage, "filters": asdict(filters), "egg_filters": egg_filters}, indent=2))}</pre>
<h2>Diagnostics</h2><pre>{html.escape(chr(10).join(report["diagnostics"]))}</pre>
<script id="data" type="application/json">{embedded}</script>
<script>const data=JSON.parse(document.getElementById('data').textContent),columns={json.dumps(columns)};let page=0;const search=document.getElementById('search'),map=document.getElementById('map'),body=document.getElementById('rows');for(const id of [...new Set(data.map(r=>r.map_id).filter(x=>x!==null))].sort((a,b)=>a-b)){{let o=document.createElement('option');o.value=id;o.textContent='Map '+id;map.append(o)}}function render(){{const q=search.value.toLowerCase(),found=data.filter(r=>(!map.value||String(r.map_id)===map.value)&&JSON.stringify(r).toLowerCase().includes(q));page=Math.min(page,Math.max(0,Math.ceil(found.length/100)-1));body.replaceChildren();for(const r of found.slice(page*100,page*100+100)){{const tr=document.createElement('tr'),sprite=document.createElement('td');if(r.image){{const img=document.createElement('img');img.src=r.image;img.alt='Shape '+r.shape+' frame '+r.frame;sprite.append(img)}}tr.append(sprite);for(const key of columns){{const td=document.createElement('td');td.textContent=r[key]??'';tr.append(td)}}body.append(tr)}}document.getElementById('count').textContent=found.length+' results; page '+(page+1);document.getElementById('previous').disabled=page===0;document.getElementById('next').disabled=(page+1)*100>=found.length}}search.oninput=map.onchange=()=>{{page=0;render()}};document.getElementById('previous').onclick=()=>{{page--;render()}};document.getElementById('next').onclick=()=>{{page++;render()}};render();</script></html>"""
    with (output / "index.html").open("x", encoding="utf-8") as stream:
        stream.write(page)
    return output


def next_u8_world_search_export(output: Path, *, eggs: bool = False) -> Path:
    """Choose a fresh report folder so earlier search exports remain untouched."""
    return next_u8_save_browser_export(output, "eggs" if eggs else "world")
