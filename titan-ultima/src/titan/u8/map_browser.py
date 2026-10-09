"""Captured U8 FIXED/NONFIXED maps, container records and exclusive map exports.

Record identities are (archive_kind, map_id, record_index), never cached item
IDs. NPCs are joined from the captured NPCDATA/ITEMCACH slots, not npc_num:
native eggs also use that byte for their hatch range.
"""

from __future__ import annotations

import csv
import html
import io
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from titan.flex import FlexArchive
from titan.u8.map import U8MapRenderer, U8MapSampler
from titan.u8.map_item_report import format_u8_map_item_report
from titan.u8.map_items import U8MapItem, U8MapItems
from titan.u8.npc_browser import U8NpcSession, filter_u8_npcs
from titan.u8.npc_names import describe_u8_npc_identity, load_u8_npc_labels
from titan.u8.npc_source import U8NpcSource
from titan.u8.save_browser import (
    next_u8_save_browser_export,
    validate_u8_save_browser_output,
)
from titan.u8.save_state import U8SaveSnapshot, format_u8_save_info
from titan.u8.shape_browser import U8ShapeLibrary, find_u8_browser_file
from titan.u8.state_report import format_u8_npcdata_report

U8_MAP_BROWSER_OUTPUT = Path("titan-out/u8_map_browse_export")


@dataclass(frozen=True)
class U8MapBrowserFilters:
    """Height/roof filters apply to world placements, including expanded GLOBs."""

    storage: str = "both"
    scope: str = "all"
    query: str = ""
    shape: int | None = None
    min_z: int = 0
    max_z: int = 250
    hide_roofs: bool = False
    hide_editor: bool = True

    def __post_init__(self) -> None:
        if self.storage not in {"both", "fixed", "nonfixed"}:
            raise ValueError("U8 map browser: unknown storage filter")
        if self.scope not in {"all", "world", "contained", "diagnostics"}:
            raise ValueError("U8 map browser: unknown record scope")
        if not 0 <= self.min_z <= self.max_z <= 250:
            raise ValueError("U8 map browser: height range must be within 0-250")
        if self.shape is not None and not 0 <= self.shape < 2048:
            raise ValueError("U8 map browser: shape must be within 0-2047")


@dataclass
class U8MapBrowserSession:
    """One graphics owner and captured static/save bytes; rendering never rereads saves."""

    library: U8ShapeLibrary
    fixed: U8MapItems
    fixed_path: Path
    nonfixed: U8MapItems | None
    snapshot: U8SaveSnapshot | None
    globs: dict[int, bytes]
    glob_path: Path | None
    typeflag: bytes | None
    npc_session: U8NpcSession | None
    extra_sources: tuple[Path, ...] = ()

    @property
    def sources(self) -> tuple[Path, ...]:
        return (
            (self.fixed_path,)
            + self.library.source_paths
            + ((self.glob_path,) if self.glob_path else ())
            + (self.snapshot.source_files if self.snapshot else ())
            + self.extra_sources
            + (self.npc_session.source_files if self.npc_session else ())
        )

    @property
    def map_ids(self) -> list[int]:
        return [
            number
            for number in range(256)
            if self.fixed.get_map(number)
            or (self.nonfixed is not None and self.nonfixed.get_map(number))
        ]

    def records(self, map_id: int) -> tuple[U8MapItem, ...]:
        """Keep both archive identities and all raw records, including slot zero."""
        return self.fixed.get_map(map_id) + (
            self.nonfixed.get_map(map_id) if self.nonfixed else ()
        )


