"""Export approved U9 actor/skeleton libraries from a discovery plan."""

from __future__ import annotations

__all__ = [
    "ANIMATION_LIBRARY_CATALOGUE_SCHEMA",
    "ANIMATION_LIBRARY_CATALOGUE_SCHEMA_VERSION",
    "ANIMATION_LIBRARY_EXPORT_SCHEMA",
    "ANIMATION_LIBRARY_EXPORT_SCHEMA_VERSION",
    "U9ExportedAnimationSkeletonLibrary",
    "U9PlannedAnimationLibraryExportError",
    "U9PlannedAnimationLibraryExportResult",
    "export_planned_animation_libraries",
    "read_animation_library_plan",
]

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from titan.u9.animation import U9Animation
from titan.u9.animation_library_plan import (
    ANIMATION_LIBRARY_PLAN_SCHEMA,
    ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION,
)
from titan.u9.animation_model_report import model_skeleton_fingerprint
from titan.u9.animated_model_bundle import (
    DEFAULT_ANIMATED_MODEL_SCALE,
    U9AnimatedModelBundleError,
    build_animation_catalogue_record,
    build_hashed_input_record,
    export_animated_model_library,
)
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.mesh_export import TextureResolver
from titan.u9.model import U9Model, U9ModelError
from titan.u9.node_registry import U9NodeRegistry

ANIMATION_LIBRARY_CATALOGUE_SCHEMA = "titan.u9.animation-library-catalogue"
ANIMATION_LIBRARY_CATALOGUE_SCHEMA_VERSION = 1
ANIMATION_LIBRARY_EXPORT_SCHEMA = "titan.u9.animation-library-export"
ANIMATION_LIBRARY_EXPORT_SCHEMA_VERSION = 1


class U9PlannedAnimationLibraryExportError(Exception):
    """Raised when an approved animation plan cannot be exported safely."""


@dataclass(frozen=True)
class U9ExportedAnimationSkeletonLibrary:
    """One actor/skeleton library produced from one or more plan entries."""

    library_id: str
    actor_hint: str
    skeleton_fingerprint: str
    representative_model_id: int
    actor_anchor_model_ids: tuple[int, ...]
    model_variant_ids: tuple[int, ...]
    plan_library_ids: tuple[str, ...]
    animation_ids: tuple[int, ...]
    sidecar_path: Path
    glb_path: Path | None
    mesh_count: int


@dataclass(frozen=True)
class U9PlannedAnimationLibraryExportResult:
    """Root paths and counts from one complete approved-plan export."""

    manifest_path: Path
    catalogue_path: Path
    libraries: tuple[U9ExportedAnimationSkeletonLibrary, ...]
    skipped_library_ids: tuple[str, ...]
    exported_animation_count: int


@dataclass
class _SkeletonTask:
    actor_hint: str
    skeleton_fingerprint: str
    representative_model_ids: set[int] = field(default_factory=set)
    actor_anchor_model_ids: set[int] = field(default_factory=set)
    model_variant_ids: set[int] = field(default_factory=set)
    plan_library_ids: set[str] = field(default_factory=set)
    animation_ids: set[int] = field(default_factory=set)
    model_track_ids: set[int] = field(default_factory=set)

    @property
    def library_id(self) -> str:
        actor = re.sub(r"[^a-z0-9]+", "-", self.actor_hint.casefold()).strip("-")
        return f"{actor or 'unassigned'}-{self.skeleton_fingerprint[:8]}"

    @property
    def representative_model_id(self) -> int:
        if not self.representative_model_ids:
            raise U9PlannedAnimationLibraryExportError(
                f"Animation library {self.library_id} has no representative model"
            )
        return min(self.representative_model_ids)


def read_animation_library_plan(path: str | Path) -> dict[str, Any]:
    """Read and validate a versioned animation library plan JSON document."""
    plan_path = Path(path)
    try:
        document = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise U9PlannedAnimationLibraryExportError(
            f"Animation library plan could not be read: {plan_path}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise U9PlannedAnimationLibraryExportError(
            "Animation library plan root is not an object"
        )
    if document.get("schema") != ANIMATION_LIBRARY_PLAN_SCHEMA:
        raise U9PlannedAnimationLibraryExportError(
            "Animation library plan has an unsupported schema"
        )
    if document.get("schema_version") != ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION:
        raise U9PlannedAnimationLibraryExportError(
            "Animation library plan has an unsupported schema version"
        )
    libraries = document.get("libraries")
    if not isinstance(libraries, list) or not libraries:
        raise U9PlannedAnimationLibraryExportError(
            "Animation library plan contains no libraries"
        )

    library_ids: set[str] = set()
    animation_ids: set[int] = set()
    for library in libraries:
        if not isinstance(library, dict):
            raise U9PlannedAnimationLibraryExportError(
                "Animation library plan contains a non-object library"
            )
        library_id = str(library.get("library_id") or "")
        if not library_id or library_id in library_ids:
            raise U9PlannedAnimationLibraryExportError(
                f"Animation library plan has an empty or duplicate ID: {library_id!r}"
            )
        library_ids.add(library_id)
        animations = library.get("animations")
        if not isinstance(animations, list) or not animations:
            raise U9PlannedAnimationLibraryExportError(
                f"Animation library {library_id} contains no animations"
            )
        for animation in animations:
            if not isinstance(animation, dict) or not isinstance(
                animation.get("animation_id"), int
            ):
                raise U9PlannedAnimationLibraryExportError(
                    f"Animation library {library_id} has an invalid animation record"
                )
            animation_id = int(animation["animation_id"])
            if animation_id in animation_ids:
                raise U9PlannedAnimationLibraryExportError(
                    f"Animation ID {animation_id} appears in more than one plan library"
                )
            animation_ids.add(animation_id)
    return document


