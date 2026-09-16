"""Export several independently playable U9 clips for one rigid actor model."""

from __future__ import annotations

__all__ = [
    "ANIMATED_MODEL_SET_SCHEMA",
    "ANIMATED_MODEL_SET_SCHEMA_VERSION",
    "U9AnimatedModelSetError",
    "U9AnimatedModelSetResult",
    "export_animated_model_set",
]

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from titan.u9.animation import U9Animation
from titan.u9.animation_selection import U9ResolvedAnimationSelection
from titan.u9.animated_model_bundle import (
    DEFAULT_ANIMATED_MODEL_SCALE,
    U9AnimatedModelBundleError,
    export_animated_model_bundle,
)
from titan.u9.mesh_export import TextureResolver
from titan.u9.model import U9Model
from titan.u9.node_registry import U9NodeRegistry

ANIMATED_MODEL_SET_SCHEMA = "titan.u9.rigid-animated-model-set"
ANIMATED_MODEL_SET_SCHEMA_VERSION = 1


class U9AnimatedModelSetError(Exception):
    """Raised when independent clips cannot form one actor animation set."""


@dataclass(frozen=True)
class U9AnimatedModelSetResult:
    """Paths and counts written by one multi-clip actor export."""

    manifest_path: Path
    clip_sidecar_paths: tuple[Path, ...]
    clip_glb_paths: tuple[Path, ...]
    clip_count: int


def _relative_path(path: Path, output: Path) -> str:
    return path.relative_to(output).as_posix()


def export_animated_model_set(
    model: U9Model,
    clips: Sequence[tuple[U9ResolvedAnimationSelection, U9Animation]],
    output_directory: str | Path,
    *,
    model_archive_path: str | Path,
    animation_archive_path: str | Path,
    registry: U9NodeRegistry | None = None,
    registry_path: str | Path | None = None,
    motion_table_path: str | Path | None = None,
    texture_resolver: TextureResolver | None = None,
    texture_archive_path: str | Path | None = None,
    palette_path: str | Path | None = None,
    lod_level: int = 0,
    coordinate_scale: float = DEFAULT_ANIMATED_MODEL_SCALE,
    include_glb: bool = True,
) -> U9AnimatedModelSetResult:
    """Export independent clips plus a neutral manifest, without a presentation timeline."""
    if not clips:
        raise U9AnimatedModelSetError("animation set requires at least one clip")
    animation_ids = [selection.animation_id for selection, _animation in clips]
    if len(set(animation_ids)) != len(animation_ids):
        raise U9AnimatedModelSetError(
            "animation set contains duplicate animation IDs; each clip must be unique"
        )
    for selection, animation in clips:
        if animation.animation_id != selection.animation_id:
            raise U9AnimatedModelSetError(
                f"animation selector {selection.selector!r} resolved to ID "
                f"{selection.animation_id}, but clip {animation.animation_id} was supplied"
            )

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    manifest_clips: list[dict[str, object]] = []
    sidecar_paths: list[Path] = []
    glb_paths: list[Path] = []
    try:
        for request_index, (selection, animation) in enumerate(clips):
            clip_directory = (
                output / "clips" / f"animation_{animation.animation_id:05d}"
            )
            bundle = export_animated_model_bundle(
                model,
                animation,
                clip_directory,
                model_archive_path=model_archive_path,
                animation_archive_path=animation_archive_path,
                registry=registry,
                registry_path=registry_path,
                motion_name=selection.motion_name,
                motion_table_path=motion_table_path,
                texture_resolver=texture_resolver,
                texture_archive_path=texture_archive_path,
                palette_path=palette_path,
                lod_level=lod_level,
                coordinate_scale=coordinate_scale,
                include_glb=include_glb,
            )
            sidecar_paths.append(bundle.sidecar_path)
            if bundle.glb_path is not None:
                glb_paths.append(bundle.glb_path)
            manifest_clips.append(
                {
                    "request_index": request_index,
                    "animation_id": animation.animation_id,
                    "motion_name": selection.motion_name,
                    "selection": selection.to_metadata(),
                    "timing": {
                        "source_fps": animation.source_fps,
                        "frame_interval_ms": animation.frame_interval_ms,
                        "duration_ms": animation.duration_ms,
                        "start_frame": animation.start_frame,
                        "end_frame": animation.end_frame,
                        "frame_count": animation.frame_count,
                    },
                    "events": [
                        {
                            "time_ms": event.time_ms,
                            "type": event.event_type,
                            "name": event.event_name,
                            "parameter": event.parameter,
                        }
                        for event in animation.events
                    ],
                    "bundle_sidecar": _relative_path(bundle.sidecar_path, output),
                    "glb": (
                        _relative_path(bundle.glb_path, output)
                        if bundle.glb_path is not None
                        else None
                    ),
                    "matched_track_count": bundle.matched_track_count,
                    "authoring_only_track_count": bundle.authoring_only_track_count,
                }
            )
    except U9AnimatedModelBundleError as error:
        raise U9AnimatedModelSetError(str(error)) from error

    actors = {
        selection.rule.actor
        for selection, _animation in clips
        if selection.rule is not None
    }
    manifest = {
        "schema": ANIMATED_MODEL_SET_SCHEMA,
        "schema_version": ANIMATED_MODEL_SET_SCHEMA_VERSION,
        "model": {
            "id": model.model_id,
            "record_format": model.record_format,
            "selected_lod": lod_level,
            "actor": next(iter(actors)) if len(actors) == 1 else None,
        },
        "clip_count": len(clips),
        "clips": manifest_clips,
        "timeline": {
            "authored": False,
            "request_order_is_not_playback_order": True,
            "durations_are_original_clip_durations": True,
            "consumer_must_choose_looping_trimming_transitions_and_root_motion_policy": True,
        },
    }
    manifest_path = output / f"model_{model.model_id:05d}_animation_set.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return U9AnimatedModelSetResult(
        manifest_path=manifest_path,
        clip_sidecar_paths=tuple(sidecar_paths),
        clip_glb_paths=tuple(glb_paths),
        clip_count=len(clips),
    )
