"""Plain-data facts about titan for front ends (no Typer/Click objects).

Front ends import this the way they import :mod:`titan._config`: it loads no
command modules, so it is cheap enough to read before the CLI tree is built.
Check for each symbol with ``hasattr`` so older titan releases keep working.
"""

from __future__ import annotations

__all__ = [
    "ANY_PARAM",
    "PARAM_KINDS",
    "PATH_KINDS",
    "RECIPE_TYPES",
    "RESULT_KINDS",
    "RecipeField",
    "RecipeSpec",
    "ModInfo",
    "SaveInfo",
    "GAMES",
    "CommandMeta",
    "GameMeta",
    "Installation",
    "command_meta",
    "command_metas",
    "discover_installs",
    "find_installs",
    "get_game",
    "has_install_support",
    "has_mods",
    "has_saves",
    "inspect_install",
    "install_candidates",
    "configured_install",
    "install_config",
    "list_mods",
    "list_saves",
    "meta",
    "path_kind",
    "resolve_save",
]

from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, TypeVar
from titan.errors import InvalidDataError


@dataclass(frozen=True)
class GameMeta:
    """One game on one platform that titan reads."""

    id: str
    """Stable id; equals ``config_section`` when the game has one."""
    game: str
    """Groups platform versions of one game (``u3nes`` and a later ``u3pc``
    both use ``"u3"``). Equals ``id`` for single-platform games."""
    cli_group: str
    """titan command group, e.g. ``"u7"``."""
    platform: str
    """``"dos"``, ``"windows"``, ``"nes"``, ..."""
    config_section: Optional[str]
    """``titan.toml`` section; ``None`` means the game has no install paths
    and every input is a command parameter."""
    game_option: Optional[str] = None
    """Value for commands in a shared group that take ``--game`` (``bg``/``si``)."""
    install: Optional[str] = None
    """Module with the install protocol (``install_candidates``,
    ``discover_installs``, ``install_config``, optionally ``configured_install``);
    ``None`` when titan finds no installs for the game."""
    saves: Optional[str] = None
    """Module with ``list_saves`` and ``resolve_save``, when titan lists saves."""
    mods: Optional[str] = None
    """Module with ``list_mods``, when the game has mods."""
    path_kinds: Optional[str] = None
    """Name of the ``[<section>.paths]`` key -> kind table in :attr:`install`."""


GAMES: tuple[GameMeta, ...] = (
    GameMeta("u3nes", "u3", "u3", "nes", None),
    GameMeta(
        "u6", "u6", "u6", "dos", "u6",
        install="titan.u6.install", saves="titan.u6.saves", path_kinds="U6_PATH_KINDS",
    ),
    GameMeta(
        "md", "md", "md", "dos", "md",
        install="titan.md.install", saves="titan.md.saves", path_kinds="MD_PATH_KINDS",
    ),
    GameMeta("uw1", "uw1", "uw1", "dos", "uw1", install="titan.uw1.install"),
    GameMeta(
        "u7bg", "u7bg", "u7", "dos", "u7bg", game_option="bg",
        install="titan.u7.install", saves="titan.u7.saves", mods="titan.u7.mods",
        path_kinds="U7_PATH_KINDS",
    ),
    GameMeta(
        "u7si", "u7si", "u7", "dos", "u7si", game_option="si",
        install="titan.u7.install", saves="titan.u7.saves", mods="titan.u7.mods",
        path_kinds="U7_PATH_KINDS",
    ),
    GameMeta("uw2", "uw2", "uw2", "dos", "uw2", install="titan.uw2.install"),
    GameMeta(
        "u8", "u8", "u8", "dos", "u8",
        install="titan.u8.install", saves="titan.u8.saves", path_kinds="U8_PATH_KINDS",
    ),
    GameMeta("uo", "uo", "uo", "windows", "uo", install="titan.uo.installs"),
    GameMeta(
        "u9", "u9", "u9", "windows", "u9",
        install="titan.u9.install", saves="titan.u9.saves", path_kinds="U9_PATH_KINDS",
    ),
)  # fmt: skip
"""Every game and platform titan supports. A game absent here is unsupported.

Each row also names the modules that support it (installs, saves, mods, config
path kinds), so a game is registered in one place. They are imported only when
called; a module two rows share (U7 BG and SI) gets the game id."""