def _selected_plan_libraries(
    document: dict[str, Any], requested_library_ids: tuple[str, ...]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    libraries = document["libraries"]
    by_id = {str(library["library_id"]): library for library in libraries}
    requested = set(requested_library_ids)
    unknown = sorted(requested - by_id.keys())
    if unknown:
        raise U9PlannedAnimationLibraryExportError(
            "Animation library plan does not contain: " + ", ".join(unknown)
        )
    selected = [
        library
        for library in libraries
        if not requested or str(library["library_id"]) in requested
    ]
    approved = [
        library for library in selected if not bool(library["requires_model_review"])
    ]
    skipped = [
        library for library in selected if bool(library["requires_model_review"])
    ]
    if not approved:
        raise U9PlannedAnimationLibraryExportError(
            "Animation library selection contains no approved libraries"
        )
    return approved, skipped


def _build_skeleton_tasks(
    approved: list[dict[str, Any]],
) -> tuple[list[_SkeletonTask], dict[int, dict[str, Any]]]:
    tasks: dict[tuple[str, str], _SkeletonTask] = {}
    animation_metadata: dict[int, dict[str, Any]] = {}
    for library in approved:
        library_id = str(library["library_id"])
        actor_hint = str(library["actor_hint"])
        animations = library["animations"]
        animation_ids = {int(animation["animation_id"]) for animation in animations}
        for animation in animations:
            animation_metadata[int(animation["animation_id"])] = {
                **animation,
                "plan_library_id": library_id,
                "actor_hint": actor_hint,
                "runtime_binding_status": library["runtime_binding_status"],
            }
        skeleton_groups = library.get("skeleton_groups")
        if not isinstance(skeleton_groups, list) or not skeleton_groups:
            raise U9PlannedAnimationLibraryExportError(
                f"Approved animation library {library_id} has no skeleton groups"
            )
        for skeleton in skeleton_groups:
            if not isinstance(skeleton, dict):
                raise U9PlannedAnimationLibraryExportError(
                    f"Animation library {library_id} has an invalid skeleton group"
                )
            fingerprint = str(skeleton.get("skeleton_fingerprint") or "")
            representative = skeleton.get("representative_model_id")
            if not fingerprint or not isinstance(representative, int):
                raise U9PlannedAnimationLibraryExportError(
                    f"Animation library {library_id} has an incomplete skeleton group"
                )
            key = (actor_hint, fingerprint)
            task = tasks.setdefault(
                key,
                _SkeletonTask(
                    actor_hint=actor_hint,
                    skeleton_fingerprint=fingerprint,
                ),
            )
            task.representative_model_ids.add(representative)
            task.actor_anchor_model_ids.update(
                int(value) for value in skeleton.get("actor_anchor_model_ids", [])
            )
            task.model_variant_ids.update(
                int(value) for value in skeleton.get("model_variant_ids", [])
            )
            task.plan_library_ids.add(library_id)
            task.animation_ids.update(animation_ids)
            task.model_track_ids.update(
                int(value) for value in library.get("model_track_ids", [])
            )
    return sorted(tasks.values(), key=lambda task: task.library_id), animation_metadata


def _load_planned_model(
    archive: U9FlxArchive,
    task: _SkeletonTask,
) -> U9Model:
    model_id = task.representative_model_id
    if model_id < 0 or model_id >= archive.num_entries:
        raise U9PlannedAnimationLibraryExportError(
            f"Animation library {task.library_id} model {model_id} is out of range"
        )
    blob = archive.read_entry(model_id)
    if not blob:
        raise U9PlannedAnimationLibraryExportError(
            f"Animation library {task.library_id} model {model_id} is empty"
        )
    try:
        model = U9Model.parse(blob, model_id=model_id)
    except U9ModelError as error:
        raise U9PlannedAnimationLibraryExportError(
            f"Animation library {task.library_id} model {model_id} failed to parse: "
            f"{error}"
        ) from error
    actual_fingerprint = model_skeleton_fingerprint(model)
    if actual_fingerprint != task.skeleton_fingerprint:
        raise U9PlannedAnimationLibraryExportError(
            f"Animation library {task.library_id} model {model_id} skeleton changed; "
            "regenerate the animation library plan"
        )
    model_limb_ids = {limb.limb_id for limb in model.limbs}
    missing = sorted(task.model_track_ids - model_limb_ids)
    if missing:
        raise U9PlannedAnimationLibraryExportError(
            f"Animation library {task.library_id} model {model_id} is missing planned "
            f"track IDs: {missing}"
        )
    return model


def _relative_path(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, start=root)).as_posix()


