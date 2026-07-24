"""
Book/sign text reader for Ultima 6 (``BOOK.DAT``).

Not documented in ``u6data/u6tech.txt``. Turns out to need no new parsing
code at all: confirmed directly against Nuvie's ``Book.cpp``
(``Book::init`` opens ``BOOK.DAT`` as ``U6Lib_n`` with ``size=2``) that
this is simply a plain ``lib_16`` file -- exactly what
:class:`titan.u6.lib.U6Library` already reads. This module is a thin,
text-decoding convenience wrapper: :meth:`U6Library.num_items` on a real
``BOOK.DAT`` is 128, and item 0 decodes to "The perpetual motion
machine." (a sign caption, not a full book -- u6edit's help docs call
this whole file "Literature," a mix of long book texts and short sign/
plaque captions).

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.book import U6Books

    books = U6Books.from_file("C:/Ultima/Ultima6/BOOK.DAT")
    print(books.num_books)
    print(books.get_text(0))
"""

from __future__ import annotations

__all__ = ["U6Books"]

import os

from titan.u6.lib import U6Library

BOOK_ENTRY_SIZE = 2  # lib_16


class U6Books:
    """Reader for BOOK.DAT's book/sign texts."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    @property
    def num_books(self) -> int:
        return len(self.texts)

    def get_text(self, num: int) -> str:
        return self.texts[num]

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U6Books:
        lib = U6Library.from_file(filepath, entry_size=BOOK_ENTRY_SIZE)
        texts = [lib.get_item(i).split(b"\x00", 1)[0].decode("latin-1") for i in range(lib.num_items)]
        return cls(texts)
