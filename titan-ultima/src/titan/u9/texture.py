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
    0x06  compression    u16  -- 0 = raw pixel data, 1 = BC1/DXT1 block
                                compression; both are decoded here
    0x08  frame_count    u32
    0x0C  (unknown)      u32
    0x10  frame directory: frame_count * (offset: u32, length: u32)

Each frame directory entry points (relative to the entry start) at a
per-frame header::

    +0x00  flags      u16  -- bit 8 (0x100) is "is_transparent"; bit 9
                            (0x200) marks an 8-bit frame as a mask
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

Bits per pixel is not stored directly. It is inferred by comparing the frame's
recorded byte length against the byte length a full 8-bit (1 byte/pixel) mip
chain would occupy at this width/height/mip-count: if they match the frame is
one byte per texel, otherwise it is 16-bit (565 when the transparency flag is
clear, 5551 when set).

**One byte per texel is three different formats**, and the length test cannot
tell them apart:

===========  ====================================  ====================
``selector``  Format                                Shipped 8-bit frames
===========  ====================================  ====================
0            ``P_8`` -- indices into ankh.pal      12,254
2            ``ALPHA_INTENSITY_44`` -- 4+4 nibbles  42
3            ``ALPHA_8`` -- coverage mask           10,428
===========  ====================================  ====================

The engine chooses between them with a descriptor byte, and that byte is in the
shipped data: ``sdInfo`` field 0 byte 1, exposed as
:attr:`titan.u9.sdinfo.U9SdInfoRecord.format_selector`. Pass it to
:func:`decode_frame` as ``selector`` and frames decode the way the engine
decodes them. Without it, :data:`INTENSITY_FLAG` (frame-flags bit 9) stands in;
that agrees about mask-versus-paletted on all 22,724 shipped 8-bit frames but
cannot separate the two mask formats, so the 42 ``ALPHA_INTENSITY_44`` frames
decode as flat masks.

Applying a palette to a mask is not a subtle error -- sparkles, lightning and
the pentagram glow come out as rainbow confetti, because consecutive intensity
values land on unrelated hues.

**Compression**: ``compression=1`` is **BC1/DXT1**, confirmed on real data --
payload length matches a BC1 base surface plus its mip chain on 2,029 of 2,029
sampled frames, and decoded frames render as clean ground textures. It is
decoded here. Earlier revisions of this module rejected it as an unknown format
because the Blender importer this reader was ported from has no path for it;
that was a limitation of that tool, not of the format. ``u9ed`` decodes it with
``BCnEncoder.Net`` as BC1. Anything other than 0 or 1 is still rejected with
:class:`U9TextureError` rather than guessed at.

Note that the length test must never be used as a stand-in for the
``compression`` field: run against real ``compression=1`` data it produces a
plausible-looking buffer-length match on 195 of 5,687 entries purely by chance,
which would silently decode compressed bytes as raw pixels.

The three archives are one texture set at three quality tiers, index-parallel to
one another: ``bitmapsh.flx`` is 8-bit, ``bitmap16.flx`` 16-bit and
``bitmapC.flx`` BC1. Masks are shared verbatim across all three rather than
re-encoded, which is why ``bitmap16`` and ``bitmapC`` carry exactly the same
3,476 8-bit frames -- every one of them a mask. ``ankh.pal`` is therefore needed
by ``bitmapsh.flx`` alone.
"""

from __future__ import annotations

__all__ = [
    "COMPRESSION_BC1",
    "FORMAT_ALPHA_8",
    "FORMAT_ALPHA_INTENSITY_44",
    "FORMAT_P8",
    "INTENSITY_FLAG",
    "COMPRESSION_NONE",
    "U9TextureError",
    "U9TextureFrame",
    "bc1_size",
    "decode_frame",
]

import struct
from dataclasses import dataclass
from typing import Optional

from titan.u9.palette import U9Palette

TEXTURE_SET_HEADER_SIZE = 0x10
FRAME_DIR_ENTRY_SIZE = 0x08
FRAME_HEADER_SIZE = 0x14

COMPRESSION_NONE = 0
COMPRESSION_BC1 = 1

FORMAT_P8 = 0
"""``sdInfo`` selector: 8-bit palette indices."""
FORMAT_ALPHA_INTENSITY_44 = 2
"""``sdInfo`` selector: 4-bit alpha in the high nibble, 4-bit intensity in the low."""
FORMAT_ALPHA_8 = 3
"""``sdInfo`` selector: 8-bit coverage mask, colour supplied by the vertex."""

INTENSITY_FLAG = 0x200
"""Frame-flags bit 9: a fallback for when no ``sdInfo`` selector is available.

The engine's real discriminator is the descriptor byte exposed as
:attr:`titan.u9.sdinfo.U9SdInfoRecord.format_selector`; pass it to
:func:`decode_frame` as ``selector`` and this bit is not consulted.

