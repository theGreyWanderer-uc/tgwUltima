"""Ultima Online ASCII font support."""

from __future__ import annotations

__all__ = ["UOAsciiFont", "UOAsciiFonts", "UOFontGlyph"]

from dataclasses import dataclass
from pathlib import Path
import struct

from PIL import Image

from titan.uo.art import color16_to_rgba

_FIRST_CHAR = 0x20
_GLYPH_COUNT = 224


@dataclass(frozen=True)
class UOFontGlyph:
    """One glyph from fonts.mul."""

    index: int
    char_code: int
    width: int
    height: int
    unknown: int
    image: Image.Image | None

    @property
    def char(self) -> str:
        return chr(self.char_code)


@dataclass(frozen=True)
class UOAsciiFont:
    """One ASCII font from fonts.mul."""

    index: int
    header: int
    glyphs: list[UOFontGlyph]

    @property
    def height(self) -> int:
        return max((glyph.height for glyph in self.glyphs), default=0)

    def atlas(self, *, columns: int = 16, padding: int = 1) -> Image.Image:
        cell_width = max((glyph.width for glyph in self.glyphs), default=1)
        cell_height = max((glyph.height for glyph in self.glyphs), default=1)
        rows = (len(self.glyphs) + columns - 1) // columns
        image = Image.new(
            "RGBA",
            (
                columns * (cell_width + padding) + padding,
                rows * (cell_height + padding) + padding,
            ),
            (0, 0, 0, 0),
        )

        for glyph in self.glyphs:
            if glyph.image is None:
                continue
            column = glyph.index % columns
            row = glyph.index // columns
            x = padding + column * (cell_width + padding)
            y = padding + row * (cell_height + padding)
            image.alpha_composite(glyph.image, (x, y))

        return image


class UOAsciiFonts:
    """A fonts.mul file."""

    def __init__(self, fonts: list[UOAsciiFont]) -> None:
        self.fonts = fonts

    @classmethod
    def from_file(cls, path: str | Path, *, max_fonts: int = 10) -> UOAsciiFonts:
        data = Path(path).read_bytes()
        offset = 0
        fonts: list[UOAsciiFont] = []

        for font_index in range(max_fonts):
            if offset >= len(data):
                break

            header = data[offset]
            offset += 1
            glyphs: list[UOFontGlyph] = []

            for glyph_index in range(_GLYPH_COUNT):
                if offset + 3 > len(data):
                    return cls(fonts)

                width = data[offset]
                height = data[offset + 1]
                unknown = data[offset + 2]
                offset += 3
                pixel_bytes = width * height * 2

                if pixel_bytes and offset + pixel_bytes > len(data):
                    return cls(fonts)

                image = None
                if width > 0 and height > 0:
                    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    pos = offset
                    for y in range(height):
                        for x in range(width):
                            color = struct.unpack_from("<H", data, pos)[0]
                            pos += 2
                            image.putpixel((x, y), color16_to_rgba(color))

                offset += pixel_bytes
                glyphs.append(
                    UOFontGlyph(
                        glyph_index,
                        _FIRST_CHAR + glyph_index,
                        width,
                        height,
                        unknown,
                        image,
                    )
                )

            fonts.append(UOAsciiFont(font_index, header, glyphs))

        return cls(fonts)
