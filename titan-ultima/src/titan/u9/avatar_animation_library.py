"""Build a complete, compatibility-labelled U9 Avatar animation library."""

from __future__ import annotations

__all__ = [
    "AVATAR_ANIMATION_LIBRARY_SCHEMA",
    "AVATAR_ANIMATION_LIBRARY_SCHEMA_VERSION",
    "U9AvatarAnimationLibraryError",
    "U9AvatarAnimationLibraryResult",
    "export_avatar_animation_library",
]

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from titan.u9.animation import U9Animation
from titan.u9.animation_selection import DEFAULT_AVATAR_ANIMATION_SELECTIONS
from titan.u9.animated_model_bundle import (
    DEFAULT_ANIMATED_MODEL_SCALE,
    U9AnimatedModelBundleError,
    U9AnimatedModelLibraryResult,
    export_animated_model_library,
)
from titan.u9.mesh_export import TextureResolver
from titan.u9.model import U9Model
from titan.u9.motion_ids import U9MotionId, U9MotionIds
from titan.u9.node_registry import U9NodeRegistry

AVATAR_ANIMATION_LIBRARY_SCHEMA = "titan.u9.avatar-animation-library"
AVATAR_ANIMATION_LIBRARY_SCHEMA_VERSION = 1

_AVATAR_TOKEN = re.compile(r"(?:^|_)AVATAR(?:_|$)")
_EQUIPMENT_LABELS = (
    "HANDONE",
    "HANDTWO",
    "POLEARM",
    "SHIELD",
    "STAFF",
    "BOW",
    "FIST",
    "GRAB",
)


class U9AvatarAnimationLibraryError(Exception):
    """Raised when Avatar-labelled clips cannot form an animation library."""


@dataclass(frozen=True)
class U9AvatarAnimationLibraryResult:
    """Exported Avatar library plus selection and compatibility totals."""

    export: U9AnimatedModelLibraryResult
    candidate_motion_count: int
    exported_clip_count: int
    unused_motion_ids: tuple[int, ...]
    incompatible_motion_ids: tuple[int, ...]
    category_counts: tuple[tuple[str, int], ...]


def _motion_classification(motion: U9MotionId) -> dict[str, object]:
    before_avatar, _, after_avatar = motion.name.partition("_AVATAR")
    prefix_tokens = before_avatar.split("_")
    family = prefix_tokens[0].casefold() if prefix_tokens else ""
    category = prefix_tokens[1].casefold() if len(prefix_tokens) > 1 else "other"
    action = "_".join(prefix_tokens[2:]).casefold()
    variant = after_avatar.removeprefix("_")
    equipment = next(
        (label.casefold() for label in _EQUIPMENT_LABELS if label in variant),
        "none" if variant.startswith("NONE") else None,
    )
    return {
        "actor": "avatar",
        "family": family,
        "category": category,
        "action": action,
        "variant_label": variant or None,
        "equipment_hint": equipment,
    }


