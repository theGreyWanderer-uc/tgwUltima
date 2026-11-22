"""The maps an Ultima VIII flavor has (``titan._meta.list_maps`` provider).

``FIXED.DAT`` holds 256 map slots; the ones with items are the game's maps.
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps"]

from titan._meta import Flavor, MapInfo, configured_install, flavor_config

MAP_COMMAND = ("u8", "map-render")
MAP_OPTIONS = ("view", "grid")


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """Every map with items in the flavor's ``FIXED.DAT``."""
    from titan.u8.map_items import U8MapItems

    install = configured_install("u8", flavor_config(flavor, config))
    fixed = install.resources.get("fixed") if install else None
    if fixed is None or not fixed.is_file():
        return []
    try:
        items = U8MapItems.from_file(fixed, kind="fixed")
    except (OSError, ValueError):
        return []
    return [
        MapInfo(str(number), f"Map {number}", {"map_num": str(number)})
        for number in range(256)
        if items.get_map(number)
    ]
