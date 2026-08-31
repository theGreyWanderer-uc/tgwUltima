from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from titan.u7.map import U7MapRenderer
from titan.u7.map_json import write_u7_map_document
from titan.u7.native_map_create import (
    U7_MAP_BYTES,
    U7NativeMapCreateError,
    _decode_u7chunks,
    create_u7_native_map,
    format_u7_map_directory_name,
)


def _flat_definition(definition_id: int, shape: int) -> dict:
    return {
        "id": definition_id,
        "usage_count": 0,
        "world_chunks": [],
        "cells": [
            {
                "index": index,
                "x": index % 16,
                "y": index // 16,
                "shape": shape,
                "frame": 0,
                "kind": "flat",
            }
            for index in range(256)
        ],
    }


def _map_document(
    definition_shapes: list[int],
    *,
    layout_definition: int = 0,
    fixed_objects: list[dict] | None = None,
) -> dict:
    definitions = [
        _flat_definition(definition_id, shape)
        for definition_id, shape in enumerate(definition_shapes)
    ]
    rows = [[layout_definition] * 192 for _ in range(192)]
    positions = [{"x": x, "y": y} for y in range(192) for x in range(192)]
    definitions[layout_definition]["usage_count"] = len(positions)
    definitions[layout_definition]["world_chunks"] = positions
    return {
        "schema": "titan.u7.map",
        "schema_version": 1,
        "game": "si",
        "definitions": definitions,
        "map_layout": {
            "order": "row-major-yx",
            "wrap_x": True,
            "wrap_y": True,
            "terrain_definition_ids": rows,
        },
        "fixed_objects": fixed_objects or [],
    }


def _write_document(path: Path, document: dict) -> Path:
    write_u7_map_document(document, path, pretty=False)
    return path


def test_format_u7_map_directory_uses_two_digit_lowercase_hex() -> None:
    assert format_u7_map_directory_name(1) == "map01"
    assert format_u7_map_directory_name(3) == "map03"
    assert format_u7_map_directory_name(16) == "map10"
    assert format_u7_map_directory_name(255) == "mapff"


def test_empty_map_matches_exult_directory_only_behavior(tmp_path: Path) -> None:
    output_root = tmp_path / "arbitrary-output"

    result = create_u7_native_map(output_root, 1)

    map_directory = output_root / "map01"
    assert result.empty_map is True
    assert map_directory.is_dir()
    assert not (map_directory / "u7map").exists()
    assert (map_directory / "titan-map-create.json").is_file()


def test_materialized_empty_map_is_full_zero_u7map(tmp_path: Path) -> None:
    output_root = tmp_path / "test-output"

    create_u7_native_map(output_root, 2, materialize_empty=True)

    data = (output_root / "map02" / "u7map").read_bytes()
    assert len(data) == U7_MAP_BYTES
    assert data == bytes(U7_MAP_BYTES)


def test_existing_map_requires_explicit_overwrite_map(tmp_path: Path) -> None:
    output_root = tmp_path / "test-output"
    create_u7_native_map(output_root, 3)

    with pytest.raises(U7NativeMapCreateError, match="pass --overwrite-map"):
        create_u7_native_map(output_root, 3, materialize_empty=True)

    create_u7_native_map(
        output_root,
        3,
        materialize_empty=True,
        overwrite_map=True,
    )
    assert (output_root / "map03" / "u7map").stat().st_size == U7_MAP_BYTES


def test_optional_gamedat_uses_matching_map_namespace(tmp_path: Path) -> None:
    output_root = tmp_path / "patch"
    gamedat_root = tmp_path / "gamedat"

    create_u7_native_map(output_root, 10, gamedat_root=gamedat_root)

    assert (output_root / "map0a").is_dir()
    assert (gamedat_root / "map0a").is_dir()

    with pytest.raises(U7NativeMapCreateError, match="pass --overwrite-map"):
        create_u7_native_map(
            output_root,
            10,
            gamedat_root=gamedat_root,
        )
    create_u7_native_map(
        output_root,
        10,
        gamedat_root=gamedat_root,
        overwrite_map=True,
    )


def test_output_and_gamedat_roots_must_differ(tmp_path: Path) -> None:
    with pytest.raises(U7NativeMapCreateError, match="must be different"):
        create_u7_native_map(tmp_path, 1, gamedat_root=tmp_path)


def test_json_map_writes_native_chunks_layout_and_ifix(tmp_path: Path) -> None:
    output_root = tmp_path / "portable-map-root"
    source_json = _write_document(
        tmp_path / "map.json",
        _map_document(
            [15, 16],
            layout_definition=1,
            fixed_objects=[
                {
                    "tx": 7,
                    "ty": 7,
                    "tz": 5,
                    "shape": 180,
                    "frame": 0,
                    "quality": 0,
                }
            ],
        ),
    )

    result = create_u7_native_map(output_root, 4, source_json=source_json)

    map_directory = output_root / "map04"
    assert result.chunks_action == "create"
    assert result.ifix_files == 1
    chunks_format, definitions = _decode_u7chunks(
        (output_root / "u7chunks").read_bytes()
    )
    assert chunks_format == "v1"
    assert len(definitions) == 2
    assert definitions[1] == tuple([(16, 0)] * 256)
    u7map = (map_directory / "u7map").read_bytes()
    assert len(u7map) == U7_MAP_BYTES
    assert struct.unpack_from("<H", u7map, 0)[0] == 1
    objects = U7MapRenderer.parse_ifix(str(map_directory / "u7ifix00"), 0)
    assert [(obj.tx, obj.ty, obj.tz, obj.shape, obj.frame) for obj in objects] == [
        (7, 7, 5, 180, 0)
    ]
    manifest = json.loads((map_directory / "titan-map-create.json").read_text())
    assert manifest["source_json"] == "map.json"


