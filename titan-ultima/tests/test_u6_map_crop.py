"""U6 crop boundaries must retain visible cells of objects anchored outside the image."""

from __future__ import annotations

import contextlib
import io
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from typer.testing import CliRunner

from tests.test_u6_cli import _make_synthetic_gamedir
from titan.u6.actor import REQUIRED_SIZE
from titan.u6.cli import cmd_map_audit_zorder, cmd_map_render, u6_app
from titan.u6.object import pack_position


@pytest.fixture
def crop_game(tmp_path: Path) -> Path:
    """Four differently colored sprite cells over black terrain, without retail data."""
    game = tmp_path / "game"
    game.mkdir()
    _make_synthetic_gamedir(str(game))
    bases = bytearray(2048)
    struct.pack_into("<H", bases, 20, 600)
    struct.pack_into("<H", bases, 22, 610)
    (game / "BASETILE").write_bytes(bases)
    tiles = bytearray((game / "OBJTILES.VGA").read_bytes())
    palette = bytearray(1024)
    for tile, index, color in (
        (600, 7, (63, 0, 0)),
        (599, 8, (0, 63, 0)),
        (598, 9, (0, 0, 63)),
        (597, 10, (63, 63, 0)),
        (610, 11, (63, 0, 63)),
    ):
        offset = (tile - 512) * 256
        tiles[offset : offset + 256] = bytes([index]) * 256
        palette[index * 3 : index * 3 + 3] = bytes(color)
    (game / "OBJTILES.VGA").write_bytes(tiles)
    (game / "U6PAL").write_bytes(palette)
    return game


def test_u6_crop_command_retains_existing_options() -> None:
    result = CliRunner().invoke(u6_app, ["map-render", "--help"])
    assert result.exit_code == 0
    for option in (
        "--region",
        "--dungeon",
        "--full",
        "--objects",
        "--tick",
        "--show-invisible",
    ):
        assert option in result.output
    for term in ("nonnegative", "positive", "visible"):
        assert term in result.output


def write_crop_objects(
    game: Path, level: int, records: list[tuple[int, int, int]], size: int
) -> None:
    """Place synthetic object records on exactly one of U6's six map levels."""
    block = struct.pack("<H", len(records)) + b"".join(
        struct.pack("<8B", 0, *pack_position(x, y, level), obj_n, 0, 1, 0)
        for x, y, obj_n in records
    )
    surface = (block if level == 0 else bytes(2)) + bytes(126)
    underground = b"".join(block if level == z else bytes(2) for z in range(1, 6))
    (game / "LZOBJBLK").write_bytes(surface)
    (game / "LZDNGBLK").write_bytes(underground + bytes(REQUIRED_SIZE))
    flags = bytearray(7168)
    flags[2048 + 600] = size
    flags[2048 + 599] = 0x10  # Native foreground overflow appends above ordinary cells.
    (game / "TILEFLAG").write_bytes(flags)


def render_crop_fixture(
    game: Path,
    region: tuple[int, int, int, int],
    dungeon: int | None = None,
    tick: int = 0,
    show_invisible: bool = False,
) -> Image.Image:
    """Exercise the actual U6 command and retain its RGBA pixel output."""
    output = game / "crop.png"
    with contextlib.redirect_stdout(io.StringIO()):
        result = cmd_map_render(
            SimpleNamespace(
                gamedir=str(game),
                palette=None,
                region=",".join(map(str, region)),
                dungeon=dungeon,
                full=False,
                tick=tick,
                objects=True,
                show_invisible=show_invisible,
                output=str(output),
            )
        )
    assert result == 0
    with Image.open(output) as image:
        return image.convert("RGBA")


