"""Bounded Ultima IX installation discovery and configured resource paths."""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from titan import _config
from titan._meta import Installation
from titan.u9.flx_archive import (
    COUNT_OFFSET,
    DIR_ENTRY_SIZE,
    DIR_OFFSET,
    FORMAT_VERSION,
    MAX_ENTRIES,
    VERSION_OFFSET,
)
from titan.errors import InvalidDataError

U9_RESOURCE_NAMES = {
    "bitmap16": "bitmap16.flx",
    "bitmapc": "bitmapC.flx",
    "bitmapsh": "bitmapsh.flx",
    "sdinfo16": "sdInfo16.flx",
    "sdinfoc": "sdInfoC.flx",
    "sdinfo": "sdInfo.flx",
    "palette": "ankh.pal",
}
U9_FILE_PATHS = {
    **{key: ("static", name) for key, name in U9_RESOURCE_NAMES.items()},
    **{
        key: ("static", name)
        for key, name in {
            "sappear": "sappear.flx",
            "types": "TYPES.DAT",
            "typenames": "TYPENAME.FLX",
            "animations": "anim.flx",
            "registry": "registry.txt",
            "highway": "highway.dat",
            "dimension": "dimension.dat",
            "spaces": "spaces.flx",
            "treedat": "treedat.flx",
            "areas": "areas.flx",
            "triggers": "triggers.flx",
            "activities": "activity.flx",
            "text": "text.flx",
            "misctext": "misctext.flx",
            "text_keys": "text.dat",
            "shade": "shade.tbl",
            "shadegry": "shadegry.tbl",
            "color_cube": "rgbccube.dat",
            "yiqccube": "yiqccube.dat",
            "books": "BOOKS-EN.FLX",
        }.items()
    },
    **{
        key: ("sound", name)
        for key, name in {
            "categories": "sfxcat.flx",
            "environments": "sfxenv.flx",
            "templates": "SFXTMPL.FLX",
            "associations": "sfxassoc.flx",
            "sfx": "sfx.flx",
            "speech": "Speech.flx",
            "music": "music.flx",
        }.items()
    },
    "npcs": ("runtime", "NPC.FLX"),
    "processes": ("savegame", "processes.dat"),
}
U9_PATH_KINDS = {
    **{
        key: "save" if folder == "savegame" else "install-file"
        for key, (folder, _) in U9_FILE_PATHS.items()
    },
    # Numbered region files: static terrain/fixed, runtime nonfixed (not a save).
    "terrain": "install-file",
    "fixed": "install-file",
    "nonfixed": "install-file",
    "static": "install-dir",
    "sound": "install-dir",
    "runtime": "install-dir",
    "savegame": "save-dir",
}
"""``[u9.paths]`` key -> kind (see :func:`titan._meta.path_kind`)."""
_SKIP_DIRS = {
    "backup",
    "backups",
    "patch",
    "mods",
    "savegame",
    "saves",
    "runtime",
    "sound",
}


def existing_u9_path(path: Path) -> Path:
    """Resolve actual filename case for U9 installs copied between platforms."""
    if path.exists():
        return path.resolve()
    if path.parent == path:
        return path
    parent = existing_u9_path(path.parent)
    try:
        return next(
            (
                item
                for item in parent.iterdir()
                if item.name.casefold() == path.name.casefold()
            ),
            parent / path.name,
        )
    except OSError:
        return parent / path.name


