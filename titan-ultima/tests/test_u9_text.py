"""Tests for titan.u9.text's text.flx / misctext.flx decoder.

Both archives store one NUL-terminated UTF-16LE string per FLX entry. The
properties pinned down here are the ones that shape the reader: a block runs
from its ``BEGIN FILE`` marker to the next marker with no closing marker, and
``misctext.flx`` has no markers at all, so block grouping has to degrade to
an empty list rather than inventing one.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.text import MARKER_SUFFIX, U9TextArchive, U9TextError

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_VERSION_OFFSET = 0x54
FLX_SIZE_OFFSET = 0x58


def _string(text: str) -> bytes:
    return (text + "\x00").encode("utf-16-le")


def _marker(path: str) -> bytes:
    return _string(path + MARKER_SUFFIX)


def _archive(entries: dict[int, bytes], count: int = 12) -> U9FlxArchive:
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


CONVO = "\\u9\\Source\\Usecode\\ConvoLib\\Raven\\Raven.cpp"
CONVO2 = "\\u9\\Source\\Usecode\\ConvoLib\\Britain\\Britain.cpp"


class TextEntryTests(unittest.TestCase):
    def test_decodes_utf16_and_strips_the_terminator(self) -> None:
        text = U9TextArchive(_archive({0: _string("The gate is locked.")}))
        entry = text.entry(0)
        assert entry is not None
        self.assertEqual(entry.text, "The gate is locked.")
        self.assertFalse(entry.is_file_marker)
        self.assertIsNone(entry.source_path)

    def test_non_ascii_survives(self) -> None:
        text = U9TextArchive(_archive({0: _string("café — Brännvin")}))
        entry = text.entry(0)
        assert entry is not None
        self.assertEqual(entry.text, "café — Brännvin")

    def test_marker_is_recognised_and_split(self) -> None:
        text = U9TextArchive(_archive({0: _marker(CONVO)}))
        entry = text.entry(0)
        assert entry is not None
        self.assertTrue(entry.is_file_marker)
        self.assertEqual(entry.source_path, CONVO)
        self.assertEqual(entry.source_file, "Raven.cpp")

    def test_unused_slot_returns_none(self) -> None:
        text = U9TextArchive(_archive({1: _string("hi")}))
        self.assertIsNone(text.entry(0))
        self.assertIsNotNone(text.entry(1))

    def test_out_of_range_raises(self) -> None:
        text = U9TextArchive(_archive({0: _string("hi")}))
        with self.assertRaises(U9TextError):
            text.entry(999)

    def test_odd_length_entry_raises(self) -> None:
        text = U9TextArchive(_archive({0: b"\x41\x00\x42"}))
        with self.assertRaises(U9TextError):
            text.entry(0)


class TextBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = U9TextArchive(_archive({
            0: _marker(CONVO),
            1: _string("Avatar!  Good timing."),
            2: _string("Help me finish them off!"),
            3: _marker(CONVO2),
            4: _string("Welcome to Britain."),
        }))

    def test_block_runs_to_the_next_marker(self) -> None:
        # There is no END FILE marker; the next BEGIN closes the previous block.
        blocks = self.text.blocks()
        self.assertEqual([b.name for b in blocks], ["Raven", "Britain"])
        self.assertEqual([len(b) for b in blocks], [2, 1])

    def test_block_names_drop_the_cpp_extension(self) -> None:
        self.assertEqual(self.text.blocks()[0].source_file, "Raven.cpp")
        self.assertEqual(self.text.blocks()[0].name, "Raven")

    def test_markers_are_not_counted_as_lines(self) -> None:
        blocks = self.text.blocks()
        self.assertTrue(all(not line.is_file_marker for b in blocks for line in b.lines))
        self.assertEqual(sum(len(b) for b in blocks) + len(blocks), len(self.text))

    def test_block_lookup_ignores_case_and_extension(self) -> None:
        for probe in ("Raven", "raven", "RAVEN", "Raven.cpp", "raven.CPP"):
            block = self.text.block_for(probe)
            self.assertIsNotNone(block, probe)
            self.assertEqual(block.name, "Raven")
        self.assertIsNone(self.text.block_for("Nobody"))

    def test_archive_without_markers_has_no_blocks(self) -> None:
        # misctext.flx is a flat list; grouping must not invent a block.
        flat = U9TextArchive(_archive({0: _string("The door is locked."), 1: _string("Use key on?")}))
        self.assertEqual(flat.blocks(), [])
        self.assertEqual(len(flat.entries()), 2)

    def test_lines_before_the_first_marker_are_not_attributed(self) -> None:
        stray = U9TextArchive(_archive({
            0: _string("orphan line"),
            1: _marker(CONVO),
            2: _string("owned line"),
        }))
        blocks = stray.blocks()
        self.assertEqual(len(blocks), 1)
        self.assertEqual([line.text for line in blocks[0].lines], ["owned line"])


class TextSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = U9TextArchive(_archive({
            0: _marker(CONVO),
            1: _string("Defeat the Guardian."),
            2: _string("the guardian waits"),
            3: _string("nothing here"),
        }))

    def test_search_is_case_insensitive_by_default(self) -> None:
        self.assertEqual([e.index for e in self.text.search("guardian")], [1, 2])

    def test_case_sensitive_search(self) -> None:
        hits = self.text.search("Guardian", ignore_case=False)
        self.assertEqual([e.index for e in hits], [1])

    def test_search_skips_markers(self) -> None:
        self.assertEqual(self.text.search("ConvoLib"), [])


if __name__ == "__main__":
    unittest.main()
