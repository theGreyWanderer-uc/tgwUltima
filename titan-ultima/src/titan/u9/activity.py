"""
``static/activity.flx`` reader for Ultima 9: Ascension.

U9's NPC activity sequences -- the named behaviour scripts an NPC runs, with
names like ``Sequence 1``, ``Stand``, ``Loiter``, ``After Yew`` and
``walking in hse``. One FLX entry holds one activity set::

    0x00  record_count    u32
    0x04  payload_length  u32  -- always the entry length minus this 8-byte header
    0x08  records         record_count records, back to back

Each record is self-delimiting::

    0x00  ordinal    u8
    0x01  name       char[15]  -- NUL-terminated, fixed width
    0x10  steps      9 bytes each, until and including a step whose opcode is 0xFF

and each step is::

    0x00  opcode             u8
    0x01  parameter_0        u16
    0x03  parameter_1        u16
    0x05  scheduled_minute   u16
    0x07  duration_code      u16

All integers are little-endian.

Three things about this layout are easy to get wrong, and each was arrived
at by testing rather than assumption:

* **The name field is fixed width.** Record sizes cluster at 25, 34, 43, 52
  and 79 bytes *regardless of name length*, which only happens if the name
  occupies a fixed field. The longest name in the archive is 14 characters,
  fitting ``char[15]`` with its terminator. Everything past the NUL is
  uninitialised memory, not data -- usually MSVC's ``0xCD`` heap fill,
  sometimes stale text (one record's padding still reads ``me`` behind
  ``Idle``). Do not read it, and do not mistake it for a type tag: the byte
  after the NUL takes values ``0x00``, ``0xCD``, ``0x65`` and ``0x63``
  scattered across every name class with no correlation to the name.
* **A record's extent is local**, not implied by its name's semantics.
  Those clustered sizes differ by multiples of 9: the name field is
  followed by a list of 9-byte steps ending at a ``0xFF`` step, the same
  shape :mod:`titan.u9.triggers` uses.
* **``ordinal`` is a label, not a counter.** It is 1-based in 209 of 214
  entries, starts at 2 in five of them, and is outright gapped in three.
  Validating it as ``1..record_count`` rejects eight perfectly good
  entries, so this reader reads it and does not constrain it.

Verified against v1.19H ``static/activity.flx`` (29,522 bytes, 352 FLX slots,
214 used): **all 214 entries parse with their bodies consumed exactly**,
yielding 617 records and 617 repeat/end markers -- one per record -- and zero
trailing slack anywhere. The retail 1.19F archive has one additional malformed
entry described below.

The pre-patch original parses 214 of 215. Its single failure, entry 76, is
the only record in either file with no ``0xFF`` terminator, and the v1.19H
patch deletes that entry outright -- so the one violation of the rule is
the one Origin removed.

**Entry index is an NPC index.** ``activity.flx`` entry *N* holds the
activity set for NPC *N* in ``runtime/NPC.FLX``, whose sole used entry is an
array of 352 fixed 316-byte NPC records. All 215 used activity slots have a
named NPC at the same index, and the names match the characters -- NPC 1
``LordBritish`` has ``After Yew`` / ``To Abyss`` / ``Endgame``, NPC 9
``Raven`` has ``Goto Despise`` / ``Go To Wrong``, NPC 39 ``Irene`` has
``Shopkeep``.

The 1.19F executable reads every step in this fixed layout and dispatches
opcodes ``0x00`` through ``0x0C`` directly. The public catalogue below uses
Titan terminology for the confirmed behavior. Opcode ``0x08`` is supported
by the executable but absent from both shipped archives checked. ``0xFF`` is
the repeat/end marker: it ends the stored record and tells the runtime to
restart the activity cycle when repetition is enabled.

The final word is converted with ``duration_code >> 2`` only by the travel
and begin-action handlers. Titan exposes both the stored word and that derived
value without discarding its low two bits. Other handlers ignore some or all
of the parameter and duration words; those bytes remain part of the lossless
step record.

Command-specific values, confirmed in the retail 1.19F executable:

* ``0x04`` begin NPC action: ``parameter_0`` is an action kind from
  :data:`ACTION_KIND_CATALOGUE`, ``parameter_1`` its argument, and the action
  lasts ``(duration_code >> 2)`` seconds (0 = until replaced). Kinds 1-38 are
  dispatched by value; twelve of them, kind 0, every kind above 38 and every
  value other than ``0xFFFE``/``0xFFFF`` start nothing. The same catalogue is
  the activity field of trigger command ``0x40``.
* ``0x06`` use selected object: ``parameter_0`` is an object *type*; the NPC
  uses the nearest object of that type within 1,280 units. ``parameter_1`` is
  never read.
* ``0x09`` run NPC triggers: ``parameter_0`` is the trigger phase, passed whole
  to the trigger executor (the value trigger command ``0x28`` passes as
  ``arg2 & 3``); the NPC must be in the fast area. Phase 0 runs the trigger in
  the low half of the NPC object's extra-data tag 62, phase 1 the high half,
  phases 2 and 3 the halves of tag 59 (:meth:`titan.u9.nonfixed.U9Nonfixed.entity_triggers`).
  Phases above 3 are not checked by the executor.

Records are looked up by ``ordinal`` every tick; ordinal 0 means "no record".
A call or switch to a missing ordinal is stored without a check, and on the
next tick the set restarts at ordinal 1. If the set's first record (in file
order) is not ordinal 1, the NPC runs its queued routine or else its default
activity from ``runtime/NPC.FLX``
(:attr:`U9Activity.starts_with_default_activity`). The call stack has
8 ordinal slots (cursor 0..7); a deeper call is ignored, and a return at depth 0 does
nothing.
Names such as ``Sequence 3`` are the authoring tool's default for ordinal 3
(all 311 in 1.19F match their record's ordinal); the runtime ignores names.

For reverse engineering, every record and step carries its byte offset
relative to the start of the FLX entry. Raw name padding, terminator
operands, trailing payload bytes, and bytes beyond the declared payload are
preserved. :meth:`U9Activity.to_bytes` therefore reproduces the original
entry exactly, including malformed or uninitialised data.

Example::

    from titan.u9.activity import U9Activities

    activities = U9Activities.from_file("static/activity.flx")
    activity = activities.activity(1)
    for record in activity.records:
        print(record.ordinal, record.name, len(record.steps))
"""

