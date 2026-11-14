"""``titan u9 model-*`` / ``dimension-*`` — 3D model and model geometry table commands."""

from __future__ import annotations

__all__ = [
    "model_info_cmd",
    "model_material_report_cmd",
    "model_export_cmd",
    "model_export_all_cmd",
    "dimension_info_cmd",
    "dimension_show_cmd",
    "dimension_csv_cmd",
]

import csv
import math
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.asset_reports import (
    MODEL_REPORT_COLUMNS,
    U9AssetReportError,
    build_model_material_report,
    write_dynamic_report,
)
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.mesh_export import MeshExportError, export_obj, export_stl
from titan.u9.model import U9Model, U9ModelError
from titan.u9.model_geometry import (
    MODEL_SLOT_COUNT,
    U9ModelGeometryRecord,
    U9ModelGeometryTable,
    U9ModelGeometryTableError,
)
from titan.u9.model_naming import label_for_model, names_for_model
from titan.u9.object_placement import U9SappearModelSource
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat, U9TypesDatError
from titan.u9.cli import _common


def _load_naming(types_path: Optional[str], typenames_path: Optional[str]):
    """Returns (U9TypesDat, U9TypeNames) if both paths are given, else None.

    Naming is optional decoration, so a bad path or a file that is not
    really a TYPES.DAT warns and falls back to unnamed output rather than
    failing the export.
    """
    if not types_path or not typenames_path:
        return None
    try:
        return U9TypesDat.from_file(types_path), U9TypeNames.from_file(typenames_path)
    except (U9TypesDatError, U9FlxArchiveError, OSError) as e:
        print(
            f"WARNING: could not load type names ({e}); continuing without them",
            file=sys.stderr,
        )
        return None


