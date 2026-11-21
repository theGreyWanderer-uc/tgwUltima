"""Bounded U7 install discovery and shared configuration/Exult path resolution."""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from titan import _config
from titan._meta import Installation
from titan.fonts.exult_cfg import find_exult_cfg, parse_exult_cfg
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette
from titan.errors import InvalidDataError

RESOURCE_NAMES = {
    "shapes": "SHAPES.VGA",
    "palette": "PALETTES.FLX",
    "text": "TEXT.FLX",
}
U7_PATH_KINDS = {
    "static": "install-dir",
    **{key: "install-file" for key in RESOURCE_NAMES},
    "gamedat": "save",
    "savegame": "save-dir",
    # Keys only mod sections ([u7bg.mods."<name>".paths]) use.
    "saves": "save-dir",
    "root": "install-dir",
    "patch": "install-dir",
    "archive": "install-file",
}
"""``[u7bg.paths]``/``[u7si.paths]`` and mod ``paths`` key -> kind (see
:func:`titan._meta.path_kind`). ``gamedat`` is a ``save``: Exult's live game
state, which ``--save`` also reads from a save file."""
_SKIP_DIRS = {"mods", "patch", "saves", "gamedat", "static"}


def existing_path(path: Path) -> Path:
    """Respect file casing on Unix for installations copied from DOS/Windows."""
    if path.exists():
        return path.resolve()
    if path.parent == path:
        return path
    parent = existing_path(path.parent)
    try:
        return next(
            (
                entry
                for entry in parent.iterdir()
                if entry.name.lower() == path.name.lower()
            ),
            parent / path.name,
        )
    except OSError:
        return parent / path.name


def install_roots(candidate: Path, *, max_depth: int = 2) -> list[Path]:
    """Find game roots within two levels, visiting at most 128 directories.

    Include both games in complete collections. Do not follow symlinks or scan
    mod/patch/save directories, which can contain misleading partial archives.
    """
    candidate = existing_path(candidate.expanduser())
    if candidate.name.lower() == "static":
        candidate = candidate.parent
    pending = deque([(candidate, 0)])
    roots: list[Path] = []
    visited = 0
    while pending and visited < 128:
        directory, depth = pending.popleft()
        visited += 1
        static = existing_path(directory / "STATIC")
        if static.is_dir() and any(
            existing_path(static / name).is_file() for name in RESOURCE_NAMES.values()
        ):
            roots.append(directory)
            # Nested mods are not additional installations of this game.
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            continue
        for child in children:
            if (
                len(pending) + visited < 128
                and child.name.lower() not in _SKIP_DIRS
                and not child.is_symlink()
                and child.is_dir()
            ):
                pending.append((child, depth + 1))
    return roots


def install_game(root: Path) -> str:
    """Recognize SI roots from their own name or their install wrapper."""
    for part in reversed(root.parts):
        name = part.lower()
        if "serpent" in name or name.endswith("si"):
            return "SI"
        if name == "ultima7" or "black gate" in name or name.endswith("bg"):
            return "BG"
    return "BG"


@dataclass
class U7Installation:
    root: Path
    game: str
    paths: dict[str, Path]
    checks: dict[str, str]

    @property
    def valid(self) -> bool:
        return all(status == "OK" for status in self.checks.values())


def check_resource(key: str, path: Path) -> str:
    """Report missing/damaged U7 resources consistently in setup and config."""
    if not path.is_file():
        return "NOT FOUND"
    try:
        if key != "palette" or path.suffix.lower() != ".pal":
            archive = U7FlexArchive.from_file(str(path), strict=True)
            if not any(archive.records):
                raise InvalidDataError("Archive has no populated records")
        if key == "palette":
            U7Palette.from_file(str(path), palette_index=0)
    except (OSError, ValueError) as error:
        return f"INVALID: {error}"
    return "OK"


def inspect_install(
    root: Path,
    game: str | None = None,
    *,
    static: Path | None = None,
    resources: dict[str, Path] | None = None,
) -> U7Installation:
    """Validate expected Flex archives and decode main palette record zero."""
    root = existing_path(root.expanduser().absolute())
    static = existing_path(static if static is not None else root / "STATIC")
    paths = {"static": static}
    checks: dict[str, str] = {}
    for key, filename in RESOURCE_NAMES.items():
        path = existing_path((resources or {}).get(key, static / filename))
        paths[key] = path
        checks[key] = check_resource(key, path)
    return U7Installation(root, game or install_game(root), paths, checks)


