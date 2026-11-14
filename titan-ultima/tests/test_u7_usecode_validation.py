"""Usecode structure, duplicate records, debug operands and CLI diagnostics."""

from __future__ import annotations

import csv
import io
import struct

import pytest
from typer.testing import CliRunner

from titan.u7 import cli
from titan.u7.shapeinfo import U7UsecodeIndex
from titan.u7.usecode import U7UsecodeFile, load_u7_intrinsic_names
from titan.u7 import install as u7_install
from tests.test_u7_usecode import (
    _extended_function_record,
    _function_record,
    _scope,
    _symbol,
)


def record(form: str, code: bytes = b"\x25") -> bytes:
    if form == "original":
        return _function_record(0x150, code)
    return _extended_function_record(
        0x12345 if form == "fffe" else 0x282, code, wide_id=form == "fffe"
    )


@pytest.mark.parametrize("form", ["original", "ffff", "fffe"])
@pytest.mark.parametrize("symbols", [False, True])
def test_shared_index_preserves_framing_csv_and_next_function(form, symbols):
    prefix = (
        b"\xff\xff\xff\xffYSCU" + _scope(_symbol("handler", 7, 0x150))
        if symbols
        else b""
    )
    first = record(form)
    data = prefix + first + _function_record(0x2C1)
    parsed = U7UsecodeFile.from_bytes(data, strict=True)
    index = U7UsecodeIndex.from_bytes(data, strict=True)
    assert len(index.functions) == 2
    for raw, row in zip(parsed.functions, index.functions):
        for name in (
            "offset",
            "func_id",
            "func_size",
            "data_size",
            "num_args",
            "num_locals",
            "num_externs",
            "externs",
            "ext32",
        ):
            assert getattr(row, name) == getattr(raw, name)
    assert index.functions[1].offset == len(prefix) + len(first)
    assert parsed.parsed_bytes == index.parsed_bytes == len(data)
    assert parsed.complete and index.complete
    assert not parsed.warnings and not index.warnings
    rows = list(csv.DictReader(io.StringIO(index.dump_csv())))
    assert rows[1]["func_id"] == str(0x2C1)
    assert rows[0]["ext32"] == str(int(form != "original"))


@pytest.mark.parametrize("form", ["original", "ffff", "fffe"])
def test_counts_externs_and_data_offsets_stay_independent_of_header_width(form):
    wide = form != "original"
    text = b"one\0two\0"
    code = b"\x24\x00\x00\x24\x01\x00\x25"
    body = struct.pack("<I" if wide else "<H", len(text)) + text
    body += struct.pack("<HHHHH", 2, 3, 2, 0x123, 0x456) + code
    if form == "fffe":
        prefix = struct.pack("<HII", 0xFFFE, 0x12345, len(body))
    elif form == "ffff":
        prefix = struct.pack("<HHI", 0xFFFF, 0x282, len(body))
    else:
        prefix = struct.pack("<HH", 0x150, len(body))
    data = prefix + body
    parsed = U7UsecodeFile.from_bytes(data, strict=True)
    fn = parsed.functions[0]
    assert (fn.num_args, fn.num_locals, fn.num_externs) == (2, 3, 2)
    assert fn.externs == [0x123, 0x456]
    assert data[fn.data_offset : fn.data_offset + fn.data_size] == text
    assert data[fn.code_offset : fn.end_offset] == code
    assert [i.operands for i in fn.iter_instructions(data)] == [[0], [1], []]


@pytest.mark.parametrize("form", ["original", "ffff", "fffe"])
def test_every_truncated_record_prefix_is_diagnosed_or_rejected(form):
    whole = record(form)
    for end in range(1, len(whole)):
        data = whole[:end]
        for reader in (U7UsecodeFile, U7UsecodeIndex):
            partial = reader.from_bytes(data)
            assert not partial.functions
            assert partial.parsed_bytes == 0 and not partial.complete
            assert partial.warnings
            with pytest.raises(ValueError, match="U7 USECODE"):
                reader.from_bytes(data, strict=True)


@pytest.mark.parametrize("form", ["original", "ffff", "fffe"])
def test_data_and_extern_bounds_do_not_borrow_from_following_function(form):
    good = _function_record(0x50)
    damaged = bytearray(record(form))
    body_start = {"original": 4, "ffff": 8, "fffe": 10}[form]
    data_width = 2 if form == "original" else 4
    # No extern bytes are present; the return opcode cannot satisfy two entries.
    struct.pack_into("<H", damaged, body_start + data_width + 4, 2)
    data = good + damaged + _function_record(0x99)
    for reader in (U7UsecodeFile, U7UsecodeIndex):
        parsed = reader.from_bytes(data)
        assert [f.func_id for f in parsed.functions] == [0x50]
        assert parsed.parsed_bytes == len(good)
        assert "extern table" in parsed.warnings[0] and not parsed.complete
        with pytest.raises(ValueError, match="extern table"):
            reader.from_bytes(data, strict=True)
    struct.pack_into("<H" if data_width == 2 else "<I", damaged, body_start, 0xFFFF)
    with pytest.raises(ValueError, match="data/count header"):
        U7UsecodeFile.from_bytes(bytes(damaged) + _function_record(0x99), strict=True)


