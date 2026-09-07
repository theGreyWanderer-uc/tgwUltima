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
        + struct.pack("<f", 2.5)  # unknown_2c
        + struct.pack("<3f", -1, -1, -1)  # min_bounds
        + struct.pack("<3f", 1, 1, 1)  # max_bounds
        + struct.pack("<4I", 100, 200, 300, 400)  # lod_thresholds
        + struct.pack("<3f", 0, 0, 0)  # center_of_mass
        + struct.pack("<f", 12.5)  # mass_or_volume
        + struct.pack("<9f", *range(1, 10))  # inertia_matrix
        + struct.pack("<f", 3.5)  # unknown_8c
    )
    assert len(data) == MODEL_HEADER_SIZE
    return data


def _limb_header(
    limb_id: int,
    parent_id: int,
    position=(0.0, 0.0, 0.0),
    rotation=(1.0, 0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
) -> bytes:
    return (
        struct.pack("<II", limb_id, parent_id)
        + struct.pack("<3f", *scale)
        + struct.pack("<3f", *position)
        + struct.pack("<4f", *rotation)
    )


def _corner(
    vertex_index: int, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0), point_offset: int = 0
) -> bytes:
    return (
        struct.pack("<II", vertex_index, point_offset)
        + struct.pack("<3f", *normal)
        + struct.pack("<2f", *uv)
    )


def _face(
    corners: tuple[bytes, bytes, bytes],
    normal=(0.0, 0.0, 1.0),
    color=(255, 255, 255, 255),
    *,
    flags: int = 0,
    flags2: int = 0,
    plane_w: float = 0.0,
    raw_material: int = 0,
    collision: bytes = b"\x00" * 8,
) -> bytes:
    data = b"".join(corners)
    data += struct.pack("<II", flags, flags2)
    data += struct.pack("<3f", *normal)
    data += struct.pack("<f", plane_w)
    data += struct.pack("<I", raw_material)
    data += bytes(color)
    data += collision
    assert len(data) == FACE_SIZE
    return data


def _material(
    texture_id: int,
    first_face: int,
    face_count: int,
    render_flags: int = 0,
    *,
    animation_type: int = 0,
    playback_direction: int = 0,
    animation_timer: int = 0,
) -> bytes:
    data = struct.pack("<6H", texture_id, 0, render_flags, 0, first_face, face_count)
    data += bytes([255, 255, 0, 0, 0, 0, animation_type, playback_direction])
    data += struct.pack("<I", animation_timer)
    assert len(data) == MATERIAL_SIZE
    return data


def _lod_offsets(face_bytes: bytes, vertex_bytes: bytes) -> tuple[int, int, int]:
    faces_off = LOD_HEADER_SIZE
    vertices_off = faces_off + len(face_bytes)
    materials_off = vertices_off + len(vertex_bytes)
    return faces_off, vertices_off, materials_off


def _lod(
    vertices: list[tuple[float, float, float]],
    faces: list[bytes],
    materials: list[bytes],
    mount_vertices: list[tuple[float, float, float]] | None = None,
    mount_faces: list[bytes] | None = None,
) -> bytes:
    mount_vertices = mount_vertices or []
    mount_faces = mount_faces or []
    vertex_bytes = b"".join(struct.pack("<3f", *v) for v in vertices)
    face_bytes = b"".join(faces)
    mount_vertex_bytes = b"".join(struct.pack("<3f", *v) for v in mount_vertices)
    mount_face_bytes = b"".join(mount_faces)
    material_bytes = b"".join(materials)
    faces_off = LOD_HEADER_SIZE
    mount_faces_off = faces_off + len(face_bytes)
    vertices_off = mount_faces_off + len(mount_face_bytes)
    mount_vertices_off = vertices_off + len(vertex_bytes)
    materials_off = mount_vertices_off + len(mount_vertex_bytes)
    mesh_size = (
        LOD_HEADER_SIZE
        + len(face_bytes)
        + len(mount_face_bytes)
        + len(vertex_bytes)
        + len(mount_vertex_bytes)
        + len(material_bytes)
    )

    header = (
        struct.pack("<I", mesh_size)
        + struct.pack("<I", 0)  # flags
        + struct.pack("<I", 0)  # unknown1
        + struct.pack("<3f", 0, 0, 0)  # sphere_center
        + struct.pack("<f", 1.0)  # sphere_radius
        + struct.pack("<3f", -1, -1, -1)  # min_bounds
        + struct.pack("<3f", 1, 1, 1)  # max_bounds
        + struct.pack("<II", 0, 0)  # unknown2, unknown3
        + struct.pack("<I", len(faces))  # face_count
        + struct.pack("<I", len(mount_faces))
        + struct.pack("<I", len(vertices))  # vertex_count
        + struct.pack("<I", len(mount_vertices))
        + struct.pack("<I", len(faces) + len(mount_faces))  # max_face_count
        + struct.pack("<I", len(materials))  # material_count
        + struct.pack("<I", faces_off)
        + struct.pack("<I", mount_faces_off)
        + struct.pack("<I", vertices_off)
        + struct.pack("<I", mount_vertices_off)
        + struct.pack("<I", materials_off)
        + struct.pack("<4I", 0, 0, 0, 0)  # sorted_faces_offset
        + struct.pack("<I", 0)  # unknown4
    )
    assert len(header) == LOD_HEADER_SIZE, len(header)
    return (
        header
        + b"\x00\x00\x00\x00"
        + face_bytes
        + mount_face_bytes
        + vertex_bytes
        + mount_vertex_bytes
        + material_bytes
    )


