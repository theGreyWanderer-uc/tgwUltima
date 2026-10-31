"""Native item/NPC state layout, cache lists, joins and saved-state CLI views."""

from __future__ import annotations

import csv
import io
import json
import struct

import pytest
from typer.testing import CliRunner

from titan.u8 import U8ItemCache, U8ItemCacheError, U8NpcData, U8NpcDataError
from titan.u8.cli import u8_app
from titan.u8.state_report import format_u8_itemcach_report, format_u8_npcdata_report


def state_flex(records: list[bytes]) -> bytes:
    """Encode native Flex without Titan's writer; retain container dead space."""
    data = bytearray(128 + len(records) * 8)
    data[:84] = b"\x1a" * 84
    struct.pack_into("<I", data, 84, len(records))
    for index, record in enumerate(records):
        struct.pack_into("<II", data, 128 + index * 8, len(data), len(record))
        data += record
    data += b"container trailer"
    return bytes(data)


def item_blocks() -> list[bytes]:
    """All but four non-null slots belong to independently encoded free lists."""
    arrays = bytearray(147456)
    # These literal offsets come from the native writer, not imported constants.
    offsets = (0, 18432, 36864, 46080, 64512, 73728, 92160, 110592, 119808, 129024)
    codes = ("H", "H", "B", "H", "B", "H", "H", "B", "B", "H")

    def put(item_id, values):
        for offset, code, value in zip(offsets, codes, values):
            struct.pack_into(
                "<" + code, arrays, offset + item_id * struct.calcsize(code), value
            )

    put(1, (60000, 45000, 253, 1, 52, 64, 65535, 42, 3, 0))
    put(7, (100, 200, 254, 24, 0, 64, 12, 77, 9, 0))
    put(5, (65535, 65535, 255, 555, 255, 65535, 65535, 255, 255, 0))
    put(300, (1, 0xABCD, 5, 241, 10, 0x8208, 25, 0, 0, 0))
    put(301, (256, 512, 12, 123, 255, 0x800, 9, 0, 0, 0))
    free_items = [i for i in range(256, 9216) if i not in {300, 301}]
    free_npcs = [i for i in range(2, 256) if i != 7]
    for ids in (free_items, free_npcs):
        for index, item_id in enumerate(ids):
            struct.pack_into(
                "<H",
                arrays,
                129024 + item_id * 2,
                ids[index + 1] if index + 1 < len(ids) else 0,
            )
    metadata = bytearray(16410)
    struct.pack_into("<5h", metadata, 0, -1, -5, 63, -64, 31)
    struct.pack_into("<H", metadata, 10 + (2 * 64 + 3) * 2, 300)
    struct.pack_into("<H", metadata, 8202 + (2 * 64 + 3) * 2, 1)
    struct.pack_into("<H", metadata, 8202 + (4 * 64 + 5) * 2, 8)
    struct.pack_into(
        "<h6Hh",
        metadata,
        16394,
        len(free_items),
        len(free_npcs),
        256,
        2,
        9215,
        255,
        301,
        1,
    )
    return [bytes(arrays) + b"array tail", bytes(metadata) + b"metadata tail"]


def item_bytes() -> bytes:
    return state_flex(item_blocks())


def npc_bytes() -> bytes:
    data = bytearray(256 * 49)
    record = bytearray(49)
    struct.pack_into("<bbbBBH", record, 0, -1, -128, 127, 255, 7, 0xBEEF)
    record[7:12] = bytes((254, 255, 254, 42, 0xF1))
    record[12:27] = bytes(range(15))
    struct.pack_into(
        "<H8HhH", record, 27, 0xFFFF, 300, 0, 9215, 65535, 7, 301, 0, 0, -200, 0xFFFE
    )
    data[49:98] = record
    data[5 * 49 + 3] = 240  # Garbage remains in a free NPC's record.
    data[7 * 49 + 3] = 10
    data[9 * 49 + 47] = 1  # in_use set, but the paired item slot is free/zero-shape.
    return state_flex([bytes(data) + bytes(range(77))])


