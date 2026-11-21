"""``titan._meta`` stays cheap to import and agrees with titan itself."""

from __future__ import annotations

import re
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


def test_every_visible_command_is_tagged() -> None:
    """A command without ``@meta`` hasn't been reviewed for front ends.

    Tag what the command produces, even when it only prints (``results=("text",)``);
    ``@meta()`` with no fields means "reviewed, nothing to say". Hidden commands
    (deprecated aliases) are exempt.
    """

    def visible(command, path):
        children = getattr(command, "commands", None)
        if children:
            for name, child in children.items():
                if not child.hidden:
                    yield from visible(child, (*path, name))
        else:
            yield path

    tagged = set(_meta.command_metas())
    missing = [
        " ".join(path)
        for path in visible(typer.main.get_command(app), ())
        if path not in tagged
    ]
    assert not missing, "commands without @meta: " + ", ".join(missing)


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
    assert kind(("u9", "npc-diff"), "save_file") == "save"
    # U9's --save is a flag that says FILE is a save; it isn't a save itself.
    assert kind(("u9", "npc-list"), "save") is None
    # U9's --nonfixed is one region file from the install, not a whole save.
    assert kind(("u9", "map-render"), "nonfixed") == "install-file"


def test_save_and_path_kinds_are_never_flags() -> None:
    commands = dict(_leaf_commands())
    for path, info in _meta.command_metas().items():
        params = {param.name: param for param in commands[path].params}
        for name, kind in info.params.items():
            if kind != "format":
                assert not getattr(params[name], "is_flag", False), (path, name, kind)


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
    assert info is not None and info.params["output_format"] == "format"


def test_path_kinds_use_the_vocabulary_and_cover_install_tables() -> None:
    from titan.md.install import MD_RESOURCE_NAMES
    from titan.u6.install import U6_RESOURCE_NAMES
    from titan.u7.install import RESOURCE_NAMES
    from titan.u8.install import U8_STATIC_FILES
    from titan.u9.install import U9_FILE_PATHS

    install_keys = {
        "u6": U6_RESOURCE_NAMES,
        "md": MD_RESOURCE_NAMES,
        "u7bg": RESOURCE_NAMES,
        "u7si": RESOURCE_NAMES,
        "u8": U8_STATIC_FILES,
        "u9": U9_FILE_PATHS,
    }
    for meta in _meta.GAMES:
        section = meta.config_section
        for key in install_keys.get(section or "", ()):
            assert _meta.path_kind(section, key) in _meta.PATH_KINDS, (section, key)
    for section, (module, table) in _meta._PATH_KIND_TABLES.items():
        assert _meta.get_game(section) is not None, section
        kinds = getattr(__import__(module, fromlist=[table]), table)
        assert set(kinds.values()) <= _meta.PATH_KINDS, section


def test_path_kind_for_known_keys() -> None:
    assert _meta.path_kind("u8", "fixed") == "install-file"
    assert _meta.path_kind("u8", "savegame") == "save-dir"
    assert _meta.path_kind("u8", "nonfixed") == "save"
    assert _meta.path_kind("u8", "shapes") == "working-dir"
    assert _meta.path_kind("u8", "globs") == "working-dir"
    assert _meta.path_kind("u7bg", "static") == "install-dir"
    assert _meta.path_kind("u7si", "gamedat") == "save"
    assert _meta.path_kind("u7bg", "patch") == "install-dir"
    assert _meta.path_kind("u9", "processes") == "save"
    assert _meta.path_kind("u9", "nonfixed") == "install-file"
    assert _meta.path_kind("u9", "runtime") == "install-dir"
    assert _meta.path_kind("u6", "savegame") == "save-dir"
    assert _meta.path_kind("md", "objlist") == "save"
    assert _meta.path_kind("u8", "no-such-key") is None
    assert _meta.path_kind("uo", "base") is None


