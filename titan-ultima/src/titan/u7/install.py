"""Bounded U7 install discovery and shared configuration/Exult path resolution."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from titan import _config
from titan.fonts.exult_cfg import find_exult_cfg, parse_exult_cfg
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette

RESOURCE_NAMES = {
    "shapes": "SHAPES.VGA",
    "palette": "PALETTES.FLX",
    "text": "TEXT.FLX",
}
_SKIP_DIRS = {"mods", "patch", "saves", "gamedat", "static"}


def existing_path(path: Path) -> Path:
    """Respect file casing on Unix for installations copied from DOS/Windows."""
    if path.exists():
        return path.resolve()
    if path.parent == path:
        return path
    parent = existing_path(path.parent)
    try:
        return next(
            (
                entry
                for entry in parent.iterdir()
                if entry.name.lower() == path.name.lower()
            ),
            parent / path.name,
        )
    except OSError:
        return parent / path.name


def install_roots(candidate: Path, *, max_depth: int = 2) -> list[Path]:
    """Find game roots within two levels, visiting at most 128 directories.

    Include both games in complete collections. Do not follow symlinks or scan
    mod/patch/save directories, which can contain misleading partial archives.
    """
    candidate = existing_path(candidate.expanduser())
    if candidate.name.lower() == "static":
        candidate = candidate.parent
    pending = deque([(candidate, 0)])
    roots: list[Path] = []
    visited = 0
    while pending and visited < 128:
        directory, depth = pending.popleft()
        visited += 1
        static = existing_path(directory / "STATIC")
        if static.is_dir() and any(
            existing_path(static / name).is_file() for name in RESOURCE_NAMES.values()
        ):
            roots.append(directory)
            # Nested mods are not additional installations of this game.
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            continue
        for child in children:
            if (
                len(pending) + visited < 128
                and child.name.lower() not in _SKIP_DIRS
                and not child.is_symlink()
                and child.is_dir()
            ):
                pending.append((child, depth + 1))
    return roots


def install_game(root: Path) -> str:
    """Recognize SI roots from their own name or their install wrapper."""
    for part in reversed(root.parts):
        name = part.lower()
        if "serpent" in name or name.endswith("si"):
            return "SI"
        if name == "ultima7" or "black gate" in name or name.endswith("bg"):
            return "BG"
    return "BG"


@dataclass
class U7Installation:
    root: Path
    game: str
    paths: dict[str, Path]
    checks: dict[str, str]

    @property
    def valid(self) -> bool:
        return all(status == "OK" for status in self.checks.values())


def check_resource(key: str, path: Path) -> str:
    """Report missing/damaged U7 resources consistently in setup and config."""
    if not path.is_file():
        return "NOT FOUND"
    try:
        if key != "palette" or path.suffix.lower() != ".pal":
            archive = U7FlexArchive.from_file(str(path), strict=True)
            if not any(archive.records):
                raise ValueError("Archive has no populated records")
        if key == "palette":
            U7Palette.from_file(str(path), palette_index=0)
    except (OSError, ValueError) as error:
        return f"INVALID: {error}"
    return "OK"


def inspect_install(
    root: Path,
    game: str | None = None,
    *,
    static: Path | None = None,
    resources: dict[str, Path] | None = None,
) -> U7Installation:
    """Validate expected Flex archives and decode main palette record zero."""
    root = existing_path(root.expanduser().absolute())
    static = existing_path(static if static is not None else root / "STATIC")
    paths = {"static": static}
    checks: dict[str, str] = {}
    for key, filename in RESOURCE_NAMES.items():
        path = existing_path((resources or {}).get(key, static / filename))
        paths[key] = path
        checks[key] = check_resource(key, path)
    return U7Installation(root, game or install_game(root), paths, checks)


def exult_game_paths(game: str) -> dict[str, Path]:
    """Read Exult's configured base and STATIC, tolerating unavailable config."""
    cfg_path = find_exult_cfg()
    if cfg_path is None:
        return {}
    try:
        paths = parse_exult_cfg(cfg_path, game)
    except (OSError, ValueError):
        return {}
    result = {}
    if paths.game_path:
        result["base"] = existing_path(Path(paths.game_path).expanduser())
    if paths.static_path:
        result["static"] = existing_path(Path(paths.static_path).expanduser())
    return result


def u7_path_candidates(game: str, key: str) -> list[Path]:
    """Try Titan settings, discovered nested roots, then Exult's game settings."""
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is not None:
            path = existing_path(path)
            if path not in candidates:
                candidates.append(path)

    add(_config.game_config_path(game, key))
    section = _config.get_config().get("u7bg" if game.upper() == "BG" else "u7si", {})
    base = _config.resolve_config_path(section.get("game", {}).get("base"))
    static = _config.game_config_path(game, "static")
    if key in RESOURCE_NAMES:
        if static:
            add(static / RESOURCE_NAMES[key])
        if base:
            add(base / "STATIC" / RESOURCE_NAMES[key])
    elif key == "static" and base:
        add(base / "STATIC")
    if base and key in {"static", *RESOURCE_NAMES}:
        for root in install_roots(base):
            if install_game(root) != game.upper() and root != base:
                continue
            add(
                root / "STATIC"
                if key == "static"
                else root / "STATIC" / RESOURCE_NAMES[key]
            )
    exult = exult_game_paths(game)
    if "static" in exult:
        if key == "static":
            add(exult["static"])
        elif key in RESOURCE_NAMES:
            add(exult["static"] / RESOURCE_NAMES[key])
    return candidates


def resolve_u7_path(game: str, key: str) -> Path | None:
    """Return the first usable automatic path; a missing setting cannot mask Exult."""
    for path in u7_path_candidates(game, key):
        exists = path.is_dir() if key in {"static", "gamedat"} else path.is_file()
        if exists:
            return path
    return None
