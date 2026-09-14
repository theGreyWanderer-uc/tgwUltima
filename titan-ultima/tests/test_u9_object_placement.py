"""Tests for joining U9 fixed/nonfixed placements to model footprints."""

from __future__ import annotations

import math
import struct
import unittest

from titan.u9.fixed import OBJECT_SIZE, PAGE_HEADER_SIZE, U9Fixed
from titan.u9.flx_archive import U9FlxArchive
from titan.u9.flx_writer import build_flx
from titan.u9.nonfixed import U9ExtraData, U9Nonfixed
from titan.u9.object_placement import (
    U9ModelBounds,
    U9ModelBoundsLookup,
    U9ObjectFootprintFilter,
    U9ObjectPlacementError,
    U9SappearModelBounds,
    object_scale_from_extra_data,
    project_model_bounds_footprint,
    resolve_region_object_placements,
)
from titan.u9.region_scene import U9RegionScene, U9WorldPosition
from titan.u9.terrain import HEADER_SIZE, POINTS_PER_CHUNK, U9Terrain, U9TerrainPoint
from titan.u9.types_dat import (
    EXPECTED_SIZE,
    HEADER_SIZE as TYPES_HEADER_SIZE,
    U9TypesDat,
)


class FakeModelBounds:
    def __init__(self, lookups: dict[int, U9ModelBoundsLookup]) -> None:
        self.lookups = lookups

    def model_bounds(self, model_id: int) -> U9ModelBoundsLookup:
        return self.lookups.get(model_id, U9ModelBoundsLookup(model_id, "out_of_range"))


def _terrain() -> U9Terrain:
    point = U9TerrainPoint.build(texture=1).value
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<II", head, 0, 32, 32)
    struct.pack_into("<I", head, 0x94, 1)
    return U9Terrain(
        bytes(head)
        + struct.pack("<4H", 0, 0, 0, 0)
        + struct.pack(f"<{POINTS_PER_CHUNK}I", *([point] * POINTS_PER_CHUNK))
    )


def _fixed(type_index: int = 42) -> U9Fixed:
    obj = struct.pack("<I4H4hI", 1, 128, 256, 300, type_index, 0, 0, 0, -32768, 0)
    end = PAGE_HEADER_SIZE + OBJECT_SIZE
    page = struct.pack("<6I", 0, end, 0, 0, 0, 0)
    page += b"\x00" * (PAGE_HEADER_SIZE - len(page)) + obj
    head = bytearray(0x24)
    struct.pack_into("<I", head, 0x08, len(page))
    struct.pack_into("<II", head, 0x10, 1, 1)
    struct.pack_into("<I", head, 0x1C, 1)
    struct.pack_into("<I", head, 0x20, 1)
    return U9Fixed(bytes(head) + page)


def _types(type_index: int = 42, model_id: int = 7) -> U9TypesDat:
    data = bytearray(EXPECTED_SIZE)
    offset = TYPES_HEADER_SIZE + type_index * 16
    struct.pack_into("<IHHHBBBBH", data, offset, 0, 0, model_id, 0, 0, 0, 0, 0, 0)
    return U9TypesDat(bytes(data))


def _nonfixed(mesh_index: int = 9) -> U9Nonfixed:
    entity_offset = 0x60
    heads = [0, entity_offset] + [0] * 15
    page = struct.pack("<7I17I", 0, 0, 0, 0, 0, 1, 0, *heads)
    page += struct.pack(
        "<IHHHH4hIHHI",
        0,
        128,
        256,
        350,
        600,
        0,
        0,
        0,
        -32768,
        0,
        mesh_index,
        0,
        0,
    )
    header = struct.pack("<5I", 0, 0, 0, len(page), 0x00C00000)
    header += struct.pack("<III", 1, 1, 1)
    header += struct.pack("<II", 1, 0)
    return U9Nonfixed(header + page)


