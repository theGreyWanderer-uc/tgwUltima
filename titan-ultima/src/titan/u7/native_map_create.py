"""Create native Exult map namespaces and materialize universal map JSON."""

from __future__ import annotations

__all__ = [
    "U7NativeMapCreateError",
    "U7NativeMapCreateResult",
    "create_u7_native_map",
    "format_u7_map_directory_name",
]

import hashlib
import json
import os
import shutil
import struct
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from titan.u7.flex import (
    U7_FLEX_EXULT_MAGIC2,
    U7FlexArchive,
)
from titan.u7.map import (
    C_CHUNKS_PER_SCHUNK,
    C_NUM_CHUNKS,
    C_NUM_SCHUNKS,
    C_TILES_PER_CHUNK,
    U7MapRenderer,
    _V2_CHUNKS_HDR_SIZE,
    _V2_CHUNKS_MAGIC,
)
from titan.u7.map_json import load_u7_map_document, validate_u7_map_document


U7_MAP_BYTES = C_NUM_CHUNKS * C_NUM_CHUNKS * 2
U7_IFIX_RECORD_COUNT = C_CHUNKS_PER_SCHUNK * C_CHUNKS_PER_SCHUNK


class U7NativeMapCreateError(ValueError):
    """Report a native U7 map creation or overwrite-safety failure."""


@dataclass(frozen=True)
class U7NativeMapCreateResult:
    """Describe files planned or written by native U7 map creation."""

    map_directory: str
    gamedat_directory: str | None
    map_number: int
    dry_run: bool
    empty_map: bool
    materialized_empty_map: bool
    u7map_bytes: int
    ifix_files: int
    fixed_objects: int
    chunks_action: str
    chunks_path: str | None
    definitions_written: int
    definitions_appended: int
    remapped_definition_references: int


def format_u7_map_directory_name(map_number: int) -> str:
    """Format a secondary U7 map directory as lowercase two-digit hexadecimal."""
    if not 1 <= map_number <= 0xFF:
        raise U7NativeMapCreateError(
            f"U7 map create map number must be 1..255, got {map_number}"
        )
    return f"map{map_number:02x}"


def _find_case_insensitive_child(root: Path, filename: str) -> Path:
    if root.is_dir():
        match = next(
            (
                child
                for child in root.iterdir()
                if child.name.lower() == filename.lower()
            ),
            None,
        )
        if match is not None:
            return match
    return root / filename.lower()


def _definition_cells(document: dict[str, Any]) -> list[tuple[tuple[int, int], ...]]:
    definitions = sorted(document["definitions"], key=lambda item: item["id"])
    if [definition["id"] for definition in definitions] != list(
        range(len(definitions))
    ):
        raise U7NativeMapCreateError(
            "U7 map create JSON definitions must use contiguous IDs starting at zero"
        )
    return [
        tuple((cell["shape"], cell["frame"]) for cell in definition["cells"])
        for definition in definitions
    ]


def _decode_u7chunks(data: bytes) -> tuple[str, list[tuple[tuple[int, int], ...]]]:
    is_v2 = data.startswith(_V2_CHUNKS_MAGIC)
    payload = data[_V2_CHUNKS_HDR_SIZE:] if is_v2 else data
    record_bytes = 768 if is_v2 else 512
    tile_bytes = 3 if is_v2 else 2
    if len(payload) % record_bytes:
        raise U7NativeMapCreateError(
            "U7 map create target u7chunks has invalid record-aligned size"
        )
    definitions: list[tuple[tuple[int, int], ...]] = []
    for base in range(0, len(payload), record_bytes):
        cells: list[tuple[int, int]] = []
        for index in range(256):
            offset = base + index * tile_bytes
            if is_v2:
                cells.append(
                    (
                        payload[offset] | (payload[offset + 1] << 8),
                        payload[offset + 2],
                    )
                )
            else:
                cells.append(
                    (
                        payload[offset] | ((payload[offset + 1] & 0x03) << 8),
                        (payload[offset + 1] >> 2) & 0x1F,
                    )
                )
        definitions.append(tuple(cells))
    return ("v2" if is_v2 else "v1"), definitions


