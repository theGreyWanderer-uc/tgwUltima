"""``titan uo map-*`` / ``radar-export`` / ``multi-export`` — facet map, radar colour and multi commands."""

from __future__ import annotations

__all__ = [
    "radar_export_cmd",
    "map_export_cmd",
    "map_render_cmd",
    "map_tiles_cmd",
    "map_inventory_cmd",
    "multi_export_cmd",
]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.uo.map import FACET_DIMENSIONS, UOMap
from titan.uo.multi import UOMultis
from titan.uo.render import UOMapRenderer
from titan.uo.tiles import FacetTileJob, build_facet_tiles
from titan.uo.cli import _common


def cmd_radar_export(args: SimpleNamespace) -> int:
    """Export the UO radar/minimap color lookup table."""
    try:
        client = _common._client_path(args.client)
        radar = _common._load_radar(client)
        tiledata = _common._try_load_tiledata(client)
        animdata = _common._try_load_animdata(client)
        defs = _common._try_load_defs(client)
        tilehelp = _common._try_load_tilehelp(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "radar"
    outdir.mkdir(parents=True, exist_ok=True)
    radar.to_swatch_image(
        columns=args.columns,
        swatch_size=args.swatch_size,
    ).save(outdir / "radarcol.png")

    rows: list[dict[str, object]] = []
    for color in radar.colors:
        red, green, blue = color.rgb
        is_land = color.index < 0x4000
        tile_id = color.index if is_land else color.index - 0x4000
        row: dict[str, object] = {
            "index": color.index,
            "kind": "land" if is_land else "static",
            "tile_id": tile_id,
            "color16": f"0x{color.color16:04X}",
            "red": red,
            "green": green,
            "blue": blue,
        }
        if is_land:
            land_tile = (
                tiledata.land[tile_id]
                if tiledata is not None and tile_id < len(tiledata.land)
                else None
            )
            row.update(_common._land_metadata(land_tile))
            texterr = defs.get("texterr.def")
            row.update(
                _common._redirect_metadata(
                    "texterr",
                    (texterr.redirects.get(tile_id) if texterr is not None else None),
                )
            )
        else:
            static_tile = (
                tiledata.statics[tile_id]
                if tiledata is not None and tile_id < len(tiledata.statics)
                else None
            )
            anim_entry = animdata.entries.get(tile_id) if animdata is not None else None
            row.update(_common._static_metadata(static_tile, anim_entry, tilehelp))
            row.update(_common._redirect_metadata("texterr", None))
        rows.append(row)
    _common._write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(radar.colors)} radar color(s) -> {outdir}")
    return 0