def exult_game_paths(game: str) -> dict[str, Path]:
    """What Exult uses for the game, tolerating unavailable config.

    ``base`` and ``static`` from ``exult.cfg``. ``savegame`` (Exult's save
    folder) and ``gamedat`` (its live game state) from ``exult.cfg``'s
    ``savegame_path``/``gamedat_path``, else Exult's defaults: the profile's
    ``blackgate``/``serpentisle`` folder and its ``gamedat``. These two are
    where Exult would write; they need not exist.
    """
    cfg_path = find_exult_cfg()
    paths = None
    if cfg_path is not None:
        try:
            paths = parse_exult_cfg(cfg_path, game)
        except (OSError, ValueError):
            paths = None
    result = {}
    if paths and paths.game_path:
        result["base"] = existing_path(Path(paths.game_path).expanduser())
    if paths and paths.static_path:
        result["static"] = existing_path(Path(paths.static_path).expanduser())
    if cfg_path is None:
        profile = exult_profile_dir()
    elif cfg_path.name == ".exult.cfg":
        profile = cfg_path.parent / ".exult"
    else:
        profile = cfg_path.parent
    base = result.get("base")
    savegame = _config.resolve_config_path(paths and paths.savegame_path, base) or (
        profile / exult_game_slug(game) if profile is not None else None
    )
    gamedat = _config.resolve_config_path(paths and paths.gamedat_path, base) or (
        savegame / "gamedat" if savegame is not None else None
    )
    if savegame is not None:
        result["savegame"] = existing_path(savegame)
    if gamedat is not None:
        result["gamedat"] = existing_path(gamedat)
    return result


def _u7_section(game: str, config: dict) -> dict:
    return config.get("u7bg" if game.upper() == "BG" else "u7si", {})


def _section_path(section: dict, key: str) -> Path | None:
    """``[<section>.paths] key`` resolved against the section's base."""
    return _config.resolve_config_path(
        section.get("paths", {}).get(key), section.get("game", {}).get("base")
    )


def u7_path_candidates(
    game: str,
    key: str,
    config: dict | None = None,
    *,
    _roots: list[Path] | None = None,
    _exult: dict[str, Path] | None = None,
) -> list[Path]:
    """Try Titan settings, discovered nested roots, then Exult's game settings.

    *config* defaults to the loaded ``titan.toml``.
    """
    section = _u7_section(game, _config.get_config() if config is None else config)
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is not None:
            path = existing_path(path)
            if path not in candidates:
                candidates.append(path)

    add(_section_path(section, key))
    base = _config.resolve_config_path(section.get("game", {}).get("base"))
    static = _section_path(section, "static")
    if key in RESOURCE_NAMES:
        if static:
            add(static / RESOURCE_NAMES[key])
        if base:
            add(base / "STATIC" / RESOURCE_NAMES[key])
    elif key == "static" and base:
        add(base / "STATIC")
    if base and key in {"static", *RESOURCE_NAMES}:
        for root in install_roots(base) if _roots is None else _roots:
            if install_game(root) != game.upper() and root != base:
                continue
            add(
                root / "STATIC"
                if key == "static"
                else root / "STATIC" / RESOURCE_NAMES[key]
            )
    exult = exult_game_paths(game) if _exult is None else _exult
    if "static" in exult:
        if key == "static":
            add(exult["static"])
        elif key in RESOURCE_NAMES:
            add(exult["static"] / RESOURCE_NAMES[key])
    return candidates


def configured_u7_path(
    game: str,
    key: str,
    config: dict | None = None,
    *,
    _roots: list[Path] | None = None,
    _exult: dict[str, Path] | None = None,
) -> Path | None:
    """The first usable automatic path; a missing setting cannot mask Exult.

    This is U7's rule for ``static`` and the STATIC archives
    (:data:`RESOURCE_NAMES`); :func:`configured_install` applies it.
    """
    for path in u7_path_candidates(game, key, config, _roots=_roots, _exult=_exult):
        exists = path.is_dir() if key in {"static", "gamedat"} else path.is_file()
        if exists:
            return path
    return None


