"""titan's shared working-data folder (``_config.data_dir``) and U8 working folders."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from titan import _config, cli
from titan.flex import FlexArchive
from titan.u8.install import u8_working_dir_for_archive


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.delenv(_config.DATA_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(_config, "_config", {})
    return tmp_path


def _u8_config(
    root: Path, paths: str = 'shapes = "shapes/"\nglobs = "globs/"\n'
) -> Path:
    base = root / "Ultima8"
    (base / "ENGLISH" / "STATIC").mkdir(parents=True, exist_ok=True)
    toml = root / "titan.toml"
    toml.write_text(
        f'[u8.game]\nbase = "{base.as_posix()}"\n[u8.paths]\nfixed = "FIXED.DAT"\n'
        f'u8shapes = "U8SHAPES.FLX"\n{paths}',
        encoding="utf-8",
    )
    return toml


def _fill(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "0001.shp").write_bytes(b"x")


def test_data_dir_per_platform_and_override(workspace, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert _config.data_dir() == workspace / "local" / "Titan"
    assert _config.data_dir("u8") == workspace / "local" / "Titan" / "u8"
    monkeypatch.setattr(sys, "platform", "linux")
    assert _config.data_dir("u8") == workspace / "xdg" / "titan" / "u8"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert _config.data_dir() == Path.home() / ".local" / "share" / "titan"
    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "elsewhere"))
    assert _config.data_dir("u8") == workspace / "elsewhere" / "u8"


def test_relative_working_dirs_resolve_in_the_data_folder(workspace, monkeypatch):
    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    absolute = workspace / "mine" / "globs"
    toml = _u8_config(
        workspace, f'shapes = "shapes/"\nglobs = "{absolute.as_posix()}"\n'
    )
    config = _config.load_config(str(toml))
    assert Path(config["u8"]["paths"]["shapes"]) == workspace / "data" / "u8" / "shapes"
    assert Path(config["u8"]["paths"]["globs"]) == absolute


def test_configured_u8_without_working_dirs_gets_the_defaults(workspace, monkeypatch):
    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    config = _config.load_config(str(_u8_config(workspace, paths="")))
    for key in ("shapes", "globs"):
        assert Path(config["u8"]["paths"][key]) == workspace / "data" / "u8" / key


def test_current_folder_extraction_is_not_read(workspace, monkeypatch, capsys):
    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    _fill(Path.cwd() / "shapes")  # where titan used to resolve shapes/
    toml = _u8_config(workspace)
    config = _config.load_config(str(toml))
    assert Path(config["u8"]["paths"]["shapes"]) == workspace / "data" / "u8" / "shapes"
    assert cli.cmd_config(SimpleNamespace(config=str(toml), edit=False)) == 0
    report = capsys.readouterr().out
    assert f"Data folder:   {workspace / 'data'}" in report
    line = next(x for x in report.splitlines() if x.strip().startswith("shapes"))
    assert "not extracted yet" in line


def _flex(path: Path) -> Path:
    archive = FlexArchive()
    archive.records = [b"first", b"", b"last"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(archive.to_bytes())
    return path


def test_flex_extract_sends_u8_working_archives_to_the_data_folder(
    workspace, monkeypatch
):
    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    toml = _u8_config(workspace)
    config = _config.load_config(str(toml))
    static = workspace / "Ultima8" / "ENGLISH" / "STATIC"
    shapes = _flex(static / "U8SHAPES.FLX")
    globs = _flex(static / "GLOB.FLX")
    music = _flex(static / "MUSIC.FLX")
    elsewhere = _flex(workspace / "copy" / "U8SHAPES.FLX")
    data = workspace / "data" / "u8"
    assert u8_working_dir_for_archive(shapes, config) == data / "shapes"
    assert u8_working_dir_for_archive(globs, config) == data / "globs"
    assert u8_working_dir_for_archive(music, config) is None
    assert u8_working_dir_for_archive(elsewhere, config) is None  # not the install's

    assert cli.cmd_flex_extract(SimpleNamespace(file=str(shapes), output=None)) == 0
    assert any((data / "shapes").iterdir())
    assert cli.cmd_flex_extract(SimpleNamespace(file=str(music), output=None)) == 0
    assert (Path.cwd() / "MUSIC").is_dir()  # exports stay in the current folder
    explicit = workspace / "out"
    assert (
        cli.cmd_flex_extract(SimpleNamespace(file=str(globs), output=str(explicit)))
        == 0
    )
    assert explicit.is_dir() and not (data / "globs").exists()


def test_flex_extract_without_u8_config_keeps_the_current_folder(workspace):
    shapes = _flex(workspace / "U8SHAPES.FLX")
    assert cli.cmd_flex_extract(SimpleNamespace(file=str(shapes), output=None)) == 0
    assert (Path.cwd() / "U8SHAPES").is_dir()


def test_working_archives_come_from_the_install(workspace, monkeypatch):
    from titan.u8.install import u8_working_archive

    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    config = _config.load_config(str(_u8_config(workspace)))
    static = workspace / "Ultima8" / "ENGLISH" / "STATIC"
    assert u8_working_archive("shapes", config) is None  # not there yet
    shapes = _flex(static / "U8SHAPES.FLX")
    glob = _flex(static / "GLOB.FLX")
    assert u8_working_archive("shapes", config) == shapes
    # No glob key in older configs: GLOB.FLX is found beside U8SHAPES.FLX.
    assert u8_working_archive("globs", config) == glob
    assert u8_working_archive("music", config) is None
    toml = _u8_config(workspace, f'glob = "{(workspace / "my.flx").as_posix()}"\n')
    assert u8_working_archive("globs", _config.load_config(str(toml))) is None


def test_map_commands_extract_into_the_data_folder_without_asking(
    workspace, monkeypatch
):
    from titan.u8.cli import maps

    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("prompted"))
    config = _config.load_config(str(_u8_config(workspace)))
    static = workspace / "Ultima8" / "ENGLISH" / "STATIC"
    _flex(static / "U8SHAPES.FLX")
    _flex(static / "GLOB.FLX")
    for key, ext, name in (
        ("shapes", ".shp", "U8SHAPES.FLX"),
        ("globs", ".dat", "GLOB.FLX"),
    ):
        folder = config["u8"]["paths"][key]
        assert maps._ensure_asset_dir(folder, ext, key, name, key)
        assert sorted(p.suffix for p in Path(folder).iterdir() if p.suffix == ext)
    # A folder of the user's own is only filled after a yes.
    answers = iter(["n"])
    monkeypatch.setattr("titan._wizard_ui.choice", lambda *a, **k: next(answers))
    mine = workspace / "mine" / "shapes"
    assert not maps._ensure_asset_dir(
        str(mine), ".shp", "Shapes", "U8SHAPES.FLX", "shapes"
    )
    assert not mine.exists()


def test_setup_prepares_u8_map_data_in_the_working_folders(workspace, monkeypatch):
    from titan.u8.install import has_working_files, prepare_working_dirs

    monkeypatch.setenv(_config.DATA_ENV, str(workspace / "data"))
    config = _config.load_config(str(_u8_config(workspace)))
    static = workspace / "Ultima8" / "ENGLISH" / "STATIC"
    assert prepare_working_dirs(config) == []  # no archives yet: nothing to do
    _flex(static / "U8SHAPES.FLX")
    _flex(static / "GLOB.FLX")
    data = workspace / "data" / "u8"
    done = prepare_working_dirs(config)
    assert [(name, folder, count) for name, folder, count in done] == [
        ("shapes", data / "shapes", 2),
        ("globs", data / "globs", 2),
    ]
    assert has_working_files(data / "shapes", "shapes") and has_working_files(
        data / "globs", "globs"
    )
    assert prepare_working_dirs(config) == []  # already extracted: left alone
