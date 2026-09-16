"""Export a U9 rigid model hierarchy, exact clip tracks, and animated GLB.

The versioned JSON sidecar is the authoritative interchange record. Separate
OBJ meshes remain in each limb's local coordinates, while the GLB is a useful
Y-up presentation that applies the runtime-compatible single-clip rules.
"""

from __future__ import annotations

__all__ = [
    "ANIMATED_MODEL_BUNDLE_SCHEMA",
    "ANIMATED_MODEL_BUNDLE_SCHEMA_VERSION",
    "DEFAULT_ANIMATED_MODEL_SCALE",
    "U9AnimatedModelBundleError",
    "U9AnimatedModelBundleResult",
    "export_animated_model_bundle",
]

import hashlib
import io
import json
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from titan.u9.animation import U9Animation, U9AnimationPart
from titan.u9.mesh_export import (
    MeshExportError,
    TextureResolver,
    export_limb_obj,
    limb_local_triangles,
)
from titan.u9.model import MATERIAL_ALPHA_NONE, U9Limb, U9Material, U9Model
from titan.u9.node_registry import U9NodeRegistry
from titan.u9.transform import mat4_trs

ANIMATED_MODEL_BUNDLE_SCHEMA = "titan.u9.rigid-animated-model"
ANIMATED_MODEL_BUNDLE_SCHEMA_VERSION = 1
DEFAULT_ANIMATED_MODEL_SCALE = 1.0 / 40.0

_ARRAY_BUFFER = 34962
_FLOAT = 5126

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


class U9AnimatedModelBundleError(Exception):
    """Raised when a model and clip cannot form a rigid animation bundle."""


