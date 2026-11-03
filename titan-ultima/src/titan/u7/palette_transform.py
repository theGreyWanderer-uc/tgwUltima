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
  colour-cycling ranges (``get_ramps``), then remapped proportionally by
  source/target ramp size (``generate_remap_xformtable``).  Both are
  written from a behavioural spec and produce output identical to
  Exult's ``Palette::get_ramps`` / ``Generate_remap_xformtable``.
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


def _ramp_boundaries(
    colors: Sequence[Tuple[int, int, int]], threshold: int
) -> list[int]:
    """Indices 2-255 that begin a new ramp.

    Every colour-cycling range start is a boundary.  Below the first
    cycling range, an index is also a boundary when its brightness
    (R+G+B) differs from the previous index's by more than *threshold*.
    """
    cycle_starts = {rng.start for rng in CYCLE_RANGES}
    gradient_limit = min(cycle_starts)
    brightness = [sum(rgb) for rgb in colors[:256]]
    return [
        idx
        for idx in range(2, 256)
        if idx in cycle_starts
        or (
            idx < gradient_limit
            and abs(brightness[idx] - brightness[idx - 1]) > threshold
        )
    ]


def get_ramps(
    colors: Sequence[Tuple[int, int, int]], *, threshold: int = DEFAULT_RAMP_THRESHOLD
) -> list[Ramp]:
    """Split palette indices 1-255 into brightness-contiguous ramps.

    *colors* is normally palette 0: ramps are always derived from the day
    palette, whichever palette is active.  Index 0 belongs to no ramp.
    Ramps run from one boundary (see :func:`_ramp_boundaries`) to just
    before the next; the final ramp ends at 255.  Matching Exult's
    ``Palette::get_ramps`` output, no boundaries yields no ramps, and at
    most 32 ramps are kept -- when truncated, the last kept ramp still
    ends just before the boundary that would have started ramp 33.
    """
    if len(colors) < 256:
        return []

    boundaries = _ramp_boundaries(colors, threshold)
    if not boundaries:
        return []

    starts = [1, *boundaries]
    ends = [b - 1 for b in boundaries] + [255]
    return [Ramp(s, e) for s, e in zip(starts, ends)][:_MAX_RAMPS]


def _rescale(position: int, source: Ramp, target: Ramp) -> int:
    """Map *position* in *source* to the same relative spot in *target*.

    The relative position is quantized to 1/256 steps first, and both
    divisions floor, so results match Exult's integer remap exactly.
    """
    source_span = source.end - source.start
    target_span = target.end - target.start
    fraction = (position - source.start) * 256 // source_span if source_span else 0
    return (target.start + fraction * target_span // 256) & 0xFF


def generate_remap_xformtable(ramps: Sequence[Ramp], remaps: Dict[int, int]) -> bytes:
    """Build a 256-entry index table moving whole ramps onto other ramps.

    *remaps* maps source ramp number -> target ramp number.  Each index in
    a source ramp is placed at the proportionally equivalent index of its
    target ramp (:func:`_rescale`).  Every other index maps to itself, as
    do entries that remap a ramp to itself, name a ramp number outside
    *ramps*, or have a source ramp starting at index 0.  Later entries win
    where source ramps overlap.  Output matches Exult's
    ``Palette::Generate_remap_xformtable`` for the same remaps.
    """
    table = bytearray(range(256))
    valid = range(len(ramps))

    for source_ramp, target_ramp in remaps.items():
        if source_ramp == target_ramp or source_ramp not in valid or target_ramp not in valid:
            continue
        source, target = ramps[source_ramp], ramps[target_ramp]
        if source.start == 0:
            continue
        for idx in range(source.start, source.end + 1):
            table[idx] = _rescale(idx, source, target)

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
