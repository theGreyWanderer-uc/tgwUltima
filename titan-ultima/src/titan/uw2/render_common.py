"""Small helpers shared by the standalone render_*.py CLI scripts.

Filename slugging, hex-color parsing, and exported-PNG texture loading were
previously copy-pasted across render_uuw2_as_u7_style.py,
render_level_flat_grid.py, and render_level_views.py.
"""

from __future__ import annotations

from pathlib import Path
import re

from PIL import Image


def slugify(value: str) -> str:
    value = value.lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "unknown"


def render_output_filename(
    slot: int, level: dict, suffix: str, name_files: bool
) -> str:
    if not name_files:
        return f"level_{slot:03d}_{suffix}.png"
    name = level.get("level_name") or level.get("world_name") or "unknown"
    return f"level_{slot:03d}_{slugify(name)}_{suffix}.png"


def parse_hex_color(value: str) -> tuple[int, int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Expected #RRGGBB background, got {value!r}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 255


def load_terrain_textures(texture_dir: Path) -> dict[int, Image.Image]:
    """Load exported t64_###.png terrain textures keyed by texture id."""
    textures: dict[int, Image.Image] = {}
    for path in sorted(texture_dir.glob("t64_*.png")):
        try:
            texture_id = int(path.stem.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        textures[texture_id] = Image.open(path).convert("RGBA")
    if not textures:
        raise FileNotFoundError(f"No t64_###.png textures found in {texture_dir}")
    return textures


def load_gr_textures(texture_dir: Path, stem: str) -> dict[int, Image.Image]:
    """Load exported GR-archive PNGs (doors/tmflat/tmobj) keyed by image id."""
    textures: dict[int, Image.Image] = {}
    if not texture_dir.exists():
        return textures

    patterns = (f"{stem}_*.png", f"{stem[:-1]}_*.png")
    for pattern in patterns:
        for path in sorted(texture_dir.glob(pattern)):
            if path.name.endswith("_contact_sheet.png"):
                continue
            try:
                texture_id = int(path.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            textures[texture_id] = Image.open(path).convert("RGBA")
    return textures