def load_u8_map_session(
    library: U8ShapeLibrary,
    *,
    source: Path | None = None,
    snapshot: U8SaveSnapshot | None = None,
    fixed: Path | None = None,
    globs: Path | None = None,
    names: Path | None = None,
) -> U8MapBrowserSession:
    """Load a matching STATIC owner plus an optional native save, directory or loose DAT."""
    if not library.world_shapes:
        raise ValueError("U8 map browser: select U8SHAPES.FLX world graphics")
    fixed_path = fixed or find_u8_browser_file(library.path.parent, "FIXED.DAT")
    if fixed_path is None:
        raise ValueError("U8 map browser: FIXED.DAT is missing; specify --fixed")
    fixed_data = U8MapItems.from_file(fixed_path, kind="fixed")
    if source is not None and snapshot is not None:
        raise ValueError(
            "U8 map browser: specify a source or captured snapshot, not both"
        )
    nonfixed = None
    extra_sources: tuple[Path, ...] = ()
    if source:
        if source.is_file() and source.name.casefold() == "nonfixed.dat":
            nonfixed = U8MapItems.from_file(source, kind="nonfixed")
            extra_sources = (source,)
        else:
            snapshot = U8SaveSnapshot.from_path(source)
            if "NONFIXED.DAT" in snapshot.decode_errors:
                raise ValueError(snapshot.decode_errors["NONFIXED.DAT"])
            if snapshot.nonfixed is None:
                raise ValueError("U8 map browser: snapshot has no NONFIXED.DAT")
            nonfixed = snapshot.nonfixed
    elif snapshot is not None:
        if "NONFIXED.DAT" in snapshot.decode_errors:
            raise ValueError(snapshot.decode_errors["NONFIXED.DAT"])
        if snapshot.nonfixed is None:
            raise ValueError("U8 map browser: snapshot has no NONFIXED.DAT")
        nonfixed = snapshot.nonfixed
    glob_path = globs or find_u8_browser_file(library.path.parent, "GLOB.FLX")
    glob_records = (
        {
            number: raw
            for number, raw in enumerate(
                FlexArchive.from_file(str(glob_path), strict=True).records
            )
            if raw
        }
        if glob_path
        else {}
    )
    typeflag_path = find_u8_browser_file(library.path.parent, "TYPEFLAG.DAT")
    typeflag = typeflag_path.read_bytes() if typeflag_path else None
    if typeflag_path:
        extra_sources += (typeflag_path,)
    npc_session = None
    if snapshot and snapshot.npc_data is not None and snapshot.item_cache is not None:
        labels = load_u8_npc_labels(names) if names else {}
        states = json.loads(
            format_u8_npcdata_report(
                snapshot.npc_data,
                item_cache=snapshot.item_cache,
                all_slots=True,
                output_format="json",
            )
        )["npcs"]
        for state in states:
            state.update(
                describe_u8_npc_identity(state, labels=labels, avatar=snapshot.avatar)
            )
            state["class_label"] = library.names.get(state["item_shape"], "")
        npc_source = U8NpcSource(
            snapshot.source,
            snapshot.npc_data,
            snapshot.item_cache,
            snapshot.source_files,
            snapshot.avatar,
        )
        npc_session = U8NpcSession(
            npc_source,
            library,
            states,
            labels,
            names,
            format_u8_save_info(snapshot),
            snapshot,
        )
    elif names:
        # Validate an explicit override even when this snapshot has no NPC state.
        load_u8_npc_labels(names)
        extra_sources += (names,)
    return U8MapBrowserSession(
        library,
        fixed_data,
        fixed_path,
        nonfixed,
        snapshot,
        glob_records,
        glob_path,
        typeflag,
        npc_session,
        extra_sources,
    )


def describe_u8_map_rows(
    session: U8MapBrowserSession, map_id: int
) -> list[dict[str, Any]]:
    """Reuse verified native report columns and add a shape label, without guessing NPC IDs."""
    rows = []
    for data in (session.fixed, session.nonfixed):
        if data is None:
            continue
        report = json.loads(
            format_u8_map_item_report(
                data,
                map_id=map_id,
                view="items",
                output_format="json",
                typeflag_data=session.typeflag if session.library.properties else None,
            )
        )
        for row in report["items"]:
            row["shape_name"] = session.library.names.get(row["shape"], "")
            rows.append(row)
    return rows


def filter_u8_map_rows(
    session: U8MapBrowserSession,
    rows: list[dict[str, Any]],
    filters: U8MapBrowserFilters,
) -> list[dict[str, Any]]:
    """Search raw record fields; container inventory coordinates are never world heights."""
    result = []
    for row in rows:
        if filters.storage != "both" and row["archive_kind"] != filters.storage:
            continue
        location = row["location_kind"]
        if filters.scope == "world" and location != "world_stored":
            continue
        if filters.scope == "contained" and location != "contained":
            continue
        if filters.scope == "diagnostics" and not row["diagnostics"]:
            continue
        if filters.shape is not None and row["shape"] != filters.shape:
            continue
        if location == "world_stored":
            if not filters.min_z <= row["z"] <= filters.max_z:
                continue
            properties = session.library.properties.get(row["shape"])
            if filters.hide_roofs and properties and properties.flags & 0x0400:
                continue
        if (
            filters.query.strip()
            and filters.query.strip().casefold()
            not in " ".join(
                str(value) for key, value in row.items() if key != "raw_hex"
            ).casefold()
        ):
            continue
        result.append(row)
    return result


