"""
Ultima 7 shape colour-cycle / translucency content scanning.

Classifies which palette indices in a shape's frames are ordinary
colour-cycling pixels (:mod:`titan.u7.palette_cycle`) versus
translucency-blend pixels (:mod:`titan.u7.translucency`).  The two
mechanisms share part of the same high-index range (224-254), but which
one actually applies is determined by the shape's own TFA translucency
flag, not the pixel value alone.  Conflating them is a silent rendering
bug (a merely-cycling shape freezing at a static translucency-preview
colour), not a crash -- see :mod:`titan.u7.translucency`'s module
docstring for the underlying mechanism.

Scans every frame of a shape, not just one, so a shape with a
cycle/translucency effect confined to a rarely-checked frame isn't missed.

Each frame report also records whether the frame is flat (tile) or RLE,
since index 255's transparency meaning is context-dependent: RLE sprites
treat it as the "uncovered by any span" sentinel (see
:mod:`titan.u7.shape`), while flat ground tiles have no transparency
concept at all and render 255 as an ordinary opaque colour like any other
index (see :func:`titan.u7.palette_semantics.is_transparent_in_context`).
A consumer needs to know which kind of frame it's looking at before it can
correctly interpret an index-255 pixel.

Shape-level reports expose the *resolved* animation parameters (type,
frame count used, recycle, freeze chance, frame delay) via
:mod:`titan.u7.shape_animation`, not just a boolean -- a client that only
gets "is this shape animated" cannot reproduce the actual timing.
"""

from __future__ import annotations

__all__ = [
    "FrameCycleReport",
    "ShapeCycleReport",
    "scan_frame",
    "scan_shape",
]

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, FrozenSet, List, Optional

import numpy as np

from titan.u7.palette_semantics import CYCLE_RANGES
from titan.u7.shape_animation import AnimationInfo, default_animation_for_tfa

if TYPE_CHECKING:
    from titan.u7.shape import U7Shape
    from titan.u7.typeflag import U7TypeFlags

# Cycle-range floor/ceiling (224/254) -- pixels outside this span are never
# cycle- or translucency-related regardless of shape flags.
_CYCLE_FLOOR = min(r.start for r in CYCLE_RANGES)
_CYCLE_CEILING = max(r.end for r in CYCLE_RANGES)

# The reserved/transparent-in-RLE-context sentinel (see module docstring).
_TRANSPARENT_INDEX = 255

# Empirical translucency-window start for Black Gate/Serpent Isle (17 blend
# slots, 0xFF-17=238). Callers with real STATIC data should pass the actual
# titan.u7.translucency.U7Translucency.xfstart instead of relying on this
# default, since the slot count is technically data-driven.
DEFAULT_XFSTART = 238


@dataclass(frozen=True)
class FrameCycleReport:
    """Per-frame pixel classification for one shape frame."""

    frame_index: int
    is_tile: bool
    cycle_indices: FrozenSet[int]
    translucent_indices: FrozenSet[int]
    has_index_255: bool

    @property
    def has_cycle(self) -> bool:
        return bool(self.cycle_indices)

    @property
    def has_translucency(self) -> bool:
        return bool(self.translucent_indices)

    @property
    def index_255_is_transparent(self) -> bool:
        """Whether this frame's index-255 pixels (if any) mean
        transparent. Only meaningful when :attr:`has_index_255` is True:
        RLE sprite frames (``is_tile=False``) treat 255 as transparent;
        flat tile frames never do."""
        return not self.is_tile


