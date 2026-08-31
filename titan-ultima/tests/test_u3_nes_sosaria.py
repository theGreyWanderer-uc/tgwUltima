from __future__ import annotations

import hashlib

from titan.u3.u3_nes_sosaria import (
    U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS,
    U3_SOSARIA_OVERWORLD_PACKED_SHA256,
    _COAST_LARGE_BY_DIAGONAL_LAND,
    _COAST_SMALL_BY_CARDINAL_LAND,
    _MOUNTAIN_INTERIOR_BANDS,
    _MOUNTAIN_NORTH_EAST_CORNER_OBJECTS,
    _MOUNTAIN_OUTSIDE_NORTH_WEST_SHAPE,
    _MOUNTAIN_SOUTH_EAST_OUTWARD_OBJECTS,
    _MOUNTAIN_SOUTH_WEST_OUTWARD_OBJECTS,
    _derived_terrain_definition,
    _mountain_local_objects,
    _mountain_upper_group_objects,
    _nearest_location_environment,
    _nearest_native_biome,
    _place_seeded_rare_features,
    _terrain_pattern_matches,
    load_embedded_u3_sosaria_overworld,
)


def _flat_definition(shape: int, frame: int) -> dict:
    return {
        "cells": [
            {
                "index": index,
                "x": index % 16,
                "y": index // 16,
                "shape": shape,
                "frame": frame,
                "kind": "flat",
            }
            for index in range(256)
        ]
    }


def test_embedded_u3_sosaria_overworld_is_complete_and_self_validating() -> None:
    decoded = load_embedded_u3_sosaria_overworld()
    packed = bytes.fromhex("".join(U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS))

    assert len(decoded) == 64
    assert all(len(row) == 64 for row in decoded)
    assert len(packed) == 2048
    assert hashlib.sha256(packed).hexdigest() == U3_SOSARIA_OVERWORLD_PACKED_SHA256
    assert U3_SOSARIA_OVERWORLD_PACKED_SHA256 == (
        "4cb9bb52a3fb8ba4d1f454575470e60cbd4ec12f667191e2af3b6c3998205bbc"
    )
    assert sorted({block for row in decoded for block in row}) == [
        0x0,
        0x1,
        0x2,
        0x3,
        0x4,
        0x7,
        0x8,
        0xC,
        0xD,
        0xE,
        0xF,
    ]


def test_mountain_upper_group_uses_si_quadrant_frame_order() -> None:
    objects = _mountain_upper_group_objects(
        2,
        3,
        shape=969,
        first_frame=8,
    )

    assert [
        (obj["tx"], obj["ty"], obj["tz"], obj["shape"], obj["frame"]) for obj in objects
    ] == [
        (39, 55, 5, 969, 8),
        (47, 55, 5, 969, 10),
        (39, 63, 5, 969, 9),
        (47, 63, 5, 969, 11),
    ]


def test_derived_terrain_definition_replaces_only_requested_cells() -> None:
    definitions = [_flat_definition(15, 0)]

    definition_id = _derived_terrain_definition(
        definitions,
        0,
        ((15, 15, 1020, 0),),
    )

    assert definition_id == 1
    assert definitions[1]["cells"][255]["shape"] == 1020
    assert definitions[1]["cells"][255]["kind"] == "rle"
    assert all(cell["shape"] == 15 for cell in definitions[1]["cells"][:255])
    assert definitions[1]["statistics"] == {
        "flat_references": 255,
        "rle_references": 1,
        "distinct_shapes": 2,
        "distinct_shape_frames": 2,
    }


def test_coast_water_diagonals_distinguish_cardinal_and_diagonal_land() -> None:
    assert _COAST_SMALL_BY_CARDINAL_LAND == {
        (True, False, True, False): (15, 15, 1020, 0),
        (True, False, False, True): (7, 15, 834, 0),
        (False, True, True, False): (15, 7, 1022, 0),
        (False, True, False, True): (7, 7, 1012, 0),
    }
    assert _COAST_LARGE_BY_DIAGONAL_LAND == {
        (True, False, False, False): 50,
        (False, True, False, False): 66,
        (False, False, True, False): 42,
        (False, False, False, True): 58,
    }


def test_mountain_interior_bands_use_confirmed_si_families() -> None:
    assert {
        modulus: (shape, first_frame)
        for modulus, (_, shape, first_frame) in _MOUNTAIN_INTERIOR_BANDS.items()
    } == {
        0: (180, 0),
        1: (183, 8),
        2: (969, 8),
        3: (183, 4),
    }


def test_outward_mountain_recipes_match_confirmed_si_chunks() -> None:
    assert _MOUNTAIN_NORTH_EAST_CORNER_OBJECTS == (
        (7, 7, 182, 4),
        (15, 7, 969, 2),
        (7, 15, 182, 5),
        (15, 15, 983, 10),
    )
    assert _MOUNTAIN_SOUTH_EAST_OUTWARD_OBJECTS == (
        (7, 7, 180, 8),
        (15, 7, 180, 10),
        (7, 15, 983, 7),
        (15, 15, 180, 11),
    )
    assert _MOUNTAIN_SOUTH_WEST_OUTWARD_OBJECTS == (
        (7, 7, 180, 4),
        (15, 7, 180, 6),
        (7, 15, 180, 7),
        (15, 15, 180, 5),
    )
    assert _MOUNTAIN_OUTSIDE_NORTH_WEST_SHAPE == 182


