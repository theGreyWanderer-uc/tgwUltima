"""
Glyph-to-shape encoder for U7 font creation.

Converts rendered glyph bitmaps (mono or grayscale) into U7Shape objects
ready for writing as ``.shp`` files or patching into FONTS.VGA.
"""

from __future__ import annotations

__all__ = ["GlyphBitmap", "FontFrame", "glyphs_to_shape",
           "EXULT_STUDIO_PREVIEW_FRAME"]

from dataclasses import dataclass

import numpy as np

from titan.u7.shape import U7Shape
from titan.fonts.palette import PaletteLUT

# Exult Studio hardcodes frame 65 ('A') as the thumbnail preview for fonts.
EXULT_STUDIO_PREVIEW_FRAME = 65


@dataclass
class GlyphBitmap:
    """Raw rendered glyph before palette mapping."""

    code: int               # ASCII/Unicode codepoint
    pixels: np.ndarray      # H×W uint8 — mono (0/1) or grayscale (0–255)
    is_mono: bool = True    # True if pixels are 0/1, False if 0–255


@dataclass
class FontFrame:
    """Palette-mapped glyph ready for shape encoding."""

    index: int              # Frame index (= ASCII code in FONTS.VGA)
    pixels: np.ndarray      # H×W uint8 (palette indices, 0xFF=transparent)
    xoff: int = 0
    yoff: int = 0


def glyph_to_font_frame(
    glyph: GlyphBitmap,
    lut: PaletteLUT,
    ink_index: int = 0,
) -> FontFrame:
    """Map a rendered glyph bitmap to palette indices.

    For mono glyphs, ink pixels (1) become *ink_index* and empty
    pixels (0) become transparent (0xFF).

    For grayscale glyphs, the *lut* mapping table is used.
    """
    h, w = glyph.pixels.shape
    result = np.full((h, w), 0xFF, dtype=np.uint8)

    if glyph.is_mono:
        result[glyph.pixels > 0] = ink_index
    else:
        # Apply LUT mapping for each pixel
        for y in range(h):
            for x in range(w):
                val = int(glyph.pixels[y, x])
                result[y, x] = lut.map_value(val)

    return FontFrame(index=glyph.code, pixels=result)


def _pick_preview_glyph(
    glyphs: dict[int, np.ndarray],
    preferred: tuple[int, ...] = (),
) -> int | None:
    """Pick the best glyph to copy into frame 65 as a preview placeholder.

    Tries *preferred* codepoints first (e.g. 71 = 'G' for Gargish),
    then falls back to the widest rendered glyph in *glyphs*.
    Returns the codepoint or ``None`` if *glyphs* is empty.
    """
    for cp in preferred:
        if cp in glyphs and glyphs[cp].shape[1] > 1:
            return cp

    # Fallback: widest non-space glyph
    best_cp: int | None = None
    best_w = 1
    for cp, bmp in glyphs.items():
        if cp == 32:
            continue
        w = bmp.shape[1]
        if w > best_w:
            best_w = w
            best_cp = cp
    return best_cp


