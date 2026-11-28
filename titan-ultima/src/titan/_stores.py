"""Find game folders from what stores and launchers record locally.

Steam (``libraryfolders.vdf`` + ``appmanifest_*.acf``), GOG on Windows (the
``GOG.com\\Games`` registry keys, confirmed by ``goggame-*.info``), Heroic
(``gog_store/installed.json``), Lutris (``pga.db``), EA's installer, the classic
UO client registration (``Origin Worlds Online``), Windows' installed-programs
list and the folders a user lists in ``[search] folders``. Nothing here goes online: each launcher's own files say
what's installed and where, which beats guessing folder names.

Every record is only a lead. Which game a folder holds, and whether it's
complete, is decided by that game's install module (``discover_installs``);
:data:`CATALOGUE` just says which records are worth asking about. A store folder
can hold several games (GOG's Ultima 7 and Underworld bundles).

Readers never raise for a missing or unreadable launcher: they return nothing.
"""

from __future__ import annotations

__all__ = [
    "CATALOGUE",
    "drives",
    "guess_roots",
    "matches",
    "matching",
    "parse_vdf",
    "refresh",
    "store_records",
]

import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from titan._meta import InstallSource

# --- catalogue -------------------------------------------------------------


@dataclass(frozen=True)
class CatalogueEntry:
    """How store records name one game."""

    titles: tuple[str, ...]
    """Regexes searched in a normalized title or folder name (lower case, no
    trademark signs, punctuation as spaces; see :func:`normalize`)."""
    store_ids: frozenset[tuple[str, str]] = frozenset()
    """``(store, id)`` pairs known to be this game (or a bundle holding it).
    Only ids seen in real store records belong here."""


CATALOGUE: dict[str, CatalogueEntry] = {
    "u6": CatalogueEntry((r"\bultima ?(vi|6)\b", r"false prophet")),
    "md": CatalogueEntry((r"martian dreams",)),
    "uw1": CatalogueEntry(
        (
            r"stygian abyss",
            r"\bunderworld ?(1|i)\b",
            r"\bunderworld ?1 ?\+ ?2\b",
            r"\bultima underworld$",
        )
    ),
    "uw2": CatalogueEntry(
        (r"labyrinth of worlds", r"\bunderworld ?(2|ii)\b", r"\bunderworld ?1 ?\+ ?2\b")
    ),
    # Ultima VII titles name Part Two (Serpent Isle) explicitly; the Complete
    # edition bundles both parts.
    "u7bg": CatalogueEntry(
        (
            r"black gate",
            r"\bultima ?(vii|7)\b(?!.*serpent)",
            r"\bultima ?(vii|7)\b.*complete",
        )
    ),
    "u7si": CatalogueEntry((r"serpent isle", r"\bultima ?(vii|7)\b.*complete")),
    "u8": CatalogueEntry((r"\bultima ?(viii|8)\b", r"\bultima\b.*\bpagan\b")),
    "u9": CatalogueEntry(
        (r"\bultima ?(ix|9)\b", r"\bultima\b.*\bascension\b"),
        frozenset({("steam", "3067560")}),
    ),
    "uo": CatalogueEntry((r"ultima online",)),
}
"""Game id -> how its store records are recognized. A match is a lead only."""


def normalize(text: str) -> str:
    """``"Ultima™ IX: Ascension"`` -> ``"ultima ix ascension"``."""
    text = re.sub(r"[™®©]", "", text.casefold())
    text = re.sub(r"[^\w+]+", " ", text)
    return " ".join(text.split())


def matches(game_id: str, record: InstallSource) -> bool:
    """Whether *record* may hold *game_id*: a ``[search] folders`` entry, a
    known store id, or a title or folder name that names the game."""
    entry = CATALOGUE.get(game_id)
    if entry is None:
        return False
    if record.store == "folder":  # the user's own folders: any game may be there
        return True
    if (record.store, record.store_id) in entry.store_ids:
        return True
    names = {normalize(record.title), normalize(record.path.name)}
    return any(
        re.search(pattern, name) for pattern in entry.titles for name in names if name
    )


# --- small helpers ----------------------------------------------------------


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_json(path: Path) -> Any:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _existing(paths: Iterable[Path]) -> list[Path]:
    """Each existing folder once (by its resolved location), in order."""
    seen: set[str] = set()
    found = []
    for path in paths:
        try:
            if not path.is_dir():
                continue
            key = os.path.normcase(str(path.resolve()))
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            found.append(path)
    return found


