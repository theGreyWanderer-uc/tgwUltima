"""Batch texture export coverage for quality tiers, frames, mips and palettes."""

from __future__ import annotations

import json
import struct

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan import _config
from titan.u9.cli import u9_app
from titan.u9.flx_writer import build_flx
from titan.u9.texture_export import U9TextureExportError, export_texture_archives


def _texture(
    frames: list[bytes],
    *,
    mips: int = 0,
    flags: int = 0x60000400,
    size: int = 2,
    compressed: bool = False,
) -> bytes:
    header = struct.pack(
        "<HBBHHII", size, mips, 0, size, int(compressed), len(frames), 0
    )
    directory = bytearray()
    payload = bytearray()
    for pixels in frames:
        frame = struct.pack("<5I", flags, size, size, 0, 0) + bytes(4 * size) + pixels
        directory.extend(
            struct.pack("<II", 16 + 8 * len(frames) + len(payload), len(frame))
        )
        payload.extend(frame)
    return header + directory + payload


def _table(frame_count: int = 1, selector: int = 0) -> bytes:
    return struct.pack("<12I", selector << 8, 0, 0, 0, 0, 2, 2, 0, 0, 2, 2, frame_count)


@pytest.fixture
def texture_install(tmp_path, monkeypatch):
    root = tmp_path / "GOG Games/Ultima 9"
    static = root / "STATIC"
    static.mkdir(parents=True)
    red = struct.pack("<H", 0xF800) * 5
    green = struct.pack("<H", 0x07E0) * 5
    entry = _texture([red, green], mips=1)
    for archive, table in (
        ("bitmap16.flx", "sdInfo16.flx"),
        ("bitmapC.flx", "sdInfoC.flx"),
        ("bitmapsh.flx", "sdInfo.flx"),
    ):
        (static / archive).write_bytes(build_flx({7: entry, 8: _texture([])}))
        (static / table).write_bytes(build_flx({7: _table(2)}))
    palette = bytearray(1024)
    palette[7 * 4 : 7 * 4 + 4] = bytes([9, 40, 200, 0])
    (static / "ankh.pal").write_bytes(palette)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(
        _config,
        "_config",
        {"u9": {"game": {"base": str(root)}, "paths": {"static": "STATIC"}}},
    )
    return root, static