Without it, bit 9 stands in. It agrees with the real selector on **22,724 of
22,724** shipped 8-bit frames as to whether a frame is a mask, but it cannot
tell :data:`FORMAT_ALPHA_8` from :data:`FORMAT_ALPHA_INTENSITY_44` -- both set
it. The 42 frames of the latter therefore decode as plain masks under the
fallback, losing their alpha nibble.

**Not to be confused with the material's own ``0x200``.** A
:class:`titan.u9.model.U9Material` carries two undecoded ``u16`` flag words of
its own, and the ``0x200`` bit there is understood to select point over
bilinear filtering -- a different field, in a different file, with a different
meaning. This constant is bit 9 of the **frame header** at ``frame_offset +
0x00``.
"""

BC1_BLOCK_BYTES = 8
BC1_BLOCK_DIM = 4


def bc1_size(width: int, height: int) -> int:
    """Bytes one BC1 surface occupies: 8 per 4x4 block, partial blocks rounded up."""
    blocks_x = max(1, (width + BC1_BLOCK_DIM - 1) // BC1_BLOCK_DIM)
    blocks_y = max(1, (height + BC1_BLOCK_DIM - 1) // BC1_BLOCK_DIM)
    return blocks_x * blocks_y * BC1_BLOCK_BYTES


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
    is_intensity: bool = False
    """True when this was an 8-bit ALPHA_8 mask -- see :data:`INTENSITY_FLAG`.

    ``pixels_rgba`` then holds the mask in the alpha channel, mirrored into RGB
    so it is visible in a plain viewer, and any palette passed to
    :func:`decode_frame` was deliberately ignored.
    """


def decode_frame(
    entry_data: bytes,
    frame_index: int = 0,
    palette: Optional[U9Palette] = None,
    *,
    selector: Optional[int] = None,
) -> U9TextureFrame:
    """
    Decode one frame from a texture archive's FLX entry bytes.

    ``palette`` (see :mod:`titan.u9.palette`, ``static/ankh.pal``) is
    only consulted for 8-bit **paletted** frames; 16-bit, BC1 and mask frames
    ignore it entirely. Without one, paletted frames fall back to flat
    grayscale.

    ``selector`` is the engine's pixel-format byte, from
    :attr:`titan.u9.sdinfo.U9SdInfoRecord.format_selector` on the ``sdInfo``
    archive matching this one. Supply it and one-byte-per-texel frames are
    decoded the way the engine decodes them; omit it and
    :data:`INTENSITY_FLAG` stands in, which cannot separate ``ALPHA_8`` from
    ``ALPHA_INTENSITY_44``.
    """
    if len(entry_data) < TEXTURE_SET_HEADER_SIZE:
        raise U9TextureError(f"data too small for a texture-set header: {len(entry_data)} bytes")

    _frame_width, mip_count, _frame_height, compression = struct.unpack_from("<4H", entry_data, 0x00)
    frame_count = struct.unpack_from("<I", entry_data, 0x08)[0]

    if compression not in (COMPRESSION_NONE, COMPRESSION_BC1):
        raise U9TextureError(
            f"unsupported compression scheme (compression={compression}); this decoder handles "
            f"raw/uncompressed pixel data (compression=0) and BC1/DXT1 block compression "
            f"(compression=1) -- see the module docstring"
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
    pixel_data_start = frame_offset + FRAME_HEADER_SIZE + 4 * height

    if compression == COMPRESSION_BC1:
        needed = bc1_size(width, height)
        if pixel_data_start + needed > len(entry_data):
            raise U9TextureError(
                f"BC1 data truncated: frame needs {needed} bytes at offset "
                f"{pixel_data_start}, entry is {len(entry_data)} bytes"
            )
        return U9TextureFrame(
            width=width,
            height=height,
            pixels_rgba=_decode_bc1(entry_data, pixel_data_start, width, height),
            is_transparent=is_transparent,
            is_intensity=False,
        )

    header_size = FRAME_HEADER_SIZE + 4 * height
    mip_sample_count = float(width * height)
    total_sample_count = mip_sample_count
    for _ in range(mip_count):
        mip_sample_count /= 4
        total_sample_count += mip_sample_count
    is_8bit = (frame_length - header_size) == total_sample_count
    # Only meaningful for 8-bit frames: the same bit on a 16-bit frame is not a
    # format selector, and reporting it as one would mislabel 12,439 of them.
    if not is_8bit:
        eight_bit_format = None
    elif selector is None:
        eight_bit_format = FORMAT_ALPHA_8 if (unknown1 & INTENSITY_FLAG) else FORMAT_P8
    elif selector in (FORMAT_ALPHA_8, FORMAT_ALPHA_INTENSITY_44):
        eight_bit_format = selector
    else:
        eight_bit_format = FORMAT_P8
    is_intensity = eight_bit_format in (FORMAT_ALPHA_8, FORMAT_ALPHA_INTENSITY_44)

    pixel_count = width * height

    # The 8-bit paths index bytes directly, so a short buffer would raise a bare
    # IndexError past this function's documented U9TextureError contract -- and
    # bitmapsh.flx is entirely 8-bit, so that is the common path, not a corner.
    bytes_needed = pixel_count * (1 if is_8bit else 2)
    if pixel_data_start + bytes_needed > len(entry_data):
        raise U9TextureError(
            f"pixel data truncated: frame needs {bytes_needed} bytes at offset "
            f"{pixel_data_start}, entry is {len(entry_data)} bytes"
        )

    try:
        if is_8bit:
            if eight_bit_format == FORMAT_ALPHA_INTENSITY_44:
                pixels_rgba = _decode_alpha_intensity_44(entry_data, pixel_data_start, pixel_count)
            elif eight_bit_format == FORMAT_ALPHA_8:
                pixels_rgba = _decode_intensity(entry_data, pixel_data_start, pixel_count)
            elif palette is not None:
                pixels_rgba = _decode_paletted(entry_data, pixel_data_start, pixel_count, palette)
            else:
                pixels_rgba = _decode_monochrome(entry_data, pixel_data_start, pixel_count)
        elif not is_transparent:
            pixels_rgba = _decode_565(entry_data, pixel_data_start, pixel_count)
        else:
            pixels_rgba = _decode_5551(entry_data, pixel_data_start, pixel_count)
    except (struct.error, IndexError) as e:
        raise U9TextureError(f"pixel data truncated: {e}") from e

    return U9TextureFrame(
        width=width,
        height=height,
        pixels_rgba=pixels_rgba,
        is_transparent=is_transparent,
        is_intensity=is_intensity,
    )


def _bc1_palette(c0: int, c1: int) -> tuple[list[tuple[int, int, int]], list[int]]:
    """The four colours a BC1 block interpolates, plus their alphas.

    ``c0 > c1`` selects the opaque four-colour mode; otherwise the block uses
    three colours and its fourth index is transparent black, which is how BC1
    carries one bit of alpha.
    """
    a = ((c0 >> 11) & 0x1F) * 255 // 31, ((c0 >> 5) & 0x3F) * 255 // 63, (c0 & 0x1F) * 255 // 31
    b = ((c1 >> 11) & 0x1F) * 255 // 31, ((c1 >> 5) & 0x3F) * 255 // 63, (c1 & 0x1F) * 255 // 31
    if c0 > c1:
        return (
            [a, b,
             tuple((2 * a[k] + b[k]) // 3 for k in range(3)),
             tuple((a[k] + 2 * b[k]) // 3 for k in range(3))],
            [255, 255, 255, 255],
        )
    return (
        [a, b, tuple((a[k] + b[k]) // 2 for k in range(3)), (0, 0, 0)],
        [255, 255, 255, 0],
    )


def _decode_bc1(data: bytes, start: int, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    pos = start
    for block_y in range(0, height, BC1_BLOCK_DIM):
        for block_x in range(0, width, BC1_BLOCK_DIM):
            c0, c1, bits = struct.unpack_from("<HHI", data, pos)
            pos += BC1_BLOCK_BYTES
            colors, alphas = _bc1_palette(c0, c1)
            for y in range(BC1_BLOCK_DIM):
                py = block_y + y
                if py >= height:
                    break
                for x in range(BC1_BLOCK_DIM):
                    px = block_x + x
                    if px >= width:
                        continue
                    index = (bits >> (2 * (BC1_BLOCK_DIM * y + x))) & 3
                    at = (py * width + px) * 4
                    out[at : at + 4] = bytes(colors[index]) + bytes([alphas[index]])
    return bytes(out)


def _decode_alpha_intensity_44(data: bytes, start: int, count: int) -> bytes:
    """ALPHA_INTENSITY_44: alpha in the high nibble, intensity in the low.

    Nibble order was settled by rendering the two planes of the three shipped
    entries separately: the high nibble is a hard-edged coverage blob and the
    low nibble is soft luminance detail, which is the way round D3D's A4L4 has
    it. Each nibble is scaled by 17 so 0x0F maps to 255.
    """
    out = bytearray(count * 4)
    for i in range(count):
        v = data[start + i]
        intensity = (v & 0x0F) * 17
        out[i * 4 : i * 4 + 4] = (intensity, intensity, intensity, ((v >> 4) & 0x0F) * 17)
    return bytes(out)


def _decode_intensity(data: bytes, start: int, count: int) -> bytes:
    """An ALPHA_8 mask: coverage in the alpha channel, mirrored into RGB.

    The colour is supplied by the vertex at render time, so **alpha is the
    authoritative channel** -- it is the only thing the file actually states.
    RGB repeats the same value purely so the mask is visible as greyscale in an
    ordinary image viewer; white-on-transparent is equally correct and renders
    as a blank rectangle, which makes an exported sheet impossible to inspect.
    A consumer compositing these should use the alpha and take colour from
    elsewhere, not treat the RGB as art.
    """
    out = bytearray(count * 4)
    for i in range(count):
        v = data[start + i]
        out[i * 4 : i * 4 + 4] = (v, v, v, v)
    return bytes(out)


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
