"""The plan view reproduces source texels exactly; framing ignores object drift.

A perspective camera cannot reproduce a texture: surfaces sit at varying angles
and distances, so a texel covers a non-integer, non-uniform run of pixels and
the GPU resamples. The plan view exists because a straight-down parallel
projection at a whole multiple of the 64-pixel terrain texture avoids that.

Framing previously came from ``reset_camera()``, which fits to the actors, so
nudging one object re-fit the camera and shifted every pixel of the output.
Region-derived bounds make two renders of one region comparable.
"""

from __future__ import annotations

import unittest

from titan.uw2.map3d import (
    MAX_RENDER_EDGE,
    _part_vertex_colors,
    NATIVE_PIXELS_PER_TILE,
    VIEW_OFFSETS,
    PLAN_VIEW,
    VIEWS,
    _framing_bounds,
    _validate_render_options,
    plan_render_size,
)
from titan.uw2.scene3d import ScenePart, SceneTriangle, UW2Scene, UW2SceneError


class PlanRenderSizeTests(unittest.TestCase):
    def test_native_scale_is_one_pixel_per_terrain_texel(self) -> None:
        self.assertEqual(NATIVE_PIXELS_PER_TILE, 64)
        self.assertEqual(plan_render_size((0, 0, 0, 0)), (64, 64))

    def test_size_follows_the_region(self) -> None:
        # 33 x 28 tiles, the Castle Britannia crop
        self.assertEqual(plan_render_size((15, 29, 47, 56)), (2112, 1792))

    def test_scale_multiplies_whole_tiles(self) -> None:
        for scale in (1, 2, 4):
            with self.subTest(scale=scale):
                width, height = plan_render_size((0, 0, 3, 1), scale)
                self.assertEqual(width, 4 * 64 * scale)
                self.assertEqual(height, 2 * 64 * scale)
                self.assertEqual(width % NATIVE_PIXELS_PER_TILE, 0)

    def test_scale_below_one_is_rejected(self) -> None:
        with self.assertRaises(UW2SceneError):
            plan_render_size((0, 0, 1, 1), 0)


class PlanViewRegistrationTests(unittest.TestCase):
    def test_plan_is_a_selectable_view(self) -> None:
        self.assertIn(PLAN_VIEW, VIEWS)

    def test_options_reject_a_bad_plan_scale(self) -> None:
        with self.assertRaises(UW2SceneError):
            _validate_render_options(
                plan_scale=0,
                views=(PLAN_VIEW,),
                size=512,
                width=None,
                height=None,
                ceiling_source="runtime",
                zoom=1.0,
                fit_margin=1.0,
                supersample=1,
                downsample_filter="lanczos",
                texture_filter="nearest",
                texture_scale=1,
                backend="pyvista",
            )

    def test_plan_scale_is_passed_through(self) -> None:
        options = _validate_render_options(
            plan_scale=2,
            views=(PLAN_VIEW,),
            size=512,
            width=None,
            height=None,
            ceiling_source="runtime",
            zoom=1.0,
            fit_margin=1.0,
            supersample=1,
            downsample_filter="lanczos",
            texture_filter="nearest",
            texture_scale=1,
            backend="pyvista",
        )
        self.assertEqual(options["plan_scale"], 2)


class NativeSizingTests(unittest.TestCase):
    """A tilted view needs a bigger image than the plan to hold the same detail.

    The measuring itself needs a live projection, so it is exercised against
    the renderer rather than here; these pin the parts that do not.
    """

    def test_the_plan_needs_no_measuring(self) -> None:
        """It is parallel and square-on, so its size is arithmetic."""
        self.assertEqual(plan_render_size((0, 0, 9, 4)), (640, 320))

    def test_the_edge_guard_is_a_real_driver_limit(self) -> None:
        self.assertEqual(MAX_RENDER_EDGE, 16384)

    def test_foreshortening_sets_how_much_bigger(self) -> None:
        """A floor tile shrinks by sin(elevation) up the screen."""
        import math

        for view, expected in (("south", 0.74), ("iso-ne", 0.49), ("low-s", 0.20)):
            with self.subTest(view=view):
                x, y, z = VIEW_OFFSETS[view]
                shrink = math.sin(math.atan2(z, math.hypot(x, y)))
                self.assertAlmostEqual(shrink, expected, delta=0.01)

    def test_the_shallower_the_view_the_larger_the_render(self) -> None:
        """Ordering only: perspective adds to this, so the true sizes are worse."""
        import math

        def shrink(view: str) -> float:
            x, y, z = VIEW_OFFSETS[view]
            return math.sin(math.atan2(z, math.hypot(x, y)))

        self.assertEqual(shrink("plan"), 1.0)
        for steeper, shallower in (
            ("plan", "top"),
            ("top", "south"),
            ("south", "iso-ne"),
            ("iso-ne", "low-ne"),
            ("iso-ne", "low-s"),
        ):
            with self.subTest(f"{steeper} vs {shallower}"):
                self.assertGreater(shrink(steeper), shrink(shallower))


