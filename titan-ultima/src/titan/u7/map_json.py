"""Universal JSON interchange for Ultima VII terrain maps and fixed objects."""

from __future__ import annotations

__all__ = [
    "U7_MAP_JSON_SCHEMA",
    "U7_MAP_JSON_VERSION",
    "build_u7_map_document",
    "load_u7_map_document",
    "renderer_from_u7_map_document",
    "validate_u7_map_document",
    "write_u7_map_document",
]

import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from titan.u7.map import (
    C_NUM_CHUNKS,
    C_NUM_SCHUNKS,
    C_TILE_SIZE,
    C_TILES_PER_CHUNK,
    U7MapObject,
    U7MapRenderer,
)
from titan.u7.names import U7ShapeNames
from titan.u7.shape import FIRST_OBJ_SHAPE, U7Shape


U7_MAP_JSON_SCHEMA = "titan.u7.map"
U7_MAP_JSON_VERSION = 1


class U7MapJsonError(ValueError):
    """Raised when universal U7 map JSON violates its schema contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _terrain_content_sha256(cells: list[tuple[int, int]]) -> str:
    digest = hashlib.sha256()
    for shape, frame in cells:
        digest.update(struct.pack("<II", shape, frame))
    return digest.hexdigest()


def _find_case_insensitive_file(directory: Path, filename: str) -> Path:
    direct = directory / filename
    if direct.is_file():
        return direct
    target = filename.lower()
    for candidate in directory.iterdir():
        if candidate.is_file() and candidate.name.lower() == target:
            return candidate
    raise U7MapJsonError(f"U7 map JSON source file missing: {directory / filename}")


def _source_map_directory(static_dir: Path, map_number: int) -> Path:
    return static_dir / f"map{map_number:02x}" if map_number > 0 else static_dir


def _chunks_format(chunks_data: bytes) -> tuple[str, int]:
    magic = b"\xff\xff\xff\xffexlt\x00\x00"
    if chunks_data.startswith(magic):
        payload_bytes = len(chunks_data) - len(magic)
        if payload_bytes < 0 or payload_bytes % 768:
            raise U7MapJsonError("U7 map JSON export found invalid V2 U7CHUNKS size")
        return "v2", 768
    if len(chunks_data) % 512:
        raise U7MapJsonError("U7 map JSON export found invalid V1 U7CHUNKS size")
    return "v1", 512


def _definition_record(
    definition_id: int,
    cells: list[tuple[int, int]],
    world_chunks: list[dict[str, int]],
) -> dict[str, Any]:
    flat_count = sum(1 for shape, _ in cells if shape < FIRST_OBJ_SHAPE)
    return {
        "id": definition_id,
        "content_sha256": _terrain_content_sha256(cells),
        "usage_count": len(world_chunks),
        "world_chunks": world_chunks,
        "statistics": {
            "flat_references": flat_count,
            "rle_references": len(cells) - flat_count,
            "distinct_shapes": len({shape for shape, _ in cells}),
            "distinct_shape_frames": len(set(cells)),
        },
        "cells": [
            {
                "index": index,
                "x": index % C_TILES_PER_CHUNK,
                "y": index // C_TILES_PER_CHUNK,
                "shape": shape,
                "frame": frame,
                "kind": "flat" if shape < FIRST_OBJ_SHAPE else "rle",
            }
            for index, (shape, frame) in enumerate(cells)
        ],
    }


def _shape_catalog(
    renderer: U7MapRenderer,
    referenced_pairs: set[tuple[int, int]],
) -> dict[str, Any]:
    names = U7ShapeNames.from_static_dir(renderer.static_dir)
    pairs_by_shape: dict[int, set[int]] = {}
    for shape, frame in referenced_pairs:
        pairs_by_shape.setdefault(shape, set()).add(frame)

    catalog: dict[str, Any] = {}
    records = renderer.shapes_vga.records
    for shape in sorted(pairs_by_shape):
        if shape >= len(records):
            continue
        is_tile = shape < FIRST_OBJ_SHAPE
        frame_count = U7Shape.count_frames_from_data(records[shape], is_tile=is_tile)
        shape_data = U7Shape.from_data(records[shape], is_tile=is_tile)
        frame_metadata: dict[str, Any] = {}
        for frame in sorted(pairs_by_shape[shape]):
            if frame < 0 or frame >= len(shape_data.frames):
                continue
            decoded = shape_data.frames[frame]
            frame_metadata[str(frame)] = {
                "width": decoded.width,
                "height": decoded.height,
                "hotspot_x_from_left": (
                    None if decoded.is_tile else decoded.hotspot_x_from_left
                ),
                "hotspot_y_from_top": (
                    None if decoded.is_tile else decoded.hotspot_y_from_top
                ),
            }
        catalog[str(shape)] = {
            "name": names.get(shape) if names else "",
            "is_tile_shape": is_tile,
            "frame_count": frame_count,
            "referenced_frames": frame_metadata,
        }
    return catalog


def build_u7_map_document(
    static_dir: str | Path,
    *,
    game: str = "bg",
    map_number: int = 0,
    include_fixed_objects: bool = True,
    include_shape_metadata: bool = True,
    wrap_x: bool = False,
    wrap_y: bool = False,
) -> dict[str, Any]:
    """Export terrain definitions, placement grid, and IFIX into one JSON object."""
    static_path = Path(static_dir)
    if not static_path.is_dir():
        raise U7MapJsonError(f"U7 map JSON STATIC directory missing: {static_path}")
    map_dir = _source_map_directory(static_path, map_number)
    chunks_path = _find_case_insensitive_file(static_path, "U7CHUNKS")
    map_path = _find_case_insensitive_file(map_dir, "U7MAP")
    chunks_data = chunks_path.read_bytes()
    chunks_format, chunks_record_bytes = _chunks_format(chunks_data)

    renderer = U7MapRenderer(str(static_path), map_num=map_number, game=game)
    terrains = renderer.terrains
    terrain_map = renderer.terrain_map

    usage: list[list[dict[str, int]]] = [[] for _ in terrains]
    map_rows: list[list[int]] = []
    for chunk_y in range(C_NUM_CHUNKS):
        row: list[int] = []
        for chunk_x in range(C_NUM_CHUNKS):
            definition_id = terrain_map[chunk_x][chunk_y]
            if definition_id < 0 or definition_id >= len(terrains):
                raise U7MapJsonError(
                    f"U7 map JSON terrain id {definition_id} at "
                    f"({chunk_x},{chunk_y}) exceeds {len(terrains)} definitions"
                )
            row.append(definition_id)
            usage[definition_id].append({"x": chunk_x, "y": chunk_y})
        map_rows.append(row)

    fixed_objects: list[dict[str, Any]] = []
    if include_fixed_objects:
        for superchunk in range(C_NUM_SCHUNKS * C_NUM_SCHUNKS):
            ifix_path = map_dir / f"U7IFIX{superchunk:02X}"
            for obj in renderer.parse_ifix(str(ifix_path), superchunk):
                fixed_objects.append(
                    {
                        "tx": obj.tx,
                        "ty": obj.ty,
                        "tz": obj.tz,
                        "shape": obj.shape,
                        "frame": obj.frame,
                        "quality": obj.quality,
                    }
                )

    definition_records = [
        _definition_record(index, cells, usage[index])
        for index, cells in enumerate(terrains)
    ]
    referenced_pairs = {
        (cell["shape"], cell["frame"])
        for definition in definition_records
        for cell in definition["cells"]
    }
    referenced_pairs.update((obj["shape"], obj["frame"]) for obj in fixed_objects)

    assets: dict[str, Any] = {}
    for filename in (
        "SHAPES.VGA",
        "PALETTES.FLX",
        "TFA.DAT",
        "SHPDIMS.DAT",
        "XFORM.TBL",
        "BLENDS.DAT",
    ):
        try:
            path = _find_case_insensitive_file(static_path, filename)
        except U7MapJsonError:
            continue
        assets[filename.lower()] = {
            "basename": path.name,
            "file_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }

    used_count = sum(1 for positions in usage if positions)
    document: dict[str, Any] = {
        "schema": U7_MAP_JSON_SCHEMA,
        "schema_version": U7_MAP_JSON_VERSION,
        "game": game.lower(),
        "map_number": map_number,
        "usage_included": True,
        "geometry": {
            "map_chunks_wide": C_NUM_CHUNKS,
            "map_chunks_high": C_NUM_CHUNKS,
            "definition_cells_wide": C_TILES_PER_CHUNK,
            "definition_cells_high": C_TILES_PER_CHUNK,
            "cell_pixels_wide": C_TILE_SIZE,
            "cell_pixels_high": C_TILE_SIZE,
            "definition_pixels_wide": C_TILES_PER_CHUNK * C_TILE_SIZE,
            "definition_pixels_high": C_TILES_PER_CHUNK * C_TILE_SIZE,
        },
        "source": {
            "chunks_format": chunks_format,
            "chunks_record_bytes": chunks_record_bytes,
            "chunks_file_bytes": chunks_path.stat().st_size,
            "chunks_sha256": _sha256_file(chunks_path),
            "map_file_bytes": map_path.stat().st_size,
            "map_sha256": _sha256_file(map_path),
            "assets": assets,
        },
        "counts": {
            "definitions": len(terrains),
            "definitions_used": used_count,
            "definitions_unused": len(terrains) - used_count,
            "map_chunk_references": C_NUM_CHUNKS * C_NUM_CHUNKS,
            "fixed_objects": len(fixed_objects),
        },
        "shape_catalog": (
            _shape_catalog(renderer, referenced_pairs) if include_shape_metadata else {}
        ),
        "definitions": definition_records,
        "map_layout": {
            "order": "row-major-yx",
            "wrap_x": bool(wrap_x),
            "wrap_y": bool(wrap_y),
            "terrain_definition_ids": map_rows,
        },
        "fixed_objects": fixed_objects,
    }
    validate_u7_map_document(document)
    return document


def _require_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise U7MapJsonError(f"U7 map JSON {field_name} must be integer >= {minimum}")
    return value


def validate_u7_map_document(document: dict[str, Any]) -> None:
    """Validate universal U7 map JSON structure and cross-references."""
    if not isinstance(document, dict):
        raise U7MapJsonError("U7 map JSON root must be an object")
    if document.get("schema") != U7_MAP_JSON_SCHEMA:
        raise U7MapJsonError(f"U7 map JSON schema must be {U7_MAP_JSON_SCHEMA!r}")
    if document.get("schema_version") != U7_MAP_JSON_VERSION:
        raise U7MapJsonError(
            f"U7 map JSON schema_version must be {U7_MAP_JSON_VERSION}"
        )

    definitions = document.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        raise U7MapJsonError("U7 map JSON definitions must be a non-empty array")
    seen_ids: set[int] = set()
    for definition in definitions:
        if not isinstance(definition, dict):
            raise U7MapJsonError("U7 map JSON definition must be an object")
        definition_id = _require_int(definition.get("id"), "definition.id")
        if definition_id in seen_ids:
            raise U7MapJsonError(f"U7 map JSON duplicate definition id {definition_id}")
        seen_ids.add(definition_id)
        cells = definition.get("cells")
        if not isinstance(cells, list) or len(cells) != 256:
            raise U7MapJsonError(
                f"U7 map JSON definition {definition_id} must contain 256 cells"
            )
        for expected_index, cell in enumerate(cells):
            if not isinstance(cell, dict):
                raise U7MapJsonError(
                    f"U7 map JSON definition {definition_id} cell must be object"
                )
            index = _require_int(cell.get("index"), "cell.index")
            if index != expected_index:
                raise U7MapJsonError(
                    f"U7 map JSON definition {definition_id} cell index "
                    f"{index} != {expected_index}"
                )
            if cell.get("x") != index % 16 or cell.get("y") != index // 16:
                raise U7MapJsonError(
                    f"U7 map JSON definition {definition_id} cell {index} coordinate mismatch"
                )
            shape = _require_int(cell.get("shape"), "cell.shape")
            _require_int(cell.get("frame"), "cell.frame")
            expected_kind = "flat" if shape < FIRST_OBJ_SHAPE else "rle"
            if cell.get("kind") != expected_kind:
                raise U7MapJsonError(
                    f"U7 map JSON definition {definition_id} cell {index} kind mismatch"
                )

    expected_ids = set(range(len(definitions)))
    if seen_ids != expected_ids:
        raise U7MapJsonError("U7 map JSON definition ids must be contiguous from zero")

    layout = document.get("map_layout")
    if not isinstance(layout, dict):
        raise U7MapJsonError("U7 map JSON map_layout must be an object")
    rows = layout.get("terrain_definition_ids")
    if not isinstance(rows, list) or len(rows) != C_NUM_CHUNKS:
        raise U7MapJsonError("U7 map JSON terrain grid must contain 192 rows")
    usage: Counter[int] = Counter()
    for y, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != C_NUM_CHUNKS:
            raise U7MapJsonError(
                f"U7 map JSON terrain grid row {y} must contain 192 ids"
            )
        for definition_id in row:
            _require_int(definition_id, "map terrain definition id")
            if definition_id not in seen_ids:
                raise U7MapJsonError(
                    f"U7 map JSON map references missing definition {definition_id}"
                )
            usage[definition_id] += 1

    for definition in definitions:
        definition_id = definition["id"]
        positions = definition.get("world_chunks")
        usage_count = definition.get("usage_count")
        if not isinstance(positions, list) or usage_count != len(positions):
            raise U7MapJsonError(
                f"U7 map JSON definition {definition_id} usage fields disagree"
            )
        if usage_count != usage[definition_id]:
            raise U7MapJsonError(
                f"U7 map JSON definition {definition_id} usage does not match map grid"
            )

    fixed_objects = document.get("fixed_objects", [])
    if not isinstance(fixed_objects, list):
        raise U7MapJsonError("U7 map JSON fixed_objects must be an array")
    max_tile = C_NUM_CHUNKS * C_TILES_PER_CHUNK - 1
    for obj in fixed_objects:
        if not isinstance(obj, dict):
            raise U7MapJsonError("U7 map JSON fixed object must be an object")
        tx = _require_int(obj.get("tx"), "fixed_object.tx")
        ty = _require_int(obj.get("ty"), "fixed_object.ty")
        if tx > max_tile or ty > max_tile:
            raise U7MapJsonError("U7 map JSON fixed object lies outside map")
        _require_int(obj.get("tz"), "fixed_object.tz")
        _require_int(obj.get("shape"), "fixed_object.shape")
        _require_int(obj.get("frame"), "fixed_object.frame")


def load_u7_map_document(path: str | Path) -> dict[str, Any]:
    """Load and validate one universal U7 map JSON file."""
    with Path(path).open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    validate_u7_map_document(document)
    return document


def write_u7_map_document(
    document: dict[str, Any],
    path: str | Path,
    *,
    pretty: bool = False,
) -> None:
    """Validate and write deterministic UTF-8 universal U7 map JSON."""
    validate_u7_map_document(document)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            document,
            handle,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            ensure_ascii=False,
        )
        handle.write("\n")


def renderer_from_u7_map_document(
    document: dict[str, Any],
    static_dir: str | Path,
    *,
    allow_asset_mismatch: bool = False,
) -> U7MapRenderer:
    """Create a JSON-backed renderer that never reads map/chunks/IFIX files."""
    validate_u7_map_document(document)
    static_path = Path(static_dir)
    if not static_path.is_dir():
        raise U7MapJsonError(f"U7 map JSON graphics directory missing: {static_path}")
    if not allow_asset_mismatch:
        for key, metadata in document.get("source", {}).get("assets", {}).items():
            if key not in {"shapes.vga", "tfa.dat", "shpdims.dat"}:
                continue
            candidate = _find_case_insensitive_file(static_path, metadata["basename"])
            if _sha256_file(candidate) != metadata["sha256"]:
                raise U7MapJsonError(
                    f"U7 map JSON asset hash mismatch: {metadata['basename']}"
                )

    definitions = sorted(document["definitions"], key=lambda item: item["id"])
    terrains = [
        [(cell["shape"], cell["frame"]) for cell in definition["cells"]]
        for definition in definitions
    ]
    rows = document["map_layout"]["terrain_definition_ids"]
    terrain_map = [
        [rows[chunk_y][chunk_x] for chunk_y in range(C_NUM_CHUNKS)]
        for chunk_x in range(C_NUM_CHUNKS)
    ]
    fixed_objects = [
        U7MapObject(
            tx=obj["tx"],
            ty=obj["ty"],
            tz=obj["tz"],
            shape=obj["shape"],
            frame=obj["frame"],
            quality=obj.get("quality", 0),
        )
        for obj in document.get("fixed_objects", [])
    ]
    return U7MapRenderer.from_map_data(
        str(static_path),
        terrain_map=terrain_map,
        terrains=terrains,
        fixed_objects=fixed_objects,
        game=document["game"],
    )
