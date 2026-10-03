"""Titan clip labels derived from the authoring path in each ``anim.flx`` entry.

Every used animation record stores the LightWave scene it was exported from::

    u:\\art\\motions\\humanoid\\movement\\lws\\walkfoward_avatar_none.lws

Titan names a clip by the directories under ``motions`` (or ``objects``) and
the file stem, dropping the ``lws`` folder: ``humanoid/movement/walkfoward_avatar_none``.
The spelling is the shipped file's, including its ``foward``.

The 857 used clips in retail 1.19F give 853 distinct labels. Four labels are
shared by two IDs each, where a clip was exported twice from one scene
(209/936, 211/937, 482/1084 and 602/1117); :meth:`U9AnimationLabels.ids_for`
returns both and callers must ask for an ID instead.
"""

from __future__ import annotations

__all__ = [
    "U9AnimationLabels",
    "U9AnimationSourceHints",
    "parse_animation_source_hints",
]

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PureWindowsPath

from titan.u9.animation import U9Animation


@dataclass(frozen=True)
class U9AnimationSourceHints:
    """Family, category and action words read from one clip's authoring path."""

    asset_group: str
    family: str
    category: str
    stem: str
    actor: str
    actor_basis: str
    action: str

    @property
    def label(self) -> str:
        return "/".join(
            value for value in (self.family, self.category, self.stem) if value
        )


def parse_animation_source_hints(source_name: str) -> U9AnimationSourceHints:
    """Split an ``anim.flx`` authoring path into Titan's label parts."""
    parts = list(PureWindowsPath(source_name).parts)
    lowered = [part.casefold() for part in parts]
    filename = parts[-1] if parts else source_name
    stem = PureWindowsPath(filename).stem.casefold()

    asset_group = "other"
    relative: list[str] = []
    for marker in ("motions", "objects"):
        if marker in lowered:
            marker_index = lowered.index(marker)
            asset_group = marker
            relative = [part.casefold() for part in parts[marker_index + 1 :]]
            break

    directories = relative[:-1]
    family = directories[0] if directories else ""
    category_parts = [part for part in directories[1:] if part != "lws"]
    category = "/".join(category_parts)

    actor = family
    actor_basis = "family-directory" if family else "none"
    if "avatar" in stem:
        actor = "avatar"
        actor_basis = "filename-token"
    elif "npc" in stem:
        actor = "npc"
        actor_basis = "filename-token"
    elif asset_group == "objects" and "_" in stem:
        actor = stem.split("_", 1)[0]
        actor_basis = "object-filename"

    action = stem
    family_prefix = f"{family}_"
    if family and action.startswith(family_prefix):
        action = action[len(family_prefix) :]
    for marker in ("_avatar", "_npc"):
        if marker in action:
            action = action.split(marker, 1)[0]
            break

    return U9AnimationSourceHints(
        asset_group=asset_group,
        family=family,
        category=category,
        stem=stem,
        actor=actor,
        actor_basis=actor_basis,
        action=action,
    )


def _normalize_label(label: str) -> str:
    return label.strip().replace("\\", "/").casefold()


class U9AnimationLabels:
    """Titan labels for a set of clips, indexed by animation ID and by label."""

    def __init__(self, labels: dict[int, str]) -> None:
        self._by_id = dict(labels)
        self._ids_by_label: dict[str, list[int]] = {}
        for animation_id in sorted(self._by_id):
            self._ids_by_label.setdefault(
                _normalize_label(self._by_id[animation_id]), []
            ).append(animation_id)

    @classmethod
    def from_animations(cls, animations: Iterable[U9Animation]) -> U9AnimationLabels:
        return cls(
            {
                animation.animation_id: parse_animation_source_hints(
                    animation.source_name
                ).label
                for animation in animations
            }
        )

    def label(self, animation_id: int) -> str | None:
        return self._by_id.get(animation_id)

    def ids_for(self, label: str) -> tuple[int, ...]:
        """Return every animation ID with this label (case-insensitive)."""
        return tuple(self._ids_by_label.get(_normalize_label(label), ()))
