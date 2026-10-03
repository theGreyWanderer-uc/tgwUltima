"""Build a complete, compatibility-labelled U9 Avatar animation library.

Clips are chosen and classified from the authoring label in each ``anim.flx``
record (:mod:`titan.u9.animation_labels`): ``humanoid/combat/attack_avatar_bowaa``
is family ``humanoid``, category ``combat``, action ``attack`` and variant
``bowaa``, with the equipment hint ``bow``.
"""

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
from titan.u9.animation_labels import parse_animation_source_hints
from titan.u9.animation_selection import DEFAULT_AVATAR_ANIMATION_SELECTIONS
from titan.u9.animated_model_bundle import (
    DEFAULT_ANIMATED_MODEL_SCALE,
    U9AnimatedModelBundleError,
    U9AnimatedModelLibraryResult,
    export_animated_model_library,
)
from titan.u9.mesh_export import TextureResolver
from titan.u9.model import U9Model

from titan.u9.node_registry import U9NodeRegistry

AVATAR_ANIMATION_LIBRARY_SCHEMA = "titan.u9.avatar-animation-library"
AVATAR_ANIMATION_LIBRARY_SCHEMA_VERSION = 1

_AVATAR_TOKEN = re.compile(r"(?:^|_)avatar(?:_|$)")
_EQUIPMENT_LABELS = (
    "handone",
    "handtwo",
    "polearm",
    "shield",
    "staff",
    "bow",
    "fist",
    "grab",
)


class U9AvatarAnimationLibraryError(Exception):
    """Raised when Avatar-labelled clips cannot form an animation library."""


@dataclass(frozen=True)
class U9AvatarAnimationLibraryResult:
    """Exported Avatar library plus selection and compatibility totals."""

    export: U9AnimatedModelLibraryResult
    candidate_clip_count: int
    exported_clip_count: int
    incompatible_animation_ids: tuple[int, ...]
    category_counts: tuple[tuple[str, int], ...]


def _clip_classification(animation: U9Animation) -> dict[str, object]:
    hints = parse_animation_source_hints(animation.source_name)
    _, _, after_avatar = hints.stem.partition("_avatar")
    variant = after_avatar.removeprefix("_")
    equipment = next(
        (label for label in _EQUIPMENT_LABELS if label in variant),
        "none" if variant.startswith("none") else None,
    )
    family = hints.family
    category = hints.category.split("/", 1)[0] or "other"
    action = hints.action
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
    output_directory: str | Path,
    *,
    model_archive_path: str | Path,
    animation_archive_path: str | Path,
    registry: U9NodeRegistry | None = None,
    registry_path: str | Path | None = None,
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

    animations_by_id = {animation.animation_id: animation for animation in animations}
    candidate_ids = {
        animation.animation_id
        for animation in animations
        if _AVATAR_TOKEN.search(parse_animation_source_hints(animation.source_name).stem)
    }
    if wanted_categories:
        candidate_ids = {
            animation_id
            for animation_id in candidate_ids
            if _clip_classification(animations_by_id[animation_id])["category"]
            in wanted_categories
        }
    if not candidate_ids:
        requested = ", ".join(sorted(wanted_categories)) or "Avatar"
        raise U9AvatarAnimationLibraryError(
            f"no {requested} animation evidence was found for the Avatar library"
        )

    model_part_ids = {limb.limb_id for limb in model.limbs}
    default_rules = {
        rule.animation_id: rule for rule in DEFAULT_AVATAR_ANIMATION_SELECTIONS
    }
    clips: list[tuple[U9Animation, str | None]] = []
    clip_metadata: dict[int, dict[str, object]] = {}
    incompatible_animation_ids: list[int] = []
    category_counts: Counter[str] = Counter()

    for animation_id in sorted(candidate_ids):
        animation = animations_by_id[animation_id]
        matched_track_ids = sorted(
            {part.part_id for part in animation.parts} & model_part_ids
        )
        if not matched_track_ids:
            incompatible_animation_ids.append(animation_id)
            continue

        classification = _clip_classification(animation)
        category = str(classification["category"])
        category_counts[category] += 1
        rule = default_rules.get(animation_id)
        clip_metadata[animation_id] = {
            **classification,
            "selection_basis": ["Avatar token in the authoring label"],
            "compatibility_basis": "shared rigid limb IDs",
            "matched_track_count": len(matched_track_ids),
            "matched_track_ids": matched_track_ids,
            "authoring_only_track_count": (
                len(animation.parts) - len(matched_track_ids)
            ),
            "known_state": rule.state if rule is not None else None,
            "known_aliases": list(rule.aliases) if rule is not None else [],
            "runtime_selection_semantics": "not yet decoded",
        }
        clips.append(
            (animation, parse_animation_source_hints(animation.source_name).label)
        )

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
            "rules": ["authoring label contains an Avatar token"],
            "category_filter": sorted(wanted_categories),
            "requires_shared_rigid_limb_id": True,
        },
        "candidate_clip_count": len(candidate_ids),
        "exported_clip_count": len(clips),
        "incompatible_animation_ids": incompatible_animation_ids,
        "category_counts": dict(sorted(category_counts.items())),
        "controller_scope": {
            "named_movement_states": len(default_rules),
            "runtime_state_mappings": "not yet decoded",
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
        candidate_clip_count=len(candidate_ids),
        exported_clip_count=len(clips),
        incompatible_animation_ids=tuple(incompatible_animation_ids),
        category_counts=tuple(sorted(category_counts.items())),
    )
