"""Strict validation of standalone U7 shapes before inserting archive records."""

from __future__ import annotations

import struct


def validate_u7_shape_data(data: bytes, *, is_tile: bool = False) -> None:
    """Reject invalid frame tables, extents and RLE spans before any archive write."""
    if is_tile:
        if not data or len(data) % 64:
            raise ValueError("U7 flat shape must contain complete 64-byte frames")
        return

    if len(data) < 8:
        raise ValueError("U7 RLE shape is missing its size and frame table")
    shape_size, first_offset = struct.unpack_from("<II", data)
    if shape_size != len(data) and not (
        len(data) % 2 == 0 and shape_size == len(data) - 1
    ):
        raise ValueError("U7 RLE shape size does not match its file length")
    if first_offset < 8 or first_offset >= shape_size or (first_offset - 4) % 4:
        raise ValueError("U7 RLE shape has an invalid frame table")

    frame_count = (first_offset - 4) // 4
    offsets = list(struct.unpack_from(f"<{frame_count}I", data, 4))
    offsets.append(shape_size)
    for frame_index in range(frame_count):
        start, end = offsets[frame_index : frame_index + 2]
        if start < first_offset or end <= start or end > shape_size:
            raise ValueError(f"U7 RLE frame {frame_index} has invalid bounds")
        _validate_u7_rle_frame(data, start, end, frame_index)


def _validate_u7_rle_frame(data: bytes, start: int, end: int, frame_index: int) -> None:
    """Check one frame's spans within its declared byte and pixel bounds."""
    error_prefix = f"U7 RLE frame {frame_index}"
    if end - start < 8:
        raise ValueError(f"{error_prefix} is missing its extents")
    xright, xleft, yabove, ybelow = struct.unpack_from("<hhhh", data, start)
    width, height = xleft + xright + 1, yabove + ybelow + 1
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError(f"{error_prefix} has invalid dimensions: {width}x{height}")
    # Exult also accepts an extents-only frame as fully transparent.
    if end - start == 8:
        return

    position = start + 8
    while position + 2 <= end:
        scan_length = struct.unpack_from("<H", data, position)[0]
        position += 2
        if scan_length == 0:
            return
        pixel_count = scan_length >> 1
        if pixel_count == 0 or position + 4 > end:
            raise ValueError(f"{error_prefix} has an incomplete span header")
        scan_x, scan_y = struct.unpack_from("<hh", data, position)
        position += 4
        pixel_x, pixel_y = scan_x + xleft, scan_y + yabove
        if not (
            0 <= pixel_y < height and 0 <= pixel_x and pixel_x + pixel_count <= width
        ):
            raise ValueError(f"{error_prefix} has a span outside its dimensions")

        if not scan_length & 1:
            position += pixel_count
            if position > end:
                raise ValueError(f"{error_prefix} has truncated raw pixels")
            continue

        remaining = pixel_count
        while remaining:
            if position >= end:
                raise ValueError(f"{error_prefix} has truncated encoded pixels")
            block = data[position]
            position += 1
            count = block >> 1
            if not 0 < count <= remaining:
                raise ValueError(f"{error_prefix} has an invalid RLE block length")
            position += 1 if block & 1 else count
            if position > end:
                raise ValueError(f"{error_prefix} has truncated encoded pixels")
            remaining -= count

    raise ValueError(f"{error_prefix} is missing its end marker")
