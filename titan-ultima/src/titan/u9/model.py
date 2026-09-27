"""
3D model (mesh) reader for Ultima 9: Ascension's ``static/sappear.flx``.

Each runtime model entry in ``sappear.flx`` uses a hierarchy
of rigid **limbs** (body parts/pieces, not a modern vertex-skinned skeleton --
see below), each with its own mesh at up to 4 levels of detail (LOD).

The layout was checked against runtime analysis and the game corpus rather than a
prior generated research summary whose offsets proved incorrect. For example,
the summary placed the limb quaternion at +0x18, while the verified layout puts
it at +0x20 after the complete 12-byte ``Position`` vector. Every offset below
was additionally cross-checked field-by-field against real game data (model ID
0, a simple debug cube: 1 limb, 1 LOD, 8 vertices, 12 faces, 1 material) before
being trusted. Each dataclass documents the real values that confirmed it.

Model record layout (all offsets relative to the start of the FLX
entry's own bytes, i.e. ``U9FlxArchive.read_entry(model_id)``)::

    0x00  submesh_count      u32  -- number of limbs
    0x04  lod_count          u32  -- number of LOD levels per limb
    0x08  cylinder_base_center   vec3  -- collision cylinder
    0x14  cylinder_base_height   f32
    0x18  cylinder_base_radius   f32
    0x1C  sphere_center          vec3  -- bounding sphere
    0x28  sphere_radius          f32
    0x2C  collision_shape_code   s16
    0x2E  collision_shape_padding  2 bytes
    0x30  min_bounds             vec3  -- bounding box
    0x3C  max_bounds             vec3
    0x48  lod_thresholds         s32[4]
    0x58  center_of_mass         vec3
    0x64  volume                 f32
    0x68  inverse_inertia_matrix f32[9]
    0x8C  inertia_diagonal_only_code  s32
    0x90  limb offset table      -- see below

The limb offset table has one entry per limb: a single u32 "header
offset" (pointing at that limb's :class:`U9Limb` header, see below),
followed by ``lod_count`` u32 LOD offsets (each pointing at that limb's
mesh at the corresponding detail level, or meaningless if that LOD
slot's :func:`_parse_lod` reports a zero mesh size -- not every limb
has geometry at every LOD).

Real data note: a limb's header offset always lands exactly at the end
of the previous structure it follows (e.g. for model 0, the offset
table itself ends at byte 152, and its one limb's header offset is
152) -- there is no padding between these structures, which was used
throughout development here as a cross-check that each field was being
read at the right size/position.

Validated against all 3,764 used entries in six byte-identical retail archive
copies.  The shipped runtime loader has only the hierarchical path above.
Sixteen entries instead contain a coherent indexed-polygon representation
that the runtime loader does not dispatch to; normal parsing rejects those
records. :meth:`U9Model.parse_forensic` retains the earlier Titan decoder for
explicit inspection of that non-runtime data.
"""

from __future__ import annotations

__all__ = [
    "U9Model",
    "U9ModelError",
    "U9Limb",
    "U9SubmeshLod",
    "U9IndexedFace",
    "U9Triangle",
    "U9TriangleCorner",
    "U9Material",
    "INVISIBLE_TEXTURE_ID",
]

import math
import struct
from dataclasses import dataclass, field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]  # (w, x, y, z)

MODEL_HEADER_SIZE = 0x90
LIMB_HEADER_SIZE = 0x30
MESH_HEADER_SIZE = 0x7C
LOD_HEADER_SIZE = 4 + MESH_HEADER_SIZE
FACE_RECORD_SIZE = 0x7C
CORNER_RECORD_SIZE = 0x1C
MATERIAL_RECORD_SIZE = 0x18
VERTEX_RECORD_SIZE = 0x0C

INDEXED_HEADER_SIZE = 0xA9
INDEXED_FACE_RECORD_SIZE = 0x34
INDEXED_CORNER_RECORD_SIZE = 0x18

INVISIBLE_TEXTURE_ID = 0xFFFF


class U9ModelError(Exception):
    """Raised when a model record is too small/malformed to parse at the expected offsets."""


@dataclass(frozen=True)
class U9TriangleCorner:
    """
    One corner of a :class:`U9Triangle`.

    Normals and UVs are stored **per corner**, not per vertex -- the
    same vertex position can carry different UVs/normals on different
    faces (e.g. a cube corner shared by 3 faces with 3 different UVs).
    Confirmed on real data: model 0's face 0, corner 0 is
    ``vertex_index=3`` (position ``(-160,-160,-160)``), ``normal=(-1,0,0)``,
    ``uv=(0.0, 1.0)``.
    """

    vertex_index: int
    normal: Vec3
    uv: Vec2
    point_offset: int = 0
    """Ordinary records store a redundant vertex-byte offset here.  Indexed
    records store a relative pointer to the vertex record instead."""


