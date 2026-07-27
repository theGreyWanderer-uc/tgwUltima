"""
Texture (bitmap) reader for Ultima 9: Ascension's model texture archives:
``static/bitmap16.flx``, ``static/bitmapC.flx``, and ``static/bitmapsh.flx``.

Ported from the real, open-source Blender importer
``Chevluh/Ultima-9-Blender-Importer``'s ``ultimaModelImporter.py``
(``makeTexture()``/``readTextureSetHeader()``/``readFrameRecord()``/
``readFrameHeader()``), found locally at
``D:\\_Repos\\_UltimaIX\\Ultima-9-Blender-Importer``. A :class:`U9Material`
(see :mod:`titan.u9.model`) references one of these archives by
``texture_id`` (the FLX entry index) and ``cur_frame`` (the animation
frame within that entry, for animated textures -- most materials have
only 1 frame).

Container layout, all offsets relative to the start of one FLX entry's
own bytes (i.e. ``U9FlxArchive.read_entry(texture_id)``)::

    0x00  frame_width    u16  -- max width across all frames
    0x02  format         u16  -- mip level count (not a format enum, despite the name)
    0x04  frame_height   u16  -- max height across all frames
    0x06  compression    u16  -- 0 = raw/uncompressed (supported here), nonzero = an
                                actually-compressed pixel format the reference importer
                                never implements either -- see below
    0x08  frame_count    u32
    0x0C  (unknown)      u32
    0x10  frame directory: frame_count * (offset: u32, length: u32)

Each frame directory entry points (relative to the entry start) at a
per-frame header::

    +0x00  unknown1   u16  -- bit 8 (0x100) is the "is_transparent" flag
    +0x02  unknown2   u16  -- usually 0x6000
    +0x04  width      u32
    +0x08  height     u32
    +0x0C  (unknown)  u32
    +0x10  (unknown)  u32
    +0x14  row offset table: height * u32 (unused here -- pixels are
           read sequentially instead, see below)

Pixel data immediately follows the row-offset table (at
``+0x14 + 4*height``). It contains the base-resolution image followed
by a full mip chain (progressively quartered), but -- matching the
reference importer's own behavior -- only the base ``width*height``
pixels are read here; the mip tail is simply left unconsumed.

Bits per pixel is not stored directly; it's inferred by comparing the
frame's recorded byte length against the byte length a full 8-bit
(1 byte/pixel) mip chain would occupy at this width/height/mip-count
-- if they match, it's 8-bit **paletted** (see :mod:`titan.u9.palette`
-- pass a ``palette`` to get the real colors; without one, this falls
back to flat grayscale, which is real but visually flatter than
intended), otherwise it's 16-bit (565 if not transparent, 5551 if
transparent).

**Known real-data limitation**: ``compression != 0`` is rejected with
:class:`U9TextureError` rather than guessed at. Checked against every
real entry in this project's test copy of the game: ``bitmap16.flx``
and ``bitmapsh.flx`` are 100% ``compression=0`` (fully decodable --
confirmed visually too: a legible "default" placeholder texture, a
fire sprite with correct alpha, and a grayscale placeholder all
decoded correctly). ``bitmapC.flx`` (likely "C" for "compressed") is
mostly (5,687 of 6,576) ``compression=1``; those entries are simply
not raw pixel data, and the reference importer has no decode path for
them either (its own byte-length-based is8bit heuristic isn't a
reliable stand-in for the real ``compression`` field -- treating it as
one on real ``compression=1`` data produced a plausible-looking
buffer-length match on 195 of 5,687 entries purely by chance, which
would have silently decoded compressed bytes as if they were raw
pixels; checking ``compression`` directly avoids that). Prefer
``bitmap16.flx`` (or ``bitmapsh.flx``) as the texture archive passed to
:func:`titan.u9.mesh_export.export_obj`.
"""

from __future__ import annotations

__all__ = ["U9TextureFrame", "U9TextureError", "decode_frame"]

import struct
from dataclasses import dataclass
from typing import Optional

from titan.u9.palette import U9Palette

TEXTURE_SET_HEADER_SIZE = 0x10
FRAME_DIR_ENTRY_SIZE = 0x08
FRAME_HEADER_SIZE = 0x14


class U9TextureError(Exception):
    """Raised when a texture entry/frame is too small or malformed to parse."""


@dataclass(frozen=True)
class U9TextureFrame:
    """One decoded texture frame: base-resolution RGBA pixels, row-major, top-to-bottom."""

    width: int
    height: int
    pixels_rgba: bytes
    """``width * height * 4`` bytes, one byte per channel, 0-255."""
    is_transparent: bool


