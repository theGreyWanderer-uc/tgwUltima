"""Shared placement and material rules for specially handled UU2 objects.

Most UU2 objects take their texture from one fixed rule per item. A handful
select it from the placed instance instead — a bridge can be surfaced with a
level architectural texture, a lever shows one of eight positions, a special
wall borrows a wall-mapping entry. Those rules previously existed as two partial
and divergent copies, one in :mod:`titan.uw2.model_render` covering six ordinary
items and one in :mod:`titan.uw2.map_render` covering the wall-mounted classes.

This module is the single source for both, so the 2.5D cutaway, the standalone
model tools, and the 3D scene builder cannot drift apart.

Rules are transcribed from the UnderworldGodot reference implementation and
checked against every object instance in the shipped levels; see
``reference/uw2/uw2-3d-model-work-plan.md`` for the per-rule evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TMOBJ = "tmobj"
"""Object texture archive, ``TMOBJ.GR``."""

TMFLAT = "tmflat"
"""Flat wall-control texture archive, ``TMFLAT.GR``."""

TERRAIN = "terrain"
"""A level texture-mapping entry, resolved through the level to ``T64.TR``."""

WALL_ROLE = "wall"
FLOOR_ROLE = "floor"

BRIDGE_ITEM = 0x0164
WRITING_ITEM = 0x0166
LEVER_ITEM = 0x0161
SWITCH_ITEM = 0x0162
BED_ITEM = 0x0167
THIN_WALL_ITEM = 0x016E
REMOVABLE_WALL_ITEM = 0x016F
CONTROL_FIRST = 0x0170
CONTROL_LAST = 0x017F

BRIDGE_TMOBJ_BASE = 30
"""Bridges with ``flags`` below 2 use ``TMOBJ.GR[30 + flags]``."""

BRIDGE_MAPPED_MINIMUM = 2
"""From ``flags`` 2 upwards a bridge uses floor mapping entry ``flags - 2``."""

ROTARY_TMOBJ_BASE = 4
"""Lever images start at 4; the switch's eight follow at 12."""

WRITING_TMOBJ_BASE = 20

WRITING_STRING_BLOCK = 8
"""Sign prefixes and message text both live in ``STRINGS.PAK`` block 8."""

WRITING_PREFIX_BASE = 368
"""Prefix strings 368-375: plaque, ancient rune, then sign."""

WRITING_MESSAGE_BIAS = 0x200
"""A writing's message index is ``quantity_or_link - 0x200``."""

DOOR_FIRST = 0x0140
DOOR_LAST = 0x014F

DOOR_FRAME_MODEL = 0x01
"""The doorway surround; its roof vertices stretch to the tile ceiling."""

DOOR_PANEL_MODEL = 0x0E
SECRET_DOOR_PANEL_MODEL = 0x0F

DOOR_OPEN_CLASS = 8
"""Class indices from 8 up are the already-open forms."""

PORTCULLIS_CLASSES = (6, 0x0E)
SECRET_DOOR_CLASSES = (7, 0x0F)

DOOR_TEXTURE_SLOTS = 6
"""A level stores six door textures; the portcullis and secret door use neither."""

PORTCULLIS_ANIMATION_FRAMES = 4
DOOR_ANIMATION_FRAMES = 5
PORTCULLIS_FULL_LIFT = 0.8
"""A fully raised portcullis clears the doorway by this many tile units."""

DOORS = "doors"
"""``DOORS.GR``, indexed through the level's six door-texture slots."""

SPECIAL_MODEL_INDEX: dict[int, int] = {
    LEVER_ITEM: 0x10,
    SWITCH_ITEM: 0x11,
    WRITING_ITEM: 0x12,
    THIN_WALL_ITEM: 0x14,
    REMOVABLE_WALL_ITEM: 0x16,
    BRIDGE_ITEM: 0x02,
    **{item: 0x10 for item in range(CONTROL_FIRST, CONTROL_LAST + 1)},
}
"""Executable model slots for classes the ordinary item table does not map.

Slots ``0x10``, ``0x11``, ``0x12`` and ``0x14`` share one offset in ``UW2.EXE``
and decode to the same 0.25x0.25 textured quad, so these classes differ only in
which texture they select. ``0x16`` is the full-tile variant.
"""

WALL_MOUNTED_ITEMS = frozenset(
    {LEVER_ITEM, SWITCH_ITEM, WRITING_ITEM, THIN_WALL_ITEM, REMOVABLE_WALL_ITEM}
    | set(range(CONTROL_FIRST, CONTROL_LAST + 1))
)
"""Classes placed against a wall face rather than standing on the floor."""


