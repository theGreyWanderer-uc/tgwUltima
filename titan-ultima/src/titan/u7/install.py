"""Bounded U7 install discovery and shared configuration/Exult path resolution."""

from __future__ import annotations

import os
import re
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


def is_u7_folder_name(name: str) -> bool:
    """Recognize a launcher folder that holds Black Gate or Serpent Isle."""
    lowered = name.lower()
    if "ultima" not in lowered:
        return False
    return bool(re.search(r"ultima\s*vii(?!i)", lowered)) or any(
        token in lowered for token in ("ultima 7", "ultima7", "black gate", "serpent")
    )


def u7_install_candidates(
    config: dict,
) -> tuple[list[Path], dict[Path, str], dict[Path, Path]]:
    """List configured, Exult-registered, GOG, Heroic and manual U7 folders.

    Also returns the game each configured or Exult base is known to hold, and
    the STATIC folder Exult records for a base, so nonstandard installs are
    recognized without relying on their folder names.
    """
    candidates: list[Path] = []

    def _add_candidate(path: Path) -> None:
        if path not in candidates:
            candidates.append(path)

    exult_hints: dict[Path, str] = {}
    exult_statics: dict[Path, Path] = {}
    for game, section_key in (("BG", "u7bg"), ("SI", "u7si")):
        previous_base = config.get(section_key, {}).get("game", {}).get("base")
        if previous_base:
            configured_base = Path(previous_base).expanduser().resolve()
            exult_hints[configured_base] = game
            _add_candidate(configured_base)
        exult_paths = exult_game_paths(game)
        if "base" in exult_paths:
            exult_hints[exult_paths["base"].absolute()] = game
            if "static" in exult_paths:
                exult_statics[exult_paths["base"].absolute()] = exult_paths["static"]
            _add_candidate(exult_paths["base"])

    for drive in "CDEFG":
        for path in [
            Path(f"{drive}:\\GOG Games\\Ultima VII"),
            Path(f"{drive}:\\GOG Games\\Ultima VII - Complete"),
            Path(f"{drive}:\\Ultima\\ultima7bg"),
            Path(f"{drive}:\\Ultima\\ultima7si"),
            Path(f"{drive}:\\Ultima\\ultima7bg_no_exult"),
            Path(f"{drive}:\\Ultima\\ultima7si_no_exult"),
            Path(f"{drive}:\\ULTIMA7"),
            Path(f"{drive}:\\SERPENT"),
        ]:
            _add_candidate(path)

    for path in [
        Path.home() / "GOG Games" / "Ultima VII",
        Path.home() / "Games" / "Heroic" / "Ultima 7",
        Path.home() / "Games" / "Heroic" / "Ultima 7 - Serpent Isle",
    ]:
        _add_candidate(path)

    for root in (Path.home() / "GOG Games", Path.home() / "Games" / "Heroic"):
        if not root.is_dir():
            continue
        try:
            for folder in root.iterdir():
                if folder.is_dir() and is_u7_folder_name(folder.name):
                    _add_candidate(folder)
        except PermissionError:
            continue
    return candidates, exult_hints, exult_statics


def select_u7_install(
    value: str,
    game: str,
    exult_hints: dict[Path, str],
    exult_statics: dict[Path, Path],
) -> U7Installation | None:
    """Inspect the game root a user-chosen base holds, including nested roots."""
    if not value:
        return None
    candidate = Path(value).expanduser().absolute()
    roots = install_roots(candidate)
    matching = [
        root
        for root in roots
        if (exult_hints.get(root.absolute()) or install_game(root)) == game
    ]
    root = next(iter(matching or roots), candidate)
    # Selecting a base explicitly chooses the game even with a custom name.
    return inspect_install(root, game, static=exult_statics.get(root))


def relative_install_paths(selected: U7Installation | None) -> dict[str, str]:
    """Express an install's resource paths relative to its root where possible."""
    if selected is None:
        return {}
    return {
        key: path.relative_to(selected.root).as_posix()
        if path.is_relative_to(selected.root)
        else path.as_posix()
        for key, path in selected.paths.items()
    }


