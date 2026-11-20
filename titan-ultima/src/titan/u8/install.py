"""Discover Ultima 8 installs and apply the game's ``titan.toml`` path rules."""

from __future__ import annotations

__all__ = [
    "U8_GAME_SAVE_DIR",
    "U8_STATIC_FILES",
    "discover_u8_installs",
    "expand_u8_paths",
    "find_u8_engine_save",
    "is_u8_folder_name",
    "prune_stale_u8_save_default",
    "resolve_u8_save",
    "u8_detected_paths",
    "u8_install_candidates",
    "u8_save_dir",
    "u8_setup_lines",
]

import os
from pathlib import Path
from typing import Optional

U8_STATIC_FILES = {
    "fixed": "FIXED.DAT",
    "palette": "U8PAL.PAL",
    "typeflag": "TYPEFLAG.DAT",
    "gumpage": "GUMPAGE.DAT",
    "xformpal": "XFORMPAL.DAT",
    "ecredits": "ECREDITS.DAT",
    "quotes": "QUOTES.DAT",
    "u8shapes": "U8SHAPES.FLX",
    "u8fonts": "U8FONTS.FLX",
    "u8gumps": "U8GUMPS.FLX",
}
"""``[u8.paths]`` keys that name files in the game's STATIC folder."""


U8_GAME_SAVE_DIR = "cloud_saves/SAVEGAME"
"""Save folder, relative to the base, for GOG installs with a language folder."""

U8_LEGACY_SAVE_DEFAULT = "U8SAVE.000"
"""``nonfixed`` value older ``titan setup`` releases wrote without checking it."""


def _str_value(paths: dict, key: str) -> str:
    value = paths.get(key)
    return value if isinstance(value, str) else ""


def _default_u8_save_dir(base_p: Path, lang: str) -> Path:
    return (base_p / U8_GAME_SAVE_DIR) if lang else base_p


def _save_in_folder(value: str, save_dir: Path) -> Path:
    """Resolve a slot number or relative name inside *save_dir*."""
    if value.isdigit():
        return save_dir / f"U8SAVE.{int(value):03d}"
    return save_dir / value


def expand_u8_paths(data: dict) -> dict:
    """Auto-expand relative STATIC / SAVEGAME paths for a U8 game section.

    ``savegame`` is the save folder, relative to the base. ``nonfixed`` is an
    optional default save: a slot number (``3``), a file name or a path,
    resolved inside the save folder.
    """
    game = data.get("game", {})
    base = game.get("base")
    lang = game.get("language", "ENGLISH")

    if base:
        base_p = Path(base).expanduser()
        static_p = (base_p / lang / "STATIC") if lang else base_p

        paths = data.setdefault("paths", {})

        for k in U8_STATIC_FILES:
            if (
                k in paths
                and isinstance(paths[k], str)
                and not Path(paths[k]).is_absolute()
            ):
                paths[k] = str(static_p / paths[k])

        _expand_u8_save_paths(paths, base_p, lang)

    return data


def _expand_u8_save_paths(paths: dict, base_p: Path, lang: str) -> None:
    savegame = _str_value(paths, "savegame")
    if savegame and not Path(savegame).expanduser().is_absolute():
        paths["savegame"] = str(base_p / savegame)
    save_p = (
        Path(paths["savegame"]).expanduser()
        if savegame
        else _default_u8_save_dir(base_p, lang)
    )
    nonfixed = _str_value(paths, "nonfixed")
    if nonfixed and not Path(nonfixed).expanduser().is_absolute():
        paths["nonfixed"] = str(_save_in_folder(nonfixed, save_p))


def u8_save_dir(config: dict) -> Optional[Path]:
    """Return the U8 save folder from a loaded config, or ``None``.

    Uses ``[u8.paths] savegame``, then the folder of a configured ``nonfixed``,
    then ``<base>/cloud_saves/SAVEGAME`` (the base itself for flat installs).
    *config* is the loaded config or a U8 section with ``game``/``paths``.
    """
    paths = config.get("paths", {})
    savegame = _str_value(paths, "savegame")
    if savegame:
        return Path(savegame).expanduser()
    nonfixed = _str_value(paths, "nonfixed")
    if nonfixed and Path(nonfixed).expanduser().is_absolute():
        return Path(nonfixed).expanduser().parent
    game = config.get("game", {})
    base = game.get("base")
    if not base:
        return None
    return _default_u8_save_dir(
        Path(base).expanduser(), game.get("language", "ENGLISH")
    )


