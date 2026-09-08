"""Resolve Ultima IX region placements to transformed model footprints.

Fixed objects identify a type in ``TYPES.DAT``; that type supplies the model
entry in ``sappear.flx``. Nonfixed objects store their model entry directly.
This module joins those formats without making the 2D renderer understand any
of their binary layouts.
"""

from __future__ import annotations

__all__ = [
    "U9ModelBounds",
    "U9ModelBoundsLookup",
    "U9ModelBoundsProvider",
    "U9ModelLookup",
    "U9ModelProvider",
    "U9ObjectFootprintFilter",
    "U9ObjectPlacementDiagnostics",
    "U9ObjectPlacementError",
    "U9ObjectPlacementResolution",
    "U9ObjectPlacementResult",
    "U9SappearModelBounds",
    "U9SappearModelSource",
    "object_scale_from_extra_data",
    "project_model_bounds_footprint",
    "resolve_region_object_placements",
]

import os
from dataclasses import dataclass
from typing import Literal, Protocol

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.model import U9Model, U9ModelError
from titan.u9.nonfixed import U9ExtraData
from titan.u9.region_scene import U9RegionScene, U9WorldPosition
from titan.u9.transform import mat4_trs, transform_point
from titan.u9.types_dat import U9TypesDat

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
PlacementKind = Literal["fixed", "nonfixed"]
FootprintSource = Literal["all", "fixed", "nonfixed"]
ModelLookupStatus = Literal["resolved", "out_of_range", "unused", "malformed"]

_SCALE_UNIFORM = 0x42
_SCALE_X = 0x49
_SCALE_Y = 0x4A
_SCALE_Z = 0x4B
_CONTAINED_OBJECT_FLAG = 0x200


class U9ObjectPlacementError(Exception):
    """Raised when placements cannot be joined to their model metadata."""


@dataclass(frozen=True)
class U9ModelBounds:
    """One model-space bounding box in native U9 coordinate units."""

    model_id: int
    minimum: Vec3
    maximum: Vec3


@dataclass(frozen=True)
class U9ModelBoundsLookup:
    """One model lookup result, including a searchable failure category."""

    model_id: int
    status: ModelLookupStatus
    bounds: U9ModelBounds | None = None


class U9ModelBoundsProvider(Protocol):
    """Look up parsed ``sappear.flx`` model bounds by model entry ID."""

    def model_bounds(self, model_id: int) -> U9ModelBoundsLookup:
        """Return bounds or a precise non-fatal lookup status."""
        ...


@dataclass(frozen=True)
class U9ModelLookup:
    """One parsed ``sappear.flx`` model or its non-fatal lookup status."""

    model_id: int
    status: ModelLookupStatus
    model: U9Model | None = None


class U9ModelProvider(U9ModelBoundsProvider, Protocol):
    """Provide both parsed models and lightweight model bounds by entry ID."""

    def model(self, model_id: int) -> U9ModelLookup:
        """Return a parsed model or a precise non-fatal lookup status."""
        ...


