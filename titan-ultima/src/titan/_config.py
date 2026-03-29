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

__all__ = ["find_config", "load_config", "cfg"]

import os
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

def find_config() -> Optional[Path]:
    """Return the first titan.toml found in the standard search order."""
    candidates: list[Path] = [
        Path.cwd() / "titan.toml",
        Path.home() / ".config" / "titan" / "config.toml",
        Path(os.getenv("APPDATA", "~")).expanduser() / "titan" / "config.toml",
    ]
    return next((p for p in candidates if p.exists()), None)


def _expand_u8_paths(data: dict) -> dict:
    """Auto-expand relative STATIC / SAVEGAME paths for a U8 game section."""
    game = data.get("game", {})
    base = game.get("base")
    lang = game.get("language", "ENGLISH")

    if base:
        base_p = Path(base).expanduser()
        static_p = (base_p / lang / "STATIC") if lang else base_p
        save_p = (base_p / "cloud_saves" / "SAVEGAME") if lang else base_p

        paths = data.setdefault("paths", {})

        for k in ("fixed", "palette", "typeflag", "gumpage", "xformpal",
                  "ecredits", "quotes", "u8shapes", "u8fonts", "u8gumps"):
            if (k in paths and isinstance(paths[k], str)
                    and not Path(paths[k]).is_absolute()):
                paths[k] = str(static_p / paths[k])

        if ("nonfixed" in paths and isinstance(paths["nonfixed"], str)
                and not Path(paths["nonfixed"]).is_absolute()):
            paths["nonfixed"] = str(save_p / paths["nonfixed"])

    return data


def load_config(config_path: Optional[str] = None) -> dict:
    """Load *titan.toml* and auto-expand relative paths.

    Supports both the legacy flat format (``[game]`` / ``[paths]``) and
    the new multi-game format (``[u8.game]`` / ``[u8.paths]``, etc.).

    If a legacy ``[game]`` section exists it is treated as ``[u8]``.
    """
    global _config

    if _tomllib is None:
        _config = {"paths": {}}
        return _config

    if config_path:
        path = Path(config_path)
    else:
        path = find_config()

    if not path or not path.exists():
        _config = {"paths": {}}
        return _config

    with open(path, "rb") as f:
        data = _tomllib.load(f)

    # ── Legacy format: [game] + [paths] → treat as U8 ─────────────
    if "game" in data and "u8" not in data:
        _expand_u8_paths(data)
        _config = data
        return _config

    # ── New multi-game format ──────────────────────────────────────
    # [u8] → expand paths using U8 rules
    if "u8" in data:
        u8_section = data["u8"]
        # Promote u8.game/u8.paths to top-level game/paths for compat
        if "game" in u8_section:
            data.setdefault("game", u8_section["game"])
        if "paths" in u8_section:
            data.setdefault("paths", u8_section["paths"])
        _expand_u8_paths(data)

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


def get_config() -> dict:
    """Return the full loaded config dict (read-only reference)."""
    return _config