def glyphs_to_shape(
    glyphs: dict[int, np.ndarray],
    total_frames: int,
    lut: PaletteLUT,
    *,
    ink_index: int = 0,
    is_mono: bool = True,
    is_indexed: bool = False,
    cell_height: int = 0,
    space_width: int = 0,
    preview_preferred: tuple[int, ...] = (),
) -> tuple[U7Shape, int | None]:
    """Convert a dict of rendered glyph bitmaps into a U7Shape.

    Parameters
    ----------
    glyphs:
        Mapping of codepoint → (H×W) uint8 bitmap (mono 0/1,
        grayscale 0–255, or pre-indexed palette values).
    total_frames:
        Total number of frames in the output shape. Empty frames are
        created for codepoints without glyph data.
    lut:
        Palette LUT for grayscale mapping. For mono rendering, *lut*
        is used only for its transparent index.
    ink_index:
        Palette index for ink pixels (mono mode only).
    is_mono:
        If True, treat glyph pixels as 0/1 mono bitmaps.
    is_indexed:
        If True, glyph pixels are already palette-indexed (0xFF =
        transparent).  Bypass LUT/ink mapping and use values as-is.
    cell_height:
        Total cell height of the font.  When non-zero, every frame
        (including stubs) gets ``yoff = cell_height - 2`` so that
        Exult's ``Font::calc_highlow()`` computes the correct
        baseline.  Original U7 fonts always set ``yabove`` uniformly
        to ``ink_height`` (= ``cell_height - 1``) for every frame.
    space_width:
        Width of the space character (codepoint 32).  When non-zero,
        the space frame is an all-transparent bitmap of this width
        at *cell_height* rows instead of a 1×1 stub.
    preview_preferred:
        Ordered tuple of codepoints to try as preview placeholder for
        frame 65.  E.g. ``(71,)`` for Gargish ('G'), ``(82,)`` for
        Runic ('R').  Falls back to widest rendered glyph.

    Returns
    -------
    tuple[U7Shape, int | None]
        The shape and the codepoint that was copied into frame 65 as
        a preview placeholder, or ``None`` if frame 65 already had
        real content.
    """
    # Derive baseline offset.  Original fonts use yabove = ink_height
    # = cell_height - 1 for *every* frame (ink + stubs).
    if cell_height > 1:
        yoff = cell_height - 2   # yabove = ink_height = cell_height - 1
    else:
        yoff = 0

    shape = U7Shape()

    for idx in range(total_frames):
        frame = U7Shape.Frame()

        if idx in glyphs:
            bmp = glyphs[idx]
            if is_indexed:
                # Pixels are already palette-indexed — use as-is
                frame.width = bmp.shape[1]
                frame.height = bmp.shape[0]
                frame.xoff = 0
                frame.yoff = yoff
                frame.pixels = bmp
            else:
                gb = GlyphBitmap(code=idx, pixels=bmp, is_mono=is_mono)
                ff = glyph_to_font_frame(gb, lut, ink_index=ink_index)
                frame.width = ff.pixels.shape[1]
                frame.height = ff.pixels.shape[0]
                frame.xoff = 0
                frame.yoff = yoff
                frame.pixels = ff.pixels
        elif idx == 32 and space_width > 0 and cell_height > 0:
            # Space — all-transparent frame at proper font dimensions
            frame.width = space_width
            frame.height = cell_height
            frame.xoff = 0
            frame.yoff = yoff
            frame.pixels = np.full(
                (cell_height, space_width), 0xFF, dtype=np.uint8
            )
        else:
            # Empty stub — 1 pixel wide at full cell height
            stub_h = cell_height if cell_height > 0 else 1
            frame.width = 1
            frame.height = stub_h
            frame.xoff = 0
            frame.yoff = yoff
            frame.pixels = np.full(
                (stub_h, 1), 0xFF, dtype=np.uint8
            )

        shape.frames.append(frame)

    # --- Exult Studio preview placeholder ---
    # If frame 65 ('A') ended up as a stub (width ≤ 1), copy a
    # representative rendered glyph there so Exult Studio shows a
    # meaningful thumbnail instead of a blank square.
    preview_src: int | None = None
    pf = EXULT_STUDIO_PREVIEW_FRAME
    if pf < len(shape.frames) and shape.frames[pf].width <= 1:
        donor_cp = _pick_preview_glyph(glyphs, preferred=preview_preferred)
        if donor_cp is not None and donor_cp < len(shape.frames):
            src = shape.frames[donor_cp]
            if src.width > 1:
                dst = shape.frames[pf]
                dst.width = src.width
                dst.height = src.height
                dst.xoff = src.xoff
                dst.yoff = src.yoff
                dst.pixels = src.pixels.copy()
                preview_src = donor_cp

    return shape, preview_src
