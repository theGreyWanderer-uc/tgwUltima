"""List Exult saves for Ultima VII (``exultNN<bg|si>.sav``) with their titles.

Exult writes ``<SAVEGAME>/exult%02d%s.sav`` (``fnames.h``), the suffix ``bg`` or
``si``, and stores the name typed in its save dialog as the Flex title or the
ZIP comment. Saves are looked for in the install record's ``savegame``
(``[u7xx.paths] savegame``, else Exult's save folder), the folder holding
GAMEDAT, and the game folder: Exult's usual save locations.

``slot`` is the save's full path, which every U7 ``--save`` accepts.
"""

from __future__ import annotations

__all__ = ["list_saves", "resolve_save", "save_folders"]

import re
from pathlib import Path
from typing import Optional

from titan._meta import SaveInfo

_SUFFIX = {"u7bg": "bg", "u7si": "si"}


def save_folders(config: dict, game_id: str, mod: Optional[str] = None) -> list[Path]:
    """Folders that may hold this game's Exult saves, most specific first: the
    install record's ``savegame``, the folder holding its ``gamedat``, the game
    folder. For *mod* (a ``titan.u7.mods`` key): its saves folder, the folder
    holding its GAMEDAT, and its Exult profile folder."""
    if mod:
        from titan.u7.mods import configured_u7_mods, find_u7_mod

        found = find_u7_mod(configured_u7_mods(config, game_id), mod)
        if found is None:
            return []
        folders = [
            found.saves,
            found.gamedat.parent if found.gamedat is not None else None,
            found.profile_dir,
        ]
    else:
        from titan.u7.install import configured_install

        install = configured_install(config, game_id)
        if install is None:
            return []
        gamedat = install.resources.get("gamedat")
        folders = [
            install.resources.get("savegame"),
            gamedat.parent if gamedat is not None else None,
            install.root if install.root != Path() else None,
        ]
    unique: dict[str, Path] = {}
    for folder in folders:
        if folder is not None and folder.is_dir():
            unique.setdefault(str(folder.resolve()).casefold(), folder)
    return list(unique.values())


def _title(path: Path) -> str:
    from titan.u7.save import U7Save

    try:
        save = U7Save.from_file(str(path))
    except (OSError, ValueError):
        return ""
    title = (save.title or "").strip()
    if title:
        return title
    # Exult also writes the save name as the ZIP comment (gamedat.cc zipClose).
    comment = save.zip_comment or b""
    return comment.decode("latin-1").strip()


def list_saves(config: dict, game_id: str, mod: Optional[str] = None) -> list[SaveInfo]:
    # A mod's or Exult game's own folder holds only its saves, whatever suffix
    # Exult gives them (a custom game under development writes exultNNdev.sav).
    suffix = "[a-z]+" if mod else _SUFFIX[game_id]
    pattern = re.compile(rf"^exult(\d{{2,}}){suffix}\.sav$", re.IGNORECASE)
    found: dict[str, tuple[int, Path]] = {}
    for folder in save_folders(config, game_id, mod):
        for path in folder.iterdir():
            match = pattern.match(path.name)
            if match and path.is_file():
                found.setdefault(str(path.resolve()).casefold(), (int(match[1]), path))
    return [
        SaveInfo(
            slot=str(path), path=path, name=_title(path), modified=path.stat().st_mtime
        )
        for _, path in sorted(found.values(), key=lambda item: (item[0], str(item[1])))
    ]


def resolve_save(value: Optional[str], config: dict) -> Optional[Path]:
    """A save file or GAMEDAT folder path; no value means the configured GAMEDAT."""
    return Path(value).expanduser() if value else None
