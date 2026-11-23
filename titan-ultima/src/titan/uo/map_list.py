"""The maps an Ultima Online flavor (client) has (``titan._meta.list_maps`` provider).

Each facet the client ships (a ``staidxN.mul``, as ``map-export`` finds them) is a
map. The Maps page uses ``map-export``: the whole facet as a radar map, one pixel
per tile. ``map-render`` (an isometric view around a centre cell) stays a command.
"""

from __future__ import annotations

__all__ = ["FACET_NAMES", "MAP_COMMAND", "MAP_OPTIONS", "list_maps"]

import re

from titan._meta import Flavor, MapInfo, configured_install, flavor_config

MAP_COMMAND = ("uo", "map-export")
MAP_OPTIONS = ("resolution", "no_statics", "patches", "heightmap")
FACET_NAMES = {
    0: "Felucca",
    1: "Trammel",
    2: "Ilshenar",
    3: "Malas",
    4: "Tokuno",
    5: "Ter Mur",
}
"""The client's facet numbers, as the server (``Map.cs``) names them."""

_STAIDX = re.compile(r"^staidx(\d+)\.mul$", re.IGNORECASE)


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """Every facet with a ``staidxN.mul`` in the flavor's client folder."""
    install = configured_install("uo", flavor_config(flavor, config))
    client = install.root if install else None
    if client is None or not client.is_dir():
        return []
    try:
        facets = sorted(
            int(match[1])
            for child in client.iterdir()
            if (match := _STAIDX.match(child.name))
        )
    except OSError:
        return []
    return [
        MapInfo(
            f"facet:{facet}",
            FACET_NAMES.get(facet, f"Facet {facet}"),
            {"facet": str(facet)},
        )
        for facet in facets
    ]
