"""Independent packed DOS fixtures for clock, actor and VM resume state."""

from __future__ import annotations

import csv
import io
import json
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u8.cli import u8_app
from titan.u8.kernel import U8KernelState
from titan.u8.kernel_process import (
    NATIVE_PROCESS_BUILD,
    decode_u8_kernel_process,
    describe_u8_process_details,
)
from titan.u8.native_state_report import format_u8_kernel_report
from titan.u8.save_diff import compare_u8_save_snapshots
from titan.u8.save_state import U8SaveSnapshot, describe_u8_save_snapshot
from tests.test_u8_native_runtime_state import kernel_records, process_bytes
from tests.test_u8_save_state import native_flex, native_save


def process_object(vtable: int, process_type: int, tail: bytes) -> bytes:
    base = bytearray(process_bytes(0)[:42])
    struct.pack_into("<H", base, 0, vtable)
    struct.pack_into("<H", base, 6, process_type)
    base[22:42] = bytes(20)
    return bytes(base) + tail


def kernel_bytes(
    raw: bytes, payload: bytes = b"", *, build: str = NATIVE_PROCESS_BUILD
) -> bytes:
    records = kernel_records()
    records[0] = build.encode("ascii") + b"\x00"
    sizes = bytearray(records[3])
    struct.pack_into("<H", sizes, 0, len(raw))
    records[3] = bytes(sizes)
    records[10:12] = [raw, payload]
    return native_flex(records)


def details(raw: bytes, payload: bytes = b"", *, build: str = NATIVE_PROCESS_BUILD):
    data = U8KernelState.from_bytes(kernel_bytes(raw, payload, build=build))
    return decode_u8_kernel_process(
        data.processes[0], build_description=data.build_description
    )


def usecode_object(*, killed: int = 0x12341234, process_type: int = 0x205) -> bytes:
    # Routine's 200-byte buffer, SP/top/BP/IP/owner, padding and suspended byte.
    routine = bytes(range(200)) + struct.pack(
        "<IIHII2sB", 0x123404A6, 0x123404B0, 180, 0xBEEF1234, 0xFEEDABCD, b"\xaa\xbb", 7
    )
    tail = (
        struct.pack("<H", 67)
        + routine
        + struct.pack("<IHBBBI", 0x87654321, 190, 2, 3, 4, killed)
    )
    return process_object(0x89F7, process_type, tail)


def test_animation_clock_is_distinct_from_scheduler_and_loop_counter():
    raw = process_object(
        0x0305,
        0x230,
        struct.pack("<IHIIIiiiiBB", 2, 30, 33333, 77, 1234, -5, 54001, 2, -1, 8, 9),
    )
    state = details(raw)
    assert state.status == "decoded" and state.native_class == "Animation"
    assert state.fields == {
        "interrupt_flags": 2,
        "hertz": 30,
        "period": 33333,
        "elapsed": 77,
        "animation_frames": 1234,
        "last_unlocked_frame": -5,
        "ticks": 54001,
        "game_hours": 2,
        "pending_ticks": -1,
        "frame_locked_raw": 8,
        "animation_stopped_raw": 9,
    }
    report = json.loads(
        format_u8_kernel_report(
            U8KernelState.from_bytes(kernel_bytes(raw)), output_format="json"
        )
    )
    assert report["core"]["current_tick"] == 123455
    assert report["game_clocks"][0]["ticks_per_game_hour"] == 27000
    assert report["game_clocks"][0]["ticks_per_second"] == 30
    loops = details(
        process_object(0x0331, 0x245, struct.pack("<IhB", 0xFFFFFFFF, -1, 255))
    )
    assert loops.fields == {"loops": 0xFFFFFFFF, "pause": -1, "hour_changed_raw": 255}


@pytest.mark.parametrize(
    "vtable,ptype,tail,expected",
    [
        (0x0400, 0x233, struct.pack("<H", 65535), {"remaining_loops": 65535}),
        (
            0x03CC,
            0x226,
            struct.pack("<IHIIHH", 2, 30, 33333, 1, 4, 5),
            {"remaining_ticks": 4, "initial_ticks": 5},
        ),
        (
            0x03A0,
            0x201,
            struct.pack("<IHIIBHH", 2, 10, 100000, 1, 255, 6, 7),
            {"running_raw": 255, "seconds": 6, "tenths": 7},
        ),
        (
            0x0374,
            0x226,
            struct.pack("<IHIIBI", 2, 30, 33333, 1, 8, 0xFFFFFFFF),
            {"timing_raw": 8, "ticks": 0xFFFFFFFF},
        ),
    ],
    ids=["round-timer", "wait", "timer", "accurate-timer"],
)
def test_timers_share_source_verified_realtime_fields(vtable, ptype, tail, expected):
    state = details(process_object(vtable, ptype, tail))
    assert state.status == "decoded"
    assert all(state.fields[key] == value for key, value in expected.items())


