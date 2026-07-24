"""
Font/glyph decoder for Ultima 6 (``U6.CH``).

Not documented in ``u6data/u6tech.txt`` beyond a brief note that the font
is "256 characters, 8x8 pixels, 2 colors, 8 bytes each." Confirmed and
extended directly against a real ``U6.CH`` (2048 bytes = 256 x 8, exact
match) and against Nuvie's ``fonts/FontManager.cpp``/``U6Font.cpp``,
which reveal the file is actually **two** 128-glyph fonts back to back::

    bytes    0-1023  glyphs   0-127   "english font"     (FontManager.cpp's own comment)
    bytes 1024-2047  glyphs 128-255   "runic & gargoyle font"

The second font is the one covering the gargoyle language / runic script
seen in-game (the ``<...>`` "Britannian text" escape in printable strings,
see :mod:`titan.u6.converse`, and Gargish dialogue, gated by the
``U6TALK_VAR_GARGF`` flag in Nuvie's ``Converse.h``). Both fonts share the
same 128-glyph layout, indexed by ASCII code 0-127 -- Nuvie's own loader
treats them identically (``U6Font::init(data, 128, 0)`` for each), just
pointed at a different 1024-byte half of the file.

Each glyph is 8 bytes, one per row, most-significant-bit first (bit 7 of
byte N is column 0 of row N) -- ported from ``U6Font::drawChar``'s pixel
loop. There is no per-pixel colour: a glyph is a 1-bit stencil, coloured
at draw time (Nuvie uses ``FONT_COLOR_U6_NORMAL``/``_HIGHLIGHT`` as
palette indices, not baked into the font data).

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.font import U6Fonts

    fonts = U6Fonts.from_file("C:/Ultima/Ultima6/U6.CH")
    fonts.english.to_pil_image(ord("A")).save("letter_A.png")
    fonts.runic.to_pil_image(ord("A")).save("rune_A.png")  # the gargoyle/runic glyph for 'A'
    fonts.runic.render_text("HELLO").save("gargish_hello.png")
"""

from __future__ import annotations

__all__ = ["U6Font", "U6Fonts", "U6FontError", "GLYPHS_PER_FONT", "GLYPH_DIM"]

import os

import numpy as np
from PIL import Image

GLYPHS_PER_FONT = 128
GLYPH_BYTES = 8
GLYPH_DIM = 8
FONT_BYTES = GLYPHS_PER_FONT * GLYPH_BYTES  # 1024
FILE_SIZE = FONT_BYTES * 2  # 2048


class U6FontError(Exception):
    """Raised when font data is too short."""


class U6Font:
    """One 128-glyph, 8x8 1-bit font (either half of ``U6.CH``)."""

    def __init__(self, data: bytes) -> None:
        if len(data) < FONT_BYTES:
            raise U6FontError(f"font data too short: {len(data)} bytes, need {FONT_BYTES}")
        self._data = data

    def glyph_array(self, char_code: int) -> np.ndarray:
        """Return one glyph as an 8x8 uint8 array (1 = foreground pixel, 0 = background)."""
        if char_code < 0 or char_code >= GLYPHS_PER_FONT:
            raise U6FontError(f"char_code {char_code} out of range (0..{GLYPHS_PER_FONT - 1})")
        rows = np.frombuffer(self._data, dtype=np.uint8, count=GLYPH_BYTES, offset=char_code * GLYPH_BYTES)
        return np.unpackbits(rows.reshape(GLYPH_DIM, 1), axis=1, count=GLYPH_DIM, bitorder="big")

    def to_pil_image(
        self,
        char_code: int,
        fg: tuple[int, int, int] = (255, 255, 255),
        bg: tuple[int, int, int] | None = None,
    ) -> Image.Image:
        """
        Render one glyph to an 8x8 image.

        Args:
            bg: background colour, or ``None`` (default) for a transparent
                background (RGBA output). A concrete colour gives RGB output.
        """
        arr = self.glyph_array(char_code)
        if bg is None:
            rgba = np.zeros((GLYPH_DIM, GLYPH_DIM, 4), dtype=np.uint8)
            rgba[arr == 1] = (*fg, 255)
            return Image.fromarray(rgba, mode="RGBA")
        rgb = np.empty((GLYPH_DIM, GLYPH_DIM, 3), dtype=np.uint8)
        rgb[arr == 1] = fg
        rgb[arr == 0] = bg
        return Image.fromarray(rgb, mode="RGB")

    def render_text(
        self,
        text: str,
        fg: tuple[int, int, int] = (255, 255, 255),
        bg: tuple[int, int, int] | None = None,
        scale: int = 1,
    ) -> Image.Image:
        """Render a string to a single image, one glyph per character (unknown/out-of-range chars render blank)."""
        n = len(text)
        mode = "RGBA" if bg is None else "RGB"
        fill = (0, 0, 0, 0) if bg is None else bg
        img = Image.new(mode, (GLYPH_DIM * n, GLYPH_DIM), fill)
        for i, ch in enumerate(text):
            code = ord(ch)
            if 0 <= code < GLYPHS_PER_FONT:
                img.paste(self.to_pil_image(code, fg=fg, bg=bg), (i * GLYPH_DIM, 0))
        if scale != 1:
            img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        return img

    def to_contact_sheet(self, cols: int = 16, scale: int = 2) -> Image.Image:
        """Render all 128 glyphs as a labeled-position grid (no labels; positions ARE the char codes)."""
        rows = (GLYPHS_PER_FONT + cols - 1) // cols
        sheet = Image.new("RGB", (cols * GLYPH_DIM * scale, rows * GLYPH_DIM * scale), (0, 0, 0))
        for code in range(GLYPHS_PER_FONT):
            glyph = self.to_pil_image(code, bg=(0, 0, 0))
            glyph = glyph.resize((GLYPH_DIM * scale, GLYPH_DIM * scale), Image.NEAREST)
            x, y = (code % cols) * GLYPH_DIM * scale, (code // cols) * GLYPH_DIM * scale
            sheet.paste(glyph, (x, y))
        return sheet


class U6Fonts:
    """Both fonts stored in ``U6.CH``: :attr:`english` and :attr:`runic` (the gargoyle/runic font)."""

    def __init__(self, english: U6Font, runic: U6Font) -> None:
        self.english = english
        self.runic = runic

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U6Fonts:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> U6Fonts:
        if len(data) < FILE_SIZE:
            raise U6FontError(f"U6.CH data too short: {len(data)} bytes, need {FILE_SIZE}")
        return cls(english=U6Font(data[:FONT_BYTES]), runic=U6Font(data[FONT_BYTES:FILE_SIZE]))