from __future__ import annotations

__all__ = [
    "ACTION_KIND_CATALOGUE",
    "ACTIVITY_OPCODE_CATALOGUE",
    "GESTURE_ANIMATION_IDS",
    "U9ActivityActionArgument",
    "U9ActivityActionKind",
    "U9Activities",
    "U9Activity",
    "U9ActivityError",
    "U9ActivityOpcodeInfo",
    "U9ActivityRecord",
    "U9ActivityStep",
    "activity_action_kind",
    "activity_action_argument",
    "activity_opcode_info",
]

import os
import struct
from collections import Counter
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

HEADER_SIZE = 8
NAME_FIELD_SIZE = 15
STEP_SIZE = 9
RECORD_HEADER_SIZE = 1 + NAME_FIELD_SIZE
TERMINATOR_OPCODE = 0xFF


@dataclass(frozen=True)
class U9ActivityOpcodeInfo:
    """Titan's stable public description of one runtime activity command."""

    opcode: int
    meaning: str
    parameter_roles: str
    evidence: str = "retail_runtime_confirmed"


ACTIVITY_OPCODE_CATALOGUE = (
    U9ActivityOpcodeInfo(0x00, "no operation", "no parameters"),
    U9ActivityOpcodeInfo(
        0x01,
        "travel between navigation points",
        "parameter_0=start point; parameter_1=destination point; duration_code>>2",
    ),
    U9ActivityOpcodeInfo(
        0x02,
        "travel cautiously between navigation points",
        "parameter_0=start point; parameter_1=destination point; duration_code>>2",
    ),
    U9ActivityOpcodeInfo(
        0x03,
        "relocate to a navigation point",
        "parameter_0=destination point; parameter_1=destination map",
    ),
    U9ActivityOpcodeInfo(
        0x04,
        "begin NPC action",
        "parameter_0=action kind; parameter_1=action argument; duration_code>>2 seconds",
    ),
    U9ActivityOpcodeInfo(
        0x05,
        "invoke conversation topic",
        "parameter_0=topic; remaining stored words ignored by dispatcher",
    ),
    U9ActivityOpcodeInfo(
        0x06,
        "use selected object",
        "parameter_0=object type (nearest within 1,280 units); parameter_1 never read",
    ),
    U9ActivityOpcodeInfo(
        0x07,
        "call activity sequence",
        "parameter_0=record ordinal; remaining stored words ignored by dispatcher",
    ),
    U9ActivityOpcodeInfo(
        0x08,
        "return from activity sequence",
        "no parameters read by dispatcher",
    ),
    U9ActivityOpcodeInfo(
        0x09,
        "run NPC triggers",
        "parameter_0=trigger phase (0-3); remaining stored words ignored by dispatcher",
    ),
    U9ActivityOpcodeInfo(
        0x0A,
        "switch activity sequence",
        "parameter_0=record ordinal; remaining stored words ignored by dispatcher",
    ),
    U9ActivityOpcodeInfo(
        0x0B,
        "branch label marker",
        "parameter_0=label; remaining stored words ignored by dispatcher",
    ),
    U9ActivityOpcodeInfo(
        0x0C,
        "jump to branch label",
        "parameter_0=label; remaining stored words ignored by dispatcher",
    ),
)

