"""Tests for titan.u9.highway's static/highway.dat decoder.

Fixtures match the byte layout verified against the real 12,428-byte
``static/highway.dat`` -- 817 points, 149 routes, a declared route block of
2,612 bytes consumed exactly, and every path node resolving to a declared
point. See the module docstring.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.highway import U9Highway, U9HighwayError


def _points(points: list[tuple[int, int, int]]) -> bytes:
    return b"".join(struct.pack("<3I", *p) for p in points)


def _route(start: int, last: int, distance: int, path: list[int], unknown: int = 0) -> bytes:
    return struct.pack("<5H", start, last, len(path), distance, unknown) + struct.pack(
        f"<{len(path)}H", *path
    )


def _build(points: list[tuple[int, int, int]], routes: list[bytes]) -> bytes:
    block = b"".join(routes)
    return (
        struct.pack("<II", len(points), len(routes))
        + _points(points)
        + struct.pack("<I", len(block))
        + block
    )


POINTS = [
    (50000, 1254, 14640),
    (50001, 1214, 13577),
    (50002, 1328, 13495),
    (50003, 2356, 13484),
]


class HighwayHeaderTests(unittest.TestCase):
    def test_parses_counts_and_points(self) -> None:
        highway = U9Highway(_build(POINTS, [_route(50000, 50003, 42, [50000, 50001, 50003])]))
        self.assertEqual(len(highway.points), 4)
        self.assertEqual(highway.declared_point_count, 4)
        self.assertEqual(highway.points[0].trigger_id, 50000)
        self.assertEqual((highway.points[0].x, highway.points[0].y), (1254, 14640))

    def test_route_block_size_is_consumed_exactly(self) -> None:
        routes = [
            _route(50000, 50003, 42, [50000, 50001, 50003]),
            _route(50003, 50000, 42, [50003, 50001, 50000]),
        ]
        highway = U9Highway(_build(POINTS, routes))
        self.assertEqual(len(highway.routes), 2)
        self.assertEqual(highway.route_bytes_consumed, highway.route_bytes)
        self.assertTrue(highway.is_complete)

    def test_empty_file_is_valid(self) -> None:
        highway = U9Highway(_build([], []))
        self.assertEqual(highway.points, ())
        self.assertEqual(highway.routes, ())
        self.assertTrue(highway.is_complete)

    def test_rejects_short_data(self) -> None:
        with self.assertRaises(U9HighwayError):
            U9Highway(b"\x00\x00\x00\x00")

    def test_rejects_point_count_past_end_of_file(self) -> None:
        data = bytearray(_build(POINTS, []))
        struct.pack_into("<I", data, 0, 10_000)
        with self.assertRaises(U9HighwayError):
            U9Highway(bytes(data))

    def test_rejects_route_block_larger_than_the_file(self) -> None:
        data = bytearray(_build(POINTS, [_route(50000, 50001, 5, [50000, 50001])]))
        struct.pack_into("<I", data, 8 + len(POINTS) * 12, 0xFFFF)
        with self.assertRaises(U9HighwayError):
            U9Highway(bytes(data))


class HighwayRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _build(
            POINTS,
            [
                _route(50000, 50003, 82, [50000, 50001, 50002, 50003]),
                _route(50003, 50000, 82, [50003, 50002, 50001, 50000]),
                _route(50001, 50002, 10, [50001, 50002]),
            ],
        )

    def test_route_fields(self) -> None:
        route = U9Highway(self.data).routes[0]
        self.assertEqual(route.start_trigger_id, 50000)
        self.assertEqual(route.last_trigger_id, 50003)
        self.assertEqual(route.path_length, 4)
        self.assertEqual(route.route_distance, 82)
        self.assertEqual(route.unknown, 0)
        self.assertEqual(route.path, (50000, 50001, 50002, 50003))

    def test_path_is_self_inclusive(self) -> None:
        # The real file stores the endpoints as the first and last path nodes.
        for route in U9Highway(self.data).routes:
            self.assertEqual(route.path[0], route.start_trigger_id)
            self.assertEqual(route.path[-1], route.last_trigger_id)

    def test_hops_is_one_fewer_than_nodes(self) -> None:
        route = U9Highway(self.data).routes[0]
        self.assertEqual(route.hops, 3)

    def test_variable_length_routes_are_walked_in_order(self) -> None:
        highway = U9Highway(self.data)
        self.assertEqual([r.path_length for r in highway.routes], [4, 4, 2])

    def test_routes_from_and_through(self) -> None:
        highway = U9Highway(self.data)
        self.assertEqual(len(highway.routes_from(50000)), 1)
        self.assertEqual(len(highway.routes_from(50003)), 1)
        self.assertEqual(len(highway.routes_through(50002)), 3)
        self.assertEqual(highway.routes_from(99999), [])


class HighwayLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.highway = U9Highway(_build(POINTS, [_route(50000, 50001, 5, [50000, 50001])]))

    def test_point_lookup_by_trigger_id(self) -> None:
        point = self.highway.point(50002)
        assert point is not None
        self.assertEqual((point.x, point.y), (1328, 13495))

    def test_unknown_trigger_id_returns_none(self) -> None:
        self.assertIsNone(self.highway.point(1))

    def test_unknown_path_nodes_is_empty_when_consistent(self) -> None:
        self.assertEqual(self.highway.unknown_path_nodes(), [])

    def test_unknown_path_nodes_reports_dangling_references(self) -> None:
        highway = U9Highway(_build(POINTS, [_route(50000, 60001, 5, [50000, 60001])]))
        self.assertEqual(highway.unknown_path_nodes(), [60001])


class HighwayGraphTests(unittest.TestCase):
    def test_neighbors_are_undirected_consecutive_pairs(self) -> None:
        highway = U9Highway(
            _build(POINTS, [_route(50000, 50003, 82, [50000, 50001, 50002, 50003])])
        )
        adjacency = highway.neighbors()
        self.assertEqual(adjacency[50000], {50001})
        self.assertEqual(adjacency[50001], {50000, 50002})
        self.assertEqual(adjacency[50002], {50001, 50003})
        self.assertEqual(adjacency[50003], {50002})

    def test_reverse_routes_merge_into_one_edge_set(self) -> None:
        highway = U9Highway(
            _build(
                POINTS,
                [
                    _route(50000, 50002, 20, [50000, 50001, 50002]),
                    _route(50002, 50000, 20, [50002, 50001, 50000]),
                ],
            )
        )
        adjacency = highway.neighbors()
        self.assertEqual(adjacency[50001], {50000, 50002})
        edges = sum(len(v) for v in adjacency.values()) // 2
        self.assertEqual(edges, 2)

    def test_points_absent_from_routes_are_not_in_the_graph(self) -> None:
        highway = U9Highway(_build(POINTS, [_route(50000, 50001, 5, [50000, 50001])]))
        adjacency = highway.neighbors()
        self.assertNotIn(50003, adjacency)
        self.assertIsNotNone(highway.point(50003))


class HighwayTruncationTests(unittest.TestCase):
    """A short route block is reported, not silently accepted."""

    def test_missing_routes_are_reported_by_is_complete(self) -> None:
        data = bytearray(_build(POINTS, [_route(50000, 50001, 5, [50000, 50001])]))
        # Claim two routes while only one is present.
        struct.pack_into("<I", data, 4, 2)
        highway = U9Highway(bytes(data))
        self.assertEqual(len(highway.routes), 1)
        self.assertEqual(highway.declared_route_count, 2)
        self.assertFalse(highway.is_complete)

    def test_trailing_bytes_are_rejected(self) -> None:
        data = _build(POINTS, [_route(50000, 50001, 5, [50000, 50001])]) + b"\x00" * 16
        with self.assertRaises(U9HighwayError):
            U9Highway(data)

    def test_unrelated_zero_headed_file_is_rejected(self) -> None:
        # An FLX archive opens with a 76-byte NUL comment, so a lenient
        # reader would read point_count/route_count as 0 and take it for a
        # valid empty graph.
        with self.assertRaises(U9HighwayError):
            U9Highway(b"\x00" * 76 + b"\x01" * 200)


if __name__ == "__main__":
    unittest.main()
