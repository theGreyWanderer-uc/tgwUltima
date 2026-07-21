"""
Ultima 7 shape frame-sequence animation.

Ports Exult's default (no ``shape_info.txt`` override) frame-animation
behavior so Titan can reproduce which frame a shape shows at a given
point in time -- distinct from palette colour-cycling
(:mod:`titan.u7.palette_cycle`), which animates colours on a single fixed
frame instead of switching between frames.

Sourced from Exult (``D:/_Repos/exult``):

* ``shapes/shapeinf/aniinf.h`` -- the ``Animation_info::AniType`` enum.
* ``shapes/shapeinf/aniinf.cc:66-116`` (``create_from_tfa``) -- the default
  animation parameters Exult derives from a shape's raw TFA animation
  nibble (0-15) when no ``shape_info.txt`` override exists.  Nibble values
  2, 3, 4, and 7 are not handled by Exult itself (its own source comment:
  "None of these are used for any animated shape") -- this module mirrors
  that faithfully rather than inventing behaviour for them.
* ``objs/animate.cc:370-426`` (``Frame_animator::get_next_frame``) -- the
  per-type frame-selection formulas.
* ``objs/animate.cc:432-441`` (``Frame_animator::handle_event``) -- confirms
  the real engine calls ``get_next_frame`` once every
  ``100 * frame_delay`` milliseconds; that's the tick unit used throughout
  this module.

Two of the five types are only approximated for a deterministic preview,
since the real engine is non-deterministic there -- both are called out
explicitly in :func:`simulate_frame_sequence`.
"""

from __future__ import annotations

__all__ = [
    "AniType",
    "AnimationInfo",
    "default_animation_for_tfa",
    "simulate_frame_sequence",
    "has_cycle_pixels",
    "save_gif",
    "TICK_MS",
]

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Optional, Sequence

import numpy as np

from titan.u7.palette_semantics import CYCLE_RANGES

if TYPE_CHECKING:
    from PIL import Image

# Exult's Frame_animator fires once every `100 * frame_delay` ms
# (objs/animate.cc:436-440).
TICK_MS = 100


class AniType(IntEnum):
    """Exult's ``Animation_info::AniType`` (aniinf.h:40-45)."""

    TIMESYNCHED = 0     # Frame based on elapsed real time.
    HOURLY = 1          # Frame based on the current in-game hour.
    NON_LOOPING = 2     # Advances once per tick, stops at the last frame.
    LOOPING = 3         # Generic loop, with optional freeze/recycle.
    RANDOM_FRAMES = 4   # Frame chosen at random each tick.


@dataclass(frozen=True)
class AnimationInfo:
    """Mirrors Exult's ``Animation_info`` (aniinf.h)."""

    ani_type: AniType
    nframes: int
    recycle: int = 0
    freeze_first_chance: int = 100
    frame_delay: int = 1
    sfx_delay: int = 0


def default_animation_for_tfa(tfa_type: int, nframes: int) -> Optional[AnimationInfo]:
    """Port of Exult's ``Animation_info::create_from_tfa``
    (``aniinf.cc:66-116``): the default animation parameters for a raw TFA
    animation nibble (0-15) when no ``shape_info.txt`` override exists.

    Returns ``None`` for nibble values Exult itself doesn't animate
    (2, 3, 4, 7, and anything outside 0-15) -- not a Titan limitation.
    """
    if tfa_type in (0, 1):
        return AnimationInfo(AniType.TIMESYNCHED, nframes)
    if tfa_type == 5:
        return AnimationInfo(AniType.LOOPING, nframes, recycle=0, freeze_first_chance=20, frame_delay=1)
    if tfa_type == 6:
        return AnimationInfo(AniType.RANDOM_FRAMES, nframes)
    if tfa_type == 8:
        return AnimationInfo(AniType.HOURLY, nframes)
    if tfa_type == 9:
        return AnimationInfo(AniType.LOOPING, nframes, recycle=0, freeze_first_chance=8)
    if tfa_type == 10:
        return AnimationInfo(AniType.LOOPING, nframes, recycle=0, freeze_first_chance=6)
    if tfa_type == 11:
        return AnimationInfo(AniType.LOOPING, nframes, recycle=nframes - 1, freeze_first_chance=0)
    if tfa_type in (12, 14):
        return AnimationInfo(AniType.TIMESYNCHED, nframes, frame_delay=4)
    if tfa_type == 13:
        return AnimationInfo(AniType.NON_LOOPING, nframes)
    if tfa_type == 15:
        return AnimationInfo(AniType.TIMESYNCHED, min(6, nframes), frame_delay=4)
    return None


