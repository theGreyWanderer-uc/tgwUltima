"""Tests for creating a new empty Ultima 7 Flex archive."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u7.cli import cmd_u7_flex_create
from titan.u7.flex import U7_FLEX_HEADER_LEN, U7FlexArchive


class U7FlexCreateCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.output_path = self.root / "U7O.VGA"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _create(self, *, force: bool = False) -> int:
        return cmd_u7_flex_create(
            SimpleNamespace(
                output=str(self.output_path),
                title="U7O dynamic shapes",
                force=force,
            )
        )

    def test_creates_valid_empty_u7_flex_archive(self) -> None:
        self.assertEqual(self._create(), 0)

        archive = U7FlexArchive.from_file(str(self.output_path))
        self.assertEqual(archive.title, "U7O dynamic shapes")
        self.assertEqual(archive.records, [])
        self.assertEqual(self.output_path.stat().st_size, U7_FLEX_HEADER_LEN)

    def test_refuses_to_overwrite_without_force(self) -> None:
        original = b"existing file"
        self.output_path.write_bytes(original)

        self.assertEqual(self._create(), 1)
        self.assertEqual(self.output_path.read_bytes(), original)

    def test_force_replaces_existing_file(self) -> None:
        self.output_path.write_bytes(b"existing file")

        self.assertEqual(self._create(force=True), 0)
        self.assertTrue(U7FlexArchive.is_u7_flex(str(self.output_path)))


if __name__ == "__main__":
    unittest.main()