_ACTIVITY_OPCODE_BY_VALUE = {info.opcode: info for info in ACTIVITY_OPCODE_CATALOGUE}
_REPEAT_MARKER_INFO = U9ActivityOpcodeInfo(
    TERMINATOR_OPCODE,
    "repeat activity cycle",
    "stored operand words ignored",
)


@dataclass(frozen=True)
class U9ActivityActionKind:
    """One NPC action kind, as dispatched by the retail begin-action routine.

    ``performed`` is False for kinds rejected by the 1.19F dispatcher.
    Accepted conversation state (0xFFFE) constructs no child action.
    ``name`` is None for values outside the catalogue.
    """

    value: int
    name: str | None
    performed: bool
    evidence: str = "retail_runtime_confirmed"


_ACTION_KIND_NAMES = (
    "none",
    "stand",
    "loiter",
    "wander",
    "patrol",
    "pace",
    "placeholder_1",
    "placeholder_2",
    "placeholder_3",
    "placeholder_4",
    "placeholder_5",
    "placeholder_6",
    "placeholder_7",
    "humanoid_loiter",
    "tend_bar",
    "serve_drinks",
    "work_forge",
    "beg",
    "keep_shop",
    "drink_at_bar",
    "pray",
    "spar",
    "cast_spells",
    "listen",
    "gesture",
    "touch_object",
    "pick_up_object",
    "put_down_object",
    "turn_to_face",
    "creature_idle",
    "patrol_by_ship",
    "sit_in_chair",
    "sleep_in_bed",
    "random_gestures",
    "drink",
    "pausing_patrol",
    "patrol_without_loiter",
    "dying",
    "loiter_until_avatar_leaves",
)
# Kinds the retail switch (u9.exe 0x00404DBA) sends to its do-nothing case.
_UNPERFORMED_ACTION_KINDS = frozenset({0, 6, 7, 8, 9, 10, 11, 12, 14, 15, 19, 21, 22})

ACTION_KIND_CATALOGUE = tuple(
    U9ActivityActionKind(value, name, value not in _UNPERFORMED_ACTION_KINDS)
    for value, name in enumerate(_ACTION_KIND_NAMES)
) + (
    U9ActivityActionKind(0xFFFE, "conversation", True),
    U9ActivityActionKind(0xFFFF, "combat", True),
)
_ACTION_KIND_BY_VALUE = {kind.value: kind for kind in ACTION_KIND_CATALOGUE}


def activity_action_kind(value: int) -> U9ActivityActionKind:
    """The catalogued action kind for ``value``; unknown values start nothing."""
    kind = _ACTION_KIND_BY_VALUE.get(value)
    return kind if kind is not None else U9ActivityActionKind(value, None, False)


