"""``titan._meta`` stays cheap to import and agrees with titan itself."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

import titan
from titan import _meta
from titan.cli import app

SRC = Path(titan.__file__).parent


def test_meta_imports_without_typer_or_cli() -> None:
    code = (
        "import sys, titan._meta; "
        "bad = [m for m in ('typer', 'click', 'titan.cli') if m in sys.modules]; "
        "print(','.join(bad))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_ids_are_unique_and_match_config_sections() -> None:
    ids = [meta.id for meta in _meta.GAMES]
    assert len(ids) == len(set(ids))
    for meta in _meta.GAMES:
        if meta.config_section is not None:
            assert meta.id == meta.config_section
        assert _meta.get_game(meta.id) is meta
    assert _meta.get_game("u4") is None


def test_every_cli_group_exists() -> None:
    groups = set(typer.main.get_command(app).commands)  # type: ignore[attr-defined]
    for meta in _meta.GAMES:
        assert meta.cli_group in groups, meta.id


def test_shared_groups_tell_games_apart_with_game_option() -> None:
    by_group: dict[str, list[_meta.GameMeta]] = {}
    for meta in _meta.GAMES:
        by_group.setdefault(meta.cli_group, []).append(meta)
    for group, metas in by_group.items():
        if len(metas) > 1:
            options = [meta.game_option for meta in metas]
            assert None not in options and len(set(options)) == len(options), group


def test_every_config_section_is_read_by_titan() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
        if path.name != "_meta.py"
    )
    for meta in _meta.GAMES:
        if meta.config_section is not None:
            assert f'"{meta.config_section}"' in sources, meta.id


def _leaf_commands():
    def walk(command, path):
        children = getattr(command, "commands", None)
        if children:
            for name, child in children.items():
                yield from walk(child, (*path, name))
        else:
            yield path, command

    yield from walk(typer.main.get_command(app), ())


def test_tagged_names_are_real_parameters() -> None:
    commands = dict(_leaf_commands())
    assert _meta.command_metas(), "no command carries metadata"
    for path, info in _meta.command_metas().items():
        names = {param.name for param in commands[path].params}
        for name in (*info.params, *info.batch_with):
            if name != _meta.ANY_PARAM:
                assert name in names, f"{' '.join(path)}: no parameter {name!r}"
        assert not info.batch_with or info.interactive, path


def test_interactive_commands_are_tagged() -> None:
    interactive = {
        path for path, info in _meta.command_metas().items() if info.interactive
    }
    browsers = {
        path
        for path, _ in _leaf_commands()
        if path[-1].endswith("-browse") or path == ("setup",)
    }
    assert browsers <= interactive
    for path in (
        ("u7", "font-create"),
        ("u7", "shape-create"),
        ("u7", "map-render"),
        ("u8", "world-query"),
        ("u8", "egg-query"),
        ("dialogue", "copy"),
    ):
        assert path in interactive, path
    shape_export = _meta.command_meta("u7", "shape-export")
    assert shape_export is None or not shape_export.interactive


def test_prompts_follows_batch_parameters() -> None:
    always = _meta.command_meta("u8", "save-browse")
    by_config = _meta.command_meta("u7", "font-create")
    by_any = _meta.command_meta("u7", "map-render")
    assert always is not None and by_config is not None and by_any is not None
    assert always.prompts(["source", "output"])
    assert by_config.prompts([]) and by_config.prompts(["output"])
    assert not by_config.prompts(["config"])
    assert by_any.prompts([]) and by_any.prompts(["game"])
    assert not by_any.prompts(["game", "full"])
    assert by_any.prompts(["full", "interactive"])
    assert not _meta.CommandMeta().prompts([])


def test_parameter_kinds_use_the_vocabulary() -> None:
    for path, info in _meta.command_metas().items():
        for name, kind in info.params.items():
            assert kind in _meta.PARAM_KINDS, f"{' '.join(path)} {name}: {kind!r}"


def test_every_save_spelling_is_tagged() -> None:
    def kind(path: tuple[str, ...], name: str) -> str | None:
        info = _meta.command_meta(*path)
        return info.params.get(name) if info else None

    assert kind(("u8", "map-render"), "nonfixed") == "save"
    assert kind(("md", "map-render"), "savegame") == "save"
    assert kind(("u7", "map-render"), "gamedat") == "save"
    assert kind(("u6", "flags-set"), "savegame") == "save"
    assert kind(("u9", "npc-list"), "save") == "save"
    # U9's --nonfixed is one region file, not a whole save.
    assert kind(("u9", "map-render"), "nonfixed") is None


def test_wizard_tags_and_kinds_share_one_decorator() -> None:
    info = _meta.command_meta("u7", "map-render")
    assert info is not None and info.interactive
    assert info.params["gamedat"] == "save"
    assert info.params["output"] == "output-file"


def test_results_use_the_vocabulary() -> None:
    for path, info in _meta.command_metas().items():
        for result in info.results:
            assert result in _meta.RESULT_KINDS, f"{' '.join(path)}: {result!r}"
        if "files" in info.results:
            assert "output-dir" in info.params.values(), path


def test_results_for_known_commands() -> None:
    def results(*path: str) -> tuple[str, ...]:
        info = _meta.command_meta(*path)
        return info.results if info else ()

    assert results("u8", "map-render") == ("image",)
    assert results("u7", "shape-export") == ("files",)
    assert set(results("uw2", "shape-info")) == {"json", "text"}
    info = _meta.command_meta("uw2", "shape-info")
    assert info is not None and info.params["json_output"] == "format"
