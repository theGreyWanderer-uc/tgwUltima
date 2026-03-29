"""
Palette LUT mapping for U7 font creation.

Maps grayscale rendered glyph pixels to game palette indices using
lookup tables derived from the original FONTS.VGA data.

Also provides :func:`resolve_game_palette` for auto-discovering the
correct ``PALETTES.FLX`` for a given target game (BG or SI).
"""

from __future__ import annotations

__all__ = ["PaletteLUT", "resolve_game_palette",
           "GRADIENT_PRESETS", "list_gradient_presets",
           "get_gradient_preset", "resolve_gradient_to_indices"]

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class PaletteLUT:
    """Grayscale-to-palette-index lookup table.

    Each entry in *mapping* is ``(min_gray, max_gray, palette_index)``.
    Entries are evaluated in order; the first matching range wins.
    """

    name: str
    description: str = ""
    transparent: int = 255
    mapping: list[tuple[int, int, int]] = field(default_factory=list)

    # Pre-built 256-entry lookup array for fast pixel mapping
    _lut: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.mapping and not self._lut:
            self._build_lut()

    def _build_lut(self) -> None:
        """Build a 256-entry direct lookup from grayscale → palette index."""
        self._lut = [self.transparent] * 256
        for lo, hi, idx in self.mapping:
            for g in range(lo, min(hi + 1, 256)):
                self._lut[g] = idx

    def map_value(self, gray: int) -> int:
        """Map a single grayscale value (0–255) to a palette index."""
        if self._lut:
            return self._lut[gray & 0xFF]
        return self.transparent

    def map_mono(self, value: int, ink_index: int) -> int:
        """Map a mono pixel (0 or 1) to a palette index.

        Used for single-colour font rendering where ink pixels map to
        *ink_index* and empty pixels map to transparent.
        """
        return ink_index if value else self.transparent

    @classmethod
    def from_toml(cls, path: str | Path) -> PaletteLUT:
        """Load a palette LUT from a TOML file."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        meta = data.get("meta", {})
        name = meta.get("name", Path(path).stem)
        desc = meta.get("description", "")
        trans = meta.get("transparent", 255)

        mapping: list[tuple[int, int, int]] = []
        for key, idx in data.get("mapping", {}).items():
            lo_s, hi_s = key.split("-")
            mapping.append((int(lo_s), int(hi_s), int(idx)))

        # Sort by range start
        mapping.sort(key=lambda t: t[0])
        return cls(name=name, description=desc, transparent=trans,
                   mapping=mapping)

    @classmethod
    def mono(cls, ink_index: int = 0) -> PaletteLUT:
        """Create a simple mono (single-colour) LUT.

        Grayscale 0 → transparent, anything > 0 → *ink_index*.
        """
        mapping = [(0, 0, 255), (1, 255, ink_index)]
        return cls(name=f"mono_ink{ink_index}", mapping=mapping)


# ---------------------------------------------------------------------------
# Built-in LUT definitions — derived from original FONTS.VGA analysis
# ---------------------------------------------------------------------------

# These are the most common palette configurations found in the original
# game fonts.  Each can be loaded by name via get_builtin_lut().

_BUILTIN_LUTS: dict[str, PaletteLUT] = {}


def _register(key: str, lut: PaletteLUT) -> None:
    _BUILTIN_LUTS[key] = lut


_register("black_ink", PaletteLUT(
    name="Black ink",
    description="Black ink on transparent — Fonts 2, 4",
    mapping=[(0, 0, 255), (1, 255, 0)],
))

_register("white_glow", PaletteLUT(
    name="White/glow",
    description="White glowing ink — Font 5",
    mapping=[(0, 0, 255), (1, 255, 15)],
))

_register("yellow_text", PaletteLUT(
    name="Yellow text",
    description="Yellow multi-shade — Fonts 0, 7",
    mapping=[
        (0, 15, 255),     # transparent
        (16, 63, 148),    # light yellow
        (64, 127, 146),   # medium yellow
        (128, 191, 144),  # dark yellow
        (192, 255, 142),  # full yellow
    ],
))

_register("red_text", PaletteLUT(
    name="Red text",
    description="Red multi-shade — Font 7 variant",
    mapping=[
        (0, 15, 255),
        (16, 63, 56),     # light red
        (64, 127, 54),    # medium red
        (128, 191, 52),   # dark red
        (192, 255, 50),   # full red
    ],
))

_register("runic_multicolor", PaletteLUT(
    name="Runic multi-color",
    description="Multi-shade runic — Fonts 1, 3, 6",
    mapping=[
        (0, 15, 255),
        (16, 63, 148),
        (64, 127, 146),
        (128, 191, 144),
        (192, 255, 142),
    ],
))

_register("serpentine_metal", PaletteLUT(
    name="Serpentine metal",
    description="Metal-toned Ophidean — Fonts 8, 9",
    mapping=[
        (0, 15, 255),
        (16, 63, 248),    # light silver
        (64, 127, 246),   # medium silver
        (128, 191, 244),  # dark silver
        (192, 255, 242),  # full silver
    ],
))

_register("serpentine_gold", PaletteLUT(
    name="Serpentine gold",
    description="Gold-toned Ophidean — Font 10",
    mapping=[
        (0, 15, 255),
        (16, 63, 148),    # light gold
        (64, 127, 146),   # medium gold
        (128, 191, 144),  # dark gold
        (192, 255, 142),  # full gold
    ],
))


def get_builtin_lut(key: str) -> PaletteLUT:
    """Get a built-in palette LUT by key name.

    Available keys: ``black_ink``, ``white_glow``, ``yellow_text``,
    ``red_text``, ``runic_multicolor``, ``serpentine_metal``,
    ``serpentine_gold``.
    """
    lut = _BUILTIN_LUTS.get(key)
    if lut is None:
        available = ", ".join(sorted(_BUILTIN_LUTS))
        raise KeyError(f"Unknown LUT key {key!r}. Available: {available}")
    return lut


def list_builtin_luts() -> list[str]:
    """Return the names of all built-in palette LUTs."""
    return sorted(_BUILTIN_LUTS)


# ---------------------------------------------------------------------------
# Gradient presets for hollow gradient rendering
# ---------------------------------------------------------------------------
# Each preset defines a source→dest colour ramp using hex RGB values.
# At generation time these are resolved to the nearest U7 palette
# indices via resolve_gradient_to_indices().
#
# Presets are intentionally defined as hex colours (not palette indices)
# so they work with any game palette.

@dataclass
class GradientPreset:
    """A named colour gradient for hollow font fill."""

    key: str                  # lookup key (e.g. "warm_flame")
    name: str                 # display name
    colors: list[str]         # hex CSS colours, top→bottom
    stroke: str = "#000000"   # hex stroke colour
    source: str = ""          # credit / origin

    @property
    def description(self) -> str:
        return " → ".join(self.colors)

    @property
    def swatches(self) -> str:
        """ANSI 24-bit colour block characters for each stop."""
        blocks: list[str] = []
        for c in self.colors:
            h = c.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            blocks.append(f"\033[38;2;{r};{g};{b}m\u2588\u2588\033[0m")
        return " ".join(blocks)


# --- Standard gradients (warm, readable on dark backgrounds) ---

GRADIENT_PRESETS: dict[str, GradientPreset] = {}


def _gp(key: str, name: str, colors: list[str], *,
        stroke: str = "#000000", source: str = "") -> None:
    GRADIENT_PRESETS[key] = GradientPreset(
        key=key, name=name, colors=colors, stroke=stroke, source=source)


# -- Warm / classic --
_gp("warm_flame", "Warm Flame",
    ["#ff9d3c", "#7d2c00"],
    source="U7 SI palette (original Pagan font)")

_gp("sunrise", "Sunrise",
    ["#FF512F", "#F09819"],
    source="uiGradients — Sunrise")

_gp("juicy_orange", "Juicy Orange",
    ["#FF8008", "#FFC837"],
    source="uiGradients — Juicy Orange")

_gp("citrus_peel", "Citrus Peel",
    ["#FDC830", "#F37335"],
    source="uiGradients — Citrus Peel")

_gp("koko_caramel", "Koko Caramel",
    ["#D1913C", "#FFD194"],
    source="uiGradients — Koko Caramel")

# -- Red / blood --
_gp("blood_red", "Blood Red",
    ["#f85032", "#e73827"],
    source="uiGradients — Blood Red")

_gp("sin_city_red", "Sin City Red",
    ["#ED213A", "#93291E"],
    source="uiGradients — Sin City Red")

_gp("firewatch", "Firewatch",
    ["#cb2d3e", "#ef473a"],
    source="uiGradients — Firewatch")

# -- Gold / yellow --
_gp("master_card", "Master Card",
    ["#f46b45", "#eea849"],
    source="uiGradients — Master Card")

_gp("sun_horizon", "Sun on the Horizon",
    ["#fceabb", "#f8b500"],
    source="uiGradients — Sun on the Horizon")

_gp("learning_leading", "Learning and Leading",
    ["#F7971E", "#FFD200"],
    source="uiGradients — Learning and Leading")

# -- Purple / violet --
_gp("electric_violet", "Electric Violet",
    ["#4776E6", "#8E54E9"],
    source="uiGradients — Electric Violet")

_gp("purple_love", "Purple Love",
    ["#cc2b5e", "#753a88"],
    source="uiGradients — Purple Love")

_gp("deep_purple", "Deep Purple",
    ["#673AB7", "#512DA8"],
    source="uiGradients — Deep Purple")

# -- Blue / cool --
_gp("reef", "Reef",
    ["#00d2ff", "#3a7bd5"],
    source="uiGradients — Reef")

_gp("royal", "Royal",
    ["#141E30", "#243B55"],
    source="uiGradients — Royal")

_gp("midnight_city", "Midnight City",
    ["#232526", "#414345"],
    source="uiGradients — Midnight City")

_gp("frost", "Frost",
    ["#000428", "#004e92"],
    source="uiGradients — Frost")

_gp("cool_sky", "Cool Sky",
    ["#2980B9", "#6DD5FA"],
    source="uiGradients — Cool Sky")

_gp("sexy_blue", "Sexy Blue",
    ["#2193b0", "#6dd5ed"],
    source="uiGradients — Sexy Blue")

_gp("cold_shivers", "Cold Shivers",
    ["#83a4d4", "#b6fbff"],
    source="uiGradients — Friday")

# -- Green / nature --
_gp("lush", "Lush",
    ["#56ab2f", "#a8e063"],
    source="uiGradients — Lush")

_gp("mojito", "Mojito",
    ["#1D976C", "#93F9B9"],
    source="uiGradients — Mojito")

_gp("quepal", "Quepal",
    ["#11998e", "#38ef7d"],
    source="uiGradients — Quepal")

# -- Interesting / fantasy --
_gp("kyoto", "Kyoto",
    ["#c21500", "#ffc500"],
    source="uiGradients — Kyoto")

_gp("witching_hour", "Witching Hour",
    ["#c31432", "#240b36"],
    source="uiGradients — Witching Hour")

_gp("stellar", "Stellar",
    ["#7474BF", "#348AC7"],
    source="uiGradients — Stellar")

_gp("flare", "Flare",
    ["#f12711", "#f5af19"],
    source="uiGradients — Flare")

_gp("crimson_tide", "Crimson Tide",
    ["#642B73", "#C6426E"],
    source="uiGradients — Crimson Tide")

_gp("steel_gray", "Steel Gray",
    ["#1F1C2C", "#928DAB"],
    source="uiGradients — Steel Gray")


def list_gradient_presets() -> list[str]:
    """Return all gradient preset keys in insertion order."""
    return list(GRADIENT_PRESETS.keys())


def get_gradient_preset(key: str) -> GradientPreset:
    """Look up a gradient preset by key. Raises KeyError if unknown."""
    preset = GRADIENT_PRESETS.get(key)
    if preset is None:
        available = ", ".join(GRADIENT_PRESETS)
        raise KeyError(f"Unknown gradient preset {key!r}. Available: {available}")
    return preset


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' to (R, G, B)."""
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _nearest_palette_index(
    r: int, g: int, b: int,
    colors: list[tuple[int, int, int]],
    exclude: set[int] | None = None,
) -> int:
    """Find the palette index with the smallest Euclidean distance."""
    best_idx = 0
    best_dist = float("inf")
    skip = exclude or set()
    for i, (pr, pg, pb) in enumerate(colors):
        if i in skip:
            continue
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def resolve_gradient_to_indices(
    preset: GradientPreset | list[str],
    palette: "U7Palette",
    steps: int = 6,
) -> tuple[list[int], int]:
    """Resolve gradient hex colours to palette indices.

    Interpolates the gradient *colors* into *steps* evenly-spaced
    colours, then maps each to the nearest palette colour.

    Returns ``(gradient_indices, stroke_index)``.
    """
    if isinstance(preset, GradientPreset):
        hex_colors = preset.colors
        stroke_hex = preset.stroke
    else:
        hex_colors = preset
        stroke_hex = "#000000"

    # Interpolate to *steps* evenly-spaced colours
    rgb_stops = [_hex_to_rgb(c) for c in hex_colors]
    if len(rgb_stops) == 1:
        interpolated = [rgb_stops[0]] * steps
    else:
        interpolated = []
        for i in range(steps):
            t = i / max(steps - 1, 1)
            # Position along the stop list
            pos = t * (len(rgb_stops) - 1)
            lo = int(pos)
            hi = min(lo + 1, len(rgb_stops) - 1)
            frac = pos - lo
            r = int(rgb_stops[lo][0] + frac * (rgb_stops[hi][0] - rgb_stops[lo][0]))
            g = int(rgb_stops[lo][1] + frac * (rgb_stops[hi][1] - rgb_stops[lo][1]))
            b = int(rgb_stops[lo][2] + frac * (rgb_stops[hi][2] - rgb_stops[lo][2]))
            interpolated.append((r, g, b))

    # Map stroke
    sr, sg, sb = _hex_to_rgb(stroke_hex)
    stroke_idx = _nearest_palette_index(sr, sg, sb, palette.colors, exclude={255})

    # Map each gradient step to nearest palette colour
    gradient_indices = []
    for r, g, b in interpolated:
        idx = _nearest_palette_index(r, g, b, palette.colors, exclude={255})
        gradient_indices.append(idx)

    return gradient_indices, stroke_idx


