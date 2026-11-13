"""MD VGA palette cycling, checked against GAME.EXE 02cd:064e–0831."""

from __future__ import annotations

from titan.u6.palette import U6Palette

__all__ = ["build_martian_palette"]


def build_martian_palette(base: U6Palette, tick: int = 0) -> U6Palette:
    """Select a DAC update phase; zero keeps the uncycled palette, independently of tile ticks."""
    if tick < 0:
        raise ValueError("Martian Dreams palette tick must be nonnegative")
    palette = U6Palette()
    palette.colors = list(base.colors)
    palette.trailing = base.trailing
    if tick:
        counter = tick & 255
        for start, size, shift in (
            (224, 8, counter + 1),
            (232, 8, counter + 1),
            (240, 4, counter // 2 + 1),
            (244, 4, counter // 2 + 1),
            (248, 4, counter // 2 + 1),
        ):
            for index in range(size):
                palette.colors[start + index] = base.colors[
                    start + (index - shift) % size
                ]
        pulse = (tick - 1) & 15
        gray = (12 + min(pulse, 15 - pulse)) * 255 // 63
        palette.colors[255] = (gray, gray, gray)
    return palette
