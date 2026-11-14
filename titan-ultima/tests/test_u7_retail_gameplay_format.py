"""Retail u8 count boundaries and WEAPONS semantics stay separate from Exult extensions."""

import csv
import io
import struct

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.combat_metadata import U7CombatLayer, U7CombatMetadata
from titan.u7.gameplay_metadata import read_gameplay_table
from titan.u7.monster import U7MonsterDefinitions, U7MonsterEquipment, U7WeaponInfos
from titan.u7.save import U7ReadyTypes
from titan.u7.shape_properties import ShapeProperties, overlay_table
from titan.u7.shapeinfo import U7Ammos, U7Armors, U7Weapons


def record(width, shape=100, *, damage=0, sound=0, tail=0):
    raw = bytearray(width)
    struct.pack_into("<H", raw, 0, shape)
    if width >= 13:
        raw[6] = damage
    if width == 21:
        raw[15] = sound
    raw[-1] = tail
    return bytes(raw)


READERS = [
    (21, U7Weapons),
    (13, U7Ammos),
    (10, U7Armors),
    (25, U7MonsterDefinitions),
    (60, U7MonsterEquipment),
    (9, U7ReadyTypes),
]


@pytest.mark.parametrize("width,reader", READERS)
def test_all_six_readers_distinguish_retail_255_from_exult_escape(width, reader):
    rows = b"".join(record(width, shape) for shape in range(255))
    retail = reader.from_bytes(b"\xff" + rows, data_format="retail")
    exult = reader.from_bytes(b"\xff\xff\0" + rows)
    assert len(retail.records) == len(exult.records) == 255
    assert retail.declared_count == exult.declared_count == 255
    assert retail.table.header_size == 1 and exult.table.header_size == 3
    assert retail.data_format == "retail" and exult.data_format == "exult"
    assert not retail.warnings and not exult.warnings


def test_retail_ff_is_a_complete_count_even_without_payload_and_invalid_format_is_rejected():
    retail = read_gameplay_table(b"\xff", 13, "AMMO.DAT", data_format="retail")
    exult = read_gameplay_table(b"\xff", 13, "AMMO.DAT")
    assert retail.declared_count == 255 and retail.header_size == 1
    assert exult.declared_count is None
    assert "records are incomplete" in retail.warnings[0]
    with pytest.raises(ValueError, match="data_format"):
        read_gameplay_table(b"", 13, "AMMO.DAT", data_format="auto")


@pytest.mark.parametrize("width,reader", READERS)
def test_file_and_directory_readers_keep_the_selected_format(tmp_path, width, reader):
    names = {
        21: "WEAPONS.DAT",
        13: "AMMO.DAT",
        10: "ARMOR.DAT",
        25: "MONSTERS.DAT",
        60: "EQUIP.DAT",
        9: "READY.DAT",
    }
    path = tmp_path / names[width]
    raw = b"\xff" + b"".join(record(width, shape) for shape in range(255))
    path.write_bytes(raw)
    direct = reader.from_file(str(path), data_format="retail")
    directory = reader.from_dir(str(tmp_path), data_format="retail")
    assert len(direct.records) == len(directory.records) == 255
    assert direct.data_format == directory.data_format == "retail"
    assert direct.table.raw == raw


@pytest.mark.parametrize(
    "width,reader", [(21, U7Weapons), (13, U7Ammos), (10, U7Armors)]
)
def test_combat_tail_ff_is_padding_in_retail_and_removal_in_exult(width, reader):
    data = b"\1" + record(width, tail=255)
    assert len(reader.from_bytes(data, data_format="retail").records) == 1
    assert not reader.from_bytes(data).records
    kind = {21: "weapon", 13: "ammo", 10: "armor"}[width]
    retail = U7CombatLayer.from_bytes(kind, data, data_format="retail")
    assert not retail.records[0].deleted and retail.to_bytes() == data
    assert U7CombatLayer.from_bytes(kind, data).records[0].deleted
    with pytest.raises(ValueError, match="require Exult"):
        retail.removal_record(100)


