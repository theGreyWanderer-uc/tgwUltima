"""Save listing for front ends: ``titan._meta.list_saves`` and each game's provider."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan import _config, _meta
from titan.u8.install import expand_u8_paths


def _sgheader(names: dict[int, list[str]]) -> bytes:
    records = []
    for slot in range(12):
        lines = names.get(slot, [])
        record = b"".join(
            line.encode("cp437").ljust(26, b"\0")[:26] for line in lines
        ).ljust(104, b"\0")
        records.append(record)
    return b"".join(records)


@pytest.fixture
def u8_config(tmp_path: Path) -> dict:
    saves = tmp_path / "u8" / "cloud_saves" / "SAVEGAME"
    saves.mkdir(parents=True)
    for name in ("U8SAVE.000", "U8SAVE.003", "u8save.005", "U8SAVE.BAK"):
        (saves / name).write_bytes(b"")
    (saves / "SGHEADER.DAT").write_bytes(
        _sgheader({3: ["Before the Necromancer's", "test"], 7: ["No file for this"]})
    )
    return expand_u8_paths(
        {
            "game": {"base": (tmp_path / "u8").as_posix(), "language": "ENGLISH"},
            "paths": {"savegame": "cloud_saves/SAVEGAME"},
        }
    )


def test_u8_lists_slots_with_sgheader_names(u8_config: dict) -> None:
    saves = _meta.list_saves("u8", u8_config)
    assert [s.slot for s in saves] == ["0", "3", "5"]
    assert saves[1].name == "Before the Necromancer's test"
    assert saves[0].name == "" and saves[2].name == ""
    assert saves[2].path.name == "u8save.005"


def test_u8_names_are_dos_code_page_437(tmp_path: Path) -> None:
    from titan.u8.saves import read_save_names

    data = _sgheader({1: ["Français"]})
    assert b"Fran\x87ais" in data  # byte 0x87 is c-cedilla in code page 437
    (tmp_path / "sgheader.dat").write_bytes(data)
    assert read_save_names(tmp_path)[1] == "Français"


def test_u8_slot_round_trips_through_resolve(u8_config: dict) -> None:
    save = _meta.list_saves("u8", u8_config)[1]
    assert _meta.resolve_save("u8", save.slot, u8_config) == save.path


def test_u8_save_browse_accepts_a_slot(
    u8_config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from titan.cli import app
    from titan.u8 import save_browser_ui

    seen = {}
    monkeypatch.setattr(_config, "_config", u8_config)
    monkeypatch.setattr(_config, "load_config", lambda *a, **k: u8_config)
    monkeypatch.setattr(
        save_browser_ui, "run_u8_save_browser", lambda **kw: seen.update(kw) or 0
    )
    result = CliRunner().invoke(app, ["u8", "save-browse", "3", "--compare", "0"])
    assert result.exit_code == 0, result.output
    saves = Path(u8_config["paths"]["savegame"])
    assert seen["source"] == saves / "U8SAVE.003"
    assert seen["compare"] == saves / "U8SAVE.000"


@pytest.mark.parametrize("game", ["u6", "md"])
def test_dos_games_list_their_savegame_folder(tmp_path: Path, game: str) -> None:
    config = {game: {"game": {"base": tmp_path.as_posix()}}}
    assert _meta.list_saves(game, config) == []
    (tmp_path / "SAVEGAME").mkdir()
    assert _meta.list_saves(game, config) == []  # no OBJLIST yet
    (tmp_path / "SAVEGAME" / "OBJLIST").write_bytes(b"")
    (save,) = _meta.list_saves(game, config)
    assert save.path == tmp_path / "SAVEGAME" and save.slot == str(save.path)
    assert _meta.resolve_save(game, save.slot, config) == save.path
    assert _meta.resolve_save(game, None, config) is None


def test_u9_lists_archives_and_keeps_unreadable_ones(tmp_path: Path) -> None:
    saves = tmp_path / "savegame"
    saves.mkdir()
    (saves / "u9game2.sav").write_bytes(b"not a save")
    (saves / "notes.txt").write_text("x")
    config = {"u9": {"game": {"base": tmp_path.as_posix()}}}
    (save,) = _meta.list_saves("u9", config)
    assert save.path.name == "u9game2.sav" and save.name == ""
    assert _meta.resolve_save("u9", save.slot, config) == Path(save.slot)


def test_games_without_a_provider() -> None:
    assert not _meta.has_saves("uo")
    assert _meta.list_saves("uo", {}) == []
    assert _meta.has_saves("u8")
