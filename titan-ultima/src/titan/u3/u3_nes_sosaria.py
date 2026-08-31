"""Build a Serpent Isle-sized map JSON from the Ultima III NES overworld."""

from __future__ import annotations

__all__ = [
    "U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS",
    "analyze_si_rare_feature_profiles",
    "build_u3_nes_sosaria_map_document",
    "load_embedded_u3_sosaria_overworld",
]

import copy
import hashlib
import math
import random
from collections import Counter, deque
from typing import Any

from titan.u7.map import C_NUM_CHUNKS, C_TILES_PER_CHUNK
from titan.u7.map_json import validate_u7_map_document
from titan.u7.shape import FIRST_OBJ_SHAPE


U3_SOURCE_SIZE = 64
U3_TO_U7_CHUNK_SCALE = 3
U3_WATER_IDS = {0x3, 0x8, 0xC}
U3_LOCATION_IDS = {0xD, 0xE, 0xF}
U3_LOCATION_ENVIRONMENT_IDS = {0x0, 0x1, 0x2}

# Canonical U3 NES Sosaria overworld. Each string is one 64-block row stored as
# 32 packed bytes; the high nibble is the left block. This is the sole U3 map
# layout source used by the generator.
U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS = (
    "1133333333333333333333333333333333333333333333333333333333331111",
    "1111333311111333333333333333333333333333333333333333333333333111",
    "111111333111113333333333333111F333333333333333333333333333333331",
    "3111111333311113333333333333333311333333333333333333333333333333",
    "1111111111111113333333333111311333333333112443333333333333333333",
    "1111111100144444333333333333333333301131112244433333333444433333",
    "11331100004400000011333333333300000001331112224433333344E3443333",
    "1133300000400000000113111111000000000011011242E43333334303343333",
    "3113300004400000000133311110000000000000001144443333334300343333",
    "3313344444000000301331111100000000000000000111433333334330343333",
    "3333311000000003333311111000000000000000000001133333334411443333",
    "3333310000000000131331110000000000000000000000133333333422433333",
    "3333300000033100111131100000000011111000000000333333333422433333",
    "333330F000131100000111100000000114441100000000333333333422433333",
    "3333330001131110000000000000001144244110000000333333333422443333",
    "3333333333333300000000000000011442224410000003333333334422243333",
    "3333333331111333300000000000011222F22410000003333333334222243333",
    "3333331133331100000000000000011442224410000000033311311222243333",
    "333331111131100000000000000000114424411000000D003333301122443333",
    "3333311001310000000000000000000114441100000000F00330000112433333",
    "3333310001110000000000000000000011111000000000000000000011433333",
    "3333311000000000000000000000000000000000000000000000000001133333",
    "3333331100000000000000000000000000000000000000001100000000133333",
    "3333334110000011111111110000000000000000000000000110000000333333",
    "3333334411000111111111111111000000000000000000000000000000333333",
    "3333333441101111444441111111110000000000000000000000131100333333",
    "3333333044111144442244411111111110000000000000000001133111333333",
    "3333333004411140422100444111111111000000000000000013113113333333",
    "333333300E411140421000014441111111100000110000000013333333333333",
    "3333330004400140410000001144411111110001110000000111311334443333",
    "3333330144000144400000001122444441111011100000011111313344E44333",
    "333333114000001440F3330011222220411111110000001144411130F4044333",
    "3333311440000011433333311122224441111100000001144744133004443333",
    "3333311000000001443333331124444111110000000011447774433000033333",
    "3333310000000000144433331444111111100000000011447E74433111333333",
    "3333330000000000001443344411111110000000000111147074333110333333",
    "3333330000000000000044440000111100000000001111142044333311033333",
    "3333331111000000000000000000011000000000001111122443311331033333",
    "3333333111111000000000000001111111000000003311124433313311033333",
    "3333333111111110000000000111111111100000000313333333113311133333",
    "3333333311111111100000001111311111111100003333000033111331133333",
    "3333333111111111111000111111331131111110033030000003311333333333",
    "3333333111111111133333111111131131111111000000000003333311333333",
    "3333331111111333333333333111131331111111100000000003333114443333",
    "3333331F11133333333113333311333311111111111000000000330111E43333",
    "3333333113333333333333333333311333111111111110000000330011143333",
    "3333333333333333333333343333111111111222221111000000333000113333",
    "3333333333333333333333344333111111222222222211110000003300133333",
    "3333333333333333333333344333111222222222222221111000000333333333",
    "3333333333333333333333333331122222222222222221111100000000333333",
    "3333333333333333333333333332222222222222222221111110000000033333",
    "3333333344444333333333333322222222222222222211113111000000033333",
    "3333333347774333333333333222222222222222222111113111100000003333",
    "3333333447D74433333334422222222222222222222111113131111000000333",
    "3333333403330433333444222222222222222222221113313131111133000333",
    "3333333400300433334411222222222222222222211111333331111333000333",
    "3333333444344433334111122442222223222222211111003000111333300333",
    "3333333344844333334E00444433322223344422211110003000011133003333",
    "3333333330C033333344444333333322334404422111000F3F00001113333313",
    "3333333330303333333333333333333333300022333300033300001111133113",
    "3333333333333333333333333333333333333333333333333333311111111113",
    "3333333333333333333333333333333333333333333333333333333111111133",
    "3333333333333333333333333333333333333333333333333333333331111113",
    "3333333333333333333333333333333333333333333333333333333333311111",
)
U3_SOSARIA_OVERWORLD_PACKED_SHA256 = (
    "4cb9bb52a3fb8ba4d1f454575470e60cbd4ec12f667191e2af3b6c3998205bbc"
)

_GRASS_POOL = {873: 2, 874: 3, 908: 3, 1798: 6, 1799: 11, 1825: 2}
_FOREST_POOLS = {
    "evergreen": {398: 1, 444: 2, 896: 3, 897: 3, 1499: 1, 1734: 2, 1735: 5, 2105: 1},
    "old_deciduous": {
        14: 1,
        103: 2,
        162: 1,
        166: 1,
        167: 1,
        169: 1,
        2304: 1,
        2305: 1,
        2306: 1,
        2585: 1,
        2917: 1,
    },
    "autumn_deciduous": {
        81: 1,
        138: 3,
        641: 3,
        643: 2,
        645: 1,
        1065: 4,
        1066: 2,
        1067: 2,
        1149: 4,
        1890: 3,
        2488: 2,
        2495: 2,
        2500: 3,
    },
    "jungle": {899: 3, 1168: 2, 1290: 1, 1291: 2, 1407: 4, 1825: 1, 2736: 3, 2737: 3},
}

