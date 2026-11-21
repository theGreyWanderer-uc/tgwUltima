"""The PyPI update check in ``titan._version``; never touches the network."""

from __future__ import annotations

import json
from importlib import metadata
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from titan import _version, cli


@pytest.fixture
def pypi(tmp_path, monkeypatch):
    """Isolate the cache and count calls to a fake PyPI."""
    monkeypatch.delenv(_version.NO_UPDATE_CHECK_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    state = SimpleNamespace(answer="9.9.9", calls=0, now=1_000_000.0)

    def fetch(timeout):
        state.calls += 1
        if isinstance(state.answer, Exception):
            raise state.answer
        return state.answer

    monkeypatch.setattr(_version, "_fetch_latest", fetch)
    monkeypatch.setattr("time.time", lambda: state.now)
    return state


def test_opt_out_never_asks_pypi(pypi, monkeypatch):
    monkeypatch.setenv(_version.NO_UPDATE_CHECK_ENV, "1")
    assert _version.latest_release() is None
    assert pypi.calls == 0


def test_answer_is_cached_for_max_age(pypi):
    assert _version.latest_release() == "9.9.9"
    pypi.answer = "10.0.0"
    pypi.now += 3600
    assert _version.latest_release() == "9.9.9"  # cached
    assert pypi.calls == 1
    pypi.now += 86400
    assert _version.latest_release() == "10.0.0"
    assert pypi.calls == 2
    assert json.loads(_version._cache_file().read_text())["version"] == "10.0.0"


def test_offline_returns_last_known_and_backs_off(pypi):
    pypi.answer = OSError("offline")
    assert _version.latest_release() is None  # nothing known yet
    assert _version.latest_release() is None
    assert pypi.calls == 1  # failure remembered: no second wait
    pypi.answer = "9.9.9"
    pypi.now += 3601
    assert _version.latest_release() == "9.9.9"
    pypi.answer = TimeoutError()
    pypi.now += 2 * 86400
    assert _version.latest_release() == "9.9.9"  # stale but known


def test_broken_cache_and_bad_answers_never_raise(pypi):
    path = _version._cache_file()
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert _version.latest_release() == "9.9.9"
    pypi.answer = KeyError("info")
    pypi.now += 2 * 86400
    assert _version.latest_release() == "9.9.9"


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.8.1", "0.8.0", True),
        ("0.10.0", "0.9.9", True),
        ("0.8.0", "0.8.0", False),
        ("0.8", "0.8.0", False),
        ("0.7.9", "0.8.0", False),
        ("0.9.0rc1", "0.8.0", False),  # pre-releases aren't offered
        (None, "0.8.0", False),
    ],
)
def test_is_newer(latest, current, expected):
    assert _version.is_newer(latest, current) is expected


def _dist(direct_url):
    return SimpleNamespace(read_text=lambda name: direct_url)


@pytest.mark.parametrize(
    "dist,expected",
    [
        (_dist('{"url": "file:///src", "dir_info": {"editable": true}}'), True),
        (_dist(None), False),  # installed from a wheel or PyPI
        (_dist('{"url": "file:///x.whl", "archive_info": {}}'), False),
    ],
)
def test_is_dev_build(monkeypatch, dist, expected):
    monkeypatch.setattr(metadata, "distribution", lambda name: dist)
    assert _version.is_dev_build() is expected


def test_is_dev_build_from_a_bare_source_tree(monkeypatch):
    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", missing)
    assert _version.is_dev_build()


@pytest.mark.parametrize(
    "dev,latest,expected,unexpected",
    [
        (False, "9.9.9", "A newer release is available: 9.9.9", "development"),
        (True, "9.9.9", "Newer release on PyPI: 9.9.9", "pip install"),
        (False, _version.__version__, "", "newer"),
        (False, None, "", "newer"),
    ],
)
def test_version_option_mentions_only_newer_releases(
    monkeypatch, dev, latest, expected, unexpected
):
    monkeypatch.setattr(_version, "is_dev_build", lambda: dev)
    monkeypatch.setattr(_version, "latest_release", lambda **_: latest)
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith(f"TITAN v{_version.__version__}")
    assert expected in result.output
    assert unexpected not in result.output.lower()


def test_ordinary_commands_never_check(monkeypatch):
    monkeypatch.delenv(_version.NO_UPDATE_CHECK_ENV, raising=False)
    monkeypatch.setattr(
        _version, "latest_release", lambda **_: pytest.fail("checked for updates")
    )
    assert CliRunner().invoke(cli.app, ["--help"]).exit_code == 0
