"""--resolution: one rule for every whole-map renderer."""

from __future__ import annotations

from PIL import Image

from titan._resolution import (
    default_resolution,
    resolution_factor,
    scale_file,
    scaled,
    size_tag,
)


def test_whole_maps_default_to_a_quarter_and_crops_to_full_size() -> None:
    assert default_resolution(True) == "25" and default_resolution(False) == "full"
    assert resolution_factor(None) == 0.25
    assert resolution_factor(None, whole_map=False) == 1.0
    assert resolution_factor("75", whole_map=False) == 0.75  # asked for: as given


def test_file_names_say_the_size() -> None:
    assert (
        size_tag(1.0) == "" and size_tag(0.25) == "_25pct" and size_tag(0.5) == "_50pct"
    )


def test_shrinking_averages_and_full_size_is_untouched(tmp_path) -> None:
    image = Image.new("RGB", (8, 4), (255, 0, 0))
    image.paste((0, 0, 255), (0, 0, 4, 4))  # left half blue
    assert scaled(image, 1.0) is image
    small = scaled(image, 0.25)
    assert small.size == (2, 1)
    assert small.getpixel((0, 0)) == (0, 0, 255) and small.getpixel((1, 0)) == (
        255,
        0,
        0,
    )
    path = tmp_path / "map.png"
    image.save(path)
    scale_file(path, 0.5)
    with Image.open(path) as saved:
        assert saved.size == (4, 2)
