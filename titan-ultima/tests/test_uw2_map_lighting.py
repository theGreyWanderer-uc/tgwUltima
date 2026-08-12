"""Tests for render_uuw2_as_u7_style's DL.DAT light_level brightness pass.

This is a top-down cutaway map, not a first-person view, so lighting is
intentionally a simple whole-scene brightness scalar per level rather than
SHADES.DAT's per-pixel view-distance/fog model (see the "Wire Up Lighting"
entry in UU2_mapping_data_structure_report.md for why the latter doesn't
apply here).
"""

from PIL import Image

from titan.uw2 import map_render as renderer


class Args:
    no_lighting = False
    min_brightness = 0.35


def test_full_light_level_is_full_brightness():
    assert renderer.level_brightness_factor({"light_level": 15}, Args()) == 1.0


def test_darkest_light_level_is_min_brightness():
    assert (
        renderer.level_brightness_factor({"light_level": 0}, Args())
        == Args.min_brightness
    )


def test_missing_light_level_defaults_to_full_brightness():
    assert renderer.level_brightness_factor({}, Args()) == 1.0


def test_no_lighting_flag_forces_full_brightness_even_when_dark():
    class NoLightingArgs(Args):
        no_lighting = True

    assert renderer.level_brightness_factor({"light_level": 0}, NoLightingArgs()) == 1.0


def test_light_level_is_clamped_to_valid_range():
    # Defensive: DL.DAT bytes are nominally 0..15, but don't blow up or
    # invert the curve if a value outside that range ever shows up.
    args = Args()
    assert renderer.level_brightness_factor({"light_level": 255}, args) == 1.0
    assert (
        renderer.level_brightness_factor({"light_level": -5}, args)
        == args.min_brightness
    )


def test_brightness_is_monotonic_in_light_level():
    args = Args()
    factors = [
        renderer.level_brightness_factor({"light_level": level}, args)
        for level in range(16)
    ]
    assert factors == sorted(factors)
    assert factors[0] < factors[-1]


def test_apply_level_lighting_dims_color_but_preserves_transparency():
    scene = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    scene.putpixel((0, 0), (200, 100, 50, 255))  # opaque content pixel
    # (1, 1) stays fully transparent -- background, nothing drawn there.

    dimmed = renderer.apply_level_lighting(scene, {"light_level": 0}, Args())

    content_pixel = dimmed.getpixel((0, 0))
    assert content_pixel[3] == 255, "opaque content must stay opaque after dimming"
    assert content_pixel[:3] < (200, 100, 50), "content color must actually get darker"

    background_pixel = dimmed.getpixel((1, 1))
    assert background_pixel[3] == 0, (
        "transparent background must stay transparent, not bleed color"
    )


def test_apply_level_lighting_is_a_noop_at_full_brightness():
    scene = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    scene.putpixel((0, 0), (200, 100, 50, 255))
    result = renderer.apply_level_lighting(scene, {"light_level": 15}, Args())
    assert result.getpixel((0, 0)) == (200, 100, 50, 255)
