"""Read Ultima IX texture-set entries from the three ``bitmap*.flx`` tiers.

All offsets below are relative to one FLX entry.  The fixed 16-byte set header
stores maximum dimensions, an additional-mip count, one reserved byte, storage
flags, the frame count, and packed playback fields.  A directory of
``(offset, length)`` pairs follows it.

Each frame begins with five little-endian ``u32`` values: full flags, width,
height, horizontal anchor, and vertical anchor.  A ``height * u32`` row table
then precedes the base pixels and mip chain.  Titan retains both headers and the
row table verbatim; compressed entries and 30 shipped raw frames contain
non-authoritative row values, so sequential decoding does not depend on them.

Frame flags explicitly store a two-bit pixel-format code and a one/two-byte
depth bit.  Payload length validates those fields; it does not choose them.
The matching ``sdInfo*.flx`` record repeats the format code and may be supplied
as ``selector`` to survive two known damaged frame headers.  Raw formats are
P8/RGB565 (code 0), ARGB1555 (code 1 at two-byte depth), AI44/AI88 (code 2),
and ALPHA8 (code 3 at one-byte depth).  Set storage bit 0 selects BC1.

For keyed P8 and RGB565 data, frame bit 30 disables the stored transparency
test; otherwise palette index 254 or the stored 16-bit key decodes with zero
alpha.  Intrinsic alpha formats retain their alpha channel independently.

The three archives are index-parallel quality tiers.  The same structure is
also used by the pre-baked terrain-panel archives.
"""

from __future__ import annotations

__all__ = [
    "COMPRESSION_BC1",
    "FORMAT_ALPHA_8",
    "FORMAT_ALPHA_INTENSITY_44",
    "FORMAT_P8",
    "SELECTOR_ARGB_1555",
    "INTENSITY_FLAG",
    "FRAME_TWO_BYTES_PER_PIXEL",
    "PALETTE_TRANSPARENCY_INDEX",
    "COMPRESSION_NONE",
    "U9TextureError",
    "U9TextureFrame",
    "U9TextureFrameInfo",
    "U9TextureSet",
    "bc1_size",
    "decode_frame",
    "mip_dimensions",
    "parse_texture_set",
]

import struct
from dataclasses import dataclass
from typing import Optional

from titan.u9.palette import PALETTE_TRANSPARENCY_INDEX, U9Palette

TEXTURE_SET_HEADER_SIZE = 0x10
FRAME_DIR_ENTRY_SIZE = 0x08
FRAME_HEADER_SIZE = 0x14

COMPRESSION_NONE = 0
COMPRESSION_BC1 = 1
TEXTURE_OPTION_COMPRESSED = 0x0001

FORMAT_P8 = 0
"""``sdInfo`` selector: 8-bit palette indices."""
FORMAT_ALPHA_INTENSITY_44 = 2
"""``sdInfo`` selector: 4-bit alpha in the high nibble, 4-bit intensity in the low."""
FORMAT_ALPHA_8 = 3
"""``sdInfo`` selector: 8-bit coverage mask, colour supplied by the vertex."""

SELECTOR_ARGB_1555 = 1
"""Pixel-format code 1 on a two-byte frame: ARGB1555.

The selector's meaning depends on the depth branch: 0 is ``P_8`` on a
one-byte-per-texel frame and ``RGB_565`` on a two-byte one. Only value 1 means
1555, and it occurs on no 8-bit frame.

The matching ``sdInfo`` selector agrees with this stored code on all but frame
1 of ``bitmap16`` entries 1623 and 6146.  Passing that per-entry selector lets
Titan decode those two damaged frame headers consistently with their siblings.
"""

INTENSITY_FLAG = 0x200
"""Compatibility name for bit 1 of the stored two-bit pixel-format code.

The complete code occupies frame-flag bits 8-9; ``0x200`` by itself is code 2,
AI44 at one-byte depth or AI88 at two-byte depth.  New code should use
:attr:`U9TextureFrameInfo.pixel_format_code` rather than testing this bit.

**Not to be confused with the material's own ``0x200``**, which selects point
over bilinear filtering. The engine's runtime material flag word collides with
two separate archive fields by bit number and matches neither in meaning --
``0x200`` here, and ``0x20`` against ``sdInfo``'s ``fields[0]``. Bit numbers in
the engine's structures say nothing about bit numbers in these files; see
``reference/u9/sdinfo/u9_sdinfo_reference.md``, "Bit numbers here mean nothing
to the engine". This constant is bit 9 of the **frame header** at
``frame_offset + 0x00``.
"""

