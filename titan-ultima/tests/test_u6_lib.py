"""Tests for titan.u6.lib's lib_16/lib_32 collection-file reader.

No real game files are used here -- fixtures are hand-built to match the
documented byte layout (u6data/u6tech.txt "Libraries", cross-checked
against Nuvie's U6Lib_n.cpp). The CONVERSE.A-shaped fixture in
particular exercises the one detail u6tech.txt's prose alone doesn't
cover: the offset-table length must be inferred by scanning for the
smallest "offset // entry_size" bound among all *nonzero* offsets, not
just the first entry, because CONVERSE.A's first two offsets are
documented null pointers.
"""

from __future__ import annotations

import unittest

from titan.u6.lib import U6Library, U6LibraryError
from titan.u6.lzw import U6Lzw

CLEAR_CODE = 0x100
END_CODE = 0x101
CODE_SIZE = 9


def _pack_codes(codes: list[int], code_size: int = CODE_SIZE) -> bytes:
    bitbuf = 0
    bitcount = 0
    out = bytearray()
    for code in codes:
        bitbuf |= (code & ((1 << code_size) - 1)) << bitcount
        bitcount += code_size
        while bitcount >= 8:
            out.append(bitbuf & 0xFF)
            bitbuf >>= 8
            bitcount -= 8
    if bitcount:
        out.append(bitbuf & 0xFF)
    return bytes(out)


def _lzw_encode(data: bytes) -> bytes:
    """Trivial always-valid U6 LZW encoder (see test_u6_lzw for rationale)."""
    codes = [CLEAR_CODE, *data, END_CODE]
    return len(data).to_bytes(4, "little") + _pack_codes(codes)


def _entry(offset: int, flag: int = 0) -> bytes:
    return ((offset & 0xFFFFFF) | (flag << 24)).to_bytes(4, "little")


class Lib32ConverseShapedTests(unittest.TestCase):
    """4-entry lib_32 with two leading null offsets, like CONVERSE.A."""

    def setUp(self):
        item2_data = b"HELLO"
        item3_data = _lzw_encode(b"WORLD!")

        table = _entry(0) + _entry(0) + _entry(16) + _entry(16 + len(item2_data), flag=0x01)
        self.buf = table + item2_data + item3_data

    def test_infers_four_items_despite_leading_nulls(self):
        lib = U6Library(self.buf, entry_size=4)
        self.assertEqual(lib.num_items, 4)

    def test_null_leading_items_are_empty(self):
        lib = U6Library(self.buf, entry_size=4)
        self.assertEqual(lib.get_item(0), b"")
        self.assertEqual(lib.get_item(1), b"")

    def test_uncompressed_item_returned_raw(self):
        lib = U6Library(self.buf, entry_size=4)
        self.assertFalse(lib.is_compressed(2))
        self.assertEqual(lib.get_item(2), b"HELLO")

    def test_compressed_item_is_transparently_decompressed(self):
        lib = U6Library(self.buf, entry_size=4)
        self.assertTrue(lib.is_compressed(3))
        self.assertEqual(lib.get_item(3), b"WORLD!")


class Lib32DeferredFlagTests(unittest.TestCase):
    """0xff flag defers compression status to the next explicitly-flagged item."""

    def test_deferred_item_inherits_next_items_compression(self):
        item0_data = _lzw_encode(b"AB")
        item1_data = _lzw_encode(b"CD")
        table = _entry(8, flag=0xFF) + _entry(8 + len(item0_data), flag=0x01)
        buf = table + item0_data + item1_data

        lib = U6Library(buf, entry_size=4)
        self.assertTrue(lib.is_compressed(0))
        self.assertEqual(lib.get_item(0), b"AB")
        self.assertEqual(lib.get_item(1), b"CD")


class Lib16Tests(unittest.TestCase):
    """16-bit-offset libraries have no flag byte and are always uncompressed."""

    def setUp(self):
        parts = [b"AA", b"BBB", b"CCCC"]
        offsets = []
        pos = 2 * len(parts)  # table size
        for part in parts:
            offsets.append(pos)
            pos += len(part)
        table = b"".join(o.to_bytes(2, "little") for o in offsets)
        self.buf = table + b"".join(parts)
        self.parts = parts

    def test_item_count_and_sizes(self):
        lib = U6Library(self.buf, entry_size=2)
        self.assertEqual(lib.num_items, 3)
        for i, part in enumerate(self.parts):
            self.assertFalse(lib.is_compressed(i))
            self.assertEqual(lib.get_item(i), part)


class ErrorHandlingTests(unittest.TestCase):
    def test_invalid_entry_size_rejected(self):
        with self.assertRaises(U6LibraryError):
            U6Library(b"\x00" * 16, entry_size=3)

    def test_out_of_range_item_raises(self):
        table = _entry(4)
        lib = U6Library(table + b"X", entry_size=4)
        with self.assertRaises(U6LibraryError):
            lib.get_item(5)


if __name__ == "__main__":
    unittest.main()