@dataclass(frozen=True)
class U9AnimatedModelBundleResult:
    """Paths and counts written by one rigid animated-model export."""

    sidecar_path: Path
    glb_path: Path | None
    limb_mesh_paths: tuple[Path, ...]
    part_count: int
    mesh_count: int
    track_count: int
    matched_track_count: int
    authoring_only_track_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _input_record(role: str, path: str | Path) -> dict[str, object]:
    resolved = Path(path)
    if not resolved.is_file():
        raise U9AnimatedModelBundleError(f"{role} input not found: {resolved}")
    return {
        "role": role,
        "name": resolved.name,
        "byte_size": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return cleaned or "unnamed"


def _part_names(
    model: U9Model,
    animation: U9Animation,
    registry: U9NodeRegistry | None,
) -> tuple[str, ...]:
    animation_names = {part.part_id: part.name for part in animation.parts}
    return tuple(
        (
            registry.name_for(limb.limb_id)
            if registry is not None
            else animation_names.get(limb.limb_id)
        )
        or f"part_{limb.limb_id}"
        for limb in model.limbs
    )


def _parent_indices(model: U9Model) -> tuple[int | None, ...]:
    first_index_for_id: dict[int, int] = {}
    for index, limb in enumerate(model.limbs):
        first_index_for_id.setdefault(limb.limb_id, index)
    parents: list[int | None] = []
    for index, limb in enumerate(model.limbs):
        parent = first_index_for_id.get(limb.parent_id)
        parents.append(None if limb.is_root or parent == index else parent)

    for start in range(len(parents)):
        seen = {start}
        current = parents[start]
        while current is not None:
            if current in seen:
                parents[start] = None
                break
            seen.add(current)
            current = parents[current]
    return tuple(parents)


def _material_record(
    part_index: int,
    lod_index: int,
    material_index: int,
    material: U9Material,
) -> dict[str, object]:
    return {
        "part_index": part_index,
        "lod_index": lod_index,
        "material_index": material_index,
        "texture_id": material.texture_id,
        "flags_02": material.flags_02,
        "render_flags": material.render_flags,
        "flags_06": material.flags_06,
        "first_face": material.first_face,
        "face_count": material.face_count,
        "default_alpha": material.default_alpha,
        "modified_alpha": material.modified_alpha,
        "animation": {
            "start_frame": material.anim_start,
            "end_frame": material.anim_end,
            "current_frame": material.cur_frame,
            "speed": material.anim_speed,
            "type": material.animation_type,
            "playback_direction": material.playback_direction,
            "timer": material.animation_timer,
        },
        "decoded_flags": {
            "invisible": material.is_invisible,
            "chromakey": material.is_chromakey,
            "sorted": material.is_sorted,
            "additive": material.is_additive,
            "clamp_s": material.clamps_s,
            "clamp_t": material.clamps_t,
        },
    }


def _lod_records(limb: U9Limb) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for lod_index, lod in enumerate(limb.lods):
        if lod is None:
            records.append({"lod_index": lod_index, "present": False})
            continue
        records.append(
            {
                "lod_index": lod_index,
                "present": True,
                "vertex_count": len(lod.vertices),
                "triangle_count": len(lod.triangles),
                "mount_vertex_count": len(lod.mount_vertices),
                "mount_triangle_count": len(lod.mount_triangles),
                "material_count": len(lod.materials),
                "sphere": {
                    "center": list(lod.sphere_center),
                    "radius": lod.sphere_radius,
                },
                "bounds": {
                    "minimum": list(lod.min_bounds),
                    "maximum": list(lod.max_bounds),
                },
            }
        )
    return records


def _frame_record(frame: Any) -> dict[str, object]:
    return {
        "time_ms": frame.time_ms,
        "rotation_wxyz": list(frame.rotation),
        "position_xyz": list(frame.position),
        "scale_xyz": list(frame.scale),
    }


def _track_record(
    part: U9AnimationPart,
    target_part_indices: tuple[int, ...],
    root_part_index: int | None,
) -> dict[str, object]:
    roles = ["rigid_rotation"] if target_part_indices else ["authoring_only"]
    if part.name.casefold() in {"pelvis", "hips"} and target_part_indices:
        roles.append("pelvis_translation")
    if root_part_index is not None and root_part_index in target_part_indices:
        roles.append("root_motion")
    return {
        "part_id": part.part_id,
        "name": part.name,
        "target_part_indices": list(target_part_indices),
        "roles": roles,
        "frames": [_frame_record(frame) for frame in part.frames],
    }


def _sidecar_document(
    model: U9Model,
    animation: U9Animation,
    *,
    part_names: tuple[str, ...],
    parent_indices: tuple[int | None, ...],
    mesh_names: tuple[str | None, ...],
    lod_level: int,
    coordinate_scale: float,
    motion_name: str | None,
    inputs: list[dict[str, object]],
) -> dict[str, object]:
    indices_by_id: dict[int, list[int]] = {}
    for index, limb in enumerate(model.limbs):
        indices_by_id.setdefault(limb.limb_id, []).append(index)
    root_part_index = next(
        (index for index, parent in enumerate(parent_indices) if parent is None), None
    )

    parts: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    for index, limb in enumerate(model.limbs):
        parent_index = parent_indices[index]
        if limb.is_root:
            parent_resolution = "self_root"
        elif parent_index is None:
            parent_resolution = "implicit_or_cycle_root"
        else:
            parent_resolution = "first_matching_part_id"
        parts.append(
            {
                "part_index": index,
                "id": limb.limb_id,
                "name": part_names[index],
                "parent_id": limb.parent_id,
                "parent_part_index": parent_index,
                "parent_resolution": parent_resolution,
                "mesh": mesh_names[index],
                "selected_lod": lod_level,
                "pivot": {
                    "parent_space_xyz": list(limb.position),
                    "mesh_space_origin_xyz": [0.0, 0.0, 0.0],
                },
                "rest_transform": {
                    "translation_xyz": list(limb.position),
                    "rotation_wxyz": list(limb.rotation),
                    "scale_xyz": list(limb.scale),
                    "matrix_row_major": list(
                        mat4_trs(limb.position, limb.rotation, limb.scale)
                    ),
                },
                "lods": _lod_records(limb),
            }
        )
        for part_lod_index, lod in enumerate(limb.lods):
            if lod is None:
                continue
            materials.extend(
                _material_record(index, part_lod_index, material_index, material)
                for material_index, material in enumerate(lod.materials)
            )

    tracks = [
        _track_record(
            part,
            tuple(indices_by_id.get(part.part_id, ())),
            root_part_index,
        )
        for part in animation.parts
    ]
    root_track = (
        animation.part(model.limbs[root_part_index].limb_id)
        if root_part_index is not None
        else None
    )
    return {
        "schema": ANIMATED_MODEL_BUNDLE_SCHEMA,
        "schema_version": ANIMATED_MODEL_BUNDLE_SCHEMA_VERSION,
        "coordinate_system": {
            "native": {
                "axes": "U9 x,y,z",
                "units": "U9 model units",
                "handedness": "not asserted",
            },
            "limb_meshes": {
                "coordinates": "native U9 limb-local",
                "units": "U9 model units",
                "pivot": "mesh origin; parent-space location is recorded per part",
            },
            "glb": {
                "axes": "right-handed Y-up",
                "native_to_glb": "(x,y,z) -> (x,z,-y)",
                "units_per_native_unit": coordinate_scale,
            },
            "quaternion_order": "w,x,y,z",
            "matrix_layout": "row-major",
            "local_transform_order": "translation * rotation * scale",
        },
        "inputs": inputs,
        "model": {
            "id": model.model_id,
            "record_format": model.record_format,
            "part_count": len(model.limbs),
            "selected_lod": lod_level,
            "bounds": {
                "minimum": list(model.min_bounds),
                "maximum": list(model.max_bounds),
            },
            "sphere": {
                "center": list(model.sphere_center),
                "radius": model.sphere_radius,
            },
            "lod_thresholds": list(model.lod_thresholds),
        },
        "parts": parts,
        "clips": [
            {
                "animation_id": animation.animation_id,
                "original_motion_name": motion_name,
                "authoring_path": animation.source_name,
                "frame_range": {
                    "start": animation.start_frame,
                    "end": animation.end_frame,
                    "count": animation.frame_count,
                },
                "timing": {
                    "fps": animation.source_fps,
                    "nominal_frame_interval_ms": animation.frame_interval_ms,
                    "duration_ms": animation.duration_ms,
                },
                "part_registry": list(animation.part_registry),
                "interpolation": {
                    "rotation": "spherical; destination hemisphere is not negated",
                    "position": "linear",
                    "scale": "linear",
                    "outside_range": "clamp to nearest stored sample",
                    "glb_rotation_approximation": "LINEAR quaternion interpolation",
                },
                "runtime_application": {
                    "rotation": "applied to every matched rigid part",
                    "translation": "applied locally only to PELVIS/HIPS",
                    "root_motion": "root translation is also separated as object motion",
                    "scale": "preserved here but not applied by the known runtime path",
                },
                "root_motion": {
                    "part_index": root_part_index,
                    "part_id": (
                        model.limbs[root_part_index].limb_id
                        if root_part_index is not None
                        else None
                    ),
                    "rest_translation_xyz": (
                        list(model.limbs[root_part_index].position)
                        if root_part_index is not None
                        else None
                    ),
                    "frames": (
                        [
                            {
                                "time_ms": frame.time_ms,
                                "raw_position_xyz": list(frame.position),
                                "delta_from_rest_xyz": [
                                    frame.position[axis]
                                    - model.limbs[root_part_index].position[axis]
                                    for axis in range(3)
                                ],
                            }
                            for frame in root_track.frames
                        ]
                        if root_track is not None and root_part_index is not None
                        else []
                    ),
                },
                "tracks": tracks,
                "events": [
                    {
                        "time_ms": event.time_ms,
                        "type": event.event_type,
                        "name": event.event_name,
                        "parameter": event.parameter,
                    }
                    for event in animation.events
                ],
            }
        ],
        "materials": materials,
    }


class _GlbBuilder:
    """Small glTF 2.0 binary writer for rigid-node model animation."""

    def __init__(self) -> None:
        self.binary = bytearray()
        self.document: dict[str, Any] = {
            "asset": {"version": "2.0", "generator": "Titan U9 animation bundle"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [],
            "meshes": [],
            "materials": [],
            "bufferViews": [],
            "accessors": [],
        }

    def add_blob(self, data: bytes, *, target: int | None = None) -> int:
        while len(self.binary) % 4:
            self.binary.append(0)
        offset = len(self.binary)
        self.binary.extend(data)
        view: dict[str, object] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data),
        }
        if target is not None:
            view["target"] = target
        views = self.document["bufferViews"]
        views.append(view)
        return len(views) - 1

    def add_float_accessor(
        self,
        values: Sequence[Any],
        accessor_type: str,
        *,
        target: int | None = None,
        bounds: bool = False,
    ) -> int:
        if not values:
            raise U9AnimatedModelBundleError("GLB accessor cannot be empty")
        width = 1 if accessor_type == "SCALAR" else len(values[0])
        flat = (
            [float(value) for value in values]
            if width == 1
            else [float(item) for value in values for item in value]
        )
        view = self.add_blob(struct.pack(f"<{len(flat)}f", *flat), target=target)
        accessor: dict[str, object] = {
            "bufferView": view,
            "componentType": _FLOAT,
            "count": len(values),
            "type": accessor_type,
        }
        if bounds:
            rows = [(float(value),) for value in values] if width == 1 else values
            accessor["min"] = [min(row[axis] for row in rows) for axis in range(width)]
            accessor["max"] = [max(row[axis] for row in rows) for axis in range(width)]
        accessors = self.document["accessors"]
        accessors.append(accessor)
        return len(accessors) - 1

    def write(self, path: Path) -> None:
        self.document["buffers"] = [{"byteLength": len(self.binary)}]
        json_bytes = json.dumps(
            self.document, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        json_bytes += b" " * (-len(json_bytes) % 4)
        binary_bytes = bytes(self.binary) + b"\x00" * (-len(self.binary) % 4)
        total_length = 12 + 8 + len(json_bytes) + 8 + len(binary_bytes)
        with path.open("wb") as stream:
            stream.write(struct.pack("<4sII", b"glTF", 2, total_length))
            stream.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
            stream.write(json_bytes)
            stream.write(struct.pack("<I4s", len(binary_bytes), b"BIN\x00"))
            stream.write(binary_bytes)


def _native_position(value: Vec3, coordinate_scale: float) -> Vec3:
    return (
        value[0] * coordinate_scale,
        value[2] * coordinate_scale,
        -value[1] * coordinate_scale,
    )


def _native_direction(value: Vec3) -> Vec3:
    return (value[0], value[2], -value[1])


def _quat_multiply(left: Quat, right: Quat) -> Quat:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _native_rotation_xyzw(value: Quat) -> tuple[float, float, float, float]:
    half = math.sqrt(0.5)
    conversion = (half, -half, 0.0, 0.0)
    inverse = (half, half, 0.0, 0.0)
    w, x, y, z = _quat_multiply(_quat_multiply(conversion, value), inverse)
    magnitude = math.sqrt(w * w + x * x + y * y + z * z)
    if magnitude:
        w, x, y, z = w / magnitude, x / magnitude, y / magnitude, z / magnitude
    return (x, y, z, w)


def _native_scale(value: Vec3) -> Vec3:
    return (value[0], value[2], value[1])


def _material_alpha(material: U9Material) -> float:
    value = (
        material.modified_alpha
        if material.modified_alpha != MATERIAL_ALPHA_NONE
        else material.default_alpha
    )
    return value / 255.0


def _add_glb_texture(
    builder: _GlbBuilder,
    material: U9Material,
    texture_resolver: TextureResolver | None,
    texture_cache: dict[tuple[int, int], int],
) -> int | None:
    if texture_resolver is None or material.is_invisible:
        return None
    key = (material.texture_id, material.cur_frame)
    if key in texture_cache:
        return texture_cache[key]
    frame = texture_resolver(*key)
    if frame is None:
        return None
    image = Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels_rgba)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    view = builder.add_blob(encoded.getvalue())
    images = builder.document.setdefault("images", [])
    images.append(
        {
            "name": f"texture_{material.texture_id}_frame_{material.cur_frame}",
            "mimeType": "image/png",
            "bufferView": view,
        }
    )
    textures = builder.document.setdefault("textures", [])
    textures.append({"source": len(images) - 1})
    texture_cache[key] = len(textures) - 1
    return len(textures) - 1