FRAME_PIXEL_FORMAT_MASK = 0x00000300
FRAME_PIXEL_FORMAT_SHIFT = 8
FRAME_TWO_BYTES_PER_PIXEL = 0x00000400
FRAME_EDITOR_ONLY = 0x00000800
FRAME_TRANSPARENCY_KEY_MASK = 0x0FFFF000
FRAME_TRANSPARENCY_KEY_SHIFT = 12
FRAME_RUN_LENGTH_ENCODED = 0x10000000
FRAME_CONTIGUOUS_ROWS = 0x20000000
FRAME_TRANSPARENCY_TEST_DISABLED = 0x40000000
FRAME_RESERVED_FLAG = 0x80000000

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
class U9TextureFrameInfo:
    """Structural metadata for one frame, without decoding its pixels."""

    index: int
    offset: int
    length: int
    flags: int
    width: int
    height: int
    anchor_x: int
    anchor_y: int
    row_offsets: tuple[int, ...]
    header_raw: bytes
    row_offsets_raw: bytes

    @property
    def header_size(self) -> int:
        """Frame header plus the per-row offset table, in bytes."""
        return FRAME_HEADER_SIZE + 4 * self.height

    @property
    def pixel_data_offset(self) -> int:
        """Absolute offset of the base image within the FLX entry bytes."""
        return self.offset + self.header_size

    @property
    def is_transparent(self) -> bool:
        """Compatibility view: whether per-pixel transparency testing is enabled."""
        return self.transparency_test_enabled

    @property
    def pixel_format_code(self) -> int:
        """Stored two-bit pixel-format code; its meaning depends on pixel depth."""
        return (self.flags & FRAME_PIXEL_FORMAT_MASK) >> FRAME_PIXEL_FORMAT_SHIFT

    @property
    def two_bytes_per_pixel(self) -> bool:
        return bool(self.flags & FRAME_TWO_BYTES_PER_PIXEL)

    @property
    def editor_only(self) -> bool:
        return bool(self.flags & FRAME_EDITOR_ONLY)

    @property
    def transparency_key_16(self) -> int:
        return (
            self.flags & FRAME_TRANSPARENCY_KEY_MASK
        ) >> FRAME_TRANSPARENCY_KEY_SHIFT

    @property
    def is_run_length_encoded(self) -> bool:
        return bool(self.flags & FRAME_RUN_LENGTH_ENCODED)

    @property
    def has_contiguous_rows(self) -> bool:
        return bool(self.flags & FRAME_CONTIGUOUS_ROWS)

    @property
    def transparency_test_enabled(self) -> bool:
        return not bool(self.flags & FRAME_TRANSPARENCY_TEST_DISABLED)

    @property
    def reserved_flag_31(self) -> bool:
        return bool(self.flags & FRAME_RESERVED_FLAG)

    @property
    def single_color_index(self) -> int:
        return self.flags & 0xFF

    @property
    def unknown_word(self) -> int:
        """Compatibility alias for the former, incorrect split-flags view."""
        return (self.flags >> 16) & 0xFFFF

    @property
    def unknown3(self) -> int:
        """Compatibility alias for :attr:`anchor_x`."""
        return self.anchor_x

    @property
    def unknown4(self) -> int:
        """Compatibility alias for :attr:`anchor_y`."""
        return self.anchor_y


