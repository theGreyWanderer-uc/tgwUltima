"""``titan u9 animation-*`` — animation clip, pose and library commands."""

from __future__ import annotations

__all__ = [
    "animation_list_cmd",
    "animation_show_cmd",
    "animation_library_plan_cmd",
    "animation_library_export_cmd",
    "animation_model_report_cmd",
    "animation_pose_export_cmd",
    "animation_bundle_export_cmd",
    "animation_set_export_cmd",
    "avatar_animation_library_export_cmd",
]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.asset_reports import U9AssetReportError, write_dynamic_report
from titan.u9.animation import U9Animation, U9AnimationError, U9Animations
from titan.u9.animation_model_report import (
    ANIMATION_MODEL_REPORT_COLUMNS,
    U9AnimationModelReportError,
    build_animation_model_report,
)
from titan.u9.animation_library_plan import (
    U9AnimationLibraryPlanError,
    build_animation_library_plan,
    write_animation_library_plan,
)
from titan.u9.animation_pose import U9AnimationPoseError, pose_model
from titan.u9.animation_selection import (
    U9AnimationSelectionError,
    resolve_animation_selector,
)
from titan.u9.animated_model_bundle import (
    DEFAULT_ANIMATED_MODEL_SCALE,
    U9AnimatedModelBundleError,
    export_animated_model_bundle,
)
from titan.u9.animated_model_set import (
    U9AnimatedModelSetError,
    export_animated_model_set,
)
from titan.u9.avatar_animation_library import (
    U9AvatarAnimationLibraryError,
    export_avatar_animation_library,
)
from titan.u9.flx_archive import U9FlxArchiveError
from titan.u9.mesh_export import MeshExportError, export_obj, export_stl
from titan.u9.model import U9ModelError
from titan.u9.animation_labels import U9AnimationLabels, parse_animation_source_hints
from titan.u9.node_registry import U9NodeRegistry, U9NodeRegistryError
from titan.u9.planned_animation_library_export import (
    U9PlannedAnimationLibraryExportError,
    export_planned_animation_libraries,
    parse_actor_model_library_spec,
)
from titan.u9.cli import _common


def _load_animations(filepath: str) -> Optional[U9Animations]:
    """Open static/anim.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Animations.from_file(filepath)
    except U9AnimationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def _animation_label(animation: U9Animation) -> str:
    """Titan's label for a clip, from its stored authoring path."""
    return parse_animation_source_hints(animation.source_name).label


def cmd_animation_list(args: SimpleNamespace) -> int:
    """List animation clips with their frame, part and event counts."""
    animations = _load_animations(args.file)
    if animations is None:
        return 1

    animation_ids = animations.used_animation_ids()
    shown = animation_ids[: args.limit] if args.limit else animation_ids
    print(
        f"{args.file} -- {len(animation_ids)} animation clip(s) "
        f"of {animations.num_entries} slots"
    )
    print(
        f"{'ID':>5}  {'Frames':>6}  {'Parts':>5}  {'Last ms':>8}  {'Game ms':>8}  "
        f"{'Events':>6}  {'Label':<42}  Authoring path"
    )
    print("-" * 152)
    for animation_id in shown:
        try:
            animation = animations.animation(animation_id)
        except U9AnimationError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if animation is None:
            continue
        print(
            f"{animation.animation_id:>5}  {animation.frame_count:>6}  "
            f"{len(animation.parts):>5}  {animation.duration_ms:>8}  "
            f"{animation.runtime_length_ms or 0:>8}  "
            f"{len(animation.events):>6}  {_animation_label(animation) or '-':<42}  "
            f"{animation.source_name}"
        )
    if args.limit and len(animation_ids) > args.limit:
        print(
            f"... ({len(animation_ids) - args.limit} more; raise --limit to see more)"
        )
    return 0