def describe_u8_map_summary(
    session: U8MapBrowserSession, map_id: int
) -> dict[str, Any]:
    """Count native records separately from disposable objects expanded from GLOB stamps."""
    records = session.records(map_id)
    return {
        "map_id": map_id,
        "storage_kind": "npc_registry" if map_id == 0 else "world_map",
        "fixed_records": len(session.fixed.get_map(map_id)),
        "nonfixed_records": len(session.nonfixed.get_map(map_id))
        if session.nonfixed
        else 0,
        "world_records": sum(item.is_world_object for item in records),
        "contained_records": sum(item.contained for item in records),
        "glob_records": sum(
            item.is_world_object and item.shape == 2 for item in records
        ),
        "diagnostic_records": sum(bool(item.diagnostics) for item in records),
        "allocated_npcs": len(map_npc_rows(session, map_id)),
    }


def map_npc_rows(session: U8MapBrowserSession, map_id: int) -> list[dict[str, Any]]:
    """Return allocated captured cache/NPC slots on this map, independent of disk record IDs."""
    return (
        filter_u8_npcs(session.npc_session.states, map_num=map_id)
        if session.npc_session
        else []
    )


def u8_map_container_children(
    session: U8MapBrowserSession,
    item: U8MapItem,
) -> tuple[U8MapItem, ...]:
    """Resolve immediate inventory children only within their original archive/map."""
    return tuple(
        candidate
        for candidate in session.records(item.map_id)
        if candidate.archive_kind == item.archive_kind
        and candidate.parent_record_index == item.record_index
    )