def _encode_u7chunks(
    definitions: list[tuple[tuple[int, int], ...]], *, prefer_v2: bool
) -> bytes:
    use_v2 = prefer_v2 or any(
        shape > 0x3FF or frame > 0x1F
        for definition in definitions
        for shape, frame in definition
    )
    payload = bytearray()
    for definition in definitions:
        if len(definition) != 256:
            raise U7NativeMapCreateError(
                "U7 map create terrain definition must contain 256 cells"
            )
        for shape, frame in definition:
            if not 0 <= shape <= 0xFFFF or not 0 <= frame <= 0xFF:
                raise U7NativeMapCreateError(
                    f"U7 map create terrain shape/frame out of range: {shape}/{frame}"
                )
            if use_v2:
                payload.extend(struct.pack("<HB", shape, frame))
            else:
                payload.extend((shape & 0xFF, ((shape >> 8) & 0x03) | (frame << 2)))
    return (_V2_CHUNKS_MAGIC if use_v2 else b"") + bytes(payload)


def _merge_u7chunks(
    document: dict[str, Any],
    chunks_path: Path,
    *,
    update_chunks: bool,
) -> tuple[list[int], bytes | None, str, int, int]:
    if chunks_path.exists() and not chunks_path.is_file():
        raise U7NativeMapCreateError(
            f"U7 map create target u7chunks is not a file: {chunks_path}"
        )
    json_definitions = _definition_cells(document)
    referenced_ids = sorted(
        {
            definition_id
            for row in document["map_layout"]["terrain_definition_ids"]
            for definition_id in row
        }
    )

    if not chunks_path.is_file():
        encoded = _encode_u7chunks(json_definitions, prefer_v2=False)
        return (
            list(range(len(json_definitions))),
            encoded,
            "create",
            len(json_definitions),
            0,
        )

    target_format, target_definitions = _decode_u7chunks(chunks_path.read_bytes())
    target_by_content: dict[tuple[tuple[int, int], ...], int] = {}
    for definition_id, definition in enumerate(target_definitions):
        target_by_content.setdefault(definition, definition_id)

    remap = list(range(len(json_definitions)))
    appended = 0
    for definition_id in referenced_ids:
        definition = json_definitions[definition_id]
        if (
            definition_id < len(target_definitions)
            and target_definitions[definition_id] == definition
        ):
            remap[definition_id] = definition_id
            continue
        existing_id = target_by_content.get(definition)
        if existing_id is not None:
            remap[definition_id] = existing_id
            continue
        new_id = len(target_definitions)
        if new_id > 0xFFFF:
            raise U7NativeMapCreateError(
                "U7 map create merged terrain definitions exceed 16-bit U7MAP IDs"
            )
        target_definitions.append(definition)
        target_by_content[definition] = new_id
        remap[definition_id] = new_id
        appended += 1

    if not appended:
        return remap, None, "unchanged", len(target_definitions), 0
    if not update_chunks:
        raise U7NativeMapCreateError(
            "U7 map create target u7chunks needs new definitions; "
            "pass --update-chunks to permit shared terrain update"
        )
    encoded = _encode_u7chunks(
        target_definitions,
        prefer_v2=target_format == "v2",
    )
    return remap, encoded, "append", len(target_definitions), appended


