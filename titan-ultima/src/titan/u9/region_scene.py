"""Canonical Ultima IX region coordinates shared by map renderers.

Ultima IX stores terrain, fixed objects, and runtime objects in related files,
but their coordinate units are not presented the same way.  The legacy
Forgotten World editor establishes the bridge used here:

* one terrain point/cell spans 128 raw X/Y world units;
* one terrain height unit spans 4 raw Z world units;
* fixed-object and nonfixed authored positions are already expressed in those
  raw world units.

The scene keeps U9's native X/Y/Z axes.  Presentation backends may invert Y
when mapping the region into image rows or a renderer's Z axis.
"""

from __future__ import annotations

__all__ = [
    "FIXED_CHUNK_TERRAIN_POINTS",
    "REGION_CHUNK_TERRAIN_POINTS",
    "TERRAIN_HEIGHT_WORLD_Z",
    "TERRAIN_POINT_WORLD_XY",
    "U9FixedPlacement",
    "U9NonfixedPlacement",
    "U9RegionScene",
    "U9RegionSceneDiagnostics",
    "U9RegionSceneError",
    "U9TerrainCell",
    "U9WorldPosition",
]

import os
from dataclasses import dataclass

from titan.u9.fixed import CHUNK_SPAN, U9Fixed, U9FixedObject
from titan.u9.nonfixed import U9Entity, U9Nonfixed
from titan.u9.terrain import U9Terrain, U9TerrainPoint

TERRAIN_POINT_WORLD_XY = 128
TERRAIN_HEIGHT_WORLD_Z = 4
REGION_CHUNK_TERRAIN_POINTS = CHUNK_SPAN // TERRAIN_POINT_WORLD_XY
# Compatibility name retained from the fixed-only first scene implementation.
FIXED_CHUNK_TERRAIN_POINTS = REGION_CHUNK_TERRAIN_POINTS


class U9RegionSceneError(Exception):
    """Raised when region files cannot share one canonical U9 world space."""


@dataclass(frozen=True)
class U9WorldPosition:
    """One position in the raw X/Y/Z coordinate units used by U9 objects."""

    x: int
    y: int
    z: int


@dataclass(frozen=True)
class U9TerrainCell:
    """One terrain surface cell and its four raw-world-space corners."""

    x: int
    y: int
    point: U9TerrainPoint
    corners: tuple[U9WorldPosition, U9WorldPosition, U9WorldPosition, U9WorldPosition]

    @property
    def triangle_corner_indices(
        self,
    ) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        """Two triangles as NW, NE, SW, SE corner indices.

        Bit 15 alternates the diagonal.  The exact triangle winding is a
        backend concern; these tuples only describe the chosen diagonal.
        """
        if self.point.is_split:
            return (0, 1, 3), (0, 3, 2)
        return (0, 1, 2), (2, 1, 3)


@dataclass(frozen=True)
class U9FixedPlacement:
    """One fixed object positioned in the scene's raw U9 world space."""

    object: U9FixedObject
    position: U9WorldPosition

    @property
    def terrain_x(self) -> float:
        """Object X expressed in terrain-cell coordinates."""
        return self.position.x / TERRAIN_POINT_WORLD_XY

    @property
    def terrain_y(self) -> float:
        """Object Y expressed in terrain-cell coordinates."""
        return self.position.y / TERRAIN_POINT_WORLD_XY


@dataclass(frozen=True)
class U9NonfixedPlacement:
    """One nonfixed entity's authored position in raw U9 world space.

    Moving actors may have a different live position in memory. Unlinked
    allocated records are exposed explicitly because their lifecycle meaning
    remains unknown.
    """

    entity: U9Entity
    position: U9WorldPosition
    is_spatially_indexed: bool

    @property
    def terrain_x(self) -> float:
        """Authored entity X expressed in terrain-cell coordinates."""
        return self.position.x / TERRAIN_POINT_WORLD_XY

    @property
    def terrain_y(self) -> float:
        """Authored entity Y expressed in terrain-cell coordinates."""
        return self.position.y / TERRAIN_POINT_WORLD_XY


