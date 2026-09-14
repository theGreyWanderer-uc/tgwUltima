"""Read Ultima IX's global model and animation node-name registry."""

from __future__ import annotations

__all__ = ["U9NodeName", "U9NodeRegistry", "U9NodeRegistryError"]

import os
from dataclasses import dataclass


class U9NodeRegistryError(Exception):
    """Raised when ``static/registry.txt`` contains an invalid node mapping."""


@dataclass(frozen=True)
class U9NodeName:
    """One global node ID and authoring name from ``registry.txt``."""

    node_id: int
    name: str


class U9NodeRegistry:
    """Map shared ``sappear.flx`` limb and ``anim.flx`` part IDs to names."""

    def __init__(self, entries: tuple[U9NodeName, ...]) -> None:
        if not entries:
            raise U9NodeRegistryError("registry.txt contains no node mappings")
        self.entries = entries
        self._by_id = {entry.node_id: entry for entry in entries}

    @classmethod
    def from_text(cls, text: str) -> U9NodeRegistry:
        """Parse comment, blank, and ``decimal_id name`` lines."""
        entries: list[U9NodeName] = []
        seen: set[int] = set()
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            fields = line.split(maxsplit=1)
            if len(fields) != 2:
                raise U9NodeRegistryError(
                    f"registry.txt line {line_number}: expected 'decimal_id name'"
                )
            try:
                node_id = int(fields[0], 10)
            except ValueError as error:
                raise U9NodeRegistryError(
                    f"registry.txt line {line_number}: invalid decimal node ID "
                    f"{fields[0]!r}"
                ) from error
            name = fields[1].strip()
            if node_id <= 0:
                raise U9NodeRegistryError(
                    f"registry.txt line {line_number}: node ID must be positive"
                )
            if node_id in seen:
                raise U9NodeRegistryError(
                    f"registry.txt line {line_number}: duplicate node ID {node_id}"
                )
            if not name:
                raise U9NodeRegistryError(
                    f"registry.txt line {line_number}: node {node_id} has no name"
                )
            seen.add(node_id)
            entries.append(U9NodeName(node_id=node_id, name=name))
        return cls(tuple(entries))

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9NodeRegistry:
        """Read one ASCII-compatible ``static/registry.txt`` file."""
        try:
            with open(filepath, encoding="ascii", errors="replace") as stream:
                return cls.from_text(stream.read())
        except OSError as error:
            raise U9NodeRegistryError(
                f"could not read registry.txt at {filepath}: {error}"
            ) from error

    def name_for(self, node_id: int) -> str | None:
        """Return the registered node name, or ``None`` for an unknown ID."""
        entry = self._by_id.get(node_id)
        return entry.name if entry is not None else None

    def __len__(self) -> int:
        return len(self.entries)
