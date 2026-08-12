"""Tests for standalone UW2 executable-model OBJ export."""

from pathlib import Path
import json

from PIL import Image

from titan.uw2.exe_models import ModelTriangle, ModelVertex, UW2Model
from titan.uw2.model_export import export_decoded_model
from titan.uw2.palette import UW2Palette


def test_exports_obj_materials_texture_and_metadata(tmp_path: Path) -> None:
    palette_colors = [(0, 0, 0)] * 256
    palette_colors[12] = (64, 128, 192)
    palette = UW2Palette(tuple(palette_colors))
    model = UW2Model(
        index=0x18,
        source_offset=123,
        extents=(1.0, 1.0, 1.0),
        triangles=(
            ModelTriangle(
                vertices=(
                    ModelVertex(0.0, 0.0, 0.0),
                    ModelVertex(1.0, 0.0, 0.0),
                    ModelVertex(0.0, 1.0, 0.0),
                ),
                palette_index=12,
            ),
            ModelTriangle(
                vertices=(
                    ModelVertex(0.0, 0.0, 1.0, 0.0, 0.0),
                    ModelVertex(1.0, 0.0, 1.0, 1.0, 0.0),
                    ModelVertex(0.0, 1.0, 1.0, 0.0, 1.0),
                ),
                palette_index=12,
                texture_id=6,
                textured=True,
            ),
        ),
        origin=(0.25, -0.5, 0.5),
        collision_half_extents=(0.5, 0.5, 0.5),
    )

    obj_path = export_decoded_model(
        model,
        palette,
        tmp_path,
        item_id=0x0158,
        name="table",
        texture_index=32,
        texture_image=Image.new("RGBA", (2, 2), (255, 0, 0, 255)),
    )

    obj = obj_path.read_text(encoding="ascii")
    mtl = obj_path.with_suffix(".mtl").read_text(encoding="ascii")
    assert "usemtl palette_012" in obj
    assert "usemtl tmobj_032" in obj
    assert "v -0.25000000 0.50000000 0.00000000" in obj
    assert "vt 0.00000000 1.00000000" in obj
    assert "Kd 0.250980 0.501961 0.752941" in mtl
    assert "map_Kd tmobj_032.png" in mtl
    assert (tmp_path / "tmobj_032.png").is_file()
    assert (tmp_path / "metadata.json").is_file()
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["origin"] == [0.25, -0.5, 0.5]
    assert metadata["placement_origin"] == [0.25, -0.5, 0.0]
