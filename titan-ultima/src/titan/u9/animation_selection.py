"""Resolve confirmed U9 actor-state selectors to animation IDs.

The initial table covers the default Avatar movement controller confirmed by
Ghidra data.  It deliberately excludes weapon-specific combat movement and
does not choose among the several shipped Avatar model IDs.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_AVATAR_ANIMATION_SELECTIONS",
    "U9AnimationSelectionError",
    "U9AnimationSelectionRule",
    "U9ResolvedAnimationSelection",
    "resolve_animation_selector",
]

import re
from dataclasses import dataclass

from titan.u9.motion_ids import U9MotionIds


class U9AnimationSelectionError(Exception):
    """Raised when an animation selector is unknown, inconsistent, or ambiguous."""


@dataclass(frozen=True)
class U9AnimationSelectionRule:
    """One confirmed actor state to original motion mapping from Ghidra data."""

    actor: str
    state: str
    animation_id: int
    motion_name: str
    aliases: tuple[str, ...]
    travel_type: str
    movement_slot: str
    lockset: str | None
    root_translation_axes: tuple[str, ...]

    def to_metadata(self) -> dict[str, object]:
        """Return stable JSON metadata without presentation-timeline policy."""
        return {
            "actor": self.actor,
            "state": self.state,
            "travel_type": self.travel_type,
            "movement_slot": self.movement_slot,
            "equipment_context": "default/no weapon override",
            "controller_scope": "default humanoid movement inherited by Avatar",
            "lockset": self.lockset,
            "root_translation_axes": list(self.root_translation_axes),
            "selection_evidence": "confirmed by Ghidra data",
        }


@dataclass(frozen=True)
class U9ResolvedAnimationSelection:
    """A user selector resolved to one archive animation ID and motion name."""

    selector: str
    animation_id: int
    motion_name: str | None
    resolution: str
    rule: U9AnimationSelectionRule | None = None

    def to_metadata(self) -> dict[str, object]:
        """Return the resolution record written into an animation-set sidecar."""
        metadata: dict[str, object] = {
            "selector": self.selector,
            "resolution": self.resolution,
        }
        if self.rule is not None:
            metadata.update(self.rule.to_metadata())
        return metadata


DEFAULT_AVATAR_ANIMATION_SELECTIONS = (
    U9AnimationSelectionRule(
        actor="avatar",
        state="breathe",
        animation_id=172,
        motion_name="HUMANOID_IDLE_BREATHE_AVATAR",
        aliases=("avatar:breathe", "avatar:idle"),
        travel_type="walk",
        movement_slot="idle",
        lockset=None,
        root_translation_axes=("z",),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="run-forward",
        animation_id=173,
        motion_name="HUMANOID_MOVEMENT_RUNFOWARD_AVATAR_NONE",
        aliases=("avatar:run", "avatar:run-forward"),
        travel_type="run",
        movement_slot="forward",
        lockset="lower",
        root_translation_axes=("x", "z"),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="walk-forward",
        animation_id=174,
        motion_name="HUMANOID_MOVEMENT_WALKFOWARD_AVATAR_NONE",
        aliases=("avatar:walk", "avatar:walk-forward"),
        travel_type="walk",
        movement_slot="forward",
        lockset="lower",
        root_translation_axes=("x", "z"),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="run-left",
        animation_id=175,
        motion_name="HUMANOID_MOVEMENT_RUNLEFT_AVATAR_NONE",
        aliases=("avatar:run-left",),
        travel_type="run",
        movement_slot="left",
        lockset="lower",
        root_translation_axes=("z",),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="run-right",
        animation_id=176,
        motion_name="HUMANOID_MOVEMENT_RUNRIGHT_AVATAR_NONE",
        aliases=("avatar:run-right",),
        travel_type="run",
        movement_slot="right",
        lockset="lower",
        root_translation_axes=("z",),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="turn-left",
        animation_id=177,
        motion_name="HUMANOID_MOVEMENT_TURNLEFT_AVATAR_NONE",
        aliases=("avatar:turn-left",),
        travel_type="walk/run",
        movement_slot="turn-left",
        lockset="lower",
        root_translation_axes=(),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="turn-right",
        animation_id=178,
        motion_name="HUMANOID_MOVEMENT_TURNRIGHT_AVATAR_NONE",
        aliases=("avatar:turn-right",),
        travel_type="walk/run",
        movement_slot="turn-right",
        lockset="lower",
        root_translation_axes=(),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="walk-backward",
        animation_id=179,
        motion_name="HUMANOID_MOVEMENT_WALKBACK_AVATAR_NONE",
        aliases=("avatar:walk-back", "avatar:walk-backward"),
        travel_type="walk/run",
        movement_slot="backward",
        lockset="lower",
        root_translation_axes=("x", "z"),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="walk-left",
        animation_id=180,
        motion_name="HUMANOID_MOVEMENT_WALKLEFT_AVATAR_NONE",
        aliases=("avatar:walk-left",),
        travel_type="walk",
        movement_slot="left",
        lockset="lower",
        root_translation_axes=("z",),
    ),
    U9AnimationSelectionRule(
        actor="avatar",
        state="walk-right",
        animation_id=181,
        motion_name="HUMANOID_MOVEMENT_WALKRIGHT_AVATAR_NONE",
        aliases=("avatar:walk-right",),
        travel_type="walk",
        movement_slot="right",
        lockset="lower",
        root_translation_axes=("z",),
    ),
)


def _normalize_semantic_selector(value: str) -> str:
    normalized = re.sub(r"[\s_]+", "-", value.strip().casefold())
    return re.sub(r"-+", "-", normalized)


_RULES_BY_ALIAS = {
    _normalize_semantic_selector(alias): rule
    for rule in DEFAULT_AVATAR_ANIMATION_SELECTIONS
    for alias in rule.aliases
}
_NUMERIC_SELECTOR = re.compile(r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)$")


def resolve_animation_selector(
    selector: str,
    motion_ids: U9MotionIds | None = None,
) -> U9ResolvedAnimationSelection:
    """Resolve a numeric ID, exact motion name, or confirmed ``actor:state`` alias."""
    stripped = selector.strip()
    if not stripped:
        raise U9AnimationSelectionError("animation selector is empty")
    if _NUMERIC_SELECTOR.fullmatch(stripped):
        animation_id = int(stripped, 0)
        motion_name = motion_ids.name(animation_id) if motion_ids is not None else None
        return U9ResolvedAnimationSelection(
            selector=selector,
            animation_id=animation_id,
            motion_name=motion_name,
            resolution="animation-id",
        )

    rule = _RULES_BY_ALIAS.get(_normalize_semantic_selector(stripped))
    if rule is not None:
        if motion_ids is not None:
            motion = motion_ids.by_name(rule.motion_name)
            if motion is None:
                raise U9AnimationSelectionError(
                    f"animation selector {selector!r}: Ghidra motion-ID table does not "
                    f"contain {rule.motion_name}"
                )
            if motion.animation_id != rule.animation_id:
                raise U9AnimationSelectionError(
                    f"animation selector {selector!r}: confirmed ID {rule.animation_id} "
                    f"disagrees with Ghidra motion-ID table ID {motion.animation_id}"
                )
        return U9ResolvedAnimationSelection(
            selector=selector,
            animation_id=rule.animation_id,
            motion_name=rule.motion_name,
            resolution="actor-state",
            rule=rule,
        )

    if motion_ids is not None:
        motion = motion_ids.by_name(stripped)
        if motion is not None:
            return U9ResolvedAnimationSelection(
                selector=selector,
                animation_id=motion.animation_id,
                motion_name=motion.name,
                resolution="motion-name",
            )

    raise U9AnimationSelectionError(
        f"unknown animation selector {selector!r}; use an animation ID, an exact "
        "motion name with --motion-ids, or a confirmed actor:state alias"
    )
