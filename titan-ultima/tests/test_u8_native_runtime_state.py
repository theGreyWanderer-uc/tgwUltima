"""Avatar/UI bytes, kernel process inventories and integrated native save views."""

from __future__ import annotations

import csv
import io
import json
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u8.avatar import U8AvatarState
from titan.u8.cli import u8_app
from titan.u8.gumps import U8GumpState
from titan.u8.kernel import U8KernelState
from titan.u8.native_state_report import (
    format_u8_avatar_report,
    format_u8_gumps_report,
    format_u8_kernel_report,
)
from titan.u8.save_diff import compare_u8_save_snapshots
from titan.u8.save_state import U8SaveSnapshot, describe_u8_save_snapshot

from tests.test_u8_save_state import native_flex, native_save


def avatar_bytes() -> bytes:
    raw = bytearray(77)
    struct.pack_into("<3h", raw, 0, -32768, 650, 32767)
    raw[6:38] = b"Av\x82\x00" + bytes(range(28))
    struct.pack_into("<h", raw, 38, -1)
    raw[40:44] = bytes((255, 2, 3, 4))
    struct.pack_into("<hI", raw, 44, -5, 0xFFFFFFFF)
    raw[50:52] = b"\xff\xaa"
    struct.pack_into("<HbbBB", raw, 52, 0x8000, -1, -2, 200, 6)
    struct.pack_into("<6h", raw, 58, -32000, 32000, -3, 4, -5, 6)
    raw[70:77] = bytes((7, 8, 9, 10, 11, 12, 13))
    return bytes(raw)


def container_bytes(ref: int = 300, *, frame: int = 32767) -> bytes:
    return (
        b"\x00\x00"
        + b"CONTAINER GUMP".ljust(16, b"\x00")
        + b"REF="
        + struct.pack("<H", ref)
        + b"RECT="
        + struct.pack("<4h", -10, -20, 100, 200)
        + struct.pack("<4h", -3, 4, 5, -6)
        + struct.pack("<HHB", 65535, 32768, 254)
        + b"SHAPE="
        + struct.pack("<h", -1)
        + b"FRAME="
        + struct.pack("<h", frame)
    )


def gumps_bytes(
    records: list[bytes] | None = None, *, count: int | None = None
) -> bytes:
    records = records or []
    rects = b"".join(
        struct.pack("<4h", -index, index, index + 10, index + 20) for index in range(16)
    )
    return (
        b"CONTAINER GUMPS START HERE".ljust(32, b"\x00")
        + b"".join(records)
        + b"\xff\xff"
        + b"CONTAINER RECTS".ljust(16, b"\x00")
        + rects
        + b"GUMP COUNTER".ljust(16, b"\x00")
        + struct.pack("<h", len(records) if count is None else count)
    )


def process_bytes(slot: int, *, process_type: int = 240, result: int = -200) -> bytes:
    raw = bytearray(42)
    struct.pack_into("<4H", raw, 0, 0xC0FE, slot, 300, process_type)
    raw[8:10] = bytes((0xA1, 0xAA))
    struct.pack_into("<i4H", raw, 10, result, 0xFFFF, 0xFFFD, 4, 5)
    struct.pack_into("<3HI", raw, 22, 0x1111, 2, 240, 0xDEADBEEF)
    struct.pack_into("<3HI", raw, 32, 0x2222, 1, 0, 0xFFEEDDCC)
    return bytes(raw) + b"derived bytes"


