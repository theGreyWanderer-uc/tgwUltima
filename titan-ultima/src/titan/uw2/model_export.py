"""OBJ, MTL, texture, and metadata export for UU2 executable models."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

from PIL import Image

from titan.uw2.exe_models import (
    ITEM_MODEL_INDEX,
    ModelTriangle,
    UW2Model,
    UW2ModelArchive,
)
from titan.uw2.gr import UW2GRArchive
from titan.uw2.model_render import ITEM_MODEL_NAMES, model_texture_index
from titan.uw2.palette import UW2Palette


class UW2ModelExportError(ValueError):
    """Raised when a built-in model cannot be exported."""


def export_object_models(
    source: str | Path,
    output: str | Path,
    *,
    item_ids: Iterable[int] | None = None,
    flags: int = 0,
) -> list[Path]:
    """Export selected items, or every mapped item, from original UU2 files."""
    source_path = Path(source).expanduser()
    data_dir = (
        source_path if source_path.name.upper() == "DATA" else source_path / "DATA"
    )
    executable = data_dir.parent / "UW2.EXE"
    palette_path = data_dir / "PALS.DAT"
    tmobj_path = data_dir / "TMOBJ.GR"
    for path, label in (
        (executable, "UW2.EXE"),
        (palette_path, "PALS.DAT"),
        (tmobj_path, "TMOBJ.GR"),
    ):
        if not path.is_file():
            raise UW2ModelExportError(f"UU2 {label} not found: {path}")

    palette = UW2Palette.from_file(palette_path)
    allpals = data_dir / "ALLPALS.DAT"
    tmobj = UW2GRArchive.from_file(tmobj_path, allpals if allpals.is_file() else None)
    models = UW2ModelArchive.from_file(executable)
    requested = sorted(ITEM_MODEL_INDEX if item_ids is None else set(item_ids))
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    manifest: list[dict[str, object]] = []
    for item_id in requested:
        model_index = ITEM_MODEL_INDEX.get(item_id)
        if model_index is None:
            raise UW2ModelExportError(
                f"UU2 item {item_id:#06x} has no decoded built-in model"
            )
        model = models.model(model_index)
        texture_index = model_texture_index(item_id, flags)
        texture_image = None
        if texture_index is not None and any(
            triangle.textured for triangle in model.triangles
        ):
            texture_image = tmobj.image(texture_index).to_image(palette)

        name = ITEM_MODEL_NAMES.get(item_id, "object")
        item_dir = output_path / f"item_{item_id:03d}_{name}"
        obj_path = export_decoded_model(
            model,
            palette,
            item_dir,
            item_id=item_id,
            name=name,
            flags=flags,
            texture_index=texture_index,
            texture_image=texture_image,
        )
        written.append(obj_path)
        manifest.append(
            {
                "item_id": item_id,
                "item_id_hex": f"{item_id:#06x}",
                "name": name,
                "model_index": model.index,
                "obj": str(obj_path.relative_to(output_path)),
                "texture_index": texture_index,
                "triangle_count": len(model.triangles),
            }
        )

    (output_path / "manifest.json").write_text(
        json.dumps({"items": manifest}, indent=2), encoding="utf-8"
    )
    return written


def export_decoded_model(
    model: UW2Model,
    palette: UW2Palette,
    output: str | Path,
    *,
    item_id: int,
    name: str,
    flags: int = 0,
    texture_index: int | None = None,
    texture_image: Image.Image | None = None,
) -> Path:
    """Write one decoded model as portable OBJ, MTL, PNG, and JSON files."""
    if not model.triangles:
        raise UW2ModelExportError(f"UU2 model {model.index:#04x} contains no triangles")
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = f"{name}_item_{item_id:03d}_model_{model.index:02d}"
    obj_path = output_path / f"{stem}.obj"
    mtl_path = output_path / f"{stem}.mtl"
    texture_name = None
    if texture_image is not None and texture_index is not None:
        texture_name = f"tmobj_{texture_index:03d}.png"
        texture_image.save(output_path / texture_name)

    material_faces: dict[str, list[tuple[int, int]]] = {}
    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []
    for triangle in model.triangles:
        first = len(positions) + 1
        normal = _face_normal(triangle)
        for vertex in triangle.vertices:
            positions.append(model.local_position(vertex))
            uvs.append((vertex.u, 1.0 - vertex.v))
        normals.append(normal)
        material = (
            f"tmobj_{texture_index:03d}"
            if triangle.textured and texture_name is not None
            else f"palette_{triangle.palette_index:03d}"
        )
        material_faces.setdefault(material, []).append((first, len(normals)))

    lines = [
        f"# Exported by titan uw2 model-export: {name} {item_id:#06x}",
        f"mtllib {mtl_path.name}",
        f"o {stem}",
    ]
    lines.extend(f"v {x:.8f} {y:.8f} {z:.8f}" for x, y, z in positions)
    lines.extend(f"vt {u:.8f} {v:.8f}" for u, v in uvs)
    lines.extend(f"vn {x:.8f} {y:.8f} {z:.8f}" for x, y, z in normals)
    for material, faces in material_faces.items():
        lines.append(f"usemtl {material}")
        for first, normal_index in faces:
            lines.append(
                "f "
                + " ".join(
                    f"{vertex}/{vertex}/{normal_index}"
                    for vertex in (first, first + 1, first + 2)
                )
            )
    obj_path.write_text("\n".join(lines) + "\n", encoding="ascii")

    mtl_lines: list[str] = [f"# Materials for {stem}"]
    for material in material_faces:
        mtl_lines.append(f"newmtl {material}")
        mtl_lines.append("Ka 0.200000 0.200000 0.200000")
        if material.startswith("palette_"):
            palette_index = int(material.removeprefix("palette_"))
            red, green, blue = palette.colors[palette_index]
            mtl_lines.append(
                f"Kd {red / 255.0:.6f} {green / 255.0:.6f} {blue / 255.0:.6f}"
            )
        else:
            mtl_lines.append("Kd 1.000000 1.000000 1.000000")
            mtl_lines.append(f"map_Kd {texture_name}")
        mtl_lines.extend(("Ks 0.050000 0.050000 0.050000", "d 1.0", "illum 2", ""))
    mtl_path.write_text("\n".join(mtl_lines), encoding="ascii")

    metadata = {
        "item_id": item_id,
        "item_id_hex": f"{item_id:#06x}",
        "name": name,
        "model_index": model.index,
        "source_offset": model.source_offset,
        "extents": model.extents,
        "origin": model.origin,
        "placement_origin": model.placement_origin,
        "collision_half_extents": model.collision_half_extents,
        "triangle_count": len(model.triangles),
        "textured_triangle_count": sum(
            triangle.textured for triangle in model.triangles
        ),
        "texture_index": texture_index,
        "flags": flags,
        "roof_vertex_count": sum(
            vertex.roof for triangle in model.triangles for vertex in triangle.vertices
        ),
        "files": {
            "obj": obj_path.name,
            "mtl": mtl_path.name,
            "texture": texture_name,
        },
    }
    (output_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return obj_path


def _face_normal(triangle: ModelTriangle) -> tuple[float, float, float]:
    a, b, c = triangle.vertices
    ab = (b.x - a.x, b.y - a.y, b.z - a.z)
    ac = (c.x - a.x, c.y - a.y, c.z - a.z)
    normal = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    length = math.sqrt(sum(component * component for component in normal))
    if length == 0.0:
        return (0.0, 0.0, 1.0)
    return (normal[0] / length, normal[1] / length, normal[2] / length)