def resolve_u7_path(game: str, key: str) -> Path | None:
    """:func:`configured_u7_path` in the loaded ``titan.toml``, through the
    configured install (``titan._meta.configured_install``)."""
    install = _configured(game)
    path = install.resources.get(key) if install is not None else None
    if path is None:
        return None
    exists = path.is_dir() if key in {"static", "gamedat"} else path.is_file()
    return path if exists else None


def is_u7_folder_name(name: str) -> bool:
    """Recognize a launcher folder that holds Black Gate or Serpent Isle."""
    lowered = name.lower()
    if "ultima" not in lowered:
        return False
    return bool(re.search(r"ultima\s*vii(?!i)", lowered)) or any(
        token in lowered for token in ("ultima 7", "ultima7", "black gate", "serpent")
    )


def u7_install_candidates(
    config: dict,
) -> tuple[list[Path], dict[Path, str], dict[Path, Path]]:
    """List configured, Exult-registered, GOG, Heroic and manual U7 folders.

    Also returns the game each configured or Exult base is known to hold, and
    the STATIC folder Exult records for a base, so nonstandard installs are
    recognized without relying on their folder names.
    """
    candidates: list[Path] = []

    def _add_candidate(path: Path) -> None:
        if path not in candidates:
            candidates.append(path)

    exult_hints: dict[Path, str] = {}
    exult_statics: dict[Path, Path] = {}
    for game, section_key in (("BG", "u7bg"), ("SI", "u7si")):
        previous_base = config.get(section_key, {}).get("game", {}).get("base")
        if previous_base:
            configured_base = Path(previous_base).expanduser().resolve()
            exult_hints[configured_base] = game
            _add_candidate(configured_base)
        exult_paths = exult_game_paths(game)
        if "base" in exult_paths:
            exult_hints[exult_paths["base"].absolute()] = game
            if "static" in exult_paths:
                exult_statics[exult_paths["base"].absolute()] = exult_paths["static"]
            _add_candidate(exult_paths["base"])

    for drive in "CDEFG":
        for path in [
            Path(f"{drive}:\\GOG Games\\Ultima VII"),
            Path(f"{drive}:\\GOG Games\\Ultima VII - Complete"),
            Path(f"{drive}:\\Ultima\\ultima7bg"),
            Path(f"{drive}:\\Ultima\\ultima7si"),
            Path(f"{drive}:\\Ultima\\ultima7bg_no_exult"),
            Path(f"{drive}:\\Ultima\\ultima7si_no_exult"),
            Path(f"{drive}:\\ULTIMA7"),
            Path(f"{drive}:\\SERPENT"),
        ]:
            _add_candidate(path)

    for path in [
        Path.home() / "GOG Games" / "Ultima VII",
        Path.home() / "Games" / "Heroic" / "Ultima 7",
        Path.home() / "Games" / "Heroic" / "Ultima 7 - Serpent Isle",
    ]:
        _add_candidate(path)

    for root in (Path.home() / "GOG Games", Path.home() / "Games" / "Heroic"):
        if not root.is_dir():
            continue
        try:
            for folder in root.iterdir():
                if folder.is_dir() and is_u7_folder_name(folder.name):
                    _add_candidate(folder)
        except PermissionError:
            continue
    return candidates, exult_hints, exult_statics


def select_u7_install(
    value: str,
    game: str,
    exult_hints: dict[Path, str],
    exult_statics: dict[Path, Path],
) -> U7Installation | None:
    """Inspect the game root a user-chosen base holds, including nested roots."""
    if not value:
        return None
    candidate = Path(value).expanduser().absolute()
    roots = install_roots(candidate)
    matching = [
        root
        for root in roots
        if (exult_hints.get(root.absolute()) or install_game(root)) == game
    ]
    root = next(iter(matching or roots), candidate)
    # Selecting a base explicitly chooses the game even with a custom name.
    return inspect_install(root, game, static=exult_statics.get(root))


def relative_install_paths(selected: U7Installation | None) -> dict[str, str]:
    """Express an install's resource paths relative to its root where possible."""
    if selected is None:
        return {}
    return {
        key: path.relative_to(selected.root).as_posix()
        if path.is_relative_to(selected.root)
        else path.as_posix()
        for key, path in selected.paths.items()
    }


