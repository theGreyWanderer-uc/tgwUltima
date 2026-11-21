"""List Exult saves for Ultima VII (``exultNN<bg|si>.sav``) with their titles.

Exult writes ``<SAVEGAME>/exult%02d%s.sav`` (``fnames.h``), the suffix ``bg`` or
``si``, and stores the name typed in its save dialog as the Flex title or the
ZIP comment. Saves are looked for in ``[u7xx.paths] savegame``, the folder
holding GAMEDAT, and the game folder: Exult's usual save locations.

``slot`` is the save's full path, which every U7 ``--save`` accepts.
"""

from __future__ import annotations

__all__ = ["list_saves", "resolve_save", "save_folders"]

import re
from pathlib import Path
from typing import Optional

from titan._config import resolve_config_path
from titan._meta import SaveInfo

_SUFFIX = {"u7bg": "bg", "u7si": "si"}


def save_folders(config: dict, game_id: str) -> list[Path]:
    """Folders that may hold this game's Exult saves, most specific first."""
    section = config.get(game_id, {})
    base = section.get("game", {}).get("base")
    paths = section.get("paths", {})
    folders = [resolve_config_path(paths.get("savegame"), base)]
    gamedat = resolve_config_path(paths.get("gamedat"), base)
    if gamedat is None and base:
        gamedat = next(
            (
                Path(base) / n
                for n in ("gamedat", "GAMEDAT")
                if (Path(base) / n).is_dir()
            ),
            None,
        )
    if gamedat is not None:
        folders.append(gamedat.parent)
    folders.append(resolve_config_path(base))
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


def list_saves(config: dict, game_id: str) -> list[SaveInfo]:
    pattern = re.compile(rf"^exult(\d{{2,}}){_SUFFIX[game_id]}\.sav$", re.IGNORECASE)
    found: dict[str, tuple[int, Path]] = {}
    for folder in save_folders(config, game_id):
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
