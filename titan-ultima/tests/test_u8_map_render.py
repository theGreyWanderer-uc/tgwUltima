"""U8 map command integration, merged source coverage and native flipped sprites."""

from __future__ import annotations

import struct

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.palette import U8Palette
from titan.u8 import U8MapRenderer, U8MapSampler, U8Shape
from titan.u8.cli import u8_app


def _item(x=64, y=64, shape=10, status=0, quality=0):
    return struct.pack("<HHBHBHHBBH", x, y, 0, shape, 0, status, quality, 0, 8, 0)


def _flex(payloads):
    raw = bytearray(2176)
    raw[:84] = b"\x1a" * 84
    struct.pack_into("<I", raw, 84, 256)
    for map_id, payload in payloads.items():
        struct.pack_into("<II", raw, 128 + map_id * 8, len(raw), len(payload))
        raw += payload
    return bytes(raw)


def _save(payload):
    name = b"NONFIXED.DAT\x00"
    return (
        b"Ultima 8 SaveGame File.\x00"
        + struct.pack("<HI", 1, len(name))
        + name
        + struct.pack("<I", len(payload))
        + payload
    )


def _shape(path, pixels, xoff=1, yoff=8):
    shape = U8Shape()
    frame = U8Shape.Frame()
    frame.pixels = np.asarray(pixels, dtype=np.uint8)
    frame.height, frame.width = frame.pixels.shape
    frame.xoff, frame.yoff, frame.compressed = xoff, yoff, 1
    shape.frames = [frame]
    path.write_bytes(shape.to_bytes())


@pytest.fixture
def assets(tmp_path):
    fixed = tmp_path / "FIXED.DAT"
    # Inventory blue must never enter the world render, with or without TYPEFLAG.
    fixed.write_bytes(_flex({3: _item() + _item(x=1, shape=11, status=8)}))
    nonfixed = _flex(
        {
            0: _item(x=4096, y=4096, shape=11),
            3: _item(x=512, y=512, shape=2, quality=7),
            8: _item() + _item(x=1, shape=11, status=8),
        }
    )
    shapes, globs = tmp_path / "shapes", tmp_path / "globs"
    shapes.mkdir()
    globs.mkdir()
    for shape_id, color in [(10, 1), (11, 2), (12, 3)]:
        _shape(shapes / f"{shape_id:04d}.shp", [[color] * 4] * 2)
    (globs / "0007.dat").write_bytes(struct.pack("<HBB B H B", 1, 4, 4, 0, 12, 0))
    palette = tmp_path / "U8PAL.PAL"
    raw_pal = bytearray(772)
    raw_pal[7:16] = bytes((63, 0, 0, 0, 0, 63, 0, 63, 0))
    palette.write_bytes(raw_pal)
    typeflag = tmp_path / "metadata.dat"
    typeflag.write_bytes(bytes(13 * 8))
    return fixed, nonfixed, shapes, globs, palette, typeflag


@pytest.mark.parametrize(
    "command", ["map-render", "map-render-all", "map-sample", "map-sample-all"]
)
@pytest.mark.parametrize("use_save", [False, True])
@pytest.mark.parametrize("use_typeflag", [False, True])
def test_all_map_commands_merge_before_selection_expand_both_sources_and_filter_inventory(
    tmp_path,
    assets,
    command,
    use_save,
    use_typeflag,
):
    fixed, raw_nf, shapes, globs, palette, typeflag = assets
    nonfixed = tmp_path / ("U8SAVE.000" if use_save else "NONFIXED.DAT")
    nonfixed.write_bytes(_save(raw_nf) if use_save else raw_nf)
    output = tmp_path / ("out" if command.endswith("-all") else "out.png")
    args = [
        command,
        "--fixed",
        str(fixed),
        "--nonfixed",
        str(nonfixed),
        "--shapes",
        str(shapes),
        "--globs",
        str(globs),
        "--palette",
        str(palette),
        "-o",
        str(output),
    ]
    if not command.endswith("-all"):
        args.extend(["--map", "8"])  # No FIXED world placements in this map.
    if command == "map-render-all":
        args.extend(["--views", "iso_classic", "--views", "birdseye"])
    if use_typeflag:
        args.extend(["--typeflag", str(typeflag)])
    result = CliRunner().invoke(u8_app, args)
    assert result.exit_code == 0, (result.output, result.exception)
    files = sorted(output.glob("*.png")) if output.is_dir() else [output]
    assert len(files) == (
        4 if command == "map-render-all" else 2 if command.endswith("-all") else 1
    )
    for file in files:
        with Image.open(file) as image:
            color_counts = image.convert("RGB").getcolors(256)
            assert color_counts is not None
            colors = {color for _, color in color_counts}
        assert (255, 0, 0) in colors
        assert (0, 0, 255) not in colors  # Neither inventory nor registry roots.
        if file.name.startswith("map_003"):
            assert (0, 255, 0) in colors  # NONFIXED glob expands to the green shape.
    assert not any(file.name.startswith("map_000") for file in files)


