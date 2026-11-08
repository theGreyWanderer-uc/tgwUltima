"""Usecode symbols, reference annotations and original-base patch semantics."""

import json
import struct

from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.usecode import U7UsecodeFile
from titan.u7.usecode_analysis import U7UsecodeWorld, annotate_usecode_instruction
from tests.test_u7_usecode import _function_record, _scope, _symbol


def test_symbols_expose_class_members_methods_and_shape_bindings():
    nested = _scope(_symbol("method", 1, 0xC00))
    prefix = b"\xff\xff\xff\xffYSCU" + _scope(
        _symbol("class", 4, 3) + nested + struct.pack("<HHH", 1, 0xC00, 2),
        _symbol("handler", 6, 0x500) + struct.pack("<I", 800),
    )
    stream = U7UsecodeFile.from_bytes(prefix + _function_record(0x500), strict=True)
    cls, handler = stream.symbols
    assert cls.children[0].name == "method" and cls.methods == (0xC00,)
    assert cls.variable_count == 2 and handler.shape == 800
    assert stream.functions[0].offset == len(prefix)


def test_instruction_annotations_keep_raw_signed_bits_and_validate_targets():
    stream = U7UsecodeFile.from_bytes(
        _function_record(100, b"\x1f\xff\xff\x06\xfa\xff\x25")
    )
    function = stream.functions[0]
    assert annotate_usecode_instruction(
        stream, function, stream.iter_instructions()[0]
    ) == ["signed=-1"]
    assert not stream.validate_references()
    invalid = U7UsecodeFile.from_bytes(
        _function_record(100, b"\x06\xfe\xff\x24\x00\x00\x1d\x00\x00\x25")
    )
    issues = invalid.validate_references()
    assert len(issues) == 3
    assert any("instruction boundary" in issue.message for issue in issues)
    assert invalid.complete


def test_patching_a_patch_keeps_the_original_base_for_callo():
    base = U7UsecodeFile.from_bytes(_function_record(100, b"\x13\x25"))
    patch = U7UsecodeFile.from_bytes(_function_record(100, b"\x14\x25"))
    newer = U7UsecodeFile.from_bytes(_function_record(100, b"\x32"))
    world = U7UsecodeWorld()
    world.add_stream(base, source="base")
    world.add_stream(patch, source="patch", patch=True)
    world.add_stream(newer, source="newer", patch=True)
    assert world.get_function(100).source == "newer"
    assert world.get_function(100, original=True).source == "base"
    assert len(world.history[100]) == 3
    assert "push true" in world.get_function(100, original=True).disassemble()


def test_usecode_cli_annotations_validation_symbols_and_original(tmp_path):
    base, patch = tmp_path / "base", tmp_path / "patch"
    base.write_bytes(_function_record(100, b"\x1f\xff\xff\x25"))
    patch.write_bytes(_function_record(100, b"\x32"))
    result = CliRunner().invoke(
        u7_app,
        [
            "usecode-disasm",
            str(base),
            "100",
            "--patch-file",
            str(patch),
            "--original",
            "--annotate",
            "--validate",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "signed=-1" in result.stdout
    result = CliRunner().invoke(u7_app, ["usecode-disasm", str(base), "--symbols"])
    assert result.exit_code == 0 and json.loads(result.stdout) == []
    result = CliRunner().invoke(u7_app, ["usecode-disasm", "--help"])
    assert all(
        flag in result.stdout
        for flag in (
            "--annotate",
            "--validate",
            "--symbols",
            "--patch-file",
            "--original",
        )
    )


def test_annotated_all_and_validation_preserve_superseded_raw_records(tmp_path):
    path = tmp_path / "usecode"
    path.write_bytes(_function_record(100, b"\x06\xfe\xff\x25") + _function_record(100))
    result = CliRunner().invoke(
        u7_app, ["usecode-disasm", str(path), "--all", "--annotate", "--validate"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.count("Function 0x64;") == 2
    assert "instruction boundary" in result.stderr
