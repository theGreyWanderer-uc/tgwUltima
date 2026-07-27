"""Tests for titan.u9.icon's "claimed by a mesh vs. not" 2D icon split.

Two layers are tested separately:

* ``_texture_ids_for_model``/object-level behavior (multiple limbs/LODs,
  a ``None`` LOD, invisible-material exclusion) uses hand-built
  :class:`U9Model` objects directly, the same shortcut
  test_u9_mesh_export.py uses -- no binary parsing involved, so no
  binary fixture is needed to exercise this traversal logic.
* ``used_texture_ids``/``icon_entry_indices`` (the archive-level glue)
  needs real parseable ``sappear.flx``-shaped binary, so those reuse
  the same hand-built binary layout validated in test_u9_model.py
  (see that file's module docstring for the real-data cross-check)
  and the same FLX container layout validated in
  test_u9_flx_archive.py.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.icon import _texture_ids_for_model, icon_entry_indices, used_texture_ids
from titan.u9.model import (
    INVISIBLE_TEXTURE_ID,
    U9Limb,
    U9Material,
    U9Model,
    U9SubmeshLod,
    U9Triangle,
    U9TriangleCorner,
)

# ---------------------------------------------------------------------------
# Object-level fixtures (no binary parsing) -- mirrors test_u9_mesh_export.py
# ---------------------------------------------------------------------------


def _material(texture_id: int) -> U9Material:
    return U9Material(
        texture_id=texture_id, subtexture_count=0, first_face=0, face_count=1,
        default_alpha=255, modified_alpha=255, anim_start=0, anim_end=0, cur_frame=0, anim_speed=0,
    )


def _triangle(material_index: int = 0) -> U9Triangle:
    normal = (0.0, 0.0, 1.0)
    corners = tuple(
        U9TriangleCorner(vertex_index=i, normal=normal, uv=(float(i), 0.0)) for i in range(3)
    )
    return U9Triangle(corners=corners, material_index=material_index, face_normal=normal, color=(255, 255, 255, 255))


def _lod(texture_ids: tuple[int, ...]) -> U9SubmeshLod:
    materials = tuple(_material(t) for t in texture_ids)
    triangles = tuple(_triangle(material_index=i) for i in range(len(materials)))
    return U9SubmeshLod(
        lod_index=0, vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), triangles=triangles,
        materials=materials, sphere_center=(0.0, 0.0, 0.0), sphere_radius=1.0,
        min_bounds=(0.0, 0.0, 0.0), max_bounds=(1.0, 1.0, 0.0),
    )


def _limb(limb_id: int, lods: tuple) -> U9Limb:
    return U9Limb(
        limb_id=limb_id, parent_id=limb_id, scale=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0),
        rotation=(1.0, 0.0, 0.0, 0.0), lods=lods,
    )


def _model(model_id: int, limbs: tuple) -> U9Model:
    return U9Model(
        model_id=model_id, cylinder_base_center=(0.0, 0.0, 0.0), cylinder_base_height=0.0,
        cylinder_base_radius=0.0, sphere_center=(0.0, 0.0, 0.0), sphere_radius=1.0,
        min_bounds=(-1.0, -1.0, -1.0), max_bounds=(1.0, 1.0, 1.0), lod_thresholds=(0, 0, 0, 0),
        center_of_mass=(0.0, 0.0, 0.0), limbs=limbs,
    )


class TextureIdsForModelTests(unittest.TestCase):
    def test_collects_texture_ids_across_limbs_and_lods(self) -> None:
        model = _model(1, (_limb(1, (_lod((10, 11)),)), _limb(2, (_lod((12,)),))))
        self.assertEqual(_texture_ids_for_model(model), {10, 11, 12})

    def test_skips_none_lod(self) -> None:
        model = _model(1, (_limb(1, (None, _lod((5,)))),))
        self.assertEqual(_texture_ids_for_model(model), {5})

    def test_excludes_invisible_material(self) -> None:
        model = _model(1, (_limb(1, (_lod((INVISIBLE_TEXTURE_ID, 7)),)),))
        self.assertEqual(_texture_ids_for_model(model), {7})


# ---------------------------------------------------------------------------
# Archive-level fixtures: real binary, same layout as test_u9_model.py /
# test_u9_flx_archive.py (kept minimal -- one material, one triangle).
# ---------------------------------------------------------------------------

MODEL_HEADER_SIZE = 0x90
LIMB_HEADER_SIZE = 0x30
LOD_HEADER_SIZE = 0x7C
FACE_SIZE = 0x7C
MATERIAL_SIZE = 0x18
DIR_OFFSET = 0x80


def _model_header() -> bytes:
    data = (
        struct.pack("<II", 1, 1)
        + struct.pack("<3f", 0, 0, 0) + struct.pack("<2f", 0, 0)
        + struct.pack("<3f", 0, 0, 0) + struct.pack("<f", 1.0) + struct.pack("<f", 0)
        + struct.pack("<3f", -1, -1, -1) + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<4I", 100, 200, 300, 400) + struct.pack("<3f", 0, 0, 0)
    )
    return data + b"\x00" * (MODEL_HEADER_SIZE - len(data))


def _limb_header_bytes() -> bytes:
    return (
        struct.pack("<II", 1, 1) + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<3f", 0, 0, 0) + struct.pack("<4f", 1, 0, 0, 0)
    )


def _corner_bytes(vertex_index: int, uv: tuple[float, float]) -> bytes:
    return struct.pack("<II", vertex_index, 0) + struct.pack("<3f", 0, 0, 1) + struct.pack("<2f", *uv)


def _face_bytes() -> bytes:
    data = b"".join(_corner_bytes(i, (float(i), 0.0)) for i in range(3))
    data += struct.pack("<II", 0, 0) + struct.pack("<3f", 0, 0, 1) + struct.pack("<f", 0.0)
    data += struct.pack("<I", 0) + bytes((255, 255, 255, 255)) + b"\x00" * 8
    assert len(data) == FACE_SIZE
    return data


def _material_bytes(texture_id: int) -> bytes:
    data = struct.pack("<6H", texture_id, 0, 0, 0, 0, 1)
    data += bytes([255, 255, 0, 0, 0, 0, 0, 0]) + struct.pack("<I", 0)
    assert len(data) == MATERIAL_SIZE
    return data


def _one_material_model_bytes(texture_id: int) -> bytes:
    """One limb, one LOD, one triangle, one material referencing *texture_id*."""
    face_bytes = _face_bytes()
    vertex_bytes = b"".join(struct.pack("<3f", *v) for v in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
    material_bytes = _material_bytes(texture_id)
    faces_off = LOD_HEADER_SIZE
    vertices_off = faces_off + len(face_bytes)
    materials_off = vertices_off + len(vertex_bytes)

    lod_header = (
        struct.pack("<I", 1) + struct.pack("<I", 0) + struct.pack("<I", 0)
        + struct.pack("<3f", 0, 0, 0) + struct.pack("<f", 1.0)
        + struct.pack("<3f", -1, -1, -1) + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<II", 0, 0) + struct.pack("<I", 1) + struct.pack("<I", 0)
        + struct.pack("<I", 3) + struct.pack("<I", 0) + struct.pack("<I", 1) + struct.pack("<I", 1)
        + struct.pack("<I", faces_off) + struct.pack("<I", 0) + struct.pack("<I", vertices_off)
        + struct.pack("<I", 0) + struct.pack("<I", materials_off)
        + struct.pack("<4I", 0, 0, 0, 0) + struct.pack("<I", 0)
    )
    assert len(lod_header) == LOD_HEADER_SIZE
    lod_bytes = lod_header + b"\x00\x00\x00\x00" + face_bytes + vertex_bytes + material_bytes

    header = _model_header()
    limb_header_off = MODEL_HEADER_SIZE + 4 + 4
    lod_off = limb_header_off + LIMB_HEADER_SIZE
    offset_table = struct.pack("<II", limb_header_off, lod_off)
    return header + offset_table + _limb_header_bytes() + lod_bytes


def _build_flx(entries_data: list[bytes | None]) -> bytes:
    """Minimal valid FLX archive: header + directory + entry payloads (see test_u9_flx_archive.py)."""
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    struct.pack_into("<I", header, 0x50, count)

    payload = bytearray()
    dir_entries: list[tuple[int, int]] = []
    cursor = DIR_OFFSET + dir_size
    for data in entries_data:
        if data is None:
            dir_entries.append((0, 0))
            continue
        dir_entries.append((cursor, len(data)))
        payload += data
        cursor += len(data)

    directory = bytearray()
    for offset, length in dir_entries:
        directory += struct.pack("<II", offset, length)

    return bytes(header) + bytes(directory) + bytes(payload)


class UsedTextureIdsArchiveTests(unittest.TestCase):
    def test_collects_texture_id_from_real_model_bytes(self) -> None:
        sappear = U9FlxArchive(_build_flx([_one_material_model_bytes(texture_id=42)]))
        self.assertEqual(used_texture_ids(sappear), {42})

    def test_skips_unparseable_model_without_raising(self) -> None:
        sappear = U9FlxArchive(_build_flx([_one_material_model_bytes(texture_id=42), b"\x00" * 4]))
        self.assertEqual(used_texture_ids(sappear), {42})


class IconEntryIndicesTests(unittest.TestCase):
    def test_excludes_claimed_includes_unclaimed(self) -> None:
        # texture_id 0 -- an entry's archive index doubles as its texture_id -- is
        # claimed by the model below, so textures entry 0 must be excluded; entry 1 is not.
        sappear = U9FlxArchive(_build_flx([_one_material_model_bytes(texture_id=0)]))
        textures = U9FlxArchive(_build_flx([b"claimed", b"unclaimed", None]))
        self.assertEqual(icon_entry_indices(sappear, textures), [1])
