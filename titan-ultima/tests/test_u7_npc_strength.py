"""BG/SI strength fields must not mix SI skin/freeze bits into actor stats."""

from __future__ import annotations

import csv
import io
import struct

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.monster import live_monsters_from_source
from titan.u7.save import U7NPCData, U7Save
from tests.test_u7_actor_schedule_context import _actor_record


def strength_record(value: int = 0x36) -> bytes:
    data = bytearray(_actor_record())
    data[18] = value
    return bytes(data)


@pytest.mark.parametrize("flavor", ["runtime", "original", "unknown", "auto"])
@pytest.mark.parametrize(
    ("game", "raw", "expected"),
    [
        ("bg", 0x36, 54),
        ("si", 0x36, 22),
        ("bg", 0xF6, 54),
        ("si", 0xF6, 22),
        ("bg", 0x3F, 63),
        ("si", 0xFF, 31),
        ("bg", 0x16, 22),
        ("si", 0x16, 22),
    ],
)
def test_strength_game_context_is_independent_of_source_flavor(
    game, raw, expected, flavor
):
    data = struct.pack("<HH", 2, 0) + strength_record(raw) * 2
    parsed = U7NPCData.from_bytes(data, game=game, npc_flavor=flavor)
    assert [npc.strength for npc in parsed.npcs] == [expected, expected]


@pytest.mark.parametrize(("game", "expected"), [("bg", 54), ("si", 22)])
def test_game_reaches_loose_save_initgame_and_auto_readers(tmp_path, game, expected):
    data = struct.pack("<HH", 1, 0) + strength_record()
    path = tmp_path / "npc.dat"
    path.write_bytes(data)
    archive = U7FlexArchive()
    archive.records = [b"npc.dat".ljust(13, b"\0") + data]
    initial = tmp_path / "INITGAME.DAT"
    initial.write_bytes(archive.to_bytes())
    save = U7Save("Test", {"npc.dat": data}, "flex")
    parsed = [
        U7NPCData.from_file(str(path), game=game),
        U7NPCData.from_save(save, game=game),
        U7NPCData.from_initgame_file(str(initial), game=game),
        U7NPCData.from_bytes_auto(data, game=game),
    ]
    assert [value.npcs[0].strength for value in parsed] == [expected] * 4
    assert U7NPCData.from_bytes(data).npcs[0].strength == 54


@pytest.mark.parametrize(("game", "expected"), [("bg", 54), ("si", 22)])
def test_game_reaches_monster_readers_and_source_loader(tmp_path, game, expected):
    data = struct.pack("<H", 1) + strength_record()
    path = tmp_path / "monsnpcs.dat"
    path.write_bytes(data)
    loaded, _ = live_monsters_from_source(str(tmp_path), game=game)
    assert [
        U7NPCData.from_monsnpcs_bytes(data, game=game).npcs[0].strength,
        U7NPCData.from_monsnpcs_file(str(path), game=game).npcs[0].strength,
        loaded.npcs[0].strength,
    ] == [expected] * 3


def test_actor_game_requires_explicit_supported_identity():
    data = struct.pack("<HH", 1, 0) + strength_record()
    with pytest.raises(ValueError, match="actor game must be bg or si"):
        U7NPCData.from_bytes(data, game="other")


@pytest.mark.parametrize(("game", "expected"), [("bg", "54"), ("si", "22")])
@pytest.mark.parametrize("command", ["npc-dump", "save-npcs", "monster-dump"])
def test_cli_threads_selected_game_to_actor_strength(tmp_path, game, expected, command):
    data = struct.pack("<HH", 1, 0) + strength_record()
    if command == "npc-dump":
        source = tmp_path / "npc.dat"
        source.write_bytes(data)
    elif command == "save-npcs":
        archive = U7FlexArchive()
        archive.records = [b"npc.dat".ljust(13, b"\0") + data]
        source = tmp_path / "sample.sav"
        source.write_bytes(archive.to_bytes())
    else:
        source = tmp_path / "monsnpcs.dat"
        source.write_bytes(struct.pack("<H", 1) + strength_record())
    output = tmp_path / "dump.csv"
    result = CliRunner().invoke(
        u7_app,
        [
            command,
            str(source),
            "--game",
            game,
            "--static",
            str(tmp_path),
            "--format",
            "csv",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    row = next(csv.DictReader(io.StringIO(output.read_text())))
    assert row["strength"] == expected