def _add_glb_material(
    builder: _GlbBuilder,
    material: U9Material,
    texture_resolver: TextureResolver | None,
    material_cache: dict[U9Material, int],
    texture_cache: dict[tuple[int, int], int],
) -> int:
    cached = material_cache.get(material)
    if cached is not None:
        return cached
    alpha = _material_alpha(material)
    base_color: dict[str, object] = {
        "baseColorFactor": [1.0, 1.0, 1.0, alpha],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.9,
    }
    texture_index = _add_glb_texture(builder, material, texture_resolver, texture_cache)
    if texture_index is not None:
        base_color["baseColorTexture"] = {"index": texture_index}
    payload: dict[str, object] = {
        "name": f"u9_texture_{material.texture_id}_frame_{material.cur_frame}",
        "pbrMetallicRoughness": base_color,
        "doubleSided": True,
        "alphaMode": (
            "BLEND"
            if alpha < 1.0 or material.is_additive
            else "MASK"
            if material.is_chromakey
            else "OPAQUE"
        ),
        "extras": _material_record(-1, -1, -1, material),
    }
    if payload["alphaMode"] == "MASK":
        payload["alphaCutoff"] = 0.1
    if material.is_additive:
        payload["emissiveFactor"] = [1.0, 1.0, 1.0]
    materials = builder.document["materials"]
    materials.append(payload)
    material_cache[material] = len(materials) - 1
    return len(materials) - 1


