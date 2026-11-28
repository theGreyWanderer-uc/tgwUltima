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

__all__ = [
    "NOT_CONFIGURED",
    "UOInstall",
    "configured_install",
    "configured_installs",
    "default_client",
    "detect_uo_install",
    "discover_installs",
    "install_candidates",
    "install_config",
    "looks_like_uo_root",
    "resolve_install",
    "uo_install_candidates",
]

from dataclasses import dataclass
from pathlib import Path

from titan._config import get_config
from titan.errors import InstallNotFoundError
from titan._meta import Installation
from titan import _stores

_CORE_FILES = {
    "art": "artLegacyMUL.uop",
    "gumps": "gumpartLegacyMUL.uop",
    "tiledata": "tiledata.mul",
    "hues": "hues.mul",
}
"""Core Classic Client files; any one of them identifies a client folder."""

_SOURCE_CHOICES = ("auto", "uop", "mul")
# Emulator references an install may override from [uo.reference].
_REFERENCE_KEYS = (
    "server_profile",
    "house_placement_tool",
    "regions_xml",
    "emulator_scripts",
)


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

    Raises :class:`~titan.errors.InstallNotFoundError` (a ``FileNotFoundError``)
    when nothing is configured or the directory does not exist.
    """
    config = get_config() if config is None else config
    installs = configured_installs(config)

    install: UOInstall | None = None
    if client is None:
        client = default_client(config)
        if client is None:
            raise InstallNotFoundError(NOT_CONFIGURED)
    elif client.lower() in installs:
        install = installs[client.lower()]

    if install is not None:
        path = install.path
    else:
        path = Path(client).expanduser()
        install = _install_for_path(path, installs)

    if not path.is_dir():
        raise InstallNotFoundError(f"client directory not found: {path}")
    return path, install


NOT_CONFIGURED = (
    "UO client directory not configured; pass CLIENT (a directory or "
    "install name), or set [uo.game] install/base in titan.toml"
)


def default_client(config: dict | None = None) -> str | None:
    """The client folder an omitted CLIENT means: ``[uo.game] install``'s path, else base.

    ``None`` when neither is set. A default install name with no
    ``[uo.installs.*]`` entry is an :class:`~titan.errors.InstallNotFoundError`.
    """
    config = get_config() if config is None else config
    game = config.get("uo", {}).get("game", {})
    default_name = game.get("install")
    if default_name:
        install = configured_installs(config).get(str(default_name).lower())
        if install is None:
            raise InstallNotFoundError(
                f"[uo.game] install = {default_name!r} is not a configured "
                f"[uo.installs.*] entry"
            )
        return str(install.path)
    if game.get("base"):
        return str(Path(str(game["base"])).expanduser())
    return None


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


def looks_like_uo_root(path: Path) -> bool:
    """Recognize a Classic Client folder by its core art and tile data files."""
    return any((path / name).is_file() for name in _CORE_FILES.values())


def uo_install_candidates() -> list[Path]:
    """List the standard EA installer and manual Classic Client folders."""
    candidates: list[Path] = []
    for drive in _stores.drives():
        for path in [
            Path(
                f"{drive}:\\Program Files (x86)\\Electronic Arts\\Ultima Online Classic"
            ),
            Path(f"{drive}:\\Ultima\\UltimaOnlineClassicClient"),
            Path(f"{drive}:\\Ultima Online Classic"),
        ]:
            if path not in candidates:
                candidates.append(path)
    return candidates


def detect_uo_install() -> Path | None:
    """Return the first standard location that holds a Classic Client."""
    for candidate in uo_install_candidates():
        if candidate.exists() and looks_like_uo_root(candidate):
            return candidate
    return None


def install_candidates(config: dict) -> list[Path]:
    """Install protocol: ``[uo.game] base``, ``[uo.installs.*]`` paths, then the
    standard Classic Client folders."""
    candidates: list[Path] = []
    base = config.get("uo", {}).get("game", {}).get("base")
    if base:
        candidates.append(Path(str(base)).expanduser())
    for entry in config.get("uo", {}).get("installs", {}).values():
        if isinstance(entry, dict) and entry.get("path"):
            candidates.append(Path(str(entry["path"])).expanduser())
    return list(dict.fromkeys([*candidates, *uo_install_candidates()]))


def discover_installs(path: Path) -> list[Installation]:
    """Install protocol: the client folder at *path*, if it is one."""
    try:
        if not looks_like_uo_root(path):
            return []
    except OSError:
        return []
    resources = {
        key: path / name for key, name in _CORE_FILES.items() if (path / name).is_file()
    }
    return [Installation("uo", path.absolute(), resources)]


def configured_install(config: dict) -> Installation | None:
    """Install protocol hook: the client an omitted CLIENT means (see :func:`default_client`).

    ``settings["install"]`` names the ``[uo.installs.*]`` entry when the
    default is a named install.
    """
    client = default_client(config)
    if client is None:
        return None
    path = Path(client)
    found = discover_installs(path) if path.is_dir() else []
    resources = dict(found[0].resources) if found else {}
    name = config.get("uo", {}).get("game", {}).get("install")
    settings = {"install": str(name)} if name else {}
    return Installation("uo", path, resources, {}, settings)


def install_config(install: Installation) -> dict:
    """Install protocol: ``[uo.game] base``. Named ``[uo.installs.*]`` entries
    are for several clients side by side; add those by hand."""
    return {"game": {"base": install.root.as_posix()}}
