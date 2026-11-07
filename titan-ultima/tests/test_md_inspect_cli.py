"""MD read-only commands export framed resources and honest unknown-opcode reports."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.md_fixtures import md_game as md_game
from titan.md.cli import md_app
from titan.u6.converse import U6ConverseInstruction, disassemble
from titan.md.references import (
    martian_dialogue_report,
    read_martian_books,
    read_martian_dialogue,
    read_martian_names,
    disassemble_martian_dialogue,
)


def test_md_reference_wrappers_and_non_npc_record(md_game: Path) -> None:
    scripts = read_martian_dialogue(md_game)
    assert len(scripts) == 1 and scripts[0].display_name == "Spector"
    unknown = scripts[0].instructions[-2]
    assert isinstance(unknown, U6ConverseInstruction)
    assert unknown.name == "UNKNOWN_0xce"
    report = martian_dialogue_report(md_game)
    assert report["npc_scripts"] == 1 and report["unknown_opcodes"][0]["item"] == 2
    assert report["unknown_opcodes"][0]["opcode"] == "0xce"
    assert report["unknown_opcodes"][0]["operands"] == []
    assert read_martian_names(md_game).get_name(3) == "canal"
    assert read_martian_books(md_game) == ["Book One\r\n*Page Two", "Sign"]
    with pytest.raises(ValueError, match="not an NPC"):
        read_martian_dialogue(md_game, 0)


@pytest.mark.parametrize(
    "command,extra,expected",
    [
        ("actor-list", ["--actor", "1"], "Avatar"),
        ("gamestate-dump", [], "1895-01-06T08:00"),
        ("converse-dump", ["--item", "2"], "SET_YSTRING"),
        ("converse-report", [], "unknown_opcodes"),
        ("look-dump", ["--tile", "3"], "canal"),
        ("book-dump", ["--book", "0"], "*Page Two"),
    ],
)
def test_md_inspection_output_files(
    md_game: Path, tmp_path: Path, command: str, extra: list[str], expected: str
) -> None:
    output = tmp_path / "exports" / f"{command}.txt"
    result = CliRunner().invoke(
        md_app, [command, "-g", str(md_game), *extra, "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert expected in output.read_text(encoding="utf-8")


def test_actor_names_use_saved_party_name(md_game: Path, tmp_path: Path) -> None:
    from tests.md_fixtures import initial_martian_objlist

    data = initial_martian_objlist()
    data[0xF00:0xF0E] = b"MyAvatar\0".ljust(14, b"\0")
    save = tmp_path / "saved"
    save.mkdir()
    (save / "OBJLIST").write_bytes(data)
    result = CliRunner().invoke(
        md_app,
        ["actor-list", "-g", str(md_game), "--savegame", str(save), "--actor", "1"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["name"] == "MyAvatar"


@pytest.mark.parametrize("flags", [0, 0x20, 0x40, 0x60])
def test_md_gamestate_reports_cistern_and_valves_separately(
    md_game: Path, tmp_path: Path, flags: int
) -> None:
    from tests.md_fixtures import initial_martian_objlist
    from titan.md.actor import MD_ACTOR_LAYOUT

    data = initial_martian_objlist()
    data[MD_ACTOR_LAYOUT.talk_flags + 118] = flags
    save = tmp_path / "saved"
    save.mkdir()
    (save / "OBJLIST").write_bytes(data)
    result = CliRunner().invoke(
        md_app, ["gamestate-dump", "-g", str(md_game), "--savegame", str(save)]
    )
    assert result.exit_code == 0, result.output
    state = json.loads(result.output)
    assert state["cistern_filled"] is bool(flags & 0x20)
    assert state["canal_valves_open"] is bool(flags & 0x40)
    assert state["canals_filled"] is (flags & 0x60 == 0x60)


def test_df_name_is_scoped_to_md_and_preserves_operands_and_offsets() -> None:
    data = b"\xdf\xd3\x03\xa7\xb6"
    shared = disassemble(data)
    martian = disassemble_martian_dialogue(data)
    shared_df, martian_df = shared[0], martian[0]
    assert isinstance(shared_df, U6ConverseInstruction)
    assert isinstance(martian_df, U6ConverseInstruction)
    assert shared_df.name == "UNKNOWN_0xdf"
    assert martian_df.name == "SET_YSTRING"
    assert shared_df.offset == martian_df.offset == 0
    assert shared_df.opcode == martian_df.opcode == 0xDF
    assert shared_df.operands == martian_df.operands
    assert [repr(op) for op in martian_df.operands] == ["3", "EVAL"]


@pytest.mark.parametrize(
    "command,extra",
    [("converse-dump", ["--item", "0"]), ("book-dump", ["--book", "99"])],
)
def test_invalid_md_record_is_reported_cleanly(
    md_game: Path, command: str, extra: list[str]
) -> None:
    result = CliRunner().invoke(md_app, [command, "-g", str(md_game), *extra])
    assert result.exit_code == 1 and "ERROR:" in result.output
    assert "Traceback" not in result.output
