"""Ultima Underworld built-in 3D models stored inside ``UW2.EXE``.

Decoder follows published model-node format. It intentionally reads model
palette entries from executable instead of embedding tables from other tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import struct


MODEL_COUNT = 32

MODEL_PALETTE_MAX = 4
"""A five-byte model info entry holds a count plus at most four colours."""

INFO_INDIRECT_FIRST_COLOR = 0x80
"""Info-entry flag marking a model whose first colour is not stored inline.

Only the moongate (``0x17``) sets it, and it is the only model whose first
colour byte is ``0x00`` - a placeholder rather than "black". The colour it
stands for is :data:`MOONGATE_FIRST_COLOR`.
"""

CHEST_MODEL = 0x19
"""The chest, whose faces name a colour the game does not appear to use."""

CHEST_COLOR_SLOT = 0
"""Which of the chest's two declared colours its faces are drawn in.

The chest declares ``0x8E`` (148, 88, 36), a warm brown, and ``0xCA``
(96, 96, 96), a grey. Its face nodes call the grey twenty-one times and the
brown once, and that same slot mechanism is demonstrably right elsewhere - the
bed's frame, the chair, the boulders all come out correct. In the game the
chest is nevertheless brown, checked in Castle Britannia where all forty of
them carry ``flags`` and ``owner`` of zero, so nothing on the instance can be
selecting it. UnderworldGodot also gives its chest a brown body
(``objects/chest.cs``), by hand rather than from the executable.

UnderworldAdventures' table agrees with our reading, but is not independent of
it: ``ModelDecoder.cpp`` maps colour offsets with the same arithmetic, so its
``{ 0x8E, 0xCA }`` was very likely dumped from the same bytes.

So this is recorded, not decoded: the chest is drawn in the colour it declares
first. The face shading still applies, which gives it the lighter lid and
darker sides the game shows.
"""

BLACKROCK_GEM_MODEL = 0x1E
"""The large blackrock gem, whose colours the engine decides, not the model."""

BLACKROCK_GEM_COLOR = 0x52
"""The gem's facet colour with no quest gems collected yet.

The gem reaches well past its own two-entry colour table - slots 3 and 12 to 16
- because the engine supplies those colours from game state rather than the
model. UnderworldGodot transcribes the rule
(``objects/largeblackrockgem.cs``): each of the eight facets is ``0x52`` until
its bit is set in quest 130, then ``0x4D``, with ``0x4F`` marking the one game
variable 6 points at, and the body cycling around ``0x53``. ``0x4C`` to ``0x52``
is a blue ramp, from lavender down to deep blue.

A map render has no save game, so the gem is drawn as it stands at the start:
every facet still ``0x52``. Reading the out-of-range slots as palette 0 instead
made it black, and wrapping them round made it white; it is blue either way in
the game.
"""

MOONGATE_FIRST_COLOR = 0x21
"""Stand-in for the moongate's placeholder first colour.

