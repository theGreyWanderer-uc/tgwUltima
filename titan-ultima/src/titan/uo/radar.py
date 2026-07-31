"""Ultima Online radar color table support."""

from __future__ import annotations

__all__ = ["UORadarColor", "UORadarColors"]

from dataclasses import dataclass
from pathlib import Path
import struct

from PIL import Image

from titan.uo.art import expand_color16_rgb


@dataclass(frozen=True)
class UORadarColor:
    """One radarcol.mul color entry."""

    index: int
    color16: int

    @property
    def rgb(self) -> tuple[int, int, int]:
        return expand_color16_rgb(self.color16)


class UORadarColors:
    """Flat radar/minimap color lookup table."""

    def __init__(self, colors: list[UORadarColor]) -> None:
        self.colors = colors

    @classmethod
    def from_file(cls, path: str | Path) -> UORadarColors:
        data = Path(path).read_bytes()
        count = len(data) // 2
        colors = [
            UORadarColor(index, struct.unpack_from("<H", data, index * 2)[0])
            for index in range(count)
        ]
        return cls(colors)

    def to_swatch_image(
        self, *, columns: int = 256, swatch_size: int = 4
    ) -> Image.Image:
        rows = (len(self.colors) + columns - 1) // columns
        image = Image.new(
            "RGBA",
            (columns * swatch_size, rows * swatch_size),
            (0, 0, 0, 0),
        )

        for color in self.colors:
            x0 = (color.index % columns) * swatch_size
            y0 = (color.index // columns) * swatch_size
            red, green, blue = color.rgb
            for y in range(y0, y0 + swatch_size):
                for x in range(x0, x0 + swatch_size):
                    image.putpixel((x, y), (red, green, blue, 255))

        return image
