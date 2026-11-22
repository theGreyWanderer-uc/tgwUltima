"""Discover Martian Dreams installs and inventory resources used by Titan."""

from __future__ import annotations

from pathlib import Path

from titan._meta import Installation
from titan.md.game_profile import resolve_martian_directory
from titan._stores import guess_roots

MD_RESOURCE_NAMES = {
    "palette": "MDPAL",
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
    "lzobjblk": "LZOBJBLK",
    "lzdngblk": "LZDNGBLK",
    "talk": "TALK.LZC",
    "look": "LOOK.LZC",
    "text": "MDTEXT.LZC",
    "fonts": "FONTS.LZC",
    "faces": "MDFACES.LZC",
    "schedule": "SCHEDULE",
    "music": "MUSIC.LZC",
    "savegame": "SAVEGAME",
    "objlist": "SAVEGAME/OBJLIST",
}
"""Martian Dreams data paths relative to MARTIAN; launcher files are excluded."""

MD_PATH_KINDS = {
    **{key: "install-file" for key in MD_RESOURCE_NAMES},
    "savegame": "save-dir",
    "objlist": "save",
}
"""``[md.paths]`` key -> kind (see :func:`titan._meta.path_kind`)."""


def martian_install_candidates(config: dict) -> list[Path]:
    """Search configured Martian Dreams data before GOG, Heroic and manual installs."""
    candidates = []
    base = config.get("md", {}).get("game", {}).get("base")
    if base:
        candidates.append(Path(base).expanduser())
    roots = guess_roots(
        "Program Files (x86)/GOG Galaxy/Games", "GOG Games", "Ultima", ""
    )
    for root in roots:
        candidates.extend(root / name for name in ("Martian Dreams", "MARTIAN"))
        try:
            candidates.extend(
                child
                for child in sorted(root.iterdir())
                if "martian" in child.name.casefold() and child.is_dir()
            )
        except OSError:
            continue
    return list(dict.fromkeys(candidates))


def inspect_martian_install(candidate: Path) -> Path | None:
    """Accept MARTIAN or its parent when MD palette, terrain and map files exist."""
    try:
        root = resolve_martian_directory(candidate).absolute()
        if all((root / name).is_file() for name in ("CHUNKS", "MAPTILES.VGA")) and any(
            (root / name).is_file() for name in ("MAP", "LZMAP")
        ):
            return root
    except (OSError, ValueError):
        pass
    return None


def martian_resource_paths(root: Path) -> dict[str, Path]:
    """Inventory existing Martian Dreams resources, including optional DOS save data."""
    return {
        key: root / name
        for key, name in MD_RESOURCE_NAMES.items()
        if ((root / name).is_dir() if key == "savegame" else (root / name).is_file())
    }


def martian_installation(root: Path, base: Path | None = None) -> Installation:
    """The install whose data is in MARTIAN folder *root*, configured from *base*.

    *base* may be MARTIAN's parent (as a user's existing setting can be); paths
    in the config are then relative to it.
    """
    return Installation("md", base or root, martian_resource_paths(root))


def install_candidates(config: dict) -> list[Path]:
    """Install protocol (see :func:`titan._meta.install_candidates`)."""
    return martian_install_candidates(config)


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: the Martian Dreams install at *path* (MARTIAN or its parent)."""
    root = inspect_martian_install(path)
    return [martian_installation(root)] if root is not None else []


def install_config(install: Installation) -> dict:
    """Install protocol: ``[md.game]`` base and ``[md.paths]`` relative to it."""
    return {
        "game": {"base": install.root.as_posix()},
        "paths": {
            key: path.relative_to(install.root).as_posix()
            for key, path in install.resources.items()
        },
    }


def martian_setup_lines(root: Path, base: Path) -> list[str]:
    """Render ``[md.game]`` and ``[md.paths]``; *base* may be MARTIAN's parent."""
    from titan._setup_config import section_lines

    return section_lines({"md": install_config(martian_installation(root, base))})
