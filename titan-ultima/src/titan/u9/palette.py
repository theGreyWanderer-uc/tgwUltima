"""Read, inspect, render, quantize, and write Ultima IX ``ankh.pal`` files.

The file is a headerless table of 256 four-byte entries. The first three
bytes are 8-bit red, green, and blue components; the fourth byte is reserved
and is zero throughout the shipped palette. It is not an alpha channel.

Paletted texture index 254 is the game's exact colour key. It is transparent
even though its stored RGB value is the same medium grey as indices 247-253
and 255. See :mod:`titan.u9.texture` for texture-surface decoding.
"""

from __future__ import annotations

__all__ = [
    "ENTRY_SIZE",
    "EXPECTED_SIZE",
    "PALETTE_ENTRY_COUNT",
    "PALETTE_TRANSPARENCY_INDEX",
    "U9Palette",
    "U9PaletteError",
]

import os
from collections.abc import Iterable, Sequence

from PIL import Image

PALETTE_ENTRY_COUNT = 256
ENTRY_SIZE = 4
EXPECTED_SIZE = PALETTE_ENTRY_COUNT * ENTRY_SIZE
PALETTE_TRANSPARENCY_INDEX = 254
"""Exact transparent colour-key index used by U9 paletted textures."""

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


class U9PaletteError(ValueError):
    """Raised when data cannot represent a complete U9 palette."""


def _validate_color(color: Sequence[int], *, label: str = "color") -> RGB:
    if len(color) != 3:
        raise U9PaletteError(f"{label} must contain exactly 3 components")
    rgb = tuple(color)
    if any(
        not isinstance(component, int) or not 0 <= component <= 255 for component in rgb
    ):
        raise U9PaletteError(f"{label} components must be integers from 0 to 255")
    return rgb[0], rgb[1], rgb[2]


