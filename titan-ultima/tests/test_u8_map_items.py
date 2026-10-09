"""Complete native map records, containment, render adapters and data commands."""

from __future__ import annotations

import csv
import io
import json
import struct

import pytest
from typer.testing import CliRunner

from titan.u8 import U8MapItems, U8MapItemsError, U8MapRenderer
from titan.u8.cli import u8_app
from titan.u8.map_item_report import format_u8_map_item_report


def item_bytes(
    x=512,
    y=1024,
    z=12,
    shape=400,
    frame=255,
    status=0,
    quality=123,
    npc=42,
    map_num=31,
    next_item=9000,
):
    return struct.pack(
        "<HHBHBHHBBH", x, y, z, shape, frame, status, quality, npc, map_num, next_item
    )


def map_flex(payloads=None):
    payloads = payloads or {3: item_bytes()}
    data = bytearray(128 + 256 * 8)
    data[:84] = b"\x1a" * 84
    struct.pack_into("<I", data, 84, 256)
    data += b"unreferenced gap"
    for map_id, payload in payloads.items():
        struct.pack_into("<II", data, 128 + map_id * 8, len(data), len(payload))
        data += payload
    data += b"dead space from earlier save"
    return bytes(data)


def native_save(payload):
    name = b"nonfixed.dat\x00"
    return (
        b"Ultima 8 SaveGame File.\x00"
        + struct.pack("<HI", 1, len(name))
        + name
        + struct.pack("<I", len(payload))
        + payload
    )


def hierarchy_bytes():
    # The root may be an actor, not a TYPEFLAG family-6 container.
    return b"".join(
        [
            item_bytes(shape=1, next_item=65535),
            item_bytes(x=1, y=0x4321, z=3, shape=64, status=0x0208),
            item_bytes(x=1, shape=800, status=8),
            item_bytes(x=2, shape=801, status=8),
            item_bytes(x=3, shape=802, status=8),
            item_bytes(x=2, shape=803, status=8),
            item_bytes(x=1, shape=804, status=8),
            item_bytes(x=1, shape=999, status=0),  # Small X alone is not containment.
            item_bytes(x=1, shape=805, status=8),
        ]
    )


@pytest.mark.parametrize("kind", ["fixed", "nonfixed"])
def test_complete_fields_offsets_and_byte_preservation(kind):
    raw = map_flex({3: item_bytes(status=0xFF77), 255: item_bytes(quality=65535)})
    data = U8MapItems.from_bytes(raw, kind=kind)
    item = data.get_map(3)[0]
    assert (
        item.x,
        item.y,
        item.z,
        item.shape,
        item.frame,
        item.status,
        item.quality,
        item.npc_num,
        item.map_num_raw,
        item.next_item,
    ) == (
        512,
        1024,
        12,
        400,
        255,
        0xFF77,
        123,
        42,
        31,
        9000,
    )
    assert item.record_index == 0 and item.map_id == 3
    assert raw[item.file_offset : item.file_offset + 16] == item.to_bytes()
    assert data.to_bytes() == raw and len(data.maps) == 256
    assert data.get_map(0) == () and data.get_map(255)[0].quality == 65535
    assert "flipped" in item.status_names() and "contained" not in item.status_names()


def test_unsigned_values_are_preserved_with_native_rejection_diagnostics():
    raw_item = item_bytes(x=65535, y=45000, z=255, shape=65535, npc=255, status=65535)
    item = U8MapItems.from_bytes(map_flex({3: raw_item})).get_map(3)[0]
    assert item.x == 65535 and item.y == 45000 and len(item.status_names()) == 16
    assert item.to_bytes() == raw_item and not item.is_world_object
    assert len(item.diagnostics) == 4


