"""The user config location is owned by titan and shared with front ends."""

from __future__ import annotations

from pathlib import Path

import pytest

from titan import _config


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)
    return home


def test_user_config_path_windows(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert _config.user_config_path() == tmp_path / "roaming" / "titan" / "config.toml"


def test_user_config_path_windows_without_appdata(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_config.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    assert _config.user_config_path() == fake_home / ".config" / "titan" / "config.toml"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_user_config_path_posix(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(_config.sys, "platform", platform)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert _config.user_config_path() == fake_home / ".config" / "titan" / "config.toml"


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_find_config_finds_user_config_path(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(_config.sys, "platform", platform)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    target = _config.user_config_path()
    assert target in _config.config_search_paths()
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    assert _config.find_config() == target


def test_cwd_config_wins(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    user = _config.user_config_path()
    user.parent.mkdir(parents=True)
    user.write_text("", encoding="utf-8")
    local = tmp_path / "titan.toml"
    local.write_text("", encoding="utf-8")
    assert _config.find_config() == local


def test_search_paths_have_no_duplicates(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_config.sys, "platform", "linux")
    paths = _config.config_search_paths()
    assert len(paths) == len(set(paths))
