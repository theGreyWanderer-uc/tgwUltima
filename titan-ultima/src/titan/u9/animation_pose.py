"""Apply one Ultima IX animation clip to a rigid ``sappear.flx`` hierarchy.

This models the single-clip behavior recovered in the Ghidra decompile. A
matching track replaces a limb's local rotation. Track translation is used
only for the ``PELVIS``/``HIPS`` limb; root translation is returned separately
as object motion, and ordinary-limb translation plus all track scale values are
ignored by the shipped runtime.

Controller blending, upper/lower locksets, axis masks, reverse playback and
event dispatch are intentionally separate future layers.
"""

from __future__ import annotations

__all__ = ["U9AnimationPoseError", "U9AnimationPoseResult", "pose_model"]

from dataclasses import dataclass, replace

from titan.u9.animation import U9Animation, U9AnimationFrame
from titan.u9.model import U9Model

Vec3 = tuple[float, float, float]


class U9AnimationPoseError(Exception):
    """Raised when a clip cannot be applied to a model hierarchy."""


@dataclass(frozen=True)
class U9AnimationPoseResult:
    """A posed model plus track-compatibility and root-motion diagnostics."""

    model: U9Model
    time_ms: int
    matched_part_ids: tuple[int, ...]
    authoring_only_part_ids: tuple[int, ...]
    model_only_limb_ids: tuple[int, ...]
    pelvis_limb_id: int | None
    raw_root_translation: Vec3
    root_motion_delta: Vec3


def _subtract(left: Vec3, right: Vec3) -> Vec3:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _root_index(model: U9Model) -> int | None:
    limb_ids = {limb.limb_id for limb in model.limbs}
    return next(
        (
            index
            for index, limb in enumerate(model.limbs)
            if limb.is_root or limb.parent_id not in limb_ids
        ),
        None,
    )


def _sampled_parts(animation: U9Animation, time_ms: int) -> dict[int, U9AnimationFrame]:
    sampled: dict[int, U9AnimationFrame] = {}
    for part in animation.parts:
        frame = part.sample(time_ms)
        if frame is not None:
            sampled[part.part_id] = frame
    return sampled


def pose_model(
    model: U9Model,
    animation: U9Animation,
    time_ms: int,
) -> U9AnimationPoseResult:
    """Return ``model`` posed at ``time_ms`` using runtime-compatible rules.

    The clip and model are explicit because the retail runtime's model/class
    selection layer is not encoded in either archive. Negative times clamp to
    the first stored sample and times after the clip clamp to its last sample.
    """
    if model.record_format != "hierarchical":
        raise U9AnimationPoseError(
            f"model {model.model_id} uses the indexed record family and has no "
            "animatable limb hierarchy"
        )

    sampled = _sampled_parts(animation, time_ms)
    model_limb_ids = {limb.limb_id for limb in model.limbs}
    animation_part_ids = set(sampled)
    matched = model_limb_ids & animation_part_ids
    if not matched:
        raise U9AnimationPoseError(
            f"animation {animation.animation_id} and model {model.model_id} have "
            "no shared limb/part IDs"
        )

    pelvis_ids = {
        part.part_id
        for part in animation.parts
        if part.name.casefold() in {"pelvis", "hips"}
    }
    pelvis_limb_id = next(
        (limb.limb_id for limb in model.limbs if limb.limb_id in pelvis_ids),
        None,
    )

    root_index = _root_index(model)
    raw_root_translation: Vec3 = (0.0, 0.0, 0.0)
    root_motion_delta: Vec3 = (0.0, 0.0, 0.0)
    if root_index is not None:
        root = model.limbs[root_index]
        root_frame = sampled.get(root.limb_id)
        if root_frame is not None:
            raw_root_translation = root_frame.position
            root_motion_delta = _subtract(root_frame.position, root.position)

    posed_limbs = []
    for limb in model.limbs:
        frame = sampled.get(limb.limb_id)
        if frame is None:
            posed_limbs.append(limb)
            continue
        position = frame.position if limb.limb_id == pelvis_limb_id else limb.position
        posed_limbs.append(replace(limb, position=position, rotation=frame.rotation))

    return U9AnimationPoseResult(
        model=replace(model, limbs=tuple(posed_limbs)),
        time_ms=time_ms,
        matched_part_ids=tuple(sorted(matched)),
        authoring_only_part_ids=tuple(sorted(animation_part_ids - model_limb_ids)),
        model_only_limb_ids=tuple(sorted(model_limb_ids - animation_part_ids)),
        pelvis_limb_id=pelvis_limb_id,
        raw_root_translation=raw_root_translation,
        root_motion_delta=root_motion_delta,
    )