def u7_base_correction(
    section_key: str, selected: U7Installation | None, config: dict
) -> tuple[dict, list[str]]:
    """Propose a corrected base for a configured game whose root has moved.

    Returns the config update and the messages describing it. Custom relative
    paths are rewritten as absolute so they keep their meaning under the new
    base; both are empty when the configured base is already right.
    """
    previous = config.get(section_key, {}).get("game", {}).get("base")
    if not (
        selected
        and previous
        and Path(str(previous)).expanduser().resolve() != selected.root.resolve()
    ):
        return {}, []
    messages = [
        f"  Proposed {section_key} base correction: {previous} -> {selected.root}"
    ]
    update: dict = {"game": {"base": selected.root.as_posix()}}
    # Preserve the meaning of custom relative paths when changing base.
    previous_section = config[section_key]
    for key, value in previous_section.get("paths", {}).items():
        old_path = _config.resolve_config_path(value, previous)
        if not value or Path(str(value)).expanduser().is_absolute():
            continue
        standard = str(value).replace("\\", "/").upper().rstrip("/") in {
            "STATIC",
            "STATIC/SHAPES.VGA",
            "STATIC/PALETTES.FLX",
            "STATIC/TEXT.FLX",
            "GAMEDAT",
        }
        if old_path and (old_path.exists() or not standard):
            update.setdefault("paths", {})[key] = old_path.absolute().as_posix()
            messages.append(f"    Preserve custom {key}: {old_path.absolute()}")
    for mod_name, mod_config in previous_section.get("mods", {}).items():
        preserved = {}
        for key, value in mod_config.get("paths", {}).items():
            if value and not Path(str(value)).expanduser().is_absolute():
                preserved_path = _config.resolve_config_path(value, previous)
                if preserved_path is not None:
                    preserved[key] = preserved_path.absolute().as_posix()
        if preserved:
            update.setdefault("mods", {})[mod_name] = {"paths": preserved}
            messages.append(f"    Preserve custom paths for mod: {mod_name}")
    return update, messages


def exult_profile_dir() -> Path | None:
    """Return Exult's per-user data folder under ``%LOCALAPPDATA%``, if present."""
    local = os.getenv("LOCALAPPDATA")
    profile = Path(local) / "Exult" if local else None
    if profile is not None and not profile.is_dir():
        return None
    return profile


def _has_runtime_npc(path: Path) -> bool:
    return (path / "npc.dat").is_file()


def preferred_u7_gamedat(base_value: str, slug: str, exult_profile: Path | None) -> str:
    """Prefer a live GAMEDAT from Exult's profile, then the install's own."""
    candidates: list[Path] = []
    if exult_profile is not None:
        candidates.append(exult_profile / slug / "gamedat")
    if base_value:
        candidates.append(Path(base_value) / "gamedat")
        candidates.append(Path(base_value) / "GAMEDAT")
    for candidate in candidates:
        if _has_runtime_npc(candidate):
            return str(candidate).replace("\\", "/")
    return "gamedat/"


def _best_saves_dir(runtime_root: Path | None) -> Path | None:
    if runtime_root is None or not runtime_root.is_dir():
        return None
    counts: dict[Path, int] = {}
    for save_file in runtime_root.rglob("*.sav"):
        if save_file.is_file():
            counts[save_file.parent] = counts.get(save_file.parent, 0) + 1
    if not counts:
        return None
    return sorted(
        counts.items(),
        key=lambda item: (-item[1], len(str(item[0])), str(item[0]).lower()),
    )[0][0]


def discover_u7_mod_sources(
    base_value: str, slug: str, exult_profile: Path | None
) -> list[dict[str, str]]:
    """Find each installed mod's runtime root, GAMEDAT, saves and initgame archive."""
    if not base_value:
        return []
    install_mods = Path(base_value) / "mods"
    if not install_mods.is_dir():
        return []

    sources: list[dict[str, str]] = []
    for mod_dir in sorted(p for p in install_mods.iterdir() if p.is_dir()):
        item: dict[str, str] = {"name": mod_dir.name}
        runtime_root = (
            exult_profile / slug / "mods" / mod_dir.name
            if exult_profile is not None
            else None
        )
        if runtime_root is not None and runtime_root.is_dir():
            item["root"] = str(runtime_root).replace("\\", "/")
        runtime_gamedat = runtime_root / "gamedat" if runtime_root is not None else None
        install_gamedat = mod_dir / "gamedat"
        if runtime_gamedat is not None and _has_runtime_npc(runtime_gamedat):
            item["gamedat"] = str(runtime_gamedat).replace("\\", "/")
        elif _has_runtime_npc(install_gamedat):
            item["gamedat"] = str(install_gamedat).replace("\\", "/")
        saves_dir = _best_saves_dir(runtime_root)
        if saves_dir is not None:
            item["saves"] = str(saves_dir).replace("\\", "/")
        for archive in (
            mod_dir / "patch" / "initgame.dat",
            mod_dir / "data" / "initgame.dat",
        ):
            if archive.is_file():
                item["archive"] = str(archive).replace("\\", "/")
                break
        if len(item) > 1:
            sources.append(item)
    return sources


