"""Native global flags, strict archives, save coverage and scoped differences."""

from __future__ import annotations

import csv
import io
import json
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u8.cli import u8_app
from titan.u8.flags import U8FlagSymbols, U8GlobalFlags
from titan.u8.flags_report import format_u8_flags_report
from titan.u8.save import U8SaveArchive
from titan.u8.save_diff import compare_u8_save_snapshots, format_u8_save_diff
from titan.u8.save_state import U8SaveSnapshot, describe_u8_save_snapshot


def native_save(entries: list[tuple[str, bytes]]) -> bytes:
    """Encode native header and entries independently of the archive parser."""
    raw = bytearray(b"Ultima 8 SaveGame File.\x00" + struct.pack("<H", len(entries)))
    for name, data in entries:
        encoded = name.encode("ascii") + b"\x00"
        raw += (
            struct.pack("<I", len(encoded))
            + encoded
            + struct.pack("<I", len(data))
            + data
        )
    return bytes(raw)


def native_flex(records: list[bytes]) -> bytes:
    """Encode native Flex offsets using literal writer layout and no production constants."""
    raw = bytearray(128 + 8 * len(records))
    raw[:84] = b"\x1a" * 84
    struct.pack_into("<I", raw, 84, len(records))
    for index, data in enumerate(records):
        struct.pack_into("<II", raw, 128 + 8 * index, len(raw), len(data))
        raw += data
    return bytes(raw)


def native_cache(*, shape: int = 241, frame: int = 9, free_head: int = 300) -> bytes:
    arrays = bytearray(147456)
    struct.pack_into("<H", arrays, 2, 64)
    struct.pack_into("<H", arrays, 18434, 128)
    struct.pack_into("<H", arrays, 46082, 1)
    arrays[64513] = frame
    arrays[119809] = 3
    struct.pack_into("<H", arrays, 46080 + 300 * 2, shape)
    metadata = bytearray(16410)
    struct.pack_into("<h", metadata, 0, 3)
    struct.pack_into(
        "<h6Hh",
        metadata,
        16394,
        1 if free_head else 0,
        0,
        free_head,
        0,
        free_head,
        0,
        0,
        0,
    )
    return native_flex([bytes(arrays), bytes(metadata)])


def native_npcs(
    *, hitpoints: int = 30, high_frame: int = 1, tail: bytes = b"tail"
) -> bytes:
    raw = bytearray(256 * 49)
    raw[49:53] = bytes((10, 11, 12, hitpoints))
    raw[56] = high_frame
    struct.pack_into("<h", raw, 49 + 45, 20)
    return native_flex([bytes(raw) + tail])


def map_item(
    shape: int, *, x: int = 64, y: int = 128, status: int = 0, quality: int = 0
) -> bytes:
    return struct.pack("<HHBHBHHBBH", x, y, 0, shape, 0, status, quality, 0, 3, 0)


def native_nonfixed(items: list[bytes], *, map_id: int = 3) -> bytes:
    records = [b""] * 256
    records[map_id] = b"".join(items)
    return native_flex(records)


def snapshot(
    tmp_path: Path, name: str, entries: list[tuple[str, bytes]]
) -> U8SaveSnapshot:
    path = tmp_path / name
    path.write_bytes(native_save(entries))
    return U8SaveSnapshot.from_path(path)


def test_flags_lsb_first_cross_byte_width_and_exact_roundtrip():
    raw = bytearray(1024)
    raw[:3] = bytes((0x80, 0xAB, 0x01))
    raw[-1] = 0x80
    flags = U8GlobalFlags.from_bytes(bytes(raw))
    assert flags.get_value(7, 16) == 0x357
    assert flags.get_value(8, 8) == 0xAB
    assert flags.get_value(8191) == 1
    assert flags.set_bit_indices() == (7, 8, 9, 11, 13, 15, 16, 8191)
    assert flags.to_bytes() == bytes(raw)


@pytest.mark.parametrize("size", [0, 1023, 1025])
def test_flags_require_exact_native_size(size: int):
    with pytest.raises(ValueError, match="expected 1024"):
        U8GlobalFlags.from_bytes(bytes(size))


@pytest.mark.parametrize(
    "index,width", [(-1, 1), (8192, 1), (8191, 2), (0, 0), (0, 17)]
)
def test_flags_reject_out_of_bounds_fields(index: int, width: int):
    with pytest.raises(ValueError):
        U8GlobalFlags.zero_default().get_value(index, width)


