"""Tests for titan.u6.converse's CONVERSE.A/B bytecode disassembler.

No real game files are used here -- fixtures are hand-built to match the
byte-classification rules ported from Nuvie's ConverseInterpret.h/.cpp
(is_print/is_ctrl/is_valop/is_datasize and collect_input()'s boundary
logic). See titan/u6/converse.py's module docstring for the real-data
validation: disassembling a real CONVERSE.A entry (confirmed elsewhere to
be Dupre's script) correctly identifies his SIDENT/name and SLOOK/look-
text, and all 200 non-empty scripts across both real CONVERSE.A and
CONVERSE.B disassemble with zero boundary/truncation errors.
"""

from __future__ import annotations

import unittest

from titan.u6.converse import (
    U6ConverseError,
    U6ConverseInstruction,
    U6ConverseTextRun,
    disassemble,
    format_instructions,
)

# A few concrete opcode bytes used across tests, named for readability.
OP_IF = 0xA1
OP_ENDIF = 0xA2
OP_JUMP = 0xB0
OP_SIDENT = 0xFF
OP_KEYWORDS = 0xEF
OP_ASKC = 0xF8
OP_SLOOK = 0xF1
OP_BYE = 0xB6
OP_GT = 0x81  # a value-op byte
OP_EVAL = 0xA7
OP_VAR = 0xB2
OP_SVAR = 0xB3


class TextRunTests(unittest.TestCase):
    def test_plain_text_is_a_single_run(self):
        data = b"Hello world"
        out = disassemble(data)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], U6ConverseTextRun)
        self.assertEqual(out[0].text, "Hello world")

    def test_text_stops_at_control_byte(self):
        data = b"Hi" + bytes([OP_BYE])
        out = disassemble(data)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].text, "Hi")
        self.assertIsInstance(out[1], U6ConverseInstruction)
        self.assertEqual(out[1].name, "BYE")


class SpecialCaseTests(unittest.TestCase):
    def test_sident_reads_number_and_name_text(self):
        data = bytes([OP_SIDENT, 2]) + b"Dupre" + bytes([OP_BYE])
        out = disassemble(data)
        sident = out[0]
        self.assertEqual(sident.name, "SIDENT")
        self.assertEqual([o.value for o in sident.operands], [2])
        self.assertEqual(sident.text, "Dupre")

    def test_jump_reads_4byte_little_endian_target(self):
        data = bytes([OP_JUMP]) + (1234).to_bytes(4, "little")
        out = disassemble(data)
        self.assertEqual(out[0].name, "JUMP")
        self.assertEqual(out[0].jump_target, 1234)

    def test_keywords_reads_text_tail(self):
        data = bytes([OP_KEYWORDS]) + b"name" + bytes([OP_BYE])
        out = disassemble(data)
        self.assertEqual(out[0].name, "KEYWORDS")
        self.assertEqual(out[0].text, "name")
        self.assertEqual(out[0].operands, [])

    def test_askc_and_slook_also_use_text_tail(self):
        for opcode, name in [(OP_ASKC, "ASKC"), (OP_SLOOK, "SLOOK")]:
            with self.subTest(opcode=opcode):
                data = bytes([opcode]) + b"abc" + bytes([OP_BYE])
                out = disassemble(data)
                self.assertEqual(out[0].name, name)
                self.assertEqual(out[0].text, "abc")


class StandardOperandTests(unittest.TestCase):
    def test_opcode_with_no_operands(self):
        data = bytes([OP_BYE, OP_BYE])  # two BYEs back to back
        out = disassemble(data)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].operands, [])
        self.assertEqual(out[1].operands, [])

    def test_literal_byte_operand(self):
        # IF followed by a bare literal value, then ENDIF.
        data = bytes([OP_IF, 5, OP_ENDIF])
        out = disassemble(data)
        self.assertEqual(out[0].name, "IF")
        self.assertEqual([o.value for o in out[0].operands], [5])
        self.assertFalse(out[0].operands[0].is_op)

    def test_size_prefixed_operands(self):
        # 0xd3 -> 1-byte value, 0xd4 -> 2-byte value, 0xd2 -> 4-byte value.
        data = bytes([OP_IF, 0xD3, 0x07, 0xD4]) + (300).to_bytes(2, "little") \
            + bytes([0xD2]) + (70000).to_bytes(4, "little") + bytes([OP_ENDIF])
        out = disassemble(data)
        values = [o.value for o in out[0].operands]
        self.assertEqual(values, [7, 300, 70000])

    def test_valop_byte_marked_as_operator(self):
        data = bytes([OP_IF, OP_GT, OP_ENDIF])
        out = disassemble(data)
        self.assertTrue(out[0].operands[0].is_op)
        self.assertEqual(repr(out[0].operands[0]), "GT")

    def test_eval_marker_recorded_without_reduction(self):
        data = bytes([OP_IF, OP_EVAL, OP_ENDIF])
        out = disassemble(data)
        self.assertTrue(out[0].operands[0].is_op)
        self.assertEqual(out[0].operands[0].value, OP_EVAL)

    def test_printable_byte_followed_by_valop_is_consumed_as_operand(self):
        # 'A' (0x41) is printable, but if the NEXT byte is a value-op, Nuvie
        # treats 'A' itself as a literal operand value rather than text.
        data = bytes([OP_IF, ord("A"), OP_GT, OP_ENDIF])
        out = disassemble(data)
        self.assertEqual([o.value for o in out[0].operands], [ord("A"), OP_GT])

    def test_printable_byte_not_followed_by_valop_ends_the_instruction(self):
        # Here 'A' is followed by 'B' (not a value-op), so 'A' starts a new
        # text run instead of being consumed as an operand.
        data = bytes([OP_IF]) + b"AB"
        out = disassemble(data)
        self.assertEqual(out[0].operands, [])
        self.assertIsInstance(out[1], U6ConverseTextRun)
        self.assertEqual(out[1].text, "AB")


