"""Old option spellings that titan still accepts after a rename.

titan standardized its option names across games (``--game-dir`` for an
install root, ``--save`` for a save, ``--output-dir`` for a folder of results,
``--format`` for the output format). Earlier spellings keep working: each
command group rewrites them before parsing, so scripts, shell history and
in-process callers (``CliRunner``) all still run. Help shows only the new name.

An alias applies to a command only when that command has the new spelling and
not the old one, so one group-wide table can't change a command that still
uses the old name for something else.
"""

from __future__ import annotations

__all__ = [
    "AliasGroup",
    "RootGroup",
    "TextOrJson",
    "alias_group",
    "renamed_options",
    "root_group",
]

from enum import Enum
from typing import Callable, Mapping, Sequence, TypeVar

from typer.core import TyperGroup

Aliases = Mapping[str, Sequence[str]]
"""Old option -> the tokens that replace it, e.g. ``{"--json": ("--format", "json")}``."""

_ATTR = "__titan_option_aliases__"
_F = TypeVar("_F", bound=Callable[..., object])


class TextOrJson(str, Enum):
    """``--format`` choice for commands that print text or JSON."""

    text = "text"
    json = "json"


def renamed_options(aliases: Mapping[str, str | Sequence[str]]) -> Callable[[_F], _F]:
    """Accept old spellings for one command (on top of its group's table)."""
    table = {old: _tokens(new) for old, new in aliases.items()}

    def decorate(fn: _F) -> _F:
        setattr(fn, _ATTR, table)
        return fn

    return decorate


def _tokens(value: str | Sequence[str]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(value)


def _options(command: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(command, "params", ()):
        names.update(getattr(param, "opts", ()))
        names.update(getattr(param, "secondary_opts", ()))
    return names


def rewrite_args(args: Sequence[str], command: object, aliases: Aliases) -> list[str]:
    """*args* for *command* with old option spellings replaced."""
    table = {**aliases, **getattr(getattr(command, "callback", None), _ATTR, {})}
    if not table:
        return list(args)
    known = _options(command)
    result: list[str] = []
    for index, token in enumerate(args):
        if token == "--":
            return result + list(args[index:])
        name, equals, value = token.partition("=")
        new = table.get(name)
        if new is None or name in known or new[0] not in known:
            result.append(token)
        elif equals and len(new) == 1:
            result.append(f"{new[0]}={value}")
        else:
            result.extend(new)
            if equals:
                result.append(value)
    return result


class AliasGroup(TyperGroup):
    """A Typer group that accepts its commands' old option spellings."""

    option_aliases: Aliases = {}

    def _command_index(self, args: Sequence[str]) -> int | None:
        """Where the subcommand name sits in *args*, after this group's options."""
        takes_value = {
            opt
            for param in self.params
            if not getattr(param, "is_flag", False)
            and param.param_type_name == "option"
            for opt in param.opts
        }
        index = 0
        while index < len(args):
            token = args[index]
            if token == "--" or not token.startswith("-"):
                return index if token != "--" else None
            if token in takes_value:
                index += 1
            index += 1
        return None

    def invoke(self, ctx):  # type: ignore[override]
        # Library code logs instead of printing; show it on the terminal.
        from titan._log import install_cli_logging

        install_cli_logging()
        return super().invoke(ctx)

    def get_command(self, ctx, cmd_name):  # type: ignore[override]
        # Omitted install inputs are filled from the configured install
        # (titan._input_fill), whether this group runs under titan or alone.
        command = super().get_command(ctx, cmd_name)
        if command is not None and not hasattr(command, "commands") and self.name:
            from titan._input_fill import wrap_command
            from titan._meta import GAMES

            groups = {game.cli_group for game in GAMES}
            path = (self.name, cmd_name) if self.name in groups else (cmd_name,)
            wrap_command(path, command)
        if command is not None and not hasattr(command, "commands"):
            # Tagged output parameters go to TITAN_RESULTS_FILE (titan._results).
            from titan._results import wrap_outputs

            wrap_outputs(command)
        return command

    def parse_args(self, ctx, args):  # type: ignore[override]
        index = self._command_index(args)
        if index is not None:
            command = self.get_command(ctx, args[index])
            if command is not None and not hasattr(command, "commands"):
                args = [
                    *args[: index + 1],
                    *rewrite_args(args[index + 1 :], command, self.option_aliases),
                ]
        return super().parse_args(ctx, args)


def alias_group(aliases: Mapping[str, str | Sequence[str]]) -> type[AliasGroup]:
    """An :class:`AliasGroup` class for a Typer app: ``typer.Typer(cls=alias_group(...))``."""
    table = {old: _tokens(new) for old, new in aliases.items()}
    return type("AliasGroup", (AliasGroup,), {"option_aliases": table})


_CONFIG_HINT = (
    "`titan config` shows the settings titan is using; `titan setup` finds installs."
)


class RootGroup(AliasGroup):
    """titan's root group: reports titan's errors cleanly and writes run results.

    A :class:`~titan.errors.TitanError` or ``OSError`` that escapes a command
    prints one ``ERROR:`` line (plus a hint for config problems) and exits
    with :func:`titan.errors.exit_code`. Ctrl+C or a prompt whose input ended
    prints ``Cancelled.`` and exits ``EXIT_CODES["cancelled"]``. Other exceptions are bugs and
    propagate with their traceback. Either way the ``TITAN_RESULTS_FILE``
    document (:mod:`titan._results`) is written.
    """

    def invoke(self, ctx):  # type: ignore[override]
        import typer

        from titan._results import write_results
        from titan.errors import ConfigError, TitanError, exit_code

        from titan._wizard_ui import PromptCancelled
        from titan.errors import EXIT_CODES

        status = 0
        try:
            return super().invoke(ctx)
        except (typer.Abort, KeyboardInterrupt, EOFError, PromptCancelled) as stop:
            # Ctrl+C, or a prompt whose input ended. Click would print
            # "Aborted!" and exit 1, which reads as a failure.
            status = EXIT_CODES["cancelled"]
            typer.echo("Cancelled.", err=True)
            raise typer.Exit(status) from stop
        except (TitanError, OSError) as error:
            status = exit_code(error)
            typer.echo(f"ERROR: {error}", err=True)
            if isinstance(error, ConfigError):
                typer.echo(_CONFIG_HINT, err=True)
            raise typer.Exit(status) from error
        except typer.Exit as stop:
            status = stop.exit_code
            raise
        except SystemExit as stop:
            status = stop.code if isinstance(stop.code, int) else 1
            raise
        except Exception:
            status = 70
            raise
        finally:
            write_results(status)


def root_group(aliases: Mapping[str, str | Sequence[str]]) -> type[RootGroup]:
    """The :class:`RootGroup` class for titan's top-level app."""
    table = {old: _tokens(new) for old, new in aliases.items()}
    return type("RootGroup", (RootGroup,), {"option_aliases": table})
