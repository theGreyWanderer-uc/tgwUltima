"""
``static/triggers.flx`` reader for Ultima 9: Ascension.

U9's trigger scripts. Each FLX entry is one trigger, and **the entry index
is the trigger ID**. A world object names the triggers it runs in two
extra-data values -- tag 62 for phases 0 and 1, tag 59 for phases 2 and 3, one
16-bit ID per half (:meth:`titan.u9.nonfixed.U9Nonfixed.entity_triggers`).

A trigger body is a flat list of 6-byte records, terminated by a record
whose opcode is ``0xFF``::

    0x00  opcode   u8
    0x01  arg0     u8
    0x02  arg1     u16
    0x04  arg2     u16

Records after the terminator are slack -- an FLX entry keeps whatever
length it was allocated, so a trigger that shrank leaves stale records
behind. 361 entries are *empty* triggers whose first record is already the
terminator, several of those with slack after it. The semantic instruction
stream stops at the first ``0xFF``, but the terminator, slack records and
entry-relative byte offsets are retained for binary research and exact
round trips.

The executable accepts a contiguous command catalogue from ``0x00`` through
``0x64``. The shipped archive uses 90 of those 101 commands. Operands are
decoded by :mod:`titan.u9.trigger_operands` and exposed on each record as
read-only views over the stored words: :attr:`U9TriggerRecord.target_selection`
(for commands using the shared object search, ``arg0`` selects a link relative
to the executor's current link context and ``arg1`` an object type),
:attr:`U9TriggerRecord.branch` (branch labels and comparisons in ``arg2``) and
:attr:`U9TriggerRecord.parameters` (the remaining ``arg2`` fields, all layouts
graded ``retail_confirmed`` in 1.19F).

Opcode ``0x31`` runs an NPC activity record:
``arg1`` is an activity set index in :mod:`titan.u9.activity` (also the NPC's
index in ``runtime/NPC.FLX``) and ``arg2``'s **low byte** is a record
``ordinal`` within that set. That pair names a record which actually exists
in 500 of the archive's 506 ``0x31`` steps (98.8%); reading ``arg2`` whole
scores 96.0%, which is what exposed the high byte as a separate field. No
other opcode with 20 or more steps passes the same test above 51.6%.

Verified against patched v1.19H (242,476 bytes, 10,000 entries, 6,712 used)
and default GOG 1.19F (242,818 bytes, 6,708 used): every used entry's length
is a multiple of 6. The versions have 6,710 and 6,706 terminated entries
respectively (99.97% in each).

The two that do not -- trigger IDs 58 and 631 -- are shipped unterminated
entries. Retail 1.19F requests 510 bytes from an entry's file offset without
clamping to its directory length; the interpreter tests ``0xFF`` and does
not test the entry boundary. In both archives, 58's read includes 59's
projectile instruction and terminator; 631's includes 632's hide/show
instructions and terminator. The earlier entry-end stopping hypothesis was
disproved by the retail loader trace (G-TRG-2).

Titan parses only the directory-owned bytes and preserves each entry exactly.
It does not merge these neighboring programs or insert an end marker.
``U9Trigger.terminated`` describes an on-disk terminator, not the end of the
retail read window. Structural validity alone does not establish a trigger's
runtime behavior; changing physical adjacency can change that behavior.

The terminator's ``arg0`` is ``0x10`` in 6,711 cases and ``0x00`` in one,
so the whole word is ``0x10FF`` almost everywhere -- but the opcode byte is
what actually ends the list, and matching on the byte rather than the word
is what recovers trigger 7318.

Cross-checked against world data: across the 1.19F ``nonfixed`` regions,
94-99% of the non-zero trigger IDs in entities' extra-data tags 62 and 59 name
a *used* entry here, where a random value would match about 10%. (An earlier
reading took the entity word at ``+0x1A`` for a trigger ID; it is the object's
link, and the navigation-point IDs of :mod:`titan.u9.highway` are values of
that link, not trigger IDs.)

Example::

    from titan.u9.triggers import U9Triggers

    triggers = U9Triggers.from_file("static/triggers.flx")
    trigger = triggers.trigger(308)
    for record in trigger.records:
        print(hex(record.opcode), record.arg0, record.arg1, record.arg2)
"""

from __future__ import annotations