def u7_base_correction(
    section_key: str, selected: U7Installation | None, config: dict
) -> tuple[dict, list[str]]:
    """Propose a corrected base for a configured game whose root has moved.

    Returns the config update and the messages describing it. Custom relative
    paths are rewritten as absolute so they keep their meaning under the new
    base; both are empty when the configured base is already right.
    """
    previous = config.get(section_key, {}).get("game", {}).get("base")
    if not (
        selected
        and previous
        and Path(str(previous)).expanduser().resolve() != selected.root.resolve()
    ):
        return {}, []
    messages = [
        f"  Proposed {section_key} base correction: {previous} -> {selected.root}"
    ]
    update: dict = {"game": {"base": selected.root.as_posix()}}
    # Preserve the meaning of custom relative paths when changing base.
    previous_section = config[section_key]
    for key, value in previous_section.get("paths", {}).items():
        old_path = _config.resolve_config_path(value, previous)
        if not value or Path(str(value)).expanduser().is_absolute():
            continue
        standard = str(value).replace("\\", "/").upper().rstrip("/") in {
            "STATIC",
            "STATIC/SHAPES.VGA",
            "STATIC/PALETTES.FLX",
            "STATIC/TEXT.FLX",
            "GAMEDAT",
        }
        if old_path and (old_path.exists() or not standard):
            update.setdefault("paths", {})[key] = old_path.absolute().as_posix()
            messages.append(f"    Preserve custom {key}: {old_path.absolute()}")
    for mod_name, mod_config in previous_section.get("mods", {}).items():
        preserved = {}
        for key, value in mod_config.get("paths", {}).items():
            if value and not Path(str(value)).expanduser().is_absolute():
                preserved_path = _config.resolve_config_path(value, previous)
                if preserved_path is not None:
                    preserved[key] = preserved_path.absolute().as_posix()
        if preserved:
            update.setdefault("mods", {})[mod_name] = {"paths": preserved}
            messages.append(f"    Preserve custom paths for mod: {mod_name}")
    return update, messages


def exult_profile_dir() -> Path | None:
    """Return Exult's per-user data folder under ``%LOCALAPPDATA%``, if present."""
    local = os.getenv("LOCALAPPDATA")
    profile = Path(local) / "Exult" if local else None
    if profile is not None and not profile.is_dir():
        return None
    return profile


def _has_runtime_npc(path: Path) -> bool:
    return (path / "npc.dat").is_file()


def preferred_u7_gamedat(base_value: str, slug: str, exult_profile: Path | None) -> str:
    """Prefer Exult's live GAMEDAT (see :func:`exult_game_paths`), then the
    install's own, as :func:`configured_u7_gamedat` does without a setting."""
    candidates: list[Path] = []
    runtime = exult_game_paths("BG" if slug == "blackgate" else "SI").get("gamedat")
    if runtime is not None:
        candidates.append(runtime)
    elif exult_profile is not None:
        candidates.append(exult_profile / slug / "gamedat")
    if base_value:
        candidates.append(Path(base_value) / "gamedat")
        candidates.append(Path(base_value) / "GAMEDAT")
    for candidate in candidates:
        if _has_runtime_npc(candidate):
            return str(candidate).replace("\\", "/")
    return "gamedat/"


def discover_u7_mod_sources(
    base_value: str, slug: str, exult_profile: Path | None
) -> list[dict[str, str]]:
    """Setup's ``[u7xx.mods]`` tables: each mod under the install's ``mods``
    folder (:func:`titan.u7.mods.configured_u7_mods`) with its Exult profile
    folder, played GAMEDAT, saves and ``initgame.dat`` where they exist."""
    from titan.u7.mods import configured_u7_mods

    if not base_value:
        return []
    install_mods = existing_path(Path(base_value) / "mods")
    if not install_mods.is_dir():
        return []
    game_id = "u7bg" if slug == "blackgate" else "u7si"
    config = {game_id: {"game": {"base": base_value}}}
    sources: list[dict[str, str]] = []
    for mod in sorted(configured_u7_mods(config, game_id), key=lambda m: m.key.lower()):
        if mod.kind != "mod" or mod.install_dir is None:
            continue
        if mod.install_dir.parent.resolve() != install_mods.resolve():
            continue
        item: dict[str, str] = {"name": mod.key}
        if mod.profile_dir is not None and mod.profile_dir.is_dir():
            item["root"] = mod.profile_dir.as_posix()
        if mod.played:
            item["gamedat"] = mod.gamedat.as_posix()
        if mod.saves is not None and any(mod.saves.glob("*.sav")):
            item["saves"] = mod.saves.as_posix()
        if mod.archive is not None:
            item["archive"] = mod.archive.as_posix()
        if len(item) > 1:
            sources.append(item)
    return sources


