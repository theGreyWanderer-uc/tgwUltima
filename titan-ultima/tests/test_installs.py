"""The install protocol in ``titan._meta`` works the same way for every game."""

from __future__ import annotations

import subprocess
import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from titan import _config, _meta, cli
from titan.u7.flex import U7FlexArchive

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep discovery away from real installs, Exult settings and config."""
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


def _files(root: Path, names) -> Path:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).touch()
    return root


def _uw1(root: Path) -> Path:
    return _files(root, ["DATA/PALS.DAT", "DATA/LEV.ARK", "DATA/W64.TR", "DATA/F16.TR"])


def _uw2(root: Path) -> Path:
    return _files(
        root, ["DATA/PALS.DAT", "DATA/LEV.ARK", "DATA/T64.TR", "DATA/BYT.ARK"]
    )


def _u6(root: Path) -> Path:
    from titan.u6.install import U6_RESOURCE_NAMES

    names = [name for key, name in U6_RESOURCE_NAMES.items() if key != "savegame"]
    return _files(root, names)


def _md(root: Path) -> Path:
    from titan.md.install import MD_RESOURCE_NAMES

    names = [name for key, name in MD_RESOURCE_NAMES.items() if key != "savegame"]
    return _files(root, names)


def _u8(base: Path, lang: str = "ENGLISH") -> Path:
    static = base / lang / "STATIC" if lang else base
    _files(static, ["FIXED.DAT", "U8PAL.PAL", "U8SHAPES.FLX"])
    if lang:
        _files(base / lang, ["USECODE/EUSECODE.FLX"])
    return base


def _u7(root: Path) -> Path:
    static = root / "STATIC"
    static.mkdir(parents=True)
    for name, records in {
        "SHAPES.VGA": [bytes(64)],
        "PALETTES.FLX": [bytes([20, 30, 40]) * 256],
        "TEXT.FLX": [b"test shape\0"],
    }.items():
        archive = U7FlexArchive()
        archive.records = records
        archive.save(str(static / name))
    return root


def _u9(root: Path) -> Path:
    from titan.u9.flx_writer import build_flx
    from titan.u9.install import U9_RESOURCE_NAMES

    static = root / "STATIC"
    static.mkdir(parents=True)
    for key, name in U9_RESOURCE_NAMES.items():
        (static / name.upper()).write_bytes(
            bytes(1024) if key == "palette" else build_flx({0: bytes(48)})
        )
    return root


def _uo(root: Path) -> Path:
    return _files(root, ["tiledata.mul", "hues.mul"])


BUILDERS = {
    "u6": _u6,
    "md": _md,
    "uw1": _uw1,
    "uw2": _uw2,
    "u7bg": _u7,
    "u8": _u8,
    "u9": _u9,
    "uo": _uo,
}
FOLDERS = {"u7bg": "ultima7bg"}


def test_every_configured_game_has_install_support() -> None:
    for game in _meta.GAMES:
        assert _meta.has_install_support(game.id) == (game.config_section is not None)
    assert not _meta.has_install_support("u3nes")
    with pytest.raises(KeyError):
        _meta.install_candidates("u3nes")


@pytest.mark.parametrize(
    "module", sorted({m for m, _ in _meta._INSTALL_PROVIDERS.values()})
)
def test_providers_implement_the_protocol(module: str) -> None:
    provider = import_module(module)
    for name in ("install_candidates", "discover_installs", "install_config"):
        assert callable(getattr(provider, name)), (module, name)


@pytest.mark.parametrize("game_id", sorted(BUILDERS))
def test_discover_inspect_and_config_round_trip(workspace: Path, game_id: str) -> None:
    root = BUILDERS[game_id](workspace / "games" / FOLDERS.get(game_id, game_id))
    install = _meta.inspect_install(game_id, root)
    assert install is not None and install.valid, install
    assert install.game_id == game_id
    assert install.root == root.absolute()
    assert install.resources
    config = _meta.install_config(install)
    section = _meta.get_game(game_id).config_section
    assert list(config) == [section]
    assert config[section]["game"]["base"] == root.absolute().as_posix()
    # The section is plain TOML data a front end can write.
    from titan._setup_config import section_lines

    assert tomllib.loads("\n".join(section_lines(config))) == config


@pytest.mark.parametrize("game_id", sorted(BUILDERS))
def test_other_folders_are_not_installs(workspace: Path, game_id: str) -> None:
    empty = workspace / "nothing"
    empty.mkdir()
    assert _meta.discover_installs(game_id, empty) == []
    assert _meta.inspect_install(game_id, empty) is None


def test_find_installs_starts_with_the_configured_base(workspace: Path) -> None:
    root = _u6(workspace / "custom" / "U6")
    config = {"u6": {"game": {"base": str(root)}}}
    assert _meta.install_candidates("u6", config)[0] == root
    assert [item.root for item in _meta.find_installs("u6", config)] == [
        root.absolute()
    ]


def test_underworld_games_tell_each_other_apart(workspace: Path) -> None:
    bundle = workspace / "home" / "GOG Games" / "Ultima Underworld 1+2"
    uw1 = _uw1(bundle / "UW")
    uw2 = _uw2(bundle / "UW2")
    assert [item.root for item in _meta.find_installs("uw1", {})] == [uw1.absolute()]
    assert [item.root for item in _meta.find_installs("uw2", {})] == [uw2.absolute()]
    # The DATA folder itself is accepted and resolves to the install root.
    assert _meta.inspect_install("uw2", uw2 / "DATA").root == uw2.absolute()
    assert _meta.inspect_install("uw1", uw2) is None


def test_incomplete_underworld_install_reports_problems(workspace: Path) -> None:
    root = _uw1(workspace / "UW")
    (root / "DATA" / "PALS.DAT").unlink()
    install = _meta.inspect_install("uw1", root)
    assert install is not None and not install.valid
    assert install.problems == {"palette": "NOT FOUND"}


def test_u8_language_folder_is_a_setting(workspace: Path) -> None:
    base = _u8(workspace / "Ultima 8")
    install = _meta.inspect_install("u8", base)
    assert install.settings["language"] == "ENGLISH"
    assert "usecode" in install.resources
    section = _meta.install_config(install)["u8"]
    assert section["game"]["language"] == "ENGLISH"
    assert section["paths"]["fixed"] == "FIXED.DAT"
    flat = _meta.inspect_install("u8", _u8(workspace / "flat", lang=""))
    assert flat.settings["language"] == ""


def test_u7_games_are_kept_apart(workspace: Path) -> None:
    collection = workspace / "Ultima VII - Complete"
    bg = _u7(collection / "ultima7bg")
    si = _u7(collection / "serpentisle")
    assert [i.root for i in _meta.discover_installs("u7bg", collection)] == [
        bg.absolute()
    ]
    assert [i.root for i in _meta.discover_installs("u7si", collection)] == [
        si.absolute()
    ]
    # An explicitly chosen root with an unhelpful name counts as the asked-for game.
    odd = _u7(workspace / "my copy")
    assert _meta.inspect_install("u7si", odd).settings["variant"] == "serpentisle"
    section = _meta.install_config(_meta.inspect_install("u7bg", bg))["u7bg"]
    assert section["paths"]["shapes"] == "STATIC/SHAPES.VGA"
    assert section["paths"]["gamedat"] == "gamedat/"


def test_install_functions_load_no_command_tree() -> None:
    code = (
        "import sys, titan._meta as m; "
        "[m.has_install_support(g.id) for g in m.GAMES]; "
        "bad = [n for n in ('typer', 'click', 'titan.cli') if n in sys.modules]; "
        "print(','.join(bad))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def _answer(monkeypatch: pytest.MonkeyPatch, answers: dict[str, str] | None = None):
    answers = answers or {}

    def answer(prompt: str) -> str:
        return next((v for k, v in answers.items() if prompt.startswith(k)), "")

    monkeypatch.setattr("builtins.input", answer)


def test_setup_detects_both_underworld_games(workspace, monkeypatch) -> None:
    bundle = workspace / "home" / "GOG Games" / "Ultima Underworld 1+2"
    uw1 = _uw1(bundle / "UW")
    uw2 = _uw2(bundle / "UW2")
    _answer(monkeypatch)
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    saved = tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert saved["uw1"] == {"game": {"base": uw1.absolute().as_posix()}}
    assert saved["uw2"] == {"game": {"base": uw2.absolute().as_posix()}}


def test_setup_rejects_a_folder_without_underworld_data(workspace, monkeypatch, capsys):
    elsewhere = workspace / "elsewhere"
    elsewhere.mkdir()
    _answer(monkeypatch, {"Ultima Underworld II base": str(elsewhere)})
    assert cli.cmd_setup(SimpleNamespace(config=None)) == 0
    assert "uw2" not in tomllib.loads((Path.cwd() / "titan.toml").read_text())
    assert "No Ultima Underworld II data at that path" in capsys.readouterr().out
