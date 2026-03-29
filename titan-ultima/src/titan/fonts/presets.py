"""
Font shape presets and TTF registry for U7 font creation.

Contains the metadata for all stock BG/SI font shapes and the registry
of built-in TrueType font sources.
"""

from __future__ import annotations

__all__ = ["FONT_SHAPES", "BUNDLED_TTFS", "get_preset", "get_ttf_path"]

from pathlib import Path

# Root of the bundled font data
_BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"


# ---------------------------------------------------------------------------
# Built-in TTF registry
# ---------------------------------------------------------------------------

BUNDLED_TTFS: dict[str, dict] = {
    "dosVga437": {
        "filename": "dosVga437-win.ttf",
        "label": "dosVga437-win (English DOS VGA 437)",
        "role": "English characters (DOS VGA 437 codepage)",
    },
    "ophidean": {
        "filename": "Ophidean Runes.ttf",
        "label": "Ophidean Runes",
        "role": "Ophidean/Serpentine script",
    },
    "brit_plaques": {
        "filename": "Britannian Runes II.ttf",
        "label": "Britannian Runes II (Plaques)",
        "role": "Britannian runes — large ornate serif",
    },
    "brit_plaquesSmall": {
        "filename": "Britannian Runes II Sans Serif.ttf",
        "label": "Britannian Runes II Sans Serif",
        "role": "Britannian runes — compact sans-serif",
    },
    "brit_signs": {
        "filename": "Britannian Runes I.ttf",
        "label": "Britannian Runes I (Signs)",
        "role": "Britannian runes — sign lettering",
    },
    "gargish": {
        "filename": "Gargish.ttf",
        "label": "Gargish",
        "role": "Gargish language script",
    },
}


def get_ttf_path(key: str) -> Path:
    """Resolve the absolute path to a bundled TTF by registry key."""
    entry = BUNDLED_TTFS.get(key)
    if entry is None:
        available = ", ".join(sorted(BUNDLED_TTFS))
        raise KeyError(f"Unknown TTF key {key!r}. Available: {available}")
    return _BUNDLED_DIR / entry["filename"]


# ---------------------------------------------------------------------------
# Font shape definitions — stock BG / SI layouts
# ---------------------------------------------------------------------------

