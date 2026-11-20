"""Saves for DOS games that keep one ``SAVEGAME`` folder (Ultima VI, Martian Dreams).

The original games have a single save, the folder holding ``OBJLIST``. Its
``slot`` is the folder's full path, which the games' save parameters accept.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from titan._config import resolve_config_path
from titan._meta import SaveInfo


def save_folder(config: dict, section: str) -> Optional[Path]:
    """``[<section>.paths] savegame`` resolved against the base (default ``SAVEGAME``)."""
    game = config.get(section, {})
    base = game.get("game", {}).get("base")
    value = game.get("paths", {}).get("savegame") or ("SAVEGAME" if base else None)
    return resolve_config_path(value, base)


def list_folder_save(config: dict, section: str) -> list[SaveInfo]:
    folder = save_folder(config, section)
    if folder is None or not folder.is_dir():
        return []
    objlist = next((p for p in folder.iterdir() if p.name.upper() == "OBJLIST"), None)
    if objlist is None or not objlist.is_file():
        return []
    return [
        SaveInfo(
            slot=str(folder), path=folder, name="", modified=objlist.stat().st_mtime
        )
    ]


def resolve_folder_save(
    value: Optional[str], config: dict, section: str
) -> Optional[Path]:
    """A save folder path; no value means no save (the game's starting state)."""
    return Path(value).expanduser() if value else None
