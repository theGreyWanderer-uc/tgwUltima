"""Discover archive destinations for retail games, mods, and Exult custom games."""

from __future__ import annotations

# Config parsing below rejects DTDs before any entity expansion.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass, replace
from pathlib import Path

from titan._config import resolve_config_path
from titan.fonts.exult_cfg import ExultGamePaths
from titan.u7.install import existing_path


@dataclass(frozen=True)
class ArchiveTarget:
    name: str
    static: Path | None
    patch: Path
    standalone: bool = False
    root: Path | None = None
    gamedat: Path | None = None
    save_root: Path | None = None


class _ConfigTreeBuilder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("Exult configuration must not contain a DTD")


def _read_config_xml(path: Path) -> ET.Element:
    # Exult Studio can write NUL bytes in mod descriptions. DTDs are rejected
    # by the parser target, so custom entities cannot expand during discovery.
    data = path.read_bytes().replace(b"\x00", b"")
    parser = ET.XMLParser(target=_ConfigTreeBuilder())  # nosec B314
    return ET.fromstring(data, parser=parser)  # nosec B314


def target_from_folder(folder: Path, game_static: Path | None) -> ArchiveTarget:
    """A game owns STATIC; a conventional mod inherits its selected retail base."""
    folder = existing_path(folder.expanduser().absolute())
    if not folder.is_dir():
        raise ValueError(f"Mod or Exult game folder not found: {folder}")
    if folder.name.lower() == "patch":
        root, patch = folder.parent, folder
    else:
        root, patch = folder, existing_path(folder / "patch")
    own_static = existing_path(root / "static")
    standalone = own_static.is_dir()
    return ArchiveTarget(
        root.name,
        own_static if standalone else game_static,
        patch,
        standalone,
        root,
        existing_path(root / "gamedat")
        if existing_path(root / "gamedat").is_dir()
        else None,
        root,
    )


def _mod_target(
    cfg_path: Path, mods: Path, game_static: Path | None, save_root: Path | None = None
) -> ArchiveTarget:
    root = _read_config_xml(cfg_path)
    info = root.find("mod_info")
    if info is None:
        info = root
    name = (info.findtext("mod_title") or cfg_path.stem).strip()
    title = " ".join((info.findtext("display_string") or name).split())
    mod_root = mods / name
    value = (info.findtext("patch") or str(mod_root / "patch")).strip()
    value = value.replace("__MODS__", str(mods)).replace("__MOD_PATH__", str(mod_root))
    patch = resolve_config_path(value, mods)
    if patch is None or "<" in str(patch):
        raise ValueError(f"Unresolved patch path in {cfg_path}")
    save_mods = save_root / "mods" if save_root else mods
    save_mod = save_mods / name
    gamedat_value = (info.findtext("gamedat_path") or str(save_mod / "gamedat")).strip()
    gamedat_value = gamedat_value.replace("__MODS__", str(save_mods)).replace(
        "__MOD_PATH__", str(save_mod)
    )
    gamedat = resolve_config_path(gamedat_value, save_mod)
    if gamedat and "<" in str(gamedat):
        gamedat = None
    save_value = (info.findtext("savegame_path") or str(save_mod)).strip()
    save_value = save_value.replace("__MODS__", str(save_mods)).replace(
        "__MOD_PATH__", str(save_mod)
    )
    saves = resolve_config_path(save_value, save_mod)
    if saves and "<" in str(saves):
        saves = None
    return ArchiveTarget(
        title,
        game_static,
        existing_path(patch),
        False,
        mod_root,
        existing_path(gamedat) if gamedat else None,
        existing_path(saves) if saves else None,
    )


def _profile_root(cfg_path: Path) -> Path:
    return (
        cfg_path.parent / ".exult" if cfg_path.name == ".exult.cfg" else cfg_path.parent
    )


def _game_save_root(
    entry: ET.Element | None, tag: str, cfg_path: Path, game_root: Path | None
) -> Path:
    value = entry.findtext("savegame_path") if entry is not None else None
    return resolve_config_path(value, game_root) or _profile_root(cfg_path) / tag


def base_target(
    game: str,
    config: dict,
    static: Path | None,
    paths: ExultGamePaths | None,
    cfg_path: Path | None,
) -> ArchiveTarget:
    section = config.get("u7bg" if game.upper() == "BG" else "u7si", {})
    root = resolve_config_path(section.get("game", {}).get("base"))
    if root is None and paths and paths.game_path:
        root = Path(paths.game_path).expanduser()
    tag = "blackgate" if game.upper() == "BG" else "serpentisle"
    entry = None
    if cfg_path:
        try:
            entry = _read_config_xml(cfg_path).find(f"disk/game/{tag}")
        except (OSError, ValueError, ET.ParseError):
            pass
    explicit = resolve_config_path(section.get("paths", {}).get("gamedat"), root)
    cfg_gamedat = (
        resolve_config_path(entry.findtext("gamedat_path"), root)
        if entry is not None
        else None
    )
    candidates = [explicit, cfg_gamedat]
    if cfg_path:
        candidates.append(_game_save_root(entry, tag, cfg_path, root) / "gamedat")
    if root:
        candidates.append(root / "gamedat")
    gamedat = next(
        (existing_path(p) for p in candidates if p and existing_path(p).is_dir()), None
    )
    patch = (
        Path(paths.patch_path).expanduser()
        if paths and paths.patch_path
        else (root or Path.cwd()) / "patch"
    )
    return ArchiveTarget(
        f"Base {game.upper()} game",
        static,
        existing_path(patch),
        False,
        root,
        gamedat,
        _game_save_root(entry, tag, cfg_path, root)
        if cfg_path
        else (gamedat.parent if gamedat else root),
    )