@pytest.mark.parametrize("dungeon", [None, 0, 1, 2, 3, 4])
@pytest.mark.parametrize(
    "size,region,color",
    [
        (0x80, (9, 10, 1, 1), (0, 255, 0, 255)),
        (0x40, (10, 9, 1, 1), (0, 255, 0, 255)),
        (0xC0, (9, 9, 1, 1), (255, 255, 0, 255)),
    ],
)
def test_u6_crop_includes_footprint_with_anchor_outside(
    crop_game: Path,
    dungeon: int | None,
    size: int,
    region: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
) -> None:
    level = 0 if dungeon is None else dungeon + 1
    write_crop_objects(crop_game, level, [(10, 10, 10)], size)
    cropped = render_crop_fixture(crop_game, region, dungeon)
    assert cropped.getpixel((0, 0)) == color
    reference = render_crop_fixture(crop_game, (8, 8, 4, 4), dungeon)
    x, y, width, height = region
    assert (
        cropped.tobytes()
        == reference.crop(
            ((x - 8) * 16, (y - 8) * 16, (x - 8 + width) * 16, (y - 8 + height) * 16)
        ).tobytes()
    )


def test_u6_off_crop_foreground_footprint_covers_ordinary_anchor(
    crop_game: Path,
) -> None:
    write_crop_objects(crop_game, 0, [(9, 10, 11), (10, 10, 10)], 0x80)
    image = render_crop_fixture(crop_game, (9, 10, 1, 1))
    # Native foreground overflow appends even when its anchor is outside view.
    assert image.getpixel((0, 0)) == (0, 255, 0, 255)


def test_u6_off_crop_plain_footprint_shows_through_transparent_anchor(
    crop_game: Path,
) -> None:
    write_crop_objects(crop_game, 0, [(9, 10, 11), (10, 10, 10)], 0x80)
    # Ordinary overflow prepends below the ordinary anchor; its pixels remain
    # visible through holes. This differs from the foreground-overflow case.
    flags = bytearray((crop_game / "TILEFLAG").read_bytes())
    flags[2048 + 599] = 0
    (crop_game / "TILEFLAG").write_bytes(flags)
    tiles = bytearray((crop_game / "OBJTILES.VGA").read_bytes())
    start = (610 - 512) * 256
    tiles[start : start + 256] = bytes([255]) * 256
    tiles[start] = 11
    (crop_game / "OBJTILES.VGA").write_bytes(tiles)
    image = render_crop_fixture(crop_game, (9, 10, 1, 1))
    assert image.getpixel((0, 0)) == (255, 0, 255, 255)
    assert image.getpixel((8, 8)) == (0, 255, 0, 255)


def test_u6_nonintersecting_footprints_stay_outside_crop(crop_game: Path) -> None:
    write_crop_objects(crop_game, 0, [(10, 10, 10)], 0xC0)
    assert render_crop_fixture(crop_game, (8, 8, 1, 1)).getpixel((0, 0)) == (
        0,
        0,
        0,
        255,
    )


@pytest.mark.parametrize("tick", [0, 1])
def test_u6_off_crop_footprint_uses_requested_animation_tick(
    crop_game: Path, tick: int
) -> None:
    write_crop_objects(crop_game, 0, [(10, 10, 10)], 0x80)
    animation = bytearray(194)
    struct.pack_into("<H", animation, 0, 1)
    struct.pack_into("<H", animation, 2, 599)
    struct.pack_into("<H", animation, 66, 610)
    animation[130] = 1
    (crop_game / "ANIMDATA").write_bytes(animation)
    image = render_crop_fixture(crop_game, (9, 10, 1, 1), tick=tick)
    assert (
        image.tobytes()
        == render_crop_fixture(crop_game, (8, 8, 4, 4), tick=tick)
        .crop((16, 32, 32, 48))
        .tobytes()
    )
    assert image.getpixel((0, 0)) == (
        (255, 0, 255, 255) if tick == 0 else (255, 0, 0, 255)
    )


def hide_crop_object(game: Path, level: int, index: int = 0) -> None:
    """Set invisibility on a synthetic map record without changing its location bits."""
    path = game / ("LZOBJBLK" if level == 0 else "LZDNGBLK")
    data = bytearray(path.read_bytes())
    offset = 2 + (level - 1) * 2 if level else 2
    data[offset + index * 8] |= 2
    path.write_bytes(data)