# ---------------------------------------------------------------------------
# Game palette auto-discovery
# ---------------------------------------------------------------------------

# Bundled PALETTES.FLX paths relative to the titan-ultima package root.
# These are in the u7data/ directory shipped with the repo.
_BUNDLED_PAL_DIRS: dict[str, str] = {
    "BG": "u7data/gameData_u7_bg_fov/STATIC/PALETTES.FLX",
    "SI": "u7data/gameData_u7_ss_si/STATIC/PALETTES.FLX",
}


def resolve_game_palette(
    game: str,
    palette_file: Optional[str] = None,
    palette_index: int = 0,
) -> Optional["U7Palette"]:
    """Load the game palette for *game* (``"BG"`` or ``"SI"``).

    Resolution order:

    1. *palette_file* — explicit path to a ``PALETTES.FLX`` or ``.pal``.
    2. ``titan.toml`` — look for ``[u7bg.paths].palette`` or
       ``[u7si.paths].palette``.
    3. Bundled ``u7data/`` directory in the titan-ultima repo.

    Returns ``None`` if no palette can be found.
    """
    from titan.u7.palette import U7Palette

    game = game.upper()

    # 1. Explicit file
    if palette_file:
        p = Path(palette_file)
        if p.is_file():
            return U7Palette.from_file(str(p), palette_index=palette_index)

    # 2. titan.toml config
    try:
        from titan._config import get_config
        cfg = get_config()
        section_key = "u7bg" if game == "BG" else "u7si"
        section = cfg.get(section_key, {})
        paths = section.get("paths", {})
        pal_path = paths.get("palette")
        if pal_path:
            p = Path(pal_path)
            if p.is_file():
                return U7Palette.from_file(str(p), palette_index=palette_index)
            # Try relative to game base
            base = section.get("game", {}).get("base")
            if base:
                bp = Path(base) / "STATIC" / pal_path
                if bp.is_file():
                    return U7Palette.from_file(str(bp), palette_index=palette_index)
    except Exception:
        pass

    # 3. Bundled u7data
    rel = _BUNDLED_PAL_DIRS.get(game)
    if rel:
        # Find package root: walk up from this file
        pkg_root = Path(__file__).resolve().parent.parent.parent.parent
        bundled = pkg_root / rel
        if bundled.is_file():
            return U7Palette.from_file(str(bundled), palette_index=palette_index)

    return None