def cmd_model_info(args: SimpleNamespace) -> int:
    """Print a model's limb/LOD/material/texture summary."""
    if not os.path.isfile(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        return 1

    try:
        model = _common._load_model(args.file, args.model_id)
    except (U9FlxArchiveError, U9ModelError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    naming = _load_naming(args.types, args.typenames)
    if naming is not None:
        types, typenames = naming
        names = names_for_model(model.model_id, types, typenames)
        if names:
            print(f"model {model.model_id}: possible name(s): {', '.join(names)}")
        else:
            print(f"model {model.model_id}: no named type claims this model")

    print(
        f"model {model.model_id}: {len(model.limbs)} limb(s), {model.record_format} record"
    )
    print(f"  bounds: {model.min_bounds} .. {model.max_bounds}")
    print(f"  sphere: center={model.sphere_center} radius={model.sphere_radius:.2f}")
    print(f"  lod_thresholds: {model.lod_thresholds}")
    print()
    print(
        f"{'Limb':>6}  {'Parent':>6}  {'Root':>5}  {'Position':<30}  "
        "LOD render t/v/m [+ mount mt/mv] (texture IDs)"
    )
    print("-" * 100)
    for limb in model.limbs:
        lod_summaries = []
        for lod in limb.lods:
            if lod is None:
                lod_summaries.append("-")
                continue
            tex_ids = sorted(
                {m.texture_id for m in lod.materials if not m.is_invisible}
            )
            mounts = (
                f" + {len(lod.connection_triangles)}ct/{len(lod.connection_vertices)}cv"
                if lod.connection_triangles or lod.connection_vertices
                else ""
            )
            lod_summaries.append(
                f"{len(lod.triangles)}t/{len(lod.vertices)}v/{len(lod.materials)}m"
                f"{mounts} {tex_ids}"
            )
        pos = tuple(round(v, 2) for v in limb.position)
        print(
            f"{limb.limb_id:>6}  {limb.parent_id:>6}  {str(limb.is_root):>5}  {str(pos):<30}  "
            + " | ".join(lod_summaries)
        )
    nonfinite_uv_corners = sum(
        not all(math.isfinite(value) for value in corner.uv)
        for limb in model.limbs
        for lod in limb.lods
        if lod is not None
        for triangle in lod.triangles
        for corner in triangle.corners
    )
    if nonfinite_uv_corners:
        print()
        print(
            f"  WARNING: {nonfinite_uv_corners} triangle corner(s) contain "
            "non-finite UVs; Titan substitutes (0, 0) during OBJ/GLB export."
        )
    return 0


def cmd_model_material_report(args: SimpleNamespace) -> int:
    """Export model/material metadata joined to every discovered texture tier."""
    try:
        rows, warnings = build_model_material_report(
            args.source,
            model_id=getattr(args, "model", None),
            textures_path=getattr(args, "textures", None),
            types_path=getattr(args, "types", None),
            typenames_path=getattr(args, "typenames", None),
            only=getattr(args, "only", None),
        )
        output = write_dynamic_report(
            rows,
            args.output,
            args.format,
            preferred_columns=MODEL_REPORT_COLUMNS,
        )
    except (U9AssetReportError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"Wrote {len(rows)} model/material row(s) to {output}")
    return 0


def cmd_model_export(args: SimpleNamespace) -> int:
    """Export one model to OBJ and/or STL, with textures resolved from a texture FLX archive if given."""
    error = _common._validate_model_export_args(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        model = _common._load_model(args.file, args.model_id)
    except (U9FlxArchiveError, U9ModelError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    resolver = _common._make_texture_resolver(args.textures, args.palette)

    naming = _load_naming(args.types, args.typenames)
    label = label_for_model(args.model_id, *naming) if naming is not None else None
    stem = f"model_{args.model_id:05d}" + (f"_{label}" if label else "")

    outdir = args.output or stem
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, stem)

    wrote = []
    try:
        if args.format in ("obj", "both"):
            export_obj(
                model, base + ".obj", lod_level=args.lod, texture_resolver=resolver
            )
            wrote.append(base + ".obj")
        if args.format in ("stl", "both"):
            export_stl(model, base + ".stl", lod_level=args.lod)
            wrote.append(base + ".stl")
    except MeshExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Exported model {args.model_id} (LOD {args.lod}) -> {outdir}/")
    for path in wrote:
        print(f"  {path}")
    if args.format in ("obj", "both") and resolver is None:
        print("  (no --textures given: OBJ materials have no images)")

    if args.preview:
        _common._generate_preview(outdir)
    return 0


def _export_all_one(
    model_id: int,
    blob: bytes,
    outdir: str,
    resolver,
    naming,
    args: SimpleNamespace,
    stats: Counter,
) -> None:
    """One model's worth of ``model-export-all`` work: parse, export, preview. Updates ``stats`` in place."""
    try:
        model = U9Model.parse(blob, model_id=model_id)
    except U9ModelError:
        stats["parse_fail"] += 1
        return

    label = label_for_model(model_id, *naming) if naming is not None else None
    stem = f"model_{model_id:05d}" + (f"_{label}" if label else "")
    if label:
        stats["named"] += 1
    model_dir = os.path.join(outdir, stem)
    os.makedirs(model_dir, exist_ok=True)
    base = os.path.join(model_dir, stem)

    try:
        if args.format in ("obj", "both"):
            export_obj(
                model, base + ".obj", lod_level=args.lod, texture_resolver=resolver
            )
        if args.format in ("stl", "both"):
            export_stl(model, base + ".stl", lod_level=args.lod)
        stats["exported"] += 1
    except MeshExportError:
        stats["no_geometry"] += 1
        os.rmdir(model_dir)  # nothing was written into it
        return

    if (
        not args.preview
        or args.format not in ("obj", "both")
        or stats["preview_unavailable"]
    ):
        return
    from titan.u9.preview import PreviewError, PreviewUnavailableError, render_preview

    try:
        render_preview(model_dir)
        stats["previewed"] += 1
    except PreviewUnavailableError as e:
        stats["preview_unavailable"] = 1
        print(f"  (skipping all further previews: {e})", flush=True)
    except PreviewError:
        stats["preview_failed"] += 1


def cmd_model_export_all(args: SimpleNamespace) -> int:
    """Export every used model in a sappear.flx archive, same options as model-export, one subfolder each."""
    error = _common._validate_model_export_args(
        SimpleNamespace(
            format=args.format,
            file=args.file,
            textures=args.textures,
            palette=args.palette,
            types=args.types,
            typenames=args.typenames,
        )
    )
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        archive = U9FlxArchive.from_file(args.file)
    except U9FlxArchiveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    resolver = _common._make_texture_resolver(args.textures, args.palette)
    naming = _load_naming(args.types, args.typenames)
    outdir = args.output or "model_export"
    os.makedirs(outdir, exist_ok=True)

    used = archive.used_entry_indices()
    stats: Counter = Counter()

    for i, model_id in enumerate(used):
        if i % 200 == 0:
            print(f"  ... {i}/{len(used)}", flush=True)
        _export_all_one(
            model_id,
            archive.read_entry(model_id),
            outdir,
            resolver,
            naming,
            args,
            stats,
        )

    print()
    print(f"total used models: {len(used)}")
    print(f"parse failures: {stats['parse_fail']}")
    print(f"no visible geometry: {stats['no_geometry']}")
    print(f"exported: {stats['exported']} -> {outdir}/")
    print(f"  of which named: {stats['named']}")
    if args.preview:
        print(f"previews rendered: {stats['previewed']}")
        print(f"preview failures: {stats['preview_failed']}")
    return 0


def _load_model_geometry_table(filepath: str) -> Optional[U9ModelGeometryTable]:
    """Open static/dimension.dat, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9ModelGeometryTable.from_file(filepath)
    except U9ModelGeometryTableError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def _load_optional_model_source(
    filepath: str | None,
) -> U9SappearModelSource | None:
    if filepath is None:
        return None
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9SappearModelSource.from_file(filepath)
    except (OSError, U9FlxArchiveError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def _float_matches(left: float, right: float) -> bool:
    return left == right or (math.isnan(left) and math.isnan(right))


def _geometry_model_differences(
    record: U9ModelGeometryRecord, model: U9Model
) -> tuple[str, ...]:
    differences: list[str] = []
    if not _float_matches(record.culling_radius, model.sphere_radius):
        differences.append("culling_radius")
    if any(
        not _float_matches(stored, current)
        for stored, current in zip(record.culling_center, model.sphere_center)
    ):
        differences.append("culling_center")
    for label, stored_values, current_values in (
        ("bounds_minimum", record.bounds_minimum, model.min_bounds),
        ("bounds_maximum", record.bounds_maximum, model.max_bounds),
    ):
        if any(
            stored is not None and not _float_matches(stored, current)
            for stored, current in zip(stored_values, current_values)
        ):
            differences.append(label)
    return tuple(differences)


def _geometry_model_join(
    record: U9ModelGeometryRecord,
    source: U9SappearModelSource | None,
) -> tuple[str, tuple[str, ...], U9Model | None]:
    if source is None:
        return "not_checked", (), None
    lookup = source.model(record.model_id)
    if lookup.model is None:
        return lookup.status, (), None
    differences = _geometry_model_differences(record, lookup.model)
    return (
        "matches_model" if not differences else "differs_from_model",
        differences,
        lookup.model,
    )


def cmd_dimension_info(args: SimpleNamespace) -> int:
    """Summarize the model-indexed geometry cache in dimension.dat."""
    table = _load_model_geometry_table(args.file)
    if table is None:
        return 1
    source = _load_optional_model_source(args.models)
    if args.models and source is None:
        return 1

    radius_statuses = Counter(record.culling_radius_status for record in table.records)
    storage_statuses = Counter(record.bounds_storage_status for record in table.records)
    warning_ids = table.warning_model_ids()
    print(f"{args.file} -- {MODEL_SLOT_COUNT} model geometry slots")
    print(
        "  radius states        : "
        + ", ".join(
            f"{status}={count}" for status, count in sorted(radius_statuses.items())
        )
    )
    print(
        "  bound storage        : "
        + ", ".join(
            f"{status}={count}" for status, count in sorted(storage_statuses.items())
        )
    )
    print(f"  structural warnings : {len(warning_ids)}")
    if source is not None:
        joins = Counter(
            _geometry_model_join(record, source)[0] for record in table.records
        )
        print(
            "  model comparison     : "
            + ", ".join(f"{status}={count}" for status, count in sorted(joins.items()))
        )
    return 0


def cmd_dimension_show(args: SimpleNamespace) -> int:
    """Show one model ID's gathered geometry values and stored fragments."""
    table = _load_model_geometry_table(args.file)
    if table is None:
        return 1
    source = _load_optional_model_source(args.models)
    if args.models and source is None:
        return 1
    try:
        record = table.record(args.id)
    except IndexError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    warnings = record.structural_warnings()
    join_status, differences, model = _geometry_model_join(record, source)
    print(f"{args.file} -- model geometry {record.model_id}")
    print(
        f"  culling radius={record.culling_radius!r} "
        f"status={record.culling_radius_status}"
    )
    print(f"  culling center={record.culling_center}")
    print(
        f"  bounds minimum={record.bounds_minimum} "
        f"maximum={record.bounds_maximum} storage={record.bounds_storage_status}"
    )
    print("  warnings: " + (", ".join(warnings) if warnings else "none"))
    print(f"  model comparison: {join_status}")
    if differences:
        print(f"  differing fields: {', '.join(differences)}")
    if model is not None:
        print(
            f"  model values: radius={model.sphere_radius!r} "
            f"center={model.sphere_center} bounds={model.min_bounds}..{model.max_bounds}"
        )
    print(
        "  raw fragments: "
        f"radius=0x{record.radius_raw_data.hex()} "
        f"center=0x{record.center_raw_data.hex()} "
        f"minimum=0x{record.minimum_raw_data.hex()} "
        f"maximum=0x{record.maximum_raw_data.hex()}"
    )
    return 0


def cmd_dimension_csv(args: SimpleNamespace) -> int:
    """Export every model geometry slot and its forensic fragments to CSV."""
    table = _load_model_geometry_table(args.file)
    if table is None:
        return 1
    source = _load_optional_model_source(args.models)
    if args.models and source is None:
        return 1

    output = Path(args.output or "dimension_csv")
    try:
        output.mkdir(parents=True, exist_ok=True)
        output_path = output / "u9_dimensions.csv"
        with output_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "model_id",
                    "culling_radius",
                    "culling_radius_status",
                    "culling_center_x",
                    "culling_center_y",
                    "culling_center_z",
                    "bounds_storage_status",
                    "bounds_minimum_x",
                    "bounds_minimum_y",
                    "bounds_minimum_z",
                    "bounds_maximum_x",
                    "bounds_maximum_y",
                    "bounds_maximum_z",
                    "structural_status",
                    "warnings",
                    "model_join_status",
                    "model_differences",
                    "model_culling_radius",
                    "model_culling_center_x",
                    "model_culling_center_y",
                    "model_culling_center_z",
                    "model_bounds_minimum_x",
                    "model_bounds_minimum_y",
                    "model_bounds_minimum_z",
                    "model_bounds_maximum_x",
                    "model_bounds_maximum_y",
                    "model_bounds_maximum_z",
                    "radius_raw_hex",
                    "center_raw_hex",
                    "minimum_raw_hex",
                    "maximum_raw_hex",
                    "stored_fragments_hex",
                ]
            )
            for record in table.records:
                warnings = record.structural_warnings()
                join_status, differences, model = _geometry_model_join(record, source)
                model_values: tuple[object, ...]
                if model is None:
                    model_values = ("",) * 10
                else:
                    model_values = (
                        model.sphere_radius,
                        *model.sphere_center,
                        *model.min_bounds,
                        *model.max_bounds,
                    )
                writer.writerow(
                    [
                        record.model_id,
                        record.culling_radius,
                        record.culling_radius_status,
                        *record.culling_center,
                        record.bounds_storage_status,
                        *(
                            "" if value is None else value
                            for value in record.bounds_minimum
                        ),
                        *(
                            "" if value is None else value
                            for value in record.bounds_maximum
                        ),
                        "ok" if not warnings else "warning",
                        ";".join(warnings),
                        join_status,
                        ";".join(differences),
                        *model_values,
                        f"0x{record.radius_raw_data.hex()}",
                        f"0x{record.center_raw_data.hex()}",
                        f"0x{record.minimum_raw_data.hex()}",
                        f"0x{record.maximum_raw_data.hex()}",
                        record.stored_fragments_hex,
                    ]
                )
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {MODEL_SLOT_COUNT} model geometry rows -> {output_path}")
    return 0


def model_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Model ID (0-7999) to inspect")],
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="Path to static/TYPES.DAT (with --typenames, shows possible name(s))",
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="Path to static/TYPENAME.FLX (with --types, shows possible name(s))",
        ),
    ] = None,
) -> None:
    """Print a model's limb/LOD/material/texture summary."""
    raise SystemExit(
        cmd_model_info(
            SimpleNamespace(
                file=file, model_id=model_id, types=types, typenames=typenames
            )
        )
    )


