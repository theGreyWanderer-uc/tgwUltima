"""
Exult configuration parser for font path resolution.

Reads ``exult.cfg`` (XML) to determine:
- Game base directories (BG / SI)
- The active font config setting (``disabled`` / ``original`` / ``serif``)
- The resolved font shape filename
- Patch directory (including mod overrides)

Search order for ``exult.cfg``:
  1. Explicit path (if supplied)
  2. ``%LOCALAPPDATA%/Exult/exult.cfg`` (Windows default)
  3. ``~/.exult.cfg`` (Linux / macOS)
"""

from __future__ import annotations

__all__ = [
    "find_exult_cfg",
    "parse_exult_cfg",
    "ExultGamePaths",
    "resolve_font_vga_path",
    "scan_font_archives",
]

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# -- Font filename dispatch (mirrors exult/game.cc) -----------------------

FONT_FILE_MAP: dict[str, str] = {
    "disabled": "fonts.vga",
    "original": "fonts_original.vga",
    "serif":    "fonts_serif.vga",
}

DEFAULT_FONT_CONFIG = "original"

# -- XML path → config key mapping ----------------------------------------

_GAME_CFG_NAMES: dict[str, str] = {
    "BG": "blackgate",
    "SI": "serpentisle",
}


# -- Data classes ----------------------------------------------------------

@dataclass
class ExultGamePaths:
    """Resolved paths for a single Exult game installation."""

    game: str                        # "BG" or "SI"
    game_path: Optional[str] = None  # Base game directory
    static_path: Optional[str] = None
    patch_path: Optional[str] = None
    mods_path: Optional[str] = None
    font_config: str = DEFAULT_FONT_CONFIG  # "disabled" / "original" / "serif"

    @property
    def font_filename(self) -> str:
        """The font VGA filename Exult will load for this config."""
        return FONT_FILE_MAP.get(self.font_config, FONT_FILE_MAP["original"])

    @property
    def font_vga_path(self) -> Optional[str]:
        """Full path to the font VGA file Exult will load from <PATCH>."""
        if self.patch_path:
            return str(Path(self.patch_path) / self.font_filename)
        return None


# -- Config file discovery -------------------------------------------------

def find_exult_cfg() -> Optional[Path]:
    """Locate ``exult.cfg`` in standard locations.

    Returns the first path found, or ``None``.
    """
    candidates: list[Path] = []

    # Windows: %LOCALAPPDATA%\Exult\exult.cfg
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Exult" / "exult.cfg")

    # Linux / macOS: ~/.exult.cfg
    candidates.append(Path.home() / ".exult.cfg")

    # Also try ~/.exult/exult.cfg (some installs)
    candidates.append(Path.home() / ".exult" / "exult.cfg")

    return next((p for p in candidates if p.is_file()), None)


# -- XML helpers -----------------------------------------------------------

def _xml_text(root: ET.Element, dotpath: str) -> Optional[str]:
    """Traverse *root* using a dotted path (``gameplay.fonts``) and
    return the stripped text content, or ``None`` if missing.

    Exult's config uses bare-tag nesting: ``<config><gameplay><fonts>``
    maps to dotpath ``gameplay.fonts``.
    """
    node = root
    for tag in dotpath.split("."):
        child = node.find(tag)
        if child is None:
            return None
        node = child
    return node.text.strip() if node.text else None


# -- Main parser -----------------------------------------------------------

def parse_exult_cfg(
    cfg_path: str | Path,
    game: str = "SI",
) -> ExultGamePaths:
    """Parse ``exult.cfg`` and extract paths for *game* (``"BG"`` or ``"SI"``).

    Parameters
    ----------
    cfg_path : path
        Path to ``exult.cfg``.
    game : str
        ``"BG"`` or ``"SI"``.

    Returns
    -------
    ExultGamePaths
        Resolved paths and font config for the game.
    """
    tree = ET.parse(str(cfg_path))
    root = tree.getroot()  # <config>

    cfg_name = _GAME_CFG_NAMES.get(game.upper(), "serpentisle")
    prefix = f"disk.game.{cfg_name}"

    result = ExultGamePaths(game=game.upper())

    # Game base path: <config><disk><game><serpentisle><path>
    game_path = _xml_text(root, f"{prefix}.path")
    if game_path:
        result.game_path = game_path

    # Static path (optional override, usually <game>/static)
    static_path = _xml_text(root, f"{prefix}.static_path")
    if static_path:
        result.static_path = static_path
    elif game_path:
        result.static_path = str(Path(game_path) / "static")

    # Patch path (optional override, usually <game>/patch)
    patch_path = _xml_text(root, f"{prefix}.patch")
    if patch_path:
        result.patch_path = patch_path
    elif game_path:
        result.patch_path = str(Path(game_path) / "patch")

    # Mods path (optional, usually <game>/mods)
    mods_path = _xml_text(root, f"{prefix}.mods")
    if mods_path:
        result.mods_path = mods_path
    elif game_path:
        result.mods_path = str(Path(game_path) / "mods")

    # Font config: <config><gameplay><fonts>  (global, not per-game)
    font_cfg = _xml_text(root, "gameplay.fonts")
    if font_cfg:
        result.font_config = font_cfg.lower()
    else:
        result.font_config = DEFAULT_FONT_CONFIG

    return result


def resolve_font_vga_path(
    game: str = "SI",
    cfg_path: str | Path | None = None,
    mod_patch_path: str | None = None,
) -> tuple[ExultGamePaths, str]:
    """Resolve the full path to the font VGA file Exult will load.

    Parameters
    ----------
    game : str
        ``"BG"`` or ``"SI"``.
    cfg_path : path or None
        Explicit ``exult.cfg`` path. If ``None``, auto-discovers.
    mod_patch_path : str or None
        If set, overrides the patch directory (for mods that use
        ``<mod>/patch/`` instead of ``<game>/patch/``).

    Returns
    -------
    (ExultGamePaths, str)
        The parsed paths object and the resolved font VGA file path.

    Raises
    ------
    FileNotFoundError
        If no ``exult.cfg`` can be found.
    """
    if cfg_path is None:
        found = find_exult_cfg()
        if found is None:
            raise FileNotFoundError(
                "Could not find exult.cfg. "
                "Checked: %LOCALAPPDATA%\\Exult\\exult.cfg, ~/.exult.cfg"
            )
        cfg_path = found

    paths = parse_exult_cfg(cfg_path, game)

    # Mod override: use the mod's patch directory
    if mod_patch_path:
        paths.patch_path = mod_patch_path

    font_path = paths.font_vga_path
    if font_path is None:
        raise FileNotFoundError(
            f"Could not determine patch directory for {game} from exult.cfg"
        )

    return paths, font_path


# -- Font archive scanner --------------------------------------------------

def scan_font_archives(game_path: str | Path) -> list[Path]:
    """Recursively find all font VGA archives under *game_path*.

    Searches for ``*.vga`` files whose name contains ``font``
    (case-insensitive).  Returns a sorted list of absolute paths.
    """
    root = Path(game_path)
    if not root.is_dir():
        return []

    results: list[Path] = []
    for vga in root.rglob("*.vga"):
        if "font" in vga.name.lower():
            results.append(vga)
    return sorted(results)
