"""Tests for titan.u6.look's LOOK.LZD object-name decoder.

No real game files are used here -- fixtures are hand-built to match the
documented format (u6data/u6tech.txt: (tile_number: u16, name: cstring)
records) plus the range-covers-the-preceding-gap behaviour and the
trailing-bare-tile-number quirk confirmed against a real LOOK.LZD (see
titan/u6/look.py's module docstring).
"""

from __future__ import annotations

import struct
import unittest

from titan.u6.look import U6LookError, U6ObjectNames


def _make_records(entries: list[tuple[int, str]]) -> bytes:
    out = bytearray()
    for tile_num, name in entries:
        out += struct.pack("<H", tile_num)
        out += name.encode("latin-1") + b"\x00"
    return bytes(out)


class ParseTests(unittest.TestCase):
    def test_parses_simple_records(self):
        data = _make_records([(1, "grass"), (5, "tree")])
        names = U6ObjectNames.parse(data)
        self.assertEqual(len(names.entries), 2)
        self.assertEqual(names.get_name(1), "grass")
        self.assertEqual(names.get_name(5), "tree")

    def test_trailing_bare_tile_number_is_not_an_error(self):
        # Real LOOK.LZD ends with a 2-byte tile number and no name at all.
        data = _make_records([(1, "grass")]) + struct.pack("<H", 2048)
        names = U6ObjectNames.parse(data)
        self.assertEqual(len(names.entries), 1)  # the trailing marker isn't added

    def test_truncated_tile_number_raises(self):
        with self.assertRaises(U6LookError):
            U6ObjectNames.parse(b"\x01")

    def test_unterminated_name_raises(self):
        data = struct.pack("<H", 1) + b"grass"  # no null terminator, more bytes exist
        with self.assertRaises(U6LookError):
            U6ObjectNames.parse(data)


class RangeLookupTests(unittest.TestCase):
    def setUp(self):
        # A run of tiles 0-4 shares "grass" (stored under tile 4, the END
        # of the range); tile 5 has its own name "tree".
        self.names = U6ObjectNames.parse(_make_records([(4, "grass"), (5, "tree")]))

    def test_exact_match(self):
        self.assertEqual(self.names.get_name(4), "grass")
        self.assertEqual(self.names.get_name(5), "tree")

    def test_lookup_within_the_preceding_range_finds_the_range_end(self):
        for tile in range(0, 4):
            self.assertEqual(self.names.get_name(tile), "grass")

    def test_lookup_past_the_last_entry_returns_none(self):
        self.assertIsNone(self.names.get_name(6))

    def test_get_entry_returns_none_for_out_of_range(self):
        self.assertIsNone(self.names.get_entry(100))


class PluralisationTests(unittest.TestCase):
    def test_singular_and_plural_resolution(self):
        # u6tech.txt's own example.
        names = U6ObjectNames.parse(_make_records([(1, "loa/f\\ves of bread")]))
        entry = names.get_entry(1)
        self.assertEqual(entry.singular(), "loaf of bread")
        self.assertEqual(entry.plural(), "loaves of bread")

    def test_name_without_markers_unaffected(self):
        names = U6ObjectNames.parse(_make_records([(1, "grass")]))
        entry = names.get_entry(1)
        self.assertEqual(entry.singular(), "grass")
        self.assertEqual(entry.plural(), "grass")


if __name__ == "__main__":
    unittest.main()
