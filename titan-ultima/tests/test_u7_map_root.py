"""Tests for rendering U7 map data from a root separate from STATIC assets."""

from __future__ import annotations

import struct
from pathlib import Path

from typer.testing import CliRunner

from titan.u7 import cli as u7_cli
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