def test_native_flag_symbols_and_named_unsigned_values():
    raw_symbols = (
        b"quest\x00"
        + struct.pack("<HH", 7, 16)
        + b"toggle\x00"
        + struct.pack("<HH", 8191, 1)
    )
    symbols = U8FlagSymbols.from_bytes(raw_symbols)
    flags = U8GlobalFlags.from_bytes(b"\xff" * 1024)
    report = json.loads(
        format_u8_flags_report(flags, symbols=symbols, output_format="json")
    )
    assert report["flags"] == [
        {"name": "quest", "index": 7, "width": 16, "value": 65535},
        {"name": "toggle", "index": 8191, "width": 1, "value": 1},
    ]
    assert symbols.to_bytes() == raw_symbols
    selected = json.loads(
        format_u8_flags_report(
            flags, symbols=symbols, name="toggle", output_format="json"
        )
    )
    assert len(selected["flags"]) == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"name",
        b"\x00\x00\x00\x01\x00",
        b"name\x00\x00",
        b"\xff\x00\x00\x00\x01\x00",
        b"a\x00\x00\x20\x01\x00",
        b"a\x00\x00\x00\x00\x00",
        b"a\x00\x00\x00\x01\x00" * 2,
    ],
)
def test_symbols_reject_truncation_names_offsets_and_widths(raw: bytes):
    with pytest.raises(ValueError):
        U8FlagSymbols.from_bytes(raw)


def test_flags_default_and_all_bits_csv_include_zeros():
    flags = U8GlobalFlags.zero_default()
    report = json.loads(format_u8_flags_report(flags, output_format="json"))
    assert (
        report["defaulted"] and report["set_bit_count"] == 0 and report["flags"] == []
    )
    rows = list(
        csv.DictReader(
            io.StringIO(
                format_u8_flags_report(flags, all_bits=True, output_format="csv")
            )
        )
    )
    assert len(rows) == 8192
    assert rows[-1] == {"name": "", "index": "8191", "width": "1", "value": "0"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 3},
        {"name": "quest"},
        {"index": 1, "all_bits": True},
        {"symbols": U8FlagSymbols.from_bytes(b""), "index": 0},
        {"symbols": U8FlagSymbols.from_bytes(b""), "all_bits": True},
        {"symbols": U8FlagSymbols.from_bytes(b""), "name": "unknown"},
        {"output_format": "xml"},
    ],
)
def test_flag_report_rejects_conflicting_or_unknown_selections(kwargs):
    with pytest.raises(ValueError):
        format_u8_flags_report(U8GlobalFlags.zero_default(), **kwargs)


@pytest.mark.parametrize(
    "filename", ["../FLAG.DAT", "..\\FLAG.DAT", "C:FLAG.DAT", ".", "..", "A\n.DAT"]
)
def test_archive_reader_rejects_non_filename_entries(filename: str):
    with pytest.raises(ValueError, match="plain filename"):
        U8SaveArchive.from_bytes(native_save([(filename, b"a")]))


@pytest.mark.parametrize(
    "case", ["header", "count", "length", "null", "payload", "duplicate", "ascii"]
)
def test_strict_archive_checks_are_shared_by_existing_commands(
    tmp_path: Path, case: str
):
    raw = bytearray(native_save([("FLAG.DAT", bytes(1024))]))
    if case == "header":
        raw[23] = 1
    elif case == "count":
        struct.pack_into("<H", raw, 24, 2)
    elif case == "length":
        struct.pack_into("<I", raw, 26, 100000)
    elif case == "null":
        raw[38] = 1
    elif case == "payload":
        raw = raw[:-1]
    elif case == "duplicate":
        raw = bytearray(native_save([("FLAG.DAT", b"a"), ("flag.dat", b"b")]))
    elif case == "ascii":
        raw[30] = 255
    path = tmp_path / "bad.save"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        U8SaveArchive.from_bytes(bytes(raw))
    for command in ("save-list", "save-extract", "save-info", "flags-dump"):
        result = CliRunner().invoke(u8_app, [command, str(path)])
        assert result.exit_code == 1 and "ERROR:" in result.output
    assert not (tmp_path / "bad").exists()


