"""Omitted install inputs come from the configured install, in one shared place."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import pytest
import typer
from typer.testing import CliRunner

from titan import _meta
from titan._cli_aliases import alias_group
from titan._input_fill import FILLED, configured_path
from titan._meta import meta
from titan.errors import ConfigFileError


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def use(sections: dict) -> None:
        monkeypatch.setattr("titan._config.get_config", lambda: sections)

    return use


def test_configured_install_applies_paths_over_the_base(config, tmp_path: Path) -> None:
    base = tmp_path / "Ultima6"
    base.mkdir()
    (base / "U6PAL").write_bytes(b"")
    elsewhere = tmp_path / "other.pal"
    elsewhere.write_bytes(b"")
    config(
        {
            "u6": {
                "game": {"base": str(base)},
                "paths": {"palette": str(elsewhere), "look": "LOOK.LZD"},
            }
        }
    )
    install = _meta.configured_install("u6")
    assert install is not None and install.root == base
    assert install.resources["palette"] == elsewhere  # [paths] wins over the base
    assert "look" not in install.resources  # configured, but not there
    assert install.problems == {"look": "NOT FOUND"}


def test_configured_install_needs_a_base(config) -> None:
    config({"u6": {"paths": {"palette": "U6PAL"}}})
    assert _meta.configured_install("u6") is None
    assert _meta.configured_install("u3nes") is None  # no config section at all


def test_configured_path_reports_a_missing_configured_file(config, tmp_path) -> None:
    config({"u6": {"game": {"base": str(tmp_path)}, "paths": {"look": "LOOK.LZD"}}})
    assert configured_path("u6", "root") == tmp_path
    with pytest.raises(ConfigFileError, match=r"\[u6.paths\] look"):
        configured_path("u6", "look")
    config({})
    assert configured_path("u6", "root") is None


def _app() -> typer.Typer:
    app = typer.Typer(name="u6", cls=alias_group({}))
    seen: dict = {}

    @app.command("probe")
    @meta()
    def probe(
        gamedir: Annotated[Optional[str], typer.Option("--game-dir")] = None,
    ) -> None:
        seen["gamedir"] = gamedir

    @app.command("needs")
    @meta()
    def needs(gamedir: Annotated[str, typer.Option("--game-dir")]) -> None:
        seen["gamedir"] = gamedir

    app.seen = seen  # type: ignore[attr-defined]
    return app


def test_an_omitted_input_is_filled_and_an_explicit_one_wins(config, tmp_path) -> None:
    assert "root" in FILLED["u6"]
    config({"u6": {"game": {"base": str(tmp_path)}}})
    app = _app()
    assert CliRunner().invoke(app, ["probe"]).exit_code == 0
    assert app.seen["gamedir"] == str(tmp_path)
    assert CliRunner().invoke(app, ["probe", "--game-dir", "mine"]).exit_code == 0
    assert app.seen["gamedir"] == "mine"


def test_required_inputs_are_never_filled(config, tmp_path) -> None:
    config({"u6": {"game": {"base": str(tmp_path)}}})
    app = _app()
    result = CliRunner().invoke(app, ["needs"])
    assert result.exit_code == 2 and "gamedir" not in app.seen


def test_nothing_is_filled_without_a_configured_install(config) -> None:
    config({})
    app = _app()
    assert CliRunner().invoke(app, ["probe"]).exit_code == 0
    assert app.seen["gamedir"] is None


def test_filling_keeps_command_metadata() -> None:
    # command_metas reads @meta from the callback, wrapped or not.
    info = _meta.command_meta("u6", "object-list")
    assert info is not None and info.resources.get("gamedir") == "root"


# --- UO: CLIENT is a folder or an [uo.installs.*] name -------------------------


def test_uo_default_client_follows_the_named_install(config, tmp_path) -> None:
    named, base = tmp_path / "named", tmp_path / "base"
    named.mkdir()
    config(
        {
            "uo": {
                "game": {"install": "Classic", "base": str(base)},
                "installs": {"classic": {"path": str(named)}},
            }
        }
    )
    install = _meta.configured_install("uo")
    assert install is not None and install.root == named  # the named install wins
    assert install.settings == {"install": "Classic"}
    config({"uo": {"game": {"base": str(base)}}})
    assert _meta.configured_install("uo").root == base
    config({})
    assert _meta.configured_install("uo") is None


def test_uo_unknown_default_install_is_a_config_error(config) -> None:
    from titan.errors import InstallNotFoundError

    config({"uo": {"game": {"install": "nope"}}})
    with pytest.raises(InstallNotFoundError, match="nope"):
        _meta.configured_install("uo")


def test_uo_omitted_client_is_filled_with_the_install_folder(
    config, tmp_path, monkeypatch
) -> None:
    from titan.uo.cli import _common, uo_app

    seen = []

    def resolve(client, config=None):
        seen.append(client)
        raise FileNotFoundError("stop here")

    monkeypatch.setattr(_common, "resolve_install", resolve)
    config({"uo": {"game": {"base": str(tmp_path)}}})
    CliRunner().invoke(uo_app, ["hue-export"])
    assert seen and seen[0] == str(tmp_path)


# --- U8: working folders, and only the map commands are filled -----------------


def test_unextracted_working_folder_is_kept_for_extraction(config, tmp_path) -> None:
    config({"u8": {"game": {"base": str(tmp_path)}, "paths": {"shapes": "shapes/"}}})
    install = _meta.configured_install("u8")
    assert install.resources["shapes"] == tmp_path / "shapes"
    assert install.problems == {"shapes": "NOT EXTRACTED"}
    # Commands extract into it, so filling it isn't an error.
    assert configured_path("u8", "shapes") == tmp_path / "shapes"


def test_u8_fills_only_the_map_commands() -> None:
    from titan._input_fill import _fills

    def fills(command: str) -> dict:
        import typer.main

        from titan.cli import app

        group = typer.main.get_command(app).commands["u8"]
        return _fills(("u8", command), group.commands[command])

    assert fills("map-render") == {
        "fixed": "fixed",
        "shapes": "shapes",
        "globs": "globs",
        "palette": "palette",
        "typeflag": "typeflag",
    }
    # The browsers default --shapes only without --game-dir; they look it up
    # in the install record themselves.
    assert fills("npc-browse") == {}
    assert fills("map-browse") == {}


# --- U9: cli_paths reads the install record; the rules live in titan.u9.inputs --


def test_u9_record_without_a_base_keeps_absolute_paths(config, tmp_path) -> None:
    typenames = tmp_path / "TYPENAME.FLX"
    typenames.write_bytes(b"")
    config({"u9": {"paths": {"typenames": str(typenames)}}})
    install = _meta.configured_install("u9")
    assert install is not None and "base" not in install.settings
    assert install.resources["typenames"] == typenames.resolve()
    assert install.configured == frozenset({"typenames"})


def test_u9_rules_read_only_the_install_they_are_given(tmp_path) -> None:
    from titan.u9.inputs import resolve_u9_input

    typenames = tmp_path / "TYPENAME.FLX"
    typenames.write_bytes(b"")
    install = _meta.Installation(
        "u9", tmp_path, {"typenames": typenames}, configured=frozenset({"typenames"})
    )
    assert resolve_u9_input(None, "typenames", install=install) == str(typenames)
    assert resolve_u9_input(None, "typenames") is None  # nothing configured


def test_u9_mistyped_path_is_a_setup_error(config, tmp_path) -> None:
    from titan.cli import app

    config(
        {"u9": {"game": {"base": str(tmp_path)}, "paths": {"typenames": "NOPE.FLX"}}}
    )
    assert _meta.configured_install("u9").problems == {"typenames": "NOT FOUND"}
    result = CliRunner().invoke(app, ["u9", "typename-dump"])
    assert result.exit_code == 78
    assert "[u9.paths] typenames not found" in result.stderr


def test_configured_keys_are_recorded(config, tmp_path) -> None:
    config({"u6": {"game": {"base": str(tmp_path)}, "paths": {"look": "LOOK.LZD"}}})
    assert _meta.configured_install("u6").configured == frozenset({"look"})
