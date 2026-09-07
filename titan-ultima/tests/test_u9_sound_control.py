from __future__ import annotations

import struct

import pytest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.flx_writer import build_flx
from titan.u9.sound_control import (
    U9SoundControlError,
    parse_sfx_associations,
    parse_sfx_template,
)


def _template_record() -> bytes:
    data = bytearray(0x38)
    struct.pack_into("<I", data, 0, 437)
    data[4:9] = b"TV EA"
    struct.pack_into("<III", data, 0x28, 1, 7, 8)
    data += bytes([51]) + b"Spell FX 1\x00".ljust(35, b"\x00")
    data += struct.pack("<I4I", 1, 0, 1322, 0, 0)
    return bytes(data)


def test_parse_sfx_template_exposes_tv_ea_sound_link() -> None:
    template = parse_sfx_template(_template_record())
    assert template.template_id == 437
    assert template.name == "TV EA"
    assert template.actions[0].category_id == 51
    assert template.actions[0].name == "Spell FX 1"
    assert template.actions[0].sound_references[0].sound_id == 1322


def test_parse_sfx_template_rejects_trailing_data() -> None:
    with pytest.raises(U9SoundControlError, match="trailing"):
        parse_sfx_template(_template_record() + b"x")


def test_parse_sfx_associations_uses_entry_as_type_id() -> None:
    archive = U9FlxArchive(build_flx({4977: struct.pack("<I", 437)}, count=5000))
    assert parse_sfx_associations(archive)[0].type_id == 4977
    assert parse_sfx_associations(archive)[0].template_id == 437
