"""``titan u8 map-*`` — map rendering and sampling commands."""

from __future__ import annotations

__all__ = [
    "map_render_cmd",
    "map_render_all_cmd",
    "map_sample_cmd",
    "map_sample_all_cmd",
]

import copy
import os
import sys
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._config import cfg as _cfg
from titan.flex import FlexArchive
from titan.u8.palette import U8Palette
from titan.u8.map import U8MapRenderer, U8MapSampler


def _get_exclude_flags(args: SimpleNamespace) -> dict[str, bool]:
    """Extract all exclude flags from argparse Namespace."""
    _exclude: dict[str, bool] = {}
    _exclude_names = [
        "no_fixed",
        "no_solid",
        "no_sea",
        "no_land",
        "no_occl",
        "no_bag",
        "no_damaging",
        "no_noisy",
        "no_draw",
        "no_ignore",
        "no_roof",
        "no_transl",
        "no_editor",
        "no_explode",
        "no_unk46",
        "no_unk47",
    ]
    for _name in _exclude_names:
        _exclude[_name] = getattr(args, _name, False)
    return _exclude


def _dir_manifest(dir_path: str, ext: str) -> dict[str, int]:
    """Return ``{filename: filesize}`` for all *ext* files in *dir_path*."""
    if not os.path.isdir(dir_path):
        return {}
    result: dict[str, int] = {}
    for name in sorted(os.listdir(dir_path)):
        if name.lower().endswith(ext.lower()):
            result[name] = os.path.getsize(os.path.join(dir_path, name))
    return result


def _verify_dir_against_flex(
    dir_path: str,
    ext: str,
    flx_path: str,
) -> tuple[list[int], list[int]]:
    """Compare extracted files against FLX records."""
    archive = FlexArchive.from_file(flx_path)
    missing: list[int] = []
    changed: list[int] = []
    for i, record in enumerate(archive.records):
        if not record:
            continue
        filename = f"{i:04d}{ext}"
        filepath = os.path.join(dir_path, filename)
        if not os.path.isfile(filepath):
            missing.append(i)
        elif os.path.getsize(filepath) != len(record):
            changed.append(i)
    return missing, changed


def _resolve_typeflag(args: SimpleNamespace) -> Optional[str]:
    """Return a path to TYPEFLAG.DAT for dimension-aware depth sorting."""
    tf = getattr(args, "typeflag", None)
    if tf and os.path.isfile(tf):
        return tf

    fixed = getattr(args, "fixed", None)
    if fixed:
        candidate = os.path.join(os.path.dirname(fixed) or ".", "TYPEFLAG.DAT")
        if os.path.isfile(candidate):
            return candidate

    if os.path.isfile("TYPEFLAG.DAT"):
        return "TYPEFLAG.DAT"

    return None