@pytest.mark.parametrize("dungeon", [None, 0, 1, 2, 3, 4])
@pytest.mark.parametrize("size,region", [(0, (10, 10, 1, 1)), (0xC0, (9, 9, 1, 1))])
def test_u6_invisible_objects_and_footprints_are_hidden(
    crop_game: Path, dungeon: int | None, size: int, region: tuple[int, int, int, int]
) -> None:
    level = 0 if dungeon is None else dungeon + 1
    write_crop_objects(crop_game, level, [(10, 10, 10)], size)
    visible = render_crop_fixture(crop_game, region, dungeon)
    assert visible.getpixel((0, 0)) != (0, 0, 0, 255)
    hide_crop_object(crop_game, level)
    assert render_crop_fixture(crop_game, region, dungeon).getpixel((0, 0)) == (
        0,
        0,
        0,
        255,
    )
    assert (
        render_crop_fixture(crop_game, region, dungeon, show_invisible=True).tobytes()
        == visible.tobytes()
    )


def test_u6_hidden_foreground_uncovers_visible_object(crop_game: Path) -> None:
    write_crop_objects(crop_game, 0, [(10, 10, 11), (10, 10, 10)], 0xC0 | 0x10)
    assert render_crop_fixture(crop_game, (10, 10, 1, 1)).getpixel((0, 0)) == (
        255,
        0,
        0,
        255,
    )
    hide_crop_object(crop_game, 0, 1)
    assert render_crop_fixture(crop_game, (10, 10, 1, 1)).getpixel((0, 0)) == (
        255,
        0,
        255,
        255,
    )
    assert render_crop_fixture(crop_game, (9, 9, 1, 1)).getpixel((0, 0)) == (
        0,
        0,
        0,
        255,
    )


def test_u6_zorder_audit_skips_invisible_objects(crop_game: Path) -> None:
    write_crop_objects(crop_game, 0, [(10, 10, 10), (10, 10, 11)], 0)
    (crop_game / "LOOK.LZD").write_bytes(
        struct.pack("<H", 600) + b"one\0" + struct.pack("<H", 610) + b"two\0"
    )
    args = SimpleNamespace(
        gamedir=str(crop_game),
        min_winner_opacity=0.6,
        min_loser_opacity=0.1,
        limit=200,
        dungeons=False,
    )
    visible_output = io.StringIO()
    with contextlib.redirect_stdout(visible_output):
        assert cmd_map_audit_zorder(args) == 0
    assert "total ordered overlap candidates: 1" in visible_output.getvalue()
    hide_crop_object(crop_game, 0)
    hidden_output = io.StringIO()
    with contextlib.redirect_stdout(hidden_output):
        assert cmd_map_audit_zorder(args) == 0
    assert "total ordered overlap candidates: 0" in hidden_output.getvalue()
    args.show_invisible = True
    revealed_output = io.StringIO()
    with contextlib.redirect_stdout(revealed_output):
        assert cmd_map_audit_zorder(args) == 0
    assert "total ordered overlap candidates: 1" in revealed_output.getvalue()


@pytest.mark.parametrize("tick", [0, 1])
def test_u6_animation_does_not_change_logical_layer_flags(
    crop_game: Path, tick: int
) -> None:
    # First ordinary record wins, even when the other's visible animation frame
    # has a foreground flag. The original compositor ranks logical tiles first.
    write_crop_objects(crop_game, 0, [(10, 10, 11), (10, 10, 10)], 0)
    animation = bytearray(194)
    struct.pack_into("<H", animation, 0, 1)
    struct.pack_into("<H", animation, 2, 600)
    struct.pack_into("<H", animation, 66, 599)
    animation[130] = 1
    (crop_game / "ANIMDATA").write_bytes(animation)
    assert render_crop_fixture(crop_game, (10, 10, 1, 1), tick=tick).getpixel(
        (0, 0)
    ) == (255, 0, 255, 255)