__all__ = [
    "TRIGGER_OPCODE_CATALOGUE",
    "TRIGGER_PHASE_MEANINGS",
    "TRIGGER_SPECIAL_ACTION_CATALOGUE",
    "U9MapTransition",
    "U9TriggerOpcodeInfo",
    "U9TriggerSpecialActionInfo",
    "U9Trigger",
    "U9TriggerRecord",
    "U9Triggers",
    "U9TriggersError",
    "trigger_opcode_info",
    "trigger_special_action_info",
]

import os
import struct
from collections import Counter
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.trigger_operands import (
    U9TriggerBranch,
    U9TriggerParameters,
    U9TriggerTarget,
    branch,
    parameters,
    target_selection,
)

RECORD_SIZE = 6
RECORD_STRUCT = "<BBHH"
TERMINATOR_OPCODE = 0xFF

# Retail caller contexts establish these roles; phases 0/1 also cover volume
# entry/exit and effect start/end, rather than one universal input event.
TRIGGER_PHASE_MEANINGS = ("activation", "deactivation", "completion", "failure")


@dataclass(frozen=True)
class U9TriggerSpecialActionInfo:
    """Independent wording for one retail 1.19F special-action slot.

    This describes the code path, without promising a visible outcome when its
    required NPC, temporary camera or other game state is missing.
    """

    action: int
    meaning: str
    evidence: str = "retail_confirmed"


TRIGGER_SPECIAL_ACTION_CATALOGUE = tuple(
    U9TriggerSpecialActionInfo(action, meaning)
    for action, meaning in enumerate(
        (
            "begin shrine cleansing",
            "refresh world lighting",
            "set camera roll to 180 degrees",
            "reset camera roll",
            "attach red light to target",
            "attach white light to target",
            "attach blue light to target",
            "remove target light",
            "request Avatar combat mode",
            "reserved no-op",
            "reserved no-op",
            "reserved no-op",
            "move Avatar inventory to NPC 9 and disable selected UI elements",
            "drop marked NPC 9 inventory near Avatar and restore UI",
            "delete Avatar contents except types 4881 and 5737",
            "position Avatar for sleeping",
            "wake Avatar from sleeping or sitting",
            "rebuild base UI and set Avatar health to zero",
            "attach effect preset 1010 mode 5 to temporary camera",
            "remove temporary camera and restore its saved control state",
            "initialize Avatar attributes from datum 480",
            "suppress weather collision checks and stop script during conversation",
            "send NPC 185 support message 7 and reposition Avatar at hardpoint 133",
            "enable NPC 9 and 185 map transfer",
        )
    )
)


def trigger_special_action_info(action: int) -> U9TriggerSpecialActionInfo | None:
    """Special-action slot 0..23, else ``None`` (retail ignores other values)."""
    if 0 <= action < len(TRIGGER_SPECIAL_ACTION_CATALOGUE):
        return TRIGGER_SPECIAL_ACTION_CATALOGUE[action]
    return None


@dataclass(frozen=True)
class U9TriggerOpcodeInfo:
    """Titan's source-independent description of one trigger command."""

    opcode: int
    meaning: str
    evidence: str
    observed_in_retail_archive: bool


_UNOBSERVED_RETAIL_OPCODES = frozenset(
    {0x04, 0x12, 0x21, 0x23, 0x27, 0x47, 0x53, 0x5E, 0x5F, 0x61, 0x62}
)