Only reached if a gate's link field does not give one. The colour a moongate
actually shows is on the instance, not the model - see
:func:`titan.uw2.instances.moongate_palette` - which is why the entry in the
executable is a placeholder in the first place. This value is
UnderworldAdventures' (``ModelDecoder.cpp``: ``{ 0x21, 0x02, 0x04 }``), the red
that most gates happen to use.
"""

UW2_BUILDS = (
    (0x54CF0, 0x59AA64D4, 0x54D8A, 0x6908A),
    (0x550E0, 0x59AA64D4, 0x5517A, 0x6947A),
)

ITEM_MODEL_INDEX = {
    0x0150: 0x03,  # bench
    0x0151: 0x08,  # arrow
    0x0153: 0x07,  # large boulder
    0x0154: 0x07,
    0x0155: 0x06,  # boulder
    0x0156: 0x05,  # small boulder
    0x0157: 0x0B,  # shrine
    0x0158: 0x18,  # table
    0x0159: 0x09,  # beam
    0x015A: 0x17,  # moongate
    0x015B: 0x1B,  # barrel
    0x015C: 0x1C,  # chair
    0x015D: 0x19,  # chest
    0x015E: 0x1A,  # nightstand
    0x015F: 0x04,  # Lotus Turbo Esprit
    0x0160: 0x0A,  # pillar
    0x0163: 0x0D,  # painting
    0x0165: 0x13,  # gravestone
    0x0167: 0x1D,  # bed
    0x0168: 0x1E,  # blackrock gem
    0x0169: 0x1F,  # shelf
}

# These model-class records contain actual inventory/world icons at the same
# OBJECTS.GR index. Later model IDs reuse those GR slots for text/UI fragments.
MODEL_ICON_ITEM_IDS = frozenset(
    item_id for item_id in ITEM_MODEL_INDEX if 0x0150 <= item_id <= 0x0160
)


def shaded_palette_index(colors, palette_index: int, shade: int) -> int:
    """Step a model face's colour down its palette ramp by ``shade``.

    A ``0x00BC`` node gives a colour and, in the word after it, how far to
    darken it - "the same calculations and palette indexing rules apply here"
    as for the Gouraud table, per ``uw-formats.txt``. The palette is laid out in
    short darkening ramps, so the step is simply the next entries along: grey
    ``0xCA`` runs 96 to 24 over five steps, the chair's brown ``0x8F`` 132 to
    44. Faces of one model use different steps, which is the shading the game
    shows on a chest or a bed and we drew flat.

    A ramp is only a handful of entries long and nothing marks where one ends,
    so a step that would *lighten* the colour has run off the end of it - three
    faces of the arrow do - and the base colour is kept instead.
    """
    if shade <= 0:
        return palette_index
    target = palette_index + shade
    if target >= len(colors):
        return palette_index
    if sum(colors[target]) > sum(colors[palette_index]):
        return palette_index
    return target


class UW2ModelError(ValueError):
    """Raised when executable model data is missing or malformed."""


@dataclass(frozen=True)
class ModelVertex:
    x: float
    y: float
    z: float
    u: float = 0.0
    v: float = 0.0
    roof: bool = False


@dataclass(frozen=True)
class ModelTriangle:
    vertices: tuple[ModelVertex, ModelVertex, ModelVertex]
    palette_index: int
    texture_id: int | None = None
    textured: bool = False
    shade: int = 0
    """Steps to darken :attr:`palette_index` by; see :func:`shaded_palette_index`."""
    corner_shades: tuple[int, int, int] | None = None
    """A step per corner, where the model shades the face across it.

    ``0x00D4`` gives every vertex its own step down the colour's ramp and
    ``0x00D6`` switches the following faces onto it. 90% of such faces have
    corners at different steps, so collapsing them to one loses the gradient
    the model draws. :attr:`shade` keeps that mean for consumers that can only
    take a colour per face."""


@dataclass(frozen=True)
class UW2Model:
    index: int
    source_offset: int
    extents: tuple[float, float, float]
    triangles: tuple[ModelTriangle, ...]
    origin: tuple[float, float, float] | None = None
    collision_half_extents: tuple[float, float, float] | None = None

    @property
    def placement_origin(self) -> tuple[float, float, float]:
        """Return the model-space pivot that belongs at the object position."""
        if self.origin is None:
            return (0.0, 0.0, 0.0)
        return (
            self.origin[0],
            self.origin[1],
            self.origin[2] - self.extents[1] / 2.0,
        )

    def local_position(self, vertex: ModelVertex) -> tuple[float, float, float]:
        """Translate one decoded vertex relative to the executable model pivot."""
        origin_x, origin_y, origin_z = self.placement_origin
        return (
            vertex.x - origin_x,
            vertex.y - origin_y,
            vertex.z - origin_z,
        )

    def oriented_position(
        self, vertex: ModelVertex, heading: int, horizontal_scale: float = 1.0
    ) -> tuple[float, float, float]:
        """Apply the UW clockwise heading and optional horizontal scale."""
        local_x, local_y, local_z = self.local_position(vertex)
        angle = -(heading & 7) * math.tau / 8.0
        cosine, sine = math.cos(angle), math.sin(angle)
        return (
            (local_x * cosine - local_y * sine) * horizontal_scale,
            (local_x * sine + local_y * cosine) * horizontal_scale,
            local_z,
        )


@dataclass
class _ModelState:
    vertices: list[ModelVertex]
    triangles: list[ModelTriangle]
    origin: tuple[float, float, float] | None = None
    collision_half_extents: tuple[float, float, float] | None = None
    vertex_dark: dict[int, int] = field(default_factory=dict)
    """How far down its ramp each vertex sits, from the model's ``0x00D4`` table."""