def cmd_animation_show(args: SimpleNamespace) -> int:
    """Show one animation, optionally dumping one part's frame transforms."""
    animations = _load_animations(args.file)
    if animations is None:
        return 1

    try:
        animation = animations.animation(args.id)
    except U9AnimationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if animation is None:
        print(f"Animation {args.id} is an unused slot.")
        return 0

    print(f"{args.file} -- animation {animation.animation_id}")
    print(f"  Label           : {_animation_label(animation) or '-'}")
    print(f"  Authoring path  : {animation.source_name}")
    print(
        f"  Authoring frames: {animation.start_frame}..{animation.end_frame} "
        f"({animation.frame_count} total)"
    )
    print(
        f"  Timing          : {animation.source_fps} fps, "
        f"{animation.frame_interval_ms} nominal ms, "
        f"last timestamp {animation.last_sample_time_ms} ms, "
        f"runtime length {animation.runtime_length_ms} ms"
    )
    event_label = "event" if len(animation.events) == 1 else "events"
    print(
        f"  Structure       : {len(animation.part_registry)} registry words, "
        f"{len(animation.parts)} parts, {len(animation.events)} {event_label}"
    )
    print(
        "  Stored status    : "
        f"ID {animation.stored_id_status}, range {animation.frame_range_status}, "
        f"timing {animation.runtime_timing_status}, "
        f"registry {animation.part_registry_status}, "
        f"tracks {animation.part_frame_count_status}, "
        f"{len(animation.part_registry_residue)} inactive registry words"
    )

    if args.part is None:
        parts = animation.parts[: args.limit] if args.limit else animation.parts
        print(f"  {'Part ID':>7}  {'Frames':>6}  {'Last ms':>8}  Name")
        print("  " + "-" * 52)
        for part in parts:
            last_ms = part.frames[-1].time_ms if part.frames else 0
            print(
                f"  {part.part_id:>7}  {part.frame_count:>6}  {last_ms:>8}  {part.name}"
            )
        if args.limit and len(animation.parts) > args.limit:
            print(
                f"  ... ({len(animation.parts) - args.limit} more; "
                "raise --limit to see more)"
            )
    else:
        selected_part = animation.part(args.part)
        if selected_part is None:
            print(
                f"ERROR: animation {animation.animation_id} has no part ID {args.part}",
                file=sys.stderr,
            )
            return 1
        frames = (
            selected_part.frames[: args.limit] if args.limit else selected_part.frames
        )
        print(
            f"  Part {selected_part.part_id}: {selected_part.name} "
            f"({selected_part.frame_count} frames)"
        )
        for index, frame in enumerate(frames):
            rotation = ", ".join(f"{value:.6g}" for value in frame.rotation)
            position = ", ".join(f"{value:.6g}" for value in frame.position)
            scale = ", ".join(f"{value:.6g}" for value in frame.scale)
            print(
                f"    {index:>4}  {frame.time_ms:>6} ms  "
                f"q=({rotation})  p=({position})  s=({scale})"
            )
        if args.limit and selected_part.frame_count > args.limit:
            print(
                f"    ... ({selected_part.frame_count - args.limit} more; "
                "raise --limit to see more)"
            )

    if animation.events:
        print(f"  {'Event ms':>8}  {'Type':>4}  {'Name':<18}  Parameter")
        print("  " + "-" * 50)
        for event in animation.events:
            print(
                f"  {event.time_ms:>8}  {event.event_type:>4}  "
                f"{event.event_name:<18}  {event.parameter}"
            )
    return 0


def cmd_animation_model_report(args: SimpleNamespace) -> int:
    """Export legacy detailed diagnostics for animation/model discovery."""
    print(
        "WARNING: animation-model-report is deprecated; use animation-library-plan "
        "with --diagnostics for the same detailed evidence.",
        file=sys.stderr,
    )
    try:
        rows, warnings = build_animation_model_report(
            args.file,
            animation_id=getattr(args, "animation", None),
            sappear_path=getattr(args, "sappear", None),
            registry_path=getattr(args, "registry", None),
            types_path=getattr(args, "types", None),
            typenames_path=getattr(args, "typenames", None),
        )
        output = write_dynamic_report(
            rows,
            args.output,
            args.format,
            preferred_columns=ANIMATION_MODEL_REPORT_COLUMNS,
        )
    except (U9AnimationModelReportError, U9AssetReportError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"Wrote {len(rows)} animation/model row(s) to {output}")
    return 0


