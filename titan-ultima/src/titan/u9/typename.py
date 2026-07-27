"""
TYPENAME.FLX reader for Ultima 9: Ascension.

Type-ID -> display-name lookup: entry ``index`` in ``static/TYPENAME.FLX``
*is* the type ID (the same index space as ``static/types.dat``'s object
type records). Each directory entry, byte-for-byte::

    0x0  reserved   u32, always 0 in every sample seen
    0x4  marker     u16, constant 0x1B81 across every sample seen
    0x6  name       optional NUL-terminated ASCII string

An entry with only the 6-byte header and no trailing string is a type
with no display name (most types -- only named NPCs/unique objects like
"Lord British" get one).

Neither ``u9ed`` nor the Ultima-9-Blender-Importer reference source
covers this archive -- this format was reverse-engineered directly from
raw bytes (not ported from another implementation), and only the two
constant fields above are confirmed stable across samples; nothing
about them is asserted beyond what was actually observed.

Example::

    from titan.u9.typename import U9TypeNames

    names = U9TypeNames.from_file("static/TYPENAME.FLX")
    print(names.name_for(1))  # "Lord British"
"""

from __future__ import annotations

__all__ = ["U9TypeNameEntry", "U9TypeNames"]

import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive

HEADER_SIZE = 6
RESERVED_STRUCT = "<IH"


@dataclass(frozen=True)
class U9TypeNameEntry:
    """One TYPENAME.FLX entry: a type ID and its optional display name."""

    type_id: int
    reserved: int
    marker: int
    name: str | None


class U9TypeNames:
    """Type-ID -> display-name lookup, decoded from ``static/TYPENAME.FLX``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.entries: list[U9TypeNameEntry] = []
        for entry in archive.entries:
            blob = archive.read_entry(entry.index)
            if len(blob) < HEADER_SIZE:
                continue

            reserved, marker = struct.unpack_from(RESERVED_STRUCT, blob, 0)

            name: str | None = None
            if len(blob) > HEADER_SIZE:
                raw = blob[HEADER_SIZE:]
                nul = raw.find(b"\x00")
                if nul != -1:
                    raw = raw[:nul]
                if raw:
                    name = raw.decode("ascii", errors="replace")

            self.entries.append(
                U9TypeNameEntry(type_id=entry.index, reserved=reserved, marker=marker, name=name)
            )

        self._by_id = {e.type_id: e for e in self.entries}

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9TypeNames:
        return cls(U9FlxArchive.from_file(filepath))

    def name_for(self, type_id: int) -> str | None:
        entry = self._by_id.get(type_id)
        return entry.name if entry else None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)
