"""MD map contracts using synthetic retail-layout files, without copyrighted data."""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.md.cli import md_app
from titan.md.game_profile import MD_PROFILE
from titan.md.actor import MD_ACTOR_LAYOUT
from titan.md.map_render import MartianMapRenderer
from titan.md.map_placements import project_martian_placements
from titan.u6.game_profile import U6_PROFILE
from titan.u6.map_objects import overlay_map_objects
from titan.u6.object import U6Object
from titan.u6.palette import U6Palette
from titan.u6.tile import U6AnimData, U6Tiles
from titan.u6.tileflag import U6TileFlagEntry
from tests.md_fixtures import initial_martian_objlist, object_block, resource_library
from tests.md_fixtures import md_game as md_game


def test_md_resource_wrapper_is_explicit_and_validated(md_game: Path) -> None:
    assert MD_PROFILE.read_resource(md_game, "MASKTYPE.VGA") == bytes(2048)
    assert (
        U6_PROFILE.read_resource(md_game, "OBJTILES.VGA")
        == (md_game / "OBJTILES.VGA").read_bytes()
    )
    (md_game / "MAPTILES.VGA").write_bytes(struct.pack("<II", 999, 0xE0000008))
    with pytest.raises(ValueError, match="resource size header"):
        MD_PROFILE.read_resource(md_game, "MAPTILES.VGA")


def test_md_terrain_palette_and_inactive_canal(md_game: Path) -> None:
    renderer = MartianMapRenderer.from_directory(md_game.parent)
    assert renderer.tiles.num_tiles == 2048
    assert renderer.animdata.resolve_tile(16, 1) == 32
    image = renderer.render_map(region=(0, 0, 2, 2), tick=1)
    assert image.size == (32, 32)
    assert image.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)


def test_md_lzmap_fallback_matches_raw_map(md_game: Path) -> None:
    (md_game / "LZMAP").write_bytes(resource_library((md_game / "MAP").read_bytes()))
    (md_game / "MAP").unlink()
    image = MartianMapRenderer.from_directory(md_game).render_map(region=(0, 0, 1, 1))
    assert image.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)


def test_md_surface_and_underground_object_overlays(md_game: Path) -> None:
    renderer = MartianMapRenderer.from_directory(md_game)
    for dungeon in (None, 0):
        image = renderer.render_map(region=(0, 0, 2, 2), dungeon=dungeon, objects=True)
        assert image.getpixel((16, 16)) == (24 * 255 // 63, 0, 0)
        assert image.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)