def find_exult_flx(flx_name: str) -> Path | None:
    """Find ``exult_bg.flx`` / ``exult_si.flx`` in a standard Exult install."""
    candidates: list[Path] = []
    for drive in "CD":
        for layout in (
            Path(f"{drive}:\\Program Files\\Exult\\data"),
            Path(f"{drive}:\\Program Files (x86)\\Exult\\data"),
            Path(f"{drive}:\\Program Files\\Exult"),
            Path(f"{drive}:\\Program Files (x86)\\Exult"),
        ):
            candidates.append(layout / flx_name)
    for share in (
        Path("/usr/share/exult"),
        Path("/usr/local/share/exult"),
        Path("/opt/exult"),
    ):
        candidates.append(share / flx_name)
    return next((p for p in candidates if p.is_file()), None)


_VARIANTS = {"u7bg": "blackgate", "u7si": "serpentisle"}
_GAME_LETTERS = {"u7bg": "BG", "u7si": "SI"}


def u7_config_section(
    variant: str,
    base: str,
    paths: dict[str, str],
    gamedat: str,
    mod_sources: list[dict[str, str]],
) -> dict:
    """One game's ``game``, ``paths`` and ``mods`` tables (see :func:`u7_setup_lines`)."""
    section: dict = {
        "game": {"base": base, "variant": variant},
        "paths": {
            **{key: paths[key] for key in ("static", *RESOURCE_NAMES)},
            "gamedat": gamedat,
        },
    }
    mods = {
        item["name"]: {
            "paths": {
                key: item[key]
                for key in ("gamedat", "saves", "root", "archive")
                if key in item
            }
        }
        for item in mod_sources
    }
    if mods:
        section["mods"] = mods
    return section


def u7_setup_lines(
    section_name: str,
    variant: str,
    base: str,
    paths: dict[str, str],
    gamedat: str,
    mod_sources: list[dict[str, str]],
) -> list[str]:
    """Render one game's ``[u7xx.game]``, ``[u7xx.paths]`` and mod sections."""
    from titan._setup_config import section_lines

    return section_lines(
        {section_name: u7_config_section(variant, base, paths, gamedat, mod_sources)}
    )


def u7_manual_config_section(static_path: str, variant: str) -> dict:
    """One game's tables from a manually entered STATIC folder."""
    static_p = Path(static_path).expanduser().absolute()
    static_norm = static_p.as_posix()
    return {
        "game": {"base": static_p.parent.as_posix(), "variant": variant},
        "paths": {
            "static": static_norm,
            **{key: f"{static_norm}/{name}" for key, name in RESOURCE_NAMES.items()},
            "gamedat": (static_p.parent / "gamedat").as_posix(),
        },
    }


def u7_manual_setup_lines(static_path: str, variant: str) -> list[str]:
    """Render a game's sections from a manually entered STATIC folder."""
    from titan._setup_config import section_lines

    section_name = "u7bg" if variant == "blackgate" else "u7si"
    return section_lines({section_name: u7_manual_config_section(static_path, variant)})


def as_installation(game_id: str, selected: U7Installation) -> Installation:
    """The :class:`~titan._meta.Installation` for a :class:`U7Installation`."""
    return Installation(
        game_id,
        selected.root,
        dict(selected.paths),
        {key: status for key, status in selected.checks.items() if status != "OK"},
        {"variant": _VARIANTS[game_id]},
    )


def install_candidates(config: dict, game_id: str) -> list[Path]:
    """Install protocol: configured, Exult-registered, GOG, Heroic and manual
    folders. They can hold either game; :func:`discover_installs` sorts them."""
    return u7_install_candidates(config)[0]