def save_bytes(entries: list[tuple[str, bytes]] | None = None) -> bytes:
    if entries is None:
        entries = [("ITEMCACH.DAT", item_bytes()), ("NPCDATA.DAT", npc_bytes())]
    data = bytearray(b"Ultima 8 SaveGame File.\x00" + struct.pack("<H", len(entries)))
    for name, payload in entries:
        raw_name = name.encode("ascii") + b"\x00"
        data += (
            struct.pack("<I", len(raw_name))
            + raw_name
            + struct.pack("<I", len(payload))
            + payload
        )
    return bytes(data)


def test_item_arrays_preserve_unsigned_values_sparse_ids_and_contained_context():
    data = U8ItemCache.from_bytes(item_bytes())
    item = data.get_item(1)
    assert (
        item.x,
        item.y,
        item.z,
        item.shape,
        item.frame_low,
        item.status,
        item.quality,
        item.npc_num,
        item.map_num_raw,
        item.next_item,
    ) == (60000, 45000, 253, 1, 52, 64, 65535, 42, 3, 0)
    contained = data.get_item(300)
    assert contained.container_id == 1 and contained.location_kind == "contained"
    assert contained.status_names() == [
        "contained",
        "equipped",
        "has_item_relative_gump",
    ]
    assert data.get_item(7).location_kind == "inactive_z"
    assert data.get_item(301).location_kind == "ethereal"
    assert data.get_item(1).location_kind == "inactive_z"
    assert data.get_item(1).container_id is None
    assert [item.item_id for item in data.iter_items()] == [1, 7, 300, 301]
    assert len(list(data.iter_items(include_free=True))) == 9216
    assert (
        data.slot_membership(5) == "free_npc"
    )  # Nonzero stale shape is not occupancy.
    assert data.slot_membership(256) == "free_item"
    assert data.slot_membership(301) == "ethereal"
    assert data.slot_membership(0) == "null"


def test_complete_cache_metadata_uses_native_16_bit_ints_and_rx_ry_order():
    data = U8ItemCache.from_bytes(item_bytes())
    meta = data.metadata
    assert (meta.map_in, meta.min_sum, meta.max_sum, meta.min_diff, meta.max_diff) == (
        -1,
        -5,
        63,
        -64,
        31,
    )
    assert len(meta.regions) == 4096
    region = meta.regions[2 * 64 + 3]
    assert (region.rx, region.ry, region.head, region.item_count) == (2, 3, 300, 1)
    assert (
        meta.free_count,
        meta.free_npc_count,
        meta.first_free,
        meta.first_free_npc,
        meta.last_free,
        meta.last_free_npc,
        meta.ethereal_top,
        meta.ethereal_count,
    ) == (8958, 253, 256, 2, 9215, 255, 301, 1)
    assert data.list_diagnostics() == []
    assert data.ethereal_items.item_ids == (301,)
    assert data.array_tail == b"array tail" and meta.trailing_bytes == b"metadata tail"
    assert data.to_bytes() == item_bytes()


def test_npc_packed_fields_high_frame_byte_flags_equipment_and_tail():
    data = U8NpcData.from_bytes(npc_bytes())
    npc = data.get_npc(1)
    assert (
        npc.strength,
        npc.dexterity,
        npc.intelligence,
        npc.hitpoints,
        npc.direction,
        npc.last_action,
        npc.frame_hi,
        npc.animation_step,
        npc.fall_start_z,
        npc.unknown_0a,
    ) == (-1, -128, 127, 255, 7, 0xBEEF, 254, 255, 254, 42)
    assert npc.alignment == 1 and npc.enemy_alignment == 0xF0
    assert npc.unknown_0c_1a == bytes(range(15))
    assert npc.control_flags == 65535 and npc.state_flags == 65534
    assert npc.equipment == (300, 0, 9215, 65535, 7, 301, 0, 0)
    assert npc.mana == -200 and not npc.in_use
    assert "invincible" in npc.flag_names() and "pathfinding" in npc.flag_names()
    assert "in_use" not in npc.flag_names()
    assert npc.full_frame(52) == 0xFE34
    assert len(npc.raw) == 49
    assert len(list(data.iter_npcs())) == 256
    assert data.trailing_bytes == bytes(range(77))
    assert data.to_bytes() == npc_bytes()


