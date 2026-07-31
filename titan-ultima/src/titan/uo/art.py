"""Ultima Online art image decoders."""

from __future__ import annotations

__all__ = ["UOArtDecoder", "color16_to_rgba", "expand_color16_rgb"]

import struct

from PIL import Image

from titan.uo.indexed import UOIndexEntry

_EXPAND_5BIT = tuple((value << 3) | (value >> 2) for value in range(32))
_LAND_TILE_PIXELS = 1012


def expand_color16_rgb(value: int) -> tuple[int, int, int]:
    """Expand UO 16-bit colour storage to RGB."""
    red = _EXPAND_5BIT[(value >> 10) & 0x1F]
    green = _EXPAND_5BIT[(value >> 5) & 0x1F]
    blue = _EXPAND_5BIT[value & 0x1F]
    return (red, green, blue)


def color16_to_rgba(value: int) -> tuple[int, int, int, int]:
    """Convert UO 16-bit colour storage to RGBA."""
    if value == 0:
        return (0, 0, 0, 0)
    red, green, blue = expand_color16_rgb(value)
    return (red, green, blue, 255)


class UOArtDecoder:
    """Decode land-tile and static-art entries."""

    @staticmethod
    def decode(entry: UOIndexEntry) -> Image.Image | None:
        if entry.index < 0x4000:
            return UOArtDecoder.decode_land(entry.data)
        return UOArtDecoder.decode_static(entry.data)

    @staticmethod
    def decode_land(data: bytes) -> Image.Image | None:
        if len(data) < _LAND_TILE_PIXELS * 2:
            return None

        image = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
        offset = 0

        for y in range(22):
            start = 22 - (y + 1)
            end = start + ((y + 1) * 2)
            for x in range(start, end):
                color = struct.unpack_from("<H", data, offset)[0]
                image.putpixel((x, y), color16_to_rgba(color))
                offset += 2

        for y in range(22):
            row = y + 22
            start = y
            end = start + ((22 - y) * 2)
            for x in range(start, end):
                color = struct.unpack_from("<H", data, offset)[0]
                image.putpixel((x, row), color16_to_rgba(color))
                offset += 2

        return image

    @staticmethod
    def decode_static(data: bytes) -> Image.Image | None:
        if len(data) < 8:
            return None

        _header, width, height = struct.unpack_from("<Ihh", data, 0)
        if width <= 0 or height <= 0 or width > 2048 or height > 2048:
            return None

        row_table_start = 8
        row_table_end = row_table_start + height * 2
        if row_table_end > len(data):
            return None

        row_offsets = [
            struct.unpack_from("<H", data, row_table_start + y * 2)[0]
            for y in range(height)
        ]
        row_data_start = row_table_end
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        for y, row_offset in enumerate(row_offsets):
            pos = row_data_start + row_offset * 2
            x = 0
            guard = 0

            while pos + 4 <= len(data):
                x_skip, run_length = struct.unpack_from("<HH", data, pos)
                pos += 4
                guard += 1

                if x_skip == 0 and run_length == 0:
                    break
                if guard > width + 1 or run_length <= 0:
                    return None

                x += x_skip
                if x + run_length > width or pos + run_length * 2 > len(data):
                    return None

                for _ in range(run_length):
                    color = struct.unpack_from("<H", data, pos)[0]
                    pos += 2
                    image.putpixel((x, y), color16_to_rgba(color))
                    x += 1

        return image