class U9SappearModelSource:
    """Lazy, cached full-model reader backed by one ``sappear.flx`` archive."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive = archive
        self._model_cache: dict[int, U9ModelLookup] = {}
        self._cache: dict[int, U9ModelBoundsLookup] = {}

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> U9SappearModelSource:
        """Open one ``sappear.flx`` archive for lazy model resolution."""
        return cls(U9FlxArchive.from_file(path))

    def model(self, model_id: int) -> U9ModelLookup:
        """Parse one full model once, retaining missing and malformed outcomes."""
        cached = self._model_cache.get(model_id)
        if cached is not None:
            return cached
        entry = self.archive.get_entry(model_id)
        if entry is None:
            result = U9ModelLookup(model_id, "out_of_range")
        elif not entry.is_used:
            result = U9ModelLookup(model_id, "unused")
        else:
            blob = self.archive.read_entry(model_id)
            try:
                model = U9Model.parse(blob, model_id)
            except U9ModelError:
                result = U9ModelLookup(model_id, "malformed")
            else:
                result = U9ModelLookup(model_id, "resolved", model)
        self._model_cache[model_id] = result
        return result

    def model_bounds(self, model_id: int) -> U9ModelBoundsLookup:
        """Parse and cache bounds without retaining every full model in memory."""
        cached = self._cache.get(model_id)
        if cached is not None:
            return cached

        entry = self.archive.get_entry(model_id)
        if entry is None:
            result = U9ModelBoundsLookup(model_id, "out_of_range")
        elif not entry.is_used:
            result = U9ModelBoundsLookup(model_id, "unused")
        else:
            blob = self.archive.read_entry(model_id)
            try:
                model = U9Model.parse(blob, model_id)
            except U9ModelError:
                result = U9ModelBoundsLookup(model_id, "malformed")
            else:
                result = U9ModelBoundsLookup(
                    model_id,
                    "resolved",
                    U9ModelBounds(model_id, model.min_bounds, model.max_bounds),
                )
        self._cache[model_id] = result
        return result


class U9SappearModelBounds(U9SappearModelSource):
    """Compatibility name for callers that only need lazy model bounds."""


@dataclass(frozen=True)
class U9ObjectPlacementResolution:
    """One fixed or nonfixed placement joined to its model and footprint."""

    source_kind: PlacementKind
    source_offset: int
    type_index: int
    model_id: int | None
    status: str
    position: U9WorldPosition
    rotation_xyzw: tuple[int, int, int, int]
    quaternion_wxyz: Quat
    scale_xyz: Vec3
    footprint_xy: tuple[Vec2, ...]
    flags: int
    trigger_id: int | None
    is_spatially_indexed: bool = True

    @property
    def is_resolved(self) -> bool:
        """Whether a real model supplied this placement's footprint."""
        return self.status == "resolved"


@dataclass(frozen=True)
class U9ObjectPlacementDiagnostics:
    """Resolution coverage for the fixed and nonfixed model joins."""

    fixed_placements: int
    fixed_resolved: int
    fixed_without_model: int
    fixed_unresolved: int
    nonfixed_placements: int
    nonfixed_resolved: int
    nonfixed_unresolved: int
    model_ids_requested: tuple[int, ...]
    model_ids_resolved: tuple[int, ...]
    missing_model_ids: tuple[int, ...]
    malformed_model_ids: tuple[int, ...]


@dataclass(frozen=True)
class U9ObjectPlacementResult:
    """Every placement resolution plus compact model-join diagnostics."""

    placements: tuple[U9ObjectPlacementResolution, ...]
    diagnostics: U9ObjectPlacementDiagnostics

    @property
    def footprints(self) -> tuple[U9ObjectPlacementResolution, ...]:
        """Return only placements with transformed model footprints."""
        return tuple(
            placement for placement in self.placements if placement.is_resolved
        )


@dataclass(frozen=True)
class U9ObjectFootprintFilter:
    """Select resolved footprints by source, type ID, and model ID.

    Empty ID sets are wildcards. When both sets are populated, a placement
    must match both; source filtering is always applied first.
    """

    source: FootprintSource = "all"
    type_ids: frozenset[int] = frozenset()
    model_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.source not in {"all", "fixed", "nonfixed"}:
            raise U9ObjectPlacementError(
                "footprint source must be all, fixed, or nonfixed"
            )
        if any(value < 0 for value in self.type_ids):
            raise U9ObjectPlacementError("footprint type IDs cannot be negative")
        if any(value < 0 for value in self.model_ids):
            raise U9ObjectPlacementError("footprint model IDs cannot be negative")

    def select(
        self, result: U9ObjectPlacementResult
    ) -> tuple[U9ObjectPlacementResolution, ...]:
        """Return resolved placements matching every active filter."""
        return tuple(
            placement for placement in result.footprints if self._matches(placement)
        )

    def _matches(self, placement: U9ObjectPlacementResolution) -> bool:
        if self.source != "all" and placement.source_kind != self.source:
            return False
        if self.type_ids and placement.type_index not in self.type_ids:
            return False
        return not self.model_ids or placement.model_id in self.model_ids


