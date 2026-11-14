"""``titan uo house-*`` — house footprint and placement capacity commands."""

from __future__ import annotations

__all__ = ["house_footprints_cmd", "house_capacity_cmd"]

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import numpy as np
import typer
from PIL import Image

from titan._config import get_config
from titan.uo.housing import (
    footprint_sheet,
    house_footprint,
    parse_house_placement_tool,
)
from titan.uo.installs import resolve_install
from titan.uo.localization import UOCliloc
from titan.uo.map import UOMap
from titan.uo.multi import UOMultis
from titan.uo.tiles import FACET_NAMES
from titan.uo.capacity_viewer import write_capacity_viewer
from titan.uo.server_profile import ServerProfile, builtin_house_entries
from titan.uo.mixed_packing import (
    CLASSES,
    HouseKind,
    MixedSettings,
    class_for,
    pack_mixed,
    zone_distances,
)
from titan.uo.placement import (
    coverage,
    _parse_region_rects,
    build_placement_grids,
    evaluate_placement,
    legal_centres,
    no_housing_region_types,
    region_layers_from_rects,
    region_outlines_from_rects,
    pack_houses,
)
from titan.uo.cli import _common


def _try_load_cliloc(client: Path, language: str) -> UOCliloc | None:
    try:
        return _common._load_cliloc(client, language)
    except FileNotFoundError:
        return None


def _reference(args: SimpleNamespace) -> dict[str, str]:
    """[uo.reference] settings, overridden by the install's own references."""
    merged = dict(get_config().get("uo", {}).get("reference", {}))
    try:
        install = resolve_install(getattr(args, "client", None))[1]
    except FileNotFoundError:
        install = None
    if install is not None and install.reference:
        merged.update(install.reference)
    return merged


_REGION_FACETS = {
    0: "Felucca",
    1: "Trammel",
    2: "Ilshenar",
    3: "Malas",
    4: "Tokuno",
    5: "TerMur",
}


@dataclass
class _ServerData:
    """Where house menu and region rules come from for one command run."""

    entries: list
    entries_source: str
    region_rects: list | None
    regions_source: str
    identity: str


def _server_data(
    args: SimpleNamespace, multis, tiledata, facet_number: int
) -> _ServerData:
    """Resolve the house menu and region rules.

    Precedence: explicit ``--placement-source``/``--regions`` flags, then a
    server profile (``--server-profile``, the install's ``server_profile`` or
    ``[uo.reference] server_profile``), then the older ``[uo.reference]``
    file settings, then Titan's built-in house list with no regions.
    """
    reference = _reference(args)
    profile_path = getattr(args, "server_profile", None) or reference.get(
        "server_profile"
    )
    profile = ServerProfile.load(profile_path) if profile_path else None
    facet_name = _REGION_FACETS.get(facet_number, str(facet_number))

    placement = getattr(args, "placement_source", None)
    if placement:
        entries, entries_source = parse_house_placement_tool(placement), str(placement)
    elif profile is not None:
        entries, entries_source = profile.houses, f"server profile {profile.path}"
    elif reference.get("house_placement_tool"):
        placement = reference["house_placement_tool"]
        entries, entries_source = parse_house_placement_tool(placement), str(placement)
    else:
        entries = builtin_house_entries(multis, tiledata)
        entries_source = "built-in house list (no server data)"

    regions_xml = getattr(args, "regions", None)
    scripts = getattr(args, "region_scripts", None)
    if regions_xml:
        forbidding = no_housing_region_types(scripts) if scripts else None
        rects, _ = _parse_region_rects(regions_xml, facet_name, forbidding)
        regions_source = f"{regions_xml} (rules: {scripts or 'built-in RunUO list'})"
        identity = f"{_file_identity(regions_xml)}|{sorted(forbidding) if forbidding else 'runuo'}"
    elif profile is not None:
        rects = profile.region_rects(facet_name)
        regions_source = f"server profile {profile.path}"
        identity = _file_identity(profile.path)
    elif reference.get("regions_xml"):
        regions_xml = reference["regions_xml"]
        scripts = reference.get("emulator_scripts")
        forbidding = no_housing_region_types(scripts) if scripts else None
        rects, _ = _parse_region_rects(regions_xml, facet_name, forbidding)
        regions_source = f"{regions_xml} (rules: {scripts or 'built-in RunUO list'})"
        identity = f"{_file_identity(regions_xml)}|{sorted(forbidding) if forbidding else 'runuo'}"
    else:
        rects, regions_source, identity = None, "none", "no-regions"
    if rects is None and regions_source != "none":
        regions_source += f" (no {facet_name} section)"
    return _ServerData(entries, entries_source, rects, regions_source, identity)


