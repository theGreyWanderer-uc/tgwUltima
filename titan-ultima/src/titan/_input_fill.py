"""Fill omitted install inputs from the configured install, before a command runs.

Each command's ``resources`` (see :attr:`titan._meta.CommandMeta.resources`)
say which install file or folder a parameter means. When the parameter is
omitted, :class:`titan._cli_aliases.AliasGroup` fills it from
:func:`titan._meta.configured_install`, so the command (and the library code
below it) receives an explicit path and never reads ``titan.toml`` itself.

A game opts resources in through :data:`FILLED`, one game at a time, and only
for inputs its commands already defaulted from config: required parameters
stay required.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from titan._input_kinds import ROOT

_U8_MAP_INPUTS = frozenset({"fixed", "shapes", "globs", "palette", "typeflag"})

FILLED: dict[str, frozenset[str] | dict[str, frozenset[str]]] = {
    "u6": frozenset({ROOT}),
    "md": frozenset({ROOT}),
    "uw1": frozenset({ROOT}),
    "uw2": frozenset({ROOT}),
    "uo": frozenset({ROOT}),
    # Only U8's map commands defaulted their inputs from config; the browsers
    # look their (conditional) defaults up in the install record themselves.
    "u8": {
        command: _U8_MAP_INPUTS
        for command in ("map-render", "map-render-all", "map-sample", "map-sample-all")
    },
}
"""CLI group -> the resources its omitted parameters are filled with, for
every command or (a dict) per command."""

_GAME_IDS = {"u6": "u6", "md": "md", "uw1": "uw1", "uw2": "uw2", "uo": "uo", "u8": "u8"}
"""CLI group -> :data:`titan._meta.GAMES` id, for groups with one game."""

_WRAPPED = "__titan_fills_inputs__"


def configured_path(game_id: str, resource: str) -> Path | None:
    """Where the configured install keeps *resource*, or ``None`` if it isn't set.

    A ``[<section>.paths]`` entry that points at a missing file is a
    :class:`~titan.errors.ConfigFileError`, not a silent fallback.
    """
    from titan._meta import configured_install, get_game
    from titan.errors import ConfigFileError

    install = configured_install(game_id)
    if install is None:
        return None
    if resource == ROOT:
        return install.root
    if install.problems.get(resource) == "NOT FOUND":
        from titan._config import get_config, resolve_config_path

        section = get_game(game_id).config_section  # type: ignore[union-attr]
        value = get_config().get(section, {}).get("paths", {}).get(resource)
        missing = resolve_config_path(value, install.root)
        raise ConfigFileError(f"[{section}.paths] {resource} not found: {missing}")
    return install.resources.get(resource)


def _fills(path: tuple[str, ...], command: Any) -> dict[str, str]:
    """``{parameter: resource}`` this command gets filled, from its metadata."""
    group = path[0] if len(path) > 1 else None
    allowed = FILLED.get(group or "")
    if isinstance(allowed, dict):
        allowed = allowed.get(path[-1])
    info = getattr(getattr(command, "callback", None), "__titan_meta__", None)
    if not allowed or info is None:
        return {}
    from titan._input_kinds import merge_inputs

    _, resources = merge_inputs(path, command.params, info)
    by_name = {param.name: param for param in command.params}
    return {
        name: resource
        for name, resource in resources.items()
        if resource in allowed and not by_name[name].required
    }


def wrap_command(path: tuple[str, ...], command: Any) -> Any:
    """Make *command* fill its omitted install inputs before running (once)."""
    callback = getattr(command, "callback", None)
    if callback is None or getattr(callback, _WRAPPED, False):
        return command
    fills = _fills(path, command)
    if not fills:
        return command
    game_id = _GAME_IDS[path[0]]
    as_path = {
        param.name
        for param in command.params
        if type(param.type).__name__ == "TyperPath"
    }

    @functools.wraps(callback)
    def filled(**kwargs: Any) -> Any:
        for name, resource in fills.items():
            if kwargs.get(name) is None:
                value = configured_path(game_id, resource)
                if value is not None:
                    kwargs[name] = value if name in as_path else str(value)
        return callback(**kwargs)

    setattr(filled, _WRAPPED, True)
    command.callback = filled
    return command


__all__ = ["FILLED", "configured_path", "wrap_command"]
