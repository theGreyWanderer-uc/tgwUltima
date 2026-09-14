"""
``static/highway.dat`` reader for Ultima 9: Ascension.

U9's NPC navigation network: a graph of "highway points" scattered through
the world, plus a set of precomputed routes through that graph. The points
are the U9 equivalent of Ultima 7's patheggs -- invisible markers an NPC
can navigate between -- and the routes let the engine answer "how do I get
from A to B" with a table lookup instead of solving the whole map path,
falling back to local pathfinding between consecutive nodes.

Points do not carry identifiers of their own. They are keyed by **trigger
ID**, the same identifier space as :mod:`titan.u9.nonfixed`'s
``U9Entity.trigger_id``, which is what ties the abstract graph to concrete
world markers. Byte-for-byte::

    0x00  point_count       u32
    0x04  route_count       u32
    0x08  points            point_count * 12 bytes:
              0x00  trigger_id   u32
              0x04  x            u32  -- absolute world X
              0x08  y            u32  -- absolute world Y
    ...   route_bytes       u32  -- total size of the route block below
    ...   routes            route_count * variable:
              0x00  start_trigger_id  u16
              0x02  last_trigger_id   u16
              0x04  path_length       u16  -- number of u16 node IDs following
              0x06  route_distance    u16  -- total distance to travel
              0x08  unknown           u16  -- zero in every route seen
              0x0A  path              u16 * path_length

All integers are little-endian. A route's ``path`` is self-inclusive: its
first element is ``start_trigger_id`` and its last is ``last_trigger_id``.

The layout is the one published on the Ultima Codex wiki (Ultima IX
Internal Formats). Verified here against the real 12,428-byte
``static/highway.dat``: 817 points and 149 routes, ``route_bytes`` of 2,612
matching the remaining bytes exactly, all 149 routes consuming that block
with zero remainder, and all 561 path references resolving to declared
points.

Cross-checked against real world data with :mod:`titan.u9.nonfixed`: 815 of
the 817 points (99.8%) have an entity of type 1134 -- unnamed in
``TYPENAME.FLX``, i.e. an invisible marker -- sitting at exactly the
``x``/``y`` this file declares. Entities of other types sharing a highway
trigger ID never agree on position, so type 1134 is what physically
constitutes a highway node. Trigger IDs are reused across regions, so
roughly four other type-1134 markers share each ID; only the owning
region's sits at the documented coordinates.

Example::

    from titan.u9.highway import U9Highway

    highway = U9Highway.from_file("static/highway.dat")
    print(len(highway.points), len(highway.routes))   # 817 149
    print(highway.point(50000))                       # U9HighwayPoint(...)
    for route in highway.routes_from(53508):
        print(route.last_trigger_id, route.route_distance, route.path)
"""

from __future__ import annotations

__all__ = [
    "U9Highway",
    "U9HighwayError",
    "U9HighwayPoint",
    "U9HighwayRoute",
]

import os
import struct
from dataclasses import dataclass

HEADER_SIZE = 8
POINT_SIZE = 12
POINT_STRUCT = "<3I"
ROUTE_HEADER_SIZE = 0x0A
ROUTE_HEADER_STRUCT = "<5H"


class U9HighwayError(Exception):
    """Raised on malformed ``static/highway.dat`` data."""


@dataclass(frozen=True)
class U9HighwayPoint:
    """One navigation node, keyed by the trigger ID of its world marker."""

    trigger_id: int
    x: int
    y: int


@dataclass(frozen=True)
class U9HighwayRoute:
    """One precomputed route between two highway points."""

    start_trigger_id: int
    last_trigger_id: int
    path_length: int
    route_distance: int
    unknown: int
    path: tuple[int, ...]

    @property
    def hops(self) -> int:
        """Number of moves along the route -- one fewer than its node count."""
        return max(len(self.path) - 1, 0)


