"""Pins the 2.5D map renderer's tuned projection defaults.

`map-render` has no depth buffer, so a wall taller than the on-screen gap to
whatever tile sits further back paints over that tile's floor. The 24-unit
`max_wall_height` cap is the tuned value that keeps uneven terrain (caves in
particular) readable; see reference/uw2/UU2_debug_render_commands.md,
"Render All Maps (2026-08-06: superseded wall-height defaults)".

These defaults are deliberate output-affecting choices, not incidental. Any
change here alters every rendered map, so it must be an explicit decision
rather than a side effect of adding renderers or options elsewhere.
"""

from __future__ import annotations

import inspect
import unittest

from titan.uw2.cli import map_render_cmd
from titan.uw2.map_pipeline import _render_options

MAX_WALL_HEIGHT = 24.0


class UW2MapRenderDefaultTests(unittest.TestCase):
    def test_pipeline_caps_wall_height_at_24_units(self) -> None:
        self.assertEqual(_render_options({})["max_wall_height"], MAX_WALL_HEIGHT)

    def test_cli_default_matches_the_pipeline_cap(self) -> None:
        default = (
            inspect.signature(map_render_cmd).parameters["max_wall_height"].default
        )

        self.assertEqual(default, MAX_WALL_HEIGHT)

    def test_obstruction_clipping_stays_on_by_default(self) -> None:
        # The per-wall clip works alongside the cap; disabling it by default
        # would let walls reach over the floor behind them again.
        self.assertFalse(_render_options({})["no_obstruction_clip"])

    def test_projection_defaults_are_unchanged(self) -> None:
        options = _render_options({})

        self.assertEqual(options["tile_size"], 64)
        self.assertEqual(options["lift_pixels"], 4.0)
        self.assertEqual(options["floor_height_per_lift"], 8.0)
        self.assertEqual(options["wall_height_scale"], 1.0)
        self.assertEqual(options["orientation"], "display")
        self.assertEqual(options["floor_texture_transform"], "auto")

    def test_explicit_overrides_still_win(self) -> None:
        self.assertEqual(
            _render_options({"max_wall_height": 0.0})["max_wall_height"], 0.0
        )


if __name__ == "__main__":
    unittest.main()
