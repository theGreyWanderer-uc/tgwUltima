"""
``static/BOOKS-EN.FLX`` reader for Ultima 9: Ascension.

Every readable object in the game that is not dialogue: books, scrolls, signs,
plaques, banners, gravestones and note-to-self quest strings. 460 of the
archive's 4,096 slots are used. The ``-EN`` names the language, so a localised
install is expected to ship the same archive under another suffix.

Each used FLX entry is one record::

    0x00  title_length  u32   -- includes the NUL
    0x04  title         char[title_length]   -- NUL-terminated
          body_length   u32
          body          char[body_length]

Text is single-byte, not the UTF-16LE that :mod:`titan.u9.text` decodes for
``text.flx`` and ``misctext.flx`` -- the two text systems in this game do not
share an encoding. Line breaks are CRLF.

Titles are numbered: every one of the 460 is shaped ``"<n>: <name>"``, and
``n`` is the entry index plus one on all 460, so the number is a one-based book
id and carries no information the index does not. :attr:`U9Book.name` is the
part after it.

Bodies carry a two-character backtick markup::

    `f1 `f2 `f3 `f5   select a font -- `f1 is body text, `f2 a heading
    `p                page break

The codes are case-insensitive (``\\`F2`` and ``\\`P`` both occur).
:attr:`U9Book.text` strips them; :attr:`U9Book.pages` splits on the page break.

Verified against the shipped archive:

* the record formula accounts for every byte of all 460 entries, with a
  NUL-terminated title in each (460/460);
* the title number equals the entry index plus one (460/460);
* outside one entry, the only markup codes present are ``\\`f`` and ``\\`p``.

That one entry is a genuine defect in the shipped data rather than a format
variant. Entry 160, ``"161: DestardSecret"``, is 19,456 bytes beginning
``D0 CF 11 E0 A1 B1 1A E1`` -- the OLE2 compound-document signature. A
Microsoft Word 8.0 file was imported into the archive in place of its text, and
the draft prose is still legible inside it. :attr:`U9Book.is_embedded_document`
flags it so a consumer can skip it instead of rendering binary; every other
body is 3 to 3,674 bytes of text.

Example::

    from titan.u9.books import U9Books

    books = U9Books.from_file("static/BOOKS-EN.FLX")
    for book in books.books():
        print(book.book_id, book.name)
        print(book.text)
"""

from __future__ import annotations

__all__ = ["U9Book", "U9Books", "U9BooksError"]

import os
import re
import struct

from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

ENCODING = "latin-1"
MARKUP_PREFIX = "`"
FONT_CODE = "f"
PAGE_CODE = "p"
MARKUP_RE = re.compile(r"`[fF][0-9]|`[pP]")
FONT_RE = re.compile(r"`[fF]([0-9])")
PAGE_RE = re.compile(r"`[pP]")
TITLE_RE = re.compile(r"^(\d+):\s*(.*)$", re.DOTALL)
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_LENGTH_SIZE = 4
MAX_FIELD = 1 << 24


class U9BooksError(Exception):
    """Raised on malformed ``BOOKS-EN.FLX`` data."""


@dataclass(frozen=True)
class U9Book:
    """One book, scroll, sign or plaque."""

    index: int
    title: str
    body: bytes

    @property
    def book_id(self) -> int:
        """The number the title carries -- the entry index plus one."""
        match = TITLE_RE.match(self.title)
        return int(match.group(1)) if match else self.index + 1

    @property
    def name(self) -> str:
        """The title with its leading ``"<n>: "`` removed."""
        match = TITLE_RE.match(self.title)
        return match.group(2) if match else self.title

    @property
    def is_embedded_document(self) -> bool:
        """True when the body is an embedded file rather than game text."""
        return self.body.startswith(OLE2_MAGIC)

    @property
    def raw_text(self) -> str:
        """The body decoded, markup left in place."""
        return self.body.decode(ENCODING)

    @property
    def text(self) -> str:
        """The body decoded with markup codes removed."""
        return MARKUP_RE.sub("", self.raw_text)

    @property
    def pages(self) -> list[str]:
        """The text split on page breaks, markup removed."""
        return [MARKUP_RE.sub("", part) for part in PAGE_RE.split(self.raw_text)]

    @property
    def fonts(self) -> list[int]:
        """Font ids selected in the body, in the order they appear."""
        return [int(digit) for digit in FONT_RE.findall(self.raw_text)]

    def __len__(self) -> int:
        return len(self.body)


class U9Books:
    """Reader for ``static/BOOKS-EN.FLX``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self._archive = archive

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Books:
        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as e:
            raise U9BooksError(str(e)) from e

    @property
    def num_entries(self) -> int:
        return self._archive.num_entries

    def used_indices(self) -> list[int]:
        return self._archive.used_entry_indices()

    @staticmethod
    def _field(data: bytes, offset: int, what: str, index: int) -> tuple[bytes, int]:
        if offset + _LENGTH_SIZE > len(data):
            raise U9BooksError(f"entry {index}: truncated before the {what} length")
        (length,) = struct.unpack_from("<I", data, offset)
        if length > MAX_FIELD or offset + _LENGTH_SIZE + length > len(data):
            raise U9BooksError(
                f"entry {index}: {what} length {length} overruns a "
                f"{len(data)}-byte record"
            )
        start = offset + _LENGTH_SIZE
        return data[start : start + length], start + length

    def book(self, index: int) -> U9Book | None:
        """One book by entry index, or ``None`` if the slot is unused."""
        entry = self._archive.get_entry(index)
        if entry is None:
            raise U9BooksError(
                f"entry index {index} out of range (0..{self.num_entries - 1})"
            )
        if not entry.is_used:
            return None

        data = self._archive.read_entry(index)
        raw_title, offset = self._field(data, 0, "title", index)
        body, end = self._field(data, offset, "body", index)
        if end != len(data):
            raise U9BooksError(
                f"entry {index}: {len(data) - end} trailing byte(s) after the body"
            )
        title = raw_title.split(b"\x00", 1)[0].decode(ENCODING)
        return U9Book(index=index, title=title, body=body)

    def books(self) -> list[U9Book]:
        """Every used entry, in index order."""
        out = []
        for index in self.used_indices():
            book = self.book(index)
            if book is not None:
                out.append(book)
        return out

    def by_name(self, name: str) -> U9Book | None:
        """One book by name, ignoring case and the leading number."""
        wanted = name.strip().lower()
        for book in self.books():
            if book.name.lower() == wanted or book.title.lower() == wanted:
                return book
        return None

    def search(self, needle: str, *, ignore_case: bool = True) -> list[U9Book]:
        """Books whose text or title contains ``needle``."""
        probe = needle.lower() if ignore_case else needle
        hits = []
        for book in self.books():
            if book.is_embedded_document:
                continue
            hay = book.text + book.title
            if probe in (hay.lower() if ignore_case else hay):
                hits.append(book)
        return hits

    def __len__(self) -> int:
        return len(self.used_indices())

    def __iter__(self):
        return iter(self.books())
