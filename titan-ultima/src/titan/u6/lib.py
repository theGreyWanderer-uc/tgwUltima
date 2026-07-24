"""
lib_16 / lib_32 collection-file reader for Ultima 6.

Several U6 data files (CONVERSE.A/B, PORTRAIT.A/B/Z, and others) are
"libraries": an offset table followed by a set of variable-length
records. Two offset widths exist -- 16-bit ("lib_16") and 32-bit
("lib_32"). The Worlds of Ultima titles (Martian Dreams, Savage Empire)
additionally prefix the whole file with a 4-byte total-size field
("s_lib_16"/"s_lib_32") that plain Ultima 6: The False Prophet does not
have; that variant is supported here (``has_size_header=True``) but is
not yet validated against real MD/SE data, since our own game files are
False Prophet.

The offset table's length isn't stored explicitly. Nuvie's
``U6Lib_n::calculate_num_offsets`` works it out by scanning forward
through candidate offset slots and, for every *nonzero* offset seen,
treating ``offset // entry_size`` as an upper bound on the table length
(a valid offset must point past the end of the table) -- taking the
running minimum across all such bounds. This is more than the simple
"read the first offset" recipe in ``u6tech.txt`` implies: CONVERSE.A's
first two offsets are documented null pointers, and the running-minimum
scan is what correctly skips over them instead of concluding a
zero-entry table.

For 32-bit offsets, the top byte is a per-item compression flag rather
than part of the offset (real U6 offsets never need 24 bits). Flag 0x01
or 0x20 means the item is LZW-compressed (see :mod:`titan.u6.lzw`); flag
0xff means "same as the next item with an explicit flag" (a run of
0xff-flagged items defers to whichever real item follows). 16-bit-offset
libraries have no room for a flag byte and are always treated as
uncompressed.

CONVERSE.A/B is a documented exception to the flag mechanism: verified
directly against a real CONVERSE.A, its entries carry flag 0x00
("uncompressed") yet are themselves complete, self-describing LZW
streams -- decompressing item 2's raw bytes despite its flag yields
readable dialogue text. Nuvie's own source even carries a comment
acknowledging this ("U6 converse files dont have flag?"). Rather than
special-case CONVERSE.A/B by name, :meth:`get_item` treats *any* item
whose raw bytes independently pass :meth:`U6Lzw.is_valid` as compressed,
regardless of what its flag says -- the flag becomes a secondary signal
rather than the sole authority.

Ported from the algorithm in Nuvie's ``files/U6Lib_n.cpp``, cross-checked
against ``u6data/u6tech.txt``'s "Libraries" section. Read for byte-layout
reference only -- this is a fresh implementation, not a translation of
GPL source.

Example::

    from titan.u6.lib import U6Library

    lib = U6Library.from_file("CONVERSE.A", entry_size=4)
    print(lib.num_items)
    script = lib.get_item(5)  # decompressed automatically if flagged
"""

from __future__ import annotations

__all__ = ["U6Library", "U6LibraryError", "U6LibraryItem"]

import os
from dataclasses import dataclass

from titan.u6.lzw import U6Lzw

HEADER_SIZE = 4
FLAG_COMPRESSED = 0x01
FLAG_COMPRESSED_MD_FONTS = 0x20
FLAG_DEFER_TO_NEXT = 0xFF


class U6LibraryError(Exception):
    """Raised on malformed library data or an out-of-range item index."""


@dataclass
class U6LibraryItem:
    """One entry in a U6 library's offset table."""

    index: int
    offset: int
    flag: int
    size: int  # raw (possibly-compressed) on-disk size; 0 if the slot is empty


