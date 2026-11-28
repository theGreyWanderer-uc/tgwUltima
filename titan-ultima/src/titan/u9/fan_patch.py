"""What a save misses of the Forgotten World patches' map changes.

The Forgotten World team's 1.19G patch adds four objects to ``runtime/nonfixed.9``
for Mariah and Jaana to come to Moonglow and Yew after their shrines, and 1.19H
lowers the floating Rune and virtue item at each shrine in ``nonfixed.9`` and
``nonfixed.22``. The game loads a map's objects from the save's own copy when it
has one and from ``runtime`` only when it does not, so a save that already holds
map 9 (or 22) when the patch is installed keeps the old objects. Everything else
the patches change is in ``static`` and reaches every save.

Detection reads data, never a patch's file hashes: the installed ``runtime``
maps say what the installation carries, the save's archived maps say what the
save carries. Measured against stock 1.19F and the 1.19G/1.19H maps; see
``reference/u9/patches/u9_patch_1_19H_diff.md``.
"""

from __future__ import annotations

__all__ = [
    "COMPANION_MAP",
    "COMPANION_MARKER_LINKS",
    "COMPANION_MARKER_TYPE",
    "SHRINE_OBJECTS",
    "FanPatchState",
    "ShrineObject",
    "companion_markers",
    "installed_state",
    "save_state",
]

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from titan.u9.nonfixed import U9Nonfixed, U9NonfixedError

COMPANION_MAP = 9
# The two highway-point markers the companions' activities walk to (map 9 links
# 12460 and 12462: activity operands 0x930AC and 0x930AE). Trigger objects 7762
# and 7763 come with them; the markers are the cheaper test and always pair.
COMPANION_MARKER_TYPE = 1134
COMPANION_MARKER_LINKS = (12460, 12462)


@dataclass(frozen=True)
class ShrineObject:
    """One Rune or virtue item 1.19H lowered, at its shrine."""

    shrine: str
    map_number: int
    type_index: int
    world_x: int
    world_y: int
    stock_z: int
    patched_z: int


# Type, x and y identify the shrine copy; most of these types appear elsewhere on
# the map too (map 9 holds six Daggers of Valor), and only the shrine copy moved.
SHRINE_OBJECTS: tuple[ShrineObject, ...] = (
    ShrineObject("Compassion", 9, 2940, 77368, 61027, 4365, 3405),
    ShrineObject("Compassion", 9, 4956, 77341, 60986, 4361, 3380),
    ShrineObject("Honesty", 9, 2941, 92677, 46920, 4129, 3669),
    ShrineObject("Honesty", 9, 4938, 92690, 46970, 4108, 3658),
    ShrineObject("Honor", 9, 2942, 54761, 18066, 2804, 2344),
    ShrineObject("Honor", 9, 5472, 54706, 18075, 2787, 2325),
    ShrineObject("Humility", 9, 2943, 82303, 37075, 2985, 2125),
    ShrineObject("Humility", 9, 5496, 82343, 37046, 2990, 2120),
    ShrineObject("Justice", 9, 2944, 46344, 86032, 3321, 2621),
    ShrineObject("Justice", 9, 5508, 46349, 86090, 3300, 2600),
    ShrineObject("Sacrifice", 9, 2945, 85428, 68598, 2759, 2300),
    ShrineObject("Sacrifice", 9, 5468, 85433, 68651, 2738, 2310),
    ShrineObject("Valor", 9, 2947, 33299, 26394, 2937, 2417),
    ShrineObject("Valor", 9, 5288, 33342, 26390, 2923, 2405),
    ShrineObject("Spirituality", 22, 2946, 2661, 3790, 4252, 3812),
    ShrineObject("Spirituality", 22, 5291, 2617, 3824, 4231, 3807),
)

SHRINE_MAPS = tuple(sorted({item.map_number for item in SHRINE_OBJECTS}))


