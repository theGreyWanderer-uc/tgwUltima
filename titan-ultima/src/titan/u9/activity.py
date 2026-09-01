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

    0x00  opcode     u8
    0x01  operands   8 bytes  -- not yet split into fields

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

Verified against the real ``static/activity.flx`` (29,522 bytes, 352 FLX
slots, 214 used): **all 214 entries parse with their bodies consumed
exactly**, yielding 617 records and 617 terminators -- one per record -- and
zero trailing slack anywhere.

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

**Step opcode semantics are mostly undecoded.** 12 distinct opcodes appear
across 1,049 non-terminator steps, dominated by ``0x04``, ``0x0A``, ``0x03``
and ``0x01``. This module exposes the step stream, not its meaning.

The exceptions are ``0x01`` and ``0x02``, which move an NPC between two
navigation points: the operand is a source ``u16`` and a destination ``u16``
naming points in :mod:`titan.u9.highway`, followed by four bytes that are
zero throughout. Both halves are declared points in all 156 such steps
(100%), against 2 of 385 for ``0x04`` and none for the rest. NPC 166
``Dermot`` is the clearest case: his ``Sequence 2`` (51823 -> 51554) and
``Sequence 4`` (51554 -> 51823) are exact mirrors, the cemetery-to-pub round
trip his patch notes describe.

Example::

    from titan.u9.activity import U9Activities

    activities = U9Activities.from_file("static/activity.flx")
    activity = activities.activity(1)
    for record in activity.records:
        print(record.ordinal, record.name, len(record.steps))
"""

from __future__ import annotations

__all__ = [
    "U9Activities",
    "U9Activity",
    "U9ActivityError",
    "U9ActivityRecord",
    "U9ActivityStep",
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


class U9ActivityError(Exception):
    """Raised on malformed ``static/activity.flx`` data."""


@dataclass(frozen=True)
class U9ActivityStep:
    """One 9-byte step.

    Only opcodes ``0xFF`` (terminator) and ``0x01``/``0x02`` (move between
    highway points) have known meanings; see the module docstring.
    """

    opcode: int
    operands: bytes

    @property
    def is_terminator(self) -> bool:
        return self.opcode == TERMINATOR_OPCODE


@dataclass(frozen=True)
class U9ActivityRecord:
    """One named activity within an entry."""

    ordinal: int
    name: str
    steps: tuple[U9ActivityStep, ...]
    terminated: bool

    @property
    def opcodes(self) -> list[int]:
        return [s.opcode for s in self.steps]


@dataclass(frozen=True)
class U9Activity:
    """One FLX entry: a set of named activity records."""

    activity_id: int
    declared_record_count: int
    payload_length: int
    records: tuple[U9ActivityRecord, ...]
    trailing_bytes: int

    @property
    def is_complete(self) -> bool:
        """True when every declared record parsed and the body was consumed exactly."""
        return (
            len(self.records) == self.declared_record_count
            and self.trailing_bytes == 0
            and all(r.terminated for r in self.records)
        )

    @property
    def names(self) -> list[str]:
        return [r.name for r in self.records]


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
        ordinal = body[pos]
        raw_name = body[pos + 1 : pos + 1 + NAME_FIELD_SIZE]
        # Everything past the NUL is uninitialised padding, never data.
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        pos += RECORD_HEADER_SIZE

        steps: list[U9ActivityStep] = []
        terminated = False
        while pos + STEP_SIZE <= len(body):
            opcode = body[pos]
            if opcode == TERMINATOR_OPCODE:
                terminated = True
                pos += STEP_SIZE
                break
            steps.append(U9ActivityStep(opcode=opcode, operands=body[pos + 1 : pos + STEP_SIZE]))
            pos += STEP_SIZE
        return (
            U9ActivityRecord(
                ordinal=ordinal, name=name, steps=tuple(steps), terminated=terminated
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