def check_u9_resource(key: str, path: Path) -> str:
    """Validate a U9 palette or archive header and directory without loading pixels."""
    if not path.is_file():
        return "NOT FOUND"
    try:
        size = path.stat().st_size
        if key == "palette":
            from titan.u9.palette import U9Palette

            U9Palette.from_file(path)
            return "OK"
        with path.open("rb") as file:
            header = file.read(DIR_OFFSET)
            if len(header) != DIR_OFFSET:
                raise InvalidDataError("truncated FLX header")
            version = struct.unpack_from("<I", header, VERSION_OFFSET)[0]
            count = struct.unpack_from("<I", header, COUNT_OFFSET)[0]
            if version != FORMAT_VERSION:
                raise InvalidDataError("not a U9 FLX archive")
            directory_end = DIR_OFFSET + count * DIR_ENTRY_SIZE
            if not 0 < count <= MAX_ENTRIES or directory_end > size:
                raise InvalidDataError("invalid FLX directory size")
            used = 0
            for offset, length in struct.iter_unpack(
                "<II", file.read(count * DIR_ENTRY_SIZE)
            ):
                if not offset or not length:
                    continue
                if offset < directory_end or offset + length > size:
                    raise InvalidDataError("FLX entry lies outside its payload")
                used += 1
            if not used:
                raise InvalidDataError("FLX archive has no populated entries")
    except (OSError, ValueError, struct.error) as error:
        return f"INVALID: {error}"
    return "OK"


@dataclass
class U9Installation:
    """One U9 game root, its discovered paths and core resource checks."""

    root: Path
    paths: dict[str, Path]
    checks: dict[str, str]

    @property
    def valid(self) -> bool:
        return all(status == "OK" for status in self.checks.values())


def inspect_u9_install(root: Path, *, static: Path | None = None) -> U9Installation:
    """Inspect all three bitmap tiers, companion tables and the game palette."""
    root = existing_u9_path(root.expanduser().absolute())
    static = existing_u9_path(static if static is not None else root / "static")
    paths = {"static": static}
    checks = {}
    for key, filename in U9_RESOURCE_NAMES.items():
        paths[key] = existing_u9_path(static / filename)
        checks[key] = check_u9_resource(key, paths[key])
    for key, (directory, filename) in U9_FILE_PATHS.items():
        if key in U9_RESOURCE_NAMES:
            continue
        path = existing_u9_path(
            (static if directory == "static" else root / directory) / filename
        )
        if path.is_file():
            paths[key] = path
    for name in ("runtime", "sound", "savegame"):
        path = existing_u9_path(root / name)
        if path.is_dir():
            paths[name] = path
    return U9Installation(root, paths, checks)


def discover_u9_installs(
    candidate: Path, *, max_depth: int = 3
) -> list[U9Installation]:
    """Find U9 roots within three levels and 128 directories, skipping backups."""
    candidate = existing_u9_path(candidate.expanduser().absolute())
    if candidate.name.casefold() == "static":
        candidate = candidate.parent
    pending = deque([(candidate, 0)])
    found = []
    visited = 0
    while pending and visited < 128:
        directory, depth = pending.popleft()
        visited += 1
        static = existing_u9_path(directory / "static")
        if static.is_dir() and any(
            existing_u9_path(static / filename).is_file()
            for filename in U9_RESOURCE_NAMES.values()
        ):
            found.append(inspect_u9_install(directory, static=static))
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(
                directory.iterdir(), key=lambda path: path.name.casefold()
            )
        except OSError:
            continue
        for child in children:
            name = child.name.casefold()
            if (
                len(pending) + visited < 128
                and name not in _SKIP_DIRS
                and not name.endswith(("_backup", ".bak"))
                and not child.is_symlink()
                and child.is_dir()
            ):
                pending.append((child, depth + 1))
    return found


def u9_install_candidates(config: dict) -> list[Path]:
    """List configured paths, then Galaxy, GOG, drive-root, Steam and Heroic installs."""
    candidates = []
    section = config.get("u9", {})
    base = section.get("game", {}).get("base")
    if base:
        candidates.append(Path(base).expanduser())
    static = _config.resolve_config_path(section.get("paths", {}).get("static"), base)
    if static is not None:
        candidates.append(static)
    names = (
        "Ultima 9",
        "Ultima IX",
        "Ultima IX Ascension",
        "Ultima 9 - Ascension",
        "Ultima9",
    )
    launcher_roots: list[Path] = []
    for layout in (
        "Program Files (x86)/GOG Galaxy/Games",
        "GOG Games",
        "",
        "Program Files/EA Games",
        "Program Files (x86)/Origin Games",
        "Program Files (x86)/Steam/steamapps/common",
        # Steam's default folder name for a library on a second drive.
        "SteamLibrary/steamapps/common",
    ):
        launcher_roots.extend(Path(f"{drive}:/") / layout for drive in "CDEFG")
    launcher_roots += [Path.home() / "GOG Games", Path.home() / "Games/Heroic"]
    for launcher in launcher_roots:
        candidates.extend(launcher / name for name in names)
        try:
            for child in sorted(launcher.iterdir()):
                name = child.name.casefold()
                if child.is_dir() and (
                    any(
                        token in name
                        for token in ("ultima 9", "ultima9", "ultima ix", "ultimaix")
                    )
                    or "ultima" in name
                    and "ascension" in name
                ):
                    candidates.append(child)
        except OSError:
            continue
    candidates.extend(Path(f"{drive}:/Ultima/Ultima9") for drive in "CDEFG")
    return list(dict.fromkeys(candidates))