@pytest.mark.parametrize("kind", ["fixed", "nonfixed"])
def test_nested_inventory_parent_root_siblings_unwind_and_gump_coordinates(kind):
    data = U8MapItems.from_bytes(map_flex({3: hierarchy_bytes()}), kind=kind)
    items = data.get_map(3)
    assert [i.parent_record_index for i in items] == [None, 0, 0, 2, 3, 2, 0, None, 7]
    assert [i.root_record_index for i in items] == [0, 0, 0, 0, 0, 0, 0, 7, 7]
    assert [i.record_index for i in items if i.is_world_object] == [0, 7]
    assert all(not i.diagnostics for i in items)
    assert (items[1].gump_x, items[1].gump_y, items[1].equipment_slot) == (
        0x21,
        0x43,
        3,
    )
    assert items[0].gump_x is None and items[2].equipment_slot is None
    # Cached next references must not control the map-local hierarchy.
    assert items[0].next_item == 65535


def test_orphan_depth_zero_and_jump_are_retained_and_diagnosed():
    raw = map_flex(
        {
            3: b"".join(
                [
                    item_bytes(x=1, status=8),
                    item_bytes(),
                    item_bytes(x=0, status=8),
                    item_bytes(),
                    item_bytes(x=3, status=8),
                    item_bytes(),
                    item_bytes(x=1, status=8),
                ]
            )
        }
    )
    items = U8MapItems.from_bytes(raw).get_map(3)
    for index in (0, 2, 4):
        assert items[index].diagnostics and items[index].parent_record_index is None
        assert not items[index].is_world_object
    assert items[6].parent_record_index == 5


def test_null_and_native_rejected_records_do_not_replace_the_previous_parent():
    raw = map_flex(
        {
            3: item_bytes()
            + item_bytes(shape=0)
            + item_bytes(z=254)
            + item_bytes(x=1, status=8)
        }
    )
    items = U8MapItems.from_bytes(raw).get_map(3)
    assert (
        items[1].location_kind == "null_shape"
        and items[2].location_kind == "inactive_z"
    )
    assert items[3].parent_record_index == 0


def test_nonfixed_slot_zero_is_npc_registry_not_world_map_zero():
    raw = map_flex(
        {
            0: item_bytes(shape=1, npc=20, map_num=8) + item_bytes(x=1, status=8),
            8: item_bytes(),
        }
    )
    data = U8MapItems.from_bytes(raw, kind="nonfixed")
    assert data.get_map(0)[0].location_kind == "npc_registry"
    assert data.get_map(0)[0].map_num_raw == 8
    assert data.get_map(0)[1].parent_record_index == 0
    assert set(U8MapRenderer.parse_nonfixed(raw)) == {8}
    # Native loadMapLevel(0) also treats roots in the FIXED pass as NPC records.
    assert U8MapItems.from_bytes(raw).get_map(0)[0].location_kind == "npc_registry"


@pytest.mark.parametrize("kind", ["fixed", "nonfixed"])
def test_render_adapters_keep_full_metadata_and_always_exclude_inventory(kind):
    raw = map_flex({3: hierarchy_bytes()})
    objects = (
        U8MapRenderer.parse_fixed_dat(raw)
        if kind == "fixed"
        else U8MapRenderer.parse_nonfixed(raw)
    )[3]
    assert len(objects) == 2 and objects[0].type_num == 1
    assert objects[0].quality == 123 and objects[0]._quality == 123
    assert objects[0].npc_num == 42 and objects[0].map_num_raw == 31
    assert objects[0].next_item == 65535 and objects[0].source_record is not None
    objects[0]._quality = 99
    assert objects[0].quality == 99
    assert len(U8MapRenderer.parse_nonfixed(raw, bytes(2048 * 8))[3]) == 2


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda b: b.__delitem__(slice(0, len(b))), "header"),
        (lambda b: struct.pack_into("<I", b, 84, 255), "256"),
        (lambda b: b.__delitem__(slice(128, len(b))), "table"),
        (lambda b: struct.pack_into("<II", b, 128 + 3 * 8, 128, 16), "bounds"),
        (lambda b: struct.pack_into("<I", b, 128 + 3 * 8, len(b)), "bounds"),
        (lambda b: struct.pack_into("<I", b, 128 + 3 * 8 + 4, 15), "partial"),
        (
            lambda b: struct.pack_into(
                "<II", b, 128 + 4 * 8, struct.unpack_from("<I", b, 128 + 3 * 8)[0], 16
            ),
            "overlap",
        ),
    ],
)
def test_rejects_malformed_archive_and_partial_items(mutation, match):
    raw = bytearray(map_flex())
    mutation(raw)
    with pytest.raises(U8MapItemsError, match=match):
        U8MapItems.from_bytes(bytes(raw))