# Retail 1.19F dwords at 0x0077F6E8, independently recovered from u9.exe.
# Selector 121 is a zero word; later words are debug text, not animation IDs.
GESTURE_ANIMATION_IDS: tuple[int, ...] = (
    258,
    259,
    260,
    261,
    262,
    263,
    264,
    265,
    266,
    267,
    268,
    270,
    271,
    272,
    273,
    274,
    275,
    276,
    277,
    278,
    279,
    280,
    281,
    282,
    283,
    284,
    285,
    286,
    287,
    288,
    289,
    290,
    291,
    292,
    293,
    294,
    295,
    296,
    297,
    298,
    299,
    301,
    302,
    303,
    304,
    305,
    306,
    307,
    308,
    309,
    310,
    311,
    312,
    313,
    314,
    315,
    316,
    317,
    318,
    319,
    320,
    321,
    324,
    325,
    326,
    340,
    506,
    581,
    582,
    583,
    584,
    703,
    713,
    805,
    327,
    328,
    329,
    330,
    331,
    332,
    333,
    334,
    335,
    336,
    337,
    338,
    339,
    449,
    450,
    451,
    460,
    461,
    462,
    463,
    464,
    465,
    466,
    467,
    468,
    469,
    470,
    471,
    472,
    473,
    474,
    475,
    476,
    477,
    478,
    605,
    606,
    607,
    608,
    936,
    937,
    1084,
    1112,
    1113,
    1113,
    1117,
    426,
)


@dataclass(frozen=True)
class U9ActivityActionArgument:
    """Kind-specific views of an unchanged unsigned 16-bit action argument.

    Inapplicable views return None. Zero links retain their action-specific
    meaning (e.g. Avatar for facing, no initial facing for prayer). Furniture
    selection in humanoid loiter applies only when its sleep branch is chosen.
    These views describe inputs; they do not simulate action execution.
    """

    kind: U9ActivityActionKind
    raw_word: int

    def __post_init__(self) -> None:
        if not 0 <= self.raw_word <= 0xFFFF:
            raise ValueError("action argument must be an unsigned 16-bit word")
        if not 0 <= self.kind.value <= 0xFFFF:
            raise ValueError("action kind must be an unsigned 16-bit word")

    @property
    def consumed_mask(self) -> int:
        """Bits read for this kind; rejected/ignored arguments consume none."""
        if self.kind.value in (13, 31, 32, 37, 38):
            return 0x0001
        if self.kind.value in (4, 5, 20, 23, 24, 25, 26, 27, 28, 30, 35, 36, 0xFFFF):
            return 0xFFFF
        return 0

    @property
    def unused_bits(self) -> int:
        return self.raw_word & (0xFFFF ^ self.consumed_mask)

    @property
    def starting_marker_link(self) -> int | None:
        return self.raw_word if self.kind.value in (4, 30, 35, 36) else None

    @property
    def heading_degrees(self) -> int | None:
        return self.raw_word if self.kind.value == 5 else None

    @property
    def facing_link(self) -> int | None:
        return self.raw_word if self.kind.value in (20, 28) else None

    @property
    def facing_base_type(self) -> int | None:
        return self.raw_word if self.kind.value == 23 else None

    @property
    def gesture_selector(self) -> int | None:
        return self.raw_word & 0x0FFF if self.kind.value == 24 else None

    @property
    def gesture_animation_id(self) -> int | None:
        """Retail clip ID, or None for non-gestures/out-of-table selectors."""
        selector = self.gesture_selector
        if selector is None or selector >= len(GESTURE_ANIMATION_IDS):
            return None
        return GESTURE_ANIMATION_IDS[selector]

    @property
    def speed_step(self) -> int | None:
        if self.kind.value == 24:
            return (self.raw_word >> 12) & 7
        if self.kind.value in (25, 26, 27):
            return self.raw_word >> 13
        return None

    @property
    def playback_scale(self) -> float | None:
        step = self.speed_step
        return None if step is None else 1.0 - 0.1 * step

    @property
    def repeat(self) -> bool | None:
        return bool(self.raw_word & 0x8000) if self.kind.value == 24 else None

    @property
    def target_link(self) -> int | None:
        return self.raw_word & 0x1FFF if self.kind.value in (25, 26) else None

    @property
    def placement_marker_link(self) -> int | None:
        return self.raw_word & 0x1FFF if self.kind.value == 27 else None

    @property
    def nearest_chair(self) -> bool | None:
        return bool(self.raw_word & 1) if self.kind.value == 31 else None

    @property
    def nearest_bed(self) -> bool | None:
        return bool(self.raw_word & 1) if self.kind.value in (13, 32, 37, 38) else None

    @property
    def request_assistance(self) -> bool | None:
        """Nonzero requests assistance on first combat entry against its target."""
        return bool(self.raw_word) if self.kind.value == 0xFFFF else None