def test_monster_and_narrow_weapon_readers_do_not_delete_retail_padding_ff():
    monsters = b"\1" + record(25, tail=255)
    assert (
        not U7MonsterDefinitions.from_bytes(monsters, data_format="retail")
        .records[0]
        .deleted
    )
    assert U7MonsterDefinitions.from_bytes(monsters).records[0].deleted
    weapon = b"\1" + record(21, tail=255)
    retail = U7WeaponInfos.from_bytes(weapon, data_format="retail")
    assert 100 in retail.records and not retail.deleted
    assert 100 in U7WeaponInfos.from_bytes(weapon).deleted
    with pytest.raises(ValueError, match="cannot mix"):
        U7WeaponInfos.merge(retail, U7WeaponInfos.from_bytes(b"\0"))


def test_copy_editing_keeps_retail_count_at_255_and_refuses_256():
    data = bytes([254]) + b"".join(record(13, shape) for shape in range(254)) + b"tail"
    retail = U7CombatLayer.from_bytes("ammo", data, data_format="retail", strict=True)
    edited = retail.append_record(record(13, 254, tail=255))
    assert edited.table.header_size == 1 and edited.table.declared_count == 255
    assert (
        edited.table.data_format == "retail" and edited.table.trailing_data == b"tail"
    )
    assert retail.to_bytes() == data
    changed = edited.replace_record(0, record(13, 900, tail=255))
    assert changed.table.data_format == "retail" and changed.records[0].shape == 900
    assert not changed.records[0].deleted
    with pytest.raises(ValueError, match="retail count exceeds 255"):
        edited.append_record(record(13, 255))
    exult = U7CombatLayer.from_bytes("ammo", data).append_record(record(13, 254))
    assert exult.table.header_size == 3 and exult.table.declared_count == 255


def test_directory_resolution_preserves_retail_rows_and_refuses_mixed_layers(tmp_path):
    static, patch = tmp_path / "static", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    base = b"\xff" + b"".join(record(21, shape) for shape in range(255))
    override = b"\1" + record(21, 100, damage=128, tail=255)
    (static / "WEAPONS.DAT").write_bytes(base)
    (patch / "weapons.dat").write_bytes(override)
    resolved = U7Weapons.from_dir(str(static), patch_dir=patch, data_format="retail")
    assert len(resolved.records) == 255 and resolved.data_format == "retail"
    selected = next(row for row in resolved.records if row.shape == 100)
    assert selected.damage == -128 and selected.raw[-1] == 255
    assert resolved.table.header_size == 1
    assert resolved.world_metadata.layers[0].to_bytes() == base
    narrow = U7WeaponInfos.from_dir(str(static), patch_dir=patch, data_format="retail")
    assert len(narrow.records) == 255 and 100 in narrow.records
    with pytest.raises(ValueError, match="cannot mix"):
        U7CombatMetadata("weapon", (resolved.world_metadata.layers[0],))
    with pytest.raises(ValueError, match="exceeds 255"):
        extra = U7CombatLayer.from_bytes(
            "weapon", b"\1" + record(21, 999), data_format="retail"
        )
        U7CombatMetadata(
            "weapon", (*resolved.world_metadata.layers, extra), data_format="retail"
        ).resolved_bytes()


@pytest.mark.parametrize(
    "game,byte,script_byte",
    [
        ("bg", 0, None),
        ("si", 0, None),
        ("bg", 1, 0),
        ("si", 1, 1),
        ("bg", 128, 127),
        ("si", 128, 128),
        ("bg", 255, 254),
        ("si", 255, 255),
    ],
)
def test_retail_weapon_sound_is_one_byte_with_game_specific_script_encoding(
    game, byte, script_byte
):
    raw = bytearray(record(21, damage=128, sound=byte, tail=255))
    raw[16:21] = b"\x12\x34\x56\x78\xff"
    retail = U7Weapons.from_bytes(b"\1" + raw, game, data_format="retail")
    rec = retail.records[0]
    assert rec.damage == rec.retail_damage == -128
    assert (
        rec.retail_sound_byte == byte
        and rec.sfx == rec.retail_sfx_script_byte == script_byte
    )
    assert rec.hitsfx is None and rec.need_target is None and rec.missile_speed is None
    row = next(csv.DictReader(io.StringIO(retail.dump_csv())))
    assert row["damage"] == "-128" and row["exult_damage"] == "128"
    assert row["hitsfx"] == "" and row["retail_padding_hex"] == "12345678ff"


