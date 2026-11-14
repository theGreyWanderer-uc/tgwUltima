"""``titan u9 map-*`` — region map rendering, atlas and GLB export commands."""

from __future__ import annotations

__all__ = ["map_atlas_cmd", "map_render_cmd", "map_export_glb_cmd", "map_render_3d_cmd"]

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional, cast

import typer

from titan.u9.flx_archive import U9FlxArchiveError
from titan.u9.fixed import U9FixedError
from titan.u9.map_atlas import U9MapAtlasError, discover_region_files, render_map_atlas
from titan.u9.map_render import (
    MAX_MAP_PIXELS_PER_CELL,
    U9MapRenderError,
    U9MapTextureSource,
    render_region_map,
    resolve_topdown_pixels_per_cell,
)
from titan.u9.nonfixed import U9NonfixedError
from titan.u9.object_placement import (
    U9ObjectFootprintFilter,
    U9ObjectPlacementError,
    U9SappearModelSource,
)
from titan.u9.region_scene import U9RegionScene, U9RegionSceneError
from titan.u9.region_glb import (
    DEFAULT_U9_GLB_SCALE,
    U9CellRegion,
    U9GlbExportError,
    export_region_glb,
)
from titan.u9.region_vtk import (
    MAX_VTK_RENDER_EDGE,
    U9VtkRenderError,
    render_region_glb,
    resolve_vtk_render_size,
)
from titan.u9.terrain import U9TerrainError
from titan.u9.types_dat import U9TypesDat, U9TypesDatError
from titan.u9.cli import _common