def model_material_report_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Path to static/sappear.flx or its static directory"),
    ],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output CSV or JSON report path"),
    ],
    model: Annotated[
        Optional[int],
        typer.Option("--model", help="Limit the report to one model ID"),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture archive or directory (default: beside sappear.flx)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option("--types", help="Optional path to static/TYPES.DAT"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option("--typenames", help="Optional path to static/TYPENAME.FLX"),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option("-f", "--format", help="Report format: csv or json"),
    ] = "csv",
    only: Annotated[
        Optional[str],
        typer.Option(
            "--only", help="Filter: animated, textured, unresolved, or errors"
        ),
    ] = None,
) -> None:
    """Export model materials and their per-tier texture/animation metadata."""
    raise SystemExit(
        cmd_model_material_report(
            SimpleNamespace(
                source=source,
                output=output,
                model=model,
                textures=textures,
                types=types,
                typenames=typenames,
                format=fmt,
                only=only,
            )
        )
    )


def model_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Model ID (0-7999) to export")],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--textures",
            help="Path to a texture archive: bitmap16.flx, bitmapsh.flx or "
            "bitmapC.flx -- all three decode, and hold the same textures",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="Path to static/TYPES.DAT (with --typenames, names the output folder/files)",
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="Path to static/TYPENAME.FLX (with --types, names the output folder/files)",
        ),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[
        str, typer.Option("-f", "--format", help="obj, stl, or both")
    ] = "obj",
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: model_<id>[_<name>]/)"
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            "--preview/--no-preview",
            help="Also render a preview.png (requires pyvista; needs a textured OBJ, camera auto-fit)",
        ),
    ] = True,
) -> None:
    """Export one model to OBJ+MTL(+PNG textures) and/or STL."""
    raise SystemExit(
        cmd_model_export(
            SimpleNamespace(
                file=file,
                model_id=model_id,
                textures=textures,
                palette=palette,
                types=types,
                typenames=typenames,
                lod=lod,
                format=fmt,
                output=output,
                preview=preview,
            )
        )
    )