def _encode_u7map(document: dict[str, Any], remap: list[int]) -> bytes:
    rows = document["map_layout"]["terrain_definition_ids"]
    output = bytearray()
    for superchunk in range(C_NUM_SCHUNKS * C_NUM_SCHUNKS):
        base_chunk_x = (superchunk % C_NUM_SCHUNKS) * C_CHUNKS_PER_SCHUNK
        base_chunk_y = (superchunk // C_NUM_SCHUNKS) * C_CHUNKS_PER_SCHUNK
        for local_y in range(C_CHUNKS_PER_SCHUNK):
            for local_x in range(C_CHUNKS_PER_SCHUNK):
                definition_id = rows[base_chunk_y + local_y][base_chunk_x + local_x]
                output.extend(struct.pack("<H", remap[definition_id]))
    if len(output) != U7_MAP_BYTES:
        raise U7NativeMapCreateError(
            f"U7 map create encoded u7map has {len(output)} bytes, expected {U7_MAP_BYTES}"
        )
    return bytes(output)


def _encode_ifix_archives(
    document: dict[str, Any], map_number: int
) -> dict[int, bytes]:
    records_by_superchunk: dict[int, list[bytearray]] = {}
    needs_v2: dict[int, bool] = {}
    for obj in document.get("fixed_objects", []):
        tx = obj["tx"]
        ty = obj["ty"]
        lift = obj["tz"]
        shape = obj["shape"]
        frame = obj["frame"]
        quality = obj.get("quality", 0)
        if quality:
            raise U7NativeMapCreateError(
                "U7 map create IFIX cannot encode nonzero fixed-object quality"
            )
        chunk_x = tx // C_TILES_PER_CHUNK
        chunk_y = ty // C_TILES_PER_CHUNK
        superchunk = (
            chunk_y // C_CHUNKS_PER_SCHUNK * C_NUM_SCHUNKS
            + chunk_x // C_CHUNKS_PER_SCHUNK
        )
        if not 0 <= superchunk < C_NUM_SCHUNKS * C_NUM_SCHUNKS:
            raise U7NativeMapCreateError(
                f"U7 map create fixed object lies outside map: ({tx}, {ty})"
            )
        chunk_record = (
            chunk_y % C_CHUNKS_PER_SCHUNK
        ) * C_CHUNKS_PER_SCHUNK + chunk_x % C_CHUNKS_PER_SCHUNK
        records = records_by_superchunk.setdefault(
            superchunk, [bytearray() for _ in range(U7_IFIX_RECORD_COUNT)]
        )
        use_v2 = shape > 0x3FF or frame > 0x3F or lift > 0x0F
        needs_v2[superchunk] = needs_v2.get(superchunk, False) or use_v2
        if not 0 <= shape <= 0xFFFF or not 0 <= frame <= 0xFF or not 0 <= lift <= 0xFF:
            raise U7NativeMapCreateError(
                f"U7 map create fixed object exceeds V2 IFIX limits: {obj}"
            )
        local_position = ((tx % 16) << 4) | (ty % 16)
        if use_v2:
            entry = struct.pack("<BBHB", local_position, lift, shape, frame)
        else:
            entry = bytes(
                (
                    local_position,
                    lift,
                    shape & 0xFF,
                    ((shape >> 8) & 0x03) | (frame << 2),
                )
            )
        records[chunk_record].extend(entry)

    archives: dict[int, bytes] = {}
    for superchunk, record_buffers in records_by_superchunk.items():
        use_v2 = needs_v2[superchunk]
        if use_v2:
            # Re-encode any classic entries because one archive has one IFIX version.
            rebuilt = [bytearray() for _ in range(U7_IFIX_RECORD_COUNT)]
            for obj in document.get("fixed_objects", []):
                chunk_x = obj["tx"] // C_TILES_PER_CHUNK
                chunk_y = obj["ty"] // C_TILES_PER_CHUNK
                obj_superchunk = (
                    chunk_y // C_CHUNKS_PER_SCHUNK * C_NUM_SCHUNKS
                    + chunk_x // C_CHUNKS_PER_SCHUNK
                )
                if obj_superchunk != superchunk:
                    continue
                chunk_record = (
                    chunk_y % C_CHUNKS_PER_SCHUNK
                ) * C_CHUNKS_PER_SCHUNK + chunk_x % C_CHUNKS_PER_SCHUNK
                rebuilt[chunk_record].extend(
                    struct.pack(
                        "<BBHB",
                        ((obj["tx"] % 16) << 4) | (obj["ty"] % 16),
                        obj["tz"],
                        obj["shape"],
                        obj["frame"],
                    )
                )
            record_buffers = rebuilt
        archive = U7FlexArchive()
        archive.title = "Exult" if use_v2 else f"Titan map{map_number:02x} IFIX"
        archive.records = [bytes(record) for record in record_buffers]
        if use_v2:
            archive.magic2 = U7_FLEX_EXULT_MAGIC2 + 1
        archives[superchunk] = archive.to_bytes()
    return archives


def _write_manifest(
    map_directory: Path,
    result: U7NativeMapCreateResult,
    *,
    source_json: Path | None,
    source_label: str | None,
) -> None:
    manifest: dict[str, Any] = {
        "schema": "titan.u7.native-map-create",
        "schema_version": 1,
        **asdict(result),
    }
    if source_json is not None:
        manifest["source_json"] = source_json.name
        manifest["source_json_sha256"] = hashlib.sha256(
            source_json.read_bytes()
        ).hexdigest()
    if source_label is not None:
        manifest["source"] = source_label
    (map_directory / "titan-map-create.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _fixed_object_signature(obj: Any) -> tuple[int, int, int, int, int]:
    return (obj.tx, obj.ty, obj.tz, obj.shape, obj.frame)


def _verify_staged_native_map(
    staged_map: Path,
    *,
    document: dict[str, Any] | None,
    u7map_bytes: bytes,
    ifix_archives: dict[int, bytes],
) -> None:
    """Read staged native files back and compare layout and fixed objects."""
    if u7map_bytes and (staged_map / "u7map").read_bytes() != u7map_bytes:
        raise U7NativeMapCreateError(
            "U7 map create staged u7map verification content mismatch"
        )
    if document is None:
        return

    expected_by_superchunk: dict[int, list[tuple[int, int, int, int, int]]] = {}
    for obj in document.get("fixed_objects", []):
        chunk_x = obj["tx"] // C_TILES_PER_CHUNK
        chunk_y = obj["ty"] // C_TILES_PER_CHUNK
        superchunk = (
            chunk_y // C_CHUNKS_PER_SCHUNK * C_NUM_SCHUNKS
            + chunk_x // C_CHUNKS_PER_SCHUNK
        )
        expected_by_superchunk.setdefault(superchunk, []).append(
            (obj["tx"], obj["ty"], obj["tz"], obj["shape"], obj["frame"])
        )

    if set(expected_by_superchunk) != set(ifix_archives):
        raise U7NativeMapCreateError(
            "U7 map create staged IFIX verification superchunk set mismatch"
        )
    for superchunk, expected in expected_by_superchunk.items():
        ifix_path = staged_map / f"u7ifix{superchunk:02x}"
        archive = U7FlexArchive.from_file(str(ifix_path))
        if len(archive.records) != U7_IFIX_RECORD_COUNT:
            raise U7NativeMapCreateError(
                f"U7 map create staged IFIX {superchunk:02x} has "
                f"{len(archive.records)} records"
            )
        actual = [
            _fixed_object_signature(obj)
            for obj in U7MapRenderer.parse_ifix(str(ifix_path), superchunk)
        ]
        # IFIX serializes objects by chunk record. Input JSON may interleave
        # objects from different chunks, so round-trip order is not stable.
        # Counter retains duplicate signatures while comparing content only.
        if Counter(actual) != Counter(expected):
            raise U7NativeMapCreateError(
                f"U7 map create staged IFIX {superchunk:02x} verification mismatch"
            )


def _replace_staged_directory(staged: Path, target: Path) -> None:
    backup: Path | None = None
    if target.exists():
        backup = target.with_name(f".{target.name}.titan-backup-{uuid.uuid4().hex}")
        target.rename(backup)
    try:
        staged.rename(target)
    except OSError:
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def create_u7_native_map(
    output_root: str | Path,
    map_number: int,
    *,
    source_json: str | Path | None = None,
    source_document: dict[str, Any] | None = None,
    source_label: str | None = None,
    gamedat_root: str | Path | None = None,
    materialize_empty: bool = False,
    overwrite_map: bool = False,
    update_chunks: bool = False,
    dry_run: bool = False,
) -> U7NativeMapCreateResult:
    """Create one native secondary map using only caller-supplied destinations."""
    map_name = format_u7_map_directory_name(map_number)
    output_path = Path(output_root).resolve()
    map_directory = output_path / map_name
    gamedat_path = Path(gamedat_root).resolve() if gamedat_root is not None else None
    gamedat_directory = gamedat_path / map_name if gamedat_path is not None else None
    if map_directory.exists() and not overwrite_map:
        raise U7NativeMapCreateError(
            f"U7 map create target exists: {map_directory}; pass --overwrite-map"
        )
    if map_directory.exists() and not map_directory.is_dir():
        raise U7NativeMapCreateError(
            f"U7 map create target is not a directory: {map_directory}"
        )
    if (
        gamedat_directory is not None
        and gamedat_directory.exists()
        and not overwrite_map
    ):
        raise U7NativeMapCreateError(
            f"U7 map create GAMEDAT target exists: {gamedat_directory}; "
            "pass --overwrite-map"
        )
    if (
        gamedat_directory is not None
        and gamedat_directory.exists()
        and not gamedat_directory.is_dir()
    ):
        raise U7NativeMapCreateError(
            f"U7 map create GAMEDAT target is not a directory: {gamedat_directory}"
        )
    if gamedat_path is not None and gamedat_path == output_path:
        raise U7NativeMapCreateError(
            "U7 map create output root and GAMEDAT root must be different"
        )
    if source_json is not None and source_document is not None:
        raise U7NativeMapCreateError(
            "U7 map create accepts either source_json or source_document, not both"
        )
    if (source_json is not None or source_document is not None) and materialize_empty:
        raise U7NativeMapCreateError(
            "U7 map create --materialize-empty cannot be combined with --from-json"
        )

    document: dict[str, Any] | None = None
    source_json_path: Path | None = None
    remap: list[int] = []
    chunks_bytes: bytes | None = None
    chunks_action = "not-needed"
    definitions_written = 0
    definitions_appended = 0
    u7map_bytes = b""
    ifix_archives: dict[int, bytes] = {}
    chunks_path: Path | None = None

    if source_json is not None:
        source_json_path = Path(source_json).resolve()
        document = load_u7_map_document(source_json_path)
    elif source_document is not None:
        validate_u7_map_document(source_document)
        document = source_document

    if document is not None:
        chunks_path = _find_case_insensitive_child(output_path, "u7chunks")
        (
            remap,
            chunks_bytes,
            chunks_action,
            definitions_written,
            definitions_appended,
        ) = _merge_u7chunks(document, chunks_path, update_chunks=update_chunks)
        u7map_bytes = _encode_u7map(document, remap)
        ifix_archives = _encode_ifix_archives(document, map_number)
    elif materialize_empty:
        u7map_bytes = bytes(U7_MAP_BYTES)

    remapped_references = 0
    if document is not None:
        remapped_references = sum(
            remap[definition_id] != definition_id
            for row in document["map_layout"]["terrain_definition_ids"]
            for definition_id in row
        )
    result = U7NativeMapCreateResult(
        map_directory=str(map_directory),
        gamedat_directory=(
            str(gamedat_directory) if gamedat_directory is not None else None
        ),
        map_number=map_number,
        dry_run=dry_run,
        empty_map=document is None,
        materialized_empty_map=document is None and materialize_empty,
        u7map_bytes=len(u7map_bytes),
        ifix_files=len(ifix_archives),
        fixed_objects=(len(document.get("fixed_objects", [])) if document else 0),
        chunks_action=chunks_action,
        chunks_path=str(chunks_path) if chunks_path is not None else None,
        definitions_written=definitions_written,
        definitions_appended=definitions_appended,
        remapped_definition_references=remapped_references,
    )
    if dry_run:
        return result

    output_path.mkdir(parents=True, exist_ok=True)
    staged_map = Path(tempfile.mkdtemp(prefix=f".{map_name}.titan-", dir=output_path))
    staged_gamedat: Path | None = None
    staged_chunks: Path | None = None
    try:
        if u7map_bytes:
            (staged_map / "u7map").write_bytes(u7map_bytes)
        for superchunk, archive_bytes in sorted(ifix_archives.items()):
            (staged_map / f"u7ifix{superchunk:02x}").write_bytes(archive_bytes)
        _write_manifest(
            staged_map,
            result,
            source_json=source_json_path,
            source_label=source_label,
        )

        if gamedat_path is not None:
            gamedat_path.mkdir(parents=True, exist_ok=True)
            staged_gamedat = Path(
                tempfile.mkdtemp(prefix=f".{map_name}.titan-", dir=gamedat_path)
            )

        if chunks_bytes is not None and chunks_path is not None:
            descriptor, staged_chunks_name = tempfile.mkstemp(
                prefix=".u7chunks.titan-", dir=output_path
            )
            os.close(descriptor)
            staged_chunks = Path(staged_chunks_name)
            staged_chunks.write_bytes(chunks_bytes)
            _, written_definitions = _decode_u7chunks(staged_chunks.read_bytes())
            if len(written_definitions) != definitions_written:
                raise U7NativeMapCreateError(
                    "U7 map create staged u7chunks verification count mismatch"
                )

        _verify_staged_native_map(
            staged_map,
            document=document,
            u7map_bytes=u7map_bytes,
            ifix_archives=ifix_archives,
        )

        if staged_chunks is not None and chunks_path is not None:
            os.replace(staged_chunks, chunks_path)
            staged_chunks = None
        _replace_staged_directory(staged_map, map_directory)
        if staged_gamedat is not None and gamedat_directory is not None:
            _replace_staged_directory(staged_gamedat, gamedat_directory)
            staged_gamedat = None
    finally:
        if staged_map.exists():
            shutil.rmtree(staged_map)
        if staged_gamedat is not None and staged_gamedat.exists():
            shutil.rmtree(staged_gamedat)
        if staged_chunks is not None and staged_chunks.exists():
            staged_chunks.unlink()
    return result
