"""U8 ANIM.DAT packed fields, table validation, aliases and CLI data views."""

from __future__ import annotations

import csv
import io
import json
import struct

import pytest
from typer.testing import CliRunner

from titan.u8 import U8AnimData, U8AnimError
from titan.u8.anim import DIRECTION_NAMES
from titan.u8.anim_report import format_u8_anim_report
from titan.u8.cli import u8_app


def animation_bytes() -> bytes:
    """Two shapes alias a table; two actions alias a stream with two frames/dir."""
    data = bytearray(8192 + 256)
    struct.pack_into("<I", data, 1 * 4, 8192)
    struct.pack_into("<I", data, 73 * 4, 8192)
    # A high ID must keep its identity when intermediate slots are empty.
    struct.pack_into("<I", data, 8192 + 0 * 4, len(data))
    struct.pack_into("<I", data, 8192 + 63 * 4, len(data))
    # All low flags; repeat=5, unk4=43, unk10=21, destroyActor=1.
    header = 2 | (0xFF << 8) | (5 << 16) | (43 << 20) | (21 << 26) | (1 << 31)
    data += struct.pack("<I", header)
    for direction in range(8):
        # Independent wire encoding, including both halves of signed nine-bit motion.
        sprite = (1500 + direction) | 0x0800 | 0xA000
        motion = (200 & 0x1FF) | 0x0200 | (5 << 10) | 0x2000 | 0x4000 | 0x8000
        data += struct.pack("<HbBH", sprite, -17, 42, motion)
        data += struct.pack("<HbBH", 10 + direction, 127, 0, (-200 & 0x1FF))
    data += b"unreferenced authoring space"
    return bytes(data)


def test_packed_nodes_and_headers_follow_decoded_u8_source():
    data = U8AnimData.from_bytes(animation_bytes())
    action = data.get_action(1, 0)
    assert action is not None
    assert action.name == "walk"
    assert action.frame_count == 2
    assert action.repeat == 5
    assert action.unknown_4 == 43
    assert action.unknown_10 == 21
    assert action.flags & 0x8000
    assert action.flag_names() == [
        "two_step",
        "attack",
        "looping",
        "unstoppable",
        "looping2",
        "hit_on_collision",
        "repeat_after_completion",
        "hanging",
        "destroy_actor",
    ]
    assert len(action.directions) == 8
    for direction, nodes in enumerate(action.directions):
        first, second = nodes
        assert first.frame == 1500 + direction
        assert first.delta_z == -17
        assert first.sfx == 42
        assert first.delta_dir == 200  # Byte-only signed decoding would yield -56.
        assert first.movement_world_units == 800
        assert (
            first.special and first.on_ground and first.flipped and first.call_usecode
        )
        assert first.flags_hi == 10
        assert first.attack_range == 5
        assert first.unknown_flag80
        assert second.frame == 10 + direction
        assert second.delta_z == 127
        assert second.delta_dir == -200  # Byte-only signed decoding would yield +56.
        assert second.movement_world_units == -800
        assert not second.on_ground and not second.special and not second.call_usecode


def test_sparse_slots_aliases_and_original_bytes_are_preserved():
    raw = animation_bytes()
    data = U8AnimData.from_bytes(raw)
    assert list(data.actions) == [(1, 0), (1, 63), (73, 0), (73, 63)]
    assert data.get_action(1, 1) is None
    assert data.get_action(0, 0) is None
    first, alias = data.get_action(1, 0), data.get_action(73, 63)
    assert first is not None and alias is not None
    assert first.directions is alias.directions
    assert alias.name == "action_63"
    assert alias.shape_num == 73 and alias.action_num == 63
    assert data.to_bytes() == raw
    assert data.to_bytes().endswith(b"unreferenced authoring space")


def test_empty_shape_table_is_valid():
    data = U8AnimData.from_bytes(bytes(8192))
    assert not data.actions and not data.action_offsets
    assert len(data.shape_offsets) == 2048


@pytest.mark.parametrize("size", [0, 1, 8191])
def test_truncated_shape_table_fails(size):
    with pytest.raises(U8AnimError, match="shape offset table"):
        U8AnimData.from_bytes(bytes(size))


@pytest.mark.parametrize("offset", [1, 8191, 0xFFFFFFFF, 8440])
def test_bad_shape_table_offsets_fail(offset):
    raw = bytearray(animation_bytes())
    struct.pack_into("<I", raw, 4, offset)
    with pytest.raises(U8AnimError, match="shape 1 action table.*out of bounds"):
        U8AnimData.from_bytes(bytes(raw))


def test_distinct_overlapping_action_tables_fail():
    raw = bytearray(animation_bytes())
    struct.pack_into("<I", raw, 73 * 4, 8196)
    with pytest.raises(U8AnimError, match="overlapping shape action tables"):
        U8AnimData.from_bytes(bytes(raw))


@pytest.mark.parametrize("offset", [1, 8191, 0xFFFFFFFF])
def test_bad_action_header_offsets_fail(offset):
    raw = bytearray(animation_bytes())
    struct.pack_into("<I", raw, 8192, offset)
    with pytest.raises(U8AnimError, match="shape 1 action 0.*header.*out of bounds"):
        U8AnimData.from_bytes(bytes(raw))


def test_actions_cannot_point_into_offset_tables():
    raw = bytearray(animation_bytes())
    struct.pack_into("<I", raw, 8192, 8192)
    with pytest.raises(U8AnimError, match="overlaps an offset table"):
        U8AnimData.from_bytes(bytes(raw))


def test_truncated_direction_payload_fails():
    raw = animation_bytes()[: 8448 + 4 + 96 - 1]
    with pytest.raises(U8AnimError, match="truncated eight-direction"):
        U8AnimData.from_bytes(raw)