def _ensure_asset_dir(
    dir_path: str,
    ext: str,
    label: str,
    flx_hint: str,
) -> bool:
    """Verify that *dir_path* contains extracted *ext* files."""
    manifest = _dir_manifest(dir_path, ext)
    if manifest:
        total_bytes = sum(manifest.values())
        print(f"  {label}: {len(manifest)} {ext} files ({total_bytes:,} bytes)")
        return True

    if not os.path.isdir(dir_path):
        print(f"\n[MISSING] {label} directory not found: {dir_path}")
    else:
        print(
            f"\n[EMPTY] {label} directory exists but contains no "
            f"{ext} files: {dir_path}"
        )
    print(f"  Map rendering needs individual {ext} files extracted from {flx_hint}.")
    clean_dir = dir_path.rstrip("/\\")
    print(
        f"  You can do this manually with: "
        f"titan flex-extract {flx_hint} -o {clean_dir}/"
    )
    print()

    from titan import _wizard_ui as ui

    try:
        answer = ui.choice(
            f"  Extract {flx_hint} into '{dir_path}' now? [y/N] ",
            ["y", "Y", "n", "N"],
            "N",
        ).lower()
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        return False

    if answer not in ("y", "yes"):
        print(f"  Aborting.  Re-run after extracting {flx_hint} manually.")
        return False

    flx_path = ""
    while not flx_path or not os.path.isfile(flx_path):
        try:
            flx_path = ui.path(f"  Enter path to {flx_hint}: ").strip()
        except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
            return False
        if not flx_path:
            continue
        if not os.path.isfile(flx_path):
            print(f"  Not found: {flx_path}")
            flx_path = ""

    print(f"\n  Loading {flx_path} ...")
    try:
        archive = FlexArchive.from_file(flx_path)
    except Exception as exc:
        print(f"  ERROR: Could not read FLX: {exc}", file=sys.stderr)
        return False

    non_empty = sum(1 for r in archive.records if r)
    print(f"  Extracting {non_empty} non-empty records to {dir_path}/ ...")
    os.makedirs(dir_path, exist_ok=True)
    extracted = archive.extract_all(dir_path)

    missing_idx, changed_idx = _verify_dir_against_flex(dir_path, ext, flx_path)
    new_manifest = _dir_manifest(dir_path, ext)
    total_bytes = sum(new_manifest.values())
    print(
        f"  Extracted {extracted} files -> {dir_path}/  ({total_bytes:,} bytes total)"
    )

    if missing_idx:
        indices_preview = missing_idx[:10]
        ellipsis = "..." if len(missing_idx) > 10 else ""
        print(
            f"  WARNING: {len(missing_idx)} records still missing after "
            f"extraction: {indices_preview}{ellipsis}",
            file=sys.stderr,
        )
    if changed_idx:
        indices_preview = changed_idx[:10]
        ellipsis = "..." if len(changed_idx) > 10 else ""
        print(
            f"  WARNING: {len(changed_idx)} files differ in size from FLX "
            f"records: {indices_preview}{ellipsis}",
            file=sys.stderr,
        )
    if not missing_idx and not changed_idx:
        print(f"  Verification OK: all {non_empty} records match disk files.")

    return bool(new_manifest)


