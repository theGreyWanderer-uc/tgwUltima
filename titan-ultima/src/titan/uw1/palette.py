"""Ultima Underworld 1 VGA palette decoding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

PALETTE_COLOR_COUNT = 256
PALETTE_BYTE_SIZE = PALETTE_COLOR_COUNT * 3


class UW1PaletteError(ValueError):
    """Raised when a complete UW1 palette cannot be decoded."""


@dataclass(frozen=True)
class UW1Palette:
    """One 256-colour palette from UW1 ``PALS.DAT``."""

    colors: tuple[tuple[int, int, int], ...]
    index: int = 0

    @classmethod
    def from_data(cls, data: bytes, index: int = 0) -> UW1Palette:
        """Decode palette *index* and expand VGA 6-bit components to 8-bit."""
        if index < 0:
            raise UW1PaletteError(f"UW1 palette index must be non-negative: {index}")
        start = index * PALETTE_BYTE_SIZE
        end = start + PALETTE_BYTE_SIZE
        if end > len(data):
            available = len(data) // PALETTE_BYTE_SIZE
            raise UW1PaletteError(
                f"UW1 palette index {index} outside input "
                f"({available} palettes, {len(data)} bytes)"
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
    def from_file(cls, path: str | Path, index: int = 0) -> UW1Palette:
        """Read one palette from ``PALS.DAT``."""
        return cls.from_data(Path(path).read_bytes(), index=index)

    def flattened_rgb(self) -> list[int]:
        """Return Pillow-compatible flattened RGB components."""
        return [component for color in self.colors for component in color]

    def to_swatch_image(self, swatch_size: int = 16) -> Image.Image:
        """Render the palette as a 16-by-16 swatch grid."""
        if swatch_size < 1:
            raise UW1PaletteError(
                f"UW1 palette swatch size must be positive: {swatch_size}"
            )
        image = Image.new("RGB", (16 * swatch_size, 16 * swatch_size))
        for color_index, color in enumerate(self.colors):
            x = (color_index % 16) * swatch_size
            y = (color_index // 16) * swatch_size
            image.paste(color, (x, y, x + swatch_size, y + swatch_size))
        return image
