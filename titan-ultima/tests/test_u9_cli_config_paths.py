"""Exercise config-backed inputs through every public U9 command's parser."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from typer.core import TyperGroup, TyperOption
from typer.main import get_command
from typer.testing import CliRunner

from titan import _config
from titan.u9 import cli, save_browser_ui
from titan.u9.cli_paths import U9_COMMAND_INPUTS, resolve_u9_input
from titan.u9.install import U9_FILE_PATHS

COMMANDS = cast(TyperGroup, get_command(cli.u9_app)).commands


@pytest.fixture
def configured_install(tmp_path, monkeypatch):
    root = tmp_path / "GOG Games/Ultima 9"
    for folder in ("static", "sound", "runtime", "savegame"):
        (root / folder).mkdir(parents=True)
    for _, (folder, filename) in U9_FILE_PATHS.items():
        (root / folder / filename).write_bytes(bytes(1024))
    for folder, name in (
        ("static", "terrain.7"),
        ("static", "fixed.7"),
        ("runtime", "nonfixed.7"),
        ("runtime", "nonfixed.8"),
        ("static", "custom.flx"),
    ):
        (root / folder / name).write_bytes(b"fixture")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(
        _config, "_config", {"u9": {"game": {"base": str(root)}, "paths": {}}}
    )
    return root


def _capture_handler(command, monkeypatch):
    seen = []
    callback = inspect.unwrap(COMMANDS[command].callback)
    handlers = [name for name in callback.__code__.co_names if name.startswith("cmd_")]
    if command == "save-browse":
        monkeypatch.setattr(
            save_browser_ui,
            "run_u9_save_browser",
            lambda **kwargs: seen.append(SimpleNamespace(**kwargs)) or 0,
        )
    else:
        assert len(handlers) == 1
        monkeypatch.setattr(cli, handlers[0], lambda args: seen.append(args) or 0)
    return seen


def test_every_u9_command_has_a_path_policy():
    assert set(COMMANDS) == set(U9_COMMAND_INPUTS)


@pytest.mark.parametrize("command", COMMANDS)
def test_all_commands_accept_config_inputs_without_changing_user_inputs(
    configured_install, tmp_path, monkeypatch, command
):
    seen = _capture_handler(command, monkeypatch)
    args = [command]
    resources = U9_COMMAND_INPUTS[command]
    for parameter in COMMANDS[command].params:
        if not parameter.required:
            continue
        if isinstance(parameter, TyperOption):
            args.append(parameter.opts[0])
        role = resources.get(parameter.name)
        if role == "archive":
            value = "custom.flx"
        elif role in {"fixed", "terrain", "nonfixed"}:
            value = f"{role}.{8 if parameter.name == 'right' else 7}"
        elif "integer" in parameter.type.name:
            value = "1"
        elif "float" in parameter.type.name:
            value = "0.5"
        elif hasattr(parameter.type, "choices"):
            value = str(parameter.type.choices[0])
        else:
            value = str(tmp_path / f"user-{parameter.name}")
        args.append(value)
    result = CliRunner().invoke(cli.u9_app, args)
    assert result.exit_code == 0, (command, args, result.output, result.exception)
    assert len(seen) == 1
    if command == "texture-info":
        assert seen[0].entry_id == 1
        assert Path(seen[0].textures) == configured_install / "static/bitmap16.flx"
    if command == "animation-pose-export":
        assert seen[0].animation_id == seen[0].model_id == 1
        assert Path(seen[0].animations) == configured_install / "static/anim.flx"
        assert Path(seen[0].sappear) == configured_install / "static/sappear.flx"
    if command in {"text-import", "typename-import"}:
        assert seen[0].csv == str(tmp_path / "user-csv_path")
    if command == "flx-pack":
        assert seen[0].output == str(tmp_path / "user-output")


@pytest.mark.parametrize(
    "tokens, expected_id", [(["4423"], 4423), (["bitmap16.flx", "4423"], 4423)]
)
def test_texture_ids_keep_their_meaning(
    configured_install, monkeypatch, tokens, expected_id
):
    seen = _capture_handler("texture-info", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["texture-info", *tokens])
    assert result.exit_code == 0, result.output
    assert seen[0].entry_id == expected_id
    assert Path(seen[0].textures) == configured_install / "static/bitmap16.flx"


def test_texture_import_keeps_image_required_and_output_explicit(
    configured_install, tmp_path, monkeypatch
):
    seen = _capture_handler("texture-import", monkeypatch)
    image = str(tmp_path / "replacement.png")
    output = str(tmp_path / "patched.flx")
    result = CliRunner().invoke(
        cli.u9_app, ["texture-import", "4423", image, "--output", output]
    )
    assert result.exit_code == 0, result.output
    assert seen[0].entry_id == 4423
    assert seen[0].image == image
    assert seen[0].output == output


def test_external_archive_uses_its_own_companions(
    configured_install, tmp_path, monkeypatch
):
    external = tmp_path / "another install/static"
    external.mkdir(parents=True)
    for name in (
        "sappear.flx",
        "bitmap16.flx",
        "ankh.pal",
        "TYPES.DAT",
        "TYPENAME.FLX",
    ):
        (external / name).touch()
    seen = _capture_handler("model-export", monkeypatch)
    result = CliRunner().invoke(
        cli.u9_app,
        ["model-export", str(external / "sappear.flx"), "12", "--no-preview"],
    )
    assert result.exit_code == 0, result.output
    assert Path(seen[0].textures) == external / "bitmap16.flx"
    assert Path(seen[0].palette) == external / "ankh.pal"
    assert Path(seen[0].types) == external / "TYPES.DAT"
    (external / "ankh.pal").unlink()
    assert (
        resolve_u9_input(None, "palette", owner=str(external / "bitmap16.flx")) is None
    )


def test_selected_texture_tier_uses_matching_table(configured_install, monkeypatch):
    seen = _capture_handler("map-render", monkeypatch)
    result = CliRunner().invoke(
        cli.u9_app, ["map-render", "7", "--textures=bitmapC.flx", "--no-objects"]
    )
    assert result.exit_code == 0, result.output
    assert Path(seen[0].terrain) == configured_install / "static/terrain.7"
    assert Path(seen[0].sdinfo) == configured_install / "static/sdInfoC.flx"


def test_save_npc_mode_selects_processes_not_shipped_table(
    configured_install, monkeypatch
):
    seen = _capture_handler("npc-show", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["npc-show", "42", "--save"])
    assert result.exit_code == 0, result.output
    assert Path(seen[0].file) == configured_install / "savegame/processes.dat"


def test_missing_config_is_actionable_and_generic_archive_is_not_guessed(monkeypatch):
    monkeypatch.setattr(_config, "_config", {})
    result = CliRunner().invoke(cli.u9_app, ["texture-info", "4423"])
    assert result.exit_code == 2
    assert "titan setup" in result.output
    result = CliRunner().invoke(cli.u9_app, ["flx-list"])
    assert result.exit_code == 2
    assert "Missing argument" in result.output


def test_config_overrides_and_absolute_explicit_paths_win(
    configured_install, tmp_path, monkeypatch
):
    custom = tmp_path / "custom palette.pal"
    custom.write_bytes(bytes(1024))
    _config._config["u9"]["paths"]["palette"] = str(custom)
    seen = _capture_handler("palette-info", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["palette-info"])
    assert result.exit_code == 0, result.output
    assert Path(seen[0].file) == custom
    explicit = tmp_path / "explicit.pal"
    result = CliRunner().invoke(cli.u9_app, ["palette-info", str(explicit)])
    assert result.exit_code == 0, result.output
    assert Path(seen[-1].file) == explicit


def test_real_palette_command_loads_root_config(configured_install, tmp_path):
    from titan.cli import app

    config = tmp_path / "titan.toml"
    config.write_text(
        f'[u9.game]\nbase="{configured_install.as_posix()}"\n', encoding="utf-8"
    )
    result = CliRunner().invoke(app, ["--config", str(config), "u9", "palette-info"])
    assert result.exit_code == 0, result.output
    assert "ankh.pal" in result.output


def test_help_describes_configuration_fallback():
    result = CliRunner().invoke(cli.u9_app, ["texture-info", "--help"])
    assert result.exit_code == 0
    assert "u9.paths" in result.output


def test_renamed_texture_and_table_overrides_stay_paired(configured_install, tmp_path):
    from titan.u9.cli_paths import paired_u9_texture_key

    texture = tmp_path / "custom compressed.flx"
    table = tmp_path / "custom metadata.flx"
    texture.touch()
    table.touch()
    _config._config["u9"]["paths"].update(
        {"bitmapc": str(texture), "sdinfoc": str(table)}
    )
    assert paired_u9_texture_key(str(texture)) == "sdinfoc"
    assert resolve_u9_input(None, "sdinfo16", owner=str(texture)) == str(table)


def test_interspersed_animation_files_and_ids_keep_existing_syntax(
    configured_install, monkeypatch
):
    seen = _capture_handler("animation-pose-export", monkeypatch)
    result = CliRunner().invoke(
        cli.u9_app,
        [
            "animation-pose-export",
            str(configured_install / "static/anim.flx"),
            "12",
            str(configured_install / "static/sappear.flx"),
            "42",
            "--no-preview",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen[0].animation_id == 12
    assert seen[0].model_id == 42


def test_end_of_options_preserves_search_terms(configured_install, monkeypatch):
    seen = _capture_handler("text-search", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["text-search", "--", "--help"])
    assert result.exit_code == 0, result.output
    assert seen[0].needle == "--help"


def test_external_save_game_dir_does_not_inject_configured_maps(
    configured_install, tmp_path, monkeypatch
):
    seen = _capture_handler("save-browse", monkeypatch)
    external = tmp_path / "external saves"
    external.mkdir()
    result = CliRunner().invoke(
        cli.u9_app, ["save-browse", "--game-dir", str(external)]
    )
    assert result.exit_code == 0, result.output
    assert seen[0].game_dir == external
    assert seen[0].static_directory is None
    assert seen[0].fixed_reference_directory is None


def test_comparison_save_is_explicit_but_can_use_configured_save_folder(
    configured_install, monkeypatch
):
    archive = configured_install / "savegame/u9game1.sav"
    archive.touch()
    seen = _capture_handler("npc-diff", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["npc-diff", "u9game1.sav"])
    assert result.exit_code == 0, result.output
    assert Path(seen[0].save_file) == archive
    assert Path(seen[0].file) == configured_install / "runtime/NPC.FLX"


def test_default_texture_override_selects_its_matching_sdinfo(
    configured_install, monkeypatch
):
    _config._config["u9"]["paths"]["textures"] = "static/bitmapC.flx"
    seen = _capture_handler("map-render", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["map-render", "7"])
    assert result.exit_code == 0, result.output
    assert Path(seen[0].textures) == configured_install / "static/bitmapC.flx"
    assert Path(seen[0].sdinfo) == configured_install / "static/sdInfoC.flx"


def test_generic_archive_selector_uses_specific_config_override(
    configured_install, tmp_path, monkeypatch
):
    speech = tmp_path / "patched speech.flx"
    speech.touch()
    _config._config["u9"]["paths"]["speech"] = str(speech)
    seen = _capture_handler("sound-list", monkeypatch)
    result = CliRunner().invoke(cli.u9_app, ["sound-list", "Speech.flx"])
    assert result.exit_code == 0, result.output
    assert Path(seen[0].file) == speech