def _apply_map_config(
    fixed: Optional[str],
    shapes: Optional[str],
    globs: Optional[str],
    palette: Optional[str],
    typeflag: Optional[str],
    nonfixed: Optional[str],
) -> tuple[str, str, str, str, Optional[str], Optional[str]]:
    """Apply titan.toml defaults to map command paths."""
    fixed = fixed or _cfg("fixed")
    shapes = shapes or _cfg("shapes")
    globs = globs or _cfg("globs")
    palette = palette or _cfg("palette")
    typeflag = typeflag or _cfg("typeflag")
    nonfixed = nonfixed or _cfg("nonfixed")
    missing = [
        k
        for k, v in [
            ("fixed", fixed),
            ("shapes", shapes),
            ("globs", globs),
            ("palette", palette),
        ]
        if not v
    ]
    if missing:
        print(
            f"Missing required argument(s): --{', --'.join(missing)}\n"
            "Supply them on the command line, or run `titan setup` to "
            "create a titan.toml config file.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    assert fixed is not None and shapes is not None
    assert globs is not None and palette is not None
    return fixed, shapes, globs, palette, typeflag, nonfixed


def _build_map_namespace(**kw: object) -> SimpleNamespace:
    """Build a SimpleNamespace for map commands with config-aware defaults."""
    fixed, shapes, globs, palette, typeflag, nonfixed = _apply_map_config(
        kw.get("fixed"),  # type: ignore[arg-type]
        kw.get("shapes"),  # type: ignore[arg-type]
        kw.get("globs"),  # type: ignore[arg-type]
        kw.get("palette"),  # type: ignore[arg-type]
        kw.get("typeflag"),  # type: ignore[arg-type]
        kw.get("nonfixed"),  # type: ignore[arg-type]
    )
    kw.update(
        fixed=fixed,
        shapes=shapes,
        globs=globs,
        palette=palette,
        typeflag=typeflag,
        nonfixed=nonfixed,
    )
    return SimpleNamespace(**kw)


def _parse_fixed_maps(
    data: bytes,
) -> Optional[dict[int, list[U8MapRenderer.MapObject]]]:
    """Report strict map-input errors through the existing command return codes."""
    try:
        return U8MapRenderer.parse_fixed_dat(data)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def _load_nonfixed_maps(
    path: str,
) -> Optional[dict[int, list[U8MapRenderer.MapObject]]]:
    """Read stored dynamic placements with a clean error for malformed files/saves."""
    try:
        return U8MapRenderer.load_nonfixed(path)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def _merge_nonfixed_input(
    fixed_maps: dict[int, list[U8MapRenderer.MapObject]],
    nonfixed_path: Optional[str],
) -> Optional[dict[int, list[U8MapRenderer.MapObject]]]:
    """Load dynamic placements before choosing maps or expanding either source's globs."""
    if not nonfixed_path:
        return U8MapRenderer.merge_maps(fixed_maps)
    nonfixed_maps = _load_nonfixed_maps(nonfixed_path)
    if nonfixed_maps is None:
        return None
    count = sum(len(items) for items in nonfixed_maps.values())
    print(f"Loaded {count} nonfixed objects across {len(nonfixed_maps)} maps")
    return U8MapRenderer.merge_maps(fixed_maps, nonfixed_maps)


def cmd_map_sample(args: SimpleNamespace) -> int:
    """Render a colour-sampled top-down map (minimap-style) to PNG."""
    if not os.path.isfile(args.fixed):
        print(f"ERROR: FIXED.DAT not found: {args.fixed}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(args.shapes, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(args.globs, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(args.palette):
        print(f"ERROR: Palette not found: {args.palette}", file=sys.stderr)
        return 1

    scale = args.scale
    map_num = args.map

    with open(args.fixed, "rb") as f:
        fixed_data = f.read()
    all_maps = _parse_fixed_maps(fixed_data)
    if all_maps is None:
        return 1
    all_maps = _merge_nonfixed_input(all_maps, getattr(args, "nonfixed", None))
    if all_maps is None:
        return 1
    if map_num not in all_maps:
        print(f"ERROR: Map {map_num} not found or empty.", file=sys.stderr)
        print(f"  Available: {sorted(all_maps.keys())}", file=sys.stderr)
        return 1

    pal = U8Palette.from_file(args.palette)
    raw_objects = all_maps[map_num]
    print(f"Map {map_num}: {len(raw_objects)} objects")

    glob_count = sum(1 for o in raw_objects if o.type_num == 2)
    objects = U8MapRenderer.expand_globs(raw_objects, args.globs)
    print(f"After GLOB expansion: {len(objects)} objects  ({glob_count} GLOBs)")

    tf = getattr(args, "typeflag", None)
    _exclude_flags = _get_exclude_flags(args)
    if any(_exclude_flags.values()):
        if not tf:
            print(
                "ERROR: Typeflag filtering requires --typeflag <typeflag.dat>",
                file=sys.stderr,
            )
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        before = len(objects)
        objects = [o for o in objects if o.type_num not in exclude_set]
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(
            f"Typeflags filter: {', '.join(active_filters)} -> "
            f"removed {before - len(objects)}, {len(objects)} remain"
        )

    print(f"Sampling at {scale} world-units/pixel ...")

    img = U8MapSampler.sample_map(
        objects,
        args.shapes,
        pal,
        scale=scale,
        grid=getattr(args, "grid", False),
        grid_size=getattr(args, "grid_size", 2),
    )
    print(f"Output size: {img.width} x {img.height}")

    out_path = args.output or f"map_{map_num:03d}_sample_{scale}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Saved: {out_path}")
    return 0


def cmd_map_sample_all(args: SimpleNamespace) -> int:
    """Colour-sample all (or selected) maps at one or more scales."""
    if not os.path.isfile(args.fixed):
        print(f"ERROR: FIXED.DAT not found: {args.fixed}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(args.shapes, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(args.globs, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(args.palette):
        print(f"ERROR: Palette not found: {args.palette}", file=sys.stderr)
        return 1

    pal = U8Palette.from_file(args.palette)
    with open(args.fixed, "rb") as f:
        fixed_data = f.read()

    print(f"Parsing {args.fixed} ...")
    all_maps = _parse_fixed_maps(fixed_data)
    if all_maps is None:
        return 1
    all_maps = _merge_nonfixed_input(all_maps, getattr(args, "nonfixed", None))
    if all_maps is None:
        return 1

    targets = sorted(args.maps) if args.maps else sorted(all_maps.keys())
    missing = [m for m in targets if m not in all_maps]
    if missing:
        print(f"WARNING: Maps not found / empty, skipping: {missing}", file=sys.stderr)
    targets = [m for m in targets if m in all_maps]
    if not targets:
        print("No maps to sample.", file=sys.stderr)
        return 1

    scales: list[int] = args.scales or [args.scale]
    os.makedirs(args.output, exist_ok=True)

    total = len(targets) * len(scales)
    done = 0

    tf = getattr(args, "typeflag", None)
    _exclude_flags = _get_exclude_flags(args)
    exclude_set: set[int] = set()
    if any(_exclude_flags.values()):
        if not tf:
            print(
                "ERROR: Typeflag filtering requires --typeflag <typeflag.dat>",
                file=sys.stderr,
            )
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(
            f"Typeflag filters active: {', '.join(active_filters)} "
            f"({len(exclude_set)} shapes excluded)"
        )

    for map_num in targets:
        raw_objects = all_maps[map_num]
        objects = U8MapRenderer.expand_globs(raw_objects, args.globs)
        if exclude_set:
            objects = [o for o in objects if o.type_num not in exclude_set]
        print(
            f"[{targets.index(map_num) + 1}/{len(targets)}] "
            f"Map {map_num:3d}: {len(raw_objects):5d} raw -> "
            f"{len(objects):5d} expanded"
        )

        for scale in scales:
            img = U8MapSampler.sample_map(
                objects,
                args.shapes,
                pal,
                scale=scale,
                grid=getattr(args, "grid", False),
                grid_size=getattr(args, "grid_size", 2),
            )
            out_name = f"map_{map_num:03d}_sample_{scale}.png"
            img.save(os.path.join(args.output, out_name))
            done += 1
            print(f"  [{done}/{total}] {out_name}  ({img.width}x{img.height})")

    print(f"\nDone.  {done} images saved to {args.output}/")
    return 0


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render an Ultima 8 map to a PNG image."""
    fixed_path = args.fixed
    shapes_dir = args.shapes
    glob_dir = args.globs
    palette_path = args.palette
    map_num = args.map
    out_path = args.output
    view = getattr(args, "view", U8MapRenderer.DEFAULT_VIEW)

    if not os.path.isfile(fixed_path):
        print(f"ERROR: FIXED.DAT not found: {fixed_path}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(shapes_dir, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(glob_dir, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette file not found: {palette_path}", file=sys.stderr)
        return 1
    if view not in U8MapRenderer.PROJECTIONS:
        print(
            f"ERROR: Unknown view '{view}'. "
            f"Choose from: {', '.join(U8MapRenderer.PROJECTIONS)}",
            file=sys.stderr,
        )
        return 1

    pal = U8Palette.from_file(palette_path)

    with open(fixed_path, "rb") as f:
        fixed_data = f.read()

    print(f"Parsing {fixed_path} ...")
    all_maps = _parse_fixed_maps(fixed_data)
    if all_maps is None:
        return 1
    all_maps = _merge_nonfixed_input(all_maps, getattr(args, "nonfixed", None))
    if all_maps is None:
        return 1

    if map_num not in all_maps:
        available = sorted(all_maps.keys())
        print(f"ERROR: Map {map_num} not found or empty.", file=sys.stderr)
        print(f"  Available non-empty maps: {available}", file=sys.stderr)
        return 1

    objects = all_maps[map_num]
    print(f"Map {map_num}: {len(objects)} objects")

    glob_count = sum(1 for o in objects if o.type_num == 2)
    if glob_count > 0:
        print(f"Expanding {glob_count} GLOB references ...")
    objects = U8MapRenderer.expand_globs(objects, glob_dir)
    print(f"After GLOB expansion: {len(objects)} objects")

    tf = getattr(args, "typeflag", None)
    _exclude_flags = _get_exclude_flags(args)
    if any(_exclude_flags.values()):
        if not tf:
            print(
                "ERROR: Typeflag filtering requires --typeflag <typeflag.dat>",
                file=sys.stderr,
            )
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        before = len(objects)
        objects = [o for o in objects if o.type_num not in exclude_set]
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(
            f"Typeflags filter: {', '.join(active_filters)} -> "
            f"removed {before - len(objects)}, {len(objects)} remain"
        )

    typeflag_sort = _resolve_typeflag(args)
    if typeflag_sort:
        print(f"Using TYPEFLAG for depth sort: {typeflag_sort}")

    print(f"Rendering view='{view}' (this may take a moment) ...")
    img = U8MapRenderer.render_map(
        objects,
        shapes_dir,
        pal,
        view=view,
        grid=getattr(args, "grid", False),
        grid_size=getattr(args, "grid_size", 2),
        typeflag_path=typeflag_sort,
    )
    print(f"Canvas size: {img.width} x {img.height}")

    if out_path is None:
        out_path = f"map_{map_num:03d}_{view}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Saved: {out_path}")
    return 0


def _render_all_shared(
    fixed_path: str,
    shapes_dir: str,
    glob_dir: str,
    palette_path: str,
    out_dir: str,
    views: list[str],
    map_nums: Optional[list[int]],
    *,
    exclude_set: set[int] | None = None,
    nonfixed_maps: Optional[dict] = None,
    grid: bool = False,
    grid_size: int = 2,
    typeflag_path: Optional[str] = None,
) -> int:
    """Shared logic for rendering multiple maps and/or views."""
    pal = U8Palette.from_file(palette_path)

    with open(fixed_path, "rb") as f:
        fixed_data = f.read()

    print(f"Parsing {fixed_path} ...")
    all_maps = _parse_fixed_maps(fixed_data)
    if all_maps is None:
        return 1
    all_maps = U8MapRenderer.merge_maps(all_maps, nonfixed_maps)

    targets = sorted(map_nums) if map_nums else sorted(all_maps.keys())
    missing = [m for m in targets if m not in all_maps]
    if missing:
        print(f"WARNING: Maps not found / empty, skipping: {missing}", file=sys.stderr)
    targets = [m for m in targets if m in all_maps]

    if not targets:
        print("No maps to render.", file=sys.stderr)
        return 1

    if exclude_set is None:
        exclude_set = set()

    os.makedirs(out_dir, exist_ok=True)
    total = len(targets) * len(views)
    done = 0

    for map_num in targets:
        raw_objects = all_maps[map_num]
        glob_count = sum(1 for o in raw_objects if o.type_num == 2)
        objects = U8MapRenderer.expand_globs(raw_objects, glob_dir)
        if exclude_set:
            objects = [o for o in objects if o.type_num not in exclude_set]
        nf_info = ""
        if nonfixed_maps and map_num in nonfixed_maps:
            nf_info = f" +{len(nonfixed_maps[map_num])} nonfixed"
        print(
            f"[{done // len(views) + 1}/{len(targets)}] "
            f"Map {map_num:3d}: {len(raw_objects):5d} raw -> "
            f"{len(objects):5d} expanded  ({glob_count} GLOBs{nf_info})"
        )

        for view in views:
            view_objects = copy.deepcopy(objects)
            img = U8MapRenderer.render_map(
                view_objects,
                shapes_dir,
                pal,
                view=view,
                grid=grid,
                grid_size=grid_size,
                typeflag_path=typeflag_path,
            )
            out_name = f"map_{map_num:03d}_{view}.png"
            img.save(os.path.join(out_dir, out_name))
            done += 1
            print(f"  [{done}/{total}] {out_name}  ({img.width}x{img.height})")

    print(f"\nDone.  {done} images saved to {out_dir}/")
    return 0


def cmd_map_render_all(args: SimpleNamespace) -> int:
    """Render all non-empty maps in all requested projection views."""
    if not os.path.isfile(args.fixed):
        print(f"ERROR: FIXED.DAT not found: {args.fixed}", file=sys.stderr)
        return 1
    if not _ensure_asset_dir(args.shapes, ".shp", "Shapes", "U8SHAPES.FLX"):
        return 1
    if not _ensure_asset_dir(args.globs, ".dat", "Globs", "GLOB.FLX"):
        return 1
    if not os.path.isfile(args.palette):
        print(f"ERROR: Palette not found: {args.palette}", file=sys.stderr)
        return 1

    views = getattr(args, "views", None) or list(U8MapRenderer.PROJECTIONS)
    bad = [v for v in views if v not in U8MapRenderer.PROJECTIONS]
    if bad:
        print(
            f"ERROR: Unknown view(s): {bad}. "
            f"Choose from: {', '.join(U8MapRenderer.PROJECTIONS)}",
            file=sys.stderr,
        )
        return 1

    map_nums: Optional[list[int]] = getattr(args, "maps", None) or None

    tf = getattr(args, "typeflag", None)
    _exclude_flags = _get_exclude_flags(args)
    exclude_set: set[int] = set()
    if any(_exclude_flags.values()):
        if not tf:
            print(
                "ERROR: Typeflag filtering requires --typeflag <typeflag.dat>",
                file=sys.stderr,
            )
            return 1
        if not os.path.isfile(tf):
            print(f"ERROR: typeflag.dat not found: {tf}", file=sys.stderr)
            return 1
        exclude_set = U8MapRenderer.build_exclude_set(tf, **_exclude_flags)
        active_filters = [k for k, v in _exclude_flags.items() if v]
        print(
            f"Typeflag filters: {', '.join(active_filters)} "
            f"({len(exclude_set)} shapes excluded)"
        )

    nonfixed_maps: Optional[dict] = None
    nf_path = getattr(args, "nonfixed", None)
    if nf_path:
        if not os.path.isfile(nf_path):
            print(f"ERROR: Nonfixed file not found: {nf_path}", file=sys.stderr)
            return 1
        nonfixed_maps = _load_nonfixed_maps(nf_path)
        if nonfixed_maps is None:
            return 1
        nf_total = sum(len(v) for v in nonfixed_maps.values())
        print(f"Loaded {nf_total} nonfixed objects across {len(nonfixed_maps)} maps")

    typeflag_sort = _resolve_typeflag(args)
    if typeflag_sort:
        print(f"Using TYPEFLAG for depth sort: {typeflag_sort}")

    return _render_all_shared(
        fixed_path=args.fixed,
        shapes_dir=args.shapes,
        glob_dir=args.globs,
        palette_path=args.palette,
        out_dir=args.output,
        views=views,
        map_nums=map_nums,
        exclude_set=exclude_set,
        nonfixed_maps=nonfixed_maps,
        grid=getattr(args, "grid", False),
        grid_size=getattr(args, "grid_size", 2),
        typeflag_path=typeflag_sort,
    )


def map_render_cmd(
    map_num: Annotated[
        int, typer.Option("--map", "-m", help="Map number to render (0\u2013255)")
    ],
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[
        Optional[str], typer.Option(help="Directory of extracted .shp shape files")
    ] = None,
    globs: Annotated[
        Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")
    ] = None,
    view: Annotated[
        str, typer.Option("--view", "-V", help="Projection view")
    ] = "iso_classic",
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output PNG path")
    ] = None,
    typeflag: Annotated[
        Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")
    ] = None,
    nonfixed: Annotated[
        Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")
    ] = None,
    no_fixed: Annotated[
        bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")
    ] = False,
    no_solid: Annotated[
        bool, typer.Option("--no-solid", help="Exclude SI_SOLID")
    ] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[
        bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")
    ] = False,
    no_noisy: Annotated[
        bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")
    ] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[
        bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")
    ] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[
        bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")
    ] = False,
    no_editor: Annotated[
        bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")
    ] = False,
    no_explode: Annotated[
        bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")
    ] = False,
    no_unk46: Annotated[
        bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")
    ] = False,
    no_unk47: Annotated[
        bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")
    ] = False,
    grid: Annotated[
        bool, typer.Option("--grid", help="Overlay chunk grid lines")
    ] = False,
    grid_size: Annotated[
        int, typer.Option("--grid-size", help="Grid line thickness in pixels")
    ] = 2,
) -> None:
    """Render a single U8 map to PNG."""
    args = _build_map_namespace(
        map=map_num,
        fixed=fixed,
        shapes=shapes,
        globs=globs,
        palette=palette,
        view=view,
        output=output,
        typeflag=typeflag,
        nonfixed=nonfixed,
        no_fixed=no_fixed,
        no_solid=no_solid,
        no_sea=no_sea,
        no_land=no_land,
        no_occl=no_occl,
        no_bag=no_bag,
        no_damaging=no_damaging,
        no_noisy=no_noisy,
        no_draw=no_draw,
        no_ignore=no_ignore,
        no_roof=no_roof,
        no_transl=no_transl,
        no_editor=no_editor,
        no_explode=no_explode,
        no_unk46=no_unk46,
        no_unk47=no_unk47,
        grid=grid,
        grid_size=grid_size,
        config=None,
    )
    raise SystemExit(cmd_map_render(args))


def map_render_all_cmd(
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[
        Optional[str], typer.Option(help="Directory of extracted .shp shape files")
    ] = None,
    globs: Annotated[
        Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")
    ] = None,
    output: Annotated[
        str, typer.Option("-o", "--output", help="Output directory")
    ] = "map_renders",
    views: Annotated[
        Optional[list[str]],
        typer.Option("--views", help="Views to render (default: all)"),
    ] = None,
    maps: Annotated[
        Optional[list[int]], typer.Option("--maps", help="Map numbers to render")
    ] = None,
    typeflag: Annotated[
        Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")
    ] = None,
    nonfixed: Annotated[
        Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")
    ] = None,
    no_fixed: Annotated[
        bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")
    ] = False,
    no_solid: Annotated[
        bool, typer.Option("--no-solid", help="Exclude SI_SOLID")
    ] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[
        bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")
    ] = False,
    no_noisy: Annotated[
        bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")
    ] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[
        bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")
    ] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[
        bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")
    ] = False,
    no_editor: Annotated[
        bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")
    ] = False,
    no_explode: Annotated[
        bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")
    ] = False,
    no_unk46: Annotated[
        bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")
    ] = False,
    no_unk47: Annotated[
        bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")
    ] = False,
    grid: Annotated[
        bool, typer.Option("--grid", help="Overlay chunk grid lines")
    ] = False,
    grid_size: Annotated[
        int, typer.Option("--grid-size", help="Grid line thickness in pixels")
    ] = 2,
) -> None:
    """Render all non-empty maps in all (or selected) projection views."""
    args = _build_map_namespace(
        fixed=fixed,
        shapes=shapes,
        globs=globs,
        palette=palette,
        output=output,
        views=views,
        maps=maps,
        typeflag=typeflag,
        nonfixed=nonfixed,
        no_fixed=no_fixed,
        no_solid=no_solid,
        no_sea=no_sea,
        no_land=no_land,
        no_occl=no_occl,
        no_bag=no_bag,
        no_damaging=no_damaging,
        no_noisy=no_noisy,
        no_draw=no_draw,
        no_ignore=no_ignore,
        no_roof=no_roof,
        no_transl=no_transl,
        no_editor=no_editor,
        no_explode=no_explode,
        no_unk46=no_unk46,
        no_unk47=no_unk47,
        grid=grid,
        grid_size=grid_size,
        config=None,
    )
    raise SystemExit(cmd_map_render_all(args))


def map_sample_cmd(
    map_num: Annotated[
        int, typer.Option("--map", "-m", help="Map number to sample (0\u2013255)")
    ],
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[
        Optional[str], typer.Option(help="Directory of extracted .shp shape files")
    ] = None,
    globs: Annotated[
        Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")
    ] = None,
    scale: Annotated[
        int, typer.Option("--scale", "-s", help="World units per output pixel")
    ] = 64,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output PNG path")
    ] = None,
    typeflag: Annotated[
        Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")
    ] = None,
    nonfixed: Annotated[
        Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")
    ] = None,
    no_fixed: Annotated[
        bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")
    ] = False,
    no_solid: Annotated[
        bool, typer.Option("--no-solid", help="Exclude SI_SOLID")
    ] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[
        bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")
    ] = False,
    no_noisy: Annotated[
        bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")
    ] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[
        bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")
    ] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[
        bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")
    ] = False,
    no_editor: Annotated[
        bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")
    ] = False,
    no_explode: Annotated[
        bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")
    ] = False,
    no_unk46: Annotated[
        bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")
    ] = False,
    no_unk47: Annotated[
        bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")
    ] = False,
    grid: Annotated[
        bool, typer.Option("--grid", help="Overlay chunk grid lines")
    ] = False,
    grid_size: Annotated[
        int, typer.Option("--grid-size", help="Grid line thickness in pixels")
    ] = 2,
) -> None:
    """Colour-sample a map top-down (minimap / MiniMapGump style)."""
    args = _build_map_namespace(
        map=map_num,
        fixed=fixed,
        shapes=shapes,
        globs=globs,
        palette=palette,
        scale=scale,
        output=output,
        typeflag=typeflag,
        nonfixed=nonfixed,
        no_fixed=no_fixed,
        no_solid=no_solid,
        no_sea=no_sea,
        no_land=no_land,
        no_occl=no_occl,
        no_bag=no_bag,
        no_damaging=no_damaging,
        no_noisy=no_noisy,
        no_draw=no_draw,
        no_ignore=no_ignore,
        no_roof=no_roof,
        no_transl=no_transl,
        no_editor=no_editor,
        no_explode=no_explode,
        no_unk46=no_unk46,
        no_unk47=no_unk47,
        grid=grid,
        grid_size=grid_size,
        config=None,
    )
    raise SystemExit(cmd_map_sample(args))


def map_sample_all_cmd(
    fixed: Annotated[Optional[str], typer.Option(help="Path to FIXED.DAT")] = None,
    shapes: Annotated[
        Optional[str], typer.Option(help="Directory of extracted .shp shape files")
    ] = None,
    globs: Annotated[
        Optional[str], typer.Option(help="Directory of extracted GLOB .dat files")
    ] = None,
    palette: Annotated[
        Optional[str], typer.Option("--palette", "-p", help="Path to .pal palette file")
    ] = None,
    output: Annotated[
        str, typer.Option("-o", "--output", help="Output directory")
    ] = "map_samples",
    scale: Annotated[
        int, typer.Option("--scale", "-s", help="Default scale when --scales not given")
    ] = 64,
    scales: Annotated[
        Optional[list[int]], typer.Option("--scales", help="One or more scales")
    ] = None,
    maps: Annotated[
        Optional[list[int]], typer.Option("--maps", help="Map numbers to sample")
    ] = None,
    typeflag: Annotated[
        Optional[str], typer.Option(help="Path to TYPEFLAG.DAT")
    ] = None,
    nonfixed: Annotated[
        Optional[str], typer.Option(help="Path to U8SAVE.000 or raw NONFIXED.DAT")
    ] = None,
    no_fixed: Annotated[
        bool, typer.Option("--no-fixed", help="Exclude SI_FIXED")
    ] = False,
    no_solid: Annotated[
        bool, typer.Option("--no-solid", help="Exclude SI_SOLID")
    ] = False,
    no_sea: Annotated[bool, typer.Option("--no-sea", help="Exclude SI_SEA")] = False,
    no_land: Annotated[bool, typer.Option("--no-land", help="Exclude SI_LAND")] = False,
    no_occl: Annotated[bool, typer.Option("--no-occl", help="Exclude SI_OCCL")] = False,
    no_bag: Annotated[bool, typer.Option("--no-bag", help="Exclude SI_BAG")] = False,
    no_damaging: Annotated[
        bool, typer.Option("--no-damaging", help="Exclude SI_DAMAGING")
    ] = False,
    no_noisy: Annotated[
        bool, typer.Option("--no-noisy", help="Exclude SI_NOISY")
    ] = False,
    no_draw: Annotated[bool, typer.Option("--no-draw", help="Exclude SI_DRAW")] = False,
    no_ignore: Annotated[
        bool, typer.Option("--no-ignore", help="Exclude SI_IGNORE")
    ] = False,
    no_roof: Annotated[bool, typer.Option("--no-roof", help="Exclude SI_ROOF")] = False,
    no_transl: Annotated[
        bool, typer.Option("--no-transl", help="Exclude SI_TRANSL")
    ] = False,
    no_editor: Annotated[
        bool, typer.Option("--no-editor", help="Exclude SI_EDITOR")
    ] = False,
    no_explode: Annotated[
        bool, typer.Option("--no-explode", help="Exclude SI_EXPLODE")
    ] = False,
    no_unk46: Annotated[
        bool, typer.Option("--no-unk46", help="Exclude SI_UNKNOWN46")
    ] = False,
    no_unk47: Annotated[
        bool, typer.Option("--no-unk47", help="Exclude SI_UNKNOWN47")
    ] = False,
    grid: Annotated[
        bool, typer.Option("--grid", help="Overlay chunk grid lines")
    ] = False,
    grid_size: Annotated[
        int, typer.Option("--grid-size", help="Grid line thickness in pixels")
    ] = 2,
) -> None:
    """Colour-sample all (or selected) maps at one or more scales."""
    args = _build_map_namespace(
        fixed=fixed,
        shapes=shapes,
        globs=globs,
        palette=palette,
        output=output,
        scale=scale,
        scales=scales,
        maps=maps,
        typeflag=typeflag,
        nonfixed=nonfixed,
        no_fixed=no_fixed,
        no_solid=no_solid,
        no_sea=no_sea,
        no_land=no_land,
        no_occl=no_occl,
        no_bag=no_bag,
        no_damaging=no_damaging,
        no_noisy=no_noisy,
        no_draw=no_draw,
        no_ignore=no_ignore,
        no_roof=no_roof,
        no_transl=no_transl,
        no_editor=no_editor,
        no_explode=no_explode,
        no_unk46=no_unk46,
        no_unk47=no_unk47,
        grid=grid,
        grid_size=grid_size,
        config=None,
    )
    raise SystemExit(cmd_map_sample_all(args))