@dataclass(frozen=True)
class U9Triangle:
    """One face. Winding order is preserved exactly as stored (corner 0, 1, 2) --
    reversal for a specific target format's handedness convention is an
    export-time concern, not baked in here."""

    corners: tuple[U9TriangleCorner, U9TriangleCorner, U9TriangleCorner]
    material_index: int
    """Index into the owning :class:`U9SubmeshLod`'s ``materials`` -- resolved
    from the material table's first_face/face_count ranges, not the face
    record's own raw ``Material`` field (the reference importer's docstring
    notes that field doesn't always correlate cleanly with the real texture;
    the material table is the reliable source)."""
    face_normal: Vec3
    color: tuple[int, int, int, int]
    """RGBA, each 0-255. Real data: model 0's faces are all (200, 200, 200, 255)."""
    flags: int = 0
    secondary_flags: int = 0
    plane_w: float = 0.0
    raw_material: int = 0
    boundary_vertex_indices: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    surface_size_code: int = 0

    @property
    def attachment_kind(self) -> int:
        """Connection-face marker kind stored in the low byte of the size cell."""
        return self.surface_size_code & 0xFF

    @property
    def attachment_scale(self) -> int:
        """Connection-face marker scale stored in the high byte of the size cell."""
        return self.surface_size_code >> 8

    @property
    def collision(self) -> bytes:
        """Compatibility view of the former opaque eight-byte tail."""
        return bytes(self.boundary_vertex_indices) + struct.pack(
            "<H", self.surface_size_code
        )


@dataclass(frozen=True)
class U9IndexedFace:
    """Original triangle or quad from an alternate ``0xA9`` model record."""

    corners: tuple[U9TriangleCorner, ...]
    corner_offsets: tuple[int, int, int, int]
    """The four relative pointers exactly as stored; zero marks no fourth corner."""
    corner_indices: tuple[int, ...]
    """The resolved indices into the record's corner section."""
    flags: int
    face_normal: Vec3
    plane_w: float
    raw_material: int
    color: tuple[int, int, int, int]
    collision: bytes

    @property
    def is_quad(self) -> bool:
        return len(self.corners) == 4


#: Bits of :attr:`U9Material.render_flags` (the meaningful low half of the
#: 32-bit storage cell at material +0x04). Retail material-building paths
#: bit-test these values when constructing renderer state.
#: Bits 1 and 12-15 are neither set in shipped data nor read by either.
MATERIAL_FLAG_CHROMAKEY = 0x0001
MATERIAL_FLAG_MODE_MASK = 0x000C
#: Bit 3 of the mode pair also routes the primitive into the engine's
#: depth-sorted translucency pool. Carried by cobwebs, fire, blood, forcefields.
MATERIAL_FLAG_SORTED_POOL = 0x0008
MATERIAL_FLAG_UNKNOWN_4 = 0x0010
MATERIAL_FLAG_RUNTIME_40 = 0x0020
MATERIAL_FLAG_RUNTIME_01 = 0x0040
MATERIAL_FLAG_RUNTIME_200 = 0x0080
MATERIAL_FLAG_CLAMP_S = 0x0100
MATERIAL_FLAG_CLAMP_T = 0x0200
MATERIAL_FLAG_TRANSLUCENT = 0x0400
#: Additive blending. Carried by ether clouds, fire, globes, forcefields,
#: sparklers, moongates and flame scrolls - emissive effects.
MATERIAL_FLAG_ADDITIVE = 0x0800

#: ``active_alpha`` uses this as "no override"; any other value is a
#: per-material constant alpha, which the engine copies to the runtime
#: material and applies to vertex colours before the backend sees them.
MATERIAL_ALPHA_NONE = 0xFF


@dataclass(frozen=True)
class U9Material:
    """
    One material entry (0x18 = 24 bytes). Real data: model 0 has exactly
    1 material with ``texture_id=0``, ``first_face=0``, ``face_count=12``
    (covering all 12 of the cube's faces).

    ``render_flags`` is the u16 at +0x04, previously read as
    ``subtexture_count``. It is a bit field, not a count: across all 3,748
    sappear entries (24,476 materials) it takes only 12 distinct values, the
    largest is 2076, and 48% of the non-zero values exceed 16. Retail code at
    ``0x00586550`` confirms it by reading the storage cell at +0x04 and
    bit-testing it to build the runtime material's flag word.

    Bits observed in shipped data, and what the engine does with each:

    ==== ======== ==================================================
    bit  in data  engine use
    ==== ======== ==================================================
    0    yes      gates the chromakey path
    2,3  yes      two-bit mode field; bit 3 also routes to the sorted pool
    4    yes      read by neither builder - still unexplained
    5    no       -> runtime ``0x40``
    6    yes      -> runtime ``0x01``
    7    no       -> runtime ``0x200``
    8,9  yes      texture clamp axes -> runtime ``0x80`` / ``0x100``
    10   no       translucent -> runtime ``0x02``
    11   yes      additive blending -> runtime ``0x400`` (set by ``0x00585C90``)
    ==== ======== ==================================================

    Bit 10 never appears in sappear data, so model translucency comes only
    from ``active_alpha != 0xFF``, which the engine stores as a per-material
    constant alpha.

    The u16 cells at +0x02 and +0x06 are alignment/storage padding, not flag
    fields. They contain uninitialised allocator fill and other stale build-
    process bytes in the shipped archive. They are retained losslessly through
    the complete source record, exposed with explicit padding names, and must
    never drive model or animation behavior.
    """

    texture_id: int
    flags_02: int
    render_flags: int
    flags_06: int
    first_face: int
    face_count: int
    default_alpha: int
    modified_alpha: int
    anim_start: int
    anim_end: int
    cur_frame: int
    anim_speed: int
    animation_type: int = 0
    playback_direction: int = 0
    animation_timer: int = 0

    @property
    def alignment_padding_02(self) -> int:
        """Uninitialised alignment storage between the ID and flag cell."""
        return self.flags_02

    @property
    def alignment_padding_06(self) -> int:
        """Uninitialised upper half of the four-byte flag storage cell."""
        return self.flags_06

    @property
    def render_flags_storage(self) -> int:
        """Complete four-byte cell, including the uninitialised upper half."""
        return self.render_flags | (self.flags_06 << 16)

    @property
    def active_alpha(self) -> int:
        """Stored current alpha; ``0xFF`` means no per-material override."""
        return self.modified_alpha

    @property
    def is_invisible(self) -> bool:
        return self.texture_id == INVISIBLE_TEXTURE_ID

    @property
    def is_chromakey(self) -> bool:
        return bool(self.render_flags & MATERIAL_FLAG_CHROMAKEY)

    @property
    def is_sorted(self) -> bool:
        return bool(self.render_flags & MATERIAL_FLAG_SORTED_POOL)

    @property
    def is_additive(self) -> bool:
        return bool(self.render_flags & MATERIAL_FLAG_ADDITIVE)

    @property
    def clamps_s(self) -> bool:
        return bool(self.render_flags & MATERIAL_FLAG_CLAMP_S)

    @property
    def clamps_t(self) -> bool:
        return bool(self.render_flags & MATERIAL_FLAG_CLAMP_T)


