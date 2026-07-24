"""
In-game palette reader for Ultima 6 (``U6PAL``).

Binary layout (1024 bytes total, verified against a real ``U6PAL``, no
header)::

    Offset 0x000, 768 bytes: 256 RGB triplets, each component 0-63 (VGA 6-bit)
    Offset 0x300, 256 bytes: trailing per-entry data, purpose undocumented
                             (u6tech.txt: "I don't know what the other 0x100
                             bytes are for")

Cut-scene palettes (``PALETTES.INT``, 8 further "packed" 6-bits-per-channel
palettes) are a separate, documented-but-unimplemented format -- not covered
here yet.

Example::

    from titan.u6.palette import U6Palette

    pal = U6Palette.from_file("U6PAL")
    swatch = pal.to_pil_image()
"""

from __future__ import annotations

__all__ = ["U6Palette", "U6PaletteError"]

import os

from PIL import Image

PALETTE_DATA_SIZE = 768  # 256 * 3
TRAILING_SIZE = 256
TOTAL_SIZE = PALETTE_DATA_SIZE + TRAILING_SIZE


class U6PaletteError(Exception):
    """Raised when palette data is too short."""


class U6Palette:
    """Ultima 6 in-game palette (``U6PAL``)."""

    def __init__(self) -> None:
        self.colors: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
        self.trailing: bytes = bytes(TRAILING_SIZE)  # undocumented per-entry data

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U6Palette:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> U6Palette:
        if len(data) < TOTAL_SIZE:
            raise U6PaletteError(f"palette data too small: {len(data)} bytes (need {TOTAL_SIZE})")

        pal = cls()
        raw = data[:PALETTE_DATA_SIZE]
        for i in range(256):
            r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
            # VGA 6-bit (0-63) -> 8-bit (0-255), matching titan.palette.U8Palette's scaling.
            pal.colors[i] = ((r * 255) // 63, (g * 255) // 63, (b * 255) // 63)
        pal.trailing = data[PALETTE_DATA_SIZE:TOTAL_SIZE]
        return pal

    def to_flat_rgb(self) -> bytes:
        """Return 768 bytes of flat RGB data (for PIL ``putpalette``)."""
        flat = bytearray(768)
        for i, (r, g, b) in enumerate(self.colors):
            flat[i * 3:i * 3 + 3] = (r, g, b)
        return bytes(flat)

    def to_pil_image(self, swatch_size: int = 16) -> Image.Image:
        """Create a 16x16 grid swatch image of the palette."""
        img = Image.new("RGB", (16 * swatch_size, 16 * swatch_size))
        pixels = img.load()
        for idx in range(256):
            row, col = divmod(idx, 16)
            color = self.colors[idx]
            for py in range(swatch_size):
                for px in range(swatch_size):
                    pixels[col * swatch_size + px, row * swatch_size + py] = color
        return img
