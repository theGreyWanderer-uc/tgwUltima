"""
Convert Ultima 8 shapes into Ultima 7 (Exult)-compatible shapes.

For a fan "de-make" of U8 static/scenery art into the U7/Exult engine.
Both engines' pre-rendered sprite formats turned out to share more than
expected once actually researched against the Pentagram and Exult
source (see each project's docs, not reproduced in depth here):

- Both use the same 2:1 pixel-art dimetric family and 8-direction
  facing convention, not an incompatible "true 3D" camera on U8's
  side -- U8 shapes are still flat, pre-rendered, palette-indexed RLE
  sprites at a fixed angle, just higher-detail. Confirmed visually: a
  real U8 shape (a small statue, a chest, a support post) already
  reads in the same "box with a top face and a receding side face"
  isometric style as real U7 examples of similar objects.
- U8's stored hotspot sits at the bottom-*center* of a shape's tile
  footprint (Pentagram's ``ItemSorter``, confirmed for square
  footprints); U7's sits at the bottom-*right* (south-east) corner
  (Exult's ``Game_object::get_footprint``). This module only needs to
  shift where the recorded origin pixel is, not redraw anything.

Given that, this module treats U8->U7 conversion as **resize + palette
requantize + hotspot-convention shift**, not a geometric
reprojection/shear -- there is no record of Origin's original 3D
authoring camera in either reimplementation's source, so there is no
ground truth to re-derive a "corrected" perspective from anyway.

Scope (deliberate): static/scenery shapes with a handful of frames
(furniture, items, decor) -- not actor/NPC animation sets, which store
directional/pose frame tables (e.g. U8's Avatar shape alone has 1200
frames across 64 actions x 8 directions) that are a distinct problem
(frame-semantics mapping, not just per-frame resizing).

Sizing is footprint-calibrated: :func:`build_footprint_size_table`
scans a real U7 STATIC directory's own ``SHAPES.VGA`` + ``TFA.DAT`` to
build an empirical (tile footprint -> real pixel size) table, so a
converted shape's target size matches what real U7 objects of the same
footprint actually look like, rather than a guessed formula. That
calibrated size is used only to derive one *uniform* scale factor (by
matching pixel area, see :func:`convert_shape`), not applied as a
forced width/height -- real testing against actual U8 game data showed
footprint alone is a poor predictor of a specific shape's aspect ratio
(e.g. a thin support post and a squat chest can share a tile
footprint), and forcing every shape at a footprint into an identical
box distorted the ones that didn't match the "typical" silhouette.

**Known limitation, confirmed on real data, not just theorized**: when
a shape's calibrated target size is already close to its native U8
size (little actual downscaling happens), the output can look muddy/
speckled rather than clean -- confirmed on a real U8 support-post prop
(shape 88, footprint 1x1x4 tiles, native 16x40px, converted to
17x43px, i.e. essentially unscaled): its original wood-grain texture
has fine per-pixel color variation that real hand-painted U7 art
doesn't, and requantizing that much per-pixel detail against a fixed
256-color palette produces visible speckle instead of the flat shaded
regions typical U7 sprites use. Two shapes with more actual
downscaling (a statue and a chest, converted from roughly 34x57 and
38x31 down to 24x40 and 32x26) came out visually clean by contrast.
Fixing this properly would need real posterization/edge simplification,
not just resizing -- out of scope for this pass.

**Known limitation: multi-orientation objects don't have a reliable
"same compass direction" mapping between the two engines, and this is
NOT fixable by a per-pixel transform** -- confirmed mathematically and
then confirmed *wrong as a pixel-level fix* empirically, both against
real data. The two engines' world-to-screen projections, while sharing
the same 2:1 dimetric scale (see above), disagree on camera azimuth:
solving each engine's own confirmed projection formula (see
:mod:`titan.u8.map`'s ``PROJECTIONS["iso_classic"]`` for U8; Exult's
``Get_shape_location`` for U7) for the screen vector of one compass
tile-step gives U7 "East" = pure horizontal screen motion and U8
"East" = diagonal (the same 2:1 slope as a box's top-face edge). The
matrix relating the two is exactly a 45-degree rotation plus a 2:1
anisotropic scale (not an approximation -- solving for it from each
engine's East/North screen vectors lands on precisely those numbers).
That correctly describes how *object positions* relate between the
two coordinate grids -- it does **not** mean a rendered sprite can be
correctly re-angled by applying that same matrix as a pixel transform.
Verified two ways, both against real data: visually, real U8 shapes
(203/204, a chest of drawers; 205/208, a desk) checked side by side
against real BG `u7examples` art show the same East/West axis drawn
horizontal in U7's art and diagonal in U8's; and directly, applying the
derived rotate+anisotropic-scale transform to an actual rendered U8
sprite (tested, not just reasoned about) produces a garbled,
broken-looking result, not a correctly-reangled object -- because a
rendered sprite is already a flat composite of a 3D box's top/front/
side faces baked in at one specific camera angle; warping those pixels
doesn't re-derive which faces a genuinely different camera azimuth
would show or how they'd occlude each other, it just distorts the
existing baked-in perspective. A correct fix would need the original
3D geometry re-rendered from the other angle, which doesn't exist in
the extracted 2D shape data.
Consequence: this converter makes no attempt to align a U8 shape's
"facing" with U7's compass convention -- when placing converted
multi-orientation objects (anything with more than one shape number
for different facings, like a desk or dresser), visually verify which
converted shape actually reads as facing the direction you want,
rather than assuming U8's own direction labeling (if any) carries over.

Example::

    from titan.u7.flex import U7FlexArchive
    from titan.u7.palette import U7Palette
    from titan.u7.typeflag import U7TypeFlags
    from titan.u8.shape import U8Shape
    from titan.u8.typeflag import U8TypeFlags
    from titan.u8.u7_shape_convert import build_footprint_size_table, convert_shape

    u7_shapes = U7FlexArchive.from_file("STATIC/SHAPES.VGA")
    u7_tfa = U7TypeFlags.from_dir("STATIC/")
    size_table = build_footprint_size_table(u7_tfa, u7_shapes)

    u8_tfa = U8TypeFlags.from_file("STATIC/TYPEFLAG.DAT")
    entry = u8_tfa[shape_num]
    u8_shape = U8Shape.from_file("0088.shp")

    u7_shape = convert_shape(
        u8_shape, (entry.x, entry.y, entry.z), u8_palette, u7_palette, size_table,
    )
    u7_shape.save("converted.shp")
"""