def kernel_records(*, changed: bool = False) -> list[bytes]:
    records = [b""] * 16  # 10 shared + 2 records per slot, 3 slots.
    records[0] = b"Defines=f7e Id=Kernel Ver. 1.00 - fixture\x00"
    statics = bytearray(157)
    struct.pack_into("<4H", statics, 14, 3, 2, 0, 55)
    struct.pack_into("<I", statics, 42, 123456 if changed else 123455)
    records[1] = bytes(statics)
    records[2] = struct.pack("<3H", 0, 2, 0x408)
    p0 = process_bytes(0, process_type=2)
    p2 = process_bytes(2, result=-201 if changed else -200)
    records[3] = struct.pack("<3H", len(p0), 0, len(p2))
    records[4] = bytes(1152)
    records[5] = bytes(9216)
    records[6] = struct.pack("<32H", 0, 2, *([0] * 30))
    records[7] = bytes(12)
    records[8] = b"unused slot preserved"
    records[10], records[11] = p0, b""
    records[14], records[15] = p2, b"raw auxiliary payload"
    return records


def test_avatar_full_signed_fields_raw_options_unknowns_and_name_bytes():
    raw = avatar_bytes()
    avatar = U8AvatarState.from_bytes(raw)
    assert (
        avatar.strength_points,
        avatar.intelligence_points,
        avatar.dexterity_points,
    ) == (-32768, 650, 32767)
    assert avatar.name == "Avé" and avatar.name_raw == raw[6:38]
    assert avatar.sex == -1 and avatar.in_stasis == -5
    assert (
        avatar.power_avatar_raw,
        avatar.hackmover_raw,
        avatar.cheater_raw,
        avatar.can_cheat_raw,
    ) == (255, 2, 3, 4)
    assert avatar.random_seed_raw == 0xFFFFFFFF and avatar.random_seed_signed == -1
    assert avatar.music_track_raw == 255 and avatar.footsteps_raw == 32768
    assert avatar.language_raw == -1 and avatar.language_code is None
    assert (
        avatar.text_speed_raw == -2
        and avatar.hunger == 200
        and avatar.cant_save_raw == 6
    )
    assert avatar.backpack_position == (-32000, 32000)
    assert avatar.status_gump_position == (-3, 4) and avatar.unknown_point_42 == (-5, 6)
    assert (avatar.speed_limiting_raw, avatar.sound_on_raw, avatar.music_on_raw) == (
        7,
        8,
        9,
    )
    assert avatar.padding_33 == b"\xaa" and avatar.padding_49 == bytes((10, 11, 12, 13))
    assert avatar.to_bytes() == raw


@pytest.mark.parametrize("size", [0, 76, 78])
def test_avatar_rejects_incomplete_or_extra_state(size: int):
    with pytest.raises(ValueError, match="expected 77"):
        U8AvatarState.from_bytes(bytes(size))


def test_avatar_name_without_nul_and_language_order():
    raw = bytearray(avatar_bytes())
    raw[6:38] = b"A" * 32
    raw[54] = 2
    avatar = U8AvatarState.from_bytes(bytes(raw))
    assert avatar.name == "A" * 32 and avatar.language_code == "G"


def test_empty_gumps_footer_retains_all_rectangles_and_counter():
    raw = gumps_bytes()
    assert len(raw) == 196
    data = U8GumpState.from_bytes(raw)
    assert not data.containers and data.gump_count == 0 and not data.diagnostics()
    assert data.rects[15] == (-15, 15, 25, 35)
    assert data.to_bytes() == raw
    report = json.loads(format_u8_gumps_report(data, output_format="json"))
    assert (
        report["container_count"] == 0
        and report["rows"] == []
        and report["raw_hex"] == raw.hex()
    )
    csv_rows = list(
        csv.DictReader(
            io.StringIO(format_u8_gumps_report(data, view="rects", output_format="csv"))
        )
    )
    assert len(csv_rows) == 16 and csv_rows[-1]["left"] == "-15"
    assert (
        "container_id"
        in format_u8_gumps_report(data, output_format="csv").splitlines()[0]
    )


def test_gumps_record_offsets_signed_screen_unsigned_world_and_raw_roundtrip():
    raw = gumps_bytes([container_bytes(65535)])
    assert len(raw) == 262
    data = U8GumpState.from_bytes(raw)
    record = data.containers[0]
    assert (
        record.file_offset == 32 and record.index == 0 and record.container_id == 65535
    )
    assert (
        record.rect == (-10, -20, 100, 200)
        and record.drag_offset == (-3, 4)
        and record.drag_start == (5, -6)
    )
    assert record.world_location == (65535, 32768, 254)
    assert record.shape == -1 and record.frame == 32767
    assert record.raw_data == container_bytes(65535)
    assert data.gump_count == 1 and data.to_bytes() == raw


