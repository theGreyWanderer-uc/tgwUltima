"""
3D model (mesh) reader for Ultima 9: Ascension's ``static/sappear.flx``.

Each used entry in ``sappear.flx`` (3,764 of 8,000 directory slots in
this project's test copy of the game) is one **model**: a hierarchy of
rigid **limbs** (body parts/pieces, not a modern vertex-skinned
skeleton -- see below), each with its own mesh at up to 4 levels of
detail (LOD).

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

Validated by parsing all 3,764 real entries in this project's test
copy of ``sappear.flx``: 3,748 parse cleanly (including a 927-vertex,
1,264-triangle, 86-limb model), and exactly 16 raise :class:`U9ModelError`
with a nonsensical ``submesh_count``/``lod_count`` (e.g. model 536 reads
``submesh_count=169, lod_count=845`` from a 2,139-byte entry -- more
than 500KB of offset table alone couldn't possibly fit). These are
genuinely corrupt/placeholder archive entries, not a parser bug: model
536 is the exact same entry the reference importer's own author flags
with ``#mesh 536 crashes`` in ``ImportSingleModel()``.
"""

from __future__ import annotations

__all__ = [
    "U9Model",
    "U9ModelError",
    "U9Limb",
    "U9SubmeshLod",
    "U9Triangle",
    "U9TriangleCorner",
    "U9Material",
    "INVISIBLE_TEXTURE_ID",
]

import struct
from dataclasses import dataclass

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


#: Bits of :attr:`U9Material.render_flags` (the u16 at material +0x04).
#: Meanings come from u9.exe ``Renderer_SetMaterial`` (``0x00586550``), which
#: bit-tests this field to build the runtime material. Bits 1, 12-15 are
#: neither set in shipped data nor read there.
MATERIAL_FLAG_CHROMAKEY = 0x0001
MATERIAL_FLAG_MODE_MASK = 0x000C
MATERIAL_FLAG_UNKNOWN_4 = 0x0010
MATERIAL_FLAG_RUNTIME_40 = 0x0020
MATERIAL_FLAG_RUNTIME_01 = 0x0040
MATERIAL_FLAG_RUNTIME_200 = 0x0080
MATERIAL_FLAG_CLAMP_S = 0x0100
MATERIAL_FLAG_CLAMP_T = 0x0200
MATERIAL_FLAG_TRANSLUCENT = 0x0400
MATERIAL_FLAG_UNKNOWN_11 = 0x0800

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
    2,3  yes      two-bit mode field, copied to runtime ``+0x10 & 0x0C``
    4    yes      not read by ``Renderer_SetMaterial``
    5    no       -> runtime ``0x40``
    6    yes      -> runtime ``0x01``
    7    no       -> runtime ``0x200``
    8,9  yes      texture clamp axes -> runtime ``0x80`` / ``0x100``
    10   no       translucent -> runtime ``0x02``
    11   yes      not read by ``Renderer_SetMaterial``
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

    @property
    def is_invisible(self) -> bool:
        return self.texture_id == INVISIBLE_TEXTURE_ID


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
    transform on top of/instead of this one. That format is not
    implemented, and note that even a full implementation only
    repositions limbs rigidly -- it can't change a triangle's UV
    mapping, so it's irrelevant to texture-placement oddities on a
    given sub-mesh, only to pose/motion.
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

    @classmethod
    def parse(cls, data: bytes, model_id: int = 0) -> U9Model:
        if len(data) < MODEL_HEADER_SIZE:
            raise U9ModelError(f"data too small for a model header: {len(data)} bytes (need {MODEL_HEADER_SIZE})")

        submesh_count, lod_count = struct.unpack_from("<II", data, 0x00)
        cylinder_base_center = struct.unpack_from("<3f", data, 0x08)
        cylinder_base_height, cylinder_base_radius = struct.unpack_from("<2f", data, 0x14)
        sphere_center = struct.unpack_from("<3f", data, 0x1C)
        sphere_radius = struct.unpack_from("<f", data, 0x28)[0]
        min_bounds = struct.unpack_from("<3f", data, 0x30)
        max_bounds = struct.unpack_from("<3f", data, 0x3C)
        lod_thresholds = struct.unpack_from("<4I", data, 0x48)
        center_of_mass = struct.unpack_from("<3f", data, 0x58)

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
                limb_id, parent_id = struct.unpack_from("<II", data, header_off)
                scale = struct.unpack_from("<3f", data, header_off + 0x08)
                position = struct.unpack_from("<3f", data, header_off + 0x14)
                qw, qx, qy, qz = struct.unpack_from("<4f", data, header_off + 0x20)

                lods = tuple(_parse_lod(data, lod_off, i) for i, lod_off in enumerate(lod_offs))
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
            raise U9ModelError(f"malformed model record (model_id={model_id}): {e}") from e

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
        )


