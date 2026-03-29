"""
FreeType glyph rendering for U7 font creation.

Provides mono (1-bit) and grayscale glyph rendering from TrueType fonts,
extracted and generalized from the font analysis test scripts.
"""

from __future__ import annotations

__all__ = [
    "find_pixel_size_for_cap",
    "render_glyph_mono",
    "render_all_glyphs_mono",
    "render_glyph_grayscale",
    "render_all_glyphs_grayscale",
    "render_all_glyphs_hollow_gradient",
    "unpack_mono_bitmap",
]

import numpy as np
import freetype


def unpack_mono_bitmap(bitmap) -> np.ndarray:
    """Unpack a FreeType mono (1-bit) bitmap into a uint8 numpy array.

    Returns a (rows, width) array where ink pixels are 1 and empty
    pixels are 0.
    """
    rows, width, pitch = bitmap.rows, bitmap.width, bitmap.pitch
    buf = bitmap.buffer
    result = np.zeros((rows, width), dtype=np.uint8)
    for y in range(rows):
        row_start = y * pitch
        for x in range(width):
            byte_idx = row_start + (x >> 3)
            bit_idx = 7 - (x & 7)
            if buf[byte_idx] & (1 << bit_idx):
                result[y, x] = 1
    return result


def find_pixel_size_for_cap(font_path: str, target_ink_h: int) -> int:
    """Find the FreeType pixel size that produces capital letters at
    exactly *target_ink_h* pixels tall.

    Scans pixel sizes 4–64 and returns the first size where a capital
    letter's rendered bitmap height matches *target_ink_h*.
    """
    face = freetype.Face(str(font_path))
    test_chars = ["A", "M", "H", "X"]
    for px in range(4, 65):
        face.set_pixel_sizes(0, px)
        for ch in test_chars:
            try:
                face.load_char(
                    ch,
                    freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO,
                )
                bmp = face.glyph.bitmap
                if bmp.rows == target_ink_h:
                    return px
                if bmp.rows > 0:
                    break
            except Exception:
                continue
    return target_ink_h + 1


def render_glyph_mono(
    face: freetype.Face,
    char: str,
    cell_height: int,
) -> np.ndarray | None:
    """Render a single glyph as a hinted mono bitmap placed on a canvas.

    Returns an (cell_height, canvas_width) uint8 array where ink pixels
    are 1 and empty pixels are 0, or ``None`` if the glyph is empty.
    The canvas width includes a 1-pixel right margin.
    """
    ink_height = cell_height - 1
    try:
        face.load_char(
            char,
            freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO,
        )
    except Exception:
        return None

    bmp = face.glyph.bitmap
    bt = face.glyph.bitmap_top
    bl = face.glyph.bitmap_left

    if bmp.rows == 0 or bmp.width == 0:
        return None

    bits = unpack_mono_bitmap(bmp)
    y_off = ink_height - bt
    if y_off < 0:
        bits = bits[-y_off:]
        y_off = 0

    x_off = max(bl, 0)
    glyph_h, glyph_w = bits.shape
    canvas_w = max(x_off + glyph_w, 1) + 1  # +1 right margin
    canvas = np.zeros((cell_height, canvas_w), dtype=np.uint8)
    y_end = min(y_off + glyph_h, cell_height)
    x_end = min(x_off + glyph_w, canvas_w - 1)
    copy_h = y_end - y_off
    copy_w = x_end - x_off
    canvas[y_off:y_off + copy_h, x_off:x_off + copy_w] = bits[:copy_h, :copy_w]

    if not np.any(canvas):
        return None
    return canvas


def render_glyph_grayscale(
    face: freetype.Face,
    char: str,
    cell_height: int,
) -> np.ndarray | None:
    """Render a single glyph as an 8-bit grayscale bitmap.

    Returns an (cell_height, canvas_width) uint8 array where values
    range from 0 (empty) to 255 (full ink), or ``None`` if empty.
    """
    ink_height = cell_height - 1
    try:
        face.load_char(char, freetype.FT_LOAD_RENDER)
    except Exception:
        return None

    bmp = face.glyph.bitmap
    bt = face.glyph.bitmap_top
    bl = face.glyph.bitmap_left

    if bmp.rows == 0 or bmp.width == 0:
        return None

    # Grayscale buffer is already a flat uint8 array
    buf = np.array(bmp.buffer, dtype=np.uint8).reshape((bmp.rows, bmp.width))

    y_off = ink_height - bt
    if y_off < 0:
        buf = buf[-y_off:]
        y_off = 0

    x_off = max(bl, 0)
    glyph_h, glyph_w = buf.shape
    canvas_w = max(x_off + glyph_w, 1) + 1
    canvas = np.zeros((cell_height, canvas_w), dtype=np.uint8)
    y_end = min(y_off + glyph_h, cell_height)
    x_end = min(x_off + glyph_w, canvas_w - 1)
    copy_h = y_end - y_off
    copy_w = x_end - x_off
    canvas[y_off:y_off + copy_h, x_off:x_off + copy_w] = buf[:copy_h, :copy_w]

    if not np.any(canvas):
        return None
    return canvas


