"""Which file a U9 input means: explicit paths, bare names, numbered resources, companions.

The rules behind U9's game-input defaults. They read the configured install
(*install*, from ``titan._meta.configured_install("u9")``) and never
``titan.toml``; without one, nothing is configured. The CLI's parser
(:mod:`titan.u9.cli_paths`) passes the configured install; library code is
given one by its caller.
"""

from __future__ import annotations

from pathlib import Path

from titan._meta import Installation
from titan.errors import TitanError
from titan.u9.install import U9_FILE_PATHS, existing_u9_path

__all__ = [
    "NO_DEFAULT",
    "U9InputError",
    "paired_u9_texture_key",
    "resolve_u9_input",
]


class U9InputError(TitanError, ValueError):
    """An input name matches more than one install file (the CLI reports a usage error)."""


def _declared(install: Installation | None) -> frozenset[str]:
    return install.configured if install is not None else frozenset()


def _configured(key: str, install: Installation | None) -> Path | None:
    """What *install* has for *key* that exists (``base`` is its root), else ``None``."""
    if install is None:
        return None
    if key == "base":
        return install.root if install.settings.get("base") else None
    return install.resources.get(key)


_NUMBERED_RESOURCES = {"terrain": "static", "fixed": "static", "nonfixed": "runtime"}
_NO_DEFAULT = {"archive", "save_source", *_NUMBERED_RESOURCES}
_TIER_PARTNERS = {
    "bitmap16.flx": "sdinfo16",
    "bitmapc.flx": "sdinfoc",
    "bitmapsh.flx": "sdinfo",
    "sdinfo16.flx": "bitmap16",
    "sdinfoc.flx": "bitmapc",
    "sdinfo.flx": "bitmapsh",
}


def _configured_owner(owner: Path, install: Installation | None) -> bool:
    directories = [
        _configured(key, install)
        for key in ("base", "static", "runtime", "sound", "savegame")
    ]
    if any(
        directory is not None and (owner == directory or owner.parent == directory)
        for directory in directories
    ):
        return True
    return any(owner == _configured(key, install) for key in _declared(install))


def paired_u9_texture_key(
    owner: str, install: Installation | None = None
) -> str | None:
    """Choose the companion tier from its filename or a configured renamed file."""
    path = existing_u9_path(Path(owner).expanduser().absolute())
    paired = _TIER_PARTNERS.get(path.name.casefold())
    if paired:
        return paired
    for key, (_, filename) in U9_FILE_PATHS.items():
        if filename.casefold() not in _TIER_PARTNERS:
            continue
        configured = _configured(key, install)
        if configured is not None and existing_u9_path(configured.absolute()) == path:
            return _TIER_PARTNERS[filename.casefold()]
    return None


def resolve_u9_input(
    value: str | None,
    key: str,
    *,
    owner: str | None = None,
    install: Installation | None = None,
) -> str | None:
    """Prefer explicit U9 inputs, then config; keep external companions together."""
    original_key = key
    if key == "textures":
        key = "bitmap16"
    owner_path = Path(owner).expanduser() if owner else None
    partner_key = paired_u9_texture_key(owner, install) if owner else None
    if owner_path is not None and original_key in {"textures", "sdinfo16"}:
        key = partner_key or key
    folder_key = (
        U9_FILE_PATHS[key][0] if key in U9_FILE_PATHS else _NUMBERED_RESOURCES.get(key)
    )
    if key == "save_source":
        folder_key = "savegame"
    if value is not None:
        path = Path(value).expanduser()
        if path.is_absolute() or path.exists():
            return str(path)
        if len(path.parts) == 1:
            declared = _declared(install)
            for resource_key, (_, filename) in U9_FILE_PATHS.items():
                if (
                    resource_key in declared
                    and path.name.casefold() == filename.casefold()
                ):
                    override = _configured(resource_key, install)
                    if override is not None:
                        return str(override)
        if key in _NUMBERED_RESOURCES and value.isdecimal():
            path = Path(f"{key}.{int(value)}")
        candidates = []
        base = _configured("base", install)
        if base is not None and (len(path.parts) > 1 or path.name == folder_key):
            candidates.append(base / path)
        if owner_path is not None:
            candidates.append(
                (owner_path if owner_path.is_dir() else owner_path.parent) / path
            )
        for directory_key in (
            (folder_key,)
            if folder_key
            else ("static", "sound", "runtime", "savegame", "base")
        ):
            directory = _configured(directory_key, install)
            if directory is not None:
                candidates.append(directory / path)
        matches = list(
            dict.fromkeys(
                existing_u9_path(candidate)
                for candidate in candidates
                if existing_u9_path(candidate).exists()
            )
        )
        if len(matches) > 1 and key == "archive":
            raise U9InputError(f"Ambiguous U9 archive {value!r}; supply its full path.")
        return str(matches[0]) if matches else value

    external = owner_path is not None and not _configured_owner(owner_path, install)
    configured = _configured(key, install)
    if original_key == "textures" and not partner_key:
        configured = _configured("textures", install) or configured
    if not external and configured is not None:
        # The install record holds only paths that exist; a [u9.paths] entry
        # that points at nothing is in install.problems, which the CLI reports.
        return str(configured)
    if owner_path is not None and key in U9_FILE_PATHS:
        resource_folder, filename = U9_FILE_PATHS[key]
        parent = owner_path if owner_path.is_dir() else owner_path.parent
        adjacent = existing_u9_path(parent / filename)
        if adjacent.is_file():
            return str(adjacent)
        if parent.name.casefold() in {"static", "runtime", "sound", "savegame"}:
            sibling = existing_u9_path(parent.parent / resource_folder / filename)
            if sibling.is_file():
                return str(sibling)
    return None


NO_DEFAULT = _NO_DEFAULT
