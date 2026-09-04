"""
Texture encoder for Ultima 9: Ascension -- the inverse of :mod:`titan.u9.texture`.

Replaces the pixels of one frame in a ``bitmap*.flx`` entry with new image
data, so a PNG can be dropped into a texture slot. The counterpart to
:mod:`titan.u9.flx_writer`, which packs the resulting entries back into an
archive.

**Same size, same encoding.** :func:`replace_frame` requires the incoming image
to match the frame it replaces, and re-encodes it the way that frame was
already encoded. That is a deliberate restriction, and it buys a strong
guarantee: the replacement payload is byte-for-byte the same *length* as the
original, so every offset in the entry stays valid and nothing outside the
pixel data is touched.

In particular these are carried through verbatim rather than regenerated:

* the frame's flags word, and the two undecoded ``u32`` fields at ``0x0C`` and
  ``0x10`` of the frame header;
* the undecoded ``u32`` at ``0x0C`` of the texture-set header;
* the row offset table;
* every other frame in the entry.

None of those four unknown fields has a known derivation, so authoring an entry
from scratch would mean guessing them. Editing in place never has to.

Encodings, chosen from what the original frame used:

===============  =========================================================
``compression``  Pixel format
===============  =========================================================
1                BC1 / DXT1 block compression
0, 8-bit         palette indices into ``static/ankh.pal``
0, 16-bit        RGB565 (opaque) or RGBA5551 (transparency flag set)
===============  =========================================================

Mip levels are **regenerated**, not preserved: a replaced base image makes the
old chain wrong. They are built by 2x2 box filtering in RGBA and re-encoding
each level, which renders correctly but does not reproduce the bytes the game
shipped -- neither box averaging (30.8% of texels) nor nearest (12.6%) matches
the original chain, so the filter Origin used is unknown. This does not affect
validity, only whether a rebuilt file is byte-identical to the shipped one.

Example::

    from titan.u9.flx_archive import U9FlxArchive
    from titan.u9.texture_writer import replace_frame

    archive = U9FlxArchive.from_file("static/bitmapC.flx")
    entry = replace_frame(archive.read_entry(2377), 0, rgba, 128, 128)
"""

from __future__ import annotations

__all__ = [
    "U9TextureWriteError",
    "encode_bc1",
    "encode_paletted",
    "encode_rgb565",
    "encode_rgba5551",
    "frame_encoding",
    "replace_frame",
]

import struct
from typing import Optional

from titan.u9.palette import U9Palette
from titan.u9.texture import (
    BC1_BLOCK_DIM,
    COMPRESSION_BC1,
    COMPRESSION_NONE,
    FRAME_DIR_ENTRY_SIZE,
    FRAME_HEADER_SIZE,
    TEXTURE_SET_HEADER_SIZE,
    bc1_size,
)

ENCODING_BC1 = "bc1"
ENCODING_PALETTED = "paletted"
ENCODING_RGB565 = "rgb565"
ENCODING_RGBA5551 = "rgba5551"

ALPHA_CUTOFF = 128
"""BC1 and RGBA5551 carry one alpha bit; this is where it flips."""


class U9TextureWriteError(Exception):
    """Raised when image data cannot be encoded into a texture frame."""


# ---------------------------------------------------------------- encoders


