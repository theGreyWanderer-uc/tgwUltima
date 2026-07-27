"""
Export Ultima 9: Ascension models (:mod:`titan.u9.model`) to OBJ+MTL+PNG
and STL.

Both exporters flatten the limb hierarchy into one shared world space
(see :mod:`titan.u9.transform` for why -- OBJ/STL have no node/parent
concept) at a single LOD level, and skip any face whose material is
"invisible" (``texture_id == 0xFFFF``, see :class:`titan.u9.model.U9Material`)
-- there is no OBJ/STL equivalent of the reference Blender importer's
wireframe-only display for these, so the closest honest behavior is to
leave them out of the exported geometry entirely, rather than export a
mesh with a nonexistent texture.

**Winding order**: real per-face normals were checked against both
possible triangle windings on real data (model 0, a 12-triangle cube):
the raw stored corner order (0, 1, 2) disagreed with the stored face
normal on all 12 faces, while the swapped order (0, 2, 1) -- the same
swap the reference Blender importer applies -- agreed on all 12.
Both exporters swap by default (``reverse_winding=True``); the flag
exists in case a different target ever needs the raw order.

**Scale**: real game units are divided by 40 by default
(``scale=1/40``), matching the reference importer's own
``scaleFactor`` constant (Blender scene units).

**Textures**: OBJ export accepts an optional texture-frame resolver
(see :func:`export_obj`) that turns ``(texture_id, frame)`` into a
decoded :class:`titan.u9.texture.U9TextureFrame`; PNGs are only written
for materials actually used by the exported LOD. Without a resolver,
OBJ still exports valid flat-colored materials (from each material's
default alpha), just without images.

**UV V-flip (critical, real bug found and fixed)**: the raw parsed
``corner.uv`` (see :class:`titan.u9.model.U9TriangleCorner`) is V=0 at
the *top* of the source texture -- confirmed independently while
decoding textures directly (:mod:`titan.u9.texture`'s own PNG output
matches the game's real images with no flip needed). OBJ/OpenGL's own
texture-space convention is the opposite, V=0 at the *bottom* -- so
writing the raw UV straight into a ``vt`` line, as an earlier version
of this module did, renders every texture upside down once loaded
through a real OBJ/MTL consumer (confirmed on a real export: a
character's face rendered with forehead-as-chin and eyebrows-as-jaw,
and a leather apron rendered leather-side-down). ``export_obj`` flips
V (``1.0 - v``) when writing ``vt`` lines to correct this; nothing
else in this module (or in :mod:`titan.u9.texture`'s own PNG output)
needs to change, since the flip is purely an OBJ-file-format
requirement, not a property of the source data.

STL is geometry-only by format limitation -- it has no material, UV,
or per-vertex-normal concept at all (ASCII/binary STL is a flat list of
triangles with one face normal each), so "textures applied" doesn't
apply there; :func:`export_stl` exports triangulated world-space
geometry only.

**Static bind pose only (minor, cosmetic)**: both exporters use each
limb's single stored transform (see :class:`titan.u9.model.U9Limb`),
not a real animated/posed configuration (``static/anim.flx`` isn't
implemented -- see ``reference/u9/anim/u9_anim_flx_reference.md`` for
exploratory notes). This can leave a small sub-mesh in an unposed
resting position (e.g. not tucked/folded the way it would be
mid-animation). Note: an earlier version of this docstring attributed
a dragon wing's hand/claw sub-mesh showing a patch of the shared
atlas's face graphic to *this* limitation -- that was wrong. That
symptom was actually the UV V-flip bug above (the wing's claw
happened to sample a UV region that, unflipped, landed on the face
texture); it's gone as of the V-flip fix, confirmed by re-rendering
model 3623. Genuine bind-pose-only effects are limb *positioning*
only and never change which texture region a triangle samples.
"""

from __future__ import annotations

__all__ = ["export_obj", "export_stl", "MeshExportError"]

import os
import struct
from dataclasses import dataclass
from typing import Callable, Optional

from titan.u9.model import U9Model
from titan.u9.texture import U9TextureFrame
from titan.u9.transform import IDENTITY, Mat4, mat4_multiply, mat4_trs, transform_normal, transform_point

Vec3 = tuple[float, float, float]
TextureResolver = Callable[[int, int], Optional[U9TextureFrame]]
"""``(texture_id, frame) -> U9TextureFrame | None``."""


class MeshExportError(Exception):
    """Raised when a model has no geometry at the requested LOD, or another export precondition fails."""