def drives() -> list[str]:
    """Letters of this PC's fixed drives (``["C", "D"]``); ``[]`` off Windows.

    Asks Windows rather than probing letters, so removable and network drives
    are never touched.
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        mask = kernel32.GetLogicalDrives()
        fixed = 3  # DRIVE_FIXED
        return [
            letter
            for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if mask >> index & 1 and kernel32.GetDriveTypeW(f"{letter}:\\") == fixed
        ]
    except (AttributeError, OSError):
        return list("CDEFG")


def guess_roots(
    *layouts: str, home: Iterable[str] = ("GOG Games", "Games/Heroic")
) -> list[Path]:
    """The usual folders games get installed under: each layout on every fixed
    drive (``""`` is the drive root), then the given folders in the home folder.

    The fallback when no store records a game; :func:`store_records` is better
    evidence."""
    roots = [Path(f"{drive}:/") / layout for layout in layouts for drive in drives()]
    return roots + [Path.home() / name for name in home]


# --- Valve KeyValues (VDF) --------------------------------------------------

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|([^\s{}"]+)')
_VDF_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


def parse_vdf(text: str) -> dict[str, Any]:
    """Parse Valve's text KeyValues format into nested dicts (keys as written).

    Enough for ``libraryfolders.vdf`` and ``appmanifest_*.acf``; conditionals
    (``[$WIN32]``) are kept as plain tokens and ignored.
    """
    tokens: list[Any] = []
    for quoted, brace, bare in (m.groups() for m in _VDF_TOKEN.finditer(text)):
        if quoted is not None:
            tokens.append(
                re.sub(r"\\(.)", lambda m: _VDF_ESCAPES.get(m[1], m[1]), quoted)
            )
        elif brace:
            tokens.append(brace)
        elif bare and not bare.startswith("["):
            tokens.append(bare)
    root: dict[str, Any] = {}
    stack = [root]
    key: Optional[str] = None
    for token in tokens:
        if token == "{":
            child: dict[str, Any] = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif token == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = token
        else:
            stack[-1][key] = token
            key = None
    return root


def _get(table: dict[str, Any], name: str) -> Any:
    """Case-insensitive key lookup (VDF keys vary: ``LibraryFolders``)."""
    lowered = name.casefold()
    return next((v for k, v in table.items() if k.casefold() == lowered), None)


# --- Windows registry -------------------------------------------------------


def _registry_values(path: str) -> list[dict[str, Any]]:
    """Values of *path* under HKCU and HKLM, both registry views; each key once."""
    if sys.platform != "win32":
        return []
    import winreg

    results = []
    seen = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                    values = {}
                    index = 0
                    while True:
                        try:
                            name, value, _kind = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        values[name] = value
                        index += 1
            except OSError:
                continue
            signature = tuple(sorted((k, str(v)) for k, v in values.items()))
            if values and signature not in seen:
                seen.add(signature)
                results.append(values)
    return results


def _registry_subkeys(path: str) -> list[str]:
    """Names of *path*'s subkeys under HKCU and HKLM, both registry views."""
    if sys.platform != "win32":
        return []
    import winreg

    names: dict[str, None] = {}
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                    index = 0
                    while True:
                        try:
                            names.setdefault(winreg.EnumKey(key, index))
                        except OSError:
                            break
                        index += 1
            except OSError:
                continue
    return list(names)


# --- Steam ------------------------------------------------------------------


def steam_roots() -> list[Path]:
    """Steam installs: the registry's on Windows, the usual native and Flatpak
    folders elsewhere."""
    candidates: list[Path] = []
    for values in _registry_values(r"Software\Valve\Steam"):
        for name in ("SteamPath", "InstallPath"):
            if isinstance(values.get(name), str):
                candidates.append(Path(values[name]))
    for values in _registry_values(r"SOFTWARE\Valve\Steam"):
        if isinstance(values.get("InstallPath"), str):
            candidates.append(Path(values["InstallPath"]))
    home = Path.home()
    candidates += [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/data/Steam",
        home / "Library/Application Support/Steam",
    ]
    return _existing(candidates)


def steam_libraries(root: Path) -> list[Path]:
    """The Steam root and every library ``libraryfolders.vdf`` lists."""
    libraries = [root]
    for vdf in (
        root / "steamapps/libraryfolders.vdf",
        root / "config/libraryfolders.vdf",
    ):
        text = _read_text(vdf)
        if text is None:
            continue
        table = _get(parse_vdf(text), "libraryfolders")
        if not isinstance(table, dict):
            continue
        for key, entry in table.items():
            if not key.isdigit():
                continue
            path = _get(entry, "path") if isinstance(entry, dict) else entry
            if isinstance(path, str) and path:
                libraries.append(Path(path))
    return _existing(libraries)