def encode_rgb565(rgba: bytes) -> bytes:
    out = bytearray(len(rgba) // 2)
    for i in range(len(rgba) // 4):
        r, g, b = rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]
        struct.pack_into(
            "<H", out, i * 2, ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        )
    return bytes(out)


def encode_rgba5551(rgba: bytes) -> bytes:
    out = bytearray(len(rgba) // 2)
    for i in range(len(rgba) // 4):
        r, g, b, a = rgba[i * 4 : i * 4 + 4]
        value = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        if a >= ALPHA_CUTOFF:
            value |= 0x8000
        struct.pack_into("<H", out, i * 2, value)
    return bytes(out)


def encode_paletted(rgba: bytes, palette: U9Palette) -> bytes:
    """Nearest palette entry per pixel, by squared RGB distance."""
    colors = palette.colors
    cache: dict[tuple[int, int, int], int] = {}
    out = bytearray(len(rgba) // 4)
    for i in range(len(out)):
        key = (rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2])
        index = cache.get(key)
        if index is None:
            r, g, b = key
            best = 0
            best_distance = 1 << 30
            for candidate, (cr, cg, cb) in enumerate(colors):
                distance = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
                if distance < best_distance:
                    best_distance, best = distance, candidate
                    if distance == 0:
                        break
            cache[key] = index = best
        out[i] = index
    return bytes(out)


def _to565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _from565(value: int) -> tuple[int, int, int]:
    return (
        ((value >> 11) & 0x1F) * 255 // 31,
        ((value >> 5) & 0x3F) * 255 // 63,
        (value & 0x1F) * 255 // 31,
    )


def _encode_bc1_block(pixels: list[tuple[int, int, int, int]]) -> bytes:
    """One 4x4 block: bounding-box endpoints, nearest-endpoint indices.

    A block holding any pixel below :data:`ALPHA_CUTOFF` switches to BC1's
    three-colour mode, where index 3 is transparent -- that is the only alpha
    the format has.
    """
    has_alpha = any(p[3] < ALPHA_CUTOFF for p in pixels)
    opaque = [p for p in pixels if p[3] >= ALPHA_CUTOFF]
    if not opaque:
        return struct.pack("<HHI", 0, 0, 0xFFFFFFFF)

    low = [min(p[k] for p in opaque) for k in range(3)]
    high = [max(p[k] for p in opaque) for k in range(3)]
    c0, c1 = _to565(*high), _to565(*low)

    if has_alpha:
        # three-colour mode needs c0 <= c1
        if c0 > c1:
            c0, c1 = c1, c0
        if c0 == c1 and c0 > 0:
            c0 -= 1
        palette = [_from565(c0), _from565(c1)]
        palette.append(tuple((palette[0][k] + palette[1][k]) // 2 for k in range(3)))
    else:
        # four-colour mode needs c0 > c1; a flat block encodes both endpoints
        # equal, so nudge one apart rather than fall into three-colour mode.
        if c0 < c1:
            c0, c1 = c1, c0
        if c0 == c1:
            if c0 > 0:
                c1 = c0 - 1
            else:
                c0 = 1
        palette = [_from565(c0), _from565(c1)]
        palette.append(tuple((2 * palette[0][k] + palette[1][k]) // 3 for k in range(3)))
        palette.append(tuple((palette[0][k] + 2 * palette[1][k]) // 3 for k in range(3)))

    bits = 0
    for n, (r, g, b, a) in enumerate(pixels):
        if has_alpha and a < ALPHA_CUTOFF:
            index = 3
        else:
            index = 0
            best = 1 << 30
            for k, (pr, pg, pb) in enumerate(palette):
                distance = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if distance < best:
                    best, index = distance, k
        bits |= index << (2 * n)
    return struct.pack("<HHI", c0, c1, bits)


def encode_bc1(rgba: bytes, width: int, height: int) -> bytes:
    out = bytearray()
    for block_y in range(0, height, BC1_BLOCK_DIM):
        for block_x in range(0, width, BC1_BLOCK_DIM):
            block = []
            for y in range(BC1_BLOCK_DIM):
                py = min(block_y + y, height - 1)
                for x in range(BC1_BLOCK_DIM):
                    px = min(block_x + x, width - 1)
                    at = (py * width + px) * 4
                    block.append(tuple(rgba[at : at + 4]))
            out += _encode_bc1_block(block)
    return bytes(out)


# ------------------------------------------------------------ mip building


def _downsample(rgba: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """One 2x2 box-filtered mip level."""
    new_width, new_height = max(1, width // 2), max(1, height // 2)
    out = bytearray(new_width * new_height * 4)
    for y in range(new_height):
        for x in range(new_width):
            totals = [0, 0, 0, 0]
            samples = 0
            for dy in range(2):
                sy = min(y * 2 + dy, height - 1)
                for dx in range(2):
                    sx = min(x * 2 + dx, width - 1)
                    at = (sy * width + sx) * 4
                    for k in range(4):
                        totals[k] += rgba[at + k]
                    samples += 1
            at = (y * new_width + x) * 4
            out[at : at + 4] = bytes(t // samples for t in totals)
    return bytes(out), new_width, new_height


# ------------------------------------------------------------- frame edits


def frame_encoding(entry_data: bytes, frame_index: int = 0) -> str:
    """Which pixel format a frame in ``entry_data`` uses."""
    _, mip_count, _, compression = struct.unpack_from("<4H", entry_data, 0x00)
    if compression == COMPRESSION_BC1:
        return ENCODING_BC1
    if compression != COMPRESSION_NONE:
        raise U9TextureWriteError(f"unsupported compression scheme {compression}")

    dir_pos = TEXTURE_SET_HEADER_SIZE + frame_index * FRAME_DIR_ENTRY_SIZE
    frame_offset, frame_length = struct.unpack_from("<2I", entry_data, dir_pos)
    flags = struct.unpack_from("<H", entry_data, frame_offset)[0]
    width, height = struct.unpack_from("<2I", entry_data, frame_offset + 4)

    header_size = FRAME_HEADER_SIZE + 4 * height
    samples = float(width * height)
    total = samples
    for _ in range(mip_count):
        samples /= 4
        total += samples
    if (frame_length - header_size) == total:
        return ENCODING_PALETTED
    return ENCODING_RGBA5551 if (flags >> 8) & 1 else ENCODING_RGB565


def _encode_level(
    rgba: bytes, width: int, height: int, encoding: str, palette: Optional[U9Palette]
) -> bytes:
    if encoding == ENCODING_BC1:
        return encode_bc1(rgba, width, height)
    if encoding == ENCODING_RGB565:
        return encode_rgb565(rgba)
    if encoding == ENCODING_RGBA5551:
        return encode_rgba5551(rgba)
    if palette is None:
        raise U9TextureWriteError(
            "this frame is 8-bit paletted; a palette (static/ankh.pal) is required "
            "to encode into it"
        )
    return encode_paletted(rgba, palette)


def replace_frame(
    entry_data: bytes,
    frame_index: int,
    rgba: bytes,
    width: int,
    height: int,
    *,
    palette: Optional[U9Palette] = None,
) -> bytes:
    """Return ``entry_data`` with one frame's pixels replaced.

    ``rgba`` is ``width * height * 4`` bytes. The image must match the frame's
    own dimensions: the replacement is spliced in place, so its encoded length
    has to equal the original's exactly.
    """
    if len(entry_data) < TEXTURE_SET_HEADER_SIZE:
        raise U9TextureWriteError(
            f"data too small for a texture-set header: {len(entry_data)} bytes"
        )
    _, mip_count, _, _compression = struct.unpack_from("<4H", entry_data, 0x00)
    frame_count = struct.unpack_from("<I", entry_data, 0x08)[0]
    if not (0 <= frame_index < frame_count):
        raise U9TextureWriteError(
            f"frame_index {frame_index} out of range (0..{frame_count - 1})"
        )

    dir_pos = TEXTURE_SET_HEADER_SIZE + frame_index * FRAME_DIR_ENTRY_SIZE
    frame_offset, frame_length = struct.unpack_from("<2I", entry_data, dir_pos)
    frame_width, frame_height = struct.unpack_from("<2I", entry_data, frame_offset + 4)

    if (width, height) != (frame_width, frame_height):
        raise U9TextureWriteError(
            f"image is {width}x{height}, frame {frame_index} is "
            f"{frame_width}x{frame_height} -- replacement must match exactly"
        )
    if len(rgba) != width * height * 4:
        raise U9TextureWriteError(
            f"expected {width * height * 4} bytes of RGBA, got {len(rgba)}"
        )

    encoding = frame_encoding(entry_data, frame_index)
    header_size = FRAME_HEADER_SIZE + 4 * height
    payload_size = frame_length - header_size
    if payload_size <= 0:
        raise U9TextureWriteError(f"frame {frame_index} declares no pixel data")

    payload = bytearray(_encode_level(rgba, width, height, encoding, palette))
    level, level_width, level_height = rgba, width, height
    for _ in range(mip_count):
        level, level_width, level_height = _downsample(level, level_width, level_height)
        payload += _encode_level(level, level_width, level_height, encoding, palette)

    if len(payload) != payload_size:
        raise U9TextureWriteError(
            f"encoded {len(payload)} bytes for frame {frame_index}, which declares "
            f"{payload_size} -- refusing to write a frame that would shift every "
            f"offset after it"
        )

    start = frame_offset + header_size
    out = bytearray(entry_data)
    out[start : start + payload_size] = payload
    return bytes(out)


def bc1_payload_size(width: int, height: int, mip_count: int) -> int:
    """Total BC1 bytes for a surface plus ``mip_count`` levels."""
    total = bc1_size(width, height)
    for _ in range(mip_count):
        width, height = max(1, width // 2), max(1, height // 2)
        total += bc1_size(width, height)
    return total