def test_invalid_kind_and_map_selections():
    with pytest.raises(U8MapItemsError, match="kind"):
        U8MapItems.from_bytes(map_flex(), kind="bad")
    for value in (-1, 256):
        with pytest.raises(U8MapItemsError, match="0-255"):
            U8MapItems.from_bytes(map_flex()).get_map(value)


def test_glob_expansion_uses_full_quality_and_retains_egg_provenance(tmp_path):
    raw = map_flex({3: item_bytes(shape=2, quality=123)})
    # GLOB's separate 6-byte child format, encoded independently of MapObject.
    (tmp_path / "0123.dat").write_bytes(struct.pack("<HBBBH B", 1, 10, 20, 3, 400, 7))
    parent = U8MapRenderer.parse_fixed_dat(raw)[3][0]
    child = U8MapRenderer.expand_globs([parent], str(tmp_path))[0]
    assert (child.x, child.y, child.z, child.type_num, child.frame) == (
        532,
        1064,
        15,
        400,
        7,
    )
    assert child.quality == 0 and child.status == 0x0082
    assert child.source_record is parent.source_record
    assert child.source_record is not None and child.source_record.glob_num == 123


def test_save_extraction_is_case_insensitive_and_bounds_checked(tmp_path):
    path = tmp_path / "U8SAVE.000"
    raw = map_flex({3: hierarchy_bytes()})
    path.write_bytes(native_save(raw))
    assert U8MapItems.from_file(path, kind="nonfixed").to_bytes() == raw
    assert len(U8MapRenderer.load_nonfixed(str(path))[3]) == 2
    path.write_bytes(native_save(raw)[:-1])
    with pytest.raises(ValueError, match="payload"):
        U8MapItems.from_file(path, kind="nonfixed")


@pytest.mark.parametrize("output_format", ["text", "json", "csv"])
def test_complete_reports_include_raw_fields_links_and_all_slots(output_format):
    data = U8MapItems.from_bytes(map_flex({3: hierarchy_bytes()}))
    report = format_u8_map_item_report(data, view="items", output_format=output_format)
    if output_format == "json":
        rows = json.loads(report)["items"]
    elif output_format == "csv":
        rows = list(csv.DictReader(io.StringIO(report)))
    else:
        assert "parent_record_index" in report and "9000" in report
        return
    assert len(rows) == 9 and int(rows[1]["parent_record_index"]) == 0
    assert rows[1]["raw_hex"] == hierarchy_bytes()[16:32].hex()
    summary = json.loads(format_u8_map_item_report(data, output_format="json"))
    assert len(summary["maps"]) == 256 and summary["total_record_count"] == 9
    assert summary["maps"][3]["contained_count"] == 7


def test_scope_filters_glob_and_optional_typeflag_enrichment():
    data = U8MapItems.from_bytes(
        map_flex(
            {3: item_bytes(shape=2, quality=123) + item_bytes(x=1, shape=64, status=8)}
        )
    )
    types = bytearray(65 * 8)
    # U8 family is the high nibble of byte 1 (source TYPE.H/TypeFlags.cpp).
    types[64 * 8 + 1] = 0x20
    report = json.loads(
        format_u8_map_item_report(
            data,
            view="items",
            scope="contained",
            typeflag_data=bytes(types),
            output_format="json",
        )
    )
    assert len(report["items"]) == 1 and report["items"][0]["family_name"] == "quantity"
    world = json.loads(
        format_u8_map_item_report(
            data, view="items", scope="world", output_format="json"
        )
    )
    assert world["items"][0]["glob_num"] == 123
    empty = format_u8_map_item_report(
        data, view="items", shape=65535, output_format="csv", typeflag_data=bytes(types)
    )
    assert "family_name" in empty and len(empty.splitlines()) == 1


