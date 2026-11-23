"""
Shared configuration loader for titan.toml.

Loads game paths from the TOML config file and makes them available
to all CLI sub-apps (U7, U8, etc.) without circular imports.

Search order for the config file:
  1. ``./titan.toml`` (current working directory)
  2. ``~/.config/titan/config.toml`` (XDG / Linux / macOS)
  3. ``%APPDATA%\\titan\\config.toml`` (Windows)

The loaded dict is stored in :data:`_config` (module-level) and
populated by the root CLI callback via :func:`load_config`.
"""

from __future__ import annotations

__all__ = [
    "cache_dir",
    "config_search_paths",
    "data_dir",
    "export_dir",
    "find_config",
    "load_config",
    "cfg",
    "user_config_path",
]

import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import tomllib  # Python 3.11+

    _tomllib = tomllib
except ImportError:
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ImportError:
        _tomllib = None  # type: ignore[assignment]


# --- module-level state (set by root CLI callback) -----------------------

_config: dict = {}
"""Populated by :func:`load_config` during CLI startup."""

explicit_config_path: Optional[str] = None
"""Set by the root CLI ``--config`` flag, if provided."""


# --- public helpers ------------------------------------------------------


def user_config_path() -> Path:
    """Return this platform's per-user config file location.

    ``%APPDATA%\\titan\\config.toml`` on Windows, otherwise
    ``~/.config/titan/config.toml``. The file may not exist yet; callers
    that create a user-level config (e.g. a desktop front end) should
    write it here so :func:`find_config` picks it up.
    """
    appdata = os.getenv("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / "titan" / "config.toml"
    return Path.home() / ".config" / "titan" / "config.toml"


DATA_ENV = "TITAN_DATA"
"""Environment variable that moves :func:`data_dir`."""


def data_dir(game: Optional[str] = None) -> Path:
    """Return titan's working-data folder, shared by the CLI and front ends.

    ``%LOCALAPPDATA%\\Titan`` on Windows, otherwise ``$XDG_DATA_HOME/titan``
    (``~/.local/share/titan``); ``TITAN_DATA`` overrides both. With *game*
    (a config section such as ``"u8"``), the game's subfolder. Working
    folders such as U8 ``shapes/`` resolve here; the folder may not exist yet.
    """
    override = os.getenv(DATA_ENV)
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "win32" and os.getenv("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "Titan"
    else:
        xdg = os.getenv("XDG_DATA_HOME")
        root = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "titan"
    return root / game if game else root


def export_dir(game: str, name: str = "") -> Path:
    """Where a command writes when no output folder is given.

    ``<data_dir(game)>/exports/<name>`` (*name* is usually the command, e.g.
    ``"map-browse"``). Resolved when the command runs, so ``TITAN_DATA`` and the
    platform folders apply; the folder may not exist yet. Commands print the
    folder they used.
    """
    root = data_dir(game) / "exports"
    return root / name if name else root


DEFAULT_OUTPUT = " (default: a folder for this command under titan's exports)"
"""Help-text suffix for output options that default to :func:`export_output`."""


def export_output(
    value: Optional[str], game: str, name: str, filename: str = ""
) -> str:
    """An output path: *value* when given, else :func:`export_dir` ``(game,
    name)`` (with *filename* appended, for a single output file). A default
    is reported to ``TITAN_RESULTS_FILE`` (:mod:`titan._results`)."""
    if value:
        return value
    from titan import _results

    folder = export_dir(game, name)
    reporting = bool(os.getenv(_results.RESULTS_ENV))
    if filename:
        if reporting:
            _results.record_output(folder / filename)
        return str(folder / filename)
    if reporting:
        _results.record_output_folder(folder, time.time() - 2)
    return str(folder)


def cache_dir() -> Path:
    """Return titan's cache folder: files titan can always recreate.

    ``%LOCALAPPDATA%\\Titan\\cache`` on Windows, otherwise
    ``$XDG_CACHE_HOME/titan`` (``~/.cache/titan``). The folder may not exist yet.
    """
    if sys.platform == "win32" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Titan" / "cache"
    xdg = os.getenv("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "titan"


def config_search_paths() -> list[Path]:
    """Return every location :func:`find_config` checks, in search order.

    Always includes :func:`user_config_path`.
    """
    candidates = [
        Path.cwd() / "titan.toml",
        Path.home() / ".config" / "titan" / "config.toml",
        Path(os.getenv("APPDATA", "~")).expanduser() / "titan" / "config.toml",
        user_config_path(),
    ]
    return list(dict.fromkeys(candidates))


def find_config() -> Optional[Path]:
    """Return the first titan.toml found in the standard search order."""
    return next((p for p in config_search_paths() if p.exists()), None)


def load_config(config_path: Optional[str] = None) -> dict:
    """Load *titan.toml* and auto-expand relative paths.

    Each game has its own section (``[u8.game]`` / ``[u8.paths]``, ...).
    titan's original U8-only layout, top-level ``[game]`` / ``[paths]``, is
    read as ``[u8]`` (:func:`migrate_legacy_u8`); the loaded config has no
    top-level ``game``/``paths``.
    """
    global _config

    if _tomllib is None:
        _config = {}
        return _config

    path: Optional[Path]
    if config_path:
        path = Path(config_path).expanduser()
    else:
        path = find_config()

    if not path or not path.exists():
        _config = {}
        return _config

    _config = read_config(path)
    return _config


def read_config(path: Path) -> dict:
    """Parse the titan.toml at *path* as :func:`load_config` does (legacy layout
    migrated, U8 paths expanded) without making it titan's loaded config."""
    if _tomllib is None:
        return {}
    try:
        with open(path, "rb") as f:
            data = _tomllib.load(f)
    except _tomllib.TOMLDecodeError as error:
        from titan.errors import ConfigFileError

        raise ConfigFileError(f"{path} is not valid TOML: {error}") from error

    # titan's original U8-only layout ([game]/[paths]) is read as [u8].
    migrate_legacy_u8(data)
    if "u8" in data:
        # Only U8 settings need U8's path rules; other games' configs load
        # without importing the U8 package.
        from titan.u8.install import expand_u8_paths

        expand_u8_paths(data["u8"])
    return data


LEGACY_U8_TABLES = ("game", "paths")
"""Top-level tables of titan's original U8-only ``titan.toml``; now ``[u8.*]``."""


def has_legacy_u8_tables(data: dict) -> bool:
    """Whether raw TOML *data* still has top-level ``[game]``/``[paths]``."""
    return any(isinstance(data.get(table), dict) for table in LEGACY_U8_TABLES)


def migrate_legacy_u8(data: dict) -> bool:
    """Move top-level ``[game]``/``[paths]`` under ``[u8]`` in raw TOML *data*.

    A value ``[u8]`` already sets wins. Returns ``True`` when anything moved.
    :func:`load_config` does this in memory; ``titan setup`` writes it back.
    """
    moved = False
    for table in LEGACY_U8_TABLES:
        legacy = data.pop(table, None)
        if isinstance(legacy, dict):
            u8 = data.setdefault("u8", {})
            u8[table] = {**legacy, **u8.get(table, {})}
            moved = True
    return moved


def cfg(key: str, section: str = "paths") -> Optional[str]:
    """A ``[u8.<section>]`` value from the loaded config (``cfg("fixed")``).

    Older readers used this for top-level ``[paths]``, which is now ``[u8.paths]``.
    """
    return _config.get("u8", {}).get(section, {}).get(key)


def exult_cfg(key: str) -> Optional[str]:
    """Get a value from the ``[exult.paths]`` config section.

    Parameters
    ----------
    key : str
        The key to look up, e.g. ``"bg_flx"`` or ``"si_flx"``.
    """
    return _config.get("exult", {}).get("paths", {}).get(key)


def get_config() -> dict:
    """Return the full loaded config dict (read-only reference)."""
    return _config


def resolve_config_path(value: object, base: object = None) -> Optional[Path]:
    """Resolve a configured path against its game base, preserving absolute paths."""
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if base and not path.is_absolute():
        path = Path(str(base)).expanduser() / path
    return path


def game_config_path(game: str, key: str) -> Optional[Path]:
    """Resolve a U7 setting using the same rules as the config inspector."""
    section = get_config().get("u7bg" if game.upper() == "BG" else "u7si", {})
    return resolve_config_path(
        section.get("paths", {}).get(key), section.get("game", {}).get("base")
    )
