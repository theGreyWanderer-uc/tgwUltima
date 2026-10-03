"""Tests for the authoring-tool colour tables the retail game never loads.

``shade.tbl`` / ``shadegry.tbl`` (titan.u9.shade_tables) are fixed-size
palette-index arrays; ``rgbccube.dat`` / ``yiqccube.dat`` (titan.u9.color_cube)
are a palette prefix plus a depth-first octree. The retail tests check exact
round trips and that the YIQ cube regenerates every shaded ``shade.tbl`` cell.
"""

from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.cli import (
    cmd_color_cube_csv,
    cmd_color_cube_info,
    cmd_color_cube_lookup,
    cmd_shade_csv,
    cmd_shade_info,
)
from titan.u9.color_cube import (
    MAX_TREE_DEPTH,
    PALETTE_PREFIX_SIZE,
    U9ColorCube,
    U9ColorCubeError,
    metric_for_filename,
)
from titan.u9.shade_tables import (
    EDITOR_COLOR_TABLE_SIZE,
    SHADE_TABLE_SIZE,
    U9EditorColorTable,
    U9ShadeTable,
    U9ShadeTableError,
)

CORPUS = Path(__file__).resolve().parents[2] / "u9data" / "gameData_u9" / "static"


def _palette() -> bytes:
    """Index i is grey (i, i, i) with a nonzero flags byte to prove preservation."""
    return b"".join(bytes((i, i, i, i & 3)) for i in range(256))


def _leaf(*indices: int) -> bytes:
    return struct.pack("<I", len(indices)) + bytes(indices)


def _internal(*children: bytes) -> bytes:
    assert len(children) == 8
    return struct.pack("<I", 0) + b"".join(children)


def _shade_bytes(filler: int = 17) -> bytearray:
    data = bytearray([filler]) * SHADE_TABLE_SIZE
    for level in range(16, 32):
        for index in range(10, 246):
            data[level * 256 + index] = (index + level) % 256
    return data


class ShadeTableTests(unittest.TestCase):
    def test_round_trip_lookup_and_filler(self) -> None:
        data = bytes(_shade_bytes())
        table = U9ShadeTable.from_bytes(data)
        self.assertEqual(table.to_bytes(), data)
        self.assertEqual(table.filler_index, 17)
        self.assertEqual(table.shade(16, 10), 26)
        self.assertEqual(table.shade(31, 245), (245 + 31) % 256)
        self.assertTrue(table.is_filler_cell(15, 100))
        self.assertTrue(table.is_filler_cell(20, 9))
        self.assertTrue(table.is_filler_cell(20, 246))
        self.assertFalse(table.is_filler_cell(16, 10))
        self.assertEqual(table.filler_anomalies(), ())

    def test_reports_filler_anomaly_without_changing_it(self) -> None:
        data = _shade_bytes()
        data[3 * 256 + 5] = 99
        table = U9ShadeTable.from_bytes(bytes(data))
        self.assertEqual(table.filler_anomalies(), ((3, 5, 99),))
        self.assertEqual(table.to_bytes(), bytes(data))

    def test_rejects_wrong_sizes_and_indices(self) -> None:
        for size in (0, SHADE_TABLE_SIZE - 1, SHADE_TABLE_SIZE + 1):
            with self.subTest(size=size):
                with self.assertRaisesRegex(U9ShadeTableError, "exactly 8192"):
                    U9ShadeTable(bytes(size))
        table = U9ShadeTable(bytes(SHADE_TABLE_SIZE))
        with self.assertRaises(IndexError):
            table.shade(32, 0)
        with self.assertRaises(IndexError):
            table.shade(0, 256)


class EditorColorTableTests(unittest.TestCase):
    def test_ramps_and_red_tint(self) -> None:
        data = bytes(range(64)) + bytes(255 - i for i in range(256))
        table = U9EditorColorTable.from_bytes(data)
        self.assertEqual(table.to_bytes(), data)
        self.assertEqual(table.ramp("blue"), bytes(range(16)))
        self.assertEqual(table.ramp("grey"), bytes(range(48, 64)))
        self.assertEqual(table.red_tint[0], 255)
        with self.assertRaises(KeyError):
            table.ramp("purple")

    def test_rejects_wrong_size(self) -> None:
        with self.assertRaisesRegex(U9ShadeTableError, "exactly 320"):
            U9EditorColorTable(bytes(EDITOR_COLOR_TABLE_SIZE - 1))