def decode_frame(entry_data: bytes, frame_index: int = 0, palette: Optional[U9Palette] = None) -> U9TextureFrame:
    """
    Decode one frame from a texture archive's FLX entry bytes.

    ``palette`` (see :mod:`titan.u9.palette`, ``static/ankh.pal``) is
    only consulted for 8-bit frames; 16-bit frames ignore it entirely.
    Without one, 8-bit frames fall back to flat grayscale.
    """
    if len(entry_data) < TEXTURE_SET_HEADER_SIZE:
        raise U9TextureError(f"data too small for a texture-set header: {len(entry_data)} bytes")

    _frame_width, mip_count, _frame_height, compression = struct.unpack_from("<4H", entry_data, 0x00)
    frame_count = struct.unpack_from("<I", entry_data, 0x08)[0]

    if compression != 0:
        raise U9TextureError(
            f"unsupported compression scheme (compression={compression}); this decoder (like the "
            f"reference importer it's ported from) only handles raw/uncompressed pixel data "
            f"(compression=0) -- see the module docstring"
        )

    if not (0 <= frame_index < frame_count):
        raise U9TextureError(f"frame_index {frame_index} out of range (0..{frame_count - 1})")

    dir_pos = TEXTURE_SET_HEADER_SIZE + frame_index * FRAME_DIR_ENTRY_SIZE
    try:
        frame_offset, frame_length = struct.unpack_from("<2I", entry_data, dir_pos)

        unknown1, _unknown2 = struct.unpack_from("<2H", entry_data, frame_offset)
        width, height, _u3, _u4 = struct.unpack_from("<4I", entry_data, frame_offset + 4)
    except struct.error as e:
        raise U9TextureError(f"malformed frame directory/header: {e}") from e

    is_transparent = (unknown1 >> 8) & 1 == 1

    header_size = FRAME_HEADER_SIZE + 4 * height
    mip_sample_count = float(width * height)
    total_sample_count = mip_sample_count
    for _ in range(mip_count):
        mip_sample_count /= 4
        total_sample_count += mip_sample_count
    is_8bit = (frame_length - header_size) == total_sample_count

    pixel_data_start = frame_offset + header_size
    pixel_count = width * height

    try:
        if is_8bit:
            if palette is not None:
                pixels_rgba = _decode_paletted(entry_data, pixel_data_start, pixel_count, palette)
            else:
                pixels_rgba = _decode_monochrome(entry_data, pixel_data_start, pixel_count)
        elif not is_transparent:
            pixels_rgba = _decode_565(entry_data, pixel_data_start, pixel_count)
        else:
            pixels_rgba = _decode_5551(entry_data, pixel_data_start, pixel_count)
    except struct.error as e:
        raise U9TextureError(f"pixel data truncated: {e}") from e

    return U9TextureFrame(width=width, height=height, pixels_rgba=pixels_rgba, is_transparent=is_transparent)


def _decode_monochrome(data: bytes, start: int, count: int) -> bytes:
    out = bytearray(count * 4)
    for i in range(count):
        v = data[start + i]
        out[i * 4 : i * 4 + 4] = (v, v, v, 255)
    return bytes(out)


def _decode_paletted(data: bytes, start: int, count: int, palette: U9Palette) -> bytes:
    out = bytearray(count * 4)
    colors = palette.colors
    for i in range(count):
        r, g, b = colors[data[start + i]]
        out[i * 4 : i * 4 + 4] = (r, g, b, 255)
    return bytes(out)


def _decode_565(data: bytes, start: int, count: int) -> bytes:
    out = bytearray(count * 4)
    for i in range(count):
        raw = struct.unpack_from("<H", data, start + i * 2)[0]
        b = (raw & 0x1F) * 255 // 31
        g = ((raw >> 5) & 0x3F) * 255 // 63
        r = ((raw >> 11) & 0x1F) * 255 // 31
        out[i * 4 : i * 4 + 4] = (r, g, b, 255)
    return bytes(out)


def _decode_5551(data: bytes, start: int, count: int) -> bytes:
    out = bytearray(count * 4)
    for i in range(count):
        raw = struct.unpack_from("<H", data, start + i * 2)[0]
        b = (raw & 0x1F) * 255 // 31
        g = ((raw >> 5) & 0x1F) * 255 // 31
        r = ((raw >> 10) & 0x1F) * 255 // 31
        a = 255 if (raw >> 15) & 1 else 0
        out[i * 4 : i * 4 + 4] = (r, g, b, a)
    return bytes(out)