def render_u8_browser_map(
    session: U8MapBrowserSession,
    map_id: int,
    *,
    filters: U8MapBrowserFilters = U8MapBrowserFilters(),
    view: str = "sample",
    scale: int = 64,
    grid: bool = False,
) -> tuple[Image.Image, dict[str, Any]]:
    """Expand GLOBs before roof/height filtering and render with native sprite resolution."""
    if view != "sample" and view not in U8MapRenderer.PROJECTIONS:
        raise ValueError("U8 map browser: unknown projection")
    if not 1 <= scale <= 4096:
        raise ValueError("U8 map browser: sample scale must be 1-4096")
    # Query/shape/scope concern raw records; the image always shows world objects.
    wanted = {
        (row["archive_kind"], row["record_index"])
        for row in filter_u8_map_rows(
            session, describe_u8_map_rows(session, map_id), filters
        )
    }
    objects = [
        U8MapRenderer.MapObject(
            item.x,
            item.y,
            item.z,
            item.shape,
            item.frame,
            quality=item.quality,
            status=item.status,
            source_record=item,
        )
        for item in session.records(map_id)
        if item.is_world_object and (item.archive_kind, item.record_index) in wanted
    ]
    # Do not prefilter a stamp by height/roof: its individual children can differ.
    if (
        filters.scope in {"all", "world"}
        and filters.shape is None
        and not filters.query.strip()
    ):
        for item in session.records(map_id):
            if (
                item.is_world_object
                and item.shape == 2
                and filters.storage in {"both", item.archive_kind}
                and (item.archive_kind, item.record_index) not in wanted
            ):
                objects.append(
                    U8MapRenderer.MapObject(
                        item.x,
                        item.y,
                        item.z,
                        item.shape,
                        item.frame,
                        quality=item.quality,
                        status=item.status,
                        source_record=item,
                    )
                )
    issues = []
    expanded = []
    for obj in objects:
        if obj.type_num != 2:
            expanded.append(obj)
            continue
        raw = session.globs.get(obj.quality)
        if raw is None:
            issues.append(f"Missing GLOB {obj.quality} for {obj.source_record}")
            continue
        if len(raw) < 2 or len(raw) != 2 + int.from_bytes(raw[:2], "little") * 6:
            issues.append(f"Malformed GLOB {obj.quality}; not expanded")
            continue
        for sub in U8MapRenderer.load_glob(raw):
            expanded.append(
                U8MapRenderer.MapObject(
                    sub.x * 2 + (obj.x & ~511),
                    sub.y * 2 + (obj.y & ~511),
                    sub.z + obj.z,
                    sub.type_num,
                    sub.frame,
                    status=0x0082,
                    source_record=obj.source_record,
                )
            )
    visible = []
    for obj in expanded:
        properties = session.library.properties.get(obj.type_num)
        if filters.hide_editor and properties and properties.flags & 0x1000:
            continue
        if not filters.min_z <= obj.z <= filters.max_z:
            continue
        if filters.hide_roofs and properties and properties.flags & 0x0400:
            continue
        try:
            shape = session.library.shape(obj.type_num)
            if not 0 <= obj.frame < len(shape.frames):
                raise ValueError(f"frame {obj.frame} outside shape {obj.type_num}")
        except ValueError as error:
            issues.append(str(error))
            continue
        visible.append(obj)
    if filters.hide_roofs and not session.library.properties:
        raise ValueError(
            "U8 map browser: roof filtering requires matching TYPEFLAG.DAT"
        )
    if filters.hide_editor and not session.library.properties:
        issues.append(
            "TYPEFLAG unavailable; editor marker filtering could not be applied"
        )
    if view == "sample" and visible:
        pixels = (max(obj.x for obj in visible) // scale + 2) * (
            max(obj.y for obj in visible) // scale + 2
        )
        if pixels > 64_000_000:
            raise ValueError("U8 map browser: sample is too large; increase scale")
    with tempfile.TemporaryDirectory(prefix="titan-u8-map-assets-") as temporary:
        directory = Path(temporary)
        for number in {obj.type_num for obj in visible}:
            (directory / f"{number:04d}.shp").write_bytes(
                session.library.records[number]
            )
        typeflag_path = None
        if session.typeflag:
            typeflag_file = directory / "TYPEFLAG.DAT"
            typeflag_file.write_bytes(session.typeflag)
            typeflag_path = str(typeflag_file)
        if view == "sample":
            image = U8MapSampler.sample_map(
                visible, str(directory), session.library.palette, scale=scale, grid=grid
            )
        else:
            image = U8MapRenderer.render_map(
                visible,
                str(directory),
                session.library.palette,
                view=view,
                grid=grid,
                typeflag_path=typeflag_path,
            )
    return image, {
        "view": view,
        "scale": scale if view == "sample" else None,
        "grid": grid,
        "width": image.width,
        "height": image.height,
        "expanded_objects": len(expanded),
        "visible_objects": len(visible),
        "diagnostics": sorted(set(issues)),
    }


def validate_u8_map_output(session: U8MapBrowserSession, output: Path) -> None:
    """Preserve source STATIC/GAMEDAT directories and all captured inputs."""
    target = output.resolve()
    owner = session.library.path.parent.resolve()
    if (
        target == owner
        or owner in target.parents
        or target in {path.resolve() for path in session.sources}
    ):
        raise ValueError("U8 map browser: export outside source STATIC and input files")
    if session.snapshot:
        validate_u8_save_browser_output(session.snapshot, output, session.sources)
    for path in session.extra_sources:
        if path.name.casefold() == "nonfixed.dat" and (
            target == path.parent.resolve() or path.parent.resolve() in target.parents
        ):
            raise ValueError("U8 map browser: export outside source NONFIXED directory")


def format_u8_map_csv(rows: list[dict[str, Any]]) -> str:
    """Encode nested status/diagnostic fields as JSON in CSV cells, including empty results."""
    fields = (
        list(rows[0])
        if rows
        else [
            "archive_kind",
            "map_id",
            "record_index",
            "shape",
            "shape_name",
            "frame",
            "x",
            "y",
            "z",
        ]
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value)
                if isinstance(value, (list, tuple, dict))
                else value
                for key, value in row.items()
            }
        )
    return stream.getvalue()


