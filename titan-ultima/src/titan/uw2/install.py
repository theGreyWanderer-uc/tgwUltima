"""Discover Ultima Underworld II (UW2) installs for ``titan setup`` and front ends."""

from __future__ import annotations

__all__ = [
    "UW2_RESOURCE_NAMES",
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

UW2_RESOURCE_NAMES = {
    "palette": "PALS.DAT",
    "allpals": "ALLPALS.DAT",
    "levels": "LEV.ARK",
    "objects": "OBJECTS.DAT",
    "comobj": "COMOBJ.DAT",
    "terrain": "TERRAIN.DAT",
    "textures": "T64.TR",
    "doors": "DOORS.GR",
    "objects_gr": "OBJECTS.GR",
    "tmflat": "TMFLAT.GR",
    "tmobj": "TMOBJ.GR",
    "animo": "ANIMO.GR",
    "shades": "SHADES.DAT",
    "dl": "DL.DAT",
    "strings": "STRINGS.PAK",
}
"""UW2 files in ``DATA`` that titan reads; ``T64.TR`` identifies the game."""

_REQUIRED = ("palette", "levels", "textures")
_FOLDER_NAMES = (
    "Ultima Underworld 2",
    "Ultima Underworld II",
    "Ultima Underworld II - Labyrinth of Worlds",
    "UW2",
)


def install_candidates(config: dict) -> list[Path]:
    """Install protocol (see :func:`titan._meta.install_candidates`)."""
    return uw_install_candidates(config, "uw2", _FOLDER_NAMES)


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: UW2 installs at or below *path* (root or ``DATA``)."""
    return discover_uw_installs("uw2", path, UW2_RESOURCE_NAMES, _REQUIRED, "textures")


def install_config(install: Installation) -> dict:
    """Install protocol: ``[uw2.game]`` base."""
    return uw_install_config(install)