from __future__ import annotations

__all__ = ["build_footprint_size_table", "pick_target_size", "convert_frame", "convert_shape", "MAX_OUTPUT_DIM"]

import statistics
from typing import Optional

import numpy as np
from PIL import Image

from titan.u7.shape import U7Shape
from titan.u7.typeflag import U7TypeFlags
from titan.u8.shape import U8Shape

Footprint = tuple[int, int, int]

# Sanity bound on tile footprint -- matches both engines' packed field
# widths (U7: 3-bit x/y-1 fields => 1-8; U8: 4-bit nibbles => 0-15, but
# real furniture/items rarely exceed U7's own 1-8 range in practice).
_MAX_FOOTPRINT_TILE = 8

# Practical U7 shape-frame pixel ceiling (user-stated convention, not a
# hard format limit -- see this module's docstring). Also doubles as a
# safety net against pathological scale factors; see convert_frame.
MAX_OUTPUT_DIM = 64


def build_footprint_size_table(
    u7_typeflags: U7TypeFlags, u7_shapes: "U7FlexArchive"  # noqa: F821 -- see titan.u7.flex
) -> dict[Footprint, list[tuple[int, int]]]:
    """Empirical ``(dims_x, dims_y, dims_z) -> [(pixel_w, pixel_h), ...]`` table.

    Built from every real, non-tile U7 shape (``shape_num >=
    U7TypeFlags.FIRST_OBJ_SHAPE``) that has both TFA dimensions and at
    least one non-empty decoded frame. Multiple samples per footprint
    are kept (not pre-averaged) so :func:`pick_target_size` can use
    whatever statistic makes sense.
    """
    table: dict[Footprint, list[tuple[int, int]]] = {}

    for shape_num in range(U7TypeFlags.FIRST_OBJ_SHAPE, len(u7_shapes.records)):
        entry = u7_typeflags.get(shape_num)
        if entry is None:
            continue
        data = u7_shapes.get_record(shape_num)
        if not data:
            continue

        shape = U7Shape.from_data(data)
        key = (entry.dims_x, entry.dims_y, entry.dims_z)
        for frame in shape.frames:
            if frame.pixels is None or frame.width <= 0 or frame.height <= 0:
                continue
            table.setdefault(key, []).append((frame.width, frame.height))

    return table