def test_retail_weapon_flags_expose_homing_speed_frames_and_distinct_power_names():
    raw = bytearray(record(21, damage=255, sound=5))
    raw[9], raw[10], raw[11] = 0x9E, 0xAB, 0x60
    struct.pack_into("<H", raw, 13, 65535)
    retail = U7Weapons.from_bytes(b"\1" + raw, data_format="retail").records[0]
    exult = U7Weapons.from_bytes(b"\1" + raw).records[0]
    assert retail.retail_homing and retail.retail_missile_speed_code == 3
    assert retail.retail_frame_step == 9 and retail.retail_speed == 5
    assert retail.retail_power_names == "drain_mana|drain_health"
    assert retail.damage == -1 and retail.usecode == -1
    assert exult.damage == 255 and exult.usecode == 65535
    assert exult.need_target is True and exult.missile_speed == 4
    text = U7Weapons.from_bytes(b"\1" + raw, data_format="retail").dump_csv()
    row = next(csv.DictReader(io.StringIO(text)))
    assert (
        row["power_names"] == "drain_mana|drain_health"
        and row["usecode_hex"] == "0xFFFF"
    )
    assert [
        row[name]
        for name in (
            "retail_melee_ready_frame",
            "retail_melee_strike_frame",
            "retail_ranged_ready_frame",
            "retail_ranged_strike_frame",
        )
    ] == ["1", "1", "0", "1"]


@pytest.mark.parametrize("stop_bits", [0, 16, 32, 48])
def test_retail_ammo_stop_flags_are_separate_from_exult_drop_homing(stop_bits):
    raw = bytearray(record(13))
    raw[7], raw[10] = stop_bits, 0x60
    retail = U7Ammos.from_bytes(b"\1" + raw, data_format="retail")
    exult = U7Ammos.from_bytes(b"\1" + raw)
    row = retail.records[0]
    assert row.homing is None and row.drop_type is None
    assert row.retail_remove_on_stop == bool(stop_bits & 16)
    assert row.retail_keep_on_stop == bool(stop_bits & 32)
    assert row.retail_continuous == (stop_bits == 48)
    assert exult.records[0].homing == (stop_bits == 48)
    exported = next(csv.DictReader(io.StringIO(retail.dump_csv())))
    assert exported["homing"] == exported["drop_type"] == ""
    assert exported["power_names"] == "drain_mana|drain_health"


def test_selected_ammo_damage_and_shape_property_overlay_use_retail_mode():
    raw = b"\1" + record(13, damage=255, tail=255)
    ammo = U7Ammos.from_bytes(raw, data_format="retail")
    assert ammo.records[0].damage == ammo.records[0].retail_damage == -1
    props = ShapeProperties()
    overlay_table(props, "ammo", raw, "retail", "bg", data_format="retail")
    assert props.tables["ammo"][100]["damage"] == "-1" and props.warnings


@pytest.mark.parametrize(
    "reader", [U7Weapons, U7Ammos, U7Armors, U7ReadyTypes, U7MonsterEquipment]
)
def test_missing_directory_sources_keep_format_without_inventing_rows(tmp_path, reader):
    result = reader.from_dir(str(tmp_path), data_format="retail")
    assert (
        result.data_format == "retail"
        and result.declared_count is None
        and not result.records
    )


