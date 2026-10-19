"""Named Ultima Online client installs from ``titan.toml``.

Several client flavours can be configured side by side, for example the EA
Classic Client and a freeshard client::

    [uo.game]
    install = "classic"            # default when CLIENT is omitted

    [uo.installs.classic]
    path   = "C:/Ultima/UltimaOnlineClassicClient"
    output = "D:/data/uodata/classic"
    label  = "EA Ultima Online Classic Client"

    [uo.installs.uof]
    path   = "G:/Games/UOForever/UO"
    output = "D:/data/uodata/uof"
    multis = "mul"                 # multi source: auto, uop or mul
    maps   = "auto"                # terrain source: auto, uop or mul
    # Server-side references, overriding [uo.reference] for this install:
    # server_profile (preferred), or house_placement_tool, regions_xml, emulator_scripts

A command's CLIENT argument may be an install name or a directory. A
directory that matches a configured install's path picks up that install's
output root and source preferences too. The older ``[uo.game] base`` setting
still works as the default directory.
"""

from __future__ import annotations

__all__ = ["UOInstall", "configured_installs", "resolve_install"]

from dataclasses import dataclass
from pathlib import Path

from titan._config import get_config

_SOURCE_CHOICES = ("auto", "uop", "mul")
# Emulator references an install may override from [uo.reference].
_REFERENCE_KEYS = ("server_profile", "house_placement_tool", "regions_xml", "emulator_scripts")


@dataclass(frozen=True)
class UOInstall:
    """One configured client install."""

    name: str
    path: Path
    output: Path | None = None
    label: str = ""
    multis: str = "auto"
    maps: str = "auto"
    reference: dict[str, str] | None = None


def configured_installs(config: dict | None = None) -> dict[str, UOInstall]:
    """Return ``[uo.installs.*]`` entries keyed by lower-case name."""
    config = get_config() if config is None else config
    installs: dict[str, UOInstall] = {}
    for name, entry in config.get("uo", {}).get("installs", {}).items():
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        output = entry.get("output")
        installs[name.lower()] = UOInstall(
            name=name,
            path=Path(str(entry["path"])).expanduser(),
            output=Path(str(output)).expanduser() if output else None,
            label=str(entry.get("label", "")),
            multis=_source_choice(entry.get("multis"), name, "multis"),
            maps=_source_choice(entry.get("maps"), name, "maps"),
            reference={
                key: str(entry[key]) for key in _REFERENCE_KEYS if entry.get(key)
            },
        )
    return installs


def resolve_install(
    client: str | None, config: dict | None = None
) -> tuple[Path, UOInstall | None]:
    """Resolve a CLIENT argument to ``(directory, install or None)``.

    Raises ``FileNotFoundError`` when nothing is configured or the directory
    does not exist.
    """
    config = get_config() if config is None else config
    installs = configured_installs(config)
    game = config.get("uo", {}).get("game", {})

    install: UOInstall | None = None
    if client is None:
        default_name = game.get("install")
        if default_name:
            install = installs.get(str(default_name).lower())
            if install is None:
                raise FileNotFoundError(
                    f"[uo.game] install = {default_name!r} is not a configured "
                    f"[uo.installs.*] entry"
                )
        elif game.get("base"):
            client = str(game["base"])
        else:
            raise FileNotFoundError(
                "UO client directory not configured; pass CLIENT (a directory or "
                "install name), or set [uo.game] install/base in titan.toml"
            )
    elif client.lower() in installs:
        install = installs[client.lower()]

    if install is not None:
        path = install.path
    else:
        path = Path(client).expanduser()
        install = _install_for_path(path, installs)

    if not path.is_dir():
        raise FileNotFoundError(f"client directory not found: {path}")
    return path, install


def _install_for_path(path: Path, installs: dict[str, UOInstall]) -> UOInstall | None:
    try:
        target = path.resolve()
    except OSError:
        return None
    for install in installs.values():
        try:
            if install.path.resolve() == target:
                return install
        except OSError:
            continue
    return None


def _source_choice(value: object, name: str, key: str) -> str:
    choice = str(value or "auto").lower()
    if choice not in _SOURCE_CHOICES:
        raise ValueError(
            f"[uo.installs.{name}] {key} must be one of {', '.join(_SOURCE_CHOICES)}"
        )
    return choice
