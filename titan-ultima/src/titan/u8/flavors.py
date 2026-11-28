"""Ultima VIII flavors: the configured install, by whose saves are used.

The same retail data can be played by the DOS game, Pentagram or ScummVM, and
each keeps its saves in its own place:

* **DOS**: ``U8SAVE.NNN`` in the game's save folder (``cloud_saves/SAVEGAME``
  for GOG, else ``SAVEGAME`` / the base); the format titan reads.
* **Pentagram**: ``U8SAVE.NNN`` in its profile's ``u8-save`` folder.
* **ScummVM**: ``<target>.NNN`` in ScummVM's save folder, for each ScummVM game
  whose ``gameid`` is ``ultima8``.

Whether titan can read an engine's saves is checked on the files themselves
(the DOS save signature), not assumed; a flavor whose saves are in another
format is still listed, with :attr:`~titan._meta.Flavor.saves_readable` off.
"""

from __future__ import annotations

__all__ = ["flavor_saves", "list_flavors", "scummvm_targets"]

import configparser
import os
import re
import sys
from pathlib import Path
from typing import Optional

from titan._meta import Flavor, Installation, SaveInfo, known_installs
from titan.u8.install import find_u8_engine_save, u8_save_dir
from titan.u8.save import U8SaveArchive

_DOS_NAME = re.compile(r"^U8SAVE\.\d{3}$", re.IGNORECASE)


def _numbered(folder: Path, prefix: str) -> list[Path]:
    """``<prefix>.NNN`` files in *folder*, by number."""
    pattern = re.compile(rf"^{re.escape(prefix)}\.(\d{{3}})$", re.IGNORECASE)
    try:
        found = [
            (int(m[1]), p)
            for p in folder.iterdir()
            if (m := pattern.match(p.name)) and p.is_file()
        ]
    except OSError:
        return []
    return [path for _, path in sorted(found)]


def _readable(files: list[Path]) -> Optional[bool]:
    """Whether the files carry the DOS save signature; ``None`` with no files."""
    if not files:
        return None
    signature = U8SaveArchive.SIGNATURE
    for path in files:
        try:
            with path.open("rb") as handle:
                if handle.read(len(signature)) != signature:
                    return False
        except OSError:
            return False
    return True


def _dos_save_dir(config: dict) -> Optional[Path]:
    """The DOS game's own save folder: the usual rule with an engine's
    ``savegame`` setting set aside."""
    section = config.get("u8", {})
    paths = {
        key: value
        for key, value in section.get("paths", {}).items()
        if key not in ("savegame", "nonfixed")
    }
    return u8_save_dir({"game": section.get("game", {}), "paths": paths})


