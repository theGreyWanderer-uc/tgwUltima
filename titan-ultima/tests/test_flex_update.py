"""Regression tests for header-preserving generic ``flex-update``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.cli import cmd_flex_update
from titan.flex import FlexArchive
from titan.u7.flex import U7_FLEX_EXULT_MAGIC2, U7FlexArchive
from titan.u7.palette import U7Palette


class FlexUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.replacement = self.root / "replacement.bin"
        self.replacement.write_bytes(bytes([17]) * 768)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_u7_update_preserves_header_dialect_and_palette_slots(self) -> None:
        original = self.root / "PALETTES.FLX"
        updated = self.root / "PALETTES.updated.FLX"
        archive = U7FlexArchive()
        archive.title = "Ultima VII Palettes"
        archive.magic2 = U7_FLEX_EXULT_MAGIC2 + 2
        archive.reserved_header = bytes(range(36))
        archive.records = [bytes([index]) * 768 for index in range(3)] + [b""]
        archive.save(str(original))

        result = cmd_flex_update(
            SimpleNamespace(
                file=str(original),
                index=1,
                data=str(self.replacement),
                output=str(updated),
            )
        )

        self.assertEqual(result, 0)
        self.assertTrue(U7FlexArchive.is_u7_flex(str(updated)))
        reopened = U7FlexArchive.from_file(str(updated))
        self.assertEqual(reopened.title, "Ultima VII Palettes")
        self.assertEqual(reopened.magic2, U7_FLEX_EXULT_MAGIC2 + 2)
        self.assertEqual(reopened.reserved_header, bytes(range(36)))
        self.assertEqual(len(reopened.records), 4)
        self.assertEqual(reopened.records[0], bytes([0]) * 768)
        self.assertEqual(reopened.records[1], self.replacement.read_bytes())
        self.assertEqual(reopened.records[2], bytes([2]) * 768)
        self.assertEqual(reopened.records[3], b"")

        slots = U7Palette.enumerate_slots(str(updated))
        self.assertEqual(len(slots), 4)
        self.assertEqual([slot.index for slot in slots if not slot.is_empty], [0, 1, 2])

    def test_generic_update_preserves_comment_and_unknown_field(self) -> None:
        original = self.root / "generic.flx"
        updated = self.root / "generic.updated.flx"
        archive = FlexArchive()
        archive.comment = "Preserve this Flex comment"
        archive.unknown_field = 7
        archive.records = [b"first", b"second"]
        archive.save(str(original))

        result = cmd_flex_update(
            SimpleNamespace(
                file=str(original),
                index=1,
                data=str(self.replacement),
                output=str(updated),
            )
        )

        self.assertEqual(result, 0)
        reopened = FlexArchive.from_file(str(updated))
        self.assertEqual(reopened.comment, "Preserve this Flex comment")
        self.assertEqual(reopened.unknown_field, 7)
        self.assertEqual(reopened.records, [b"first", self.replacement.read_bytes()])


if __name__ == "__main__":
    unittest.main()
