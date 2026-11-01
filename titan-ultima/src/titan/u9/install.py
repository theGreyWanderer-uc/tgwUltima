"""Bounded Ultima IX installation discovery and configured resource paths."""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from titan import _config
from titan.u9.flx_archive import (
    COUNT_OFFSET,
    DIR_ENTRY_SIZE,
    DIR_OFFSET,
    FORMAT_VERSION,
    MAX_ENTRIES,
    VERSION_OFFSET,
)

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
                raise ValueError("truncated FLX header")
            version = struct.unpack_from("<I", header, VERSION_OFFSET)[0]
            count = struct.unpack_from("<I", header, COUNT_OFFSET)[0]
            if version != FORMAT_VERSION:
                raise ValueError("not a U9 FLX archive")
            directory_end = DIR_OFFSET + count * DIR_ENTRY_SIZE
            if not 0 < count <= MAX_ENTRIES or directory_end > size:
                raise ValueError("invalid FLX directory size")
            used = 0
            for offset, length in struct.iter_unpack(
                "<II", file.read(count * DIR_ENTRY_SIZE)
            ):
                if not offset or not length:
                    continue
                if offset < directory_end or offset + length > size:
                    raise ValueError("FLX entry lies outside its payload")
                used += 1
            if not used:
                raise ValueError("FLX archive has no populated entries")
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
    """List configured paths, then Galaxy, GOG, drive-root and Heroic installs."""
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


def configured_u9_path(key: str) -> Path | None:
    """Resolve a U9 config path relative to its game base, retaining file case."""
    section = _config.get_config().get("u9", {})
    base = section.get("game", {}).get("base")
    value = base if key == "base" else section.get("paths", {}).get(key)
    path = _config.resolve_config_path(value, base if key != "base" else None)
    if path is None and key in {"static", "runtime", "sound", "savegame"} and base:
        path = _config.resolve_config_path(key, base)
    if path is None and key in U9_FILE_PATHS:
        directory, filename = U9_FILE_PATHS[key]
        owner = configured_u9_path(directory)
        if owner is not None:
            path = owner / filename
    return existing_u9_path(path) if path is not None else None
