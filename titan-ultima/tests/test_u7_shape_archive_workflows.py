"""Sparse patch inheritance must agree across reading and shape insertion."""

from pathlib import Path
import json

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape
from titan.u7.shape_archive import U7ShapeArchive


@pytest.fixture(autouse=True)
def isolate_install_config(monkeypatch):
    monkeypatch.setattr("titan._config._config", {})
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})


def shape_bytes(index: int) -> bytes:
    shape = U7Shape()
    frame = U7Shape.Frame()
    frame.width = frame.height = 2
    frame.pixels = np.full((2, 2), index, dtype=np.uint8)
    shape.frames.append(frame)
    return shape.to_bytes()


def write_archive(path: Path, records: list[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    archive = U7FlexArchive()
    archive.records = records
    path.write_bytes(archive.to_bytes())


@pytest.fixture
def archives(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "game/STATIC/SHAPES.VGA"
    patch = tmp_path / "game/mods/example/patch/shapes.vga"
    write_archive(
        base, [b""] * 150 + [shape_bytes(224), shape_bytes(7), shape_bytes(8)]
    )
    write_archive(patch, [b""] * 151 + [shape_bytes(9)])
    (base.parent / "TFA.DAT").write_bytes(bytes(3 * 1024))
    return base, patch


def test_resolves_holes_and_records_beyond_patch_count_without_flattening(archives):
    base, patch = archives
    before = patch.read_bytes()
    resolved = U7ShapeArchive.from_file(str(patch))
    assert resolved.base_fill_count == 2
    assert resolved.effective.records[150] == shape_bytes(224)
    assert resolved.effective.records[151] == shape_bytes(9)
    assert resolved.effective.records[152] == shape_bytes(8)
    assert resolved.selected.records[150] == b""
    assert patch.read_bytes() == before
    assert U7ShapeArchive.from_file(str(base)).base is None


@pytest.mark.parametrize(
    "command",
    [
        "shape-export",
        "shape-batch",
        "shape-animate",
        "shape-frame-report",
        "shape-cycle-scan",
    ],
)
def test_shape_commands_read_inherited_records(command, archives, tmp_path):
    base, patch = archives
    output = tmp_path / (
        "result.gif"
        if command == "shape-animate"
        else "report.json"
        if command == "shape-frame-report"
        else "output"
    )
    args = [command, str(patch), "-o", str(output)]
    if command == "shape-export":
        args += ["--shape", "150", "--indexed"]
    elif command in {"shape-batch", "shape-cycle-scan"}:
        args += ["--range-start", "150", "--range-end", "153"]
        if command == "shape-batch":
            args += ["--indexed"]
        else:
            args += ["--static", str(base.parent)]
    elif command == "shape-animate":
        args += ["--shape", "150", "--mode", "cycle", "--steps", "2"]
    else:
        args += ["--format", "json"]
    result = CliRunner().invoke(u7_app, args)
    assert result.exit_code == 0, result.output
    if command == "shape-frame-report":
        report = json.loads(output.read_text())
        assert report["populated_shape_count"] == 3
        assert report["shape_count"] == 153
    elif command == "shape-animate":
        with Image.open(output) as image:
            assert image.size == (2, 2)
    else:
        pngs = list(output.rglob("*.png"))
        assert len(pngs) == (3 if command == "shape-batch" else 1)
        image_path = next(p for p in pngs if "0150" in p.name)
        with Image.open(image_path) as image:
            assert image.getpixel((0, 0)) == 224


def test_add_checks_combined_occupancy_and_keeps_patch_sparse(archives, tmp_path):
    base, patch = archives
    before = (base.read_bytes(), patch.read_bytes())
    shape = tmp_path / "new.shp"
    shape.write_bytes(shape_bytes(10))
    output = tmp_path / "new.vga"
    result = CliRunner().invoke(
        u7_app, ["flex-add-shape", str(patch), str(shape), "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    updated = U7FlexArchive.from_file(str(output))
    assert updated.records[:152] == U7FlexArchive.from_file(str(patch)).records
    assert updated.records[152] == b""
    assert updated.records[153] == shape.read_bytes()
    assert (base.read_bytes(), patch.read_bytes()) == before


@pytest.mark.parametrize("index", [150, 152])
def test_inherited_slots_require_replace_even_beyond_patch_count(
    index, archives, tmp_path
):
    _, patch = archives
    shape = tmp_path / "new.shp"
    shape.write_bytes(shape_bytes(10))
    output = tmp_path / "new.vga"
    args = [
        "flex-add-shape",
        str(patch),
        str(shape),
        "-o",
        str(output),
        "--index",
        str(index),
    ]
    runner = CliRunner()
    denied = runner.invoke(u7_app, args)
    assert denied.exit_code == 1
    assert "occupied" in denied.output
    assert not output.exists()
    allowed = runner.invoke(u7_app, args + ["--replace"])
    assert allowed.exit_code == 0, allowed.output
    updated = U7FlexArchive.from_file(str(output))
    assert updated.records[index] == shape.read_bytes()
    assert updated.records[149] == b""


def test_explicit_base_for_renamed_copies(archives, tmp_path):
    base, patch = archives
    copied = tmp_path / "renamed.vga"
    copied.write_bytes(patch.read_bytes())
    result = CliRunner().invoke(
        u7_app,
        [
            "shape-export",
            str(copied),
            "--base-archive",
            str(base),
            "--shape",
            "152",
            "-o",
            str(tmp_path / "pngs"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_cannot_allocate_in_unresolved_patch(tmp_path):
    patch = tmp_path / "patch/shapes.vga"
    write_archive(patch, [])
    shape = tmp_path / "new.shp"
    shape.write_bytes(shape_bytes(7))
    output = tmp_path / "new.vga"
    result = CliRunner().invoke(
        u7_app, ["flex-add-shape", str(patch), str(shape), "-o", str(output)]
    )
    assert result.exit_code == 1
    assert "--base-archive" in result.output
    assert not output.exists()


def test_exult_base_is_included_when_allocating_sparse_archive(
    archives, tmp_path, monkeypatch
):
    base, _ = archives
    monkeypatch.setattr(
        "titan.u7.install.exult_game_paths", lambda game: {"static": base.parent}
    )
    patch = tmp_path / "elsewhere" / "patch" / "shapes.vga"
    write_archive(patch, [])
    shape = tmp_path / "new.shp"
    shape.write_bytes(shape_bytes(7))
    output = tmp_path / "new.vga"
    result = CliRunner().invoke(
        u7_app, ["flex-add-shape", str(patch), str(shape), "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    archive = U7FlexArchive.from_file(str(output), strict=True)
    assert archive.records[150:153] == [b"", b"", b""]
    assert archive.records[153] == shape_bytes(7)


def test_custom_mod_library_can_be_used_without_a_retail_base(tmp_path):
    archive = tmp_path / "patch/custom.vga"
    write_archive(archive, [])
    shape = tmp_path / "new.shp"
    shape.write_bytes(shape_bytes(7))
    output = tmp_path / "new.vga"
    result = CliRunner().invoke(
        u7_app,
        [
            "flex-add-shape",
            str(archive),
            str(shape),
            "--archive-kind",
            "generic",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert U7FlexArchive.from_file(str(output)).records == [shape.read_bytes()]


def test_case_independent_other_archive_and_explicit_base_errors(tmp_path):
    base = tmp_path / "game/static/FACES.VGA"
    patch = tmp_path / "game/mods/example/patch/faces.vga"
    write_archive(base, [shape_bytes(7)])
    write_archive(patch, [])
    resolved = U7ShapeArchive.from_file(str(patch))
    assert resolved.effective.records == [shape_bytes(7)]
    with pytest.raises(ValueError, match="distinct"):
        U7ShapeArchive.from_file(str(patch), base_archive=str(patch))
    with pytest.raises(FileNotFoundError):
        U7ShapeArchive.from_file(str(patch), base_archive=str(tmp_path / "missing.vga"))


def test_allocation_reuses_only_slots_empty_in_both_archives(archives, tmp_path):
    base, patch = archives
    archive = U7FlexArchive.from_file(str(base))
    archive.records[152] = b""
    base.write_bytes(archive.to_bytes())
    shape = tmp_path / "new.shp"
    shape.write_bytes(shape_bytes(7))
    output = tmp_path / "new.vga"
    result = CliRunner().invoke(
        u7_app, ["flex-add-shape", str(patch), str(shape), "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert len(U7FlexArchive.from_file(str(output)).records) == 153


def test_flat_slots_inherited_from_base_are_occupied(tmp_path):
    base = tmp_path / "game/STATIC/SHAPES.VGA"
    patch = tmp_path / "game/mods/example/patch/shapes.vga"
    write_archive(base, [bytes([7]) * 64] * 150)
    write_archive(patch, [])
    shape = tmp_path / "flat.shp"
    shape.write_bytes(bytes([8]) * 64)
    output = tmp_path / "new.vga"
    result = CliRunner().invoke(
        u7_app, ["flex-add-shape", str(patch), str(shape), "--flat", "-o", str(output)]
    )
    assert result.exit_code == 1
    assert "No free" in result.output
    assert not output.exists()


def test_effective_inventory_keeps_empty_base_tail_slots(tmp_path):
    base = tmp_path / "game/STATIC/SHAPES.VGA"
    patch = tmp_path / "game/mods/example/patch/shapes.vga"
    write_archive(base, [b""] * 200)
    write_archive(patch, [b""] * 150 + [shape_bytes(7)])
    resolved = U7ShapeArchive.from_file(str(patch))
    assert len(resolved.effective.records) == 200
    assert resolved.base_fill_count == 0
