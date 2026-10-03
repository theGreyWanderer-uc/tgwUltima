from __future__ import annotations

import struct
from pathlib import Path

from titan.u9.flx_writer import write_flx
from titan.u9.sound_report import build_sound_metadata_report


def _sound_record() -> bytes:
    payload = bytes(30)
    header = bytearray(0x3C)
    struct.pack_into("<I", header, 0, 1322)
    header[4:12] = b"EASports"
    struct.pack_into("<5I", header, 0x28, len(payload), 22050, 16, 1, 1)
    return bytes(header) + payload


def _template_record() -> bytes:
    data = bytearray(0x38)
    struct.pack_into("<I", data, 0, 437)
    data[4:9] = b"TV EA"
    struct.pack_into("<III", data, 0x28, 1, 360, 360)
    data[0x34:0x36] = bytes([1, 25])
    data += bytes([51]) + b"Spell FX 1\x00".ljust(33, b"\x00") + b"\x00\x00"
    data += struct.pack("<I", 1)
    data += b"\x01\x00\x00\x00" + struct.pack("<I", 1322)
    data += bytes([100, 75, 0, 0, 10, 3, 0, 0])
    return bytes(data)


def _types_dat(base_type_ids: list[int]) -> bytes:
    record = struct.Struct("<IHHHBBBBH")
    records = [
        record.pack(0, base_type_id, 0, 0, 0, 0, 0, 0, 0)
        for base_type_id in base_type_ids
    ]
    filler = record.pack(0, 0, 0, 0, 254, 0, 0, 0, 0)
    return struct.pack("<II", len(records), 0) + b"".join(
        records + [filler] * (8192 - len(records))
    )


def test_report_includes_sizes_duration_and_template_link(tmp_path: Path) -> None:
    write_flx(tmp_path / "sfx.flx", {1322: _sound_record()}, count=1400)
    write_flx(tmp_path / "SFXTMPL.FLX", {437: _template_record()}, count=500)

    rows, warnings = build_sound_metadata_report(tmp_path, entry_id=1322)

    assert warnings == []
    assert len(rows) == 1
    row = rows[0]
    assert row["record_length_exact"] is True
    assert row["sample_frames"] == 56
    assert row["sfx_template_ids"] == [437]
    assert row["sfx_template_names"] == ["TV EA"]
    assert row["sfx_action_names"] == ["Spell FX 1"]
    details = row["sfx_reference_details"][0]
    assert details["choice_id"] == 1
    assert details["full_volume_percent"] == 100
    assert details["off_axis_volume_percent"] == 75
    assert details["pitch_variation_percent"] == 10
    assert details["selection_weight"] == 3


def test_report_discovers_all_three_audio_archives_from_root(tmp_path: Path) -> None:
    sound = tmp_path / "sound"
    sound.mkdir()
    for name in ("Speech.flx", "sfx.flx", "music.flx"):
        write_flx(sound / name, {0: _sound_record()}, count=1)
    rows, _warnings = build_sound_metadata_report(tmp_path)
    assert {row["archive_kind"] for row in rows} == {"speech", "sfx", "music"}


def test_report_includes_direct_and_base_type_associations(tmp_path: Path) -> None:
    sound = tmp_path / "sound"
    static = tmp_path / "static"
    sound.mkdir()
    static.mkdir()
    write_flx(sound / "sfx.flx", {1322: _sound_record()}, count=1400)
    write_flx(sound / "SFXTMPL.FLX", {437: _template_record()}, count=500)
    write_flx(sound / "sfxassoc.flx", {1: struct.pack("<I", 437)}, count=8192)
    (static / "TYPES.DAT").write_bytes(_types_dat([0, 1, 1]))

    rows, warnings = build_sound_metadata_report(tmp_path, entry_id=1322)

    assert warnings == []
    assert rows[0]["direct_associated_type_ids"] == [1]
    assert rows[0]["inherited_associated_type_ids"] == [2]
    assert rows[0]["associated_type_ids"] == [1, 2]
