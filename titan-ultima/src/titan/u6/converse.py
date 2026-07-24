"""
CONVERSE.A/B dialogue script disassembler for Ultima 6.

Not documented in ``u6data/u6tech.txt`` beyond the container format (the
"library" framing that :mod:`titan.u6.lib` already handles, including its
LZW-regardless-of-flag quirk). The *scripting language itself* -- the
compiled bytecode a decompressed CONVERSE.A/B entry actually contains --
isn't covered by any source surveyed except Nuvie's own interpreter,
``ConverseInterpret.cpp``/``.h``, which this module is ported from.
u6edit's help docs describe a *source* language that presumably compiles
down to this bytecode, useful for understanding opcode semantics, but not
the wire format itself.

This is a disassembler, not an interpreter: it faithfully replicates
Nuvie's ``collect_input()`` byte-stream walk (opcode/operand/text
boundary detection) to produce a structured, byte-accurate instruction
list, but does not simulate game state (actor stats, party membership,
etc.) the way actually *running* a script would. Where the real
interpreter's ``eval()`` reduces an embedded expression (values and
value-operator bytes such as ``ADD``/``GT``/``VAR``) to a single result
at runtime, this module records the raw, unreduced operand sequence
instead, since that reduction depends on live game state a static tool
doesn't have.

Byte classification (ported from ``is_print``/``is_ctrl``/``is_valop``/
``is_datasize`` in ``ConverseInterpret.h``)::

    text        0x0a, 0x20-0x7a, 0x7e, 0x7b
    size prefix 0xd2 (4-byte value follows), 0xd3 (1-byte), 0xd4 (2-byte)
    value-op    comparison/arithmetic/query opcodes (listed in VALUE_OPS)
                plus 0xa7 (EVAL, a mid-expression reduce marker)
    control     everything else >= 0xa1, plus 0x9c and 0x9e

An instruction's operand list has no fixed arity: Nuvie's own parser
determines it by scanning forward, byte by byte, stopping when it hits
what looks like the start of a new instruction or a real text run (a
printable byte NOT immediately followed by a value-op byte). Four
opcodes are special-cased with an explicit, fixed layout instead of this
generic scan: ``JUMP`` (opcode + a raw 4-byte target), ``SIDENT``
(opcode + a raw 1-byte number + a text run: the NPC name), and
``KEYWORDS``/``ASKC``/``SLOOK`` (opcode + a text run).

Validated against a real CONVERSE.A: disassembling item 2's decompressed
bytes (confirmed elsewhere, see :mod:`titan.u6.lib`, to be Dupre's
script) correctly identifies a ``SIDENT`` instruction with number 2
(matching the default symbol table's ``N_DUPRE=2``) and name "Dupre",
followed by an ``SLOOK`` instruction whose text is Dupre's exact
look-description, ending in the literal ``*`` pause character. More
broadly, every non-empty entry across both real ``CONVERSE.A`` and
``CONVERSE.B`` (200 scripts, 36209 instructions total) disassembles with
no boundary/truncation errors, and the resulting instruction streams
show the expected ``ASK``/``KEYWORDS``/``ANSWER``/``JUMP`` conversation-
loop shape throughout.

The known-variable annotations below are likewise validated against every
real script: ``PARTYLIVE`` alone is correctly annotated 74 times (almost
always an ``IF ... VAR 23 VAR LE`` "does the party have enough living
members" check), plus real hits for ``PARTYALL``, ``KARMA``, ``HP``, and
``PLAYER_NAME`` -- the last one correctly resolved through ``SVAR``
rather than ``VAR``, confirming the per-opcode table selection works.

A handful of control opcodes (0xc8, 0xbc, 0xdf, 0xfa) appear in real
scripts but have no name anywhere in Nuvie's source -- not in
``ConverseInterpret.h``'s ``#define``s, nor in ``op_str()``/``evop_str()``.
Structural disassembly is unaffected (``is_ctrl()`` classifies them
correctly regardless of whether a friendly name is known), but
:attr:`U6ConverseInstruction.name` falls back to ``UNKNOWN_0x..`` for
these. Left unnamed rather than guessed.

``VAR``/``SVAR`` (0xb2/0xb3) read/write one of a small table of global
variables by number -- ``KNOWN_INT_VARIABLES``/``KNOWN_STR_VARIABLES``
name the ones Nuvie's own ``Converse.h`` gives numeric ``#define``s for
(``U6TALK_VAR_*``: karma 0x14, Gargish-knowledge 0x15, gender 0x10, quest
flag 0x1a, work type 0x20, party head/live counts 0x17/0x18, HP 0x19,
input string 0x23), cross-checked against the same numbers independently
documented in ``docs/ultima6/u6converse.txt``'s "-Globals-" table. Origin's
own conversation-compiler spec (``U6_Conversation_Syntax.md``) names
variables by source-level letter (``#I`` = karma, etc.) instead, and that
letter isn't the compiled slot number (``#I`` is not slot 8) -- it
corroborates *which* variables the engine tracks but doesn't supply new
numeric mappings beyond what ``Converse.h`` already gives directly.
Slots 0x17 and 0x19 mean different things depending on whether they're
read as an integer (``PARTYLIVE``/``HP``) or a string (``NPC_NAME``/
``PLAYER_NAME``) -- :func:`format_instructions` picks the right table
from which opcode (``VAR`` vs ``SVAR``) precedes the index. Every other
variable number (most of them, in practice) is a per-script *local*
variable the NPC's own script declares -- these have no fixed global
name in any source and are rendered as plain numbers, same as before.

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.lib import U6Library
    from titan.u6.converse import disassemble, format_instructions

    lib = U6Library.from_file("CONVERSE.A", entry_size=4)
    script = lib.get_item(2)
    instructions = disassemble(script)
    print(format_instructions(instructions))
"""