def discover_targets(
    game: str,
    config: dict,
    game_static: Path | None,
    exult_paths: ExultGamePaths | None,
    exult_cfg_path: Path | None,
) -> list[ArchiveTarget]:
    """Combine Titan settings, installed mods, and custom exult.cfg game entries."""
    targets: dict[Path, ArchiveTarget] = {}
    cfg_root = ET.Element("config")
    if exult_cfg_path:
        try:
            cfg_root = _read_config_xml(exult_cfg_path)
        except (OSError, ValueError, ET.ParseError):
            pass
    tag = "blackgate" if game.upper() == "BG" else "serpentisle"

    def add(target: ArchiveTarget) -> None:
        key = target.patch.resolve()
        previous = targets.get(key)
        if previous is None:
            targets[key] = target
        else:
            # Keep explicit Titan archive paths while filling runtime paths
            # from the matching Exult mod description.
            targets[key] = replace(
                previous,
                gamedat=previous.gamedat or target.gamedat,
                save_root=previous.save_root or target.save_root,
            )

    section = config.get("u7bg" if game.upper() == "BG" else "u7si", {})
    base = section.get("game", {}).get("base")
    for name, mod in section.get("mods", {}).items():
        paths = mod.get("paths", {})
        patch = resolve_config_path(paths.get("patch"), base)
        static = resolve_config_path(paths.get("static"), base)
        root = resolve_config_path(paths.get("root"), base)
        archive = resolve_config_path(paths.get("archive"), base)
        if patch is None and archive and archive.parent.name.lower() == "patch":
            patch = archive.parent
        if patch is None and root and existing_path(root / "patch").is_dir():
            patch = existing_path(root / "patch")
        if patch:
            add(
                ArchiveTarget(
                    name,
                    static or game_static,
                    existing_path(patch),
                    static is not None,
                    root or patch.parent,
                    resolve_config_path(paths.get("gamedat"), base)
                    or (root / "gamedat" if root else None),
                    resolve_config_path(paths.get("savegame"), base),
                )
            )

    mod_dirs: list[Path] = []
    if exult_paths and exult_paths.mods_path:
        mod_dirs.append(Path(exult_paths.mods_path).expanduser())
    if base:
        mod_dirs.append(Path(base).expanduser() / "mods")
    for directory in dict.fromkeys(mod_dirs):
        directory = existing_path(directory)
        if not directory.is_dir():
            continue
        # Read descriptions before folders so the configured title and path win.
        for entry in sorted(
            directory.iterdir(), key=lambda path: (path.is_dir(), path.name.lower())
        ):
            if entry.is_file() and entry.suffix.lower() == ".cfg":
                try:
                    save_root = (
                        _game_save_root(
                            cfg_root.find(f"disk/game/{tag}"),
                            tag,
                            exult_cfg_path,
                            Path(base) if base else None,
                        )
                        if exult_cfg_path
                        else None
                    )
                    target = _mod_target(entry, directory, game_static, save_root)
                    settings = (
                        section.get("mods", {}).get(entry.stem, {}).get("paths", {})
                    )
                    runtime = resolve_config_path(settings.get("gamedat"), base)
                    runtime_root = resolve_config_path(settings.get("root"), base)
                    if runtime_root and not runtime:
                        runtime = runtime_root / "gamedat"
                    if runtime:
                        target = replace(target, gamedat=runtime)
                    add(target)
                except (OSError, ValueError, ET.ParseError):
                    continue
            elif entry.is_dir() and existing_path(entry / "patch").is_dir():
                add(target_from_folder(entry, game_static))

    if exult_cfg_path:
        for game_entry in cfg_root.findall("disk/game/*"):
            if game_entry.tag in {"blackgate", "serpentisle"}:
                continue
            base_path = (game_entry.findtext("path") or "").strip()
            if not base_path:
                continue
            custom_root = Path(base_path).expanduser()
            if not custom_root.is_dir():
                continue
            static = resolve_config_path(
                game_entry.findtext("static_path") or "static", custom_root
            )
            patch = resolve_config_path(
                game_entry.findtext("patch") or "patch", custom_root
            )
            if static is not None and patch is not None:
                title = " ".join(
                    (game_entry.findtext("title") or game_entry.tag).split()
                )
                add(
                    ArchiveTarget(
                        f"{title} (Exult game)",
                        existing_path(static),
                        existing_path(patch),
                        True,
                        custom_root,
                        resolve_config_path(
                            game_entry.findtext("gamedat_path"), custom_root
                        )
                        or _game_save_root(
                            game_entry, game_entry.tag, exult_cfg_path, custom_root
                        )
                        / "gamedat",
                        _game_save_root(
                            game_entry, game_entry.tag, exult_cfg_path, custom_root
                        ),
                    )
                )
    return sorted(targets.values(), key=lambda target: target.name.lower())