def test_case_insensitive_archive_lookup_and_container_trailer():
    raw = (
        native_save([("flag.dat", b"a"), ("OTHER.DAT", b"")])
        + b"unused container bytes"
    )
    archive = U8SaveArchive.from_bytes(raw)
    assert archive.get_data("FLAG.DAT") == b"a"
    assert archive.get_data("other.dat") == b""
    assert archive.get_data("missing") is None


def test_initial_save_overview_joins_npcs_without_in_use_flag(tmp_path: Path):
    data = snapshot(
        tmp_path,
        "start.save",
        [
            ("ITEMCACH.DAT", native_cache()),
            ("NPCDATA.DAT", native_npcs()),
            (
                "NONFIXED.DAT",
                native_nonfixed([map_item(100), map_item(101, x=1, status=8)]),
            ),
            ("AVATAR.DAT", bytes(77)),
        ],
    )
    report = describe_u8_save_snapshot(data)
    assert report["entry_count"] == 4
    assert report["global_flags"] == {
        "defaulted": True,
        "bit_count": 8192,
        "set_bit_count": 0,
    }
    assert report["missing_entries"] == ["FLAG.DAT", "GUMPS.DAT", "KERNEL.DAT"]
    assert report["npcs"]["present_count"] == 1
    assert report["npcs"]["stored_in_use_count"] == 0
    assert report["npcs"]["avatar_npc_slot"]["frame"] == 265
    assert report["item_cache"]["slot_membership_counts"]["free_item"] == 1
    assert report["nonfixed"]["maps"][0]["world_count"] == 1
    assert report["nonfixed"]["maps"][0]["contained_count"] == 1
    assert (
        next(row for row in report["entries"] if row["name"] == "AVATAR.DAT")[
            "decode_status"
        ]
        == "decoded"
    )


def test_invalid_known_entries_stay_visible_and_skip_semantic_diff(tmp_path: Path):
    before = snapshot(
        tmp_path, "before", [("FLAG.DAT", b"bad"), ("NPCDATA.DAT", b"bad")]
    )
    after = snapshot(
        tmp_path, "after", [("FLAG.DAT", bytes(1024)), ("NPCDATA.DAT", native_npcs())]
    )
    info = describe_u8_save_snapshot(before)
    assert all(row["decode_status"] == "invalid" for row in info["entries"])
    diff = compare_u8_save_snapshots(before, after)
    assert diff["changed_entry_count"] == 2
    assert (
        "global_flag_bits" not in diff["sections"]
        and "npc_slots" not in diff["sections"]
    )
    assert diff["decode_errors"]["before"]["FLAG.DAT"]
    assert any(
        row["entry"] == "FLAG.DAT" for row in diff["skipped_semantic_comparisons"]
    )


def test_gamedat_snapshots_ignore_temp_files_and_match_archive(tmp_path: Path):
    directory = tmp_path / "gamedat"
    directory.mkdir()
    (directory / "itemcach.dat").write_bytes(native_cache())
    (directory / "NPCDATA.DAT").write_bytes(native_npcs())
    (directory / "NONFIXED.$$$").write_bytes(b"temporary file")
    archive = snapshot(
        tmp_path,
        "same.save",
        [("ITEMCACH.DAT", native_cache()), ("NPCDATA.DAT", native_npcs())],
    )
    loose = U8SaveSnapshot.from_path(directory)
    assert loose.source_kind == "gamedat_directory" and len(loose.entries) == 2
    assert U8GlobalFlags.from_file(directory).defaulted
    assert compare_u8_save_snapshots(archive, loose)["changed_entry_count"] == 0


def test_loose_and_archive_flags_match_and_missing_archive_defaults(tmp_path: Path):
    raw = bytes((0x80,)) + bytes(1023)
    loose = tmp_path / "FLAG.DAT"
    loose.write_bytes(raw)
    packed = snapshot(tmp_path, "packed", [("flag.dat", raw)])
    empty = snapshot(tmp_path, "initial", [("AVATAR.DAT", bytes(77))])
    assert U8GlobalFlags.from_file(loose).to_bytes() == raw
    assert U8GlobalFlags.from_file(packed.source).to_bytes() == raw
    assert U8GlobalFlags.from_file(empty.source).defaulted