FONT_SHAPES: dict[int, dict] = {
    0: {
        "name": "Normal yellow",
        "group": "english",
        "cell_height": 14,
        "ink_height": 13,
        "total_frames": 128,
        "frame_range": (0x20, 0x7E),
        "h_lead": -2,
        "games": ["BG", "SI"],
        "ttf_sources": ["dosVga437"],
        "palette_lut": "yellow_text",
        "render_method": "lut",
        "usage": "Main dialogue text, most UI text",
    },
    1: {
        "name": "Large runes",
        "group": "runic",
        "cell_height": 22,
        "ink_height": 21,
        "total_frames": 125,
        "frame_range": (0x21, 0x7C),
        "h_lead": -1,
        "games": ["BG", "SI"],
        "ttf_sources": ["brit_plaques", "brit_plaquesSmall", "brit_signs"],
        "palette_lut": "runic_multicolor",
        "render_method": "lut",
        "usage": "Large signs, plaques, prominent runic inscriptions",
    },
    2: {
        "name": "Small black (zstats)",
        "group": "english",
        "cell_height": 8,
        "ink_height": 7,
        "total_frames": 127,
        "frame_range": (0x21, 0x7E),
        "h_lead": 0,
        "games": ["BG", "SI"],
        "ttf_sources": ["dosVga437"],
        "palette_lut": "black_ink",
        "render_method": "mono",
        "usage": "Z-stats panel, item descriptions, compact UI text",
    },
    3: {
        "name": "Runes",
        "group": "runic",
        "cell_height": 14,
        "ink_height": 13,
        "total_frames": 125,
        "frame_range": (0x21, 0x7C),
        "h_lead": -1,
        "games": ["BG", "SI"],
        "ttf_sources": ["brit_plaques", "brit_plaquesSmall", "brit_signs"],
        "palette_lut": "runic_multicolor",
        "render_method": "lut",
        "usage": "Medium runic text, signs, in-world inscriptions",
    },
    4: {
        "name": "Tiny black (books)",
        "group": "english",
        "cell_height": 6,
        "ink_height": 5,
        "total_frames": 127,
        "frame_range": (0x21, 0x7E),
        "h_lead": 0,
        "games": ["BG", "SI"],
        "ttf_sources": ["dosVga437"],
        "palette_lut": "black_ink",
        "render_method": "mono",
        "usage": "Book text, scrolls, small print",
    },
    5: {
        "name": "Small white glowing (spellbooks)",
        "group": "english",
        "cell_height": 6,
        "ink_height": 5,
        "total_frames": 127,
        "frame_range": (0x21, 0x7E),
        "h_lead": 0,
        "games": ["BG", "SI"],
        "ttf_sources": ["dosVga437"],
        "palette_lut": "white_glow",
        "render_method": "mono",
        "usage": "Spellbook reagent lists, magical text",
    },
    6: {
        "name": "Runes (variant)",
        "group": "runic",
        "cell_height": 14,
        "ink_height": 13,
        "total_frames": 125,
        "frame_range": (0x21, 0x7C),
        "h_lead": -1,
        "games": ["BG", "SI"],
        "ttf_sources": ["brit_plaques", "brit_plaquesSmall", "brit_signs"],
        "palette_lut": "runic_multicolor",
        "render_method": "lut",
        "usage": "Alternate runic text rendering",
    },
    7: {
        "name": "Normal red",
        "group": "english",
        "cell_height": 14,
        "ink_height": 13,
        "total_frames": 128,
        "frame_range": (0x20, 0x7E),
        "h_lead": -2,
        "games": ["BG", "SI"],
        "ttf_sources": ["dosVga437"],
        "palette_lut": "red_text",
        "render_method": "lut",
        "usage": "Highlighted or warning text",
    },
    8: {
        "name": "Serpentine (books)",
        "group": "serpentine",
        "cell_height": 10,
        "ink_height": 9,
        "total_frames": 123,
        "frame_range": (0x20, 0x7A),
        "h_lead": -1,
        "games": ["SI"],
        "ttf_sources": ["ophidean"],
        "palette_lut": "serpentine_metal",
        "render_method": "lut",
        "usage": "Ophidean/Serpentine book text",
    },
    9: {
        "name": "Serpentine (signs)",
        "group": "serpentine",
        "cell_height": 17,
        "ink_height": 16,
        "total_frames": 91,
        "frame_range": (0x21, 0x5A),
        "h_lead": -1,
        "games": ["SI"],
        "ttf_sources": ["ophidean"],
        "palette_lut": "serpentine_metal",
        "render_method": "lut",
        "usage": "Large Ophidean sign text",
    },
    10: {
        "name": "Serpentine (gold signs)",
        "group": "serpentine",
        "cell_height": 17,
        "ink_height": 16,
        "total_frames": 91,
        "frame_range": (0x21, 0x5A),
        "h_lead": 0,
        "games": ["SI"],
        "ttf_sources": ["ophidean"],
        "palette_lut": "serpentine_gold",
        "render_method": "lut",
        "usage": "Gold Ophidean sign text",
    },
}


def get_preset(slot: int) -> dict:
    """Return the preset definition for a font shape slot.

    Raises ``KeyError`` if the slot number is not a known preset.
    """
    if slot not in FONT_SHAPES:
        raise KeyError(f"No preset for font slot {slot}. "
                       f"Known slots: {sorted(FONT_SHAPES)}")
    return FONT_SHAPES[slot]


def presets_for_game(game: str) -> dict[int, dict]:
    """Return only the presets applicable to a specific game.

    *game* should be ``"BG"`` or ``"SI"`` (case-insensitive).
    """
    g = game.upper()
    return {k: v for k, v in FONT_SHAPES.items() if g in v["games"]}
