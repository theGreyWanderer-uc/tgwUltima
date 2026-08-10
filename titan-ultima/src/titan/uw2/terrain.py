"""UU2 texture and palette helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TRTexture:
    index: int
    offset: int
    width: int
    height: int
    pixels: bytes

    def to_image(self, palette_rgb: list[int]) -> Image.Image:
        array = np.frombuffer(self.pixels, dtype=np.uint8).reshape(
            (self.height, self.width)
        )
        image = Image.fromarray(array, mode="P")
        image.putpalette(palette_rgb)
        return image.convert("RGBA")


@dataclass(frozen=True)
class TRArchive:
    path: Path
    format_byte: int
    resolution: int
    textures: list[TRTexture]

    @classmethod
    def from_file(cls, path: str | Path) -> "TRArchive":
        path = Path(path)
        data = path.read_bytes()
        if len(data) < 4:
            raise ValueError(f"{path} is too small to be a TR texture archive")

        format_byte = data[0]
        resolution = data[1]
        entries = struct.unpack_from("<H", data, 2)[0]
        table_end = 4 + entries * 4
        if format_byte != 2:
            raise ValueError(f"{path} has unexpected TR format byte {format_byte:#x}")
        if table_end > len(data):
            raise ValueError(f"{path} offset table extends past EOF")

        offsets = list(struct.unpack_from(f"<{entries}I", data, 4))
        size = resolution * resolution
        textures: list[TRTexture] = []
        for index, offset in enumerate(offsets):
            if offset >= len(data) or offset + size > len(data):
                continue
            textures.append(
                TRTexture(
                    index=index,
                    offset=offset,
                    width=resolution,
                    height=resolution,
                    pixels=data[offset : offset + size],
                )
            )
        return cls(
            path=path, format_byte=format_byte, resolution=resolution, textures=textures
        )

    def summary(self) -> dict:
        return {
            "path": str(self.path),
            "format_byte": self.format_byte,
            "resolution": self.resolution,
            "texture_count": len(self.textures),
            "textures": [
                {
                    "index": texture.index,
                    "offset": texture.offset,
                    "width": texture.width,
                    "height": texture.height,
                }
                for texture in self.textures
            ],
        }


def load_palette_rgb(pals_dat: str | Path, palette_index: int = 0) -> list[int]:
    data = Path(pals_dat).read_bytes()
    offset = palette_index * 256 * 3
    end = offset + 256 * 3
    if end > len(data):
        raise ValueError(f"palette {palette_index} is outside {pals_dat}")

    # Underworld palettes are 6-bit VGA RGB values. Scale to 8-bit like
    # UnderworldAdventures and Titan's U7/U8 palette helpers do.
    raw = data[offset:end]
    return [min(component << 2, 255) for component in raw]


def make_contact_sheet(
    images: list[Image.Image], columns: int = 16, padding: int = 2
) -> Image.Image:
    if not images:
        raise ValueError("cannot make a contact sheet without images")

    width, height = images[0].size
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new(
        "RGBA",
        (
            columns * width + (columns + 1) * padding,
            rows * height + (rows + 1) * padding,
        ),
        (20, 20, 20, 255),
    )

    for index, image in enumerate(images):
        x = padding + (index % columns) * (width + padding)
        y = padding + (index // columns) * (height + padding)
        sheet.alpha_composite(image, (x, y))

    return sheet
