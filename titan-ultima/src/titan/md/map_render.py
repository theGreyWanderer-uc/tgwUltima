"""Render Martian Dreams maps with the shared U6 terrain and object decoders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from titan.md.actor import parse_martian_actors
from titan.md.game_profile import MD_PROFILE, resolve_martian_directory
from titan.md.gamestate import MD_STATE_REQUIRED_SIZE, MartianGameState
from titan.md.map_animation import build_martian_animation
from titan.md.map_placements import project_martian_placements
from titan.md.lighting import (
    apply_martian_lightmap,
    build_martian_light_field,
    martian_readied_light,
    restore_martian_lamp_posts,
)
from titan.md.palette import build_martian_palette
from titan.md.power_state import restore_martian_power_objects
from titan.md.world_state import load_martian_objlist
from titan.md.viewport import MartianViewport, resolve_martian_view_tiles
from titan.u6.map import DUNGEON_LEVELS, U6Chunks, U6Map, render_tile_grid
from titan.u6.map_objects import overlay_map_objects
from titan.u6.object import U6Object, U6WorldObjects, read_basetile
from titan.u6.palette import U6Palette
from titan.u6.tile import U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlags

__all__ = ["MartianMapRenderer"]


@dataclass
class MartianMapRenderer:
    """Loaded MD map assets; object overlays use initial or explicitly selected save data."""

    gamedir: Path
    tiles: U6Tiles
    palette: U6Palette
    chunks: U6Chunks
    world_map: U6Map
    raw_animdata: U6AnimData

    @property
    def animdata(self) -> U6AnimData:
        """Initial animation defaults when no world-state snapshot is selected."""
        return build_martian_animation(self.raw_animdata)

    @classmethod
    def from_directory(
        cls, gamedir: str | Path, *, palette: str | Path | None = None
    ) -> MartianMapRenderer:
        """Load MARTIAN directly, or find it beneath an installation's outer directory."""
        directory = resolve_martian_directory(gamedir)
        animation_bytes = (directory / "ANIMDATA").read_bytes()
        if (
            len(animation_bytes) != 194
            or int.from_bytes(animation_bytes[:2], "little") > 32
        ):
            raise ValueError(
                f"Invalid Martian Dreams ANIMDATA: {directory / 'ANIMDATA'}"
            )
        raw_anim = U6AnimData.parse(animation_bytes)
        map_path = directory / "MAP"
        map_data = (
            map_path.read_bytes()
            if map_path.is_file()
            else MD_PROFILE.read_resource(directory, "LZMAP")
        )
        return cls(
            gamedir=directory,
            tiles=U6Tiles.from_directory(directory, profile=MD_PROFILE),
            palette=U6Palette.from_file(
                Path(palette).expanduser()
                if palette
                else directory / MD_PROFILE.palette_filename
            ),
            chunks=U6Chunks.from_file(directory / "CHUNKS"),
            world_map=U6Map.parse(map_data),
            raw_animdata=raw_anim,
        )

    def render_map(
        self,
        *,
        region: tuple[int, int, int, int] | None = None,
        dungeon: int | None = None,
        tick: int = 0,
        palette_tick: int = 0,
        lighting: bool = False,
        objects: bool = False,
        actors: bool = False,
        savegame: str | Path | None = None,
        show_markers: bool = False,
        show_invisible: bool = False,
    ) -> Image.Image:
        """Render static terrain and optional objects; region units are 16-pixel world tiles."""
        if dungeon is not None and not 0 <= dungeon < DUNGEON_LEVELS:
            raise ValueError("Martian Dreams dungeon must be between 0 and 4")
        if tick < 0:
            raise ValueError("Martian Dreams animation tick must be nonnegative")
        if lighting and (
            region is None or not 1 <= region[2] <= 11 or not 1 <= region[3] <= 11
        ):
            raise ValueError(
                "Martian Dreams lighting requires --region with a crop no larger than 11x11 tiles"
            )
        palette = build_martian_palette(self.palette, palette_tick)
        world = None
        if objects or lighting:
            world = (
                U6WorldObjects.from_savegame(Path(savegame).expanduser())
                if savegame is not None
                else U6WorldObjects.from_directory(self.gamedir, profile=MD_PROFILE)
            )
        objlist = b""
        if world is not None:
            objlist = world.objlist_tail
        elif actors or savegame is not None:
            objlist = load_martian_objlist(self.gamedir, savegame)
        state = None
        if actors or savegame is not None or len(objlist) >= MD_STATE_REQUIRED_SIZE:
            state = MartianGameState.parse(objlist)
        animdata = build_martian_animation(self.raw_animdata, state)
        level = 0 if dungeon is None else dungeon + 1
        placements = list(
            (world.iter_surface() if dungeon is None else world.iter_dungeon(dungeon))
            if world
            else ()
        )
        if state is not None:
            placements = restore_martian_lamp_posts(
                restore_martian_power_objects(placements, state.power_active), state
            )
        actor_records = parse_martian_actors(objlist) if actors or lighting else []
        tileflags = (
            U6TileFlags.from_file(self.gamedir / "TILEFLAG")
            if objects or actors or lighting
            else []
        )
        basetile = (
            read_basetile(self.gamedir / "BASETILE")
            if objects or actors or lighting
            else ()
        )
        grid = (
            self.world_map.build_surface_grid(self.chunks)
            if dungeon is None
            else self.world_map.build_dungeon_grid(dungeon, self.chunks)
        )
        if region is not None:
            x, y, width, height = region
            if x < 0 or y < 0 or width <= 0 or height <= 0:
                raise ValueError(
                    "Martian Dreams region needs nonnegative x/y and positive width/height"
                )
            if x + width > grid.shape[1] or y + height > grid.shape[0]:
                raise ValueError(
                    f"Martian Dreams region exceeds the {grid.shape[1]}x{grid.shape[0]} map"
                )
        overlay_region = region or (0, 0, grid.shape[1], grid.shape[0])
        overlay_objects = project_martian_placements(
            placements if objects else (), overlay_region, 1024
        )
        overlay_actors = project_martian_placements(
            actor_records if actors else (), overlay_region, 1024
        )
        viewport = None
        if lighting and state is not None and region is not None:
            inventory = (
                [
                    obj
                    for member in state.party
                    for obj in world.actor_inventory.get(member.actor_id, ())
                ]
                if world
                else []
            )
            light_objects = placements + [
                U6Object(0, a.x, a.y, a.z, a.obj_n, a.frame_n, 0, 0)
                for a in actor_records
                if a.is_active
            ]
            field = build_martian_light_field(
                grid,
                light_objects,
                tileflags,
                basetile,
                state,
                region,
                level,
                martian_readied_light(inventory, tileflags, basetile),
            )
            viewport = MartianViewport(
                resolve_martian_view_tiles(field, tileflags),
                field,
                (region[0], region[1]),
                tileflags,
            )
            if objects:
                viewport.restore_lower_terrain(
                    overlay_objects, basetile, level, show_invisible=show_invisible
                )
        image = render_tile_grid(
            viewport.terrain if viewport else grid,
            self.tiles,
            palette,
            region=None if viewport else region,
            animdata=animdata,
            tick=tick,
        )
        if objects or actors:
            overlay_map_objects(
                image,
                overlay_objects,
                self.tiles,
                palette,
                tileflags,
                basetile,
                animdata,
                MD_PROFILE,
                origin=(region[0], region[1]) if region else (0, 0),
                level=level,
                tick=tick,
                show_markers=show_markers,
                show_invisible=show_invisible,
                actors=overlay_actors,
                player_actor_id=0 if state and state.in_dream_mode else 1,
                cell_filter=viewport.allows_cell if viewport else None,
            )
        if viewport:
            apply_martian_lightmap(image, viewport.field.levels, self.tiles, palette)
        return image