def _shared(field_name: str, module: Optional[str]) -> bool:
    return sum(getattr(entry, field_name) == module for entry in GAMES) > 1


_BY_ID = {entry.id: entry for entry in GAMES}


def get_game(game_id: str) -> Optional[GameMeta]:
    """Return the entry for *game_id*, or ``None`` if titan doesn't support it."""
    return _BY_ID.get(game_id)


# --- commands ------------------------------------------------------------

ANY_PARAM = "*"
"""``batch_with`` entry meaning: any parameter other than ``game``."""

PARAM_KINDS = frozenset(
    {
        "save",  # a save slot, save file or save folder for this game
        "mod",  # a mod or Exult custom game key for this game (list_mods)
        "palette",  # a palette file
        "install-file",  # a file inside the game install
        "install-dir",  # a folder of the game install: its root, STATIC, a patch folder
        "input-file",
        "input-dir",
        "output-file",
        "output-dir",
        "working-dir",  # extracted intermediate data, e.g. U8 shapes/ and globs/
        "recipe",  # a TOML recipe that replaces a wizard
        "format",  # picks the output format: a choice (csv -> table, json -> json,
        # anything else -> text) or a --json flag (set -> json, unset -> text)
    }
)
"""What a tagged parameter can mean; front ends pick a widget per kind."""

RESULT_KINDS = frozenset(
    {
        "image",  # an image at the output-file parameter
        "table",  # CSV rows, in the output file or on stdout
        "json",  # one JSON document, in the output file or on stdout
        "text",  # plain text, in the output file or on stdout
        "files",  # new files in the output-dir parameter
        "file",  # one file a front end can't preview (archive, shape, model, save)
    }
)
"""What a command can produce; a ``format`` parameter picks between several."""

_ATTR = "__titan_meta__"
_F = TypeVar("_F", bound=Callable[..., object])


@dataclass(frozen=True)
class CommandMeta:
    """What a command's parameters can't say about it."""

    interactive: bool = False
    """Prompts or opens an interactive UI, so it needs a terminal with stdin."""
    batch_with: tuple[str, ...] = ()
    """For an ``interactive`` command: parameter names that each make it run
    without prompting. Empty means it always prompts. ``ANY_PARAM`` means any
    parameter other than ``game``."""
    params: Mapping[str, str] = field(default_factory=dict)
    """``{parameter name: kind}``, e.g. ``{"nonfixed": "save"}``; kinds are
    from :data:`PARAM_KINDS`."""
    results: tuple[str, ...] = ()
    """What the command can produce, from :data:`RESULT_KINDS`. Empty means
    unknown: show the log."""
    recipe: Optional[str] = None
    """``"module:function"`` returning the :class:`RecipeSpec` its ``recipe``
    parameter reads; use :meth:`recipe_spec`. Named, not imported, so tagging
    a command doesn't load the wizard."""
    resources: Mapping[str, str] = field(default_factory=dict)
    """``{parameter name: install resource}`` for ``install-file``,
    ``install-dir``, ``working-dir`` and ``palette`` parameters a front end can fill from a
    detected install: a key of :attr:`Installation.resources` (and of the
    game's ``[<section>.paths]``), or ``"root"`` for :attr:`Installation.root`.
    A parameter without one is still from the install; titan just can't name
    which file (any FLX, say)."""

    def recipe_spec(self) -> Optional[RecipeSpec]:
        """The recipe this command reads, or ``None``. Imports the recipe module."""
        if not self.recipe:
            return None
        module, _, name = self.recipe.partition(":")
        return getattr(import_module(module), name)()

    def prompts(self, given: Iterable[str]) -> bool:
        """Whether a run with the parameters named in *given* will prompt.

        A parameter named ``interactive`` (an explicit ``--interactive``)
        always asks for prompts.
        """
        if not self.interactive:
            return False
        names = set(given) - {"game"}
        if "interactive" in names:
            return True
        if not self.batch_with:
            return True
        if ANY_PARAM in self.batch_with:
            return not names
        return not names & set(self.batch_with)