def discover_installs(path: Path, game_id: str) -> list[Installation]:
    """Install protocol: *game_id* roots within two levels of *path*.

    A root's game comes from Exult's settings, then its folder name. When
    *path* is itself a root that no hint places in either game, it counts as
    the requested one: choosing a folder explicitly chooses the game.
    """
    game = _GAME_LETTERS[game_id]
    hints: dict[Path, str] = {}
    statics: dict[Path, Path] = {}
    for letter in ("BG", "SI"):
        exult = exult_game_paths(letter)
        if "base" in exult:
            hints[exult["base"].absolute()] = letter
            if "static" in exult:
                statics[exult["base"].absolute()] = exult["static"]
    candidate = existing_path(path.expanduser().absolute())
    roots = [root.absolute() for root in install_roots(candidate)]
    if candidate in statics and not roots:
        roots = [candidate]
    matching = [
        root for root in roots if (hints.get(root) or install_game(root)) == game
    ]
    if not matching and candidate in roots and candidate not in hints:
        matching = [candidate]
    return [
        as_installation(game_id, inspect_install(root, game, static=statics.get(root)))
        for root in matching
    ]


def install_config(install: Installation) -> dict:
    """Install protocol: the game's tables as setup writes them, with the
    preferred GAMEDAT and any mods found under the install."""
    variant = _VARIANTS[install.game_id]
    base = install.root.as_posix()
    profile = exult_profile_dir()
    paths = {
        key: path.relative_to(install.root).as_posix()
        if path.is_relative_to(install.root)
        else path.as_posix()
        for key, path in install.resources.items()
    }
    return u7_config_section(
        variant,
        base,
        paths,
        preferred_u7_gamedat(base, variant, profile),
        discover_u7_mod_sources(base, variant, profile),
    )


def configured_u7_gamedat(
    game: str, config: dict | None = None, *, _exult: dict | None = None
) -> Path | None:
    """U7's ``gamedat`` rule: ``[<section>.paths] gamedat`` as configured (it
    need not exist yet), else Exult's live GAMEDAT when it holds a played game
    (``npc.dat``; see :func:`exult_game_paths`), else the base's own
    ``gamedat`` folder."""
    section = _u7_section(game, _config.get_config() if config is None else config)
    base = section.get("game", {}).get("base")
    base_path = Path(str(base)).expanduser() if base else None
    configured = section.get("paths", {}).get("gamedat")
    if configured:
        path = Path(str(configured)).expanduser()
        if path.is_absolute() or base_path is None:
            return path
        return base_path / path
    runtime = (exult_game_paths(game) if _exult is None else _exult).get("gamedat")
    if runtime is not None and _has_runtime_npc(runtime):
        return runtime
    if base_path is not None:
        for name in ("gamedat", "GAMEDAT"):
            candidate = base_path / name
            if candidate.is_dir():
                return candidate
    return None


def default_u7_exult_flx(game: str) -> str | None:
    """A standard Exult install's ``exult_bg.flx``/``exult_si.flx``, or ``None``.

    What library loaders use when given no bundle. It reads no ``titan.toml``:
    an ``[exult.paths]`` bundle comes from the caller (``resolve_u7_exult_flx``,
    or ``configured_install(...).resources["exult_flx"]``).
    """
    found = find_exult_flx(f"exult_{'bg' if game.lower() == 'bg' else 'si'}.flx")
    return str(found) if found else None


def configured_u7_exult_flx(game: str, config: dict | None = None) -> Path | None:
    """Exult's per-game bundle: ``[exult.paths] bg_flx``/``si_flx`` when it
    exists, else a standard Exult install's ``exult_bg.flx``/``exult_si.flx``."""
    game_key = "bg" if game.lower() == "bg" else "si"
    loaded = _config.get_config() if config is None else config
    configured = loaded.get("exult", {}).get("paths", {}).get(f"{game_key}_flx")
    if configured and Path(configured).is_file():
        return Path(configured)
    return find_exult_flx(f"exult_{game_key}.flx")


