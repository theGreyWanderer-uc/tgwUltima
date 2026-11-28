"""Discover Ultima 8 installs and apply the game's ``titan.toml`` path rules."""

from __future__ import annotations

__all__ = [
    "U8_GAME_SAVE_DIR",
    "U8_PATH_KINDS",
    "U8_STATIC_FILES",
    "U8_WORKING_DIRS",
    "U8_WORKING_DIR_ARCHIVES",
    "U8_WORKING_DIR_EXTS",
    "discover_installs",
    "discover_u8_installs",
    "expand_u8_paths",
    "find_u8_engine_save",
    "install_candidates",
    "install_config",
    "has_working_files",
    "is_u8_folder_name",
    "prepare_working_dirs",
    "prune_stale_u8_save_default",
    "resolve_u8_save",
    "resolve_u8_working_dir",
    "u8_detected_paths",
    "u8_install_candidates",
    "u8_cfg",
    "u8_config_section",
    "u8_save_dir",
    "u8_section",
    "u8_setup_lines",
    "u8_working_archive",
    "u8_working_dir_for_archive",
]

import os
from pathlib import Path
from typing import Optional

from titan._meta import Installation
from titan import _stores

U8_STATIC_FILES = {
    "fixed": "FIXED.DAT",
    "palette": "U8PAL.PAL",
    "typeflag": "TYPEFLAG.DAT",
    "gumpage": "GUMPAGE.DAT",
    "xformpal": "XFORMPAL.DAT",
    "ecredits": "ECREDITS.DAT",
    "quotes": "QUOTES.DAT",
    "u8shapes": "U8SHAPES.FLX",
    "glob": "GLOB.FLX",
    "u8fonts": "U8FONTS.FLX",
    "u8gumps": "U8GUMPS.FLX",
}
"""``[u8.paths]`` keys that name files in the game's STATIC folder."""

U8_WORKING_DIRS = ("shapes", "globs")
"""``[u8.paths]`` keys for folders extracted from the game (``flex-extract``)."""

U8_PATH_KINDS = {
    **{key: "install-file" for key in U8_STATIC_FILES},
    "usecode": "install-file",
    "savegame": "save-dir",
    "nonfixed": "save",
    **{key: "working-dir" for key in U8_WORKING_DIRS},
}
"""``[u8.paths]`` key -> kind (see :func:`titan._meta.path_kind`)."""


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

    if base or any(k in data.get("paths", {}) for k in U8_WORKING_DIRS):
        _expand_u8_working_dirs(data, default=bool(base))

    return data


def resolve_u8_working_dir(value: str, *, data: Optional[Path] = None) -> Path:
    """Resolve a ``shapes``/``globs`` value.

    A relative value lives in titan's data folder (:func:`titan._config.data_dir`,
    or *data*); absolute values are used unchanged.
    """
    from titan._config import data_dir

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (data or data_dir("u8")) / path


U8_WORKING_DIR_ARCHIVES = {
    "shapes": ("u8shapes", "U8SHAPES.FLX"),
    "globs": ("glob", "GLOB.FLX"),
}
"""Working folder -> (``[u8.paths]`` key, file name) of the archive it comes from."""


def u8_section(config: Optional[dict] = None) -> dict:
    """The ``[u8]`` section of a loaded config, as ``{"game": ..., "paths": ...}``.

    *config* is a loaded config (by default the one titan loaded), raw TOML
    still in titan's old flat layout (top-level ``[game]``/``[paths]``) or a
    U8 section itself.
    """
    if config is None:
        from titan._config import get_config

        config = get_config()
    section = config.get("u8")
    if isinstance(section, dict):
        return section
    return {"game": config.get("game", {}), "paths": config.get("paths", {})}


def u8_cfg(key: str, table: str = "paths") -> Optional[str]:
    """One ``[u8.<table>]`` value from the loaded config, e.g. ``u8_cfg("fixed")``."""
    value = u8_section().get(table, {}).get(key)
    return value if value is None else str(value)


def _u8_paths(config: dict) -> dict:
    return u8_section(config).get("paths", {})


U8_WORKING_DIR_EXTS = {"shapes": ".shp", "globs": ".dat"}
"""Working folder -> the file extension its extracted records have."""


def has_working_files(folder: Path, working_dir: str) -> bool:
    """Whether *folder* already holds extracted records for *working_dir*."""
    ext = U8_WORKING_DIR_EXTS[working_dir]
    try:
        return any(child.suffix.lower() == ext for child in folder.iterdir())
    except OSError:
        return False


