"""Resolve U9 actor-state selectors to animation IDs.

The table names the default Avatar movement clips. Each entry is identified by
the authoring label stored in its ``anim.flx`` record
(``humanoid/movement/walkfoward_avatar_none`` and so on); see
:mod:`titan.u9.animation_labels`. It says which clip carries which motion, not
how the runtime chooses among them: weapon-specific combat movement, layered
controllers and the choice among the shipped Avatar model IDs are not covered.
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

from titan.u9.animation_labels import U9AnimationLabels


class U9AnimationSelectionError(Exception):
    """Raised when an animation selector is unknown, inconsistent, or ambiguous."""


@dataclass(frozen=True)
class U9AnimationSelectionRule:
    """One actor-state name for a clip identified by its authoring label."""

    actor: str
    state: str
    animation_id: int
    animation_label: str
    aliases: tuple[str, ...]

    def to_metadata(self) -> dict[str, object]:
        """Return stable JSON metadata without presentation-timeline policy."""
        return {
            "actor": self.actor,
            "state": self.state,
            "selection_evidence": "authoring label of the anim.flx record",
            "runtime_selection": "not yet decoded",
        }


@dataclass(frozen=True)
class U9ResolvedAnimationSelection:
    """A user selector resolved to one archive animation ID and its label."""

    selector: str
    animation_id: int
    animation_label: str | None
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


def _avatar_movement(
    state: str, animation_id: int, stem: str, *aliases: str
) -> U9AnimationSelectionRule:
    return U9AnimationSelectionRule(
        actor="avatar",
        state=state,
        animation_id=animation_id,
        animation_label=f"humanoid/movement/{stem}_avatar_none",
        aliases=aliases or (f"avatar:{state}",),
    )


DEFAULT_AVATAR_ANIMATION_SELECTIONS = (
    U9AnimationSelectionRule(
        actor="avatar",
        state="breathe",
        animation_id=172,
        animation_label="humanoid/idle/breathe_avatar",
        aliases=("avatar:breathe", "avatar:idle"),
    ),
    _avatar_movement("run-forward", 173, "runfoward", "avatar:run", "avatar:run-forward"),
    _avatar_movement(
        "walk-forward", 174, "walkfoward", "avatar:walk", "avatar:walk-forward"
    ),
    _avatar_movement("run-left", 175, "runleft"),
    _avatar_movement("run-right", 176, "runright"),
    _avatar_movement("turn-left", 177, "turnleft"),
    _avatar_movement("turn-right", 178, "turnright"),
    _avatar_movement(
        "walk-backward", 179, "walkback", "avatar:walk-back", "avatar:walk-backward"
    ),
    _avatar_movement("walk-left", 180, "walkleft"),
    _avatar_movement("walk-right", 181, "walkright"),
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


def _resolve_label(
    selector: str, labels: U9AnimationLabels
) -> U9ResolvedAnimationSelection | None:
    animation_ids = labels.ids_for(selector)
    if len(animation_ids) > 1:
        raise U9AnimationSelectionError(
            f"animation selector {selector!r} matches IDs "
            f"{', '.join(str(value) for value in animation_ids)}; use an ID"
        )
    if not animation_ids:
        return None
    return U9ResolvedAnimationSelection(
        selector=selector,
        animation_id=animation_ids[0],
        animation_label=labels.label(animation_ids[0]),
        resolution="animation-label",
    )


def resolve_animation_selector(
    selector: str,
    labels: U9AnimationLabels | None = None,
) -> U9ResolvedAnimationSelection:
    """Resolve a numeric ID, an authoring label, or an ``actor:state`` alias.

    ``labels`` comes from the archive being exported. With it, labels resolve
    and every alias is checked against the clip actually stored at its ID.
    """
    stripped = selector.strip()
    if not stripped:
        raise U9AnimationSelectionError("animation selector is empty")
    if _NUMERIC_SELECTOR.fullmatch(stripped):
        animation_id = int(stripped, 0)
        return U9ResolvedAnimationSelection(
            selector=selector,
            animation_id=animation_id,
            animation_label=labels.label(animation_id) if labels is not None else None,
            resolution="animation-id",
        )

    rule = _RULES_BY_ALIAS.get(_normalize_semantic_selector(stripped))
    if rule is not None:
        if labels is not None:
            stored = labels.label(rule.animation_id)
            if stored != rule.animation_label:
                raise U9AnimationSelectionError(
                    f"animation selector {selector!r}: expected clip "
                    f"{rule.animation_label} at ID {rule.animation_id}, but the "
                    f"archive holds {stored or 'no clip'} there"
                )
        return U9ResolvedAnimationSelection(
            selector=selector,
            animation_id=rule.animation_id,
            animation_label=rule.animation_label,
            resolution="actor-state",
            rule=rule,
        )

    if labels is not None:
        labelled = _resolve_label(selector, labels)
        if labelled is not None:
            return labelled

    raise U9AnimationSelectionError(
        f"unknown animation selector {selector!r}; use an animation ID, an "
        "authoring label such as humanoid/idle/breathe_avatar, or a known "
        "actor:state alias"
    )