class ColorCubeTests(unittest.TestCase):
    def test_single_leaf_root(self) -> None:
        data = _palette() + _leaf(40)
        cube = U9ColorCube.from_bytes(data)
        self.assertEqual(cube.to_bytes(), data)
        self.assertEqual(len(cube.nodes), 1)
        self.assertEqual(cube.closest_index((200, 0, 0), "rgb"), 40)
        self.assertEqual(cube.palette_flags[:4], bytes((0, 1, 2, 3)))

    def test_child_order_and_nearest_candidate(self) -> None:
        # Child n: bit 0 upper red, bit 1 upper green, bit 2 upper blue.
        children = [_leaf(10 + n) for n in range(8)]
        children[7] = _leaf(250, 200)  # upper cube offers two candidates
        data = _palette() + _internal(*children)
        cube = U9ColorCube.from_bytes(data)
        self.assertEqual(cube.to_bytes(), data)
        self.assertEqual(cube.leaf_for((200, 0, 0)).path, (1,))
        self.assertEqual(cube.leaf_for((0, 200, 0)).path, (2,))
        self.assertEqual(cube.leaf_for((0, 0, 200)).path, (4,))
        self.assertEqual(cube.leaf_for((0, 0, 200)).cube_origin, (0, 0, 128))
        self.assertEqual(cube.closest_index((210, 210, 210), "rgb"), 200)
        self.assertEqual(cube.closest_index((250, 250, 250), "yiq"), 250)

    def test_nested_paths_and_origin(self) -> None:
        inner = _internal(*[_leaf(n + 20) for n in range(8)])
        data = _palette() + _internal(inner, *[_leaf(n) for n in range(1, 8)])
        cube = U9ColorCube.from_bytes(data)
        leaf = cube.leaf_for((127, 64, 0))
        self.assertEqual(
            (leaf.path, leaf.cube_origin, leaf.cube_size), ((0, 3), (64, 64, 0), 64)
        )
        self.assertEqual([node.depth for node in cube.nodes[:3]], [0, 1, 2])

    def test_rejects_truncation_at_every_boundary(self) -> None:
        data = _palette() + _internal(*[_leaf(n, n + 1) for n in range(8)])
        for size in range(len(data)):
            with self.subTest(size=size):
                with self.assertRaises(U9ColorCubeError):
                    U9ColorCube.from_bytes(data[:size])

    def test_rejects_trailing_bytes_and_oversized_leaf(self) -> None:
        with self.assertRaisesRegex(U9ColorCubeError, "trailing"):
            U9ColorCube.from_bytes(_palette() + _leaf(1) + b"\x00")
        with self.assertRaisesRegex(U9ColorCubeError, "claims"):
            U9ColorCube.from_bytes(_palette() + struct.pack("<I", 0xFFFFFFFF))

    def test_rejects_splits_below_the_colour_resolution(self) -> None:
        # A chain of internal nodes, each with its first child internal again.
        data = b""
        tail = _leaf(1)
        for _ in range(MAX_TREE_DEPTH + 1):
            tail = _internal(tail, *[_leaf(2)] * 7)
        data = _palette() + tail
        with self.assertRaisesRegex(U9ColorCubeError, "cannot split deeper"):
            U9ColorCube.from_bytes(data)

    def test_metric_by_name_and_rejects_bad_input(self) -> None:
        self.assertEqual(metric_for_filename("static/YIQCCUBE.DAT"), "yiq")
        self.assertEqual(metric_for_filename("rgbccube.dat"), "rgb")
        cube = U9ColorCube.from_bytes(_palette() + _leaf(1))
        with self.assertRaises(ValueError):
            cube.closest_index((0, 0, 0), "lab")
        with self.assertRaises(ValueError):
            cube.closest_index((0, 0, 256), "rgb")
        with self.assertRaisesRegex(U9ColorCubeError, "at least"):
            U9ColorCube.from_bytes(bytes(PALETTE_PREFIX_SIZE))


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.shade = self.root / "shade.tbl"
        self.shade.write_bytes(bytes(_shade_bytes()))
        self.gry = self.root / "shadegry.tbl"
        self.gry.write_bytes(bytes(EDITOR_COLOR_TABLE_SIZE))
        self.pal = self.root / "ankh.pal"
        self.pal.write_bytes(_palette())
        self.cube = self.root / "yiqccube.dat"
        self.cube.write_bytes(
            _palette() + _internal(*[_leaf(10 + n) for n in range(8)])
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_shade_commands(self) -> None:
        for path in (self.shade, self.gry):
            self.assertEqual(
                cmd_shade_info(SimpleNamespace(file=str(path), palette=str(self.pal))),
                0,
            )
        out = self.root / "shade.csv"
        self.assertEqual(
            cmd_shade_csv(
                SimpleNamespace(
                    file=str(self.shade), palette=str(self.pal), output=str(out)
                )
            ),
            0,
        )
        with out.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), SHADE_TABLE_SIZE)
        self.assertEqual(rows[16 * 256 + 10]["cell_kind"], "shaded")
        self.assertEqual(rows[16 * 256 + 10]["output_rgb"], "26,26,26")
        bad = self.root / "bad.tbl"
        bad.write_bytes(b"123")
        self.assertEqual(
            cmd_shade_info(SimpleNamespace(file=str(bad), palette=None)), 1
        )

    def test_color_cube_commands(self) -> None:
        self.assertEqual(
            cmd_color_cube_info(
                SimpleNamespace(file=str(self.cube), palette=str(self.pal))
            ),
            0,
        )
        self.assertEqual(
            cmd_color_cube_lookup(
                SimpleNamespace(
                    file=str(self.cube), red=0, green=0, blue=200, metric=None
                )
            ),
            0,
        )
        self.assertEqual(
            cmd_color_cube_lookup(
                SimpleNamespace(
                    file=str(self.cube), red=0, green=0, blue=0, metric="lab"
                )
            ),
            1,
        )
        out = self.root / "nodes.csv"
        self.assertEqual(
            cmd_color_cube_csv(SimpleNamespace(file=str(self.cube), output=str(out))), 0
        )
        with out.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual([row["kind"] for row in rows], ["internal"] + ["leaf"] * 8)
        self.assertEqual(rows[5]["path"], "4")
        self.assertEqual(rows[5]["cube_blue"], "128")