def prepare_working_dirs(config: Optional[dict] = None) -> list[tuple[str, Path, int]]:
    """Extract every empty U8 working folder (``shapes`` from U8SHAPES.FLX, ``globs``
    from GLOB.FLX) into where the config puts it, so map commands and front ends find
    them ready. Folders that already hold files are left alone.

    Returns ``(working_dir, folder, records written)`` for each folder extracted.
    """
    from titan._meta import configured_install
    from titan.flex import FlexArchive

    install = configured_install("u8", config)
    if install is None:
        return []
    done = []
    for working_dir in U8_WORKING_DIRS:
        folder = install.resources.get(working_dir)
        archive = u8_working_archive(working_dir, config)
        if (
            folder is None
            or archive is None
            or has_working_files(Path(folder), working_dir)
        ):
            continue
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        written = FlexArchive.from_file(str(archive)).extract_all(
            str(folder), flex_name=archive.name
        )
        done.append((working_dir, folder, written))
    return done


def u8_working_archive(
    working_dir: str, config: Optional[dict] = None
) -> Optional[Path]:
    """The configured install's archive for a working folder (``"shapes"``), or ``None``.

    ``shapes`` comes from ``U8SHAPES.FLX`` and ``globs`` from ``GLOB.FLX``. A
    config without a ``glob`` key finds GLOB.FLX beside ``u8shapes``/``fixed``.
    Returns ``None`` when the archive isn't configured or doesn't exist.
    """
    entry = U8_WORKING_DIR_ARCHIVES.get(working_dir)
    if entry is None:
        return None
    key, filename = entry
    paths = _u8_paths(config)
    configured = _str_value(paths, key)
    candidates = (
        [configured]
        if configured
        else [
            str(Path(value).expanduser().parent / filename)
            for value in (_str_value(paths, "u8shapes"), _str_value(paths, "fixed"))
            if value
        ]
    )
    for value in candidates:
        if Path(value).expanduser().is_file():
            return Path(value).expanduser()
    return None


def u8_working_dir_for_archive(archive: str | Path, config: dict) -> Optional[Path]:
    """The working folder an extraction of *archive* belongs in, or ``None``.

    Only the configured install's ``U8SHAPES.FLX`` and ``GLOB.FLX`` qualify:
    extracting them feeds the map commands, so they go to the folder those
    read (``[u8.paths] shapes``/``globs``). *config* is the loaded config.
    """
    paths = _u8_paths(config)
    try:
        path = Path(archive).expanduser().resolve()
        for working_dir in U8_WORKING_DIR_ARCHIVES:
            source = u8_working_archive(working_dir, config)
            target = _str_value(paths, working_dir)
            if source is not None and target and source.resolve() == path:
                return Path(target)
    except OSError:
        return None
    return None


