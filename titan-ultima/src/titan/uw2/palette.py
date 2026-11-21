"""Ultima Underworld II 6-bit VGA palette decoding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from titan.errors import InvalidDataError

PALETTE_COLOR_COUNT = 256
PALETTE_BYTE_SIZE = PALETTE_COLOR_COUNT * 3


class UW2PaletteError(InvalidDataError):
    """Raised when PALS.DAT cannot provide one complete 256-color palette."""


@dataclass(frozen=True)
class UW2Palette:
    """One 256-color palette from UU2 ``PALS.DAT``."""

    colors: tuple[tuple[int, int, int], ...]
    index: int = 0

    @classmethod
    def from_data(cls, data: bytes, index: int = 0) -> UW2Palette:
        """Decode palette *index*; source components use VGA 6-bit range."""
        if index < 0:
            raise UW2PaletteError(f"UW2 palette index must be non-negative: {index}")
        start = index * PALETTE_BYTE_SIZE
        end = start + PALETTE_BYTE_SIZE
        if end > len(data):
            available = len(data) // PALETTE_BYTE_SIZE
            raise UW2PaletteError(
                f"UW2 palette index {index} outside source ({available} palettes, {len(data)} bytes)"
            )
        raw = data[start:end]
        colors = tuple(
            (
                min(raw[offset] << 2, 255),
                min(raw[offset + 1] << 2, 255),
                min(raw[offset + 2] << 2, 255),
            )
            for offset in range(0, PALETTE_BYTE_SIZE, 3)
        )
        return cls(colors=colors, index=index)

    @classmethod
    def from_file(cls, path: str | Path, index: int = 0) -> UW2Palette:
        """Read one palette from UU2 ``PALS.DAT``."""
        return cls.from_data(Path(path).read_bytes(), index=index)

    def to_flat_rgb(self) -> bytes:
        """768 bytes ``r0 g0 b0 r1 ...`` for Pillow's ``putpalette``."""
        return bytes(component for color in self.colors for component in color)

    def flattened_rgb(self) -> list[int]:
        """:meth:`to_flat_rgb` as a list of ints (the older name)."""
        return list(self.to_flat_rgb())

    def to_pil_image(self, swatch_size: int = 16) -> Image.Image:
        """Render palette as 16x16 swatch grid."""
        if swatch_size < 1:
            raise UW2PaletteError(
                f"UW2 palette swatch size must be positive: {swatch_size}"
            )
        image = Image.new("RGB", (16 * swatch_size, 16 * swatch_size))
        for color_index, color in enumerate(self.colors):
            x = (color_index % 16) * swatch_size
            y = (color_index // 16) * swatch_size
            image.paste(color, (x, y, x + swatch_size, y + swatch_size))
        return image

    def to_swatch_image(self, swatch_size: int = 16) -> Image.Image:
        """:meth:`to_pil_image` (the older name)."""
        return self.to_pil_image(swatch_size)