def test_populated_zero_length_action_fails():
    raw = bytearray(animation_bytes())
    raw[8448] = 0
    with pytest.raises(U8AnimError, match="zero frames"):
        U8AnimData.from_bytes(bytes(raw))


@pytest.mark.parametrize("shape,action", [(-1, 0), (2048, 0), (1, -1), (1, 64)])
def test_lookup_rejects_out_of_range_ids(shape, action):
    with pytest.raises(U8AnimError, match="shape must be"):
        U8AnimData.from_bytes(animation_bytes()).get_action(shape, action)


def test_json_direction_filter_keeps_ids_raw_bytes_and_unknown_fields():
    data = U8AnimData.from_bytes(animation_bytes())
    report = json.loads(
        format_u8_anim_report(
            data,
            shape=73,
            action=63,
            direction=7,
            output_format="json",
        )
    )
    assert report["shape_count"] == 2 and report["action_count"] == 4
    assert report["selected_action_count"] == 1
    row = report["actions"][0]
    assert row["shape"] == 73 and row["action"] == 63
    assert row["unknown_4"] == 43 and row["unknown_10"] == 21
    assert len(row["frames"]) == 2
    assert row["frames"][0]["direction_name"] == "NW"
    assert row["frames"][0]["direction"] == 7
    assert row["frames"][1]["delta_dir"] == -200
    assert (
        bytes.fromhex(row["frames"][0]["raw"])
        == data.actions[73, 63].directions[7][0].raw
    )


def test_csv_summary_and_frame_rows():
    data = U8AnimData.from_bytes(animation_bytes())
    summary = list(
        csv.DictReader(io.StringIO(format_u8_anim_report(data, output_format="csv")))
    )
    assert len(summary) == 4 and "frame" not in summary[0]
    frames = list(
        csv.DictReader(
            io.StringIO(
                format_u8_anim_report(
                    data,
                    shape=1,
                    action=0,
                    direction=2,
                    output_format="csv",
                )
            )
        )
    )
    assert len(frames) == 2
    assert frames[0]["frame"] == "1502" and frames[0]["direction_name"] == "E"
    assert frames[1]["movement_world_units"] == "-800"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shape": 2048},
        {"action": 64},
        {"direction": 8},
        {"output_format": "xml"},
    ],
)
def test_report_rejects_invalid_filters(kwargs):
    with pytest.raises(U8AnimError):
        format_u8_anim_report(U8AnimData.from_bytes(animation_bytes()), **kwargs)


def test_cli_help_contract():
    result = CliRunner().invoke(u8_app, ["anim-dump", "--help"])
    assert result.exit_code == 0, result.output
    for token in (
        "ANIM.DAT",
        "--shape",
        "--action",
        "--direction",
        "--frames",
        "--format",
        "--output",
    ):
        assert token in result.output


def test_cli_json_stdout_and_file_output_preserve_source(tmp_path):
    source = tmp_path / "ANIM.DAT"
    raw = animation_bytes()
    source.write_bytes(raw)
    runner = CliRunner()
    result = runner.invoke(
        u8_app,
        ["anim-dump", str(source), "--shape", "1", "--action", "0", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["selected_action_count"] == 1
    assert "frames" not in report["actions"][0]
    output = tmp_path / "reports" / "walk.csv"
    result = runner.invoke(
        u8_app,
        [
            "anim-dump",
            str(source),
            "--shape",
            "1",
            "--action",
            "0",
            "--direction",
            "0",
            "--format",
            "csv",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(list(csv.DictReader(io.StringIO(output.read_text())))) == 2
    assert source.read_bytes() == raw


def test_cli_existing_outputs_and_source_cannot_be_replaced(tmp_path):
    source = tmp_path / "ANIM.DAT"
    source.write_bytes(animation_bytes())
    original = source.read_bytes()
    runner = CliRunner()
    result = runner.invoke(u8_app, ["anim-dump", str(source), "-o", str(source)])
    assert result.exit_code == 1 and "output must differ" in result.output
    assert source.read_bytes() == original
    output = tmp_path / "existing.txt"
    output.write_text("keep")
    result = runner.invoke(u8_app, ["anim-dump", str(source), "-o", str(output)])
    assert result.exit_code == 1
    assert output.read_text() == "keep"


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--shape", "2048"),
        ("--action", "64"),
        ("--direction", "8"),
        ("--format", "xml"),
    ],
)
def test_cli_invalid_options_do_not_create_reports(tmp_path, flag, value):
    source = tmp_path / "ANIM.DAT"
    source.write_bytes(animation_bytes())
    output = tmp_path / "report.txt"
    result = CliRunner().invoke(
        u8_app, ["anim-dump", str(source), flag, value, "-o", str(output)]
    )
    assert result.exit_code != 0
    assert not output.exists()


def test_cli_malformed_input_reports_error_without_output(tmp_path):
    source = tmp_path / "ANIM.DAT"
    source.write_bytes(b"broken")
    output = tmp_path / "report.json"
    result = CliRunner().invoke(u8_app, ["anim-dump", str(source), "-o", str(output)])
    assert result.exit_code == 1 and "ANIM.DAT:" in result.output
    assert not output.exists()


def test_text_detail_shows_all_directions_and_empty_search():
    data = U8AnimData.from_bytes(animation_bytes())
    report = format_u8_anim_report(data, shape=1, action=0, frames=True)
    for direction in DIRECTION_NAMES:
        assert f"{direction:2} step=" in report
    assert "delta_dir=-200" in report
    assert "No populated actions" in format_u8_anim_report(data, shape=0)