def find_exult_flx(flx_name: str) -> Path | None:
    """Find ``exult_bg.flx`` / ``exult_si.flx`` in a standard Exult install."""
    candidates: list[Path] = []
    for drive in "CD":
        for layout in (
            Path(f"{drive}:\\Program Files\\Exult\\data"),
            Path(f"{drive}:\\Program Files (x86)\\Exult\\data"),
            Path(f"{drive}:\\Program Files\\Exult"),
            Path(f"{drive}:\\Program Files (x86)\\Exult"),
        ):
            candidates.append(layout / flx_name)
    for share in (
        Path("/usr/share/exult"),
        Path("/usr/local/share/exult"),
        Path("/opt/exult"),
    ):
        candidates.append(share / flx_name)
    return next((p for p in candidates if p.is_file()), None)


def u7_setup_lines(
    section_name: str,
    variant: str,
    base: str,
    paths: dict[str, str],
    gamedat: str,
    mod_sources: list[dict[str, str]],
) -> list[str]:
    """Render one game's ``[u7xx.game]``, ``[u7xx.paths]`` and mod sections."""
    lines = [
        "",
        f"[{section_name}.game]",
        f'base     = "{base}"',
        f'variant  = "{variant}"',
        "",
        f"[{section_name}.paths]",
        f'static   = "{paths["static"]}"',
        f'shapes   = "{paths["shapes"]}"',
        f'palette  = "{paths["palette"]}"',
        f'text     = "{paths["text"]}"',
        f'gamedat  = "{gamedat}"',
    ]
    for item in mod_sources:
        lines += [
            "",
            f'[{section_name}.mods."{item["name"]}".paths]',
        ]
        if "gamedat" in item:
            lines.append(f'gamedat  = "{item["gamedat"]}"')
        if "saves" in item:
            lines.append(f'saves    = "{item["saves"]}"')
        if "root" in item:
            lines.append(f'root     = "{item["root"]}"')
        if "archive" in item:
            lines.append(f'archive  = "{item["archive"]}"')
    return lines


def u7_manual_setup_lines(static_path: str, variant: str) -> list[str]:
    """Render a game's sections from a manually entered STATIC folder."""
    static_norm = Path(static_path).expanduser().absolute().as_posix()
    static_p = Path(static_norm)
    base_guess = static_p.parent.as_posix()
    gamedat_guess = str(static_p.parent / "gamedat").replace("\\", "/")
    section_name = "u7bg" if variant == "blackgate" else "u7si"
    return [
        "",
        f"[{section_name}.game]",
        f'base     = "{base_guess}"',
        f'variant  = "{variant}"',
        "",
        f"[{section_name}.paths]",
        f'static   = "{static_norm}"',
        f'shapes   = "{static_norm}/SHAPES.VGA"',
        f'palette  = "{static_norm}/PALETTES.FLX"',
        f'text     = "{static_norm}/TEXT.FLX"',
        f'gamedat  = "{gamedat_guess}"',
    ]


def resolve_u7_static_and_palette(game: str) -> tuple[str | None, str | None]:
    """Share verified config/nested-install/Exult paths with the shape wizard."""
    static = resolve_u7_path(game, "static")
    palette = resolve_u7_path(game, "palette")
    return str(static) if static else None, str(palette) if palette else None


def resolve_u7_patch_base_static(
    selected_static: str,
    configured_static: str | None,
) -> str | None:
    """Find a distinct base STATIC for an explicitly selected mod patch."""
    selected_path = Path(selected_static).expanduser().resolve()

    def _is_usable_base(candidate: Path) -> bool:
        try:
            distinct = candidate.resolve() != selected_path
        except OSError:
            distinct = candidate != selected_path
        if not distinct or not candidate.is_dir():
            return False
        return any(
            (candidate / filename).is_file()
            for filename in ("SHAPES.VGA", "shapes.vga")
        )

    if configured_static:
        configured_path = Path(configured_static).expanduser()
        if _is_usable_base(configured_path):
            return str(configured_path)

    for ancestor in (selected_path, *selected_path.parents):
        for dirname in ("STATIC", "static"):
            candidate = ancestor / dirname
            if _is_usable_base(candidate):
                return str(candidate)
    return None


def resolve_u7_text_flx(game: str, static_dir: str | None = None) -> str | None:
    """Resolve TEXT.FLX path from config, with fallback to STATIC dir."""
    configured = _config.game_config_path(game, "text")
    if configured and existing_path(configured).is_file():
        return str(existing_path(configured))
    if static_dir:
        selected = existing_path(Path(static_dir) / "TEXT.FLX")
        if selected.is_file():
            return str(selected)
    path = resolve_u7_path(game, "text")
    return str(path) if path else None


