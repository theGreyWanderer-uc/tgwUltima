"""
``static/text.flx`` and ``static/misctext.flx`` reader for Ultima 9: Ascension.

Both archives hold the game's writing, and both use the same trivial record:
one **NUL-terminated UTF-16LE string** per FLX entry, nothing else. Every used
entry in both files decodes cleanly -- 7,656 of 7,656 and 340 of 340 -- with an
even byte length and a single trailing NUL.

======================  ========  ==========================================
archive                 entries   content
======================  ========  ==========================================
``static/text.flx``        7,656   conversation text, grouped by source file
``static/misctext.flx``      340   short interface and interaction strings
======================  ========  ==========================================

``misctext.flx`` is a flat list: ``The gate is locked.``, ``Use key on?``.

``text.flx`` carries structure on top of the flat list. 266 of its entries are
**file markers** of the form::

    \\u9\\Source\\Usecode\\ConvoLib\\Ambrosia\\Ambrosia.cpp : BEGIN FILE

A marker opens a block and every entry after it belongs to that block until the
next marker -- there is no matching ``END FILE``, and the first marker is entry
0, so the file is fully partitioned. That leaves 7,390 real lines across 266
blocks, averaging 27.8 lines each and running to 470 for the largest.

The blocks are named after the conversation scripts they came from, and **239
of the 266 basenames match an NPC name in** ``runtime/NPC.FLX`` (90%) --
``Exferlem``, ``Valkadesh``, ``Wislem``, ``LordBritish``. The remainder are
places rather than people: ``Ambrosia``, ``Britain``, ``Minoc``, ``Destard``,
``BuccaneersDen``. So a block is "everything this NPC or location says", and
:meth:`U9TextArchive.block_for` looks one up by name.

The marker paths are the only trace of Origin's source tree left in the shipped
data.

Example::

    from titan.u9.text import U9TextArchive

    text = U9TextArchive.from_file("static/text.flx")
    for line in text.block_for("Raven").lines:
        print(line.text)
"""

from __future__ import annotations

__all__ = ["U9TextArchive", "U9TextBlock", "U9TextEntry", "U9TextError"]

import os
from dataclasses import dataclass, field

ENCODING = "utf-16-le"
MARKER_SUFFIX = " : BEGIN FILE"
_SEPARATOR = "\\"


class U9TextError(Exception):
    """Raised on malformed ``text.flx`` / ``misctext.flx`` data."""


@dataclass(frozen=True)
class U9TextEntry:
    """One string, decoded from one FLX entry."""

    index: int
    text: str

    @property
    def is_file_marker(self) -> bool:
        """True for a ``... : BEGIN FILE`` marker rather than real text."""
        return self.text.endswith(MARKER_SUFFIX)

    @property
    def source_path(self) -> str | None:
        """The marker's source path, or ``None`` on a normal line."""
        if not self.is_file_marker:
            return None
        return self.text[: -len(MARKER_SUFFIX)]

    @property
    def source_file(self) -> str | None:
        """The marker's file name without directories, or ``None``."""
        path = self.source_path
        return path.rsplit(_SEPARATOR, 1)[-1] if path else None


@dataclass(frozen=True)
class U9TextBlock:
    """One source file's lines: a marker and everything up to the next one."""

    source_path: str
    source_file: str
    marker_index: int
    lines: tuple[U9TextEntry, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        """The file name with its extension dropped -- usually an NPC or place."""
        stem = self.source_file
        lowered = stem.lower()
        return stem[:-4] if lowered.endswith(".cpp") else stem

    def __len__(self) -> int:
        return len(self.lines)


def _normalise(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


class U9TextArchive:
    """Reader for one of U9's UTF-16 text archives."""

    def __init__(self, archive) -> None:
        self._archive = archive

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9TextArchive:
        from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as e:
            raise U9TextError(f"not a readable FLX archive: {e}") from e

    @property
    def num_entries(self) -> int:
        return self._archive.num_entries

    def used_indices(self) -> list[int]:
        return self._archive.used_entry_indices()

    def entry(self, index: int) -> U9TextEntry | None:
        """One string by entry index, or ``None`` if that slot is unused."""
        if index < 0 or index >= self.num_entries:
            raise U9TextError(f"index {index} out of range (0..{self.num_entries - 1})")
        blob = self._archive.read_entry(index)
        if not blob:
            return None
        if len(blob) % 2:
            raise U9TextError(
                f"entry {index}: {len(blob)} bytes is odd, so not UTF-16 -- "
                f"not a text archive?"
            )
        try:
            text = blob.decode(ENCODING)
        except UnicodeDecodeError as e:
            raise U9TextError(f"entry {index}: not valid UTF-16LE ({e})") from e
        return U9TextEntry(index=index, text=text.rstrip("\x00"))

    def entries(self) -> list[U9TextEntry]:
        """Every used entry, in index order."""
        out = []
        for index in self.used_indices():
            entry = self.entry(index)
            if entry is not None:
                out.append(entry)
        return out

    def blocks(self) -> list[U9TextBlock]:
        """Group entries by ``BEGIN FILE`` marker.

        Empty for ``misctext.flx``, which carries no markers. Any entries
        before the first marker are not returned -- in ``text.flx`` the first
        marker is entry 0, so nothing is lost.
        """
        out: list[U9TextBlock] = []
        current: list[U9TextEntry] = []
        header: U9TextEntry | None = None
        for entry in self.entries():
            if entry.is_file_marker:
                if header is not None:
                    out.append(self._finish(header, current))
                header, current = entry, []
            elif header is not None:
                current.append(entry)
        if header is not None:
            out.append(self._finish(header, current))
        return out

    @staticmethod
    def _finish(header: U9TextEntry, lines: list[U9TextEntry]) -> U9TextBlock:
        return U9TextBlock(
            source_path=header.source_path or "",
            source_file=header.source_file or "",
            marker_index=header.index,
            lines=tuple(lines),
        )

    def block_for(self, name: str) -> U9TextBlock | None:
        """One block by name, matched loosely -- case and punctuation ignored.

        ``block_for("Raven")``, ``block_for("raven")`` and
        ``block_for("Raven.cpp")`` all find the same block.
        """
        wanted = _normalise(name.removesuffix(".cpp").removesuffix(".CPP"))
        for block in self.blocks():
            if _normalise(block.name) == wanted:
                return block
        return None

    def search(self, needle: str, *, ignore_case: bool = True) -> list[U9TextEntry]:
        """Every entry whose text contains ``needle``, markers excluded."""
        probe = needle.lower() if ignore_case else needle
        out = []
        for entry in self.entries():
            if entry.is_file_marker:
                continue
            hay = entry.text.lower() if ignore_case else entry.text
            if probe in hay:
                out.append(entry)
        return out

    def __len__(self) -> int:
        return len(self.used_indices())

    def __iter__(self):
        return iter(self.entries())