def test_u6_audit_requires_actual_intersecting_opaque_pixels(crop_game: Path) -> None:
    write_crop_objects(crop_game, 0, [(10, 10, 10), (10, 10, 11)], 0)
    tiles = bytearray((crop_game / "OBJTILES.VGA").read_bytes())
    for tile, index, left in ((600, 7, True), (610, 11, False)):
        raw = bytes(index if (p % 16 < 8) == left else 255 for p in range(256))
        tiles[(tile - 512) * 256 : (tile - 511) * 256] = raw
    (crop_game / "OBJTILES.VGA").write_bytes(tiles)
    (crop_game / "LOOK.LZD").write_bytes(
        struct.pack("<H", 600) + b"one\0" + struct.pack("<H", 610) + b"two\0"
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert (
            cmd_map_audit_zorder(
                SimpleNamespace(
                    gamedir=str(crop_game),
                    min_winner_opacity=0.4,
                    min_loser_opacity=0.1,
                    limit=0,
                    dungeons=False,
                )
            )
            == 0
        )
    assert "total ordered overlap candidates: 0" in output.getvalue()


def test_u6_show_invisible_cli_reveals_world_objects(crop_game: Path) -> None:
    write_crop_objects(crop_game, 0, [(10, 10, 10)], 0)
    hide_crop_object(crop_game, 0)
    output = crop_game / "revealed.png"
    result = CliRunner().invoke(
        u6_app,
        [
            "map-render",
            "-g",
            str(crop_game),
            "--region=10,10,1,1",
            "--objects",
            "--show-invisible",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    with Image.open(output) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)


def test_u6_show_invisible_requires_object_overlay(crop_game: Path) -> None:
    result = CliRunner().invoke(
        u6_app,
        ["map-render", "-g", str(crop_game), "--region=0,0,1,1", "--show-invisible"],
    )
    assert result.exit_code == 1
    assert "--show-invisible requires --objects" in result.output


def test_u6_zorder_audit_help_lists_visibility_option() -> None:
    result = CliRunner().invoke(u6_app, ["map-audit-zorder", "--help"])
    assert result.exit_code == 0
    assert "--show-invisible" in result.output


@pytest.mark.parametrize("objects", [False, True])
@pytest.mark.parametrize(
    "dungeon,region,message",
    [
        (None, (-1, 0, 1, 1), "nonnegative"),
        (None, (0, -1, 1, 1), "nonnegative"),
        (None, (0, 0, 0, 1), "positive"),
        (None, (0, 0, 1, 0), "positive"),
        (None, (0, 0, -1, 1), "positive"),
        (None, (0, 0, 1, -1), "positive"),
        (None, (1023, 0, 2, 1), "1024x1024"),
        (None, (0, 1023, 1, 2), "1024x1024"),
        (0, (255, 0, 2, 1), "256x256"),
        (4, (0, 255, 1, 2), "256x256"),
        (None, (1024, 0, 1, 1), "1024x1024"),
        (0, (0, 256, 1, 1), "256x256"),
    ],
)
def test_u6_invalid_crop_reports_error_without_overwriting_output(
    crop_game: Path,
    capsys: pytest.CaptureFixture[str],
    objects: bool,
    dungeon: int | None,
    region: tuple[int, int, int, int],
    message: str,
) -> None:
    output = crop_game / "existing.png"
    output.write_bytes(b"existing output")
    args = SimpleNamespace(
        gamedir=str(crop_game),
        palette=None,
        region=",".join(map(str, region)),
        dungeon=dungeon,
        full=False,
        tick=0,
        objects=objects,
        output=str(output),
    )
    assert cmd_map_render(args) == 1
    error = capsys.readouterr().err
    assert "ERROR: --region" in error and message in error
    assert output.read_bytes() == b"existing output"


@pytest.mark.parametrize("region", ["-1,0,1,1", "0,0,0,1", "1023,0,2,1"])
def test_u6_invalid_crop_cli_has_no_traceback(crop_game: Path, region: str) -> None:
    output = crop_game / "not_created.png"
    result = CliRunner().invoke(
        u6_app,
        ["map-render", "-g", str(crop_game), f"--region={region}", "-o", str(output)],
    )
    assert result.exit_code == 1
    assert "ERROR: --region" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


@pytest.mark.parametrize("dungeon,side", [(None, 1024), (4, 256)])
def test_u6_last_map_cell_is_a_valid_crop(
    crop_game: Path, dungeon: int | None, side: int
) -> None:
    assert render_crop_fixture(crop_game, (side - 1, side - 1, 1, 1), dungeon).size == (
        16,
        16,
    )