def steam_records(roots: Optional[Iterable[Path]] = None) -> list[InstallSource]:
    """One record per installed Steam app, from each library's app manifests."""
    records = []
    for root in steam_roots() if roots is None else roots:
        for library in steam_libraries(Path(root)):
            try:
                manifests = sorted((library / "steamapps").glob("appmanifest_*.acf"))
            except OSError:
                continue
            for manifest in manifests:
                text = _read_text(manifest)
                state = _get(parse_vdf(text), "AppState") if text else None
                if not isinstance(state, dict):
                    continue
                installdir = _get(state, "installdir")
                if not isinstance(installdir, str) or not installdir:
                    continue
                records.append(
                    InstallSource(
                        "steam",
                        str(_get(state, "appid") or ""),
                        str(_get(state, "name") or installdir),
                        library / "steamapps" / "common" / installdir,
                        "steam-manifest",
                    )
                )
    return records


# --- GOG --------------------------------------------------------------------


def gog_info(folder: Path) -> list[dict[str, Any]]:
    """The ``goggame-<id>.info`` documents in *folder* (GOG's own identity files)."""
    try:
        files = sorted(folder.glob("goggame-*.info"))
    except OSError:
        return []
    return [
        doc for doc in (_read_json(path) for path in files) if isinstance(doc, dict)
    ]


def _gog_title(folder: Path, fallback: str) -> str:
    for doc in gog_info(folder):
        if doc.get("name") and (doc.get("rootGameId") in (None, doc.get("gameId"))):
            return str(doc["name"])
    return fallback


def gog_registry_records() -> list[InstallSource]:
    """GOG games registered under ``GOG.com\\Games`` (Galaxy and offline installers)."""
    records = []
    base = r"SOFTWARE\GOG.com\Games"
    for product in _registry_subkeys(base):
        for values in _registry_values(f"{base}\\{product}"):
            path = values.get("path") or values.get("PATH")
            if not isinstance(path, str) or not path:
                continue
            folder = Path(path)
            title = str(values.get("gameName") or values.get("GAMENAME") or folder.name)
            records.append(
                InstallSource(
                    "gog",
                    str(values.get("gameID") or values.get("productID") or product),
                    _gog_title(folder, title),
                    folder,
                    "gog-registry",
                )
            )
    return records


# --- EA, the classic UO client, Windows installers ----------------------------


def ea_records() -> list[InstallSource]:
    """Games EA's installer registered (``Electronic Arts\\EA Games\\<product>``)."""
    records = []
    base = r"SOFTWARE\Electronic Arts\EA Games"
    for product in _registry_subkeys(base):
        for values in _registry_values(f"{base}\\{product}"):
            path = values.get("InstallDir") or values.get("Install Dir")
            if isinstance(path, str) and path:
                records.append(
                    InstallSource("ea", "", product, Path(path), "ea-registry")
                )
    return records


def uo_registry_records() -> list[InstallSource]:
    """UO clients registered the classic way (``Origin Worlds Online\\<product>\\<version>``),
    as Origin's installer did and freeshard installers (UO Forever, ...) still do."""
    records = []
    base = r"SOFTWARE\Origin Worlds Online"
    for product in _registry_subkeys(base):
        for version in _registry_subkeys(f"{base}\\{product}"):
            for values in _registry_values(f"{base}\\{product}\\{version}"):
                path = values.get("InstCDPath")
                exe = values.get("ExePath") or values.get("StartExePath")
                if isinstance(path, str) and path:
                    folder: Optional[Path] = Path(path)
                elif isinstance(exe, str) and exe:
                    folder = Path(exe).parent
                else:
                    folder = None
                if folder is not None:
                    records.append(
                        InstallSource("origin", "", product, folder, "uo-registry")
                    )
    return records


