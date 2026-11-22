"""The maps an Ultima VII flavor has (``titan._meta.list_maps`` provider).

Map 0 is the main world: ``U7MAP``/``U7CHUNKS``/``U7IFIXnn`` at the root of a map
folder. Exult adds maps as ``mapNN`` sub-folders (``NN`` in hex) of the same root.
The base game's maps live in its STATIC; a mod or Exult custom game can bring
its own in its patch (or STATIC) folder. ``map-render --mod`` finds them there
(:func:`mod_map_root`), so a map only needs its number.
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps", "mod_map_root"]

import re
from pathlib import Path
from typing import Optional

from titan._meta import Flavor, MapInfo, configured_install, flavor_config, list_mods

MAP_COMMAND = ("u7", "map-render")
MAP_OPTIONS = ("full", "resolution", "superchunk", "view", "grid", "max_lift")
"""The options worth showing first. With no area chosen, the full world renders at 25%."""

_MAP_DIR = re.compile(r"^map([0-9a-f]{2})$", re.IGNORECASE)
_MAP_FILE = re.compile(r"^(u7map|u7chunks|u7ifix[0-9a-f]{2})$", re.IGNORECASE)


def _files(folder: Path) -> list[str]:
    try:
        return [child.name for child in folder.iterdir() if child.is_file()]
    except OSError:
        return []


def _has_map(folder: Path) -> bool:
    return any(_MAP_FILE.match(name) for name in _files(folder))


def _map_dirs(root: Path) -> dict[int, Path]:
    try:
        children = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return {}
    found = {}
    for child in children:
        match = _MAP_DIR.match(child.name)
        if match and _has_map(child):
            found[int(match[1], 16)] = child
    return found


def _numbers(root: Path) -> set[int]:
    """The map numbers *root* holds: 0 for its own map files, N for ``mapNN``."""
    found = {number for number in _map_dirs(root) if number}
    return found | {0} if _has_map(root) else found


def _maps_in(root: Path, note: str) -> dict[int, MapInfo]:
    notes = (note,) if note else ()
    return {
        number: MapInfo(
            "0" if number == 0 else f"{number:02x}",
            "Main world" if number == 0 else f"Map {number:02x}",
            {"map_num": str(number)},
            notes,
        )
        for number in sorted(_numbers(root))
    }


def mod_map_roots(mod) -> list[Path]:
    """Where a mod (a ``titan.u7.mods.U7Mod`` or ``ModInfo``) keeps maps, patch
    first, as Exult reads it."""
    paths = getattr(mod, "paths", None)
    if paths is not None:  # ModInfo: what was found, by key
        roots = (paths.get("patch"), paths.get("static"))
    else:  # U7Mod
        roots = (mod.patch, mod.static)
    return [Path(root) for root in roots if root is not None]


def mod_map_root(mod, map_num: int) -> Optional[Path]:
    """The folder ``map-render --mod`` reads map *map_num* from: the mod's own
    folder holding it, or ``None`` (the base game's)."""
    return next(
        (root for root in mod_map_roots(mod) if map_num in _numbers(root)), None
    )


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """The flavor's maps: the base game's, with a mod's own maps in their place."""
    install = configured_install(flavor.game_id, flavor_config(flavor, config))
    static: Optional[Path] = install.resources.get("static") if install else None
    maps = _maps_in(static, "") if static is not None else {}
    if flavor.kind in ("mod", "exult-game"):
        key = flavor.args.get("mod", "")
        mod = next((m for m in list_mods(flavor.game_id, config) if m.key == key), None)
        if mod is not None:
            note = (
                "From this Exult game"
                if flavor.kind == "exult-game"
                else "From this mod"
            )
            for root in reversed(
                mod_map_roots(mod)
            ):  # patch last: it wins, as in Exult
                maps.update(_maps_in(root, note))
    return [maps[number] for number in sorted(maps)]