@dataclass(frozen=True)
class U9TextureSet:
    """Parsed texture-set and frame metadata from one FLX entry."""

    max_width: int
    mip_count: int
    reserved_0x03: int
    max_height: int
    storage_flags: int
    frame_count: int
    playback_flags: int
    frames: tuple[U9TextureFrameInfo, ...]
    header_raw: bytes

    @property
    def is_compressed(self) -> bool:
        return bool(self.storage_flags & TEXTURE_OPTION_COMPRESSED)

    @property
    def animation_mode_code(self) -> int:
        return self.playback_flags & 0x7

    @property
    def playback_reverse(self) -> bool:
        return bool(self.playback_flags & 0x8)

    @property
    def playback_rate(self) -> int:
        return (self.playback_flags >> 4) & 0xFF

    @property
    def width_exponent(self) -> int:
        return (self.playback_flags >> 12) & 0xF

    @property
    def height_exponent(self) -> int:
        return (self.playback_flags >> 16) & 0xF

    @property
    def default_first_frame(self) -> int:
        return (self.playback_flags >> 20) & 0xF

    @property
    def default_last_frame(self) -> int:
        return (self.playback_flags >> 24) & 0xFF

    @property
    def playback_status(self) -> str:
        if self.frame_count == 0:
            return "not_applicable"
        if (
            self.default_first_frame >= self.frame_count
            or self.default_last_frame >= self.frame_count
            or self.default_first_frame > self.default_last_frame
        ):
            return "out_of_range"
        return "ok"

    @property
    def dimension_exponent_status(self) -> str:
        if self.max_width == 0 or self.max_height == 0:
            return "not_applicable"
        expected_width = self.max_width.bit_length() - 1
        expected_height = self.max_height.bit_length() - 1
        if (
            self.width_exponent != expected_width
            or self.height_exponent != expected_height
        ):
            return "mismatch"
        return "ok"

    @property
    def frame_width(self) -> int:
        """Compatibility alias for :attr:`max_width`."""
        return self.max_width

    @property
    def frame_height(self) -> int:
        """Compatibility alias for :attr:`max_height`."""
        return self.max_height

    @property
    def compression(self) -> int:
        """Compatibility view of storage bit 0 (0 raw, 1 BC1)."""
        return int(self.is_compressed)

    @property
    def unknown(self) -> int:
        """Compatibility alias for the now-decoded playback flags."""
        return self.playback_flags


@dataclass(frozen=True)
class U9TextureFrame:
    """One decoded texture surface: RGBA pixels, row-major, top-to-bottom."""

    width: int
    height: int
    pixels_rgba: bytes
    """``width * height * 4`` bytes, one byte per channel, 0-255."""
    is_transparent: bool
    """True when the decoded surface contains at least one alpha value below 255."""
    is_intensity: bool = False
    """True when this was an alpha/intensity or alpha-only format.

    ``pixels_rgba`` then holds the mask in the alpha channel, mirrored into RGB
    so it is visible in a plain viewer, and any palette passed to
    :func:`decode_frame` was deliberately ignored.
    """
    mip_level: int = 0
    """Zero for the base image; positive values identify stored mip levels."""