def model_export_all_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "-t",
            "--textures",
            help="Path to a texture archive: bitmap16.flx, bitmapsh.flx or "
            "bitmapC.flx -- all three decode, and hold the same textures",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to static/ankh.pal -- colors 8-bit textures (default: flat grayscale)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="Path to static/TYPES.DAT (with --typenames, names each output folder/files)",
        ),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="Path to static/TYPENAME.FLX (with --types, names each output folder/files)",
        ),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[
        str, typer.Option("-f", "--format", help="obj, stl, or both")
    ] = "obj",
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: model_export/)"
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            "--preview/--no-preview",
            help="Also render a preview.png for each model (requires pyvista)",
        ),
    ] = True,
) -> None:
    """Export every used model in sappear.flx (one subfolder each), same options as model-export."""
    raise SystemExit(
        cmd_model_export_all(
            SimpleNamespace(
                file=file,
                textures=textures,
                palette=palette,
                types=types,
                typenames=typenames,
                lod=lod,
                format=fmt,
                output=output,
                preview=preview,
            )
        )
    )


def dimension_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/dimension.dat")],
    models: Annotated[
        Optional[str],
        typer.Option("--models", help="Optional static/sappear.flx comparison"),
    ] = None,
) -> None:
    """Summarize U9 model culling geometry and stored bound coverage."""
    raise SystemExit(cmd_dimension_info(SimpleNamespace(file=file, models=models)))


def dimension_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/dimension.dat")],
    id: Annotated[int, typer.Argument(help="Model ID")],
    models: Annotated[
        Optional[str],
        typer.Option("--models", help="Optional static/sappear.flx comparison"),
    ] = None,
) -> None:
    """Show one U9 model's cached culling geometry and raw fragments."""
    raise SystemExit(
        cmd_dimension_show(SimpleNamespace(file=file, id=id, models=models))
    )


def dimension_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/dimension.dat")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory for the CSV file"),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option("--models", help="Optional static/sappear.flx comparison"),
    ] = None,
) -> None:
    """Export lossless U9 model geometry and optional model comparisons."""
    raise SystemExit(
        cmd_dimension_csv(SimpleNamespace(file=file, output=output, models=models))
    )