def _single_limb_model(
    faces: list[bytes],
    vertices: list[tuple[float, float, float]],
    materials: list[bytes],
) -> bytes:
    header = _model_header(submesh_count=1, lod_count=1)
    limb_header_off = (
        MODEL_HEADER_SIZE + 4 + 4
    )  # offset table: 1 header offset + 1 lod offset
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


def _indexed_model() -> bytes:
    """Build one alternate record containing a triangle and a quad."""
    face_count = 2
    corner_vertex_indices = (0, 1, 2, 0, 1, 2, 3)
    corner_count = len(corner_vertex_indices)
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))
    corner_start = 0xA9 + face_count * 0x34
    vertex_start = corner_start + corner_count * 0x18
    trailing_start = vertex_start + len(vertices) * 0x0C

    header = bytearray(0xA9)
    struct.pack_into("<4I", header, 0, 0xA9, corner_start, vertex_start, trailing_start)
    struct.pack_into("<3I", header, 0x10, face_count, corner_count, len(vertices))

    face_bytes = bytearray()
    for face_index, (first_corner, count, texture_id) in enumerate(
        ((0, 3, 7), (3, 4, 8))
    ):
        face_pos = 0xA9 + face_index * 0x34
        absolute_corners = [
            corner_start + (first_corner + i) * 0x18 for i in range(count)
        ]
        offsets = [corner_pos - face_pos for corner_pos in absolute_corners]
        offsets.extend([0] * (4 - count))
        face_bytes += struct.pack("<4I", *offsets)
        face_bytes += struct.pack(
            "<I3ffI4B", 0x123, 0.0, 0.0, 1.0, -1.0, texture_id, 1, 2, 3, 4
        )
        face_bytes += bytes(range(8))

    corner_bytes = bytearray()
    for corner_index, vertex_index in enumerate(corner_vertex_indices):
        corner_pos = corner_start + corner_index * 0x18
        point_offset = vertex_start + vertex_index * 0x0C - corner_pos
        corner_bytes += struct.pack("<I3f2f", point_offset, 0.0, 0.0, 1.0, 0.25, 0.75)

    vertex_bytes = b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    return bytes(header + face_bytes + corner_bytes + vertex_bytes + b"TAIL")