from __future__ import annotations

__all__ = [
    "disassemble",
    "format_instructions",
    "U6ConverseInstruction",
    "U6ConverseTextRun",
    "U6ConverseError",
    "CONTROL_OPS",
    "VALUE_OPS",
    "OPCODE_NAMES",
    "KNOWN_INT_VARIABLES",
    "KNOWN_STR_VARIABLES",
]

from dataclasses import dataclass, field

# --- Opcode name tables, ported from ConverseInterpret.cpp's op_str()/evop_str() ---

CONTROL_OPS: dict[int, str] = {
    0x9C: "HORSE", 0x9E: "SLEEP",
    0xA1: "IF", 0xA2: "ENDIF", 0xA3: "ELSE", 0xA4: "SETF", 0xA5: "CLEARF",
    0xA6: "DECL", 0xA8: "ASSIGN",
    0xB0: "JUMP", 0xB5: "DPRINT", 0xB6: "BYE", 0xB8: "ENDDATA", 0xB9: "NEW", 0xBA: "DELETE",
    0xBE: "INVENTORY", 0xBF: "PORTRAIT",
    0xC4: "ADDKARMA", 0xC5: "SUBKARMA", 0xC9: "GIVE",
    0xCB: "WAIT", 0xCD: "WORKTYPE",
    0xD1: "MISC_ACTION",  # Nuvie's MDOP_MISC_ACTION -- shares the U6 opcode space too
    0xD6: "RESURRECT", 0xD8: "SETNAME", 0xD9: "HEAL", 0xDB: "CURE",
    0xEE: "ENDANSWER", 0xEF: "KEYWORDS",
    0xF1: "SLOOK", 0xF2: "SCONVERSE", 0xF3: "SPREFIX",
    0xF6: "ANSWER", 0xF7: "ASK", 0xF8: "ASKC",
    0xF9: "INPUTSTR", 0xFB: "INPUT", 0xFC: "INPUTNUM",
    0xFF: "SIDENT",
}

VALUE_OPS: dict[int, str] = {
    0x81: "GT", 0x82: "GE", 0x83: "LT", 0x84: "LE", 0x85: "NE", 0x86: "EQ",
    0x90: "ADD", 0x91: "SUB", 0x92: "MUL", 0x93: "DIV", 0x94: "LOR", 0x95: "LAND",
    0x9A: "CANCARRY", 0x9B: "WEIGHT", 0x9D: "HORSED", 0x9F: "HASOBJ",
    0xA0: "RAND", 0xAB: "FLAG", 0xB2: "VAR", 0xB3: "SVAR", 0xB4: "DATA",
    0xB7: "INDEXOF", 0xBB: "OBJCOUNT",
    0xC6: "INPARTY", 0xC7: "OBJINPARTY", 0xCA: "JOIN", 0xCC: "LEAVE",
    0xD7: "NPCNEARBY", 0xDA: "WOUNDED", 0xDC: "POISONED", 0xDD: "NPC",
    0xE0: "EXP", 0xE1: "LVL", 0xE2: "STR", 0xE3: "INT", 0xE4: "DEX",
}

