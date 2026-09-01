"""
TYPES.DAT reader for Ultima 9: Ascension.

``static/TYPES.DAT`` is the flat object-type table: entry index *is*
the type ID (the same index space as ``static/TYPENAME.FLX``, see
:mod:`titan.u9.typename`). An 8-byte file header is followed by 8,192
fixed 16-byte records, byte-for-byte::

    0x00  (unknown)          u32, either 0 or 0xCDCDCDCD, no apparent pattern
    0x04  usecode_id         u16 -- index into the game engine's usecode function list
    0x06  default_model_id   u16 -- index into static/sappear.flx (0 = none)
    0x08  type_flags         u16 -- bitmask (never-hidden, npc-only-collision, etc.)
    0x0A  weight              u8
    0x0B  volume              u8
    0x0C  book_number         u8 -- vestigial
    0x0D  hitpoints           u8 -- vestigial
    0x0E  (unknown)          u16, always 0 in every sample seen

Reverse-engineered from this project's own prior exploration
(``u9data/scripts/parsers/types_dat.py``) and re-validated here against
the real file: 131,080 bytes = 8 + 16*8192 exactly, with zero remainder.

That exact size is also the only way to tell a ``TYPES.DAT`` from any
other file -- there is no magic number -- so :class:`U9TypesDat` requires
it and raises :class:`U9TypesDatError` otherwise. A looser "whole number
of records" rule is not enough: across the 545 U9 data files in this
project's copy of the game, 144 satisfy it (every ``terrain.*`` file plus
``text.dat`` and ``treedat.flx``), while the exact-size rule accepts
exactly one, the real ``TYPES.DAT``.

``default_model_id`` is the only link from a ``TYPENAME.FLX`` display
name to a ``sappear.flx`` model: multiple type IDs (and thus possibly
multiple names) commonly share one ``default_model_id`` (a generic body
mesh reused across several named NPCs), so the mapping from model ID
back to a name is **not unique** -- see :meth:`U9TypesDat.type_ids_for_model`
and :mod:`titan.u9.model_naming`, which builds the actual name lookup on
top of this.

Example::

    from titan.u9.types_dat import U9TypesDat

    types = U9TypesDat.from_file("static/TYPES.DAT")
    print(types.records[1].default_model_id)  # 1805
    print(types.type_ids_for_model(1805))      # [1, ...]
"""

from __future__ import annotations

__all__ = ["U9TypeRecord", "U9TypesDat", "U9TypesDatError"]

import os
import struct
from dataclasses import dataclass

HEADER_SIZE = 8
RECORD_SIZE = 16
RECORD_STRUCT = "<IHHHBBBBH"

# The type ID space is shared with static/TYPENAME.FLX and with the
# ``type_index`` field of runtime entities, and tops out at 8,191.
MAX_RECORDS = 8192
EXPECTED_SIZE = HEADER_SIZE + RECORD_SIZE * MAX_RECORDS  # 131,080


class U9TypesDatError(Exception):
    """Raised on malformed ``static/TYPES.DAT`` data."""


@dataclass(frozen=True)
class U9TypeRecord:
    """One ``TYPES.DAT`` entry."""

    type_id: int
    usecode_id: int
    default_model_id: int
    type_flags: int
    weight: int
    volume: int
    book_number: int
    hitpoints: int


class U9TypesDat:
    """``type_id`` -> :class:`U9TypeRecord` lookup, decoded from ``static/TYPES.DAT``."""

    def __init__(self, data: bytes) -> None:
        # TYPES.DAT carries no magic number, so its size is the only thing
        # distinguishing it from an arbitrary file, and only the exact size
        # will do. A "whole number of records" check is far too weak: every
        # terrain.* file in the game, plus text.dat and treedat.flx, happens
        # to be a multiple of 16 plus 8 bytes -- 143 files in this project's
        # copy alone would pass it. The table is indexed by type ID, so a
        # short one could not serve its purpose anyway.
        if len(data) < HEADER_SIZE:
            raise U9TypesDatError(
                f"data too small to contain an 8-byte header: {len(data)} bytes"
            )
        payload = len(data) - HEADER_SIZE
        if payload % RECORD_SIZE:
            raise U9TypesDatError(
                f"{payload} bytes after the header is not a whole number of "
                f"{RECORD_SIZE}-byte records ({payload % RECORD_SIZE} left over) "
                f"-- not a TYPES.DAT?"
            )
        if payload != EXPECTED_SIZE - HEADER_SIZE:
            raise U9TypesDatError(
                f"expected {EXPECTED_SIZE} bytes "
                f"({HEADER_SIZE} + {RECORD_SIZE}*{MAX_RECORDS}), got {len(data)} "
                f"-- not a TYPES.DAT?"
            )
        self.records: list[U9TypeRecord] = []
        offset = HEADER_SIZE
        type_id = 0
        while offset + RECORD_SIZE <= len(data):
            _unknown1, usecode_id, default_model_id, type_flags, weight, volume, book_number, hitpoints, _unknown2 = (
                struct.unpack_from(RECORD_STRUCT, data, offset)
            )
            self.records.append(
                U9TypeRecord(
                    type_id=type_id,
                    usecode_id=usecode_id,
                    default_model_id=default_model_id,
                    type_flags=type_flags,
                    weight=weight,
                    volume=volume,
                    book_number=book_number,
                    hitpoints=hitpoints,
                )
            )
            offset += RECORD_SIZE
            type_id += 1

        self._model_to_types: dict[int, list[int]] = {}
        for record in self.records:
            if record.default_model_id:
                self._model_to_types.setdefault(record.default_model_id, []).append(record.type_id)

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9TypesDat:
        with open(filepath, "rb") as f:
            return cls(f.read())

    def type_ids_for_model(self, model_id: int) -> list[int]:
        """Every ``type_id`` whose ``default_model_id`` is ``model_id`` (often more than one, or none)."""
        return list(self._model_to_types.get(model_id, ()))

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)
