"""MD power rendering contracts established by the original executable probe."""

from __future__ import annotations

import struct
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.md_fixtures import initial_martian_objlist, resource_library
from tests.md_fixtures import md_game as md_game
from titan.md.actor import MD_ACTOR_LAYOUT
from titan.md.gamestate import MartianGameState
from titan.md.map_animation import build_martian_animation
from titan.md.map_render import MartianMapRenderer
from titan.md.power_state import restore_martian_power_objects
from titan.u6.object import U6Object, pack_position
from titan.u6.tile import U6AnimData, U6AnimEntry


@pytest.mark.parametrize("flags", [0, 4, 0x10, 0x14])
@pytest.mark.parametrize("tick", [0, 1, 2, 7, 15, 16, 31, 65535, 65536])
def test_md_power_ranges_match_dos_exclusive_bounds(flags: int, tick: int) -> None:
    # Include boundary neighbors absent from retail ANIMDATA, as well as real entries.
    controlled = (848, 850, 854, 857, 1980, 1981, 1983, 1992, 1993)
    neighbors = (847, 851, 853, 858, 1979, 1984, 1991, 1994)
    raw = U6AnimData([U6AnimEntry(tile, 408, 6, 1) for tile in controlled + neighbors])
    data = initial_martian_objlist()
    data[MD_ACTOR_LAYOUT.talk_flags + 115] = flags
    animation = build_martian_animation(raw, MartianGameState.parse(bytes(data)))
    for tile in controlled:
        assert animation.resolve_tile(tile, tick) == 408 + (
            ((tick & 6) >> 1) if flags & 4 else 0
        )
    for tile in neighbors:
        assert animation.resolve_tile(tile, tick) == 408 + ((tick & 6) >> 1)


@pytest.mark.parametrize("power", [False, True])
def test_md_power_object_frames_match_original_load_branches(power: bool) -> None:
    source = [
        U6Object(0, i, 10, 0, obj, frame, 7, 9)
        for i, (obj, frame) in enumerate(
            [(154, n) for n in range(8)] + [(233, n) for n in range(8)] + [(10, 5)]
        )
    ]
    original = [asdict(obj) for obj in source]
    restored = restore_martian_power_objects(source, power)
    assert [(obj.obj_n, obj.frame_n) for obj in restored] == (
        [(154, 1)] * 8
        + [(233, n + 4 if n in (1, 3) else n) for n in range(8)]
        + [(10, 5)]
        if power
        else [
            (obj, n - 4 if n in (5, 7) else n) for obj in (154, 233) for n in range(8)
        ]
        + [(10, 5)]
    )
    assert [asdict(obj) for obj in source] == original
    assert all((obj.qty, obj.quality) == (7, 9) for obj in restored)


def test_md_power_steam_creation_deduplicates_and_preserves_source_records() -> None:
    source = [
        U6Object(0, 10, 10, 0, 208, 0, 0, 0),
        U6Object(0, 10, 10, 0, 208, 0, 0, 0),
        U6Object(0, 11, 10, 0, 208, 0, 0, 0),
        U6Object(0, 11, 11, 0, 209, 0, 0, 0),
        U6Object(0, 10, 11, 1, 209, 1, 0, 0),
    ]
    powered = restore_martian_power_objects(source, True)
    assert len(powered) == 6
    assert asdict(powered[-1]) == asdict(U6Object(0, 10, 11, 0, 209, 1, 0, 0))
    assert restore_martian_power_objects(powered, True) == powered
    assert restore_martian_power_objects(powered, False) == source[:3]
    assert len(source) == 5 and source[3].frame_n == 0


def test_md_power_does_not_rewrite_carried_object_placements() -> None:
    inventory = U6Object(0x10, 1, 0, 0, 154, 0, 1, 0)
    assert not inventory.is_on_map
    assert restore_martian_power_objects([inventory], True) == [inventory]


@pytest.mark.parametrize("power", [False, True])
@pytest.mark.parametrize("saved", [False, True])
def test_md_renderer_restores_saved_power_art_without_writing_save(
    md_game: Path, tmp_path: Path, power: bool, saved: bool
) -> None:
    basetile = bytearray((md_game / "BASETILE").read_bytes())
    for obj, tile in ((154, 700), (208, 720), (209, 730)):
        struct.pack_into("<H", basetile, obj * 2, tile)
    (md_game / "BASETILE").write_bytes(basetile)
    objects = [(154, 0, 0, 0), (208, 0, 1, 0), (209, 0, 2, 1)]
    block = struct.pack("<H", len(objects)) + b"".join(
        struct.pack("<B3BHBB", 0, *pack_position(x, y, 0), obj | (frame << 10), 0, 0)
        for obj, frame, x, y in objects
    )
    (md_game / "LZOBJBLK").write_bytes(resource_library(block + bytes(126)))
    data = initial_martian_objlist()
    data[MD_ACTOR_LAYOUT.talk_flags + 115] = 4 if power else 0
    (md_game / "LZDNGBLK").write_bytes(resource_library(bytes(10) + data))
    snapshot = None
    if saved:
        snapshot = tmp_path / "SAVEGAME"
        snapshot.mkdir()
        for row in range(8):
            for col in range(8):
                (snapshot / f"OBJBLK{chr(65 + col)}{chr(65 + row)}").write_bytes(
                    bytes(2)
                )
        for level in range(5):
            (snapshot / f"OBJBLK{chr(65 + level)}I").write_bytes(bytes(2))
        (snapshot / "OBJBLKAA").write_bytes(block)
        (snapshot / "OBJLIST").write_bytes(data)
    saved_original = (
        {p.name: p.read_bytes() for p in snapshot.iterdir()} if snapshot else {}
    )
    original = {p.name: p.read_bytes() for p in md_game.iterdir()}
    image = MartianMapRenderer.from_directory(md_game).render_map(
        region=(0, 0, 3, 2), objects=True, savegame=snapshot
    )
    assert image.getpixel((0, 0)) == (((701 if power else 700) % 64) * 255 // 63, 0, 0)
    assert image.getpixel((16, 16)) == (((731 % 64) if power else 32) * 255 // 63, 0, 0)
    assert image.getpixel((32, 16)) == (((730 % 64) if power else 32) * 255 // 63, 0, 0)
    assert {p.name: p.read_bytes() for p in md_game.iterdir()} == original
    if snapshot:
        assert {p.name: p.read_bytes() for p in snapshot.iterdir()} == saved_original
