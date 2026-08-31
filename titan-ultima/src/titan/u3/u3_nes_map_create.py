"""Create native U7 map data from Titan's embedded Ultima III NES world."""

from __future__ import annotations

__all__ = ["U3NesMapCreateResult", "create_u3_nes_sosaria_map"]

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from titan.u3.u3_nes_sosaria import build_u3_nes_sosaria_map_document
from titan.u7.map_json import load_u7_map_document, write_u7_map_document
from titan.u7.native_map_create import (
    U7NativeMapCreateResult,
    create_u7_native_map,
    format_u7_map_directory_name,
)


@dataclass(frozen=True)
class U3NesMapCreateResult:
    """Describe U3 generation plus optional native-map materialization."""

    map_number: int
    seed: int
    json_path: str | None
    json_only: bool
    dry_run: bool
    counts: dict[str, int]
    generation: dict[str, Any]
    native_map: U7NativeMapCreateResult | None


def create_u3_nes_sosaria_map(
    si_source_json: str | Path,
    output_root: str | Path,
    *,
    map_number: int = 4,
    seed: int = 42,
    json_output: str | Path | None = None,
    json_only: bool = False,
    pretty_json: bool = False,
    gamedat_root: str | Path | None = None,
    overwrite_map: bool = False,
    update_chunks: bool = False,
    dry_run: bool = False,
) -> U3NesMapCreateResult:
    """Generate U3 Sosaria, then optionally write one native U7 map namespace."""
    format_u7_map_directory_name(map_number)
    if json_only and json_output is None:
        raise ValueError("U3 map create --json-only requires --json-output")
    if json_only and dry_run:
        raise ValueError("U3 map create --json-only cannot be combined with --dry-run")

    source_document = load_u7_map_document(si_source_json)
    document = build_u3_nes_sosaria_map_document(source_document, seed=seed)
    document["map_number"] = map_number

    json_path: Path | None = None
    if json_output is not None and not dry_run:
        json_path = Path(json_output).resolve()
        write_u7_map_document(document, json_path, pretty=pretty_json)

    native_result: U7NativeMapCreateResult | None = None
    if not json_only:
        native_result = create_u7_native_map(
            output_root,
            map_number,
            source_document=document,
            source_label="titan.u3.map-create",
            gamedat_root=gamedat_root,
            overwrite_map=overwrite_map,
            update_chunks=update_chunks,
            dry_run=dry_run,
        )

    return U3NesMapCreateResult(
        map_number=map_number,
        seed=seed,
        json_path=str(json_path) if json_path is not None else None,
        json_only=json_only,
        dry_run=dry_run,
        counts=dict(document["counts"]),
        generation=dict(document["generation"]),
        native_map=native_result,
    )