def test_actor_animation_packed_unaligned_fields_and_flagged_lists():
    tail = struct.pack(
        "<IHb8BIHHIBhbBBB",
        0xFFFFFFFF,
        55,
        -1,
        20,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        0xFFFF001F,
        0xF123,
        65535,
        0xDEADBEEF,
        8,
        -32768,
        -128,
        9,
        10,
        11,
    )
    raw = bytearray(process_object(0x1ECF, 0xF0, tail))
    struct.pack_into("<3HI", raw, 22, 1, 3, 240, 0x11112222)
    struct.pack_into("<3HI", raw, 32, 2, 2, 0, 0x33334444)
    state = details(
        bytes(raw), struct.pack("<5H", 0x404, 0xFFFF, 0x408, 0x2802, 0x5003)
    )
    assert state.native_class == "Work" and state.status == "decoded"
    assert (
        state.fields["animation"] == 55
        and state.fields["animation_result"] == 0xFFFF001F
    )
    assert (
        state.fields["direction"] == -1
        and state.fields["saved_last_animation"] == -32768
    )
    assert state.fields["destination_pointer_raw"] == 0xDEADBEEF
    assert (
        state.fields["target_ref"] == 65535 and state.fields["saved_direction"] == -128
    )
    assert state.fields["saved_animation_frame"] == 11
    view = describe_u8_process_details(state)
    assert view["depend_entries"][0]["operator"] == "or"
    assert view["depend_entries"][1]["pid"] is None
    assert view["depend_entries"][1]["unknown_bits"] == 0x8000
    assert (
        view["notify_entries"][0]["pid"] == 2
        and view["notify_entries"][0]["passive_dependency"]
    )
    assert (
        view["notify_entries"][1]["pid"] == 3
        and view["notify_entries"][1]["active_interrupt"]
    )


def test_standing_leap_preserves_additional_signed_jump_fields_and_world_points():
    tail = bytes(34) + struct.pack(
        "<hhhHHBHHB", -32768, -123, 32767, 65535, 32768, 255, 10, 20, 30
    )
    state = details(process_object(0x9450, 0xF0, tail))
    assert state.status == "decoded" and state.native_class == "StandingLeap"
    assert state.fields["jump_total_distance"] == -32768
    assert state.fields["jump_z_difference"] == -123
    assert state.fields["jump_frames"] == 32767
    assert (
        state.fields["jump_target_x"],
        state.fields["jump_target_y"],
        state.fields["jump_target_z"],
    ) == (65535, 32768, 255)
    assert (
        state.fields["jump_start_x"],
        state.fields["jump_start_y"],
        state.fields["jump_start_z"],
    ) == (10, 20, 30)
    assert details(process_object(0x9450, 0xF0, bytes(34))).status == "invalid"


@pytest.mark.parametrize("ptype", [1, 0x205, 0x208, 0x20A, 0x9999])
@pytest.mark.parametrize("killed", [0, 0x12341234])
def test_usecode_identity_mutable_type_stack_and_optional_killed_byte(
    ptype: int, killed: int
):
    suffix = (
        struct.pack("<HB", 190, 2)
        + (b"\xff" if killed else b"")
        + struct.pack("<H", 0xABCD)
    )
    state = details(usecode_object(killed=killed, process_type=ptype), suffix)
    assert (
        state.status == "decoded" and state.kind == "usecode" and not state.diagnostics
    )
    assert (
        state.fields["unit"] == 67
        and state.fields["stack_hex"] == bytes(range(200)).hex()
    )
    assert state.fields["stack_pointer_offset"] == 190
    assert state.fields["active_stack_hex"] == bytes(range(190, 200)).hex()
    assert state.fields["routine_padding_hex"] == "aabb"
    assert state.fields["suspended_raw"] == 7 and state.fields["finished_raw"] == 3
    assert (
        state.fields["running_raw"] == 4
        and state.fields["instruction_offset_saved"] == 0xABCD
    )
    assert state.fields["instruction_pointer_raw"] == 0xBEEF1234
    assert state.fields["killed_saved_raw"] == (255 if killed else None)
    assert (
        state.depend_words == state.notify_words == () and state.payload_unparsed == b""
    )


def test_lists_only_serialize_when_allocated_and_usecode_suffix_is_after_both():
    raw = bytearray(usecode_object())
    struct.pack_into(
        "<3HI", raw, 22, 1, 9, 0, 0
    )  # count residue without data pointer: no bytes.
    struct.pack_into("<3HI", raw, 32, 2, 2, 0, 1)
    state = details(bytes(raw), struct.pack("<2HHBBH", 0x2001, 0x4002, 190, 2, 0, 321))
    assert state.depend_words == () and state.notify_words == (0x2001, 0x4002)
    assert state.fields["instruction_offset_saved"] == 321 and state.status == "decoded"


