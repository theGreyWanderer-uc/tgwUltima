"""Gameplay count framing, charge semantics and BG/SI translation regressions."""

from __future__ import annotations

import csv
import io
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from titan.u7 import cli
from titan.u7.gameplay_metadata import U7GameplayMetadata, read_gameplay_table
from titan.u7.monster import (
    U7MonsterDefinitions,
    U7MonsterEquipment,
    U7WeaponInfos,
    monster_equipment_csv,
    monster_equipment_rows,
    monster_equipment_summary,
)
from titan.u7.save import U7ReadyTypes
from titan.u7.shapeinfo import U7Ammos, U7Armors, U7Weapons


READERS: list[tuple[Callable[[bytes], U7GameplayMetadata], int]] = [
    (U7Weapons.from_bytes, 21),
    (U7WeaponInfos.from_bytes, 21),
    (U7Ammos.from_bytes, 13),
    (U7Armors.from_bytes, 10),
    (U7ReadyTypes.from_bytes, 9),
    (U7MonsterDefinitions.from_bytes, 25),
    (U7MonsterEquipment.from_bytes, 60),
]


def counted(records: list[bytes]) -> bytes:
    count = len(records)
    header = bytes([count]) if count < 255 else b"\xff" + struct.pack("<H", count)
    return header + b"".join(records)


def record(width: int, shape: int = 300) -> bytes:
    return struct.pack("<H", shape) + bytes(width - 2)


@pytest.mark.parametrize("reader,width", READERS)
def test_canonical_extended_count_and_record_boundaries(
    reader: Callable[[bytes], U7GameplayMetadata],
    width: int,
) -> None:
    data = counted([record(width, 300 + n) for n in range(255)])
    parsed = reader(data)
    assert parsed.declared_count == 255 and parsed.table is not None
    assert parsed.table.parsed_count == 255 and parsed.table.header_size == 3
    assert parsed.table.consumed_bytes == len(data) and not parsed.warnings
    assert parsed.table.records[-1][:2] == struct.pack("<H", 554)


@pytest.mark.parametrize("reader,width", READERS)
@pytest.mark.parametrize("data", [b"", b"\xff", b"\xff\x01"])
def test_short_count_header_is_reported_without_fabricated_records(
    reader: Callable[[bytes], U7GameplayMetadata],
    width: int,
    data: bytes,
) -> None:
    parsed = reader(data)
    assert parsed.declared_count is None and parsed.warnings
    assert parsed.table is not None and parsed.table.raw == data
    assert not parsed.table.records


@pytest.mark.parametrize("reader,width", READERS)
def test_partial_records_and_trailing_bytes_remain_distinct(
    reader: Callable[[bytes], U7GameplayMetadata],
    width: int,
) -> None:
    complete = record(width)
    partial = complete[:-1]
    parsed = reader(b"\x02" + complete + partial)
    assert parsed.table is not None and parsed.table.parsed_count == 1
    assert parsed.table.partial_record == partial and not parsed.table.trailing_data
    assert parsed.table.consumed_bytes == 1 + width
    assert "declares 2, parsed 1" in parsed.warnings[0]
    extra = reader(b"\x01" + complete + b"future")
    assert extra.table is not None and extra.table.trailing_data == b"future"
    assert not extra.table.partial_record and "trailing" in extra.warnings[0]
    empty = reader(b"\x00")
    assert not empty.warnings and empty.declared_count == 0


def test_monster_count_is_not_a_version_and_headerless_requires_explicit_selection() -> (
    None
):
    data = counted([record(25, 300), record(25, 301)])
    parsed = U7MonsterDefinitions.from_bytes(data)
    assert [(r.shape, r.offset, r.declared_count) for r in parsed.records] == [
        (300, 1, 2),
        (301, 26, 2),
    ]
    assert parsed.records[0].file_version is None
    rows = list(csv.DictReader(io.StringIO(parsed.dump_csv())))
    assert rows[0]["declared_count"] == "2" and "file_version" not in rows[0]
    headerless = data[1:]
    assert U7MonsterDefinitions.from_bytes(headerless).warnings
    explicit = U7MonsterDefinitions.from_bytes(headerless, headerless=True)
    assert [r.shape for r in explicit.records] == [300, 301]
    assert explicit.declared_count is None and not explicit.warnings


def test_counts_bound_monster_records_and_merge_preserves_partial_source_diagnostics() -> (
    None
):
    data = b"\x01" + record(25, 300) + record(25, 301)
    base = U7MonsterDefinitions.from_bytes(data)
    assert [r.shape for r in base.records] == [300]
    patch = U7MonsterDefinitions.from_bytes(counted([record(25, 302)]))
    merged = U7MonsterDefinitions.merge(base, patch)
    assert [r.shape for r in merged.records] == [300, 302]
    assert merged.warnings == base.warnings and "trailing" in merged.dump_summary()


@pytest.mark.parametrize(
    "game,code,slot", [("bg", 0, 1), ("si", 0, 8), ("bg", 18, 3), ("si", 18, 22)]
)
def test_ready_spell_flag_does_not_change_bg_si_slot_translation(
    game: str, code: int, slot: int
) -> None:
    raw = struct.pack("<HB", 300, (code << 3) | 1) + b"\xffpad!!"
    ready = U7ReadyTypes.from_bytes(counted([raw]), game)
    assert ready.slot_for_shape(300) == slot and ready.spell_flag_for_shape(300) is True
    assert ready.records[0].ready_code == code and ready.records[0].raw == raw
    assert ready.spell_flag_for_shape(301) is None and not ready.warnings
    replacement = raw[:2] + bytes([code << 3]) + raw[3:]
    repeated = U7ReadyTypes.from_bytes(counted([raw, replacement]), game)
    assert repeated.spell_flag_for_shape(300) is False and len(repeated.records) == 2