_COAST_POOLS = {
    "north": (8, 15, 9, 8),
    "south": (17, 17, 19, 16),
    "east": (27, 27, 24),
    "west": (33, 33, 32),
}
_COAST_LARGE_BY_DIAGONAL_LAND = {
    # Key order is diagonal land north-west, north-east, south-west, south-east.
    (True, False, False, False): 50,  # southeast water
    (False, True, False, False): 66,  # southwest water
    (False, False, True, False): 42,  # northeast water
    (False, False, False, True): 58,  # northwest water
}
_COAST_SMALL_BY_CARDINAL_LAND = {
    # Key order is cardinal land north, south, west, east around a water chunk.
    (True, False, True, False): (15, 15, 1020, 0),  # southeast
    (True, False, False, True): (7, 15, 834, 0),  # southwest
    (False, True, True, False): (15, 7, 1022, 0),  # northeast
    (False, True, False, True): (7, 7, 1012, 0),  # northwest
}

_MOUNTAIN_NORTH_SHAPE = 180
_MOUNTAIN_OUTSIDE_NORTH_WEST_SHAPE = 182
_MOUNTAIN_SOUTH_SHAPE = 183
_MOUNTAIN_VERTICAL_SHAPE = 969
_MOUNTAIN_GROUP_A_FIRST_FRAME = 0
_MOUNTAIN_GROUP_B_FIRST_FRAME = 4
_MOUNTAIN_GROUP_C_FIRST_FRAME = 8
_MOUNTAIN_BASE_DEFINITION = 1799
_MOUNTAIN_NORTH_EAST_CORNER_OBJECTS = (
    (7, 7, 182, 4),
    (15, 7, 969, 2),
    (7, 15, 182, 5),
    (15, 15, 983, 10),
)
_MOUNTAIN_SOUTH_EAST_OUTWARD_OBJECTS = (
    (7, 7, 180, 8),
    (15, 7, 180, 10),
    (7, 15, 983, 7),
    (15, 15, 180, 11),
)
_MOUNTAIN_SOUTH_WEST_OUTWARD_OBJECTS = (
    (7, 7, 180, 4),
    (15, 7, 180, 6),
    (7, 15, 180, 7),
    (15, 15, 180, 5),
)
_MOUNTAIN_INTERIOR_BANDS = {
    0: ("north-a", 180, _MOUNTAIN_GROUP_A_FIRST_FRAME),
    1: ("south-c", 183, _MOUNTAIN_GROUP_C_FIRST_FRAME),
    2: ("vertical-c", 969, _MOUNTAIN_GROUP_C_FIRST_FRAME),
    3: ("south-b", 183, _MOUNTAIN_GROUP_B_FIRST_FRAME),
}

_SI_BIOME_IDENTIFYING_TREE_SHAPES = {
    "evergreen": 306,
    "old_deciduous": 327,
    "autumn_deciduous": 670,
    "jungle": 453,
    "icy": 238,
}

_EVERGREEN_CUT_TREE_PATTERN = ((626, 627), (625, 624))
_EVERGREEN_POND_PATTERN = ((513, 463), (328, 265))
_OLD_DECIDUOUS_THICK_TREE_PATTERN = ((2585, 2586), (2917, 2680))

_RARE_FEATURE_FREQUENCY_SCALE = 0.25
_ONE_PER_BIOME_RARE_FEATURES = frozenset({"meadow_sinkhole"})
_MEADOW_SINKHOLE_BIOME_CHANCE_DENOMINATOR = 5

# These feature/biome associations are the conservative identities confirmed
# by the representative-area documents. SI reuses some individual definitions
# elsewhere, but those incidental contexts are not imported as new rules.
_SI_RARE_FEATURE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "evergreen_cut_tree_area",
        "biome": "evergreen",
        "patterns": (_EVERGREEN_CUT_TREE_PATTERN,),
    },
    {
        "name": "evergreen_pond",
        "biome": "evergreen",
        "patterns": (_EVERGREEN_POND_PATTERN,),
    },
    {
        "name": "old_deciduous_thick_tree_area",
        "biome": "old_deciduous",
        "patterns": (_OLD_DECIDUOUS_THICK_TREE_PATTERN,),
    },
    {
        "name": "meadow_sinkhole",
        "biome": "meadow",
        "patterns": (((1917,),),),
    },
    {
        "name": "evergreen_grass_clearing",
        "biome": "evergreen",
        "patterns": (((948,),),),
    },
    {
        "name": "old_deciduous_rock_pile",
        "biome": "old_deciduous",
        "patterns": (((906,),),),
    },
    {
        "name": "old_deciduous_dirt_clearing",
        "biome": "old_deciduous",
        "patterns": (((1613,),),),
    },
    {
        "name": "old_deciduous_dirt_clearing_with_rocks",
        "biome": "old_deciduous",
        "patterns": (((762,),),),
    },
    {
        "name": "autumn_deciduous_dirt_clearing_with_rocks",
        "biome": "autumn_deciduous",
        "patterns": (((762,),),),
    },
    {
        "name": "grass_dirt_and_rock_patches",
        "biome": "grass",
        "patterns": (
            ((1608,),),
            ((1609,),),
            ((1610,),),
            ((1611,),),
            ((990,),),
        ),
    },
)


def _decode_u3_overworld_row(encoded: bytes) -> list[int]:
    """Expand 32 packed U3 bytes into one 64-block row."""
    return [
        nibble for value in encoded for nibble in ((value >> 4) & 0x0F, value & 0x0F)
    ]


