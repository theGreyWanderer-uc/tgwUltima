"""Tests for titan.u9.mesh_export's OBJ/STL exporters.

Builds :class:`titan.u9.model.U9Model` instances directly (not from
binary fixtures -- that's covered in test_u9_model.py) to isolate
export-specific behavior: world-space hierarchy flattening, winding
reversal, invisible-material exclusion, and scale. Real per-triangle
winding-order correctness (why the default is ``reverse_winding=True``)
was validated against real game data (model 0, a 12-triangle cube: the
raw stored order disagreed with the stored face normal on all 12
faces, the swapped order agreed on all 12) -- see mesh_export's module
docstring, not re-derived here.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest

from titan.u9.mesh_export import (
    MeshExportError,
    _world_matrices,
    export_obj,
    export_stl,
)
from titan.u9.model import (
    INVISIBLE_TEXTURE_ID,
    U9Limb,
    U9Material,
    U9Model,
    U9SubmeshLod,
    U9Triangle,
    U9TriangleCorner,
)


def _material(texture_id: int, first_face: int = 0, face_count: int = 1) -> U9Material:
    return U9Material(
        texture_id=texture_id,
        flags_02=0,
        render_flags=0,
        flags_06=0,
        first_face=first_face,
        face_count=face_count,
        default_alpha=255,
        modified_alpha=255,
        anim_start=0,
        anim_end=0,
        cur_frame=0,
        anim_speed=0,
    )


def _triangle(indices=(0, 1, 2), material_index=0, normal=(0.0, 0.0, 1.0)) -> U9Triangle:
    corners = tuple(
        U9TriangleCorner(vertex_index=i, normal=normal, uv=(float(j), 0.0)) for j, i in enumerate(indices)
    )
    return U9Triangle(corners=corners, material_index=material_index, face_normal=normal, color=(255, 255, 255, 255))


def _model_header_defaults(model_id: int, limbs) -> U9Model:
    return U9Model(
        model_id=model_id,
        cylinder_base_center=(0.0, 0.0, 0.0),
        cylinder_base_height=0.0,
        cylinder_base_radius=0.0,
        sphere_center=(0.0, 0.0, 0.0),
        sphere_radius=1.0,
        min_bounds=(-1.0, -1.0, -1.0),
        max_bounds=(1.0, 1.0, 1.0),
        lod_thresholds=(0, 0, 0, 0),
        center_of_mass=(0.0, 0.0, 0.0),
        limbs=tuple(limbs),
    )


def _single_triangle_lod(texture_id: int) -> U9SubmeshLod:
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    material = _material(texture_id)
    triangle = _triangle()
    return U9SubmeshLod(
        lod_index=0,
        vertices=vertices,
        triangles=(triangle,),
        materials=(material,),
        sphere_center=(0.0, 0.0, 0.0),
        sphere_radius=1.0,
        min_bounds=(0.0, 0.0, 0.0),
        max_bounds=(1.0, 1.0, 0.0),
    )


def _parse_obj_positions(path: str) -> list[tuple[float, float, float]]:
    positions = []
    with open(path, encoding="ascii") as f:
        for line in f:
            if line.startswith("v "):
                positions.append(tuple(float(x) for x in line.split()[1:4]))
    return positions


def _parse_obj_faces(path: str) -> list[list[int]]:
    faces = []
    with open(path, encoding="ascii") as f:
        for line in f:
            if line.startswith("f "):
                faces.append([int(part.split("/")[0]) for part in line.split()[1:]])
    return faces


def _parse_obj_uvs(path: str) -> list[tuple[float, float]]:
    uvs = []
    with open(path, encoding="ascii") as f:
        for line in f:
            if line.startswith("vt "):
                parts = line.split()
                uvs.append((float(parts[1]), float(parts[2])))
    return uvs


class ExportObjWorldSpaceTests(unittest.TestCase):
    def test_root_limb_translation_applied(self) -> None:
        limb = U9Limb(
            limb_id=1,
            parent_id=1,
            scale=(1.0, 1.0, 1.0),
            position=(10.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0),
            lods=(_single_triangle_lod(texture_id=5),),
        )
        model = _model_header_defaults(1, [limb])

        out_path = self._export_tmp_obj(model)
        positions = _parse_obj_positions(out_path)
        # scale defaults to 1/40; local (1,0,0) + world offset (10,0,0) -> (11,0,0)/40
        self.assertIn((11.0 / 40, 0.0, 0.0), [tuple(round(c, 6) for c in p) for p in positions])

    def test_child_limb_inherits_parent_translation(self) -> None:
        parent = U9Limb(
            limb_id=1, parent_id=1, scale=(1.0, 1.0, 1.0), position=(10.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(None,),
        )
        child = U9Limb(
            limb_id=2, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 5.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(texture_id=5),),
        )
        model = _model_header_defaults(2, [parent, child])

        out_path = self._export_tmp_obj(model)
        positions = [tuple(round(c, 6) for c in p) for p in _parse_obj_positions(out_path)]
        # child local (0,0,0) -> world (10,5,0) -> scaled /40
        self.assertIn((10.0 / 40, 5.0 / 40, 0.0), positions)

    def _export_tmp_obj(self, model: U9Model) -> str:
        import tempfile

        tmpdir = tempfile.mkdtemp()
        out_path = tmpdir + "/out.obj"
        export_obj(model, out_path)
        return out_path


class ExportObjWindingTests(unittest.TestCase):
    def test_default_reverses_winding(self) -> None:
        limb = U9Limb(
            limb_id=1, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(texture_id=5),),
        )
        model = _model_header_defaults(1, [limb])
        import tempfile

        tmpdir = tempfile.mkdtemp()

        reversed_path = tmpdir + "/reversed.obj"
        raw_path = tmpdir + "/raw.obj"
        export_obj(model, reversed_path, scale=1.0, reverse_winding=True)
        export_obj(model, raw_path, scale=1.0, reverse_winding=False)

        # resolve each file's face indices back to actual positions (index assignment
        # order is independent per file, so comparing raw index numbers isn't meaningful).
        reversed_positions = _parse_obj_positions(reversed_path)
        raw_positions = _parse_obj_positions(raw_path)
        reversed_face = [reversed_positions[i - 1] for i in _parse_obj_faces(reversed_path)[0]]
        raw_face = [raw_positions[i - 1] for i in _parse_obj_faces(raw_path)[0]]

        # source corner order is (vtx0, vtx1, vtx2); reversed swaps to (vtx0, vtx2, vtx1).
        self.assertEqual(raw_face, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        self.assertEqual(reversed_face, [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)])


class ExportObjUvFlipTests(unittest.TestCase):
    def test_v_is_flipped_for_obj_texture_space_convention(self) -> None:
        # Real bug, confirmed and fixed against a real export: the raw parsed UV is
        # V=0 at the *top* of the source texture (titan.u9.texture's own PNG output
        # needs no flip to match the game's real images), but OBJ/OpenGL's texture
        # convention is V=0 at the *bottom* -- writing the raw value straight into a
        # `vt` line rendered every texture upside down through a real OBJ/MTL loader
        # (confirmed: a face rendered forehead-as-chin, a leather apron rendered
        # leather-side-down). Every written V must be `1.0 - raw_v`.
        vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        corners = (
            U9TriangleCorner(vertex_index=0, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.1)),
            U9TriangleCorner(vertex_index=1, normal=(0.0, 0.0, 1.0), uv=(1.0, 0.25)),
            U9TriangleCorner(vertex_index=2, normal=(0.0, 0.0, 1.0), uv=(0.0, 1.0)),
        )
        triangle = U9Triangle(
            corners=corners, material_index=0, face_normal=(0.0, 0.0, 1.0), color=(255, 255, 255, 255)
        )
        lod = U9SubmeshLod(
            lod_index=0, vertices=vertices, triangles=(triangle,), materials=(_material(5),),
            sphere_center=(0.0, 0.0, 0.0), sphere_radius=1.0,
            min_bounds=(0.0, 0.0, 0.0), max_bounds=(1.0, 1.0, 0.0),
        )
        limb = U9Limb(
            limb_id=1, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(lod,),
        )
        model = _model_header_defaults(1, [limb])

        import tempfile

        out_path = tempfile.mkdtemp() + "/out.obj"
        export_obj(model, out_path, scale=1.0)

        written_uvs = set(_parse_obj_uvs(out_path))
        self.assertEqual(written_uvs, {(0.0, 0.9), (1.0, 0.75), (0.0, 0.0)})


class ExportInvisibleMaterialTests(unittest.TestCase):
    def test_invisible_material_faces_excluded(self) -> None:
        visible_lod = _single_triangle_lod(texture_id=5)
        invisible_lod = _single_triangle_lod(texture_id=INVISIBLE_TEXTURE_ID)

        visible_limb = U9Limb(
            limb_id=1, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(visible_lod,),
        )
        invisible_limb = U9Limb(
            limb_id=2, parent_id=1, scale=(1.0, 1.0, 1.0), position=(5.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(invisible_lod,),
        )
        model = _model_header_defaults(1, [visible_limb, invisible_limb])

        import tempfile

        out_path = tempfile.mkdtemp() + "/out.obj"
        export_obj(model, out_path)
        faces = _parse_obj_faces(out_path)
        self.assertEqual(len(faces), 1)  # only the visible limb's triangle

    def test_only_invisible_geometry_raises(self) -> None:
        limb = U9Limb(
            limb_id=1, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(texture_id=INVISIBLE_TEXTURE_ID),),
        )
        model = _model_header_defaults(1, [limb])

        import tempfile

        out_path = tempfile.mkdtemp() + "/out.obj"
        with self.assertRaises(MeshExportError):
            export_obj(model, out_path)


class ExportStlTests(unittest.TestCase):
    def test_binary_stl_triangle_count_and_bounds(self) -> None:
        limb = U9Limb(
            limb_id=1, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0),
            rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(texture_id=5),),
        )
        model = _model_header_defaults(1, [limb])

        import tempfile

        out_path = tempfile.mkdtemp() + "/out.stl"
        # reverse_winding=False here so the written vertex order matches the
        # source corner order (0,1,2) exactly -- winding itself is covered by
        # ExportObjWindingTests, this test is about scale/position only.
        export_stl(model, out_path, scale=1.0, reverse_winding=False)

        with open(out_path, "rb") as f:
            data = f.read()
        tri_count = struct.unpack_from("<I", data, 80)[0]
        self.assertEqual(tri_count, 1)
        self.assertEqual(len(data), 84 + 50 * tri_count)

        # second written vertex = corner 1 = vertex_index 1 = local (1,0,0), scale 1 -> world (1,0,0)
        vx, vy, vz = struct.unpack_from("<3f", data, 84 + 12 + 12)
        self.assertAlmostEqual(vx, 1.0, places=5)


class DuplicateLimbIdRegressionTests(unittest.TestCase):
    """Three shipped models reuse a limb_id across limbs with different transforms.

    ``sappear.flx`` models 217, 775 and 1296 each carry two or more limbs
    sharing one ``limb_id``. Resolving world matrices into a dict keyed by
    ``limb_id`` keeps only the last of them, so every copy is placed at that
    one's position -- model 775's three ``limb_id=91`` limbs, stored at
    (-49.6, 27.2, 0), (30.4, 44.8, 0) and (22.4, -25.6, 0), all collapsed onto
    the third. Matrices are keyed by limb index instead.
    """

    def _duplicate_id_model(self) -> U9Model:
        # two limbs, same limb_id, different translations, both roots
        limbs = [
            U9Limb(limb_id=7, parent_id=7, scale=(1.0, 1.0, 1.0), position=(10.0, 0.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
            U9Limb(limb_id=7, parent_id=7, scale=(1.0, 1.0, 1.0), position=(0.0, 20.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
        ]
        return _model_header_defaults(775, limbs)

    def test_duplicate_ids_keep_their_own_transforms(self) -> None:
        matrices = _world_matrices(self._duplicate_id_model())
        self.assertEqual(len(matrices), 2)
        translations = [(matrices[i][3], matrices[i][7], matrices[i][11]) for i in (0, 1)]
        self.assertEqual(translations, [(10.0, 0.0, 0.0), (0.0, 20.0, 0.0)])

    def test_export_does_not_collapse_duplicate_limbs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dup.obj")
            export_obj(self._duplicate_id_model(), path, scale=1.0)
            xs = {round(p[0], 3) for p in _parse_obj_positions(path)}
            ys = {round(p[1], 3) for p in _parse_obj_positions(path)}
        # the second limb must still contribute geometry 20 units up in Y
        self.assertIn(10.0, xs)
        self.assertIn(20.0, ys)

    def test_parent_named_by_a_duplicated_id_resolves_to_the_first(self) -> None:
        limbs = [
            U9Limb(limb_id=3, parent_id=3, scale=(1.0, 1.0, 1.0), position=(5.0, 0.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
            U9Limb(limb_id=3, parent_id=3, scale=(1.0, 1.0, 1.0), position=(0.0, 9.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
            U9Limb(limb_id=4, parent_id=3, scale=(1.0, 1.0, 1.0), position=(1.0, 0.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
        ]
        matrices = _world_matrices(_model_header_defaults(1, limbs))
        # child of "limb 3" rides the *first* limb 3 (5,0,0), not the second
        self.assertEqual((matrices[2][3], matrices[2][7], matrices[2][11]), (6.0, 0.0, 0.0))


class ImplicitRootRegressionTests(unittest.TestCase):
    """505 shipped models point a limb at parent 0, which is never stored.

    Limb 0 is an implicit model root that no ``sappear.flx`` record writes out.
    A limb naming it must fall back to its own local transform rather than
    being dropped or resolved against a missing parent.
    """

    def test_missing_parent_falls_back_to_the_local_transform(self) -> None:
        limbs = [
            U9Limb(limb_id=1, parent_id=0, scale=(1.0, 1.0, 1.0), position=(3.0, 4.0, 5.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
        ]
        matrices = _world_matrices(_model_header_defaults(2, limbs))
        self.assertEqual((matrices[0][3], matrices[0][7], matrices[0][11]), (3.0, 4.0, 5.0))

    def test_parent_cycle_still_terminates(self) -> None:
        limbs = [
            U9Limb(limb_id=1, parent_id=2, scale=(1.0, 1.0, 1.0), position=(1.0, 0.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
            U9Limb(limb_id=2, parent_id=1, scale=(1.0, 1.0, 1.0), position=(0.0, 1.0, 0.0),
                   rotation=(1.0, 0.0, 0.0, 0.0), lods=(_single_triangle_lod(1),)),
        ]
        matrices = _world_matrices(_model_header_defaults(3, limbs))
        self.assertEqual(len(matrices), 2)


if __name__ == "__main__":
    unittest.main()