@dataclass(frozen=True)
class U9RegionSceneDiagnostics:
    """Alignment checks across terrain, fixed, and nonfixed region data."""

    fixed_objects: int
    fixed_objects_in_bounds: int
    fixed_objects_out_of_bounds: int
    fixed_chunk_position_mismatches: int
    nonfixed_indexed_entities: int
    nonfixed_unlinked_entities: int
    nonfixed_allocated_entities: int
    nonfixed_entities_in_bounds: int
    nonfixed_entities_out_of_bounds: int
    nonfixed_chunk_position_mismatches: int
    nonfixed_incomplete_chunks: int


@dataclass(frozen=True)
class U9RegionScene:
    """Terrain plus optional fixed and nonfixed data in canonical U9 space."""

    terrain: U9Terrain
    fixed: U9Fixed | None = None
    nonfixed: U9Nonfixed | None = None

    def __post_init__(self) -> None:
        if self.terrain.is_empty:
            raise U9RegionSceneError("cannot build a scene for an empty terrain slot")
        for label, region in (("fixed", self.fixed), ("nonfixed", self.nonfixed)):
            if region is None:
                continue
            expected_width = region.width * REGION_CHUNK_TERRAIN_POINTS
            expected_height = region.height * REGION_CHUNK_TERRAIN_POINTS
            if (self.terrain.width, self.terrain.height) != (
                expected_width,
                expected_height,
            ):
                raise U9RegionSceneError(
                    f"terrain/{label} region extent mismatch: "
                    f"terrain is {self.terrain.width}x{self.terrain.height} points, "
                    f"{label} is {region.width}x{region.height} chunks "
                    f"({expected_width}x{expected_height} terrain points)"
                )

    @classmethod
    def from_files(
        cls,
        terrain_path: str | os.PathLike[str],
        fixed_path: str | os.PathLike[str] | None = None,
        nonfixed_path: str | os.PathLike[str] | None = None,
    ) -> U9RegionScene:
        """Load a region scene from terrain and optional object-region files."""
        terrain = U9Terrain.from_file(terrain_path)
        fixed = U9Fixed.from_file(fixed_path) if fixed_path is not None else None
        nonfixed = (
            U9Nonfixed.from_file(nonfixed_path) if nonfixed_path is not None else None
        )
        return cls(terrain=terrain, fixed=fixed, nonfixed=nonfixed)

    @property
    def extent_x(self) -> int:
        """Full region width in raw U9 world units."""
        return self.terrain.width * TERRAIN_POINT_WORLD_XY

    @property
    def extent_y(self) -> int:
        """Full region height in raw U9 world units."""
        return self.terrain.height * TERRAIN_POINT_WORLD_XY

    def terrain_world_position(self, x: int, y: int) -> U9WorldPosition:
        """Convert a terrain point to raw U9 X/Y/Z world units."""
        point = self.terrain.point(x, y)
        return U9WorldPosition(
            x=x * TERRAIN_POINT_WORLD_XY,
            y=y * TERRAIN_POINT_WORLD_XY,
            z=point.height * TERRAIN_HEIGHT_WORLD_Z,
        )

    def terrain_cell(self, x: int, y: int) -> U9TerrainCell:
        """Return one cell; its east/south edge wraps like the legacy editor."""
        if not (0 <= x < self.terrain.width and 0 <= y < self.terrain.height):
            raise U9RegionSceneError(
                f"terrain cell ({x}, {y}) out of range for "
                f"{self.terrain.width}x{self.terrain.height} cells"
            )
        east = (x + 1) % self.terrain.width
        south = (y + 1) % self.terrain.height
        north_west = self.terrain_world_position(x, y)
        north_east_height = self.terrain.point(east, y).height
        south_west_height = self.terrain.point(x, south).height
        south_east_height = self.terrain.point(east, south).height
        corners = (
            north_west,
            U9WorldPosition(
                (x + 1) * TERRAIN_POINT_WORLD_XY,
                y * TERRAIN_POINT_WORLD_XY,
                north_east_height * TERRAIN_HEIGHT_WORLD_Z,
            ),
            U9WorldPosition(
                x * TERRAIN_POINT_WORLD_XY,
                (y + 1) * TERRAIN_POINT_WORLD_XY,
                south_west_height * TERRAIN_HEIGHT_WORLD_Z,
            ),
            U9WorldPosition(
                (x + 1) * TERRAIN_POINT_WORLD_XY,
                (y + 1) * TERRAIN_POINT_WORLD_XY,
                south_east_height * TERRAIN_HEIGHT_WORLD_Z,
            ),
        )
        return U9TerrainCell(x=x, y=y, point=self.terrain.point(x, y), corners=corners)

    def fixed_placements(self) -> tuple[U9FixedPlacement, ...]:
        """Return every fixed object in raw U9 world coordinates."""
        if self.fixed is None:
            return ()
        return tuple(
            U9FixedPlacement(
                object=obj,
                position=U9WorldPosition(obj.world_x, obj.world_y, obj.z),
            )
            for obj in self.fixed.objects()
        )

    def nonfixed_placements(
        self, *, include_unlinked: bool = False
    ) -> tuple[U9NonfixedPlacement, ...]:
        """Return authored nonfixed positions, excluding unlinked records by default."""
        if self.nonfixed is None:
            return ()
        placements: list[U9NonfixedPlacement] = []
        for chunk in self.nonfixed.chunks():
            placements.extend(
                U9NonfixedPlacement(
                    entity=entity,
                    position=U9WorldPosition(entity.world_x, entity.world_y, entity.z),
                    is_spatially_indexed=True,
                )
                for entity in chunk.entities
            )
            if include_unlinked:
                placements.extend(
                    U9NonfixedPlacement(
                        entity=entity,
                        position=U9WorldPosition(
                            entity.world_x, entity.world_y, entity.z
                        ),
                        is_spatially_indexed=False,
                    )
                    for entity in chunk.unlinked_entities
                )
        return tuple(placements)

    def diagnostics(self) -> U9RegionSceneDiagnostics:
        """Check object bounds, chunk alignment, and nonfixed decode coverage."""
        fixed_total = 0
        fixed_in_bounds = 0
        fixed_chunk_mismatches = 0
        if self.fixed is not None:
            for fixed_chunk in self.fixed.chunks():
                for obj in fixed_chunk.objects:
                    fixed_total += 1
                    if (
                        0 <= obj.world_x < self.extent_x
                        and 0 <= obj.world_y < self.extent_y
                    ):
                        fixed_in_bounds += 1
                    if (
                        obj.world_x // CHUNK_SPAN != fixed_chunk.chunk_x
                        or obj.world_y // CHUNK_SPAN != fixed_chunk.chunk_y
                    ):
                        fixed_chunk_mismatches += 1

        nonfixed_indexed = 0
        nonfixed_unlinked = 0
        nonfixed_in_bounds = 0
        nonfixed_chunk_mismatches = 0
        nonfixed_incomplete_chunks = 0
        if self.nonfixed is not None:
            for nonfixed_chunk in self.nonfixed.chunks():
                nonfixed_indexed += len(nonfixed_chunk.entities)
                nonfixed_unlinked += len(nonfixed_chunk.unlinked_entities)
                nonfixed_incomplete_chunks += int(
                    not nonfixed_chunk.allocation_is_complete
                )
                for entity in nonfixed_chunk.allocated_entities:
                    if (
                        0 <= entity.world_x < self.extent_x
                        and 0 <= entity.world_y < self.extent_y
                    ):
                        nonfixed_in_bounds += 1
                    if (
                        entity.world_x // CHUNK_SPAN != nonfixed_chunk.chunk_x
                        or entity.world_y // CHUNK_SPAN != nonfixed_chunk.chunk_y
                    ):
                        nonfixed_chunk_mismatches += 1

        nonfixed_total = nonfixed_indexed + nonfixed_unlinked
        return U9RegionSceneDiagnostics(
            fixed_objects=fixed_total,
            fixed_objects_in_bounds=fixed_in_bounds,
            fixed_objects_out_of_bounds=fixed_total - fixed_in_bounds,
            fixed_chunk_position_mismatches=fixed_chunk_mismatches,
            nonfixed_indexed_entities=nonfixed_indexed,
            nonfixed_unlinked_entities=nonfixed_unlinked,
            nonfixed_allocated_entities=nonfixed_total,
            nonfixed_entities_in_bounds=nonfixed_in_bounds,
            nonfixed_entities_out_of_bounds=nonfixed_total - nonfixed_in_bounds,
            nonfixed_chunk_position_mismatches=nonfixed_chunk_mismatches,
            nonfixed_incomplete_chunks=nonfixed_incomplete_chunks,
        )
