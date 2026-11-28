"""Ultima Online flavors: one per client install.

Each ``[uo.installs.*]`` entry is its own client (the EA Classic Client, UO
Forever's, another freeshard's), with its own files, output folder, MUL/UOP
preferences and server references. Clients the registry records (EA's
installer, the classic ``Origin Worlds Online`` key freeshard installers write)
that no entry names are listed too, as are installs without named entries
(``[uo.game] base``): the default flavors.
"""

from __future__ import annotations

__all__ = ["list_flavors"]

import os

from titan._meta import Flavor, Installation, default_flavors
from titan.uo.installs import configured_installs, discover_installs


def list_flavors(config: dict) -> list[Flavor]:
    """``titan._meta.list_flavors`` provider for ``uo``."""
    installs = configured_installs(config)
    if not installs:
        return default_flavors("uo", config)

    def same(a: object, b: object) -> bool:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(
            os.path.abspath(str(b))
        )

    default_name = str(
        config.get("uo", {}).get("game", {}).get("install") or ""
    ).lower()
    base = config.get("uo", {}).get("game", {}).get("base")
    flavors = []
    for name, entry in installs.items():
        found = discover_installs(entry.path) if entry.path.is_dir() else []
        if found:
            install = found[0]
        else:
            install = Installation("uo", entry.path, {}, {"root": "NOT FOUND"})
        notes = []
        if entry.multis != "auto" or entry.maps != "auto":
            notes.append(f"Reads multis from {entry.multis}, maps from {entry.maps}.")
        if entry.reference.get("server_profile"):
            notes.append(f"Server profile: {entry.reference['server_profile']}")
        is_default = name == default_name or (
            not default_name and base and same(base, entry.path)
        )
        flavors.append(
            Flavor(
                "uo",
                f"client:{entry.name}",
                entry.label or entry.name,
                "client",
                install,
                args={"client": entry.name},
                config={} if is_default else {"uo": {"game": {"install": entry.name}}},
                notes=tuple(notes),
                default=bool(is_default),
            )
        )
    named = [entry.path for entry in installs.values()]
    for flavor in default_flavors("uo", config):
        root = flavor.install.root if flavor.install else None
        if (
            not flavor.default
            and root is not None
            and not any(same(root, p) for p in named)
        ):
            flavors.append(flavor)
    return flavors