@pytest.mark.parametrize(
    "control,state,expected",
    [
        (0x0010, 0, ["animation_failed"]),
        (0, 0x0020, ["weapon_hit"]),
        (0x0010, 0x0020, ["animation_failed", "weapon_hit"]),
        (0xFFE0, 0, []),
    ],
)
def test_npc_animation_latches_use_native_word_offsets_and_preserve_raw_bytes(
    control, state, expected
):
    record = bytearray(256 * 49)
    struct.pack_into("<H", record, 7 * 49 + 0x1B, control)
    struct.pack_into("<H", record, 7 * 49 + 0x2F, state)
    raw = state_flex([bytes(record)])
    data = U8NpcData.from_bytes(raw)
    assert data.get_npc(7).flag_names() == expected
    assert data.to_bytes() == raw
    for output_format in ("text", "json", "csv"):
        output = format_u8_npcdata_report(data, npc_id=7, output_format=output_format)
        for label in expected:
            assert label in output
        assert "unknown_flag1b_4" not in output
        assert "unknown_flag2f_5" not in output
    row = json.loads(format_u8_npcdata_report(data, npc_id=7, output_format="json"))[
        "npcs"
    ][0]
    assert row["control_flags"] == control and row["state_flags"] == state
    assert row["unknown_control_bits"] == control & 0xFFE0


@pytest.mark.parametrize("index", [-1, 9216])
def test_item_ids_outside_native_table_raise(index):
    with pytest.raises(U8ItemCacheError):
        U8ItemCache.from_bytes(item_bytes()).get_item(index)


@pytest.mark.parametrize("index", [-1, 256])
def test_npc_ids_outside_native_table_raise(index):
    with pytest.raises(U8NpcDataError):
        U8NpcData.from_bytes(npc_bytes()).get_npc(index)


@pytest.mark.parametrize("low", [-1, 256])
def test_full_frame_requires_a_low_byte(low):
    with pytest.raises(U8NpcDataError):
        U8NpcData.from_bytes(npc_bytes()).get_npc(1).full_frame(low)


@pytest.mark.parametrize(
    "head,expected", [(65535, "outside"), (-1, "outside"), (300, "cycle")]
)
def test_corrupt_lists_stop_and_report_issues_without_rejecting_raw_data(
    head, expected
):
    blocks = item_blocks()
    arrays = bytearray(blocks[0])
    struct.pack_into("<H", arrays, 129024 + 300 * 2, 300)
    data = U8ItemCache.from_bytes(state_flex([bytes(arrays), blocks[1]]))
    chain = data.trace_chain(head)
    assert expected in chain.issues[0]
    assert len(chain.item_ids) <= 1
    assert data.trace_chain(0).item_ids == ()


def test_cache_list_diagnostics_report_bad_counts_tails_and_overlaps():
    blocks = item_blocks()
    meta = bytearray(blocks[1])
    struct.pack_into("<h6Hh", meta, 16394, -1, 253, 2, 2, 1, 255, 301, 1)
    data = U8ItemCache.from_bytes(state_flex([blocks[0], bytes(meta)]))
    issues = data.list_diagnostics()
    assert any("stored count -1" in issue for issue in issues)
    assert any("stored tail 1" in issue for issue in issues)
    assert any("lists overlap" in issue for issue in issues)


