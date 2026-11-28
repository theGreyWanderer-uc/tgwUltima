"""The maps an Ultima VII flavor has (``titan._meta.list_maps`` provider).

Map 0 is the main world: ``U7MAP``/``U7CHUNKS``/``U7IFIXnn`` at the root of a map
folder. Exult adds maps as ``mapNN`` sub-folders (``NN`` in hex) of the same root.
The base game's maps live in its STATIC; a mod or Exult custom game can bring
its own in its patch (or STATIC) folder. ``map-render --mod`` finds them there
(:func:`mod_map_root`), so a map only needs its number.

Exult records nothing that marks a map as a mod's, so a mod's map is compared with
the base game's map of the same number (:func:`mod_map_note`): the same layout
(``U7MAP``), or one differing in under half its superchunks, means the base map,
edited by the mod's layout, object files (``U7IFIXnn``) and terrain (the shared
``U7CHUNKS``); more replaces it; a number the base game lacks is a new map.
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps", "mod_map_note", "mod_map_root"]

import re
from pathlib import Path
from typing import Optional

from titan._meta import Flavor, MapInfo, configured_install, flavor_config, list_mods

MAP_COMMAND = ("u7", "map-render")
MAP_OPTIONS = ("full", "view", "grid", "max_lift")
"""The options worth showing first; ``full``'s resolution and area options come with it
(``option_groups``/``option_alternatives``). With no area chosen, the full world renders at 25%."""

_GAME_TITLES = {"u7bg": "The Black Gate", "u7si": "Serpent Isle"}
_IFIX = re.compile(r"^u7ifix[0-9a-f]{2}$", re.IGNORECASE)
_EXULT_CHUNKS = b"\xff\xff\xff\xffexlt\x00\x00"  # Exult's 3-byte-tile U7CHUNKS

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


def _map_info(number: int, notes: tuple[str, ...] = ()) -> MapInfo:
    return MapInfo(
        "0" if number == 0 else f"{number:02x}",
        "Main world" if number == 0 else f"Map {number:02x}",
        {"map_num": str(number)},
        notes,
    )


def _maps_in(root: Path, note: str) -> dict[int, MapInfo]:
    notes = (note,) if note else ()
    return {number: _map_info(number, notes) for number in sorted(_numbers(root))}


def _find(folder: Path, name: str) -> Optional[Path]:
    """*name* in *folder*, any case (Exult writes lower case, DOS upper)."""
    lower = name.lower()
    return next((folder / f for f in _files(folder) if f.lower() == lower), None)


def _map_folder(root: Path, number: int) -> Path:
    if number == 0:
        return root
    return _map_dirs(root).get(number, root / f"map{number:02x}")


def _layout(roots: list[Path], number: int) -> Optional[bytes]:
    """Map *number*'s ``U7MAP`` from the first of *roots* that has one."""
    for root in roots:
        found = _find(_map_folder(root, number), "U7MAP")
        if found is not None:
            return found.read_bytes()
    return None


def _ifix_count(roots: list[Path], number: int) -> int:
    """Superchunks whose objects (``U7IFIXnn``) *roots* bring for map *number*."""
    return len(
        {
            name.lower()
            for root in roots
            for name in _files(_map_folder(root, number))
            if _IFIX.match(name)
        }
    )


def _terrain(path: Path):
    """``U7CHUNKS`` as an ``(n, 256, 2)`` array of (shape, frame): the original
    2-byte tiles or Exult's 3-byte ``exlt`` format."""
    import numpy as np

    data = path.read_bytes()
    if data[: len(_EXULT_CHUNKS)] == _EXULT_CHUNKS:
        raw = np.frombuffer(data[len(_EXULT_CHUNKS) :], dtype=np.uint8)
        raw = raw[: len(raw) // 768 * 768].reshape(-1, 256, 3).astype(np.int32)
        return np.stack((raw[..., 0] | raw[..., 1] << 8, raw[..., 2]), axis=-1)
    tiles = np.frombuffer(data[: len(data) // 512 * 512], dtype="<u2").reshape(-1, 256)
    tiles = tiles.astype(np.int32)
    return np.stack((tiles & 0x3FF, (tiles >> 10) & 0x1F), axis=-1)


def _terrain_changes(mod_roots: list[Path], static: Path, layout: bytes) -> int:
    """Terrain chunks map *layout* uses that the mod's ``U7CHUNKS`` draws differently."""
    import numpy as np

    mod_file = next((f for r in mod_roots if (f := _find(r, "U7CHUNKS"))), None)
    base_file = _find(static, "U7CHUNKS")
    if mod_file is None or base_file is None:
        return 0
    base, mod = _terrain(base_file), _terrain(mod_file)
    count = min(len(base), len(mod))
    changed = np.any(base[:count] != mod[:count], axis=(1, 2))
    used = np.unique(np.frombuffer(layout[: len(layout) // 2 * 2], dtype="<u2"))
    return int(changed[used[used < count]].sum())


def _layout_changes(base: bytes, mod: bytes) -> int:
    """Superchunks (256 chunk slots each in ``U7MAP``) whose layout differs."""
    import numpy as np

    size = min(len(base), len(mod)) // 512 * 512
    a = np.frombuffer(base[:size], dtype="<u2").reshape(-1, 256)
    b = np.frombuffer(mod[:size], dtype="<u2").reshape(-1, 256)
    return int(np.any(a != b, axis=1).sum()) + abs(len(base) - len(mod)) // 512


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def mod_map_note(
    mod_roots: list[Path], static: Optional[Path], number: int, game_id: str
) -> str:
    """What a mod does to map *number*: edits the base game's map (with counts),
    replaces it (over half its superchunks laid out differently), or adds a new map."""
    base_name = _GAME_TITLES.get(game_id, "The base game") + (
        "" if number == 0 else f"'s map {number:02x}"
    )
    try:
        base_layout = _layout([static], number) if static is not None else None
        if base_layout is None:
            return "New map from this mod"
        mod_layout = _layout(mod_roots, number)
        layout = _layout_changes(base_layout, mod_layout) if mod_layout else 0
        if layout > len(base_layout) // 1024:  # over half its superchunks
            return f"Replaces {base_name}" + ("'s world" if number == 0 else "")
        objects = _ifix_count(mod_roots, number)
        terrain = _terrain_changes(mod_roots, static, base_layout)
    except (OSError, ValueError):
        return "From this mod"
    changes = [
        _plural(layout, "superchunk") + " of layout" if layout else "",
        _plural(objects, "superchunk") + " of objects" if objects else "",
        _plural(terrain, "terrain chunk") if terrain else "",
    ]
    changes = [c for c in changes if c]
    if not changes:
        return f"{base_name}, unchanged by this mod"
    return f"{base_name}, edited by this mod: " + ", ".join(changes)


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
        if mod is not None and flavor.kind == "exult-game":
            # its own STATIC: every map is the game's own
            for root in reversed(
                mod_map_roots(mod)
            ):  # patch last: it wins, as in Exult
                maps.update(_maps_in(root, "From this Exult game"))
        elif mod is not None:
            roots = mod_map_roots(mod)
            for number in sorted(set().union(*(_numbers(root) for root in roots))):
                note = mod_map_note(roots, static, number, flavor.game_id)
                maps[number] = _map_info(number, (note,))
    return [maps[number] for number in sorted(maps)]
