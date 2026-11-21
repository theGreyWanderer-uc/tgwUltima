"""Regression coverage for setup discovery, config preservation, and inspection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from titan import _config, cli
from titan._meta import configured_install
from titan._setup_config import write_setup_config
from titan.errors import EXIT_CODES
from titan.u7 import install as u7_install
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


def _u9_install(root: Path) -> Path:
    from titan.u9.flx_writer import build_flx
    from titan.u9.install import U9_RESOURCE_NAMES

    static = root / "STATIC"
    static.mkdir(parents=True)
    for key, name in U9_RESOURCE_NAMES.items():
        (static / name.upper()).write_bytes(
            bytes(1024) if key == "palette" else build_flx({0: bytes(48)})
        )
    for name in ("sound", "runtime", "savegame"):
        (root / name).mkdir()
    return root


def _u6_install(root: Path) -> Path:
    from titan.u6.install import U6_RESOURCE_NAMES

    root.mkdir(parents=True)
    for key, name in U6_RESOURCE_NAMES.items():
        if key == "savegame":
            (root / name).mkdir()
        else:
            (root / name).touch()
    return root


def test_u6_candidates_include_configured_and_gog_installs(setup_workspace):
    from titan.u6.install import u6_install_candidates

    configured = setup_workspace / "custom U6"
    candidates = u6_install_candidates({"u6": {"game": {"base": str(configured)}}})
    assert candidates[0] == configured
    for drive in "CDEFG":
        for layout in (
            "Program Files (x86)/GOG Galaxy/Games",
            "GOG Games",
            "Ultima",
            "",
        ):
            assert Path(f"{drive}:/") / layout / "Ultima 6" in candidates
            assert Path(f"{drive}:/") / layout / "Ultima VI" in candidates


@pytest.mark.parametrize("name", ["Ultima 6", "Ultima VI - The False Prophet"])
def test_setup_detects_u6_and_inventories_resources(setup_workspace, monkeypatch, name):
    root = _u6_install(setup_workspace / "home/Games/Heroic" / name)
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u6"]["game"]["base"] == root.as_posix()
    assert saved["u6"]["paths"]["palette"] == "U6PAL"
    assert saved["u6"]["paths"]["converse_a"] == "CONVERSE.A"
    assert saved["u6"]["paths"]["books"] == "BOOK.DAT"
    assert saved["u6"]["paths"]["objlist"] == "SAVEGAME/OBJLIST"


def test_u6_discovery_does_not_match_roman_u7_or_u8(setup_workspace):
    from titan.u6.install import u6_install_candidates

    launcher = setup_workspace / "home/Games/Heroic"
    for name in ("Ultima VII - Complete", "Ultima VIII", "UltimaVII", "Martian Dreams"):
        directory = launcher / name
        directory.mkdir(parents=True, exist_ok=True)
        assert directory not in u6_install_candidates({})


def test_setup_accepts_quoted_u6_without_optional_saves(setup_workspace, monkeypatch):
    root = _u6_install(setup_workspace / "custom game/Ultima6")
    (root / "SAVEGAME/OBJLIST").unlink()
    (root / "SAVEGAME").rmdir()
    _answer_setup(monkeypatch, {"Ultima VI base": f'"{root}"'})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u6"]["game"]["base"] == root.as_posix()
    assert "savegame" not in saved["u6"]["paths"]
    assert "objlist" not in saved["u6"]["paths"]


@pytest.mark.parametrize("missing", ["U6PAL", "MAP", "MAPTILES.VGA"])
def test_setup_rejects_incomplete_u6_data(setup_workspace, monkeypatch, missing):
    root = _u6_install(setup_workspace / "home/GOG Games/Ultima 6")
    (root / missing).unlink()
    (root / "MDPAL").touch()  # MD's palette must not stand in for U6PAL.
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert "u6" not in tomllib.loads((Path.cwd() / "titan.toml").read_text())


@pytest.mark.parametrize("decline", [False, True])
def test_setup_preserves_custom_u6_settings_and_backup(
    setup_workspace, monkeypatch, decline
):
    root = _u6_install(setup_workspace / "custom U6")
    path = Path.cwd() / "titan.toml"
    original = (
        f'[u6.game]\nbase="{root.as_posix()}"\n[u6.paths]\npalette="custom.pal"\n'
    )
    path.write_text(original)
    _answer_setup(monkeypatch, {"Are these paths correct?": "n"} if decline else {})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["u6"]["game"]["base"] == root.as_posix()
    assert saved["u6"]["paths"]["palette"] == "custom.pal"
    assert ("converse_a" in saved["u6"]["paths"]) != decline
    assert path.with_name("titan.toml.bak").read_text() == original


def test_u6_only_config_inspects_relative_absolute_and_missing_paths(
    setup_workspace, capsys
):
    root = _u6_install(setup_workspace / "Ultima6")
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u6.game]\nbase="{root.as_posix()}"\n[u6.paths]\n'
        f'palette="U6PAL"\nbooks="{(root / "BOOK.DAT").as_posix()}"\n'
        'objlist="SAVEGAME/OBJLIST"\nmissing="MISSING.DAT"\n'
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    report = capsys.readouterr().out
    assert "[u6.game]" in report and "[u6.paths]" in report
    for key in ("palette", "books", "objlist"):
        assert "[OK]" in next(
            line for line in report.splitlines() if line.strip().startswith(key)
        )
    assert "[NOT FOUND]" in next(
        line for line in report.splitlines() if line.strip().startswith("missing")
    )


def test_config_shows_missing_working_folders_neutrally(setup_workspace, capsys):
    base = setup_workspace / "Ultima8"
    (base / "ENGLISH" / "STATIC").mkdir(parents=True)
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u8.game]\nbase="{base.as_posix()}"\n[u8.paths]\n'
        'fixed="FIXED.DAT"\nshapes="shapes"\n'
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    lines = capsys.readouterr().out.splitlines()

    def flag(key: str) -> str:
        return next(line for line in lines if line.strip().startswith(key))

    assert "[not extracted yet]" in flag("shapes")
    assert "[NOT FOUND]" in flag("fixed")


def _md_install(root: Path) -> Path:
    from titan.md.install import MD_RESOURCE_NAMES

    root.mkdir(parents=True)
    for key, name in MD_RESOURCE_NAMES.items():
        if key == "savegame":
            (root / name).mkdir()
        else:
            (root / name).touch()
    return root


def test_martian_candidates_include_configured_and_gog_installs(setup_workspace):
    from titan.md.install import martian_install_candidates

    configured = setup_workspace / "custom/MARTIAN"
    candidates = martian_install_candidates({"md": {"game": {"base": str(configured)}}})
    assert candidates[0] == configured
    for drive in "CDEFG":
        for layout in (
            "Program Files (x86)/GOG Galaxy/Games",
            "GOG Games",
            "Ultima",
            "",
        ):
            assert Path(f"{drive}:/") / layout / "Martian Dreams" in candidates


def test_setup_detects_martian_gog_layout_and_inventories_resources(
    setup_workspace, monkeypatch
):
    root = _md_install(setup_workspace / "home/GOG Games/Martian Dreams/MARTIAN")
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["md"]["game"]["base"] == root.as_posix()
    assert saved["md"]["paths"]["palette"] == "MDPAL"
    assert saved["md"]["paths"]["talk"] == "TALK.LZC"
    assert saved["md"]["paths"]["text"] == "MDTEXT.LZC"
    assert saved["md"]["paths"]["objlist"] == "SAVEGAME/OBJLIST"


@pytest.mark.parametrize("use_parent", [False, True])
def test_setup_preserves_martian_base_custom_paths_and_backup(
    setup_workspace, monkeypatch, use_parent
):
    root = _md_install(setup_workspace / "custom game/MARTIAN")
    base = root.parent if use_parent else root
    path = Path.cwd() / "titan.toml"
    original = (
        f'[md.game]\nbase="{base.as_posix()}"\n[md.paths]\npalette="custom.pal"\n'
    )
    path.write_text(original)
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["md"]["game"]["base"] == base.as_posix()
    assert saved["md"]["paths"]["palette"] == "custom.pal"
    assert (
        saved["md"]["paths"]["talk"] == ("MARTIAN/" if use_parent else "") + "TALK.LZC"
    )
    assert path.with_name("titan.toml.bak").read_text() == original


def test_setup_accepts_quoted_martian_parent_without_optional_saves(
    setup_workspace, monkeypatch
):
    root = _md_install(setup_workspace / "custom game/MARTIAN")
    (root / "SAVEGAME/OBJLIST").unlink()
    (root / "SAVEGAME").rmdir()
    (root / "MAP").unlink()  # LZMAP also identifies a valid map install.
    _answer_setup(monkeypatch, {"Martian Dreams base": f'"{root.parent}"'})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["md"]["game"]["base"] == root.parent.as_posix()
    assert saved["md"]["paths"]["lzmap"] == "MARTIAN/LZMAP"
    assert "savegame" not in saved["md"]["paths"]
    assert "objlist" not in saved["md"]["paths"]


@pytest.mark.parametrize("missing", ["MDPAL", "MAPTILES.VGA"])
def test_setup_rejects_incomplete_martian_data(setup_workspace, monkeypatch, missing):
    root = _md_install(setup_workspace / "home/GOG Games/Martian Dreams/MARTIAN")
    (root / missing).unlink()
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert "md" not in tomllib.loads((Path.cwd() / "titan.toml").read_text())


def test_martian_only_config_inspects_relative_and_missing_paths(
    setup_workspace, capsys
):
    root = _md_install(setup_workspace / "MARTIAN")
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[md.game]\nbase="{root.as_posix()}"\n[md.paths]\n'
        'palette="MDPAL"\nobjlist="SAVEGAME/OBJLIST"\nmissing="missing.lzc"\n'
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    report = capsys.readouterr().out
    assert "[md.game]" in report and "[md.paths]" in report
    for key in ("palette", "objlist"):
        assert "[OK]" in next(
            line for line in report.splitlines() if line.strip().startswith(key)
        )
    assert "[NOT FOUND]" in next(
        line for line in report.splitlines() if line.strip().startswith("missing")
    )


def test_setup_help_mentions_martian_dreams():
    result = CliRunner().invoke(cli.app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "Martian Dreams" in result.output


def test_u9_candidates_include_spaced_windows_layouts_on_multiple_drives(
    setup_workspace,
):
    from titan.u9.install import u9_install_candidates

    candidates = u9_install_candidates({})
    for drive in "CDEFG":
        for layout in ("Program Files (x86)/GOG Galaxy/Games", "GOG Games", ""):
            assert Path(f"{drive}:/") / layout / "Ultima 9" in candidates
    assert candidates.index(
        Path("C:/Program Files (x86)/GOG Galaxy/Games/Ultima 9")
    ) < candidates.index(Path("C:/GOG Games/Ultima 9"))
    assert candidates.index(Path("C:/GOG Games/Ultima 9")) < candidates.index(
        Path("C:/Ultima 9")
    )


def test_u9_candidates_include_steam_libraries_on_multiple_drives(setup_workspace):
    from titan.u9.install import u9_install_candidates

    candidates = u9_install_candidates({})
    for drive in "CDEFG":
        for layout in (
            "Program Files (x86)/Steam/steamapps/common",
            "SteamLibrary/steamapps/common",
        ):
            assert Path(f"{drive}:/") / layout / "Ultima IX" in candidates


def test_setup_detects_u9_nested_install_and_records_actual_case(
    setup_workspace, monkeypatch
):
    root = _u9_install(setup_workspace / "home/GOG Games/Ultima 9/game")
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u9"]["game"]["base"] == root.as_posix()
    assert saved["u9"]["paths"]["palette"] == "STATIC/ANKH.PAL"
    assert saved["u9"]["paths"]["sdinfo16"] == "STATIC/SDINFO16.FLX"
    assert saved["u9"]["paths"]["savegame"] == "savegame"


@pytest.mark.parametrize("problem", ["missing", "header", "bounds", "palette"])
def test_setup_does_not_select_incomplete_u9_install(
    setup_workspace, monkeypatch, capsys, problem
):
    root = _u9_install(setup_workspace / "home/GOG Games/Ultima 9")
    if problem == "missing":
        (root / "STATIC/ANKH.PAL").unlink()
    elif problem == "header":
        (root / "STATIC/BITMAP16.FLX").write_bytes(b"not an FLX")
    elif problem == "palette":
        (root / "STATIC/ANKH.PAL").write_bytes(bytes(12))
    else:
        path = root / "STATIC/BITMAP16.FLX"
        path.write_bytes(path.read_bytes()[:-1])
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert "u9" not in tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert "Incomplete or damaged Ultima 9" in capsys.readouterr().out


def test_setup_accepts_quoted_u9_base_with_spaces(setup_workspace, monkeypatch):
    root = _u9_install(setup_workspace / "custom game/Ultima 9")
    _answer_setup(monkeypatch, {"Ultima IX base": f'"{root}"'})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["u9"]["game"]["base"] == root.as_posix()


def test_setup_declining_u9_correction_preserves_base(setup_workspace, monkeypatch):
    outer = setup_workspace / "wrapper"
    _u9_install(outer / "game")
    path = Path.cwd() / "titan.toml"
    path.write_text(f'[u9.game]\nbase="{outer.as_posix()}"\n')
    _answer_setup(monkeypatch, {"Are these paths correct?": "n"})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert tomllib.loads(path.read_text())["u9"]["game"]["base"] == outer.as_posix()


def test_u9_config_inspection_and_shared_resolution(setup_workspace, capsys):
    from titan.u9.install import configured_u9_path

    root = _u9_install(setup_workspace / "install")
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u9.game]\nbase="{root.as_posix()}"\n'
        '[u9.paths]\nstatic="static"\npalette="static/ankh.pal"\n'
        'bitmap16="static/bitmap16.flx"\nmissing="static/missing.flx"\n'
    )
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    report = capsys.readouterr().out
    assert "[u9.game]" in report and "[u9.paths]" in report
    assert "[OK]" in next(
        line for line in report.splitlines() if line.strip().startswith("bitmap16")
    )
    assert "[NOT FOUND]" in next(
        line for line in report.splitlines() if line.strip().startswith("missing")
    )
    assert configured_u9_path("palette") == root / "STATIC/ANKH.PAL"


def test_u9_discovery_skips_backups_and_accepts_static_path(setup_workspace):
    from titan.u9.install import discover_u9_installs

    outer = setup_workspace / "collection"
    root = _u9_install(outer / "game")
    _u9_install(outer / "backup/copy")
    _u9_install(outer / "other_backup/copy")
    _u9_install(outer / "patch/copy")
    assert [item.root for item in discover_u9_installs(outer)] == [root]
    assert discover_u9_installs(root / "STATIC")[0].root == root
    assert discover_u9_installs(outer, max_depth=0) == []


def test_setup_preserves_u9_custom_paths_and_confirms_base_correction(
    setup_workspace, monkeypatch
):
    outer = setup_workspace / "wrapper"
    root = _u9_install(outer / "game")
    path = Path.cwd() / "titan.toml"
    original = (
        f'[u9.game]\nbase="{outer.as_posix()}"\n[u9.paths]\npalette="custom.pal"\n'
    )
    path.write_text(original)
    _answer_setup(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["u9"]["game"]["base"] == root.as_posix()
    assert saved["u9"]["paths"]["palette"] == "custom.pal"
    assert path.with_name("titan.toml.bak").read_text() == original


def test_u9_save_browser_uses_config_only_without_explicit_source(
    setup_workspace, monkeypatch
):
    from titan.u9 import save_browser_ui

    root = _u9_install(setup_workspace / "install")
    monkeypatch.setattr(
        _config,
        "_config",
        {"u9": {"game": {"base": str(root)}, "paths": {"static": "STATIC"}}},
    )
    seen = []
    monkeypatch.setattr(
        save_browser_ui, "choose_u9_save_browser_source", lambda game: seen.append(game)
    )
    assert save_browser_ui.run_u9_save_browser() == 0
    assert seen == [root]
    seen.clear()
    other = setup_workspace / "other"
    assert save_browser_ui.run_u9_save_browser(game_dir=other) == 0
    assert seen == [other]


def test_u9_save_browser_help_mentions_config_default():
    result = CliRunner().invoke(cli.app, ["u9", "save-browse", "--help"])
    assert result.exit_code == 0
    assert "[u9.game].base" in result.output


def test_setup_menu_cancellation_preserves_files(setup_workspace, monkeypatch):
    import questionary

    from titan import _wizard_ui as ui

    monkeypatch.setattr(ui, "menus_enabled", lambda: True)

    class Prompt:
        def ask(self):
            return None

    monkeypatch.setattr(questionary, "path", lambda *args, **kwargs: Prompt())
    result = CliRunner().invoke(cli.app, ["setup"])
    assert result.exit_code == EXIT_CODES["cancelled"], result.output
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


def test_setup_moves_legacy_u8_config_under_u8_without_adding_defaults(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = Path.cwd() / "titan.toml"
    path.write_text('[game]\nbase="legacy"\n[paths]\nfixed="CUSTOM.DAT"\n')
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = tomllib.loads(path.read_text())
    assert "game" not in saved and "paths" not in saved
    assert saved["u8"] == {"game": {"base": "legacy"}, "paths": {"fixed": "CUSTOM.DAT"}}
    assert "[game]" in path.with_name("titan.toml.bak").read_text()


@pytest.mark.parametrize("save_exists", [False, True])
def test_setup_records_u8_save_folder_and_prunes_only_stale_default(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch, save_exists: bool
) -> None:
    base = setup_workspace / "u8"
    if save_exists:
        saves = base / "cloud_saves" / "SAVEGAME"
        saves.mkdir(parents=True)
        (saves / "U8SAVE.000").write_bytes(b"")
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u8.game]\nbase="{base.as_posix()}"\nlanguage="ENGLISH"\n'
        '[u8.paths]\nnonfixed="U8SAVE.000"\n'
    )
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = tomllib.loads(path.read_text())["u8"]["paths"]
    assert saved["savegame"] == "cloud_saves/SAVEGAME"
    assert ("nonfixed" in saved) is save_exists


def test_setup_fresh_u8_config_has_no_default_save(
    setup_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer_setup(monkeypatch)

    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0

    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())["u8"]["paths"]
    assert "nonfixed" not in saved


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
    # The loaded config has [u8] only; titan's old top-level copy is gone.
    assert "game" not in saved and "paths" not in saved
    assert saved["u8"]["game"]["language"] == "ENGLISH"


def test_legacy_flat_config_loads_as_u8(setup_workspace: Path, capsys) -> None:
    base = setup_workspace / "u8"
    path = setup_workspace / "flat.toml"
    path.write_text(f'[game]\nbase="{base.as_posix()}"\n[paths]\nfixed="FIXED.DAT"\n')
    saved = _config.load_config(str(path))
    assert set(saved) == {"u8"}
    assert Path(_config.cfg("fixed")) == base / "ENGLISH" / "STATIC" / "FIXED.DAT"
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0
    out = capsys.readouterr().out
    assert "[u8.paths]" in out and "old U8-only layout" in out


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
    from titan.u7 import shape_wizard

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
    install = configured_install(section)
    wizard_config = shape_wizard.ShapeWizardConfig(game=game, install=install)
    assert resolve_u7_path(game, "palette") == expected
    assert shape_wizard._static_path(wizard_config) == str(root / "STATIC")
    assert u7_install.resolve_u7_static_and_palette(game) == (
        str(root / "STATIC"),
        str(expected),
    )
    assert u7_install.resolve_u7_text_flx(game) == str(root / "STATIC/TEXT.FLX")
    assert resolve_game_palette(game, install=install).colors[0] == (80, 121, 161)
    assert shape_wizard._palette(wizard_config).colors[0] == (80, 121, 161)


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


def test_u7_configured_install_is_what_commands_use(setup_workspace, monkeypatch):
    root = _u7_install(setup_workspace / "game")
    bundle = setup_workspace / "exult_bg.flx"
    bundle.write_bytes(b"")
    exult = _u7_install(setup_workspace / "exult-game")
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths",
        lambda game: {"base": exult, "static": exult / "STATIC"},
    )
    monkeypatch.setattr(
        _config,
        "_config",
        {
            "u7bg": {
                "game": {"base": str(root), "variant": "blackgate"},
                "paths": {"text": "STATIC/NOPE.FLX", "gamedat": "gamedat"},
            },
            "exult": {"paths": {"bg_flx": str(bundle)}},
        },
    )
    install = configured_install("u7bg")
    assert install.root == root
    assert install.resources["static"] == root / "STATIC"
    assert install.resources["palette"] == root / "STATIC/PALETTES.FLX"
    # A missing configured file falls back, and the setting is still reported.
    assert install.resources["text"] == root / "STATIC/TEXT.FLX"
    assert install.problems["text"] == "NOT FOUND"
    # Exult creates a configured gamedat on first run: kept, and reported.
    assert install.resources["gamedat"] == root / "gamedat"
    assert install.problems["gamedat"] == "NOT FOUND"
    assert install.resources["exult_flx"] == bundle
    assert install.configured == {"text", "gamedat"}
    assert install.settings == {"variant": "blackgate"}
    assert u7_install.resolve_u7_static_and_palette("BG") == (
        str(root / "STATIC"),
        str(root / "STATIC/PALETTES.FLX"),
    )
    assert u7_install.resolve_u7_gamedat("BG") == str(root / "gamedat")
    assert u7_install.resolve_u7_exult_flx("BG") == str(bundle)
    # The configured TEXT.FLX is missing, so a selected STATIC's own wins.
    assert u7_install.resolve_u7_text_flx("BG", str(exult / "STATIC")) == str(
        exult / "STATIC/TEXT.FLX"
    )


def test_u7_configured_install_without_config_uses_exult(setup_workspace, monkeypatch):
    exult = _u7_install(setup_workspace / "exult-game")
    monkeypatch.setattr("titan.u7.install.find_exult_flx", lambda name: None)
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths",
        lambda game: {"base": exult, "static": exult / "STATIC"},
    )
    install = configured_install("u7si")
    assert install.root == exult
    assert install.resources["static"] == exult / "STATIC"
    assert not install.problems and not install.configured
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    assert configured_install("u7si") is None


def test_u7_library_defaults_come_from_the_install_not_config(
    setup_workspace, monkeypatch
):
    from titan.fonts.archive import read_font_archive
    from titan.fonts.palette import resolve_game_palette
    from titan.u7 import shape_wizard

    root = _u7_install(setup_workspace / "game")
    monkeypatch.setattr(_config, "_config", {"u7bg": {"game": {"base": str(root)}}})
    monkeypatch.setattr("titan.fonts.palette._BUNDLED_PAL_DIRS", {})
    assert resolve_game_palette("BG") is None
    assert shape_wizard._static_path(shape_wizard.ShapeWizardConfig()) is None
    install = configured_install("u7bg")
    assert resolve_game_palette("BG", install=install) is not None
    config = shape_wizard.ShapeWizardConfig(install=install)
    assert shape_wizard._static_path(config) == str(root / "STATIC")

    base = U7FlexArchive()
    base.records = [b"base0", b"base1"]
    base.save(str(root / "STATIC/FONTS.VGA"))
    patch = setup_workspace / "mods/example/patch/fonts.vga"
    patch.parent.mkdir(parents=True)
    sparse = U7FlexArchive()
    sparse.records = [b"", b"mine"]
    sparse.save(str(patch))
    monkeypatch.setattr("titan.fonts.archive.game_paths", lambda game: None)
    with pytest.raises(ValueError, match="Cannot resolve FONTS.VGA base"):
        read_font_archive(patch)
    assert read_font_archive(patch, install=install).records == [b"base0", b"mine"]


def test_u7_exult_bundles_come_from_the_record_not_library_config(
    setup_workspace, monkeypatch
):
    bundle = setup_workspace / "custom/exult_bg.flx"
    common = setup_workspace / "custom/exult.flx"
    bundle.parent.mkdir()
    bundle.write_bytes(b"")
    common.write_bytes(b"")
    monkeypatch.setattr("titan.u7.install.find_exult_flx", lambda name: None)
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    root = _u7_install(setup_workspace / "game")
    monkeypatch.setattr(
        _config,
        "_config",
        {
            "u7bg": {"game": {"base": str(root)}},
            "exult": {"paths": {"bg_flx": str(bundle), "flx": str(common)}},
        },
    )
    install = configured_install("u7bg")
    assert install.resources["exult_flx"] == bundle
    assert install.resources["exult_common_flx"] == common
    assert u7_install.resolve_u7_exult_flx("BG") == str(bundle)
    # What library loaders fall back to ignores [exult.paths].
    assert u7_install.default_u7_exult_flx("BG") is None


def test_library_modules_read_no_config():
    """Only the CLI/UI layer and each game's install module read ``titan.toml``.

    Library code gets an install record or explicit paths from its caller
    (``titan._meta.configured_install``). Covers every titan package; the
    interactive U7 world picker is the one exception.
    """
    import re

    import titan

    package = Path(titan.__file__).parent
    reads = re.compile(
        r"\bresolve_u7_(path|static_and_palette|text_flx|gamedat|exult_flx|"
        r"mod_gamedat|mod_archive)\(|\bget_config\(|\bexult_cfg\(|"
        r"\bgame_config_path\(|\bu8_cfg\(|\bu8_section\(\)"
    )
    allowed = {"u7/target_picker.py"}
    folders = sorted(
        path
        for path in package.iterdir()
        if (path / "__init__.py").is_file() and path.name != "third_party"
    )
    games = {"md", "u6", "u7", "u8", "u9", "uo", "uw1", "uw2", "fonts"}
    assert games <= {folder.name for folder in folders}
    offenders = []
    for folder in folders:
        for path in sorted(folder.rglob("*.py")):
            relative = path.relative_to(package)
            name = relative.as_posix()
            if (
                name in allowed
                or "cli" in relative.parts[:-1]
                or path.name in ("cli.py", "install.py", "installs.py")
                or name.endswith("_ui.py")
            ):
                continue
            for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
                if reads.search(line):
                    offenders.append(f"{name}:{number}: {line.strip()}")
    assert offenders == []


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
    assert u7_install.resolve_u7_mod_gamedat("si", "Test") == str(gamedat)
    assert u7_install.resolve_u7_mod_archive("si", "Test") == str(archive)
    lines = capsys.readouterr().out.splitlines()
    assert all(
        "[OK]" in line for line in lines if "gamedat " in line or "archive " in line
    )


@pytest.mark.parametrize("mod", ["Unplayed", "Nope"])
def test_u7_mod_commands_stop_instead_of_reading_the_base_game(
    setup_workspace, monkeypatch, capsys, mod
):
    from titan.u7.cli import npcs, saves

    root = _u7_install(setup_workspace / "game")
    (root / "gamedat").mkdir()
    (root / "gamedat" / "npc.dat").touch()
    path = Path.cwd() / "titan.toml"
    path.write_text(
        f'[u7bg.game]\nbase="{root.as_posix()}"\n'
        '[u7bg.mods.Unplayed.paths]\nroot="mods/Unplayed"\n'
    )
    monkeypatch.setattr(_config, "_config", _config.load_config(str(path)))

    def base_game(*_args, **_kwargs):
        raise AssertionError("--mod fell back to the base game's GAMEDAT")

    monkeypatch.setattr(u7_install, "resolve_u7_gamedat", base_game)
    report = SimpleNamespace(game="bg", mod=mod, static=str(root / "STATIC"))
    assert npcs.cmd_monster_report(report) == 1
    assert saves.cmd_gamedat_info(SimpleNamespace(game="bg", mod=mod)) == 1
    errors = capsys.readouterr().err
    assert errors.count(f"ERROR: --mod {mod}: no ") == 2
    if mod == "Nope":
        assert "no BG mod or Exult game has that name (found: Unplayed;" in errors
    else:
        assert "Has it been played in Exult yet?" in errors


@pytest.mark.parametrize("configured", [True, False])
def test_u7_gamedat_prefers_configured_then_exult_then_install(
    setup_workspace, monkeypatch, configured
):
    root = _u7_install(setup_workspace / "game")
    profile = setup_workspace / "local" / "Exult" / "blackgate" / "gamedat"
    for folder in (root / "gamedat", profile):
        folder.mkdir(parents=True)
        (folder / "npc.dat").touch()
    path = Path.cwd() / "titan.toml"
    lines = [f'[u7bg.game]\nbase="{root.as_posix()}"\n']
    if configured:
        lines.append(f'[u7bg.paths]\ngamedat="{(root / "gamedat").as_posix()}"\n')
    path.write_text("".join(lines))
    monkeypatch.setattr(_config, "_config", _config.load_config(str(path)))
    expected = root / "gamedat" if configured else profile
    assert Path(u7_install.resolve_u7_gamedat("bg")) == expected
    record = configured_install("u7bg")
    assert record.resources["savegame"] == profile.parent  # Exult's save folder
    assert cli.cmd_config(SimpleNamespace(config=str(path), edit=False)) == 0


def test_u7_exult_cfg_runtime_paths_feed_the_record(setup_workspace, monkeypatch):
    root = _u7_install(setup_workspace / "game")
    live = root / "live"
    live.mkdir()
    (live / "npc.dat").touch()
    (setup_workspace / "saves").mkdir()
    cfg = setup_workspace / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><blackgate><path>{root}</path>"
        f"<savegame_path>{setup_workspace / 'saves'}</savegame_path>"
        "<gamedat_path>live</gamedat_path></blackgate></game></disk></config>"
    )
    monkeypatch.setattr(u7_install, "find_exult_cfg", lambda: cfg)
    record = u7_install.configured_install({}, "u7bg")
    assert record.root == root
    assert record.resources["gamedat"] == live
    assert record.resources["savegame"] == setup_workspace / "saves"


def test_setup_finds_uo_through_the_install_protocol(
    setup_workspace, monkeypatch, capsys
):
    client = setup_workspace / "UO"
    client.mkdir()
    (client / "tiledata.mul").write_bytes(b"\0")
    prompt = "Ultima Online Classic Client base"
    _answer_setup(monkeypatch, {prompt: str(client)})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    path = Path.cwd() / "titan.toml"
    assert tomllib.loads(path.read_text())["uo"]["game"]["base"] == client.as_posix()
    # The configured base is the default; a folder without a client is rejected.
    asked: list[str] = []
    monkeypatch.setattr("builtins.input", lambda text: asked.append(text) or "")
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    shown = next(text for text in asked if text.startswith(prompt))
    assert client.as_posix() in shown.replace("\\", "/")
    assert tomllib.loads(path.read_text())["uo"]["game"]["base"] == client.as_posix()
    empty = setup_workspace / "not-uo"
    empty.mkdir()
    _answer_setup(monkeypatch, {prompt: str(empty)})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert "No Ultima Online Classic Client at that path" in capsys.readouterr().out
    assert tomllib.loads(path.read_text())["uo"]["game"]["base"] == client.as_posix()
