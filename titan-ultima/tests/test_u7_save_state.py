"""Exult save-state regressions across old/new extensions and malformed boundaries."""

from __future__ import annotations

import csv
import io
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from titan.u7.cli.saves import cmd_gamedat_info, cmd_save_info
from titan.u7.save import (
    U7GameState,
    U7GlobalFlags,
    U7Keyring,
    U7Save,
    U7SaveInfo,
    U7UsecodeData,
    U7UsecodeVars,
)


def party_prefix(count: int = 3) -> bytes:
    return struct.pack("<9H", count, 11, 22, 33, 44, 55, 66, 77, 88)


def dense_runtime() -> bytes:
    return party_prefix() + struct.pack("<20I", *range(100, 120))


def window_state() -> bytes:
    return struct.pack(
        "<5HIiI4B", 301, 402, 17, 23, 59, 123456, -1, (27 << 16) | 1, 1, 0, 1, 0
    )


def populated_statics() -> bytes:
    # All six tags, including sentinel bytes inside values, not block boundaries.
    integer = b"\x00" + struct.pack("<I", 0xFFFFFFFF)
    string = b"\x01\x04\x00\xff\xff\xff\xff"
    pointer = b"\x03\x00\x00\x00\x00"
    symbol = b"\x04\x03\x00Foo"
    class_object = b"\x05\x02\x00" + symbol + integer
    array = b"\x02\x03\x00" + integer + string + class_object
    return (
        struct.pack("<I", 1)
        + array
        + struct.pack("<II", 0x1234, 1)
        + pointer
        + struct.pack("<IH", 0xFFFFFFFE, 3)
        + b"foo"
        + struct.pack("<I", 1)
        + integer
        + struct.pack("<I", 0xFFFFFFFF)
    )


def preview_info(count: int = 2) -> bytes:
    header = bytearray(64)
    header[:4] = bytes([58, 23, 7, 11])
    struct.pack_into("<HBBHH", header, 4, 2026, 59, 22, 17, 9)
    header[12], header[14] = count, 42
    record = bytearray(64)
    record[:18] = b"ABCDEFGHIJKLMNOPQR"
    struct.pack_into("<HIII", record, 18, 1027, 123456, 0x80000001, 0x12345678)
    record[32:40] = bytes([20, 63, 21, 22, 23, 24, 25, 26])
    struct.pack_into("<hH", record, 40, -7, 2)
    return bytes(header) + bytes(record) * count


@pytest.mark.parametrize(
    "tail",
    [b"", struct.pack("<hhh", 301, 402, 3), struct.pack("<hhhH", 301, 402, 3, 9)],
)
def test_dense_runtime_eight_slots_and_unique_timers(tail: bytes) -> None:
    state = U7UsecodeData.from_bytes(dense_runtime() + tail)
    assert state.party_members == [11, 22, 33]
    assert [(t.timer_id, t.value) for t in state.timers] == list(
        enumerate(range(100, 120))
    )
    assert state.timer_format == "legacy"
    assert (state.saved_tx, state.saved_ty, state.saved_tz) == (
        (301, 402, 3) if tail else (-1, -1, -1)
    )
    assert state.saved_map == (9 if len(tail) == 8 else -1)
    assert not state.warnings


def test_sparse_runtime_ids_terminator_signed_position_and_map() -> None:
    data = party_prefix(0) + struct.pack(
        "<IHIHIH", 0xFFFFFFFF, 7, 123, 450, 456, 0xFFFF
    )
    state = U7UsecodeData.from_bytes(data + struct.pack("<hhhH", -2, 402, 3, 0xFFFF))
    assert state.party_members == []
    assert state.timer_format == "sparse"
    assert [(t.timer_id, t.value) for t in state.timers] == [(7, 123), (450, 456)]
    assert state.saved_tx == -2 and state.saved_tz == 3
    assert state.saved_map == 65535  # Stored map word differs from an absent map.


@pytest.mark.parametrize("position", [(-1, -1, -1), (301, 402, 14)])
def test_runtime_invalid_lift_preserves_raw_coordinates(
    position: tuple[int, int, int],
) -> None:
    state = U7UsecodeData.from_bytes(dense_runtime() + struct.pack("<hhh", *position))
    assert (state.saved_tx, state.saved_ty, state.saved_tz) == (-1, -1, -1)
    assert state.saved_position_raw == position


