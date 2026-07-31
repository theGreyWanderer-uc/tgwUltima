"""Ultima Online art.def redirect metadata support."""

from __future__ import annotations

__all__ = ["UOArtDef", "UOArtDefEntry"]

from dataclasses import dataclass
from pathlib import Path
import re

_LINE_RE = re.compile(
    r"^\s*(?P<source>\d+)\s+\{(?P<targets>[-?\d,\s]+)\}\s+(?P<hue>-?\d+)"
)


@dataclass(frozen=True)
class UOArtDefEntry:
    """One art.def redirect entry."""

    source: int
    targets: tuple[int, ...]
    hue: int

    @property
    def first_target(self) -> int | None:
        return self.targets[0] if self.targets else None


class UOArtDef:
    """Parsed art.def substitutions."""

    def __init__(self, entries: dict[int, UOArtDefEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_file(cls, path: str | Path) -> UOArtDef:
        entries: dict[int, UOArtDefEntry] = {}
        for raw_line in (
            Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
        ):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            match = _LINE_RE.match(line)
            if match is None:
                continue

            source = int(match.group("source"), 10)
            targets = tuple(
                int(value.strip(), 10)
                for value in match.group("targets").split(",")
                if value.strip()
            )
            hue = int(match.group("hue"), 10)
            entries[source] = UOArtDefEntry(source, targets, hue)

        return cls(entries)
