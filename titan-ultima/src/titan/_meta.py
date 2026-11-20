"""Plain-data facts about titan for front ends (no Typer/Click objects).

Front ends import this the way they import :mod:`titan._config`: it loads no
command modules, so it is cheap enough to read before the CLI tree is built.
Check for each symbol with ``hasattr`` so older titan releases keep working.
"""

from __future__ import annotations

__all__ = [
    "ANY_PARAM",
    "PARAM_KINDS",
    "RESULT_KINDS",
    "GAMES",
    "CommandMeta",
    "GameMeta",
    "command_meta",
    "command_metas",
    "get_game",
    "meta",
]

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Iterable, Mapping, Optional, TypeVar


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


GAMES: tuple[GameMeta, ...] = (
    GameMeta("u3nes", "u3", "u3", "nes", None),
    GameMeta("u6", "u6", "u6", "dos", "u6"),
    GameMeta("md", "md", "md", "dos", "md"),
    GameMeta("uw1", "uw1", "uw1", "dos", "uw1"),
    GameMeta("u7bg", "u7bg", "u7", "dos", "u7bg", game_option="bg"),
    GameMeta("u7si", "u7si", "u7", "dos", "u7si", game_option="si"),
    GameMeta("uw2", "uw2", "uw2", "dos", "uw2"),
    GameMeta("u8", "u8", "u8", "dos", "u8"),
    GameMeta("uo", "uo", "uo", "windows", "uo"),
    GameMeta("u9", "u9", "u9", "windows", "u9"),
)
"""Every game and platform titan supports. A game absent here is unsupported."""

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
        "palette",  # a palette file
        "install-file",  # a file inside the game install
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
) -> Callable[[_F], _F]:
    """Attach :class:`CommandMeta` to a command function.

    The command's path comes from where the function sits in titan's command
    tree, not from its name, so one function registered twice gets both paths.
    """
    info = CommandMeta(
        interactive, tuple(batch_with), dict(params or {}), tuple(results)
    )

    def decorate(fn: _F) -> _F:
        setattr(fn, _ATTR, info)
        return fn

    return decorate


@lru_cache(maxsize=1)
def command_metas() -> dict[tuple[str, ...], CommandMeta]:
    """Every tagged command, keyed by its full path, e.g. ``("u7", "shape-create")``.

    Builds titan's command tree on first call (about two seconds).
    """
    import typer.main

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
            found[path] = info

    walk(typer.main.get_command(app), ())
    return found


def command_meta(*path: str) -> Optional[CommandMeta]:
    """Metadata for the command at *path* (``"u7", "shape-create"``), or ``None``."""
    return command_metas().get(path)
