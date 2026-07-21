"""
Ultima 7 palette-index transformations.

Ports Exult's ``ShapeID::PaletteTransformType`` operations
(``shapeid.cc:591-628``, enum at ``shapeid.h:311-328``): whole-shape
recolouring operations distinct from per-pixel translucency compositing
(:mod:`titan.u7.translucency`), though ``PT_xForm`` reuses the exact same
xform-table data.  All four operate on raw palette indices *before* RGB
conversion, matching Exult.

* ``PT_Shift`` -- ``shift_index``: ``(index + offset) & 0xff``, with
  indices 0 and 255 always mapping to themselves (``shapeid.cc:617-623``).
* ``PT_xForm`` -- ``xform_index``: remap through the same 256-byte xform
  table used for translucency compositing, addressed directly by slot
  number rather than by a translucent pixel value (``shapeid.cc:625-626``).
* ``PT_RampRemap`` / ``PT_RampRemapAllFrom`` -- ``remap_ramp`` /
  ``remap_all_ramps``: proportionally remap one colour "ramp" (a
  brightness-contiguous run of palette entries) onto another.  Ramps are
  **not** a fixed layout -- they're detected by scanning palette 0 for
  brightness discontinuities, with forced breaks at the six
  colour-cycling ranges (``get_ramps``, porting ``palette.cc:581-654``),
  then remapped proportionally by source/target ramp size
  (``generate_remap_xformtable``, porting ``palette.cc:697-724``).
"""

from __future__ import annotations

__all__ = [
    "Ramp",
    "get_ramps",
    "generate_remap_xformtable",
    "shift_index",
    "xform_index",
    "remap_ramp",
    "remap_all_ramps",
]

from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

from titan.u7.palette_semantics import CYCLE_RANGES
from titan.u7.translucency import U7Translucency

# Exult's 6-bit brightness-jump threshold is 48; its own comment notes
# that's "equiv to 192 in 8 bit" (palette.cc:614-615).  Titan's
# U7Palette.colors are always stored 8-bit-expanded regardless of the
# source archive's native encoding, so this module operates on that
# normalized 8-bit form and uses the 8-bit-equivalent threshold.
DEFAULT_RAMP_THRESHOLD = 192

_MAX_RAMPS = 32


@dataclass(frozen=True)
class Ramp:
    """One brightness-contiguous run of palette indices (inclusive)."""

    start: int
    end: int


def get_ramps(
    colors: Sequence[Tuple[int, int, int]], *, threshold: int = DEFAULT_RAMP_THRESHOLD
) -> list[Ramp]:
    """Port of Exult's ``Palette::get_ramps`` (``palette.cc:581-654``).

    Scans *colors* (normally palette 0 -- Exult always derives ramps from
    the day palette regardless of which palette is active) for brightness
    discontinuities greater than *threshold*, with forced ramp breaks at
    each of the six palette-cycling range starts.  Index 0 is never
    included in any ramp.  Returns at most 32 ramps, matching Exult's
    fixed-size ``Ramp ramps[32]``.
    """
    if len(colors) < 256:
        return []

    cycle_starts = frozenset(rng.start for rng in CYCLE_RANGES)
    first_cycle_start = min(cycle_starts)

    starts = [1]
    ends: list[int] = []
    r = 0
    hit_cap = False
    last = sum(colors[1])

    for c in range(2, 256):
        brightness = sum(colors[c])
        is_break = (
            (c < first_cycle_start and abs(brightness - last) > threshold)
            or c in cycle_starts
        )
        if is_break:
            ends.append(c - 1)
            r += 1
            if r >= _MAX_RAMPS:
                hit_cap = True
                break
            starts.append(c)
        last = brightness

    if r == 0:
        return []
    if not hit_cap:
        ends.append(255)

    return [Ramp(s, e) for s, e in zip(starts, ends)]


def generate_remap_xformtable(ramps: Sequence[Ramp], remaps: Dict[int, int]) -> bytes:
    """Port of Exult's ``Palette::Generate_remap_xformtable``
    (``palette.cc:697-724``).

    *remaps* maps a source ramp number to a target ramp number for every
    ramp that should be remapped -- a dict rather than Exult's
    sentinel-terminated 32-int array, which encodes the same "which ramps
    remap to which" input differently.  Ramps not present in *remaps*, or
    mapping to themselves, or referencing an out-of-range ramp number, are
    left as identity (Titan tightens Exult's ``to > num_ramps`` bound to
    ``>=`` since this port's ``ramps`` list is sized exactly to the
    detected count, unlike Exult's fixed 32-slot array).
    """
    num_ramps = len(ramps)
    table = bytearray(range(256))

    for source_ramp, target_ramp in remaps.items():
        if source_ramp == target_ramp:
            continue
        if not (0 <= source_ramp < num_ramps) or not (0 <= target_ramp < num_ramps):
            continue

        from_ramp = ramps[source_ramp]
        to_ramp = ramps[target_ramp]
        from_size = from_ramp.end - from_ramp.start
        to_size = to_ramp.end - to_ramp.start
        if from_ramp.start == 0:
            continue

        for c in range(from_ramp.start, from_ramp.end + 1):
            offset = ((c - from_ramp.start) * 256) // from_size if from_size else 0
            table[c] = (to_ramp.start + (offset * to_size) // 256) & 0xFF

    return bytes(table)


def shift_index(index: int, offset: int) -> int:
    """``PT_Shift``: ``(index + offset) & 0xff``, except indices 0 and
    255 always map to themselves (``shapeid.cc:617-623``)."""
    if index == 0:
        return 0
    if index == 255:
        return 255
    return (index + offset) & 0xFF


def xform_index(index: int, translucency: U7Translucency, table_slot: int) -> int:
    """``PT_xForm``: remap *index* through ``xforms[table_slot]`` -- the
    same 256-byte xform table used for per-pixel translucency
    compositing (``shapeid.cc:625-626``), addressed directly by slot
    number rather than by a translucent pixel value."""
    table = translucency.table_by_slot(table_slot)
    return index if table is None else table[index]


def remap_ramp(index: int, ramp_from: int, ramp_to: int, ramps: Sequence[Ramp]) -> int:
    """``PT_RampRemap``: remap *index* by moving it from ramp *ramp_from*
    to the proportionally-equivalent position in ramp *ramp_to*."""
    table = generate_remap_xformtable(ramps, {ramp_from: ramp_to})
    return table[index]


def remap_all_ramps(index: int, ramp_to: int, ramps: Sequence[Ramp]) -> int:
    """``PT_RampRemapAllFrom``: remap every ramp except *ramp_to* itself
    onto *ramp_to* (Exult's ``from == 255`` sentinel case)."""
    remaps = {r: ramp_to for r in range(len(ramps)) if r != ramp_to}
    table = generate_remap_xformtable(ramps, remaps)
    return table[index]
