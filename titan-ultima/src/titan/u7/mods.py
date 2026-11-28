"""Ultima VII mods and Exult custom games: one list for ``--mod``, the world
picker and ``titan setup``.

A mod is found from its description (``<mods>/<key>.cfg``, Exult's format),
a bare folder with a ``patch`` folder (``<mods>/<key>/patch``), or a
``[u7bg.mods."<key>".paths]`` table. The mods folders are Exult's
(``exult.cfg``) and the install's ``mods``. Exult custom games are the other
``exult.cfg`` ``<disk><game>`` entries.

Each path follows the install record's rule: a configured path wins (and is
reported in ``problems`` when it doesn't exist), then the ``.cfg``
description, then the standard folders.
"""

from __future__ import annotations

# Config parsing below rejects DTDs before any entity expansion.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from titan._config import resolve_config_path
from titan.fonts.exult_cfg import ExultGamePaths, parse_exult_cfg
from titan.u7 import install as _install
from titan.u7.install import existing_path
from titan.errors import InvalidDataError

__all__ = [
    "MOD_PATH_KEYS",
    "U7Mod",
    "configured_u7_mods",
    "discover_u7_mods",
    "find_u7_mod",
    "list_mods",
]

MOD_PATH_KEYS = ("root", "patch", "static", "gamedat", "saves", "archive")
"""``[u7bg.mods."<key>".paths]`` keys (``savegame`` is accepted for ``saves``)."""

_FIELDS = {"root": "profile_dir"}
_INITGAME = "initgame.dat"


@dataclass(frozen=True)
class U7Mod:
    """One mod or Exult custom game for BG or SI."""

    key: str
    """What ``--mod`` takes: the ``.cfg`` name, folder name or config table name."""
    title: str
    """The ``.cfg`` ``display_string`` (or ``exult.cfg`` title), else *key*."""
    kind: str = "mod"
    """``"mod"`` or ``"exult-game"`` (an ``exult.cfg`` custom game)."""
    install_dir: Optional[Path] = None
    """The mod's own folder (``<mods>/<key>``), or the Exult game's folder."""
    profile_dir: Optional[Path] = None
    """Where Exult keeps its live state and saves (config key ``root``)."""
    patch: Optional[Path] = None
    static: Optional[Path] = None
    """Its own STATIC, for a mod or game that doesn't use the retail one."""
    gamedat: Optional[Path] = None
    """Where its GAMEDAT is or will be; see :attr:`played`."""
    saves: Optional[Path] = None
    archive: Optional[Path] = None
    """Its ``initgame.dat`` (the starting GAMEDAT), when it has one."""
    problems: Mapping[str, str] = field(default_factory=dict)
    """Config key -> ``"NOT FOUND"`` for configured paths that don't exist."""
    configured: frozenset[str] = frozenset()
    """The path keys ``[u7xx.mods."<key>".paths]`` sets."""

    @property
    def played(self) -> bool:
        """Whether its GAMEDAT holds a game (``npc.dat``)."""
        return self.gamedat is not None and (self.gamedat / "npc.dat").is_file()

    @property
    def label(self) -> str:
        """How pickers show it: the title, with the ``--mod`` key."""
        game = ", Exult game" if self.kind == "exult-game" else ""
        if self.title == self.key and not game:
            return self.key
        return f"{self.title} ({self.key}{game})"


class _ConfigTreeBuilder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("Exult configuration must not contain a DTD")


def _read_config_xml(path: Path) -> ET.Element:
    # Exult Studio can write NUL bytes in mod descriptions. DTDs are rejected
    # by the parser target, so custom entities cannot expand during discovery.
    data = path.read_bytes().replace(b"\x00", b"")
    parser = ET.XMLParser(target=_ConfigTreeBuilder())  # nosec B314
    return ET.fromstring(data, parser=parser)  # nosec B314


def _profile_root(cfg_path: Path) -> Path:
    return (
        cfg_path.parent / ".exult" if cfg_path.name == ".exult.cfg" else cfg_path.parent
    )


def _game_save_root(
    entry: ET.Element | None, tag: str, cfg_path: Path, game_root: Path | None
) -> Path:
    value = entry.findtext("savegame_path") if entry is not None else None
    return resolve_config_path(value, game_root) or _profile_root(cfg_path) / tag


