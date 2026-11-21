"""One list of U7 mods and Exult custom games for --mod, pickers and setup."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from titan import _config, _meta
from titan.u7 import install
from titan.u7.cli import u7_app
from titan.u7.cli._common import complete_mod
from titan.u7.mods import configured_u7_mods, discover_u7_mods, find_u7_mod


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A BG install with three mods, an Exult profile and an Exult custom game."""
    base = tmp_path / "ULTIMA7"
    (base / "STATIC").mkdir(parents=True)
    mods = base / "mods"
    profile = tmp_path / "Exult"
    # Described, played in Exult's profile, saves in a subfolder.
    (mods / "Keyring" / "data").mkdir(parents=True)
    (mods / "Keyring" / "data" / "initgame.dat").write_bytes(b"zip")
    (mods / "Keyring.cfg").write_text(
        "<mod_info><display_string>BLACK GATE\nKEYRING</display_string>"
        "<patch>__MOD_PATH__/data</patch>"
        "<savegame_path>__MOD_PATH__/saves</savegame_path></mod_info>"
    )
    live = profile / "blackgate" / "mods" / "Keyring"
    (live / "gamedat").mkdir(parents=True)
    (live / "gamedat" / "npc.dat").touch()
    (live / "saves").mkdir()
    (live / "saves" / "exult00bg.sav").write_bytes(b"save")
    # Described, never played.
    (mods / "islefaq" / "patch").mkdir(parents=True)
    (mods / "islefaq.cfg").write_text(
        "<mod_info><display_string>SourceForge Island</display_string></mod_info>"
    )
    # A bare folder.
    (mods / "plain" / "patch").mkdir(parents=True)
    # An Exult custom game.
    custom = profile / "mygame"
    (custom / "patch").mkdir(parents=True)
    (custom / "static").mkdir()
    (custom / "gamedat").mkdir()
    (custom / "gamedat" / "npc.dat").touch()
    (custom / "exult00dev.sav").write_bytes(b"save")
    cfg = profile / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><blackgate><path>{base}</path></blackgate>"
        f"<mygame><path>{custom}</path><title>My\nGame</title></mygame>"
        "</game></disk></config>"
    )
    monkeypatch.setattr(install, "find_exult_cfg", lambda: cfg)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = {"u7bg": {"game": {"base": base.as_posix()}}}
    monkeypatch.setattr(_config, "_config", config)
    return SimpleNamespace(
        base=base, mods=mods, profile=profile, live=live, custom=custom, config=config
    )


def _by_key(config: dict) -> dict:
    return {mod.key: mod for mod in configured_u7_mods(config, "u7bg")}


def test_mods_are_found_from_descriptions_folders_and_exult(world) -> None:
    mods = _by_key(world.config)
    assert set(mods) == {"Keyring", "islefaq", "plain", "mygame"}
    keyring = mods["Keyring"]
    assert keyring.title == "BLACK GATE KEYRING"
    assert keyring.label == "BLACK GATE KEYRING (Keyring)"
    assert keyring.install_dir == world.mods / "Keyring"
    assert keyring.profile_dir == world.live
    assert keyring.patch == world.mods / "Keyring" / "data"
    assert keyring.gamedat == world.live / "gamedat" and keyring.played
    assert keyring.saves == world.live / "saves"
    assert keyring.archive == world.mods / "Keyring" / "data" / "initgame.dat"
    assert not mods["islefaq"].played
    assert mods["plain"].label == "plain"
    game = mods["mygame"]
    assert game.kind == "exult-game" and game.played
    assert game.label == "My Game (mygame, Exult game)"
    assert game.static == world.custom / "static"


def test_configured_paths_win_and_missing_ones_are_reported(world) -> None:
    world.config["u7bg"]["mods"] = {
        "islefaq": {"paths": {"gamedat": "C:/no/such/gamedat", "saves": "elsewhere"}},
        "Extra": {"paths": {"archive": "mods/extra/initgame.dat"}},
    }
    mods = _by_key(world.config)
    islefaq = mods["islefaq"]
    assert islefaq.gamedat == Path("C:/no/such/gamedat")
    assert islefaq.saves == world.base / "elsewhere"
    assert islefaq.problems == {"gamedat": "NOT FOUND", "saves": "NOT FOUND"}
    assert islefaq.configured == {"gamedat", "saves"}
    # A table with no mod on disk is still listed, with its problems.
    assert mods["Extra"].problems == {"archive": "NOT FOUND"}
    assert mods["Extra"].patch is None