class U9Palette:
    """The 256-entry RGB colour table stored in ``static/ankh.pal``.

    ``data`` may contain trailing bytes for compatibility with callers that
    read from a larger buffer. They are exposed as :attr:`trailing_data`, but
    :meth:`to_bytes` writes only the 1,024-byte palette structure.
    """

    def __init__(self, data: bytes) -> None:
        if len(data) < EXPECTED_SIZE:
            raise U9PaletteError(
                f"palette data too small: {len(data)} bytes (need {EXPECTED_SIZE})"
            )
        entries = data[:EXPECTED_SIZE]
        self.colors: tuple[RGB, ...] = tuple(
            (
                entries[offset],
                entries[offset + 1],
                entries[offset + 2],
            )
            for offset in range(0, EXPECTED_SIZE, ENTRY_SIZE)
        )
        self.reserved: tuple[int, ...] = tuple(
            entries[offset + 3] for offset in range(0, EXPECTED_SIZE, ENTRY_SIZE)
        )
        self.trailing_data = data[EXPECTED_SIZE:]

    @classmethod
    def parse(cls, data: bytes) -> U9Palette:
        """Parse palette bytes; equivalent to constructing :class:`U9Palette`."""
        return cls(data)

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Palette:
        """Read a palette from *filepath*."""
        with open(filepath, "rb") as file:
            return cls(file.read())

    @classmethod
    def from_colors(
        cls,
        colors: Sequence[Sequence[int]],
        *,
        reserved: Sequence[int] | None = None,
    ) -> U9Palette:
        """Build a writable palette from exactly 256 RGB colours.

        The reserved fourth byte defaults to zero for every entry. Supplying
        it explicitly is useful when reconstructing a variant palette whose
        reserved values are not all zero.
        """
        if len(colors) != PALETTE_ENTRY_COUNT:
            raise U9PaletteError(
                f"palette needs exactly {PALETTE_ENTRY_COUNT} colors, got {len(colors)}"
            )
        if reserved is None:
            reserved = (0,) * PALETTE_ENTRY_COUNT
        if len(reserved) != PALETTE_ENTRY_COUNT:
            raise U9PaletteError(
                f"reserved-byte table needs exactly {PALETTE_ENTRY_COUNT} values, "
                f"got {len(reserved)}"
            )

        data = bytearray(EXPECTED_SIZE)
        for index, color in enumerate(colors):
            r, g, b = _validate_color(color, label=f"color {index}")
            fourth = reserved[index]
            if not isinstance(fourth, int) or not 0 <= fourth <= 255:
                raise U9PaletteError(
                    f"reserved byte {index} must be an integer from 0 to 255"
                )
            data[index * ENTRY_SIZE : index * ENTRY_SIZE + ENTRY_SIZE] = (
                r,
                g,
                b,
                fourth,
            )
        return cls(bytes(data))

    def color_for(self, index: int) -> RGB:
        """Return the stored RGB colour for *index*."""
        self._validate_index(index)
        return self.colors[index]

    def rgba_for(self, index: int) -> RGBA:
        """Return RGB plus colour-key alpha for a paletted texture index."""
        r, g, b = self.color_for(index)
        alpha = 0 if index == PALETTE_TRANSPARENCY_INDEX else 255
        return r, g, b, alpha

    def nearest_color_index(
        self,
        color: Sequence[int],
        *,
        exclude: Iterable[int] = (),
    ) -> int:
        """Return the lowest-index nearest RGB entry by squared distance.

        Exact duplicate colours deliberately resolve to the first index. U9
        texture encoders exclude index 254 for opaque pixels so the RGB-equal
        but opaque index 247 wins instead.
        """
        r, g, b = _validate_color(color)
        excluded = frozenset(exclude)
        invalid = sorted(index for index in excluded if not 0 <= index < len(self))
        if invalid:
            raise U9PaletteError(f"excluded palette index out of range: {invalid[0]}")

        best_index: int | None = None
        best_distance: int | None = None
        for index, (pr, pg, pb) in enumerate(self.colors):
            if index in excluded:
                continue
            distance = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if best_distance is None or distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            raise U9PaletteError("nearest-color search excluded every palette index")
        return best_index

    def duplicate_groups(self) -> tuple[tuple[RGB, tuple[int, ...]], ...]:
        """Return repeated colours and all of their indices, in index order."""
        indices_by_color: dict[RGB, list[int]] = {}
        for index, color in enumerate(self.colors):
            indices_by_color.setdefault(color, []).append(index)
        return tuple(
            (color, tuple(indices))
            for color, indices in indices_by_color.items()
            if len(indices) > 1
        )

    def to_flat_rgb(self) -> bytes:
        """Return 768 RGB bytes suitable for Pillow's ``putpalette``."""
        return bytes(component for color in self.colors for component in color)

    def to_bytes(self) -> bytes:
        """Serialize the exact 1,024-byte RGB-plus-reserved palette table."""
        data = bytearray(EXPECTED_SIZE)
        for index, ((r, g, b), fourth) in enumerate(zip(self.colors, self.reserved)):
            data[index * ENTRY_SIZE : index * ENTRY_SIZE + ENTRY_SIZE] = (
                r,
                g,
                b,
                fourth,
            )
        return bytes(data)

    def to_pil_image(self, swatch_size: int = 16) -> Image.Image:
        """Render a 16x16 RGB swatch grid without treating byte 3 as alpha."""
        if swatch_size <= 0:
            raise U9PaletteError("swatch_size must be greater than zero")
        image = Image.new("RGB", (16 * swatch_size, 16 * swatch_size))
        pixels = image.load()
        if pixels is None:  # Pillow only returns None for unsupported image types.
            raise U9PaletteError("could not access swatch image pixels")
        for index, color in enumerate(self.colors):
            row, column = divmod(index, 16)
            left = column * swatch_size
            top = row * swatch_size
            for y in range(top, top + swatch_size):
                for x in range(left, left + swatch_size):
                    pixels[x, y] = color
        return image

    @staticmethod
    def _validate_index(index: int) -> None:
        if not isinstance(index, int) or not 0 <= index < PALETTE_ENTRY_COUNT:
            raise IndexError(
                f"palette index {index!r} out of range (0..{PALETTE_ENTRY_COUNT - 1})"
            )

    def __len__(self) -> int:
        return len(self.colors)