def _macro_path(value: str, mods: Path, mod: Path) -> Path | None:
    value = (
        value.strip().replace("__MODS__", str(mods)).replace("__MOD_PATH__", str(mod))
    )
    path = resolve_config_path(value, mod)
    return None if path is None or "<" in str(path) else path


def _described(cfg_path: Path, mods: Path, save_root: Path | None) -> dict:
    """A mod from its ``.cfg`` description, with Exult's path macros expanded."""
    root = _read_config_xml(cfg_path)
    info = root.find("mod_info")
    if info is None:
        info = root
    name = (info.findtext("mod_title") or cfg_path.stem).strip()
    mod_root = mods / name
    patch = _macro_path(
        info.findtext("patch") or str(mod_root / "patch"), mods, mod_root
    )
    if patch is None:
        raise InvalidDataError(f"Unresolved patch path in {cfg_path}")
    save_mods = save_root / "mods" if save_root else mods
    save_mod = save_mods / name
    gamedat = _macro_path(
        info.findtext("gamedat_path") or str(save_mod / "gamedat"), save_mods, save_mod
    )
    saves = _macro_path(
        info.findtext("savegame_path") or str(save_mod), save_mods, save_mod
    )
    return {
        "key": cfg_path.stem,
        "title": " ".join((info.findtext("display_string") or name).split()),
        "install_dir": mod_root,
        "profile_dir": save_mod if save_root else None,
        "patch": existing_path(patch),
        "gamedat": existing_path(gamedat) if gamedat else None,
        "saves": existing_path(saves) if saves else None,
    }


def _folder(folder: Path) -> dict:
    """A mod folder with a ``patch`` folder and no description."""
    own_static = existing_path(folder / "static")
    gamedat = existing_path(folder / "gamedat")
    return {
        "key": folder.name,
        "title": folder.name,
        "install_dir": folder,
        "patch": existing_path(folder / "patch"),
        "static": own_static if own_static.is_dir() else None,
        "gamedat": gamedat if gamedat.is_dir() else None,
        "saves": folder,
    }


def _exult_games(
    cfg_root: ET.Element, cfg_path: Path, game: str | None = None
) -> list[dict]:
    """Exult's custom games (``exult.cfg`` ``<disk><game>`` entries other than
    the two retail ones). With *game* (``"BG"``/``"SI"``), only those built on
    it: a custom game's own STATIC data says which (Serpent Isle's paperdolls
    and speech vs the Black Gate's endgame and speech); one whose data says
    neither is kept for both."""
    from titan.u7.install import content_game

    games = []
    for entry in cfg_root.findall("disk/game/*"):
        if entry.tag in {"blackgate", "serpentisle"}:
            continue
        base_path = (entry.findtext("path") or "").strip()
        if not base_path:
            continue
        root = Path(base_path).expanduser()
        if not root.is_dir():
            continue
        built_on = content_game(root)
        if game and built_on and built_on != game.upper():
            continue
        static = resolve_config_path(entry.findtext("static_path") or "static", root)
        patch = resolve_config_path(entry.findtext("patch") or "patch", root)
        if static is None or patch is None:
            continue
        saves = _game_save_root(entry, entry.tag, cfg_path, root)
        games.append(
            {
                "key": entry.tag,
                "title": " ".join((entry.findtext("title") or entry.tag).split()),
                "kind": "exult-game",
                "install_dir": root,
                "profile_dir": saves,
                "patch": existing_path(patch),
                "static": existing_path(static),
                "gamedat": resolve_config_path(entry.findtext("gamedat_path"), root)
                or saves / "gamedat",
                "saves": saves,
            }
        )
    return games


def _found(path: Path) -> Path:
    """*path* as written when it exists, else its case-insensitive match."""
    return path if path.exists() else existing_path(path)


def _has_npc(path: Path | None) -> bool:
    return path is not None and (path / "npc.dat").is_file()


def _scan_mod_dir(directory: Path, save_root: Path | None, found: dict) -> None:
    """Add the mods in one mods folder: descriptions first, so a described
    mod keeps its title, then bare folders not already described."""
    for entry in sorted(
        directory.iterdir(), key=lambda path: (path.is_dir(), path.name.lower())
    ):
        if entry.is_file() and entry.suffix.lower() == ".cfg":
            try:
                item = _described(entry, directory, save_root)
            except (OSError, ValueError, ET.ParseError):
                continue
        elif entry.is_dir() and existing_path(entry / "patch").is_dir():
            item = _folder(existing_path(entry.absolute()))
            if _with_patch(found, item["patch"], skip=()) is not None:
                continue
        else:
            continue
        found.setdefault(item["key"].casefold(), item)


