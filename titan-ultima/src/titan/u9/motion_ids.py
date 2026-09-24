"""Reader for an optional Ultima IX animation-name table.

The retail data stores animation IDs and authoring paths but no original engine
symbol. An external analysis table can map each used ``anim.flx`` entry ID to
the name used by gameplay and movement logic::

    HUMANOID_IDLE_BREATHE_AVATAR = 172,

Titan reads this optional table when the user supplies it and does not bundle
the external names.
"""

from __future__ import annotations

__all__ = ["U9MotionId", "U9MotionIds", "U9MotionIdsError"]

import re
from dataclasses import dataclass
from pathlib import Path


class U9MotionIdsError(Exception):
    """Raised when an animation-name table cannot be parsed safely."""


_ENTRY_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(0[xX][0-9A-Fa-f]+|[0-9]+)\s*,",
    re.MULTILINE,
)


@dataclass(frozen=True)
class U9MotionId:
    """One original engine animation name and its ``anim.flx`` entry ID."""

    animation_id: int
    name: str

    @property
    def family(self) -> str:
        """Leading actor/object family token used by the generated symbol."""
        return self.name.split("_", 1)[0].casefold()


class U9MotionIds:
    """Validated motion symbols indexed by animation ID and by name."""

    def __init__(self, entries: tuple[U9MotionId, ...]) -> None:
        self.entries = entries
        self._by_id = {entry.animation_id: entry for entry in entries}
        self._by_name = {entry.name: entry for entry in entries}

    @classmethod
    def parse(cls, text: str) -> U9MotionIds:
        entries = tuple(
            U9MotionId(animation_id=int(match.group(2), 0), name=match.group(1))
            for match in _ENTRY_RE.finditer(text)
        )
        if not entries:
            raise U9MotionIdsError("no animation-name entries found")

        ids: dict[int, str] = {}
        names: set[str] = set()
        for entry in entries:
            previous = ids.get(entry.animation_id)
            if previous is not None:
                raise U9MotionIdsError(
                    f"animation ID {entry.animation_id} is assigned to both "
                    f"{previous} and {entry.name}"
                )
            if entry.name in names:
                raise U9MotionIdsError(f"duplicate motion name {entry.name}")
            ids[entry.animation_id] = entry.name
            names.add(entry.name)
        return cls(tuple(sorted(entries, key=lambda entry: entry.animation_id)))

    @classmethod
    def from_file(cls, path: str | Path) -> U9MotionIds:
        source = Path(path)
        try:
            text = source.read_text(encoding="latin-1")
        except OSError as error:
            raise U9MotionIdsError(
                f"could not read motion-ID header {source}: {error}"
            ) from error
        return cls.parse(text)

    def motion(self, animation_id: int) -> U9MotionId | None:
        return self._by_id.get(animation_id)

    def by_name(self, name: str) -> U9MotionId | None:
        return self._by_name.get(name.upper())

    def name(self, animation_id: int) -> str | None:
        motion = self.motion(animation_id)
        return motion.name if motion is not None else None

    def missing_animation_ids(self, animation_ids: list[int]) -> list[int]:
        """Return archive IDs that have no external animation name."""
        return [
            animation_id
            for animation_id in animation_ids
            if animation_id not in self._by_id
        ]

    def unused_motion_ids(self, animation_ids: list[int]) -> list[int]:
        """Return animation-name table IDs whose archive slots are unused."""
        used = set(animation_ids)
        return [
            entry.animation_id
            for entry in self.entries
            if entry.animation_id not in used
        ]