def load_embedded_u3_sosaria_overworld() -> list[list[int]]:
    """Load the canonical embedded 64x64 U3 NES Sosaria overworld."""
    if len(U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS) != U3_SOURCE_SIZE:
        raise RuntimeError(
            "Embedded U3 Sosaria row count mismatch: "
            f"found {len(U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS)}, "
            f"expected {U3_SOURCE_SIZE}"
        )

    packed_rows: list[bytes] = []
    for row_number, packed_hex in enumerate(U3_SOSARIA_OVERWORLD_PACKED_HEX_ROWS):
        try:
            encoded = bytes.fromhex(packed_hex)
        except ValueError as exc:
            raise RuntimeError(
                f"Embedded U3 Sosaria row {row_number} is not hexadecimal"
            ) from exc
        if len(encoded) != U3_SOURCE_SIZE // 2:
            raise RuntimeError(
                f"Embedded U3 Sosaria row {row_number} contains {len(encoded)} "
                f"bytes, expected {U3_SOURCE_SIZE // 2}"
            )
        packed_rows.append(encoded)

    packed = b"".join(packed_rows)
    packed_sha256 = hashlib.sha256(packed).hexdigest()
    if packed_sha256 != U3_SOSARIA_OVERWORLD_PACKED_SHA256:
        raise RuntimeError(
            "Embedded U3 Sosaria checksum mismatch: "
            f"found {packed_sha256}, expected {U3_SOSARIA_OVERWORLD_PACKED_SHA256}"
        )
    return [_decode_u3_overworld_row(encoded) for encoded in packed_rows]


def _weighted_choice(rng: random.Random, weights: dict[int, int]) -> int:
    values = list(weights)
    return rng.choices(values, weights=[weights[value] for value in values], k=1)[0]