@pytest.mark.parametrize(
    "case", ["build", "vtable", "size", "type", "short-payload", "extra-payload"]
)
def test_unmatched_and_malformed_subtypes_do_not_invalidate_kernel(case: str):
    raw = bytearray(process_object(0x0331, 0x245, struct.pack("<IhB", 12, -1, 0)))
    payload = b""
    build = NATIVE_PROCESS_BUILD
    if case == "build":
        build = NATIVE_PROCESS_BUILD + " alternate"
    elif case == "vtable":
        struct.pack_into("<H", raw, 0, 0xCCCC)
    elif case == "size":
        raw = raw[:-1]
    elif case == "type":
        struct.pack_into("<H", raw, 6, 0x230)
    elif case == "short-payload":
        struct.pack_into("<3HI", raw, 22, 1, 1, 0, 1)
    else:
        payload = b"extra"
    data = U8KernelState.from_bytes(kernel_bytes(bytes(raw), payload, build=build))
    state = decode_u8_kernel_process(
        data.processes[0], build_description=data.build_description
    )
    assert state.status == ("unsupported" if case in {"build", "vtable"} else "invalid")
    assert data.to_bytes() == kernel_bytes(bytes(raw), payload, build=build)
    assert state.payload_unparsed == payload


def test_resume_state_and_stack_bounds_report_diagnostics_without_pointer_resolution():
    raw = bytearray(usecode_object())
    struct.pack_into("<I", raw, 244, 0x55550000)  # unrelated stack segment
    struct.pack_into("<H", raw, 252, 65535)
    state = details(bytes(raw), struct.pack("<HBBH", 197, 255, 0, 123))
    assert (
        state.fields["stack_pointer_offset"] is None
        and state.fields["active_stack_hex"] is None
    )
    assert state.fields["this_size_saved"] == 255 and len(state.diagnostics) == 4


@pytest.mark.parametrize("output_format", ["text", "json", "csv"])
def test_decoded_view_reports_and_slot_selection(output_format: str):
    data = U8KernelState.from_bytes(
        kernel_bytes(usecode_object(), struct.pack("<HBBH", 190, 2, 0, 123))
    )
    report = format_u8_kernel_report(
        data, view="decoded", slot=0, output_format=output_format
    )
    assert "UnkProcess" in report and "instruction_offset_saved" in report
    if output_format == "json":
        assert json.loads(report)["rows"][0]["fields"]["unit"] == 67
    elif output_format == "csv":
        rows = list(csv.DictReader(io.StringIO(report)))
        assert len(rows) == 1 and json.loads(rows[0]["fields"])["unit"] == 67


def test_save_overview_diff_and_cli_include_verified_resume_state(tmp_path: Path):
    paths = [tmp_path / name for name in ("before.save", "after.save")]
    for path, offset in zip(paths, (123, 456)):
        path.write_bytes(
            native_save(
                [
                    (
                        "KERNEL.DAT",
                        kernel_bytes(
                            usecode_object(), struct.pack("<HBBH", 190, 2, 0, offset)
                        ),
                    )
                ]
            )
        )
    before, after = (U8SaveSnapshot.from_path(path) for path in paths)
    overview = describe_u8_save_snapshot(after)
    assert overview["kernel"]["decoded_class_counts"] == {"UnkProcess": 1}
    assert overview["kernel"]["process_decode_counts"] == {
        "decoded": 1,
        "unsupported": 1,
    }
    diff = compare_u8_save_snapshots(before, after)
    rows = diff["sections"]["kernel_process_state"]["rows"]
    assert rows == [
        {
            "slot": 0,
            "reference_kind": "reusable_process_slot",
            "changes": {
                "fields.instruction_offset_saved": {"before": 123, "after": 456}
            },
        }
    ]
    assert diff["sections"]["kernel_process_slots"]["rows"][0]["changes"]["payload_hex"]
    assert (
        compare_u8_save_snapshots(after, after)["sections"]["kernel_process_state"][
            "total_count"
        ]
        == 0
    )
    runner = CliRunner()
    report = runner.invoke(
        u8_app,
        [
            "kernel-dump",
            str(paths[1]),
            "--view",
            "decoded",
            "--slot",
            "0",
            "--format",
            "json",
        ],
    )
    assert (
        report.exit_code == 0
        and json.loads(report.output)["rows"][0]["fields"]["instruction_offset_saved"]
        == 456
    )
    assert "decoded" in runner.invoke(u8_app, ["kernel-dump", "--help"]).output