class U9Highway:
    """Reader for ``static/highway.dat``."""

    def __init__(self, data: bytes) -> None:
        if len(data) < HEADER_SIZE:
            raise U9HighwayError(f"data too small to contain a highway header: {len(data)} bytes")

        point_count, route_count = struct.unpack_from("<II", data, 0)

        points_end = HEADER_SIZE + point_count * POINT_SIZE
        if points_end + 4 > len(data):
            raise U9HighwayError(
                f"truncated: {point_count} points need {points_end + 4} bytes, "
                f"file is {len(data)} bytes -- not a highway.dat?"
            )

        self._data = data
        self.points: tuple[U9HighwayPoint, ...] = tuple(
            U9HighwayPoint(*struct.unpack_from(POINT_STRUCT, data, HEADER_SIZE + i * POINT_SIZE))
            for i in range(point_count)
        )

        self.route_bytes = struct.unpack_from("<I", data, points_end)[0]
        self.routes_offset = points_end + 4

        # The layout has no slack: the header, point table and route block
        # account for every byte. Requiring that is what stops an unrelated
        # file whose first eight bytes happen to be zero -- an FLX archive,
        # say -- from parsing as a valid empty graph.
        expected = self.routes_offset + self.route_bytes
        if expected != len(data):
            raise U9HighwayError(
                f"size mismatch: {point_count} points and a {self.route_bytes}-byte "
                f"route block account for {expected} bytes, file is {len(data)} "
                f"bytes -- truncated, or not a highway.dat?"
            )

        routes: list[U9HighwayRoute] = []
        pos = self.routes_offset
        limit = self.routes_offset + self.route_bytes
        for _ in range(route_count):
            if pos + ROUTE_HEADER_SIZE > limit:
                break
            start, last, path_length, distance, unknown = struct.unpack_from(
                ROUTE_HEADER_STRUCT, data, pos
            )
            end = pos + ROUTE_HEADER_SIZE + path_length * 2
            if end > limit:
                break
            path = struct.unpack_from(f"<{path_length}H", data, pos + ROUTE_HEADER_SIZE)
            routes.append(
                U9HighwayRoute(
                    start_trigger_id=start,
                    last_trigger_id=last,
                    path_length=path_length,
                    route_distance=distance,
                    unknown=unknown,
                    path=path,
                )
            )
            pos = end
        self.routes: tuple[U9HighwayRoute, ...] = tuple(routes)

        # Declared vs actually parsed, so callers can tell a clean file from
        # a truncated one without re-deriving the arithmetic.
        self.declared_point_count = point_count
        self.declared_route_count = route_count
        self.route_bytes_consumed = pos - self.routes_offset

        self._by_id = {p.trigger_id: p for p in self.points}

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Highway:
        with open(filepath, "rb") as f:
            return cls(f.read())

    @property
    def is_complete(self) -> bool:
        """True when every declared route parsed, consuming the block exactly.

        The constructor already rejects a file whose size does not match its
        own header, so this reports the narrower case of a route block that
        holds fewer records than ``route_count`` claims.
        """
        return (
            len(self.points) == self.declared_point_count
            and len(self.routes) == self.declared_route_count
            and self.route_bytes_consumed == self.route_bytes
        )

    def point(self, trigger_id: int) -> U9HighwayPoint | None:
        """One point by trigger ID, or ``None`` if this file declares no such node."""
        return self._by_id.get(trigger_id)

    def unknown_path_nodes(self) -> list[int]:
        """Trigger IDs referenced by routes that no declared point defines.

        Empty on the shipped file -- a non-empty result means the route
        block and the point table disagree.
        """
        referenced: set[int] = set()
        for route in self.routes:
            referenced.update(route.path)
            referenced.add(route.start_trigger_id)
            referenced.add(route.last_trigger_id)
        return sorted(referenced - set(self._by_id))

    def routes_from(self, trigger_id: int) -> list[U9HighwayRoute]:
        """Routes starting at one point."""
        return [r for r in self.routes if r.start_trigger_id == trigger_id]

    def routes_through(self, trigger_id: int) -> list[U9HighwayRoute]:
        """Routes whose path visits one point, at any position."""
        return [r for r in self.routes if trigger_id in r.path]

    def neighbors(self) -> dict[int, set[int]]:
        """Adjacency built from consecutive node pairs across every route.

        Undirected: routes are stored in both directions where the game
        needs them, and this merges both into one edge set per node.
        """
        adjacency: dict[int, set[int]] = {}
        for route in self.routes:
            for a, b in zip(route.path, route.path[1:]):
                adjacency.setdefault(a, set()).add(b)
                adjacency.setdefault(b, set()).add(a)
        return adjacency