def _parse_lod(data: bytes, start: int, lod_index: int) -> U9SubmeshLod | None:
    mesh_size = struct.unpack_from("<I", data, start)[0]
    if mesh_size == 0:
        return None

    sphere_center = struct.unpack_from("<3f", data, start + 0x0C)
    sphere_radius = struct.unpack_from("<f", data, start + 0x18)[0]
    min_bounds = struct.unpack_from("<3f", data, start + 0x1C)
    max_bounds = struct.unpack_from("<3f", data, start + 0x28)
    face_count, _mount_face_count, vertex_count, _mount_vertex_count, _max_face_count, material_count = (
        struct.unpack_from("<6I", data, start + 0x3C)
    )
    face_off, _mount_face_off, vertex_off, _mount_vertex_off, material_off = struct.unpack_from(
        "<5I", data, start + 0x54
    )

    faces_start = start + face_off + 4
    raw_faces = [_parse_face(data, faces_start + i * FACE_RECORD_SIZE) for i in range(face_count)]

    verts_start = start + vertex_off + 4
    vertices = tuple(
        struct.unpack_from("<3f", data, verts_start + i * VERTEX_RECORD_SIZE) for i in range(vertex_count)
    )

    mats_start = start + material_off + 4
    materials = tuple(_parse_material(data, mats_start + i * MATERIAL_RECORD_SIZE) for i in range(material_count))

    face_material_index = [0] * face_count
    for mat_idx, mat in enumerate(materials):
        for f in range(mat.first_face, mat.first_face + mat.face_count):
            if 0 <= f < face_count:
                face_material_index[f] = mat_idx

    triangles = tuple(
        U9Triangle(
            corners=raw_face[0],
            material_index=face_material_index[i],
            face_normal=raw_face[1],
            color=raw_face[2],
        )
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
    )


def _parse_face(
    data: bytes, pos: int
) -> tuple[tuple[U9TriangleCorner, U9TriangleCorner, U9TriangleCorner], Vec3, tuple[int, int, int, int]]:
    corners = tuple(_parse_corner(data, pos + i * CORNER_RECORD_SIZE) for i in range(3))
    normal = struct.unpack_from("<3f", data, pos + 0x5C)
    color = struct.unpack_from("<4B", data, pos + 0x70)
    return corners, normal, color  # type: ignore[return-value]


def _parse_corner(data: bytes, pos: int) -> U9TriangleCorner:
    vertex_index = struct.unpack_from("<I", data, pos)[0]
    # pos+4: byte offset of the vertex -- redundant with vertex_index, unused here.
    normal = struct.unpack_from("<3f", data, pos + 0x08)
    uv = struct.unpack_from("<2f", data, pos + 0x14)
    return U9TriangleCorner(vertex_index=vertex_index, normal=normal, uv=uv)


def _parse_material(data: bytes, pos: int) -> U9Material:
    tex_id, flags_02, render_flags, flags_06, first_face, face_count = struct.unpack_from("<6H", data, pos)
    default_alpha, modified_alpha, anim_start, anim_end, cur_frame, anim_speed, _anim_type, _playback = (
        struct.unpack_from("<8B", data, pos + 12)
    )
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
    )