def export_avatar_animation_library(
    model: U9Model,
    animations: Sequence[U9Animation],
    motion_ids: U9MotionIds,
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
    categories: Sequence[str] = (),
    lod_level: int = 0,
    coordinate_scale: float = DEFAULT_ANIMATED_MODEL_SCALE,
    include_glb: bool = True,
) -> U9AvatarAnimationLibraryResult:
    """Export every Avatar-labelled compatible clip, optionally by category."""
    wanted_categories = {category.strip().casefold() for category in categories}
    if "" in wanted_categories:
        raise U9AvatarAnimationLibraryError("Avatar library category cannot be empty")

    candidate_motions = tuple(
        motion for motion in motion_ids.entries if _AVATAR_TOKEN.search(motion.name)
    )
    if wanted_categories:
        candidate_motions = tuple(
            motion
            for motion in candidate_motions
            if _motion_classification(motion)["category"] in wanted_categories
        )
    if not candidate_motions:
        requested = ", ".join(sorted(wanted_categories)) or "Avatar"
        raise U9AvatarAnimationLibraryError(
            f"no {requested} animation names were found in the Ghidra motion table"
        )

    animations_by_id = {animation.animation_id: animation for animation in animations}
    model_part_ids = {limb.limb_id for limb in model.limbs}
    default_rules = {
        rule.animation_id: rule for rule in DEFAULT_AVATAR_ANIMATION_SELECTIONS
    }
    clips: list[tuple[U9Animation, str]] = []
    clip_metadata: dict[int, dict[str, object]] = {}
    unused_motion_ids: list[int] = []
    incompatible_motion_ids: list[int] = []
    category_counts: Counter[str] = Counter()

    for motion in candidate_motions:
        animation = animations_by_id.get(motion.animation_id)
        if animation is None:
            unused_motion_ids.append(motion.animation_id)
            continue
        matched_track_ids = sorted(
            {part.part_id for part in animation.parts} & model_part_ids
        )
        if not matched_track_ids:
            incompatible_motion_ids.append(motion.animation_id)
            continue

        classification = _motion_classification(motion)
        category = str(classification["category"])
        category_counts[category] += 1
        rule = default_rules.get(motion.animation_id)
        clip_metadata[motion.animation_id] = {
            **classification,
            "selection_basis": "explicit Avatar token in the original motion name",
            "compatibility_basis": "shared rigid limb IDs",
            "matched_track_count": len(matched_track_ids),
            "matched_track_ids": matched_track_ids,
            "authoring_only_track_count": (
                len(animation.parts) - len(matched_track_ids)
            ),
            "known_state": rule.state if rule is not None else None,
            "known_aliases": list(rule.aliases) if rule is not None else [],
            "runtime_selection_semantics": (
                "confirmed default movement state"
                if rule is not None
                else "not yet decoded"
            ),
        }
        clips.append((animation, motion.name))

    if not clips:
        raise U9AvatarAnimationLibraryError(
            f"model {model.model_id} shares no rigid limb IDs with the selected "
            "Avatar animations"
        )

    library_metadata: dict[str, object] = {
        "schema": AVATAR_ANIMATION_LIBRARY_SCHEMA,
        "schema_version": AVATAR_ANIMATION_LIBRARY_SCHEMA_VERSION,
        "actor": "avatar",
        "selection": {
            "rule": "original motion name contains the complete AVATAR token",
            "category_filter": sorted(wanted_categories),
            "requires_shared_rigid_limb_id": True,
        },
        "candidate_motion_count": len(candidate_motions),
        "exported_clip_count": len(clips),
        "unused_motion_ids": unused_motion_ids,
        "incompatible_motion_ids": incompatible_motion_ids,
        "category_counts": dict(sorted(category_counts.items())),
        "controller_scope": {
            "known_default_movement_states": len(default_rules),
            "other_runtime_state_mappings": "not yet decoded",
        },
        "timeline": {
            "authored": False,
            "consumer_selects_actions": True,
            "consumer_chooses_looping_trimming_transitions_and_root_motion_policy": True,
        },
    }
    try:
        exported = export_animated_model_library(
            model,
            clips,
            output_directory,
            model_archive_path=model_archive_path,
            animation_archive_path=animation_archive_path,
            registry=registry,
            registry_path=registry_path,
            motion_table_path=motion_table_path,
            texture_resolver=texture_resolver,
            texture_archive_path=texture_archive_path,
            palette_path=palette_path,
            lod_level=lod_level,
            coordinate_scale=coordinate_scale,
            include_glb=include_glb,
            library_metadata=library_metadata,
            clip_metadata=clip_metadata,
        )
    except U9AnimatedModelBundleError as error:
        raise U9AvatarAnimationLibraryError(str(error)) from error

    return U9AvatarAnimationLibraryResult(
        export=exported,
        candidate_motion_count=len(candidate_motions),
        exported_clip_count=len(clips),
        unused_motion_ids=tuple(unused_motion_ids),
        incompatible_motion_ids=tuple(incompatible_motion_ids),
        category_counts=tuple(sorted(category_counts.items())),
    )