def test_path_kind_loads_no_command_tree() -> None:
    code = (
        "import sys, titan._meta as m; "
        "[m.path_kind(s, 'x') for s in ('u6', 'md', 'u7bg', 'u8', 'u9')]; "
        "bad = [n for n in ('typer', 'click', 'titan.cli') if n in sys.modules]; "
        "print(','.join(bad))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


# --- input kinds -------------------------------------------------------------

_PATH_HELP = re.compile(
    r"\b(files?|folders?|director(y|ies)|dirs?|paths?|archives?|flx|vga|static"
    r"|gamedat|install(ation)?|patch|csv|json|png|toml|images?)\b",
    re.IGNORECASE,
)
_NOT_PATH_TYPES = {
    "BoolParamType",
    "IntParamType",
    "IntRange",
    "FloatParamType",
    "FloatRange",
    "TyperChoice",
}
# Strings whose help mentions files but which aren't paths.
_NOT_PATHS = {
    "title",  # u7 flex-create: archive title
    "mod",  # a mod's name
    "only",  # u9 texture-frame-report filter
    "metric",  # u9 color-cube-lookup
    "diagnostics_format",  # u9 animation-library-plan: csv or json
    "container",  # uo: auto, uop or mul
    "suffix",  # uo: alternate file-set suffix
    "size",  # uo map-render WIDTHxHEIGHT
    "name",  # uo map-render output stem
}


def _visible_leaves():
    def walk(command, path):
        children = getattr(command, "commands", None)
        if children:
            for name, child in children.items():
                if not child.hidden:
                    yield from walk(child, (*path, name))
        else:
            yield path, command

    yield from walk(typer.main.get_command(app), ())


def _path_like(param) -> bool:
    if getattr(param, "is_flag", False):
        return False
    kind = type(param.type).__name__
    if kind in _NOT_PATH_TYPES:
        return False
    return (
        kind == "TyperPath"
        or param.name in ("file", "gamedir", "game_dir")
        or bool(_PATH_HELP.search(param.help or ""))
    )


def test_every_input_path_has_a_kind() -> None:
    """A file or folder parameter needs a kind for the front end to pick a widget.

    Common inputs get theirs from ``titan._input_kinds``; tag the rest with
    ``@meta(params=...)`` (and ``resources=`` for install files). The dialogue
    pipeline is left as it is on purpose.
    """
    metas = _meta.command_metas()
    missing = [
        f"{' '.join(path)} {param.name}"
        for path, command in _visible_leaves()
        if path[0] != "dialogue"
        for param in command.params
        if _path_like(param)
        and param.name not in _NOT_PATHS
        and param.name not in metas[path].params
    ]
    assert not missing, "path parameters without a kind: " + ", ".join(missing)


def test_resources_name_install_keys() -> None:
    from titan._input_kinds import RESOURCE_KINDS, ROOT

    sections = {"u7": "u7bg"}
    for path, command in _visible_leaves():
        info = _meta.command_metas().get(path)
        if not info or not info.resources:
            continue
        section = sections.get(path[0], path[0])
        table = _meta._PATH_KIND_TABLES.get(section)
        keys = (
            set(getattr(__import__(table[0], fromlist=["x"]), table[1]))
            if table
            else set()
        )
        for name, resource in info.resources.items():
            where = f"{' '.join(path)} {name}"
            assert info.params.get(name) in RESOURCE_KINDS, where
            assert resource == ROOT or resource in keys, f"{where}: {resource!r}"


def test_input_kinds_for_known_commands() -> None:
    def tag(path, name):
        info = _meta.command_meta(*path)
        return info.params.get(name), info.resources.get(name)

    assert tag(("u9", "flx-list"), "file") == ("install-file", None)  # any FLX
    assert tag(("u9", "model-export"), "textures") == ("install-file", "bitmap16")
    assert tag(("u9", "npc-diff"), "save_file") == ("save", None)
    assert tag(("u8", "map-render"), "shapes") == ("working-dir", "shapes")
    assert tag(("u8", "map-render"), "palette") == ("palette", "palette")
    assert tag(("u7", "egg-query"), "static") == ("install-dir", "static")
    assert tag(("u7", "shape-export"), "file") == ("install-file", "shapes")
    assert tag(("u7", "save-info"), "file") == ("save", None)
    assert tag(("u6", "look-dump"), "file") == ("install-file", "look")
    assert tag(("uw2", "map-render"), "gamedir") == ("install-dir", "root")
    assert tag(("uo", "art-export"), "client") == ("install-dir", "root")
    # Explicit tags win: a positional that takes a save or a loose file.
    assert tag(("u8", "npc-browse"), "source") == ("input-file", None)