_OPCODE_MEANINGS = (
    "do nothing",
    "invoke object behavior",
    "assign object link",
    "write object property",
    "replace object kind",
    "replace visual state",
    "enable object status bits",
    "disable object status bits",
    "invert object status bits",
    "hide object",
    "show object",
    "delete object",
    "spawn object",
    "write shared datum",
    "branch on shared datum",
    "create disappearance effect",
    "remove disappearance effect",
    "select targets by link",
    "select targets by relative link",
    "make trigger one-shot",
    "include the triggering object",
    "branch on target count",
    "mark branch destination",
    "branch unconditionally",
    "assign local value",
    "adjust local value",
    "branch on local value",
    "move objects over time",
    "relocate objects instantly",
    "face objects toward target",
    "launch objects",
    "transition between maps",
    "play one-shot sound",
    "choose a random target",
    "rotate objects about the vertical axis",
    "reserved target command",
    "rotate objects about the lateral axis",
    "rotate objects about the longitudinal axis",
    "begin looping sound",
    "assign a random local value",
    "activate other triggers",
    "test object status bits",
    "launch a projectile",
    "halt object movement",
    "set target search radius",
    "branch on use-state count",
    "move objects by repeated coordinate steps",
    "branch on source link",
    "play speech",
    "choose NPC activity record",
    "end looping sound",
    "play an audio sample",
    "alert nearby monsters",
    "begin music",
    "end music",
    "play a movie",
    "float an object",
    "follow a sequence of linked markers",
    "branch on game time",
    "test all object status bits",
    "set storm state",
    "run a special action",
    "manage avatar equipment",
    "set or advance the clock",
    "assign NPC activity",
    "set object opacity",
    "set object scale",
    "adjust object opacity",
    "adjust object scale",
    "branch on object opacity",
    "branch on X scale",
    "branch on Y scale",
    "branch on Z scale",
    "invoke a spell",
    "register a chunk crossing",
    "branch on avatar inventory",
    "begin an audio sample",
    "end an audio sample",
    "tint an object",
    "branch when an object lacks a tint",
    "damage an object",
    "choose combat behavior",
    "set or adjust avatar mana",
    "branch on avatar mana",
    "move objects quickly by repeated coordinate steps",
    "order an NPC attack",
    "turn an NPC toward a target",
    "adjust an object link",
    "branch on interface state",
    "invoke the alternate spell action",
    "branch on hit points",
    "branch on quest datum",
    "configure the trigger camera",
    "set combat mode and mortality",
    "lock or unlock avatar controls",
    "adjust avatar mana",
    "begin or end breath tracking",
    "branch on an avatar attribute",
    "modify an avatar attribute",
    "fade the display",
    "branch on demo mode",
)


def _opcode_evidence(opcode: int) -> str:
    if opcode in (0x1B, 0x1F, 0x23, 0x2E, 0x39, 0x3D, 0x52, 0x53, 0x54):
        return "retail_runtime_confirmed"
    if opcode == 0x31:
        return "retail_archive_confirmed"
    return "implementation_correlated"


TRIGGER_OPCODE_CATALOGUE = tuple(
    U9TriggerOpcodeInfo(
        opcode=opcode,
        meaning=meaning,
        evidence=_opcode_evidence(opcode),
        observed_in_retail_archive=opcode not in _UNOBSERVED_RETAIL_OPCODES,
    )
    for opcode, meaning in enumerate(_OPCODE_MEANINGS)
)
_OPCODE_INFO_BY_VALUE = {info.opcode: info for info in TRIGGER_OPCODE_CATALOGUE}
_TERMINATOR_INFO = U9TriggerOpcodeInfo(
    opcode=TERMINATOR_OPCODE,
    meaning="end instruction stream",
    evidence="retail_runtime_confirmed",
    observed_in_retail_archive=True,
)


def trigger_opcode_info(opcode: int) -> U9TriggerOpcodeInfo | None:
    """Return Titan's meaning for ``opcode``, if the runtime defines it."""
    if opcode == TERMINATOR_OPCODE:
        return _TERMINATOR_INFO
    return _OPCODE_INFO_BY_VALUE.get(opcode)


@dataclass(frozen=True)
class U9MapTransition:
    """Decoded operands for command ``0x1F`` without altering stored words."""

    destination_link_delta: int | None
    unclassified_flag_bits: int
    map_number: int
    effect_variant: int
    retain_running_tasks: bool
    relative_position: bool
    unclassified_parameter_bits: int


class U9TriggersError(Exception):
    """Raised on malformed ``static/triggers.flx`` data."""