@dataclass(frozen=True)
class _FlatVertex:
    position: Vec3
    normal: Vec3
    uv: tuple[float, float]
    material_key: tuple[int, int]  # (texture_id, cur_frame)


def _world_matrices(model: U9Model) -> dict[int, Mat4]:
    """Resolve each limb's world matrix by walking its parent chain (memoized, cycle-safe)."""
    by_id = {limb.limb_id: limb for limb in model.limbs}
    resolved: dict[int, Mat4] = {}

    def resolve(limb_id: int, _visiting: frozenset[int] = frozenset()) -> Mat4:
        if limb_id in resolved:
            return resolved[limb_id]
        limb = by_id.get(limb_id)
        if limb is None:
            return IDENTITY

        local = mat4_trs(limb.position, limb.rotation, limb.scale)
        if limb.is_root or limb.parent_id in _visiting or limb.parent_id not in by_id:
            world = local
        else:
            parent_world = resolve(limb.parent_id, _visiting | {limb_id})
            world = mat4_multiply(parent_world, local)

        resolved[limb_id] = world
        return world

    for limb in model.limbs:
        resolve(limb.limb_id)
    return resolved


def _flatten(model: U9Model, lod_level: int, reverse_winding: bool) -> list[tuple[_FlatVertex, _FlatVertex, _FlatVertex]]:
    world_matrices = _world_matrices(model)
    triangles: list[tuple[_FlatVertex, _FlatVertex, _FlatVertex]] = []

    for limb in model.limbs:
        if lod_level >= len(limb.lods):
            continue
        lod = limb.lods[lod_level]
        if lod is None:
            continue
        world = world_matrices.get(limb.limb_id, IDENTITY)

        for tri in lod.triangles:
            material = lod.materials[tri.material_index] if lod.materials else None
            if material is not None and material.is_invisible:
                continue
            material_key = (material.texture_id, material.cur_frame) if material is not None else (0xFFFF, 0)

            flat_corners = []
            for corner in tri.corners:
                pos = transform_point(world, lod.vertices[corner.vertex_index])
                normal = transform_normal(world, corner.normal)
                flat_corners.append(_FlatVertex(position=pos, normal=normal, uv=corner.uv, material_key=material_key))

            if reverse_winding:
                flat_corners = [flat_corners[0], flat_corners[2], flat_corners[1]]
            triangles.append((flat_corners[0], flat_corners[1], flat_corners[2]))

    return triangles


def _material_name(texture_id: int, frame: int) -> str:
    return f"tex_{texture_id}_{frame}" if texture_id != 0xFFFF else "untextured"


def export_obj(
    model: U9Model,
    output_path: str,
    *,
    lod_level: int = 0,
    scale: float = 1.0 / 40.0,
    reverse_winding: bool = True,
    texture_resolver: Optional[TextureResolver] = None,
) -> None:
    """
    Export ``model`` to an OBJ + MTL (+ one PNG per used texture) file set.

    ``output_path`` is the ``.obj`` path; the ``.mtl`` and any ``.png``
    files are written alongside it with matching stems.
    ``texture_resolver`` is any callable ``(texture_id, frame) ->
    U9TextureFrame | None`` (e.g. built from a texture FLX archive via
    :func:`titan.u9.texture.decode_frame`) -- return ``None`` for a
    material to fall back to an untextured (flat alpha) MTL entry.
    """
    triangles = _flatten(model, lod_level, reverse_winding)
    if not triangles:
        raise MeshExportError(f"model {model.model_id} has no visible geometry at LOD {lod_level}")

    base = os.path.splitext(output_path)[0]
    mtl_path = base + ".mtl"
    mtl_name = os.path.basename(mtl_path)

    positions, uvs, normals, faces_by_material = _build_obj_tables(triangles, scale)

    with open(output_path, "w", encoding="ascii", errors="replace") as f:
        f.write(f"# Exported by titan u9 model-export (model {model.model_id}, LOD {lod_level})\n")
        f.write(f"mtllib {mtl_name}\n")
        for p in positions:
            f.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
        for uv in uvs:
            f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
        for n in normals:
            f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
        for key, faces in faces_by_material.items():
            f.write(f"usemtl {_material_name(*key)}\n")
            for vi1, ti1, ni1, vi2, ti2, ni2, vi3, ti3, ni3 in faces:
                f.write(f"f {vi1}/{ti1}/{ni1} {vi2}/{ti2}/{ni2} {vi3}/{ti3}/{ni3}\n")

    _write_mtl(mtl_path, faces_by_material.keys(), texture_resolver)