def test_default_exports_only_highest_tier_and_base_frames(texture_install, tmp_path):
    root, static = texture_install
    before = {path.name: path.read_bytes() for path in static.iterdir()}
    output = tmp_path / "export"
    result = CliRunner().invoke(u9_app, ["texture-export-all", "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert {path.name for path in output.iterdir()} == {"bitmap16"}
    files = sorted((output / "bitmap16").glob("*.png"))
    assert [path.name for path in files] == [
        "texture_00007_frame_000_mip_00.png",
        "texture_00007_frame_001_mip_00.png",
    ]
    with Image.open(files[0]) as image:
        assert image.size == (2, 2)
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    manifest = json.loads((output / "bitmap16/manifest.json").read_text())
    assert manifest["entries_without_frames"] == [8]
    assert manifest["errors"] == []
    assert manifest["frames_written"] == 2
    assert "100%" in result.output
    assert {path.name: path.read_bytes() for path in static.iterdir()} == before


def test_all_mips_does_not_enable_lower_quality_tiers(texture_install, tmp_path):
    _, static = texture_install
    output = tmp_path / "export"
    result = export_texture_archives(static, output, all_mips=True)
    assert not result.errors
    assert result.images_written == 4
    assert {path.name for path in output.iterdir()} == {"bitmap16"}
    with Image.open(output / "bitmap16/texture_00007_frame_001_mip_01.png") as image:
        assert image.size == (1, 1)
        assert image.getpixel((0, 0)) == (0, 255, 0, 255)


def test_all_tiers_exports_base_only_unless_mips_requested(texture_install, tmp_path):
    root, _ = texture_install
    output = tmp_path / "export"
    result = export_texture_archives(root, output, all_tiers=True)
    assert not result.errors
    assert result.images_written == 6
    assert {path.name for path in output.iterdir()} == {
        "bitmap16",
        "bitmapC",
        "bitmapsh",
    }
    assert len(list(output.rglob("*mip_01.png"))) == 0


def test_single_archive_paletted_alpha_and_external_owner(texture_install, tmp_path):
    external = tmp_path / "other install/static"
    external.mkdir(parents=True)
    archive = external / "bitmapsh.flx"
    archive.write_bytes(
        build_flx({1: _texture([bytes([7, 254, 7, 7])], flags=0x20000000)})
    )
    palette = bytearray(1024)
    palette[28:32] = bytes([10, 20, 30, 0])
    (external / "ankh.pal").write_bytes(palette)
    output = tmp_path / "export"
    result = CliRunner().invoke(
        u9_app, ["texture-export-all", str(archive), "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    with Image.open(output / "bitmapsh/texture_00001_frame_000_mip_00.png") as image:
        assert image.getpixel((0, 0)) == (10, 20, 30, 255)
        assert image.getpixel((1, 0))[3] == 0
    (external / "ankh.pal").unlink()
    failed = export_texture_archives(archive, tmp_path / "missing palette")
    assert failed.errors
    assert "Paletted frame needs ankh.pal" in str(failed.errors)
    assert failed.images_written == 0


def test_format_table_overrides_damaged_frame_format(texture_install, tmp_path):
    _, static = texture_install
    # Stored code 1 would decode as ARGB1555; sdInfo's code 0 restores RGB565.
    archive = static / "bitmap16.flx"
    archive.write_bytes(
        build_flx({7: _texture([struct.pack("<H", 0xF800) * 4], flags=0x60000500)})
    )
    output = tmp_path / "export"
    result = export_texture_archives(archive, output)
    assert not result.errors
    with Image.open(output / "bitmap16/texture_00007_frame_000_mip_00.png") as image:
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)


def test_decode_failure_does_not_hide_later_entries(texture_install, tmp_path):
    _, static = texture_install
    archive = static / "bitmap16.flx"
    archive.write_bytes(build_flx({1: b"bad entry", 7: _texture([b"@J" * 4])}))
    output = tmp_path / "export"
    result = CliRunner().invoke(
        u9_app, ["texture-export-all", str(archive), "-o", str(output)]
    )
    assert result.exit_code == 1, result.output
    assert (output / "bitmap16/texture_00007_frame_000_mip_00.png").is_file()
    manifest = json.loads((output / "bitmap16/manifest.json").read_text())
    assert manifest["errors"][0]["entry"] == 1
    assert "@J" not in " ".join(path.name for path in output.rglob("*.png"))


def test_highest_available_fallback_and_unselected_bad_tier(texture_install, tmp_path):
    _, static = texture_install
    (static / "bitmap16.flx").unlink()
    result = export_texture_archives(static, tmp_path / "export")
    assert result.manifests[0].parent.name == "bitmapC"
    assert not result.errors
    _config._config["u9"]["paths"]["bitmapsh"] = "does-not-exist.flx"
    result = export_texture_archives(static, tmp_path / "export2")
    assert not result.errors


def test_entry_filter_and_invalid_source_errors(texture_install, tmp_path):
    _, static = texture_install
    result = CliRunner().invoke(
        u9_app,
        [
            "texture-export-all",
            "--all-tiers",
            "--all-mips",
            "--entry",
            "7",
            "-o",
            str(tmp_path / "export"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "export").rglob("*.png"))) == 12
    bad = export_texture_archives(static, tmp_path / "bad", entry_id=42)
    assert bad.errors and bad.images_written == 0
    with pytest.raises(U9TextureExportError, match="requires a STATIC directory"):
        export_texture_archives(
            static / "bitmap16.flx", tmp_path / "bad", all_tiers=True
        )
    with pytest.raises(U9TextureExportError, match="Texture source not found"):
        export_texture_archives(tmp_path / "missing", tmp_path / "bad")


def test_help_describes_quality_and_mip_controls():
    result = CliRunner().invoke(u9_app, ["texture-export-all", "--help"])
    assert result.exit_code == 0
    assert "--all-mips" in result.output
    assert "--all-tiers" in result.output
    assert "u9.paths" in result.output


def test_explicit_bc1_archive_uses_its_stored_compression(texture_install, tmp_path):
    _, static = texture_install
    block = struct.pack("<HHI", 0xF800, 0x07E0, 0)
    source = static / "bitmapC.flx"
    source.write_bytes(build_flx({7: _texture([block], size=4, compressed=True)}))
    result = export_texture_archives(source, tmp_path / "export")
    assert not result.errors
    with Image.open(
        tmp_path / "export/bitmapC/texture_00007_frame_000_mip_00.png"
    ) as image:
        assert image.size == (4, 4)
        assert image.tobytes() == bytes([255, 0, 0, 255]) * 16


def test_standard_library_progress_terminal_and_redirected_output(monkeypatch, capsys):
    import sys

    from titan.u9.texture_export import print_texture_export_progress

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    print_texture_export_progress("bitmap16.flx", 1, 2, 3)
    print_texture_export_progress("bitmap16.flx", 2, 2, 6)
    output = capsys.readouterr().out
    assert "\r" in output and "100%" in output and output.endswith("\n")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    print_texture_export_progress("empty.flx", 0, 0, 0)
    output = capsys.readouterr().out
    assert "100%" in output and "\r" not in output


def test_terrain_panel_regions_have_distinct_output_folders(texture_install, tmp_path):
    _, static = texture_install
    for region in (9, 14):
        source = static / f"Texture16.{region}"
        source.write_bytes(build_flx({7: _texture([struct.pack("<H", 0xF800) * 4])}))
        result = export_texture_archives(source, tmp_path / "panels")
        assert not result.errors
        assert result.manifests[0].parent.name == f"Texture16.{region}"
    assert len(list((tmp_path / "panels").rglob("*.png"))) == 2