def test_diff_global_fields_and_missing_zero_default_keep_presence_changes(
    tmp_path: Path,
):
    raw = bytes((0x80, 0x01)) + bytes(1022)
    before = snapshot(tmp_path, "before", [("AVATAR.DAT", b"x")])
    after = snapshot(tmp_path, "after", [("AVATAR.DAT", b"x"), ("FLAG.DAT", raw)])
    symbols = U8FlagSymbols.from_bytes(b"quest\x00" + struct.pack("<HH", 7, 3))
    diff = compare_u8_save_snapshots(before, after, symbols=symbols)
    assert diff["changed_entry_count"] == 1
    assert diff["flags_defaulted"] == {"before": True, "after": False}
    assert diff["sections"]["global_flag_bits"]["rows"] == [
        {"index": 7, "before": 0, "after": 1},
        {"index": 8, "before": 0, "after": 1},
    ]
    assert diff["sections"]["global_flag_variables"]["rows"] == [
        {"name": "quest", "index": 7, "width": 3, "before": 0, "after": 3}
    ]
    zero = snapshot(tmp_path, "zero", [("AVATAR.DAT", b"x"), ("FLAG.DAT", bytes(1024))])
    zero_diff = compare_u8_save_snapshots(before, zero)
    assert (
        zero_diff["changed_entry_count"] == 1
        and zero_diff["sections"]["global_flag_bits"]["total_count"] == 0
    )


def test_diff_cache_reuse_npc_frame_and_preserved_tails(tmp_path: Path):
    before = snapshot(
        tmp_path,
        "before",
        [("ITEMCACH.DAT", native_cache()), ("NPCDATA.DAT", native_npcs())],
    )
    after = snapshot(
        tmp_path,
        "after",
        [
            ("ITEMCACH.DAT", native_cache(shape=242, frame=10, free_head=0)),
            ("NPCDATA.DAT", native_npcs(hitpoints=20, high_frame=2, tail=b"new tail")),
        ],
    )
    report = compare_u8_save_snapshots(before, after)
    slot = next(
        row
        for row in report["sections"]["item_cache_slots"]["rows"]
        if row["item_id"] == 300
    )
    assert slot["reference_kind"] == "reusable_item_slot"
    assert slot["changes"]["shape"] == {"before": 241, "after": 242}
    assert slot["changes"]["slot_membership"] == {
        "before": "free_item",
        "after": "allocated",
    }
    npc = report["sections"]["npc_slots"]["rows"][0]
    assert npc["npc_id"] == 1
    assert npc["changes"]["hitpoints"] == {"before": 30, "after": 20}
    assert npc["changes"]["full_frame"] == {"before": 265, "after": 522}
    assert report["sections"]["npc_record_tail"]["total_count"] == 1


def test_nonfixed_reordered_siblings_and_roots_do_not_invent_changes(tmp_path: Path):
    root_a, root_b = map_item(100), map_item(200)
    child_a, child_b = map_item(101, x=1, status=8), map_item(102, x=1, status=8)
    before = snapshot(
        tmp_path,
        "before",
        [("NONFIXED.DAT", native_nonfixed([root_a, child_a, child_b, root_b]))],
    )
    after = snapshot(
        tmp_path,
        "after",
        [("NONFIXED.DAT", native_nonfixed([root_b, root_a, child_b, child_a]))],
    )
    diff = compare_u8_save_snapshots(before, after)
    assert (
        diff["changed_entry_count"] == 1
    )  # Stored bytes changed, logical multiset did not.
    assert diff["sections"]["nonfixed_records"]["total_count"] == 0


def test_nonfixed_parent_changes_and_duplicate_multiplicity_are_reported(
    tmp_path: Path,
):
    root_a, root_b = map_item(100), map_item(200)
    child = map_item(101, x=1, status=8)
    before = snapshot(
        tmp_path,
        "before",
        [("NONFIXED.DAT", native_nonfixed([root_a, child, child, root_b]))],
    )
    after = snapshot(
        tmp_path, "after", [("NONFIXED.DAT", native_nonfixed([root_a, root_b, child]))]
    )
    diff = compare_u8_save_snapshots(before, after)
    row = diff["sections"]["nonfixed_maps"]["rows"][0]
    assert row["removed_record_count"] == 2 and row["added_record_count"] == 1
    records = diff["sections"]["nonfixed_records"]["rows"]
    assert records[0]["count"] == 2 and records[0]["ancestor_raw_hex"] == [root_a.hex()]
    assert records[1]["ancestor_raw_hex"] == [root_b.hex()]


