"""Ultima Underworld II ``.GR`` shape archive decoding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from titan.uw2.palette import UW2Palette


class UW2GRError(ValueError):
    """Raised when a UU2 GR archive or image record is malformed."""


@dataclass(frozen=True)
class UW2GRImage:
    """One indexed image decoded from a UU2 GR archive."""

    index: int
    offset: int
    bitmap_type: int
    width: int
    height: int
    auxiliary_palette_index: int | None
    palette_indices: bytes

    def to_image(self, palette: UW2Palette, transparent_index: int = 0) -> Image.Image:
        """Convert indexed pixels to RGBA; index 0 is transparent by default."""
        pixels: np.ndarray = np.frombuffer(
            self.palette_indices, dtype=np.uint8
        ).reshape((self.height, self.width))
        indexed = Image.fromarray(pixels, mode="P")
        indexed.putpalette(palette.flattened_rgb())
        rgba = indexed.convert("RGBA")
        alpha = np.where(pixels == transparent_index, 0, 255).astype(np.uint8)
        rgba.putalpha(Image.fromarray(alpha, mode="L"))
        return rgba


@dataclass(frozen=True)
class UW2GRArchive:
    """Decoded UU2 GR offset table plus all non-empty images."""

    source: str
    declared_image_count: int
    images: tuple[UW2GRImage, ...]

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        allpals_path: str | Path | None = None,
    ) -> UW2GRArchive:
        """Read GR file and optional ``ALLPALS.DAT`` auxiliary palettes."""
        source_path = Path(path)
        auxiliary = (
            load_auxiliary_palettes(Path(allpals_path).read_bytes())
            if allpals_path is not None
            else default_auxiliary_palettes()
        )
        return cls.from_data(
            source_path.read_bytes(), source=str(source_path), auxiliary=auxiliary
        )

    @classmethod
    def from_data(
        cls,
        data: bytes,
        *,
        source: str = "<bytes>",
        auxiliary: tuple[tuple[int, ...], ...] | None = None,
    ) -> UW2GRArchive:
        """Decode a GR archive from bytes."""
        if len(data) < 3:
            raise UW2GRError(f"UW2 GR archive too small: {source} ({len(data)} bytes)")
        if data[0] != 1:
            raise UW2GRError(
                f"UW2 GR format byte must be 0x01: {source} has {data[0]:#04x}"
            )
        declared_count = struct.unpack_from("<H", data, 1)[0]
        table_end = 3 + declared_count * 4
        if table_end > len(data):
            raise UW2GRError(f"UW2 GR offset table exceeds source: {source}")
        offsets = struct.unpack_from(f"<{declared_count}I", data, 3)
        palettes = auxiliary or default_auxiliary_palettes()
        images: list[UW2GRImage] = []
        for index, offset in enumerate(offsets):
            next_offset = (
                offsets[index + 1] if index + 1 < declared_count else len(data)
            )
            if offset == next_offset or offset == 0:
                continue
            if offset < table_end or offset >= len(data) or next_offset > len(data):
                raise UW2GRError(
                    f"UW2 GR image {index} has invalid offset {offset:#x}: {source}"
                )
            images.append(_decode_gr_image(data, index, offset, next_offset, palettes))
        return cls(
            source=source, declared_image_count=declared_count, images=tuple(images)
        )

    def image(self, index: int) -> UW2GRImage:
        """Return archive image by declared index, including sparse archives."""
        found = next((image for image in self.images if image.index == index), None)
        if found is None:
            raise UW2GRError(
                f"UW2 GR image index {index} missing from {self.source} "
                f"(declared range 0..{self.declared_image_count - 1})"
            )
        return found

    def summary(self) -> dict[str, object]:
        """Return JSON-ready archive and image metadata."""
        return {
            "source": self.source,
            "declared_image_count": self.declared_image_count,
            "decoded_image_count": len(self.images),
            "images": [
                {
                    "index": image.index,
                    "offset": image.offset,
                    "bitmap_type": image.bitmap_type,
                    "width": image.width,
                    "height": image.height,
                    "auxiliary_palette_index": image.auxiliary_palette_index,
                }
                for image in self.images
            ],
        }


def load_auxiliary_palettes(data: bytes) -> tuple[tuple[int, ...], ...]:
    """Decode 16-byte lookup rows from ``ALLPALS.DAT``."""
    palettes = tuple(
        tuple(data[offset : offset + 16]) for offset in range(0, len(data) - 15, 16)
    )
    if not palettes:
        raise UW2GRError(
            f"UW2 ALLPALS.DAT has no complete palette rows ({len(data)} bytes)"
        )
    return palettes


def default_auxiliary_palettes() -> tuple[tuple[int, ...], ...]:
    """Return diagnostic identity palettes when ALLPALS.DAT is unavailable."""
    return tuple(tuple(range(16)) for _ in range(32))


def _decode_gr_image(
    data: bytes,
    index: int,
    offset: int,
    end: int,
    auxiliary: tuple[tuple[int, ...], ...],
) -> UW2GRImage:
    if offset + 3 > end:
        raise UW2GRError(f"UW2 GR image {index} header truncated")
    bitmap_type, width, height = data[offset : offset + 3]
    pixel_count = width * height
    auxiliary_index: int | None = None

    if bitmap_type == 0x04:
        _require_record_bytes(index, offset, end, 5)
        data_length = struct.unpack_from("<H", data, offset + 3)[0]
        pixels = data[offset + 5 : min(offset + 5 + data_length, end)]
    elif bitmap_type == 0x0A:
        _require_record_bytes(index, offset, end, 6)
        auxiliary_index = data[offset + 3]
        palette = _auxiliary_palette(auxiliary, auxiliary_index, index)
        data_length = struct.unpack_from("<H", data, offset + 4)[0]
        packed = data[offset + 6 : min(offset + 6 + data_length, end)]
        pixels = bytes(palette[value] for value in _unpack_nibbles(packed, pixel_count))
    elif bitmap_type in (0x06, 0x08):
        _require_record_bytes(index, offset, end, 6)
        auxiliary_index = data[offset + 3]
        palette = _auxiliary_palette(auxiliary, auxiliary_index, index)
        word_size = 5 if bitmap_type == 0x06 else 4
        word_count = struct.unpack_from("<H", data, offset + 4)[0]
        byte_count = (word_count * word_size + 7) // 8
        packed = data[offset + 6 : min(offset + 6 + byte_count, end)]
        words = _unpack_words(packed, word_count, word_size)
        pixels = _decode_rle_words(words, pixel_count, word_size, palette)
    else:
        raise UW2GRError(
            f"UW2 GR image {index} uses unsupported bitmap type {bitmap_type:#04x}"
        )

    pixels = pixels[:pixel_count].ljust(pixel_count, b"\x00")
    return UW2GRImage(
        index=index,
        offset=offset,
        bitmap_type=bitmap_type,
        width=width,
        height=height,
        auxiliary_palette_index=auxiliary_index,
        palette_indices=pixels,
    )


def _require_record_bytes(index: int, offset: int, end: int, size: int) -> None:
    if offset + size > end:
        raise UW2GRError(f"UW2 GR image {index} record header truncated")


def _auxiliary_palette(
    palettes: tuple[tuple[int, ...], ...], index: int, image_index: int
) -> tuple[int, ...]:
    if index >= len(palettes):
        raise UW2GRError(
            f"UW2 GR image {image_index} requests auxiliary palette {index}; "
            f"only {len(palettes)} available"
        )
    return palettes[index]


def _unpack_nibbles(data: bytes, count: int) -> list[int]:
    values: list[int] = []
    for byte in data:
        values.extend(((byte >> 4) & 0x0F, byte & 0x0F))
        if len(values) >= count:
            break
    return values[:count]


def _unpack_words(data: bytes, count: int, word_size: int) -> list[int]:
    values: list[int] = []
    bit_position = 0
    while len(values) < count and bit_position + word_size <= len(data) * 8:
        value = 0
        for _ in range(word_size):
            byte = data[bit_position // 8]
            bit = 7 - bit_position % 8
            value = (value << 1) | ((byte >> bit) & 1)
            bit_position += 1
        values.append(value)
    return values


def _decode_rle_words(
    words: list[int],
    pixel_count: int,
    word_size: int,
    auxiliary_palette: tuple[int, ...],
) -> bytes:
    output: list[int] = []
    position = 0
    state = "repeat_start"
    repeat_count = 0
    count = 0
    while len(output) < pixel_count and position < len(words):
        if state == "repeat_start":
            count, position = _read_rle_count(words, position, word_size)
            if count == 1:
                state = "run"
            elif count == 2:
                repeat_count, position = _read_rle_count(words, position, word_size)
                repeat_count = max(0, repeat_count - 1)
            else:
                state = "repeat"
        elif state == "repeat":
            value = auxiliary_palette[words[position] % len(auxiliary_palette)]
            position += 1
            output.extend([value] * min(count, pixel_count - len(output)))
            if repeat_count == 0:
                state = "run"
            else:
                repeat_count -= 1
                state = "repeat_start"
        else:
            count, position = _read_rle_count(words, position, word_size)
            for _ in range(min(count, pixel_count - len(output))):
                if position >= len(words):
                    break
                output.append(
                    auxiliary_palette[words[position] % len(auxiliary_palette)]
                )
                position += 1
            state = "repeat_start"
    return bytes(output)


def _read_rle_count(words: list[int], position: int, word_size: int) -> tuple[int, int]:
    if position >= len(words):
        return 0, position
    count = words[position]
    position += 1
    if count:
        return count, position
    if position + 1 >= len(words):
        return 0, len(words)
    count = (words[position] << word_size) | words[position + 1]
    position += 2
    if count:
        return count, position
    if position + 2 >= len(words):
        return 0, len(words)
    count = ((words[position] << word_size) | words[position + 1]) << word_size
    count |= words[position + 2]
    return count, position + 3
