"""Discover Ultima Underworld (UW1) installs for ``titan setup`` and front ends."""

from __future__ import annotations

__all__ = [
    "UW1_RESOURCE_NAMES",
    "discover_installs",
    "install_candidates",
    "install_config",
]

from pathlib import Path

from titan._meta import Installation
from titan._uw_install import (
    discover_uw_installs,
    uw_install_candidates,
    uw_install_config,
)

UW1_RESOURCE_NAMES = {
    "palette": "PALS.DAT",
    "allpals": "ALLPALS.DAT",
    "levels": "LEV.ARK",
    "objects": "OBJECTS.DAT",
    "comobj": "COMOBJ.DAT",
    "terrain": "TERRAIN.DAT",
    "floors16": "F16.TR",
    "floors32": "F32.TR",
    "walls16": "W16.TR",
    "walls64": "W64.TR",
    "strings": "STRINGS.PAK",
}
"""UW1 files in ``DATA`` that titan reads; ``W64.TR`` identifies the game."""

_REQUIRED = ("palette", "levels", "walls64")
_FOLDER_NAMES = (
    "Ultima Underworld",
    "Ultima Underworld 1",
    "Ultima Underworld - The Stygian Abyss",
    "UW1",
    "UW",
)


def install_candidates(config: dict) -> list[Path]:
    """Install protocol (see :func:`titan._meta.install_candidates`)."""
    return uw_install_candidates(config, "uw1", _FOLDER_NAMES)


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: UW1 installs at or below *path* (root or ``DATA``)."""
    return discover_uw_installs("uw1", path, UW1_RESOURCE_NAMES, _REQUIRED, "walls64")


def install_config(install: Installation) -> dict:
    """Install protocol: ``[uw1.game]`` base."""
    return uw_install_config(install)