def scummvm_config() -> Optional[Path]:
    """ScummVM's settings file on this platform, if it exists."""
    home = Path.home()
    candidates = [
        home / ".config/scummvm/scummvm.ini",
        home / ".scummvmrc",
        home / "Library/Preferences/ScummVM Preferences",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.insert(0, Path(appdata) / "ScummVM" / "scummvm.ini")
    return next((path for path in candidates if path.is_file()), None)


def _scummvm_default_saves() -> Path:
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / "ScummVM" / "Saves"
    if sys.platform == "darwin":
        return Path.home() / "Documents/ScummVM Savegames"
    return Path.home() / ".local/share/scummvm/saves"


def scummvm_targets(ini: Optional[Path] = None) -> list[tuple[str, str, Path]]:
    """``(target, description, save folder)`` for each Ultima 8 game ScummVM has."""
    ini = scummvm_config() if ini is None else ini
    if ini is None:
        return []
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(ini, encoding="utf-8")
    except (OSError, configparser.Error):
        return []
    default = parser.get("scummvm", "savepath", fallback="") or str(
        _scummvm_default_saves()
    )
    targets = []
    for target in parser.sections():
        if parser.get(target, "gameid", fallback="").lower() != "ultima8":
            continue
        saves = parser.get(target, "savepath", fallback="") or default
        description = parser.get(target, "description", fallback="") or target
        targets.append((target, description, Path(saves).expanduser()))
    return targets


def _flavor(
    install: Installation,
    key: str,
    title: str,
    engine: str,
    folder: Path,
    files: list[Path],
    default: bool,
) -> Flavor:
    readable = _readable(files)
    notes: list[str] = []
    if readable is False:
        notes.append(f"titan can't read {title}'s save format yet.")
    elif readable is None:
        notes.append("No saves yet.")
    return Flavor(
        "u8",
        key,
        title,
        "engine",
        install,
        engine,
        config={} if default else {"u8": {"paths": {"savegame": folder.as_posix()}}},
        saves_readable=readable is not False,
        notes=tuple(notes),
        default=default,
    )


def list_flavors(config: dict) -> list[Flavor]:
    """``titan._meta.list_flavors`` provider for ``u8``."""
    known = [
        install for install, configured in known_installs("u8", config) if configured
    ]
    if not known:
        return []
    install = known[0]
    current = u8_save_dir(config)
    flavors = []
    seen: set[str] = set()

    def add(
        key: str,
        title: str,
        engine: str,
        folder: Optional[Path],
        files: list[Path],
        prefix: str = "U8SAVE",
    ) -> None:
        if folder is None or not folder.is_dir():
            return
        marker = os.path.normcase(os.path.abspath(folder)) + "|" + prefix
        if marker in seen:
            return
        seen.add(marker)
        is_default = (
            current is not None
            and os.path.normcase(os.path.abspath(current))
            == os.path.normcase(os.path.abspath(folder))
            and prefix == "U8SAVE"
        )
        flavors.append(_flavor(install, key, title, engine, folder, files, is_default))

    dos = _dos_save_dir(config)
    add("dos", "DOS", "dos", dos, _numbered(dos, "U8SAVE") if dos else [])
    pentagram = find_u8_engine_save()
    pentagram_dir = pentagram.parent if pentagram else None
    if pentagram_dir is None:
        appdata = os.environ.get("APPDATA")
        guess = Path(appdata) / "Pentagram" / "u8-save" if appdata else None
        pentagram_dir = guess if guess and guess.is_dir() else None
    add(
        "pentagram",
        "Pentagram",
        "pentagram",
        pentagram_dir,
        _numbered(pentagram_dir, "U8SAVE") if pentagram_dir else [],
    )
    for target, description, folder in scummvm_targets():
        add(
            f"scummvm:{target}",
            f"ScummVM ({description})",
            "scummvm",
            folder,
            _numbered(folder, target),
            prefix=target,
        )
    if not any(flavor.default for flavor in flavors) and flavors:
        flavors[0] = Flavor(**{**flavors[0].__dict__, "default": True, "config": {}})
    if not flavors:
        flavors.append(
            Flavor(
                "u8",
                "configured",
                "Configured install",
                "install",
                install,
                default=True,
                notes=("No save folder found.",),
            )
        )
    return flavors


def flavor_saves(flavor: Flavor, config: dict) -> list[SaveInfo]:
    """``titan._meta.flavor_saves`` provider: the flavor's numbered saves."""
    from titan._meta import flavor_config
    from titan.u8.saves import list_saves

    if flavor.engine == "scummvm":
        folder = Path(
            str(flavor.config.get("u8", {}).get("paths", {}).get("savegame", ""))
        )  # type: ignore[union-attr]
        prefix = flavor.key.partition(":")[
            2
        ]  # scummvm:<target>; files are <target>.NNN
        return (
            [
                SaveInfo(
                    slot=str(path), path=path, name="", modified=path.stat().st_mtime
                )
                for path in _numbered(folder, prefix)
            ]
            if prefix and folder.is_dir()
            else []
        )
    return list_saves(flavor_config(flavor, config))