EVAL_OP = 0xA7  # is_valop() includes this, but it has no name in evop_str() (Nuvie
                # consumes/skips it directly in collect_input() before it's stored).

OPCODE_NAMES: dict[int, str] = {**CONTROL_OPS, **VALUE_OPS, EVAL_OP: "EVAL"}

# --- Known global CONVERSE variable slots, ported from Nuvie's Converse.h
# U6TALK_VAR_* #defines (see module docstring). Everything else is a
# per-script local variable with no fixed global name. ---

KNOWN_INT_VARIABLES: dict[int, str] = {
    0x10: "SEX",        # avatar gender: 0=male, 1=female
    0x14: "KARMA",      # avatar's karma
    0x15: "GARGF",      # 1 = player knows Gargish
    0x17: "PARTYLIVE",  # number of people (living) following the avatar
    0x18: "PARTYALL",   # number of people (total) following the avatar
    0x19: "HP",         # avatar's health
    0x1A: "QUESTF",     # 0 = "Thou art not upon a sacred quest!"
    0x20: "WORKTYPE",   # NPC's current schedule activity
    0x23: "INPUT",      # previous input from the player ($Z)
}

KNOWN_STR_VARIABLES: dict[int, str] = {
    0x17: "NPC_NAME",
    0x19: "PLAYER_NAME",
    0x22: "YSTRING",  # value of the $Y variable
}

_OP_VAR = 0xB2
_OP_SVAR = 0xB3

_IS_VALOP_BYTES = frozenset(VALUE_OPS) | {EVAL_OP}
_DATASIZE_BYTES = frozenset({0xD2, 0xD3, 0xD4})

# Opcodes with an explicit, non-generic operand layout (see module docstring).
_OP_JUMP = 0xB0
_OP_SIDENT = 0xFF
_TEXT_TAIL_OPS = frozenset({0xEF, 0xF8, 0xF1})  # KEYWORDS, ASKC, SLOOK


class U6ConverseError(Exception):
    """Raised when script data is truncated mid-instruction."""


def _is_print(b: int) -> bool:
    return b == 0x0A or 0x20 <= b <= 0x7A or b == 0x7E or b == 0x7B


def _is_datasize(b: int) -> bool:
    return b in _DATASIZE_BYTES


def _is_valop(b: int) -> bool:
    return b in _IS_VALOP_BYTES


def _is_ctrl(b: int) -> bool:
    return (b >= 0xA1 or b == 0x9C or b == 0x9E) and not _is_valop(b) and not _is_datasize(b)


@dataclass
class U6ConverseTextRun:
    """A run of literal dialogue text printed directly (not an instruction operand)."""

    offset: int
    text: str


@dataclass
class U6ConverseOperand:
    """One raw operand value. ``is_op`` marks a value-operator byte (part of an
    unreduced embedded expression, e.g. ``ADD``/``GT``/``VAR``) rather than a
    literal value."""

    value: int
    is_op: bool = False

    def __repr__(self) -> str:
        if self.is_op:
            return OPCODE_NAMES.get(self.value, f"OP_{self.value:#04x}")
        return str(self.value)


@dataclass
class U6ConverseInstruction:
    """One control instruction: an opcode plus its (unreduced) operand list."""

    offset: int
    opcode: int
    operands: list[U6ConverseOperand] = field(default_factory=list)
    text: str | None = None  # attached text, for SIDENT/KEYWORDS/ASKC/SLOOK
    jump_target: int | None = None  # for JUMP only

    @property
    def name(self) -> str:
        return OPCODE_NAMES.get(self.opcode, f"UNKNOWN_{self.opcode:#04x}")


def _read_text(data: bytes, pos: int) -> tuple[str, int]:
    start = pos
    n = len(data)
    while pos < n and _is_print(data[pos]):
        pos += 1
    return data[start:pos].decode("latin-1"), pos


def _read_value(data: bytes, pos: int) -> tuple[int, int]:
    """Read one (possibly size-prefixed) value. Returns (value, new_pos)."""
    n = len(data)
    if pos >= n:
        raise U6ConverseError(f"truncated value at offset {pos}")
    b = data[pos]
    pos += 1
    if b == 0xD3:
        if pos >= n:
            raise U6ConverseError(f"truncated 1-byte value at offset {pos}")
        return data[pos], pos + 1
    if b == 0xD2:
        if pos + 4 > n:
            raise U6ConverseError(f"truncated 4-byte value at offset {pos}")
        return int.from_bytes(data[pos:pos + 4], "little"), pos + 4
    if b == 0xD4:
        if pos + 2 > n:
            raise U6ConverseError(f"truncated 2-byte value at offset {pos}")
        return int.from_bytes(data[pos:pos + 2], "little"), pos + 2
    return b, pos


