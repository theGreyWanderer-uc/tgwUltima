"""
FLX archive reader for Ultima 9: Ascension.

An FLX file is a flat directory-of-blobs container used throughout U9's
``static/``, ``sound/``, and ``runtime/`` data (bitmap16.flx, sappear.flx,
TYPENAME.FLX, Speech.flx, NPC.FLX, ...). Layout, byte-for-byte::

    0x00  Comment          76 bytes, ASCII -- **space**-padded in every shipped
                           archive, not NUL-padded (all 25 agree)
    0x4C  Unknown1         u32   -- 0 in every shipped archive
    0x50  Count            u32   -- number of directory entries
    0x54  Format version   u32   -- always 2; see FORMAT_VERSION
    0x58  Size             u32   -- total file size
    0x5C  Size2            u32   -- the same value again
    0x60  Unknown3         32 bytes, reserved -- zero but for a 1 at 0x68
    0x80  Directory        Count * 8 bytes: (offset: u32, length: u32) each

An entry with ``offset == 0`` (or ``length == 0``) is an unused slot, not
an entry at offset 0 -- the archive's own header always occupies real
offset 0, so a genuine entry can never legitimately start there.

``0x4C`` and the reserved block at ``0x60``-``0x7F`` are **unused and empty** in
every shipped archive -- a zero word, and 32 zero bytes but for a ``1`` at
``0x68``. Neither ever varies, so neither carries information and nothing can be
inferred about their purpose from the data. Write the shipped values; read
nothing into them. The 76-byte comment field is likewise 76 spaces in every
archive, never written to.

The word at ``0x54`` is checked on construction, because without it this reader
accepted **570 of the 595 files** in a game install -- ``ddraw.dll``,
``ConfigINI.exe``, ``.ini`` and ``.txt`` among them. With it, exactly the 41
real archives parse. That is 16 more than the 25 with a ``.flx`` extension:
``Texture8.9``/``.14`` and ``texture16.9``/``.14`` are FLX despite the
extension, and so are twelve dialect variants of the game text --
``Mbrk``/``Tbrk``/``Tnbrk`` with ``.br``, ``.fn``, ``.ns`` and ``.vl``
suffixes.

Cross-validated against ``u9ed``'s ``FLXFile.cs`` (a real, open-source C#
FLX/bitmap viewer -- see ``FLXFile.Load()``), which reads this exact
field order and these exact offsets. Read for byte-layout reference
only -- this is a fresh implementation, not a translation of that GPL
source.

Example::

    from titan.u9.flx_archive import U9FlxArchive

    archive = U9FlxArchive.from_file("static/TYPENAME.FLX")
    print(archive.num_entries)
    blob = archive.read_entry(1)  # b"" if that slot is unused
"""

from __future__ import annotations

__all__ = [
    "FORMAT_VERSION",
    "MAX_ENTRIES",
    "U9FlxArchive",
    "U9FlxArchiveError",
    "U9FlxDirEntry",
]

import os
import struct
from dataclasses import dataclass

COMMENT_SIZE = 0x4C
VERSION_OFFSET = 0x54
COUNT_OFFSET = 0x50
SIZE_OFFSET = 0x58
SIZE2_OFFSET = 0x5C
DIR_OFFSET = 0x80
DIR_ENTRY_SIZE = 8

FORMAT_VERSION = 2
"""The word at ``0x54``, identical in all 41 shipped archives.

Origin's older FLEX container has the same header layout with its fields four
bytes later, and titan's own ``flex.py`` documents FLEX's equivalent slot as
"often ``0x00000001``" -- so this reads as a format version, 1 for FLEX and 2
for U9's FLX. That reading is unconfirmed: the only FLEX files to hand are
tool-generated and hold neither value.

Whatever it means, it makes a reliable signature. Without checking it the
reader accepted **570 of the 595 files** in a game install, including
``ddraw.dll``, ``ConfigINI.exe`` and assorted ``.ini`` and ``.txt`` files;
checking it accepts exactly the 41 real archives.
"""

MAX_ENTRIES = 1 << 20
"""Sanity ceiling on the directory. The largest shipped archive declares 16,384."""


class U9FlxArchiveError(Exception):
    """Raised on malformed FLX archive data or an out-of-range entry index."""


@dataclass(frozen=True)
class U9FlxDirEntry:
    """One directory slot: where an entry's payload lives, or an unused slot."""

    index: int
    offset: int
    length: int

    @property
    def is_used(self) -> bool:
        return self.offset != 0 and self.length != 0


class U9FlxArchive:
    """Reader for Ultima 9 FLX archives."""

    def __init__(self, data: bytes) -> None:
        if len(data) < DIR_OFFSET:
            raise U9FlxArchiveError(f"data too small to contain an FLX header: {len(data)} bytes")

        version = struct.unpack_from("<I", data, VERSION_OFFSET)[0]
        if version != FORMAT_VERSION:
            raise U9FlxArchiveError(
                f"not an FLX archive: format word at {VERSION_OFFSET:#x} is {version}, "
                f"expected {FORMAT_VERSION}"
            )

        count = struct.unpack_from("<I", data, COUNT_OFFSET)[0]
        if count > MAX_ENTRIES:
            raise U9FlxArchiveError(
                f"not an FLX archive: implausible entry count {count} "
                f"(0..{MAX_ENTRIES})"
            )
        if DIR_OFFSET + count * DIR_ENTRY_SIZE > len(data):
            raise U9FlxArchiveError(
                f"truncated: a {count}-entry directory needs "
                f"{DIR_OFFSET + count * DIR_ENTRY_SIZE} bytes, data is {len(data)}"
            )

        self._data = data
        self.comment = data[:COMMENT_SIZE].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        self.count = count
        self.size = struct.unpack_from("<I", data, SIZE_OFFSET)[0]
        self.size2 = struct.unpack_from("<I", data, SIZE2_OFFSET)[0]

        self.entries: list[U9FlxDirEntry] = []
        for index in range(self.count):
            pos = DIR_OFFSET + index * DIR_ENTRY_SIZE
            if pos + DIR_ENTRY_SIZE > len(data):
                break
            offset, length = struct.unpack_from("<II", data, pos)
            self.entries.append(U9FlxDirEntry(index=index, offset=offset, length=length))

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9FlxArchive:
        with open(filepath, "rb") as f:
            return cls(f.read())

    @property
    def num_entries(self) -> int:
        return len(self.entries)

    def get_entry(self, index: int) -> U9FlxDirEntry | None:
        if index < 0 or index >= len(self.entries):
            return None
        return self.entries[index]

    def read_entry(self, index: int) -> bytes:
        """Return raw bytes for one entry; ``b""`` if that slot is unused."""
        entry = self.get_entry(index)
        if entry is None:
            raise U9FlxArchiveError(f"entry index {index} out of range (0..{len(self.entries) - 1})")
        if not entry.is_used:
            return b""
        if entry.offset + entry.length > len(self._data):
            return b""
        return self._data[entry.offset : entry.offset + entry.length]

    def used_entry_indices(self) -> list[int]:
        return [e.index for e in self.entries if e.is_used]