class UnknownOpcodeTests(unittest.TestCase):
    def test_unrecognized_control_byte_gets_fallback_name(self):
        data = bytes([0xC8, OP_BYE])  # 0xc8 has no name in any source consulted
        out = disassemble(data)
        self.assertEqual(out[0].name, "UNKNOWN_0xc8")


class ErrorHandlingTests(unittest.TestCase):
    def test_truncated_jump_target_raises(self):
        data = bytes([OP_JUMP, 0x01, 0x02])
        with self.assertRaises(U6ConverseError):
            disassemble(data)

    def test_truncated_sident_number_raises(self):
        data = bytes([OP_SIDENT])
        with self.assertRaises(U6ConverseError):
            disassemble(data)

    def test_truncated_size_prefixed_value_raises(self):
        data = bytes([OP_IF, 0xD2, 0x01, 0x02])  # claims 4 bytes, only 2 follow
        with self.assertRaises(U6ConverseError):
            disassemble(data)

    def test_stray_non_print_non_ctrl_byte_is_skipped(self):
        # Bytes below 0x20 that aren't 0x0a aren't printable and aren't
        # control opcodes (control requires >= 0xa1, or 0x9c/0x9e) --
        # Nuvie skips these with a warning; so does this disassembler.
        data = bytes([0x01]) + b"hi"
        out = disassemble(data)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].text, "hi")


class FormatInstructionsTests(unittest.TestCase):
    def test_format_includes_offsets_and_names(self):
        data = bytes([OP_SIDENT, 2]) + b"Dupre"
        out = disassemble(data)
        text = format_instructions(out)
        self.assertIn("SIDENT", text)
        self.assertIn("Dupre", text)

    def test_format_shows_jump_target(self):
        data = bytes([OP_JUMP]) + (42).to_bytes(4, "little")
        out = disassemble(data)
        text = format_instructions(out)
        self.assertIn("-> 42", text)


class KnownVariableAnnotationTests(unittest.TestCase):
    def test_known_int_variable_is_annotated(self):
        data = bytes([OP_IF, OP_VAR, 0x14, OP_ENDIF])  # VAR 0x14 = KARMA
        text = format_instructions(disassemble(data))
        self.assertIn("VAR 20 ; KARMA", text)

    def test_svar_uses_the_string_table_not_the_int_table(self):
        # Slot 0x19 means PLAYER_NAME as a string var, HP as an int var.
        data = bytes([OP_IF, OP_SVAR, 0x19, OP_ENDIF])
        text = format_instructions(disassemble(data))
        self.assertIn("SVAR 25 ; PLAYER_NAME", text)
        self.assertNotIn("HP", text)

    def test_var_with_the_same_slot_number_uses_the_int_table(self):
        data = bytes([OP_IF, OP_VAR, 0x19, OP_ENDIF])
        text = format_instructions(disassemble(data))
        self.assertIn("VAR 25 ; HP", text)

    def test_unknown_variable_number_is_not_annotated(self):
        data = bytes([OP_IF, OP_VAR, 0x02, OP_ENDIF])  # a per-script local, no known name
        text = format_instructions(disassemble(data))
        self.assertIn("VAR 2", text)
        self.assertNotIn(";", text)

    def test_annotation_does_not_leak_to_a_later_operand(self):
        # VAR KARMA GT 5 -- the literal 5 (GT's other operand) must stay plain.
        data = bytes([OP_IF, OP_VAR, 0x14, OP_GT, 5, OP_ENDIF])
        text = format_instructions(disassemble(data))
        self.assertIn("VAR 20 ; KARMA GT 5", text)
        self.assertNotIn("5 ;", text)


if __name__ == "__main__":
    unittest.main()
