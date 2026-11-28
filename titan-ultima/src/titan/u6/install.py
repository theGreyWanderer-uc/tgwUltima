"""Discover Ultima VI installs and inventory the game's data resources."""

from __future__ import annotations

import re
from pathlib import Path

from titan._meta import Installation
from titan._stores import guess_roots

U6_RESOURCE_NAMES = {
    "palette": "U6PAL",
    "map": "MAP",
    "lzmap": "LZMAP",
    "chunks": "CHUNKS",
    "maptiles": "MAPTILES.VGA",
    "objtiles": "OBJTILES.VGA",
    "tileindx": "TILEINDX.VGA",
    "masktype": "MASKTYPE.VGA",
    "tileflag": "TILEFLAG",
    "basetile": "BASETILE",
    "animdata": "ANIMDATA",
    "animmask": "ANIMMASK.VGA",
    "lzobjblk": "LZOBJBLK",
    "lzdngblk": "LZDNGBLK",
    "converse_a": "CONVERSE.A",
    "converse_b": "CONVERSE.B",
    "look": "LOOK.LZD",
    "books": "BOOK.DAT",
    "font": "U6.CH",
    "portrait_a": "PORTRAIT.A",
    "portrait_b": "PORTRAIT.B",
    "portrait_z": "PORTRAIT.Z",
    "schedule": "SCHEDULE",
    "palettes": "PALETTES.INT",
    "convert_palette": "CONVERT.PAL",
    "savegame": "SAVEGAME",
    "objlist": "SAVEGAME/OBJLIST",
}
"""Ultima VI data paths relative to the game directory, including optional saves."""

U6_PATH_KINDS = {
    **{key: "install-file" for key in U6_RESOURCE_NAMES},
    "savegame": "save-dir",
    "objlist": "save",
}
"""``[u6.paths]`` key -> kind (see :func:`titan._meta.path_kind`)."""


def u6_install_candidates(config: dict) -> list[Path]:
    """Search configured Ultima VI data before GOG, Heroic and manual installs."""
    candidates = []
    base = config.get("u6", {}).get("game", {}).get("base")
    if base:
        candidates.append(Path(base).expanduser())
    roots = guess_roots(
        "Program Files (x86)/GOG Galaxy/Games", "GOG Games", "Ultima", ""
    )
    for root in roots:
        candidates.extend(
            root / name
            for name in (
                "Ultima 6",
                "Ultima VI",
                "Ultima6",
                "UltimaVI",
                "Ultima VI - The False Prophet",
            )
        )
        try:
            candidates.extend(
                child
                for child in sorted(root.iterdir())
                if child.is_dir()
                and (
                    re.search(
                        r"ultima[\s_-]*(?:6|vi)(?![a-z0-9])", child.name.casefold()
                    )
                    or "ultima" in child.name.casefold()
                    and "false prophet" in child.name.casefold()
                )
            )
        except OSError:
            continue
    return list(dict.fromkeys(candidates))


def inspect_u6_install(candidate: Path) -> Path | None:
    """Recognize Ultima VI by its own palette plus the terrain and map files."""
    root = candidate.expanduser().absolute()
    try:
        if all(
            (root / name).is_file()
            for name in ("U6PAL", "CHUNKS", "MAPTILES.VGA", "MAP")
        ):
            return root
    except OSError:
        pass
    return None


def u6_resource_paths(root: Path) -> dict[str, Path]:
    """Inventory existing Ultima VI resources, including optional DOS save data."""
    return {
        key: root / name
        for key, name in U6_RESOURCE_NAMES.items()
        if ((root / name).is_dir() if key == "savegame" else (root / name).is_file())
    }


def install_candidates(config: dict) -> list[Path]:
    """Install protocol (see :func:`titan._meta.install_candidates`)."""
    return u6_install_candidates(config)


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: the Ultima VI install at *path*, if it is one."""
    root = inspect_u6_install(path)
    if root is None:
        return []
    return [Installation("u6", root, u6_resource_paths(root))]


def install_config(install: Installation) -> dict:
    """Install protocol: ``[u6.game]`` base and ``[u6.paths]`` relative to it."""
    return {
        "game": {"base": install.root.as_posix()},
        "paths": {
            key: path.relative_to(install.root).as_posix()
            for key, path in install.resources.items()
        },
    }


def u6_setup_lines(root: Path) -> list[str]:
    """Render ``[u6.game]`` and ``[u6.paths]`` for a new ``titan.toml``."""
    from titan._setup_config import section_lines

    return section_lines({"u6": install_config(discover_installs(root)[0])})
