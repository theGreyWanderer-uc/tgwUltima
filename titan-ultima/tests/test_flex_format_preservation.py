"""Generic Flex operations must preserve U7/Exult and U8 archive formats."""

import struct

import pytest
from typer.testing import CliRunner

from titan.cli import app
from titan.flex import FlexArchive
from titan.u7.flex import U7FlexArchive


def source_bytes(version: int | None) -> bytes:
    if version is None:
        archive = FlexArchive()
        archive.comment = "Pagan archive  "
        archive.records = [b"first", b"", b"last"]
        raw = bytearray(archive.to_bytes())
        raw[0x60:0x64] = b"keep"
        return bytes(raw)
    archive = U7FlexArchive()
    archive.title = "Retail or Exult archive"
    archive.magic2 = version
    archive.records = [b"first", b"", b"last"]
    raw = bytearray(archive.to_bytes())
    raw[0x60:0x64] = b"keep"
    return bytes(raw)


@pytest.mark.parametrize("version", [None, 0xCC, 0xCC01])
def test_generic_update_preserves_source_header_and_other_records(version, tmp_path):
    source = tmp_path / "archive.flx"
    raw = source_bytes(version)
    source.write_bytes(raw)
    replacement = tmp_path / "new.bin"
    replacement.write_bytes(b"replacement")
    output = tmp_path / "updated.flx"
    result = CliRunner().invoke(
        app,
        [
            "flex-update",
            str(source),
            "--index",
            "1",
            "--data",
            str(replacement),
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    updated = output.read_bytes()
    if version is not None:
        assert updated[:128] == raw[:128]
        assert U7FlexArchive.from_file(str(output), strict=True).magic2 == version
    else:
        assert struct.unpack_from("<I", updated, 0x50)[0] == 0x1A1A
        assert updated[:0x5C] == raw[:0x5C]
        assert updated[0x60:128] == raw[0x60:128]
    assert FlexArchive.from_file(str(output)).records == [
        b"first",
        b"replacement",
        b"last",
    ]
    assert source.read_bytes() == raw


@pytest.mark.parametrize("version", [None, 0xCC, 0xCC01])
def test_extract_create_roundtrip_preserves_format_without_original_source(
    version, tmp_path
):
    source = tmp_path / "archive.flx"
    raw = source_bytes(version)
    source.write_bytes(raw)
    extracted = tmp_path / "records"
    output = tmp_path / "rebuilt.flx"
    runner = CliRunner()
    result = runner.invoke(app, ["flex-extract", str(source), "-o", str(extracted)])
    assert result.exit_code == 0, result.output
    source.unlink()
    result = runner.invoke(app, ["flex-create", str(extracted), "-o", str(output)])
    assert result.exit_code == 0, result.output
    rebuilt = output.read_bytes()
    assert rebuilt == raw


@pytest.mark.parametrize(
    "extension,format_name,magic",
    [("vga", None, 0xFFFF1A00), ("flx", "u7", 0xFFFF1A00), ("flx", None, 0x1A1A)],
)
def test_fresh_archive_format_is_explicit_or_inferred_from_vga(
    extension, format_name, magic, tmp_path
):
    records = tmp_path / "records"
    records.mkdir()
    (records / "0001.bin").write_bytes(b"payload")
    output = tmp_path / ("created." + extension)
    args = ["flex-create", str(records), "-o", str(output)]
    if format_name:
        args += ["--archive-format", format_name]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert struct.unpack_from("<I", output.read_bytes(), 0x50)[0] == magic
    assert FlexArchive.from_file(str(output)).records == [b"", b"payload"]


def test_u7_title_need_not_contain_u8_fill_bytes(tmp_path):
    archive = U7FlexArchive()
    archive.title = "A" * 80
    archive.records = [b"payload"]
    raw = archive.to_bytes()
    assert FlexArchive.from_bytes(raw).archive_format == "u7"
    assert FlexArchive.from_bytes(raw).to_bytes() == raw


def test_generic_update_rejects_damaged_u7_archive(tmp_path):
    source = tmp_path / "broken.vga"
    raw = bytearray(source_bytes(0xCC))
    struct.pack_into("<I", raw, 128, 20)
    source.write_bytes(raw)
    replacement = tmp_path / "new.bin"
    replacement.write_bytes(b"new")
    output = tmp_path / "updated.vga"
    result = CliRunner().invoke(
        app,
        [
            "flex-update",
            str(source),
            "--index",
            "0",
            "--data",
            str(replacement),
            "-o",
            str(output),
        ],
    )
    assert result.exit_code != 0
    assert source.read_bytes() == raw
    assert not output.exists()


def test_legacy_manifest_can_identify_u7_flx_from_its_version_marker(tmp_path):
    records = tmp_path / "records"
    records.mkdir()
    (records / "0000.bin").write_bytes(b"payload")
    (records / "_manifest.txt").write_text(
        "# Source: missing.flx\n# Comment: Original title\n"
        "# Unknown field: 0x0000CC01\n0|7|0000.bin|\n"
    )
    output = tmp_path / "rebuilt.flx"
    result = CliRunner().invoke(app, ["flex-create", str(records), "-o", str(output)])
    assert result.exit_code == 0, result.output
    archive = U7FlexArchive.from_file(str(output), strict=True)
    assert archive.magic2 == 0xCC01
    assert archive.title == "Original title"
    assert archive.records == [b"payload"]


def test_long_u8_comment_keeps_a_required_fill_byte():
    archive = FlexArchive()
    archive.comment = "B" * 100
    archive.records = [b"payload"]
    raw = archive.to_bytes()
    parsed = FlexArchive.from_bytes(raw)
    assert parsed.archive_format == "u8"
    assert parsed.comment == "B" * 81
    assert parsed.to_bytes() == raw
