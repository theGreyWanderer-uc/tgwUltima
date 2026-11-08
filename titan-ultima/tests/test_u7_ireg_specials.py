"""Special-record ownership, bounded decoding and serialized readied index semantics."""

from __future__ import annotations

import csv
import io
import json
import struct
from dataclasses import asdict
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.ireg_specials import (
    U7IregExtras,
    read_ireg_index,
    read_ireg_special,
    saved_slot_row,
)
from titan.u7.map import U7MapRenderer
from titan.u7.save import U7NPCData, U7ReadyTypes, _read_ireg_inventory


def special(kind: int, payload: bytes = b"") -> bytes:
    return (
        b"\xff"
        + bytes([kind])
        + (b"" if kind == 2 else struct.pack("<H", len(payload)) + payload)
    )


def integer(value: int) -> bytes:
    return b"\0" + struct.pack("<I", value & 0xFFFFFFFF)


def text(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + struct.pack("<H", len(value)) + value


def script(*values: bytes) -> bytes:
    return (
        struct.pack("<HH", len(values), 0)
        + b"".join(values)
        + struct.pack("<HHI", 7, 1, 123456)
    )


def obj(shape: int = 100, *, children: bool = False) -> bytes:
    payload = bytearray(12 if children else 6)
    payload[2], payload[3] = shape & 255, shape >> 8
    if children:
        payload[4] = 1
    return bytes([len(payload)]) + payload


def index(word: int) -> bytes:
    return b"\x02" + struct.pack("<H", word)


def actor(name: str, flags: int = 0) -> bytes:
    data = bytearray(117)
    struct.pack_into("<H", data, 2, 150)
    struct.pack_into("<H", data, 4, flags)
    struct.pack_into("<H", data, 14, 1)
    data[10], data[18], data[93] = 20, 20, 24
    data[101 : 101 + len(name)] = name.encode("ascii")
    return bytes(data)


def test_scheduled_values_preserve_all_types_and_raw_integer_bits() -> None:
    array = b"\x02\x02\x00" + integer(42) + text(4, b"Example")
    instance = b"\x05\x01\x00" + text(4, b"Class")
    payload = script(integer(-1), text(1, b"a\0\xff"), array, b"\x03\0\0\0\0", instance)
    record, end = read_ireg_special(special(1, payload), 0)
    assert end == len(record.raw)
    assert record.complete and record.decoded_complete
    assert record.payload == payload
    assert record.decoded["frame_index"] == 7 and record.decoded["delay_ms"] == 123456
    values = record.decoded["values"]
    assert isinstance(values, list)
    assert values[0]["value"] == -1 and values[0]["raw_integer"] == 0xFFFFFFFF
    assert values[1]["bytes_hex"] == "6100ff"
    assert values[2]["value"][1]["type"] == "class_symbol"
    assert values[3]["resolved"] is False
    assert values[4]["type"] == "class_object"
    json.dumps(record.as_row())


def test_duplicate_attributes_unsigned_values_and_binary_names_are_preserved() -> None:
    payload = b"rank\0\x01\0rank\0\xff\xff\xffname\0\0\0"
    record, _ = read_ireg_special(special(3, payload), 0)
    assert record.complete and record.decoded_complete
    assert record.decoded["effective"] == {"rank": 65535, "\xffname": 0}
    pairs = record.decoded["pairs"]
    assert isinstance(pairs, list)
    assert [pair["value"] for pair in pairs] == [1, 65535, 0]
    assert pairs[2]["name_hex"] == "ff6e616d65"
    assert record.payload == payload


@pytest.mark.parametrize("payload", [b"unterminated", b"name\0\x01"])
def test_bad_attributes_keep_complete_prefix_pairs(payload: bytes) -> None:
    record, _ = read_ireg_special(special(3, b"ok\0\x03\0" + payload), 0)
    assert record.complete and not record.decoded_complete
    assert record.decoded["effective"] == {"ok": 3}
    assert record.warnings and record.raw == special(3, b"ok\0\x03\0" + payload)


@pytest.mark.parametrize(
    "payload,decoded",
    [
        (b"fn\0", True),
        (b"\0", True),
        (b"\xff\0tail", True),
        (b"fn", False),
        (b"", False),
    ],
)
def test_strings_keep_nul_and_trailing_bytes(payload: bytes, decoded: bool) -> None:
    record, _ = read_ireg_special(special(4, payload), 0)
    assert record.complete and record.decoded_complete == decoded
    assert record.payload == payload
    assert record.decoded["bytes_hex"] == payload.split(b"\0", 1)[0].hex()


@pytest.mark.parametrize("cut", range(1, len(special(1, script(integer(-3))))))
def test_every_truncated_special_prefix_is_bounded_and_retained(cut: int) -> None:
    wire = special(1, script(integer(-3)))
    prefix = wire[:cut]
    record, end = read_ireg_special(prefix, 0)
    assert end == len(prefix)
    assert record.raw == prefix
    assert not record.complete and not record.decoded_complete
    assert record.warnings


@pytest.mark.parametrize(
    "payload",
    [struct.pack("<HH", 1, 0) + b"\x7f", script(integer(1))[:-1], b"\xff\xff\0\0"],
)
def test_bad_script_values_and_footer_stay_inside_the_payload(payload: bytes) -> None:
    wire = special(1, payload) + obj(101)
    record, end = read_ireg_special(wire, 0)
    assert record.complete and not record.decoded_complete
    assert end == len(special(1, payload))
    assert record.warnings
    assert wire[end:] == obj(101)


def test_script_depth_limit_reports_and_retains_wire_bytes() -> None:
    nested = b"\x02\x01\0" * 130 + integer(1)
    wire = special(1, script(nested))
    record, _ = read_ireg_special(wire, 0)
    assert not record.decoded_complete
    assert any("nesting" in warning for warning in record.warnings)
    assert record.raw == wire


@pytest.mark.parametrize(
    "word,expected,slot",
    [
        (0, 0, "head"),
        (3, 3, "left_hand"),
        (17, 17, "usecode_container"),
        (18, 18, ""),
        (127, 127, ""),
        (128, -128, ""),
        (255, -1, ""),
        (65535, -1, ""),
        (0xAB03, 3, "left_hand"),
    ],
)
def test_index_ids_use_signed_low_byte_without_bg_si_ready_translation(
    word: int, expected: int, slot: str
) -> None:
    record, end = read_ireg_index(index(word), 0, 99)
    assert end == 3 and record.raw_word == word
    assert (
        record.scope_offset == 99
        and record.index == expected
        and record.slot_name == slot
    )
    assert saved_slot_row(record)["saved_index_id"] == expected


def test_index_persistence_nested_scope_and_special_ownership_in_both_readers() -> None:
    child_string = special(4, b"child\0")
    parent_script = special(1, script(integer(0x27), integer(5)))
    wire = (
        index(3)
        + obj(522, children=True)
        + obj(100)
        + index(8)
        + obj(101)
        + child_string
        + b"\1"
        + parent_script
        + obj(102)
        + index(255)
        + obj(103)
        + b"\1"
    )
    stream = U7MapRenderer.parse_ireg_stream(wire)
    extras = U7IregExtras()
    items, end = _read_ireg_inventory(wire, 0, extras=extras)
    assert stream.raw == wire and end == len(wire)
    parent, sibling, unreadied = stream.objects
    assert parent.ireg_index_id is not None and parent.ireg_index_id.index == 3
    assert parent.children[0].ireg_index_id is None
    assert (
        parent.children[1].ireg_index_id is not None
        and parent.children[1].ireg_index_id.index == 8
    )
    assert sibling.ireg_index_id is parent.ireg_index_id
    assert unreadied.ireg_index_id is not None and unreadied.ireg_index_id.index == -1
    assert parent.ireg_specials[0].raw == parent_script
    assert parent.children[1].ireg_specials[0].raw == child_string
    assert parent.ireg_specials[0].owner_offset == parent.ireg_offset
    assert [item.shape for item in items] == [522, 100, 101, 102, 103]
    assert items[0].ireg_specials[0].raw == parent_script
    assert items[2].ireg_specials[0].raw == child_string
    assert [asdict(record) for record in extras.indices] == [
        asdict(record) for record in stream.extras.indices
    ]


def test_orphans_unknowns_endmarks_and_partial_indices_are_available_in_stream_report() -> (
    None
):
    orphan = special(99, b"\x01\xff")
    wire = orphan + b"\xff\x02" + obj(101) + b"\x02\xff"
    stream = U7MapRenderer.parse_ireg_stream(wire)
    assert stream.raw == wire and len(stream.objects) == 1
    assert stream.extras.specials[0].owner_offset is None
    assert stream.extras.specials[0].raw == orphan
    assert stream.extras.specials[1].raw == b"\xff\x02"
    assert stream.extras.indices[-1].complete is False
    assert any("no preceding" in warning for warning in stream.extras.warnings)
    assert any("index ID is truncated" in warning for warning in stream.extras.warnings)


@pytest.mark.parametrize("game", ["bg", "si"])
def test_actor_specials_follow_inventory_and_do_not_consume_next_npc(game: str) -> None:
    inventory = index(3) + obj(100) + special(4, b"item\0") + b"\1"
    tail = (
        special(3, b"rank\0\xff\xff")
        + special(1, script(integer(0x46), integer(5)))
        + special(2)
    )
    wire = (
        struct.pack("<HH", 2, 0) + actor("Avatar", 3) + inventory + tail + actor("Iolo")
    )
    parsed = U7NPCData.from_bytes(wire, game=game)
    assert parsed._parsed_bytes == len(wire)
    assert [npc.name for npc in parsed.npcs] == ["Avatar", "Iolo"]
    first = parsed.npcs[0]
    assert (
        first.inventory_ireg is not None
        and bytes.fromhex(first.inventory_ireg.raw_hex) == inventory
    )
    assert [record.type_id for record in first.ireg_specials] == [3, 1, 2]
    assert first.ireg_specials[0].decoded["effective"] == {"rank": 65535}
    assert first.inventory[0].ireg_specials[0].decoded["text"] == "item"
    ready = U7ReadyTypes({100: 8})
    row = next(
        csv.DictReader(io.StringIO(parsed.dump_inventory_csv(ready_types=ready)))
    )
    assert row["ready_slot"] == "right_hand"  # preference is a separate field
    assert row["saved_slot_name"] == "left_hand"
    assert row["location"] == "saved_readied:left_hand"
    assert json.loads(row["ireg_specials"])[0]["decoded"]["text"] == "item"
    actor_row = next(csv.DictReader(io.StringIO(parsed.dump_csv())))
    assert (
        json.loads(actor_row["ireg_specials"])[0]["decoded"]["effective"]["rank"]
        == 65535
    )
    json.dumps(asdict(first))


def test_ready_preference_never_fabricates_saved_assignment() -> None:
    wire = struct.pack("<HH", 1, 0) + actor("Avatar", 1) + obj(100) + b"\1"
    parsed = U7NPCData.from_bytes(wire)
    row = next(
        csv.DictReader(
            io.StringIO(parsed.dump_inventory_csv(ready_types=U7ReadyTypes({100: 8})))
        )
    )
    assert row["saved_slot_name"] == row["saved_index_id"] == ""
    assert row["location"] == "actor_top_slot_unrecorded"


def test_monster_special_and_index_offsets_refer_to_the_original_file() -> None:
    inventory = index(8) + obj(100) + special(4, b"item\0") + b"\1"
    tail = special(3, b"rank\0\x01\0") + special(2)
    wire = struct.pack("<H", 1) + actor("Monster", 3) + inventory + tail
    parsed = U7NPCData.from_monsnpcs_bytes(wire)
    npc = parsed.npcs[0]
    item = npc.inventory[0]
    assert item.ireg_index_id is not None
    assert item.ireg_index_id.offset == 119
    assert wire[item.ireg_index_id.offset : item.ireg_index_id.offset + 3] == index(8)
    assert wire[item.ireg_specials[0].offset :].startswith(special(4, b"item\0"))
    assert wire[npc.ireg_specials[0].offset :].startswith(special(3, b"rank\0\x01\0"))
    assert npc.ireg_specials[0].owner_offset == 2


def test_cli_dumps_complete_evidence_and_refuses_to_replace_inputs_or_reports(
    tmp_path: Path,
) -> None:
    source = tmp_path / "U7IREG00"
    wire = special(9, b"orphan") + index(3) + obj(100) + special(1, script(integer(-1)))
    source.write_bytes(wire)
    output = tmp_path / "inspect.json"
    runner = CliRunner()
    result = runner.invoke(u7_app, ["ireg-dump", str(source), "-o", str(output)])
    assert result.exit_code == 0, result.output
    report = json.loads(output.read_text())
    assert bytes.fromhex(report["stream"]["raw_hex"]) == wire
    assert report["objects"][0]["ireg_index_id"]["slot_name"] == "left_hand"
    assert (
        report["objects"][0]["ireg_specials"][0]["decoded"]["values"][0]["value"] == -1
    )
    assert report["stream"]["specials"][0]["owner_offset"] is None
    original_report = output.read_bytes()
    assert (
        runner.invoke(u7_app, ["ireg-dump", str(source), "-o", str(output)]).exit_code
        == 1
    )
    assert output.read_bytes() == original_report
    assert (
        runner.invoke(u7_app, ["ireg-dump", str(source), "-o", str(source)]).exit_code
        == 1
    )
    assert source.read_bytes() == wire


@pytest.mark.parametrize("game,npc_number", [("bg", -1), ("si", 129)])
def test_cli_honors_game_without_static_metadata(
    tmp_path: Path, game: str, npc_number: int
) -> None:
    payload = bytearray(14)
    payload[2], payload[3], payload[7], payload[8] = 144, 1, 1, 1
    source = tmp_path / "body.ireg"
    source.write_bytes(b"\x0e" + payload)
    result = CliRunner().invoke(u7_app, ["ireg-dump", str(source), "--game", game])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["objects"][0]["ireg_data"]["npc_number"] == npc_number