@pytest.mark.parametrize("kind,parser", [("item", U8ItemCache), ("npc", U8NpcData)])
@pytest.mark.parametrize(
    "case", ["header", "count", "table", "bounds", "overlap", "magic", "payload"]
)
def test_state_container_and_required_block_truncations_are_rejected(
    kind, parser, case
):
    raw = bytearray(item_bytes() if kind == "item" else npc_bytes())
    if case == "header":
        raw = raw[:100]
    elif case == "count":
        struct.pack_into("<I", raw, 84, 65)
    elif case == "table":
        raw = raw[:135]
    elif case == "bounds":
        struct.pack_into("<I", raw, 128, len(raw))
    elif case == "overlap":
        struct.pack_into("<I", raw, 128, 128)
    elif case == "magic":
        raw[:84] = bytes(84)
    elif case == "payload":
        raw = bytearray(
            state_flex([bytes(147455), item_blocks()[1]])
            if kind == "item"
            else state_flex([bytes(12543)])
        )
    with pytest.raises(ValueError):
        parser.from_bytes(bytes(raw))


def test_truncated_cache_metadata_is_rejected():
    with pytest.raises(U8ItemCacheError, match="cache metadata"):
        U8ItemCache.from_bytes(state_flex([item_blocks()[0], bytes(16409)]))


def test_loose_files_and_case_insensitive_save_entries_preserve_inner_bytes(tmp_path):
    source = tmp_path / "U8SAVE.000"
    source.write_bytes(
        save_bytes([("itemcach.dat", item_bytes()), ("npcdata.dat", npc_bytes())])
    )
    assert U8ItemCache.from_file(source).to_bytes() == item_bytes()
    assert U8NpcData.from_file(source).to_bytes() == npc_bytes()
    for name, raw, parser in (
        ("ITEMCACH.DAT", item_bytes(), U8ItemCache),
        ("NPCDATA.DAT", npc_bytes(), U8NpcData),
    ):
        path = tmp_path / name
        path.write_bytes(raw)
        assert parser.from_file(str(path)).to_bytes() == raw


@pytest.mark.parametrize(
    "case", ["missing", "name_length", "terminator", "payload", "duplicate", "header"]
)
def test_malformed_save_entries_are_validated_before_extraction(tmp_path, case):
    raw = bytearray(save_bytes())
    if case == "missing":
        raw = bytearray(save_bytes([("OTHER.DAT", b"other")]))
    elif case == "name_length":
        struct.pack_into("<I", raw, 26, 0xFFFFFFFF)
    elif case == "terminator":
        raw[30 + len("ITEMCACH.DAT")] = 1
    elif case == "payload":
        raw = raw[:-1]
    elif case == "duplicate":
        raw = bytearray(
            save_bytes([("ITEMCACH.DAT", item_bytes()), ("itemcach.dat", item_bytes())])
        )
    elif case == "header":
        raw = raw[:24]
    path = tmp_path / "U8SAVE.000"
    path.write_bytes(raw)
    with pytest.raises(U8ItemCacheError):
        U8ItemCache.from_file(path)


def test_item_reports_show_all_metadata_and_filters_preserve_explicit_free_slots():
    data = U8ItemCache.from_bytes(item_bytes())
    report = json.loads(format_u8_itemcach_report(data, output_format="json"))
    assert [row["item_id"] for row in report["items"]] == [1, 7, 300, 301]
    assert len(report["cache"]["regions"]) == 4096
    assert len(report["lists"]["free_items"]["item_ids"]) == 8958
    assert report["array_trailing_bytes"] == b"array tail".hex()
    contained = report["items"][2]
    assert contained["gump_x"] == 205 and contained["gump_y"] == 171
    assert "has_item_relative_gump" in contained["status_names"]
    free = json.loads(format_u8_itemcach_report(data, item_id=5, output_format="json"))
    assert free["items"][0]["slot_membership"] == "free_npc"
    rows = list(
        csv.DictReader(
            io.StringIO(format_u8_itemcach_report(data, shape=241, output_format="csv"))
        )
    )
    assert len(rows) == 1 and rows[0]["item_id"] == "300"
    assert json.loads(rows[0]["status_names"]) == [
        "contained",
        "equipped",
        "has_item_relative_gump",
    ]
    assert "No slots match" in format_u8_itemcach_report(data, shape=1234)


