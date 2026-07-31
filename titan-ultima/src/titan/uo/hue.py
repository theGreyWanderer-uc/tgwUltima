"""Ultima Online hue table reader and exporter."""

from __future__ import annotations

__all__ = ["UOHue", "UOHuesFile"]

from dataclasses import dataclass
from pathlib import Path
import struct

from PIL import Image

from titan.uo.art import expand_color16_rgb

_HUE_ENTRY_SIZE = 88
_HUE_GROUP_SIZE = 4 + _HUE_ENTRY_SIZE * 8


@dataclass(frozen=True)
class UOHue:
    """One 32-colour hue ramp."""

    index: int
    group: int
    entry: int
    colors: tuple[int, ...]
    table_start: int
    table_end: int
    name: str

    @property
    def client_id(self) -> int:
        return self.index + 1

    def to_image(self, swatch_size: int = 8) -> Image.Image:
        width = 32 * swatch_size
        image = Image.new("RGBA", (width, swatch_size), (0, 0, 0, 255))
        for i, color in enumerate(self.colors):
            r, g, b = expand_color16_rgb(color)
            for y in range(swatch_size):
                for x in range(swatch_size):
                    image.putpixel((i * swatch_size + x, y), (r, g, b, 255))
        return image


class UOHuesFile:
    """Parsed hues.mul file."""

    def __init__(self, hues: list[UOHue]) -> None:
        self.hues = hues

    @classmethod
    def from_file(cls, path: str | Path) -> UOHuesFile:
        data = Path(path).read_bytes()
        hues: list[UOHue] = []
        group_count = len(data) // _HUE_GROUP_SIZE

        for group in range(group_count):
            group_offset = group * _HUE_GROUP_SIZE + 4
            for entry in range(8):
                offset = group_offset + entry * _HUE_ENTRY_SIZE
                colors = struct.unpack_from("<32H", data, offset)
                table_start, table_end = struct.unpack_from("<HH", data, offset + 64)
                name_bytes = data[offset + 68 : offset + 88]
                name = name_bytes.split(b"\0", 1)[0].decode("ascii", errors="replace")
                hues.append(
                    UOHue(
                        index=len(hues),
                        group=group,
                        entry=entry,
                        colors=colors,
                        table_start=table_start,
                        table_end=table_end,
                        name=name,
                    )
                )

        return cls(hues)