def configured_u9_path(key: str, config: dict | None = None) -> Path | None:
    """Resolve a U9 config path relative to its game base, retaining file case.

    The rule behind :func:`configured_install`; code outside the install
    module reads the configured install (``titan._meta.configured_install("u9")``).
    """
    section = (_config.get_config() if config is None else config).get("u9", {})
    base = section.get("game", {}).get("base")
    value = base if key == "base" else section.get("paths", {}).get(key)
    path = _config.resolve_config_path(value, base if key != "base" else None)
    if path is None and key in {"static", "runtime", "sound", "savegame"} and base:
        path = _config.resolve_config_path(key, base)
    if path is None and key in U9_FILE_PATHS:
        directory, filename = U9_FILE_PATHS[key]
        owner = configured_u9_path(directory, config)
        if owner is not None:
            path = owner / filename
    return existing_u9_path(path) if path is not None else None


def _relative(path: Path, root: Path) -> str:
    return (path.relative_to(root) if path.is_relative_to(root) else path).as_posix()


def as_installation(selected: U9Installation) -> Installation:
    """The :class:`~titan._meta.Installation` for a :class:`U9Installation`."""
    return Installation(
        "u9",
        selected.root,
        dict(selected.paths),
        {key: status for key, status in selected.checks.items() if status != "OK"},
    )


def install_candidates(config: dict) -> list[Path]:
    """Install protocol (see :func:`titan._meta.install_candidates`)."""
    return u9_install_candidates(config)


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: U9 roots within three levels of *path*."""
    return [as_installation(item) for item in discover_u9_installs(path)]


def configured_install(config: dict) -> Installation | None:
    """Install protocol hook: what U9 commands use by default (:func:`configured_u9_path`).

    ``resources`` hold every known or configured key that exists, with
    folders defaulting under the base and files under their folder.
    ``problems`` lists ``[u9.paths]`` entries that point at nothing
    (``"NOT FOUND"``). ``settings["base"]`` is set only when ``[u9.game] base``
    is; U9 also works from absolute ``[u9.paths]`` alone, and then ``root``
    is ``Path()`` (no base).
    """
    section = config.get("u9", {})
    declared = section.get("paths", {})
    base = configured_u9_path("base", config)
    if base is None and not declared:
        return None
    resources: dict[str, Path] = {}
    problems: dict[str, str] = {}
    for key in dict.fromkeys([*U9_PATH_KINDS, *declared]):
        path = configured_u9_path(key, config)
        if path is not None and path.exists():
            resources[key] = path
        elif key in declared:
            problems[key] = "NOT FOUND"
    settings = {"base": str(base)} if base is not None else {}
    return Installation(
        "u9", base or Path(), resources, problems, settings, frozenset(declared)
    )


def install_config(install: Installation) -> dict:
    """Install protocol: ``[u9.game]`` base and ``[u9.paths]`` relative to it."""
    return {
        "game": {"base": install.root.as_posix()},
        "paths": {
            key: _relative(path, install.root)
            for key, path in install.resources.items()
        },
    }


def u9_setup_lines(selected: U9Installation) -> list[str]:
    """Render ``[u9.game]`` and ``[u9.paths]`` for a new ``titan.toml``."""
    from titan._setup_config import section_lines

    return section_lines({"u9": install_config(as_installation(selected))})