def cmd_animation_library_plan(args: SimpleNamespace) -> int:
    """Write the compact animation library plan and optional diagnostics."""
    try:
        plan = build_animation_library_plan(
            args.file,
            sappear_path=getattr(args, "sappear", None),
            registry_path=getattr(args, "registry", None),
            types_path=getattr(args, "types", None),
            typenames_path=getattr(args, "typenames", None),
        )
        output = write_animation_library_plan(plan, args.output)
        diagnostics_path = getattr(args, "diagnostics", None)
        diagnostics_output = None
        if diagnostics_path is not None:
            diagnostics_output = write_dynamic_report(
                list(plan.diagnostics),
                diagnostics_path,
                getattr(args, "diagnostics_format", "csv"),
                preferred_columns=ANIMATION_MODEL_REPORT_COLUMNS,
            )
    except (
        U9AnimationLibraryPlanError,
        U9AssetReportError,
        OSError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in plan.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    summary = plan.document["summary"]
    print(
        f"Wrote {summary['library_count']} animation libraries covering "
        f"{summary['animation_count']} clips to {output}"
    )
    print(f"  Actor hints     : {summary['actor_hint_count']}")
    print(f"  Track signatures: {summary['track_signature_count']}")
    print(f"  Auto-exportable : {summary['auto_export_library_count']}")
    print(f"  Needs review    : {summary['review_library_count']}")
    if diagnostics_output is not None:
        print(f"  Diagnostics     : {diagnostics_output}")
    return 0


def cmd_animation_library_export(args: SimpleNamespace) -> int:
    """Export approved actor/skeleton libraries using one shared catalogue."""
    for label, path in (
        ("Animation library plan", args.plan),
        ("Animation archive", args.animations),
        ("Model archive", args.sappear),
        ("Texture archive", args.textures),
        ("Palette", args.palette),
        ("Node registry", args.registry),
    ):
        if path is not None and not Path(path).is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 1

    animations = _load_animations(args.animations)
    if animations is None:
        return 1
    registry_path = Path(args.registry) if args.registry else None
    if registry_path is None:
        registry_path = _common._find_case_insensitive_file(
            Path(args.animations).resolve().parent, "registry.txt"
        )
    try:
        registry = (
            U9NodeRegistry.from_file(registry_path)
            if registry_path is not None
            else None
        )
        palette_path, _ = _common._find_palette(args.palette, args.textures)
        texture_resolver = _common._make_texture_resolver(args.textures, palette_path)
        output = args.output or "u9_animation_library_export"
        result = export_planned_animation_libraries(
            args.plan,
            animations.animations(),
            args.sappear,
            args.animations,
            output,
            registry=registry,
            registry_path=registry_path,
            texture_resolver=texture_resolver,
            texture_archive_path=args.textures,
            palette_path=palette_path,
            library_ids=tuple(args.library_ids or ()),
            actor_models=tuple(
                parse_actor_model_library_spec(value)
                for value in getattr(args, "actor_models", None) or ()
            ),
            lod_level=args.lod,
            coordinate_scale=args.coordinate_scale,
            include_glb=args.glb,
        )
    except (
        OSError,
        U9AnimationError,
        U9FlxArchiveError,
        U9NodeRegistryError,
        U9PlannedAnimationLibraryExportError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Exported {len(result.libraries)} actor/skeleton libraries containing "
        f"{result.exported_animation_count} unique clips -> {output}/"
    )
    print(f"  Shared catalogue: {result.catalogue_path}")
    print(f"  Root manifest   : {result.manifest_path}")
    print(f"  Review-only skip: {len(result.skipped_library_ids)}")
    print(f"  GLB output      : {'enabled' if args.glb else 'disabled'}")
    if args.textures is None:
        print("  (no --textures given: exported materials have no images)")
    return 0


def cmd_animation_pose_export(args: SimpleNamespace) -> int:
    """Export one hierarchical model posed by one animation at a given time."""
    error = _common._validate_model_export_args(
        SimpleNamespace(
            format=args.format,
            file=args.sappear,
            textures=args.textures,
            palette=args.palette,
            types=None,
            typenames=None,
        )
    )
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    animations = _load_animations(args.animations)
    if animations is None:
        return 1

    try:
        animation = animations.animation(args.animation_id)
        if animation is None:
            raise U9AnimationPoseError(
                f"animation {args.animation_id} is an unused anim.flx slot"
            )
        model = _common._load_model(args.sappear, args.model_id)
        result = pose_model(model, animation, args.time_ms)
        resolver = _common._make_texture_resolver(args.textures, args.palette)
        clip_label = _animation_label(animation).replace("/", "_")
        clip_suffix = f"_{clip_label}" if clip_label else ""
        stem = (
            f"animation_{args.animation_id:05d}{clip_suffix}_"
            f"model_{args.model_id:05d}_{args.time_ms:06d}ms"
        )
        outdir = args.output or stem
        os.makedirs(outdir, exist_ok=True)
        base = os.path.join(outdir, stem)
        wrote = []
        if args.format in ("obj", "both"):
            export_obj(
                result.model,
                base + ".obj",
                lod_level=args.lod,
                texture_resolver=resolver,
            )
            wrote.append(base + ".obj")
        if args.format in ("stl", "both"):
            export_stl(result.model, base + ".stl", lod_level=args.lod)
            wrote.append(base + ".stl")
    except (
        U9AnimationError,
        U9AnimationPoseError,
        U9FlxArchiveError,
        U9ModelError,
        MeshExportError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Exported animation {args.animation_id} on model {args.model_id} "
        f"at {args.time_ms} ms (LOD {args.lod}) -> {outdir}/"
    )
    for path in wrote:
        print(f"  {path}")
    print(f"  Matched parts   : {len(result.matched_part_ids)}")
    print(f"  Authoring-only  : {list(result.authoring_only_part_ids)}")
    print(f"  Model-only      : {list(result.model_only_limb_ids)}")
    print(f"  Root motion     : {result.root_motion_delta}")
    if args.format in ("obj", "both") and resolver is None:
        print("  (no --textures given: OBJ materials have no images)")
    if args.preview:
        _common._generate_preview(outdir)
    return 0


def cmd_animation_bundle_export(args: SimpleNamespace) -> int:
    """Export one complete rigid hierarchy, clip sidecar, and animated GLB."""
    for label, path in (
        ("Animation archive", args.animations),
        ("Model archive", args.sappear),
        ("Texture archive", args.textures),
        ("Palette", args.palette),
        ("Node registry", args.registry),
    ):
        if path is not None and not Path(path).is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 1

    animations = _load_animations(args.animations)
    if animations is None:
        return 1

    registry_path = Path(args.registry) if args.registry else None
    if registry_path is None:
        registry_path = _common._find_case_insensitive_file(
            Path(args.animations).resolve().parent, "registry.txt"
        )
    try:
        registry = (
            U9NodeRegistry.from_file(registry_path)
            if registry_path is not None
            else None
        )
        animation = animations.animation(args.animation_id)
        if animation is None:
            raise U9AnimatedModelBundleError(
                f"animation {args.animation_id} is an unused archive slot"
            )
        model = _common._load_model(args.sappear, args.model_id)
        palette_path, _ = _common._find_palette(args.palette, args.textures)
        texture_resolver = _common._make_texture_resolver(args.textures, palette_path)
        output = args.output or (
            f"model_{args.model_id:05d}_animation_{args.animation_id:05d}_bundle"
        )
        result = export_animated_model_bundle(
            model,
            animation,
            output,
            model_archive_path=args.sappear,
            animation_archive_path=args.animations,
            registry=registry,
            registry_path=registry_path,
            animation_label=_animation_label(animation),
            texture_resolver=texture_resolver,
            texture_archive_path=args.textures,
            palette_path=palette_path,
            lod_level=args.lod,
            coordinate_scale=args.coordinate_scale,
            include_glb=args.glb,
        )
    except (
        OSError,
        U9AnimationError,
        U9AnimatedModelBundleError,
        U9FlxArchiveError,
        U9ModelError,
        U9NodeRegistryError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Exported model {args.model_id} with animation {args.animation_id} "
        f"(LOD {args.lod}) -> {output}/"
    )
    print(f"  Sidecar         : {result.sidecar_path}")
    print(f"  Limb meshes     : {result.mesh_count}/{result.part_count}")
    print(f"  Animation tracks: {result.track_count}")
    print(f"  Matched tracks  : {result.matched_track_count}")
    print(f"  Authoring-only  : {result.authoring_only_track_count}")
    if result.glb_path is not None:
        print(f"  Animated GLB    : {result.glb_path}")
    if args.textures is None:
        print("  (no --textures given: exported materials have no images)")
    return 0


def cmd_animation_set_export(args: SimpleNamespace) -> int:
    """Export independently playable clips for one explicit rigid actor model."""
    if not args.clips:
        print("ERROR: At least one --clip selector is required.", file=sys.stderr)
        return 1
    for label, path in (
        ("Animation archive", args.animations),
        ("Model archive", args.sappear),
        ("Texture archive", args.textures),
        ("Palette", args.palette),
        ("Node registry", args.registry),
    ):
        if path is not None and not Path(path).is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 1

    animations = _load_animations(args.animations)
    if animations is None:
        return 1

    registry_path = Path(args.registry) if args.registry else None
    if registry_path is None:
        registry_path = _common._find_case_insensitive_file(
            Path(args.animations).resolve().parent, "registry.txt"
        )
    try:
        registry = (
            U9NodeRegistry.from_file(registry_path)
            if registry_path is not None
            else None
        )
        labels = U9AnimationLabels.from_animations(animations.animations())
        selected_clips = []
        for selector in args.clips:
            selection = resolve_animation_selector(selector, labels)
            animation = animations.animation(selection.animation_id)
            if animation is None:
                raise U9AnimatedModelSetError(
                    f"animation selector {selector!r} resolved to unused archive slot "
                    f"{selection.animation_id}"
                )
            selected_clips.append((selection, animation))

        model = _common._load_model(args.sappear, args.model_id)
        palette_path, _ = _common._find_palette(args.palette, args.textures)
        texture_resolver = _common._make_texture_resolver(args.textures, palette_path)
        output = args.output or f"model_{args.model_id:05d}_animation_set"
        result = export_animated_model_set(
            model,
            selected_clips,
            output,
            model_archive_path=args.sappear,
            animation_archive_path=args.animations,
            registry=registry,
            registry_path=registry_path,
            texture_resolver=texture_resolver,
            texture_archive_path=args.textures,
            palette_path=palette_path,
            lod_level=args.lod,
            coordinate_scale=args.coordinate_scale,
            include_glb=args.glb,
        )
    except (
        OSError,
        U9AnimationError,
        U9AnimationSelectionError,
        U9AnimatedModelSetError,
        U9FlxArchiveError,
        U9ModelError,
        U9NodeRegistryError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Exported {result.clip_count} animation clip(s) for model {args.model_id} "
        f"(LOD {args.lod}) -> {output}/"
    )
    print(f"  Set manifest    : {result.manifest_path}")
    for selection, animation in selected_clips:
        label = selection.animation_label or f"animation_{animation.animation_id}"
        print(f"  Clip {animation.animation_id:>5}: {label} ({selection.selector})")
    print(f"  Clip sidecars   : {len(result.clip_sidecar_paths)}")
    print(f"  Animated GLBs   : {len(result.clip_glb_paths)}")
    print("  Timeline        : not authored (consumer chooses duration and order)")
    if args.textures is None:
        print("  (no --textures given: exported materials have no images)")
    return 0


def cmd_avatar_animation_library_export(args: SimpleNamespace) -> int:
    """Export all compatible Avatar-labelled clips with shared actor assets."""
    for label, path in (
        ("Animation archive", args.animations),
        ("Model archive", args.sappear),
        ("Texture archive", args.textures),
        ("Palette", args.palette),
        ("Node registry", args.registry),
    ):
        if path is not None and not Path(path).is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 1

    animations = _load_animations(args.animations)
    if animations is None:
        return 1

    registry_path = Path(args.registry) if args.registry else None
    if registry_path is None:
        registry_path = _common._find_case_insensitive_file(
            Path(args.animations).resolve().parent, "registry.txt"
        )
    try:
        registry = (
            U9NodeRegistry.from_file(registry_path)
            if registry_path is not None
            else None
        )
        model = _common._load_model(args.sappear, args.model_id)
        palette_path, _ = _common._find_palette(args.palette, args.textures)
        texture_resolver = _common._make_texture_resolver(args.textures, palette_path)
        output = args.output or f"model_{args.model_id:05d}_avatar_animation_library"
        result = export_avatar_animation_library(
            model,
            animations.animations(),
            output,
            model_archive_path=args.sappear,
            animation_archive_path=args.animations,
            registry=registry,
            registry_path=registry_path,
            texture_resolver=texture_resolver,
            texture_archive_path=args.textures,
            palette_path=palette_path,
            categories=args.categories or (),
            lod_level=args.lod,
            coordinate_scale=args.coordinate_scale,
            include_glb=args.glb,
        )
    except (
        OSError,
        U9AnimationError,
        U9AvatarAnimationLibraryError,
        U9FlxArchiveError,
        U9ModelError,
        U9NodeRegistryError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    exported = result.export
    print(
        f"Exported {result.exported_clip_count} Avatar animation clip(s) for "
        f"model {args.model_id} (LOD {args.lod}) -> {output}/"
    )
    print(f"  Library sidecar : {exported.sidecar_path}")
    print(f"  Multi-clip GLB  : {exported.glb_path or 'disabled'}")
    print(f"  Shared meshes   : {exported.mesh_count}")
    print(
        "  Categories      : "
        + ", ".join(f"{name}={count}" for name, count in result.category_counts)
    )
    print(f"  Incompatible    : {len(result.incompatible_animation_ids)}")
    print("  Timeline        : not authored (consumer selects and sequences actions)")
    if args.textures is None:
        print("  (no --textures given: exported materials have no images)")
    return 0


def animation_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 animation clips, authoring paths, frame counts and animated parts."""
    raise SystemExit(cmd_animation_list(SimpleNamespace(file=file, limit=limit)))


def animation_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    id: Annotated[int, typer.Argument(help="Animation ID (the FLX entry index)")],
    part: Annotated[
        Optional[int],
        typer.Option("-p", "--part", help="Dump transform frames for this part ID"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum parts or frames to print"),
    ] = None,
) -> None:
    """Show one U9 animation's structure or one part's transform frames."""
    raise SystemExit(
        cmd_animation_show(
            SimpleNamespace(
                file=file,
                id=id,
                part=part,
                limit=limit,
            )
        )
    )


def animation_library_plan_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Compact JSON library plan path"),
    ],
    sappear: Annotated[
        Optional[str],
        typer.Option(
            "--sappear",
            help="sappear.flx path (default: beside anim.flx)",
        ),
    ] = None,
    registry: Annotated[
        Optional[str],
        typer.Option(
            "--registry",
            help="registry.txt path (default: beside anim.flx)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option("--types", help="TYPES.DAT path (default: beside anim.flx)"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="TYPENAME.FLX path (default: beside anim.flx)",
        ),
    ] = None,
    diagnostics: Annotated[
        Optional[str],
        typer.Option(
            "--diagnostics",
            help="Optional detailed animation/model diagnostics path",
        ),
    ] = None,
    diagnostics_format: Annotated[
        str,
        typer.Option(
            "--diagnostics-format",
            help="Detailed diagnostics format: csv or json",
        ),
    ] = "csv",
) -> None:
    """Plan actor animation libraries; emit detailed diagnostics only on request."""
    raise SystemExit(
        cmd_animation_library_plan(
            SimpleNamespace(
                file=file,
                output=output,
                sappear=sappear,
                registry=registry,
                types=types,
                typenames=typenames,
                diagnostics=diagnostics,
                diagnostics_format=diagnostics_format,
            )
        )
    )


def animation_library_export_cmd(
    plan: Annotated[str, typer.Argument(help="Animation library plan JSON path")],
    animations: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    sappear: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    registry: Annotated[
        Optional[str],
        typer.Option(
            "--registry",
            help="registry.txt path (default: beside the animation archive)",
        ),
    ] = None,
    library_ids: Annotated[
        Optional[list[str]],
        typer.Option(
            "--library",
            help="Optional approved plan library ID; repeat to limit the export",
        ),
    ] = None,
    actor_models: Annotated[
        Optional[list[str]],
        typer.Option(
            "--actor-model",
            help=(
                "Explicit actor library as "
                "ACTOR=MODEL_ID:PLAN_LIBRARY[,PLAN_LIBRARY...]; repeatable"
            ),
        ),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option("-t", "--textures", help="Optional U9 bitmap texture FLX"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Optional static/ankh.pal"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    coordinate_scale: Annotated[
        float,
        typer.Option(
            "--coordinate-scale",
            help="GLB units per native U9 model unit",
        ),
    ] = DEFAULT_ANIMATED_MODEL_SCALE,
    glb: Annotated[
        bool,
        typer.Option("--glb/--no-glb", help="Write one multi-action GLB per skeleton"),
    ] = True,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output animation-library directory"),
    ] = None,
) -> None:
    """Export every approved plan entry as deduplicated actor/skeleton libraries."""
    raise SystemExit(
        cmd_animation_library_export(
            SimpleNamespace(
                plan=plan,
                animations=animations,
                sappear=sappear,
                registry=registry,
                library_ids=library_ids,
                actor_models=actor_models,
                textures=textures,
                palette=palette,
                lod=lod,
                coordinate_scale=coordinate_scale,
                glb=glb,
                output=output,
            )
        )
    )


def animation_model_report_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="Output CSV or JSON report path"),
    ],
    animation: Annotated[
        Optional[int],
        typer.Option("--animation", help="Limit the report to one animation ID"),
    ] = None,
    sappear: Annotated[
        Optional[str],
        typer.Option(
            "--sappear",
            help="sappear.flx path (default: beside anim.flx)",
        ),
    ] = None,
    registry: Annotated[
        Optional[str],
        typer.Option(
            "--registry",
            help="registry.txt path (default: beside anim.flx)",
        ),
    ] = None,
    types: Annotated[
        Optional[str],
        typer.Option("--types", help="TYPES.DAT path (default: beside anim.flx)"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option(
            "--typenames",
            help="TYPENAME.FLX path (default: beside anim.flx)",
        ),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option("-f", "--format", help="Report format: csv or json"),
    ] = "csv",
) -> None:
    """Deprecated: write detailed diagnostics; use animation-library-plan."""
    raise SystemExit(
        cmd_animation_model_report(
            SimpleNamespace(
                file=file,
                output=output,
                animation=animation,
                sappear=sappear,
                registry=registry,
                types=types,
                typenames=typenames,
                format=fmt,
            )
        )
    )


def animation_pose_export_cmd(
    animations: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    animation_id: Annotated[int, typer.Argument(help="Animation/FLX entry ID")],
    sappear: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Hierarchical model ID")],
    time_ms: Annotated[
        int,
        typer.Option("--time-ms", help="Clip time to sample in milliseconds"),
    ] = 0,
    textures: Annotated[
        Optional[str],
        typer.Option("-t", "--textures", help="Optional U9 bitmap texture FLX"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Optional static/ankh.pal"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    fmt: Annotated[
        str,
        typer.Option("-f", "--format", help="obj, stl, or both"),
    ] = "obj",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option("--preview/--no-preview", help="Also render preview.png"),
    ] = True,
) -> None:
    """Export one runtime-compatible rigid-limb animation pose."""
    raise SystemExit(
        cmd_animation_pose_export(
            SimpleNamespace(
                animations=animations,
                animation_id=animation_id,
                sappear=sappear,
                model_id=model_id,
                time_ms=time_ms,
                textures=textures,
                palette=palette,
                lod=lod,
                format=fmt,
                output=output,
                preview=preview,
            )
        )
    )


def animation_bundle_export_cmd(
    animations: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    animation_id: Annotated[int, typer.Argument(help="Animation/FLX entry ID")],
    sappear: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Hierarchical model ID")],
    registry: Annotated[
        Optional[str],
        typer.Option(
            "--registry",
            help="registry.txt path (default: beside the animation archive)",
        ),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option("-t", "--textures", help="Optional U9 bitmap texture FLX"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Optional static/ankh.pal"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    coordinate_scale: Annotated[
        float,
        typer.Option(
            "--coordinate-scale",
            help="GLB units per native U9 model unit",
        ),
    ] = DEFAULT_ANIMATED_MODEL_SCALE,
    glb: Annotated[
        bool,
        typer.Option("--glb/--no-glb", help="Also write the animated GLB"),
    ] = True,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output bundle directory"),
    ] = None,
) -> None:
    """Export local limb meshes, exact U9 tracks, and an animated GLB."""
    raise SystemExit(
        cmd_animation_bundle_export(
            SimpleNamespace(
                animations=animations,
                animation_id=animation_id,
                sappear=sappear,
                model_id=model_id,
                registry=registry,
                textures=textures,
                palette=palette,
                lod=lod,
                coordinate_scale=coordinate_scale,
                glb=glb,
                output=output,
            )
        )
    )


def animation_set_export_cmd(
    animations: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    sappear: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Explicit hierarchical model ID")],
    clips: Annotated[
        Optional[list[str]],
        typer.Option(
            "--clip",
            help=(
                "Clip selector; repeat for IDs, clip labels such as "
                "humanoid/idle/breathe_avatar, or aliases such as avatar:walk"
            ),
        ),
    ] = None,
    registry: Annotated[
        Optional[str],
        typer.Option(
            "--registry",
            help="registry.txt path (default: beside the animation archive)",
        ),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option("-t", "--textures", help="Optional U9 bitmap texture FLX"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Optional static/ankh.pal"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    coordinate_scale: Annotated[
        float,
        typer.Option(
            "--coordinate-scale",
            help="GLB units per native U9 model unit",
        ),
    ] = DEFAULT_ANIMATED_MODEL_SCALE,
    glb: Annotated[
        bool,
        typer.Option("--glb/--no-glb", help="Write one animated GLB per clip"),
    ] = True,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output animation-set directory"),
    ] = None,
) -> None:
    """Export named clips and a neutral actor animation-set manifest."""
    raise SystemExit(
        cmd_animation_set_export(
            SimpleNamespace(
                animations=animations,
                sappear=sappear,
                model_id=model_id,
                clips=clips,
                registry=registry,
                textures=textures,
                palette=palette,
                lod=lod,
                coordinate_scale=coordinate_scale,
                glb=glb,
                output=output,
            )
        )
    )


def avatar_animation_library_export_cmd(
    animations: Annotated[str, typer.Argument(help="Path to static/anim.flx")],
    sappear: Annotated[str, typer.Argument(help="Path to static/sappear.flx")],
    model_id: Annotated[int, typer.Argument(help="Explicit Avatar model ID")],
    registry: Annotated[
        Optional[str],
        typer.Option(
            "--registry",
            help="registry.txt path (default: beside the animation archive)",
        ),
    ] = None,
    categories: Annotated[
        Optional[list[str]],
        typer.Option(
            "--category",
            help="Optional category filter; repeat for movement, idle, combat, etc.",
        ),
    ] = None,
    textures: Annotated[
        Optional[str],
        typer.Option("-t", "--textures", help="Optional U9 bitmap texture FLX"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Optional static/ankh.pal"),
    ] = None,
    lod: Annotated[int, typer.Option("--lod", help="LOD level to export")] = 0,
    coordinate_scale: Annotated[
        float,
        typer.Option(
            "--coordinate-scale",
            help="GLB units per native U9 model unit",
        ),
    ] = DEFAULT_ANIMATED_MODEL_SCALE,
    glb: Annotated[
        bool,
        typer.Option("--glb/--no-glb", help="Write one GLB containing every clip"),
    ] = True,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output Avatar library directory"),
    ] = None,
) -> None:
    """Export shared Avatar assets and every compatible named animation clip."""
    raise SystemExit(
        cmd_avatar_animation_library_export(
            SimpleNamespace(
                animations=animations,
                sappear=sappear,
                model_id=model_id,
                registry=registry,
                categories=categories,
                textures=textures,
                palette=palette,
                lod=lod,
                coordinate_scale=coordinate_scale,
                glb=glb,
                output=output,
            )
        )
    )