@dataclass(frozen=True)
class U9TriggerRecord:
    """One 6-byte trigger instruction.

    Command names cover the executable's complete ``0x00`` through ``0x64``
    catalogue. All 101 retail operand layouts receive typed views;
    all four stored fields remain available regardless.
    """

    opcode: int
    arg0: int
    arg1: int
    arg2: int
    entry_offset: int = 0

    @property
    def is_terminator(self) -> bool:
        return self.opcode == TERMINATOR_OPCODE

    @property
    def opcode_info(self) -> U9TriggerOpcodeInfo | None:
        """Known command meaning and its evidence level, if defined."""
        return trigger_opcode_info(self.opcode)

    @property
    def semantic_name(self) -> str:
        """Readable command name, retaining unknown values numerically."""
        info = self.opcode_info
        return (
            info.meaning if info is not None else f"unknown opcode 0x{self.opcode:02X}"
        )

    @property
    def arg2_low(self) -> int:
        """Low byte of ``arg2``; the activity ordinal for opcode ``0x31``."""
        return self.arg2 & 0xFF

    @property
    def arg2_high(self) -> int:
        """High byte of ``arg2``, kept separate during opcode research."""
        return self.arg2 >> 8

    @property
    def activity_reference(self) -> tuple[int, int] | None:
        """Known ``(activity_id, ordinal)`` reference, or ``None``."""
        if self.opcode != 0x31:
            return None
        return self.arg1, self.arg2_low

    @property
    def map_transition(self) -> U9MapTransition | None:
        """Typed map-transition operands for command ``0x1F``.

        A zero selector uses the firing object's link unchanged. Nonzero
        selectors encode a signed delta around 16. Map zero means the current
        map. Unknown parameter bits are retained explicitly.
        """
        if self.opcode != 0x1F:
            return None
        link_selector = self.arg0 & 0x1F
        link_delta = None if link_selector == 0 else link_selector - 16
        classified_mask = 0x00FF | 0x0300 | 0x4000 | 0x8000
        return U9MapTransition(
            destination_link_delta=link_delta,
            unclassified_flag_bits=self.arg0 & ~0x1F,
            map_number=self.arg2_low,
            effect_variant=(self.arg2 >> 8) & 0x03,
            retain_running_tasks=bool(self.arg2 & 0x4000),
            relative_position=bool(self.arg2 & 0x8000),
            unclassified_parameter_bits=self.arg2 & ~classified_mask,
        )

    @property
    def target_selection(self) -> U9TriggerTarget | None:
        """Link and object-type search for a targeted command, else ``None``."""
        return target_selection(self.opcode, self.arg0, self.arg1)

    @property
    def branch(self) -> U9TriggerBranch | None:
        """Branch label and comparison in ``arg2``, for branching commands."""
        return branch(self.opcode, self.arg2)

    @property
    def parameters(self) -> U9TriggerParameters | None:
        """Named ``arg2`` fields and leftover bits, for catalogued commands."""
        return parameters(self.opcode, self.arg2)

    @property
    def search_radius(self) -> int | None:
        """World-unit search half-extent set by 0x2C, else ``None``.

        Bit 15 selects absolute units; otherwise the value is multiplied by
        128. Either encoding of zero restores the default of 1,280 units.
        """
        if self.opcode != 0x2C:
            return None
        value = self.arg2 & 0x7FFF
        return (value if self.arg2 & 0x8000 else value * 128) or 1280

    @property
    def special_action_info(self) -> U9TriggerSpecialActionInfo | None:
        """Retail special-action meaning for 0x3D, else ``None``."""
        if self.opcode != 0x3D:
            return None
        return trigger_special_action_info(self.arg2)

    @property
    def movement_duration_ms(self) -> int | None:
        """0x1B duration in milliseconds; encoded zero selects 500 ms."""
        if self.opcode != 0x1B:
            return None
        return 500 * max(self.arg2 & 0x1F, 1)

    def to_bytes(self) -> bytes:
        """Encode this instruction in its exact six-byte disk layout."""
        return struct.pack(RECORD_STRUCT, self.opcode, self.arg0, self.arg1, self.arg2)


@dataclass(frozen=True)
class U9Trigger:
    """One trigger script, keyed by its FLX entry index."""

    trigger_id: int
    records: tuple[U9TriggerRecord, ...]
    slack_records: int
    terminated: bool
    terminator: U9TriggerRecord | None = None
    slack: tuple[U9TriggerRecord, ...] = ()
    raw_data: bytes = b""

    @property
    def is_empty(self) -> bool:
        """True when the trigger's body is empty -- the terminator came first."""
        return not self.records

    @property
    def opcodes(self) -> list[int]:
        return [r.opcode for r in self.records]

    @property
    def all_records(self) -> tuple[U9TriggerRecord, ...]:
        """Body, terminator, and stale records in their original order."""
        if self.terminator is None:
            return self.records
        return self.records + (self.terminator,) + self.slack

    def unresolved_branch_labels(self) -> list[tuple[int, int]]:
        """``(record index, label)`` for branches to a label this trigger lacks.

        The executor looks for a ``0x16`` label instruction with that number;
        finding none, it ends the script -- the same outcome as label 0.
        """
        labels = {record.arg2 for record in self.records if record.opcode == 0x16}
        unresolved = []
        for index, record in enumerate(self.records):
            view = record.branch
            if view is not None and view.form != "label" and view.label:
                if view.label not in labels:
                    unresolved.append((index, view.label))
        return unresolved

    def to_bytes(self) -> bytes:
        """Return the complete original FLX-entry payload byte for byte."""
        if self.raw_data:
            return self.raw_data
        return b"".join(record.to_bytes() for record in self.all_records)