def cmd_house_footprints(args: SimpleNamespace) -> int:
    """Export house placement footprints: emulator house table joined to client multis."""
    try:
        client = _common._client_path(args.client)
        multis = UOMultis.from_client(client, container=_common._source(args, "multis"))
        tiledata = _common._load_tiledata(client)
        cliloc = _try_load_cliloc(client, "enu")
        server = _server_data(args, multis, tiledata, 0)
        entries, source = server.entries, server.entries_source
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "housing"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    cells: dict[str, dict[str, object]] = {}
    missing = 0
    sheet_items = []
    for entry in entries:
        multi = multis.multis.get(entry.multi_id)
        footprint = house_footprint(multi, tiledata) if multi is not None else None
        name = (
            cliloc.entries[entry.cliloc].text
            if cliloc and entry.cliloc in cliloc.entries
            else ""
        )
        row: dict[str, object] = {
            "category": entry.category,
            "type": entry.type_name,
            "cliloc": entry.cliloc,
            "name": name,
            "multi_id": f"0x{entry.multi_id:04X}",
            "in_client": footprint is not None,
            "cost": entry.cost,
            "storage": entry.storage,
            "lockdowns": entry.lockdowns,
            "vendors": entry.vendors,
            "offset_x": entry.offset[0],
            "offset_y": entry.offset[1],
            "offset_z": entry.offset[2],
        }
        if footprint is None:
            missing += 1
        else:
            for label, part in (
                ("occupied", footprint.occupied),
                ("foundation", footprint.foundation),
                ("border", footprint.border),
                ("yard", footprint.yard),
            ):
                min_x, max_x, min_y, max_y = footprint.extent(part)
                row[f"{label}_cells"] = len(part)
                row[f"{label}_min_x"], row[f"{label}_max_x"] = min_x, max_x
                row[f"{label}_min_y"], row[f"{label}_max_y"] = min_y, max_y
            min_x, max_x, min_y, max_y = footprint.extent(footprint.occupied)
            row["width"], row["height"] = max_x - min_x + 1, max_y - min_y + 1
            row["stairs_added"] = footprint.stairs_added
            sheet_items.append((entry, name, footprint))
            cells[row["multi_id"]] = {
                key: sorted(getattr(footprint, key))
                for key in ("occupied", "foundation", "border", "yard")
            }
        rows.append(row)

    _common._write_manifest(outdir / "house_footprints.csv", rows)
    if sheet_items:
        install = resolve_install(args.client)[1]
        label = install.label or install.name if install else str(client)
        footprint_sheet(
            sheet_items,
            scale=args.scale,
            title=f"House footprints: {label} ({multis.source}), {Path(str(source)).name}",
        ).save(outdir / "house_footprints.png")
    meta = {
        "placement_source": str(source),
        "client": str(client),
        "multis": {"source": multis.source, "layout": multis.layout},
        "entries": len(entries),
        "missing_in_client": missing,
        "coordinates": "cells relative to the house centre; centre = cursor - offset",
        "footprints": cells,
    }
    (outdir / "house_footprints.json").write_text(json.dumps(meta), encoding="utf-8")
    print(
        f"Exported {len(rows)} house footprint(s) ({missing} not in the client's "
        f"{multis.source}) -> {outdir}"
    )
    return 0


_WORKSHOP_IDS = frozenset(
    (0x00A0, 0x00A2)
)  # small stone / marble workshop: the "forges"