def test_document_map_uses_shared_native_writer_and_source_label(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "document-map-root"
    document = _map_document([15], fixed_objects=[])

    result = create_u7_native_map(
        output_root,
        4,
        source_document=document,
        source_label="titan.u3.map-create",
    )

    assert result.empty_map is False
    assert (output_root / "map04" / "u7map").stat().st_size == U7_MAP_BYTES
    manifest = json.loads((output_root / "map04" / "titan-map-create.json").read_text())
    assert manifest["source"] == "titan.u3.map-create"
    assert "source_json" not in manifest


def test_native_writer_rejects_two_source_forms(tmp_path: Path) -> None:
    source_json = _write_document(tmp_path / "map.json", _map_document([15]))

    with pytest.raises(U7NativeMapCreateError, match="either source_json"):
        create_u7_native_map(
            tmp_path / "output",
            4,
            source_json=source_json,
            source_document=_map_document([15]),
        )


def test_json_map_uses_exult_v2_ifix_when_classic_limits_are_exceeded(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "portable-map-root"
    source_json = _write_document(
        tmp_path / "v2-map.json",
        _map_document(
            [15],
            fixed_objects=[
                {
                    "tx": 7,
                    "ty": 7,
                    "tz": 16,
                    "shape": 1024,
                    "frame": 64,
                    "quality": 0,
                }
            ],
        ),
    )

    create_u7_native_map(output_root, 6, source_json=source_json)

    ifix_path = output_root / "map06" / "u7ifix00"
    objects = U7MapRenderer.parse_ifix(str(ifix_path), 0)
    assert [(obj.tx, obj.ty, obj.tz, obj.shape, obj.frame) for obj in objects] == [
        (7, 7, 16, 1024, 64)
    ]


def test_json_map_verification_accepts_ifix_record_ordering(tmp_path: Path) -> None:
    """IFIX groups by chunk record even when source objects are interleaved."""
    output_root = tmp_path / "portable-map-root"
    fixed_objects = [
        {"tx": 7, "ty": 7, "tz": 0, "shape": 180, "frame": 0, "quality": 0},
        {"tx": 23, "ty": 7, "tz": 0, "shape": 320, "frame": 0, "quality": 0},
        {"tx": 8, "ty": 8, "tz": 0, "shape": 922, "frame": 22, "quality": 0},
    ]
    source_json = _write_document(
        tmp_path / "interleaved.json",
        _map_document([15], fixed_objects=fixed_objects),
    )

    create_u7_native_map(output_root, 7, source_json=source_json)

    objects = U7MapRenderer.parse_ifix(str(output_root / "map07" / "u7ifix00"), 0)
    actual = sorted((obj.tx, obj.ty, obj.tz, obj.shape, obj.frame) for obj in objects)
    expected = sorted(
        (obj["tx"], obj["ty"], obj["tz"], obj["shape"], obj["frame"])
        for obj in fixed_objects
    )
    assert actual == expected


def test_existing_chunks_reuse_content_and_remap_u7map(tmp_path: Path) -> None:
    output_root = tmp_path / "shared-map-root"
    first_json = _write_document(
        tmp_path / "first.json",
        _map_document([15, 16], layout_definition=0),
    )
    create_u7_native_map(output_root, 1, source_json=first_json)
    original_chunks = (output_root / "u7chunks").read_bytes()

    swapped_json = _write_document(
        tmp_path / "swapped.json",
        _map_document([16, 15], layout_definition=0),
    )
    result = create_u7_native_map(output_root, 2, source_json=swapped_json)

    assert result.chunks_action == "unchanged"
    assert result.remapped_definition_references == 192 * 192
    assert (output_root / "u7chunks").read_bytes() == original_chunks
    u7map = (output_root / "map02" / "u7map").read_bytes()
    assert struct.unpack_from("<H", u7map, 0)[0] == 1


def test_existing_chunks_require_update_permission_before_append(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "shared-map-root"
    first_json = _write_document(
        tmp_path / "first.json",
        _map_document([15], layout_definition=0),
    )
    create_u7_native_map(output_root, 1, source_json=first_json)
    expanded_json = _write_document(
        tmp_path / "expanded.json",
        _map_document([15, 16], layout_definition=1),
    )

    with pytest.raises(U7NativeMapCreateError, match="pass --update-chunks"):
        create_u7_native_map(output_root, 2, source_json=expanded_json)
    assert not (output_root / "map02").exists()

    result = create_u7_native_map(
        output_root,
        2,
        source_json=expanded_json,
        update_chunks=True,
    )
    assert result.definitions_appended == 1
    _, definitions = _decode_u7chunks((output_root / "u7chunks").read_bytes())
    assert len(definitions) == 2


def test_u7chunks_target_must_be_a_file(tmp_path: Path) -> None:
    output_root = tmp_path / "shared-map-root"
    (output_root / "u7chunks").mkdir(parents=True)
    source_json = _write_document(
        tmp_path / "map.json",
        _map_document([15], layout_definition=0),
    )

    with pytest.raises(U7NativeMapCreateError, match="u7chunks is not a file"):
        create_u7_native_map(output_root, 1, source_json=source_json)


def test_dry_run_writes_no_directories(tmp_path: Path) -> None:
    output_root = tmp_path / "absent-root"

    result = create_u7_native_map(
        output_root,
        5,
        materialize_empty=True,
        dry_run=True,
    )

    assert result.dry_run is True
    assert not output_root.exists()