class ObjectPlacementTests(unittest.TestCase):
    def test_sappear_bounds_provider_classifies_archive_entries(self) -> None:
        model = bytearray(0x90)
        struct.pack_into("<II", model, 0, 0, 0)
        struct.pack_into("<3f", model, 0x30, -4.0, -5.0, -6.0)
        struct.pack_into("<3f", model, 0x3C, 7.0, 8.0, 9.0)
        archive = U9FlxArchive(build_flx({0: bytes(model), 2: b"broken"}, count=4))
        provider = U9SappearModelBounds(archive)

        resolved = provider.model_bounds(0)
        self.assertEqual(resolved.status, "resolved")
        if resolved.bounds is None:
            self.fail("resolved model did not expose bounds")
        self.assertEqual(resolved.bounds.minimum, (-4.0, -5.0, -6.0))
        self.assertEqual(resolved.bounds.maximum, (7.0, 8.0, 9.0))
        self.assertEqual(provider.model_bounds(1).status, "unused")
        self.assertEqual(provider.model_bounds(2).status, "malformed")
        self.assertEqual(provider.model_bounds(4).status, "out_of_range")
        self.assertIs(provider.model_bounds(0), resolved)
        full_model = provider.model(0)
        self.assertEqual(full_model.status, "resolved")
        self.assertIsNotNone(full_model.model)
        self.assertIs(provider.model(0), full_model)

    def test_projects_rotated_model_box_to_native_xy_hull(self) -> None:
        bounds = U9ModelBounds(7, (-10.0, -20.0, -5.0), (10.0, 20.0, 5.0))
        half = math.sqrt(0.5)
        footprint = project_model_bounds_footprint(
            bounds,
            U9WorldPosition(100, 200, 300),
            (half, 0.0, 0.0, half),
            (2.0, 1.0, 1.0),
        )
        self.assertEqual(len(footprint), 4)
        xs = [point[0] for point in footprint]
        ys = [point[1] for point in footprint]
        self.assertAlmostEqual(min(xs), 80.0)
        self.assertAlmostEqual(max(xs), 120.0)
        self.assertAlmostEqual(min(ys), 180.0)
        self.assertAlmostEqual(max(ys), 220.0)

    def test_decodes_uniform_and_native_axis_scale_percentages(self) -> None:
        uniform = U9ExtraData(0, 1, (0x42, 0, 0), (250, 0, 0))
        self.assertEqual(object_scale_from_extra_data(uniform), (2.5, 2.5, 2.5))
        axis = U9ExtraData(0, 3, (0x49, 0x4A, 0x4B), (200, 300, 400))
        self.assertEqual(object_scale_from_extra_data(axis), (1.0, 1.0, 4.0))

    def test_resolves_fixed_type_through_types_dat(self) -> None:
        lookup = U9ModelBoundsLookup(
            7, "resolved", U9ModelBounds(7, (-64, -32, 0), (64, 32, 100))
        )
        result = resolve_region_object_placements(
            U9RegionScene(_terrain(), fixed=_fixed()),
            FakeModelBounds({7: lookup}),
            types=_types(),
        )
        placement = result.placements[0]
        self.assertEqual(placement.model_id, 7)
        self.assertEqual(placement.status, "resolved")
        self.assertEqual(placement.position, U9WorldPosition(128, 256, 300))
        self.assertEqual(placement.rotation_xyzw, (0, 0, 0, -32768))
        self.assertEqual(placement.flags, 0)
        self.assertIsNone(placement.trigger_id)
        self.assertEqual(result.diagnostics.fixed_resolved, 1)
        self.assertEqual(result.diagnostics.model_ids_resolved, (7,))

    def test_fixed_resolution_requires_types_dat(self) -> None:
        with self.assertRaisesRegex(U9ObjectPlacementError, "TYPES.DAT"):
            resolve_region_object_placements(
                U9RegionScene(_terrain(), fixed=_fixed()), FakeModelBounds({})
            )

    def test_reports_fixed_types_without_models(self) -> None:
        result = resolve_region_object_placements(
            U9RegionScene(_terrain(), fixed=_fixed()),
            FakeModelBounds({}),
            types=_types(model_id=0),
        )
        self.assertEqual(result.placements[0].status, "no_model")
        self.assertEqual(result.diagnostics.fixed_without_model, 1)
        self.assertEqual(result.diagnostics.model_ids_requested, ())

    def test_nonfixed_uses_direct_mesh_index(self) -> None:
        lookup = U9ModelBoundsLookup(
            9, "resolved", U9ModelBounds(9, (-10, -10, 0), (10, 10, 20))
        )
        result = resolve_region_object_placements(
            U9RegionScene(_terrain(), nonfixed=_nonfixed()),
            FakeModelBounds({9: lookup}),
        )
        placement = result.placements[0]
        self.assertEqual(placement.model_id, 9)
        self.assertEqual(placement.type_index, 600)
        self.assertEqual(placement.trigger_id, 0)
        self.assertEqual(result.diagnostics.nonfixed_resolved, 1)

    def test_missing_model_is_nonfatal_and_diagnosed(self) -> None:
        result = resolve_region_object_placements(
            U9RegionScene(_terrain(), nonfixed=_nonfixed(mesh_index=9999)),
            FakeModelBounds({}),
        )
        self.assertEqual(result.placements[0].status, "out_of_range")
        self.assertEqual(result.placements[0].footprint_xy, ())
        self.assertEqual(result.diagnostics.nonfixed_unresolved, 1)
        self.assertEqual(result.diagnostics.missing_model_ids, (9999,))

    def test_footprint_filter_intersects_source_type_and_model_ids(self) -> None:
        models = FakeModelBounds(
            {
                7: U9ModelBoundsLookup(
                    7, "resolved", U9ModelBounds(7, (-1, -1, 0), (1, 1, 2))
                ),
                9: U9ModelBoundsLookup(
                    9, "resolved", U9ModelBounds(9, (-1, -1, 0), (1, 1, 2))
                ),
            }
        )
        result = resolve_region_object_placements(
            U9RegionScene(_terrain(), fixed=_fixed(), nonfixed=_nonfixed()),
            models,
            types=_types(),
        )

        selected = U9ObjectFootprintFilter(
            source="nonfixed",
            type_ids=frozenset({600}),
            model_ids=frozenset({9}),
        ).select(result)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].source_kind, "nonfixed")
        self.assertEqual(selected[0].model_id, 9)
        self.assertEqual(
            U9ObjectFootprintFilter(model_ids=frozenset({999})).select(result), ()
        )

    def test_footprint_filter_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(U9ObjectPlacementError, "source"):
            U9ObjectFootprintFilter(source="dynamic")  # type: ignore[arg-type]
        with self.assertRaisesRegex(U9ObjectPlacementError, "negative"):
            U9ObjectFootprintFilter(type_ids=frozenset({-1}))


if __name__ == "__main__":
    unittest.main()
