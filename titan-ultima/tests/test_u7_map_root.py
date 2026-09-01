"""Tests for rendering U7 map data from a root separate from STATIC assets."""

from __future__ import annotations

import struct
from pathlib import Path

from typer.testing import CliRunner

from titan.u7 import cli as u7_cli
from titan.u7.flex import U7FlexArchive
from titan.u7.map import U7MapRenderer


def _write_native_map_data(map_root: Path, map_number: int) -> None:
    map_directory = map_root / f"map{map_number:02x}"
    map_directory.mkdir(parents=True)

    u7map = bytearray(144 * 256 * 2)
    struct.pack_into("<H", u7map, 0, 1)
    (map_directory / "u7map").write_bytes(u7map)

    definition_zero = bytes(512)
    definition_one = bytes((7, 3 << 2)) * 256
    (map_root / "u7chunks").write_bytes(definition_zero + definition_one)


def _write_shapes_archive(path: Path, records: list[bytes]) -> None:
    archive = U7FlexArchive()
    archive.records = records
    archive.save(str(path))


def test_patch_base_static_is_inferred_from_game_install_tree(tmp_path: Path) -> None:
    game_root = tmp_path / "ULTIMA7"
    base_static = game_root / "STATIC"
    patch_static = game_root / "mods" / "MyMod" / "patch"
    base_static.mkdir(parents=True)
    patch_static.mkdir(parents=True)
    (base_static / "SHAPES.VGA").write_bytes(b"placeholder")

    resolved = u7_cli._resolve_u7_patch_base_static(str(patch_static), None)

    assert resolved == str(base_static)


def test_renderer_reads_native_map_files_from_separate_map_root(
    tmp_path: Path,
) -> None:
    static_dir = tmp_path / "static-assets"
    map_root = tmp_path / "scratch-map"
    static_dir.mkdir()
    _write_native_map_data(map_root, 4)

    renderer = U7MapRenderer(
        str(static_dir),
        map_num=4,
        map_root=str(map_root),
    )

    assert renderer.static_dir == str(static_dir)
    assert renderer.map_root == str(map_root)
    assert renderer.terrain_map[0][0] == 1
    assert renderer.terrains[1][0] == (7, 3)


def test_renderer_default_map_root_remains_static_directory(tmp_path: Path) -> None:
    static_dir = tmp_path / "combined-static"
    static_dir.mkdir()
    _write_native_map_data(static_dir, 4)

    renderer = U7MapRenderer(str(static_dir), map_num=4)

    assert renderer.map_root == str(static_dir)
    assert renderer.terrain_map[0][0] == 1
    assert renderer.terrains[1][0] == (7, 3)


def test_renderer_fills_sparse_patch_shapes_from_base(tmp_path: Path) -> None:
    base_static = tmp_path / "base-static"
    patch_static = tmp_path / "patch-static"
    base_static.mkdir()
    patch_static.mkdir()
    _write_shapes_archive(
        base_static / "SHAPES.VGA",
        [b"base-zero", b"base-one", b"base-two"],
    )
    _write_shapes_archive(
        patch_static / "SHAPES.VGA",
        [b"", b"patch-one", b"", b"patch-three"],
    )

    renderer = U7MapRenderer(
        str(patch_static),
        base_static_dir=str(base_static),
    )

    assert renderer.shapes_vga.records == [
        b"base-zero",
        b"patch-one",
        b"base-two",
        b"patch-three",
    ]
    assert renderer.shapes_vga_base_fill_count == 2


def test_renderer_leaves_complete_shapes_archive_unchanged(tmp_path: Path) -> None:
    base_static = tmp_path / "base-static"
    selected_static = tmp_path / "selected-static"
    base_static.mkdir()
    selected_static.mkdir()
    _write_shapes_archive(base_static / "SHAPES.VGA", [b"base-zero"])
    _write_shapes_archive(
        selected_static / "SHAPES.VGA",
        [b"selected-zero", b"selected-one"],
    )

    renderer = U7MapRenderer(
        str(selected_static),
        base_static_dir=str(base_static),
    )

    assert renderer.shapes_vga.records == [b"selected-zero", b"selected-one"]
    assert renderer.shapes_vga_base_fill_count == 0


def test_renderer_without_base_keeps_sparse_shapes_archive(tmp_path: Path) -> None:
    selected_static = tmp_path / "selected-static"
    selected_static.mkdir()
    _write_shapes_archive(
        selected_static / "SHAPES.VGA",
        [b"", b"selected-one"],
    )

    renderer = U7MapRenderer(str(selected_static))

    assert renderer.shapes_vga.records == [b"", b"selected-one"]
    assert renderer.shapes_vga_base_fill_count == 0


def test_map_render_cli_forwards_optional_map_root(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_map_render(args) -> int:
        captured["static"] = args.static
        captured["map_root"] = args.map_root
        captured["map_num"] = args.map_num
        return 0

    monkeypatch.setattr(u7_cli, "cmd_map_render", capture_map_render)
    static_dir = tmp_path / "static-assets"
    map_root = tmp_path / "scratch-map"

    result = CliRunner().invoke(
        u7_cli.u7_app,
        [
            "map-render",
            str(static_dir),
            "--map-root",
            str(map_root),
            "--map-num",
            "4",
            "--sc",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "static": str(static_dir),
        "map_root": str(map_root),
        "map_num": 4,
    }


def test_map_render_uses_configured_game_static_as_patch_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    patch_static = tmp_path / "patch"
    base_static = tmp_path / "base-static"
    patch_static.mkdir()
    base_static.mkdir()
    (patch_static / "SHAPES.VGA").write_bytes(b"placeholder")
    (base_static / "SHAPES.VGA").write_bytes(b"placeholder")
    palette_path = base_static / "PALETTES.FLX"
    palette_path.write_bytes(b"placeholder")
    captured: dict[str, object] = {}

    class FakeRenderer:
        PROJECTIONS: dict[str, dict[str, object]] = {"classic": {}}

        def __init__(
            self,
            static_dir: str,
            map_num: int = 0,
            *,
            map_root: str | None = None,
            base_static_dir: str | None = None,
            game: str = "bg",
        ) -> None:
            captured.update(
                static_dir=static_dir,
                map_num=map_num,
                map_root=map_root,
                base_static_dir=base_static_dir,
                game=game,
            )

        @property
        def shapes_vga_base_fill_count(self) -> int:
            return 0

    monkeypatch.setattr(
        u7_cli,
        "_resolve_u7_paths",
        lambda game: (str(base_static), str(palette_path)),
    )
    monkeypatch.setattr("titan.u7.map.U7MapRenderer", FakeRenderer)
    monkeypatch.setattr(
        "titan.u7.palette.U7Palette.from_file",
        staticmethod(lambda path: object()),
    )

    result = u7_cli.cmd_map_render(
        u7_cli.SimpleNamespace(
            static=str(patch_static),
            game="si",
            map_root=None,
            palette=None,
            map_num=2,
            view="invalid",
        )
    )

    assert result == 1
    assert captured == {
        "static_dir": str(patch_static),
        "map_num": 2,
        "map_root": None,
        "base_static_dir": str(base_static),
        "game": "si",
    }