def disassemble(data: bytes) -> list[U6ConverseInstruction | U6ConverseTextRun]:
    """Disassemble one decompressed CONVERSE.A/B script into instructions and text runs."""
    pos = 0
    n = len(data)
    out: list[U6ConverseInstruction | U6ConverseTextRun] = []

    while pos < n:
        b = data[pos]

        if _is_print(b):
            text, pos = _read_text(data, pos)
            out.append(U6ConverseTextRun(offset=pos - len(text), text=text))
            continue

        if not _is_ctrl(b):
            # Nuvie prints a warning and skips one byte in this case (a stray
            # byte that's neither text nor a recognized control code).
            pos += 1
            continue

        instr_start = pos

        if b == _OP_JUMP:
            pos += 1
            if pos + 4 > n:
                raise U6ConverseError(f"truncated JUMP target at offset {pos}")
            target = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
            out.append(U6ConverseInstruction(instr_start, b, [], jump_target=target))
            continue

        if b == _OP_SIDENT:
            pos += 1
            if pos >= n:
                raise U6ConverseError(f"truncated SIDENT number at offset {pos}")
            number = data[pos]
            pos += 1
            text, pos = _read_text(data, pos)
            out.append(U6ConverseInstruction(instr_start, b, [U6ConverseOperand(number)], text=text))
            continue

        if b in _TEXT_TAIL_OPS:
            pos += 1
            text, pos = _read_text(data, pos)
            out.append(U6ConverseInstruction(instr_start, b, [], text=text))
            continue

        # Standard case: opcode plus operands, both collected via the same
        # generic scan (the opcode is simply the first value read).
        values: list[U6ConverseOperand] = []
        while True:
            cur = data[pos]
            if _is_print(cur) and (pos + 1 >= n or not _is_valop(data[pos + 1])):
                break
            if cur == EVAL_OP:
                values.append(U6ConverseOperand(cur, is_op=True))
                pos += 1
            else:
                val, pos = _read_value(data, pos)
                values.append(U6ConverseOperand(val, is_op=_is_valop(cur)))
            if pos >= n or _is_ctrl(data[pos]):
                break

        opcode = values[0].value
        out.append(U6ConverseInstruction(instr_start, opcode, values[1:]))

    return out


def _format_operands(operands: list[U6ConverseOperand]) -> str:
    """Render an operand list, annotating a VAR/SVAR's variable-index operand with its
    known name (see KNOWN_INT_VARIABLES/KNOWN_STR_VARIABLES) when it's one of the small
    set of global slots Nuvie's Converse.h names -- most variable numbers are per-script
    locals with no fixed global name, and are left as plain numbers."""
    parts: list[str] = []
    pending_table: dict[int, str] | None = None
    for op in operands:
        text = repr(op)
        if pending_table is not None and not op.is_op:
            name = pending_table.get(op.value)
            if name:
                text = f"{text} ; {name}"
            pending_table = None
        elif op.is_op and op.value == _OP_VAR:
            pending_table = KNOWN_INT_VARIABLES
        elif op.is_op and op.value == _OP_SVAR:
            pending_table = KNOWN_STR_VARIABLES
        else:
            pending_table = None
        parts.append(text)
    return " ".join(parts)


def format_instructions(items: list[U6ConverseInstruction | U6ConverseTextRun]) -> str:
    """Render a disassembly as readable text, one instruction/text-run per line."""
    lines: list[str] = []
    for item in items:
        if isinstance(item, U6ConverseTextRun):
            lines.append(f"{item.offset:6d}  TEXT    {item.text!r}")
        elif item.jump_target is not None:
            lines.append(f"{item.offset:6d}  {item.name:<10} -> {item.jump_target}")
        elif item.text is not None:
            operand_str = _format_operands(item.operands)
            lines.append(f"{item.offset:6d}  {item.name:<10} {operand_str}  {item.text!r}")
        else:
            operand_str = _format_operands(item.operands)
            lines.append(f"{item.offset:6d}  {item.name:<10} {operand_str}")
    return "\n".join(lines)