def configured_install(config: dict, game_id: str) -> Installation | None:
    """Install protocol hook: what U7 commands use by default.

    ``resources`` hold ``static`` and the STATIC archives from
    :func:`configured_u7_path` (the configured path, then the base's own
    STATIC, nested roots and Exult's game settings: a configured path that
    doesn't exist falls back rather than masking Exult), ``gamedat`` from
    :func:`configured_u7_gamedat` (kept even when it doesn't exist yet, since
    Exult creates it), ``savegame`` (as configured, else Exult's save folder
    when it exists, else the folder holding GAMEDAT), any other ``[<section>.paths]`` key that exists, and
    ``exult_flx`` (:func:`configured_u7_exult_flx`), and ``exult_common_flx``
    (``[exult.paths] flx``, Exult's ``exult.flx``) when set. ``problems`` reports
    each ``[<section>.paths]`` entry that doesn't exist (``"NOT FOUND"``), even
    when a fallback stands in for it. ``root`` is
    the configured base, else Exult's base for the game, else ``Path()``.
    ``None`` when neither the config nor Exult provides the game.
    """
    game = _GAME_LETTERS[game_id]
    section = _u7_section(game, config)
    declared = [
        key
        for key, value in section.get("paths", {}).items()
        if isinstance(value, (str, Path))
    ]
    base = _config.resolve_config_path(section.get("game", {}).get("base"))
    roots = install_roots(base) if base else []
    exult = exult_game_paths(game)
    resources: dict[str, Path] = {}
    problems: dict[str, str] = {}
    for key in ("static", *RESOURCE_NAMES):
        path = configured_u7_path(game, key, config, _roots=roots, _exult=exult)
        if path is not None:
            resources[key] = path
        setting = _section_path(section, key) if key in declared else None
        if setting is not None and existing_path(setting) != path:
            problems[key] = "NOT FOUND"
    gamedat = configured_u7_gamedat(game, config, _exult=exult)
    if gamedat is not None:
        resources["gamedat"] = gamedat
        if not gamedat.is_dir():
            problems["gamedat"] = "NOT FOUND"
    for key in declared:
        if key in resources or key in problems:
            continue
        path = _section_path(section, key)
        if path is not None and path.exists():
            resources[key] = path
        else:
            problems[key] = "NOT FOUND"
    if "savegame" not in resources and "savegame" not in problems:
        saves = exult.get("savegame")
        if saves is not None and saves.is_dir():
            resources["savegame"] = saves
        elif gamedat is not None and gamedat.is_dir():
            resources["savegame"] = gamedat.parent
    runtime_only = {"gamedat", "savegame"}
    if base is None and not set(resources) - runtime_only and not problems:
        return None
    exult_flx = configured_u7_exult_flx(game, config)
    if exult_flx is not None:
        resources["exult_flx"] = exult_flx
    common = config.get("exult", {}).get("paths", {}).get("flx")
    if common and Path(common).expanduser().is_file():
        resources["exult_common_flx"] = Path(common).expanduser()
    settings = {"variant": _VARIANTS[game_id]}
    settings.update(
        (key, str(value))
        for key, value in section.get("game", {}).items()
        if key != "base" and isinstance(value, (str, int, float, bool))
    )
    return Installation(
        game_id,
        base or exult.get("base") or Path(),
        resources,
        problems,
        settings,
        frozenset(declared),
    )


def _configured(game: str) -> Installation | None:
    """The configured install for ``"BG"``/``"SI"`` (``titan._meta.configured_install``)."""
    from titan._meta import configured_install as configured

    return configured("u7bg" if game.upper() == "BG" else "u7si")


def u7_static_and_palette(
    install: Installation | None,
) -> tuple[str | None, str | None]:
    """*install*'s STATIC folder and PALETTES.FLX, as strings."""
    resources = install.resources if install is not None else {}
    static, palette = resources.get("static"), resources.get("palette")
    return str(static) if static else None, str(palette) if palette else None


def u7_text_flx(
    install: Installation | None, static_dir: str | None = None
) -> str | None:
    """TEXT.FLX: the configured one when it exists, else *static_dir*'s own,
    else whatever *install* found."""
    text = install.resources.get("text") if install is not None else None
    if (
        text is not None
        and "text" in install.configured
        and "text" not in install.problems
    ):
        return str(text)
    if static_dir:
        selected = existing_path(Path(static_dir) / "TEXT.FLX")
        if selected.is_file():
            return str(selected)
    return str(text) if text else None


def resolve_u7_static_and_palette(game: str) -> tuple[str | None, str | None]:
    """The configured install's STATIC and PALETTES.FLX (:func:`u7_static_and_palette`)."""
    return u7_static_and_palette(_configured(game))


def resolve_u7_patch_base_static(
    selected_static: str,
    configured_static: str | None,
) -> str | None:
    """Find a distinct base STATIC for an explicitly selected mod patch."""
    selected_path = Path(selected_static).expanduser().resolve()

    def _is_usable_base(candidate: Path) -> bool:
        try:
            distinct = candidate.resolve() != selected_path
        except OSError:
            distinct = candidate != selected_path
        if not distinct or not candidate.is_dir():
            return False
        return any(
            (candidate / filename).is_file()
            for filename in ("SHAPES.VGA", "shapes.vga")
        )

    if configured_static:
        configured_path = Path(configured_static).expanduser()
        if _is_usable_base(configured_path):
            return str(configured_path)

    for ancestor in (selected_path, *selected_path.parents):
        for dirname in ("STATIC", "static"):
            candidate = ancestor / dirname
            if _is_usable_base(candidate):
                return str(candidate)
    return None