@pytest.mark.parametrize(
    "case",
    [
        "truncated",
        "notice",
        "record_label",
        "sentinel",
        "rect_label",
        "count_label",
        "extra",
    ],
)
def test_gumps_validates_records_markers_and_exact_footer(case: str):
    raw = bytearray(gumps_bytes([container_bytes()]))
    if case == "truncated":
        raw = raw[:-1]
    elif case == "notice":
        raw[0] = 0
    elif case == "record_label":
        raw[50] = 0
    elif case == "sentinel":
        raw[98:100] = b"\x00\x00"
    elif case == "rect_label":
        raw[100] = 0
    elif case == "count_label":
        raw[-18] = 0
    else:
        raw += b"extra"
    with pytest.raises(ValueError):
        U8GumpState.from_bytes(bytes(raw))


def test_gumps_counter_residue_diagnostic_is_not_a_parse_failure():
    data = U8GumpState.from_bytes(gumps_bytes(count=-1))
    assert data.gump_count == -1 and len(data.diagnostics()) == 2


def test_kernel_inventory_native_sizes_process_prefix_lists_and_pointers():
    raw = native_flex(kernel_records())
    data = U8KernelState.from_bytes(raw)
    assert (
        data.max_processes == 3 and len(data.records) == 16 and len(data.processes) == 2
    )
    assert data.build_defines == 0xF7E and data.realtime_words == (0, 2, 0x408)
    assert data.core_fields()["current_tick"] == 123455
    assert data.priority_counts[1] == 2
    process = data.processes[1]
    assert (
        process.slot == process.pid == 2
        and process.object_record == 14
        and process.payload_record == 15
    )
    assert process.ref == 300 and process.process_type == 240 and process.result == -200
    assert process.priority_raw == 0xA1 and process.padding_09 == 0xAA
    assert process.flags == 65535 and len(process.flag_names()) == 16
    assert (
        process.save_flags_raw == 65533
        and process.allocations == 4
        and process.message_groups == 5
    )
    assert (
        process.depend_count == 2
        and process.depend_linear_type == 240
        and process.depend_pointer_raw == 0xDEADBEEF
    )
    assert process.notify_count == 1 and process.notify_pointer_raw == 0xFFEEDDCC
    assert (
        process.derived_object_bytes == b"derived bytes"
        and process.raw_payload == b"raw auxiliary payload"
    )
    assert data.records[8] == b"unused slot preserved" and data.to_bytes() == raw
    assert not data.diagnostics()
    report = json.loads(
        format_u8_kernel_report(data, view="processes", slot=2, output_format="json")
    )
    assert len(report["rows"]) == 1 and report["rows"][0]["priority"] == 1
    assert report["rows"][0]["object_hex"] == process.raw_object.hex()
    empty_csv = format_u8_kernel_report(
        data, view="processes", slot=1, output_format="csv"
    )
    assert (
        "pid" in empty_csv.splitlines()[0]
        and list(csv.DictReader(io.StringIO(empty_csv))) == []
    )