class UW2ModelArchive:
    """One supported UW2 executable with lazily decoded built-in models."""

    def __init__(
        self,
        data: bytes,
        *,
        source: str,
        table_offset: int,
        base_offset: int,
        info_offset: int,
    ) -> None:
        self.data = data
        self.source = source
        self.table_offset = table_offset
        self.base_offset = base_offset
        self.info_offset = info_offset
        self.offsets = struct.unpack_from(f"<{MODEL_COUNT}H", data, table_offset)
        self._cache: dict[int, UW2Model] = {}

    @classmethod
    def from_file(cls, path: str | Path) -> UW2ModelArchive:
        source_path = Path(path)
        return cls.from_data(source_path.read_bytes(), source=str(source_path))

    @classmethod
    def from_data(cls, data: bytes, *, source: str = "<bytes>") -> UW2ModelArchive:
        for table_offset, signature, base_offset, info_offset in UW2_BUILDS:
            if table_offset + MODEL_COUNT * 2 > len(data):
                continue
            if struct.unpack_from("<I", data, table_offset)[0] == signature:
                if info_offset + MODEL_COUNT * 5 > len(data):
                    raise UW2ModelError(f"UW2 model information table exceeds {source}")
                return cls(
                    data,
                    source=source,
                    table_offset=table_offset,
                    base_offset=base_offset,
                    info_offset=info_offset,
                )
        raise UW2ModelError(f"no supported UW2 model table found in {source}")

    def model_for_item(self, item_id: int) -> UW2Model | None:
        model_index = ITEM_MODEL_INDEX.get(item_id)
        return self.model(model_index) if model_index is not None else None

    def model(self, index: int) -> UW2Model:
        if index < 0 or index >= MODEL_COUNT:
            raise UW2ModelError(f"UW2 model index must be in 0..31: {index}")
        cached = self._cache.get(index)
        if cached is not None:
            return cached
        source_offset = self.base_offset + self.offsets[index]
        if source_offset + 10 > len(self.data):
            raise UW2ModelError(f"UW2 model {index:#04x} starts outside {self.source}")
        extents = tuple(
            _fixed(struct.unpack_from("<h", self.data, source_offset + 4 + axis * 2)[0])
            for axis in range(3)
        )
        state = _ModelState(vertices=[], triangles=[])
        parser = _ModelParser(
            self.data,
            model_index=index,
            palette=self._model_palette(index),
            state=state,
            source=self.source,
        )
        parser.parse(source_offset + 10)
        model = UW2Model(
            index=index,
            source_offset=source_offset,
            extents=(extents[0], extents[1], extents[2]),
            triangles=tuple(state.triangles),
            origin=state.origin,
            collision_half_extents=state.collision_half_extents,
        )
        self._cache[index] = model
        return model

    def _model_palette(self, index: int) -> tuple[int, ...]:
        """Per-model colour table from the executable's model info entry.

        An info entry is five bytes: a count in the low nibble of the first,
        then up to four palette indices. ``uw-formats.txt`` documents only
        three colours plus a trailing byte, but the bed (``0x1D``) declares
        four and uses all four - reading only three painted its quilt and
        pillow with the frame's colour. Two models declare more than three;
        widening the table to four changes the bed alone.

        The count is trusted as written except that it is capped: the pillar
        (``0x0A``) claims nine colours where four bytes follow. It draws no
        flat-coloured face at all, so nothing reads the surplus.

        One model carries :data:`INFO_INDIRECT_FIRST_COLOR`; see there.
        """
        offset = self.info_offset + index * 5
        header = self.data[offset]
        count = header & 0x0F
        if count == 0:
            return (0,)
        count = min(count, MODEL_PALETTE_MAX)
        colors = list(self.data[offset + 1 : offset + 1 + count])
        if header & INFO_INDIRECT_FIRST_COLOR and colors:
            colors[0] = MOONGATE_FIRST_COLOR
        return tuple(colors)