def _mixed_house_kinds(entries, multis, tiledata, cliloc, settings):
    """Classic houses plus one square customizable plot per size, classified."""
    kinds = []
    plot_sizes = set()
    for entry in entries:
        multi = multis.multis.get(entry.multi_id)
        if multi is None:
            continue
        label = (
            cliloc.entries[entry.cliloc].text
            if cliloc and entry.cliloc in cliloc.entries
            else entry.type_name
        )
        if entry.category == "ClassicHouses":
            pass
        elif entry.category.endswith("Foundations"):
            size = re.match(r"(\d+)x(\d+)", label)
            if (
                not size
                or size.group(1) != size.group(2)
                or size.group(1) in plot_sizes
            ):
                continue
            plot_sizes.add(size.group(1))
        else:
            continue
        footprint = house_footprint(multi, tiledata)
        kinds.append(
            HouseKind(
                entry.multi_id,
                label,
                class_for(
                    len(footprint.occupied), settings, entry.multi_id in _WORKSHOP_IDS
                ),
                footprint,
            )
        )
    return kinds


def _file_identity(path) -> str:
    stat = Path(path).stat()
    return f"{Path(path).resolve()}|{stat.st_size}|{stat.st_mtime_ns}"


def _legal_cache_key(base_key: str, multi) -> str:
    components = sorted((c.item_id, c.x, c.y, c.z, c.flags) for c in multi.components)
    return hashlib.sha1(
        f"{base_key}|{multi.multi_id}|{components}".encode()
    ).hexdigest()[:20]


def _run_mixed_packing(
    *,
    grids,
    kinds,
    multis,
    tiledata,
    window,
    outlines,
    land_ids,
    settings,
    outdir,
    cache_key,
):
    """Legal centres per kind (cached on disk), zone distances, and the mixed packing.

    ``cache_key`` identifies everything legality depends on besides the house
    itself: map files, tiledata, window, regions and region rules. Cached
    legal centres live in ``outdir/cache`` and are reused only on an exact
    key match.
    """
    x0, y0, x1, y1 = window
    cache_dir = outdir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    centres = []
    for kind in kinds:
        multi = multis.multis[kind.multi_id]
        path = (
            cache_dir
            / f"legal_{kind.multi_id:04X}_{_legal_cache_key(cache_key, multi)}.npz"
        )
        if path.is_file():
            with np.load(path) as cached:
                rows, cols = (
                    cached["rows"].astype(np.int64),
                    cached["cols"].astype(np.int64),
                )
            print(
                f"  mixed: legal centres for 0x{kind.multi_id:04X} {kind.label} (cached)"
            )
        else:
            print(
                f"  mixed: legal centres for 0x{kind.multi_id:04X} {kind.label} ({kind.house_class})..."
            )
            rows, cols = legal_centres(grids, multi, tiledata)
            np.savez_compressed(
                path, rows=rows.astype(np.int32), cols=cols.astype(np.int32)
            )
        centres.append((rows, cols))

    town = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    for region in outlines or []:
        if "Town" not in str(region["type"]) and region["type"] != "NewMaginciaRegion":
            continue
        rx0, ry0 = max(region["x"] - x0, 0), max(region["y"] - y0, 0)
        rx1 = min(region["x"] + region["w"] - x0, x1 - x0)
        ry1 = min(region["y"] + region["h"] - y0, y1 - y0)
        if rx0 < rx1 and ry0 < ry1:
            town[ry0:ry1, rx0:rx1] = True
    rock_ids = np.array([t.name.lower() == "rock" for t in tiledata.land[:0x4000]])
    rock = rock_ids[land_ids[y0:y1, x0:x1] & 0x3FFF]
    town_distance, rock_distance = zone_distances(town.shape, town, rock, settings)
    packing = pack_mixed(window, kinds, centres, town_distance, rock_distance, settings)

    _common._write_manifest(
        outdir / "mixed_packed.csv",
        [
            {
                "x": x,
                "y": y,
                "multi_id": f"0x{kinds[k].multi_id:04X}",
                "class": kinds[k].house_class,
                "name": kinds[k].label,
            }
            for x, y, k in packing.placed
        ],
    )
    per_kind: dict[str, int] = {}
    for _x, _y, k in packing.placed:
        per_kind[kinds[k].label] = per_kind.get(kinds[k].label, 0) + 1
    summary = {
        "houses_placed": len(packing.placed),
        "by_class": packing.counts,
        "by_house": dict(sorted(per_kind.items(), key=lambda item: -item[1])),
        "zones_by_class": {
            name: int((packing.zone_classes == index).sum())
            for index, name in enumerate(CLASSES)
        },
        "kinds": [
            {
                "multi_id": f"0x{k.multi_id:04X}",
                "name": k.label,
                "class": k.house_class,
                "tiles": k.tiles,
                "legal_centres": int(len(c[0])),
            }
            for k, c in zip(kinds, centres)
        ],
        "settings": {
            key: getattr(settings, key) for key in settings.__dataclass_fields__
        },
    }
    return packing, summary