def activity_action_argument(kind: int, argument: int) -> U9ActivityActionArgument:
    """Decode the word retained for an activity or trigger begin-action command."""
    return U9ActivityActionArgument(activity_action_kind(kind), argument)


def activity_opcode_info(opcode: int) -> U9ActivityOpcodeInfo | None:
    """Return the confirmed runtime description for ``opcode``, if known."""
    if opcode == TERMINATOR_OPCODE:
        return _REPEAT_MARKER_INFO
    return _ACTIVITY_OPCODE_BY_VALUE.get(opcode)


class U9ActivityError(Exception):
    """Raised on malformed ``static/activity.flx`` data."""


@dataclass(frozen=True)
class U9ActivityStep:
    """One lossless nine-byte command with typed views over its operands."""

    opcode: int
    operands: bytes
    entry_offset: int = 0

    @property
    def is_terminator(self) -> bool:
        return self.opcode == TERMINATOR_OPCODE

    @property
    def is_repeat_marker(self) -> bool:
        """Whether this is the stored end marker for a repeatable cycle."""
        return self.opcode == TERMINATOR_OPCODE

    @property
    def opcode_info(self) -> U9ActivityOpcodeInfo | None:
        return activity_opcode_info(self.opcode)

    @property
    def semantic_name(self) -> str:
        info = self.opcode_info
        return "unknown" if info is None else info.meaning

    @property
    def operands_u16(self) -> tuple[int, int, int, int]:
        """The raw operand bytes viewed as four little-endian words."""
        return struct.unpack("<4H", self.operands)

    @property
    def operands_u32(self) -> tuple[int, int]:
        """The raw operand bytes viewed as two little-endian double words."""
        return struct.unpack("<2I", self.operands)

    @property
    def parameter_0(self) -> int:
        return self.operands_u16[0]

    @property
    def parameter_1(self) -> int:
        return self.operands_u16[1]

    @property
    def scheduled_minute(self) -> int:
        """World-clock minute used to schedule this step; zero means untimed."""
        return self.operands_u16[2]

    @property
    def duration_code(self) -> int:
        """Stored duration word, before command-specific conversion."""
        return self.operands_u16[3]

    @property
    def duration_value(self) -> int | None:
        """Duration consumed by travel and begin-action commands."""
        if self.opcode not in (0x01, 0x02, 0x04):
            return None
        return self.duration_code >> 2

    @property
    def duration_remainder(self) -> int | None:
        """Preserved low bits discarded by duration-using handlers."""
        if self.opcode not in (0x01, 0x02, 0x04):
            return None
        return self.duration_code & 0x03

    @property
    def movement_points(self) -> tuple[int, int] | None:
        """Start/destination navigation points for travel commands."""
        if self.opcode not in (0x01, 0x02):
            return None
        return self.parameter_0, self.parameter_1

    @property
    def relocation_target(self) -> tuple[int, int] | None:
        """Destination navigation point and map for relocation commands."""
        if self.opcode != 0x03:
            return None
        return self.parameter_0, self.parameter_1

    @property
    def npc_action(self) -> tuple[int, int] | None:
        """NPC action kind and its command-specific argument."""
        if self.opcode != 0x04:
            return None
        return self.parameter_0, self.parameter_1

    @property
    def npc_action_argument(self) -> U9ActivityActionArgument | None:
        """Typed action argument for opcode 0x04, preserving the original word."""
        if self.opcode != 0x04:
            return None
        return activity_action_argument(self.parameter_0, self.parameter_1)

    @property
    def npc_action_kind(self) -> U9ActivityActionKind | None:
        """Catalogued action kind for a begin-action step (``0x04``)."""
        if self.opcode != 0x04:
            return None
        return activity_action_kind(self.parameter_0)

    @property
    def conversation_topic(self) -> int | None:
        return self.parameter_0 if self.opcode == 0x05 else None

    @property
    def object_selector(self) -> int | None:
        return self.parameter_0 if self.opcode == 0x06 else None

    @property
    def sequence_ordinal(self) -> int | None:
        if self.opcode not in (0x07, 0x0A):
            return None
        return self.parameter_0

    @property
    def trigger_phase(self) -> int | None:
        return self.parameter_0 if self.opcode == 0x09 else None

    @property
    def branch_label(self) -> int | None:
        if self.opcode not in (0x0B, 0x0C):
            return None
        return self.parameter_0

    def to_bytes(self) -> bytes:
        """Encode this step in its exact nine-byte disk layout."""
        if len(self.operands) != 8:
            raise U9ActivityError(
                f"opcode 0x{self.opcode:02X}: expected 8 operand bytes, "
                f"got {len(self.operands)}"
            )
        return bytes((self.opcode,)) + self.operands