@dataclass(frozen=True)
class U9SubmeshLod:
    """One limb's mesh at one level of detail."""

    lod_index: int
    vertices: tuple[Vec3, ...]
    triangles: tuple[U9Triangle, ...]
    materials: tuple[U9Material, ...]
    sphere_center: Vec3
    sphere_radius: float
    min_bounds: Vec3
    max_bounds: Vec3
    connection_vertices: tuple[Vec3, ...] = ()
    connection_triangles: tuple[U9Triangle, ...] = ()
    mesh_size: int = 0
    flags: int = 0
    secondary_flags: int = 0
    build_higher_detail_pointer: int = 0
    build_lower_detail_pointer: int = 0
    max_face_count: int = 0
    face_offset: int = 0
    connection_face_offset: int = 0
    vertex_offset: int = 0
    connection_vertex_offset: int = 0
    material_offset: int = 0
    sorted_face_offsets: tuple[int, int, int, int] = (0, 0, 0, 0)
    sorted_face_indices: tuple[
        tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]
    ] = ((), (), (), ())
    reserved_words: tuple[int, int] = (0, 0)

    # Compatibility aliases for Titan's earlier observational names.
    @property
    def mount_vertices(self) -> tuple[Vec3, ...]:
        return self.connection_vertices

    @property
    def mount_triangles(self) -> tuple[U9Triangle, ...]:
        return self.connection_triangles

    @property
    def unknown_08(self) -> int:
        return self.secondary_flags

    @property
    def unknown_34(self) -> int:
        return self.build_higher_detail_pointer

    @property
    def unknown_38(self) -> int:
        return self.build_lower_detail_pointer

    @property
    def mount_face_offset(self) -> int:
        return self.connection_face_offset

    @property
    def mount_vertex_offset(self) -> int:
        return self.connection_vertex_offset

    @property
    def unknown_78(self) -> int:
        return self.reserved_words[0]


@dataclass(frozen=True)
class U9Limb:
    """
    One rigid body part, positioned relative to its parent limb.

    Ultima 9 models are **not** a modern vertex-skinned mesh -- each
    limb is a separately rigid-transformed sub-mesh (translate + rotate
    + scale relative to its parent), matching a traditional "rigid
    hierarchy" rig rather than smooth skinning. ``parent_id == limb_id``
    marks the root limb (no parent). Real data: model 0's only limb has
    ``limb_id=0``, ``parent_id=0`` (root), ``scale=(1,1,1)``,
    ``position=(0,0,0)``, ``rotation=(1,0,0,0)`` (identity quaternion).

    ``position``/``rotation``/``scale`` are this model's only stored
    transform for the limb -- a static "bind pose", not necessarily the
    pose the creature is meant to be seen in during real gameplay.
    Real animation (``static/anim.flx``) applies runtime-selected per-frame
    transforms. :mod:`titan.u9.animation_pose` can sample and apply an
    explicitly selected clip, but automatic model/state-to-clip selection and
    layered controller composition are not implemented.
    :mod:`titan.u9.animated_model_bundle` exports the complete rigid hierarchy,
    exact clip tracks, and a generated animated GLB. Even when applied,
    animation only repositions
    limbs rigidly -- it can't change a triangle's UV mapping, so it's
    irrelevant to texture-placement oddities on a given sub-mesh, only
    to pose/motion.
    """

    limb_id: int
    parent_id: int
    scale: Vec3
    position: Vec3
    rotation: Quat
    lods: tuple[U9SubmeshLod | None, ...]
    """Indexed by LOD level; ``None`` at an index means this limb has no
    geometry at that detail level (a zero mesh-size marker in the source
    data), matching the reference importer's ``readSubmesh()`` returning
    ``None`` in that case."""

    @property
    def is_root(self) -> bool:
        return self.parent_id == self.limb_id


