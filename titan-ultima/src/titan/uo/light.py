"""Ultima Online light mask decoder."""

from __future__ import annotations

__all__ = ["UOLightDecoder"]

from PIL import Image

from titan.uo.indexed import UOIndexEntry


class UOLightDecoder:
    """Decode UO light entries into grayscale RGBA images."""

    @staticmethod
    def decode(entry: UOIndexEntry) -> Image.Image | None:
        width = entry.extra >> 16
        height = entry.extra & 0xFFFF
        data = entry.data

        if width <= 0 or height <= 0 or width > 2048 or height > 2048:
            return None
        if len(data) < width * height:
            return None

        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        offset = 0
        for y in range(height):
            for x in range(width):
                value = data[offset]
                offset += 1
                if value > 0x1F:
                    value = (~value) & 0x1F
                gray = value << 3
                alpha = 255 if value else 0
                image.putpixel((x, y), (gray, gray, gray, alpha))

        return image
