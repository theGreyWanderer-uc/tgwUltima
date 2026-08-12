"""Ultima Underworld built-in 3D models stored inside ``UW2.EXE``.

Decoder follows published model-node format. It intentionally reads model
palette entries from executable instead of embedding tables from other tools.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import struct


MODEL_COUNT = 32
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
        offset = self.info_offset + index * 5
        count = self.data[offset] & 0x0F
        if count == 0:
            return (0,)
        count = min(count, 3)
        return tuple(self.data[offset + 1 : offset + 1 + count])


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
                    self._add_face(indices, color)
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
                    reader.vertex_ref()
                elif command == 0x0016:
                    reader.vertex_ref()
                    color = self._color(reader.u16())
                    reader.u16()
                elif command == 0x00BC:
                    color = self._color(reader.u16())
                    reader.u16()
                elif command == 0x00BE:
                    self._color(reader.u16())
                    color = self._color(reader.u16())
                elif command == 0x00D4:
                    count = reader.u16()
                    color = self._color(reader.u16())
                    for _ in range(count):
                        reader.vertex_ref()
                        reader.u8()
                    if count & 1:
                        reader.u8()
                elif command in {0x0040, 0x0044, 0x00D6}:
                    pass
                elif command in {0x0012, 0x002E, 0x00B2}:
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
        index = ((color_offset - 0x2680) // 2) % len(self.palette)
        return self.palette[index]

    def _add_face(self, indices: list[int], color: int) -> None:
        self._triangulate([self._vertex(index) for index in indices], color, None)

    def _triangulate(
        self,
        vertices: list[ModelVertex],
        color: int,
        texture_id: int | None,
        *,
        textured: bool = False,
    ) -> None:
        if len(vertices) < 3:
            return
        for index in range(1, len(vertices) - 1):
            self.state.triangles.append(
                ModelTriangle(
                    vertices=(vertices[0], vertices[index], vertices[index + 1]),
                    palette_index=color,
                    texture_id=texture_id,
                    textured=textured,
                )
            )


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