@unittest.skipUnless(
    (CORPUS / "yiqccube.dat").is_file(), "retail static/ colour tables not available"
)
class RetailCorpusTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        for name, reader in (
            ("shade.tbl", U9ShadeTable),
            ("shadegry.tbl", U9EditorColorTable),
            ("rgbccube.dat", U9ColorCube),
            ("yiqccube.dat", U9ColorCube),
        ):
            with self.subTest(name=name):
                data = (CORPUS / name).read_bytes()
                self.assertEqual(reader.from_bytes(data).to_bytes(), data)

    def test_cube_palettes_equal_ankh_pal(self) -> None:
        palette = (CORPUS / "ankh.pal").read_bytes()
        for name in ("rgbccube.dat", "yiqccube.dat"):
            with self.subTest(name=name):
                cube = U9ColorCube.from_file(CORPUS / name)
                self.assertEqual(cube.palette_prefix, palette)
                indices = {i for leaf in cube.leaves for i in leaf.candidates}
                self.assertEqual((min(indices), max(indices)), (10, 245))

    def test_yiq_cube_regenerates_every_shaded_cell(self) -> None:
        shade = U9ShadeTable.from_file(CORPUS / "shade.tbl")
        cube = U9ColorCube.from_file(CORPUS / "yiqccube.dat")
        self.assertEqual(shade.filler_anomalies(), ())
        palette = cube.palette_colors
        dark = [int(0.2 * 0x10000), int(0.2 * 0x10000), int(0.3 * 0x10000)]
        step = [(int(1.3 * 0x10000) - value) >> 4 for value in dark]
        levels = dark
        for level in range(16, 32):
            for index in range(10, 246):
                color = tuple(
                    min(255, (component * scale) >> 16)
                    for component, scale in zip(palette[index], levels)
                )
                self.assertEqual(
                    cube.closest_index(color, "yiq"), shade.shade(level, index)
                )
            levels = [value + delta for value, delta in zip(levels, step)]


if __name__ == "__main__":
    unittest.main()
