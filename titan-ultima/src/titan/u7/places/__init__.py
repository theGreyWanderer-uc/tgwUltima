"""Named places on Ultima VII maps: buildings, dungeons, areas and towns.

The finders read the player's own game files; names and town outlines come
from the bundled place data. ``build_places_document`` does both and returns
the document ``titan u7 places-export`` writes.
"""

from .buildings import BuildingFinds, find_buildings
from .data import (
    PlaceDataError,
    available_games,
    compact_place_data,
    dump_place_data,
    load_place_data,
)
from .dungeons import DungeonFinds, find_dungeons
from .export import assemble_document, build_places_document, write_places_document
from .scan import GAME_IDS, MapScan

__all__ = [
    "GAME_IDS",
    "BuildingFinds",
    "DungeonFinds",
    "MapScan",
    "PlaceDataError",
    "assemble_document",
    "available_games",
    "build_places_document",
    "compact_place_data",
    "dump_place_data",
    "find_buildings",
    "find_dungeons",
    "load_place_data",
    "write_places_document",
]
