"""Shared U6-engine object compositing without game-specific object-ID fixes.

Each cell's background flag (TILEFLAG extra 0x20) selects the lower layer,
as verified in MD's original compositor; the breakthrough flag is separate.
Visit anchors from southeast to northwest, preserving record order at a shared
coordinate. Actors sit between ordinary
objects and foreground cells. Lighting masks are outside this static renderer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PIL import Image

from titan.u6.actor import U6Actor
from titan.u6.game_profile import U6GameProfile
from titan.u6.object import U6Object
from titan.u6.palette import U6Palette
from titan.u6.tile import TILE_DIM, U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlagEntry

__all__ = ["overlay_map_objects"]


def overlay_map_objects(
    image: Image.Image,
    objects: Iterable[U6Object],
    tiles: U6Tiles,
    palette: U6Palette,
    tileflags: list[U6TileFlagEntry],
    basetile: tuple[int, ...],
    animdata: U6AnimData,
    profile: U6GameProfile,
    *,
    origin: tuple[int, int] = (0, 0),
    level: int = 0,
    tick: int = 0,
    show_markers: bool = False,
    show_invisible: bool = False,
    actors: Iterable[U6Actor] = (),
    player_actor_id: int | None = None,
    cell_filter: Callable[[int, int], bool] | None = None,
) -> int:
    """Draw objects and actors in engine layer order, including footprints beyond crop edges."""
    ox, oy = origin
    draws: list[tuple[int, int, int, int, bool]] = []
    drawn = 0

    def append_footprint(
        x: int, y: int, tnum: int, *, actor: bool = False, outline: bool = False
    ) -> bool:
        if not show_markers and tnum in profile.hidden_marker_tiles:
            return False
        if not 0 <= tnum < min(tiles.num_tiles, len(tileflags)):
            raise ValueError(f"Invalid map object tile {tnum} at ({x}, {y}, {level})")
        anchor_flags = tileflags[tnum]
        visible = False
        for dx, dy, cell_tile in anchor_flags.double_size_footprint(tnum):
            px, py = (x + dx - ox) * TILE_DIM, (y + dy - oy) * TILE_DIM
            if (
                px + TILE_DIM <= 0
                or py + TILE_DIM <= 0
                or px >= image.width
                or py >= image.height
            ):
                continue
            if not 0 <= cell_tile < len(tileflags):
                raise ValueError(f"Invalid map object footprint tile {cell_tile}")
            if cell_filter is not None and not cell_filter(x + dx, y + dy):
                continue
            flags = tileflags[cell_tile]
            if flags.is_background:
                layer = 0
            elif actor:
                layer = 2
            elif flags.is_foreground:
                layer = 3
            else:
                layer = 1
            resolved = animdata.resolve_tile(cell_tile, tick)
            if not 0 <= resolved < tiles.num_tiles:
                raise ValueError(f"Invalid map animation tile {resolved}")
            draws.append((layer, px, py, resolved, outline))
            visible = True
        return visible

    for obj in sorted(objects, key=lambda obj: (-obj.y, -obj.x)):
        if (
            obj.is_on_map
            and (show_invisible or not obj.is_invisible)
            and obj.z == level
        ):
            drawn += append_footprint(obj.x, obj.y, obj.tile_num(basetile))

    for actor in sorted(actors, key=lambda actor: actor.actor_id):
        if not actor.is_active or actor.is_dead or actor.z != level:
            continue
        invisible = bool(actor.obj_flags & 2)
        if invisible and not actor.is_in_party and actor.actor_id != player_actor_id:
            continue
        drawn += append_footprint(
            actor.x, actor.y, actor.tile_num(basetile), actor=True, outline=invisible
        )

    sprites: dict[tuple[int, bool], Image.Image] = {}
    # Stable sort retains anchor traversal and per-coordinate record order.
    for _, px, py, tnum, outline in sorted(draws, key=lambda draw: draw[0]):
        key = (tnum, outline)
        if key not in sprites:
            if outline:
                outline_tile = bytes(
                    11 if pixel == 0 else 255 for pixel in tiles.get_tile(tnum)
                )
                sprites[key] = U6Tiles([outline_tile]).to_pil_image(
                    0, palette, transparent=True
                )
            else:
                sprites[key] = tiles.to_pil_image(tnum, palette, transparent=True)
        sprite = sprites[key]
        image.paste(sprite, (px, py), sprite)
    return drawn