def cmd_house_capacity(args: SimpleNamespace) -> int:
    """Simulate legal house placement over a facet and pack houses greedily."""
    try:
        client = _common._client_path(args.client)
        tiledata = _common._load_tiledata(client)
        multis = UOMultis.from_client(client, container=_common._source(args, "multis"))
        facet = UOMap.from_client(
            client, args.facet, container=_common._source(args, "maps"), mapped=True
        )
        server = _server_data(args, multis, tiledata, args.facet)
        entries = server.entries
        names = {e.multi_id: e for e in entries}
        if args.multi:
            multi_ids = [int(value, 0) for value in args.multi]
        else:
            sized = [
                (
                    len(house_footprint(multis.multis[e.multi_id], tiledata).occupied),
                    e.multi_id,
                )
                for e in entries
                if e.multi_id in multis.multis
            ]
            multi_ids = [min(sized)[1]]
        missing = [f"0x{m:X}" for m in multi_ids if m not in multis.multis]
        if missing:
            raise ValueError(f"multi(s) not in {multis.source}: {', '.join(missing)}")
        layers = None
        blocked = None
        region_counts: dict[str, int] = {}
        if server.region_rects is not None:
            layers = region_layers_from_rects(
                server.region_rects, facet.width, facet.height
            )
            ground = next(layer for layer in layers if layer.z_min <= 0 < layer.z_max)
            blocked = ground.blocked
            seen = set()
            for key, allow, _nh, *_rest, rtype in server.region_rects:
                if not allow and key not in seen:
                    seen.add(key)
                    region_counts[rtype] = region_counts.get(rtype, 0) + 1
        else:
            print(
                "WARNING: no region rules for this facet; towns, dungeons and no-housing "
                "areas are not excluded. Pass --server-profile to include them.",
                file=sys.stderr,
            )
        window = (
            _common._parse_int_list(args.window, (4,), "--window")
            if args.window
            else [
                0,
                0,
                min(facet.width, 5120) if args.facet in (0, 1) else facet.width,
                facet.height,
            ]
        )
        cliloc = _try_load_cliloc(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "housing" / "capacity" / f"map{args.facet}"
    outdir.mkdir(parents=True, exist_ok=True)
    radar = _common._load_radar(client)
    base = None
    radar_rgb = None
    viewer_houses: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "client": str(client),
        "facet": args.facet,
        "window": window,
        "regions": server.regions_source,
        "region_types_forbidding": region_counts,
        "placement_source": server.entries_source,
        "t2a_excluded": args.facet == 0,
        "houses": [],
    }
    x0, y0, x1, y1 = window
    land_ids, _land_z = facet.land_arrays()
    print(f"Preparing placement grids for {(x1 - x0) * (y1 - y0):,} centres...")
    grids = build_placement_grids(
        facet, tiledata, region_layers=layers, t2a=args.facet == 0, window=tuple(window)
    )
    impassable = np.array([bool(t.flags & 0x40) for t in tiledata.land[:0x4000]])
    passable_land = int((~impassable[land_ids[y0:y1, x0:x1] & 0x3FFF]).sum())
    summary["passable_land_cells"] = passable_land

    for multi_id in multi_ids:
        entry = names.get(multi_id)
        label = (
            cliloc.entries[entry.cliloc].text
            if entry and cliloc and entry.cliloc in cliloc.entries
            else f"multi 0x{multi_id:X}"
        )
        print(
            f"0x{multi_id:04X} {label}: checking {(x1 - x0) * (y1 - y0):,} centres..."
        )
        result = evaluate_placement(grids, multis.multis[multi_id], tiledata)
        covered = coverage(result)
        packings = {
            order: pack_houses(result, order=order) for order in ("row", "column")
        }
        best_order = max(packings, key=lambda order: len(packings[order]))
        placed = packings[best_order]
        fp = result.footprint
        fx0, fx1, fy0, fy1 = fp.extent(fp.occupied)
        house = {
            "multi_id": f"0x{multi_id:04X}",
            "name": label,
            "footprint": f"{fx1 - fx0 + 1}x{fy1 - fy0 + 1}",
            "occupied_cells": len(fp.occupied),
            "legal_centres": result.legal_count,
            "covered_cells": int(covered.sum()),
            "covered_share_of_passable_land": round(
                int(covered.sum()) / passable_land, 4
            )
            if passable_land
            else None,
            "rejected_centres_by_first_rule": result.reasons,
            "packed_houses": len(placed),
            "packed_by_order": {order: len(p) for order, p in packings.items()},
            "packed_tiles": len(placed) * len(fp.occupied),
        }
        summary["houses"].append(house)
        viewer_houses.append(
            {"label": label, "result": result, "coverage": covered, "placed": placed}
        )
        stem = f"0x{multi_id:04X}"
        _common._write_manifest(
            outdir / f"{stem}_packed.csv",
            [{"x": x, "y": y, "z": None} for x, y in placed],
        )
        if base is None:
            radar_rgb = np.asarray(facet.render_radar(radar))[y0:y1, x0:x1]
            base = radar_rgb.astype(np.float32)
            if blocked is not None:
                base[blocked[y0:y1, x0:x1]] *= 0.55
        overlay = base.copy()
        overlay[covered] = overlay[covered] * 0.4 + np.array([60, 200, 90]) * 0.6
        houses = np.zeros_like(covered)
        for x, y in placed:
            for dx, dy in fp.occupied:
                X, Y = x - x0 + dx, y - y0 + dy
                if 0 <= X < houses.shape[1] and 0 <= Y < houses.shape[0]:
                    houses[Y, X] = True
        overlay[houses] = (240, 200, 60)
        Image.fromarray(overlay.clip(0, 255).astype(np.uint8)).save(
            outdir / f"{stem}_overlay.png"
        )
        print(
            f"  legal centres {result.legal_count:,}; covered cells {house['covered_cells']:,} "
            f"({house['covered_share_of_passable_land']:.1%} of passable land); "
            f"packed {len(placed):,} houses ({best_order} order)"
        )

    outlines = (
        region_outlines_from_rects(server.region_rects)
        if server.region_rects is not None
        else None
    )
    viewer_packings = []
    if not args.no_mixed:
        if not entries or not outlines:
            print(
                "Mixed packing skipped: it needs region rules (towns) to place house sizes."
            )
        else:
            settings = MixedSettings(seed=args.seed)
            kinds = _mixed_house_kinds(entries, multis, tiledata, cliloc, settings)
            print(f"Mixed packing over {len(kinds)} house kinds...")
            cache_key = "|".join(
                [
                    _file_identity(facet.source.land_path),
                    _file_identity(facet.source.staidx_path),
                    _file_identity(facet.source.statics_path),
                    _file_identity(client / "tiledata.mul"),
                    server.identity,
                    str(tuple(window)),
                    str(args.facet == 0),
                ]
            )
            packing, mixed_summary = _run_mixed_packing(
                cache_key=cache_key,
                grids=grids,
                kinds=kinds,
                multis=multis,
                tiledata=tiledata,
                window=window,
                outlines=outlines,
                land_ids=land_ids,
                settings=settings,
                outdir=outdir,
            )
            summary["mixed"] = mixed_summary
            print(
                f"  mixed: {len(packing.placed):,} houses "
                + ", ".join(f"{c} {n:,}" for c, n in sorted(packing.counts.items()))
            )
            viewer_packings.append(
                {
                    "label": "Mixed: towns small, outskirts large, workshops by mountains",
                    "kinds": [
                        {
                            "label": k.label,
                            "multi": f"0x{k.multi_id:04X}",
                            "class": k.house_class,
                            "footprint": k.footprint,
                        }
                        for k in kinds
                    ],
                    "placed": packing.placed,
                }
            )

    (outdir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    if not args.no_viewer and viewer_houses:
        install = resolve_install(args.client)[1]
        page = write_capacity_viewer(
            outdir / "viewer",
            title=f"House capacity: {FACET_NAMES.get(args.facet, args.facet)}, "
            f"{install.label or install.name if install else client.name}",
            window=tuple(window),
            base_rgb=radar_rgb,
            houses=viewer_houses,
            regions=outlines,
            packings=viewer_packings,
            notes=[
                "Empty world: existing houses, placed items and regions created at "
                "runtime are not included.",
                "Regions are shown as they apply at z 0.",
                "Packing is greedy, so the house count is a lower bound.",
                "Mixed packing is one seeded scenario: house sizes are drawn per "
                "32-tile zone by distance from towns and mountain rock.",
            ],
        )
        print(f"Viewer: {page}")
    print(f"Wrote {outdir}")
    return 0


def house_footprints_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    server_profile: Annotated[
        Optional[str],
        typer.Option(
            "--server-profile",
            help="Server profile JSON (regions, region rules, house menu). Default: the install's or [uo.reference] server_profile.",
        ),
    ] = None,
    placement_source: Annotated[
        Optional[str],
        typer.Option(
            "--placement-source",
            help="RunUO/ServUO HousePlacementTool.cs listing the houses a server offers. Default: [uo.reference] house_placement_tool.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Multi source: auto, uop or mul. Default: the install's multis setting, else auto.",
        ),
    ] = None,
    scale: Annotated[
        int,
        typer.Option("--scale", help="Pixels per tile in house_footprints.png."),
    ] = 6,
) -> None:
    """Export house placement footprints (cells as CSV/JSON plus a contact sheet PNG)."""
    raise SystemExit(cmd_house_footprints(SimpleNamespace(**locals())))