def object_scale_from_extra_data(extra: U9ExtraData | None) -> Vec3:
    """Decode nonfixed scale properties as native U9 X/Y/Z multipliers.

    The functioning Forgotten World editor treats values as percentages and
    applies each scale property as a complete replacement. Repeating that
    ordering matters if a hand-edited record contains more than one scale tag.
    """
    scale: Vec3 = (1.0, 1.0, 1.0)
    if extra is None:
        return scale
    for argument_type, raw_value in extra.args:
        value = raw_value / 100.0
        if argument_type == _SCALE_UNIFORM:
            scale = (value, value, value)
        elif argument_type == _SCALE_X:
            scale = (value, 1.0, 1.0)
        elif argument_type == _SCALE_Y:
            scale = (1.0, value, 1.0)
        elif argument_type == _SCALE_Z:
            scale = (1.0, 1.0, value)
    return scale


def _placement_quaternion(rotation_xyzw: tuple[int, int, int, int]) -> Quat:
    """Convert stored X/Y/Z/W fixed-point order to native W/X/Y/Z order."""
    x, y, z, w = rotation_xyzw
    divisor = 32767.0
    return (w / divisor, x / divisor, y / divisor, z / divisor)


def _convex_hull(points: tuple[Vec2, ...]) -> tuple[Vec2, ...]:
    """Return the counter-clockwise convex hull of a small projected box."""
    unique = sorted(set(points))
    if len(unique) <= 1:
        return tuple(unique)

    def cross(origin: Vec2, a: Vec2, b: Vec2) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (
            b[0] - origin[0]
        )

    lower: list[Vec2] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Vec2] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def project_model_bounds_footprint(
    bounds: U9ModelBounds,
    position: U9WorldPosition,
    quaternion_wxyz: Quat,
    scale_xyz: Vec3,
) -> tuple[Vec2, ...]:
    """Transform all eight model-box corners and return their native X/Y hull."""
    matrix = mat4_trs(
        (float(position.x), float(position.y), float(position.z)),
        quaternion_wxyz,
        scale_xyz,
    )
    minimum = bounds.minimum
    maximum = bounds.maximum
    projected = tuple(
        transform_point(matrix, (x, y, z))[:2]
        for x in (minimum[0], maximum[0])
        for y in (minimum[1], maximum[1])
        for z in (minimum[2], maximum[2])
    )
    return _convex_hull(projected)


def _resolved_placement(
    *,
    source_kind: PlacementKind,
    source_offset: int,
    type_index: int,
    model_id: int | None,
    status: str,
    position: U9WorldPosition,
    rotation_xyzw: tuple[int, int, int, int],
    scale_xyz: Vec3,
    flags: int,
    trigger_id: int | None,
    lookup: U9ModelBoundsLookup | None,
    is_spatially_indexed: bool = True,
) -> U9ObjectPlacementResolution:
    quaternion = _placement_quaternion(rotation_xyzw)
    footprint: tuple[Vec2, ...] = ()
    if lookup is not None and lookup.bounds is not None:
        footprint = project_model_bounds_footprint(
            lookup.bounds, position, quaternion, scale_xyz
        )
    return U9ObjectPlacementResolution(
        source_kind=source_kind,
        source_offset=source_offset,
        type_index=type_index,
        model_id=model_id,
        status=status,
        position=position,
        rotation_xyzw=rotation_xyzw,
        quaternion_wxyz=quaternion,
        scale_xyz=scale_xyz,
        footprint_xy=footprint,
        flags=flags,
        trigger_id=trigger_id,
        is_spatially_indexed=is_spatially_indexed,
    )