def meta(
    *,
    interactive: bool = False,
    batch_with: Iterable[str] = (),
    params: Optional[Mapping[str, str]] = None,
    results: Iterable[str] = (),
    recipe: Optional[str] = None,
    resources: Optional[Mapping[str, str]] = None,
) -> Callable[[_F], _F]:
    """Attach :class:`CommandMeta` to a command function.

    The command's path comes from where the function sits in titan's command
    tree, not from its name, so one function registered twice gets both paths.
    Common inputs (``--gamedir``, U9's configured FILE arguments, U8 options
    named like ``[u8.paths]`` keys, ...) get their kind and resource from
    :mod:`titan._input_kinds`; tag only what those rules don't cover.
    """
    info = CommandMeta(
        interactive,
        tuple(batch_with),
        dict(params or {}),
        tuple(results),
        recipe,
        dict(resources or {}),
    )

    def decorate(fn: _F) -> _F:
        setattr(fn, _ATTR, info)
        return fn

    return decorate


@lru_cache(maxsize=1)
def command_metas() -> dict[tuple[str, ...], CommandMeta]:
    """Every tagged command, keyed by its full path, e.g. ``("u7", "shape-create")``.

    ``params`` and ``resources`` include what :mod:`titan._input_kinds` works
    out for common inputs; explicit tags win. Builds titan's command tree on
    first call (about two seconds).
    """
    import typer.main

    from titan._input_kinds import merge_inputs
    from titan.cli import app

    found: dict[tuple[str, ...], CommandMeta] = {}

    def walk(command: object, path: tuple[str, ...]) -> None:
        children = getattr(command, "commands", None)
        if children:
            for name, child in children.items():
                walk(child, (*path, name))
            return
        info = getattr(getattr(command, "callback", None), _ATTR, None)
        if isinstance(info, CommandMeta):
            params, resources = merge_inputs(path, command.params, info)
            found[path] = replace(info, params=params, resources=resources)

    walk(typer.main.get_command(app), ())
    return found


def command_meta(*path: str) -> Optional[CommandMeta]:
    """Metadata for the command at *path* (``"u7", "shape-create"``), or ``None``."""
    return command_metas().get(path)


# --- recipes -------------------------------------------------------------

RECIPE_TYPES = frozenset({"str", "int", "bool", "path", "int-list"})
"""Value types a :class:`RecipeField` can hold."""


@dataclass(frozen=True)
class RecipeField:
    """One ``[section] key`` of a wizard's TOML recipe."""

    section: str
    key: str
    type: str
    """From :data:`RECIPE_TYPES`."""
    default: object = None
    """What the command uses when the field is left out. ``None`` means the
    command works it out (from a preset, the archive, Exult's config, ...);
    ``help`` says how."""
    help: str = ""
    choices: tuple[object, ...] = ()
    """Allowed values; with ``open`` they are suggestions and any value is allowed."""
    open: bool = False
    """``choices`` are named presets; a path (of ``kind``) is also accepted."""
    kind: Optional[str] = None
    """For paths, what the path is, from :data:`PARAM_KINDS`."""
    required: bool = False
    when: Optional[tuple[str, tuple[object, ...]]] = None
    """``("section.key", values)``: the field only matters when that field has
    one of *values*. A front end shows it while that field is still unset."""

    @property
    def name(self) -> str:
        """``"section.key"``, the name :meth:`RecipeSpec.to_toml` takes."""
        return f"{self.section}.{self.key}"


@dataclass(frozen=True)
class RecipeSpec:
    """The recipe a wizard command reads with its ``param`` option.

    Relative paths in a recipe are relative to the recipe file, so a front end
    that writes one to a temporary folder should pass absolute paths.
    """

    param: str
    """The command parameter that takes the recipe file (``"config"``)."""
    fields: tuple[RecipeField, ...]

    def field(self, name: str) -> Optional[RecipeField]:
        """The field called ``"section.key"``, or ``None``."""
        return next((f for f in self.fields if f.name == name), None)

    def to_toml(self, values: Mapping[str, object]) -> str:
        """A recipe holding *values* (``{"section.key": value}``); ``None`` values
        are left out. Raises ``ValueError`` for unknown fields or bad values."""
        import tomli_w

        data: dict[str, dict[str, object]] = {}
        for name, value in values.items():
            spec = self.field(name)
            if spec is None:
                raise InvalidDataError(f"Unknown recipe field: {name}")
            if value is None:
                continue
            data.setdefault(spec.section, {})[spec.key] = _recipe_value(spec, value)
        missing = [
            f.name
            for f in self.fields
            if f.required and f.key not in data.get(f.section, {})
        ]
        if missing:
            raise InvalidDataError(f"Missing recipe fields: {', '.join(missing)}")
        return tomli_w.dumps(data)


