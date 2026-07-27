"""Tests for titan.u9.transform's limb-hierarchy world-space flattening.

Each case below is a hand-verifiable geometric fact (identity, pure
translation, a 90-degree rotation, non-uniform-scale normal handling,
parent-child chaining) -- exact values are computed independently here
(not copied from the implementation), matching this project's
established convention of only asserting synthetic values that are
safely hand-checkable.
"""

from __future__ import annotations

import math
import unittest

from titan.u9.transform import IDENTITY, mat4_multiply, mat4_trs, transform_normal, transform_point


def _approx_equal(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


class Mat4TrsTests(unittest.TestCase):
    def test_identity_matrix_is_identity(self) -> None:
        m = mat4_trs((0, 0, 0), (1, 0, 0, 0), (1, 1, 1))
        self.assertEqual(m, IDENTITY)

    def test_pure_translation(self) -> None:
        m = mat4_trs((10, -5, 2), (1, 0, 0, 0), (1, 1, 1))
        self.assertTrue(_approx_equal(transform_point(m, (1, 2, 3)), (11, -3, 5)))

    def test_pure_scale(self) -> None:
        m = mat4_trs((0, 0, 0), (1, 0, 0, 0), (2, 3, 4))
        self.assertTrue(_approx_equal(transform_point(m, (1, 1, 1)), (2, 3, 4)))

    def test_90_degree_rotation_around_z(self) -> None:
        half = math.radians(90) / 2
        q = (math.cos(half), 0.0, 0.0, math.sin(half))  # (w, x, y, z)
        m = mat4_trs((0, 0, 0), q, (1, 1, 1))
        self.assertTrue(_approx_equal(transform_point(m, (1, 0, 0)), (0, 1, 0)))

    def test_parent_child_chain_composes_translations(self) -> None:
        parent = mat4_trs((5, 0, 0), (1, 0, 0, 0), (1, 1, 1))
        child_local = mat4_trs((1, 0, 0), (1, 0, 0, 0), (1, 1, 1))
        child_world = mat4_multiply(parent, child_local)
        self.assertTrue(_approx_equal(transform_point(child_world, (0, 0, 0)), (6, 0, 0)))


class TransformNormalTests(unittest.TestCase):
    def test_identity_leaves_normal_unchanged(self) -> None:
        self.assertTrue(_approx_equal(transform_normal(IDENTITY, (0, 1, 0)), (0, 1, 0)))

    def test_non_uniform_scale_preserves_normal_perpendicular_to_stretch_axis(self) -> None:
        # stretching X shouldn't affect a normal that's purely in Y or Z.
        m = mat4_trs((0, 0, 0), (1, 0, 0, 0), (2, 1, 1))
        self.assertTrue(_approx_equal(transform_normal(m, (0, 1, 0)), (0, 1, 0)))
        self.assertTrue(_approx_equal(transform_normal(m, (0, 0, 1)), (0, 0, 1)))

    def test_translation_does_not_affect_normals(self) -> None:
        m = mat4_trs((100, 200, 300), (1, 0, 0, 0), (1, 1, 1))
        self.assertTrue(_approx_equal(transform_normal(m, (1, 0, 0)), (1, 0, 0)))


if __name__ == "__main__":
    unittest.main()
