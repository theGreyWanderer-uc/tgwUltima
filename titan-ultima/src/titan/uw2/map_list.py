"""The maps an Ultima Underworld II flavor has (``titan._meta.list_maps`` provider).

``DATA/LEV.ARK`` holds 80 level slots; the populated ones are the game's levels,
named by :func:`titan.uw2.level.level_name_for_slot`. ``map-render --slots N``
renders one.
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps"]

from titan._meta import Flavor, MapInfo, configured_install, flavor_config

MAP_COMMAND = ("uw2", "map-render")
MAP_OPTIONS = ("resolution",)
LEVEL_SLOTS = 80


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """Every populated LEV.ARK slot in the flavor's install, with its level name."""
    from titan.uw2.ark import ArkArchive
    from titan.uw2.level import level_name_for_slot, world_name_for_slot

    install = configured_install("uw2", flavor_config(flavor, config))
    levels = install.resources.get("levels") if install else None
    if levels is None or not levels.is_file():
        return []
    try:
        archive = ArkArchive.from_file(levels)
    except (OSError, ValueError):
        return []
    maps = []
    for slot in range(LEVEL_SLOTS):
        if not archive.is_available(slot):
            continue
        world = world_name_for_slot(slot)
        maps.append(
            MapInfo(
                f"slot:{slot}",
                level_name_for_slot(slot) or f"Level slot {slot}",
                {"slots": str(slot)},
                (world,) if world else (),
            )
        )
    return maps