@dataclass(frozen=True)
class U9ActivityRecord:
    """One named activity within an entry."""

    ordinal: int
    name: str
    steps: tuple[U9ActivityStep, ...]
    terminated: bool
    entry_offset: int = 0
    raw_name_field: bytes = b""
    terminator: U9ActivityStep | None = None

    @property
    def opcodes(self) -> list[int]:
        return [s.opcode for s in self.steps]

    def to_bytes(self) -> bytes:
        """Encode the record while preserving its original name padding."""
        if self.raw_name_field:
            name_field = self.raw_name_field
        else:
            encoded = self.name.encode("ascii", errors="replace")[: NAME_FIELD_SIZE - 1]
            name_field = (encoded + b"\x00").ljust(NAME_FIELD_SIZE, b"\x00")
        result = bytes((self.ordinal,)) + name_field
        result += b"".join(step.to_bytes() for step in self.steps)
        if self.terminator is not None:
            result += self.terminator.to_bytes()
        return result


@dataclass(frozen=True)
class U9Activity:
    """One FLX entry: a set of named activity records."""

    activity_id: int
    declared_record_count: int
    payload_length: int
    records: tuple[U9ActivityRecord, ...]
    trailing_bytes: int
    trailing_data: bytes = b""
    post_payload_data: bytes = b""
    raw_data: bytes = b""

    @property
    def is_complete(self) -> bool:
        """True when every declared record parsed and the body was consumed exactly."""
        return (
            len(self.records) == self.declared_record_count
            and self.trailing_bytes == 0
            and not self.post_payload_data
            and all(r.terminated for r in self.records)
        )

    @property
    def names(self) -> list[str]:
        return [r.name for r in self.records]

    @property
    def starts_with_default_activity(self) -> bool:
        """True when the first record is not ordinal 1.

        The runtime starts a set at ordinal 1 and, when the first record is
        some other ordinal, runs the NPC's queued or default activity
        instead, so the set's records run only when something switches to
        them.
        """
        return bool(self.records) and self.records[0].ordinal != 1

    def unresolved_sequence_references(self) -> list[tuple[int, int, int]]:
        """``(record ordinal, step index, target)`` for call/switch steps
        (``0x07``/``0x0A``) naming an ordinal this set lacks; on the next tick
        the runtime restarts the set at ordinal 1."""
        ordinals = {record.ordinal for record in self.records}
        return [
            (record.ordinal, index, step.parameter_0)
            for record in self.records
            for index, step in enumerate(record.steps)
            if step.opcode in (0x07, 0x0A) and step.parameter_0 not in ordinals
        ]

    def to_bytes(self) -> bytes:
        """Return the complete original FLX-entry payload byte for byte."""
        if self.raw_data:
            return self.raw_data
        body = b"".join(record.to_bytes() for record in self.records)
        body += self.trailing_data
        return (
            struct.pack("<II", self.declared_record_count, self.payload_length)
            + body
            + self.post_payload_data
        )