@dataclass(frozen=True)
class MaterialRef:
    """Which archive supplies a placed object's texture, and at which index.

    For :data:`TERRAIN` the index is a *texture-mapping entry*, not a ``T64.TR``
    id; call :func:`terrain_texture_id` with the level to resolve it.
    """

    source: str
    index: int
    role: str | None = None

    @property
    def is_terrain(self) -> bool:
        return self.source == TERRAIN


def object_material(
    item_id: int,
    flags: int = 0,
    owner: int = 0,
    tile: dict | None = None,
) -> MaterialRef | None:
    """Resolve the texture a placed object selects, or ``None`` for none.

    ``tile`` is only consulted by classes that borrow their tile's own wall
    texture, currently the secret door.
    """
    flags = int(flags)
    low = flags & 0x07

    if is_door(item_id):
        if is_secret_door(item_id):
            # A secret door wears the wall it hides in.
            if tile is None:
                return None
            return MaterialRef(TERRAIN, int(tile["wall_texture_index"]), WALL_ROLE)
        slot = door_texture_slot(item_id)
        return None if slot is None else MaterialRef(DOORS, slot)

    if item_id == 0x0158:
        return MaterialRef(TMOBJ, 32)
    if item_id == 0x015C:
        return MaterialRef(TMOBJ, 38)
    if item_id == 0x0160:
        return MaterialRef(TMOBJ, flags & 0xFF)
    if item_id == 0x0163:
        return MaterialRef(TMOBJ, 42 + (flags & 0xFF))
    if item_id == 0x0165:
        return MaterialRef(TMOBJ, 28 + (flags & 0xFF))
    if item_id == 0x0169:
        return MaterialRef(TMOBJ, 36 + (flags & 0xFF))

    if item_id in (LEVER_ITEM, SWITCH_ITEM):
        # Eight sprites per item; the position is a texture change, not a
        # rotation. Lever takes 4-11 and switch 12-19.
        return MaterialRef(TMOBJ, ROTARY_TMOBJ_BASE + (item_id - LEVER_ITEM) * 8 + low)
    if item_id == WRITING_ITEM:
        return MaterialRef(TMOBJ, WRITING_TMOBJ_BASE + low)
    if CONTROL_FIRST <= item_id <= CONTROL_LAST:
        return MaterialRef(TMFLAT, item_id & 0x0F)

    if item_id == BRIDGE_ITEM:
        if flags < BRIDGE_MAPPED_MINIMUM:
            return MaterialRef(TMOBJ, BRIDGE_TMOBJ_BASE + flags)
        # Architectural bridges borrow a level floor texture.
        return MaterialRef(TERRAIN, flags - BRIDGE_MAPPED_MINIMUM, FLOOR_ROLE)
    if item_id in (THIN_WALL_ITEM, REMOVABLE_WALL_ITEM):
        return MaterialRef(TERRAIN, int(owner), WALL_ROLE)

    return None


def object_material_for(obj: dict, tile: dict | None = None) -> MaterialRef | None:
    """Resolve :func:`object_material` straight from a decoded object record."""
    return object_material(
        int(obj.get("item_id", 0)),
        int(obj.get("flags", 0)),
        int(obj.get("owner", 0)),
        tile,
    )


def terrain_texture_id(ref: MaterialRef, level: dict) -> int | None:
    """Resolve a :data:`TERRAIN` reference through the level texture mapping."""
    if not ref.is_terrain:
        return None
    entries = level.get("texture_mapping", {}).get("entries", [])
    if not 0 <= ref.index < len(entries):
        return None
    return int(entries[ref.index])


def is_door(item_id: int) -> bool:
    return DOOR_FIRST <= item_id <= DOOR_LAST


def door_class(item_id: int) -> int:
    """Low nibble of a door's item ID, which carries kind and open state."""
    return item_id & 0x0F


def is_open_door(item_id: int) -> bool:
    return door_class(item_id) >= DOOR_OPEN_CLASS


def is_portcullis(item_id: int) -> bool:
    return door_class(item_id) in PORTCULLIS_CLASSES


def is_secret_door(item_id: int) -> bool:
    return door_class(item_id) in SECRET_DOOR_CLASSES


def door_panel_model(item_id: int) -> int:
    return SECRET_DOOR_PANEL_MODEL if is_secret_door(item_id) else DOOR_PANEL_MODEL


def door_animation_frames(item_id: int) -> int:
    """Steps between fully closed and fully open."""
    return (
        PORTCULLIS_ANIMATION_FRAMES if is_portcullis(item_id) else DOOR_ANIMATION_FRAMES
    )