def resolve_u7_gamedat(game: str) -> str | None:
    """Resolve loose GAMEDAT path from multi-game config for BG/SI."""
    cfg = _config.get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    paths_cfg = section.get("paths", {}) if isinstance(section, dict) else {}

    base = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    base_path = Path(str(base)).expanduser() if base else None

    configured = paths_cfg.get("gamedat") if isinstance(paths_cfg, dict) else None
    if configured:
        path = Path(str(configured)).expanduser()
        if path.is_absolute() or base_path is None:
            return str(path)
        return str(base_path / path)

    if base_path is not None:
        for name in ("gamedat", "GAMEDAT"):
            candidate = base_path / name
            if candidate.is_dir():
                return str(candidate)
    return None


def resolve_u7_exult_flx(game: str) -> str | None:
    """Resolve installed Exult per-game FLX bundle path."""
    game_key = "bg" if game.lower() == "bg" else "si"
    configured = _config.exult_cfg(f"{game_key}_flx")
    if configured and Path(configured).is_file():
        return configured

    found = find_exult_flx(f"exult_{game_key}.flx")
    return str(found) if found else None


def resolve_ucxt_intrinsics_data(
    game: str,
    intrinsics_data: str | None = None,
) -> str | None:
    """Resolve optional UCXT intrinsic-name table for U7 raw usecode output."""
    game_key = game.lower()
    if game_key not in ("bg", "si"):
        raise ValueError("U7 intrinsic game must be bg or si")
    if intrinsics_data is not None:
        path = Path(intrinsics_data).expanduser()
        if not path.is_file():
            raise ValueError(f"U7 intrinsic table not found: {path}")
        return str(path)
    filename = "u7bgintrinsics.data" if game_key == "bg" else "u7siintrinsics.data"
    candidates: list[Path] = []
    for drive in ("C", "D"):
        candidates.extend(
            [
                Path(f"{drive}:\\Program Files\\Exult\\Tools\\data") / filename,
                Path(f"{drive}:\\Program Files (x86)\\Exult\\Tools\\data") / filename,
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def exult_game_slug(game: str) -> str:
    return "blackgate" if game.lower() == "bg" else "serpentisle"


def resolve_u7_mod_gamedat(game: str, mod: str | None) -> str | None:
    """Resolve per-user Exult runtime GAMEDAT for a base game or mod."""
    cfg = _config.get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    mods_cfg = section.get("mods", {}) if isinstance(section, dict) else {}
    if mod and isinstance(mods_cfg, dict):
        mod_cfg = mods_cfg.get(mod, {})
        if isinstance(mod_cfg, dict):
            paths_cfg = mod_cfg.get("paths", {})
            if isinstance(paths_cfg, dict):
                configured = paths_cfg.get("gamedat")
                if configured:
                    path = _config.resolve_config_path(configured, game_cfg.get("base"))
                    if path and (path / "npc.dat").is_file():
                        return str(path)

    root = exult_profile_dir()
    if root is None:
        return None
    base = root / exult_game_slug(game)
    candidate = base / "gamedat" if not mod else base / "mods" / mod / "gamedat"
    if (candidate / "npc.dat").is_file():
        return str(candidate)

    base_path = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    if mod and base_path:
        install_candidate = Path(str(base_path)).expanduser() / "mods" / mod / "gamedat"
        if (install_candidate / "npc.dat").is_file():
            return str(install_candidate)
    return None


def resolve_u7_mod_archive(game: str, mod: str | None) -> str | None:
    """Resolve configured Exult mod archive data, such as patch/initgame.dat."""
    if not mod:
        return None
    cfg = _config.get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    mods_cfg = section.get("mods", {}) if isinstance(section, dict) else {}
    mod_cfg = mods_cfg.get(mod, {}) if isinstance(mods_cfg, dict) else {}
    paths_cfg = mod_cfg.get("paths", {}) if isinstance(mod_cfg, dict) else {}
    archive = paths_cfg.get("archive") if isinstance(paths_cfg, dict) else None
    if archive:
        path = _config.resolve_config_path(archive, game_cfg.get("base"))
        if path and path.is_file():
            return str(path)
    base_path = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    if base_path:
        mod_root = Path(str(base_path)).expanduser() / "mods" / mod
        for candidate in (
            mod_root / "patch" / "initgame.dat",
            mod_root / "data" / "initgame.dat",
        ):
            if candidate.is_file():
                return str(candidate)
    return None
