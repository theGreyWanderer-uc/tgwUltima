"""U7 ``--gamedat`` accepts an Exult save, and Exult saves are listed for front ends."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan import _meta
from titan.u7 import gamedat_source
from titan.u7.gamedat_source import u7_gamedat_folder


def _exult_zip(title: str, files: dict[str, bytes], *, prefixed: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.comment = title.encode("latin-1")
        for name, data in files.items():
            archive.writestr(name, data)
    data = buf.getvalue()
    return title.encode("latin-1").ljust(80, b"\0") + data if prefixed else data


FILES = {"identity": b"BLACKGATE", "npc.dat": b"\x01\x02", "map01/u7ireg00": b"x"}


def test_folder_and_none_pass_through(tmp_path: Path) -> None:
    assert u7_gamedat_folder(None) is None
    assert u7_gamedat_folder(str(tmp_path)) == str(tmp_path)


def test_save_unpacks_once_into_a_gamedat_folder(tmp_path: Path) -> None:
    save = tmp_path / "exult00bg.sav"
    save.write_bytes(_exult_zip("Trinsic", FILES))
    cache = tmp_path / "cache"
    folder = Path(u7_gamedat_folder(save, cache_root=cache))
    assert (folder / "identity").read_bytes() == b"BLACKGATE"
    assert (folder / "map01" / "u7ireg00").read_bytes() == b"x"
    (folder / "npc.dat").write_bytes(b"marker")  # a second call reuses the folder
    assert Path(u7_gamedat_folder(save, cache_root=cache)) == folder
    assert (folder / "npc.dat").read_bytes() == b"marker"
    assert [p.name for p in cache.iterdir()] == [folder.name]  # no staging left


def test_non_save_file_is_rejected(tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("not a save")
    with pytest.raises(ValueError, match="Not a U7 save"):
        u7_gamedat_folder(junk, cache_root=tmp_path / "cache")


def test_gamedat_option_unpacks_for_a_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from titan.cli import app
    from titan.u7.cli import npcs

    save = tmp_path / "exult03bg.sav"
    save.write_bytes(_exult_zip("Cove", FILES))
    monkeypatch.setattr(gamedat_source, "gamedat_cache_root", lambda: tmp_path / "c")
    seen = {}
    monkeypatch.setattr(
        npcs, "cmd_monster_report", lambda args: seen.update(vars(args)) or 0
    )
    result = CliRunner().invoke(app, ["u7", "monster-report", "--gamedat", str(save)])
    assert result.exit_code == 0, result.output
    assert (Path(seen["gamedat"]) / "identity").is_file()

    junk = tmp_path / "junk.sav"
    junk.write_bytes(b"nope")
    result = CliRunner().invoke(app, ["u7", "monster-report", "--gamedat", str(junk)])
    assert result.exit_code == 2 and "Not a U7 save" in result.output


def test_exult_saves_are_listed_per_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    (tmp_path / "gamedat").mkdir()
    (tmp_path / "exult00bg.sav").write_bytes(_exult_zip("Trinsic", FILES))
    (tmp_path / "exult12bg.sav").write_bytes(
        _exult_zip("Comment only", FILES, prefixed=False)
    )
    (tmp_path / "exult01si.sav").write_bytes(_exult_zip("Monitor", FILES))
    (tmp_path / "exult02bg.sav").write_bytes(b"damaged")
    config = {
        "u7bg": {"game": {"base": tmp_path.as_posix()}},
        "u7si": {"game": {"base": tmp_path.as_posix()}},
    }
    bg = _meta.list_saves("u7bg", config)
    assert [(s.path.name, s.name) for s in bg] == [
        ("exult00bg.sav", "Trinsic"),
        ("exult02bg.sav", ""),
        ("exult12bg.sav", "Comment only"),
    ]
    assert all(s.slot == str(s.path) for s in bg)
    assert [s.name for s in _meta.list_saves("u7si", config)] == ["Monitor"]


def test_exult_save_folder_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    (game / "gamedat").mkdir(parents=True)
    exult = tmp_path / "Exult" / "blackgate"
    exult.mkdir(parents=True)
    (exult / "exult03bg.sav").write_bytes(_exult_zip("Britain", FILES))
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths",
        lambda g: {"savegame": exult, "gamedat": exult / "gamedat"},
    )
    config = {"u7bg": {"game": {"base": game.as_posix()}}}
    assert [s.name for s in _meta.list_saves("u7bg", config)] == ["Britain"]
