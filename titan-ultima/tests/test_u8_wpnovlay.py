"""Weapon overlay wire format, ANIM pairing, sparse slots and command reports."""

from __future__ import annotations

import csv
import io
import json
import struct

import pytest
from typer.testing import CliRunner

from titan.u8 import U8AnimData, U8WeaponOverlayData, U8WeaponOverlayError
from titan.u8.cli import u8_app
from titan.u8.wpnovlay import WEAPON_OVERLAY_TYPES
from titan.u8.wpnovlay_report import format_u8_wpnovlay_report


def avatar_animation_bytes() -> bytes:
    """Two independently encoded avatar streams with different sequence lengths."""
    data = bytearray(8192 + 256)
    struct.pack_into("<I", data, 4, 8192)
    for action, count in ((4, 2), (63, 1)):
        struct.pack_into("<I", data, 8192 + action * 4, len(data))
        data += bytes((count, 2 if action == 63 else 0, 1, 0))
        for direction in range(8):
            for step in range(count):
                data += struct.pack("<HbBH", 100 + direction * 2 + step, 0, 0, 0)
    return bytes(data)


def overlay_payload(type_count: int, frame_count: int) -> bytes:
    """Type-major then direction-major four-byte offsets/unsigned sprite frames."""
    data = bytearray()
    for overlay_type in range(type_count):
        for direction in range(8):
            for step in range(frame_count):
                data += struct.pack(
                    "<bbH",
                    -128 + overlay_type,
                    127 - direction,
                    65535
                    if overlay_type == 14
                    else 30000 + overlay_type * 100 + direction * 3 + step,
                )
    return bytes(data)


def overlay_flex_bytes(records: dict[int, bytes] | None = None) -> bytes:
    """Build a sparse Flex without using Titan's parser or writer as an oracle."""
    if records is None:
        records = {4: overlay_payload(15, 2), 63: overlay_payload(2, 1)}
    data = bytearray(128 + 64 * 8)
    data[:84] = b"\x1a" * 84
    data[:7] = b"overlay"
    struct.pack_into("<I", data, 0x54, 64)
    struct.pack_into("<I", data, 0x58, 1)
    for action, payload in sorted(records.items()):
        struct.pack_into("<II", data, 128 + action * 8, len(data), len(payload))
        data += payload
    data += b"unused trailing authoring space"
    struct.pack_into("<I", data, 0x5C, len(data))
    return bytes(data)


def parsed_overlays() -> U8WeaponOverlayData:
    return U8WeaponOverlayData.from_bytes(
        overlay_flex_bytes(), U8AnimData.from_bytes(avatar_animation_bytes())
    )


def test_all_types_directions_and_steps_decode_without_compaction():
    data = parsed_overlays()
    assert list(data.actions) == [4, 63]
    assert len(data.record_entries) == 64
    action = data.get_action(4)
    assert action is not None and action.frame_count == 2
    assert action.name == "stand_up"
    assert len(action.overlays) == 15
    # The parser reports non-attack streams too, rather than discarding source bytes.
    assert not action.avatar_animation.flags & 2
    for overlay_type, overlay in enumerate(action.overlays):
        for direction, nodes in enumerate(overlay.directions):
            assert len(nodes) == 2
            for step, node in enumerate(nodes):
                assert node.x_offset == -128 + overlay_type
                assert node.y_offset == 127 - direction
                assert node.frame == (
                    65535
                    if overlay_type == 14
                    else 30000 + overlay_type * 100 + direction * 3 + step
                )
                assert len(node.raw) == 4
                assert data.get_frame(4, overlay_type, direction, step) is node
    other = data.get_action(63)
    assert other is not None and other.frame_count == 1 and len(other.overlays) == 2
    assert data.get_action(3) is None
    assert data.get_frame(3, 0, 0, 0) is None
    assert data.get_frame(63, 2, 0, 0) is None
    assert data.get_frame(63, 0, 0, 1) is None


def test_sprite_mappings_come_from_executable_and_unknown_slots_are_retained():
    action = parsed_overlays().get_action(4)
    assert action is not None
    assert [overlay.shape_num for overlay in action.overlays[:7]] == [
        241,
        243,
        244,
        245,
        398,
        399,
        400,
    ]
    assert action.overlays[4].name == "earth_glow"
    assert action.overlays[14].name == "overlay_14"
    assert action.overlays[14].shape_num is None
    assert len(WEAPON_OVERLAY_TYPES) == 15
    assert WEAPON_OVERLAY_TYPES[0x1A2] == 3