def test_runtime_rejects_short_party_and_timers_without_fabricating_values() -> None:
    data = dense_runtime()
    for size in range(len(data)):
        with pytest.raises(ValueError, match="usecode.dat"):
            U7UsecodeData.from_bytes(data[:size])


@pytest.mark.parametrize(
    "data",
    [
        party_prefix(9),
        party_prefix() + struct.pack("<I", 0xFFFFFFFF),
        party_prefix() + struct.pack("<IH", 0xFFFFFFFF, 7),
        party_prefix() + struct.pack("<IHI", 0xFFFFFFFF, 7, 123),
        dense_runtime() + bytes(1),
        dense_runtime() + bytes(5),
        dense_runtime() + bytes(7),
    ],
)
def test_runtime_rejects_incomplete_extensions_and_sparse_termination(
    data: bytes,
) -> None:
    with pytest.raises(ValueError, match="usecode.dat"):
        U7UsecodeData.from_bytes(data)


def test_runtime_reports_duplicate_sparse_ids_and_trailing_bytes() -> None:
    data = party_prefix() + struct.pack("<IHIHIH", 0xFFFFFFFF, 7, 123, 7, 456, 0xFFFF)
    state = U7UsecodeData.from_bytes(data + struct.pack("<hhhH", 301, 402, 3, 1) + b"X")
    assert [timer.value for timer in state.timers] == [123, 456]
    assert state.trailing_data == b"X"
    assert "duplicate sparse timer" in state.dump() and "trailing" in state.dump()


@pytest.mark.parametrize("length", [10, 14, 22, 23, 24, 25, 26])
def test_window_old_exult_prefixes_and_extensions(length: int) -> None:
    state = U7GameState.from_bytes(window_state()[:length])
    assert (state.scroll_tx, state.scroll_ty, state.clock_day) == (301, 402, 17)
    assert state.special_light == (123456 if length >= 14 else 0)
    assert state.music_track == -1
    assert state.music_track_raw == (0xFFFFFFFF if length >= 22 else None)
    assert state.music_egg_count == (27 if length >= 22 else 0)
    assert state.armageddon == (length >= 23)
    assert state.combat == (length >= 25)
    assert not state.warnings
    assert "4294967295" not in state.dump()
    assert ("not stored" if length < 22 else "none") in state.dump()


@pytest.mark.parametrize("length", [0, 9, 11, 12, 13, 15, 18, 21])
def test_window_rejects_incomplete_present_fields(length: int) -> None:
    with pytest.raises(ValueError, match="gamewin.dat"):
        U7GameState.from_bytes(window_state()[:length])


def test_window_noncanonical_flags_and_future_tail_are_reported() -> None:
    data = bytearray(window_state())
    data[22:26] = bytes([2, 1, 255, 0])
    state = U7GameState.from_bytes(bytes(data) + b"future")
    assert (state.armageddon, state.ambient_light, state.combat) == (False, True, False)
    assert state.raw_flags == bytes([2, 1, 255, 0])
    assert state.trailing_data == b"future" and len(state.warnings) == 3


def test_static_values_traverse_all_tags_globals_and_named_numeric_blocks() -> None:
    data = populated_statics()
    state = U7UsecodeVars.from_bytes(data)
    assert state.global_static_count == 1 and state.local_static_blocks == 2
    array = state.global_values[0]
    assert array.type_tag == 2 and isinstance(array.value, tuple)
    assert [value.type_tag for value in array.value] == [0, 1, 5]
    assert array.value[0].value == 0xFFFFFFFF
    assert array.value[1].value == bytes([255]) * 4
    class_object = array.value[2]
    assert isinstance(class_object.value, tuple)
    assert class_object.value[0].type_tag == 4 and class_object.value[0].value == b"Foo"
    numeric, named = state.function_statics
    assert numeric.function_id == 0x1234 and numeric.function_name is None
    assert numeric.values[0].type_tag == 3 and numeric.values[0].value == 0
    assert named.function_id is None and named.function_name == b"foo"
    assert named.end_offset == len(data) - 4
    assert data[array.offset] == 2 and not state.warnings