class SouthViewTests(unittest.TestCase):
    """A square-on southern camera, as distinct from the corner iso presets."""

    def test_south_views_look_due_north(self) -> None:
        for view in ("south", "low-s"):
            with self.subTest(view=view):
                x, y, _z = VIEW_OFFSETS[view]
                self.assertEqual(x, 0.0)  # no east/west bearing at all
                self.assertLess(y, 0.0)  # camera stands south, looking north

    def test_south_is_between_the_plan_and_the_iso_presets(self) -> None:
        import math

        def elevation(view: str) -> float:
            x, y, z = VIEW_OFFSETS[view]
            return math.degrees(math.atan2(z, math.hypot(x, y)))

        self.assertAlmostEqual(elevation("south"), 48, delta=1)
        self.assertGreater(elevation("south"), elevation("iso-ne"))
        self.assertLess(elevation("south"), elevation("top"))

    def test_low_s_matches_the_other_low_presets(self) -> None:
        import math

        def elevation(view: str) -> float:
            x, y, z = VIEW_OFFSETS[view]
            return math.degrees(math.atan2(z, math.hypot(x, y)))

        self.assertAlmostEqual(elevation("low-s"), elevation("low-ne"), delta=1)

    def test_they_use_the_upright_camera_up_vector(self) -> None:
        from titan.uw2.map3d import _view_up

        for view in ("south", "low-s"):
            with self.subTest(view=view):
                self.assertEqual(_view_up(view), (0.0, 0.0, 1.0))


def _part(vertices) -> ScenePart:
    return ScenePart(
        name="t",
        material_key="m",
        triangles=[SceneTriangle(tuple(vertices), ((0, 0), (1, 0), (1, 1)))],
    )


class FramingBoundsTests(unittest.TestCase):
    """Horizontal framing must come from the region, height from the scene."""

    def _scene(self, vertices) -> UW2Scene:
        scene = UW2Scene(slot=0, level_name=None, region=(10, 20, 12, 24))
        scene.architecture.append(_part(vertices))
        return scene

    def test_horizontal_bounds_are_the_region(self) -> None:
        bounds = self._scene([(10.4, 20.4, 1.0), (11.0, 21.0, 2.0), (11.5, 22.0, 3.0)])
        result = _framing_bounds(bounds)
        self.assertEqual(result[:4], (10.0, 13.0, 20.0, 25.0))

    def test_an_object_outside_the_region_cannot_move_the_framing(self) -> None:
        tight = _framing_bounds(
            self._scene([(10.4, 20.4, 1.0), (11.0, 21.0, 2.0), (11.5, 22.0, 3.0)])
        )
        strayed = _framing_bounds(
            self._scene([(-40.0, 20.4, 1.0), (11.0, 99.0, 2.0), (11.5, 22.0, 3.0)])
        )
        self.assertEqual(tight[:4], strayed[:4])

    def test_height_still_comes_from_the_geometry(self) -> None:
        result = _framing_bounds(
            self._scene([(10.4, 20.4, 1.5), (11.0, 21.0, 2.0), (11.5, 22.0, 7.25)])
        )
        self.assertEqual(result[4:], (1.5, 7.25))


class VertexColorTests(unittest.TestCase):
    """A face the model shades across its corners keeps a colour per corner.

    ``_part_arrays`` gives every triangle three fresh points rather than
    sharing corners between faces, so the colour array lines up with it one for
    one and needs no re-indexing. That is what makes this cheap: a part still
    names one material, and the colour simply moves onto the points.
    """

    def _part(self, *triangles):
        return ScenePart(name="p", material_key="m", triangles=list(triangles))

    def _tri(self, colors=None):
        return SceneTriangle(
            vertices=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
            uvs=((0, 0), (1, 0), (1, 1)),
            colors=colors,
        )

    def test_a_part_reports_whether_any_face_is_shaded(self) -> None:
        self.assertFalse(self._part(self._tri()).has_vertex_colors)
        shaded = self._tri(((1, 2, 3, 255), (4, 5, 6, 255), (7, 8, 9, 255)))
        self.assertTrue(self._part(shaded).has_vertex_colors)

    def test_colours_line_up_with_the_points(self) -> None:
        shaded = self._tri(((1, 2, 3, 255), (4, 5, 6, 255), (7, 8, 9, 255)))
        colors = _part_vertex_colors(self._part(shaded), (0, 0, 0, 255))
        self.assertEqual(colors.tolist(), [[1, 2, 3], [4, 5, 6], [7, 8, 9]])

    def test_an_unshaded_face_falls_back_to_the_material(self) -> None:
        colors = _part_vertex_colors(self._part(self._tri()), (10, 20, 30, 255))
        self.assertEqual(colors.tolist(), [[10, 20, 30]] * 3)

    def test_a_part_may_mix_the_two(self) -> None:
        shaded = self._tri(((1, 1, 1, 255), (2, 2, 2, 255), (3, 3, 3, 255)))
        colors = _part_vertex_colors(self._part(self._tri(), shaded), (9, 9, 9, 255))
        self.assertEqual(len(colors), 6)
        self.assertEqual(colors[:3].tolist(), [[9, 9, 9]] * 3)
        self.assertEqual(colors[3:].tolist(), [[1, 1, 1], [2, 2, 2], [3, 3, 3]])


if __name__ == "__main__":
    unittest.main()