def test_diff_opaque_bytes_empty_entry_presence_and_row_limits(tmp_path: Path):
    before = snapshot(
        tmp_path, "before", [("KERNEL.DAT", b"abcde"), ("EMPTY.DAT", b"")]
    )
    after = snapshot(
        tmp_path, "after", [("KERNEL.DAT", b"AbCdEf"), ("FLAG.DAT", b"\xff" * 1024)]
    )
    report = compare_u8_save_snapshots(before, after, limit=1)
    assert report["changed_entry_count"] == 3
    assert report["sections"]["global_flag_bits"]["total_count"] == 8192
    assert report["sections"]["global_flag_bits"]["omitted_count"] == 8191
    all_rows = compare_u8_save_snapshots(before, after, limit=0)
    entries = all_rows["sections"]["entries"]["rows"]
    kernel = next(row for row in entries if row["name"] == "KERNEL.DAT")
    assert kernel["byte_difference"]["changed_byte_count"] == 4
    assert kernel["byte_difference"]["ranges"] == [
        {"start": 0, "end_exclusive": 1},
        {"start": 2, "end_exclusive": 3},
        {"start": 4, "end_exclusive": 6},
    ]
    assert (
        next(row for row in entries if row["name"] == "EMPTY.DAT")["status"]
        == "removed"
    )


@pytest.mark.parametrize(
    "command,options",
    [
        (
            "flags-dump",
            ["--index", "--width", "--symbols", "--all-bits", "--format", "--output"],
        ),
        ("save-info", ["--format", "--output"]),
        ("save-diff", ["--symbols", "--limit", "--format", "--output"]),
    ],
)
def test_save_state_help_contract(command: str, options: list[str]):
    result = CliRunner().invoke(u8_app, [command, "--help"])
    assert result.exit_code == 0
    for option in options:
        assert option in result.output


@pytest.mark.parametrize("command", ["flags-dump", "save-info", "save-diff"])
def test_save_state_cli_json_and_output_preservation(tmp_path: Path, command: str):
    before = snapshot(tmp_path, "before.save", [("AVATAR.DAT", bytes(77))])
    after = snapshot(
        tmp_path,
        "after.save",
        [("AVATAR.DAT", bytes(77)), ("FLAG.DAT", b"\x01" + bytes(1023))],
    )
    args = (
        [command, str(after.source)]
        if command != "save-diff"
        else [command, str(before.source), str(after.source)]
    )
    output = tmp_path / "report.json"
    result = CliRunner().invoke(u8_app, args + ["--format", "json", "-o", str(output)])
    assert result.exit_code == 0
    assert json.loads(output.read_text())
    old_output = output.read_bytes()
    assert CliRunner().invoke(u8_app, args + ["-o", str(output)]).exit_code == 1
    assert output.read_bytes() == old_output
    source_raw = after.source.read_bytes()
    result = CliRunner().invoke(u8_app, args + ["-o", str(after.source)])
    assert result.exit_code == 1 and "output must differ" in result.output
    assert after.source.read_bytes() == source_raw


def test_report_output_cannot_overwrite_gamedat_source(tmp_path: Path):
    directory = tmp_path / "gamedat"
    directory.mkdir()
    source = directory / "FLAG.DAT"
    source.write_bytes(bytes(1024))
    for command in ("flags-dump", "save-info", "save-diff"):
        args = [command, str(directory)] + (
            [str(directory)] if command == "save-diff" else []
        )
        result = CliRunner().invoke(u8_app, args + ["-o", str(source)])
        assert result.exit_code == 1 and "output must differ" in result.output
    assert source.read_bytes() == bytes(1024)


def test_diff_text_skipped_comparisons_and_validation(tmp_path: Path):
    before = snapshot(tmp_path, "before", [("AVATAR.DAT", b"a")])
    after = snapshot(tmp_path, "after", [("AVATAR.DAT", b"b")])
    text = format_u8_save_diff(before, after)
    assert "Changed entries: 1" in text and "Skipped semantic comparisons" in text
    with pytest.raises(ValueError, match="nonnegative"):
        compare_u8_save_snapshots(before, after, limit=-1)
    with pytest.raises(ValueError, match="format"):
        format_u8_save_diff(before, after, output_format="csv")