def pick_target_size(
    table: dict[Footprint, list[tuple[int, int]]], footprint: Footprint
) -> tuple[int, int]:
    """Representative (median) real U7 pixel size for a tile footprint.

    Falls back, in order: exact ``(x,y,z)`` match -> nearest ``z`` at
    the same ``(x,y)`` -> nearest footprint overall by simple tile-count
    distance -> a global average-pixels-per-tile formula if the table
    is empty (shouldn't happen against real game data, but keeps this
    function total).
    """
    x, y, z = footprint
    x = max(1, min(_MAX_FOOTPRINT_TILE, x))
    y = max(1, min(_MAX_FOOTPRINT_TILE, y))
    z = max(0, min(_MAX_FOOTPRINT_TILE - 1, z))

    if (x, y, z) in table:
        return _median_size(table[(x, y, z)])

    same_xy = {key: samples for key, samples in table.items() if key[0] == x and key[1] == y}
    if same_xy:
        nearest_key = min(same_xy, key=lambda k: abs(k[2] - z))
        return _median_size(same_xy[nearest_key])

    if table:
        nearest_key = min(table, key=lambda k: abs(k[0] - x) + abs(k[1] - y) + abs(k[2] - z))
        return _median_size(table[nearest_key])

    # No real data at all (empty table) -- last-resort generic formula.
    return (max(8, x * 24), max(8, y * 16 + z * 6))


def _median_size(samples: list[tuple[int, int]]) -> tuple[int, int]:
    widths = sorted(w for w, _ in samples)
    heights = sorted(h for _, h in samples)
    return (
        int(statistics.median(widths)),
        int(statistics.median(heights)),
    )


def _quantize_to_palette(rgba_img: Image.Image, palette) -> np.ndarray:
    """Nearest-RGB quantize an RGBA image against any ``palette.colors``.

    Same approach as :meth:`titan.u8.shape.U8Shape.quantize_to_palette`,
    generalized to work with either :class:`titan.palette.U8Palette` or
    :class:`titan.u7.palette.U7Palette` (both expose ``.colors``, a
    256-entry list of RGB tuples).
    """
    arr = np.asarray(rgba_img)
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int32)
    alpha = arr[:, :, 3]

    pal_arr = np.array(palette.colors, dtype=np.int32)
    diff = rgb.reshape(-1, 1, 3) - pal_arr.reshape(1, 256, 3)
    dist_sq = (diff * diff).sum(axis=2)
    nearest = dist_sq.argmin(axis=1).astype(np.uint8)
    result = nearest.reshape(h, w)
    result[alpha < 128] = 0xFF
    return result


