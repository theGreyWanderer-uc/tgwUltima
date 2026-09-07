"""
3D model (mesh) reader for Ultima 9: Ascension's ``static/sappear.flx``.

Each used entry in ``sappear.flx`` (3,764 of 8,000 directory slots in
this project's test copy of the game) is one **model**. Most use a hierarchy
of rigid **limbs** (body parts/pieces, not a modern vertex-skinned skeleton --
see below), each with its own mesh at up to 4 levels of detail (LOD). Sixteen
use the alternate indexed-polygon record described below.

Ported and reverse-engineered from the real, open-source Blender
importer ``Chevluh/Ultima-9-Blender-Importer``'s
``ultimaModelImporter.py`` (found locally at
``D:\\_Repos\\_UltimaIX\\Ultima-9-Blender-Importer``) -- **not** from a
prior ChatGPT-generated research summary the user also supplied, which
claimed several byte offsets that turned out to be wrong when checked
against the real importer source (e.g. it placed the limb quaternion
at +0x18, but the real importer places it at +0x20, after a full
12-byte ``Position`` vec3 the summary's offsets didn't leave room for).
Every offset below was additionally cross-checked field-by-field
against real game data (model ID 0, a simple debug cube: 1 limb, 1 LOD,
8 vertices, 12 faces, 1 material) before being trusted -- see each
dataclass's docstring for the specific real values that confirmed it.

Model record layout (all offsets relative to the start of the FLX
entry's own bytes, i.e. ``U9FlxArchive.read_entry(model_id)``)::

    0x00  submesh_count      u32  -- number of limbs
    0x04  lod_count          u32  -- number of LOD levels per limb
    0x08  cylinder_base_center   vec3  -- collision cylinder
    0x14  cylinder_base_height   f32
    0x18  cylinder_base_radius   f32
    0x1C  sphere_center          vec3  -- bounding sphere
    0x28  sphere_radius          f32
    0x2C  (unknown)              f32
    0x30  min_bounds             vec3  -- bounding box
    0x3C  max_bounds             vec3
    0x48  lod_thresholds         u32[4]
    0x58  center_of_mass         vec3
    0x64  (mass/volume, unused here)  f32
    0x68  (inertia matrix, unused here)  36 bytes
    0x8C  (unknown)              f32
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

Validated against all 3,764 used entries in this project's test copy of
``sappear.flx``.  Most entries use the hierarchical format above.  Sixteen
start with a 169-byte (``0xA9``) header and use an alternate indexed-polygon
layout; :meth:`U9Model.parse` recognises both.  The alternate face records can
hold triangles or quads.  Quads are triangulated for the normal ``limbs`` API,
while their original four-corner form remains available in
``U9Model.indexed_faces``.
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
LOD_HEADER_SIZE = 0x7C
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
    flags2: int = 0
    plane_w: float = 0.0
    raw_material: int = 0
    collision: bytes = b"\x00" * 8


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


#: Bits of :attr:`U9Material.render_flags` (the u16 at material +0x04).
#: Meanings come from u9.exe ``Renderer_SetMaterial`` (``0x00586550``), which
#: bit-tests this field to build the runtime material, and by ``0x00585C90``,
#: the pooled/deferred setter, which decodes two bits the first one ignores.
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

#: ``modified_alpha`` uses this as "no override"; any other value is a
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
    largest is 2076, and 48% of the non-zero values exceed 16. The engine
    confirms it - ``Renderer_SetMaterial`` at u9.exe ``0x00586550`` reads a u32
    at +0x04 and bit-tests it to build the runtime material's flag word.

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
    from ``modified_alpha != 0xFF``, which the engine stores as a per-material
    constant alpha.

    ``flags_02`` and ``flags_06`` are the u16 fields at +0x02 and +0x06,
    exposed raw and **not safe to branch on**. Roughly 17.5% of each field
    holds MSVC debug-heap fill - ``0xCDCD`` (uninitialised heap) and ``0xBAAD``
    (``BAADF00D``) - so the tool that built ``sappear.flx`` wrote these structs
    without clearing them, and much of what is stored is uninitialised memory
    rather than data.

    * ``flags_02``: 36.7% zero, 17.5% debug fill, 43.6% large arbitrary values,
      and only 2.2% small values with no repeating family. Treat as noise
      unless proven otherwise.
    * ``flags_06``: carries a real signal under the noise. 26.1% of materials
      hold a value below ``0x100``, dominated by a tight family - ``0x82``
      (3557), ``0x8B`` (1431), ``0x84`` (514), ``0x83`` (136), plus ``0x9F``,
      ``0x9C``, ``0x80``. That ``0x80``-``0x9F`` clustering is structured and
      worth decoding.

    ``render_flags`` by contrast shows no fill patterns at all and takes just
    12 values, which is independent evidence that +0x04 is a field the writer
    initialises and +0x02 / +0x06 partly are not.

    ``Renderer_SetMaterial`` reads none of these two, consistent with them
    being ignored by the renderer.
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
    mount_vertices: tuple[Vec3, ...] = ()
    mount_triangles: tuple[U9Triangle, ...] = ()
    mesh_size: int = 0
    flags: int = 0
    unknown_08: int = 0
    unknown_34: int = 0
    unknown_38: int = 0
    max_face_count: int = 0
    face_offset: int = 0
    mount_face_offset: int = 0
    vertex_offset: int = 0
    mount_vertex_offset: int = 0
    material_offset: int = 0
    sorted_face_offsets: tuple[int, int, int, int] = (0, 0, 0, 0)
    unknown_78: int = 0


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
    Real animation (``static/anim.flx``) would apply its own per-frame
    transform on top of/instead of this one. :mod:`titan.u9.animation`
    parses those tracks, but model-to-clip selection and animated export
    are not implemented. Even when applied, animation only repositions
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
    unknown_2c: float = 0.0
    mass_or_volume: float = 0.0
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
    unknown_8c: float = 0.0
    record_format: str = "hierarchical"
    indexed_faces: tuple[U9IndexedFace, ...] = ()
    alternate_header: bytes = b""
    trailing_data: bytes = b""
    _raw_data: bytes = field(default=b"", repr=False, compare=False)

    @classmethod
    def parse(cls, data: bytes, model_id: int = 0) -> U9Model:
        if (
            len(data) >= 4
            and struct.unpack_from("<I", data, 0)[0] == INDEXED_HEADER_SIZE
        ):
            return _parse_indexed_model(data, model_id)
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
        unknown_2c = struct.unpack_from("<f", data, 0x2C)[0]
        min_bounds = struct.unpack_from("<3f", data, 0x30)
        max_bounds = struct.unpack_from("<3f", data, 0x3C)
        lod_thresholds = struct.unpack_from("<4I", data, 0x48)
        center_of_mass = struct.unpack_from("<3f", data, 0x58)
        mass_or_volume = struct.unpack_from("<f", data, 0x64)[0]
        inertia_matrix = struct.unpack_from("<9f", data, 0x68)
        unknown_8c = struct.unpack_from("<f", data, 0x8C)[0]

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
            unknown_2c=unknown_2c,
            mass_or_volume=mass_or_volume,
            inertia_matrix=inertia_matrix,
            unknown_8c=unknown_8c,
            _raw_data=data,
        )

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

    flags, unknown_08 = struct.unpack_from("<2I", data, start + 0x04)
    sphere_center = struct.unpack_from("<3f", data, start + 0x0C)
    sphere_radius = struct.unpack_from("<f", data, start + 0x18)[0]
    min_bounds = struct.unpack_from("<3f", data, start + 0x1C)
    max_bounds = struct.unpack_from("<3f", data, start + 0x28)
    unknown_34, unknown_38 = struct.unpack_from("<2I", data, start + 0x34)
    (
        face_count,
        mount_face_count,
        vertex_count,
        mount_vertex_count,
        max_face_count,
        material_count,
    ) = struct.unpack_from("<6I", data, start + 0x3C)
    face_off, mount_face_off, vertex_off, mount_vertex_off, material_off = (
        struct.unpack_from("<5I", data, start + 0x54)
    )
    sorted_face_offsets = struct.unpack_from("<4I", data, start + 0x68)
    unknown_78 = struct.unpack_from("<I", data, start + 0x78)[0]

    faces_start = _array_start(
        data, start, face_off, face_count, FACE_RECORD_SIZE, "faces"
    )
    raw_faces = tuple(
        _parse_face(data, faces_start + i * FACE_RECORD_SIZE) for i in range(face_count)
    )

    verts_start = _array_start(
        data, start, vertex_off, vertex_count, VERTEX_RECORD_SIZE, "vertices"
    )
    vertices = tuple(
        struct.unpack_from("<3f", data, verts_start + i * VERTEX_RECORD_SIZE)
        for i in range(vertex_count)
    )

    mount_faces_start = _array_start(
        data,
        start,
        mount_face_off,
        mount_face_count,
        FACE_RECORD_SIZE,
        "mount faces",
    )
    mount_faces = tuple(
        _parse_face(data, mount_faces_start + i * FACE_RECORD_SIZE)
        for i in range(mount_face_count)
    )
    mount_verts_start = _array_start(
        data,
        start,
        mount_vertex_off,
        mount_vertex_count,
        VERTEX_RECORD_SIZE,
        "mount vertices",
    )
    mount_vertices = tuple(
        struct.unpack_from("<3f", data, mount_verts_start + i * VERTEX_RECORD_SIZE)
        for i in range(mount_vertex_count)
    )

    mats_start = _array_start(
        data, start, material_off, material_count, MATERIAL_RECORD_SIZE, "materials"
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
    _validate_face_indices(mount_faces, len(mount_vertices), "mount face")

    triangles = tuple(
        _with_material(raw_face, face_material_index[i])
        for i, raw_face in enumerate(raw_faces)
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
        mount_vertices=mount_vertices,
        mount_triangles=mount_faces,
        mesh_size=mesh_size,
        flags=flags,
        unknown_08=unknown_08,
        unknown_34=unknown_34,
        unknown_38=unknown_38,
        max_face_count=max_face_count,
        face_offset=face_off,
        mount_face_offset=mount_face_off,
        vertex_offset=vertex_off,
        mount_vertex_offset=mount_vertex_off,
        material_offset=material_off,
        sorted_face_offsets=sorted_face_offsets,
        unknown_78=unknown_78,
    )


def _parse_face(data: bytes, pos: int) -> U9Triangle:
    _require_range(data, pos, FACE_RECORD_SIZE, "face record")
    corners = tuple(_parse_corner(data, pos + i * CORNER_RECORD_SIZE) for i in range(3))
    flags, flags2 = struct.unpack_from("<2I", data, pos + 0x54)
    normal = struct.unpack_from("<3f", data, pos + 0x5C)
    plane_w = struct.unpack_from("<f", data, pos + 0x68)[0]
    raw_material = struct.unpack_from("<I", data, pos + 0x6C)[0]
    color = struct.unpack_from("<4B", data, pos + 0x70)
    collision = data[pos + 0x74 : pos + 0x7C]
    return U9Triangle(
        corners=corners,  # type: ignore[arg-type]
        material_index=-1,
        face_normal=normal,
        color=color,
        flags=flags,
        flags2=flags2,
        plane_w=plane_w,
        raw_material=raw_material,
        collision=collision,
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
) -> int:
    if count == 0:
        return record_start
    if relative_offset < LOD_HEADER_SIZE:
        raise U9ModelError(
            f"{label} offset {relative_offset:#x} points inside the LOD header"
        )
    result = record_start + relative_offset + 4
    _require_range(data, result, count * item_size, label)
    return result


def _with_material(triangle: U9Triangle, material_index: int) -> U9Triangle:
    return U9Triangle(
        corners=triangle.corners,
        material_index=material_index,
        face_normal=triangle.face_normal,
        color=triangle.color,
        flags=triangle.flags,
        flags2=triangle.flags2,
        plane_w=triangle.plane_w,
        raw_material=triangle.raw_material,
        collision=triangle.collision,
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
        record_format="indexed",
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
            collision=face.collision,
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