class U9Activities:
    """Reader for ``static/activity.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self._archive = archive

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Activities:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as e:
            raise U9ActivityError(f"not a readable FLX archive: {e}") from e

    @property
    def num_entries(self) -> int:
        return self._archive.num_entries

    def used_activity_ids(self) -> list[int]:
        """FLX entry indices that hold data."""
        return self._archive.used_entry_indices()

    def _read_record(self, body: bytes, pos: int) -> tuple[U9ActivityRecord, int]:
        record_offset = HEADER_SIZE + pos
        ordinal = body[pos]
        raw_name = body[pos + 1 : pos + 1 + NAME_FIELD_SIZE]
        # Everything past the NUL is uninitialised padding, never data.
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        pos += RECORD_HEADER_SIZE

        steps: list[U9ActivityStep] = []
        terminated = False
        terminator = None
        while pos + STEP_SIZE <= len(body):
            opcode = body[pos]
            step = U9ActivityStep(
                opcode=opcode,
                operands=body[pos + 1 : pos + STEP_SIZE],
                entry_offset=HEADER_SIZE + pos,
            )
            if opcode == TERMINATOR_OPCODE:
                terminated = True
                terminator = step
                pos += STEP_SIZE
                break
            steps.append(step)
            pos += STEP_SIZE
        return (
            U9ActivityRecord(
                ordinal=ordinal,
                name=name,
                steps=tuple(steps),
                terminated=terminated,
                entry_offset=record_offset,
                raw_name_field=raw_name,
                terminator=terminator,
            ),
            pos,
        )

    def activity(self, activity_id: int) -> U9Activity | None:
        """One entry by FLX index, or ``None`` if that slot is unused."""
        if activity_id < 0 or activity_id >= self.num_entries:
            raise U9ActivityError(
                f"activity ID {activity_id} out of range (0..{self.num_entries - 1})"
            )
        blob = self._archive.read_entry(activity_id)
        if not blob:
            return None
        if len(blob) < HEADER_SIZE:
            raise U9ActivityError(
                f"activity {activity_id}: {len(blob)} bytes is too small for an 8-byte header"
            )

        record_count, payload_length = struct.unpack_from("<II", blob, 0)
        if payload_length > len(blob) - HEADER_SIZE:
            raise U9ActivityError(
                f"activity {activity_id}: declared payload of {payload_length} bytes "
                f"exceeds the {len(blob) - HEADER_SIZE} available"
            )
        body = blob[HEADER_SIZE : HEADER_SIZE + payload_length]

        records: list[U9ActivityRecord] = []
        pos = 0
        for _ in range(record_count):
            if pos + RECORD_HEADER_SIZE > len(body):
                break
            record, pos = self._read_record(body, pos)
            records.append(record)
            if not record.terminated:
                break

        return U9Activity(
            activity_id=activity_id,
            declared_record_count=record_count,
            payload_length=payload_length,
            records=tuple(records),
            trailing_bytes=len(body) - pos,
            trailing_data=body[pos:],
            post_payload_data=blob[HEADER_SIZE + payload_length :],
            raw_data=blob,
        )

    def activities(self) -> list[U9Activity]:
        """Every used entry, in ID order."""
        result = []
        for activity_id in self.used_activity_ids():
            activity = self.activity(activity_id)
            if activity is not None:
                result.append(activity)
        return result

    def opcode_histogram(self) -> Counter[int]:
        """How often each step opcode appears, terminators excluded."""
        histogram: Counter[int] = Counter()
        for activity in self.activities():
            for record in activity.records:
                histogram.update(record.opcodes)
        return histogram

    def name_histogram(self) -> Counter[str]:
        """How often each activity name appears across the archive."""
        histogram: Counter[str] = Counter()
        for activity in self.activities():
            histogram.update(activity.names)
        return histogram

    def incomplete_activity_ids(self) -> list[int]:
        """Entries that did not parse cleanly.

        Empty on the shipped archive. The pre-patch original reports entry
        76, whose single record has no terminator; the patch deletes it.
        """
        return [a.activity_id for a in self.activities() if not a.is_complete]
