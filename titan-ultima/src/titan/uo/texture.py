"""Ultima Online texture decoder."""

from __future__ import annotations

__all__ = ["UOTextureDecoder"]

import struct

from PIL import Image

from titan.uo.art import expand_color16_rgb
from titan.uo.indexed import UOIndexEntry


class UOTextureDecoder:
    """Decode raw UO land texture entries into RGBA images."""

    @staticmethod
    def decode(entry: UOIndexEntry) -> Image.Image | None:
        data = entry.data
        if len(data) == 0x2000:
            size = 64
        elif len(data) == 0x8000:
            size = 128
        else:
            return None

        image = Image.new("RGBA", (size, size), (0, 0, 0, 255))
        offset = 0
        for y in range(size):
            for x in range(size):
                color = struct.unpack_from("<H", data, offset)[0]
                offset += 2
                r, g, b = expand_color16_rgb(color)
                image.putpixel((x, y), (r, g, b, 255))

        return image