def _recipe_value(spec: RecipeField, value: object) -> object:
    def bad() -> ValueError:
        return ValueError(f"{spec.name}: expected {spec.type}, got {value!r}")

    if spec.type == "bool":
        if not isinstance(value, bool):
            raise bad()
        return value
    if spec.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad()
        result: object = value
    elif spec.type == "int-list":
        if not isinstance(value, (list, tuple)) or any(
            isinstance(v, bool) or not isinstance(v, int) for v in value
        ):
            raise bad()
        return list(value)
    elif isinstance(value, Path):
        result = value.as_posix()
    elif isinstance(value, str) and value:
        result = value
    else:
        raise bad()
    if spec.choices and not spec.open and result not in spec.choices:
        choices = ", ".join(map(str, spec.choices))
        raise InvalidDataError(f"{spec.name}: {value!r} is not one of {choices}")
    return result


# --- saves ---------------------------------------------------------------


@dataclass(frozen=True)
class SaveInfo:
    """One save a front end can offer for a game's ``save`` parameters."""

    slot: str
    """The value to pass to this game's ``save`` parameters, unchanged. Each
    game decides what it is: U8 uses the slot number (``"3"``); games whose
    commands take paths use the full path."""
    path: Path
    name: str
    """The in-game description, or ``""``."""
    modified: float
    """File modification time (``st_mtime``)."""


_SAVE_PROVIDERS = {
    entry.id: (entry.saves, _shared("saves", entry.saves))
    for entry in GAMES
    if entry.saves
}
"""From :data:`GAMES`: game id -> (module, takes game id). The module has ``list_saves(config)`` and
``resolve_save(value, config)``; a shared module (U7 BG and SI) also gets the
game id: ``list_saves(config, game_id)``."""


def has_saves(game_id: str) -> bool:
    """Whether titan can list saves for *game_id*."""
    return game_id in _SAVE_PROVIDERS


def _save_provider(game_id: str):
    entry = _SAVE_PROVIDERS.get(game_id)
    return import_module(entry[0]) if entry else None


def _loaded_config(config: Optional[dict]) -> dict:
    if config is not None:
        return config
    from titan._config import get_config

    return get_config()


def list_saves(
    game_id: str, config: Optional[dict] = None, mod: Optional[str] = None
) -> list[SaveInfo]:
    """Saves for *game_id* found through titan's config; ``[]`` if none or unsupported.

    *config* is a loaded config (:func:`titan._config.load_config`); by default
    the one titan already loaded. *mod* (a :func:`list_mods` key) lists that
    mod's saves instead; ``[]`` for a game without mods.
    """
    provider = _save_provider(game_id)
    if provider is None or (mod and not has_mods(game_id)):
        return []
    extra = (game_id,) if _SAVE_PROVIDERS[game_id][1] else ()
    if mod:
        return provider.list_saves(_loaded_config(config), *extra, mod=mod)
    return provider.list_saves(_loaded_config(config), *extra)


@dataclass(frozen=True)
class ModInfo:
    """One mod (or Exult custom game) a front end can offer for ``mod`` parameters."""

    key: str
    """The value to pass to ``mod`` parameters (``--mod``)."""
    title: str
    kind: str
    """``"mod"`` or ``"exult-game"``."""
    played: bool
    """Whether it has live game state (a GAMEDAT with ``npc.dat``)."""
    paths: Mapping[str, Path] = field(default_factory=dict)
    """What was found: ``install_dir``, ``profile_dir``, ``patch``, ``static``,
    ``gamedat``, ``saves``, ``archive`` (only those it has)."""
    problems: Mapping[str, str] = field(default_factory=dict)
    """Configured path key -> ``"NOT FOUND"``."""


_MOD_PROVIDERS = {entry.id: entry.mods for entry in GAMES if entry.mods}
"""From :data:`GAMES`: game id -> module with ``list_mods(config, game_id)``."""


