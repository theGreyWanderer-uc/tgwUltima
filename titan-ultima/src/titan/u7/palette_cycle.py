"""
Ultima 7 palette colour-cycling engine.

Reproduces Exult's ``Game_window::rotatecolours()`` (``gamewin.cc:1053-1067``):
every tick, six fixed pixel-index ranges are each rotated by one colour
slot, all in the same direction (the last colour in each range moves to
the front; every other colour shifts up by one slot -- matching
``Image_window8::rotate_colors``'s ``std::rotate`` semantics, confirmed
against the source rather than assumed).  Exult's default tick rate is
100ms (``gamewin.cc:1058``); the 2x slowdown Exult applies in
non-palettized/scaled display modes is a rendering detail this data-layer
API does not model.
"""

from __future__ import annotations

__all__ = ["rotate_range", "apply_all_cycles", "DEFAULT_CYCLE_MS"]

from typing import Sequence, TypeVar

from titan.u7.palette_semantics import CYCLE_RANGES

DEFAULT_CYCLE_MS = 100

_T = TypeVar("_T")


def rotate_range(
    colors: Sequence[_T], start: int, length: int, steps: int = 1
) -> list[_T]:
    """Return *colors* (a 256-entry sequence) with the *length*-colour
    slice starting at *start* rotated by *steps* slots.

    Matches Exult's ``Image_window8::rotate_colors``: with each step, the
    *last* colour in the range moves to the front and every other colour
    in the range shifts up by one slot.  All six of Exult's hardcoded
    ranges use this same direction.
    """
    result = list(colors)
    if length <= 0:
        return result

    steps = steps % length
    if steps == 0:
        return result

    window = result[start:start + length]
    rotated = window[-steps:] + window[:-steps]
    result[start:start + length] = rotated
    return result


def apply_all_cycles(colors: Sequence[_T], steps: int = 1) -> list[_T]:
    """Apply *steps* rotation step(s) to all six of Exult's cycling
    ranges, matching *steps* calls to ``rotatecolours()``."""
    result = list(colors)
    for rng in CYCLE_RANGES:
        result = rotate_range(result, rng.start, rng.length, steps=steps)
    return result