class _ModelParser:
    def __init__(
        self,
        data: bytes,
        *,
        model_index: int,
        palette: tuple[int, ...],
        state: _ModelState,
        source: str,
    ) -> None:
        self.data = data
        self.model_index = model_index
        self.palette = palette
        self.state = state
        self.source = source
        self.active_streams: set[int] = set()

    def parse(self, position: int) -> None:
        self._parse_stream(position, self.palette[0], (0.0, 0.0, 0.0), 0)

    def _parse_stream(
        self,
        position: int,
        color: int,
        translation: tuple[float, float, float],
        depth: int,
        shade: int = 0,
        gouraud: bool = False,
    ) -> None:
        if depth > 128:
            raise UW2ModelError(f"UW2 model {self.model_index:#04x} node tree too deep")
        if position in self.active_streams:
            raise UW2ModelError(
                f"UW2 model {self.model_index:#04x} cyclic node stream at {position:#x}"
            )
        self.active_streams.add(position)
        reader = _Reader(self.data, position, self.source)
        try:
            while True:
                command_offset = reader.position
                command = reader.u16()
                if command == 0x0000:
                    return
                if command == 0x0078:
                    origin_vertex = self._vertex(reader.vertex_ref())
                    self.state.origin = (
                        origin_vertex.x,
                        origin_vertex.y,
                        origin_vertex.z,
                    )
                    self.state.collision_half_extents = (
                        reader.fixed(),
                        reader.fixed(),
                        reader.fixed(),
                    )
                    reader.u16()
                elif command == 0x004A:
                    tx = reader.fixed()
                    tz = reader.fixed()
                    ty = reader.fixed()
                    translation = (tx, ty, tz)
                elif command == 0x00BA:
                    color = self._color(reader.u16())
                    relative = reader.s16()
                    continuation = reader.position
                    self._parse_stream(
                        continuation + relative,
                        color,
                        translation,
                        depth + 1,
                    )
                elif command == 0x007A:
                    vertex = self._translated(
                        reader.fixed(), reader.fixed(), reader.fixed(), translation
                    )
                    self._store(reader.vertex_ref(), vertex)
                elif command == 0x0082:
                    count = reader.u16()
                    first = reader.u16()
                    for vertex_index in range(first, first + count):
                        vertex = self._translated(
                            reader.fixed(),
                            reader.fixed(),
                            reader.fixed(),
                            translation,
                        )
                        self._store(vertex_index, vertex)
                elif command in {0x0086, 0x0088, 0x008A}:
                    reference = reader.vertex_ref()
                    delta = reader.fixed()
                    destination = reader.vertex_ref()
                    vertex = self._vertex(reference)
                    values = [vertex.x, vertex.y, vertex.z]
                    axis = {0x0086: 0, 0x008A: 1, 0x0088: 2}[command]
                    values[axis] += delta
                    self._store(
                        destination,
                        ModelVertex(
                            x=values[0],
                            y=values[1],
                            z=values[2],
                            roof=vertex.roof,
                        ),
                    )
                elif command in {0x0090, 0x0092, 0x0094}:
                    delta_a = reader.fixed()
                    delta_b = reader.fixed()
                    reference = reader.vertex_ref()
                    destination = reader.vertex_ref()
                    vertex = self._vertex(reference)
                    values = [vertex.x, vertex.y, vertex.z]
                    axes = {0x0090: (0, 2), 0x0092: (0, 1), 0x0094: (1, 2)}[command]
                    values[axes[0]] += delta_a
                    values[axes[1]] += delta_b
                    self._store(
                        destination,
                        ModelVertex(
                            x=values[0],
                            y=values[1],
                            z=values[2],
                            roof=vertex.roof,
                        ),
                    )
                elif command == 0x008C:
                    reference = reader.vertex_ref()
                    reader.u16()
                    destination = reader.vertex_ref()
                    vertex = self._vertex(reference)
                    self._store(
                        destination,
                        ModelVertex(vertex.x, vertex.y, vertex.z, roof=True),
                    )
                elif command == 0x0058:
                    reader.skip(14)
                elif command in {0x005E, 0x0060, 0x0062}:
                    reader.skip(10)
                elif command in {0x0064, 0x0066, 0x0068}:
                    reader.skip(6)
                elif command == 0x007E:
                    indices = [reader.vertex_ref() for _ in range(reader.u16())]
                    face_shade = shade
                    corner_darks = None
                    if gouraud:
                        face_shade = self._face_dark(indices, shade)
                        corner_darks = [
                            self.state.vertex_dark.get(index, face_shade)
                            for index in indices
                        ]
                    self._add_face(indices, color, face_shade, corner_darks)
                elif command in {0x00A8, 0x00B4, 0x00CE}:
                    # The 00A8 field is always 6 in known data. It marks the
                    # textured face form; the placed item selects TMOBJ.GR.
                    texture_id = reader.u16() if command == 0x00A8 else None
                    count = reader.u16()
                    vertices = []
                    for _ in range(count):
                        vertex = self._vertex(reader.vertex_ref())
                        vertices.append(
                            ModelVertex(
                                vertex.x,
                                vertex.y,
                                vertex.z,
                                reader.texcoord(),
                                reader.texcoord(),
                                vertex.roof,
                            )
                        )
                    self._triangulate(vertices, color, texture_id, textured=True)
                elif command in {0x00A0, 0x00D2}:
                    texture_id = reader.u16() if command == 0x00A0 else None
                    indices = [reader.u8() for _ in range(4)]
                    vertices = []
                    for index, (u, v) in zip(
                        indices,
                        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
                    ):
                        vertex = self._vertex(index)
                        vertices.append(
                            ModelVertex(
                                vertex.x,
                                vertex.y,
                                vertex.z,
                                u,
                                v,
                                vertex.roof,
                            )
                        )
                    self._triangulate(vertices, color, texture_id, textured=True)
                elif command in {0x0006, 0x000C, 0x000E, 0x0010}:
                    reader.skip(12 if command == 0x0006 else 8)
                    left_relative = reader.u16()
                    left = reader.position + left_relative
                    right_relative = reader.u16()
                    right = reader.position + right_relative
                    self._parse_stream(left, color, translation, depth + 1)
                    self._parse_stream(right, color, translation, depth + 1)
                elif command == 0x0014:
                    reader.vertex_ref()
                    color = self._color(reader.u16())
                    shade = 0
                    reader.vertex_ref()
                elif command == 0x0016:
                    reader.vertex_ref()
                    color = self._color(reader.u16())
                    shade = 0
                    reader.u16()
                elif command == 0x00BC:
                    # "define flat face shade": a colour and, in the word after
                    # it, how far down that colour's ramp to go.
                    color = self._color(reader.u16())
                    shade = reader.u16()
                    gouraud = False
                elif command == 0x00BE:
                    self._color(reader.u16())
                    color = self._color(reader.u16())
                    shade = 0
                elif command == 0x00D4:
                    # The model's one vertex shading table: a base colour, then
                    # how far down its ramp each vertex sits.
                    count = reader.u16()
                    color = self._color(reader.u16())
                    shade = 0
                    for _ in range(count):
                        vertex_index = reader.vertex_ref()
                        self.state.vertex_dark[vertex_index] = reader.u8()
                    if count & 1:
                        reader.u8()
                elif command == 0x00D6:
                    gouraud = True
                elif command in {0x0040, 0x0044}:
                    pass
                elif command == 0x002E:
                    # Documented as switching Gouraud back off; the Lotus leans
                    # on it and the table uses it once.
                    gouraud = False
                    reader.u16()
                elif command in {0x0012, 0x00B2}:
                    reader.u16()
                else:
                    raise UW2ModelError(
                        f"UW2 model {self.model_index:#04x} unknown node "
                        f"{command:#06x} at {command_offset:#x} in {self.source}"
                    )
        finally:
            self.active_streams.remove(position)

    def _translated(
        self,
        x: float,
        y: float,
        z: float,
        translation: tuple[float, float, float],
    ) -> ModelVertex:
        return ModelVertex(x + translation[0], y + translation[1], z + translation[2])

    def _store(self, index: int, vertex: ModelVertex) -> None:
        while len(self.state.vertices) <= index:
            self.state.vertices.append(ModelVertex(0.0, 0.0, 0.0))
        self.state.vertices[index] = vertex

    def _vertex(self, index: int) -> ModelVertex:
        if index >= len(self.state.vertices):
            raise UW2ModelError(
                f"UW2 model {self.model_index:#04x} references undefined vertex {index}"
            )
        return self.state.vertices[index]

    def _color(self, color_offset: int) -> int:
        if self.model_index == CHEST_MODEL and self.palette:
            # See CHEST_COLOR_SLOT: its faces ask for the grey, the game shows
            # the brown, and no instance field can be choosing between them.
            return self.palette[min(CHEST_COLOR_SLOT, len(self.palette) - 1)]
        index = (color_offset - 0x2680) // 2
        if not 0 <= index < len(self.palette):
            # Reaching past the model's own table means the engine, not the
            # model, chooses this colour. Only the gem does it in a way that
            # shows; everything else that reaches out has a one-entry table and
            # wrapped onto the same colour anyway. UnderworldAdventures returns
            # palette 0 here, which suits those but turns the gem black.
            if self.model_index == BLACKROCK_GEM_MODEL:
                return BLACKROCK_GEM_COLOR
            return 0
        return self.palette[index]

    def _face_dark(self, indices: list[int], fallback: int) -> int:
        """One shade for a Gouraud face, averaged over the vertices it uses.

        UW2 shades these faces across their corners, each vertex carrying its
        own step down the colour's ramp. A scene part here is one colour for
        many triangles, so the face takes the mean of its corners instead: on
        the boulders, shrine and furniture that use this the faces are small
        enough that the difference is slight, and it is the whole of the
        modelling that was being dropped. It does flatten a gradient drawn
        across a single large panel - a moongate is one quad with a bright
        middle - which needs colour per vertex to show properly.
        """
        darks = [
            self.state.vertex_dark[index]
            for index in indices
            if index in self.state.vertex_dark
        ]
        if not darks:
            return fallback
        return int(round(sum(darks) / len(darks)))

    def _add_face(
        self,
        indices: list[int],
        color: int,
        shade: int = 0,
        corner_darks: list[int] | None = None,
    ) -> None:
        self._triangulate(
            [self._vertex(index) for index in indices],
            color,
            None,
            shade=shade,
            corner_darks=corner_darks,
        )

    def _triangulate(
        self,
        vertices: list[ModelVertex],
        color: int,
        texture_id: int | None,
        *,
        textured: bool = False,
        shade: int = 0,
        corner_darks: list[int] | None = None,
    ) -> None:
        if len(vertices) < 3:
            return
        for first, second, third in _triangulate_polygon(vertices):
            corner_shades = (
                (
                    corner_darks[first],
                    corner_darks[second],
                    corner_darks[third],
                )
                if corner_darks is not None and len(corner_darks) == len(vertices)
                else None
            )
            self.state.triangles.append(
                ModelTriangle(
                    vertices=(vertices[first], vertices[second], vertices[third]),
                    palette_index=color,
                    texture_id=texture_id,
                    textured=textured,
                    shade=shade,
                    corner_shades=corner_shades,
                )
            )


