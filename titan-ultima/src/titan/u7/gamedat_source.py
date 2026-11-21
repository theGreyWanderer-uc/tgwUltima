"""Let ``--save`` take an Exult save file as well as a GAMEDAT folder.

Exult saves (``exultNN<bg|si>.sav``, Flex or ZIP; see ``save_container``) hold
the same files Exult writes into GAMEDAT, ``mapNN/`` folders included. A save
is unpacked once into a cache folder named by its contents, so commands that
read a GAMEDAT folder can read any save without the user extracting it.
"""

from __future__ import annotations

__all__ = ["gamedat_cache_root", "u7_gamedat_folder"]

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from titan.errors import InvalidDataError

COMPLETE_MARKER = ".titan-complete"


def gamedat_cache_root() -> Path:
    """Where unpacked saves live: ``u7-saves`` in :func:`titan._config.cache_dir`."""
    from titan._config import cache_dir

    return cache_dir() / "u7-saves"


def u7_gamedat_folder(
    value: Optional[str | Path], *, cache_root: Optional[Path] = None
) -> Optional[str]:
    """A GAMEDAT folder for *value*: a folder as given, or a save file unpacked.

    Returns ``None`` for no value, so callers keep their configured default.
    Raises ``ValueError`` for a file that isn't a readable U7 save.
    """
    if value is None or str(value) == "":
        return None
    path = Path(value).expanduser()
    if not path.is_file():
        return str(value)

    from titan.u7.save import U7Save
    from titan.u7.save_extraction import extract_u7_save_members

    data = path.read_bytes()
    root = cache_root or gamedat_cache_root()
    target = root / hashlib.sha256(data).hexdigest()[:24]
    if (target / COMPLETE_MARKER).is_file():
        return str(target)

    try:
        save = U7Save.from_bytes(data)
    except ValueError as error:
        raise InvalidDataError(
            f"Not a U7 save or GAMEDAT folder: {path} ({error})"
        ) from error
    if not save.members:
        raise InvalidDataError(f"Not a U7 save or GAMEDAT folder: {path}")
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="unpack-", dir=root))
    try:
        extract_u7_save_members(save.members, staging / "gamedat")
        (staging / "gamedat" / COMPLETE_MARKER).write_text(str(path), encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        (staging / "gamedat").rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return str(target)