@dataclass(frozen=True)
class U9Model:
    """One parsed ``sappear.flx`` entry."""

    model_id: int
    cylinder_base_center: Vec3
    cylinder_base_height: float
    cylinder_base_radius: float
    sphere_center: Vec3
    sphere_radius: float
    min_bounds: Vec3
    max_bounds: Vec3
    lod_thresholds: tuple[int, int, int, int]
    center_of_mass: Vec3
    limbs: tuple[U9Limb, ...]
    collision_shape_code: int = 0
    collision_shape_padding: bytes = b"\x00\x00"
    volume: float = 0.0
    inertia_matrix: tuple[
        float, float, float, float, float, float, float, float, float
    ] = (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    inertia_diagonal_only_code: int = 0
    record_format: str = "hierarchical"
    runtime_compatible: bool = True
    indexed_faces: tuple[U9IndexedFace, ...] = ()
    alternate_header: bytes = b""
    trailing_data: bytes = b""
    _raw_data: bytes = field(default=b"", repr=False, compare=False)

    @property
    def collision_shape(self) -> str:
        """Titan label for the stored collision-shape selector."""
        return {0: "box", 1: "sphere", 2: "cylinder"}.get(
            self.collision_shape_code, "unknown"
        )

    @property
    def inertia_diagonal_only(self) -> bool | None:
        """Decoded optimization hint, or ``None`` for a non-boolean stored code."""
        if self.inertia_diagonal_only_code in (0, 1):
            return bool(self.inertia_diagonal_only_code)
        return None

    # Compatibility views for names used by Titan's earlier partial decoder.
    @property
    def unknown_2c(self) -> float:
        return struct.unpack(
            "<f",
            struct.pack(
                "<h2s", self.collision_shape_code, self.collision_shape_padding
            ),
        )[0]

    @property
    def mass_or_volume(self) -> float:
        return self.volume

    @property
    def unknown_8c(self) -> float:
        return struct.unpack("<f", struct.pack("<i", self.inertia_diagonal_only_code))[
            0
        ]

    @classmethod
    def parse(cls, data: bytes, model_id: int = 0) -> U9Model:
        if (
            len(data) >= 4
            and struct.unpack_from("<I", data, 0)[0] == INDEXED_HEADER_SIZE
        ):
            raise U9ModelError(
                "record uses the orphaned indexed-geometry layout; the retail "
                "model loader has no dispatch for it (use parse_forensic for "
                "explicit non-runtime inspection)"
            )
        if len(data) < MODEL_HEADER_SIZE:
            raise U9ModelError(
                f"data too small for a model header: {len(data)} bytes (need {MODEL_HEADER_SIZE})"
            )

        submesh_count, lod_count = struct.unpack_from("<II", data, 0x00)
        table_size = submesh_count * (lod_count + 1) * 4
        _require_range(data, MODEL_HEADER_SIZE, table_size, "limb offset table")
        cylinder_base_center = struct.unpack_from("<3f", data, 0x08)
        cylinder_base_height, cylinder_base_radius = struct.unpack_from(
            "<2f", data, 0x14
        )
        sphere_center = struct.unpack_from("<3f", data, 0x1C)
        sphere_radius = struct.unpack_from("<f", data, 0x28)[0]
        collision_shape_code = struct.unpack_from("<h", data, 0x2C)[0]
        collision_shape_padding = data[0x2E:0x30]
        min_bounds = struct.unpack_from("<3f", data, 0x30)
        max_bounds = struct.unpack_from("<3f", data, 0x3C)
        lod_thresholds = struct.unpack_from("<4i", data, 0x48)
        center_of_mass = struct.unpack_from("<3f", data, 0x58)
        volume = struct.unpack_from("<f", data, 0x64)[0]
        inertia_matrix = struct.unpack_from("<9f", data, 0x68)
        inertia_diagonal_only_code = struct.unpack_from("<i", data, 0x8C)[0]

        try:
            offset = MODEL_HEADER_SIZE
            limb_descs: list[tuple[int, tuple[int, ...]]] = []
            for _ in range(submesh_count):
                header_off = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                lod_offs = struct.unpack_from(f"<{lod_count}I", data, offset)
                offset += 4 * lod_count
                limb_descs.append((header_off, lod_offs))

            limbs = []
            for header_off, lod_offs in limb_descs:
                _require_range(data, header_off, LIMB_HEADER_SIZE, "limb header")
                limb_id, parent_id = struct.unpack_from("<II", data, header_off)
                scale = struct.unpack_from("<3f", data, header_off + 0x08)
                position = struct.unpack_from("<3f", data, header_off + 0x14)
                qw, qx, qy, qz = struct.unpack_from("<4f", data, header_off + 0x20)

                lods = tuple(
                    _parse_lod(data, lod_off, i) for i, lod_off in enumerate(lod_offs)
                )
                limbs.append(
                    U9Limb(
                        limb_id=limb_id,
                        parent_id=parent_id,
                        scale=scale,
                        position=position,
                        rotation=(qw, qx, qy, qz),
                        lods=lods,
                    )
                )
        except struct.error as e:
            raise U9ModelError(
                f"malformed model record (model_id={model_id}): {e}"
            ) from e

        return cls(
            model_id=model_id,
            cylinder_base_center=cylinder_base_center,
            cylinder_base_height=cylinder_base_height,
            cylinder_base_radius=cylinder_base_radius,
            sphere_center=sphere_center,
            sphere_radius=sphere_radius,
            min_bounds=min_bounds,
            max_bounds=max_bounds,
            lod_thresholds=lod_thresholds,
            center_of_mass=center_of_mass,
            limbs=tuple(limbs),
            collision_shape_code=collision_shape_code,
            collision_shape_padding=collision_shape_padding,
            volume=volume,
            inertia_matrix=inertia_matrix,
            inertia_diagonal_only_code=inertia_diagonal_only_code,
            _raw_data=data,
        )

    @classmethod
    def parse_forensic(cls, data: bytes, model_id: int = 0) -> U9Model:
        """Parse runtime models plus Titan's non-runtime indexed recovery.

        This entry point is deliberately explicit: the retail model loader has
        no branch for the indexed representation, so callers must not treat
        the recovered geometry as game-recognized model data.
        """
        if (
            len(data) >= 4
            and struct.unpack_from("<I", data, 0)[0] == INDEXED_HEADER_SIZE
        ):
            return _parse_indexed_model(data, model_id)
        return cls.parse(data, model_id)

    def to_bytes(self) -> bytes:
        """Return the exact source record bytes, including fields not decoded yet."""
        if not self._raw_data:
            raise U9ModelError(
                "model was constructed in memory and has no source bytes"
            )
        return self._raw_data


def _parse_lod(data: bytes, start: int, lod_index: int) -> U9SubmeshLod | None:
    _require_range(data, start, 4, f"LOD {lod_index} size")
    mesh_size = struct.unpack_from("<I", data, start)[0]
    if mesh_size == 0:
        return None
    _require_range(data, start, LOD_HEADER_SIZE, f"LOD {lod_index} header")
    _require_range(data, start, mesh_size + 4, f"LOD {lod_index} declared mesh")
    record_end = start + mesh_size + 4

    flags, secondary_flags = struct.unpack_from("<2I", data, start + 0x04)
    sphere_center = struct.unpack_from("<3f", data, start + 0x0C)
    sphere_radius = struct.unpack_from("<f", data, start + 0x18)[0]
    min_bounds = struct.unpack_from("<3f", data, start + 0x1C)
    max_bounds = struct.unpack_from("<3f", data, start + 0x28)
    build_higher_detail_pointer, build_lower_detail_pointer = struct.unpack_from(
        "<2I", data, start + 0x34
    )
    (
        face_count,
        connection_face_count,
        vertex_count,
        connection_vertex_count,
        max_face_count,
        material_count,
    ) = struct.unpack_from("<6I", data, start + 0x3C)
    (
        face_off,
        connection_face_off,
        vertex_off,
        connection_vertex_off,
        material_off,
    ) = struct.unpack_from("<5I", data, start + 0x54)
    sorted_face_offsets = struct.unpack_from("<4I", data, start + 0x68)
    reserved_words = struct.unpack_from("<2I", data, start + 0x78)

    faces_start = _array_start(
        data, start, face_off, face_count, FACE_RECORD_SIZE, "faces", record_end
    )
    raw_faces = tuple(
        _parse_face(data, faces_start + i * FACE_RECORD_SIZE) for i in range(face_count)
    )

    verts_start = _array_start(
        data,
        start,
        vertex_off,
        vertex_count,
        VERTEX_RECORD_SIZE,
        "vertices",
        record_end,
    )
    vertices = tuple(
        struct.unpack_from("<3f", data, verts_start + i * VERTEX_RECORD_SIZE)
        for i in range(vertex_count)
    )

    connection_faces_start = _array_start(
        data,
        start,
        connection_face_off,
        connection_face_count,
        FACE_RECORD_SIZE,
        "connection faces",
        record_end,
    )
    connection_faces = tuple(
        _parse_face(data, connection_faces_start + i * FACE_RECORD_SIZE)
        for i in range(connection_face_count)
    )
    connection_verts_start = _array_start(
        data,
        start,
        connection_vertex_off,
        connection_vertex_count,
        VERTEX_RECORD_SIZE,
        "connection vertices",
        record_end,
    )
    connection_vertices = tuple(
        struct.unpack_from("<3f", data, connection_verts_start + i * VERTEX_RECORD_SIZE)
        for i in range(connection_vertex_count)
    )

    mats_start = _array_start(
        data,
        start,
        material_off,
        material_count,
        MATERIAL_RECORD_SIZE,
        "materials",
        record_end,
    )
    materials = tuple(
        _parse_material(data, mats_start + i * MATERIAL_RECORD_SIZE)
        for i in range(material_count)
    )

    face_material_index = [-1] * face_count
    for mat_idx, mat in enumerate(materials):
        for f in range(mat.first_face, mat.first_face + mat.face_count):
            if not 0 <= f < face_count:
                raise U9ModelError(
                    f"material {mat_idx} face range {mat.first_face}.."
                    f"{mat.first_face + mat.face_count} exceeds {face_count} faces"
                )
            if face_material_index[f] != -1:
                raise U9ModelError(f"face {f} is covered by more than one material")
            face_material_index[f] = mat_idx

    missing = next(
        (
            i
            for i, material_index in enumerate(face_material_index)
            if material_index < 0
        ),
        None,
    )
    if missing is not None:
        raise U9ModelError(f"face {missing} is not covered by any material")

    _validate_face_indices(raw_faces, len(vertices), "face")
    _validate_face_indices(
        connection_faces, len(connection_vertices), "connection face"
    )

    triangles = tuple(
        _with_material(raw_face, face_material_index[i])
        for i, raw_face in enumerate(raw_faces)
    )
    sorted_face_indices = tuple(
        _parse_sorted_face_indices(
            data, start, relative_offset, face_count, direction, record_end
        )
        for direction, relative_offset in enumerate(sorted_face_offsets)
    )

    return U9SubmeshLod(
        lod_index=lod_index,
        vertices=vertices,
        triangles=triangles,
        materials=materials,
        sphere_center=sphere_center,
        sphere_radius=sphere_radius,
        min_bounds=min_bounds,
        max_bounds=max_bounds,
        connection_vertices=connection_vertices,
        connection_triangles=connection_faces,
        mesh_size=mesh_size,
        flags=flags,
        secondary_flags=secondary_flags,
        build_higher_detail_pointer=build_higher_detail_pointer,
        build_lower_detail_pointer=build_lower_detail_pointer,
        max_face_count=max_face_count,
        face_offset=face_off,
        connection_face_offset=connection_face_off,
        vertex_offset=vertex_off,
        connection_vertex_offset=connection_vertex_off,
        material_offset=material_off,
        sorted_face_offsets=sorted_face_offsets,
        sorted_face_indices=sorted_face_indices,  # type: ignore[arg-type]
        reserved_words=reserved_words,
    )


def _parse_face(data: bytes, pos: int) -> U9Triangle:
    _require_range(data, pos, FACE_RECORD_SIZE, "face record")
    corners = tuple(_parse_corner(data, pos + i * CORNER_RECORD_SIZE) for i in range(3))
    flags, secondary_flags = struct.unpack_from("<2I", data, pos + 0x54)
    normal = struct.unpack_from("<3f", data, pos + 0x5C)
    plane_w = struct.unpack_from("<f", data, pos + 0x68)[0]
    raw_material = struct.unpack_from("<I", data, pos + 0x6C)[0]
    color = struct.unpack_from("<4B", data, pos + 0x70)
    boundary_vertex_indices = struct.unpack_from("<6B", data, pos + 0x74)
    surface_size_code = struct.unpack_from("<H", data, pos + 0x7A)[0]
    return U9Triangle(
        corners=corners,  # type: ignore[arg-type]
        material_index=-1,
        face_normal=normal,
        color=color,
        flags=flags,
        secondary_flags=secondary_flags,
        plane_w=plane_w,
        raw_material=raw_material,
        boundary_vertex_indices=boundary_vertex_indices,
        surface_size_code=surface_size_code,
    )


def _parse_corner(data: bytes, pos: int) -> U9TriangleCorner:
    vertex_index, point_offset = struct.unpack_from("<2I", data, pos)
    normal = struct.unpack_from("<3f", data, pos + 0x08)
    uv = struct.unpack_from("<2f", data, pos + 0x14)
    return U9TriangleCorner(
        vertex_index=vertex_index, normal=normal, uv=uv, point_offset=point_offset
    )


def _parse_material(data: bytes, pos: int) -> U9Material:
    tex_id, flags_02, render_flags, flags_06, first_face, face_count = (
        struct.unpack_from("<6H", data, pos)
    )
    (
        default_alpha,
        modified_alpha,
        anim_start,
        anim_end,
        cur_frame,
        anim_speed,
        anim_type,
        playback,
    ) = struct.unpack_from("<8B", data, pos + 12)
    animation_timer = struct.unpack_from("<I", data, pos + 0x14)[0]
    return U9Material(
        texture_id=tex_id,
        flags_02=flags_02,
        render_flags=render_flags,
        flags_06=flags_06,
        first_face=first_face,
        face_count=face_count,
        default_alpha=default_alpha,
        modified_alpha=modified_alpha,
        anim_start=anim_start,
        anim_end=anim_end,
        cur_frame=cur_frame,
        anim_speed=anim_speed,
        animation_type=anim_type,
        playback_direction=playback,
        animation_timer=animation_timer,
    )


def _require_range(data: bytes, start: int, size: int, label: str) -> None:
    if start < 0 or size < 0 or start > len(data) or size > len(data) - start:
        raise U9ModelError(
            f"{label} range {start:#x}..{start + size:#x} exceeds {len(data):#x}-byte record"
        )


def _array_start(
    data: bytes,
    record_start: int,
    relative_offset: int,
    count: int,
    item_size: int,
    label: str,
    record_end: int | None = None,
) -> int:
    if count == 0:
        return record_start
    if relative_offset < MESH_HEADER_SIZE:
        raise U9ModelError(
            f"{label} offset {relative_offset:#x} points inside the LOD header"
        )
    result = record_start + relative_offset + 4
    _require_range(data, result, count * item_size, label)
    if record_end is not None and result + count * item_size > record_end:
        raise U9ModelError(f"{label} extends beyond its declared mesh record")
    return result


def _parse_sorted_face_indices(
    data: bytes,
    record_start: int,
    relative_offset: int,
    face_count: int,
    direction: int,
    record_end: int,
) -> tuple[int, ...]:
    if face_count == 0:
        return ()
    label = f"sorted face list {direction}"
    pos = _array_start(
        data,
        record_start,
        relative_offset,
        face_count + 2,
        2,
        label,
        record_end,
    )
    stored = struct.unpack_from(f"<{face_count + 2}h", data, pos)
    if stored[0] != -1 or stored[-1] != -1:
        raise U9ModelError(f"{label} is not bounded by -1 sentinels")
    indices = stored[1:-1]
    if sorted(indices) != list(range(face_count)):
        raise U9ModelError(f"{label} does not contain each render face exactly once")
    return indices


def _with_material(triangle: U9Triangle, material_index: int) -> U9Triangle:
    return U9Triangle(
        corners=triangle.corners,
        material_index=material_index,
        face_normal=triangle.face_normal,
        color=triangle.color,
        flags=triangle.flags,
        secondary_flags=triangle.secondary_flags,
        plane_w=triangle.plane_w,
        raw_material=triangle.raw_material,
        boundary_vertex_indices=triangle.boundary_vertex_indices,
        surface_size_code=triangle.surface_size_code,
    )


def _validate_face_indices(
    faces: tuple[U9Triangle, ...], vertex_count: int, label: str
) -> None:
    for face_index, face in enumerate(faces):
        for corner_index, corner in enumerate(face.corners):
            if corner.vertex_index >= vertex_count:
                raise U9ModelError(
                    f"{label} {face_index} corner {corner_index} references vertex "
                    f"{corner.vertex_index}, but only {vertex_count} vertices exist"
                )


def _parse_indexed_model(data: bytes, model_id: int) -> U9Model:
    _require_range(data, 0, INDEXED_HEADER_SIZE, "indexed model header")
    corner_start, vertex_start, trailing_start = struct.unpack_from("<3I", data, 0x04)
    face_count, corner_count, vertex_count = struct.unpack_from("<3I", data, 0x10)

    expected_corner_start = INDEXED_HEADER_SIZE + face_count * INDEXED_FACE_RECORD_SIZE
    expected_vertex_start = corner_start + corner_count * INDEXED_CORNER_RECORD_SIZE
    expected_trailing_start = vertex_start + vertex_count * VERTEX_RECORD_SIZE
    if corner_start != expected_corner_start:
        raise U9ModelError(
            f"indexed corner offset is {corner_start:#x}, expected {expected_corner_start:#x}"
        )
    if vertex_start != expected_vertex_start:
        raise U9ModelError(
            f"indexed vertex offset is {vertex_start:#x}, expected {expected_vertex_start:#x}"
        )
    if trailing_start != expected_trailing_start:
        raise U9ModelError(
            f"indexed trailing offset is {trailing_start:#x}, expected {expected_trailing_start:#x}"
        )
    _require_range(
        data,
        INDEXED_HEADER_SIZE,
        face_count * INDEXED_FACE_RECORD_SIZE,
        "indexed faces",
    )
    _require_range(
        data, corner_start, corner_count * INDEXED_CORNER_RECORD_SIZE, "indexed corners"
    )
    _require_range(
        data, vertex_start, vertex_count * VERTEX_RECORD_SIZE, "indexed vertices"
    )
    _require_range(data, trailing_start, 0, "indexed trailing data")

    vertices = tuple(
        struct.unpack_from("<3f", data, vertex_start + i * VERTEX_RECORD_SIZE)
        for i in range(vertex_count)
    )
    corners = tuple(
        _parse_indexed_corner(
            data,
            corner_start + i * INDEXED_CORNER_RECORD_SIZE,
            vertex_start,
            vertex_count,
        )
        for i in range(corner_count)
    )
    used_vertices = {corner.vertex_index for corner in corners}
    if used_vertices != set(range(vertex_count)):
        raise U9ModelError("indexed vertex table contains unreferenced records")

    indexed_faces = tuple(
        _parse_indexed_face(
            data,
            INDEXED_HEADER_SIZE + i * INDEXED_FACE_RECORD_SIZE,
            corner_start,
            corners,
        )
        for i in range(face_count)
    )
    used_corners = {corner for face in indexed_faces for corner in face.corner_indices}
    expected_corners = set(range(corner_count))
    if used_corners != expected_corners:
        raise U9ModelError(
            "indexed corner table contains unreferenced or duplicate-address records"
        )

    texture_ids = tuple(dict.fromkeys(face.raw_material for face in indexed_faces))
    if any(texture_id > 0xFFFF for texture_id in texture_ids):
        raise U9ModelError("indexed face material does not fit a texture ID")
    material_indices = {
        texture_id: index for index, texture_id in enumerate(texture_ids)
    }
    materials = tuple(
        U9Material(
            texture_id=texture_id,
            flags_02=0,
            render_flags=0,
            flags_06=0,
            first_face=0,
            face_count=0,
            default_alpha=0xFF,
            modified_alpha=0xFF,
            anim_start=0,
            anim_end=0,
            cur_frame=0,
            anim_speed=0,
        )
        for texture_id in texture_ids
    )
    triangles = tuple(
        triangle
        for face in indexed_faces
        for triangle in _triangulate_indexed_face(
            face, material_indices[face.raw_material]
        )
    )
    min_bounds, max_bounds, sphere_center, sphere_radius = _geometry_bounds(vertices)
    lod = U9SubmeshLod(
        lod_index=0,
        vertices=vertices,
        triangles=triangles,
        materials=materials,
        sphere_center=sphere_center,
        sphere_radius=sphere_radius,
        min_bounds=min_bounds,
        max_bounds=max_bounds,
        mesh_size=len(data),
        max_face_count=len(triangles),
    )
    limb = U9Limb(
        limb_id=0,
        parent_id=0,
        scale=(1.0, 1.0, 1.0),
        position=(0.0, 0.0, 0.0),
        rotation=(1.0, 0.0, 0.0, 0.0),
        lods=(lod,),
    )
    return U9Model(
        model_id=model_id,
        cylinder_base_center=(0.0, 0.0, 0.0),
        cylinder_base_height=0.0,
        cylinder_base_radius=0.0,
        sphere_center=sphere_center,
        sphere_radius=sphere_radius,
        min_bounds=min_bounds,
        max_bounds=max_bounds,
        lod_thresholds=(0, 0, 0, 0),
        center_of_mass=(0.0, 0.0, 0.0),
        limbs=(limb,),
        record_format="forensic_indexed",
        runtime_compatible=False,
        indexed_faces=indexed_faces,
        alternate_header=data[:INDEXED_HEADER_SIZE],
        trailing_data=data[trailing_start:],
        _raw_data=data,
    )


def _parse_indexed_corner(
    data: bytes, pos: int, vertex_start: int, vertex_count: int
) -> U9TriangleCorner:
    point_offset = struct.unpack_from("<I", data, pos)[0]
    vertex_pos = pos + point_offset
    delta = vertex_pos - vertex_start
    if (
        delta < 0
        or delta % VERTEX_RECORD_SIZE
        or delta // VERTEX_RECORD_SIZE >= vertex_count
    ):
        raise U9ModelError(
            f"indexed corner at {pos:#x} has invalid vertex pointer {point_offset:#x}"
        )
    normal = struct.unpack_from("<3f", data, pos + 0x04)
    uv = struct.unpack_from("<2f", data, pos + 0x10)
    return U9TriangleCorner(
        vertex_index=delta // VERTEX_RECORD_SIZE,
        normal=normal,
        uv=uv,
        point_offset=point_offset,
    )


def _parse_indexed_face(
    data: bytes,
    pos: int,
    corner_start: int,
    corners: tuple[U9TriangleCorner, ...],
) -> U9IndexedFace:
    relative_offsets = struct.unpack_from("<4I", data, pos)
    if 0 in relative_offsets[:3]:
        raise U9ModelError(f"indexed face at {pos:#x} has a missing triangle corner")
    resolved_corners = []
    corner_indices = []
    for relative_offset in relative_offsets:
        if relative_offset == 0:
            continue
        corner_pos = pos + relative_offset
        delta = corner_pos - corner_start
        if delta < 0 or delta % INDEXED_CORNER_RECORD_SIZE:
            raise U9ModelError(
                f"indexed face at {pos:#x} has invalid corner pointer {relative_offset:#x}"
            )
        corner_index = delta // INDEXED_CORNER_RECORD_SIZE
        if corner_index >= len(corners):
            raise U9ModelError(
                f"indexed face at {pos:#x} points beyond the corner table"
            )
        resolved_corners.append(corners[corner_index])
        corner_indices.append(corner_index)

    flags = struct.unpack_from("<I", data, pos + 0x10)[0]
    face_normal = struct.unpack_from("<3f", data, pos + 0x14)
    plane_w = struct.unpack_from("<f", data, pos + 0x20)[0]
    raw_material = struct.unpack_from("<I", data, pos + 0x24)[0]
    color = struct.unpack_from("<4B", data, pos + 0x28)
    collision = data[pos + 0x2C : pos + 0x34]
    return U9IndexedFace(
        corners=tuple(resolved_corners),
        corner_offsets=relative_offsets,
        corner_indices=tuple(corner_indices),
        flags=flags,
        face_normal=face_normal,
        plane_w=plane_w,
        raw_material=raw_material,
        color=color,
        collision=collision,
    )


def _triangulate_indexed_face(
    face: U9IndexedFace, material_index: int
) -> tuple[U9Triangle, ...]:
    corner_sets = (
        (face.corners[:3],)
        if not face.is_quad
        else (face.corners[:3], (face.corners[0], *face.corners[2:4]))
    )
    return tuple(
        U9Triangle(
            corners=corners,  # type: ignore[arg-type]
            material_index=material_index,
            face_normal=face.face_normal,
            color=face.color,
            flags=face.flags,
            plane_w=face.plane_w,
            raw_material=face.raw_material,
            boundary_vertex_indices=tuple(face.collision[:6]),  # type: ignore[arg-type]
            surface_size_code=struct.unpack("<H", face.collision[6:])[0],
        )
        for corners in corner_sets
    )


def _geometry_bounds(vertices: tuple[Vec3, ...]) -> tuple[Vec3, Vec3, Vec3, float]:
    if not vertices:
        zero = (0.0, 0.0, 0.0)
        return zero, zero, zero, 0.0
    min_bounds = tuple(min(vertex[axis] for vertex in vertices) for axis in range(3))
    max_bounds = tuple(max(vertex[axis] for vertex in vertices) for axis in range(3))
    center = tuple(
        (minimum + maximum) / 2.0 for minimum, maximum in zip(min_bounds, max_bounds)
    )
    radius = max(math.dist(center, vertex) for vertex in vertices)
    return min_bounds, max_bounds, center, radius  # type: ignore[return-value]