def test_md_multitile_footprint_overflows_into_crop(md_game: Path) -> None:
    flags = bytearray(7168)
    flags[2048 + 600] = 0xC0  # double width and height, bottom-right anchor
    (md_game / "TILEFLAG").write_bytes(flags)
    (md_game / "LZOBJBLK").write_bytes(
        resource_library(object_block(2, 2) + bytes(126))
    )
    image = MartianMapRenderer.from_directory(md_game).render_map(
        region=(1, 1, 1, 1), objects=True
    )
    assert image.getpixel((0, 0)) == (21 * 255 // 63, 0, 0)  # tile 597


@pytest.mark.parametrize("dungeon,side", [(None, 1024), (0, 256)])
@pytest.mark.parametrize("lighting", [False, True])
@pytest.mark.parametrize(
    "size,x,y,cell", [(0x80, -1, 0, 599), (0x40, 0, -1, 599), (0xC0, -1, -1, 597)]
)
def test_md_multitile_objects_wrap_world_seams(
    md_game: Path,
    dungeon: int | None,
    side: int,
    lighting: bool,
    size: int,
    x: int,
    y: int,
    cell: int,
) -> None:
    flags = bytearray(7168)
    flags[2048 + 600] = size
    (md_game / "TILEFLAG").write_bytes(flags)
    (md_game / "LZOBJBLK").write_bytes(
        resource_library(object_block(0, 0) + bytes(126))
    )
    (md_game / "LZDNGBLK").write_bytes(
        resource_library(object_block(0, 0, 1) + bytes(8) + initial_martian_objlist())
    )
    image = MartianMapRenderer.from_directory(md_game).render_map(
        region=(x % side, y % side, 1, 1),
        dungeon=dungeon,
        objects=True,
        lighting=lighting,
    )
    # Original objects use ten-bit coordinates even on 256-cell underground maps.
    expected = cell if dungeon is None else 32
    assert image.getpixel((0, 0)) == ((expected % 64) * 255 // 63, 0, 0)


def test_md_seam_alias_keeps_anchor_overlap_order(md_game: Path) -> None:
    flags = bytearray(7168)
    flags[2048 + 600] = 0x80
    (md_game / "TILEFLAG").write_bytes(flags)
    bases = bytearray((md_game / "BASETILE").read_bytes())
    struct.pack_into("<H", bases, 22, 610)
    (md_game / "BASETILE").write_bytes(bases)
    second = bytearray(object_block(1023, 1)[2:])
    second[4] = 11
    (md_game / "LZOBJBLK").write_bytes(
        resource_library(
            struct.pack("<H", 2) + object_block(0, 1)[2:] + second + bytes(126)
        )
    )
    image = MartianMapRenderer.from_directory(md_game).render_map(
        region=(1023, 1, 1, 1), objects=True
    )
    assert image.getpixel((0, 0)) == (34 * 255 // 63, 0, 0)


def test_md_actor_footprint_wraps_world_seam(md_game: Path) -> None:
    flags = bytearray(7168)
    flags[2048 + 600] = 0x80
    (md_game / "TILEFLAG").write_bytes(flags)
    image = MartianMapRenderer.from_directory(md_game).render_map(
        region=(1023, 0, 1, 1), actors=True
    )
    assert image.getpixel((0, 0)) == (23 * 255 // 63, 0, 0)


def test_md_full_atlas_projection_keeps_both_ends_without_mutation() -> None:
    obj = U6Object(0, 0, 0, 0, 10, 0, 0, 0)
    projected = project_martian_placements([obj], (0, 0, 8, 8), 8)
    assert [(o.x, o.y) for o in projected] == [(0, 0), (8, 0), (0, 8), (8, 8)]
    assert obj.x == 0 and obj.y == 0
    assert all(o.obj_n == 10 for o in projected)


def test_md_savegame_uses_selected_object_placements(
    md_game: Path, tmp_path: Path
) -> None:
    save = tmp_path / "SAVEGAME"
    save.mkdir()
    for row in range(8):
        for col in range(8):
            (save / f"OBJBLK{chr(65 + col)}{chr(65 + row)}").write_bytes(bytes(2))
    for level in range(5):
        (save / f"OBJBLK{chr(65 + level)}I").write_bytes(bytes(2))
    (save / "OBJBLKAA").write_bytes(object_block(0, 0))
    (save / "OBJLIST").write_bytes(initial_martian_objlist())
    image = MartianMapRenderer.from_directory(md_game).render_map(
        region=(0, 0, 2, 2), objects=True, savegame=save
    )
    assert image.getpixel((0, 0)) == (24 * 255 // 63, 0, 0)
    assert image.getpixel((16, 16)) == (32 * 255 // 63, 0, 0)


@pytest.mark.parametrize("region", [(-1, 0, 1, 1), (0, 0, 0, 1), (1023, 0, 2, 1)])
def test_md_invalid_regions_fail_clearly(
    md_game: Path, region: tuple[int, int, int, int]
) -> None:
    with pytest.raises(ValueError, match="region"):
        MartianMapRenderer.from_directory(md_game).render_map(region=region)


def test_md_underground_crop_cannot_exceed_level(md_game: Path) -> None:
    with pytest.raises(ValueError, match="256x256"):
        MartianMapRenderer.from_directory(md_game).render_map(
            region=(255, 0, 2, 1), dungeon=0
        )


def test_shared_object_passes_use_flags_and_hide_invisible_objects() -> None:
    tiles = U6Tiles([bytes([i]) * 256 for i in range(8)])
    palette = U6Palette()
    palette.colors = [(i, i, i) for i in range(256)]
    flags = [U6TileFlagEntry(i, 0, 0, 0, 0) for i in range(8)]
    flags[2].extra = 32  # background, even though it is later in file order
    flags[3].flags = 16  # foreground beats ordinary objects
    objects = [U6Object(0, 0, 0, 0, i, 0, 1, 0) for i in (3, 1, 2)]
    image = Image.new("RGB", (16, 16))
    overlay_map_objects(
        image,
        objects,
        tiles,
        palette,
        flags,
        tuple(range(8)),
        U6AnimData([]),
        MD_PROFILE,
    )
    assert image.getpixel((0, 0)) == (3, 3, 3)
    objects[0].status = 2  # invisible foreground
    image = Image.new("RGB", (16, 16))
    overlay_map_objects(
        image,
        objects,
        tiles,
        palette,
        flags,
        tuple(range(8)),
        U6AnimData([]),
        MD_PROFILE,
    )
    assert image.getpixel((0, 0)) == (1, 1, 1)


def test_md_marker_tiles_hidden_unless_requested(md_game: Path) -> None:
    basetile = bytearray((md_game / "BASETILE").read_bytes())
    struct.pack_into("<H", basetile, 20, 2047)
    (md_game / "BASETILE").write_bytes(basetile)
    renderer = MartianMapRenderer.from_directory(md_game)
    hidden = renderer.render_map(region=(1, 1, 1, 1), objects=True)
    shown = renderer.render_map(region=(1, 1, 1, 1), objects=True, show_markers=True)
    assert hidden.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    assert shown.getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.parametrize("lighting", [False, True])
@pytest.mark.parametrize("dungeon", [None, 0])
def test_md_show_invisible_reveals_world_objects(
    md_game: Path, lighting: bool, dungeon: int | None
) -> None:
    surface = bytearray(object_block(1, 1) + bytes(126))
    surface[2] |= 2
    underground = bytearray(
        object_block(1, 1, 1) + bytes(8) + initial_martian_objlist()
    )
    underground[2] |= 2
    (md_game / "LZOBJBLK").write_bytes(resource_library(bytes(surface)))
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(underground)))
    renderer = MartianMapRenderer.from_directory(md_game)
    hidden = renderer.render_map(
        region=(1, 1, 1, 1), dungeon=dungeon, objects=True, lighting=lighting
    )
    shown = renderer.render_map(
        region=(1, 1, 1, 1),
        dungeon=dungeon,
        objects=True,
        lighting=lighting,
        show_invisible=True,
    )
    assert hidden.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    assert shown.getpixel((0, 0)) == (24 * 255 // 63, 0, 0)


def test_md_show_invisible_preserves_multitile_and_marker_rules(md_game: Path) -> None:
    block = bytearray(object_block(2, 2) + bytes(126))
    block[2] |= 2
    (md_game / "LZOBJBLK").write_bytes(resource_library(bytes(block)))
    flags = bytearray(7168)
    flags[2048 + 600] = 0xC0
    (md_game / "TILEFLAG").write_bytes(flags)
    renderer = MartianMapRenderer.from_directory(md_game)
    assert renderer.render_map(
        region=(1, 1, 1, 1), objects=True, show_invisible=True
    ).getpixel((0, 0)) == (21 * 255 // 63, 0, 0)
    bases = bytearray((md_game / "BASETILE").read_bytes())
    struct.pack_into("<H", bases, 20, 2047)
    (md_game / "BASETILE").write_bytes(bases)
    assert renderer.render_map(
        region=(2, 2, 1, 1), objects=True, show_invisible=True
    ).getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    assert renderer.render_map(
        region=(2, 2, 1, 1), objects=True, show_invisible=True, show_markers=True
    ).getpixel((0, 0)) == (255, 0, 0)


def test_md_show_invisible_cli_wiring_and_requirement(
    md_game: Path, tmp_path: Path
) -> None:
    block = bytearray(object_block(1, 1) + bytes(126))
    block[2] |= 2
    (md_game / "LZOBJBLK").write_bytes(resource_library(bytes(block)))
    output = tmp_path / "revealed.png"
    args = [
        "map-render",
        "-g",
        str(md_game),
        "--region=1,1,1,1",
        "--show-invisible",
        "-o",
        str(output),
    ]
    result = CliRunner().invoke(md_app, args)
    assert result.exit_code == 2
    assert "--show-invisible requires --objects" in result.output
    result = CliRunner().invoke(md_app, args + ["--objects"])
    assert result.exit_code == 0, result.output
    with Image.open(output) as image:
        assert image.getpixel((0, 0)) == (24 * 255 // 63, 0, 0)


def test_md_cli_renders_png_using_config(md_game: Path, tmp_path: Path) -> None:
    destination = tmp_path / "output" / "map.png"
    with patch(
        "titan.md.cli.get_config", return_value={"md": {"game": {"base": str(md_game)}}}
    ):
        result = CliRunner().invoke(
            md_app,
            ["map-render", "--region", "0,0,2,2", "--objects", "-o", str(destination)],
        )
    assert result.exit_code == 0, result.output
    with Image.open(destination) as image:
        assert image.size == (32, 32)
        assert image.format == "PNG"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--region", "bad"],
        ["--region", "1,2,3"],
        ["--region", "0,0,1,1", "--full"],
        ["--dungeon", "5"],
        ["--tick", "-1", "--full"],
        ["--show-markers", "--full"],
        [],
    ],
)
def test_md_cli_rejects_invalid_requests(md_game: Path, arguments: list[str]) -> None:
    result = CliRunner().invoke(md_app, ["map-render", "-g", str(md_game), *arguments])
    assert result.exit_code == 2, result.output


def test_md_cli_reports_missing_resources_without_traceback(md_game: Path) -> None:
    (md_game / "MAPTILES.VGA").unlink()
    result = CliRunner().invoke(
        md_app, ["map-render", "-g", str(md_game), "--region", "0,0,1,1"]
    )
    assert result.exit_code == 1
    assert "MAPTILES.VGA" in result.output
    assert "Traceback" not in result.output


def test_md_actor_layer_sits_above_objects_and_below_foreground(md_game: Path) -> None:
    data = initial_martian_objlist()
    struct.pack_into("<H", data, 0x402, 11)
    basetile = bytearray((md_game / "BASETILE").read_bytes())
    struct.pack_into("<H", basetile, 22, 610)
    (md_game / "BASETILE").write_bytes(basetile)
    (md_game / "LZOBJBLK").write_bytes(
        resource_library(object_block(0, 0) + bytes(126))
    )
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(10) + data))
    renderer = MartianMapRenderer.from_directory(md_game)
    image = renderer.render_map(region=(0, 0, 1, 1), objects=True, actors=True)
    assert image.getpixel((0, 0)) == (34 * 255 // 63, 0, 0)
    flags = bytearray(7168)
    flags[2048 + 600] = 0x10
    (md_game / "TILEFLAG").write_bytes(flags)
    image = renderer.render_map(region=(0, 0, 1, 1), objects=True, actors=True)
    assert image.getpixel((0, 0)) == (24 * 255 // 63, 0, 0)


def test_md_invisible_npc_hidden_but_party_keeps_outline(md_game: Path) -> None:
    data = initial_martian_objlist()
    data[2] = 2
    data[0x802] = 0
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(10) + data))
    objtiles = bytearray((md_game / "OBJTILES.VGA").read_bytes())
    objtiles[(600 - 512) * 256] = 0
    (md_game / "OBJTILES.VGA").write_bytes(objtiles)
    renderer = MartianMapRenderer.from_directory(md_game)
    hidden = renderer.render_map(region=(1, 0, 1, 1), actors=True)
    assert hidden.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    data[0x802] = 0x80
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(10) + data))
    party = renderer.render_map(region=(1, 0, 1, 1), actors=True)
    assert party.getpixel((0, 0)) == (11 * 255 // 63, 0, 0)
    assert party.getpixel((1, 0)) == (32 * 255 // 63, 0, 0)


def test_md_saved_canal_state_changes_render_without_changing_game_files(
    md_game: Path, tmp_path: Path
) -> None:
    save = tmp_path / "snapshot"
    save.mkdir()
    data = initial_martian_objlist()
    (save / "OBJLIST").write_bytes(data)
    renderer = MartianMapRenderer.from_directory(md_game)
    dry = renderer.render_map(region=(10, 10, 1, 1), savegame=save, tick=1)
    data[MD_ACTOR_LAYOUT.talk_flags + 118] = (1 << 5) | (1 << 6)
    (save / "OBJLIST").write_bytes(data)
    wet = renderer.render_map(region=(10, 10, 1, 1), savegame=save, tick=1)
    assert dry.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    assert wet.getpixel((0, 0)) == (33 * 255 // 63, 0, 0)
    assert MD_PROFILE.read_resource(md_game, "LZDNGBLK").endswith(
        initial_martian_objlist()
    )


@pytest.mark.parametrize(
    "flags,cistern,canal", [(0, 34, 32), (0x20, 35, 32), (0x40, 34, 32), (0x60, 35, 33)]
)
@pytest.mark.parametrize("tick", [0, 1, 8])
def test_md_saved_water_renders_static_adjacent_art(
    md_game: Path, tmp_path: Path, flags: int, cistern: int, canal: int, tick: int
) -> None:
    # Distinct placeholder/base art catches rendering the raw dry placeholder.
    chunks = bytearray((md_game / "CHUNKS").read_bytes())
    chunks[0] = 1
    (md_game / "CHUNKS").write_bytes(chunks)
    animation = bytearray((md_game / "ANIMDATA").read_bytes())
    struct.pack_into("<H", animation, 0, 2)
    struct.pack_into("<H", animation, 4, 1)
    struct.pack_into("<H", animation, 68, 34)
    animation[131] = 1
    (md_game / "ANIMDATA").write_bytes(animation)
    save = tmp_path / "controlled-state"
    save.mkdir()
    data = initial_martian_objlist()
    data[MD_ACTOR_LAYOUT.talk_flags + 118] = flags
    (save / "OBJLIST").write_bytes(data)
    renderer = MartianMapRenderer.from_directory(md_game)
    image = renderer.render_map(region=(0, 0, 2, 1), savegame=save, tick=tick)
    assert image.getpixel((0, 0)) == (cistern * 255 // 63, 0, 0)
    assert image.getpixel((16, 0)) == (canal * 255 // 63, 0, 0)
    # Reusing a renderer after a progressed state must return to initial dry art.
    initial = renderer.render_map(region=(0, 0, 2, 1), tick=tick)
    assert initial.getpixel((0, 0)) == (34 * 255 // 63, 0, 0)
    assert initial.getpixel((16, 0)) == (32 * 255 // 63, 0, 0)


def test_md_dream_player_keeps_invisibility_outline_without_party_flag(
    md_game: Path,
) -> None:
    from titan.u6.object import pack_position

    data = initial_martian_objlist()
    data[0] = 2
    struct.pack_into("<H", data, 0x400, 10)
    data[0x103:0x106] = bytes(pack_position(9, 9, 0))
    objtiles = bytearray((md_game / "OBJTILES.VGA").read_bytes())
    objtiles[(600 - 512) * 256] = 0
    (md_game / "OBJTILES.VGA").write_bytes(objtiles)
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(10) + data))
    renderer = MartianMapRenderer.from_directory(md_game)
    awake = renderer.render_map(region=(0, 0, 1, 1), actors=True)
    assert awake.getpixel((0, 0)) == (32 * 255 // 63, 0, 0)
    struct.pack_into("<H", data, 0x1D29, 0x10)
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(10) + data))
    dreaming = renderer.render_map(region=(0, 0, 1, 1), actors=True)
    assert dreaming.getpixel((0, 0)) == (11 * 255 // 63, 0, 0)
    assert dreaming.getpixel((1, 0)) == (32 * 255 // 63, 0, 0)