def convert_frame(
    u8_frame: "U8Shape.Frame", scale: float, u8_palette, u7_palette
) -> Optional[U7Shape.Frame]:
    """Uniformly rescale + requantize one U8 frame into a U7-hotspot-convention frame.

    Returns ``None`` for an empty/placeholder source frame. *scale* is
    applied equally to width and height -- deliberately, so a frame
    keeps its own natural aspect ratio (a tall thin post stays tall and
    thin) rather than being force-fit into some other object's typical
    box at the same tile footprint, which real testing against actual
    U8 game data showed distorts non-representative shapes badly (see
    :func:`convert_shape` for how *scale* is derived). The output
    hotspot is placed at the bottom-right (south-east) corner of the
    resized frame -- U7's convention (see this module's docstring) --
    regardless of where U8's own hotspot was, since the resize already
    recenters the art within its new bounding box.

    Output width/height are clamped to :data:`MAX_OUTPUT_DIM` (64px,
    the user-stated practical ceiling for a real U7 shape -- also a
    real safety net: a real U8 shape (580, an animated growth/VFX
    effect) was found during testing whose frames range from 1x1 up to
    119x62 within the *same* shape; without this clamp a large
    *scale* computed from one frame can blow up a much bigger sibling
    frame to a huge size, which both looks wrong for U7 and can exhaust
    memory during palette requantization).
    """
    if u8_frame.pixels is None or u8_frame.width <= 0 or u8_frame.height <= 0:
        return None

    target_w = max(1, min(MAX_OUTPUT_DIM, round(u8_frame.width * scale)))
    target_h = max(1, min(MAX_OUTPUT_DIM, round(u8_frame.height * scale)))

    tmp = U8Shape()
    tmp.frames = [u8_frame]
    rgba = tmp.to_pngs(u8_palette, transparent=True)[0]
    resized = rgba.resize((target_w, target_h), Image.LANCZOS)

    pixels = _quantize_to_palette(resized, u7_palette)

    frame = U7Shape.Frame()
    frame.width = target_w
    frame.height = target_h
    frame.xoff = target_w - 1  # xleft: hotspot 1px in from the right edge
    frame.yoff = target_h - 1  # yabove: hotspot 1px in from the bottom edge
    frame.pixels = pixels
    frame.is_tile = False
    return frame


def convert_shape(
    u8_shape: U8Shape,
    footprint: Footprint,
    u8_palette,
    u7_palette,
    size_table: dict[Footprint, list[tuple[int, int]]],
) -> U7Shape:
    """Convert every non-empty frame of a U8 shape into a new :class:`U7Shape`.

    The target size from :func:`pick_target_size` (calibrated against
    real U7 objects of the same tile footprint) is used only to derive
    one uniform *scale factor* -- via matching pixel *area*, not a
    forced width/height -- applied to every frame, using the *largest*
    non-empty frame as the reference size. This keeps each frame's own
    aspect ratio intact instead of stretching every shape at a given
    footprint into an identical box (real U8 data showed footprint
    alone is a poor predictor of a specific shape's silhouette
    proportions -- e.g. a thin support post and a squat chest can share
    a tile footprint).

    Deliberately *not* the first non-empty frame: a real U8 shape (580,
    an animated growth/VFX effect) was found whose frame sizes range
    from 1x1 up to 119x62 within the same shape -- using its 1x1 first
    frame as the reference produced a huge scale factor that then
    blew up every other frame too. The largest frame is a much more
    representative "full size" for the shape as a whole.
    """
    non_empty = [f for f in u8_shape.frames if f.pixels is not None and f.width > 0 and f.height > 0]
    if not non_empty:
        return U7Shape()
    reference = max(non_empty, key=lambda f: f.width * f.height)

    target_w, target_h = pick_target_size(size_table, footprint)
    source_area = reference.width * reference.height
    target_area = target_w * target_h
    scale = (target_area / source_area) ** 0.5 if source_area > 0 else 1.0

    u7_shape = U7Shape()
    for u8_frame in u8_shape.frames:
        frame = convert_frame(u8_frame, scale, u8_palette, u7_palette)
        if frame is not None:
            u7_shape.frames.append(frame)
    return u7_shape