class ParseModelHeaderTests(unittest.TestCase):
    def test_header_fields(self) -> None:
        model = U9Model.parse(_triangle_model(), model_id=42)
        self.assertEqual(model.model_id, 42)
        self.assertEqual(model.sphere_radius, 1.0)
        self.assertEqual(model.min_bounds, (-1.0, -1.0, -1.0))
        self.assertEqual(model.max_bounds, (1.0, 1.0, 1.0))
        self.assertEqual(model.lod_thresholds, (100, 200, 300, 400))
        self.assertEqual(model.unknown_2c, 2.5)
        self.assertEqual(model.mass_or_volume, 12.5)
        self.assertEqual(
            model.inertia_matrix, tuple(float(value) for value in range(1, 10))
        )
        self.assertEqual(model.unknown_8c, 3.5)

    def test_source_bytes_round_trip_exactly(self) -> None:
        data = _triangle_model()
        self.assertEqual(U9Model.parse(data).to_bytes(), data)

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
        self.assertEqual(
            lod.vertices, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        )
        self.assertEqual(len(lod.triangles), 1)
        tri = lod.triangles[0]
        self.assertEqual([c.vertex_index for c in tri.corners], [0, 1, 2])
        self.assertEqual(
            [c.uv for c in tri.corners], [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        )
        self.assertEqual(tri.color, (255, 255, 255, 255))

    def test_raw_face_and_material_fields_are_exposed(self) -> None:
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        face = _face(
            (_corner(0, point_offset=10), _corner(1), _corner(2)),
            flags=11,
            flags2=12,
            plane_w=2.25,
            raw_material=99,
            collision=b"abcdefgh",
        )
        material = _material(
            7, 0, 1, animation_type=3, playback_direction=1, animation_timer=1234
        )
        lod = (
            U9Model.parse(_single_limb_model([face], vertices, [material]))
            .limbs[0]
            .lods[0]
        )
        self.assertEqual(lod.triangles[0].corners[0].point_offset, 10)
        self.assertEqual(lod.triangles[0].flags, 11)
        self.assertEqual(lod.triangles[0].flags2, 12)
        self.assertEqual(lod.triangles[0].plane_w, 2.25)
        self.assertEqual(lod.triangles[0].raw_material, 99)
        self.assertEqual(lod.triangles[0].collision, b"abcdefgh")
        self.assertEqual(lod.materials[0].animation_type, 3)
        self.assertEqual(lod.materials[0].playback_direction, 1)
        self.assertEqual(lod.materials[0].animation_timer, 1234)

    def test_mount_geometry_is_preserved_separately(self) -> None:
        main_vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        mount_vertices = [(10.0, 0.0, 0.0), (10.0, 1.0, 0.0), (10.0, 0.0, 1.0)]
        main_face = _face((_corner(0), _corner(1), _corner(2)))
        mount_face = _face((_corner(0), _corner(1), _corner(2)), raw_material=0xBEEF)
        lod_bytes = _lod(
            main_vertices,
            [main_face],
            [_material(7, 0, 1)],
            mount_vertices,
            [mount_face],
        )
        header = _model_header(1, 1)
        limb_header_off = MODEL_HEADER_SIZE + 8
        lod_off = limb_header_off + LIMB_HEADER_SIZE
        model = U9Model.parse(
            header
            + struct.pack("<II", limb_header_off, lod_off)
            + _limb_header(1, 1)
            + lod_bytes
        )
        lod = model.limbs[0].lods[0]
        self.assertEqual(lod.mount_vertices, tuple(mount_vertices))
        self.assertEqual(len(lod.mount_triangles), 1)
        self.assertEqual(lod.mount_triangles[0].material_index, -1)
        self.assertEqual(lod.mount_triangles[0].raw_material, 0xBEEF)

    def test_material_resolved_onto_triangle(self) -> None:
        model = U9Model.parse(_triangle_model())
        lod = model.limbs[0].lods[0]
        self.assertEqual(len(lod.materials), 1)
        self.assertEqual(lod.materials[0].texture_id, 7)
        self.assertEqual(lod.triangles[0].material_index, 0)


class MalformedModelTests(unittest.TestCase):
    def test_absurd_submesh_count_raises_cleanly(self) -> None:
        header = _model_header(submesh_count=169, lod_count=845)
        with self.assertRaises(U9ModelError):
            U9Model.parse(header)

    def test_uncovered_face_raises(self) -> None:
        data = _single_limb_model(
            [_face((_corner(0), _corner(1), _corner(2)))],
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            [],
        )
        with self.assertRaisesRegex(U9ModelError, "not covered"):
            U9Model.parse(data)

    def test_out_of_range_vertex_index_raises(self) -> None:
        data = _single_limb_model(
            [_face((_corner(0), _corner(1), _corner(99)))],
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            [_material(7, 0, 1)],
        )
        with self.assertRaisesRegex(U9ModelError, "references vertex 99"):
            U9Model.parse(data)


class ParseIndexedModelTests(unittest.TestCase):
    def test_triangle_and_quad_are_parsed_and_export_ready(self) -> None:
        data = _indexed_model()
        model = U9Model.parse(data, model_id=536)
        lod = model.limbs[0].lods[0]

        self.assertEqual(model.record_format, "indexed")
        self.assertEqual(len(model.indexed_faces), 2)
        self.assertFalse(model.indexed_faces[0].is_quad)
        self.assertTrue(model.indexed_faces[1].is_quad)
        self.assertEqual(len(lod.triangles), 3)
        self.assertEqual(
            [corner.vertex_index for corner in lod.triangles[1].corners], [0, 1, 2]
        )
        self.assertEqual(
            [corner.vertex_index for corner in lod.triangles[2].corners], [0, 2, 3]
        )
        self.assertEqual([material.texture_id for material in lod.materials], [7, 8])
        self.assertEqual(model.trailing_data, b"TAIL")
        self.assertEqual(model.to_bytes(), data)

    def test_bad_indexed_section_offset_raises(self) -> None:
        data = bytearray(_indexed_model())
        struct.pack_into("<I", data, 4, 0xAA)
        with self.assertRaisesRegex(U9ModelError, "indexed corner offset"):
            U9Model.parse(bytes(data))


if __name__ == "__main__":
    unittest.main()
