"""One read of a U7 map, shared by the building and dungeon finders."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from titan.u7.install import u7_static_and_palette
from titan.u7.map import U7MapObject, U7MapRenderer
from titan.u7.map_inventory import _ireg_entries
from titan.u7.usecode import U7UsecodeFile
from titan.u7.world import (
    WorldQueryParams,
    load_ireg_context,
    load_query_metadata,
    resolve_world_sources,
)

from .geometry import NUM_SUPERCHUNKS, TILES_PER_CHUNK, WORLD_TILES
from .npcs import load_npcs

if TYPE_CHECKING:
    from titan._meta import Installation

GAME_IDS = {"bg": "u7bg", "si": "u7si"}


@dataclass
class MapScan:
    """Everything the finders read from the game files, loaded once.

    ``fixed`` holds the IFIX objects in superchunk order and ``ireg`` the
    starting world's movable objects (doors, signs), or None when skipped.
    """

    game: str
    map_num: int
    static_dir: str
    palette_path: str | None
    params: WorldQueryParams
    base: Path
    tfa: Any
    names: Any
    shape_count: int
    renderer: U7MapRenderer
    usecode: U7UsecodeFile | None
    fixed: list[U7MapObject]
    ireg: list[U7MapObject] | None
    npcs: list[dict]
    warnings: list[str] = field(default_factory=list)

    @property
    def game_id(self) -> str:
        return GAME_IDS[self.game]

    def shape_name(self, shape: int) -> str:
        return ((self.names.get(shape) if self.names else "") or "").strip()

    def template_objects(self) -> Iterator[U7MapObject]:
        """Object shapes (>= 150) set into the chunk templates, at lift 0.

        Most house walls are these, not IFIX objects.
        """
        terrain_map, terrains = self.renderer.terrain_map, self.renderer.terrains
        per_template: dict[int, list] = {}
        for cx in range(WORLD_TILES // TILES_PER_CHUNK):
            for cy in range(WORLD_TILES // TILES_PER_CHUNK):
                template = terrain_map[cx][cy]
                if template not in per_template:
                    tiles = terrains[template] if template < len(terrains) else []
                    per_template[template] = [
                        (i % TILES_PER_CHUNK, i // TILES_PER_CHUNK, shape, frame)
                        for i, (shape, frame) in enumerate(tiles)
                        if shape >= 150
                    ]
                for lx, ly, shape, frame in per_template[template]:
                    yield U7MapObject(
                        tx=cx * TILES_PER_CHUNK + lx,
                        ty=cy * TILES_PER_CHUNK + ly,
                        tz=0,
                        shape=shape,
                        frame=frame,
                    )

    @classmethod
    def load(
        cls,
        static_dir: str | None = None,
        game: str = "bg",
        map_num: int = 0,
        *,
        read_ireg: bool = True,
        install: Installation | None = None,
    ) -> MapScan:
        """Read a map from STATIC, by default *install*'s (``titan._meta.configured_install``).

        ``palette_path`` is *install*'s PALETTES.FLX, if it has one.
        """
        if game not in GAME_IDS:
            raise ValueError(
                f"unknown game {game!r}; expected one of {sorted(GAME_IDS)}"
            )
        configured, palette_path = u7_static_and_palette(install)
        static_dir = static_dir or configured
        if not static_dir or not Path(static_dir).is_dir():
            raise FileNotFoundError(f"STATIC directory not found: {static_dir}")

        bundle = install.resources.get("exult_flx") if install is not None else None
        params = WorldQueryParams(
            static_dir=static_dir,
            game=game,
            map_num=map_num,
            exult_flx_path=str(bundle) if bundle else None,
        )
        base, patch = resolve_world_sources(params)
        tfa, names, _frames, count = load_query_metadata(params)
        renderer = U7MapRenderer(
            str(base),
            map_num=map_num,
            patch_dir=str(patch) if patch else None,
            game=game,
        )
        usecode_path = next(
            (p for p in Path(base).iterdir() if p.name.upper() == "USECODE"), None
        )
        usecode = U7UsecodeFile.from_file(str(usecode_path)) if usecode_path else None
        fixed = [
            obj
            for sc in range(NUM_SUPERCHUNKS)
            for obj in renderer._fixed_objects_for_superchunk(sc)
        ]
        warnings: list[str] = []
        ireg = None
        if read_ireg:
            context = load_ireg_context(params, tfa)
            entries = _ireg_entries(base, map_num, None, None, {}, warnings)
            ireg = [
                obj
                for sc, (label, data) in entries.items()
                for obj in U7MapRenderer.parse_ireg_deep(
                    label, sc, tfa, data=data, context=context
                )
            ]
        return cls(
            game=game,
            map_num=map_num,
            static_dir=str(static_dir),
            palette_path=palette_path,
            params=params,
            base=Path(base),
            tfa=tfa,
            names=names,
            shape_count=count,
            renderer=renderer,
            usecode=usecode,
            fixed=fixed,
            ireg=ireg,
            npcs=load_npcs(base, game, map_num),
            warnings=warnings,
        )
