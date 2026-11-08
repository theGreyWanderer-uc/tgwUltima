"""Usecode symbols/classes, bounded reference analysis and base/patch/original lookup."""

from __future__ import annotations

from dataclasses import dataclass, field

from titan.u7.usecode import (
    U7UsecodeFile,
    U7UsecodeFunctionRecord,
    U7UsecodeInstruction,
    _MAX_SYMBOL_SCOPE_DEPTH,
    _UCSYMTBL_MAGIC,
    _require_bytes,
    _signed,
    _u16,
    _u32,
)


@dataclass(frozen=True)
class U7UsecodeSymbol:
    """A symbol preserves its kind/value, class scope, method IDs and shape binding."""

    name: str
    name_raw_hex: str
    kind: int
    value: int
    offset: int
    children: tuple[U7UsecodeSymbol, ...] = ()
    methods: tuple[int, ...] = ()
    variable_count: int | None = None
    shape: int | None = None
    scope_version: int = 0


def read_usecode_symbol_scope(
    data: bytes, pos: int, depth: int = 0
) -> tuple[tuple[U7UsecodeSymbol, ...], int]:
    """Parse one bounded symbol scope; return the exact function-stream boundary."""
    if depth >= _MAX_SYMBOL_SCOPE_DEPTH:
        raise ValueError(
            f"U7 USECODE symbol-table nesting exceeds {_MAX_SYMBOL_SCOPE_DEPTH} scopes"
        )
    _require_bytes(data, pos, 8, "symbol-table scope header")
    count, version = _u32(data, pos), _u32(data, pos + 4)
    pos += 8
    symbols = []
    for _ in range(count):
        start = pos
        end = data.find(b"\0", pos)
        if end < 0:
            raise ValueError(
                f"Unterminated U7 USECODE symbol name at file offset 0x{pos:X}"
            )
        name = data[pos:end]
        pos = end + 1
        _require_bytes(data, pos, 6, "symbol record")
        kind, value = _u16(data, pos), _u32(data, pos + 2)
        pos += 6
        children: tuple[U7UsecodeSymbol, ...] = ()
        methods: tuple[int, ...] = ()
        variables: int | None = None
        shape: int | None = None
        if kind == 4:
            children, pos = read_usecode_symbol_scope(data, pos, depth + 1)
            _require_bytes(data, pos, 2, "class method count")
            method_count = _u16(data, pos)
            pos += 2
            _require_bytes(data, pos, method_count * 2 + 2, "class metadata")
            methods = tuple(_u16(data, pos + i * 2) for i in range(method_count))
            pos += method_count * 2
            variables = _u16(data, pos)
            pos += 2
        elif kind == 6:
            _require_bytes(data, pos, 4, "shape-function metadata")
            shape = _u32(data, pos)
            pos += 4
        symbols.append(
            U7UsecodeSymbol(
                name.decode("latin-1"),
                name.hex(),
                kind,
                value,
                start,
                children,
                methods,
                variables,
                shape,
                version,
            )
        )
    return tuple(symbols), pos


def read_usecode_symbols(data: bytes) -> tuple[U7UsecodeSymbol, ...]:
    """Return an empty collection when no symbol prefix exists, without guessing symbol names."""
    return (
        read_usecode_symbol_scope(data, len(_UCSYMTBL_MAGIC))[0]
        if data.startswith(_UCSYMTBL_MAGIC)
        else ()
    )


@dataclass(frozen=True)
class U7UsecodeDiagnostic:
    """A structural instruction/reference issue; it is not a VM execution result."""

    function: int
    file_offset: int
    message: str


def annotate_usecode_instruction(
    stream: U7UsecodeFile,
    function: U7UsecodeFunctionRecord,
    instruction: U7UsecodeInstruction,
) -> list[str]:
    """Resolve branch/data/extern references and signed constants without replacing raw operands."""
    notes = []
    for value, kind in zip(instruction.operands, instruction.operand_types):
        if kind in ("offset", "offset32"):
            delta = _signed(value, 32 if kind == "offset32" else 16)
            notes.append(
                f"target={instruction.code_offset + len(instruction.raw) + delta:+d}"
            )
        elif kind == "extern":
            notes.append(
                f"function=0x{function.externs[value]:X}"
                if value < len(function.externs)
                else "invalid extern index"
            )
        elif kind in ("data", "data32"):
            if value < function.data_size:
                start = function.data_offset + value
                end = stream.data.find(
                    b"\0", start, function.data_offset + function.data_size
                )
                notes.append(
                    f"data[{value}]={stream.data[start : end if end >= 0 else function.data_offset + function.data_size]!r}"
                )
            else:
                notes.append("invalid data offset")
        elif instruction.opcode in (0x1F, 0x9F):
            notes.append(
                f"signed={_signed(value, 32 if instruction.opcode == 0x9F else 16)}"
            )
        elif kind == "var" and instruction.opcode in (
            0x50,
            0x51,
            0x5A,
            0x5B,
            0x5C,
            0xDC,
        ):
            signed = _signed(value, 16)
            notes.append(
                f"{'global' if signed < 0 else 'function'} static[{abs(signed)}]"
            )
    return notes


