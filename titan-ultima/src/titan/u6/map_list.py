"""The maps an Ultima VI flavor has (``titan._meta.list_maps`` provider).

``MAP`` holds the surface and five dungeon levels; ``map-render`` takes ``--full``
for the surface and ``--dungeon N`` (0-4) for a level. Each map sets ``full``
either way, so a form hides the area options (its alternatives).
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps"]

from titan._meta import Flavor, MapInfo, configured_install, flavor_config

MAP_COMMAND = ("u6", "map-render")
MAP_OPTIONS = ("resolution", "objects", "tick")
DUNGEON_LEVELS = 5


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """The surface and each dungeon level, when the flavor's install has its map."""
    install = configured_install("u6", flavor_config(flavor, config))
    resources = install.resources if install else {}
    if not any(resources.get(key) for key in ("map", "lzmap")):
        return []
    return [MapInfo("surface", "Surface", {"full": "true"})] + [
        MapInfo(
            f"dungeon:{level}",
            f"Dungeon level {level}",
            {"full": "false", "dungeon": str(level)},
        )
        for level in range(DUNGEON_LEVELS)
    ]
