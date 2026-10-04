"""Regression coverage for setup discovery, config preservation, and inspection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from titan import _config, cli
from titan._setup_config import write_setup_config
from titan.u7.flex import U7FlexArchive
from titan.u7.install import inspect_install, install_roots, resolve_u7_path

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
        for prefix, value in answers.items():
            if prompt.startswith(prefix):
                return value
        return ""

    monkeypatch.setattr("builtins.input", answer)


def _u7_install(root: Path, *, lowercase: bool = False) -> Path:
    static = root / ("static" if lowercase else "STATIC")
    static.mkdir(parents=True)
    for name, records in {
        "SHAPES.VGA": [bytes(64)],
        "PALETTES.FLX": [bytes([20, 30, 40]) * 256],
        "TEXT.FLX": [b"test shape\0"],
    }.items():
        archive = U7FlexArchive()
        archive.records = records
        archive.save(str(static / (name.lower() if lowercase else name)))
    return root


def test_setup_menu_cancellation_preserves_files(setup_workspace, monkeypatch):
    from titan import _wizard_ui as ui
    import questionary

    monkeypatch.setattr(ui, "menus_enabled", lambda: True)

    class Prompt:
        def ask(self):
            return None

    monkeypatch.setattr(questionary, "path", lambda *args, **kwargs: Prompt())
    result = CliRunner().invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.output
    assert "Setup cancelled" in result.output
    assert not (setup_workspace / "work/titan.toml").exists()


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
    _u7_install(install)
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
    _u7_install(base)
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


@pytest.mark.parametrize(
    ("folder", "section"), [("ULTIMA7", "u7bg"), ("SERPENT", "u7si")]
)
def test_setup_normalizes_manual_nested_root(
    setup_workspace, monkeypatch, capsys, folder, section
):
    outer = setup_workspace / "install"
    root = _u7_install(outer / folder)
    prefix = "Ultima VII Black Gate" if section == "u7bg" else "Ultima VII Serpent Isle"
    _answer_setup(monkeypatch, {prefix: str(outer)})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved[section]["game"]["base"] == root.as_posix()
    for key in ("static", "shapes", "palette", "text"):
        assert (root / saved[section]["paths"][key]).exists()
    assert "[OK]" in capsys.readouterr().out


def test_setup_discovers_both_games_in_complete_install(setup_workspace, monkeypatch):
    outer = setup_workspace / "home" / "GOG Games" / "Ultima VII"
    bg = _u7_install(outer / "ULTIMA7")
    si = _u7_install(outer / "SERPENT")
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u7bg"]["game"]["base"] == bg.as_posix()
    assert saved["u7si"]["game"]["base"] == si.as_posix()


def test_setup_repairs_existing_nested_base_and_preserves_custom_paths(
    setup_workspace, monkeypatch, capsys
):
    outer = setup_workspace / "install"
    root = _u7_install(outer / "SERPENT")
    custom_palette = setup_workspace / "custom.pal"
    custom_palette.write_bytes(bytes(768))
    path = Path.cwd() / "titan.toml"
    original = (
        f'[u7si.game]\nbase="{outer.as_posix()}"\nvariant="serpentisle"\n'
        f'[u7si.paths]\nstatic="STATIC/"\npalette="{custom_palette.as_posix()}"\n'
        '[custom]\nvalue="preserve"\n'
    )
    path.write_text(original)
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["u7si"]["game"]["base"] == root.as_posix()
    assert saved["u7si"]["paths"]["palette"] == custom_palette.as_posix()
    assert saved["custom"]["value"] == "preserve"
    assert path.with_name("titan.toml.bak").read_text() == original
    assert "Proposed u7si base correction" in capsys.readouterr().out


def test_setup_keeps_valid_custom_game_selection(setup_workspace, monkeypatch):
    custom = _u7_install(setup_workspace / "custom-install")
    _u7_install(setup_workspace / "home" / "GOG Games" / "Ultima VII" / "SERPENT")
    path = Path.cwd() / "titan.toml"
    path.write_text(f'[u7si.game]\nbase="{custom.as_posix()}"\n')
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert tomllib.loads(path.read_text())["u7si"]["game"]["base"] == custom.as_posix()
    assert "u7bg" not in tomllib.loads(path.read_text())


def test_setup_declining_correction_preserves_existing_base(
    setup_workspace, monkeypatch
):
    outer = setup_workspace / "install"
    _u7_install(outer / "SERPENT")
    path = Path.cwd() / "titan.toml"
    path.write_text(f'[u7si.game]\nbase="{outer.as_posix()}"\n')
    _answer_setup(monkeypatch, {"Are these paths correct?": "n"})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert tomllib.loads(path.read_text())["u7si"]["game"]["base"] == outer.as_posix()


@pytest.mark.parametrize("problem", ["missing", "header", "bounds", "palette"])
def test_setup_reports_incomplete_or_damaged_install_without_auto_selecting(
    setup_workspace, monkeypatch, capsys, problem
):
    root = _u7_install(setup_workspace / "home" / "GOG Games" / "Ultima VII")
    shapes = root / "STATIC/SHAPES.VGA"
    if problem == "missing":
        (root / "STATIC/TEXT.FLX").unlink()
    elif problem == "header":
        shapes.write_bytes(b"not a Flex archive")
    elif problem == "bounds":
        shapes.write_bytes(shapes.read_bytes()[:128])
    else:
        palette = root / "STATIC/PALETTES.FLX"
        archive = U7FlexArchive()
        archive.records = [bytes(12)]
        archive.save(str(palette))
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert "u7bg" not in saved
    report = capsys.readouterr().out
    assert "Incomplete or damaged" in report
    assert ("NOT FOUND" if problem == "missing" else "INVALID") in report


def test_setup_uses_actual_filename_case(setup_workspace, monkeypatch):
    root = _u7_install(setup_workspace / "lowercase", lowercase=True)
    _answer_setup(monkeypatch, {"Ultima VII Black Gate": str(root)})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u7bg"]["paths"]["palette"] == "static/palettes.flx"


def test_discovery_is_bounded_and_ignores_mod_archives(setup_workspace):
    outer = setup_workspace / "outer"
    found = _u7_install(outer / "a" / "SERPENT")
    _u7_install(outer / "deep" / "nested" / "ULTIMA7")
    _u7_install(outer / "mods" / "ULTIMA7")
    _u7_install(outer / "patch" / "SERPENT")
    assert install_roots(outer) == [found]
    assert install_roots(found / "STATIC") == [found]


def test_empty_static_folder_is_not_an_install(setup_workspace):
    root = setup_workspace / "empty"
    (root / "STATIC").mkdir(parents=True)
    assert install_roots(root) == []
    assert not inspect_install(root).valid


@pytest.mark.parametrize("game", ["BG", "SI"])
def test_shared_workflows_fall_back_to_exult_for_missing_configured_paths(
    setup_workspace, monkeypatch, game
):
    from titan.fonts.palette import resolve_game_palette
    from titan.u7 import cli as u7_cli, shape_wizard

    root = _u7_install(setup_workspace / "unusual-install")
    section = "u7bg" if game == "BG" else "u7si"
    monkeypatch.setattr(
        _config,
        "_config",
        {
            section: {
                "game": {"base": str(setup_workspace / "missing")},
                "paths": {"static": "STATIC", "palette": "STATIC/PALETTES.FLX"},
            }
        },
    )
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths",
        lambda game: {"base": root, "static": root / "STATIC"},
    )
    expected = root / "STATIC/PALETTES.FLX"
    assert resolve_u7_path(game, "palette") == expected
    assert shape_wizard._static_path(game) == str(root / "STATIC")
    assert u7_cli._resolve_u7_paths(game) == (str(root / "STATIC"), str(expected))
    assert u7_cli._resolve_u7_text_flx(game) == str(root / "STATIC/TEXT.FLX")
    assert resolve_game_palette(game).colors[0] == (80, 121, 161)
    assert shape_wizard._palette(shape_wizard.ShapeWizardConfig(game=game)).colors[
        0
    ] == (80, 121, 161)


def test_missing_explicit_palette_is_an_error_even_with_exult(
    setup_workspace, monkeypatch
):
    from titan.fonts.palette import resolve_game_palette

    root = _u7_install(setup_workspace / "game")
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths", lambda game: {"static": root / "STATIC"}
    )
    with pytest.raises(FileNotFoundError):
        resolve_game_palette("BG", str(setup_workspace / "missing.pal"))


def test_config_reports_actual_resolved_paths_and_does_not_mask_bad_settings(
    setup_workspace, monkeypatch, capsys
):
    root = _u7_install(setup_workspace / "install" / "SERPENT")
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u7si.game]\nbase="{root.parent.as_posix()}"\n'
        '[u7si.paths]\npalette="STATIC/PALETTES.FLX"\n'
    )
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths", lambda game: {"static": root / "STATIC"}
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    line = next(
        line for line in capsys.readouterr().out.splitlines() if "palette " in line
    )
    assert "[NOT FOUND]" in line
    assert str(root.parent / "STATIC/PALETTES.FLX") in line
    assert resolve_u7_path("SI", "palette") == root / "STATIC/PALETTES.FLX"


def test_base_correction_preserves_custom_relative_resource_locations(
    setup_workspace, monkeypatch
):
    outer = setup_workspace / "install"
    root = _u7_install(outer / "SERPENT")
    custom = outer / "assets" / "custom.pal"
    custom.parent.mkdir()
    custom.write_bytes(bytes(768))
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u7si.game]\nbase="{outer.as_posix()}"\n'
        '[u7si.paths]\npalette="assets/custom.pal"\n'
    )
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["u7si"]["game"]["base"] == root.as_posix()
    assert Path(saved["u7si"]["paths"]["palette"]) == custom


def test_setup_validates_preserved_custom_palette_before_saving(
    setup_workspace, monkeypatch, capsys
):
    root = _u7_install(setup_workspace / "install" / "SERPENT")
    custom = setup_workspace / "broken.pal"
    custom.write_bytes(bytes(12))
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u7si.game]\nbase="{root.as_posix()}"\n'
        f'[u7si.paths]\npalette="{custom.as_posix()}"\n'
    )
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    output = capsys.readouterr().out
    assert any(
        str(custom) in line and "INVALID" in line for line in output.splitlines()
    )


def test_config_marks_damaged_palette_invalid(setup_workspace, capsys):
    root = _u7_install(setup_workspace / "install")
    (root / "STATIC/PALETTES.FLX").write_bytes(b"bad")
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u7bg.game]\nbase="{root.as_posix()}"\n'
        '[u7bg.paths]\npalette="STATIC/PALETTES.FLX"\n'
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    line = next(
        line for line in capsys.readouterr().out.splitlines() if "palette " in line
    )
    assert "[INVALID:" in line
    assert str(root / "STATIC/PALETTES.FLX") in line


def test_setup_discovers_exult_game_and_static_overrides(setup_workspace, monkeypatch):
    root = setup_workspace / "custom-base"
    root.mkdir()
    donor = _u7_install(setup_workspace / "resources")
    static = donor / "STATIC"
    cfg = setup_workspace / "local" / "Exult" / "exult.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        f"<config><disk><game><serpentisle><path>{root}</path>"
        f"<static_path>{static}</static_path></serpentisle></game></disk></config>"
    )
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u7si"]["game"]["base"] == root.as_posix()
    assert Path(saved["u7si"]["paths"]["palette"]) == static / "PALETTES.FLX"
    assert "u7bg" not in saved


def test_manual_static_selection_is_verified_and_updates_existing_config(
    setup_workspace, monkeypatch, capsys
):
    root = _u7_install(setup_workspace / "manual" / "SERPENT")
    path = Path.cwd() / "titan.toml"
    path.write_text('[u7si.game]\nbase="old"\n[u7si.paths]\nstatic="old-static"\n')
    _answer_setup(
        monkeypatch,
        {"Are these paths correct?": "n", "U7 SI STATIC path": str(root / "STATIC")},
    )
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["u7si"]["game"]["base"] == root.as_posix()
    assert Path(saved["u7si"]["paths"]["palette"]) == root / "STATIC/PALETTES.FLX"
    assert "[OK]" in capsys.readouterr().out


def test_cancel_manual_paths_leaves_existing_config_untouched(
    setup_workspace, monkeypatch
):
    path = Path.cwd() / "titan.toml"
    original = '[custom]\nvalue="original"\n'
    path.write_text(original)
    _answer_setup(
        monkeypatch,
        {"Are these paths correct?": "n", "Save these manually selected paths?": "n"},
    )
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert path.read_text() == original
    assert not path.with_name("titan.toml.bak").exists()


def test_relative_mod_paths_agree_between_inspector_and_workflows(
    setup_workspace, capsys
):
    from titan.u7 import cli as u7_cli

    root = _u7_install(setup_workspace / "game")
    gamedat = root / "mods" / "Test" / "gamedat"
    gamedat.mkdir(parents=True)
    (gamedat / "npc.dat").touch()
    archive = root / "mods" / "Test" / "initgame.dat"
    archive.touch()
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u7si.game]\nbase="{root.as_posix()}"\n'
        '[u7si.mods.Test.paths]\ngamedat="mods/Test/gamedat"\narchive="mods/Test/initgame.dat"\n'
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    assert u7_cli._resolve_u7_mod_gamedat("si", "Test") == str(gamedat)
    assert u7_cli._resolve_u7_mod_archive("si", "Test") == str(archive)
    lines = capsys.readouterr().out.splitlines()
    assert all(
        "[OK]" in line for line in lines if "gamedat " in line or "archive " in line
    )
