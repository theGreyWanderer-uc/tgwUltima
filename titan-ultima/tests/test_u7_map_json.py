from __future__ import annotations

from titan.u7.map import U7MapObject, U7MapRenderer
from titan.u7.map_json import validate_u7_map_document


def _one_definition_document() -> dict:
    cells = [
        {
            "index": index,
            "x": index % 16,
            "y": index // 16,
            "shape": 15,
            "frame": 0,
            "kind": "flat",
        }
        for index in range(256)
    ]
    positions = [{"x": x, "y": y} for y in range(192) for x in range(192)]
    return {
        "schema": "titan.u7.map",
        "schema_version": 1,
        "game": "si",
        "definitions": [
            {
                "id": 0,
                "cells": cells,
                "usage_count": len(positions),
                "world_chunks": positions,
            }
        ],
        "map_layout": {
            "order": "row-major-yx",
            "wrap_x": True,
            "wrap_y": True,
            "terrain_definition_ids": [[0] * 192 for _ in range(192)],
        },
        "fixed_objects": [],
    }


def test_validate_complete_universal_map_document() -> None:
    validate_u7_map_document(_one_definition_document())


def test_renderer_accepts_injected_map_and_fixed_objects() -> None:
    terrain_map = [[0] * 192 for _ in range(192)]
    terrain = [(15, 0)] * 256
    fixed = U7MapObject(tx=257, ty=3, tz=0, shape=180, frame=0)

    renderer = U7MapRenderer.from_map_data(
        "unused-static-path",
        terrain_map=terrain_map,
        terrains=[terrain],
        fixed_objects=[fixed],
        game="si",
    )

    assert renderer.terrain_map is terrain_map
    assert renderer.terrains == [terrain]
    assert renderer._fixed_objects_for_superchunk(1) == [fixed]
    assert renderer._fixed_objects_for_superchunk(0) == []
