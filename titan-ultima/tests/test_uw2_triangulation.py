"""Tests for planar face triangulation of UW2 executable models.

Faces in these models are not all convex. A bed's side is one outline tracing
up the foot post, along the rail, up the head post and back underneath, which
leaves a notch between the posts. Fanning from the first vertex filled that
notch solid and welded the posts to the frame; eight of the thirty-two models
were mis-shaped that way.
"""

from __future__ import annotations

import unittest

from titan.uw2.exe_models import ModelVertex, _triangulate_polygon


def _polygon(points: list[tuple[float, float]]) -> list[ModelVertex]:
    """Build a face in the XZ plane, as the bed's side panels are."""
    return [ModelVertex(x, 0.0, z) for x, z in points]


def _area_2d(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for index, (x, z) in enumerate(points):
        next_x, next_z = points[(index + 1) % len(points)]
        total += x * next_z - next_x * z
    return abs(total) / 2.0


def _triangulated_area(
    points: list[tuple[float, float]], triangles: list[tuple[int, int, int]]
) -> float:
    total = 0.0
    for first, second, third in triangles:
        ax, az = points[first]
        bx, bz = points[second]
        cx, cz = points[third]
        total += abs((bx - ax) * (cz - az) - (cx - ax) * (bz - az)) / 2.0
    return total


SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

# Two posts with a rail between them, and a notch underneath - the shape that
# exposed the bug.
BED_SIDE = [
    (0.0, 0.0),
    (0.0, 1.0),
    (0.2, 1.0),
    (0.2, 0.4),
    (0.8, 0.4),
    (0.8, 1.0),
    (1.0, 1.0),
    (1.0, 0.0),
]
NOTCH_POINT = (0.7, 0.6)
"""Inside the notch between the posts, and inside the fan's coverage."""


class UW2TriangulationTests(unittest.TestCase):
    def test_triangle_passes_straight_through(self) -> None:
        self.assertEqual(
            _triangulate_polygon(_polygon([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])),
            [(0, 1, 2)],
        )

    def test_degenerate_input_yields_nothing(self) -> None:
        self.assertEqual(_triangulate_polygon(_polygon([(0.0, 0.0)])), [])
        self.assertEqual(_triangulate_polygon([]), [])

    def test_convex_face_area_is_preserved(self) -> None:
        triangles = _triangulate_polygon(_polygon(SQUARE))

        self.assertEqual(len(triangles), len(SQUARE) - 2)
        self.assertAlmostEqual(
            _triangulated_area(SQUARE, triangles), _area_2d(SQUARE), places=6
        )

    def test_concave_face_area_is_preserved(self) -> None:
        # A fan from vertex 0 covers the notch too, inflating the area.
        triangles = _triangulate_polygon(_polygon(BED_SIDE))

        self.assertEqual(len(triangles), len(BED_SIDE) - 2)
        self.assertAlmostEqual(
            _triangulated_area(BED_SIDE, triangles), _area_2d(BED_SIDE), places=6
        )

    def test_concave_notch_is_left_open(self) -> None:
        triangles = _triangulate_polygon(_polygon(BED_SIDE))

        for first, second, third in triangles:
            with self.subTest(triangle=(first, second, third)):
                self.assertFalse(
                    _inside(
                        BED_SIDE[first],
                        BED_SIDE[second],
                        BED_SIDE[third],
                        NOTCH_POINT,
                    ),
                    "the gap between the bed posts was filled in",
                )

    def test_a_fan_would_have_filled_the_notch(self) -> None:
        # Guards the test itself: the fixture really does exercise the bug.
        fan = [(0, i, i + 1) for i in range(1, len(BED_SIDE) - 1)]

        self.assertGreater(
            _triangulated_area(BED_SIDE, fan),
            _area_2d(BED_SIDE) + 1e-6,
            "a fan should over-cover this outline",
        )
        self.assertTrue(
            any(
                _inside(BED_SIDE[a], BED_SIDE[b], BED_SIDE[c], NOTCH_POINT)
                for a, b, c in fan
            )
        )

    def test_reversed_winding_is_handled(self) -> None:
        triangles = _triangulate_polygon(_polygon(list(reversed(BED_SIDE))))
        reversed_points = list(reversed(BED_SIDE))

        self.assertAlmostEqual(
            _triangulated_area(reversed_points, triangles),
            _area_2d(BED_SIDE),
            places=6,
        )

    def test_every_index_stays_in_range(self) -> None:
        triangles = _triangulate_polygon(_polygon(BED_SIDE))

        for triple in triangles:
            for index in triple:
                self.assertTrue(0 <= index < len(BED_SIDE))


def _inside(a, b, c, point) -> bool:
    def cross(origin, first, second):
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    first = cross(a, b, point)
    second = cross(b, c, point)
    third = cross(c, a, point)
    return (first > 0 and second > 0 and third > 0) or (
        first < 0 and second < 0 and third < 0
    )


if __name__ == "__main__":
    unittest.main()