def parse_texture_set(entry_data: bytes) -> U9TextureSet:
    """Parse one texture FLX entry's headers, directory, and row tables.

    This structure is shared by ``bitmap*.flx`` and the extensionless-FLX
    terrain-panel archives ``Texture8.*``/``texture16.*``.
    """
    if len(entry_data) < TEXTURE_SET_HEADER_SIZE:
        raise U9TextureError(
            f"data too small for a texture-set header: {len(entry_data)} bytes"
        )

    (
        max_width,
        mip_count,
        reserved_0x03,
        max_height,
        storage_flags,
        frame_count,
        playback_flags,
    ) = struct.unpack_from("<HBBHHII", entry_data, 0x00)
    directory_end = TEXTURE_SET_HEADER_SIZE + frame_count * FRAME_DIR_ENTRY_SIZE
    if directory_end > len(entry_data):
        raise U9TextureError(
            f"truncated frame directory: {frame_count} entries need {directory_end} "
            f"bytes, data is {len(entry_data)} bytes"
        )

    frames = []
    for index in range(frame_count):
        dir_pos = TEXTURE_SET_HEADER_SIZE + index * FRAME_DIR_ENTRY_SIZE
        frame_offset, frame_length = struct.unpack_from("<2I", entry_data, dir_pos)
        frame_end = frame_offset + frame_length
        if frame_offset < directory_end or frame_end > len(entry_data):
            raise U9TextureError(
                f"frame {index} range {frame_offset}..{frame_end} lies outside "
                f"its header/directory or {len(entry_data)}-byte entry"
            )
        if frame_length < FRAME_HEADER_SIZE:
            raise U9TextureError(
                f"frame {index} is only {frame_length} bytes; need at least "
                f"{FRAME_HEADER_SIZE} for its header"
            )

        try:
            flags, width, height, anchor_x, anchor_y = struct.unpack_from(
                "<5I", entry_data, frame_offset
            )
        except struct.error as error:
            raise U9TextureError(f"malformed frame {index} header: {error}") from error
        if width == 0 or height == 0:
            raise U9TextureError(
                f"frame {index} has invalid dimensions {width}x{height}"
            )

        header_size = FRAME_HEADER_SIZE + 4 * height
        if header_size > frame_length:
            raise U9TextureError(
                f"frame {index} row table needs {header_size} bytes, frame is "
                f"{frame_length} bytes"
            )
        try:
            row_offsets = struct.unpack_from(
                f"<{height}I", entry_data, frame_offset + FRAME_HEADER_SIZE
            )
        except struct.error as error:
            raise U9TextureError(
                f"malformed frame {index} row table: {error}"
            ) from error

        frames.append(
            U9TextureFrameInfo(
                index=index,
                offset=frame_offset,
                length=frame_length,
                flags=flags,
                width=width,
                height=height,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                row_offsets=row_offsets,
                header_raw=entry_data[frame_offset : frame_offset + FRAME_HEADER_SIZE],
                row_offsets_raw=entry_data[
                    frame_offset + FRAME_HEADER_SIZE : frame_offset + header_size
                ],
            )
        )

    return U9TextureSet(
        max_width=max_width,
        mip_count=mip_count,
        reserved_0x03=reserved_0x03,
        max_height=max_height,
        storage_flags=storage_flags,
        frame_count=frame_count,
        playback_flags=playback_flags,
        frames=tuple(frames),
        header_raw=entry_data[:TEXTURE_SET_HEADER_SIZE],
    )