def _add_limb_mesh(
    builder: _GlbBuilder,
    limb: U9Limb,
    *,
    name: str,
    lod_level: int,
    coordinate_scale: float,
    texture_resolver: TextureResolver | None,
    material_cache: dict[U9Material, int],
    texture_cache: dict[tuple[int, int], int],
) -> int | None:
    triangles = limb_local_triangles(limb, lod_level)
    if not triangles:
        return None
    groups: dict[U9Material, list[Any]] = {}
    for triangle in triangles:
        material = triangle[0].material
        if material is not None:
            groups.setdefault(material, []).append(triangle)
    primitives = []
    for material, material_triangles in groups.items():
        positions: list[Vec3] = []
        normals: list[Vec3] = []
        uvs: list[tuple[float, float]] = []
        for triangle in material_triangles:
            for corner in triangle:
                positions.append(_native_position(corner.position, coordinate_scale))
                normals.append(_native_direction(corner.normal))
                uvs.append(
                    corner.uv
                    if all(math.isfinite(value) for value in corner.uv)
                    else (0.0, 0.0)
                )
        primitives.append(
            {
                "attributes": {
                    "POSITION": builder.add_float_accessor(
                        positions, "VEC3", target=_ARRAY_BUFFER, bounds=True
                    ),
                    "NORMAL": builder.add_float_accessor(
                        normals, "VEC3", target=_ARRAY_BUFFER
                    ),
                    "TEXCOORD_0": builder.add_float_accessor(
                        uvs, "VEC2", target=_ARRAY_BUFFER
                    ),
                },
                "material": _add_glb_material(
                    builder,
                    material,
                    texture_resolver,
                    material_cache,
                    texture_cache,
                ),
                "mode": 4,
            }
        )
    if not primitives:
        return None
    meshes = builder.document["meshes"]
    meshes.append({"name": name, "primitives": primitives})
    return len(meshes) - 1