def test_merge_preserves_distinct_items_metadata_and_source_lists():
    a = U8MapRenderer.MapObject(64, 64, 0, 10, 0, quality=77, status=32)
    b = U8MapRenderer.MapObject(64, 64, 0, 11, 0, quality=88)
    fixed, nonfixed = {3: [a]}, {3: [b], 8: [b]}
    merged = U8MapRenderer.merge_maps(fixed, nonfixed)
    assert list(merged) == [3, 8] and merged[3] == [a, b]
    merged[3].reverse()
    assert fixed[3] == [a] and nonfixed[3] == [b]
    assert a.quality == 77 and a.status == 32


@pytest.mark.parametrize(
    "command", ["map-render", "map-render-all", "map-sample", "map-sample-all"]
)
def test_map_help_retains_source_and_selection_options(command):
    result = CliRunner().invoke(u8_app, [command, "--help"])
    assert result.exit_code == 0
    for option in ("--fixed", "--nonfixed", "--typeflag", "--map"):
        assert option in result.output


def test_compatibility_imports_share_the_updated_renderer():
    from titan import U8MapRenderer as root_renderer
    from titan.map import U8MapRenderer as compatibility_renderer

    assert root_renderer is compatibility_renderer is U8MapRenderer


@pytest.mark.parametrize("view", ["iso_classic", "birdseye"])
def test_flip_cache_is_per_item_and_mirrors_around_the_shape_origin(tmp_path, view):
    pal = U8Palette()
    pal.colors[1:4] = [(255, 0, 0), (0, 0, 255), (0, 255, 0)]
    _shape(tmp_path / "0010.shp", [[1, 2, 3]], xoff=0, yoff=0)
    normal = U8MapRenderer.MapObject(64, 64, 0, 10, 0)
    flipped = U8MapRenderer.MapObject(128, 64, 0, 10, 0, status=32)
    image = U8MapRenderer.render_map([normal, flipped], str(tmp_path), pal, view=view)
    if view == "iso_classic":
        left, top = 270, 264  # Flipped origin at (272,264), extent two pixels left.
    else:
        left, top = 272, 256  # Birdseye retains its top-left map marker convention.
    assert [image.getpixel((left + i, top))[:3] for i in range(3)] == [
        (0, 255, 0),
        (0, 0, 255),
        (255, 0, 0),
    ]
    assert [image.getpixel((256 + i, 256))[:3] for i in range(3)] == [
        (255, 0, 0),
        (0, 0, 255),
        (0, 255, 0),
    ]


def test_sampler_applies_flip_when_sampling_around_the_origin(tmp_path):
    pal = U8Palette()
    pal.colors[1:4] = [(255, 0, 0), (0, 0, 255), (0, 255, 0)]
    _shape(tmp_path / "0010.shp", [[1, 2, 3]] * 2, xoff=1, yoff=1)
    normal = U8MapRenderer.MapObject(64, 64, 0, 10, 0)
    flipped = U8MapRenderer.MapObject(64, 64, 0, 10, 0, status=32)
    ordinary = U8MapSampler.sample_map([normal], str(tmp_path), pal, scale=8)
    mirrored = U8MapSampler.sample_map([flipped], str(tmp_path), pal, scale=8)
    assert ordinary.getpixel((7, 7)) == (0, 127, 127)  # Blue + green.
    assert mirrored.getpixel((7, 7)) == (127, 0, 127)  # Blue + red.


def test_depth_sort_swaps_asymmetric_xy_footpads_for_flipped_items(tmp_path):
    pal = U8Palette()
    _shape(tmp_path / "0010.shp", [[1]])
    _shape(tmp_path / "0011.shp", [[1]])
    typeflag = tmp_path / "TYPEFLAG.DAT"
    raw = bytearray(12 * 8)
    raw[10 * 8 + 2 : 10 * 8 + 4] = bytes((0x10, 0x18))  # 32 x 256 footprint, height 8.
    raw[11 * 8 + 2 : 11 * 8 + 4] = bytes((0x10, 0x11))  # 32 x 32 footprint, height 8.
    typeflag.write_bytes(raw)

    def ordered(status):
        items = [
            U8MapRenderer.MapObject(256, 256, 0, 10, 0, status=status),
            U8MapRenderer.MapObject(200, 240, 0, 11, 0),
        ]
        U8MapRenderer.render_map(items, str(tmp_path), pal, typeflag_path=str(typeflag))
        return [item.type_num for item in items]

    assert ordered(0) == [11, 10]
    assert ordered(32) == [10, 11]
