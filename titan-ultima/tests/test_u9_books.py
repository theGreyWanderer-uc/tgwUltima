"""Tests for titan.u9.books' static/BOOKS-EN.FLX decoder.

Fixtures match the layout verified against the shipped archive (460 used
entries of 4,096 slots). The properties pinned down here are the ones that
shape the reader:

* text is single-byte, **not** the UTF-16LE that ``text.flx`` uses;
* the title's leading number is the entry index plus one, so it is a label
  rather than data;
* markup is stripped from ``text`` but a page break still splits ``pages``;
* one shipped entry is an embedded Word document, and the reader has to hand
  it back flagged rather than choking on it or pretending it is prose.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.books import OLE2_MAGIC, U9Book, U9Books, U9BooksError
from titan.u9.flx_archive import U9FlxArchive

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_VERSION_OFFSET = 0x54
FLX_SIZE_OFFSET = 0x58


def _record(title: str, body: str | bytes) -> bytes:
    raw_title = title.encode("latin-1") + b"\x00"
    raw_body = body.encode("latin-1") if isinstance(body, str) else body
    return (
        struct.pack("<I", len(raw_title))
        + raw_title
        + struct.pack("<I", len(raw_body))
        + raw_body
    )


def _archive(entries: dict[int, bytes], count: int = 8) -> U9FlxArchive:
    header = bytearray(FLX_DIR_OFFSET + count * 8)
    payload = b""
    directory = []
    base = len(header)
    for index in range(count):
        blob = entries.get(index, b"")
        if blob:
            directory.append((base + len(payload), len(blob)))
            payload += blob
        else:
            directory.append((0, 0))
    for index, (offset, length) in enumerate(directory):
        struct.pack_into("<II", header, FLX_DIR_OFFSET + index * 8, offset, length)
    struct.pack_into("<I", header, FLX_COUNT_OFFSET, count)
    struct.pack_into("<I", header, FLX_VERSION_OFFSET, 2)
    struct.pack_into("<I", header, FLX_SIZE_OFFSET, len(header) + len(payload))
    return U9FlxArchive(bytes(header) + payload)


class BookRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.books = U9Books(_archive({
            0: _record("1: History of Britannia", "`f2Heading\r\n`f1The tale began."),
            2: _record("3: signtest", "Beware."),
        }))

    def test_title_and_body_decode(self) -> None:
        book = self.books.book(0)
        assert book is not None
        self.assertEqual(book.title, "1: History of Britannia")
        self.assertEqual(book.name, "History of Britannia")
        self.assertEqual(book.book_id, 1)

    def test_title_number_is_the_index_plus_one(self) -> None:
        book = self.books.book(2)
        assert book is not None
        self.assertEqual(book.book_id, 3)
        self.assertEqual(book.index, 2)
        self.assertEqual(book.name, "signtest")

    def test_text_strips_markup_but_raw_text_keeps_it(self) -> None:
        book = self.books.book(0)
        assert book is not None
        self.assertEqual(book.text, "Heading\r\nThe tale began.")
        self.assertIn("`f2", book.raw_text)

    def test_fonts_are_reported_in_order(self) -> None:
        book = self.books.book(0)
        assert book is not None
        self.assertEqual(book.fonts, [2, 1])

    def test_unused_slot_returns_none(self) -> None:
        self.assertIsNone(self.books.book(1))

    def test_out_of_range_raises(self) -> None:
        with self.assertRaises(U9BooksError):
            self.books.book(999)

    def test_single_byte_encoding_not_utf16(self) -> None:
        # text.flx is UTF-16LE; this archive is not, and decoding it that way
        # would silently produce CJK from ordinary prose.
        books = U9Books(_archive({0: _record("1: x", "caf\xe9 \xbd")}))
        book = books.book(0)
        assert book is not None
        self.assertEqual(book.text, "café ½")


class BookMarkupTests(unittest.TestCase):
    def test_page_break_splits_pages(self) -> None:
        books = U9Books(_archive({0: _record("1: b", "one`ptwo`pthree")}))
        book = books.book(0)
        assert book is not None
        self.assertEqual(book.pages, ["one", "two", "three"])

    def test_markup_is_case_insensitive(self) -> None:
        books = U9Books(_archive({0: _record("1: b", "`F2Head`Ptail")}))
        book = books.book(0)
        assert book is not None
        self.assertEqual(book.pages, ["Head", "tail"])
        self.assertEqual(book.fonts, [2])

    def test_leading_page_break_yields_an_empty_first_page(self) -> None:
        # The shipped bestiary opens with a page break; keep the empty page
        # rather than silently renumbering the rest.
        books = U9Books(_archive({0: _record("1: b", "`pbody")}))
        book = books.book(0)
        assert book is not None
        self.assertEqual(book.pages, ["", "body"])

    def test_body_without_markup_is_one_page(self) -> None:
        books = U9Books(_archive({0: _record("1: b", "plain")}))
        book = books.book(0)
        assert book is not None
        self.assertEqual(book.pages, ["plain"])
        self.assertEqual(book.fonts, [])


class BookDefectTests(unittest.TestCase):
    """Entry 160 of the shipped archive is an embedded Word document."""

    def test_embedded_document_is_flagged_not_decoded_as_prose(self) -> None:
        blob = OLE2_MAGIC + b"\x00" * 64
        books = U9Books(_archive({0: _record("1: DestardSecret", blob)}))
        book = books.book(0)
        assert book is not None
        self.assertTrue(book.is_embedded_document)
        self.assertEqual(book.body, blob)

    def test_ordinary_book_is_not_flagged(self) -> None:
        books = U9Books(_archive({0: _record("1: b", "prose")}))
        book = books.book(0)
        assert book is not None
        self.assertFalse(book.is_embedded_document)

    def test_search_skips_embedded_documents(self) -> None:
        blob = OLE2_MAGIC + b"secret prose"
        books = U9Books(_archive({
            0: _record("1: DestardSecret", blob),
            1: _record("2: real", "secret prose"),
        }))
        self.assertEqual([b.index for b in books.search("secret prose")], [1])


class BookValidationTests(unittest.TestCase):
    def test_truncated_length_field_raises(self) -> None:
        books = U9Books(_archive({0: b"\x05\x00"}))
        with self.assertRaises(U9BooksError):
            books.book(0)

    def test_length_overrunning_the_record_raises(self) -> None:
        bad = struct.pack("<I", 999) + b"1: x\x00"
        books = U9Books(_archive({0: bad}))
        with self.assertRaises(U9BooksError):
            books.book(0)

    def test_trailing_bytes_after_the_body_raise(self) -> None:
        books = U9Books(_archive({0: _record("1: x", "body") + b"junk"}))
        with self.assertRaises(U9BooksError):
            books.book(0)


class BookLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.books = U9Books(_archive({
            0: _record("1: History of Britannia", "The Guardian came."),
            1: _record("2: bestiary", "Archers are proficient."),
        }))

    def test_by_name_ignores_case_and_the_number(self) -> None:
        for probe in ("bestiary", "BESTIARY", "2: bestiary"):
            book = self.books.by_name(probe)
            self.assertIsNotNone(book, probe)
            self.assertEqual(book.book_id, 2)
        self.assertIsNone(self.books.by_name("nothing"))

    def test_search_matches_body_and_title(self) -> None:
        self.assertEqual([b.index for b in self.books.search("guardian")], [0])
        self.assertEqual([b.index for b in self.books.search("bestiary")], [1])

    def test_case_sensitive_search(self) -> None:
        self.assertEqual(self.books.search("guardian", ignore_case=False), [])

    def test_len_and_iteration_cover_used_entries(self) -> None:
        self.assertEqual(len(self.books), 2)
        self.assertEqual([b.book_id for b in self.books], [1, 2])


if __name__ == "__main__":
    unittest.main()