def _nearest_location_environment(
    source: list[list[int]], source_x: int, source_y: int
) -> tuple[int, int]:
    """Choose the nearest surrounding grass, meadow, or forest source terrain."""
    for radius in range(1, U3_SOURCE_SIZE // 2 + 1):
        positions = {
            ((source_x + dx) % U3_SOURCE_SIZE, (source_y + dy) % U3_SOURCE_SIZE)
            for dy in range(-radius, radius + 1)
            for dx in range(-radius, radius + 1)
            if max(abs(dx), abs(dy)) == radius
        }
        counts = Counter(
            source[y][x]
            for x, y in positions
            if source[y][x] in U3_LOCATION_ENVIRONMENT_IDS
        )
        if counts:
            # Prefer the most common terrain on the nearest useful ring. The
            # numeric tie-break keeps the result deterministic without using
            # or perturbing the seeded decorative-terrain random stream.
            terrain_id = min(counts, key=lambda value: (-counts[value], value))
            return terrain_id, radius
    raise ValueError(
        f"U3 location ({source_x}, {source_y}) has no surrounding environment"
    )


def _nearest_forest_component(
    source: list[list[int]],
    component_grid: list[list[int]],
    source_x: int,
    source_y: int,
) -> int:
    """Join a forest-filled location to the nearest surrounding forest biome."""
    for radius in range(1, U3_SOURCE_SIZE // 2 + 1):
        positions = {
            ((source_x + dx) % U3_SOURCE_SIZE, (source_y + dy) % U3_SOURCE_SIZE)
            for dy in range(-radius, radius + 1)
            for dx in range(-radius, radius + 1)
            if max(abs(dx), abs(dy)) == radius
        }
        counts = Counter(
            component_grid[y][x] for x, y in positions if source[y][x] == 0x2
        )
        if counts:
            return min(counts, key=lambda value: (-counts[value], value))
    raise ValueError(f"U3 location ({source_x}, {source_y}) has no surrounding forest")


def _tree_components(
    source: list[list[int]],
) -> tuple[list[list[int]], list[list[tuple[int, int]]]]:
    component_grid = [[-1] * U3_SOURCE_SIZE for _ in range(U3_SOURCE_SIZE)]
    components: list[list[tuple[int, int]]] = []
    for start_y in range(U3_SOURCE_SIZE):
        for start_x in range(U3_SOURCE_SIZE):
            if source[start_y][start_x] != 0x2 or component_grid[start_y][start_x] >= 0:
                continue
            component_id = len(components)
            queue = deque([(start_x, start_y)])
            component_grid[start_y][start_x] = component_id
            cells: list[tuple[int, int]] = []
            while queue:
                x, y = queue.popleft()
                cells.append((x, y))
                for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                    nx = (x + dx) % U3_SOURCE_SIZE
                    ny = (y + dy) % U3_SOURCE_SIZE
                    if source[ny][nx] == 0x2 and component_grid[ny][nx] < 0:
                        component_grid[ny][nx] = component_id
                        queue.append((nx, ny))
            components.append(cells)
    return component_grid, components


def _definition_shapes(definitions: list[dict[str, Any]]) -> list[set[int]]:
    return [
        {cell["shape"] for cell in definition["cells"]} for definition in definitions
    ]


def _safe_forest_pools(definition_shapes: list[set[int]]) -> dict[str, dict[int, int]]:
    pools = copy.deepcopy(_FOREST_POOLS)
    pools["autumn_deciduous"] = {
        definition_id: weight
        for definition_id, weight in pools["autumn_deciduous"].items()
        if 1012 not in definition_shapes[definition_id]
    }
    pools["jungle"] = {
        definition_id: weight
        for definition_id, weight in pools["jungle"].items()
        if not (definition_shapes[definition_id] & ({12, 195, 196, 395, 396}))
    }
    if not pools["jungle"]:
        raise ValueError("U3 Sosaria builder found no clean jungle definitions")
    return pools


def _native_si_biome_grid(
    source_document: dict[str, Any],
) -> tuple[list[list[str | None]], Counter[str]]:
    """Classify native SI chunks by the representative biome identifiers."""
    definitions = source_document["definitions"]
    shape_counts = [
        Counter(cell["shape"] for cell in definition["cells"])
        for definition in definitions
    ]
    rows = source_document["map_layout"]["terrain_definition_ids"]
    biome_rows: list[list[str | None]] = []
    biome_counts: Counter[str] = Counter()
    for row in rows:
        biome_row: list[str | None] = []
        for definition_id in row:
            scores = {
                biome: shape_counts[definition_id][shape]
                for biome, shape in _SI_BIOME_IDENTIFYING_TREE_SHAPES.items()
            }
            best_biome = max(scores, key=lambda candidate: scores[candidate])
            biome: str | None = best_biome
            if scores[best_biome] == 0:
                if definition_id == 4:
                    biome = "meadow"
                elif definition_id in _GRASS_POOL:
                    biome = "grass"
                else:
                    biome = None
            biome_row.append(biome)
            if biome is not None:
                biome_counts[biome] += 1
        biome_rows.append(biome_row)
    return biome_rows, biome_counts


def _terrain_pattern_matches(
    rows: list[list[int]],
    pattern: tuple[tuple[int, ...], ...],
) -> list[tuple[int, int]]:
    """Find every exact, non-wrapping top-left placement of a terrain pattern."""
    pattern_height = len(pattern)
    pattern_width = len(pattern[0])
    return [
        (x, y)
        for y in range(len(rows) - pattern_height + 1)
        for x in range(len(rows[0]) - pattern_width + 1)
        if all(
            tuple(rows[y + offset_y][x : x + pattern_width]) == pattern[offset_y]
            for offset_y in range(pattern_height)
        )
    ]


def _nearest_native_biome(
    biome_rows: list[list[str | None]],
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    preferred_biome: str | None = None,
) -> str | None:
    """Identify the nearest surrounding native biome outside a feature group."""
    map_height = len(biome_rows)
    map_width = len(biome_rows[0])
    for radius in range(1, max(map_width, map_height)):
        counts: Counter[str] = Counter()
        for check_y in range(y - radius, y + height + radius):
            for check_x in range(x - radius, x + width + radius):
                if not (0 <= check_x < map_width and 0 <= check_y < map_height):
                    continue
                distance_x = (
                    0
                    if x <= check_x < x + width
                    else min(abs(check_x - x), abs(check_x - (x + width - 1)))
                )
                distance_y = (
                    0
                    if y <= check_y < y + height
                    else min(abs(check_y - y), abs(check_y - (y + height - 1)))
                )
                if max(distance_x, distance_y) != radius:
                    continue
                biome = biome_rows[check_y][check_x]
                if biome is not None:
                    counts[biome] += 1
        if counts:
            highest_count = max(counts.values())
            if (
                preferred_biome is not None
                and counts.get(preferred_biome, 0) == highest_count
            ):
                return preferred_biome
            return min(counts, key=lambda biome: (-counts[biome], biome))
    return None


def analyze_si_rare_feature_profiles(
    source_document: dict[str, Any],
) -> dict[str, Any]:
    """Count grouped rare feature placements per native SI biome chunk."""
    validate_u7_map_document(source_document)
    if source_document.get("game") != "si":
        raise ValueError("U3 rare feature analysis requires a Serpent Isle map")
    rows = source_document["map_layout"]["terrain_definition_ids"]
    biome_rows, biome_counts = _native_si_biome_grid(source_document)
    profiles: list[dict[str, Any]] = []
    for spec in _SI_RARE_FEATURE_SPECS:
        pattern_counts: list[dict[str, Any]] = []
        native_group_count = 0
        for pattern in spec["patterns"]:
            width = len(pattern[0])
            height = len(pattern)
            matches = [
                (x, y)
                for x, y in _terrain_pattern_matches(rows, pattern)
                if _nearest_native_biome(
                    biome_rows,
                    x,
                    y,
                    width,
                    height,
                    preferred_biome=spec["biome"],
                )
                == spec["biome"]
            ]
            native_group_count += len(matches)
            pattern_counts.append(
                {
                    "terrain_definition_ids": [list(row) for row in pattern],
                    "native_group_count": len(matches),
                }
            )
        native_biome_chunks = biome_counts[spec["biome"]]
        if not native_biome_chunks:
            raise ValueError(
                f"U3 rare feature analysis found no native {spec['biome']} chunks"
            )
        if not native_group_count:
            raise ValueError(
                f"U3 rare feature analysis found no {spec['name']} placements"
            )
        rate = native_group_count / native_biome_chunks
        profiles.append(
            {
                "name": spec["name"],
                "biome": spec["biome"],
                "native_group_count": native_group_count,
                "native_biome_chunks": native_biome_chunks,
                "placement_rate": rate,
                "placement_percent": round(rate * 100, 6),
                "patterns": pattern_counts,
            }
        )
    return {
        "method": "exact-pattern-count-per-identifying-native-biome-chunk",
        "native_biome_chunks": dict(sorted(biome_counts.items())),
        "profiles": profiles,
    }


def _generated_biome_candidates(
    biome_rows: list[list[str | None]],
    biome: str,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Find top-left anchors whose complete feature footprint stays in a biome."""
    map_height = len(biome_rows)
    map_width = len(biome_rows[0])
    return [
        (x, y)
        for y in range(map_height - height + 1)
        for x in range(map_width - width + 1)
        if all(
            biome_rows[y + offset_y][x + offset_x] == biome
            for offset_y in range(height)
            for offset_x in range(width)
        )
    ]


def _toroidal_biome_component_grid(
    biome_rows: list[list[str | None]],
    biome: str,
) -> tuple[list[list[int]], list[list[tuple[int, int]]]]:
    """Label four-way connected regions of one generated, wrapping biome."""
    map_height = len(biome_rows)
    map_width = len(biome_rows[0])
    component_grid = [[-1] * map_width for _ in range(map_height)]
    components: list[list[tuple[int, int]]] = []
    for start_y in range(map_height):
        for start_x in range(map_width):
            if (
                biome_rows[start_y][start_x] != biome
                or component_grid[start_y][start_x] >= 0
            ):
                continue
            component_id = len(components)
            queue = deque([(start_x, start_y)])
            component_grid[start_y][start_x] = component_id
            cells: list[tuple[int, int]] = []
            while queue:
                x, y = queue.popleft()
                cells.append((x, y))
                for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                    nx = (x + dx) % map_width
                    ny = (y + dy) % map_height
                    if biome_rows[ny][nx] == biome and component_grid[ny][nx] < 0:
                        component_grid[ny][nx] = component_id
                        queue.append((nx, ny))
            components.append(cells)
    return component_grid, components


def _place_seeded_rare_features(
    rows: list[list[int]],
    biome_rows: list[list[str | None]],
    native_analysis: dict[str, Any],
    *,
    seed: int,
) -> dict[str, Any]:
    """Apply quarter-rate rare groups plus chance-based Meadow sinkholes."""
    generated_biome_counts = Counter(
        biome for row in biome_rows for biome in row if biome is not None
    )
    occupied: set[tuple[int, int]] = set()
    placed_profiles: list[dict[str, Any]] = []
    for profile in native_analysis["profiles"]:
        pattern_entries = profile["patterns"]
        patterns = [
            tuple(tuple(row) for row in entry["terrain_definition_ids"])
            for entry in pattern_entries
        ]
        pattern_weights = [entry["native_group_count"] for entry in pattern_entries]
        widths = {len(pattern[0]) for pattern in patterns}
        heights = {len(pattern) for pattern in patterns}
        if len(widths) != 1 or len(heights) != 1:
            raise ValueError(
                f"U3 rare feature {profile['name']} variants differ in dimensions"
            )
        width = widths.pop()
        height = heights.pop()
        generated_biome_chunks = generated_biome_counts[profile["biome"]]
        effective_rate = profile["placement_rate"] * _RARE_FEATURE_FREQUENCY_SCALE
        raw_target = generated_biome_chunks * effective_rate
        target_groups = math.floor(raw_target + 0.5)
        if generated_biome_chunks and profile["native_group_count"]:
            target_groups = max(1, target_groups)

        candidates = _generated_biome_candidates(
            biome_rows,
            profile["biome"],
            width,
            height,
        )
        component_grid: list[list[int]] | None = None
        eligible_component_count: int | None = None
        selected_component_ids: set[int] | None = None
        if profile["name"] in _ONE_PER_BIOME_RARE_FEATURES:
            component_grid, _ = _toroidal_biome_component_grid(
                biome_rows,
                profile["biome"],
            )
            eligible_component_ids = {component_grid[y][x] for x, y in candidates}
            eligible_component_count = len(eligible_component_ids)
            chance_rng = random.Random(  # nosec B311
                f"{seed}:rare-feature:{profile['name']}:biome-chance"
            )
            selected_component_ids = {
                component_id
                for component_id in sorted(eligible_component_ids)
                if chance_rng.randrange(_MEADOW_SINKHOLE_BIOME_CHANCE_DENOMINATOR) == 0
            }
            target_groups = len(selected_component_ids)

        # Each feature owns an independent deterministic stream so adding a
        # later feature does not perturb established placement coordinates.
        feature_rng = random.Random(  # nosec B311
            f"{seed}:rare-feature:{profile['name']}"
        )
        feature_rng.shuffle(candidates)
        placements: list[dict[str, Any]] = []
        used_component_ids: set[int] = set()
        for x, y in candidates:
            if len(placements) == target_groups:
                break
            component_id = component_grid[y][x] if component_grid is not None else None
            if (
                selected_component_ids is not None
                and component_id not in selected_component_ids
            ):
                continue
            if component_id is not None and component_id in used_component_ids:
                continue
            footprint = {
                (x + offset_x, y + offset_y)
                for offset_y in range(height)
                for offset_x in range(width)
            }
            if footprint & occupied:
                continue
            pattern = feature_rng.choices(
                patterns,
                weights=pattern_weights,
                k=1,
            )[0]
            for offset_y, pattern_row in enumerate(pattern):
                for offset_x, definition_id in enumerate(pattern_row):
                    rows[y + offset_y][x + offset_x] = definition_id
            occupied.update(footprint)
            if component_id is not None:
                used_component_ids.add(component_id)
            placements.append(
                {
                    "chunk_x": x,
                    "chunk_y": y,
                    "width_chunks": width,
                    "height_chunks": height,
                    "terrain_definition_ids": [list(row) for row in pattern],
                    **(
                        {"biome_component_id": component_id}
                        if component_id is not None
                        else {}
                    ),
                }
            )
        if len(placements) != target_groups:
            raise ValueError(
                f"U3 rare feature {profile['name']} placed {len(placements)} of "
                f"{target_groups} requested groups"
            )
        placed_profiles.append(
            {
                **profile,
                "generated_biome_chunks": generated_biome_chunks,
                "frequency_scale": _RARE_FEATURE_FREQUENCY_SCALE,
                "effective_placement_rate": effective_rate,
                "effective_placement_percent": round(effective_rate * 100, 6),
                "raw_target_group_count": round(raw_target, 6),
                "target_group_count": target_groups,
                "placed_group_count": len(placements),
                "placed_chunk_count": len(placements) * width * height,
                **(
                    {
                        "per_biome_cap": 1,
                        "biome_component_connectivity": "four-way-toroidal",
                        "eligible_biome_component_count": eligible_component_count,
                        "biome_selection_chance": 1
                        / _MEADOW_SINKHOLE_BIOME_CHANCE_DENOMINATOR,
                        "biome_selection_chance_fraction": (
                            f"1/{_MEADOW_SINKHOLE_BIOME_CHANCE_DENOMINATOR}"
                        ),
                        "biome_chance_seed_stream": (
                            f"{seed}:rare-feature:{profile['name']}:biome-chance"
                        ),
                        "selected_biome_component_count": len(
                            selected_component_ids or ()
                        ),
                        "selected_biome_component_ids": sorted(
                            selected_component_ids or ()
                        ),
                    }
                    if eligible_component_count is not None
                    else {}
                ),
                "placements": placements,
            }
        )
    return {
        "method": "quarter-native-rate-with-seeded-component-chance-overrides",
        "seed_stream": f"{seed}:rare-feature:<feature-name>",
        "rate_basis": native_analysis["method"],
        "frequency_scale": _RARE_FEATURE_FREQUENCY_SCALE,
        "minimum_groups_for_present_biome": 1,
        "special_rules": {
            "meadow_sinkhole": {
                "maximum_groups_per_biome_component": 1,
                "biome_component_connectivity": "four-way-toroidal",
                "biome_selection_chance": 1 / _MEADOW_SINKHOLE_BIOME_CHANCE_DENOMINATOR,
                "biome_selection_chance_fraction": (
                    f"1/{_MEADOW_SINKHOLE_BIOME_CHANCE_DENOMINATOR}"
                ),
                "selection_seed_stream": (
                    f"{seed}:rare-feature:meadow_sinkhole:biome-chance"
                ),
            }
        },
        "native_biome_chunks": native_analysis["native_biome_chunks"],
        "generated_biome_chunks": dict(sorted(generated_biome_counts.items())),
        "profiles": placed_profiles,
        "total_groups": sum(
            profile["placed_group_count"] for profile in placed_profiles
        ),
        "total_chunks": len(occupied),
    }


def _mountain_upper_group_objects(
    chunk_x: int,
    chunk_y: int,
    *,
    shape: int,
    first_frame: int,
) -> list[dict[str, int]]:
    """Build one aligned 128x128 mountain face from four 64x64 quadrants."""
    base_tx = chunk_x * C_TILES_PER_CHUNK
    base_ty = chunk_y * C_TILES_PER_CHUNK
    return [
        {
            "tx": base_tx + local_x,
            "ty": base_ty + local_y,
            "tz": 5,
            "shape": shape,
            "frame": first_frame + frame_offset,
            "quality": 0,
        }
        for local_x, local_y, frame_offset in (
            (7, 7, 0),
            (15, 7, 2),
            (7, 15, 1),
            (15, 15, 3),
        )
    ]


def _mountain_local_objects(
    chunk_x: int,
    chunk_y: int,
    placements: tuple[tuple[int, int, int, int], ...],
) -> list[dict[str, int]]:
    """Place an exact SI mountain object recipe in one generated chunk."""
    base_tx = chunk_x * C_TILES_PER_CHUNK
    base_ty = chunk_y * C_TILES_PER_CHUNK
    return [
        {
            "tx": base_tx + local_x,
            "ty": base_ty + local_y,
            "tz": 5,
            "shape": shape,
            "frame": frame,
            "quality": 0,
        }
        for local_x, local_y, shape, frame in placements
    ]


def _rebuild_usage(document: dict[str, Any]) -> None:
    rows = document["map_layout"]["terrain_definition_ids"]
    positions: list[list[dict[str, int]]] = [[] for _ in document["definitions"]]
    for y, row in enumerate(rows):
        for x, definition_id in enumerate(row):
            positions[definition_id].append({"x": x, "y": y})
    for definition, world_chunks in zip(document["definitions"], positions):
        definition["world_chunks"] = world_chunks
        definition["usage_count"] = len(world_chunks)
    used = sum(1 for chunks in positions if chunks)
    document["counts"]["definitions"] = len(document["definitions"])
    document["counts"]["definitions_used"] = used
    document["counts"]["definitions_unused"] = len(positions) - used
    document["counts"]["map_chunk_references"] = C_NUM_CHUNKS * C_NUM_CHUNKS
    document["counts"]["fixed_objects"] = len(document.get("fixed_objects", []))


def _derived_terrain_definition(
    definitions: list[dict[str, Any]],
    base_definition_id: int,
    replacements: tuple[tuple[int, int, int, int], ...],
) -> int:
    """Append a terrain definition derived by replacing selected cells."""
    cells = copy.deepcopy(definitions[base_definition_id]["cells"])
    occupied: set[int] = set()
    for x, y, shape, frame in replacements:
        index = y * C_TILES_PER_CHUNK + x
        if index in occupied:
            raise ValueError(f"duplicate generated terrain cell ({x}, {y})")
        occupied.add(index)
        cells[index].update(
            {
                "shape": shape,
                "frame": frame,
                "kind": "flat" if shape < FIRST_OBJ_SHAPE else "rle",
            }
        )

    digest = hashlib.sha256()
    for cell in cells:
        digest.update(cell["shape"].to_bytes(4, "little"))
        digest.update(cell["frame"].to_bytes(4, "little"))
    pairs = {(cell["shape"], cell["frame"]) for cell in cells}
    definition_id = len(definitions)
    definitions.append(
        {
            "id": definition_id,
            "content_sha256": digest.hexdigest(),
            "usage_count": 0,
            "world_chunks": [],
            "statistics": {
                "flat_references": sum(cell["kind"] == "flat" for cell in cells),
                "rle_references": sum(cell["kind"] == "rle" for cell in cells),
                "distinct_shapes": len({cell["shape"] for cell in cells}),
                "distinct_shape_frames": len(pairs),
            },
            "cells": cells,
        }
    )
    return definition_id


def build_u3_nes_sosaria_map_document(
    source_document: dict[str, Any],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Build a U7 map from Titan's canonical embedded U3 Sosaria layout."""
    validate_u7_map_document(source_document)
    if source_document.get("game") != "si":
        raise ValueError("U3 Sosaria builder requires a Serpent Isle source document")
    source = load_embedded_u3_sosaria_overworld()
    source_packed_bytes = bytes(
        (row[index] << 4) | row[index + 1]
        for row in source
        for index in range(0, U3_SOURCE_SIZE, 2)
    )
    # Deterministic content generation, not cryptographic randomness.
    rng = random.Random(seed)  # nosec B311
    document = copy.deepcopy(source_document)
    definitions = document["definitions"]
    definition_shapes = _definition_shapes(definitions)
    forest_pools = _safe_forest_pools(definition_shapes)
    native_rare_feature_analysis = analyze_si_rare_feature_profiles(source_document)

    component_grid, components = _tree_components(source)
    forest_names = tuple(forest_pools)
    component_biomes = [rng.choice(forest_names) for _ in components]
    location_fills: dict[tuple[int, int], dict[str, Any]] = {}
    location_rngs: dict[tuple[int, int], random.Random] = {}
    for source_y, source_row in enumerate(source):
        for source_x, source_block in enumerate(source_row):
            if source_block not in U3_LOCATION_IDS:
                continue
            terrain_id, radius = _nearest_location_environment(
                source, source_x, source_y
            )
            forest_component = (
                _nearest_forest_component(
                    source,
                    component_grid,
                    source_x,
                    source_y,
                )
                if terrain_id == 0x2
                else None
            )
            location_fills[(source_x, source_y)] = {
                "source_block": source_block,
                "terrain_id": terrain_id,
                "search_radius": radius,
                "forest_component": forest_component,
            }
            location_rngs[(source_x, source_y)] = random.Random(  # nosec B311
                f"{seed}:location:{source_x}:{source_y}"
            )

    rows = [[1740] * C_NUM_CHUNKS for _ in range(C_NUM_CHUNKS)]
    biome_rows: list[list[str | None]] = [
        [None] * C_NUM_CHUNKS for _ in range(C_NUM_CHUNKS)
    ]
    water_mask = [[False] * C_NUM_CHUNKS for _ in range(C_NUM_CHUNKS)]
    mountain_mask = [[False] * C_NUM_CHUNKS for _ in range(C_NUM_CHUNKS)]

    for source_y in range(U3_SOURCE_SIZE):
        for source_x in range(U3_SOURCE_SIZE):
            block = source[source_y][source_x]
            location_fill = location_fills.get((source_x, source_y))
            effective_block = (
                location_fill["terrain_id"] if location_fill is not None else block
            )
            terrain_rng = (
                location_rngs[(source_x, source_y)]
                if location_fill is not None
                else rng
            )
            for local_y in range(U3_TO_U7_CHUNK_SCALE):
                target_y = source_y * U3_TO_U7_CHUNK_SCALE + local_y
                for local_x in range(U3_TO_U7_CHUNK_SCALE):
                    target_x = source_x * U3_TO_U7_CHUNK_SCALE + local_x
                    target_biome: str | None = None
                    if effective_block == 0x0:
                        definition_id = _weighted_choice(terrain_rng, _GRASS_POOL)
                        target_biome = "grass"
                    elif effective_block == 0x1:
                        definition_id = 4
                        target_biome = "meadow"
                    elif effective_block == 0x2:
                        component_id = (
                            location_fill["forest_component"]
                            if location_fill is not None
                            else component_grid[source_y][source_x]
                        )
                        biome = component_biomes[component_id]
                        definition_id = _weighted_choice(
                            terrain_rng, forest_pools[biome]
                        )
                        target_biome = biome
                    elif effective_block in U3_WATER_IDS:
                        definition_id = 1740
                        water_mask[target_y][target_x] = True
                    elif effective_block == 0x4:
                        definition_id = _MOUNTAIN_BASE_DEFINITION
                        mountain_mask[target_y][target_x] = True
                    elif effective_block == 0x7:
                        definition_id = 2271
                    else:
                        raise ValueError(
                            "U3 Sosaria builder has no mapping for "
                            f"block ${effective_block:X}"
                        )
                    rows[target_y][target_x] = definition_id
                    biome_rows[target_y][target_x] = target_biome

    rare_feature_construction = _place_seeded_rare_features(
        rows,
        biome_rows,
        native_rare_feature_analysis,
        seed=seed,
    )

    # Coast chunks occupy water next to land. Opposite map edges join. Cardinal
    # land corners use small grass-backed quarters; diagonal-only land uses the
    # complementary large water-major definition.
    coast_small_requests: dict[
        tuple[int, int], tuple[int, tuple[int, int, int, int]]
    ] = {}
    coast_large_diagonal_chunks = 0
    coast_water_chunks_with_small_diagonals = 0
    for y in range(C_NUM_CHUNKS):
        for x in range(C_NUM_CHUNKS):
            if not water_mask[y][x]:
                continue
            land_north = not water_mask[(y - 1) % C_NUM_CHUNKS][x]
            land_south = not water_mask[(y + 1) % C_NUM_CHUNKS][x]
            land_west = not water_mask[y][(x - 1) % C_NUM_CHUNKS]
            land_east = not water_mask[y][(x + 1) % C_NUM_CHUNKS]
            corner_key = (land_north, land_south, land_west, land_east)
            small_replacement = _COAST_SMALL_BY_CARDINAL_LAND.get(corner_key)
            if small_replacement is not None:
                coast_small_requests[(x, y)] = (
                    _MOUNTAIN_BASE_DEFINITION,
                    small_replacement,
                )
                coast_water_chunks_with_small_diagonals += 1
            elif not any(corner_key):
                diagonal_land_key = (
                    not water_mask[(y - 1) % C_NUM_CHUNKS][(x - 1) % C_NUM_CHUNKS],
                    not water_mask[(y - 1) % C_NUM_CHUNKS][(x + 1) % C_NUM_CHUNKS],
                    not water_mask[(y + 1) % C_NUM_CHUNKS][(x - 1) % C_NUM_CHUNKS],
                    not water_mask[(y + 1) % C_NUM_CHUNKS][(x + 1) % C_NUM_CHUNKS],
                )
                large_definition = _COAST_LARGE_BY_DIAGONAL_LAND.get(diagonal_land_key)
                if large_definition is not None:
                    rows[y][x] = large_definition
                    coast_large_diagonal_chunks += 1
            elif land_north and not (land_south or land_west or land_east):
                rows[y][x] = rng.choice(_COAST_POOLS["south"])
            elif land_south and not (land_north or land_west or land_east):
                rows[y][x] = rng.choice(_COAST_POOLS["north"])
            elif land_west and not (land_north or land_south or land_east):
                rows[y][x] = rng.choice(_COAST_POOLS["east"])
            elif land_east and not (land_north or land_south or land_west):
                rows[y][x] = rng.choice(_COAST_POOLS["west"])
            elif land_north:
                rows[y][x] = rng.choice(_COAST_POOLS["south"])
            elif land_south:
                rows[y][x] = rng.choice(_COAST_POOLS["north"])
            elif land_west:
                rows[y][x] = rng.choice(_COAST_POOLS["east"])
            elif land_east:
                rows[y][x] = rng.choice(_COAST_POOLS["west"])

    coast_derived_cache: dict[
        tuple[int, tuple[tuple[int, int, int, int], ...]], int
    ] = {}
    for (x, y), (base_definition_id, replacement) in sorted(
        coast_small_requests.items()
    ):
        replacements = (replacement,)
        cache_key = (base_definition_id, replacements)
        if cache_key not in coast_derived_cache:
            coast_derived_cache[cache_key] = _derived_terrain_definition(
                definitions,
                base_definition_id,
                replacements,
            )
        rows[y][x] = coast_derived_cache[cache_key]

    generated_fixed: list[dict[str, Any]] = []
    mountain_face_counts: Counter[str] = Counter()
    for y in range(C_NUM_CHUNKS):
        for x in range(C_NUM_CHUNKS):
            if not mountain_mask[y][x]:
                continue
            north_exposed = not mountain_mask[(y - 1) % C_NUM_CHUNKS][x]
            south_exposed = not mountain_mask[(y + 1) % C_NUM_CHUNKS][x]
            west_exposed = not mountain_mask[y][(x - 1) % C_NUM_CHUNKS]
            east_exposed = not mountain_mask[y][(x + 1) % C_NUM_CHUNKS]

            if north_exposed and west_exposed:
                face_name = "outside-north-west"
                rows[y][x] = _MOUNTAIN_BASE_DEFINITION
                mountain_face_counts[face_name] += 1
                generated_fixed.extend(
                    _mountain_upper_group_objects(
                        x,
                        y,
                        shape=_MOUNTAIN_OUTSIDE_NORTH_WEST_SHAPE,
                        first_frame=_MOUNTAIN_GROUP_A_FIRST_FRAME,
                    )
                )
                continue
            if north_exposed and east_exposed:
                face_name = "outside-north-east"
                rows[y][x] = _MOUNTAIN_BASE_DEFINITION
                mountain_face_counts[face_name] += 1
                generated_fixed.extend(
                    _mountain_local_objects(
                        x,
                        y,
                        _MOUNTAIN_NORTH_EAST_CORNER_OBJECTS,
                    )
                )
                continue
            if south_exposed and west_exposed:
                face_name = "outward-south-west"
                rows[y][x] = _MOUNTAIN_BASE_DEFINITION
                mountain_face_counts[face_name] += 1
                generated_fixed.extend(
                    _mountain_local_objects(
                        x,
                        y,
                        _MOUNTAIN_SOUTH_WEST_OUTWARD_OBJECTS,
                    )
                )
                continue
            if south_exposed and east_exposed:
                face_name = "outward-south-east"
                rows[y][x] = _MOUNTAIN_BASE_DEFINITION
                mountain_face_counts[face_name] += 1
                generated_fixed.extend(
                    _mountain_local_objects(
                        x,
                        y,
                        _MOUNTAIN_SOUTH_EAST_OUTWARD_OBJECTS,
                    )
                )
                continue

            if north_exposed:
                face_name = "north"
                shape = _MOUNTAIN_NORTH_SHAPE
                first_frame = _MOUNTAIN_GROUP_A_FIRST_FRAME
            elif south_exposed:
                face_name = "south"
                shape = _MOUNTAIN_SOUTH_SHAPE
                first_frame = _MOUNTAIN_GROUP_B_FIRST_FRAME
            elif west_exposed or east_exposed:
                face_name = "vertical"
                shape = _MOUNTAIN_VERTICAL_SHAPE
                first_frame = _MOUNTAIN_GROUP_C_FIRST_FRAME
            else:
                band_name, shape, first_frame = _MOUNTAIN_INTERIOR_BANDS[y % 4]
                face_name = f"interior-{band_name}"

            mountain_face_counts[face_name] += 1
            generated_fixed.extend(
                _mountain_upper_group_objects(
                    x,
                    y,
                    shape=shape,
                    first_frame=first_frame,
                )
            )

    document["map_layout"] = {
        "order": "row-major-yx",
        "wrap_x": True,
        "wrap_y": True,
        "terrain_definition_ids": rows,
    }
    document["fixed_objects"] = generated_fixed
    document["map_number"] = 0
    document["generation"] = {
        "generator": "titan.u3.map-create",
        "seed": seed,
        "source_map_packed_sha256": hashlib.sha256(source_packed_bytes).hexdigest(),
        "nibble_order": "high-nibble-left",
        "source_blocks_wide": U3_SOURCE_SIZE,
        "source_blocks_high": U3_SOURCE_SIZE,
        "u7_chunks_per_source_block": U3_TO_U7_CHUNK_SCALE,
        "forest_component_connectivity": "four-way-toroidal",
        "forest_components": len(components),
        "forest_component_biomes": component_biomes,
        "location_fill": {
            "method": "nearest-ring-majority-grass-meadow-or-forest",
            "eligible_source_blocks": {
                "grass": 0,
                "meadow": 1,
                "forest": 2,
            },
            "tie_break": "lowest-source-block-id",
            "locations": [
                {
                    "source_x": source_x,
                    "source_y": source_y,
                    "source_block": details["source_block"],
                    "replacement_block": details["terrain_id"],
                    "replacement_name": {0: "grass", 1: "meadow", 2: "forest"}[
                        details["terrain_id"]
                    ],
                    "search_radius": details["search_radius"],
                    **(
                        {"forest_biome": component_biomes[details["forest_component"]]}
                        if details["forest_component"] is not None
                        else {}
                    ),
                }
                for (source_x, source_y), details in sorted(location_fills.items())
            ],
        },
        "rare_feature_construction": rare_feature_construction,
        "water_definition": 1740,
        "coast_construction": {
            "method": "cardinal-small-and-diagonal-only-large-water-corners",
            "large_diagonal_chunks": coast_large_diagonal_chunks,
            "water_chunks_with_small_diagonals": coast_water_chunks_with_small_diagonals,
            "chunks_with_small_diagonals": len(coast_small_requests),
            "derived_small_definitions": len(coast_derived_cache),
        },
        "lava_definition": 2271,
        "mountain_construction": {
            "method": "clean-cardinal-contours-lower-diagonals-filled-interiors",
            "copied_source_terrain_definitions": False,
            "terrain_base_definition": _MOUNTAIN_BASE_DEFINITION,
            "north_group": {"shape": 180, "frames": [0, 1, 2, 3]},
            "south_group": {"shape": 183, "frames": [4, 5, 6, 7]},
            "vertical_group": {"shape": 969, "frames": [8, 9, 10, 11]},
            "outside_north_west_group": {"shape": 182, "frames": [0, 1, 2, 3]},
            "outside_north_east_objects": [
                {"local_x": x, "local_y": y, "shape": shape, "frame": frame}
                for x, y, shape, frame in _MOUNTAIN_NORTH_EAST_CORNER_OBJECTS
            ],
            "south_east_outward_objects": [
                {"local_x": x, "local_y": y, "shape": shape, "frame": frame}
                for x, y, shape, frame in _MOUNTAIN_SOUTH_EAST_OUTWARD_OBJECTS
            ],
            "south_west_outward_objects": [
                {"local_x": x, "local_y": y, "shape": shape, "frame": frame}
                for x, y, shape, frame in _MOUNTAIN_SOUTH_WEST_OUTWARD_OBJECTS
            ],
            "interior_bands_by_world_y_modulo_4": {
                str(modulus): {
                    "name": name,
                    "shape": shape,
                    "frames": list(range(first_frame, first_frame + 4)),
                }
                for modulus, (
                    name,
                    shape,
                    first_frame,
                ) in _MOUNTAIN_INTERIOR_BANDS.items()
            },
            "face_chunks": dict(sorted(mountain_face_counts.items())),
        },
    }
    _rebuild_usage(document)
    validate_u7_map_document(document)
    return document