def door_animation_index(item_id: int, flags: int) -> int:
    """Which animation step a placed door sits at.

    The open forms are fully open by definition. For the closed forms ``flags``
    is the step, and every closed door in the shipped levels carries `0`. The
    open forms carry values well past the step count - 13 and 12 against counts
    of 5 and 4 - so their state comes from the item ID, not from a step that
    cannot be one.
    """
    frames = door_animation_frames(item_id)
    if is_open_door(item_id):
        return frames
    return int(flags) if 0 <= int(flags) <= frames else 0


def door_swing_radians(item_id: int, flags: int, doordir: int) -> float:
    """Panel rotation about its hinge; zero for a closed door or portcullis."""
    if is_portcullis(item_id):
        return 0.0
    frames = door_animation_frames(item_id)
    step = (math.pi / 2.0) / frames
    direction = -1.0 if int(doordir) == 1 else 1.0
    return direction * door_animation_index(item_id, flags) * step


def door_lift(item_id: int, flags: int) -> float:
    """Vertical rise for a portcullis; zero for a hinged door."""
    if not is_portcullis(item_id):
        return 0.0
    frames = door_animation_frames(item_id)
    return door_animation_index(item_id, flags) * (PORTCULLIS_FULL_LIFT / frames)


PORTCULLIS_VERTICAL_BARS = (0.218, 0.532, 0.846)
"""Vertical bar centres, as fractions of the doorway's width."""

PORTCULLIS_CROSS_BARS = (0.82, 0.62, 0.42, 0.22)
"""Cross bar centres, as fractions of the doorway's height."""

PORTCULLIS_BAR_WIDTH = 0.064
"""Vertical bar thickness, as a fraction of the doorway's width."""

PORTCULLIS_BAR_HEIGHT = 0.05
"""Cross bar thickness, as a fraction of the doorway's height."""


def portcullis_bar_model(panel):
    """A portcullis grid built to fill the door panel's own bounding box.

    **This geometry is reconstructed, not decoded.** ``UW2.EXE`` has no
    portcullis model: slot ``0x0E`` decodes to an eight-vertex solid box, the
    ordinary door panel, and the engine draws a portcullis as bars by other
    means. Rendering the solid panel instead gives a slab across the doorway,
    which is plainly wrong, so the bars are rebuilt here in the proportions
    UnderworldGodot uses - three vertical and four cross - fitted to the panel's
    bounds so the doorway and swing behaviour are unchanged.

    Scene objects built from this carry ``door_geometry`` set to
    ``"reconstructed"`` so an exporter can tell it apart from decoded geometry.
    """
    from titan.uw2.exe_models import ModelTriangle, ModelVertex, UW2Model

    corners = [
        (vertex.x, vertex.y, vertex.z)
        for triangle in panel.triangles
        for vertex in triangle.vertices
    ]
    if not corners:
        return panel
    x0, x1 = min(c[0] for c in corners), max(c[0] for c in corners)
    y0, y1 = min(c[1] for c in corners), max(c[1] for c in corners)
    z0, z1 = min(c[2] for c in corners), max(c[2] for c in corners)
    width, height = x1 - x0, z1 - z0
    palette_index = panel.triangles[0].palette_index

    bars: list[tuple[float, float, float, float]] = []
    half_bar = width * PORTCULLIS_BAR_WIDTH / 2.0
    for centre in PORTCULLIS_VERTICAL_BARS:
        middle = x0 + width * centre
        bars.append((middle - half_bar, middle + half_bar, z0, z1))
    half_cross = height * PORTCULLIS_BAR_HEIGHT / 2.0
    for centre in PORTCULLIS_CROSS_BARS:
        middle = z0 + height * centre
        bars.append((x0, x1, middle - half_cross, middle + half_cross))

    triangles: list = []
    for bar_x0, bar_x1, bar_z0, bar_z1 in bars:
        triangles.extend(
            _box_triangles(
                ModelTriangle,
                ModelVertex,
                (bar_x0, bar_x1),
                (y0, y1),
                (bar_z0, bar_z1),
                palette_index,
            )
        )
    return UW2Model(
        index=panel.index,
        source_offset=panel.source_offset,
        extents=panel.extents,
        triangles=tuple(triangles),
        origin=panel.origin,
        collision_half_extents=panel.collision_half_extents,
    )