def mip_dimensions(
    width: int, height: int, mip_count: int
) -> tuple[tuple[int, int], ...]:
    """Return base dimensions followed by every declared stored mip level."""
    if width <= 0 or height <= 0:
        raise U9TextureError(f"invalid texture dimensions {width}x{height}")
    dimensions = [(width, height)]
    for _ in range(mip_count):
        width = max(1, width // 2)
        height = max(1, height // 2)
        dimensions.append((width, height))
    return tuple(dimensions)


def decode_frame(
    entry_data: bytes,
    frame_index: int = 0,
    palette: Optional[U9Palette] = None,
    *,
    selector: Optional[int] = None,
    mip_level: int = 0,
) -> U9TextureFrame:
    """
    Decode one frame from a texture archive's FLX entry bytes.

    ``palette`` (see :mod:`titan.u9.palette`, ``static/ankh.pal``) is
    only consulted for 8-bit **paletted** frames; 16-bit, BC1 and mask frames
    ignore it entirely. Without one, paletted frames fall back to flat
    grayscale.

    ``mip_level`` selects the base image (zero) or one of the stored,
    progressively halved surfaces. ``selector`` is the companion pixel-format byte, from
    :attr:`titan.u9.sdinfo.U9SdInfoRecord.format_selector` on the ``sdInfo``
    archive matching this one. Supply it to override a damaged per-frame
    format code; otherwise the identical two-bit code stored in the frame
    flags is used.
    """
    texture_set = parse_texture_set(entry_data)
    mip_count = texture_set.mip_count
    compression = texture_set.compression
    frame_count = texture_set.frame_count

    if texture_set.storage_flags & ~TEXTURE_OPTION_COMPRESSED:
        raise U9TextureError(
            f"unsupported texture storage flags 0x{texture_set.storage_flags:04x}; "
            "only bit 0 (BC1 compression) is defined"
        )

    if not (0 <= frame_index < frame_count):
        raise U9TextureError(
            f"frame_index {frame_index} out of range (0..{frame_count - 1})"
        )
    if not (0 <= mip_level <= mip_count):
        raise U9TextureError(f"mip_level {mip_level} out of range (0..{mip_count})")

    frame_info = texture_set.frames[frame_index]
    width = frame_info.width
    height = frame_info.height
    frame_length = frame_info.length
    pixel_data_start = frame_info.pixel_data_offset
    dimensions = mip_dimensions(width, height, mip_count)

    if compression == COMPRESSION_BC1:
        level_sizes = tuple(
            bc1_size(level_width, level_height)
            for level_width, level_height in dimensions
        )
        payload_length = frame_length - frame_info.header_size
        expected_length = sum(level_sizes)
        if payload_length != expected_length:
            raise U9TextureError(
                f"BC1 payload size mismatch: frame has {payload_length} bytes, "
                f"declared levels need {expected_length}"
            )
        pixel_data_start += sum(level_sizes[:mip_level])
        width, height = dimensions[mip_level]
        pixels_rgba = _decode_bc1(entry_data, pixel_data_start, width, height)
        return U9TextureFrame(
            width=width,
            height=height,
            pixels_rgba=pixels_rgba,
            is_transparent=_has_transparent_pixels(pixels_rgba),
            is_intensity=False,
            mip_level=mip_level,
        )

    level_sample_counts = tuple(
        level_width * level_height for level_width, level_height in dimensions
    )
    total_sample_count = sum(level_sample_counts)
    payload_length = frame_length - frame_info.header_size
    bytes_per_pixel = 2 if frame_info.two_bytes_per_pixel else 1
    expected_payload_length = total_sample_count * bytes_per_pixel
    if payload_length != expected_payload_length:
        raise U9TextureError(
            f"raw payload size mismatch: frame has {payload_length} bytes, expected "
            f"{expected_payload_length} from the stored "
            f"{'two-byte' if bytes_per_pixel == 2 else 'one-byte'} depth flag"
        )
    is_8bit = bytes_per_pixel == 1
    pixel_format = frame_info.pixel_format_code if selector is None else selector
    is_intensity = pixel_format in (FORMAT_ALPHA_8, FORMAT_ALPHA_INTENSITY_44)

    pixel_data_start += sum(level_sample_counts[:mip_level]) * bytes_per_pixel
    width, height = dimensions[mip_level]
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
            if pixel_format == FORMAT_ALPHA_INTENSITY_44:
                pixels_rgba = _decode_alpha_intensity_44(
                    entry_data, pixel_data_start, pixel_count
                )
            elif pixel_format == FORMAT_ALPHA_8:
                pixels_rgba = _decode_intensity(
                    entry_data, pixel_data_start, pixel_count
                )
            elif pixel_format != FORMAT_P8:
                raise U9TextureError(
                    f"unsupported one-byte pixel format code {pixel_format}"
                )
            elif palette is not None:
                pixels_rgba = _decode_paletted(
                    entry_data,
                    pixel_data_start,
                    pixel_count,
                    palette,
                    frame_info.transparency_test_enabled,
                )
            else:
                pixels_rgba = _decode_monochrome(
                    entry_data,
                    pixel_data_start,
                    pixel_count,
                    frame_info.transparency_test_enabled,
                )
        elif pixel_format == SELECTOR_ARGB_1555:
            pixels_rgba = _decode_5551(entry_data, pixel_data_start, pixel_count)
        elif pixel_format == FORMAT_ALPHA_INTENSITY_44:
            pixels_rgba = _decode_alpha_intensity_88(
                entry_data, pixel_data_start, pixel_count
            )
        elif pixel_format == FORMAT_P8:
            pixels_rgba = _decode_565(
                entry_data,
                pixel_data_start,
                pixel_count,
                frame_info.transparency_key_16,
                frame_info.transparency_test_enabled,
            )
        else:
            raise U9TextureError(
                f"unsupported two-byte pixel format code {pixel_format}"
            )
    except (struct.error, IndexError) as e:
        raise U9TextureError(f"pixel data truncated: {e}") from e

    return U9TextureFrame(
        width=width,
        height=height,
        pixels_rgba=pixels_rgba,
        is_transparent=_has_transparent_pixels(pixels_rgba),
        is_intensity=is_intensity,
        mip_level=mip_level,
    )


def _bc1_palette(c0: int, c1: int) -> tuple[list[tuple[int, int, int]], list[int]]:
    """The four colours a BC1 block interpolates, plus their alphas.

    ``c0 > c1`` selects the opaque four-colour mode; otherwise the block uses
    three colours and its fourth index is transparent black, which is how BC1
    carries one bit of alpha.
    """
    a = (
        ((c0 >> 11) & 0x1F) * 255 // 31,
        ((c0 >> 5) & 0x3F) * 255 // 63,
        (c0 & 0x1F) * 255 // 31,
    )
    b = (
        ((c1 >> 11) & 0x1F) * 255 // 31,
        ((c1 >> 5) & 0x3F) * 255 // 63,
        (c1 & 0x1F) * 255 // 31,
    )
    if c0 > c1:
        return (
            [
                a,
                b,
                _mix_rgb(a, b, 2, 1, 3),
                _mix_rgb(a, b, 1, 2, 3),
            ],
            [255, 255, 255, 255],
        )
    return (
        [a, b, _mix_rgb(a, b, 1, 1, 2), (0, 0, 0)],
        [255, 255, 255, 0],
    )


def _mix_rgb(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    first_weight: int,
    second_weight: int,
    divisor: int,
) -> tuple[int, int, int]:
    return (
        (first_weight * first[0] + second_weight * second[0]) // divisor,
        (first_weight * first[1] + second_weight * second[1]) // divisor,
        (first_weight * first[2] + second_weight * second[2]) // divisor,
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
        out[i * 4 : i * 4 + 4] = (
            intensity,
            intensity,
            intensity,
            ((v >> 4) & 0x0F) * 17,
        )
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


def _decode_monochrome(
    data: bytes, start: int, count: int, transparency_test_enabled: bool
) -> bytes:
    out = bytearray(count * 4)
    for i in range(count):
        v = data[start + i]
        alpha = (
            0
            if transparency_test_enabled and v == PALETTE_TRANSPARENCY_INDEX
            else 255
        )
        out[i * 4 : i * 4 + 4] = (v, v, v, alpha)
    return bytes(out)


def _decode_paletted(
    data: bytes,
    start: int,
    count: int,
    palette: U9Palette,
    transparency_test_enabled: bool,
) -> bytes:
    out = bytearray(count * 4)
    colors = palette.colors
    for i in range(count):
        index = data[start + i]
        r, g, b = colors[index]
        alpha = (
            0
            if transparency_test_enabled and index == PALETTE_TRANSPARENCY_INDEX
            else 255
        )
        out[i * 4 : i * 4 + 4] = (r, g, b, alpha)
    return bytes(out)


def _decode_565(
    data: bytes,
    start: int,
    count: int,
    transparency_key: int,
    transparency_test_enabled: bool,
) -> bytes:
    out = bytearray(count * 4)
    for i in range(count):
        raw = struct.unpack_from("<H", data, start + i * 2)[0]
        b = (raw & 0x1F) * 255 // 31
        g = ((raw >> 5) & 0x3F) * 255 // 63
        r = ((raw >> 11) & 0x1F) * 255 // 31
        alpha = 0 if transparency_test_enabled and raw == transparency_key else 255
        out[i * 4 : i * 4 + 4] = (r, g, b, alpha)
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


def _decode_alpha_intensity_88(data: bytes, start: int, count: int) -> bytes:
    """Two-byte alpha/intensity: intensity byte first, alpha byte second."""
    out = bytearray(count * 4)
    for i in range(count):
        intensity, alpha = struct.unpack_from("<BB", data, start + i * 2)
        out[i * 4 : i * 4 + 4] = (intensity, intensity, intensity, alpha)
    return bytes(out)


def _has_transparent_pixels(pixels_rgba: bytes) -> bool:
    return any(alpha != 255 for alpha in pixels_rgba[3::4])
