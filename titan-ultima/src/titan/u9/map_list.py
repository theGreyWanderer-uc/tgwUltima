"""The maps an Ultima IX flavor has (``titan._meta.list_maps`` provider).

Each region is a ``static/terrain.N`` height map, with its ``fixed.N`` objects.
"""

from __future__ import annotations

__all__ = ["MAP_COMMAND", "MAP_OPTIONS", "list_maps"]

from titan._meta import Flavor, MapInfo, configured_install, flavor_config

MAP_COMMAND = ("u9", "map-render")
MAP_OPTIONS = ("resolution", "hillshade", "water", "objects")


def list_maps(flavor: Flavor, config: dict) -> list[MapInfo]:
    """Every region with a terrain file in the flavor's STATIC folder."""
    from titan.u9.map_atlas import U9MapAtlasError, discover_region_files

    install = configured_install("u9", flavor_config(flavor, config))
    static = install.resources.get("static") if install else None
    if static is None or not static.is_dir():
        return []
    try:
        regions = discover_region_files(static)
    except (OSError, U9MapAtlasError):
        return []
    maps = []
    for region in regions:
        args = {"terrain": str(region.terrain_path)}
        if region.fixed_path is not None:
            args["fixed"] = str(region.fixed_path)
        maps.append(
            MapInfo(f"region:{region.region_id}", f"Region {region.region_id}", args)
        )
    return maps
