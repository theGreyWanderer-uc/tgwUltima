"""Lossless reader for Ultima IX ``static/rgbccube.dat`` and ``static/yiqccube.dat``.

**Neither file is loaded by the retail game.** Retail 1.19F keeps a file-name
pointer for each (``0x007868BC`` and ``0x007868C0``) but nothing reads either
pointer and neither name appears anywhere else in ``u9.exe``. They are caches
written by the authoring tool to speed up colour matching against the palette.
Titan reads them as historical data and never regenerates or rebalances them.

Layout (little-endian)::

    256 x (red, green, blue, flags)   -- the palette the cache was built from
    node                              -- root of an octree over RGB space

    node:
        uint32 count
        count > 0:  count bytes       -- leaf: candidate palette indices
        count == 0: 8 child nodes     -- internal, children 0..7 in order

The root covers the whole 0..255 cube. Child ``n`` of a node splits each axis
at the node's midpoint: bit 0 of ``n`` selects the upper red half, bit 1 green
and bit 2 blue. To match a colour the tool descends to the leaf containing it
and picks the candidate whose stored palette colour is nearest, using squared
RGB distance for ``rgbccube.dat`` and a YIQ-space distance for
``yiqccube.dat``. The two files share this grammar exactly; only the metric
used to build and query them differs, and the file does not record it.

In the shipped copies the palette prefix equals ``ankh.pal`` byte for byte,
both trees end exactly at the end of the file, and every candidate is in
``10..245`` -- the palette range the tool matched against.
"""

from __future__ import annotations

__all__ = [
    "MAX_TREE_DEPTH",
    "METRICS",
    "PALETTE_PREFIX_SIZE",
    "U9ColorCube",
    "U9ColorCubeError",
    "U9ColorCubeNode",
    "metric_for_filename",
]

import os
import struct
from dataclasses import dataclass
from pathlib import Path

PALETTE_PREFIX_SIZE = 256 * 4
# Eight halvings exhaust the 8-bit colour axes, so no lookup can reach deeper.
MAX_TREE_DEPTH = 8
METRICS = ("rgb", "yiq")
_COUNT = struct.Struct("<I")
_CHILDREN = 8

RGB = tuple[int, int, int]


class U9ColorCubeError(Exception):
    """Raised when a colour-cube file is truncated or its tree cannot close."""


@dataclass(frozen=True)
class U9ColorCubeNode:
    """One tree node, in the stored depth-first order."""

    offset: int
    depth: int
    path: tuple[int, ...]
    count: int
    candidates: bytes

    @property
    def is_leaf(self) -> bool:
        return self.count > 0

    @property
    def cube_origin(self) -> RGB:
        """The lowest ``(red, green, blue)`` corner this node covers."""
        red = green = blue = 0
        for depth, child in enumerate(self.path):
            half = 128 >> depth
            red += half if child & 1 else 0
            green += half if child & 2 else 0
            blue += half if child & 4 else 0
        return red, green, blue

    @property
    def cube_size(self) -> int:
        return 256 >> self.depth


def metric_for_filename(name: str) -> str:
    """``yiq`` for a name containing ``yiq``, otherwise ``rgb``."""
    return "yiq" if "yiq" in Path(name).name.lower() else "rgb"


def _rgb_distance(first: RGB, second: RGB) -> float:
    return sum((a - b) ** 2 for a, b in zip(first, second))


def _yiq(color: RGB) -> tuple[float, float, float]:
    red, green, blue = color
    return (
        0.299 * red + 0.587 * green + 0.114 * blue,
        0.596 * red - 0.275 * green - 0.321 * blue,
        0.212 * red - 0.528 * green + 0.311 * blue,
    )


def _yiq_distance(first: RGB, second: RGB) -> float:
    # The tool truncates the float sum to an unsigned integer.
    return float(int(sum((a - b) ** 2 for a, b in zip(_yiq(first), _yiq(second)))))


_DISTANCES = {"rgb": _rgb_distance, "yiq": _yiq_distance}