def _triangulate_polygon(
    vertices: list[ModelVertex],
) -> list[tuple[int, int, int]]:
    """Triangulate one planar face, returning index triples into ``vertices``.

    Faces in these models are not all convex. A bed's side is a single outline
    tracing up one post, along the rail, up the other post and back underneath,
    which leaves a notch between the posts. Fanning from the first vertex fills
    that notch solid, welding the posts to the frame. Ear clipping follows the
    real outline instead, and reduces to the same surface as a fan whenever the
    polygon is convex.
    """
    count = len(vertices)
    if count < 3:
        return []
    if count == 3:
        return [(0, 1, 2)]

    plane = _dominant_plane(vertices)
    points = [plane(vertex) for vertex in vertices]
    remaining = list(range(count))
    if _signed_area(points, remaining) < 0.0:
        remaining.reverse()

    triangles: list[tuple[int, int, int]] = []
    guard = 0
    while len(remaining) > 3 and guard < count * count:
        guard += 1
        for position in range(len(remaining)):
            previous = remaining[position - 1]
            current = remaining[position]
            following = remaining[(position + 1) % len(remaining)]
            if _is_ear(points, remaining, previous, current, following):
                triangles.append((previous, current, following))
                remaining.pop(position)
                break
        else:
            # Degenerate or self-intersecting outline: fall back rather than
            # drop the face entirely.
            return [(0, index, index + 1) for index in range(1, count - 1)]
    if len(remaining) == 3:
        triangles.append((remaining[0], remaining[1], remaining[2]))
    return triangles


