"""MD dialogue, object names and book texts through the shared U6 readers.

TALK record 0 is build-script text, not NPC dialogue. Retail GAME.EXE's
overlay 92 identifies 0xdf as SET_YSTRING: evaluate and resolve an actor,
then select "you" for resolved actor 1 or the actor-name lookup otherwise.
The result goes into string variable 0x22 ($Y).
See reference/md/converse/md_converse_opcode_df_reference.md
and ../mddata/scripts/probe_md_opcode_df.py for the machine-code evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from titan.md.game_profile import MD_PROFILE
from titan.u6.converse import U6ConverseInstruction, U6ConverseTextRun, disassemble
from titan.u6.lib import U6Library
from titan.u6.look import U6ObjectNames

__all__ = [
    "MartianDialogue",
    "read_martian_dialogue",
    "read_martian_books",
    "read_martian_names",
    "martian_dialogue_report",
    "MartianConverseInstruction",
    "disassemble_martian_dialogue",
]

MD_OPCODE_NAMES = {0xDF: "SET_YSTRING"}


class MartianConverseInstruction(U6ConverseInstruction):
    """A shared-format instruction with opcode names verified for the MD dialect only."""

    @property
    def name(self) -> str:
        """Use MD opcode semantics without changing the context-free U6 opcode table."""
        return MD_OPCODE_NAMES.get(self.opcode, super().name)


def disassemble_martian_dialogue(
    data: bytes,
) -> list[U6ConverseInstruction | U6ConverseTextRun]:
    """Preserve shared decoding, byte offsets and operands while applying MD names."""
    return [
        MartianConverseInstruction(
            offset=item.offset,
            opcode=item.opcode,
            operands=item.operands,
            text=item.text,
            jump_target=item.jump_target,
        )
        if isinstance(item, U6ConverseInstruction)
        else item
        for item in disassemble(data)
    ]


def _open_martian_library(directory: str | Path, filename: str) -> U6Library:
    path = Path(directory) / filename
    data = path.read_bytes()
    if len(data) < 8 or int.from_bytes(data[:4], "little") != len(data):
        raise ValueError(f"Invalid Martian Dreams library size header: {path}")
    return U6Library(data, has_size_header=True)


@dataclass
class MartianDialogue:
    """One NPC script, retaining its library slot and unmodified SIDENT name."""

    item: int
    raw_name: str
    instructions: list[U6ConverseInstruction | U6ConverseTextRun]

    @property
    def display_name(self) -> str:
        """Replace dialogue name separators for display, retaining raw_name separately."""
        return self.raw_name.replace("_", " ").strip()


def read_martian_dialogue(
    directory: str | Path, item: int | None = None
) -> list[MartianDialogue]:
    """Disassemble NPC records from TALK.LZC; preserve unknown instructions and operands."""
    library = _open_martian_library(directory, "TALK.LZC")
    if item is not None and not 0 <= item < library.num_items:
        raise ValueError(
            f"Martian Dreams dialogue item must be 0-{library.num_items - 1}"
        )
    scripts = []
    for index in [item] if item is not None else range(library.num_items):
        data = library.get_item(index)
        if not data:
            continue
        instructions = disassemble_martian_dialogue(data)
        identities = [
            x
            for x in instructions
            if isinstance(x, U6ConverseInstruction) and x.name == "SIDENT"
        ]
        if not identities:
            if item is not None:
                raise ValueError(
                    f"Martian Dreams TALK record {index} is not an NPC script"
                )
            continue
        scripts.append(MartianDialogue(index, identities[0].text or "", instructions))
    return scripts


def martian_dialogue_report(directory: str | Path) -> dict:
    """Report NPC coverage and every unknown opcode location without inventing semantics."""
    scripts = read_martian_dialogue(directory)
    unknown = [
        {
            "item": script.item,
            "npc": script.display_name,
            "offset": inst.offset,
            "opcode": f"0x{inst.opcode:02x}",
            "operands": [repr(op) for op in inst.operands],
        }
        for script in scripts
        for inst in script.instructions
        if isinstance(inst, U6ConverseInstruction) and inst.name.startswith("UNKNOWN_")
    ]
    return {
        "npc_scripts": len(scripts),
        "instructions_and_text_runs": sum(len(s.instructions) for s in scripts),
        "unknown_opcodes": unknown,
        "non_npc_records_excluded": True,
        "note": "MD 0xdf is SET_YSTRING: resolved actor 1 selects 'you'; other actors use name lookup. Verified against retail GAME.EXE and bounded machine-code emulation.",
    }


def read_martian_names(directory: str | Path) -> U6ObjectNames:
    """Unwrap LOOK.LZC before parsing its range-based object names."""
    return U6ObjectNames.parse(MD_PROFILE.read_resource(directory, "LOOK.LZC"))


def read_martian_books(directory: str | Path) -> list[str]:
    """Read MD's 32-bit MDTEXT.LZC text library, preserving page and line markers."""
    library = _open_martian_library(directory, "MDTEXT.LZC")
    return [
        library.get_item(i).split(b"\0", 1)[0].decode("latin-1")
        for i in range(library.num_items)
    ]