def resolve_region_object_placements(
    scene: U9RegionScene,
    models: U9ModelBoundsProvider,
    *,
    types: U9TypesDat | None = None,
    include_unlinked_nonfixed: bool = False,
) -> U9ObjectPlacementResult:
    """Resolve a scene's object records to models and transformed XY footprints."""
    if scene.fixed is not None and types is None:
        raise U9ObjectPlacementError("fixed model resolution requires static/TYPES.DAT")

    placements: list[U9ObjectPlacementResolution] = []
    for fixed_placement in scene.fixed_placements():
        if types is None:
            raise U9ObjectPlacementError(
                "fixed model resolution requires static/TYPES.DAT"
            )
        type_index = fixed_placement.object.type_index
        if not 0 <= type_index < len(types.records):
            placements.append(
                _resolved_placement(
                    source_kind="fixed",
                    source_offset=fixed_placement.object.offset,
                    type_index=type_index,
                    model_id=None,
                    status="type_out_of_range",
                    position=fixed_placement.position,
                    rotation_xyzw=fixed_placement.object.rotation,
                    scale_xyz=(1.0, 1.0, 1.0),
                    flags=fixed_placement.object.flags,
                    trigger_id=None,
                    lookup=None,
                )
            )
            continue
        model_id = types.records[type_index].default_model_id
        if model_id == 0:
            placements.append(
                _resolved_placement(
                    source_kind="fixed",
                    source_offset=fixed_placement.object.offset,
                    type_index=type_index,
                    model_id=None,
                    status="no_model",
                    position=fixed_placement.position,
                    rotation_xyzw=fixed_placement.object.rotation,
                    scale_xyz=(1.0, 1.0, 1.0),
                    flags=fixed_placement.object.flags,
                    trigger_id=None,
                    lookup=None,
                )
            )
            continue
        lookup = models.model_bounds(model_id)
        placements.append(
            _resolved_placement(
                source_kind="fixed",
                source_offset=fixed_placement.object.offset,
                type_index=type_index,
                model_id=model_id,
                status=lookup.status,
                position=fixed_placement.position,
                rotation_xyzw=fixed_placement.object.rotation,
                scale_xyz=(1.0, 1.0, 1.0),
                flags=fixed_placement.object.flags,
                trigger_id=None,
                lookup=lookup,
            )
        )

    for nonfixed_placement in scene.nonfixed_placements(
        include_unlinked=include_unlinked_nonfixed
    ):
        entity = nonfixed_placement.entity
        lookup = models.model_bounds(entity.mesh_index)
        extra = (
            scene.nonfixed.extra_data(entity) if scene.nonfixed is not None else None
        )
        rotation = entity.rotation
        if entity.flags & _CONTAINED_OBJECT_FLAG:
            rotation = (0, 0, 0, 32767)
        placements.append(
            _resolved_placement(
                source_kind="nonfixed",
                source_offset=entity.offset,
                type_index=entity.type_index,
                model_id=entity.mesh_index,
                status=lookup.status,
                position=nonfixed_placement.position,
                rotation_xyzw=rotation,
                scale_xyz=object_scale_from_extra_data(extra),
                flags=entity.flags,
                trigger_id=entity.trigger_id,
                lookup=lookup,
                is_spatially_indexed=nonfixed_placement.is_spatially_indexed,
            )
        )

    fixed = [item for item in placements if item.source_kind == "fixed"]
    nonfixed = [item for item in placements if item.source_kind == "nonfixed"]
    requested = sorted(
        {item.model_id for item in placements if item.model_id is not None}
    )
    resolved = sorted(
        {
            item.model_id
            for item in placements
            if item.is_resolved and item.model_id is not None
        }
    )
    missing = sorted(
        {
            item.model_id
            for item in placements
            if item.model_id is not None and item.status in {"out_of_range", "unused"}
        }
    )
    malformed = sorted(
        {
            item.model_id
            for item in placements
            if item.model_id is not None and item.status == "malformed"
        }
    )
    diagnostics = U9ObjectPlacementDiagnostics(
        fixed_placements=len(fixed),
        fixed_resolved=sum(item.is_resolved for item in fixed),
        fixed_without_model=sum(item.status == "no_model" for item in fixed),
        fixed_unresolved=sum(
            item.status not in {"resolved", "no_model"} for item in fixed
        ),
        nonfixed_placements=len(nonfixed),
        nonfixed_resolved=sum(item.is_resolved for item in nonfixed),
        nonfixed_unresolved=sum(not item.is_resolved for item in nonfixed),
        model_ids_requested=tuple(requested),
        model_ids_resolved=tuple(resolved),
        missing_model_ids=tuple(missing),
        malformed_model_ids=tuple(malformed),
    )
    return U9ObjectPlacementResult(tuple(placements), diagnostics)