_ObjFace = tuple[int, int, int, int, int, int, int, int, int]


def _build_obj_tables(
    triangles: list[tuple[_FlatVertex, _FlatVertex, _FlatVertex]], scale: float
) -> tuple[list[Vec3], list[tuple[float, float]], list[Vec3], dict[tuple[int, int], list[_ObjFace]]]:
    """Build deduplicated, 1-based-indexed OBJ position/uv/normal tables plus per-material face lists."""
    positions: list[Vec3] = []
    normals: list[Vec3] = []
    uvs: list[tuple[float, float]] = []
    position_index: dict[Vec3, int] = {}
    normal_index: dict[Vec3, int] = {}
    uv_index: dict[tuple[float, float], int] = {}

    def index_of(value, store, index_map):
        idx = index_map.get(value)
        if idx is None:
            store.append(value)
            idx = len(store)  # OBJ indices are 1-based
            index_map[value] = idx
        return idx

    faces_by_material: dict[tuple[int, int], list[_ObjFace]] = {}
    for a, b, c in triangles:
        key = a.material_key
        face_indices = []
        for v in (a, b, c):
            pos = (v.position[0] * scale, v.position[1] * scale, v.position[2] * scale)
            # OBJ/OpenGL texture-space convention is V=0 at the bottom of the image;
            # the raw parsed UV is V=0 at the top (see module docstring) -- flip here.
            obj_uv = (v.uv[0], 1.0 - v.uv[1])
            face_indices.append(index_of(pos, positions, position_index))
            face_indices.append(index_of(obj_uv, uvs, uv_index))
            face_indices.append(index_of(v.normal, normals, normal_index))
        faces_by_material.setdefault(key, []).append(tuple(face_indices))  # type: ignore[arg-type]

    return positions, uvs, normals, faces_by_material


def _write_mtl(mtl_path: str, keys, texture_resolver: Optional[TextureResolver]) -> None:
    from PIL import Image

    base_dir = os.path.dirname(mtl_path)
    with open(mtl_path, "w", encoding="ascii", errors="replace") as f:
        for texture_id, frame in keys:
            name = _material_name(texture_id, frame)
            f.write(f"newmtl {name}\n")
            f.write("Ka 1.000 1.000 1.000\n")
            f.write("Kd 1.000 1.000 1.000\n")
            f.write("d 1.0\n")

            if texture_id == 0xFFFF:
                f.write("\n")
                continue

            frame_data = texture_resolver(texture_id, frame) if texture_resolver is not None else None
            if frame_data is None:
                f.write("\n")
                continue

            png_name = f"{name}.png"
            img = Image.frombytes("RGBA", (frame_data.width, frame_data.height), frame_data.pixels_rgba)
            img.save(os.path.join(base_dir, png_name))
            f.write(f"map_Kd {png_name}\n\n")


def export_stl(
    model: U9Model,
    output_path: str,
    *,
    lod_level: int = 0,
    scale: float = 1.0 / 40.0,
    reverse_winding: bool = True,
    binary: bool = True,
) -> None:
    """
    Export ``model`` to STL: flattened, world-space, geometry-only
    (STL has no material/UV/hierarchy concept -- see module docstring).
    """
    triangles = _flatten(model, lod_level, reverse_winding)
    if not triangles:
        raise MeshExportError(f"model {model.model_id} has no visible geometry at LOD {lod_level}")

    if binary:
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 80)
            f.write(struct.pack("<I", len(triangles)))
            for a, b, c in triangles:
                nx, ny, nz = a.normal
                f.write(struct.pack("<3f", nx, ny, nz))
                for v in (a, b, c):
                    f.write(struct.pack("<3f", v.position[0] * scale, v.position[1] * scale, v.position[2] * scale))
                f.write(struct.pack("<H", 0))
    else:
        with open(output_path, "w", encoding="ascii", errors="replace") as f:
            f.write(f"solid model_{model.model_id}\n")
            for a, b, c in triangles:
                f.write(f"facet normal {a.normal[0]:.6f} {a.normal[1]:.6f} {a.normal[2]:.6f}\n")
                f.write("outer loop\n")
                for v in (a, b, c):
                    f.write(f"vertex {v.position[0]*scale:.6f} {v.position[1]*scale:.6f} {v.position[2]*scale:.6f}\n")
                f.write("endloop\nendfacet\n")
            f.write(f"endsolid model_{model.model_id}\n")