def test_a_table_naming_a_mods_patch_folder_joins_that_mod(world) -> None:
    patch = (world.mods / "islefaq" / "patch").as_posix()
    world.config["u7bg"]["mods"] = {"My Isle": {"paths": {"patch": patch}}}
    mods = _by_key(world.config)
    assert "islefaq" not in mods
    assert mods["My Isle"].title == "SourceForge Island"
    assert mods["My Isle"].label == "SourceForge Island (My Isle)"


def test_mod_lookup_is_exact_then_case_insensitive(world) -> None:
    mods = configured_u7_mods(world.config, "u7bg")
    assert find_u7_mod(mods, "keyring").key == "Keyring"
    assert find_u7_mod(mods, "nope") is None
    gamedat = str(world.live / "gamedat")
    assert install.resolve_u7_mod_gamedat("bg", "KEYRING") == gamedat
    assert install.resolve_u7_mod_gamedat("bg", "islefaq") is None
    assert install.resolve_u7_mod_gamedat("bg", "mygame") == str(
        world.custom / "gamedat"
    )
    assert install.resolve_u7_mod_archive("bg", "Keyring").endswith("initgame.dat")


def test_without_exult_settings_mods_keep_state_in_their_own_folder(
    tmp_path: Path,
) -> None:
    mods = tmp_path / "mods"
    (mods / "pagan" / "patch").mkdir(parents=True)
    (mods / "pagan.cfg").write_text("<modinfo/>")
    (found,) = discover_u7_mods("SI", {"u7si": {"game": {"base": str(tmp_path)}}})
    assert found.profile_dir is None
    assert found.gamedat == mods / "pagan" / "gamedat"
    assert found.saves == mods / "pagan"


def test_setup_writes_mods_under_the_install(world) -> None:
    sources = install.discover_u7_mod_sources(
        world.base.as_posix(), "blackgate", world.profile
    )
    assert [item["name"] for item in sources] == ["Keyring"]
    assert sources[0] == {
        "name": "Keyring",
        "root": world.live.as_posix(),
        "gamedat": (world.live / "gamedat").as_posix(),
        "saves": (world.live / "saves").as_posix(),
        "archive": (world.mods / "Keyring" / "data" / "initgame.dat").as_posix(),
    }


def test_list_mods_and_mod_saves_for_front_ends(world) -> None:
    infos = {info.key: info for info in _meta.list_mods("u7bg")}
    assert infos["Keyring"].paths["gamedat"] == world.live / "gamedat"
    assert infos["Keyring"].played and infos["mygame"].kind == "exult-game"
    assert "static" not in infos["Keyring"].paths
    assert _meta.has_mods("u7si") and not _meta.has_mods("u8")
    assert _meta.list_mods("u8") == []
    assert [s.path.name for s in _meta.list_saves("u7bg", mod="Keyring")] == [
        "exult00bg.sav"
    ]
    assert [s.path.name for s in _meta.list_saves("u7bg", mod="mygame")] == [
        "exult00dev.sav"
    ]
    assert _meta.list_saves("u7bg", mod="nope") == []
    assert _meta.list_saves("u8", mod="Keyring") == []


def test_mod_options_are_tagged_and_complete(world) -> None:
    for path in (("u7", "monster-report"), ("u7", "gamedat-info")):
        assert _meta.command_meta(*path).params["mod"] == "mod"
    ctx = SimpleNamespace(params={"game": "bg"})
    assert complete_mod(ctx, "") == ["Keyring", "mygame", "plain", "islefaq"]
    assert complete_mod(ctx, "k") == ["Keyring"]


def test_mods_command_lists_keys_and_paths(world) -> None:
    runner = CliRunner()
    text = runner.invoke(u7_app, ["mods", "--game", "bg"])
    assert text.exit_code == 0
    lines = text.output.splitlines()
    assert lines[0] == "BG mods and Exult games (pass the key to --mod):"
    assert any(line.split()[:3] == ["Keyring", "mod", "played"] for line in lines[1:])
    assert any("islefaq" in line and "not played" in line for line in lines)
    rows = json.loads(runner.invoke(u7_app, ["mods", "--format", "json"]).output)
    keyring = next(row for row in rows if row["key"] == "Keyring")
    assert keyring["gamedat"] == str(world.live / "gamedat")
    assert keyring["kind"] == "mod" and keyring["problems"] == {}