def _add_animation_channel(
    builder: _GlbBuilder,
    animation_payload: dict[str, Any],
    *,
    input_accessor: int,
    values: Sequence[tuple[float, ...]],
    accessor_type: str,
    node_index: int,
    path: str,
) -> None:
    output_accessor = builder.add_float_accessor(values, accessor_type)
    sampler_index = len(animation_payload["samplers"])
    animation_payload["samplers"].append(
        {
            "input": input_accessor,
            "output": output_accessor,
            "interpolation": "LINEAR",
        }
    )
    animation_payload["channels"].append(
        {
            "sampler": sampler_index,
            "target": {"node": node_index, "path": path},
        }
    )


def _write_animated_glb(
    path: Path,
    model: U9Model,
    animation: U9Animation,
    *,
    part_names: tuple[str, ...],
    parent_indices: tuple[int | None, ...],
    lod_level: int,
    coordinate_scale: float,
    motion_name: str | None,
    texture_resolver: TextureResolver | None,
) -> None:
    builder = _GlbBuilder()
    builder.document["nodes"].append(
        {
            "name": f"model_{model.model_id}_root_motion",
            "children": [],
            "extras": {"u9_role": "root_motion"},
        }
    )
    material_cache: dict[U9Material, int] = {}
    texture_cache: dict[tuple[int, int], int] = {}
    node_indices = []
    for part_index, limb in enumerate(model.limbs):
        mesh_index = _add_limb_mesh(
            builder,
            limb,
            name=(f"part_{part_index:03d}_id_{limb.limb_id}_{part_names[part_index]}"),
            lod_level=lod_level,
            coordinate_scale=coordinate_scale,
            texture_resolver=texture_resolver,
            material_cache=material_cache,
            texture_cache=texture_cache,
        )
        node: dict[str, object] = {
            "name": f"part_{part_index:03d}_id_{limb.limb_id}_{part_names[part_index]}",
            "translation": list(_native_position(limb.position, coordinate_scale)),
            "rotation": list(_native_rotation_xyzw(limb.rotation)),
            "scale": list(_native_scale(limb.scale)),
            "extras": {
                "u9_part_index": part_index,
                "u9_part_id": limb.limb_id,
                "u9_parent_id": limb.parent_id,
            },
        }
        if mesh_index is not None:
            node["mesh"] = mesh_index
        builder.document["nodes"].append(node)
        node_indices.append(len(builder.document["nodes"]) - 1)

    for part_index, parent_index in enumerate(parent_indices):
        parent_node = 0 if parent_index is None else node_indices[parent_index]
        children = builder.document["nodes"][parent_node].setdefault("children", [])
        children.append(node_indices[part_index])

    indices_by_id: dict[int, list[int]] = {}
    for part_index, limb in enumerate(model.limbs):
        indices_by_id.setdefault(limb.limb_id, []).append(part_index)
    root_part_index = next(
        (index for index, parent in enumerate(parent_indices) if parent is None), None
    )
    animation_payload: dict[str, Any] = {
        "name": motion_name or f"animation_{animation.animation_id}",
        "samplers": [],
        "channels": [],
        "extras": {
            "u9_animation_id": animation.animation_id,
            "u9_events": [
                {
                    "time_ms": event.time_ms,
                    "type": event.event_type,
                    "name": event.event_name,
                    "parameter": event.parameter,
                }
                for event in animation.events
            ],
            "u9_sidecar_is_authoritative": True,
        },
    }
    for track in animation.parts:
        target_parts = indices_by_id.get(track.part_id, [])
        if not target_parts or not track.frames:
            continue
        times = [frame.time_ms / 1000.0 for frame in track.frames]
        input_accessor = builder.add_float_accessor(times, "SCALAR", bounds=True)
        rotations = [_native_rotation_xyzw(frame.rotation) for frame in track.frames]
        for part_index in target_parts:
            _add_animation_channel(
                builder,
                animation_payload,
                input_accessor=input_accessor,
                values=rotations,
                accessor_type="VEC4",
                node_index=node_indices[part_index],
                path="rotation",
            )
        if track.name.casefold() in {"pelvis", "hips"}:
            positions = [
                _native_position(frame.position, coordinate_scale)
                for frame in track.frames
            ]
            for part_index in target_parts:
                _add_animation_channel(
                    builder,
                    animation_payload,
                    input_accessor=input_accessor,
                    values=positions,
                    accessor_type="VEC3",
                    node_index=node_indices[part_index],
                    path="translation",
                )
        if root_part_index is not None and root_part_index in target_parts:
            root_rest = model.limbs[root_part_index].position
            deltas = [
                _native_position(
                    (
                        frame.position[0] - root_rest[0],
                        frame.position[1] - root_rest[1],
                        frame.position[2] - root_rest[2],
                    ),
                    coordinate_scale,
                )
                for frame in track.frames
            ]
            _add_animation_channel(
                builder,
                animation_payload,
                input_accessor=input_accessor,
                values=deltas,
                accessor_type="VEC3",
                node_index=0,
                path="translation",
            )
    if animation_payload["channels"]:
        builder.document["animations"] = [animation_payload]
    builder.write(path)


