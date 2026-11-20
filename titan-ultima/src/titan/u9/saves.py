"""List Ultima IX saves (``u9gameN.sav``) with their in-game descriptions."""

from __future__ import annotations

__all__ = ["list_saves", "resolve_save"]

from pathlib import Path
from typing import Optional

from titan._config import resolve_config_path
from titan._meta import SaveInfo
from titan.u9.install import existing_u9_path


def save_folder(config: dict) -> Optional[Path]:
    """``[u9.paths] savegame`` resolved against the base (default ``savegame``)."""
    section = config.get("u9", {})
    base = section.get("game", {}).get("base")
    value = section.get("paths", {}).get("savegame") or ("savegame" if base else None)
    path = resolve_config_path(value, base)
    return existing_u9_path(path) if path is not None else None


def list_saves(config: dict) -> list[SaveInfo]:
    """Every ``u9gameN.sav`` in the save folder, by slot; ``slot`` is the full path."""
    from titan.u9.save_browser import discover_u9_save_archives

    folder = save_folder(config)
    if folder is None or not folder.is_dir():
        return []
    saves = []
    for row in discover_u9_save_archives(folder):
        path = Path(row["path"])
        name = "" if row.get("read_error") else str(row.get("description") or "")
        saves.append(
            SaveInfo(
                slot=str(path), path=path, name=name, modified=path.stat().st_mtime
            )
        )
    return saves


def resolve_save(value: Optional[str], config: dict) -> Optional[Path]:
    """A save file path; no value means no save."""
    return Path(value).expanduser() if value else None