def resolve_u8_save(value: Optional[str], config: dict) -> Optional[Path]:
    """Resolve the save a U8 command should read, or ``None`` for the base world.

    *value* comes from the command line: a slot number (``3``), a file name
    (``U8SAVE.003``) or a path. A relative path that exists from the current
    folder is used as given; a bare name or slot is looked up in the save
    folder. With no *value*, ``[u8.paths] nonfixed`` is the default save.

    Raises ``ValueError`` for a slot number when no save folder is known.
    """
    if value:
        path = Path(value).expanduser()
        if not value.isdigit() and (path.is_absolute() or path.exists()):
            return path
    else:
        value = _str_value(config.get("paths", {}), "nonfixed")
        if not value:
            return None
    save_dir = u8_save_dir(config)
    if save_dir is not None and (value.isdigit() or len(Path(value).parts) == 1):
        return _save_in_folder(value, save_dir)
    if value.isdigit():
        raise ValueError(
            f"Save slot {value!r} needs a save folder: set [u8.paths] savegame "
            "(or run `titan setup`), or pass a path to the save file."
        )
    return Path(value).expanduser()


def prune_stale_u8_save_default(data: dict) -> bool:
    """Drop a ``nonfixed`` default that only an old ``titan setup`` wrote.

    Removes ``[u8.paths] nonfixed`` only when it is exactly ``U8SAVE.000``
    and that file does not exist in the save folder. *data* is raw TOML
    (unexpanded); returns ``True`` when the key was removed.
    """
    paths = data.get("u8", {}).get("paths")
    if not isinstance(paths, dict) or paths.get("nonfixed") != U8_LEGACY_SAVE_DEFAULT:
        return False
    section = expand_u8_paths(
        {
            "game": dict(data["u8"].get("game", {})),
            "paths": dict(paths),
        }
    )
    if not section["game"].get("base"):
        return False
    if Path(section["paths"]["nonfixed"]).is_file():
        return False
    del paths["nonfixed"]
    return True


def is_u8_folder_name(name: str) -> bool:
    """Recognize a launcher folder that holds Ultima 8 rather than Ultima 7."""
    lowered = name.lower()
    if "ultima" not in lowered:
        return False
    # Avoid nearby U7/SI installs when dynamically scanning launcher roots.
    if "serpent" in lowered:
        return False
    if "ultima 7" in lowered or "ultima7" in lowered:
        return False
    return any(token in lowered for token in ("ultima 8", "ultima8", "viii", "pagan"))


def u8_install_candidates() -> list[Path]:
    """List GOG Galaxy, GOG offline, legacy disc, Heroic and manual U8 folders."""
    candidates: list[Path] = []

    def _add_candidate(path: Path) -> None:
        if path not in candidates:
            candidates.append(path)

    # Windows: GOG Galaxy client (most common current install)
    for drive in "CDEFG":
        _add_candidate(
            Path(f"{drive}:\\Program Files (x86)\\GOG Galaxy\\Games\\Ultima 8")
        )
    # Windows: GOG Offline Installer + common manual redirects
    for drive in "CDEFG":
        for path in [
            Path(f"{drive}:\\GOG Games\\Ultima 8"),
            Path(f"{drive}:\\ULTIMA8"),
            Path(f"{drive}:\\ultima8"),
        ]:
            _add_candidate(path)
    # Windows: Legacy EA/Origin disc installs
    for path in [
        Path(r"C:\Program Files\EA Games\Ultima 8 Gold Edition"),
        Path(r"C:\Program Files (x86)\Origin Games\Ultima 8 Gold Edition"),
    ]:
        _add_candidate(path)

    # Linux: direct known paths
    _add_candidate(Path.home() / "GOG Games" / "Ultima 8")
    _add_candidate(Path.home() / "Games" / "Heroic" / "Ultima 8")

    # Linux: dynamic launcher roots (discover all Ultima-* folders)
    for root in (Path.home() / "GOG Games", Path.home() / "Games" / "Heroic"):
        if not root.is_dir():
            continue
        try:
            for folder in root.iterdir():
                if folder.is_dir() and is_u8_folder_name(folder.name):
                    _add_candidate(folder)
        except PermissionError:
            continue
    return candidates