def test_trailer_empty_stream_and_symbol_only_stream(tmp_path):
    data = _function_record(5) + b"\xaa"
    path = tmp_path / "usecode"
    path.write_bytes(data)
    for reader in (U7UsecodeFile, U7UsecodeIndex):
        parsed = reader.from_file(str(path))
        assert len(parsed.functions) == 1 and not parsed.complete
        assert "function header" in parsed.warnings[0]
        with pytest.raises(ValueError, match="function header"):
            reader.from_file(str(path), strict=True)
        assert reader.from_bytes(b"", strict=True).complete
        symbols = b"\xff\xff\xff\xffYSCU" + _scope()
        assert reader.from_bytes(symbols, strict=True).complete


def test_invalid_wide_id_and_too_small_body():
    for data, context in (
        (struct.pack("<HII", 0xFFFE, 0xFFFFFFFF, 10) + bytes(10), "negative wide"),
        (struct.pack("<HH", 1, 2) + bytes(2), "incomplete function body"),
    ):
        with pytest.raises(ValueError, match=context):
            U7UsecodeFile.from_bytes(data, strict=True)
        assert not U7UsecodeFile.from_bytes(data).complete


def test_symbol_nesting_has_bounded_failure():
    scope = _scope()
    for _ in range(70):
        scope = _scope(_symbol("nested", 4, 0, scope + struct.pack("<HH", 0, 0)))
    with pytest.raises(ValueError, match="nesting exceeds"):
        U7UsecodeFile.from_bytes(b"\xff\xff\xff\xffYSCU" + scope)


@pytest.mark.parametrize("form", ["original", "ffff", "fffe"])
def test_dbgfunc32_is_two_dwords_and_independent_of_header_form(form):
    code = b"\xcd" + struct.pack("<II", 0x12345, 0x67890) + b"\x38\x14\x00\x01\x25"
    data = record(form, code)
    parsed = U7UsecodeFile.from_bytes(data, strict=True)
    instructions = parsed.iter_instructions()
    assert [(i.mnemonic, i.code_offset, len(i.raw)) for i in instructions] == [
        ("dbgfunc32", 0, 9),
        ("callis", 9, 4),
        ("ret", 13, 1),
    ]
    assert instructions[0].operands == [0x12345, 0x67890]
    assert instructions[0].operand_types == ["data32", "data32"]
    calls = parsed.scan_intrinsic(0x14)
    assert len(calls) == 1 and calls[0].code_offset == 9
    assert calls[0].file_offset == parsed.functions[0].code_offset + 9


def test_duplicate_ids_lookup_last_but_raw_disassembly_and_scans_keep_both():
    first = _function_record(5, b"\x13\x38\x14\x00\x00\x25")
    second = _function_record(5, b"\x14\x39\x14\x00\x00\x25")
    parsed = U7UsecodeFile.from_bytes(first + second, strict=True)
    selected = parsed.get_function(5)
    assert selected is not None and selected.offset == len(first)
    assert parsed.iter_instructions(5)[0].mnemonic == "push false"
    assert parsed.function_for_offset(0) is parsed.functions[0]
    assert parsed.function_for_offset(len(first)) is parsed.functions[1]
    text = parsed.disassemble_all()
    assert text.count("push true") == text.count("push false") == 1
    assert "push false" in parsed.disassemble(
        5
    ) and "push true" not in parsed.disassemble(5)
    calls = parsed.scan_intrinsic(0x14)
    assert [call.returns_value for call in calls] == [True, False]
    assert [call.function_offset for call in calls] == [0, len(first)]


def test_truncated_opcode_is_raw_inspection_not_false_intrinsic_match():
    parsed = U7UsecodeFile.from_bytes(_function_record(5, b"\x38\x14"), strict=True)
    assert parsed.complete  # Structural completeness does not certify VM instructions.
    instruction = parsed.iter_instructions()[0]
    assert instruction.truncated and instruction.raw == b"\x38\x14"
    assert "truncated" in instruction.format_asm()
    assert parsed.scan_intrinsic(0x14) == []


@pytest.fixture
def usecode_path(tmp_path):
    path = tmp_path / "usecode"
    path.write_bytes(_function_record(5, b"\x38\x14\x00\x00\x25"))
    return path


