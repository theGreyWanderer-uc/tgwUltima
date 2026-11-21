"""Kinds and install resources for common command inputs, so ``@meta`` needn't repeat them.

:func:`titan._meta.command_metas` merges these into each command's
``params`` / ``resources``; an explicit ``@meta(params=..., resources=...)``
tag always wins. The rules cover inputs that mean the same thing everywhere:

* ``--gamedir`` / ``--game-dir`` (and UO's ``client``): the install's root.
* U9 parameters titan fills from ``[u9.paths]`` (:data:`titan.u9.cli_paths.U9_COMMAND_INPUTS`).
* U8 parameters named like a ``[u8.paths]`` key (``--fixed``, ``--shapes``, ...).
* U7 ``--static``, ``--patch`` / ``--patch-dir``, ``--text`` and their spellings.

Imported only by :func:`~titan._meta.command_metas`, which builds the command
tree anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Mapping

if TYPE_CHECKING:
    from titan._meta import CommandMeta

ROOT = "root"
"""Resource name for :attr:`titan._meta.Installation.root`."""

RESOURCE_KINDS = frozenset({"install-file", "install-dir", "working-dir", "palette"})
"""Parameter kinds that can name an install resource (a palette usually ships with the game)."""

_ROOT_NAMES = {"gamedir", "game_dir"}
_UO_ROOT_NAMES = {"client"}

# U7 option -> (kind, [u7bg]/[u7si] paths key)
_U7_INPUTS = {
    "static": ("install-dir", "static"),
    "base_static": ("install-dir", "static"),
    "patch": ("install-dir", "patch"),
    "patch_dir": ("install-dir", "patch"),
    "text": ("install-file", "text"),
}

# U9 resources whose cli_paths name differs from the [u9.paths] key.
_U9_ALIASES = {"textures": "bitmap16", "fixed_reference": "fixed", "base": ROOT}
_U9_DIRS = {"static", "runtime", "sound", ROOT}


def _u9(command: str, name: str) -> tuple[str, str | None] | None:
    from titan.u9.cli_paths import U9_COMMAND_INPUTS

    resource = U9_COMMAND_INPUTS.get(command, {}).get(name)
    if resource is None:
        return None
    if resource == "save_source":
        return "save", None
    if resource == "archive":  # any FLX in the install; there's no default one
        return "install-file", None
    resource = _U9_ALIASES.get(resource, resource)
    return ("install-dir" if resource in _U9_DIRS else "install-file"), resource


def _u8(name: str) -> tuple[str, str | None] | None:
    from titan.u8.install import U8_PATH_KINDS

    kind = U8_PATH_KINDS.get(name)
    if kind is None:
        return None
    if kind in RESOURCE_KINDS:
        return kind, name
    return kind, None  # "save": the save picker handles it


def infer_input(path: tuple[str, ...], name: str) -> tuple[str, str | None] | None:
    """``(kind, resource)`` for parameter *name* of the command at *path*, if a rule covers it."""
    game = path[0] if len(path) > 1 else None
    if name in _ROOT_NAMES or (game == "uo" and name in _UO_ROOT_NAMES):
        return "install-dir", ROOT
    if game == "u9":
        return _u9(path[-1], name)
    if game == "u8":
        return _u8(name)
    if game == "u7":
        return _U7_INPUTS.get(name)
    return None


def merge_inputs(
    path: tuple[str, ...], params: Iterable[object], info: CommandMeta
) -> tuple[dict[str, str], dict[str, str]]:
    """The command's ``params`` and ``resources``: the rules, then its own tags.

    An explicit kind replaces an inferred one. The inferred resource stays
    only when the explicit kind agrees: the same kind, or ``palette`` for an
    inferred ``install-file`` (the install's palette).
    """
    kinds: dict[str, str] = {}
    resources: dict[str, str] = {}
    explicit: Mapping[str, str] = info.params
    for param in params:
        name = getattr(param, "name", None)
        if not name or getattr(param, "is_flag", False):
            continue
        inferred = infer_input(path, name)
        if inferred is None:
            continue
        kind, resource = inferred
        chosen = explicit.get(name, kind)
        kinds[name] = chosen
        agrees = chosen == kind or (chosen == "palette" and kind == "install-file")
        if resource is not None and agrees:
            resources[name] = resource
    kinds.update(explicit)
    resources.update(info.resources)
    return kinds, resources
