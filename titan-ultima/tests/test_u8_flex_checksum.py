"""Native U8 Flex checksum boundaries, signed chars and generic write workflows."""

import struct

import pytest
from typer.testing import CliRunner

from titan.cli import app
from titan.flex import FlexArchive, calculate_u8_flex_checksum
from titan.u7.flex import U7FlexArchive


@pytest.mark.parametrize("length", [128, 129, 255, 256])
def test_native_checksum_has_empty_range_for_small_archives(length):
    assert calculate_u8_flex_checksum(bytes([127]) * length) == 0


def test_native_checksum_sums_signed_bytes_excluding_header_and_final_128_bytes():
    raw = bytes([127]) * 128 + b"\x80\xff\x7f\x01" + bytes([127]) * 128
    # Native signed-char arithmetic: -128 - 1 + 127 + 1 = -1.
    assert calculate_u8_flex_checksum(raw) == 0xFFFFFFFF
    assert calculate_u8_flex_checksum(bytearray(raw)) == 0xFFFFFFFF


def test_native_checksum_rejects_truncated_header():
    with pytest.raises(ValueError, match="U8 Flex checksum: truncated header"):
        calculate_u8_flex_checksum(bytes(127))


def test_u8_writer_checksums_directory_and_payload_after_packing():
    archive = FlexArchive()
    archive.records = [b"\xff" * 256]
    raw = archive.to_bytes()
    # Directory: offset 136 contributes -120; size 256 contributes 1.
    # Only the first 128 payload bytes are covered: 128 * -1.
    assert struct.unpack_from("<I", raw, 0x60)[0] == (-247 & 0xFFFFFFFF)
    assert raw[0x52:0x54] == b"\x00\x00"
    assert struct.unpack_from("<I", raw, 0x5C)[0] == len(raw)


def test_u8_repack_replaces_stale_checksum_and_preserves_other_header_bytes():
    archive = FlexArchive()
    archive.comment = "Native U8"
    archive.unknown_field = 205
    archive.records = [b"\xff" * 256]
    raw = bytearray(archive.to_bytes())
    raw[0x60:0x64] = b"old!"
    raw[0x64:0x80] = bytes(range(28))
    updated = FlexArchive.from_bytes(bytes(raw)).to_bytes()
    assert updated[:0x60] == raw[:0x60]
    assert updated[0x64:] == raw[0x64:]
    assert struct.unpack_from("<I", updated, 0x60)[0] == (-247 & 0xFFFFFFFF)


def test_generic_update_recalculates_checksum_for_resized_u8_record(tmp_path):
    source = tmp_path / "original.flx"
    output = tmp_path / "updated.flx"
    replacement = tmp_path / "replacement.bin"
    archive = FlexArchive()
    archive.records = [b"\x01" * 256, b"", b"\x02" * 256, b""]
    original = archive.to_bytes()
    source.write_bytes(original)
    replacement.write_bytes(b"\x80" * 300)
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
    assert result.exit_code == 0, result.output
    raw = output.read_bytes()
    # Directory: (160,300),(0,0),(460,256),(0,0) contributes -101.
    # Covered payload: 300 signed -128 bytes plus 128 bytes with value 2.
    assert struct.unpack_from("<I", raw, 0x60)[0] == (-38245 & 0xFFFFFFFF)
    assert raw[0x60:0x64] != original[0x60:0x64]
    assert FlexArchive.from_file(str(output), strict=True).records == [
        b"\x80" * 300,
        b"",
        b"\x02" * 256,
        b"",
    ]
    assert source.read_bytes() == original


def test_manifest_rebuild_recalculates_checksum_without_source_file(tmp_path):
    source = tmp_path / "original.flx"
    extracted = tmp_path / "records"
    output = tmp_path / "rebuilt.flx"
    archive = FlexArchive()
    archive.records = [b"\x01" * 256]
    source.write_bytes(archive.to_bytes())
    runner = CliRunner()
    result = runner.invoke(app, ["flex-extract", str(source), "-o", str(extracted)])
    assert result.exit_code == 0, result.output
    (extracted / "0000.bin").write_bytes(b"\xff" * 256)
    source.unlink()
    result = runner.invoke(app, ["flex-create", str(extracted), "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert struct.unpack_from("<I", output.read_bytes(), 0x60)[0] == (-247 & 0xFFFFFFFF)


def test_u7_reserved_checksum_position_is_never_recalculated():
    archive = U7FlexArchive()
    archive.records = [b"\xff" * 256]
    raw = bytearray(archive.to_bytes())
    raw[0x60:0x64] = b"keep"
    shared = FlexArchive.from_bytes(bytes(raw))
    shared.records[0] = b"\x80" * 300
    assert shared.to_bytes()[0x5C:0x80] == raw[0x5C:0x80]