def export_u8_map_bundle(
    session: U8MapBrowserSession,
    map_id: int,
    output: Path,
    *,
    filters: U8MapBrowserFilters = U8MapBrowserFilters(),
    view: str = "iso_classic",
    scale: int = 64,
    grid: bool = False,
) -> Path:
    """Write a fresh offline map report, two PNGs and native record CSV/JSON; never overwrite."""
    validate_u8_map_output(session, output)
    if output.exists():
        raise ValueError("U8 map browser: report destination must be a new directory")
    rows = filter_u8_map_rows(session, describe_u8_map_rows(session, map_id), filters)
    sample, sample_info = render_u8_browser_map(
        session, map_id, filters=filters, scale=scale, grid=grid
    )
    iso, iso_info = render_u8_browser_map(
        session, map_id, filters=filters, view=view, scale=scale, grid=grid
    )
    summary = describe_u8_map_summary(session, map_id)
    npc_rows = map_npc_rows(session, map_id)
    report: dict[str, Any] = {
        "summary": summary,
        "filters": asdict(filters),
        "selected_records": len(rows),
        "sources": [str(path) for path in dict.fromkeys(session.sources)],
        "snapshot": str(session.snapshot.source) if session.snapshot else None,
        "rendering": {"sample": sample_info, "isometric": iso_info},
        "items": rows,
        "npcs": npc_rows,
        "record_identity": "archive_kind + map_id + record_index; not a cached item ID",
        "npc_identity": "captured allocated NPC slots on this map; npc_num also has non-NPC meanings",
    }
    output.mkdir(parents=True)
    for filename, value in (
        ("objects.csv", format_u8_map_csv(rows)),
        ("report.json", json.dumps(report, indent=2) + "\n"),
    ):
        with (output / filename).open("x", encoding="utf-8", newline="") as stream:
            stream.write(value)
    for filename, image in (("overview.png", sample), ("isometric.png", iso)):
        with (output / filename).open("xb") as stream:
            image.save(stream, format="PNG")
    npc_html = "".join(
        f"<tr><td>{row['npc_id']}</td><td>{html.escape(row['npc_label'])}</td><td>{row['item_shape']}</td><td>{row['item_x']}, {row['item_y']}, {row['item_z']}</td></tr>"
        for row in npc_rows
    )
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>U8 map {map_id:03d}</title><style>body{{background:#202124;color:#eee;font:16px sans-serif;margin:2em}}a{{color:#9dd5ff}}img{{max-width:100%;image-rendering:pixelated}}pre{{white-space:pre-wrap}}td,th{{padding:.4em;text-align:left}}.iso{{overflow:auto}}.iso img{{max-width:none}}</style>
<h1>U8 map {map_id:03d}</h1><p>FIXED {summary["fixed_records"]:,}; NONFIXED {summary["nonfixed_records"]:,}; contained {summary["contained_records"]:,}; selected records {len(rows):,}.</p>
<p><a href="objects.csv">Object CSV</a> · <a href="report.json">Full JSON report</a> · <a href="isometric.png">Native isometric PNG</a></p>
<h2>Filters</h2><pre>{html.escape(json.dumps(asdict(filters), indent=2))}</pre>
<h2>Top-down colour overview</h2><img src="overview.png" alt="Colour-sampled top-down overview">
<h2>Isometric view ({html.escape(view)})</h2><div class="iso"><img src="isometric.png" alt="Isometric map at native sprite resolution"></div>
<h2>Rendering diagnostics</h2><pre>{html.escape(json.dumps(report["rendering"], indent=2))}</pre>
<h2>Captured NPCs on this map</h2><table><tr><th>NPC slot</th><th>Name / slot label</th><th>Shape</th><th>X, Y, Z</th></tr>{npc_html}</table>
<p>Map record indices are local to each archive/map. They are not cache item IDs. NPC names come from captured NPC slots; map npc_num bytes are not used as identities. Images use stored FIXED/NONFIXED records; active ITEMCACH regions are not merged into the image. The overview samples sprite colours; the isometric PNG retains native pixels. These are static data views, without lighting, animation or usecode execution.</p>
<h2>Sources</h2><pre>{html.escape(chr(10).join(report["sources"]))}</pre></html>"""
    with (output / "index.html").open("x", encoding="utf-8") as stream:
        stream.write(page)
    return output


def next_u8_map_export(output: Path, map_id: int) -> Path:
    """Choose a fresh per-map report folder; the exporter still creates it exclusively."""
    return next_u8_save_browser_export(output, f"map_{map_id:03d}_report")