def _box_triangles(
    triangle_type,
    vertex_type,
    xs: tuple[float, float],
    ys: tuple[float, float],
    zs: tuple[float, float],
    palette_index: int,
) -> list:
    """Twelve triangles closing one axis-aligned bar."""
    corners = [
        vertex_type(xs[i & 1], ys[(i >> 1) & 1], zs[(i >> 2) & 1]) for i in range(8)
    ]
    faces = (
        (0, 2, 3, 1),
        (4, 5, 7, 6),
        (0, 1, 5, 4),
        (2, 6, 7, 3),
        (0, 4, 6, 2),
        (1, 3, 7, 5),
    )
    triangles = []
    for a, b, c, d in faces:
        for first, second, third in ((a, b, c), (a, c, d)):
            triangles.append(
                triangle_type(
                    (corners[first], corners[second], corners[third]),
                    palette_index=palette_index,
                )
            )
    return triangles


def door_texture_slot(item_id: int) -> int | None:
    """Which of the level's six door textures a door uses, if any.

    The portcullis and the secret door fall outside the six: a secret door
    borrows its tile's wall texture instead, and the portcullis has no slot.
    """
    slot = item_id & 0x07
    return slot if slot < DOOR_TEXTURE_SLOTS else None


def door_texture_id(reference: MaterialRef, level: dict) -> int | None:
    """Resolve a :data:`DOORS` reference through the level's door slots."""
    if reference.source != DOORS:
        return None
    slots = level.get("texture_mapping", {}).get("door_raw", [])
    if not 0 <= reference.index < len(slots):
        return None
    return int(slots[reference.index])


def special_model_index(item_id: int) -> int | None:
    """Executable model slot for a specially handled class, if it has one."""
    return SPECIAL_MODEL_INDEX.get(item_id)


def is_wall_mounted(item_id: int) -> bool:
    return item_id in WALL_MOUNTED_ITEMS


def heading_vector(heading: int) -> tuple[float, float]:
    """Unit XY direction for a UU2 heading, in the clockwise convention.

    Matches :meth:`titan.uw2.exe_models.UW2Model.oriented_position`, which
    rotates by ``-heading * 45`` degrees.
    """
    angle = -(int(heading) & 7) * math.tau / 8.0
    return (math.cos(angle), math.sin(angle))


def wall_mount_offset(heading: int, distance: float) -> tuple[float, float]:
    """Offset along a heading, used to lift a panel clear of its wall face."""
    dx, dy = heading_vector(heading)
    return (dx * distance, dy * distance)


BED_LINEN_PALETTE = 77
"""Bed model ``0x1D`` holds the quilt and the pillow in one colour group.

The model declares four colours - frame 49, mattress 198, an unused 82, and
77 for the bedding. The quilt and pillow share 77 and are told apart by
position instead.
"""

BED_PILLOW_MIN_Y = 0.15
"""Long-axis split between the bed's quilt and its pillow.

The two are spatially disjoint with a clean gap: quilt faces sit at y
-0.167..+0.018 and the pillow's raised box at y +0.243..+0.316.
"""


def bed_face_palette(triangle, owner: int) -> int | None:
    """Owner-derived palette index for one bed face, or ``None`` to leave it.

    Only the bedding is owner-coloured; the frame and mattress keep the
    model's own colours. Confirmed against the game: the quilt takes
    ``4 * owner + 5`` and the pillow ``4 * owner``.
    """
    if triangle.palette_index != BED_LINEN_PALETTE:
        return None
    sheet, pillow = bed_palette_indices(owner)
    centre_y = sum(vertex.y for vertex in triangle.vertices) / 3.0
    return pillow if centre_y > BED_PILLOW_MIN_Y else sheet


def bed_palette_indices(owner: int) -> tuple[int, int]:
    """Return ``(sheet, pillow)`` palette indices for a bed's owner value.

    The reference computes ``4 * owner + 5`` and ``4 * owner`` then casts to a
    byte, so the sheet index wraps for high owners rather than overflowing. One
    bed in the shipped game relies on this: ``owner`` 63 gives 257, which wraps
    to 1.
    """
    owner = int(owner)
    return ((4 * owner + 5) & 0xFF, (4 * owner) & 0xFF)


def writing_prefix_index(flags: int) -> int:
    """String index in block 8 for a sign's ``The plaque reads: `` prefix."""
    return WRITING_PREFIX_BASE + (int(flags) & 0x07)


def writing_message_index(obj: dict) -> int | None:
    """String index in block 8 for a writing's readable text, when it has one."""
    value = obj.get("special_property_value")
    if value is None:
        link = obj.get("quantity_or_link")
        if link is None or int(link) <= WRITING_MESSAGE_BIAS:
            return None
        value = int(link) - WRITING_MESSAGE_BIAS
    return int(value)
