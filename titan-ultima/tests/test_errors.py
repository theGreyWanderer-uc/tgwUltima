"""titan's error categories, exit codes, default export folder and run results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan import _config, _results, cli
from titan.errors import (
    EXIT_CODES,
    ConfigError,
    ConfigFileError,
    InstallNotFoundError,
    InvalidDataError,
    TitanError,
    UnsupportedError,
    exit_code,
)
from titan.flex import FlexArchive


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TITAN_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(_config, "explicit_config_path", None)
    monkeypatch.setattr(_config, "_config", {})
    monkeypatch.setattr(_config, "find_config", lambda: None)
    return tmp_path


def test_categories_keep_the_builtin_types_callers_catch() -> None:
    assert issubclass(InvalidDataError, ValueError)
    assert issubclass(InstallNotFoundError, FileNotFoundError)
    assert issubclass(InstallNotFoundError, ConfigError)
    assert issubclass(ConfigFileError, ValueError)
    for category in (ConfigError, InvalidDataError, UnsupportedError):
        assert issubclass(category, TitanError)


def test_exit_codes() -> None:
    assert exit_code(InstallNotFoundError("x")) == EXIT_CODES["config"] == 78
    assert exit_code(InvalidDataError("x")) == EXIT_CODES["invalid-data"] == 65
    assert exit_code(UnsupportedError("x")) == EXIT_CODES["unsupported"] == 69
    assert exit_code(TitanError("x")) == EXIT_CODES["error"] == 1
    assert exit_code(FileNotFoundError("x")) == EXIT_CODES["file-not-found"] == 66
    assert exit_code(PermissionError("x")) == EXIT_CODES["io"] == 74
    assert exit_code(ValueError("x")) == 1
    assert len(set(EXIT_CODES.values())) == len(EXIT_CODES)


def test_game_errors_sit_under_the_categories() -> None:
    from titan.u6.palette import U6PaletteError
    from titan.u9.flx_archive import U9FlxArchiveError
    from titan.u9.flx_writer import U9FlxWriteError
    from titan.u9.preview import PreviewUnavailableError
    from titan.uw2.gr import UW2GRError

    assert issubclass(U6PaletteError, InvalidDataError)
    assert issubclass(U9FlxArchiveError, InvalidDataError)
    assert issubclass(UW2GRError, InvalidDataError)
    assert issubclass(U9FlxWriteError, TitanError)
    assert not issubclass(U9FlxWriteError, InvalidDataError)
    assert exit_code(PreviewUnavailableError("no pyvista")) == 69


def test_every_titan_error_class_derives_from_titan_errors() -> None:
    import re

    src = Path(cli.__file__).parent
    allowed = {"_Cancelled", "PromptCancelled", "FoldRunError"}
    for path in src.rglob("*.py"):
        if "third_party" in path.parts:
            continue
        for name, bases in re.findall(
            r"^class (\w+Error)\(([^)]*)\):", path.read_text(encoding="utf-8"), re.M
        ):
            if name in allowed or path.name == "errors.py":
                continue
            assert "Exception" not in bases.split(", "), (path.name, name)
            assert bases != "ValueError", (path.name, name)


def test_missing_install_is_a_config_error_with_a_hint(isolated: Path) -> None:
    result = CliRunner().invoke(cli.app, ["u6", "actor-list"])
    assert result.exit_code == 78, result.output
    assert "ERROR: No U6 game directory found" in result.output
    assert "titan setup" in result.output
    assert "Traceback" not in result.output


def test_invalid_titan_toml_is_reported_not_raised(isolated: Path) -> None:
    bad = isolated / "bad.toml"
    bad.write_text("[u6.game\nbase = 1\n", encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["-c", str(bad), "config"])
    assert result.exit_code == 78, result.output
    assert "is not valid TOML" in result.output


def test_main_exits_70_for_a_bug(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def broken() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "app", broken)
    assert cli.main() == 70
    assert "RuntimeError: boom" in capsys.readouterr().err


def test_export_dir_follows_titan_data(isolated: Path) -> None:
    assert (
        _config.export_dir("u8", "map-browse")
        == isolated / "data/u8/exports/map-browse"
    )
    assert _config.export_dir("uo") == isolated / "data/uo/exports"


def test_browser_defaults_resolve_when_the_command_runs(isolated: Path) -> None:
    import inspect

    from titan.u8.map_browser_ui import map_browse_cmd

    assert inspect.signature(map_browse_cmd).parameters["output"].default is None


def test_results_file_lists_what_a_command_wrote(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = FlexArchive()
    archive.records = [b"one", b"two"]
    source = isolated / "TEST.FLX"
    archive.save(str(source))
    results = isolated / "results.json"
    monkeypatch.setenv(_results.RESULTS_ENV, str(results))
    out = isolated / "out"
    result = CliRunner().invoke(cli.app, ["flex-extract", str(source), "-o", str(out)])
    assert result.exit_code == 0, result.output
    document = json.loads(results.read_text(encoding="utf-8"))
    assert document == {"outputs": [out.absolute().as_posix()], "exit_code": 0}


def test_results_file_records_a_failed_run(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = isolated / "results.json"
    monkeypatch.setenv(_results.RESULTS_ENV, str(results))
    result = CliRunner().invoke(cli.app, ["u6", "actor-list"])
    assert result.exit_code == 78
    assert json.loads(results.read_text(encoding="utf-8")) == {
        "outputs": [],
        "exit_code": 78,
    }