def test_location_environment_uses_nearest_eligible_ring_majority() -> None:
    source = [[0x4] * 64 for _ in range(64)]
    source[10][10] = 0xD
    source[9][9] = 0x1
    source[9][10] = 0x1
    source[10][11] = 0x0
    source[11][11] = 0x7

    assert _nearest_location_environment(source, 10, 10) == (0x1, 1)


def test_location_environment_skips_ineligible_nearest_ring() -> None:
    source = [[0x4] * 64 for _ in range(64)]
    source[10][10] = 0xF
    source[8][10] = 0x2

    assert _nearest_location_environment(source, 10, 10) == (0x2, 2)


def test_mountain_local_objects_preserve_exact_mixed_recipe() -> None:
    objects = _mountain_local_objects(
        10,
        20,
        _MOUNTAIN_SOUTH_EAST_OUTWARD_OBJECTS,
    )

    assert [
        (obj["tx"], obj["ty"], obj["tz"], obj["shape"], obj["frame"]) for obj in objects
    ] == [
        (167, 327, 5, 180, 8),
        (175, 327, 5, 180, 10),
        (167, 335, 5, 983, 7),
        (175, 335, 5, 180, 11),
    ]


def test_rare_feature_pattern_scan_counts_complete_groups() -> None:
    rows = [
        [0, 0, 0, 0, 0],
        [0, 626, 627, 0, 0],
        [0, 625, 624, 626, 627],
        [0, 0, 0, 625, 624],
    ]

    matches = _terrain_pattern_matches(
        rows,
        ((626, 627), (625, 624)),
    )

    assert matches == [(1, 1), (3, 2)]


def test_rare_feature_context_tie_prefers_documented_biome() -> None:
    biome_rows: list[list[str | None]] = [
        ["evergreen", "evergreen", "grass"],
        ["evergreen", None, "grass"],
        ["grass", "grass", "grass"],
    ]

    biome = _nearest_native_biome(
        biome_rows,
        1,
        1,
        1,
        1,
        preferred_biome="grass",
    )

    assert biome == "grass"


def test_seeded_rare_feature_groups_are_deterministic_and_non_overlapping() -> None:
    analysis = {
        "method": "test-native-rate",
        "native_biome_chunks": {"evergreen": 20},
        "profiles": [
            {
                "name": "test_two_by_two_group",
                "biome": "evergreen",
                "native_group_count": 2,
                "native_biome_chunks": 20,
                "placement_rate": 0.1,
                "placement_percent": 10.0,
                "patterns": [
                    {
                        "terrain_definition_ids": [[1, 2], [3, 4]],
                        "native_group_count": 2,
                    }
                ],
            }
        ],
    }
    biome_rows: list[list[str | None]] = [["evergreen"] * 8 for _ in range(8)]
    first_rows = [[0] * 8 for _ in range(8)]
    second_rows = [[0] * 8 for _ in range(8)]

    first = _place_seeded_rare_features(
        first_rows,
        biome_rows,
        analysis,
        seed=42,
    )
    second = _place_seeded_rare_features(
        second_rows,
        biome_rows,
        analysis,
        seed=42,
    )

    assert first == second
    assert first_rows == second_rows
    profile = first["profiles"][0]
    assert first["frequency_scale"] == 0.25
    assert profile["effective_placement_rate"] == 0.025
    assert profile["target_group_count"] == 2
    assert profile["placed_group_count"] == 2
    footprints: list[set[tuple[int, int]]] = []
    for placement in profile["placements"]:
        x = placement["chunk_x"]
        y = placement["chunk_y"]
        footprint = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
        assert all(not (footprint & other) for other in footprints)
        footprints.append(footprint)


def test_meadow_sinkholes_have_seeded_one_in_five_chance_per_toroidal_biome() -> None:
    analysis = {
        "method": "test-native-rate",
        "native_biome_chunks": {"meadow": 8},
        "profiles": [
            {
                "name": "meadow_sinkhole",
                "biome": "meadow",
                "native_group_count": 8,
                "native_biome_chunks": 8,
                "placement_rate": 1.0,
                "placement_percent": 100.0,
                "patterns": [
                    {
                        "terrain_definition_ids": [[1917]],
                        "native_group_count": 8,
                    }
                ],
            }
        ],
    }
    biome_rows: list[list[str | None]] = [[None] * 9 for _ in range(9)]
    for y in range(1, 9, 2):
        for x in range(1, 9, 2):
            biome_rows[y][x] = "meadow"
    rows = [[0] * 9 for _ in range(9)]
    second_rows = [[0] * 9 for _ in range(9)]

    result = _place_seeded_rare_features(rows, biome_rows, analysis, seed=42)
    second = _place_seeded_rare_features(
        second_rows,
        biome_rows,
        analysis,
        seed=42,
    )

    assert result == second
    assert rows == second_rows
    profile = result["profiles"][0]
    assert profile["eligible_biome_component_count"] == 16
    assert profile["biome_selection_chance"] == 0.2
    assert profile["biome_selection_chance_fraction"] == "1/5"
    assert profile["target_group_count"] == profile["selected_biome_component_count"]
    assert profile["placed_group_count"] == profile["target_group_count"]
    assert profile["per_biome_cap"] == 1
    placements = profile["placements"]
    assert len({placement["biome_component_id"] for placement in placements}) == len(
        placements
    )
    assert {placement["biome_component_id"] for placement in placements} == set(
        profile["selected_biome_component_ids"]
    )