@pytest.mark.parametrize("command", ["usecode-disasm", "usecode-scan-intrinsic"])
def test_cli_missing_explicit_intrinsic_table_errors_without_default_fallback(
    usecode_path, command
):
    target = "5" if command == "usecode-disasm" else "0x14"
    result = CliRunner().invoke(
        cli.u7_app,
        [
            command,
            str(usecode_path),
            target,
            "--intrinsics-data",
            str(usecode_path.parent / "absent.data"),
        ],
    )
    assert result.exit_code == 1 and "intrinsic table not found" in result.output


@pytest.mark.parametrize(
    "data", [b"no intrinsic entries", b"<0x10000> impossible </>", b"\xff"]
)
def test_cli_invalid_explicit_intrinsic_table_is_an_error(usecode_path, data):
    table = usecode_path.parent / "intrinsics.data"
    table.write_bytes(data)
    result = CliRunner().invoke(
        cli.u7_app,
        ["usecode-disasm", str(usecode_path), "5", "--intrinsics-data", str(table)],
    )
    assert result.exit_code == 1 and "Cannot read U7 intrinsic table" in result.output


def test_intrinsic_table_identity_and_numeric_fallback(usecode_path, monkeypatch):
    table = usecode_path.parent / "si-beta.data"
    table.write_text("<intrinsics>\n<0x14> beta_name </>\n</>", encoding="utf-8-sig")
    assert load_u7_intrinsic_names(str(table)) == {0x14: "beta_name"}
    result = CliRunner().invoke(
        cli.u7_app,
        [
            "usecode-disasm",
            str(usecode_path),
            "5",
            "--game",
            "si",
            "--intrinsics-data",
            str(table),
        ],
    )
    assert result.exit_code == 0 and "beta_name@00" in result.output
    monkeypatch.setattr(u7_install, "resolve_ucxt_intrinsics_data", lambda *args: None)
    numeric = CliRunner().invoke(cli.u7_app, ["usecode-disasm", str(usecode_path), "5"])
    assert numeric.exit_code == 0 and "0x0014@00" in numeric.output


@pytest.mark.parametrize("game", ["bg", "si"])
def test_default_intrinsic_table_lookup_uses_separate_game_names(game, monkeypatch):
    from pathlib import Path

    expected = "u7bgintrinsics.data" if game == "bg" else "u7siintrinsics.data"
    monkeypatch.setattr(Path, "is_file", lambda path: path.name == expected)
    selected = u7_install.resolve_ucxt_intrinsics_data(game)
    assert selected is not None and selected.endswith(expected)


def test_intrinsic_game_validation_at_cli_and_helper(usecode_path):
    with pytest.raises(ValueError, match="must be bg or si"):
        u7_install.resolve_ucxt_intrinsics_data("wrong")
    result = CliRunner().invoke(
        cli.u7_app, ["usecode-disasm", str(usecode_path), "5", "--game", "wrong"]
    )
    assert result.exit_code == 2


@pytest.mark.parametrize("command", ["usecode-disasm", "usecode-scan-intrinsic"])
def test_cli_reports_permissive_prefix_and_unrecoverable_symbol_errors(
    usecode_path, command, monkeypatch
):
    monkeypatch.setattr(u7_install, "resolve_ucxt_intrinsics_data", lambda *args: None)
    target = "5" if command == "usecode-disasm" else "0x14"
    usecode_path.write_bytes(usecode_path.read_bytes() + b"\xaa")
    result = CliRunner().invoke(cli.u7_app, [command, str(usecode_path), target])
    assert (
        result.exit_code == 0
        and "Warning: Truncated U7 USECODE function header" in result.output
    )
    strict = CliRunner().invoke(
        cli.u7_app, [command, str(usecode_path), target, "--strict"]
    )
    assert (
        strict.exit_code == 1
        and "ERROR: Truncated U7 USECODE function header" in strict.output
    )
    usecode_path.write_bytes(b"\xff\xff\xff\xffYSCU" + struct.pack("<II", 1, 0))
    bad = CliRunner().invoke(cli.u7_app, [command, str(usecode_path), target])
    assert bad.exit_code == 1 and "symbol name" in bad.output


def test_metadata_dump_uses_symbol_prefix_and_propagates_warnings(usecode_path):
    prefix = b"\xff\xff\xff\xffYSCU" + _scope(_symbol("handler", 7, 5))
    usecode_path.write_bytes(prefix + _function_record(5) + b"\xaa")
    result = CliRunner().invoke(
        cli.u7_app, ["static-data-dump", "usecode", str(usecode_path.parent)]
    )
    assert (
        result.exit_code == 0
        and "Warning: Truncated U7 USECODE function header" in result.output
    )
    assert "0x0005" in result.output


@pytest.mark.parametrize("value", ["-1", "65536", "invalid"])
def test_intrinsic_cli_rejects_invalid_u16_target(usecode_path, value):
    result = CliRunner().invoke(
        cli.u7_app, ["usecode-scan-intrinsic", str(usecode_path), value]
    )
    assert result.exit_code != 0