def simulate_frame_sequence(
    anim: AnimationInfo,
    first_frame: int,
    num_steps: int,
    *,
    hour_start: int = 0,
    always_advance: bool = True,
) -> list[int]:
    """Simulate *num_steps* engine ticks and return the resulting sequence
    of absolute frame indices, one per tick.  Each tick is
    ``TICK_MS * anim.frame_delay`` real milliseconds apart (except
    ``HOURLY``, which advances by one in-game hour per tick regardless of
    ``frame_delay`` -- see the class docstring).

    ``TIMESYNCHED``, ``HOURLY``, and ``NON_LOOPING`` are exact ports.
    ``LOOPING``'s partial "freeze chance" (0 < chance < 100) is a real
    per-tick random gate in Exult; with the default ``always_advance=True``
    this renders the full cycle deterministically instead of mostly
    sitting on the first frame. ``RANDOM_FRAMES`` is genuinely
    non-deterministic in Exult (``rand() % nframes`` every tick); this
    renders a deterministic sequential cycle instead, since a faithful
    random reproduction isn't meaningful for a static export.
    """
    nframes = anim.nframes
    if nframes <= 1:
        return [first_frame] * num_steps

    currpos = 0
    frames: list[int] = []
    for step in range(num_steps):
        if anim.ani_type == AniType.HOURLY:
            currpos = (hour_start + step) % nframes
        elif anim.ani_type == AniType.NON_LOOPING:
            currpos = min(step, nframes - 1)
        elif anim.ani_type == AniType.RANDOM_FRAMES:
            currpos = step % nframes
        elif anim.ani_type == AniType.LOOPING:
            chance = anim.freeze_first_chance
            advances = currpos != 0 or chance == 100 or (always_advance and chance > 0)
            if advances:
                currpos = (currpos + 1) % nframes
                if currpos == 0 and nframes >= anim.recycle:
                    currpos = (nframes - anim.recycle) % nframes
        else:  # TIMESYNCHED
            currpos = step % nframes
        frames.append(first_frame + currpos)

    return frames


def has_cycle_pixels(pixels: np.ndarray) -> bool:
    """Whether *pixels* (a decoded frame's index array) contains any of
    Exult's six palette-cycling indices (224-254) -- i.e. this frame
    animates via colour cycling rather than (or in addition to) frame
    switching, even though it's a single static frame."""
    for rng in CYCLE_RANGES:
        if np.any((pixels >= rng.start) & (pixels <= rng.end)):
            return True
    return False


def save_gif(frames: Sequence["Image.Image"], path: str, *, duration_ms: int, loop: int = 0) -> None:
    """Save a sequence of rendered frames as an animated GIF.

    U7 renders never exceed 256 colours, so GIF's palette is a natural
    fit here -- unlike a general RGBA source, nothing needs
    requantizing. GIF transparency is binary (no partial alpha), which
    matches how Exult itself displays these frames (palette-swap based,
    not alpha-blended) closely enough for a preview/export tool.
    """
    if not frames:
        raise ValueError("save_gif requires at least one frame")

    first, *rest = [f.convert("RGBA") for f in frames]
    first.save(
        path,
        save_all=True,
        append_images=rest,
        duration=duration_ms,
        loop=loop,
        disposal=2,
    )