@dataclass
class ShapeCycleReport:
    """Whole-shape colour-cycle / translucency / frame-animation
    classification, scanned across every frame."""

    shape_num: int
    frame_count: int
    is_translucent: bool
    is_animated: bool
    anim_type: int
    anim_type_name: str
    resolved_animation: Optional[AnimationInfo] = None
    name: str = ""
    frames: List[FrameCycleReport] = field(default_factory=list)

    @property
    def has_frame_animation(self) -> bool:
        """Whether Exult will actually run frame-sequence animation on
        this shape. Equivalent to ``resolved_animation is not None``,
        which is itself gated on the TFA ``is_animated`` flag, *not*
        merely ``anim_type != -1`` -- a handful of shapes carry a
        leftover nonzero animation nibble despite ``is_animated`` being
        false, and Exult's ``Frame_animator`` bails out immediately for
        those (``objs/animate.cc:273``), never consulting the nibble at
        all."""
        return self.resolved_animation is not None

    @property
    def is_tile_shape(self) -> bool:
        """Whether this shape's frames are flat ground tiles rather than
        RLE sprites (uniform across all of a shape's frames -- U7Shape
        parses a whole record as one or the other, never mixed)."""
        return bool(self.frames) and self.frames[0].is_tile

    @property
    def cycle_frame_indices(self) -> List[int]:
        return [f.frame_index for f in self.frames if f.has_cycle]

    @property
    def translucent_frame_indices(self) -> List[int]:
        return [f.frame_index for f in self.frames if f.has_translucency]

    @property
    def index_255_frame_indices(self) -> List[int]:
        return [f.frame_index for f in self.frames if f.has_index_255]

    @property
    def has_any_cycle(self) -> bool:
        return any(f.has_cycle for f in self.frames)

    @property
    def has_any_translucency(self) -> bool:
        return any(f.has_translucency for f in self.frames)

    @property
    def all_cycle_indices(self) -> FrozenSet[int]:
        return frozenset().union(*(f.cycle_indices for f in self.frames)) if self.frames else frozenset()

    @property
    def all_translucent_indices(self) -> FrozenSet[int]:
        return frozenset().union(*(f.translucent_indices for f in self.frames)) if self.frames else frozenset()

    @property
    def is_affected(self) -> bool:
        """Whether this shape has any animation-relevant content at all:
        TFA frame-sequencing, ordinary colour cycling, or translucency
        compositing."""
        return self.has_frame_animation or self.has_any_cycle or self.has_any_translucency


def scan_frame(
    pixels: np.ndarray,
    frame_index: int,
    *,
    is_translucent: bool,
    is_tile: bool = False,
    xfstart: int = DEFAULT_XFSTART,
) -> FrameCycleReport:
    """Classify one frame's pixel indices into ordinary colour-cycle vs
    translucency-blend, depending on whether the owning shape is
    TFA-translucent.

    Indices below *xfstart* are always ordinary cycle pixels (they're
    outside the translucency window entirely, e.g. the "magic" and most
    of the "fire" ranges). Indices from *xfstart* through 254 are cycle
    pixels on a non-translucent shape, or translucency-blend pixels on
    one flagged translucent -- never both for the same shape.

    *is_tile* records whether this is a flat ground-tile frame or an RLE
    sprite frame, since that determines whether a present index-255 pixel
    means transparent (see :attr:`FrameCycleReport.index_255_is_transparent`).
    """
    present = {int(v) for v in np.unique(pixels) if _CYCLE_FLOOR <= v <= _CYCLE_CEILING}
    has_255 = bool(np.any(pixels == _TRANSPARENT_INDEX))

    if is_translucent:
        cycle = {v for v in present if v < xfstart}
        translucent = {v for v in present if v >= xfstart}
    else:
        cycle = present
        translucent = set()

    return FrameCycleReport(frame_index, is_tile, frozenset(cycle), frozenset(translucent), has_255)


def scan_shape(
    shape: "U7Shape",
    shape_num: int,
    tfa: "U7TypeFlags",
    *,
    xfstart: int = DEFAULT_XFSTART,
    name: str = "",
) -> ShapeCycleReport:
    """Scan every frame of *shape* and classify its colour-cycle /
    translucency / frame-animation content."""
    entry = tfa.get(shape_num)
    is_translucent = bool(entry and entry.has_translucency)
    is_animated = bool(entry and entry.is_animated)
    anim_type = entry.anim_type if entry is not None else -1
    anim_type_name = entry.anim_type_name if entry is not None else ""

    resolved_animation = (
        default_animation_for_tfa(anim_type, len(shape.frames)) if is_animated else None
    )

    frame_reports = [
        scan_frame(
            frame.pixels, i,
            is_translucent=is_translucent, is_tile=frame.is_tile, xfstart=xfstart,
        )
        for i, frame in enumerate(shape.frames)
        if frame.pixels is not None
    ]

    return ShapeCycleReport(
        shape_num=shape_num,
        frame_count=len(shape.frames),
        is_translucent=is_translucent,
        is_animated=is_animated,
        anim_type=anim_type,
        anim_type_name=anim_type_name,
        resolved_animation=resolved_animation,
        name=name,
        frames=frame_reports,
    )