def test_file_read_and_exact_original_bytes_preserve_empty_slots_and_dead_space(
    tmp_path,
):
    raw = overlay_flex_bytes()
    source = tmp_path / "WPNOVLAY.DAT"
    source.write_bytes(raw)
    data = U8WeaponOverlayData.from_file(
        source, U8AnimData.from_bytes(avatar_animation_bytes())
    )
    assert data.to_bytes() == raw
    assert data.to_bytes().endswith(b"unused trailing authoring space")
    assert data.record_entries[0] == (0, 0)
    assert [entry.action_num for entry in data.iter_actions()] == [4, 63]


def test_empty_archive_needs_no_populated_avatar_actions():
    data = U8WeaponOverlayData.from_bytes(
        overlay_flex_bytes({}), U8AnimData.from_bytes(bytes(8192))
    )
    assert not data.actions and len(data.record_entries) == 64


def test_shared_flex_payloads_keep_distinct_action_ids():
    raw = bytearray(overlay_flex_bytes({4: overlay_payload(2, 2)}))
    struct.pack_into(
        "<II", raw, 128 + 63 * 8, *struct.unpack_from("<II", raw, 128 + 4 * 8)
    )
    # Both actions need equal ANIM lengths when their Flex records alias.
    anim = bytearray(avatar_animation_bytes())
    struct.pack_into(
        "<I", anim, 8192 + 63 * 4, struct.unpack_from("<I", anim, 8192 + 4 * 4)[0]
    )
    data = U8WeaponOverlayData.from_bytes(
        bytes(raw), U8AnimData.from_bytes(bytes(anim))
    )
    assert list(data.actions) == [4, 63]
    assert data.actions[4].raw == data.actions[63].raw
    assert data.to_bytes() == raw


@pytest.mark.parametrize(
    "case,expected",
    [
        ("header", "header"),
        ("magic", "Invalid Flex header"),
        ("count", "64 action slots"),
        ("table", "record table"),
        ("bounds", "bounds"),
        ("table_overlap", "bounds"),
        ("zero_offset", "bounds"),
        ("partial", "multiple"),
    ],
)
def test_malformed_container_or_payload_is_rejected(case, expected):
    raw = bytearray(overlay_flex_bytes())
    if case == "header":
        raw = raw[:100]
    elif case == "magic":
        raw[:84] = bytes(84)
    elif case == "count":
        struct.pack_into("<I", raw, 0x54, 65)
    elif case == "table":
        raw = raw[:639]
    elif case == "bounds":
        struct.pack_into("<I", raw, 128 + 4 * 8, len(raw))
    elif case == "table_overlap":
        struct.pack_into("<I", raw, 128 + 4 * 8, 128)
    elif case == "zero_offset":
        struct.pack_into("<I", raw, 128 + 4 * 8, 0)
    elif case == "partial":
        raw = bytearray(overlay_flex_bytes({4: overlay_payload(15, 2)[:-1]}))
    with pytest.raises(U8WeaponOverlayError, match=expected):
        U8WeaponOverlayData.from_bytes(
            bytes(raw), U8AnimData.from_bytes(avatar_animation_bytes())
        )


def test_missing_avatar_animation_is_not_silently_skipped():
    with pytest.raises(U8WeaponOverlayError, match="action 4 has no avatar animation"):
        U8WeaponOverlayData.from_bytes(
            overlay_flex_bytes(), U8AnimData.from_bytes(bytes(8192))
        )


@pytest.mark.parametrize(
    "indices",
    [(-1, 0, 0, 0), (64, 0, 0, 0), (4, -1, 0, 0), (4, 0, 8, 0), (4, 0, 0, -1)],
)
def test_invalid_lookup_indices_raise(indices):
    with pytest.raises(U8WeaponOverlayError):
        parsed_overlays().get_frame(*indices)


def test_json_csv_and_text_join_avatar_steps_and_signed_offsets():
    data = parsed_overlays()
    report = json.loads(
        format_u8_wpnovlay_report(
            data, action=4, overlay_type=14, direction=7, output_format="json"
        )
    )
    assert report["record_count"] == 64 and report["action_count"] == 2
    assert report["selected_action_count"] == 1
    overlay = report["actions"][0]["overlays"][0]
    assert overlay["overlay_type"] == 14 and overlay["overlay_shape"] is None
    assert overlay["frames"][1] == {
        "direction": 7,
        "direction_name": "NW",
        "step": 1,
        "avatar_frame": 115,
        "frame": 65535,
        "x_offset": -114,
        "y_offset": 120,
        "raw": "8e78ffff",
    }
    rows = list(
        csv.DictReader(
            io.StringIO(
                format_u8_wpnovlay_report(data, frames=True, output_format="csv")
            )
        )
    )
    assert len(rows) == 15 * 8 * 2 + 2 * 8
    assert rows[0]["x_offset"] == "-128" and rows[0]["avatar_frame"] == "100"
    assert rows[-1]["action"] == "63"
    summary = list(
        csv.DictReader(
            io.StringIO(format_u8_wpnovlay_report(data, output_format="csv"))
        )
    )
    assert len(summary) == 17 and "raw" not in summary[0]
    text = format_u8_wpnovlay_report(data, action=63, direction=0)
    assert "screen pixels" in text and "avatar_frame= 100" in text
    assert "No populated overlays" in format_u8_wpnovlay_report(data, overlay_type=15)
    empty_csv = format_u8_wpnovlay_report(
        data, action=0, frames=True, output_format="csv"
    )
    assert "avatar_frame" in empty_csv and len(empty_csv.splitlines()) == 1