def house_capacity_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    facet: Annotated[
        int,
        typer.Option("--facet", "-f", help="Facet number."),
    ] = 0,
    multi: Annotated[
        Optional[list[str]],
        typer.Option(
            "--multi",
            help="House multi ID (e.g. 0x13EC); repeat for several. Default: the smallest house in the placement table.",
        ),
    ] = None,
    window: Annotated[
        Optional[str],
        typer.Option(
            "--window",
            help="Centre window X0,Y0,X1,Y1. Default: Britannia proper (x < 5120) on facets 0/1, else the whole facet.",
        ),
    ] = None,
    regions: Annotated[
        Optional[str],
        typer.Option(
            "--regions",
            help="RunUO/ServUO Regions.xml. Default: the install's or [uo.reference] regions_xml.",
        ),
    ] = None,
    region_scripts: Annotated[
        Optional[str],
        typer.Option(
            "--region-scripts",
            help="Emulator Scripts folder; region types that forbid housing are read from its AllowHousing overrides. Default: emulator_scripts, else RunUO's six types.",
        ),
    ] = None,
    server_profile: Annotated[
        Optional[str],
        typer.Option(
            "--server-profile",
            help="Server profile JSON (regions, region rules, house menu). Default: the install's or [uo.reference] server_profile.",
        ),
    ] = None,
    placement_source: Annotated[
        Optional[str],
        typer.Option(
            "--placement-source",
            help="HousePlacementTool.cs, used for names and the default house. Default: [uo.reference] house_placement_tool.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Multi source: auto, uop or mul. Default: the install's multis setting.",
        ),
    ] = None,
    no_viewer: Annotated[
        bool,
        typer.Option(
            "--no-viewer", help="Skip the interactive viewer (viewer/index.html)."
        ),
    ] = False,
    no_mixed: Annotated[
        bool,
        typer.Option("--no-mixed", help="Skip the mixed-size packing scenario."),
    ] = False,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Random seed for the mixed packing's zone draws."),
    ] = 20261018,
) -> None:
    """Simulate legal house placement on a facet and greedily pack houses."""
    raise SystemExit(cmd_house_capacity(SimpleNamespace(**locals())))
