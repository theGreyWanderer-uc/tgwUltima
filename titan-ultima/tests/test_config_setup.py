"""Regression coverage for setup discovery, config preservation, and inspection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from titan import _config, cli
from titan._setup_config import write_setup_config

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@pytest.fixture
def setup_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate discovery from real installs and the user's existing config."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(_config, "explicit_config_path", None)
    monkeypatch.setattr(_config, "_config", {})
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    for method_name in ("exists", "is_dir", "is_file"):
        original = getattr(Path, method_name)

        def confined(path, original=original):
            return original(path) if path.absolute().is_relative_to(tmp_path) else False

        monkeypatch.setattr(Path, method_name, confined)
    return tmp_path


def _answer_setup(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, str] | None = None
) -> None:
    answers = answers or {}

    def answer(prompt: str) -> str:
        if prompt.startswith("\nExtract shapes/"):
            return "n"
        for prefix, value in answers.items():
            if prompt.startswith(prefix):
                return value
        return ""

    monkeypatch.setattr("builtins.input", answer)


def test_setup_preserves_custom_settings_and_backs_up_original(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = Path.cwd() / "titan.toml"
    original = (
        "# Custom config comments must survive in the backup.\n"
        '[u8.game]\nbase="custom-u8"\nlanguage="FRENCH"\n'
        '[u8.paths]\nfixed="CUSTOM.DAT"\n'
        '[uw2.game]\nbase="custom-uw2"\n'
        '[u9.game]\nbase="custom-u9"\n'
        '[u7si.mods."My Mod".paths]\narchive="custom-initgame.dat"\n'
        "[custom]\nvalues=[1,2]\ndate=2024-01-01\n"
    ).encode()
    path.write_bytes(original)
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    old = tomllib.loads(original.decode())
    assert saved["u8"]["game"] == old["u8"]["game"]
    assert saved["u8"]["paths"]["fixed"] == "CUSTOM.DAT"
    assert saved["u8"]["paths"]["palette"] == "U8PAL.PAL"
    assert Path(saved["u8"]["paths"]["usecode"]) == (
        Path("custom-u8") / "FRENCH" / "USECODE" / "EUSECODE.FLX"
    )
    for section in ("uw2", "u9", "u7si", "custom"):
        assert saved[section] == old[section]
    assert path.with_name("titan.toml.bak").read_bytes() == original


def test_setup_keeps_legacy_u8_config_without_adding_overriding_defaults(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = Path.cwd() / "titan.toml"
    path.write_text('[game]\nbase="legacy"\n[paths]\nfixed="CUSTOM.DAT"\n')
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = tomllib.loads(path.read_text())
    assert "u8" not in saved
    assert saved["paths"]["fixed"] == "CUSTOM.DAT"


def test_setup_honors_global_config_and_creates_parent_directories(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd_path = Path.cwd() / "titan.toml"
    original = '[u9.game]\nbase="leave-this-file-alone"\n'
    cwd_path.write_text(original)
    target = setup_workspace / "new" / "nested" / "config.toml"
    _answer_setup(monkeypatch)

    result = CliRunner().invoke(cli.app, ["--config", str(target), "setup"])

    assert result.exit_code == 0, result.output
    assert "u8" in tomllib.loads(target.read_text())
    assert cwd_path.read_text() == original


def test_setup_updates_explicit_existing_config_only(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = setup_workspace / "config.toml"
    original = '[uw2.game]\nbase="custom-uw2"\n'
    target.write_text(original)
    _answer_setup(monkeypatch)

    result = CliRunner().invoke(cli.app, ["-c", str(target), "setup"])

    assert result.exit_code == 0, result.output
    saved = tomllib.loads(target.read_text())
    assert saved["uw2"]["game"]["base"] == "custom-uw2"
    assert "u8" in saved
    assert target.with_name("config.toml.bak").read_text() == original
    assert not (Path.cwd() / "titan.toml").exists()


def test_setup_detects_flat_u8_install(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = setup_workspace / "home" / "GOG Games" / "Ultima 8"
    install.mkdir(parents=True)
    (install / "FIXED.DAT").touch()
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = _config.load_config(str(Path.cwd() / "titan.toml"))
    assert saved["u8"]["game"]["base"] == install.as_posix()
    assert saved["u8"]["game"]["language"] == ""
    fixed = _config.cfg("fixed")
    assert fixed is not None
    assert Path(fixed) == install / "FIXED.DAT"


@pytest.mark.parametrize(
    ("name", "detected"),
    [
        ("Ultima VII - Complete", True),
        ("UltimaVII", True),
        ("Ultima VII - Serpent Isle", True),
        ("Ultima VIII", False),
        ("UltimaVIII", False),
        ("Ultima 9", False),
    ],
)
def test_setup_recognizes_roman_u7_names_without_matching_u8(
    setup_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    detected: bool,
) -> None:
    install = setup_workspace / "home" / "Games" / "Heroic" / name
    (install / "STATIC").mkdir(parents=True)
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = _config.load_config(str(Path.cwd() / "titan.toml"))
    section = "u7si" if "Serpent" in name else "u7bg"
    assert (section in saved) == detected
    if detected:
        assert saved[section]["game"]["base"] == install.as_posix()


@pytest.mark.parametrize("section", ["u7bg", "u7si"])
def test_config_inspects_u7_paths_from_game_base_and_absolute_mod_paths(
    setup_workspace: Path, capsys: pytest.CaptureFixture[str], section: str
) -> None:
    base = setup_workspace / "install"
    (base / "STATIC").mkdir(parents=True)
    (base / "STATIC" / "PALETTES.FLX").touch()
    archive = base / "mods" / "Test Mod" / "initgame.dat"
    archive.parent.mkdir(parents=True)
    archive.touch()
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[{section}.game]\nbase="{base.as_posix()}"\n'
        f'[{section}.paths]\nstatic="STATIC/"\npalette="STATIC/PALETTES.FLX"\n'
        'missing="STATIC/MISSING.DAT"\n'
        f'[{section}.mods."Test Mod".paths]\narchive="{archive.as_posix()}"\n'
    )

    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0

    lines = capsys.readouterr().out.splitlines()
    for key in ("static", "palette", "archive"):
        assert "[OK]" in next(line for line in lines if line.strip().startswith(key))
    assert "[NOT FOUND]" in next(line for line in lines if "missing " in line)


def test_multi_game_u8_overrides_legacy_and_expands_fallback_paths(
    setup_workspace: Path,
) -> None:
    path = setup_workspace / "mixed.toml"
    base = setup_workspace / "new-install"
    path.write_text(
        '[game]\nbase="legacy"\nlanguage="FRENCH"\n'
        '[paths]\nfixed="LEGACY.DAT"\npalette="FALLBACK.PAL"\n'
        f'[u8.game]\nbase="{base.as_posix()}"\nlanguage="ENGLISH"\n'
        '[u8.paths]\nfixed="FIXED.DAT"\n'
    )

    saved = _config.load_config(str(path))

    fixed = _config.cfg("fixed")
    palette = _config.cfg("palette")
    assert fixed is not None and palette is not None
    assert Path(fixed) == base / "ENGLISH" / "STATIC" / "FIXED.DAT"
    assert Path(palette) == base / "ENGLISH" / "STATIC" / "FALLBACK.PAL"
    assert saved["u8"]["paths"] == saved["paths"]
    assert saved["u8"]["game"] == saved["game"]


def test_setup_writer_keeps_previous_backups(setup_workspace: Path) -> None:
    path = setup_workspace / "config.toml"
    original = '[custom]\nvalue="keep"\n'
    path.write_text(original)
    generated = '[uo.game]\nbase="uo"\n'
    first = write_setup_config(path, generated)
    second = write_setup_config(path, generated)

    assert first is not None and second is not None and first != second
    assert first.read_text() == original
    assert tomllib.loads(second.read_text())["uo"]["game"]["base"] == "uo"


def test_setup_writer_leaves_invalid_existing_config_untouched(
    setup_workspace: Path,
) -> None:
    path = setup_workspace / "config.toml"
    original = b"[broken\n"
    path.write_bytes(original)

    with pytest.raises(ValueError):
        write_setup_config(path, '[uo.game]\nbase="uo"\n')

    assert path.read_bytes() == original
    assert not path.with_name("config.toml.bak").exists()
