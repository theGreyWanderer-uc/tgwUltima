"""Discover archive destinations for retail games, mods, and Exult custom games.

Mods and Exult custom games come from :mod:`titan.u7.mods`; a target is one
of those with a patch folder, or the retail game itself (:func:`base_target`).
"""

from __future__ import annotations

# Exult configs are read with titan.u7.mods' DTD-rejecting parser.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from pathlib import Path

from titan._meta import Installation
from titan.fonts.exult_cfg import ExultGamePaths
from titan.u7.install import existing_path
from titan.u7.mods import (
    U7Mod,
    _game_save_root,
    _read_config_xml,
    discover_u7_mods,
)

__all__ = [
    "ArchiveTarget",
    "base_target",
    "discover_targets",
    "mod_targets",
    "target_from_folder",
    "_read_config_xml",
]


@dataclass(frozen=True)
class ArchiveTarget:
    name: str
    static: Path | None
    patch: Path
    standalone: bool = False
    root: Path | None = None
    gamedat: Path | None = None
    save_root: Path | None = None


def target_from_folder(folder: Path, game_static: Path | None) -> ArchiveTarget:
    """A game owns STATIC; a conventional mod inherits its selected retail base."""
    folder = existing_path(folder.expanduser().absolute())
    if not folder.is_dir():
        raise ValueError(f"Mod or Exult game folder not found: {folder}")
    if folder.name.lower() == "patch":
        root, patch = folder.parent, folder
    else:
        root, patch = folder, existing_path(folder / "patch")
    own_static = existing_path(root / "static")
    standalone = own_static.is_dir()
    return ArchiveTarget(
        root.name,
        own_static if standalone else game_static,
        patch,
        standalone,
        root,
        existing_path(root / "gamedat")
        if existing_path(root / "gamedat").is_dir()
        else None,
        root,
    )


def base_target(
    game: str,
    install: Installation | None,
    static: Path | None,
    paths: ExultGamePaths | None,
) -> ArchiveTarget:
    """The retail game itself, from the configured install record: its
    ``gamedat`` and ``savegame`` (see ``titan.u7.install.configured_install``)
    and Exult's patch folder."""
    root = install.root if install is not None and install.root != Path() else None
    if root is None and paths and paths.game_path:
        root = Path(paths.game_path).expanduser()
    resources = install.resources if install is not None else {}
    gamedat = resources.get("gamedat")
    gamedat = existing_path(gamedat) if gamedat else None
    if gamedat is not None and not gamedat.is_dir():
        gamedat = None
    patch = (
        Path(paths.patch_path).expanduser()
        if paths and paths.patch_path
        else (root or Path.cwd()) / "patch"
    )
    return ArchiveTarget(
        f"Base {game.upper()} game",
        static,
        existing_path(patch),
        False,
        root,
        gamedat,
        resources.get("savegame") or (gamedat.parent if gamedat else root),
    )


def mod_targets(mods: list[U7Mod], game_static: Path | None) -> list[ArchiveTarget]:
    """The mods and Exult games with a patch folder, as picker targets named by
    :attr:`U7Mod.label`, sorted by name."""
    targets = [
        ArchiveTarget(
            mod.label,
            mod.static or game_static,
            mod.patch,
            mod.static is not None,
            mod.install_dir or mod.patch.parent,
            mod.gamedat,
            mod.saves,
        )
        for mod in mods
        if mod.patch is not None
    ]
    return sorted(targets, key=lambda target: target.name.lower())


def discover_targets(
    game: str,
    config: dict,
    game_static: Path | None,
    exult_paths: ExultGamePaths | None,
    exult_cfg_path: Path | None,
) -> list[ArchiveTarget]:
    """Titan settings, installed mods and custom ``exult.cfg`` games as targets
    (:func:`titan.u7.mods.discover_u7_mods`, Exult's save folder read from
    *exult_cfg_path*)."""
    save_root = None
    if exult_cfg_path:
        tag = "blackgate" if game.upper() == "BG" else "serpentisle"
        base = config.get("u7bg" if game.upper() == "BG" else "u7si", {})
        base = base.get("game", {}).get("base")
        try:
            entry = _read_config_xml(exult_cfg_path).find(f"disk/game/{tag}")
        except (OSError, ValueError, ET.ParseError):
            entry = None
        save_root = _game_save_root(
            entry, tag, exult_cfg_path, Path(base) if base else None
        )
    mods = discover_u7_mods(
        game,
        config,
        exult_paths=exult_paths,
        exult_cfg_path=exult_cfg_path,
        save_root=save_root,
    )
    return mod_targets(mods, game_static)