@pytest.mark.parametrize("game,expected", [("bg", -1), ("si", 0)])
def test_sound_adjustment_is_preserved_and_damage_type_five_is_sonic(
    game: str, expected: int
) -> None:
    weapon = bytearray(record(21))
    weapon[7] = 5 << 4
    parsed = U7Weapons.from_bytes(counted([bytes(weapon)]), game)
    assert parsed.records[0].sfx == expected and parsed.records[0].hitsfx == expected
    assert (
        list(csv.DictReader(io.StringIO(parsed.dump_csv())))[0]["damage_type_name"]
        == "sonic"
    )
    ammo = bytearray(record(13))
    ammo[9] = 5 << 4
    assert (
        list(
            csv.DictReader(
                io.StringIO(U7Ammos.from_bytes(counted([bytes(ammo)])).dump_csv())
            )
        )[0]["damage_type_name"]
        == "sonic"
    )


def write_equipment_world(
    root: Path, shape_class: int = 2, ammo: int = -2, quantity: int = 99
) -> None:
    monster = bytearray(record(25, 500))
    monster[14] = 1
    (root / "MONSTERS.DAT").write_bytes(counted([bytes(monster)]))
    weapon = bytearray(record(21))
    struct.pack_into("<h", weapon, 2, ammo)
    (root / "WEAPONS.DAT").write_bytes(counted([bytes(weapon)]))
    equipment = struct.pack("<HBB", 300, 50, quantity) + bytes(56)
    (root / "EQUIP.DAT").write_bytes(counted([equipment]))
    tfa = bytearray(3072)
    tfa[300 * 3 + 1] = shape_class
    (root / "TFA.DAT").write_bytes(tfa)


@pytest.mark.parametrize("shape_class", [2, 6, 7, 11, 12, 13])
def test_charge_weapons_create_one_item_with_separate_charges(
    tmp_path: Path, shape_class: int
) -> None:
    write_equipment_world(tmp_path, shape_class)
    rows = monster_equipment_rows(str(tmp_path), "si")
    assert len(rows) == 1
    row = rows[0]
    assert row["quantity_mode"] == "one_item_with_charges"
    assert (
        row["quantity"]
        == row["min_quantity_if_created"]
        == row["max_quantity_if_created"]
        == 1
    )
    assert row["quantity_parameter"] == row["charges_if_created"] == 99
    assert (
        row["average_quantity_if_created"] == "1.00"
        and row["expected_quantity_per_spawn"] == "0.50"
    )
    assert "x1 (99 charges)" in monster_equipment_summary(str(tmp_path), "si")
    csv_row = list(
        csv.DictReader(io.StringIO(monster_equipment_csv(str(tmp_path), "si")))
    )[0]
    assert csv_row["quantity"] == "1" and csv_row["charges_if_created"] == "99"


@pytest.mark.parametrize(
    "shape_class,ammo,quantity,mode,minimum,maximum",
    [
        (3, -3, 4, "random_1_to_quantity", 1, 4),
        (2, -1, 4, "exact_quantity", 4, 4),
        (3, -2, 4, "random_1_to_quantity", 1, 4),  # Not a quality-bearing class.
        (2, -2, 0, "one_item_with_charges", 1, 1),
    ],
)
def test_quantity_modes_preserve_noncharge_behavior(
    tmp_path: Path,
    shape_class: int,
    ammo: int,
    quantity: int,
    mode: str,
    minimum: int,
    maximum: int,
) -> None:
    write_equipment_world(tmp_path, shape_class, ammo, quantity)
    row = monster_equipment_rows(str(tmp_path), "bg")[0]
    assert (
        row["quantity_mode"],
        row["min_quantity_if_created"],
        row["max_quantity_if_created"],
    ) == (mode, minimum, maximum)


def test_generated_ammo_and_probability_limits_remain_separate(tmp_path: Path) -> None:
    write_equipment_world(tmp_path, ammo=350)
    raw = bytearray((tmp_path / "EQUIP.DAT").read_bytes())
    raw[3] = 150
    (tmp_path / "EQUIP.DAT").write_bytes(raw)
    diagnostics: list[str] = []
    rows = monster_equipment_rows(str(tmp_path), "si", diagnostics=diagnostics)
    ammo = next(row for row in rows if row["generated"])
    assert ammo["item_shape"] == 350 and ammo["quantity"] == "2d10"
    assert (
        ammo["expected_quantity_per_spawn"] == "11.00"
        and ammo["charges_if_created"] == ""
    )
    assert any("above 100" in warning for warning in diagnostics)


def test_cli_table_diagnostics_do_not_contaminate_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ARMOR.DAT").write_bytes(b"\x02" + record(10))
    monkeypatch.setattr(cli, "_resolve_u7_exult_flx", lambda game: None)
    args = SimpleNamespace(
        static=str(tmp_path), kind="armor", game="si", output=None, exult_flx=None
    )
    assert cli.cmd_static_data_dump(args) == 0
    output = capsys.readouterr()
    assert "incomplete" in output.err
    assert len(list(csv.DictReader(io.StringIO(output.out)))) == 1


def test_invalid_record_width_is_rejected() -> None:
    with pytest.raises(ValueError, match="width"):
        read_gameplay_table(b"\x00", 0, "bad.dat")
