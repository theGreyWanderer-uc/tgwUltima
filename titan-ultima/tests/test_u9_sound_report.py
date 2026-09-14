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
    struct.pack_into("<III", data, 0x28, 1, 0, 0)
    data += bytes([51]) + b"Spell FX 1\x00".ljust(35, b"\x00")
    data += struct.pack("<I4I", 1, 0, 1322, 0, 0)
    return bytes(data)


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
    assert row["sfx_reference_details"][0]["reference_unknown_08"] == 0


def test_report_discovers_all_three_audio_archives_from_root(tmp_path: Path) -> None:
    sound = tmp_path / "sound"
    sound.mkdir()
    for name in ("Speech.flx", "sfx.flx", "music.flx"):
        write_flx(sound / name, {0: _sound_record()}, count=1)
    rows, _warnings = build_sound_metadata_report(tmp_path)
    assert {row["archive_kind"] for row in rows} == {"speech", "sfx", "music"}