def test_cli_explicit_retail_mode_handles_255_records_and_keeps_default_exult(tmp_path):
    path = tmp_path / "AMMO.DAT"
    path.write_bytes(b"\xff" + b"".join(record(13, shape) for shape in range(255)))
    result = CliRunner().invoke(
        u7_app,
        ["static-data-dump", "ammo", "--file", str(path), "--data-format", "retail"],
    )
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    assert len(rows) == 255 and all(row["data_format"] == "retail" for row in rows)
    path.write_bytes(b"\1" + record(13, tail=255))
    exult = CliRunner().invoke(
        u7_app, ["static-data-dump", "ammo", "--file", str(path)]
    )
    assert exult.exit_code == 0 and "0 ammo row(s)" in exult.stdout
    invalid = CliRunner().invoke(
        u7_app, ["static-data-dump", "gumps", str(tmp_path), "--data-format", "retail"]
    )
    assert (
        invalid.exit_code != 0 and "supports weapon, ammo and armor" in invalid.output
    )


def combat_record(kind, shape, value=0, *, deleted=False):
    size = {"weapon": 21, "ammo": 13, "armor": 10}[kind]
    data = bytearray(size)
    data[:2] = shape.to_bytes(2, "little")
    data[2] = value
    data[-1] = 255 if deleted else 0
    return bytes(data)


@pytest.mark.parametrize(
    "kind,reader,name",
    [
        ("weapon", U7Weapons, "WEAPONS.DAT"),
        ("ammo", U7Ammos, "AMMO.DAT"),
        ("armor", U7Armors, "ARMOR.DAT"),
    ],
)
def test_shared_combat_world_resolves_sparse_replacements_and_removals(
    tmp_path, kind, reader, name
):
    static, patch = tmp_path / "STATIC", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    assert reader.from_dir(str(static)).declared_count is None
    base = bytes([2]) + combat_record(kind, 100, 1) + combat_record(kind, 101, 2)
    mod = (
        bytes([3])
        + combat_record(kind, 100, deleted=True)
        + combat_record(kind, 102, 3)
        + combat_record(kind, 102, 4)
    )
    (static / name).write_bytes(base)
    (patch / name.lower()).write_bytes(mod)
    parsed = reader.from_dir(str(static), patch_dir=patch)
    assert {row.shape for row in parsed.records} == {101, 102}
    assert [layer.to_bytes() for layer in parsed.world_metadata.layers] == [base, mod]
    assert parsed.world_metadata.records[102].raw[2] == 4
    assert parsed.world_metadata.records[102].source.endswith(name.lower())


@pytest.mark.parametrize("kind", ["weapon", "ammo", "armor"])
def test_combat_copy_edits_preserve_headers_unknown_bytes_and_tail(kind):
    row = combat_record(kind, 100, 9)
    raw = b"\xff\x01\x00" + row + b"unknown-tail"
    layer = U7CombatLayer.from_bytes(kind, raw, strict=True)
    edited = layer.replace_record(0, combat_record(kind, 101, 8))
    assert layer.to_bytes() == raw and edited.to_bytes()[:3] == raw[:3]
    assert edited.table.trailing_data == b"unknown-tail"
    removed = edited.append_record(edited.removal_record(101))
    assert U7CombatMetadata(kind, (removed,)).records == {}
    assert removed.table.header_size == 3 and removed.table.declared_count == 2
    with pytest.raises(ValueError):
        layer.replace_record(0, b"short")


def test_combat_append_crosses_255_without_losing_unknown_data():
    row = combat_record("armor", 100)
    source = U7CombatLayer.from_bytes("armor", bytes([254]) + row * 254 + b"tail")
    appended = source.append_record(combat_record("armor", 101))
    assert appended.to_bytes()[:3] == b"\xff\xff\x00"
    assert appended.table.trailing_data == b"tail" and source.table.header_size == 1
    with pytest.raises(ValueError, match="incomplete"):
        U7CombatLayer.from_bytes("armor", b"\x01short").append_record(row)