def _exe_folder(value: object) -> Optional[Path]:
    """The folder of a registry command or icon value (``"C:\\x\\a.exe",0``)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith('"'):
        text = text[1:].split('"', 1)[0]
    else:
        match = re.match(
            r"(.+?\.(?:exe|ico|bat|com))\b", text.split(",", 1)[0], re.IGNORECASE
        )
        text = match[1] if match else text.split(",", 1)[0]
    return Path(text).parent if text else None


def uninstall_records() -> list[InstallSource]:
    """Programs in Windows' installed-programs list (any installer: GOG offline,
    EA, a freeshard's), by ``InstallLocation`` or the folder of their icon or
    uninstaller."""
    records = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for key in _registry_subkeys(base):
        for values in _registry_values(f"{base}\\{key}"):
            name = values.get("DisplayName")
            if not isinstance(name, str) or not name:
                continue
            location = values.get("InstallLocation")
            if isinstance(location, str) and location.strip():
                folder: Optional[Path] = Path(location.strip().strip('"'))
            else:
                folder = _exe_folder(values.get("DisplayIcon")) or _exe_folder(
                    values.get("UninstallString")
                )
            if folder is not None and folder.parts:
                records.append(
                    InstallSource("windows", key, name, folder, "uninstall-registry")
                )
    return records


# --- Heroic -----------------------------------------------------------------


def heroic_config_dirs() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".config/heroic",
        home / ".var/app/com.heroicgameslauncher.hgl/config/heroic",
        home / "Library/Application Support/heroic",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.insert(0, Path(appdata) / "heroic")
    return _existing(candidates)


def heroic_records(config_dirs: Optional[Iterable[Path]] = None) -> list[InstallSource]:
    """GOG games Heroic installed (``gog_store/installed.json``)."""
    records = []
    for config_dir in heroic_config_dirs() if config_dirs is None else config_dirs:
        store = Path(config_dir) / "gog_store"
        installed = _read_json(store / "installed.json")
        entries = (
            installed.get("installed") if isinstance(installed, dict) else installed
        )
        if not isinstance(entries, list):
            continue
        library = _read_json(store / "library.json")
        games = library.get("games") if isinstance(library, dict) else None
        titles = {
            str(game.get("app_name")): str(game.get("title"))
            for game in games or ()
            if isinstance(game, dict) and game.get("app_name") and game.get("title")
        }
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("install_path") or entry.get("installPath")
            if not isinstance(path, str) or not path:
                continue
            app = str(entry.get("appName") or entry.get("app_name") or "")
            folder = Path(path)
            title = str(entry.get("title") or titles.get(app) or folder.name)
            records.append(
                InstallSource(
                    "gog", app, _gog_title(folder, title), folder, "heroic-manifest"
                )
            )
    return records


# --- Lutris -----------------------------------------------------------------


def lutris_databases() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local/share/lutris/pga.db",
        home / ".var/app/net.lutris.Lutris/data/lutris/pga.db",
    ]
    return [path for path in candidates if path.is_file()]


def lutris_records(databases: Optional[Iterable[Path]] = None) -> list[InstallSource]:
    """Installed games in Lutris's database, opened read-only."""
    records = []
    for database in lutris_databases() if databases is None else databases:
        try:
            uri = Path(database).absolute().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute("SELECT * FROM games").fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            fields = dict(row)
            if fields.get("installed") in (0, "0", False) or not fields.get(
                "directory"
            ):
                continue
            service = str(fields.get("service") or "")
            records.append(
                InstallSource(
                    "gog" if service == "gog" else "lutris",
                    str(fields.get("service_id") or fields.get("slug") or ""),
                    str(fields.get("name") or fields.get("slug") or ""),
                    Path(str(fields["directory"])),
                    "lutris-db",
                )
            )
    return records


# --- the user's own folders --------------------------------------------------


def search_folder_records(config: dict) -> list[InstallSource]:
    """``[search] folders``: each listed folder and the folders directly in it."""
    folders = config.get("search", {}).get("folders", [])
    if isinstance(folders, str):
        folders = [folders]
    records = []
    for value in folders:
        root = Path(str(value)).expanduser()
        try:
            children = sorted(child for child in root.iterdir() if child.is_dir())
        except OSError:
            continue
        for folder in (root, *children):
            records.append(
                InstallSource("folder", "", folder.name, folder, "search-folder")
            )
    return records


# --- all records --------------------------------------------------------------

_CACHE_SECONDS = 30.0
_cache: dict[tuple[str, ...], tuple[float, list[InstallSource]]] = {}


def refresh() -> None:
    """Forget cached store records (they're kept for :data:`_CACHE_SECONDS`)."""
    _cache.clear()


def store_records(config: Optional[dict] = None) -> list[InstallSource]:
    """Every installed game the launchers record, plus ``[search] folders``.

    Not only Ultima games: :func:`matching` picks a game's. Cached briefly, since
    each game's install search asks again.
    """
    config = config or {}
    folders = config.get("search", {}).get("folders", [])
    key = tuple(map(str, folders if isinstance(folders, list) else [folders]))
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    records = [
        *steam_records(),
        *gog_registry_records(),
        *ea_records(),
        *uo_registry_records(),
        *heroic_records(),
        *lutris_records(),
        *uninstall_records(),
        *search_folder_records(config),
    ]
    _cache[key] = (time.monotonic(), records)
    return records


def matching(game_id: str, config: Optional[dict] = None) -> list[InstallSource]:
    """The store records that may hold *game_id*, each folder once."""
    seen: set[str] = set()
    found = []
    for record in store_records(config):
        if not matches(game_id, record):
            continue
        key = os.path.normcase(str(record.path))
        if key not in seen:
            seen.add(key)
            found.append(record)
    return found