class U6Library:
    """Reader for U6 lib_16 / lib_32 collection files."""

    def __init__(
        self,
        data: bytes,
        entry_size: int = 4,
        has_size_header: bool = False,
    ) -> None:
        if entry_size not in (2, 4):
            raise U6LibraryError(f"entry_size must be 2 or 4, got {entry_size}")
        self._data = data
        self.entry_size = entry_size
        self.has_size_header = has_size_header
        self.items: list[U6LibraryItem] = []
        self._parse()

    @classmethod
    def from_file(
        cls,
        filepath: str | os.PathLike[str],
        entry_size: int = 4,
        has_size_header: bool = False,
    ) -> U6Library:
        """Load a library file. ``entry_size`` is 2 for lib_16, 4 for lib_32."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls(data, entry_size=entry_size, has_size_header=has_size_header)

    @property
    def num_items(self) -> int:
        return len(self.items)

    def _read_entry(self, pos: int) -> int:
        return int.from_bytes(self._data[pos:pos + self.entry_size], "little")

    def _count_offsets(self, table_start: int) -> int:
        """Scan the offset table until candidate length bounds converge (see module docstring)."""
        max_count: int | None = None
        pos = table_start
        i = 0
        while pos + self.entry_size <= len(self._data):
            if max_count is not None and i == max_count:
                return i
            raw = self._read_entry(pos)
            pos += self.entry_size
            offset = (raw & 0xFFFFFF) if self.entry_size == 4 else raw
            if offset:
                table_relative = offset - table_start
                candidate = table_relative // self.entry_size
                if max_count is None or candidate < max_count:
                    max_count = candidate
            i += 1
        return max_count if max_count is not None else 0

    def _parse(self) -> None:
        table_start = HEADER_SIZE if self.has_size_header else 0
        filesize = (
            int.from_bytes(self._data[0:4], "little")
            if self.has_size_header
            else len(self._data)
        )

        num_offsets = self._count_offsets(table_start)

        raw_offsets: list[int] = []
        flags: list[int] = []
        pos = table_start
        for _ in range(num_offsets):
            raw = self._read_entry(pos)
            pos += self.entry_size
            if self.entry_size == 4:
                flags.append((raw >> 24) & 0xFF)
                raw_offsets.append(raw & 0xFFFFFF)
            else:
                flags.append(0)
                raw_offsets.append(raw)

        # Sentinel: end-of-file terminates the last real item's size.
        bounds = raw_offsets + [filesize]

        self.items = []
        for i in range(num_offsets):
            offset = raw_offsets[i]
            next_offset = 0
            for later in bounds[i + 1:]:
                if later:
                    next_offset = later
                    break
            size = (next_offset - offset) if (offset and next_offset > offset) else 0
            self.items.append(U6LibraryItem(index=i, offset=offset, flag=flags[i], size=size))

    def is_compressed(self, item_number: int) -> bool:
        """
        Whether ``item_number``'s flag byte marks it as LZW-compressed.

        This is the flag-based signal only -- see :meth:`get_item`, which
        also treats an item as compressed whenever its raw bytes are
        independently a valid LZW stream, since CONVERSE.A/B entries are
        compressed without setting this flag.
        """
        item = self.items[item_number]
        if self.entry_size != 4:
            return False
        if item.flag in (FLAG_COMPRESSED, FLAG_COMPRESSED_MD_FONTS):
            return True
        if item.flag == FLAG_DEFER_TO_NEXT:
            for later in self.items[item_number + 1:]:
                if later.flag != FLAG_DEFER_TO_NEXT:
                    return self.is_compressed(later.index)
        return False

    def get_item(self, item_number: int) -> bytes:
        """Return the bytes for one item, transparently LZW-decompressed if needed."""
        if item_number < 0 or item_number >= len(self.items):
            raise U6LibraryError(f"item index {item_number} out of range (0..{len(self.items) - 1})")
        item = self.items[item_number]
        if item.size == 0 or item.offset == 0:
            return b""
        raw = self._data[item.offset:item.offset + item.size]
        if self.is_compressed(item_number) or U6Lzw.is_valid(raw):
            return U6Lzw.decompress_buffer(raw)
        return raw
