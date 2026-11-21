"""Shared install discovery for the two Ultima Underworld games.

Both games keep their data in a ``DATA`` folder below the install root, with
the same core files (``LEV.ARK``, ``PALS.DAT``). The texture archives tell
them apart: UW1 ships ``W64.TR`` wall textures, UW2 ships ``T64.TR``. That lets
a GOG "1+2" bundle folder hold both without either being mistaken for the
other.
"""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Mapping

from titan._meta import Installation

_SKIP_DIRS = {"data", "saves", "crit", "cuts", "sound", "dosbox"}


def data_directory(path: Path) -> Path:
    """The ``DATA`` folder for an install root, or *path* itself if it is one."""
    return path if path.name.upper() == "DATA" else path / "DATA"


def _child(directory: Path, name: str) -> Path:
    """*directory* / *name*, matching the name's case as it exists on disk."""
    exact = directory / name
    if exact.exists():
        return exact
    try:
        return next(
            (item for item in directory.iterdir() if item.name.upper() == name.upper()),
            exact,
        )
    except OSError:
        return exact


def uw_resource_paths(root: Path, names: Mapping[str, str]) -> dict[str, Path]:
    """The files in *names* that exist in *root*'s ``DATA`` folder."""
    data = data_directory(root)
    found = {key: _child(data, name) for key, name in names.items()}
    return {key: path for key, path in found.items() if path.is_file()}


def inspect_uw_install(
    game_id: str,
    path: Path,
    names: Mapping[str, str],
    required: tuple[str, ...],
    signature: str,
) -> Installation | None:
    """The install at *path* (its root or ``DATA`` folder) if its ``DATA``
    holds the game's *signature* file. Missing *required* keys are problems."""
    path = path.expanduser().absolute()
    root = path.parent if path.name.upper() == "DATA" else path
    try:
        if not _child(data_directory(root), names[signature]).is_file():
            return None
    except OSError:
        return None
    resources = uw_resource_paths(root, names)
    problems = {key: "NOT FOUND" for key in required if key not in resources}
    return Installation(game_id, root, resources, problems)


def discover_uw_installs(
    game_id: str,
    path: Path,
    names: Mapping[str, str],
    required: tuple[str, ...],
    signature: str,
    *,
    max_depth: int = 2,
) -> list[Installation]:
    """Installs at or up to two levels below *path*, visiting at most 64 folders."""
    pending = deque([(path.expanduser().absolute(), 0)])
    found: list[Installation] = []
    visited = 0
    while pending and visited < 64:
        directory, depth = pending.popleft()
        visited += 1
        install = inspect_uw_install(game_id, directory, names, required, signature)
        if install is not None:
            found.append(install)
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        pending.extend(
            (child, depth + 1)
            for child in children
            if child.name.lower() not in _SKIP_DIRS
            and not child.is_symlink()
            and child.is_dir()
        )
    return found


def uw_install_candidates(
    config: dict, section: str, names: tuple[str, ...]
) -> list[Path]:
    """Configured base, then GOG, Heroic and manual folders for an Underworld game.

    Any launcher-root folder with "underworld" in its name is included, so
    bundle folders are searched by :func:`discover_uw_installs`.
    """
    candidates: list[Path] = []
    base = config.get(section, {}).get("game", {}).get("base")
    if base:
        candidates.append(Path(base).expanduser())
    roots = [
        Path(f"{drive}:/") / layout
        for layout in (
            "Program Files (x86)/GOG Galaxy/Games",
            "GOG Games",
            "Ultima",
            "",
        )
        for drive in "CDEFG"
    ]
    roots += [Path.home() / "GOG Games", Path.home() / "Games/Heroic"]
    for root in roots:
        candidates.extend(root / name for name in names)
        try:
            candidates.extend(
                child
                for child in sorted(root.iterdir())
                if child.is_dir()
                and (
                    "underworld" in child.name.casefold()
                    or re.fullmatch(r"uu?w[12]?", child.name.casefold())
                )
            )
        except OSError:
            continue
    return list(dict.fromkeys(candidates))


def uw_install_config(install: Installation) -> dict:
    """``[uw1.game]`` / ``[uw2.game]`` base: commands find every file from it."""
    return {"game": {"base": install.root.as_posix()}}
