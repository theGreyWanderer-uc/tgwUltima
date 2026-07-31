"""Ultima Online gump image decoder."""

from __future__ import annotations

__all__ = ["UOGumpDecoder"]

import struct

from PIL import Image

from titan.uo.art import color16_to_rgba
from titan.uo.indexed import UOIndexEntry


class UOGumpDecoder:
    """Decode gumpart entries into RGBA images."""

    @staticmethod
    def decode(entry: UOIndexEntry) -> Image.Image | None:
        width = entry.extra >> 16
        height = entry.extra & 0xFFFF
        data = entry.data

        if width <= 0 or height <= 0 or width > 4096 or height > 4096:
            return None
        if len(data) < height * 4:
            return None

        row_offsets = [struct.unpack_from("<I", data, y * 4)[0] for y in range(height)]
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        half_len = len(data) // 4

        for y, row_offset in enumerate(row_offsets):
            pos = row_offset * 4
            if pos < 0 or pos >= len(data):
                return None

            x = 0
            row_end_words = row_offsets[y + 1] if y + 1 < height else half_len
            row_end = min(len(data), row_end_words * 4)
            while x < width and pos + 4 <= row_end:
                color, run_length = struct.unpack_from("<HH", data, pos)
                pos += 4
                if run_length <= 0 or x + run_length > width:
                    return None

                rgba = color16_to_rgba(color)
                for _ in range(run_length):
                    image.putpixel((x, y), rgba)
                    x += 1

            if x != width:
                return None

        return image
