"""List native Ultima 8 saves with their in-game descriptions.

The DOS game names a save ``U8SAVE.NNN`` in its save folder and keeps every
description in that folder's ``SGHEADER.DAT`` (``MainMenu`` in the original
``MAINMENU.C``): 12 records of 104 bytes, record *N* for ``U8SAVE.NNN``. A
record is the save menu's 4 lines of 26 bytes, each ended by a NUL, in DOS
code page 437. Slot 0 is the starting save.
"""

from __future__ import annotations

__all__ = ["list_saves", "read_save_names", "resolve_save"]

import re
from pathlib import Path
from typing import Optional

from titan._meta import SaveInfo
from titan.u8.install import resolve_u8_save, u8_save_dir

SAVE_NAME_RE = re.compile(r"^U8SAVE\.(\d{3})$", re.IGNORECASE)
HEADER_FILE = "SGHEADER.DAT"
HEADER_RECORDS = 12
RECORD_SIZE = 104
LINE_SIZE = 26


def read_save_names(save_dir: Path) -> dict[int, str]:
    """Descriptions from ``SGHEADER.DAT``, keyed by slot; missing file -> ``{}``."""
    header = next(
        (p for p in _children(save_dir) if p.name.upper() == HEADER_FILE), None
    )
    if header is None:
        return {}
    try:
        data = header.read_bytes()
    except OSError:
        return {}
    names: dict[int, str] = {}
    for slot in range(min(HEADER_RECORDS, len(data) // RECORD_SIZE)):
        record = data[slot * RECORD_SIZE : (slot + 1) * RECORD_SIZE]
        lines = (
            record[i : i + LINE_SIZE].split(b"\0", 1)[0].decode("cp437").strip()
            for i in range(0, RECORD_SIZE, LINE_SIZE)
        )
        text = " ".join(line for line in lines if line)
        if text:
            names[slot] = text
    return names


def list_saves(config: dict) -> list[SaveInfo]:
    """Every ``U8SAVE.NNN`` in the configured save folder, by slot number.

    ``slot`` is the number (``"3"``), which every U8 save parameter accepts.
    """
    save_dir = u8_save_dir(config)
    if save_dir is None:
        return []
    names = read_save_names(save_dir)
    saves = []
    for path in _children(save_dir):
        match = SAVE_NAME_RE.match(path.name)
        if not match or not path.is_file():
            continue
        number = int(match[1])
        saves.append(
            SaveInfo(
                slot=str(number),
                path=path,
                name=names.get(number, ""),
                modified=path.stat().st_mtime,
            )
        )
    return sorted(saves, key=lambda save: int(save.slot))


def resolve_save(value: Optional[str], config: dict) -> Optional[Path]:
    """A slot, file name or path for a U8 save parameter; see :func:`resolve_u8_save`."""
    return resolve_u8_save(value, config)


def _children(folder: Path) -> list[Path]:
    try:
        return list(folder.iterdir())
    except OSError:
        return []
