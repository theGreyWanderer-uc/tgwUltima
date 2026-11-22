"""Tests for rendering U7 map data from a root separate from STATIC assets."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from typer.testing import CliRunner

from titan.u7 import cli as u7_cli
from titan.u7 import install as u7_install
from titan.u7.flex import U7FlexArchive
from titan.u7.map import U7MapRenderer, _frame_to_rgba, _load_map_font
from titan.u7.shape import U7Shape


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

    resolved = u7_install.resolve_u7_patch_base_static(str(patch_static), None)

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

    monkeypatch.setattr(u7_cli.maps, "cmd_map_render", capture_map_render)
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
        u7_install,
        "resolve_u7_static_and_palette",
        lambda game: (str(base_static), str(palette_path)),
    )
    monkeypatch.setattr("titan.u7.map.U7MapRenderer", FakeRenderer)
    monkeypatch.setattr(
        "titan.u7.palette.U7Palette.from_file",
        staticmethod(lambda path: object()),
    )

    result = u7_cli.maps.cmd_map_render(
        u7_cli.maps.SimpleNamespace(
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


def test_map_frame_without_pixels_has_a_clear_error() -> None:
    with pytest.raises(ValueError, match="U7 frame has no pixel data"):
        _frame_to_rgba(U7Shape.Frame(), bytes(768))


def test_map_font_fallback_can_draw_when_arial_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = ImageFont.load_default()

    def missing_font(*args, **kwargs):
        raise OSError("Arial unavailable")

    monkeypatch.setattr(ImageFont, "truetype", missing_font)
    monkeypatch.setattr(ImageFont, "load_default", lambda: fallback)
    font = _load_map_font(18)
    image = Image.new("L", (100, 30))
    ImageDraw.Draw(image).text((0, 0), "SC 0", fill=255, font=font)
    assert image.getbbox() is not None


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--full"], 0.25),
        (["--full", "--resolution", "50"], 0.5),
        (["--full", "--resolution", "full"], 1.0),
        (["--sc", "0"], 1.0),
        (["--sc", "0", "--resolution", "75"], 0.75),
    ],
)
def test_map_render_resolution_defaults_to_a_quarter_for_the_full_world(
    tmp_path: Path, monkeypatch, arguments: list[str], expected: float
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        u7_cli.maps,
        "cmd_map_render",
        lambda args: captured.update(resolution=args.resolution) or 0,
    )

    result = CliRunner().invoke(
        u7_cli.u7_app, ["map-render", str(tmp_path), *arguments]
    )

    assert result.exit_code == 0, result.output
    assert captured == {"resolution": expected}


def _fake_render(tmp_path: Path, monkeypatch) -> dict[str, object]:
    """Run cmd_map_render against a stub renderer; return what it was asked."""
    static = tmp_path / "static"
    static.mkdir(exist_ok=True)
    (static / "SHAPES.VGA").write_bytes(b"placeholder")
    (static / "PALETTES.FLX").write_bytes(b"placeholder")
    captured: dict[str, object] = {}

    class FakeRenderer:
        PROJECTIONS: dict[str, dict[str, object]] = {"classic": {}}
        shapes_vga_base_fill_count = 0

        def __init__(self, *args, **kwargs) -> None:
            pass

        def render_superchunk(self, sc, palette, **options):
            captured["call"] = ("superchunk", sc)
            return Image.new("RGBA", (2, 2))

        def render_region(self, cx0, cy0, cx1, cy1, palette, **options):
            captured["call"] = (
                "region",
                (cx0, cy0, cx1, cy1),
                options.get("resolution"),
            )
            return Image.new("RGBA", (2, 2))

    def fake_export_output(value, game, command, default):
        captured["name"] = default
        return str(tmp_path / default)

    monkeypatch.setattr("titan.u7.map.U7MapRenderer", FakeRenderer)
    monkeypatch.setattr(
        "titan.u7.palette.U7Palette.from_file", staticmethod(lambda path: object())
    )
    monkeypatch.setattr(u7_cli.maps, "export_output", fake_export_output)
    captured["static"] = str(static)
    return captured


def _render_args(static: str, **overrides) -> object:
    values = dict(
        static=static,
        game="si",
        map_root=None,
        palette=None,
        map_num=1,
        view="classic",
        output=None,
        superchunk=None,
        chunk_x0=0,
        chunk_y0=0,
        chunk_x1=None,
        chunk_y1=None,
        exclude_flags=None,
        gamedat=None,
        grid=False,
        grid_size=1,
        max_lift=None,
    )
    values.update(overrides)
    return u7_cli.maps.SimpleNamespace(**values)


def test_full_world_default_name_carries_game_map_and_size(
    tmp_path: Path, monkeypatch
) -> None:
    captured = _fake_render(tmp_path, monkeypatch)
    args = _render_args(captured["static"], chunk_x1=191, chunk_y1=191, resolution=0.25)

    assert u7_cli.maps.cmd_map_render(args) == 0
    assert captured["call"] == ("region", (0, 0, 191, 191), 0.25)
    assert captured["name"] == "u7_si_map01_full_classic_25pct.png"


def test_scaled_superchunk_renders_as_its_chunk_range(
    tmp_path: Path, monkeypatch
) -> None:
    captured = _fake_render(tmp_path, monkeypatch)
    args = _render_args(captured["static"], superchunk=13, resolution=0.5)

    assert u7_cli.maps.cmd_map_render(args) == 0
    assert captured["call"] == ("region", (16, 16, 31, 31), 0.5)
    assert captured["name"] == "u7_si_map01_sc0D_classic_50pct.png"


def test_full_size_superchunk_keeps_the_superchunk_renderer(
    tmp_path: Path, monkeypatch
) -> None:
    captured = _fake_render(tmp_path, monkeypatch)
    args = _render_args(captured["static"], superchunk=13, map_num=0, game="bg")

    assert u7_cli.maps.cmd_map_render(args) == 0
    assert captured["call"] == ("superchunk", 13)
    assert captured["name"] == "u7_bg_map00_sc0D_classic.png"
