"""Ultima 7 USECODE parser and raw disassembler."""

from __future__ import annotations

__all__ = [
    "U7UsecodeCallSite",
    "U7UsecodeFile",
    "U7UsecodeFunctionRecord",
    "U7UsecodeInstruction",
    "load_u7_intrinsic_names",
]

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path


_OPCODE_INFO: dict[int, tuple[str, tuple[str, ...]]] = {
    0x02: ("loop", ("short", "short", "short", "var", "offset")),
    0x04: ("startconv", ("offset",)),
    0x05: ("jne", ("offset",)),
    0x06: ("jmp", ("offset",)),
    0x07: ("cmps", ("short", "offset")),
    0x09: ("add", ()),
    0x0A: ("sub", ()),
    0x0B: ("div", ()),
    0x0C: ("mul", ()),
    0x0D: ("mod", ()),
    0x0E: ("and", ()),
    0x0F: ("or", ()),
    0x10: ("not", ()),
    0x12: ("pop", ("var",)),
    0x13: ("push true", ()),
    0x14: ("push false", ()),
    0x16: ("cmpgt", ()),
    0x17: ("cmplt", ()),
    0x18: ("cmpge", ()),
    0x19: ("cmple", ()),
    0x1A: ("cmpne", ()),
    0x1C: ("addsi", ("data",)),
    0x1D: ("pushs", ("data",)),
    0x1E: ("arrc", ("short",)),
    0x1F: ("pushi", ("short",)),
    0x21: ("push", ("var",)),
    0x22: ("cmpeq", ()),
    0x24: ("call", ("extern",)),
    0x25: ("ret", ()),
    0x26: ("aidx", ("var",)),
    0x2C: ("ret2", ()),
    0x2D: ("retv", ()),
    0x2E: ("initloop", ()),
    0x2F: ("addsv", ("var",)),
    0x30: ("in", ()),
    0x31: ("default", ("short", "offset")),
    0x32: ("retz", ()),
    0x33: ("say", ()),
    0x38: ("callis", ("intrinsic", "byte")),
    0x39: ("calli", ("intrinsic", "byte")),
    0x3E: ("push itemref", ()),
    0x3F: ("abrt", ()),
    0x40: ("endconv", ()),
    0x42: ("pushf", ("flag",)),
    0x43: ("popf", ("flag",)),
    0x44: ("pushb", ("byte",)),
    0x46: ("setarrayelem", ("var",)),
    0x47: ("calle", ("short",)),
    0x48: ("push eventid", ()),
    0x4A: ("arra", ()),
    0x4B: ("pop eventid", ()),
    0x4C: ("dbgline", ("short",)),
    0x4D: ("dbgfunc", ("short", "data")),
    0x50: ("push static", ("var",)),
    0x51: ("pop static", ("var",)),
    0x52: ("callo", ("short",)),
    0x53: ("callind", ()),
    0x54: ("push clsvar", ("var",)),
    0x55: ("pop clsvar", ("var",)),
    0x56: ("callm", ("short",)),
    0x57: ("callms", ("short", "short")),
    0x58: ("clscreate", ("short",)),
    0x59: ("classdel", ()),
    0x5A: ("aidxs", ("var",)),
    0x5B: ("setstaticarrayelem", ("var",)),
    0x5C: ("staticloop", ("short", "short", "short", "var", "offset")),
    0x5D: ("aidxclsvar", ("var",)),
    0x5E: ("setclsvararrayelem", ("var",)),
    0x5F: ("clsvarloop", ("short", "short", "short", "var", "offset")),
    0x60: ("push choice", ()),
    0x61: ("starttry", ("offset",)),
    0x62: ("endtry", ()),
    0x82: ("loop32", ("short", "short", "short", "var", "offset32")),
    0x84: ("startconv32", ("offset32",)),
    0x85: ("jne32", ("offset32",)),
    0x86: ("jmp32", ("offset32",)),
    0x87: ("cmps32", ("short", "offset32")),
    0x9C: ("addsi32", ("data32",)),
    0x9D: ("pushs32", ("data32",)),
    0x9F: ("pushi32", ("long",)),
    0xA4: ("call32", ("long",)),
    0xAE: ("initloop32", ()),
    0xB1: ("default32", ("short", "offset32")),
    0xBF: ("throw", ()),
    0xC2: ("pushfvar", ()),
    0xC3: ("popfvar", ()),
    0xC7: ("calle32", ("long",)),
    0xCD: ("dbgfunc32", ("short", "data32")),
    0xD3: ("callindex_old", ()),
    0xD4: ("callindex", ("byte",)),
    0xDC: ("staticloop32", ("short", "short", "short", "var", "offset32")),
    0xDF: ("clsvarloop32", ("short", "short", "short", "var", "offset32")),
    0xE1: ("starttry32", ("offset32",)),
}