@pytest.mark.parametrize(
    "kwargs",
    [{"action": 64}, {"overlay_type": -1}, {"direction": 8}, {"output_format": "xml"}],
)
def test_report_filters_are_validated(kwargs):
    with pytest.raises(U8WeaponOverlayError):
        format_u8_wpnovlay_report(parsed_overlays(), **kwargs)


def test_cli_help_contract():
    result = CliRunner().invoke(u8_app, ["wpnovlay-dump", "--help"])
    assert result.exit_code == 0, result.output
    for token in (
        "WPNOVLAY.DAT",
        "--anim",
        "--action",
        "--overlay-type",
        "--direction",
        "--frames",
        "--format",
        "--output",
    ):
        assert token in result.output


def test_cli_default_anim_and_explicit_anim_exports(tmp_path):
    source = tmp_path / "WPNOVLAY.DAT"
    source.write_bytes(overlay_flex_bytes())
    anim = tmp_path / "ANIM.DAT"
    anim.write_bytes(avatar_animation_bytes())
    runner = CliRunner()
    result = runner.invoke(
        u8_app, ["wpnovlay-dump", str(source), "--action", "4", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["selected_action_count"] == 1
    custom_anim = tmp_path / "custom_anim.dat"
    anim.rename(custom_anim)
    output = tmp_path / "reports" / "overlays.csv"
    result = runner.invoke(
        u8_app,
        [
            "wpnovlay-dump",
            str(source),
            "--anim",
            str(custom_anim),
            "--action",
            "63",
            "--overlay-type",
            "1",
            "--direction",
            "0",
            "--format",
            "csv",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(output.read_text())))
    assert len(rows) == 1 and rows[0]["frame"] == "30100"
    assert source.read_bytes() == overlay_flex_bytes()
    assert custom_anim.read_bytes() == avatar_animation_bytes()


@pytest.mark.parametrize("target", ["overlay", "anim", "existing"])
def test_cli_preserves_both_sources_and_existing_outputs(tmp_path, target):
    source = tmp_path / "WPNOVLAY.DAT"
    source.write_bytes(overlay_flex_bytes())
    anim = tmp_path / "ANIM.DAT"
    anim.write_bytes(avatar_animation_bytes())
    existing = tmp_path / "existing.txt"
    existing.write_text("keep")
    output = {"overlay": source, "anim": anim, "existing": existing}[target]
    original = output.read_bytes()
    result = CliRunner().invoke(
        u8_app, ["wpnovlay-dump", str(source), "-o", str(output)]
    )
    assert result.exit_code == 1
    assert output.read_bytes() == original


@pytest.mark.parametrize(
    "case",
    [
        "missing_anim",
        "missing_overlay",
        "broken_overlay",
        "broken_anim",
        "invalid_format",
        "invalid_direction",
        "invalid_action",
        "invalid_type",
    ],
)
def test_cli_errors_do_not_create_report(tmp_path, case):
    source = tmp_path / "WPNOVLAY.DAT"
    source.write_bytes(overlay_flex_bytes())
    anim = tmp_path / "ANIM.DAT"
    anim.write_bytes(avatar_animation_bytes())
    options = []
    if case == "missing_anim":
        anim.unlink()
    elif case == "missing_overlay":
        source.unlink()
    elif case == "broken_overlay":
        source.write_bytes(b"broken")
    elif case == "broken_anim":
        anim.write_bytes(b"broken")
    else:
        options = {
            "invalid_format": ["--format", "xml"],
            "invalid_direction": ["--direction", "8"],
            "invalid_action": ["--action", "64"],
            "invalid_type": ["--overlay-type", "-1"],
        }[case]
    output = tmp_path / "reports" / "output.txt"
    result = CliRunner().invoke(
        u8_app, ["wpnovlay-dump", str(source), *options, "-o", str(output)]
    )
    assert result.exit_code != 0
    assert not output.exists() and not output.parent.exists()
