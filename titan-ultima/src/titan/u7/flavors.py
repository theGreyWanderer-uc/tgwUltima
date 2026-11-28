"""Ultima VII flavors: each known install, by the engine that has state there.

One folder of retail data can be played by Exult, by the original DOS game
(DOSBox, a GOG copy), or both. Each leaves its own state, so that is what
decides the flavor, not the folder's name:

* **Exult**: Exult's settings point at the folder, or it holds Exult's state
  (a GAMEDAT with ``exult.ver``, ``exultNN<bg|si>.sav`` saves). Exult's mods
  and custom games for the game sit under this flavor.
* **DOS**: the folder has the DOS game's own ``GAMEDAT`` (no ``exult.ver``) or
  ``GAMEnn.U7`` saves; commands then use that GAMEDAT and those saves.
* Neither: the install alone (its STATIC data), with no live state.

Installs are the ones a person pointed titan at (:func:`titan._meta.known_installs`).
"""

from __future__ import annotations

__all__ = ["flavor_saves", "list_flavors"]

import os
import re
from pathlib import Path
from typing import Optional

from titan._meta import (
    Flavor,
    Installation,
    SaveInfo,
    _install_key,
    _install_title,
    flavor_config,
    get_game,
    known_installs,
)
from titan.u7.install import (
    _GAME_LETTERS,
    existing_path,
    exult_game_paths,
    install_config,
)

_EXULT_SAVE = re.compile(r"^exult\d{2,}[a-z]+\.sav$", re.IGNORECASE)
_DOS_SAVE = re.compile(r"^game\d{2}\.u7$", re.IGNORECASE)


def _same(a: Optional[Path], b: Optional[Path]) -> bool:
    if a is None or b is None:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _names(folder: Path) -> list[str]:
    try:
        return [path.name for path in folder.iterdir()]
    except OSError:
        return []


def _exult_gamedat(folder: Optional[Path]) -> bool:
    return folder is not None and (existing_path(folder) / "exult.ver").is_file()


def engines(install: Installation, exult_base: Optional[Path]) -> list[str]:
    """``"exult"`` and/or ``"dos"``: which engines have state at *install*."""
    root = install.root
    names = _names(root)
    gamedat = existing_path(root / "GAMEDAT")
    exult = (
        _same(root, exult_base)
        or _exult_gamedat(install.resources.get("gamedat"))
        or _exult_gamedat(gamedat)
        or any(_EXULT_SAVE.match(name) for name in names)
    )
    dos_gamedat = (
        gamedat.is_dir() and not _exult_gamedat(gamedat) and bool(_names(gamedat))
    )
    dos = dos_gamedat or any(_DOS_SAVE.match(name) for name in names)
    return [engine for engine, present in (("exult", exult), ("dos", dos)) if present]


def _overlay(install: Installation, section: str, **paths: Path) -> dict:
    """``[section]`` ``game``/``paths`` tables selecting *install*, with *paths* set;
    the user's mods table is left alone."""
    tables = install_config(install)
    table_paths = dict(tables.get("paths", {}))
    table_paths.update({key: value.as_posix() for key, value in paths.items()})
    return {section: {"game": tables["game"], "paths": table_paths}}


def list_flavors(config: dict, game_id: str) -> list[Flavor]:
    """``titan._meta.list_flavors`` provider for ``u7bg`` / ``u7si``."""
    from titan.u7.mods import list_mods

    game = get_game(game_id)
    section = game.config_section  # type: ignore[union-attr]
    option = {"game": game.game_option or ""}  # type: ignore[union-attr]
    exult = exult_game_paths(_GAME_LETTERS[game_id])
    exult_base = exult.get("base")
    flavors: list[Flavor] = []
    mods_parent: Optional[tuple[str, Installation]] = None
    for install, configured in known_installs(game_id, config):
        prefix = "" if configured else _install_key(install, configured) + "/"
        label = "" if configured else _install_title(install, configured) + " "
        found = engines(install, exult_base)
        configured_gamedat = install.resources.get("gamedat") if configured else None
        default_engine = (
            (
                "exult"
                if _exult_gamedat(configured_gamedat)
                else "dos"
                if configured_gamedat
                else None
            )
            if configured
            else None
        )
        if default_engine not in found:
            default_engine = found[0] if configured and found else None
        if "exult" in found:
            key = prefix + "exult"
            gamedat = (
                configured_gamedat
                if default_engine == "exult"
                else exult.get("gamedat")
            )
            flavors.append(
                Flavor(
                    game_id,
                    key,
                    f"{label}Exult".strip() if label else "Exult",
                    "engine",
                    install,
                    "exult",
                    args=option,
                    config={}
                    if default_engine == "exult"
                    else _overlay(
                        install, section, **({"gamedat": gamedat} if gamedat else {})
                    ),
                    default=default_engine == "exult",
                )
            )
            if mods_parent is None and (configured or _same(install.root, exult_base)):
                mods_parent = (key, install)
        if "dos" in found:
            root = install.root
            flavors.append(
                Flavor(
                    game_id,
                    prefix + "dos",
                    f"{label}DOS".strip() if label else "DOS",
                    "engine",
                    install,
                    "dos",
                    args=option,
                    config={}
                    if default_engine == "dos"
                    else _overlay(
                        install,
                        section,
                        gamedat=existing_path(root / "GAMEDAT"),
                        savegame=root,
                    ),
                    default=default_engine == "dos",
                )
            )
        if not found:
            flavors.append(
                Flavor(
                    game_id,
                    prefix + "install",
                    _install_title(install, configured),
                    "install",
                    install,
                    args=option,
                    config={} if configured else _overlay(install, section),
                    default=configured,
                    notes=("No saved game state here yet.",),
                )
            )
    if mods_parent is not None:
        parent_key, install = mods_parent
        for mod in list_mods(config, game_id):
            flavors.append(
                Flavor(
                    game_id,
                    f"{mod.kind}:{mod.key}",
                    mod.title,
                    mod.kind,
                    install,
                    "exult",
                    parent=parent_key,
                    args={**option, "mod": mod.key},
                    notes=() if mod.played else ("Not played in Exult yet.",),
                )
            )
    return flavors


def flavor_saves(flavor: Flavor, config: dict, game_id: str) -> list[SaveInfo]:
    """``titan._meta.flavor_saves`` provider: Exult's or the DOS game's saves."""
    from titan.u7.saves import list_dos_saves, list_saves

    if flavor.kind in ("mod", "exult-game"):
        return list_saves(config, game_id, mod=flavor.args.get("mod"))
    if flavor.engine == "exult":
        return list_saves(flavor_config(flavor, config), game_id)
    if flavor.engine == "dos" and flavor.install is not None:
        return list_dos_saves(flavor.install.root)
    return []
