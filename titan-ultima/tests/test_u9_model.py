"""Tests for titan.u9.model's sappear.flx mesh parser.

Fixtures are hand-built binary records matching the exact byte layout
validated in this project against real game data (see titan.u9.model's
module docstring for the real-data cross-check: model 0, a debug cube,
matched field-for-field). The three offset fields inside a LOD
record (face/vertex/material) follow a general formula derived and
confirmed against that real data::

    faces_off     = header_size                       (= 0x7C)
    vertices_off  = faces_off + len(face_bytes)
    materials_off = vertices_off + len(vertex_bytes)

-- reproduced here as ``_lod_offsets()`` rather than hardcoded, so the
fixture stays correct if the number of faces/vertices in a test changes.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.model import U9Model, U9ModelError

MODEL_HEADER_SIZE = 0x90
LIMB_HEADER_SIZE = 0x30
LOD_HEADER_SIZE = 0x7C
FACE_SIZE = 0x7C
CORNER_SIZE = 0x1C
MATERIAL_SIZE = 0x18


def _model_header(submesh_count: int, lod_count: int) -> bytes:
    data = (
        struct.pack("<II", submesh_count, lod_count)
        + struct.pack("<3f", 0, 0, 0)  # cylinder_base_center
        + struct.pack("<2f", 0, 0)  # cylinder_base_height, radius
        + struct.pack("<3f", 0, 0, 0)  # sphere_center
        + struct.pack("<f", 1.0)  # sphere_radius
        + struct.pack("<f", 0)  # unknown
        + struct.pack("<3f", -1, -1, -1)  # min_bounds
        + struct.pack("<3f", 1, 1, 1)  # max_bounds
        + struct.pack("<4I", 100, 200, 300, 400)  # lod_thresholds
        + struct.pack("<3f", 0, 0, 0)  # center_of_mass
    )
    assert len(data) <= MODEL_HEADER_SIZE
    return data + b"\x00" * (MODEL_HEADER_SIZE - len(data))  # pad out unused tail fields


def _limb_header(limb_id: int, parent_id: int, position=(0.0, 0.0, 0.0), rotation=(1.0, 0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> bytes:
    return (
        struct.pack("<II", limb_id, parent_id)
        + struct.pack("<3f", *scale)
        + struct.pack("<3f", *position)
        + struct.pack("<4f", *rotation)
    )


def _corner(vertex_index: int, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0)) -> bytes:
    return struct.pack("<II", vertex_index, 0) + struct.pack("<3f", *normal) + struct.pack("<2f", *uv)


def _face(corners: tuple[bytes, bytes, bytes], normal=(0.0, 0.0, 1.0), color=(255, 255, 255, 255)) -> bytes:
    data = b"".join(corners)
    data += struct.pack("<II", 0, 0)  # flags, flags2
    data += struct.pack("<3f", *normal)
    data += struct.pack("<f", 0.0)  # vector_w
    data += struct.pack("<I", 0)  # raw material value (unused by parser)
    data += bytes(color)
    data += b"\x00" * 8  # collision
    assert len(data) == FACE_SIZE
    return data


def _material(texture_id: int, first_face: int, face_count: int, render_flags: int = 0) -> bytes:
    data = struct.pack("<6H", texture_id, 0, render_flags, 0, first_face, face_count)
    data += bytes([255, 255, 0, 0, 0, 0, 0, 0])  # default_alpha, modified_alpha, anim fields
    data += struct.pack("<I", 0)  # anim timer
    assert len(data) == MATERIAL_SIZE
    return data


def _lod_offsets(face_bytes: bytes, vertex_bytes: bytes) -> tuple[int, int, int]:
    faces_off = LOD_HEADER_SIZE
    vertices_off = faces_off + len(face_bytes)
    materials_off = vertices_off + len(vertex_bytes)
    return faces_off, vertices_off, materials_off


def _lod(vertices: list[tuple[float, float, float]], faces: list[bytes], materials: list[bytes]) -> bytes:
    vertex_bytes = b"".join(struct.pack("<3f", *v) for v in vertices)
    face_bytes = b"".join(faces)
    material_bytes = b"".join(materials)
    faces_off, vertices_off, materials_off = _lod_offsets(face_bytes, vertex_bytes)

    header = (
        struct.pack("<I", 1)  # mesh_size placeholder, just needs to be nonzero
        + struct.pack("<I", 0)  # flags
        + struct.pack("<I", 0)  # unknown1
        + struct.pack("<3f", 0, 0, 0)  # sphere_center
        + struct.pack("<f", 1.0)  # sphere_radius
        + struct.pack("<3f", -1, -1, -1)  # min_bounds
        + struct.pack("<3f", 1, 1, 1)  # max_bounds
        + struct.pack("<II", 0, 0)  # unknown2, unknown3
        + struct.pack("<I", len(faces))  # face_count
        + struct.pack("<I", 0)  # mount_face_count
        + struct.pack("<I", len(vertices))  # vertex_count
        + struct.pack("<I", 0)  # mount_vertex_count
        + struct.pack("<I", len(faces))  # max_face_count
        + struct.pack("<I", len(materials))  # material_count
        + struct.pack("<I", faces_off)
        + struct.pack("<I", 0)  # mount_face_offset
        + struct.pack("<I", vertices_off)
        + struct.pack("<I", 0)  # (buggy-key field in the reference importer; unused here)
        + struct.pack("<I", materials_off)
        + struct.pack("<4I", 0, 0, 0, 0)  # sorted_faces_offset
        + struct.pack("<I", 0)  # unknown4
    )
    assert len(header) == LOD_HEADER_SIZE, len(header)
    return header + b"\x00\x00\x00\x00" + face_bytes + vertex_bytes + material_bytes


def _single_limb_model(faces: list[bytes], vertices: list[tuple[float, float, float]], materials: list[bytes]) -> bytes:
    header = _model_header(submesh_count=1, lod_count=1)
    limb_header_off = MODEL_HEADER_SIZE + 4 + 4  # offset table: 1 header offset + 1 lod offset
    lod_off = limb_header_off + LIMB_HEADER_SIZE

    offset_table = struct.pack("<II", limb_header_off, lod_off)
    limb = _limb_header(limb_id=1, parent_id=1)
    lod = _lod(vertices, faces, materials)

    return header + offset_table + limb + lod


def _triangle_model() -> bytes:
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    face = _face(
        (
            _corner(0, uv=(0.0, 0.0)),
            _corner(1, uv=(1.0, 0.0)),
            _corner(2, uv=(0.0, 1.0)),
        )
    )
    material = _material(texture_id=7, first_face=0, face_count=1)
    return _single_limb_model([face], vertices, [material])


class ParseModelHeaderTests(unittest.TestCase):
    def test_header_fields(self) -> None:
        model = U9Model.parse(_triangle_model(), model_id=42)
        self.assertEqual(model.model_id, 42)
        self.assertEqual(model.sphere_radius, 1.0)
        self.assertEqual(model.min_bounds, (-1.0, -1.0, -1.0))
        self.assertEqual(model.max_bounds, (1.0, 1.0, 1.0))
        self.assertEqual(model.lod_thresholds, (100, 200, 300, 400))

    def test_too_small_data_raises(self) -> None:
        with self.assertRaises(U9ModelError):
            U9Model.parse(b"\x00" * 10)


class ParseLimbAndLodTests(unittest.TestCase):
    def test_single_limb_is_root(self) -> None:
        model = U9Model.parse(_triangle_model())
        self.assertEqual(len(model.limbs), 1)
        limb = model.limbs[0]
        self.assertEqual(limb.limb_id, 1)
        self.assertEqual(limb.parent_id, 1)
        self.assertTrue(limb.is_root)
        self.assertEqual(limb.scale, (1.0, 1.0, 1.0))
        self.assertEqual(limb.rotation, (1.0, 0.0, 0.0, 0.0))

    def test_lod_geometry(self) -> None:
        model = U9Model.parse(_triangle_model())
        lod = model.limbs[0].lods[0]
        self.assertIsNotNone(lod)
        self.assertEqual(lod.vertices, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        self.assertEqual(len(lod.triangles), 1)
        tri = lod.triangles[0]
        self.assertEqual([c.vertex_index for c in tri.corners], [0, 1, 2])
        self.assertEqual([c.uv for c in tri.corners], [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        self.assertEqual(tri.color, (255, 255, 255, 255))

    def test_material_resolved_onto_triangle(self) -> None:
        model = U9Model.parse(_triangle_model())
        lod = model.limbs[0].lods[0]
        self.assertEqual(len(lod.materials), 1)
        self.assertEqual(lod.materials[0].texture_id, 7)
        self.assertEqual(lod.triangles[0].material_index, 0)


class MalformedModelTests(unittest.TestCase):
    def test_absurd_submesh_count_raises_cleanly(self) -> None:
        # mirrors a real, genuinely-corrupt sappear.flx entry (model 536 in this
        # project's test copy of the game) -- see module docstring.
        header = _model_header(submesh_count=169, lod_count=845)
        with self.assertRaises(U9ModelError):
            U9Model.parse(header)


if __name__ == "__main__":
    unittest.main()
