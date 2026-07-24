"""Tests for titan.u6.book's BOOK.DAT reader.

No real game files are used here -- the fixture is a hand-built lib_16
buffer (BOOK.DAT's actual format, confirmed directly against Nuvie's
Book.cpp: ``U6Lib_n`` opened with ``size=2``). titan.u6.lib.U6Library
already has thorough lib_16/lib_32 coverage of its own; these tests only
cover this module's own text-decoding convenience layer.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from titan.u6.book import U6Books


def _make_book_dat(texts: list[str]) -> bytes:
    table_size = len(texts) * 2
    body = bytearray()
    offsets = []
    for text in texts:
        offsets.append(table_size + len(body))
        body += text.encode("latin-1") + b"\x00"
    table = b"".join(o.to_bytes(2, "little") for o in offsets)
    return table + bytes(body)


class BooksTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write(self, texts: list[str]) -> str:
        path = os.path.join(self.tmpdir.name, "BOOK.DAT")
        with open(path, "wb") as f:
            f.write(_make_book_dat(texts))
        return path

    def test_from_file_reads_all_books_and_strips_null_terminator(self):
        path = self._write(["The perpetual motion machine.", "A monolith.", ""])
        books = U6Books.from_file(path)
        self.assertEqual(books.num_books, 3)
        self.assertEqual(books.get_text(0), "The perpetual motion machine.")
        self.assertEqual(books.get_text(1), "A monolith.")
        self.assertEqual(books.get_text(2), "")

    def test_multiline_text_preserved(self):
        path = self._write(["Left: The mystery fountain.\n\nRight: The energy field."])
        books = U6Books.from_file(path)
        self.assertEqual(books.get_text(0), "Left: The mystery fountain.\n\nRight: The energy field.")


if __name__ == "__main__":
    unittest.main()