def validate_usecode_function(
    stream: U7UsecodeFile, function: U7UsecodeFunctionRecord
) -> list[U7UsecodeDiagnostic]:
    """Validate branch instruction boundaries and data/extern bounds without simulating the stack."""
    instructions = function.iter_instructions(stream.data)
    starts = {inst.code_offset for inst in instructions}
    issues: list[U7UsecodeDiagnostic] = []
    for inst in instructions:
        messages = []
        if inst.truncated:
            messages.append("truncated instruction")
        if inst.mnemonic == "db":
            messages.append(f"unknown opcode 0x{inst.opcode:02X}")
        for value, kind in zip(inst.operands, inst.operand_types):
            if kind in ("offset", "offset32"):
                target = (
                    inst.code_offset
                    + len(inst.raw)
                    + _signed(value, 32 if kind == "offset32" else 16)
                )
                if target not in starts:
                    messages.append(
                        f"branch target {target} is not an instruction boundary"
                    )
            elif kind == "extern" and value >= len(function.externs):
                messages.append(
                    f"extern index {value} exceeds {len(function.externs)} entries"
                )
            elif kind in ("data", "data32") and value >= function.data_size:
                messages.append(
                    f"data offset {value} exceeds {function.data_size} bytes"
                )
        issues.extend(
            U7UsecodeDiagnostic(function.func_id, inst.file_offset, message)
            for message in messages
        )
    return issues


@dataclass(frozen=True)
class U7UsecodeDefinition:
    """Bind a raw function record to its source stream so local offsets remain meaningful."""

    stream: U7UsecodeFile
    record: U7UsecodeFunctionRecord
    source: str = ""

    def disassemble(
        self, *, annotate: bool = False, intrinsic_names: dict[int, str] | None = None
    ) -> str:
        if not annotate:
            return self.stream.disassemble_record(self.record, intrinsic_names)
        lines = [f"Function 0x{self.record.func_id:X}; source={self.source}"]
        for inst in self.record.iter_instructions(self.stream.data):
            notes = annotate_usecode_instruction(self.stream, self.record, inst)
            lines.append(
                inst.format_asm(intrinsic_names)
                + (" ; " + "; ".join(notes) if notes else "")
            )
        return "\n".join(lines)


@dataclass
class U7UsecodeWorld:
    """Last-definition lookup with callo bound to the original base, not a superseded patch."""

    definitions: dict[int, U7UsecodeDefinition] = field(default_factory=dict)
    originals: dict[int, U7UsecodeDefinition] = field(default_factory=dict)
    symbols: tuple[U7UsecodeSymbol, ...] = ()
    history: dict[int, list[U7UsecodeDefinition]] = field(default_factory=dict)

    @property
    def symbol_values(self) -> dict[str, int]:
        """Expose root-scope name lookup used by Exult's named actor bindings."""
        return {symbol.name: symbol.value for symbol in self.symbols}

    def add_stream(
        self, stream: U7UsecodeFile, *, source: str = "", patch: bool = False
    ) -> None:
        if stream.data.startswith(_UCSYMTBL_MAGIC):
            self.symbols = read_usecode_symbols(stream.data)
        for record in stream.functions:
            previous = self.definitions.get(record.func_id)
            if patch and previous is not None:
                self.originals.setdefault(record.func_id, previous)
            elif not patch:
                self.originals.pop(record.func_id, None)
            definition = U7UsecodeDefinition(stream, record, source)
            self.history.setdefault(record.func_id, []).append(definition)
            self.definitions[record.func_id] = definition

    def get_function(
        self, function_id: int, *, original: bool = False
    ) -> U7UsecodeDefinition | None:
        return (self.originals if original else self.definitions).get(function_id)