def companion_markers(region: U9Nonfixed) -> frozenset[int]:
    """The companion marker links present in a map 9 region."""
    return frozenset(
        entity.link
        for chunk in region.chunks()
        for entity in chunk.entities
        if entity.type_index == COMPANION_MARKER_TYPE
        and entity.link in COMPANION_MARKER_LINKS
    )


def _shrine_heights(
    region: U9Nonfixed, map_number: int, objects: tuple[ShrineObject, ...]
) -> dict[ShrineObject, int]:
    """The z of each shrine object present in the region, keyed by the object."""
    wanted = {
        (item.type_index, item.world_x, item.world_y): item
        for item in objects
        if item.map_number == map_number
    }
    found: dict[ShrineObject, int] = {}
    for chunk in region.chunks():
        for entity in chunk.entities:
            item = wanted.get((entity.type_index, entity.world_x, entity.world_y))
            if item is not None and item not in found:
                found[item] = entity.z
    return found


@dataclass(frozen=True)
class FanPatchState:
    """What a set of maps carries of the patches' map changes.

    ``companions`` is None when map 9 is not in the set. ``shrine_heights`` holds
    the z of every listed shrine object found, for the maps in the set.
    """

    maps: frozenset[int]
    companions: bool | None
    shrine_heights: dict[ShrineObject, int]

    def stock_shrines(self) -> list[ShrineObject]:
        """Shrine objects still at their stock height: never moved, still floating."""
        return [item for item, z in self.shrine_heights.items() if z == item.stock_z]

    def lowered_shrines(self) -> list[ShrineObject]:
        """Shrine objects at the 1.19H height."""
        return [item for item, z in self.shrine_heights.items() if z == item.patched_z]


def save_state(
    regions: dict[int, U9Nonfixed],
    objects: tuple[ShrineObject, ...] = SHRINE_OBJECTS,
) -> FanPatchState:
    """What a save's archived maps carry, by map number."""
    heights: dict[ShrineObject, int] = {}
    for map_number in SHRINE_MAPS:
        region = regions.get(map_number)
        if region is not None:
            heights.update(_shrine_heights(region, map_number, objects))
    companion_region = regions.get(COMPANION_MAP)
    companions = (
        None
        if companion_region is None
        else companion_markers(companion_region) == frozenset(COMPANION_MARKER_LINKS)
    )
    return FanPatchState(frozenset(regions), companions, heights)


def _find_map(runtime: Path, map_number: int) -> Path | None:
    name = f"nonfixed.{map_number}"
    try:
        for entry in os.scandir(runtime):
            if entry.is_file() and entry.name.casefold() == name:
                return Path(entry.path)
    except OSError:
        return None
    return None


@lru_cache(maxsize=8)
def _installed_state_cached(
    runtime: str,
    stamps: tuple[tuple[int, int, int], ...],
    objects: tuple[ShrineObject, ...],
) -> FanPatchState:
    regions: dict[int, U9Nonfixed] = {}
    for map_number, _size, _mtime in stamps:
        path = _find_map(Path(runtime), map_number)
        if path is None:
            continue
        try:
            regions[map_number] = U9Nonfixed.from_file(path)
        except (OSError, U9NonfixedError, ValueError, IndexError):
            continue
    return save_state(regions, objects)


def installed_state(
    runtime: str | Path, objects: tuple[ShrineObject, ...] = SHRINE_OBJECTS
) -> FanPatchState:
    """What the installation's ``runtime`` maps carry. Cached while the files are unchanged."""
    path = Path(runtime)
    stamps = []
    for map_number in sorted({COMPANION_MAP, *SHRINE_MAPS}):
        found = _find_map(path, map_number)
        if found is None:
            continue
        try:
            stat = found.stat()
        except OSError:
            continue
        stamps.append((map_number, stat.st_size, stat.st_mtime_ns))
    return _installed_state_cached(str(path), tuple(stamps), objects)
