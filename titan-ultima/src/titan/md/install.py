"""Discover Martian Dreams installs and inventory resources used by Titan."""

from __future__ import annotations

import json
from pathlib import Path

from titan.md.game_profile import resolve_martian_directory

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


def martian_install_candidates(config: dict) -> list[Path]:
    """Search configured Martian Dreams data before GOG, Heroic and manual installs."""
    candidates = []
    base = config.get("md", {}).get("game", {}).get("base")
    if base:
        candidates.append(Path(base).expanduser())
    roots = [
        Path(f"{drive}:/") / layout
        for layout in (
            "Program Files (x86)/GOG Galaxy/Games",
            "GOG Games",
            "Ultima",
            "",
        )
        for drive in "CDEFG"
    ]
    roots += [Path.home() / "GOG Games", Path.home() / "Games/Heroic"]
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


def martian_setup_lines(root: Path, base: Path) -> list[str]:
    """Render ``[md.game]`` and ``[md.paths]``; *base* may be MARTIAN's parent."""
    lines = [
        "",
        "[md.game]",
        f"base = {json.dumps(base.as_posix())}",
        "",
        "[md.paths]",
    ]
    for key, resource in martian_resource_paths(root).items():
        lines.append(f"{key} = {json.dumps(resource.relative_to(base).as_posix())}")
    return lines
