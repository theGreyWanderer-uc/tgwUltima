"""Ultima Online animation body-name metadata from packaged and client sources."""

from __future__ import annotations

__all__ = [
    "UOAnimationBodyName",
    "UOAnimationBodyNames",
    "load_animation_body_names",
]

import csv
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
import re

_DEF_COMMENT_RE = re.compile(
    r"^\s*(?P<body>\d+)\s+(?P<rest>.*?)\s+#\s*(?P<comment>.+?)\s*$"
)


@dataclass(frozen=True)
class UOAnimationBodyName:
    """One body-id/name clue for an animation body."""

    body: int
    name: str
    source: str
    detail: str


class UOAnimationBodyNames:
    """Aggregated body-id/name clues."""

    def __init__(self, entries: list[UOAnimationBodyName]) -> None:
        self.entries = entries
        self._by_body: dict[int, list[UOAnimationBodyName]] = {}
        for entry in entries:
            self._by_body.setdefault(entry.body, []).append(entry)

    def preferred(self, body: int) -> UOAnimationBodyName | None:
        entries = self._by_body.get(body)
        return entries[0] if entries else None

    def names_for(self, body: int) -> tuple[str, ...]:
        entries = self._by_body.get(body, [])
        names: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            key = entry.name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(entry.name)
        return tuple(names)


def load_animation_body_names(
    *,
    client: str | Path,
) -> UOAnimationBodyNames:
    """Load best-effort body-id names from packaged and client sources."""
    entries: list[UOAnimationBodyName] = []
    entries.extend(_load_packaged_body_names())

    root = Path(client)
    entries.extend(_load_client_def_comments(root))

    return UOAnimationBodyNames(_dedupe_entries(entries))


def _load_packaged_body_names() -> list[UOAnimationBodyName]:
    try:
        resource = resources.files("titan.uo.resources").joinpath(
            "animation_body_names.csv"
        )
    except ModuleNotFoundError:
        return []

    if not resource.is_file():
        return []

    entries: list[UOAnimationBodyName] = []
    with resource.open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                body = int(row.get("body", ""), 10)
            except ValueError:
                continue

            name = _clean_name(row.get("name", ""))
            if not name:
                continue

            entries.append(
                UOAnimationBodyName(
                    body=body,
                    name=name,
                    source=_clean_name(row.get("source", "")) or "titan:packaged",
                    detail=_clean_name(row.get("detail", "")),
                )
            )
    return entries


def _load_client_def_comments(client: Path) -> list[UOAnimationBodyName]:
    entries: list[UOAnimationBodyName] = []
    for filename in ("Body.def", "Bodyconv.def", "Corpse.def", "Equipconv.def"):
        path = client / filename
        if not path.is_file():
            continue
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(),
            1,
        ):
            match = _DEF_COMMENT_RE.match(raw_line)
            if match is None:
                continue
            name = _clean_name(match.group("comment"))
            if not name:
                continue
            entries.append(
                UOAnimationBodyName(
                    body=int(match.group("body"), 10),
                    name=name,
                    source=f"client:{filename}",
                    detail=f"{path.name}:{line_number}",
                )
            )
    return entries


def _dedupe_entries(
    entries: list[UOAnimationBodyName],
) -> list[UOAnimationBodyName]:
    priority = {
        "ouo:gm_body_names": 0,
        "client:Bodyconv.def": 1,
        "client:Body.def": 2,
        "client:Corpse.def": 3,
        "client:Equipconv.def": 4,
        "emulator:ModernUO": 5,
        "emulator:ServUO": 6,
        "emulator:RunUO": 7,
    }
    seen: set[tuple[int, str, str]] = set()
    unique: list[UOAnimationBodyName] = []
    for entry in sorted(
        entries,
        key=lambda item: (
            item.body,
            priority.get(item.source, 99),
            item.name.lower(),
            item.detail,
        ),
    ):
        key = (entry.body, entry.name.lower(), entry.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _clean_name(value: str) -> str:
    value = value.strip().strip("/")
    value = re.sub(r"\s+", " ", value)
    return value.strip()