def test_region_reports_use_xy_order_and_keep_counts_without_heads():
    data = U8ItemCache.from_bytes(item_bytes())
    rows = list(
        csv.DictReader(
            io.StringIO(
                format_u8_itemcach_report(data, view="regions", output_format="csv")
            )
        )
    )
    assert rows == [
        {"rx": "2", "ry": "3", "head": "300", "item_count": "1"},
        {"rx": "4", "ry": "5", "head": "0", "item_count": "8"},
    ]
    all_rows = list(
        csv.DictReader(
            io.StringIO(
                format_u8_itemcach_report(
                    data, view="regions", all_slots=True, output_format="csv"
                )
            )
        )
    )
    assert len(all_rows) == 4096


def test_paired_npc_report_uses_cache_not_in_use_and_resolves_equipment_without_guessing():
    cache = U8ItemCache.from_bytes(item_bytes())
    npcs = U8NpcData.from_bytes(npc_bytes())
    report = json.loads(
        format_u8_npcdata_report(npcs, item_cache=cache, output_format="json")
    )
    assert [row["npc_id"] for row in report["npcs"]] == [1, 7]
    npc = report["npcs"][0]
    assert npc["item_frame"] == 0xFE34 and not npc["in_use"]
    assert npc["item_npc_num"] == 42 and npc["npc_id"] == 1
    assert npc["equipment_items"][0]["item"]["shape"] == 241
    assert npc["equipment_items"][0]["item"]["container_id"] == 1
    assert npc["equipment_items"][1]["item"] is None
    assert npc["equipment_items"][2]["item"]["slot_membership"] == "free_item"
    assert "outside" in npc["equipment_items"][3]["issue"]
    assert npc["unknown_control_bits"] == 0xFFE0
    csv_rows = list(
        csv.DictReader(
            io.StringIO(
                format_u8_npcdata_report(
                    npcs, item_cache=cache, map_num=3, output_format="csv"
                )
            )
        )
    )
    assert len(csv_rows) == 1 and csv_rows[0]["npc_id"] == "1"
    assert json.loads(csv_rows[0]["equipment"])[0] == 300
    assert len(json.loads(csv_rows[0]["equipment_items"])) == 8


def test_npc_unpaired_all_and_explicit_views_do_not_invent_item_data():
    data = U8NpcData.from_bytes(npc_bytes())
    report = json.loads(format_u8_npcdata_report(data, output_format="json"))
    assert [row["npc_id"] for row in report["npcs"]] == [1, 5, 7, 9]
    assert report["npcs"][0]["item_frame"] is None
    assert "activity unknown" in report["selection_basis"]
    all_rows = json.loads(
        format_u8_npcdata_report(data, all_slots=True, output_format="json")
    )["npcs"]
    assert len(all_rows) == 256 and all_rows[0]["npc_id"] == 0
    explicit = json.loads(
        format_u8_npcdata_report(data, npc_id=0, output_format="json")
    )
    assert len(explicit["npcs"]) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"item_id": 9216},
        {"shape": 65536},
        {"view": "unknown"},
        {"view": "regions", "item_id": 1},
        {"output_format": "xml"},
    ],
)
def test_item_report_invalid_options_raise(kwargs):
    with pytest.raises(ValueError):
        format_u8_itemcach_report(U8ItemCache.from_bytes(item_bytes()), **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [{"npc_id": 256}, {"map_num": 256}, {"map_num": 3}, {"output_format": "xml"}],
)
def test_npc_report_invalid_options_raise(kwargs):
    with pytest.raises(ValueError):
        format_u8_npcdata_report(U8NpcData.from_bytes(npc_bytes()), **kwargs)


@pytest.mark.parametrize(
    "command,tokens",
    [
        (
            "itemcach-dump",
            (
                "ITEMCACH.DAT",
                "--item",
                "--shape",
                "--view",
                "--all-slots",
                "--format",
                "--output",
            ),
        ),
        (
            "npcdata-dump",
            (
                "NPCDATA.DAT",
                "--itemcach",
                "--npc",
                "--map",
                "--all-slots",
                "--format",
                "--output",
            ),
        ),
    ],
)
def test_cli_help_contract(command, tokens):
    result = CliRunner().invoke(u8_app, [command, "--help"])
    assert result.exit_code == 0, result.output
    for token in tokens:
        assert token in result.output


