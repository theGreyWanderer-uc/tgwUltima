"""Tests for UU2 3D camera presets, render options, and level stacking.

The five original presets are load-bearing: their offsets frame every existing
`map-3d-render` output, so they are pinned here. `low-ne`/`low-nw` were added
alongside them, and the default zoom/fit-margin pair must keep reproducing the
framing the presets were tuned against.
"""

from __future__ import annotations

import unittest

from titan.uw2.map3d import (
    BACKENDS,
    DEFAULT_ZOOM,
    DOWNSAMPLE_FILTERS,
    TEXTURE_FILTERS,
    VIEW_OFFSETS,
    VIEWS,
    _camera_basis,
    _offset_part,
    _render_software,
    _scene_stem,
    _validate_render_options,
)
from titan.uw2.scene3d import (
    SceneMaterial,
    ScenePart,
    SceneTriangle,
    UW2Scene,
    UW2SceneError,
)

ORIGINAL_OFFSETS = {
    "iso-ne": (1.0, 1.0, 0.8),
    "iso-nw": (-1.0, 1.0, 0.8),
    "iso-se": (1.0, -1.0, 0.8),
    "iso-sw": (-1.0, -1.0, 0.8),
    "top": (0.0, -0.001, 1.8),
}


def _valid_options(**overrides):
    options = {
        "views": ("top",),
        "size": 512,
        "width": None,
        "height": None,
        "ceiling_source": "runtime",
        "zoom": DEFAULT_ZOOM,
        "fit_margin": 1.0,
        "supersample": 1,
        "downsample_filter": "lanczos",
        "texture_filter": "linear",
        "texture_scale": 1,
        "backend": "auto",
    }
    options.update(overrides)
    return options


def _demo_scene() -> UW2Scene:
    scene = UW2Scene(slot=3, level_name="Prison Tower - Basement", region=(0, 0, 3, 3))
    scene.materials["flat"] = SceneMaterial(key="flat", color=(200, 40, 40, 255))
    part = ScenePart(name="architecture_flat", material_key="flat")
    part.triangles.append(
        SceneTriangle(
            vertices=((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0)),
            uvs=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
        )
    )
    scene.architecture.append(part)
    return scene


class UW2ViewPresetTests(unittest.TestCase):
    def test_original_presets_keep_their_framing(self) -> None:
        for view, offset in ORIGINAL_OFFSETS.items():
            with self.subTest(view=view):
                self.assertEqual(VIEW_OFFSETS[view], offset)

    def test_low_angle_presets_share_bearings_but_drop_the_camera(self) -> None:
        self.assertIn("low-ne", VIEWS)
        self.assertIn("low-nw", VIEWS)
        for low, iso in (("low-ne", "iso-ne"), ("low-nw", "iso-nw")):
            with self.subTest(view=low):
                self.assertEqual(VIEW_OFFSETS[low][:2], VIEW_OFFSETS[iso][:2])
                self.assertLess(VIEW_OFFSETS[low][2], VIEW_OFFSETS[iso][2])

    def test_camera_basis_is_orthonormal_for_every_preset(self) -> None:
        for view in sorted(VIEWS):
            with self.subTest(view=view):
                forward, right, up = _camera_basis(view)
                for vector in (forward, right, up):
                    self.assertAlmostEqual(float((vector**2).sum()) ** 0.5, 1.0)
                self.assertAlmostEqual(float(forward @ right), 0.0)
                self.assertAlmostEqual(float(forward @ up), 0.0)
                self.assertAlmostEqual(float(right @ up), 0.0)


class UW2RenderOptionTests(unittest.TestCase):
    def test_defaults_reproduce_the_tuned_framing(self) -> None:
        options = _validate_render_options(**_valid_options())

        self.assertEqual(options["zoom"] / options["fit_margin"], DEFAULT_ZOOM)
        self.assertEqual(options["width"], 512)
        self.assertEqual(options["height"], 512)

    def test_width_and_height_override_square_size(self) -> None:
        options = _validate_render_options(**_valid_options(width=1600, height=900))

        self.assertEqual((options["width"], options["height"]), (1600, 900))

    def test_rejects_unknown_view(self) -> None:
        with self.assertRaises(UW2SceneError):
            _validate_render_options(**_valid_options(views=("iso-up",)))

    def test_rejects_empty_view_list(self) -> None:
        with self.assertRaises(UW2SceneError):
            _validate_render_options(**_valid_options(views=()))

    def test_rejects_out_of_range_numbers(self) -> None:
        for field, value in (
            ("zoom", 0.0),
            ("fit_margin", 0.0),
            ("supersample", 0),
            ("texture_scale", 0),
            ("size", 64),
        ):
            with self.subTest(field=field):
                with self.assertRaises(UW2SceneError):
                    _validate_render_options(**_valid_options(**{field: value}))

    def test_rejects_unknown_choices(self) -> None:
        for field, allowed in (
            ("downsample_filter", tuple(DOWNSAMPLE_FILTERS)),
            ("texture_filter", TEXTURE_FILTERS),
            ("backend", BACKENDS),
            ("ceiling_source", ("runtime", "ua")),
        ):
            with self.subTest(field=field):
                self.assertNotIn("nope", allowed)
                with self.assertRaises(UW2SceneError):
                    _validate_render_options(**_valid_options(**{field: "nope"}))


class UW2SoftwareRendererTests(unittest.TestCase):
    def test_draws_scene_geometry_at_the_requested_size(self) -> None:
        image = _render_software(
            _demo_scene(),
            view="top",
            width=200,
            height=160,
            zoom=1.0,
            fit_margin=1.0,
        )

        self.assertEqual(image.size, (200, 160))
        colors = {color for _count, color in image.getcolors(maxcolors=1 << 16)}
        self.assertIn((200, 40, 40, 255), colors)

    def test_empty_scene_reports_the_same_error_as_the_pyvista_path(self) -> None:
        # Both backends must agree: an empty region is a mistake worth naming,
        # not a blank PNG that looks like a rendering failure.
        empty = UW2Scene(slot=0, level_name=None, region=(0, 0, 0, 0))
        empty.architecture.append(ScenePart(name="none", material_key="flat"))
        empty.materials["flat"] = SceneMaterial(key="flat")

        with self.assertRaises(UW2SceneError):
            _render_software(
                empty, view="top", width=140, height=140, zoom=1.0, fit_margin=1.0
            )


class UW2SceneStackingTests(unittest.TestCase):
    def test_offset_part_translates_every_vertex_and_renames(self) -> None:
        part = _demo_scene().architecture[0]

        moved = _offset_part(part, "slot009", (1.0, 2.0, -7.0))

        self.assertTrue(moved.name.startswith("slot009_"))
        self.assertEqual(moved.material_key, part.material_key)
        self.assertEqual(
            moved.triangles[0].vertices[0],
            (1.0, 2.0, -7.0),
        )
        self.assertEqual(moved.triangles[0].uvs, part.triangles[0].uvs)
        # The source part is untouched, so a scene can be stacked repeatedly.
        self.assertEqual(part.triangles[0].vertices[0], (0.0, 0.0, 0.0))


class UW2SceneStemTests(unittest.TestCase):
    def test_stem_is_slot_and_region_by_default(self) -> None:
        self.assertEqual(_scene_stem(_demo_scene()), "uw2_slot_003_x0-3_y0-3_3d")

    def test_name_files_inserts_the_slugged_level_name(self) -> None:
        self.assertEqual(
            _scene_stem(_demo_scene(), name_files=True),
            "uw2_slot_003_prison_tower_basement_x0-3_y0-3_3d",
        )


if __name__ == "__main__":
    unittest.main()
