"""
Semantic metadata for Ultima 7 palette indices and slots.

Models the parts of Exult's palette handling that are *meaning*, not
colour data: which ``PALETTES.FLX`` slot corresponds to which in-game
state (day/night/etc.), which pixel-index ranges are engine-cycled, and
the context-dependent rule for index 255's transparency.

Sourced from Exult (``D:/_Repos/exult``): ``palette.h:32-45`` (named slot
constants), ``gamewin.cc:1053-1067`` (``Game_window::rotatecolours``, the
six hardcoded cycle ranges), ``shapeid.h:55-70`` (``Pixel_colors`` enum
naming the same six ranges).
"""

from __future__ import annotations

__all__ = [
    "PALETTE_SLOT_NAMES",
    "palette_slot_name",
    "CycleRange",
    "CYCLE_RANGES",
    "is_transparent_in_context",
]

from dataclasses import dataclass
from typing import Optional

# Named PALETTES.FLX slots (Exult palette.h:32-45).  Index 9 has no Exult
# constant -- its own source only comments "9 has lots of black" -- and it
# is absent entirely from Black Gate's PALETTES.FLX (populated only in
# Serpent Isle).  Unknown/custom slots simply have no entry here; see
# palette_slot_name() -- absence is not invalidity.
PALETTE_SLOT_NAMES: dict[int, str] = {
    0: "day",
    1: "dusk",  # Exult's own comment: "Think this is it" (PALETTE_DUSK / PALETTE_DAWN alias)
    2: "night",
    3: "invisible",
    4: "overcast",
    5: "fog",
    6: "spell",
    7: "candle",
    8: "red",  # combat hit
    10: "lightning",
    11: "single_light",
    12: "many_lights",
}


def palette_slot_name(index: int) -> Optional[str]:
    """Return the Exult-documented name for a ``PALETTES.FLX`` slot, or
    ``None`` for unknown/custom slots.  A missing name is just a missing
    label -- the slot remains fully usable."""
    return PALETTE_SLOT_NAMES.get(index)


@dataclass(frozen=True)
class CycleRange:
    """One of Exult's six hardcoded palette-cycling ranges."""

    name: str
    start: int
    length: int

    @property
    def end(self) -> int:
        """Inclusive end index."""
        return self.start + self.length - 1


# The six ranges Game_window::rotatecolours() rotates every tick
# (gamewin.cc:1062-1067), named per shapeid.h's Pixel_colors enum
# (shapeid.h:64-69).  All six rotate the same direction, one colour slot
# per tick -- see titan.u7.palette_cycle for the rotation itself.
CYCLE_RANGES: tuple[CycleRange, ...] = (
    CycleRange("magic", 224, 8),    # cyan/white
    CycleRange("fire", 232, 8),     # yellow/red
    CycleRange("green", 240, 4),
    CycleRange("magenta", 244, 4),
    CycleRange("yellow", 248, 4),   # white/yellow
    CycleRange("ryb", 252, 3),      # red/yellow/black
)


def is_transparent_in_context(index: int, *, rle_sprite: bool) -> bool:
    """Whether palette *index* renders as transparent.

    Index 255 is transparent only for RLE sprite pixels (an
    encoder/decoder convention -- see titan.u7.shape's use of 0xFF as the
    "uncovered by any span" sentinel); flat (non-RLE) terrain tiles render
    every index, including 255, as an ordinary opaque colour.  Titan
    should never claim index 255 is "always" transparent.
    """
    return rle_sprite and index == 0xFF
