"""List the save for titan's ``[md]`` config: the DOS ``SAVEGAME`` folder."""

from __future__ import annotations

__all__ = ["list_saves", "resolve_save"]

from pathlib import Path
from typing import Optional

from titan._dos_saves import list_folder_save, resolve_folder_save
from titan._meta import SaveInfo


def list_saves(config: dict) -> list[SaveInfo]:
    return list_folder_save(config, "md")


def resolve_save(value: Optional[str], config: dict) -> Optional[Path]:
    return resolve_folder_save(value, config, "md")
