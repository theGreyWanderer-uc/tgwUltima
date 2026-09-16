"""Tests for U9 rigid animated-model bundle export."""

from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from titan.u9.animated_model_bundle import (
    ANIMATED_MODEL_BUNDLE_SCHEMA,
    ANIMATED_MODEL_BUNDLE_SCHEMA_VERSION,
    U9AnimatedModelBundleError,
    export_animated_model_bundle,
)
from titan.u9.animation import (
    U9Animation,
    U9AnimationFrame,
    U9AnimationPart,
    U9AnimationSuffix,
)
from titan.u9.model import (
    U9Limb,
    U9Material,
    U9Model,
    U9SubmeshLod,
    U9Triangle,
    U9TriangleCorner,
)
from titan.u9.node_registry import U9NodeRegistry


def _material() -> U9Material:
    return U9Material(
        texture_id=7,
        flags_02=2,
        render_flags=1,
        flags_06=3,
        first_face=0,
        face_count=1,
        default_alpha=255,
        modified_alpha=255,
        anim_start=1,
        anim_end=3,
        cur_frame=2,
        anim_speed=4,
        animation_type=5,
        playback_direction=6,
        animation_timer=700,
    )


def _lod() -> U9SubmeshLod:
    corners = tuple(
        U9TriangleCorner(index, (0.0, 0.0, 1.0), uv)
        for index, uv in enumerate(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
    )
    triangle = U9Triangle(
        corners=corners,  # type: ignore[arg-type]
        material_index=0,
        face_normal=(0.0, 0.0, 1.0),
        color=(255, 255, 255, 255),
    )
    return U9SubmeshLod(
        lod_index=0,
        vertices=((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0)),
        triangles=(triangle,),
        materials=(_material(),),
        sphere_center=(2.0, 2.0, 0.0),
        sphere_radius=3.0,
        min_bounds=(0.0, 0.0, 0.0),
        max_bounds=(4.0, 4.0, 0.0),
    )


def _model(record_format: str = "hierarchical") -> U9Model:
    identity = (1.0, 0.0, 0.0, 0.0)
    unit = (1.0, 1.0, 1.0)
    limbs = (
        U9Limb(1, 0, unit, (10.0, 20.0, 30.0), identity, (None,)),
        U9Limb(2, 1, unit, (1.0, 2.0, 3.0), identity, (_lod(),)),
        U9Limb(3, 2, unit, (4.0, 5.0, 6.0), identity, (_lod(),)),
    )
    return U9Model(
        model_id=7,
        cylinder_base_center=(0.0, 0.0, 0.0),
        cylinder_base_height=0.0,
        cylinder_base_radius=0.0,
        sphere_center=(0.0, 0.0, 0.0),
        sphere_radius=1.0,
        min_bounds=(0.0, 0.0, 0.0),
        max_bounds=(1.0, 1.0, 1.0),
        lod_thresholds=(1, 2, 3, 4),
        center_of_mass=(0.0, 0.0, 0.0),
        limbs=limbs,
        record_format=record_format,
    )


def _frame(
    time_ms: int,
    position: tuple[float, float, float],
) -> U9AnimationFrame:
    return U9AnimationFrame(
        time_ms=time_ms,
        rotation=(1.0, 0.0, 0.0, 0.0),
        position=position,
        scale=(1.0, 1.0, 1.0),
    )


def _animation() -> U9Animation:
    parts = (
        U9AnimationPart(
            1, "BIP01", (_frame(0, (10.0, 20.0, 30.0)), _frame(33, (11.0, 20.0, 30.0)))
        ),
        U9AnimationPart(
            2, "PELVIS", (_frame(0, (1.0, 2.0, 3.0)), _frame(33, (2.0, 2.0, 3.0)))
        ),
        U9AnimationPart(
            99,
            "CAMERA_TARGET",
            (_frame(0, (7.0, 8.0, 9.0)), _frame(33, (8.0, 8.0, 9.0))),
        ),
    )
    return U9Animation(
        animation_id=172,
        start_frame=0,
        end_frame=1,
        frame_count=2,
        source_fps=30,
        frame_interval_ms=33,
        source_name="avatar_breathe",
        header_words=(1, 2, 99, 0),
        parts=parts,
        suffixes=(U9AnimationSuffix((33, 1, 9)),),
    )


def _read_glb_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or total_length != len(data):
        raise ValueError("test GLB header is invalid")
    json_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON":
        raise ValueError("test GLB has no leading JSON chunk")
    return json.loads(data[20 : 20 + json_length].decode("utf-8"))


def _read_glb_float_accessor(
    path: Path, document: dict[str, Any], accessor_index: int
) -> tuple[tuple[float, ...], ...]:
    data = path.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    binary_header_offset = 20 + json_length
    binary_length, chunk_type = struct.unpack_from("<I4s", data, binary_header_offset)
    if chunk_type != b"BIN\x00":
        raise ValueError("test GLB has no binary chunk")
    binary = data[binary_header_offset + 8 : binary_header_offset + 8 + binary_length]
    accessor = document["accessors"][accessor_index]
    view = document["bufferViews"][accessor["bufferView"]]
    widths = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    width = widths[accessor["type"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    values = struct.unpack_from(f"<{accessor['count'] * width}f", binary, offset)
    return tuple(
        tuple(values[index : index + width]) for index in range(0, len(values), width)
    )


class AnimatedModelBundleTests(unittest.TestCase):
    def test_sidecar_preserves_hierarchy_tracks_events_materials_and_hashes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model_archive.bin"
            animation_archive = root / "animation_archive.bin"
            registry_path = root / "registry.txt"
            model_archive.write_bytes(b"model archive")
            animation_archive.write_bytes(b"animation archive")
            registry_path.write_text(
                "1 BIP01\n2 PELVIS\n3 LEFT_HAND\n", encoding="ascii"
            )

            result = export_animated_model_bundle(
                _model(),
                _animation(),
                root / "bundle",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
                registry=U9NodeRegistry.from_file(registry_path),
                registry_path=registry_path,
                motion_name="HUMANOID_IDLE_BREATHE_AVATAR",
            )
            document = json.loads(result.sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(document["schema"], ANIMATED_MODEL_BUNDLE_SCHEMA)
            self.assertEqual(
                document["schema_version"], ANIMATED_MODEL_BUNDLE_SCHEMA_VERSION
            )
            self.assertEqual(document["model"]["id"], 7)
            self.assertEqual(document["parts"][0]["parent_part_index"], None)
            self.assertEqual(document["parts"][1]["parent_part_index"], 0)
            self.assertEqual(document["parts"][2]["name"], "LEFT_HAND")
            self.assertEqual(
                document["parts"][1]["pivot"]["parent_space_xyz"],
                [1.0, 2.0, 3.0],
            )
            self.assertEqual(
                document["parts"][1]["rest_transform"]["rotation_wxyz"],
                [1.0, 0.0, 0.0, 0.0],
            )
            tracks = document["clips"][0]["tracks"]
            self.assertEqual([track["part_id"] for track in tracks], [1, 2, 99])
            self.assertEqual(tracks[2]["roles"], ["authoring_only"])
            self.assertEqual(tracks[1]["frames"][1]["time_ms"], 33)
            self.assertEqual(document["clips"][0]["events"][0]["name"], "loop")
            self.assertEqual(document["materials"][0]["texture_id"], 7)
            self.assertEqual(document["materials"][0]["animation"]["timer"], 700)
            self.assertEqual(
                document["inputs"][0]["sha256"],
                hashlib.sha256(b"model archive").hexdigest(),
            )
            self.assertEqual(result.part_count, 3)
            self.assertEqual(result.mesh_count, 2)
            self.assertEqual(result.track_count, 3)
            self.assertEqual(result.matched_track_count, 2)
            self.assertEqual(result.authoring_only_track_count, 1)
            self.assertTrue(all(path.is_file() for path in result.limb_mesh_paths))
            mesh_text = result.limb_mesh_paths[0].read_text(encoding="ascii")
            self.assertIn("v 4.000000 0.000000 0.000000", mesh_text)

    def test_glb_has_rigid_hierarchy_root_motion_and_pelvis_translation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")
            result = export_animated_model_bundle(
                _model(),
                _animation(),
                root / "bundle",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
            )

            self.assertIsNotNone(result.glb_path)
            document = _read_glb_json(result.glb_path)  # type: ignore[arg-type]
            nodes = document["nodes"]
            self.assertEqual(nodes[0]["children"], [1])
            self.assertEqual(nodes[1]["children"], [2])
            self.assertEqual(nodes[2]["children"], [3])
            animation = document["animations"][0]
            targets = [channel["target"] for channel in animation["channels"]]
            self.assertIn({"node": 0, "path": "translation"}, targets)
            self.assertIn({"node": 1, "path": "rotation"}, targets)
            self.assertIn({"node": 2, "path": "rotation"}, targets)
            self.assertIn({"node": 2, "path": "translation"}, targets)
            self.assertNotIn({"node": 3, "path": "rotation"}, targets)

    def test_glb_preserves_top_left_u9_texture_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")
            result = export_animated_model_bundle(
                _model(),
                _animation(),
                root / "bundle",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
            )

            self.assertIsNotNone(result.glb_path)
            glb_path = result.glb_path
            if glb_path is None:
                self.fail("animated GLB was not written")
            document = _read_glb_json(glb_path)
            accessor_index = document["meshes"][0]["primitives"][0]["attributes"][
                "TEXCOORD_0"
            ]

            self.assertEqual(
                _read_glb_float_accessor(glb_path, document, accessor_index),
                ((0.0, 0.0), (0.0, 1.0), (1.0, 0.0)),
            )

    def test_rejects_models_without_an_animatable_shared_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")
            with self.assertRaisesRegex(U9AnimatedModelBundleError, "indexed"):
                export_animated_model_bundle(
                    _model("indexed"),
                    _animation(),
                    root / "bundle",
                    model_archive_path=model_archive,
                    animation_archive_path=animation_archive,
                )


if __name__ == "__main__":
    unittest.main()