class U9Triggers:
    """Reader for ``static/triggers.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self._archive = archive

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Triggers:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as e:
            raise U9TriggersError(f"not a readable FLX archive: {e}") from e

    @property
    def num_entries(self) -> int:
        return self._archive.num_entries

    def used_trigger_ids(self) -> list[int]:
        """Trigger IDs whose FLX slot holds data."""
        return self._archive.used_entry_indices()

    def trigger(self, trigger_id: int) -> U9Trigger | None:
        """One trigger by ID, or ``None`` if that slot is unused."""
        if trigger_id < 0 or trigger_id >= self.num_entries:
            raise U9TriggersError(
                f"trigger ID {trigger_id} out of range (0..{self.num_entries - 1})"
            )
        blob = self._archive.read_entry(trigger_id)
        if not blob:
            return None
        if len(blob) % RECORD_SIZE:
            raise U9TriggersError(
                f"trigger {trigger_id}: {len(blob)} bytes is not a whole number "
                f"of {RECORD_SIZE}-byte records"
            )

        records: list[U9TriggerRecord] = []
        terminated = False
        count = len(blob) // RECORD_SIZE
        for index in range(count):
            offset = index * RECORD_SIZE
            fields = struct.unpack_from(RECORD_STRUCT, blob, offset)
            record = U9TriggerRecord(
                opcode=fields[0],
                arg0=fields[1],
                arg1=fields[2],
                arg2=fields[3],
                entry_offset=offset,
            )
            if record.is_terminator:
                terminated = True
                slack_records = []
                for slack_offset in range(offset + RECORD_SIZE, len(blob), RECORD_SIZE):
                    slack_fields = struct.unpack_from(RECORD_STRUCT, blob, slack_offset)
                    slack_records.append(
                        U9TriggerRecord(
                            opcode=slack_fields[0],
                            arg0=slack_fields[1],
                            arg1=slack_fields[2],
                            arg2=slack_fields[3],
                            entry_offset=slack_offset,
                        )
                    )
                slack = tuple(slack_records)
                return U9Trigger(
                    trigger_id=trigger_id,
                    records=tuple(records),
                    slack_records=len(slack),
                    terminated=True,
                    terminator=record,
                    slack=slack,
                    raw_data=blob,
                )
            records.append(record)
        return U9Trigger(
            trigger_id=trigger_id,
            records=tuple(records),
            slack_records=0,
            terminated=terminated,
            raw_data=blob,
        )

    def triggers(self) -> list[U9Trigger]:
        """Every used trigger, in ID order."""
        result = []
        for trigger_id in self.used_trigger_ids():
            trigger = self.trigger(trigger_id)
            if trigger is not None:
                result.append(trigger)
        return result

    def opcode_histogram(self) -> Counter[int]:
        """How often each opcode appears across every trigger body.

        Terminators are excluded -- this counts the instructions, not the
        end markers.
        """
        histogram: Counter[int] = Counter()
        for trigger in self.triggers():
            histogram.update(trigger.opcodes)
        return histogram

    def unresolved_branch_labels(self) -> dict[int, list[tuple[int, int]]]:
        """Per trigger ID, branches whose label the trigger does not contain."""
        found = {}
        for trigger in self.triggers():
            unresolved = trigger.unresolved_branch_labels()
            if unresolved:
                found[trigger.trigger_id] = unresolved
        return found

    def unterminated_trigger_ids(self) -> list[int]:
        """Entries without an on-disk ``0xFF`` record (shipped IDs 58 and 631).

        Retail 1.19F reads across entry boundaries; these IDs are a structural
        diagnostic, not a claim that the game stops at the entry's end.
        """
        return [t.trigger_id for t in self.triggers() if not t.terminated]