def test_static_values_empty_tail_and_all_truncated_prefixes() -> None:
    empty = U7UsecodeVars.from_bytes(struct.pack("<II", 0, 0xFFFFFFFF))
    assert empty.local_static_blocks == 0 and not empty.global_values
    data = populated_statics()
    for size in range(len(data)):
        with pytest.raises(ValueError, match="usecode.var"):
            U7UsecodeVars.from_bytes(data[:size])
    state = U7UsecodeVars.from_bytes(data + b"future")
    assert state.trailing_data == b"future" and "trailing" in state.dump()


@pytest.mark.parametrize(
    "values",
    [
        b"\x06",
        b"\x01\xff\xff",
        b"\x02\xff\xff",
        b"\x02\x01\x00" * 130 + b"\x00" + bytes(4),
    ],
)
def test_static_values_reject_unknown_tags_bad_lengths_and_excessive_nesting(
    values: bytes,
) -> None:
    with pytest.raises(ValueError, match="usecode.var"):
        U7UsecodeVars.from_bytes(struct.pack("<I", 1) + values + bytes([255]) * 4)


def test_save_preview_offsets_resolved_stats_signed_health_and_partial_roster() -> None:
    data = preview_info()
    info = U7SaveInfo.from_bytes(data)
    assert info.real_second == 42 and info.real_year == 2026
    assert info.party[0].name == "ABCDEFGHIJKLMNOPQR"
    assert info.party[0].strength == 63 and info.party[0].health == -7
    assert info.party[0].shape_file == 2 and not info.warnings
    partial = U7SaveInfo.from_bytes(data[:130])
    assert len(partial.party) == 1 and "roster is incomplete" in partial.dump()
    extra = U7SaveInfo.from_bytes(data + b"extra")
    assert extra.trailing_data == b"extra" and "trailing" in extra.dump()
    with pytest.raises(ValueError, match="saveinfo.dat"):
        U7SaveInfo.from_bytes(data[:63])


def test_keyring_empty_raw_order_unique_memberships_and_dangling_word() -> None:
    assert not U7Keyring.from_bytes(b"").warnings
    state = U7Keyring.from_bytes(struct.pack("<4H", 7, 0x1234, 7, 1) + b"\xff")
    assert state.keys == [7, 0x1234, 7, 1] and state.unique_keys == [1, 7, 0x1234]
    assert state.trailing_data == b"\xff" and len(state.warnings) == 2
    assert "3 unique, 4 stored" in state.dump()


def test_flaginit_keeps_byte_values_without_imposing_exult_page_size() -> None:
    state = U7GlobalFlags.from_bytes(b"\x00\x01\x02")
    assert state.raw == b"\x00\x01\x02" and state.is_set(2)
    assert state.nonzero_count == 2


@pytest.mark.parametrize(
    "game,identity", [("bg", b"BLACKGATE"), ("si", b"SERPENTISLE")]
)
def test_exult_bg_si_archive_and_cli_report_same_runtime_layouts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    game: str,
    identity: bytes,
) -> None:
    from titan.u7 import cli

    monkeypatch.setattr(cli._common, "_load_container_shapes", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli._common, "_load_shape_count", lambda *args, **kwargs: None)
    members = {
        "identity": identity,
        "usecode.dat": dense_runtime(),
        "usecode.var": populated_statics(),
        "gamewin.dat": window_state(),
        "saveinfo.dat": preview_info()[:64],
    }
    if game == "si":
        members["keyring.dat"] = b"\x34\x12\xff"
    path = tmp_path / f"test-{game}.sav"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    original = path.read_bytes()
    save = U7Save.from_file(str(path))
    runtime_data = save.get_data("usecode.dat")
    assert runtime_data is not None
    assert U7UsecodeData.from_bytes(runtime_data).timers[-1].value == 119
    args = SimpleNamespace(directory=str(path), game=game, format="csv", output=None)
    assert cmd_gamedat_info(args) == 0
    rows = {
        row["file"]: row for row in csv.DictReader(io.StringIO(capsys.readouterr().out))
    }
    assert rows["saveinfo.dat"]["status"] == "parsed with warnings"
    assert "roster is incomplete" in rows["saveinfo.dat"]["note"]
    assert "2 local blocks" in rows["usecode.var"]["note"]
    assert ("keyring.dat" in rows) == (game == "si")
    if game == "si":
        assert rows["keyring.dat"]["status"] == "parsed with warnings"
    assert cmd_save_info(SimpleNamespace(file=str(path), output=None)) == 0
    output = capsys.readouterr().out
    assert "roster is incomplete" in output and "Music:       none" in output
    assert path.read_bytes() == original