_OPERAND_WIDTH = {
    "byte": 1,
    "data": 2,
    "data32": 4,
    "extern": 2,
    "flag": 2,
    "intrinsic": 2,
    "long": 4,
    "offset": 2,
    "offset32": 4,
    "short": 2,
    "var": 2,
}


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 2], "little")


def _u32(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 4], "little")


def _signed(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def _rows_to_csv(rows: list[dict[str, object]]) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


@dataclass
class U7UsecodeInstruction:
    function_id: int
    file_offset: int
    code_offset: int
    opcode: int
    mnemonic: str
    operands: list[int]
    operand_types: list[str]
    raw: bytes
    truncated: bool = False

    @property
    def is_intrinsic_call(self) -> bool:
        return self.opcode in (0x38, 0x39) and len(self.operands) >= 2

    @property
    def intrinsic_id(self) -> int | None:
        return self.operands[0] if self.is_intrinsic_call else None

    @property
    def intrinsic_arg_count(self) -> int | None:
        return self.operands[1] if self.is_intrinsic_call else None

    @property
    def returns_value(self) -> bool:
        return self.opcode == 0x38

    def format_asm(self, intrinsic_names: dict[int, str] | None = None) -> str:
        if self.mnemonic == "db":
            return f"{self.code_offset:04X}: {self.raw.hex(' ').upper():<14} db 0x{self.opcode:02X}"
        if self.is_intrinsic_call:
            intrinsic_id = self.intrinsic_id or 0
            name = (
                intrinsic_names.get(intrinsic_id, f"UNKNOWN_{intrinsic_id:02X}")
                if intrinsic_names
                else f"0x{intrinsic_id:04X}"
            )
            args = self.intrinsic_arg_count or 0
            return (
                f"{self.code_offset:04X}: {self.raw.hex(' ').upper():<14} "
                f"{self.mnemonic:<8} {name}@{args:02d}"
            )
        operands = ", ".join(
            _format_operand(value, typ, self.code_offset + len(self.raw))
            for value, typ in zip(self.operands, self.operand_types)
        )
        suffix = f" {operands}" if operands else ""
        mark = " ; truncated" if self.truncated else ""
        return (
            f"{self.code_offset:04X}: {self.raw.hex(' ').upper():<14} "
            f"{self.mnemonic}{suffix}{mark}"
        )


def _format_operand(value: int, typ: str, next_code_offset: int) -> str:
    if typ in {"offset", "offset32"}:
        bits = 32 if typ.endswith("32") else 16
        rel = _signed(value, bits)
        return f"{rel:+d}->0x{(next_code_offset + rel) & 0xFFFFFFFF:04X}"
    if typ == "byte":
        return f"0x{value:02X}"
    return f"0x{value:04X}" if value <= 0xFFFF else f"0x{value:08X}"


@dataclass
class U7UsecodeCallSite:
    function_id: int
    function_offset: int
    file_offset: int
    relative_offset: int
    code_offset: int
    intrinsic_id: int
    arg_count: int
    returns_value: bool
    raw: bytes
    intrinsic_name: str = ""


@dataclass
class U7UsecodeFunctionRecord:
    offset: int
    func_id: int
    func_size: int
    data_size: int
    num_args: int
    num_locals: int
    num_externs: int
    externs: list[int]
    ext32: bool
    code_offset: int
    code_size: int
    end_offset: int

    def iter_instructions(self, data: bytes) -> list[U7UsecodeInstruction]:
        instructions: list[U7UsecodeInstruction] = []
        pos = self.code_offset
        end = min(self.code_offset + self.code_size, len(data))
        while pos < end:
            inst = _decode_instruction(data, self.func_id, self.code_offset, pos, end)
            instructions.append(inst)
            pos += max(len(inst.raw), 1)
        return instructions


class U7UsecodeFile:
    """Parsed U7 USECODE file with function and bytecode helpers."""

    def __init__(self, data: bytes, functions: list[U7UsecodeFunctionRecord]) -> None:
        self.data = data
        self.functions = functions

    @classmethod
    def from_file(cls, filepath: str) -> "U7UsecodeFile":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7UsecodeFile":
        pos = 0
        functions: list[U7UsecodeFunctionRecord] = []
        while pos + 6 <= len(data):
            start = pos
            func_id = _u16(data, pos)
            pos += 2
            ext32 = func_id == 0xFFFF
            if ext32:
                if pos + 10 > len(data):
                    break
                func_id = _u16(data, pos)
                func_size = _u32(data, pos + 2)
                data_size = _u32(data, pos + 6)
                pos += 10
                end_offset = start + func_size + 10
            else:
                if pos + 4 > len(data):
                    break
                func_size = _u16(data, pos)
                data_size = _u16(data, pos + 2)
                pos += 4
                end_offset = start + func_size + 4
            if func_size <= 0 or end_offset > len(data):
                break

            code_header = pos + data_size
            if code_header + 6 > end_offset:
                break
            num_args = _u16(data, code_header)
            num_locals = _u16(data, code_header + 2)
            num_externs = _u16(data, code_header + 4)
            externs_pos = code_header + 6
            externs: list[int] = []
            for _ in range(num_externs):
                if externs_pos + 2 > end_offset:
                    break
                externs.append(_u16(data, externs_pos))
                externs_pos += 2
            code_offset = externs_pos
            code_size = max(0, end_offset - code_offset)
            functions.append(
                U7UsecodeFunctionRecord(
                    offset=start,
                    func_id=func_id,
                    func_size=func_size,
                    data_size=data_size,
                    num_args=num_args,
                    num_locals=num_locals,
                    num_externs=num_externs,
                    externs=externs,
                    ext32=ext32,
                    code_offset=code_offset,
                    code_size=code_size,
                    end_offset=end_offset,
                )
            )
            pos = end_offset
        return cls(data, functions)

    def get_function(self, func_id: int) -> U7UsecodeFunctionRecord | None:
        for fn in self.functions:
            if fn.func_id == func_id:
                return fn
        return None

    def function_for_offset(self, file_offset: int) -> U7UsecodeFunctionRecord | None:
        for fn in self.functions:
            if fn.offset <= file_offset < fn.end_offset:
                return fn
        return None

    def iter_instructions(
        self,
        func_id: int | None = None,
    ) -> list[U7UsecodeInstruction]:
        functions = self.functions
        if func_id is not None:
            fn = self.get_function(func_id)
            functions = [fn] if fn else []
        result: list[U7UsecodeInstruction] = []
        for fn in functions:
            result.extend(fn.iter_instructions(self.data))
        return result

    def scan_intrinsic(
        self,
        intrinsic_id: int,
        intrinsic_names: dict[int, str] | None = None,
    ) -> list[U7UsecodeCallSite]:
        calls: list[U7UsecodeCallSite] = []
        names = intrinsic_names or {}
        for fn in self.functions:
            for inst in fn.iter_instructions(self.data):
                if inst.intrinsic_id != intrinsic_id:
                    continue
                calls.append(
                    U7UsecodeCallSite(
                        function_id=fn.func_id,
                        function_offset=fn.offset,
                        file_offset=inst.file_offset,
                        relative_offset=inst.file_offset - fn.offset,
                        code_offset=inst.code_offset,
                        intrinsic_id=intrinsic_id,
                        arg_count=inst.intrinsic_arg_count or 0,
                        returns_value=inst.returns_value,
                        raw=inst.raw,
                        intrinsic_name=names.get(intrinsic_id, ""),
                    )
                )
        return calls

    def scan_intrinsic_csv(
        self,
        intrinsic_id: int,
        intrinsic_names: dict[int, str] | None = None,
    ) -> str:
        rows: list[dict[str, object]] = [
            {
                "function_id": call.function_id,
                "function_id_hex": f"0x{call.function_id:04X}",
                "function_offset": call.function_offset,
                "function_offset_hex": f"0x{call.function_offset:08X}",
                "file_offset": call.file_offset,
                "file_offset_hex": f"0x{call.file_offset:08X}",
                "relative_offset": call.relative_offset,
                "relative_offset_hex": f"0x{call.relative_offset:04X}",
                "code_offset": call.code_offset,
                "code_offset_hex": f"0x{call.code_offset:04X}",
                "intrinsic_id": call.intrinsic_id,
                "intrinsic_id_hex": f"0x{call.intrinsic_id:04X}",
                "intrinsic_name": call.intrinsic_name,
                "arg_count": call.arg_count,
                "returns_value": int(call.returns_value),
                "opcode": "callis" if call.returns_value else "calli",
                "raw_hex": call.raw.hex(),
            }
            for call in self.scan_intrinsic(intrinsic_id, intrinsic_names)
        ]
        return _rows_to_csv(rows)

    def disassemble(
        self,
        func_id: int,
        intrinsic_names: dict[int, str] | None = None,
    ) -> str:
        fn = self.get_function(func_id)
        if fn is None:
            raise KeyError(f"Function 0x{func_id:04X} not found")
        lines = [
            f"Function 0x{fn.func_id:04X}",
            f"  file_offset: 0x{fn.offset:08X}",
            f"  function_size: 0x{fn.func_size:04X}",
            f"  data_size: 0x{fn.data_size:04X}",
            f"  args: {fn.num_args}",
            f"  locals: {fn.num_locals}",
            f"  externs: {fn.num_externs}",
            f"  code_offset: 0x{fn.code_offset - fn.offset:04X} relative, 0x{fn.code_offset:08X} file",
            "",
        ]
        lines.extend(
            inst.format_asm(intrinsic_names) for inst in fn.iter_instructions(self.data)
        )
        return "\n".join(lines)

    def disassemble_all(self, intrinsic_names: dict[int, str] | None = None) -> str:
        """Raw-disassemble every parsed function."""
        return "\n\n".join(
            self.disassemble(fn.func_id, intrinsic_names) for fn in self.functions
        )


def _decode_instruction(
    data: bytes,
    function_id: int,
    function_code_offset: int,
    pos: int,
    end: int,
) -> U7UsecodeInstruction:
    opcode = data[pos]
    mnemonic, operand_types = _OPCODE_INFO.get(opcode, ("db", ()))
    offset = pos + 1
    operands: list[int] = []
    truncated = False
    for operand_type in operand_types:
        width = _OPERAND_WIDTH[operand_type]
        if offset + width > end:
            truncated = True
            break
        raw_value = data[offset : offset + width]
        operands.append(int.from_bytes(raw_value, "little"))
        offset += width
    raw = data[pos:offset] if not truncated else data[pos:end]
    if truncated:
        offset = end
    return U7UsecodeInstruction(
        function_id=function_id,
        file_offset=pos,
        code_offset=pos - function_code_offset,
        opcode=opcode,
        mnemonic=mnemonic,
        operands=operands,
        operand_types=list(operand_types[: len(operands)]),
        raw=raw,
        truncated=truncated,
    )


def load_u7_intrinsic_names(filepath: str) -> dict[int, str]:
    """Load UCXT-style U7 intrinsic name data if available."""
    text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    result: dict[int, str] = {}
    for match in re.finditer(r"<0x([0-9A-Fa-f]+)>\s*([^<\r\n]+?)\s*</>", text):
        result[int(match.group(1), 16)] = match.group(2).strip()
    return result