class U9ColorCube:
    """Palette prefix plus octree, preserved in stored order."""

    def __init__(
        self, palette_prefix: bytes, nodes: tuple[U9ColorCubeNode, ...]
    ) -> None:
        if len(palette_prefix) != PALETTE_PREFIX_SIZE:
            raise U9ColorCubeError(
                f"palette prefix must be {PALETTE_PREFIX_SIZE} bytes; "
                f"found {len(palette_prefix)}"
            )
        self.palette_prefix = bytes(palette_prefix)
        self.nodes = nodes
        self._leaves_by_path = {node.path: node for node in nodes if node.is_leaf}

    @classmethod
    def from_bytes(cls, data: bytes) -> U9ColorCube:
        data = bytes(data)
        if len(data) < PALETTE_PREFIX_SIZE + _COUNT.size:
            raise U9ColorCubeError(
                f"colour cube needs at least {PALETTE_PREFIX_SIZE + _COUNT.size} "
                f"bytes; found {len(data)}"
            )
        offset = PALETTE_PREFIX_SIZE
        nodes: list[U9ColorCubeNode] = []
        # Depth-first with an explicit stack; children are pushed in reverse
        # so they are read in stored order 0..7.
        stack: list[tuple[int, ...]] = [()]
        max_nodes = (len(data) - PALETTE_PREFIX_SIZE) // _COUNT.size
        while stack:
            path = stack.pop()
            if len(nodes) >= max_nodes or offset + _COUNT.size > len(data):
                raise U9ColorCubeError(
                    f"tree truncated at 0x{offset:x}: node {len(nodes)} "
                    f"({len(stack) + 1} still open) passes the end of {len(data)} bytes"
                )
            (count,) = _COUNT.unpack_from(data, offset)
            node_offset = offset
            offset += _COUNT.size
            if count:
                if count > len(data) - offset:
                    raise U9ColorCubeError(
                        f"leaf at 0x{node_offset:x} claims {count} candidates; "
                        f"only {len(data) - offset} bytes remain"
                    )
                candidates = data[offset : offset + count]
                offset += count
            else:
                if len(path) >= MAX_TREE_DEPTH:
                    raise U9ColorCubeError(
                        f"internal node at 0x{node_offset:x} is at depth {len(path)}; "
                        f"a colour cube cannot split deeper than {MAX_TREE_DEPTH}"
                    )
                candidates = b""
                stack.extend(path + (child,) for child in reversed(range(_CHILDREN)))
            nodes.append(
                U9ColorCubeNode(
                    offset=node_offset,
                    depth=len(path),
                    path=path,
                    count=count,
                    candidates=candidates,
                )
            )
        if offset != len(data):
            raise U9ColorCubeError(
                f"tree closes at 0x{offset:x} but the file is {len(data)} bytes; "
                f"{len(data) - offset} trailing byte(s)"
            )
        return cls(data[:PALETTE_PREFIX_SIZE], tuple(nodes))

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> U9ColorCube:
        try:
            return cls.from_bytes(Path(path).read_bytes())
        except OSError as error:
            raise U9ColorCubeError(str(error)) from error

    def to_bytes(self) -> bytes:
        parts = [self.palette_prefix]
        for node in self.nodes:
            parts.append(_COUNT.pack(node.count))
            parts.append(node.candidates)
        return b"".join(parts)

    @property
    def palette_colors(self) -> tuple[RGB, ...]:
        prefix = self.palette_prefix
        return tuple(
            (prefix[i], prefix[i + 1], prefix[i + 2])
            for i in range(0, PALETTE_PREFIX_SIZE, 4)
        )

    @property
    def palette_flags(self) -> bytes:
        return self.palette_prefix[3::4]

    @property
    def leaves(self) -> tuple[U9ColorCubeNode, ...]:
        return tuple(node for node in self.nodes if node.is_leaf)

    @property
    def max_depth(self) -> int:
        return max(node.depth for node in self.nodes)

    def leaf_for(self, color: RGB) -> U9ColorCubeNode:
        """The leaf whose cube contains ``color``."""
        _check_color(color)
        wanted = tuple(
            ((color[0] >> (7 - depth)) & 1)
            | (((color[1] >> (7 - depth)) & 1) << 1)
            | (((color[2] >> (7 - depth)) & 1) << 2)
            for depth in range(MAX_TREE_DEPTH)
        )
        for depth in range(MAX_TREE_DEPTH + 1):
            node = self._leaves_by_path.get(wanted[:depth])
            if node is not None:
                return node
        raise U9ColorCubeError(
            f"no leaf covers {color}"
        )  # unreachable for a closed tree

    def closest_index(self, color: RGB, metric: str) -> int:
        """The palette index the tool would choose for ``color``.

        Ties keep the first candidate in stored order, as the tool does.
        """
        if metric not in _DISTANCES:
            raise ValueError(f"metric must be one of {METRICS}; found {metric!r}")
        leaf = self.leaf_for(color)
        palette = self.palette_colors
        distance = _DISTANCES[metric]
        best = leaf.candidates[0]
        best_distance = distance(color, palette[best])
        for candidate in leaf.candidates[1:]:
            current = distance(color, palette[candidate])
            if current < best_distance:
                best, best_distance = candidate, current
        return best


def _check_color(color: RGB) -> None:
    if len(color) != 3 or any(not 0 <= value <= 255 for value in color):
        raise ValueError(f"colour must be three values in 0..255; found {color}")
