"""
Object-name decoder for Ultima 6 (``LOOK.LZD``).

Documented in ``u6data/u6tech.txt`` (unlike most other formats this
project has covered): LZW-compressed, a sequence of
``(tile_number: u16, name: null-terminated string)`` records, sorted by
ascending tile number. Confirmed directly against a real ``LOOK.LZD``
(genuinely LZW-compressed, unlike the false claim about ``TILEINDX.VGA``
elsewhere in this project's history) -- the first several records decode
to exactly the expected low-tile-number ground names ("grass", "swamp",
"shrub", "bush", "water", "shore", "tree", ...).

u6tech.txt notes a non-obvious detail, confirmed by pu6e's ``look.py``
doing the same thing: a run of consecutive tile numbers that share one
name is stored as a *single* record, tagged with the tile at the *end*
of the range -- not the start. Looking up a name for a tile therefore
means searching forward for the nearest tile number that has an entry,
not an exact-match dictionary lookup. :meth:`U6ObjectNames.get_name`
does this.

Names may contain the escape markers u6tech.txt documents for
pluralisation: ``/`` marks a singular-only word ending, ``\\`` marks a
plural-only word ending (e.g. ``"loa/f\\ves of bread"`` -> "loaf of
bread" singular, "loaves of bread" plural). :meth:`singular`/:meth:`plural`
resolve these the same way pu6e's ``Obj.name()`` does.

A real ``LOOK.LZD`` ends with a bare, name-less tile number right after
the tile-0x800 sentinel pu6e's own comments flag ("there's an object
(sentinel?) at 0x800"). :meth:`U6ObjectNames.parse` treats this trailing
tile-with-no-name as a harmless end marker rather than an error.

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.look import U6ObjectNames

    names = U6ObjectNames.from_file("C:/Ultima/Ultima6/LOOK.LZD")
    print(names.get_name(1))              # "grass"
    print(names.get_entry(51).singular()) # tree-like name, singular form
"""

from __future__ import annotations

__all__ = ["U6ObjectNames", "U6LookEntry", "U6LookError"]

import bisect
import os
import re
import struct
from dataclasses import dataclass

from titan.u6.lzw import U6Lzw

_PLURAL_SUFFIX_RE = re.compile(r"\\[A-Za-z]*")
_SINGULAR_SUFFIX_RE = re.compile(r"/[A-Za-z]*")


class U6LookError(Exception):
    """Raised on malformed LOOK.LZD data."""


@dataclass
class U6LookEntry:
    tile_num: int  # the LAST tile number this name applies to (see module docstring)
    name: str

    def singular(self) -> str:
        """Resolve escape markers for the singular form."""
        return _PLURAL_SUFFIX_RE.sub("", self.name).replace("/", "")

    def plural(self) -> str:
        """Resolve escape markers for the plural form."""
        return _SINGULAR_SUFFIX_RE.sub("", self.name).replace("\\", "")


class U6ObjectNames:
    """Reader for LOOK.LZD, with range-aware tile-to-name lookup."""

    def __init__(self, entries: list[U6LookEntry]) -> None:
        self.entries = entries
        self._by_tile = {e.tile_num: e for e in entries}
        self._sorted_tiles = sorted(self._by_tile)

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U6ObjectNames:
        data = U6Lzw.decompress_file(filepath)
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> U6ObjectNames:
        entries: list[U6LookEntry] = []
        pos = 0
        n = len(data)
        while pos < n:
            if pos + 2 > n:
                raise U6LookError(f"truncated tile number at offset {pos}")
            tile_num = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if pos >= n:
                # A real LOOK.LZD ends with a bare tile number and no name
                # at all (confirmed: right after the documented tile-0x800
                # sentinel, real data has one trailing u16 with zero bytes
                # following it). Harmless trailing marker, not a real entry.
                break
            end = data.find(0, pos)
            if end == -1:
                raise U6LookError(f"unterminated name at offset {pos}")
            name = data[pos:end].decode("latin-1")
            entries.append(U6LookEntry(tile_num, name))
            pos = end + 1
        return cls(entries)

    def get_entry(self, tile_num: int) -> U6LookEntry | None:
        """Return the entry covering ``tile_num`` (searching forward; see module docstring)."""
        idx = bisect.bisect_left(self._sorted_tiles, tile_num)
        if idx >= len(self._sorted_tiles):
            return None
        return self._by_tile[self._sorted_tiles[idx]]

    def get_name(self, tile_num: int) -> str | None:
        entry = self.get_entry(tile_num)
        return entry.name if entry else None