def cmd_map_atlas(args: SimpleNamespace) -> int:
    """Render a labelled, numerically ordered catalogue of U9 regions."""
    resolution = getattr(args, "resolution", "full")
    explicit_pixels = getattr(args, "pixels_per_cell", None)
    try:
        args.pixels_per_cell = resolve_topdown_pixels_per_cell(
            resolution, explicit_pixels
        )
    except U9MapRenderError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    effective_resolution = "custom" if explicit_pixels is not None else resolution
    object_meshes = getattr(args, "objects", False)
    object_lod = getattr(args, "object_lod", 0)
    needs_models = args.object_footprints or object_meshes
    static_directory = Path(args.static)
    runtime_directory = Path(args.runtime) if args.runtime else None
    if not static_directory.is_dir():
        print(f"ERROR: Static directory not found: {static_directory}", file=sys.stderr)
        return 1
    if runtime_directory is not None and not runtime_directory.is_dir():
        print(
            f"ERROR: Runtime directory not found: {runtime_directory}",
            file=sys.stderr,
        )
        return 1

    textures_path = args.textures
    if textures_path is None:
        match = _common._find_case_insensitive_file(static_directory, "bitmap16.flx")
        textures_path = str(match) if match is not None else None
    if textures_path is None or not os.path.isfile(textures_path):
        print(
            "ERROR: bitmap16.flx was not found in the static directory; "
            "pass --textures",
            file=sys.stderr,
        )
        return 1

    models_path = args.models
    types_path = args.types
    try:
        sources = discover_region_files(
            static_directory,
            runtime_directory=runtime_directory,
            region_ids=tuple(args.region_ids or ()),
        )
    except U9MapAtlasError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if needs_models:
        if models_path is None:
            match = _common._find_case_insensitive_file(static_directory, "sappear.flx")
            models_path = str(match) if match is not None else None
        if models_path is None or not os.path.isfile(models_path):
            print(
                "ERROR: sappear.flx was not found in the static directory; "
                "pass --models",
                file=sys.stderr,
            )
            return 1
        if any(source.fixed_path is not None for source in sources):
            if types_path is None:
                match = _common._find_case_insensitive_file(
                    static_directory, "TYPES.DAT"
                )
                types_path = str(match) if match is not None else None
            if types_path is None or not os.path.isfile(types_path):
                print(
                    "ERROR: TYPES.DAT was not found in the static directory; "
                    "pass --types",
                    file=sys.stderr,
                )
                return 1

    output_directory = Path(args.output or "u9_map_atlas")
    try:
        textures = U9MapTextureSource.from_file(
            textures_path,
            palette_path=args.palette,
            sdinfo_path=args.sdinfo,
        )
        object_models = (
            U9SappearModelSource.from_file(models_path)
            if needs_models and models_path is not None
            else None
        )
        object_types = (
            U9TypesDat.from_file(types_path)
            if needs_models and types_path is not None
            else None
        )
        result = render_map_atlas(
            sources,
            textures,
            output_directory,
            thumbnail_size=args.thumbnail_size,
            columns=args.columns,
            pixels_per_cell=args.pixels_per_cell,
            hillshade=args.hillshade,
            hillshade_strength=args.hillshade_strength,
            water=args.water,
            water_frame=args.water_frame,
            fixed_markers=args.fixed_markers,
            fixed_marker_radius=args.fixed_marker_radius,
            nonfixed_markers=args.nonfixed_markers,
            nonfixed_marker_radius=args.nonfixed_marker_radius,
            include_unlinked_nonfixed=args.include_unlinked_nonfixed,
            object_meshes=object_meshes,
            object_mesh_models=object_models if object_meshes else None,
            object_textures=textures if object_meshes else None,
            object_lod=object_lod,
            object_footprints=args.object_footprints,
            object_models=object_models,
            object_types=object_types,
            object_footprint_source=args.object_footprint_source,
            object_type_ids=tuple(args.object_type_ids or ()),
            object_model_ids=tuple(args.object_model_ids or ()),
            object_footprint_style=args.object_footprint_style,
            cell_grid=args.cell_grid,
            tile_grid=args.tile_grid,
            tile_coordinates=args.tile_coordinates,
            chunk_labels=args.chunk_labels,
            flip_y=args.flip_y,
            continue_on_error=not args.strict,
        )
    except (
        OSError,
        U9MapAtlasError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
        U9FlxArchiveError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    metadata = Path(args.metadata) if args.metadata else output_directory / "atlas.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    manifest = result.manifest()
    manifest["sources"] = {
        "static_directory": str(static_directory.resolve()),
        "runtime_directory": (
            str(runtime_directory.resolve()) if runtime_directory else None
        ),
        "textures": str(Path(textures_path).resolve()),
        "palette": (
            str(textures.palette_path.resolve()) if textures.palette_path else None
        ),
        "sdinfo": str(textures.sdinfo_path.resolve()) if textures.sdinfo_path else None,
        "models": str(Path(models_path).resolve()) if models_path else None,
        "types": str(Path(types_path).resolve()) if types_path else None,
    }
    manifest["rendering"] = {
        "resolution": effective_resolution,
        "pixels_per_cell": args.pixels_per_cell,
        "hillshade": args.hillshade,
        "hillshade_strength": args.hillshade_strength,
        "water": args.water,
        "water_frame": args.water_frame,
        "fixed_markers": args.fixed_markers,
        "fixed_marker_radius": args.fixed_marker_radius,
        "nonfixed_markers": args.nonfixed_markers,
        "nonfixed_marker_radius": args.nonfixed_marker_radius,
        "include_unlinked_nonfixed": args.include_unlinked_nonfixed,
        "objects": object_meshes,
        "object_lod": object_lod,
        "object_footprints": args.object_footprints,
        "object_footprint_source": args.object_footprint_source,
        "object_type_ids": list(args.object_type_ids or ()),
        "object_model_ids": list(args.object_model_ids or ()),
        "object_footprint_style": args.object_footprint_style,
        "cell_grid": args.cell_grid,
        "tile_grid": args.tile_grid,
        "tile_coordinates": args.tile_coordinates,
        "chunk_labels": args.chunk_labels,
        "flip_y": args.flip_y,
    }
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(
        f"Rendered {diagnostics.rendered_regions}/{diagnostics.requested_regions} "
        f"region(s) -> {result.atlas_path}"
    )
    print(f"  Manifest         : {metadata}")
    print(f"  Region previews  : {result.regions_directory}")
    print(
        f"  Fixed/nonfixed   : {diagnostics.regions_with_fixed}/"
        f"{diagnostics.regions_with_nonfixed} region(s)"
    )
    print(f"  Missing textures : {diagnostics.regions_with_missing_textures} region(s)")
    for record in result.regions:
        if record.error:
            print(f"  FAILED region {record.region_id}: {record.error}")
    if diagnostics.failed_regions:
        print(
            f"  Render failures  : {diagnostics.failed_regions} "
            f"({'strict mode disabled' if not args.strict else 'strict mode enabled'})"
        )
    print("  Ordering         : numeric region ID; geographic adjacency not inferred")
    return 0


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render terrain with decoded textures and optional object placements."""
    resolution = getattr(args, "resolution", "full")
    explicit_pixels = getattr(args, "pixels_per_cell", None)
    try:
        args.pixels_per_cell = resolve_topdown_pixels_per_cell(
            resolution, explicit_pixels
        )
    except U9MapRenderError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    effective_resolution = "custom" if explicit_pixels is not None else resolution
    object_meshes = getattr(args, "objects", False)
    object_lod = getattr(args, "object_lod", 0)
    object_footprints = getattr(args, "object_footprints", False)
    needs_models = object_footprints or object_meshes
    object_footprint_source = cast(
        Literal["all", "fixed", "nonfixed"],
        getattr(args, "object_footprint_source", "all"),
    )
    object_type_ids = tuple(getattr(args, "object_type_ids", None) or ())
    object_model_ids = tuple(getattr(args, "object_model_ids", None) or ())
    object_footprint_style = cast(
        Literal["outline", "fill"],
        getattr(args, "object_footprint_style", "outline"),
    )
    object_legend = getattr(args, "object_legend", True)
    models_path = getattr(args, "models", None)
    types_path = getattr(args, "types", None)
    for label, path in (
        ("Terrain", args.terrain),
        ("Fixed", args.fixed),
        ("Nonfixed", args.nonfixed),
        ("Models", models_path),
        ("Types", types_path),
    ):
        if path is not None and not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 1

    textures_path = args.textures
    if textures_path is None:
        terrain_dir = Path(args.terrain).resolve().parent
        textures_match = _common._find_case_insensitive_file(
            terrain_dir, "bitmap16.flx"
        )
        textures_path = str(textures_match) if textures_match is not None else None
    if textures_path is None or not os.path.isfile(textures_path):
        print(
            "ERROR: bitmap16.flx was not found beside the terrain file; "
            "pass --textures",
            file=sys.stderr,
        )
        return 1

    terrain_dir = Path(args.terrain).resolve().parent
    if needs_models:
        if args.fixed is None and args.nonfixed is None:
            print(
                "ERROR: --objects/--object-footprints requires --fixed or --nonfixed",
                file=sys.stderr,
            )
            return 1
        if models_path is None:
            models_match = _common._find_case_insensitive_file(
                terrain_dir, "sappear.flx"
            )
            models_path = str(models_match) if models_match is not None else None
        if models_path is None or not os.path.isfile(models_path):
            print(
                "ERROR: sappear.flx was not found beside the terrain file; "
                "pass --models",
                file=sys.stderr,
            )
            return 1
        if args.fixed is not None and types_path is None:
            types_match = _common._find_case_insensitive_file(terrain_dir, "TYPES.DAT")
            types_path = str(types_match) if types_match is not None else None
        if args.fixed is not None and (
            types_path is None or not os.path.isfile(types_path)
        ):
            print(
                "ERROR: TYPES.DAT was not found beside the terrain file; pass --types",
                file=sys.stderr,
            )
            return 1

    try:
        scene = U9RegionScene.from_files(
            args.terrain,
            fixed_path=args.fixed,
            nonfixed_path=args.nonfixed,
        )
        textures = U9MapTextureSource.from_file(
            textures_path,
            palette_path=args.palette,
            sdinfo_path=args.sdinfo,
        )
        object_models = (
            U9SappearModelSource.from_file(models_path)
            if needs_models and models_path is not None
            else None
        )
        object_types = (
            U9TypesDat.from_file(types_path)
            if needs_models and types_path is not None
            else None
        )
        result = render_region_map(
            scene,
            textures,
            pixels_per_cell=args.pixels_per_cell,
            hillshade=args.hillshade,
            hillshade_strength=args.hillshade_strength,
            water=args.water,
            water_frame=args.water_frame,
            fixed_markers=args.fixed_markers,
            fixed_marker_radius=args.fixed_marker_radius,
            nonfixed_markers=args.nonfixed_markers,
            nonfixed_marker_radius=args.nonfixed_marker_radius,
            include_unlinked_nonfixed=args.include_unlinked_nonfixed,
            object_meshes=object_meshes,
            object_mesh_models=object_models if object_meshes else None,
            object_textures=textures if object_meshes else None,
            object_lod=object_lod,
            object_footprints=object_footprints,
            object_models=object_models,
            object_types=object_types,
            object_footprint_source=object_footprint_source,
            object_type_ids=object_type_ids,
            object_model_ids=object_model_ids,
            object_footprint_style=object_footprint_style,
            object_legend=object_legend,
            flip_y=args.flip_y,
        )
    except (
        OSError,
        U9FixedError,
        U9NonfixedError,
        U9TerrainError,
        U9RegionSceneError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
        U9FlxArchiveError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else Path(f"{args.terrain}_map.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(output)
    metadata = Path(args.metadata) if args.metadata else output.with_suffix(".json")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    report = result.diagnostics.to_dict()
    report.update(
        {
            "resolution": effective_resolution,
            "terrain_file": str(Path(args.terrain).resolve()),
            "fixed_file": str(Path(args.fixed).resolve()) if args.fixed else None,
            "nonfixed_file": (
                str(Path(args.nonfixed).resolve()) if args.nonfixed else None
            ),
            "object_model_file": (
                str(Path(models_path).resolve()) if models_path else None
            ),
            "object_types_file": (
                str(Path(types_path).resolve()) if types_path else None
            ),
            "texture_file": str(textures.archive_path.resolve()),
            "palette_file": (
                str(textures.palette_path.resolve()) if textures.palette_path else None
            ),
            "sdinfo_file": (
                str(textures.sdinfo_path.resolve()) if textures.sdinfo_path else None
            ),
        }
    )
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(
        f"Rendered {diagnostics.terrain_name or '(unnamed)'}: "
        f"{diagnostics.image_width}x{diagnostics.image_height} -> {output}"
    )
    print(f"  Metadata        : {metadata}")
    print(f"  Texture keys    : {diagnostics.texture_keys}")
    print(
        f"  Missing textures: {len(diagnostics.missing_texture_keys)} key(s), "
        f"{diagnostics.missing_texture_cells} cell(s)"
    )
    if diagnostics.water_enabled:
        print(
            f"  Global water    : Z {diagnostics.water_level}, "
            f"texture {diagnostics.water_texture_id} frame {diagnostics.water_frame}"
        )
        print(
            f"  Water coverage  : {diagnostics.water_visible_cells} cell(s), "
            f"{diagnostics.water_visible_pixels} output pixel(s)"
        )
        print(
            f"  Water texture   : "
            f"{'MISSING (diagnostic magenta)' if diagnostics.water_texture_missing else 'decoded'}"
        )
    if args.fixed:
        print(
            f"  Fixed objects   : {diagnostics.fixed_objects} "
            f"({diagnostics.fixed_objects_in_bounds} in bounds, "
            f"{diagnostics.fixed_objects_out_of_bounds} outside)"
        )
        print(f"  Chunk mismatches: {diagnostics.fixed_chunk_position_mismatches}")
    if args.nonfixed:
        print(f"  Nonfixed indexed: {diagnostics.nonfixed_indexed_entities}")
        print(
            f"  Unlinked records : {diagnostics.nonfixed_unlinked_entities} "
            f"({'included' if args.include_unlinked_nonfixed else 'excluded'} from markers)"
        )
        print(f"  Markers drawn    : {diagnostics.nonfixed_markers_drawn}")
        print(
            f"  Known allocated : {diagnostics.nonfixed_allocated_entities} "
            f"({diagnostics.nonfixed_entities_in_bounds} in bounds, "
            f"{diagnostics.nonfixed_entities_out_of_bounds} outside)"
        )
        print(
            "  Chunk mismatches: "
            f"{diagnostics.nonfixed_chunk_position_mismatches} nonfixed"
        )
        print(f"  Incomplete chunks: {diagnostics.nonfixed_incomplete_chunks}")
    if diagnostics.object_footprints_enabled:
        print(
            f"  Model footprints: {diagnostics.object_footprints_drawn} shown / "
            f"{diagnostics.object_footprints_resolved_total} resolved "
            f"({diagnostics.object_footprints_filtered_out} filtered)"
        )
        print(
            f"  Displayed models: {len(diagnostics.object_model_ids_drawn)} distinct; "
            f"source={diagnostics.object_footprint_source_filter}, "
            f"style={diagnostics.object_footprint_style}"
        )
        if args.fixed:
            print(
                f"  Fixed resolved  : {diagnostics.fixed_footprints_resolved} "
                f"({diagnostics.fixed_footprints_without_model} type(s) without a model, "
                f"{diagnostics.fixed_footprints_unresolved} unresolved)"
            )
        if args.nonfixed:
            print(
                f"  Nonfixed resolved: {diagnostics.nonfixed_footprints_resolved} "
                f"({diagnostics.nonfixed_footprints_unresolved} unresolved)"
            )
        if diagnostics.missing_object_model_ids:
            print(
                "  Missing model IDs: "
                + ", ".join(
                    str(value) for value in diagnostics.missing_object_model_ids
                )
            )
        if diagnostics.malformed_object_model_ids:
            print(
                "  Malformed models : "
                + ", ".join(
                    str(value) for value in diagnostics.malformed_object_model_ids
                )
            )
    if diagnostics.object_meshes_enabled:
        print(
            f"  Object meshes   : {diagnostics.object_mesh_placements_drawn} drawn / "
            f"{diagnostics.object_mesh_placements_selected} selected at LOD "
            f"{diagnostics.object_mesh_lod}"
        )
        print(
            f"  Mesh triangles  : {diagnostics.object_mesh_triangles_drawn} visible / "
            f"{diagnostics.object_mesh_triangles_considered} considered; "
            f"{diagnostics.object_mesh_pixels_drawn} pixel writes"
        )
        if diagnostics.missing_object_texture_keys:
            print(
                "  Object textures : "
                f"{len(diagnostics.missing_object_texture_keys)} missing frame(s)"
            )
    return 0


def cmd_map_export_glb(args: SimpleNamespace) -> int:
    """Export textured terrain, water, and placed models as a Y-up GLB."""
    models_path = getattr(args, "models", None)
    types_path = getattr(args, "types", None)
    for label, path in (
        ("Terrain", args.terrain),
        ("Fixed", args.fixed),
        ("Nonfixed", args.nonfixed),
        ("Models", models_path),
        ("Types", types_path),
    ):
        if path is not None and not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 1

    terrain_dir = Path(args.terrain).resolve().parent
    textures_path = args.textures
    if textures_path is None:
        match = _common._find_case_insensitive_file(terrain_dir, "bitmap16.flx")
        textures_path = str(match) if match is not None else None
    if textures_path is None or not os.path.isfile(textures_path):
        print(
            "ERROR: bitmap16.flx was not found beside the terrain file; "
            "pass --textures",
            file=sys.stderr,
        )
        return 1

    has_object_input = args.fixed is not None or args.nonfixed is not None
    if args.objects and has_object_input:
        if models_path is None:
            match = _common._find_case_insensitive_file(terrain_dir, "sappear.flx")
            models_path = str(match) if match is not None else None
        if models_path is None or not os.path.isfile(models_path):
            print(
                "ERROR: sappear.flx was not found beside the terrain file; "
                "pass --models",
                file=sys.stderr,
            )
            return 1
        if args.fixed is not None and types_path is None:
            match = _common._find_case_insensitive_file(terrain_dir, "TYPES.DAT")
            types_path = str(match) if match is not None else None
        if args.fixed is not None and (
            types_path is None or not os.path.isfile(types_path)
        ):
            print(
                "ERROR: TYPES.DAT was not found beside the terrain file; pass --types",
                file=sys.stderr,
            )
            return 1

    output = Path(args.output) if args.output else Path(f"{args.terrain}_map.glb")
    try:
        scene = U9RegionScene.from_files(
            args.terrain,
            fixed_path=args.fixed,
            nonfixed_path=args.nonfixed,
        )
        textures = U9MapTextureSource.from_file(
            textures_path,
            palette_path=args.palette,
            sdinfo_path=args.sdinfo,
        )
        cell_region = U9CellRegion.parse(args.cell_region) if args.cell_region else None
        model_source = (
            U9SappearModelSource.from_file(models_path)
            if args.objects and has_object_input and models_path is not None
            else None
        )
        object_types = (
            U9TypesDat.from_file(types_path)
            if args.objects and args.fixed is not None and types_path is not None
            else None
        )
        object_filter = U9ObjectFootprintFilter(
            source=args.object_source,
            type_ids=frozenset(args.object_type or ()),
            model_ids=frozenset(args.object_model or ()),
        )
        result = export_region_glb(
            scene,
            textures,
            output,
            cell_region=cell_region,
            include_terrain=args.terrain_layer,
            include_water=args.water,
            water_frame=args.water_frame,
            include_objects=args.objects,
            object_models=model_source,
            object_types=object_types,
            object_filter=object_filter,
            include_unlinked_nonfixed=args.include_unlinked_nonfixed,
            lod_level=args.lod,
            coordinate_scale=args.coordinate_scale,
        )
    except (
        OSError,
        U9FixedError,
        U9NonfixedError,
        U9TerrainError,
        U9RegionSceneError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
        U9FlxArchiveError,
        U9GlbExportError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    metadata = Path(args.metadata) if args.metadata else output.with_suffix(".json")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    manifest = result.manifest()
    manifest["sources"] = {
        "terrain": str(Path(args.terrain).resolve()),
        "fixed": str(Path(args.fixed).resolve()) if args.fixed else None,
        "nonfixed": str(Path(args.nonfixed).resolve()) if args.nonfixed else None,
        "models": str(Path(models_path).resolve()) if models_path else None,
        "types": str(Path(types_path).resolve()) if types_path else None,
        "textures": str(Path(textures_path).resolve()),
        "palette": (
            str(textures.palette_path.resolve()) if textures.palette_path else None
        ),
        "sdinfo": (
            str(textures.sdinfo_path.resolve()) if textures.sdinfo_path else None
        ),
    }
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(
        f"Exported {diagnostics.terrain_name or '(unnamed)'} cells "
        f"{diagnostics.cell_region} -> {result.glb_path}"
    )
    print(f"  Manifest         : {metadata}")
    print(
        f"  Terrain          : {diagnostics.terrain_cells_exported} cell(s), "
        f"{diagnostics.terrain_triangles} triangle(s), "
        f"{diagnostics.terrain_materials} material(s)"
    )
    if diagnostics.water_enabled:
        print(
            f"  Water            : surface Z {diagnostics.water_surface_z:g} "
            f"(source {diagnostics.water_level}, "
            f"epsilon +{diagnostics.water_surface_epsilon:g}), "
            f"{diagnostics.water_triangles} triangle(s)"
        )
    if diagnostics.objects_enabled:
        print(
            f"  Objects          : {diagnostics.object_placements_exported} exported / "
            f"{diagnostics.object_placements_in_region} selected in region, "
            f"{diagnostics.object_triangles} triangle(s)"
        )
        print(
            f"  Object models    : "
            f"{len(diagnostics.object_model_ids_exported)} distinct"
        )
        print(
            f"  Object meshes    : {diagnostics.object_meshes_exported} shared mesh(es) / "
            f"{diagnostics.object_parts_exported} placement part node(s)"
        )
        if diagnostics.object_uv_corners_sanitized:
            print(
                f"  Sanitized UVs    : {diagnostics.object_uv_corners_sanitized} corner(s) "
                f"in model(s) {diagnostics.object_model_ids_with_sanitized_uvs}"
            )
    print(
        f"  Scene geometry   : {diagnostics.geometry_meshes} mesh(es) / "
        f"{diagnostics.geometry_nodes} node(s)"
    )
    if diagnostics.missing_texture_keys:
        print(
            f"  Missing textures : {len(diagnostics.missing_texture_keys)} "
            "(magenta fallback; see manifest)"
        )
    return 0


def cmd_map_render_3d(args: SimpleNamespace) -> int:
    """Render a Titan U9 region GLB with the south-high orthographic camera."""
    scene = Path(args.scene)
    if not scene.is_file():
        print(f"ERROR: Scene GLB not found: {scene}", file=sys.stderr)
        return 1
    output = (
        Path(args.output)
        if args.output
        else scene.with_name(f"{scene.stem}_south_high.png")
    )
    try:
        width, height = resolve_vtk_render_size(
            getattr(args, "resolution", "full"),
            getattr(args, "width", None),
            getattr(args, "height", None),
        )
        result = render_region_glb(
            scene,
            output,
            width=width,
            height=height,
            fit_margin=args.fit_margin,
            anti_aliasing=args.anti_aliasing,
            texture_filter=args.texture_filter,
            lighting=args.lighting,
            ambient_strength=args.ambient_strength,
            headlight_intensity=args.headlight_intensity,
            background=args.background,
            background_top=args.background_top,
        )
    except (OSError, U9VtkRenderError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    metadata = Path(args.metadata) if args.metadata else output.with_suffix(".json")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    manifest = result.manifest()
    manifest["sources"] = {"scene_glb": str(scene.resolve())}
    manifest["rendering"] = {
        "resolution": (
            "custom"
            if getattr(args, "width", None) is not None
            or getattr(args, "height", None) is not None
            else getattr(args, "resolution", "full")
        )
    }
    with metadata.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    diagnostics = result.diagnostics
    print(f"Rendered {scene.name} -> {result.image_path}")
    print(f"  Manifest         : {metadata}")
    print(f"  View/projection  : {diagnostics.view} / {diagnostics.projection}")
    print(f"  Output           : {diagnostics.width}x{diagnostics.height}")
    print(
        f"  Actors/textured  : {diagnostics.actor_count}/"
        f"{diagnostics.textured_actor_count}"
    )
    print(
        f"  Renderer         : VTK {diagnostics.vtk_version} / "
        f"{diagnostics.render_window_class}"
    )
    return 0


def map_atlas_cmd(
    static: Annotated[
        str,
        typer.Argument(help="Directory containing terrain.N and fixed.N files"),
    ],
    runtime: Annotated[
        Optional[str],
        typer.Option(
            "--runtime", help="Directory containing matching nonfixed.N files"
        ),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture tier FLX (default: static/bitmap16.flx)",
        ),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option(
            "--models",
            help="sappear.flx for object meshes/footprints (auto-discovered in static)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="TYPES.DAT for fixed model lookup (auto-discovered in static)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette", help="ankh.pal (auto-discovered beside textures)"
        ),
    ] = None,
    sdinfo: Annotated[
        Optional[str],
        typer.Option("--sdinfo", help="Matching sdInfo*.flx (auto-discovered)"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory (default: ./u9_map_atlas)",
        ),
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Manifest path (default: OUTPUT/atlas.json)"),
    ] = None,
    region_ids: Annotated[
        Optional[list[int]],
        typer.Option(
            "--region",
            min=0,
            help="Region ID to render (repeatable; default: every terrain.N)",
        ),
    ] = None,
    resolution: Annotated[
        Literal["full", "75", "50", "25"],
        typer.Option(
            "--resolution",
            help="2D scale preset: full=28, 75=21, 50=14, 25=7 pixels/cell",
        ),
    ] = "full",
    pixels_per_cell: Annotated[
        Optional[int],
        typer.Option(
            "--pixels-per-cell",
            min=1,
            max=MAX_MAP_PIXELS_PER_CELL,
            help="Explicit detail override for --resolution",
        ),
    ] = None,
    thumbnail_size: Annotated[
        int,
        typer.Option(
            "--thumbnail-size",
            min=32,
            max=1024,
            help="Square map area for each labelled atlas card",
        ),
    ] = 224,
    columns: Annotated[
        int,
        typer.Option("--columns", min=1, max=32, help="Atlas card columns"),
    ] = 6,
    hillshade: Annotated[
        bool,
        typer.Option("--hillshade/--no-hillshade", help="Shade decoded terrain relief"),
    ] = True,
    hillshade_strength: Annotated[
        float,
        typer.Option(
            "--hillshade-strength",
            min=0.0,
            max=1.0,
            help="Relief shading blend",
        ),
    ] = 0.55,
    water: Annotated[
        bool,
        typer.Option("--water/--no-water", help="Render each region's water surface"),
    ] = True,
    water_frame: Annotated[
        int,
        typer.Option("--water-frame", min=0, help="Water texture frame"),
    ] = 0,
    fixed_markers: Annotated[
        bool,
        typer.Option(
            "--fixed-markers/--no-fixed-markers",
            help="Draw fixed-object anchor markers",
        ),
    ] = True,
    fixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--fixed-marker-radius", min=1, help="Fixed marker radius in output pixels"
        ),
    ] = 1,
    nonfixed_markers: Annotated[
        bool,
        typer.Option(
            "--nonfixed-markers/--no-nonfixed-markers",
            help="Draw indexed nonfixed placement markers",
        ),
    ] = True,
    nonfixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--nonfixed-marker-radius",
            min=1,
            help="Nonfixed marker radius in output pixels",
        ),
    ] = 1,
    include_unlinked_nonfixed: Annotated[
        bool,
        typer.Option(
            "--include-unlinked-nonfixed",
            help="Also draw allocated records absent from the spatial index",
        ),
    ] = False,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects/--no-objects",
            help="Rasterize textured sappear model triangles at object placements",
        ),
    ] = False,
    object_lod: Annotated[
        int,
        typer.Option(
            "--object-lod",
            min=0,
            help="sappear model LOD used by --objects (LOD 0 preserves coverage)",
        ),
    ] = 0,
    object_footprints: Annotated[
        bool,
        typer.Option(
            "--object-footprints/--no-object-footprints",
            help="Draw transformed sappear model bounds",
        ),
    ] = False,
    object_footprint_source: Annotated[
        str,
        typer.Option(
            "--object-source", help="Object source filter: all, fixed, or nonfixed"
        ),
    ] = "all",
    object_type_ids: Annotated[
        Optional[list[int]],
        typer.Option("--object-type", help="Type ID filter (repeatable)"),
    ] = None,
    object_model_ids: Annotated[
        Optional[list[int]],
        typer.Option("--object-model", help="sappear model ID filter (repeatable)"),
    ] = None,
    object_footprint_style: Annotated[
        str,
        typer.Option(
            "--object-footprint-style", help="Footprint style: outline or fill"
        ),
    ] = "outline",
    cell_grid: Annotated[
        bool,
        typer.Option(
            "--cell-grid/--no-cell-grid",
            help="Overlay every terrain-cell boundary (needs 4+ pixels per cell)",
        ),
    ] = False,
    tile_grid: Annotated[
        bool,
        typer.Option(
            "--tile-grid/--no-tile-grid",
            help="Overlay 16x16-cell tile/chunk-placement boundaries",
        ),
    ] = False,
    tile_coordinates: Annotated[
        bool,
        typer.Option(
            "--tile-coordinates/--no-tile-coordinates",
            help=(
                "Label each tile placement with its stored x,y coordinate "
                "and cell origin (needs 4+ pixels per cell)"
            ),
        ),
    ] = False,
    chunk_labels: Annotated[
        bool,
        typer.Option(
            "--chunk-labels/--no-chunk-labels",
            help="Label each tile with its referenced stored chunk ID (needs 2+ pixels per cell)",
        ),
    ] = False,
    flip_y: Annotated[
        bool,
        typer.Option(
            "--flip-y/--no-flip-y",
            help="Invert U9 Y into image rows as the legacy editor does",
        ),
    ] = True,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Stop at the first malformed region instead of making an error card",
        ),
    ] = False,
) -> None:
    """Render all discovered U9 regions as a labelled visual catalogue."""
    raise SystemExit(
        cmd_map_atlas(
            SimpleNamespace(
                static=static,
                runtime=runtime,
                textures=textures,
                models=models,
                types=types,
                palette=palette,
                sdinfo=sdinfo,
                output=output,
                metadata=metadata,
                region_ids=region_ids,
                resolution=resolution,
                pixels_per_cell=pixels_per_cell,
                thumbnail_size=thumbnail_size,
                columns=columns,
                hillshade=hillshade,
                hillshade_strength=hillshade_strength,
                water=water,
                water_frame=water_frame,
                fixed_markers=fixed_markers,
                fixed_marker_radius=fixed_marker_radius,
                nonfixed_markers=nonfixed_markers,
                nonfixed_marker_radius=nonfixed_marker_radius,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                objects=objects,
                object_lod=object_lod,
                object_footprints=object_footprints,
                object_footprint_source=object_footprint_source,
                object_type_ids=object_type_ids,
                object_model_ids=object_model_ids,
                object_footprint_style=object_footprint_style,
                cell_grid=cell_grid,
                tile_grid=tile_grid,
                tile_coordinates=tile_coordinates,
                chunk_labels=chunk_labels,
                flip_y=flip_y,
                strict=strict,
            )
        )
    )


def map_render_cmd(
    terrain: Annotated[
        str, typer.Argument(help="Path to a static/terrain.<region> file")
    ],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture tier FLX (default: adjacent bitmap16.flx)",
        ),
    ] = None,
    fixed: Annotated[
        Optional[str],
        typer.Option("--fixed", help="Matching static/fixed.<region> overlay"),
    ] = None,
    nonfixed: Annotated[
        Optional[str],
        typer.Option(
            "--nonfixed",
            help="Matching runtime or savegame nonfixed.<region> overlay",
        ),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option(
            "--models",
            help="sappear.flx for object meshes/footprints (auto-discovered beside terrain)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="TYPES.DAT for fixed model lookup (auto-discovered beside terrain)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--palette", help="ankh.pal (auto-discovered beside textures)"
        ),
    ] = None,
    sdinfo: Annotated[
        Optional[str],
        typer.Option("--sdinfo", help="Matching sdInfo*.flx (auto-discovered)"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output PNG path")
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Output JSON path (default: beside PNG)"),
    ] = None,
    resolution: Annotated[
        Literal["full", "75", "50", "25"],
        typer.Option(
            "--resolution",
            help="2D scale preset: full=28, 75=21, 50=14, 25=7 pixels/cell",
        ),
    ] = "full",
    pixels_per_cell: Annotated[
        Optional[int],
        typer.Option(
            "--pixels-per-cell",
            min=1,
            max=MAX_MAP_PIXELS_PER_CELL,
            help="Explicit detail override for --resolution",
        ),
    ] = None,
    hillshade: Annotated[
        bool,
        typer.Option("--hillshade/--no-hillshade", help="Shade decoded terrain relief"),
    ] = True,
    hillshade_strength: Annotated[
        float,
        typer.Option(
            "--hillshade-strength",
            min=0.0,
            max=1.0,
            help="Relief shading blend",
        ),
    ] = 0.55,
    water: Annotated[
        bool,
        typer.Option(
            "--water/--no-water",
            help="Render the map-wide water surface from the terrain header",
        ),
    ] = True,
    water_frame: Annotated[
        int,
        typer.Option(
            "--water-frame",
            min=0,
            help="Static frame from water texture entry 49",
        ),
    ] = 0,
    fixed_markers: Annotated[
        bool,
        typer.Option(
            "--fixed-markers/--no-fixed-markers",
            help="Draw fixed-object anchor markers when --fixed is supplied",
        ),
    ] = True,
    fixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--fixed-marker-radius", min=1, help="Fixed marker radius in output pixels"
        ),
    ] = 1,
    nonfixed_markers: Annotated[
        bool,
        typer.Option(
            "--nonfixed-markers/--no-nonfixed-markers",
            help="Draw indexed authored placements when --nonfixed is supplied",
        ),
    ] = True,
    nonfixed_marker_radius: Annotated[
        int,
        typer.Option(
            "--nonfixed-marker-radius",
            min=1,
            help="Nonfixed marker radius in output pixels",
        ),
    ] = 1,
    include_unlinked_nonfixed: Annotated[
        bool,
        typer.Option(
            "--include-unlinked-nonfixed",
            help="Also draw allocated records absent from the spatial index",
        ),
    ] = False,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects/--no-objects",
            help="Rasterize textured sappear model triangles at object placements",
        ),
    ] = False,
    object_lod: Annotated[
        int,
        typer.Option(
            "--object-lod",
            min=0,
            help="sappear model LOD used by --objects (LOD 0 preserves coverage)",
        ),
    ] = 0,
    object_footprints: Annotated[
        bool,
        typer.Option(
            "--object-footprints/--no-object-footprints",
            help="Draw transformed sappear model bounds beneath object anchors",
        ),
    ] = False,
    object_footprint_source: Annotated[
        str,
        typer.Option(
            "--object-source",
            help="Object source filter: all, fixed, or nonfixed",
        ),
    ] = "all",
    object_type_ids: Annotated[
        Optional[list[int]],
        typer.Option(
            "--object-type",
            help="Type ID object filter (repeatable; matches fixed and nonfixed)",
        ),
    ] = None,
    object_model_ids: Annotated[
        Optional[list[int]],
        typer.Option(
            "--object-model",
            help="sappear model ID object filter (repeatable)",
        ),
    ] = None,
    object_footprint_style: Annotated[
        str,
        typer.Option(
            "--object-footprint-style",
            help="Footprint polygon style: outline or fill",
        ),
    ] = "outline",
    object_legend: Annotated[
        bool,
        typer.Option(
            "--object-legend/--no-object-legend",
            help="Embed footprint colours, filters, and display counts",
        ),
    ] = True,
    flip_y: Annotated[
        bool,
        typer.Option(
            "--flip-y/--no-flip-y",
            help="Invert U9 Y into image rows as the legacy editor does",
        ),
    ] = True,
) -> None:
    """Render one textured U9 region with optional object overlays."""
    raise SystemExit(
        cmd_map_render(
            SimpleNamespace(
                terrain=terrain,
                textures=textures,
                fixed=fixed,
                nonfixed=nonfixed,
                models=models,
                types=types,
                palette=palette,
                sdinfo=sdinfo,
                output=output,
                metadata=metadata,
                resolution=resolution,
                pixels_per_cell=pixels_per_cell,
                hillshade=hillshade,
                hillshade_strength=hillshade_strength,
                water=water,
                water_frame=water_frame,
                fixed_markers=fixed_markers,
                fixed_marker_radius=fixed_marker_radius,
                nonfixed_markers=nonfixed_markers,
                nonfixed_marker_radius=nonfixed_marker_radius,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                objects=objects,
                object_lod=object_lod,
                object_footprints=object_footprints,
                object_footprint_source=object_footprint_source,
                object_type_ids=object_type_ids,
                object_model_ids=object_model_ids,
                object_footprint_style=object_footprint_style,
                object_legend=object_legend,
                flip_y=flip_y,
            )
        )
    )


def map_export_glb_cmd(
    terrain: Annotated[
        str, typer.Argument(help="Path to a static/terrain.<region> file")
    ],
    textures: Annotated[
        Optional[str],
        typer.Option(
            "--textures",
            help="Texture tier FLX (default: adjacent bitmap16.flx)",
        ),
    ] = None,
    fixed: Annotated[
        Optional[str],
        typer.Option("--fixed", help="Matching static/fixed.<region> objects"),
    ] = None,
    nonfixed: Annotated[
        Optional[str],
        typer.Option("--nonfixed", help="Matching runtime/save nonfixed.<region>"),
    ] = None,
    models: Annotated[
        Optional[str],
        typer.Option(
            "--models",
            help="sappear.flx (auto-discovered beside terrain for objects)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option(
            "--types",
            help="TYPES.DAT (auto-discovered for fixed-object model lookup)",
        ),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="ankh.pal (auto-discovered)"),
    ] = None,
    sdinfo: Annotated[
        Optional[str],
        typer.Option("--sdinfo", help="Matching sdInfo*.flx (auto-discovered)"),
    ] = None,
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output .glb path")
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Output JSON manifest (default: beside GLB)"),
    ] = None,
    cell_region: Annotated[
        Optional[str],
        typer.Option(
            "--cell-region",
            help="Half-open terrain rectangle x0,y0,x1,y1 (default: full region)",
        ),
    ] = None,
    terrain_layer: Annotated[
        bool,
        typer.Option(
            "--terrain/--no-terrain", help="Include textured terrain geometry"
        ),
    ] = True,
    water: Annotated[
        bool,
        typer.Option("--water/--no-water", help="Include the global water plane"),
    ] = True,
    water_frame: Annotated[
        int,
        typer.Option("--water-frame", min=0, help="Water texture 49 frame"),
    ] = 0,
    objects: Annotated[
        bool,
        typer.Option(
            "--objects/--no-objects",
            help="Include supplied fixed/nonfixed model geometry",
        ),
    ] = True,
    include_unlinked_nonfixed: Annotated[
        bool,
        typer.Option(
            "--include-unlinked-nonfixed",
            help="Also export allocated nonfixed records absent from the index",
        ),
    ] = False,
    object_source: Annotated[
        str,
        typer.Option(
            "--object-source", help="Object source filter: all, fixed, or nonfixed"
        ),
    ] = "all",
    object_type: Annotated[
        Optional[list[int]],
        typer.Option("--object-type", help="Type ID filter (repeatable)"),
    ] = None,
    object_model: Annotated[
        Optional[list[int]],
        typer.Option("--object-model", help="sappear model ID filter (repeatable)"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", min=0, help="Model LOD level")] = 0,
    coordinate_scale: Annotated[
        float,
        typer.Option(
            "--coordinate-scale",
            min=0.000001,
            help="GLB units per native U9 unit (default matches model export)",
        ),
    ] = DEFAULT_U9_GLB_SCALE,
) -> None:
    """Export one textured U9 region rectangle as a Y-up GLB scene."""
    raise SystemExit(
        cmd_map_export_glb(
            SimpleNamespace(
                terrain=terrain,
                textures=textures,
                fixed=fixed,
                nonfixed=nonfixed,
                models=models,
                types=types,
                palette=palette,
                sdinfo=sdinfo,
                output=output,
                metadata=metadata,
                cell_region=cell_region,
                terrain_layer=terrain_layer,
                water=water,
                water_frame=water_frame,
                objects=objects,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                object_source=object_source,
                object_type=object_type,
                object_model=object_model,
                lod=lod,
                coordinate_scale=coordinate_scale,
            )
        )
    )


def map_render_3d_cmd(
    scene: Annotated[
        str,
        typer.Argument(help="Titan map-export-glb scene to render"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    metadata: Annotated[
        Optional[str],
        typer.Option("--metadata", help="Output JSON manifest (default: beside PNG)"),
    ] = None,
    resolution: Annotated[
        Literal["full", "half"],
        typer.Option(
            "--resolution",
            help="Square output preset: full=16384, half=8192",
        ),
    ] = "full",
    width: Annotated[
        Optional[int],
        typer.Option(
            "--width",
            min=1,
            max=MAX_VTK_RENDER_EDGE,
            help="Explicit width override; omitted dimension follows it",
        ),
    ] = None,
    height: Annotated[
        Optional[int],
        typer.Option(
            "--height",
            min=1,
            max=MAX_VTK_RENDER_EDGE,
            help="Explicit height override; omitted dimension follows it",
        ),
    ] = None,
    fit_margin: Annotated[
        float,
        typer.Option(
            "--fit-margin",
            min=1.0,
            help="Padding around projected scene bounds",
        ),
    ] = 1.04,
    anti_aliasing: Annotated[
        Literal["none", "fxaa", "ssaa"],
        typer.Option(
            "--anti-aliasing",
            help="VTK anti-aliasing mode",
        ),
    ] = "fxaa",
    texture_filter: Annotated[
        Literal["nearest", "linear"],
        typer.Option(
            "--texture-filter",
            help="Texture sampling filter (mipmaps remain enabled)",
        ),
    ] = "linear",
    lighting: Annotated[
        bool,
        typer.Option(
            "--lighting/--no-lighting",
            help="Apply VTK's light kit to the imported materials",
        ),
    ] = True,
    ambient_strength: Annotated[
        float,
        typer.Option(
            "--ambient-strength",
            min=0.0,
            max=1.0,
            help="Ambient material contribution when lighting is enabled",
        ),
    ] = 0.3,
    headlight_intensity: Annotated[
        float,
        typer.Option(
            "--headlight-intensity",
            min=0.0,
            help="White camera-headlight intensity",
        ),
    ] = 1.25,
    background: Annotated[
        str,
        typer.Option("--background", help="Bottom background colour"),
    ] = "#0c1118",
    background_top: Annotated[
        str,
        typer.Option("--background-top", help="Top background colour"),
    ] = "#526171",
) -> None:
    """Render a U9 GLB with the south-high orthographic VTK/OpenGL view."""
    raise SystemExit(
        cmd_map_render_3d(
            SimpleNamespace(
                scene=scene,
                output=output,
                metadata=metadata,
                resolution=resolution,
                width=width,
                height=height,
                fit_margin=fit_margin,
                anti_aliasing=anti_aliasing,
                texture_filter=texture_filter,
                lighting=lighting,
                ambient_strength=ambient_strength,
                headlight_intensity=headlight_intensity,
                background=background,
                background_top=background_top,
            )
        )
    )
