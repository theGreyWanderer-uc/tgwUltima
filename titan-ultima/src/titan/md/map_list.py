"""The maps a Martian Dreams flavor has (``titan._meta.list_maps`` provider).

``MAP`` holds the surface and five underground levels; ``map-render`` takes
``--full`` for the surface and ``--dungeon N`` (0-4) for a level. Each map sets
``full`` either way, so a form hides the area options (its alternatives).
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps"]

from titan._meta import Flavor, MapInfo, configured_install, flavor_config

MAP_COMMAND = ("md", "map-render")
MAP_OPTIONS = ("resolution", "objects", "actors", "lighting", "tick")
UNDERGROUND_LEVELS = 5


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """The surface and each underground level, when the flavor's install has its map."""
    install = configured_install("md", flavor_config(flavor, config))
    resources = install.resources if install else {}
    if not any(resources.get(key) for key in ("map", "lzmap")):
        return []
    return [MapInfo("surface", "Surface", {"full": "true"})] + [
        MapInfo(
            f"underground:{level}",
            f"Underground level {level}",
            {"full": "false", "dungeon": str(level)},
        )
        for level in range(UNDERGROUND_LEVELS)
    ]
