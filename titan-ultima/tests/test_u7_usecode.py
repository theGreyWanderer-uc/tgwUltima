"""Tests for parsing and disassembling Ultima VII USECODE files."""

from __future__ import annotations

import struct
import unittest

from titan.u7.usecode import U7UsecodeFile


def _function_record(func_id: int, code: bytes = b"\x25") -> bytes:
    data = b""
    body = struct.pack("<H", len(data)) + data
    body += struct.pack("<HHH", 0, 0, 0) + code
    return struct.pack("<HH", func_id, len(body)) + body


def _extended_function_record(
    func_id: int, code: bytes = b"\x25", *, wide_id: bool = False
) -> bytes:
    data = b""
    body = struct.pack("<I", len(data)) + data
    body += struct.pack("<HHH", 0, 0, 0) + code
    marker = 0xFFFE if wide_id else 0xFFFF
    encoded_id = struct.pack("<I", func_id) if wide_id else struct.pack("<H", func_id)
    return struct.pack("<H", marker) + encoded_id + struct.pack("<I", len(body)) + body


def _symbol(name: str, kind: int, value: int, extra: bytes = b"") -> bytes:
    return name.encode("ascii") + b"\0" + struct.pack("<HI", kind, value) + extra


def _scope(*symbols: bytes) -> bytes:
    return struct.pack("<II", len(symbols), 0) + b"".join(symbols)


class U7UsecodeSymbolTableTests(unittest.TestCase):
    def test_reads_function_after_exult_symbol_table(self):
        symbol_table = b"\xff\xff\xff\xffYSCU" + _scope(_symbol("AvatarFunc", 7, 0x60E))
        data = symbol_table + _function_record(0x60E)

        usecode = U7UsecodeFile.from_bytes(data)
        function = usecode.get_function(0x60E)

        self.assertIsNotNone(function)
        if function is None:
            self.fail("Expected function 0x60E after the symbol table")
        self.assertEqual(function.offset, len(symbol_table))
        self.assertEqual(function.end_offset, len(data))
        self.assertEqual(function.iter_instructions(data)[0].mnemonic, "ret")

    def test_skips_nested_class_and_shape_function_metadata(self):
        class_scope = _scope(_symbol("method", 1, 0xC00))
        class_metadata = struct.pack("<HHH", 1, 0xC00, 3)
        symbol_table = b"\xff\xff\xff\xffYSCU" + _scope(
            _symbol("helpers", 4, 0, class_scope + class_metadata),
            _symbol("shapeHandler", 6, 0x900, struct.pack("<I", 721)),
        )
        data = symbol_table + _function_record(0x900)

        usecode = U7UsecodeFile.from_bytes(data)

        self.assertEqual(len(usecode.functions), 1)
        self.assertEqual(usecode.functions[0].func_id, 0x900)
        self.assertEqual(usecode.functions[0].offset, len(symbol_table))

    def test_rejects_truncated_symbol_table(self):
        data = b"\xff\xff\xff\xffYSCU" + struct.pack("<II", 1, 0)

        with self.assertRaisesRegex(ValueError, "symbol name"):
            U7UsecodeFile.from_bytes(data)

    def test_original_game_file_without_symbol_table_is_unchanged(self):
        data = _function_record(0x150)

        usecode = U7UsecodeFile.from_bytes(data)

        self.assertEqual(len(usecode.functions), 1)
        self.assertEqual(usecode.functions[0].offset, 0)
        self.assertEqual(usecode.functions[0].func_id, 0x150)

    def test_old_extended_record_does_not_consume_next_function_id(self):
        first = _extended_function_record(0x282)
        data = first + _function_record(0x2C1)

        usecode = U7UsecodeFile.from_bytes(data)

        self.assertEqual(
            [function.func_id for function in usecode.functions], [0x282, 0x2C1]
        )
        self.assertEqual(usecode.functions[0].end_offset, len(first))
        self.assertEqual(usecode.functions[1].offset, len(first))

    def test_new_extended_record_supports_32_bit_function_id(self):
        data = _extended_function_record(0x12345, wide_id=True)

        usecode = U7UsecodeFile.from_bytes(data)

        self.assertEqual(len(usecode.functions), 1)
        self.assertEqual(usecode.functions[0].func_id, 0x12345)
        self.assertEqual(usecode.functions[0].end_offset, len(data))


if __name__ == "__main__":
    unittest.main()
