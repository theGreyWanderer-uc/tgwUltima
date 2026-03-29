"""
Font creation toolkit for Ultima 7.

Provides a rendering pipeline, palette mapping, preset definitions,
and an interactive wizard for creating U7 FONTS.VGA-compatible shape
files from TrueType font sources.

Public API::

    from titan.fonts.renderer import render_glyph_mono, find_pixel_size_for_cap
    from titan.fonts.palette import PaletteLUT
    from titan.fonts.encoder import glyphs_to_shape
    from titan.fonts.presets import FONT_SHAPES, BUNDLED_TTFS
    from titan.fonts.wizard import run_wizard
"""

from titan.fonts.renderer import (
    find_pixel_size_for_cap,
    render_glyph_mono,
    render_all_glyphs_mono,
    unpack_mono_bitmap,
)
from titan.fonts.palette import PaletteLUT
from titan.fonts.encoder import glyphs_to_shape, GlyphBitmap, FontFrame, EXULT_STUDIO_PREVIEW_FRAME
from titan.fonts.presets import FONT_SHAPES, BUNDLED_TTFS

__all__ = [
    "find_pixel_size_for_cap",
    "render_glyph_mono",
    "render_all_glyphs_mono",
    "unpack_mono_bitmap",
    "PaletteLUT",
    "glyphs_to_shape",
    "GlyphBitmap",
    "FontFrame",
    "EXULT_STUDIO_PREVIEW_FRAME",
    "FONT_SHAPES",
    "BUNDLED_TTFS",
]