@pytest.mark.parametrize(
    "case",
    [
        "description",
        "statics",
        "capacity",
        "sizes",
        "quick_refs",
        "quick_types",
        "priorities",
        "pointers",
        "realtime",
        "process_size",
        "unused_payload",
        "short_object",
    ],
)
def test_kernel_rejects_unsupported_or_inconsistent_record_layouts(case: str):
    records = kernel_records()
    if case == "description":
        records[0] = b"Defines=f7e Id=Kernel Ver. 2.00\x00"
    elif case == "statics":
        records[1] = records[1][:-1]
    elif case == "capacity":
        raw = bytearray(records[1])
        struct.pack_into("<H", raw, 14, 4)
        records[1] = bytes(raw)
    elif case == "sizes":
        records[3] = b""
    elif case == "quick_refs":
        records[4] = records[4][:-1]
    elif case == "quick_types":
        records[5] = records[5][:-1]
    elif case == "priorities":
        records[6] = records[6][:-1]
    elif case == "pointers":
        records[7] = records[7][:-1]
    elif case == "realtime":
        records[2] += b"x"
    elif case == "process_size":
        records[14] = records[14][:-1]
    elif case == "unused_payload":
        records[13] = b"not empty"
    else:
        records[10] = bytes(41)
        sizes = bytearray(records[3])
        struct.pack_into("<H", sizes, 0, 41)
        records[3] = bytes(sizes)
    with pytest.raises(ValueError):
        U8KernelState.from_bytes(native_flex(records))


def test_kernel_rejects_directory_bounds_and_overlap():
    raw = bytearray(native_flex(kernel_records()))
    with pytest.raises(ValueError, match="truncated"):
        U8KernelState.from_bytes(bytes(raw[:127]))
    struct.pack_into("<I", raw, 84, 15)
    with pytest.raises(ValueError, match="paired"):
        U8KernelState.from_bytes(bytes(raw))
    raw = bytearray(native_flex(kernel_records()))
    statics_offset = struct.unpack_from("<I", raw, 136)[0]
    struct.pack_into("<I", raw, 128 + 2 * 8, statics_offset)
    with pytest.raises(ValueError, match="overlap"):
        U8KernelState.from_bytes(bytes(raw))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"view": "unknown"},
        {"slot": 0},
        {"record": 0},
        {"view": "processes", "slot": 3},
        {"view": "records", "record": 16},
        {"output_format": "xml"},
    ],
)
def test_kernel_report_validates_view_and_filters(kwargs):
    with pytest.raises(ValueError):
        format_u8_kernel_report(
            U8KernelState.from_bytes(native_flex(kernel_records())), **kwargs
        )


def test_new_layouts_save_overview_and_field_differences(tmp_path: Path):
    before_file, after_file = tmp_path / "before.save", tmp_path / "after.save"
    avatar_after = bytearray(avatar_bytes())
    struct.pack_into("<h", avatar_after, 0, 10)
    before_file.write_bytes(
        native_save(
            [
                ("AVATAR.DAT", avatar_bytes()),
                ("GUMPS.DAT", gumps_bytes()),
                ("KERNEL.DAT", native_flex(kernel_records())),
            ]
        )
    )
    after_file.write_bytes(
        native_save(
            [
                ("AVATAR.DAT", bytes(avatar_after)),
                ("GUMPS.DAT", gumps_bytes([container_bytes()])),
                ("KERNEL.DAT", native_flex(kernel_records(changed=True))),
            ]
        )
    )
    before, after = (
        U8SaveSnapshot.from_path(before_file),
        U8SaveSnapshot.from_path(after_file),
    )
    overview = describe_u8_save_snapshot(after)
    assert not overview["decode_errors"]
    assert {row["name"]: row["decode_status"] for row in overview["entries"]} == {
        "AVATAR.DAT": "decoded",
        "GUMPS.DAT": "decoded",
        "KERNEL.DAT": "partial",
    }
    assert (
        overview["avatar"]["strength_points"] == 10
        and overview["gumps"]["container_count"] == 1
    )
    assert overview["kernel"]["saved_process_count"] == 2
    diff = compare_u8_save_snapshots(before, after)
    assert diff["sections"]["avatar_fields"]["rows"] == [
        {"field": "strength_points", "before": -32768, "after": 10}
    ]
    assert diff["sections"]["gump_counter"]["total_count"] == 1
    assert diff["sections"]["container_gump_records"]["rows"][0]["status"] == "added"
    assert diff["sections"]["kernel_core"]["rows"] == [
        {"field": "current_tick", "before": 123455, "after": 123456}
    ]
    process = diff["sections"]["kernel_process_slots"]["rows"][0]
    assert process["slot"] == 2 and process["reference_kind"] == "reusable_process_slot"
    assert process["changes"]["result"] == {"before": -200, "after": -201}