def _dominant_plane(vertices: list[ModelVertex]):
    """Pick the axis pair that best preserves a planar face's area."""
    normal_x = normal_y = normal_z = 0.0
    for index, current in enumerate(vertices):
        following = vertices[(index + 1) % len(vertices)]
        normal_x += (current.y - following.y) * (current.z + following.z)
        normal_y += (current.z - following.z) * (current.x + following.x)
        normal_z += (current.x - following.x) * (current.y + following.y)
    largest = max(abs(normal_x), abs(normal_y), abs(normal_z))
    if largest == abs(normal_x):
        return lambda vertex: (vertex.y, vertex.z)
    if largest == abs(normal_y):
        return lambda vertex: (vertex.z, vertex.x)
    return lambda vertex: (vertex.x, vertex.y)


def _signed_area(points: list[tuple[float, float]], order: list[int]) -> float:
    total = 0.0
    for position, index in enumerate(order):
        following = order[(position + 1) % len(order)]
        total += (
            points[index][0] * points[following][1]
            - points[following][0] * points[index][1]
        )
    return total / 2.0


def _cross(
    origin: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return (first[0] - origin[0]) * (second[1] - origin[1]) - (first[1] - origin[1]) * (
        second[0] - origin[0]
    )


def _is_ear(
    points: list[tuple[float, float]],
    remaining: list[int],
    previous: int,
    current: int,
    following: int,
) -> bool:
    area = _cross(points[previous], points[current], points[following])
    if area <= 1e-12:
        return False
    for other in remaining:
        if other in (previous, current, following):
            continue
        if _contains(points, previous, current, following, points[other]):
            return False
    return True


def _contains(
    points: list[tuple[float, float]],
    previous: int,
    current: int,
    following: int,
    point: tuple[float, float],
) -> bool:
    first = _cross(points[previous], points[current], point)
    second = _cross(points[current], points[following], point)
    third = _cross(points[following], points[previous], point)
    return first >= 0.0 and second >= 0.0 and third >= 0.0


class _Reader:
    def __init__(self, data: bytes, position: int, source: str) -> None:
        self.data = data
        self.position = position
        self.source = source

    def _require(self, count: int) -> None:
        if self.position + count > len(self.data):
            raise UW2ModelError(
                f"UW2 model read exceeds {self.source} at {self.position:#x}"
            )

    def skip(self, count: int) -> None:
        self._require(count)
        self.position += count

    def u8(self) -> int:
        self._require(1)
        value = self.data[self.position]
        self.position += 1
        return value

    def u16(self) -> int:
        self._require(2)
        value = struct.unpack_from("<H", self.data, self.position)[0]
        self.position += 2
        return value

    def s16(self) -> int:
        self._require(2)
        value = struct.unpack_from("<h", self.data, self.position)[0]
        self.position += 2
        return value

    def fixed(self) -> float:
        return _fixed(self.s16())

    def texcoord(self) -> float:
        return self.u16() / 65535.0

    def vertex_ref(self) -> int:
        return self.u16() >> 3


def _fixed(value: int) -> float:
    return value / 256.0