def _with_patch(found: dict, patch: Path, skip) -> str | None:
    """The key of the found mod whose patch folder is *patch*, if any."""
    target = patch.resolve()
    return next(
        (
            key
            for key, item in found.items()
            if key not in skip
            and item.get("patch") is not None
            and item["patch"].resolve() == target
        ),
        None,
    )


def discover_u7_mods(
    game: str,
    config: dict,
    *,
    exult_paths: ExultGamePaths | None = None,
    exult_cfg_path: Path | None = None,
    save_root: Path | None = None,
) -> list[U7Mod]:
    """Every mod and Exult custom game for ``"BG"``/``"SI"``, sorted by title.

    *config* is a loaded ``titan.toml`` (only ``[u7xx.game] base`` and
    ``[u7xx.mods]`` are read); *exult_paths* and *exult_cfg_path* are Exult's
    settings for the game and its ``exult.cfg``; *save_root* is Exult's save
    folder for the game (mods keep their state in ``<save_root>/mods/<key>``;
    without one, in the mod's own folder).
    """
    section = config.get("u7bg" if game.upper() == "BG" else "u7si", {})
    base = section.get("game", {}).get("base")
    found: dict[str, dict] = {}

    mod_dirs: list[Path] = []
    if exult_paths and exult_paths.mods_path:
        mod_dirs.append(Path(exult_paths.mods_path).expanduser())
    if base:
        mod_dirs.append(Path(base).expanduser() / "mods")
    for directory in dict.fromkeys(existing_path(d) for d in mod_dirs):
        if directory.is_dir():
            _scan_mod_dir(directory, save_root, found)

    if exult_cfg_path:
        try:
            cfg_root = _read_config_xml(exult_cfg_path)
        except (OSError, ValueError, ET.ParseError):
            cfg_root = ET.Element("config")
        for item in _exult_games(cfg_root, exult_cfg_path, game):
            found.setdefault(item["key"].casefold(), item)

    settings = {
        name.casefold(): (name, entry)
        for name, entry in section.get("mods", {}).items()
        if isinstance(entry, dict)
    }
    # A table named differently from the mod it configures (same patch folder)
    # joins that mod; its table name becomes the key.
    for folded, (name, entry) in settings.items():
        patch = _configured_patch(entry.get("paths", {}), base)
        if folded in found or patch is None:
            continue
        match = _with_patch(found, patch, skip=settings)
        if match is not None:
            found[folded] = {**found.pop(match), "key": name}

    mods: list[U7Mod] = []
    for folded in dict.fromkeys([*found, *settings]):
        item = dict(found.get(folded) or {})
        name, entry = settings.get(folded, (None, {}))
        item.setdefault("key", name)
        item.setdefault("title", name)
        mods.append(_with_settings(item, entry.get("paths", {}), base))
    return sorted(mods, key=lambda mod: (mod.title.casefold(), mod.key.casefold()))


def _configured_patch(paths: object, base: object) -> Path | None:
    if not isinstance(paths, dict):
        return None
    patch = resolve_config_path(paths.get("patch"), base)
    archive = resolve_config_path(paths.get("archive"), base)
    if patch is None and archive is not None and archive.parent.name.lower() == "patch":
        patch = archive.parent
    return patch


def _apply_settings(item: dict, paths: object, base: object) -> tuple[set, dict]:
    """Put each configured path over the discovered one; report missing ones."""
    configured: set[str] = set()
    problems: dict[str, str] = {}
    if not isinstance(paths, dict):
        return configured, problems
    for key in (*MOD_PATH_KEYS, "savegame"):
        name = "saves" if key == "savegame" else key
        path = resolve_config_path(paths.get(key), base)
        if path is None or name in configured:
            continue
        path = _found(path)
        configured.add(name)
        if not path.exists():
            problems[name] = "NOT FOUND"
        item[_FIELDS.get(name, name)] = path
    return configured, problems


