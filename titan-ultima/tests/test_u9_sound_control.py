from __future__ import annotations

import struct

import pytest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.flx_writer import build_flx
from titan.u9.sound_control import (
    SFX_ASSOCIATION_REPRESENTATION,
    U9SfxAssociations,
    U9SfxTemplates,
    U9SoundControlError,
    parse_sfx_associations,
    parse_sfx_template,
)
from titan.u9.types_dat import U9TypesDat


def _template_record() -> bytes:
    data = bytearray(0x38)
    struct.pack_into("<I", data, 0, 437)
    data[4:9] = b"TV EA"
    struct.pack_into("<III", data, 0x28, 1, 360, 360)
    data[0x34:0x38] = b"\x01\x19\xcd\xcd"
    data += bytes([51]) + b"Spell FX 1\x00".ljust(33, b"\x00") + b"\x00\x00"
    data += struct.pack("<I", 1)
    data += b"\x01\xcd\xcd\xcd" + struct.pack("<I", 1322)
    data += bytes([100, 75, 0, 0, 10, 3]) + b"\xcd\xcd"
    return bytes(data)


def test_parse_sfx_template_exposes_tv_ea_sound_link() -> None:
    template = parse_sfx_template(_template_record())
    assert template.template_id == 437
    assert template.name == "TV EA"
    assert template.inner_cone_angle_degrees == 360
    assert template.outer_cone_angle_degrees == 360
    assert template.near_distance == 1
    assert template.far_distance == 25
    assert template.trailing_alignment_bytes == b"\xcd\xcd"
    assert template.actions[0].category_id == 51
    assert template.actions[0].name == "Spell FX 1"
    choice = template.actions[0].sound_references[0]
    assert choice.choice_id == 1
    assert choice.sound_id == 1322
    assert choice.full_volume_percent == 100
    assert choice.off_axis_volume_percent == 75
    assert choice.active_hour_start == 0
    assert choice.active_hour_stop == 0
    assert choice.pitch_variation_percent == 10
    assert choice.selection_weight == 3
    assert choice.leading_alignment_bytes == b"\xcd\xcd\xcd"
    assert choice.trailing_alignment_bytes == b"\xcd\xcd"
    assert choice.warnings == ()
    assert template.warnings == ()


def test_template_collection_round_trips_archive_exactly() -> None:
    raw = build_flx({437: _template_record()}, count=8192)
    templates = U9SfxTemplates(U9FlxArchive(raw))
    assert len(templates) == 1
    assert templates.archive_slot_count == 8192
    assert templates.warnings == ()
    assert templates.template(437) is not None
    assert templates.to_bytes() == raw


def test_template_warnings_flag_ranges_without_rewriting_bytes() -> None:
    record = bytearray(_template_record())
    struct.pack_into("<I", record, 0, 99)
    struct.pack_into("<II", record, 0x2C, 361, 100)
    record[0x34:0x36] = bytes([26, 1])
    record[-8:-2] = bytes([101, 101, 24, 24, 31, 0])
    template = parse_sfx_template(bytes(record), archive_index=437)
    assert "stored_id_differs_from_archive_index" in template.warnings
    assert "inner_cone_angle_out_of_range" in template.warnings
    assert "outer_cone_smaller_than_inner_cone" in template.warnings
    assert "near_distance_out_of_editor_range" in template.warnings
    assert "far_distance_smaller_than_near_distance" in template.warnings
    choice_warnings = template.actions[0].sound_references[0].warnings
    assert "full_volume_percent_out_of_range" in choice_warnings
    assert "active_hour_start_out_of_range" in choice_warnings
    assert "pitch_variation_percent_out_of_range" in choice_warnings
    assert "selection_weight_out_of_range" in choice_warnings
    assert template.raw == bytes(record)


def test_parse_sfx_template_rejects_trailing_data() -> None:
    with pytest.raises(U9SoundControlError, match="trailing"):
        parse_sfx_template(_template_record() + b"x")


def _types_dat(base_type_ids: list[int]) -> U9TypesDat:
    record = struct.Struct("<IHHHBBBBH")
    records = [
        record.pack(0, base_type_id, 0, 0, 0, 0, 0, 0, 0)
        for base_type_id in base_type_ids
    ]
    filler = record.pack(0, 0, 0, 0, 254, 0, 0, 0, 0)
    data = struct.pack("<II", len(records), 0) + b"".join(
        records + [filler] * (8192 - len(records))
    )
    return U9TypesDat(data)


def test_parse_sfx_associations_uses_entry_as_object_type_id() -> None:
    archive = U9FlxArchive(build_flx({4977: struct.pack("<I", 437)}, count=8192))
    association = parse_sfx_associations(archive)[0]
    assert association.object_type_id == 4977
    assert association.sound_template_id == 437
    assert association.raw == struct.pack("<I", 437)
    assert association.record_representation == SFX_ASSOCIATION_REPRESENTATION


def test_association_collection_round_trips_archive_exactly() -> None:
    raw = build_flx({1: struct.pack("<I", 12)}, count=8192)
    associations = U9SfxAssociations(U9FlxArchive(raw))
    assert len(associations) == 1
    assert associations.archive_slot_count == 8192
    assert associations.warnings == ()
    assert associations.to_bytes() == raw


def test_resolution_uses_direct_link_before_one_step_base_type() -> None:
    archive = U9FlxArchive(
        build_flx({1: struct.pack("<I", 12), 2: struct.pack("<I", 99)}, count=8192)
    )
    associations = U9SfxAssociations(archive)
    types = _types_dat([0, 1, 1, 1])

    direct = associations.resolve(2, types)
    assert direct.link_source == "direct"
    assert direct.matched_object_type_id == 2
    assert direct.sound_template_id == 99

    inherited = associations.resolve(3, types)
    assert inherited.link_source == "base_type"
    assert inherited.matched_object_type_id == 1
    assert inherited.sound_template_id == 12

    unmapped = associations.resolve(0, types)
    assert unmapped.link_source == "unmapped"
    assert unmapped.sound_template_id is None


def test_association_collection_reports_nonstandard_slot_capacity() -> None:
    archive = U9FlxArchive(build_flx({1: struct.pack("<I", 12)}, count=2))
    assert U9SfxAssociations(archive).warnings == ("unexpected_archive_slot_count",)


def test_parse_sfx_associations_rejects_non_four_byte_record() -> None:
    archive = U9FlxArchive(build_flx({1: b"bad"}, count=8192))
    with pytest.raises(U9SoundControlError, match="expected exactly 4"):
        U9SfxAssociations(archive)
