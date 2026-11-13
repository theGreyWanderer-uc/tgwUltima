"""U6 z-order diagnosis and rendering must use file order consistently everywhere."""

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
from titan.u6.cli import cmd_map_audit_zorder, cmd_map_render, u6_app
from titan.u6.object import pack_position


def test_u6_overlap_help_describes_engine_order_and_retains_options() -> None:
    result = CliRunner().invoke(u6_app, ["map-audit-zorder", "--help"])
    assert result.exit_code == 0
    for option in (
        "--min-winner-opacity",
        "--min-loser-opacity",
        "--limit",
        "--dungeons",
        "--show-invisible",
    ):
        assert option in result.output
    # Rich wraps descriptions at the terminal width; assert wording without
    # requiring a phrase to remain on one physical line.
    for term in ("original", "cell-stack", "deterministic", "tick", "zero"):
        assert term in result.output


@pytest.fixture
def sign_game(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    game.mkdir()
    _make_synthetic_gamedir(str(game))
    bases = bytearray(2048)
    struct.pack_into("<H", bases, 20, 1246)
    struct.pack_into("<H", bases, 22, 1243)
    (game / "BASETILE").write_bytes(bases)
    tiles = bytearray((game / "OBJTILES.VGA").read_bytes())
    tiles[(1243 - 512) * 256 : (1244 - 512) * 256] = bytes([8]) * 256
    (game / "OBJTILES.VGA").write_bytes(tiles)
    palette = bytearray(1024)
    palette[21:24], palette[24:27] = bytes([63, 0, 0]), bytes([0, 0, 63])
    (game / "U6PAL").write_bytes(palette)
    (game / "LOOK.LZD").write_bytes(
        struct.pack("<H", 1243)
        + b"north plaque\0"
        + struct.pack("<H", 1246)
        + b"post\0"
    )
    records = []
    for x, y in ((294, 407), (284, 410), (50, 50)):
        for obj_n in (10, 11):
            records.append(
                struct.pack("<8B", 0, *pack_position(x, y, 0), obj_n, 0, 1, 0)
            )
    (game / "LZOBJBLK").write_bytes(
        struct.pack("<H", len(records)) + b"".join(records) + bytes(126)
    )
    return game


def test_u6_audit_explains_the_same_stack_order_at_every_coordinate(
    sign_game: Path,
) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert (
            cmd_map_audit_zorder(
                SimpleNamespace(
                    gamedir=str(sign_game),
                    min_winner_opacity=0.6,
                    min_loser_opacity=0.1,
                    limit=0,
                    dungeons=False,
                )
            )
            == 0
        )
    text = output.getvalue()
    assert "total ordered overlap candidates: 3" in text
    assert "(50, 50, 0)" in text
    assert "(294, 407, 0)" in text
    assert "(284, 410, 0)" in text
    assert text.count("order=ordinary-prepend overlap_pixels=256") == 3
    assert text.count("OVER: 'post'") == 3


@pytest.mark.parametrize(
    "x,y,color",
    [(294, 407, (255, 0, 0)), (284, 410, (255, 0, 0)), (50, 50, (255, 0, 0))],
)
def test_u6_signpost_rendering_has_no_coordinate_exceptions(
    sign_game: Path, x: int, y: int, color: tuple[int, int, int]
) -> None:
    destination = sign_game / "sign.png"
    with contextlib.redirect_stdout(io.StringIO()):
        assert (
            cmd_map_render(
                SimpleNamespace(
                    gamedir=str(sign_game),
                    palette=None,
                    region=f"{x},{y},1,1",
                    dungeon=None,
                    full=False,
                    tick=0,
                    objects=True,
                    output=str(destination),
                )
            )
            == 0
        )
    with Image.open(destination) as image:
        assert image.convert("RGB").getpixel((0, 0)) == color