def resolve_u7_text_flx(game: str, static_dir: str | None = None) -> str | None:
    """The configured install's TEXT.FLX (:func:`u7_text_flx`)."""
    return u7_text_flx(_configured(game), static_dir)


def resolve_u7_gamedat(game: str) -> str | None:
    """The configured install's loose GAMEDAT (:func:`configured_u7_gamedat`)."""
    install = _configured(game)
    gamedat = install.resources.get("gamedat") if install is not None else None
    return str(gamedat) if gamedat else None


def resolve_u7_exult_flx(game: str) -> str | None:
    """The Exult bundle the configured install uses (:func:`configured_u7_exult_flx`)."""
    install = _configured(game)
    if install is None:
        bundle = configured_u7_exult_flx(game)
    else:
        bundle = install.resources.get("exult_flx")
    return str(bundle) if bundle else None


def resolve_ucxt_intrinsics_data(
    game: str,
    intrinsics_data: str | None = None,
) -> str | None:
    """Resolve optional UCXT intrinsic-name table for U7 raw usecode output."""
    game_key = game.lower()
    if game_key not in ("bg", "si"):
        raise ValueError("U7 intrinsic game must be bg or si")
    if intrinsics_data is not None:
        path = Path(intrinsics_data).expanduser()
        if not path.is_file():
            raise ValueError(f"U7 intrinsic table not found: {path}")
        return str(path)
    filename = "u7bgintrinsics.data" if game_key == "bg" else "u7siintrinsics.data"
    candidates: list[Path] = []
    for drive in ("C", "D"):
        candidates.extend(
            [
                Path(f"{drive}:\\Program Files\\Exult\\Tools\\data") / filename,
                Path(f"{drive}:\\Program Files (x86)\\Exult\\Tools\\data") / filename,
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def exult_game_slug(game: str) -> str:
    return "blackgate" if game.lower() == "bg" else "serpentisle"


def _configured_mod(game: str, mod: str | None, config: dict | None):
    from titan.u7.mods import configured_u7_mods, find_u7_mod

    if not mod:
        return None
    loaded = (_config.get_config() if config is None else config) or {}
    game_id = "u7bg" if game.lower() == "bg" else "u7si"
    return find_u7_mod(configured_u7_mods(loaded, game_id), mod)


def resolve_u7_mod_gamedat(
    game: str, mod: str | None, config: dict | None = None
) -> str | None:
    """The played GAMEDAT of ``--mod MOD`` (:func:`titan.u7.mods.configured_u7_mods`),
    or ``None``. *config* defaults to the loaded ``titan.toml``."""
    found = _configured_mod(game, mod, config)
    return str(found.gamedat) if found is not None and found.played else None


def resolve_u7_mod_archive(
    game: str, mod: str | None, config: dict | None = None
) -> str | None:
    """The ``initgame.dat`` of ``--mod MOD`` (see :func:`resolve_u7_mod_gamedat`)."""
    found = _configured_mod(game, mod, config)
    archive = found.archive if found is not None else None
    return str(archive) if archive is not None and archive.is_file() else None
    cfg = (_config.get_config() if config is None else config) or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    mods_cfg = section.get("mods", {}) if isinstance(section, dict) else {}
    mod_cfg = mods_cfg.get(mod, {}) if isinstance(mods_cfg, dict) else {}
    paths_cfg = mod_cfg.get("paths", {}) if isinstance(mod_cfg, dict) else {}
    archive = paths_cfg.get("archive") if isinstance(paths_cfg, dict) else None
    if archive:
        path = _config.resolve_config_path(archive, game_cfg.get("base"))
        if path and path.is_file():
            return str(path)
    base_path = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    if base_path:
        mod_root = Path(str(base_path)).expanduser() / "mods" / mod
        for candidate in (
            mod_root / "patch" / "initgame.dat",
            mod_root / "data" / "initgame.dat",
        ):
            if candidate.is_file():
                return str(candidate)
    return None
