"""
``static/triggers.flx`` reader for Ultima 9: Ascension.

U9's trigger scripts. Each FLX entry is one trigger, and **the entry index
is the trigger ID** -- the same value carried by
:attr:`titan.u9.nonfixed.U9Entity.trigger_id`, which is what associates a
world object with the script that fires for it.

A trigger body is a flat list of 6-byte records, terminated by a record
whose opcode is ``0xFF``::

    0x00  opcode   u8
    0x01  arg0     u8
    0x02  arg1     u16
    0x04  arg2     u16

Records after the terminator are slack -- an FLX entry keeps whatever
length it was allocated, so a trigger that shrank leaves stale records
behind. 361 entries are *empty* triggers whose first record is already the
terminator, several of those with slack after it. This reader stops at the
first ``0xFF`` and reports the leftovers as
:attr:`U9Trigger.slack_records` rather than decoding them.

**Opcode semantics are almost entirely undecoded.** 90 distinct opcodes
appear across the 20,000-odd body records; this module exposes the record
stream and the container structure, not their meaning. ``arg0`` is a genuine
per-record parameter and not a category tag -- opcode ``0x01`` alone uses 32
distinct ``arg0`` values, and only 13 of the 90 opcodes hold ``arg0``
constant.

The one exception is opcode ``0x31``, which runs an NPC activity record:
``arg1`` is an activity set index in :mod:`titan.u9.activity` (also the NPC's
index in ``runtime/NPC.FLX``) and ``arg2``'s **low byte** is a record
``ordinal`` within that set. That pair names a record which actually exists
in 500 of the archive's 506 ``0x31`` steps (98.8%); reading ``arg2`` whole
scores 96.0%, which is what exposed the high byte as a separate field. No
other opcode with 20 or more steps passes the same test above 51.6%.

Verified against the real ``static/triggers.flx`` (242,476 bytes, 10,000
entries, 6,712 used, both the v1.19H copy and its pre-patch original):
every used entry's length is a multiple of 6, and 6,710 of 6,712 (99.97%)
carry a ``0xFF`` terminator.

The two that do not -- trigger IDs 58 and 631 -- appear to be **valid
triggers that simply omit the redundant terminator**, not damage. Their
records use ordinary opcodes (``0x0C``, ``0x0A``, ``0x33``, each common
elsewhere) with the usual ``arg0`` of 16; the FLX directory tiles the
payload with zero gaps and zero overlaps, so nothing is truncated; and 54
world entities across 20 regions reference trigger 58, which a broken
trigger would make a conspicuous and widely reproducing bug. Since the
terminator is the final record in 6,700 of 6,712 entries, it is redundant
with the entry length almost everywhere. The engine most likely stops at
the terminator *or* the end of the entry, whichever comes first -- which
also explains the ten entries carrying slack behind their terminator.
``U9Trigger.terminated`` reports the distinction without judging it.

The terminator's ``arg0`` is ``0x10`` in 6,711 cases and ``0x00`` in one,
so the whole word is ``0x10FF`` almost everywhere -- but the opcode byte is
what actually ends the list, and matching on the byte rather than the word
is what recovers trigger 7318.

Cross-checked against world data: of the ``nonfixed`` entity trigger IDs
that fall inside this archive's index range, 8,205 of 8,439 (97.2%) name a
*used* entry here. Trigger IDs at or above 12,460 belong to
:mod:`titan.u9.highway` instead -- the two files partition the ID space.

Example::

    from titan.u9.triggers import U9Triggers

    triggers = U9Triggers.from_file("static/triggers.flx")
    trigger = triggers.trigger(308)
    for record in trigger.records:
        print(hex(record.opcode), record.arg0, record.arg1, record.arg2)
"""

from __future__ import annotations

__all__ = [
    "U9Trigger",
    "U9TriggerRecord",
    "U9Triggers",
    "U9TriggersError",
]

import os
import struct
from collections import Counter
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

RECORD_SIZE = 6
RECORD_STRUCT = "<BBHH"
TERMINATOR_OPCODE = 0xFF


class U9TriggersError(Exception):
    """Raised on malformed ``static/triggers.flx`` data."""


@dataclass(frozen=True)
class U9TriggerRecord:
    """One 6-byte trigger instruction.

    Only opcode ``0xFF`` (terminator) and ``0x31`` (run an activity record)
    have known meanings; see the module docstring.
    """

    opcode: int
    arg0: int
    arg1: int
    arg2: int

    @property
    def is_terminator(self) -> bool:
        return self.opcode == TERMINATOR_OPCODE


@dataclass(frozen=True)
class U9Trigger:
    """One trigger script, keyed by its FLX entry index."""

    trigger_id: int
    records: tuple[U9TriggerRecord, ...]
    slack_records: int
    terminated: bool

    @property
    def is_empty(self) -> bool:
        """True when the trigger's body is empty -- the terminator came first."""
        return not self.records

    @property
    def opcodes(self) -> list[int]:
        return [r.opcode for r in self.records]


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
            record = U9TriggerRecord(*struct.unpack_from(RECORD_STRUCT, blob, index * RECORD_SIZE))
            if record.is_terminator:
                terminated = True
                return U9Trigger(
                    trigger_id=trigger_id,
                    records=tuple(records),
                    slack_records=count - index - 1,
                    terminated=True,
                )
            records.append(record)
        return U9Trigger(
            trigger_id=trigger_id,
            records=tuple(records),
            slack_records=0,
            terminated=terminated,
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

    def unterminated_trigger_ids(self) -> list[int]:
        """Triggers whose record list runs off the end without a ``0xFF``.

        Two in the shipped archive (IDs 58 and 631); a longer list means the
        file is damaged or is not a triggers archive.
        """
        return [t.trigger_id for t in self.triggers() if not t.terminated]
