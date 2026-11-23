"""Config drift: shadowing copies, entries an old setup wrote, paths that don't resolve."""

from __future__ import annotations

from pathlib import Path

import pytest

from titan import _config
from titan._config_health import config_report, fix_config, shadowing_config

MAIN = '[u8.game]\nbase = "{base}"\n[u8.paths]\nfixed = "FIXED.DAT"\nsavegame = "cloud_saves/SAVEGAME"\n'
OLD_SAVE = 'nonfixed = "U8SAVE.000"\n'


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A home folder (the current folder), a user config folder, and a U8 install."""
    home, appdata = tmp_path / "home", tmp_path / "appdata"
    home.mkdir()
    base = tmp_path / "ULTIMA8"
    (base / "ENGLISH" / "STATIC").mkdir(parents=True)
    (base / "ENGLISH" / "STATIC" / "FIXED.DAT").write_bytes(b"")
    (base / "cloud_saves" / "SAVEGAME").mkdir(parents=True)
    monkeypatch.chdir(home)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv(_config.DATA_ENV, str(tmp_path / "data"))
    user = _config.user_config_path()
    user.parent.mkdir(parents=True)
    user.write_text(MAIN.format(base=base.as_posix()), encoding="utf-8")
    return {"home": home, "user": user, "base": base}


def _kinds(issues):
    return [(issue.kind, issue.action) for issue in issues]


def test_a_clean_main_config_has_no_issues(folders) -> None:
    assert shadowing_config() is None
    assert config_report() == []


def test_an_old_copy_in_the_current_folder_shadows_the_main_config(folders) -> None:
    stray = folders["home"] / "titan.toml"
    stray.write_text(
        MAIN.format(base=folders["base"].as_posix()) + OLD_SAVE, encoding="utf-8"
    )
    assert shadowing_config() == stray
    issues = config_report()
    assert _kinds(issues) == [("shadowed", "retire"), ("stale", "prune")]
    assert all(issue.file == stray for issue in issues)
    assert config_report(str(folders["user"])) == []  # --config: nothing shadows it

    done = fix_config(issues)
    assert done == [f"Renamed {stray} to titan.toml.old"]  # set aside, not edited first
    assert not stray.exists() and (folders["home"] / "titan.toml.old").is_file()
    assert config_report() == []


def test_an_old_setups_save_line_is_removed_with_a_backup(folders) -> None:
    user = folders["user"]
    user.write_text(
        user.read_text(encoding="utf-8") + "# kept comment\n" + OLD_SAVE,
        encoding="utf-8",
    )
    issues = config_report()
    assert _kinds(issues) == [
        ("stale", "prune")
    ]  # its missing path isn't reported twice
    done = fix_config(issues)
    assert len(done) == 1 and "backup: config.toml.bak" in done[0]
    text = user.read_text(encoding="utf-8")
    assert "nonfixed" not in text and "# kept comment" in text  # only that line goes
    assert OLD_SAVE in (user.parent / "config.toml.bak").read_text(encoding="utf-8")
    assert config_report() == []


def test_a_real_old_save_is_not_stale(folders) -> None:
    user = folders["user"]
    (folders["base"] / "cloud_saves" / "SAVEGAME" / "U8SAVE.000").write_bytes(b"")
    user.write_text(user.read_text(encoding="utf-8") + OLD_SAVE, encoding="utf-8")
    assert config_report() == []


def test_the_original_u8_layout_is_moved_under_u8(folders) -> None:
    user = folders["user"]
    user.write_text(
        f'[game]\nbase = "{folders["base"].as_posix()}"\n[paths]\nfixed = "FIXED.DAT"\n',
        encoding="utf-8",
    )
    issues = config_report()
    assert ("stale", "migrate") in _kinds(issues)
    fix_config(issues)
    assert "[u8.game]" in user.read_text(encoding="utf-8")
    assert not [i for i in config_report() if i.kind == "stale"]


def test_missing_paths_are_reported_for_setup(folders) -> None:
    (folders["base"] / "ENGLISH" / "STATIC" / "FIXED.DAT").unlink()
    issues = config_report()
    assert ("path", "setup") in _kinds(issues)
    assert not [
        i for i in issues if i.fixable
    ]  # titan setup's job, not an automatic fix
    assert fix_config(issues) == []


def test_unextracted_u8_map_data_is_extracted_by_the_fix(folders) -> None:
    from titan.flex import FlexArchive

    archive = FlexArchive()
    archive.records = [b"one", b"two"]
    static = folders["base"] / "ENGLISH" / "STATIC"
    for name in ("U8SHAPES.FLX", "GLOB.FLX"):
        (static / name).write_bytes(archive.to_bytes())
    user = folders["user"]
    user.write_text(
        user.read_text(encoding="utf-8")
        + 'u8shapes = "U8SHAPES.FLX"\nshapes = "shapes/"\nglobs = "globs/"\n',
        encoding="utf-8",
    )
    issues = config_report()
    assert sorted(i.key for i in issues) == [
        "path:u8:globs:extract",
        "path:u8:shapes:extract",
    ]
    assert all(i.severity == "info" and i.fixable for i in issues)
    done = fix_config(issues)
    assert len(done) == 1 and "Extracted U8 shapes: 2 files" in done[0]
    assert config_report() == []