def has_mods(game_id: str) -> bool:
    """Whether titan can list mods for *game_id* (U7 BG and SI)."""
    return game_id in _MOD_PROVIDERS


def list_mods(game_id: str, config: Optional[dict] = None) -> list[ModInfo]:
    """Mods and Exult custom games for *game_id*, sorted by title; ``[]`` if unsupported.

    *config* is a loaded config; by default the one titan already loaded.
    """
    module = _MOD_PROVIDERS.get(game_id)
    if module is None:
        return []
    return import_module(module).list_mods(_loaded_config(config), game_id)


def resolve_save(
    game_id: str, value: Optional[str], config: Optional[dict] = None
) -> Optional[Path]:
    """The save file or folder a ``save`` parameter value means, or ``None``."""
    provider = _save_provider(game_id)
    if provider is None:
        return Path(value).expanduser() if value else None
    return provider.resolve_save(value, _loaded_config(config))


# --- installs ------------------------------------------------------------


@dataclass(frozen=True)
class Installation:
    """One game install titan found, and what it found in it."""

    game_id: str
    """The :data:`GAMES` id this install belongs to."""
    root: Path
    """The folder ``[<section>.game] base`` names."""
    resources: Mapping[str, Path] = field(default_factory=dict)
    """Files and folders found, keyed like ``[<section>.paths]`` where the game
    has that section (UW1, UW2 and UO name their own keys)."""
    problems: Mapping[str, str] = field(default_factory=dict)
    """Resource key -> what's wrong (``"NOT FOUND"``, ``"INVALID: ..."``) for
    the files a valid install needs. Empty for a usable install."""
    settings: Mapping[str, str] = field(default_factory=dict)
    """Other facts ``[<section>.game]`` records, e.g. U8 ``language``."""
    configured: frozenset[str] = frozenset()
    """For :func:`configured_install`: the resource keys ``[<section>.paths]``
    sets explicitly (the rest were detected). Empty for a detected install."""

    @property
    def valid(self) -> bool:
        """Whether every file the game needs is present and readable."""
        return not self.problems


_INSTALL_PROVIDERS = {
    entry.id: (entry.install, _shared("install", entry.install))
    for entry in GAMES
    if entry.install
}
"""From :data:`GAMES`: game id -> (module, takes game id). The module has
``install_candidates(config)``, ``discover_installs(path)`` and
``install_config(install)``; a shared module (U7 BG and SI) also gets the game
id as the last argument of the first two."""


def has_install_support(game_id: str) -> bool:
    """Whether titan can find and check installs of *game_id*."""
    return game_id in _INSTALL_PROVIDERS


def _install_provider(game_id: str):
    entry = _INSTALL_PROVIDERS.get(game_id)
    if entry is None:
        raise KeyError(f"titan finds no installs for {game_id!r}")
    return import_module(entry[0]), ((game_id,) if entry[1] else ())


def install_candidates(game_id: str, config: Optional[dict] = None) -> list[Path]:
    """Folders worth checking for *game_id*: configured ones first, then the
    usual GOG, Steam and manual locations. Most won't exist."""
    provider, extra = _install_provider(game_id)
    return provider.install_candidates(_loaded_config(config), *extra)


def discover_installs(game_id: str, path: Path) -> list[Installation]:
    """Installs of *game_id* at or a few levels below *path*, valid or not.

    ``[]`` means nothing there looks like the game. An install with
    :attr:`Installation.problems` is the game, but incomplete or damaged.
    """
    provider, extra = _install_provider(game_id)
    return provider.discover_installs(Path(path).expanduser(), *extra)


def inspect_install(game_id: str, path: Path) -> Optional[Installation]:
    """The install of *game_id* at *path* (preferring a valid one), or ``None``."""
    found = discover_installs(game_id, path)
    return next((item for item in found if item.valid), found[0] if found else None)


def find_installs(game_id: str, config: Optional[dict] = None) -> list[Installation]:
    """Every install of *game_id* in :func:`install_candidates`, each root once."""
    found: dict[Path, Installation] = {}
    for candidate in install_candidates(game_id, config):
        for install in discover_installs(game_id, candidate):
            found.setdefault(install.root, install)
    return list(found.values())