def export_planned_animation_libraries(
    plan_path: str | Path,
    animations: Sequence[U9Animation],
    model_archive_path: str | Path,
    animation_archive_path: str | Path,
    output_directory: str | Path,
    *,
    registry: U9NodeRegistry | None = None,
    registry_path: str | Path | None = None,
    texture_resolver: TextureResolver | None = None,
    texture_archive_path: str | Path | None = None,
    palette_path: str | Path | None = None,
    library_ids: tuple[str, ...] = (),
    lod_level: int = 0,
    coordinate_scale: float = DEFAULT_ANIMATED_MODEL_SCALE,
    include_glb: bool = True,
) -> U9PlannedAnimationLibraryExportResult:
    """Export every approved actor/skeleton group using one shared clip catalogue."""
    document = read_animation_library_plan(plan_path)
    approved, skipped = _selected_plan_libraries(document, library_ids)
    tasks, animation_metadata = _build_skeleton_tasks(approved)
    animations_by_id = {animation.animation_id: animation for animation in animations}
    missing_animation_ids = sorted(set(animation_metadata) - animations_by_id.keys())
    if missing_animation_ids:
        raise U9PlannedAnimationLibraryExportError(
            "Animation archive is missing planned IDs: "
            + ", ".join(str(value) for value in missing_animation_ids)
        )

    try:
        model_archive = U9FlxArchive.from_file(model_archive_path)
    except (OSError, U9FlxArchiveError) as error:
        raise U9PlannedAnimationLibraryExportError(
            f"Model archive could not be read: {error}"
        ) from error
    models = {
        task.library_id: _load_planned_model(model_archive, task) for task in tasks
    }

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    catalogue_path = output / "animation_catalogue.u9anim.json"
    manifest_path = output / "animation_libraries.json"
    input_paths = [
        ("animation_library_plan", plan_path),
        ("animation_archive", animation_archive_path),
        ("model_archive", model_archive_path),
        ("node_registry", registry_path),
        ("texture_archive", texture_archive_path),
        ("palette", palette_path),
    ]
    input_records = [
        build_hashed_input_record(role, path)
        for role, path in input_paths
        if path is not None
    ]

    task_ids_by_animation: dict[int, list[str]] = {}
    for task in tasks:
        for animation_id in task.animation_ids:
            task_ids_by_animation.setdefault(animation_id, []).append(task.library_id)
    catalogue_clips = []
    for animation_id in sorted(animation_metadata):
        metadata = animation_metadata[animation_id]
        catalogue_clips.append(
            build_animation_catalogue_record(
                animations_by_id[animation_id],
                metadata.get("motion_name"),
                catalogue={
                    "plan_library_id": metadata["plan_library_id"],
                    "skeleton_library_ids": sorted(
                        task_ids_by_animation.get(animation_id, [])
                    ),
                    "actor_hint": metadata["actor_hint"],
                    "actor_hint_basis": metadata.get("actor_hint_basis"),
                    "category": metadata.get("category"),
                    "action": metadata.get("action"),
                    "runtime_binding_status": metadata["runtime_binding_status"],
                },
            )
        )
    catalogue_document = {
        "schema": ANIMATION_LIBRARY_CATALOGUE_SCHEMA,
        "schema_version": ANIMATION_LIBRARY_CATALOGUE_SCHEMA_VERSION,
        "inputs": input_records,
        "clip_count": len(catalogue_clips),
        "clips": catalogue_clips,
    }
    with catalogue_path.open("w", encoding="utf-8") as stream:
        json.dump(catalogue_document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    exported_animation_count = len(catalogue_clips)
    del catalogue_document, catalogue_clips

    exported_libraries: list[U9ExportedAnimationSkeletonLibrary] = []
    for task in tasks:
        model = models[task.library_id]
        animation_ids = tuple(sorted(task.animation_ids))
        clips = tuple(
            (
                animations_by_id[animation_id],
                animation_metadata[animation_id].get("motion_name"),
            )
            for animation_id in animation_ids
        )
        library_directory = output / "libraries" / task.library_id
        catalogue_reference = {
            "schema": ANIMATION_LIBRARY_CATALOGUE_SCHEMA,
            "schema_version": ANIMATION_LIBRARY_CATALOGUE_SCHEMA_VERSION,
            "path": _relative_path(catalogue_path, library_directory),
            "animation_ids": list(animation_ids),
        }
        library_metadata = {
            "library_id": task.library_id,
            "actor_hint": task.actor_hint,
            "skeleton_fingerprint": task.skeleton_fingerprint,
            "representative_model_id": task.representative_model_id,
            "actor_anchor_model_ids": sorted(task.actor_anchor_model_ids),
            "model_variant_ids": sorted(task.model_variant_ids),
            "plan_library_ids": sorted(task.plan_library_ids),
            "runtime_binding_status": "unresolved",
            "timeline_authored": False,
        }
        try:
            exported = export_animated_model_library(
                model,
                clips,
                library_directory,
                model_archive_path=model_archive_path,
                animation_archive_path=animation_archive_path,
                registry=registry,
                registry_path=registry_path,
                texture_resolver=texture_resolver,
                texture_archive_path=texture_archive_path,
                palette_path=palette_path,
                lod_level=lod_level,
                coordinate_scale=coordinate_scale,
                include_glb=include_glb,
                library_metadata=library_metadata,
                shared_catalogue_reference=catalogue_reference,
                input_records=input_records,
            )
        except U9AnimatedModelBundleError as error:
            raise U9PlannedAnimationLibraryExportError(
                f"Animation library {task.library_id} could not be exported: {error}"
            ) from error
        exported_libraries.append(
            U9ExportedAnimationSkeletonLibrary(
                library_id=task.library_id,
                actor_hint=task.actor_hint,
                skeleton_fingerprint=task.skeleton_fingerprint,
                representative_model_id=task.representative_model_id,
                actor_anchor_model_ids=tuple(sorted(task.actor_anchor_model_ids)),
                model_variant_ids=tuple(sorted(task.model_variant_ids)),
                plan_library_ids=tuple(sorted(task.plan_library_ids)),
                animation_ids=animation_ids,
                sidecar_path=exported.sidecar_path,
                glb_path=exported.glb_path,
                mesh_count=exported.mesh_count,
            )
        )

    manifest_document = {
        "schema": ANIMATION_LIBRARY_EXPORT_SCHEMA,
        "schema_version": ANIMATION_LIBRARY_EXPORT_SCHEMA_VERSION,
        "inputs": input_records,
        "catalogue": {
            "schema": ANIMATION_LIBRARY_CATALOGUE_SCHEMA,
            "schema_version": ANIMATION_LIBRARY_CATALOGUE_SCHEMA_VERSION,
            "path": _relative_path(catalogue_path, output),
            "clip_count": exported_animation_count,
        },
        "summary": {
            "approved_plan_library_count": len(approved),
            "exported_skeleton_library_count": len(exported_libraries),
            "exported_animation_count": exported_animation_count,
            "skipped_review_library_count": len(skipped),
        },
        "libraries": [
            {
                "library_id": library.library_id,
                "actor_hint": library.actor_hint,
                "skeleton_fingerprint": library.skeleton_fingerprint,
                "representative_model_id": library.representative_model_id,
                "actor_anchor_model_ids": list(library.actor_anchor_model_ids),
                "model_variant_ids": list(library.model_variant_ids),
                "plan_library_ids": list(library.plan_library_ids),
                "animation_count": len(library.animation_ids),
                "animation_ids": list(library.animation_ids),
                "sidecar": _relative_path(library.sidecar_path, output),
                "glb": (
                    _relative_path(library.glb_path, output)
                    if library.glb_path is not None
                    else None
                ),
            }
            for library in exported_libraries
        ],
        "skipped_review_libraries": [
            {
                "library_id": library["library_id"],
                "confidence": library["confidence"],
                "animation_count": library["animation_count"],
                "model_selection_basis": library["model_selection_basis"],
            }
            for library in skipped
        ],
        "interchange": {
            "raw_animation_data_is_shared": True,
            "skeleton_sidecars_contain_bindings_only": True,
            "glb_actions_are_generated_per_skeleton": include_glb,
            "timeline_authored": False,
        },
    }
    with manifest_path.open("w", encoding="utf-8") as stream:
        json.dump(manifest_document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return U9PlannedAnimationLibraryExportResult(
        manifest_path=manifest_path,
        catalogue_path=catalogue_path,
        libraries=tuple(exported_libraries),
        skipped_library_ids=tuple(str(library["library_id"]) for library in skipped),
        exported_animation_count=exported_animation_count,
    )