def render_all_glyphs_mono(
    font_path: str,
    cell_height: int,
    code_range: range | None = None,
) -> tuple[dict[int, np.ndarray], int]:
    """Render all glyphs from a TTF as mono bitmaps.

    Returns ``(glyphs, pixel_size)`` where *glyphs* maps codepoint →
    (cell_height × width) uint8 array (0/1).
    """
    ink_h = cell_height - 1
    px_size = find_pixel_size_for_cap(font_path, ink_h)
    face = freetype.Face(str(font_path))
    face.set_pixel_sizes(0, px_size)

    if code_range is None:
        code_range = range(0x21, 0x7F)

    glyphs: dict[int, np.ndarray] = {}
    for code in code_range:
        bmp = render_glyph_mono(face, chr(code), cell_height)
        if bmp is not None:
            glyphs[code] = bmp
    return glyphs, px_size


def render_all_glyphs_grayscale(
    font_path: str,
    cell_height: int,
    code_range: range | None = None,
) -> tuple[dict[int, np.ndarray], int]:
    """Render all glyphs from a TTF as grayscale bitmaps.

    Returns ``(glyphs, pixel_size)`` where *glyphs* maps codepoint →
    (cell_height × width) uint8 array (0–255).
    """
    ink_h = cell_height - 1
    px_size = find_pixel_size_for_cap(font_path, ink_h)
    face = freetype.Face(str(font_path))
    face.set_pixel_sizes(0, px_size)

    if code_range is None:
        code_range = range(0x21, 0x7F)

    glyphs: dict[int, np.ndarray] = {}
    for code in code_range:
        bmp = render_glyph_grayscale(face, chr(code), cell_height)
        if bmp is not None:
            glyphs[code] = bmp
    return glyphs, px_size


# ---------------------------------------------------------------------------
# Hollow gradient rendering (stroke outline + vertical gradient fill)
# ---------------------------------------------------------------------------

def _erode_binary(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    """Morphological erosion of a binary mask using a 4-connected kernel."""
    result = mask.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1, mode='constant', constant_values=0)
        result = (
            padded[1:-1, 1:-1] &
            padded[0:-2, 1:-1] &
            padded[2:,   1:-1] &
            padded[1:-1, 0:-2] &
            padded[1:-1, 2:]
        )
    return result


def _build_gradient_row_lut(
    ink_top: int,
    ink_bottom: int,
    height: int,
    gradient_indices: list[int],
) -> list[int]:
    """Build a per-row lookup table of palette indices for a vertical gradient."""
    transparent = 0xFF
    span = ink_bottom - ink_top
    if span <= 0:
        mid = gradient_indices[len(gradient_indices) // 2]
        return [mid] * height

    n = len(gradient_indices)
    lut = [transparent] * height
    for y in range(ink_top, ink_bottom + 1):
        t = (y - ink_top) / max(span, 1)
        idx = min(int(t * n), n - 1)
        lut[y] = gradient_indices[idx]
    return lut


def _render_hollow_gradient_glyph(
    face: freetype.Face,
    char: str,
    cell_height: int,
    gradient_indices: list[int],
    stroke_width: int = 1,
    stroke_index: int = 0,
) -> np.ndarray | None:
    """Render a single glyph with stroke outline and vertical gradient fill.

    Returns an (cell_height, width) uint8 array of palette indices
    (0xFF = transparent), or ``None`` if the glyph is empty.
    """
    mono = render_glyph_mono(face, char, cell_height)
    if mono is None:
        return None

    h, w = mono.shape
    ink_mask = mono > 0
    interior = _erode_binary(ink_mask, iterations=stroke_width)
    stroke_mask = ink_mask & ~interior

    ink_rows = np.where(np.any(ink_mask, axis=1))[0]
    if len(ink_rows) == 0:
        return None
    ink_top = int(ink_rows[0])
    ink_bottom = int(ink_rows[-1])

    row_lut = _build_gradient_row_lut(ink_top, ink_bottom, h, gradient_indices)

    result = np.full((h, w), 0xFF, dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            if interior[y, x]:
                result[y, x] = row_lut[y]
    result[stroke_mask] = stroke_index
    return result


def render_all_glyphs_hollow_gradient(
    font_path: str,
    cell_height: int,
    gradient_indices: list[int],
    stroke_width: int = 1,
    stroke_index: int = 0,
    code_range: range | None = None,
) -> tuple[dict[int, np.ndarray], int]:
    """Render all glyphs with stroke outline and vertical gradient fill.

    Returns ``(glyphs, pixel_size)`` where *glyphs* maps codepoint →
    (cell_height × width) uint8 array of palette indices (0xFF =
    transparent).
    """
    ink_h = cell_height - 1
    px_size = find_pixel_size_for_cap(font_path, ink_h)
    face = freetype.Face(str(font_path))
    face.set_pixel_sizes(0, px_size)

    if code_range is None:
        code_range = range(0x21, 0x7F)

    glyphs: dict[int, np.ndarray] = {}
    for code in code_range:
        bmp = _render_hollow_gradient_glyph(
            face, chr(code), cell_height,
            gradient_indices, stroke_width, stroke_index,
        )
        if bmp is not None:
            glyphs[code] = bmp
    return glyphs, px_size