def install_config(install: Installation) -> dict:
    """The ``titan.toml`` section that selects *install*, as
    ``{section: {"game": {...}, "paths": {...}, ...}}``."""
    provider, _ = _install_provider(install.game_id)
    section = get_game(install.game_id).config_section  # type: ignore[union-attr]
    return {section: provider.install_config(install)}


def configured_install(
    game_id: str, config: Optional[dict] = None
) -> Optional[Installation]:
    """The install *config* selects for *game_id*: what commands use by default.

    ``root`` is ``[<section>.game] base`` as configured. ``resources`` are
    what :func:`inspect_install` finds there, with each ``[<section>.paths]``
    key on top (relative paths are under the base). A configured path that
    doesn't exist is left out of ``resources`` and reported in ``problems``
    as ``"NOT FOUND"``; a ``working-dir`` that doesn't exist yet stays in
    ``resources`` (commands extract into it) and is reported as
    ``"NOT EXTRACTED"``. ``settings`` are the other ``[<section>.game]`` keys
    (U8 ``language``) over what detection found. ``None`` when the config
    sets no base.

    A game whose install module defines ``configured_install(config)`` decides
    itself (UO: ``[uo.game] install`` names a ``[uo.installs.*]`` entry).
    """
    game = get_game(game_id)
    if game is None or game.config_section is None:
        return None
    if game_id in _INSTALL_PROVIDERS:
        provider, extra = _install_provider(game_id)
        hook = getattr(provider, "configured_install", None)
        if hook is not None:
            return hook(_loaded_config(config), *extra)
    from titan._config import resolve_config_path

    section = _loaded_config(config).get(game.config_section, {})
    base = section.get("game", {}).get("base")
    if not base:
        return None
    root = Path(str(base)).expanduser()
    found = None
    if root.is_dir() and game_id in _INSTALL_PROVIDERS:
        found = inspect_install(game_id, root)
    resources = dict(found.resources) if found else {}
    problems: dict[str, str] = {}
    for key, value in section.get("paths", {}).items():
        if not isinstance(value, (str, Path)):
            continue
        path = resolve_config_path(value, root)
        if path is not None and path.exists():
            resources[key] = path
        elif path is not None and path_kind(game.config_section, key) == "working-dir":
            resources[key] = path
            problems[key] = "NOT EXTRACTED"
        else:
            resources.pop(key, None)
            problems[key] = "NOT FOUND"
    settings = dict(found.settings) if found else {}
    settings.update(
        (key, str(value))
        for key, value in section.get("game", {}).items()
        if key != "base" and isinstance(value, (str, int, float, bool))
    )
    configured = frozenset(
        key
        for key, value in section.get("paths", {}).items()
        if isinstance(value, (str, Path))
    )
    return Installation(game_id, root, resources, problems, settings, configured)


# --- config paths --------------------------------------------------------

PATH_KINDS = frozenset(
    {
        "install-file",  # a file the game install ships
        "install-dir",  # a folder of the game install (STATIC, runtime, a mod's patch)
        "save",  # one save: a save file, or U7's live gamedat folder
        "save-dir",  # the folder that holds the game's saves
        "working-dir",  # extracted intermediate data a command creates (U8 shapes/)
    }
)
"""What a ``[<section>.paths]`` key names; see :func:`path_kind`."""

_PATH_KIND_TABLES = {
    entry.config_section: (entry.install, entry.path_kinds)
    for entry in GAMES
    if entry.config_section and entry.install and entry.path_kinds
}
"""From :data:`GAMES`: config section -> (module, table). Each game keeps its table beside its
install rules; it is imported only when asked for."""


def path_kind(config_section: str, key: str) -> Optional[str]:
    """What the ``[<config_section>.paths]`` key *key* names, from :data:`PATH_KINDS`.

    U7 mod sections (``[u7bg.mods."<name>".paths]``) use their game's section.
    ``None`` means titan doesn't know the key: treat it as an install path.
    Only ``install-file`` and ``install-dir`` must exist for the game to work;
    a missing ``working-dir`` just hasn't been extracted yet.
    """
    entry = _PATH_KIND_TABLES.get(config_section)
    if entry is None:
        return None
    return getattr(import_module(entry[0]), entry[1]).get(key)
