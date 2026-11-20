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
    "find_config",
    "load_config",
    "cfg",
    "user_config_path",
]

import os
import sys
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

    Supports both the legacy flat format (``[game]`` / ``[paths]``) and
    the new multi-game format (``[u8.game]`` / ``[u8.paths]``, etc.).

    If a legacy ``[game]`` section exists it is treated as ``[u8]``.
    """
    global _config

    # Imported here: the U8 package itself reads this module at import time.
    from titan.u8.install import expand_u8_paths

    if _tomllib is None:
        _config = {"paths": {}}
        return _config

    path: Optional[Path]
    if config_path:
        path = Path(config_path).expanduser()
    else:
        path = find_config()

    if not path or not path.exists():
        _config = {"paths": {}}
        return _config

    with open(path, "rb") as f:
        data = _tomllib.load(f)

    # ── Legacy format: [game] + [paths] → treat as U8 ─────────────
    if "game" in data and "u8" not in data:
        expand_u8_paths(data)
        _config = data
        return _config

    # ── New multi-game format ──────────────────────────────────────
    # [u8] → expand paths using U8 rules
    if "u8" in data:
        u8_section = data["u8"]
        # Merge legacy fallback values before expanding the effective U8 paths.
        for section in ("game", "paths"):
            if section in data or section in u8_section:
                u8_section[section] = {
                    **data.get(section, {}),
                    **u8_section.get(section, {}),
                }
        expand_u8_paths(u8_section)
        # Promote u8.game/u8.paths to top-level game/paths for compat
        if "game" in u8_section:
            data["game"] = u8_section["game"]
        if "paths" in u8_section:
            data["paths"] = u8_section["paths"]

    _config = data
    return _config


def cfg(key: str, section: str = "paths") -> Optional[str]:
    """Get a path value from the loaded config.

    Parameters
    ----------
    key : str
        The key to look up (e.g. ``"fixed"``, ``"palette"``).
    section : str
        Top-level section (default ``"paths"``).
    """
    return _config.get(section, {}).get(key)


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