def test_ui_container_reorder_and_duplicates_use_multisets(tmp_path: Path):
    paths = [tmp_path / "before", tmp_path / "after"]
    first, second = container_bytes(300), container_bytes(301)
    for path, records in zip(paths, ([first, second, first], [second, first, first])):
        path.write_bytes(native_save([("GUMPS.DAT", gumps_bytes(records))]))
    diff = compare_u8_save_snapshots(
        *(U8SaveSnapshot.from_path(path) for path in paths)
    )
    assert (
        diff["changed_entry_count"] == 1
        and diff["sections"]["container_gump_records"]["total_count"] == 0
    )


@pytest.mark.parametrize(
    "command,options",
    [
        ("avatar-dump", ["--format", "--output"]),
        ("gumps-dump", ["--view", "--format", "--output"]),
        ("kernel-dump", ["--view", "--slot", "--record", "--format", "--output"]),
    ],
)
def test_native_runtime_help_contract(command: str, options: list[str]):
    result = CliRunner().invoke(u8_app, [command, "--help"])
    assert result.exit_code == 0
    for option in options:
        assert option in result.output


@pytest.mark.parametrize(
    "command,entry,raw",
    [
        ("avatar-dump", "AVATAR.DAT", avatar_bytes()),
        ("gumps-dump", "GUMPS.DAT", gumps_bytes()),
        ("kernel-dump", "KERNEL.DAT", native_flex(kernel_records())),
    ],
    ids=["avatar", "gumps", "kernel"],
)
def test_commands_loose_and_archive_equivalence_and_output_safety(
    tmp_path: Path, command: str, entry: str, raw: bytes
):
    loose, archive = tmp_path / entry, tmp_path / "snapshot.save"
    loose.write_bytes(raw)
    archive.write_bytes(native_save([(entry.lower(), raw)]))
    runner = CliRunner()
    loose_result = runner.invoke(u8_app, [command, str(loose), "--format", "json"])
    save_result = runner.invoke(u8_app, [command, str(archive), "--format", "json"])
    assert loose_result.exit_code == save_result.exit_code == 0
    assert json.loads(loose_result.output) == json.loads(save_result.output)
    output = tmp_path / "report.json"
    assert (
        runner.invoke(
            u8_app, [command, str(archive), "--format", "json", "-o", str(output)]
        ).exit_code
        == 0
    )
    saved_output = output.read_bytes()
    assert (
        runner.invoke(u8_app, [command, str(archive), "-o", str(output)]).exit_code == 1
    )
    assert output.read_bytes() == saved_output
    assert (
        runner.invoke(u8_app, [command, str(archive), "-o", str(archive)]).exit_code
        == 1
    )
    assert archive.read_bytes() == native_save([(entry.lower(), raw)])
    missing = tmp_path / "initial.save"
    missing.write_bytes(native_save([]))
    missing_result = runner.invoke(u8_app, [command, str(missing)])
    assert missing_result.exit_code == 1 and "has no" in missing_result.output


@pytest.mark.parametrize("output_format", ["text", "json", "csv"])
def test_all_native_report_formats_preserve_raw_values(output_format: str):
    avatar = format_u8_avatar_report(
        U8AvatarState.from_bytes(avatar_bytes()), output_format=output_format
    )
    gumps = format_u8_gumps_report(
        U8GumpState.from_bytes(gumps_bytes([container_bytes()])),
        output_format=output_format,
    )
    kernel = format_u8_kernel_report(
        U8KernelState.from_bytes(native_flex(kernel_records())),
        view="records",
        record=8,
        output_format=output_format,
    )
    assert avatar_bytes().hex() in avatar
    assert container_bytes().hex() in gumps
    assert b"unused slot preserved".hex() in kernel