@pytest.mark.parametrize(
    "options,match",
    [
        ({"record_index": 0}, "requires --map"),
        ({"map_id": 3, "record_index": 99}, "outside"),
        ({"view": "bad"}, "view"),
        ({"scope": "bad"}, "scope"),
        ({"output_format": "bad"}, "format"),
        ({"shape": -1}, "shape"),
        ({"typeflag_data": b"bad"}, "TYPEFLAG"),
    ],
)
def test_report_rejects_invalid_selections(options, match):
    with pytest.raises(U8MapItemsError, match=match):
        format_u8_map_item_report(U8MapItems.from_bytes(map_flex()), **options)


@pytest.mark.parametrize("command", ["fixed-dump", "nonfixed-dump"])
def test_commands_exports_help_filters_and_output_protection(tmp_path, command):
    source = tmp_path / "items.dat"
    raw = map_flex({3: hierarchy_bytes()})
    source.write_bytes(native_save(raw) if command == "nonfixed-dump" else raw)
    runner = CliRunner()
    assert runner.invoke(u8_app, [command, "--help"]).exit_code == 0
    result = runner.invoke(
        u8_app,
        [command, str(source), "--map", "3", "--record", "1", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["items"][0]
    assert row["archive_kind"] == command.split("-")[0] and row["equipment_slot"] == 3
    output = tmp_path / "out" / "items.csv"
    args = [
        command,
        str(source),
        "--view",
        "items",
        "--format",
        "csv",
        "-o",
        str(output),
    ]
    assert runner.invoke(u8_app, args).exit_code == 0
    assert len(list(csv.DictReader(io.StringIO(output.read_text())))) == 9
    before = output.read_bytes()
    assert runner.invoke(u8_app, args).exit_code == 1 and output.read_bytes() == before
    result = runner.invoke(u8_app, [command, str(source), "-o", str(source)])
    assert result.exit_code == 1 and "differ" in result.output
    assert runner.invoke(u8_app, [command, str(source), "--record", "0"]).exit_code == 1
    source.write_bytes(b"bad")
    result = runner.invoke(u8_app, [command, str(source)])
    assert result.exit_code == 1 and "ERROR:" in result.output


@pytest.mark.parametrize(
    "command", ["map-render", "map-sample", "map-render-all", "map-sample-all"]
)
def test_existing_map_commands_report_bad_fixed_input_cleanly(tmp_path, command):
    fixed = tmp_path / "FIXED.DAT"
    fixed.write_bytes(b"bad")
    palette = tmp_path / "U8PAL.PAL"
    palette.write_bytes(bytes(772))
    shapes = tmp_path / "shapes"
    shapes.mkdir()
    (shapes / "0000.shp").write_bytes(b"placeholder")
    globs = tmp_path / "globs"
    globs.mkdir()
    (globs / "0000.dat").write_bytes(b"placeholder")
    args = [
        command,
        "--fixed",
        str(fixed),
        "--shapes",
        str(shapes),
        "--globs",
        str(globs),
        "--palette",
        str(palette),
        "-o",
        str(tmp_path / "output"),
    ]
    if command in {"map-render", "map-sample"}:
        args.extend(["--map", "3"])
    result = CliRunner().invoke(u8_app, args)
    assert result.exit_code == 1 and "truncated Flex header" in result.output, (
        result.output
    )


def test_existing_map_input_helpers_report_bad_nonfixed_cleanly(tmp_path, capsys):
    from titan.u8.cli import _load_nonfixed_maps

    source = tmp_path / "NONFIXED.DAT"
    source.write_bytes(b"bad")
    assert _load_nonfixed_maps(str(source)) is None
    assert "ERROR: NONFIXED.DAT: truncated Flex header" in capsys.readouterr().err
