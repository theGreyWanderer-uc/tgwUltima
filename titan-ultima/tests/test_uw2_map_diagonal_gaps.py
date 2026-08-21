"""Regression tests for the diagonal wall corner-gap fill in map_render.

A diagonal tile's hypotenuse ends on two shared grid points it has in common
with its cut-corner neighbours. ``make_diagonal_wall`` and each neighbour's
``make_edge_wall`` project that shared point using their own tile's floor lift
and wall height, so a floor/ceiling mismatch lands the two panels' corners on
different screen points and leaves a background-coloured notch.
``make_diagonal_corner_fills`` bridges it, and must stay silent when the
heights already agree.

This was hand-debugged against Ice Caverns level 1 display (37,51) -- a
``diagonal_ne`` whose cut corner borders a 96-unit height mismatch -- and
against Castle Britannia display (35,30); see
``reference/uw2/UU2_debug_render_commands.md``. The fixtures below rebuild
those configurations synthetically, so the default suite still needs no game
files. ``UW2RealMapDiagonalTests`` re-checks the original two map locations
and is skipped unless ``TITAN_UW2_GAMEDIR`` points at a UU2 install.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.uw2.map_render import make_diagonal_corner_fills
from titan.uw2.topology import neighbor_coords, neighbor_is_open_across_side

Y_SIZE = 64


def _render_args(orientation: str = "raw") -> SimpleNamespace:
    """The subset of render options make_diagonal_corner_fills reads."""
    return SimpleNamespace(
        tile_size=64,
        lift_pixels=4.0,
        floor_height_per_lift=8.0,
        wall_height_scale=2.0,
        max_wall_height=128.0,
        orientation=orientation,
    )


def _tile(
    x: int,
    y: int,
    type_name: str,
    *,
    floor_height: int = 96,
    ceiling_height: int = 128,
) -> dict:
    return {
        "x": x,
        "y": y,
        "type_name": type_name,
        "floor_height": floor_height,
        "ceiling_height": ceiling_height,
        "texture_wall": 1,
    }


class UW2DiagonalCornerFillTests(unittest.TestCase):
    """diagonal_ne at (5,5) cuts its 'back' and 'left' corners, so the fills
    are measured against the neighbours at (5,4) and (4,5)."""

    def test_no_fill_when_neighbour_heights_match(self) -> None:
        tile = _tile(5, 5, "diagonal_ne")
        tile_map = {
            (5, 5): tile,
            (5, 4): _tile(5, 4, "open"),
            (4, 5): _tile(4, 5, "open"),
        }

        fills = make_diagonal_corner_fills(tile, tile_map, 0, Y_SIZE, _render_args())

        self.assertEqual(fills, [])

    def test_emits_fill_when_cut_corner_neighbour_floor_is_higher(self) -> None:
        # The Ice Caverns case: a 96-unit floor/ceiling mismatch across the
        # diagonal's cut corner used to leave a visible notch.
        tile = _tile(5, 5, "diagonal_ne")
        mismatched = _tile(5, 4, "open", floor_height=0, ceiling_height=32)
        tile_map = {
            (5, 5): tile,
            (5, 4): mismatched,
            (4, 5): _tile(4, 5, "open"),
        }

        fills = make_diagonal_corner_fills(tile, tile_map, 0, Y_SIZE, _render_args())

        self.assertEqual(len(fills), 1)
        fill = fills[0]
        self.assertEqual(fill.texture_id, 1)
        self.assertEqual(fill.texture_kind, "terrain")
        self.assertEqual(fill.side, "diagonal")
        self.assertEqual(len(fill.quad), 4)

    def test_skips_solid_and_missing_cut_corner_neighbours(self) -> None:
        # A solid neighbour draws no edge wall of its own, so there is no
        # notch to bridge; a missing neighbour is off the map entirely.
        tile = _tile(5, 5, "diagonal_ne")
        tile_map = {
            (5, 5): tile,
            (5, 4): _tile(5, 4, "solid", floor_height=0, ceiling_height=32),
        }

        fills = make_diagonal_corner_fills(tile, tile_map, 0, Y_SIZE, _render_args())

        self.assertEqual(fills, [])

    def test_non_diagonal_tile_has_no_hypotenuse_to_bridge(self) -> None:
        tile = _tile(5, 5, "open")
        tile_map = {(5, 5): tile, (5, 4): _tile(5, 4, "open", floor_height=0)}

        fills = make_diagonal_corner_fills(tile, tile_map, 0, Y_SIZE, _render_args())

        self.assertEqual(fills, [])


def _game_directory() -> Path | None:
    value = os.environ.get("TITAN_UW2_GAMEDIR")
    if not value:
        return None
    path = Path(value).expanduser()
    data = path if path.name.upper() == "DATA" else path / "DATA"
    return path if (data / "LEV.ARK").is_file() else None


@unittest.skipIf(
    _game_directory() is None,
    "set TITAN_UW2_GAMEDIR to a UU2 install to re-check the original map cases",
)
class UW2RealMapDiagonalTests(unittest.TestCase):
    """Opt-in checks that the two hand-debugged map locations still hold."""

    @classmethod
    def setUpClass(cls) -> None:
        from titan.uw2.map_pipeline import load_levels

        source = _game_directory()
        cls.levels = {
            level["slot_index"]: level for level in load_levels(source, (0, 24))
        }

    def _tile_map(self, slot: int) -> dict:
        level = self.levels[slot]
        return {(tile["x"], tile["y"]): tile for tile in level["tiles"]}

    def test_britannia_display_35_30_is_blocked_by_its_diagonal_neighbour(self) -> None:
        tiles = self._tile_map(0)
        diagonal_tile = tiles[(35, Y_SIZE - 1 - 29)]
        open_tile = tiles[(35, Y_SIZE - 1 - 30)]
        self.assertEqual(diagonal_tile["type_name"], "diagonal_nw")
        self.assertEqual(open_tile["type_name"], "open")

        # The diagonal sits across the open tile's "front" side (raw y+1) and
        # must read as blocked there, not open.
        self.assertEqual(
            neighbor_coords("front", open_tile["x"], open_tile["y"]),
            (diagonal_tile["x"], diagonal_tile["y"]),
        )
        self.assertIs(neighbor_is_open_across_side(diagonal_tile, "back"), False)

    def test_ice_caverns_diagonal_corner_gap_is_closed(self) -> None:
        level = self.levels[24]
        tile_map = self._tile_map(24)
        non_solid = [t for t in level["tiles"] if t["type_name"] != "solid"]
        min_floor = min(tile["floor_height"] for tile in non_solid)

        tile = tile_map[(37, Y_SIZE - 1 - 51)]
        self.assertEqual(tile["type_name"], "diagonal_ne")

        fills = make_diagonal_corner_fills(
            tile, tile_map, min_floor, Y_SIZE, _render_args("display")
        )

        self.assertGreaterEqual(
            len(fills),
            1,
            "expected a corner-fill panel across the height-mismatched diagonal",
        )


if __name__ == "__main__":
    unittest.main()