def discover_u8_installs(candidates: list[Path]) -> list[tuple[Path, str]]:
    """Return ``(base, language folder)`` per install; flat installs use ``""``."""
    detected: list[tuple[Path, str]] = []
    for candidate_base in candidates:
        if not candidate_base.is_dir():
            continue
        if (candidate_base / "FIXED.DAT").is_file():
            detected.append((candidate_base, ""))
            continue
        try:
            for folder in candidate_base.iterdir():
                if not folder.is_dir():
                    continue
                static = folder / "STATIC"
                if static.exists() and (static / "FIXED.DAT").exists():
                    detected.append((candidate_base, folder.name))
                    break
        except PermissionError:
            continue
    return detected


def find_u8_engine_save() -> Optional[Path]:
    """Find a Pentagram ``U8SAVE.000`` in its Windows or macOS profile folder."""
    appdata = os.getenv("APPDATA")
    # Windows: %APPDATA%\Pentagram\u8-save
    if appdata:
        pent_save = Path(appdata) / "Pentagram" / "u8-save"
        if (pent_save / "U8SAVE.000").exists():
            return pent_save / "U8SAVE.000"
    # macOS: ~/Library/Application Support/Pentagram/u8-save
    mac_save = Path.home() / "Library" / "Application Support" / "Pentagram" / "u8-save"
    if (mac_save / "U8SAVE.000").exists():
        return mac_save / "U8SAVE.000"
    return None


def u8_detected_paths(base: str, lang: str) -> tuple[Path, Path]:
    """Return the STATIC folder and EUSECODE.FLX for a base and language folder."""
    root = Path(base) / lang if lang else Path(base)
    static = (root / "STATIC") if lang else root
    return static, root / "USECODE" / "EUSECODE.FLX"


def u8_setup_lines(
    base: str,
    lang: str,
    savegame_value: str,
    usecode_detected: Path,
    *,
    manual_static: str = "",
    manual_usecode: str = "",
) -> list[str]:
    """Render ``[u8.game]`` and ``[u8.paths]`` for a new ``titan.toml``.

    A manually entered STATIC folder writes absolute file paths; otherwise
    the bare filenames are written and expanded against base and language
    when the config is loaded.

    *savegame_value* is the save folder (relative to base, or absolute for a
    third-party engine); empty means the base folder. Setup never picks a
    save: ``nonfixed`` is left for the user to set.
    """
    static_manual = Path(manual_static) if manual_static else None
    if manual_usecode:
        usecode = manual_usecode
    elif static_manual is not None:
        usecode = str(static_manual.parent / "USECODE" / "EUSECODE.FLX").replace(
            "\\", "/"
        )
    else:
        usecode = str(usecode_detected).replace("\\", "/")

    if static_manual is not None:
        paths = {
            key: str(static_manual / filename).replace("\\", "/")
            for key, filename in U8_STATIC_FILES.items()
        }
    else:
        paths = dict(U8_STATIC_FILES)

    def _entry(key: str, value: str) -> str:
        return f'{key:<10}= "{value}"'

    base_toml = base.replace("\\", "/")
    lines = [
        "[u8.game]",
        f'base     = "{base_toml}"',
        f'language = "{lang}"',
        "",
        "[u8.paths]",
        *(
            _entry(key, paths[key])
            for key in (
                "fixed",
                "palette",
                "typeflag",
                "gumpage",
                "xformpal",
                "ecredits",
                "quotes",
            )
        ),
        "",
        *(_entry(key, paths[key]) for key in ("u8shapes", "u8fonts", "u8gumps")),
        _entry("usecode", usecode),
        "",
        "# Pre-extracted directories (relative to where you run titan)",
        'shapes    = "shapes/"',
        'globs     = "globs/"',
        "",
        "# Save folder; map commands take --nonfixed as a slot (3), file name or path",
    ]
    if not savegame_value:
        lines.append("# (flat install: saves are read from the base folder)")
    elif Path(savegame_value).is_absolute():
        lines.append(f'savegame  = "{savegame_value}"  # absolute (third-party engine)')
    else:
        lines.append(f'savegame  = "{savegame_value}"')
    lines.append('# Optional default save for map commands, e.g. nonfixed = "3"')
    return lines