def _default_patch(item: dict, base: object) -> Path | None:
    archive = item.get("archive")
    profile = item.get("profile_dir")
    candidates = []
    if archive is not None and archive.parent.name.lower() == "patch":
        return archive.parent
    if profile is not None:
        candidates.append(profile / "patch")
    if base:
        candidates.append(Path(str(base)).expanduser() / "mods" / item["key"] / "patch")
    return next(
        (existing_path(c) for c in candidates if existing_path(c).is_dir()), None
    )


def _default_install_dir(item: dict, base: object) -> Path | None:
    if base:
        own = existing_path(Path(str(base)).expanduser() / "mods" / item["key"])
        if own.is_dir():
            return own
    return item["patch"].parent if item.get("patch") is not None else None


def _default_gamedat(item: dict, configured: set) -> Path | None:
    """The configured, described or profile GAMEDAT; for an unplayed one, a
    played GAMEDAT in the mod's own folder instead."""
    profile = item.get("profile_dir")
    if "root" in configured and "gamedat" not in configured:
        item["gamedat"] = profile / "gamedat"
    gamedat = item.get("gamedat")
    if gamedat is None and profile is not None:
        gamedat = profile / "gamedat"
    own = item.get("install_dir")
    own = existing_path(own / "gamedat") if own is not None else None
    if "gamedat" not in configured and not _has_npc(gamedat) and _has_npc(own):
        return own
    return gamedat


def _default_archive(item: dict) -> Path | None:
    candidates = []
    if item.get("patch") is not None:
        candidates.append(item["patch"] / _INITGAME)
    if item.get("install_dir") is not None:
        candidates += [
            item["install_dir"] / sub / _INITGAME for sub in ("patch", "data")
        ]
    return next((_found(c) for c in candidates if _found(c).is_file()), None)


def _with_settings(item: dict, paths: dict, base: object) -> U7Mod:
    """Apply ``[u7xx.mods."<key>".paths]`` over what discovery found, then fill
    in the standard folders for what is still missing."""
    configured, problems = _apply_settings(item, paths, base)
    if item.get("patch") is None:
        item["patch"] = _default_patch(item, base)
    if item.get("install_dir") is None:
        item["install_dir"] = _default_install_dir(item, base)
    item["gamedat"] = _default_gamedat(item, configured)
    if item.get("saves") is None:
        item["saves"] = item.get("profile_dir")
    if item.get("archive") is None:
        item["archive"] = _default_archive(item)
    return U7Mod(
        **{k: v for k, v in item.items() if k in U7Mod.__dataclass_fields__},
        problems=problems,
        configured=frozenset(configured),
    )


def configured_u7_mods(
    config: dict,
    game_id: str,
    *,
    exult_cfg_path: Path | None | bool = True,
    exult_paths: ExultGamePaths | None | bool = True,
) -> list[U7Mod]:
    """:func:`discover_u7_mods` with Exult's settings looked up: ``exult.cfg``
    (``True`` means find it), its paths for the game, and Exult's save folder
    (:func:`titan.u7.install.exult_game_paths`)."""
    game = "BG" if game_id == "u7bg" else "SI"
    cfg = _install.find_exult_cfg() if exult_cfg_path is True else exult_cfg_path
    paths = exult_paths if exult_paths is not True else None
    if exult_paths is True and cfg:
        try:
            paths = parse_exult_cfg(cfg, game)
        except (OSError, ValueError):
            paths = None
    return discover_u7_mods(
        game,
        config,
        exult_paths=paths or None,
        exult_cfg_path=cfg or None,
        save_root=_install.exult_game_paths(game).get("savegame"),
    )


_PATH_FIELDS = (
    "install_dir",
    "profile_dir",
    "patch",
    "static",
    "gamedat",
    "saves",
    "archive",
)


def list_mods(config: dict, game_id: str) -> list:
    """``titan._meta.list_mods`` provider."""
    from titan._meta import ModInfo

    return [
        ModInfo(
            mod.key,
            mod.title,
            mod.kind,
            mod.played,
            {
                name: getattr(mod, name)
                for name in _PATH_FIELDS
                if getattr(mod, name) is not None
            },
            dict(mod.problems),
        )
        for mod in configured_u7_mods(config, game_id)
    ]


def find_u7_mod(mods: list[U7Mod], key: str) -> U7Mod | None:
    """The mod ``--mod KEY`` means: an exact key, else a case-insensitive one."""
    exact = next((mod for mod in mods if mod.key == key), None)
    return exact or next(
        (mod for mod in mods if mod.key.casefold() == key.casefold()), None
    )