def test_both_commands_accept_save_and_npc_command_pairs_snapshot_automatically(
    tmp_path,
):
    source = tmp_path / "U8SAVE.000"
    source.write_bytes(save_bytes())
    runner = CliRunner()
    result = runner.invoke(
        u8_app, ["itemcach-dump", str(source), "--item", "300", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["items"][0]["container_id"] == 1
    output = tmp_path / "reports" / "npcs.json"
    result = runner.invoke(
        u8_app,
        [
            "npcdata-dump",
            str(source),
            "--map",
            "3",
            "--format",
            "json",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(output.read_text())
    assert report["paired_item_cache"] and report["npcs"][0]["item_frame"] == 0xFE34
    assert source.read_bytes() == save_bytes()


def test_npc_command_accepts_loose_pair_and_unpaired_file(tmp_path):
    source = tmp_path / "NPCDATA.DAT"
    source.write_bytes(npc_bytes())
    cache = tmp_path / "ITEMCACH.DAT"
    cache.write_bytes(item_bytes())
    runner = CliRunner()
    result = runner.invoke(
        u8_app,
        [
            "npcdata-dump",
            str(source),
            "--itemcach",
            str(cache),
            "--npc",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["npcs"][0]["item_frame"] == 0xFE34
    result = runner.invoke(
        u8_app, ["npcdata-dump", str(source), "--npc", "1", "--format", "json"]
    )
    assert result.exit_code == 0 and not json.loads(result.output)["paired_item_cache"]


@pytest.mark.parametrize("command", ["itemcach-dump", "npcdata-dump"])
@pytest.mark.parametrize("target", ["source", "existing"])
def test_cli_preserves_save_and_existing_output(tmp_path, command, target):
    source = tmp_path / "U8SAVE.000"
    source.write_bytes(save_bytes())
    existing = tmp_path / "existing.txt"
    existing.write_text("keep")
    output = source if target == "source" else existing
    before = output.read_bytes()
    result = CliRunner().invoke(u8_app, [command, str(source), "-o", str(output)])
    assert result.exit_code == 1 and output.read_bytes() == before


def test_npc_command_protects_explicit_item_cache_source(tmp_path):
    source = tmp_path / "NPCDATA.DAT"
    source.write_bytes(npc_bytes())
    cache = tmp_path / "ITEMCACH.DAT"
    cache.write_bytes(item_bytes())
    result = CliRunner().invoke(
        u8_app,
        ["npcdata-dump", str(source), "--itemcach", str(cache), "-o", str(cache)],
    )
    assert result.exit_code == 1 and cache.read_bytes() == item_bytes()


@pytest.mark.parametrize(
    "command,options",
    [
        ("itemcach-dump", ["--item", "9216"]),
        ("itemcach-dump", ["--view", "other"]),
        ("npcdata-dump", ["--npc", "256"]),
        ("npcdata-dump", ["--format", "xml"]),
    ],
)
def test_cli_invalid_options_do_not_create_reports(tmp_path, command, options):
    source = tmp_path / "U8SAVE.000"
    source.write_bytes(save_bytes())
    output = tmp_path / "reports" / "output.txt"
    result = CliRunner().invoke(
        u8_app, [command, str(source), *options, "-o", str(output)]
    )
    assert result.exit_code != 0 and not output.exists()


@pytest.mark.parametrize("command", ["itemcach-dump", "npcdata-dump"])
def test_cli_malformed_input_has_controlled_error_and_no_output(tmp_path, command):
    source = tmp_path / "broken.dat"
    source.write_bytes(b"broken")
    output = tmp_path / "output.json"
    result = CliRunner().invoke(u8_app, [command, str(source), "-o", str(output)])
    assert result.exit_code == 1 and "ERROR:" in result.output
    assert not output.exists()