def _expand_u8_working_dirs(data: dict, *, default: bool) -> None:
    """Resolve working folders; a configured U8 without them gets the defaults."""
    paths = data.setdefault("paths", {})
    for key in U8_WORKING_DIRS:
        value = _str_value(paths, key) or (f"{key}/" if default else "")
        if value:
            paths[key] = str(resolve_u8_working_dir(value))


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
    config = u8_section(config)
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
    folder. With no *value*, ``[u8.paths] nonfixed`` is the default save (the
    ``U8SAVE.000`` old setups wrote counts only when that file exists).

    Raises ``ValueError`` for a slot number when no save folder is known.
    """
    if value:
        path = Path(value).expanduser()
        if not value.isdigit() and (path.is_absolute() or path.exists()):
            return path
    else:
        value = _str_value(_u8_paths(config), "nonfixed")
        if not value:
            return None
        if Path(value).name.upper() == U8_LEGACY_SAVE_DEFAULT:
            # Old `titan setup` runs wrote this default whether or not the save existed
            # (loading expands it to a path in the save folder); it meant the base world.
            # Use it only when that save is really there.
            save_dir = u8_save_dir(config)
            legacy = Path(value).expanduser()
            if not legacy.is_absolute() and save_dir is not None:
                legacy = _save_in_folder(value, save_dir)
            return legacy if legacy.is_file() else None
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


def u8_install_candidates(config: dict | None = None) -> list[Path]:
    """List store-recorded, GOG Galaxy, GOG offline, legacy disc, Heroic and manual U8 folders.

    Folders Steam, GOG, Heroic or Lutris record for U8 (and ``[search] folders``
    from *config*) come first; see :mod:`titan._stores`.
    """
    candidates: list[Path] = []

    def _add_candidate(path: Path) -> None:
        if path not in candidates:
            candidates.append(path)

    for record in _stores.matching("u8", config):
        _add_candidate(record.path)

    # Windows: GOG Galaxy client (most common current install)
    for drive in _stores.drives():
        _add_candidate(
            Path(f"{drive}:\\Program Files (x86)\\GOG Galaxy\\Games\\Ultima 8")
        )
    # Windows: GOG Offline Installer + common manual redirects
    for drive in _stores.drives():
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


_U8_PATH_GROUPS = (
    ("fixed", "palette", "typeflag", "gumpage", "xformpal", "ecredits", "quotes"),
    ("u8shapes", "glob", "u8fonts", "u8gumps", "usecode"),
)


def u8_config_section(
    base: str,
    lang: str,
    savegame_value: str,
    usecode_detected: Path,
    *,
    manual_static: str = "",
    manual_usecode: str = "",
) -> dict:
    """``[u8.game]`` and ``[u8.paths]`` for an install (see :func:`u8_setup_lines`)."""
    static_manual = Path(manual_static) if manual_static else None
    if manual_usecode:
        usecode = manual_usecode
    elif static_manual is not None:
        usecode = str(static_manual.parent / "USECODE" / "EUSECODE.FLX")
    else:
        usecode = str(usecode_detected)

    if static_manual is not None:
        paths = {
            key: str(static_manual / filename).replace("\\", "/")
            for key, filename in U8_STATIC_FILES.items()
        }
    else:
        paths = dict(U8_STATIC_FILES)
    paths["usecode"] = usecode.replace("\\", "/")
    paths.update({key: f"{key}/" for key in U8_WORKING_DIRS})
    if savegame_value:
        paths["savegame"] = savegame_value
    return {
        "game": {"base": base.replace("\\", "/"), "language": lang},
        "paths": paths,
    }


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
    section = u8_config_section(
        base,
        lang,
        savegame_value,
        usecode_detected,
        manual_static=manual_static,
        manual_usecode=manual_usecode,
    )
    game, paths = section["game"], section["paths"]

    def _entry(key: str) -> str:
        return f'{key:<10}= "{paths[key]}"'

    lines = [
        "[u8.game]",
        f'base     = "{game["base"]}"',
        f'language = "{game["language"]}"',
        "",
        "[u8.paths]",
        *(_entry(key) for key in _U8_PATH_GROUPS[0]),
        "",
        *(_entry(key) for key in _U8_PATH_GROUPS[1]),
        "",
        "# Extracted working folders, relative to titan's data folder (titan config shows it)",
        *(_entry(key) for key in U8_WORKING_DIRS),
        "",
        "# Save folder; map commands take --save as a slot (3), file name or path",
    ]
    if not savegame_value:
        lines.append("# (flat install: saves are read from the base folder)")
    elif Path(savegame_value).is_absolute():
        lines.append(f'savegame  = "{savegame_value}"  # absolute (third-party engine)')
    else:
        lines.append(f'savegame  = "{savegame_value}"')
    lines.append('# Optional default save for map commands, e.g. nonfixed = "3"')
    return lines


def install_candidates(config: dict) -> list[Path]:
    """Install protocol: ``[u8.game] base``, then :func:`u8_install_candidates`."""
    base = u8_section(config).get("game", {}).get("base")
    configured = [Path(str(base)).expanduser()] if base else []
    return list(dict.fromkeys([*configured, *u8_install_candidates(config)]))


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: the U8 install at *path* (flat, or with a language folder)."""
    found = []
    for base, lang in discover_u8_installs([path.expanduser().absolute()]):
        static, usecode = u8_detected_paths(str(base), lang)
        resources = {
            key: static / name
            for key, name in U8_STATIC_FILES.items()
            if (static / name).is_file()
        }
        if usecode.is_file():
            resources["usecode"] = usecode
        save_dir = _default_u8_save_dir(base, lang)
        if save_dir.is_dir():
            resources["savegame"] = save_dir
        found.append(Installation("u8", base, resources, settings={"language": lang}))
    return found


def install_config(install: Installation) -> dict:
    """Install protocol: ``[u8.game]`` and ``[u8.paths]`` as setup writes them."""
    lang = install.settings.get("language", "")
    _, usecode = u8_detected_paths(str(install.root), lang)
    return u8_config_section(
        install.root.as_posix(), lang, U8_GAME_SAVE_DIR if lang else "", usecode
    )