def cmd_map_export(args: SimpleNamespace) -> int:
    """Render UO facets as one-pixel-per-tile radar images."""
    try:
        client = _common._client_path(args.client)
        radar = _common._load_radar(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    facets = args.facet or [
        facet
        for facet in sorted(FACET_DIMENSIONS)
        if (client / f"staidx{facet}{args.suffix}.mul").is_file()
    ]
    if not facets:
        print("ERROR: no staidxN.mul files found", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "maps"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for facet in facets:
        try:
            facet_map = UOMap.from_client(
                client,
                facet,
                container=_common._source(args, "maps"),
                suffix=args.suffix,
                patches=args.patches,
            )
        except Exception as exc:
            print(f"ERROR: facet {facet}: {exc}", file=sys.stderr)
            return 1

        stem = f"map{facet}{args.suffix}"
        facet_map.render_radar(radar, statics=not args.no_statics).save(
            outdir / f"{stem}.png"
        )
        if args.heightmap:
            facet_map.render_heightmap().save(outdir / f"{stem}_height.png")

        source = facet_map.source
        summary = facet_map.static_index_summary()
        rows.append(
            {
                "facet": facet,
                "image": f"{stem}.png",
                "width": facet_map.width,
                "height": facet_map.height,
                "land_container": source.land_container if source else "",
                "land_file": Path(source.land_path).name if source else "",
                "trailing_land_blocks": source.trailing_land_blocks if source else 0,
                "land_patch_blocks": source.land_patch_blocks if source else 0,
                "static_patch_blocks": source.static_patch_blocks if source else 0,
                **summary,
            }
        )
        print(
            f"facet {facet}: {facet_map.width}x{facet_map.height}, "
            f"{summary['static_count']} static(s) -> {outdir / f'{stem}.png'}"
        )

    _common._write_manifest(outdir / "summary.csv", rows)
    print(f"Exported {len(rows)} facet map(s) -> {outdir}")
    return 0


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render an isometric view of a UO facet like the client."""
    try:
        client = _common._client_path(args.client)
        center = _common._parse_int_list(args.center, (2, 3), "--center")
        width, height = _common._parse_int_list(args.size, (2,), "--size")
        facet_map = UOMap.from_client(
            client,
            args.facet,
            container=_common._source(args, "maps"),
            suffix=args.suffix,
            patches=args.patches,
        )
        renderer = UOMapRenderer.from_client(client, facet_map, hues=not args.no_hues)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    image = renderer.render(
        center[0],
        center[1],
        width,
        height,
        center_z=center[2] if len(center) == 3 else None,
        statics=not args.no_statics,
        roofs=not args.no_roofs,
        shading=not args.no_shading,
    )
    outdir = _common._out(args) / "maps" / "render"
    outdir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"map{args.facet}{args.suffix}_{center[0]}_{center[1]}"
    path = outdir / f"{name}.png"
    image.save(path)
    print(
        f"Rendered facet {args.facet} at {center[0]},{center[1]} ({width}x{height}) -> {path}"
    )
    return 0


def cmd_map_inventory(args: SimpleNamespace) -> int:
    """Count every land and static tile a facet uses, ranked by placements."""
    from titan.uo.map_inventory import build_uo_map_inventory, write_uo_map_inventory
    from titan.uo.render import UOArtSource

    try:
        client = _common._client_path(args.client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    facets = args.facet or [
        facet
        for facet in sorted(FACET_DIMENSIONS)
        if (client / f"staidx{facet}{args.suffix}.mul").is_file()
    ]
    if not facets:
        print("ERROR: no staidxN.mul files found", file=sys.stderr)
        return 1
    try:
        tiledata = _common._load_tiledata(client)
        art = None if args.no_previews else UOArtSource.from_client(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    root = _common._out(args) if args.output else _common._out(args) / "map-inventory"
    for facet in facets:
        try:
            inventory = build_uo_map_inventory(
                client,
                facet,
                container=_common._source(args, "maps"),
                suffix=args.suffix,
                patches=args.patches,
                tiledata=tiledata,
            )
            outdir = root / f"map{facet}{args.suffix}"
            summary = write_uo_map_inventory(
                inventory, outdir, previews=not args.no_previews, art=art
            )
        except Exception as exc:
            print(f"ERROR: facet {facet}: {exc}", file=sys.stderr)
            return 1
        statics, land = summary["statics"], summary["land"]
        coverage = statics["coverage_by_top_names_pct"]
        print(
            f"facet {facet}: {statics['placements']:,} statics over {statics['tile_ids']:,} tile IDs "
            f"and {statics['names']:,} names (top 100 names {coverage['top_100']}%); "
            f"{land['cells']:,} land cells over {land['tile_ids']:,} land IDs -> {outdir}"
        )
    return 0


def cmd_map_tiles(args: SimpleNamespace) -> int:
    """Render a whole facet as a zoomable tile pyramid with an offline viewer."""
    try:
        client = _common._client_path(args.client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = _common._out(args) / "maps" / "tiles" / f"map{args.facet}{args.suffix}"
    job = FacetTileJob(
        client=str(client),
        facet=args.facet,
        output=str(output),
        tile_size=args.tile_size,
        quality=args.quality,
        container=_common._source(args, "maps"),
        suffix=args.suffix,
        patches=args.patches,
        statics=not args.no_statics,
        roofs=not args.no_roofs,
        shading=not args.no_shading,
        hues=not args.no_hues,
    )
    workers = args.workers or max(1, min(16, (os.cpu_count() or 2) - 2))
    try:
        build_facet_tiles(job, workers=workers)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_multi_export(args: SimpleNamespace) -> int:
    """Export UO multi component metadata to CSV."""
    try:
        client = _common._client_path(args.client)
        multis = UOMultis.from_client(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
            container="mul" if args.mul_only else _common._source(args, "multis"),
        )
        tiledata = _common._try_load_tiledata(client)
        animdata = _common._try_load_animdata(client)
        tilehelp = _common._try_load_tilehelp(client, "enu")
        cliloc = _common._load_cliloc(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "multis"
    outdir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, object]] = []
    component_rows: list[dict[str, object]] = []

    for multi in sorted(multis.multis.values(), key=lambda item: item.multi_id):
        min_x, max_x, min_y, max_y, min_z, max_z = multi.bounds
        summary_rows.append(
            {
                "multi_id": multi.multi_id,
                "source": multi.source,
                "layout": multi.layout,
                "component_count": len(multi.components),
                "visible_component_count": len(multi.visible_components),
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
                "min_z": min_z,
                "max_z": max_z,
                "width": max_x - min_x + 1 if multi.components else 0,
                "height": max_y - min_y + 1 if multi.components else 0,
            }
        )
        for component_index, component in enumerate(multi.components):
            static_tile = (
                tiledata.statics[component.item_id]
                if tiledata is not None and component.item_id < len(tiledata.statics)
                else None
            )
            anim_entry = (
                animdata.entries.get(component.item_id)
                if animdata is not None
                else None
            )
            cliloc_texts = [
                cliloc.entries[value].text
                for value in component.clilocs
                if value in cliloc.entries
            ]
            row: dict[str, object] = {
                "multi_id": multi.multi_id,
                "component": component_index,
                "source": multi.source,
                "layout": multi.layout,
                "item_id": component.item_id,
                "art_id": component.item_id + 0x4000,
                "x": component.x,
                "y": component.y,
                "z": component.z,
                "flags": f"0x{component.flags:X}",
                "extra": f"0x{component.extra:X}",
                "visible": 1 if component.visible else 0,
                "clilocs": "|".join(str(value) for value in component.clilocs),
                "cliloc_text": "|".join(cliloc_texts),
            }
            row.update(_common._static_metadata(static_tile, anim_entry, tilehelp))
            component_rows.append(row)

    _common._write_manifest(outdir / "summary.csv", summary_rows)
    _common._write_manifest(outdir / "components.csv", component_rows)
    print(
        f"Exported {len(summary_rows)} multi(s), {len(component_rows)} component row(s) "
        f"from {multis.source} ({multis.layout}) -> {outdir}"
    )
    return 0


def radar_export_cmd(
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
    columns: Annotated[
        int,
        typer.Option("--columns", help="Swatch columns."),
    ] = 256,
    swatch_size: Annotated[
        int,
        typer.Option("--swatch-size", help="Pixel size for each color entry."),
    ] = 4,
) -> None:
    """Export the UO radar/minimap color lookup table."""
    raise SystemExit(cmd_radar_export(SimpleNamespace(**locals())))


def map_export_cmd(
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
        Optional[list[int]],
        typer.Option(
            "--facet",
            "-f",
            help="Facet number to export; repeat for several. Default: every facet with a staidxN.mul.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_statics: Annotated[
        bool,
        typer.Option("--no-statics", help="Render terrain only."),
    ] = False,
    heightmap: Annotated[
        bool,
        typer.Option("--heightmap", help="Also write a greyscale land-altitude PNG."),
    ] = False,
) -> None:
    """Render UO facets as one-pixel-per-tile radar map PNGs."""
    raise SystemExit(cmd_map_export(SimpleNamespace(**locals())))


def map_render_cmd(
    center: Annotated[
        str,
        typer.Option(
            "--center",
            "-c",
            help="Centre cell as X,Y or X,Y,Z (Z defaults to the land altitude there).",
        ),
    ],
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
    size: Annotated[
        str,
        typer.Option("--size", help="Image size in pixels, WIDTHxHEIGHT."),
    ] = "1600x1200",
    name: Annotated[
        Optional[str],
        typer.Option("--name", help="Output file stem. Default: mapN_X_Y."),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_statics: Annotated[
        bool,
        typer.Option("--no-statics", help="Render terrain only."),
    ] = False,
    no_roofs: Annotated[
        bool,
        typer.Option("--no-roofs", help="Hide statics flagged as roofs."),
    ] = False,
    no_shading: Annotated[
        bool,
        typer.Option("--no-shading", help="Draw sloped land without normal lighting."),
    ] = False,
    no_hues: Annotated[
        bool,
        typer.Option("--no-hues", help="Ignore static hues."),
    ] = False,
) -> None:
    """Render an isometric view of a UO facet, drawn like the client."""
    raise SystemExit(cmd_map_render(SimpleNamespace(**locals())))


def map_tiles_cmd(
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
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            "-j",
            help="Worker processes. Default: CPU count - 2, at most 16.",
        ),
    ] = 0,
    tile_size: Annotated[
        int,
        typer.Option("--tile-size", help="Tile edge in pixels."),
    ] = 512,
    quality: Annotated[
        int,
        typer.Option("--quality", help="JPEG quality for tiles."),
    ] = 85,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_statics: Annotated[
        bool,
        typer.Option("--no-statics", help="Render terrain only."),
    ] = False,
    no_roofs: Annotated[
        bool,
        typer.Option("--no-roofs", help="Hide statics flagged as roofs."),
    ] = False,
    no_shading: Annotated[
        bool,
        typer.Option("--no-shading", help="Draw sloped land without normal lighting."),
    ] = False,
    no_hues: Annotated[
        bool,
        typer.Option("--no-hues", help="Ignore static hues."),
    ] = False,
) -> None:
    """Render a whole UO facet as a zoomable tile pyramid with an offline viewer."""
    raise SystemExit(cmd_map_tiles(SimpleNamespace(**locals())))


def map_inventory_cmd(
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
            help="Output directory; each facet goes in mapN/ inside it. Default: <install output>/map-inventory.",
        ),
    ] = None,
    facet: Annotated[
        Optional[list[int]],
        typer.Option(
            "--facet",
            "-f",
            help="Facet number to inventory; repeat for several. Default: every facet with a staidxN.mul.",
        ),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Terrain source: auto (mapNLegacyMUL.uop, else mapN.mul), uop or mul. Default: the install's maps setting, else auto.",
        ),
    ] = None,
    suffix: Annotated[
        str,
        typer.Option(
            "--suffix",
            help="Alternate file-set suffix, e.g. 'x' for map0x/staidx0x/statics0x.",
        ),
    ] = "",
    patches: Annotated[
        bool,
        typer.Option(
            "--patches", help="Apply mapdif/stadif difference files when present."
        ),
    ] = False,
    no_previews: Annotated[
        bool,
        typer.Option("--no-previews", help="Skip art PNGs and index.html."),
    ] = False,
) -> None:
    """Inventory every land and static tile a facet uses, ranked by placements.

    Writes statics.csv and land.csv (one row per tile ID, with tiledata
    name, category, flags, height, altitude range, block spread and a
    sample cell), names.csv (statics rolled up by tiledata name),
    summary.json and, unless --no-previews, art PNGs with a filterable
    index.html.
    """
    raise SystemExit(cmd_map_inventory(SimpleNamespace(**locals())))


def multi_export_cmd(
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
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum multis to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First multi ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last multi ID, exclusive."),
    ] = None,
    container: Annotated[
        Optional[str],
        typer.Option(
            "--container",
            help="Multi source: auto (MultiCollection.uop, else multi.mul), uop or mul. Default: the install's multis setting, else auto.",
        ),
    ] = None,
    mul_only: Annotated[
        bool,
        typer.Option("--mul-only", help="Shorthand for --container mul."),
    ] = False,
) -> None:
    """Export UO multi component metadata to CSV."""
    raise SystemExit(cmd_multi_export(SimpleNamespace(**locals())))