def export_animated_model_bundle(
    model: U9Model,
    animation: U9Animation,
    output_directory: str | Path,
    *,
    model_archive_path: str | Path,
    animation_archive_path: str | Path,
    registry: U9NodeRegistry | None = None,
    registry_path: str | Path | None = None,
    motion_name: str | None = None,
    motion_table_path: str | Path | None = None,
    texture_resolver: TextureResolver | None = None,
    texture_archive_path: str | Path | None = None,
    palette_path: str | Path | None = None,
    lod_level: int = 0,
    coordinate_scale: float = DEFAULT_ANIMATED_MODEL_SCALE,
    include_glb: bool = True,
) -> U9AnimatedModelBundleResult:
    """Write local limb OBJs, the versioned sidecar, and an animated GLB."""
    if model.record_format != "hierarchical":
        raise U9AnimatedModelBundleError(
            f"model {model.model_id} uses the indexed record family and has no "
            "animatable rigid hierarchy"
        )
    if lod_level < 0:
        raise U9AnimatedModelBundleError("LOD level must be non-negative")
    if coordinate_scale <= 0:
        raise U9AnimatedModelBundleError("coordinate scale must be positive")
    model_ids = {limb.limb_id for limb in model.limbs}
    matched_track_count = sum(part.part_id in model_ids for part in animation.parts)
    if not matched_track_count:
        raise U9AnimatedModelBundleError(
            f"animation {animation.animation_id} and model {model.model_id} have "
            "no shared limb/part IDs"
        )

    inputs = [
        _input_record("model_archive", model_archive_path),
        _input_record("animation_archive", animation_archive_path),
    ]
    optional_inputs = (
        ("node_registry", registry_path),
        ("ghidra_motion_table", motion_table_path),
        ("texture_archive", texture_archive_path),
        ("palette", palette_path),
    )
    inputs.extend(
        _input_record(role, path) for role, path in optional_inputs if path is not None
    )

    output = Path(output_directory)
    mesh_directory = output / "meshes"
    mesh_directory.mkdir(parents=True, exist_ok=True)
    part_names = _part_names(model, animation, registry)
    parent_indices = _parent_indices(model)
    mesh_names: list[str | None] = []
    mesh_paths: list[Path] = []
    for part_index, limb in enumerate(model.limbs):
        if not limb_local_triangles(limb, lod_level):
            mesh_names.append(None)
            continue
        mesh_name = (
            f"part_{part_index:03d}_id_{limb.limb_id:05d}_"
            f"{_safe_name(part_names[part_index])}.obj"
        )
        mesh_path = mesh_directory / mesh_name
        try:
            export_limb_obj(
                model,
                part_index,
                str(mesh_path),
                lod_level=lod_level,
                scale=1.0,
                texture_resolver=texture_resolver,
            )
        except MeshExportError as error:
            raise U9AnimatedModelBundleError(str(error)) from error
        mesh_names.append(f"meshes/{mesh_name}")
        mesh_paths.append(mesh_path)

    sidecar = _sidecar_document(
        model,
        animation,
        part_names=part_names,
        parent_indices=parent_indices,
        mesh_names=tuple(mesh_names),
        lod_level=lod_level,
        coordinate_scale=coordinate_scale,
        motion_name=motion_name,
        inputs=inputs,
    )
    stem = f"model_{model.model_id:05d}_animation_{animation.animation_id:05d}"
    sidecar_path = output / f"{stem}.u9anim.json"
    sidecar_path.write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    glb_path = output / f"{stem}.glb" if include_glb else None
    if glb_path is not None:
        _write_animated_glb(
            glb_path,
            model,
            animation,
            part_names=part_names,
            parent_indices=parent_indices,
            lod_level=lod_level,
            coordinate_scale=coordinate_scale,
            motion_name=motion_name,
            texture_resolver=texture_resolver,
        )
    return U9AnimatedModelBundleResult(
        sidecar_path=sidecar_path,
        glb_path=glb_path,
        limb_mesh_paths=tuple(mesh_paths),
        part_count=len(model.limbs),
        mesh_count=len(mesh_paths),
        track_count=len(animation.parts),
        matched_track_count=matched_track_count,
        authoring_only_track_count=len(animation.parts) - matched_track_count,
    )
