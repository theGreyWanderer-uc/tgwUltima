"""Tests for the LEV.ARK smoke check behind ``titan uw2 map-verify``.

The check reports rather than raises, so one malformed slot cannot hide the
rest of the archive. Every fixture here is a synthetic uncompressed ARK built
from the documented header layout; no game files are required.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from titan.uw2.map_pipeline import (
    ARK_BLOCK_COUNT,
    AUTOMAP_BLOCK_SIZE,
    MARKER_OFFSET,
    TEXTURE_MAPPING_BLOCK_SIZE,
    verify_maps,
)
from titan.uw2.level import LEVEL_BLOCK_MIN_SIZE


def _build_ark(
    *,
    block_count: int = ARK_BLOCK_COUNT,
    level_size: int = LEVEL_BLOCK_MIN_SIZE,
    texture_size: int = TEXTURE_MAPPING_BLOCK_SIZE,
    automap_size: int | None = AUTOMAP_BLOCK_SIZE,
    marker: int = 0x7577,
) -> bytes:
    """One populated slot 0 in an otherwise empty uncompressed archive."""
    offsets = [0] * block_count
    flags = [0] * block_count
    sizes = [0] * block_count
    available = [0] * block_count
    payload = bytearray()
    data_base = 6 + block_count * 4 * 4

    def add(index: int, body: bytes) -> None:
        if index >= block_count:
            return  # a truncated table simply has no such block
        offsets[index] = data_base + len(payload)
        sizes[index] = len(body)
        available[index] = len(body)
        payload.extend(body)

    level_block = bytearray(level_size)
    if level_size >= MARKER_OFFSET + 2:
        struct.pack_into("<H", level_block, MARKER_OFFSET, marker)
    add(0, bytes(level_block))
    add(80, bytes(texture_size))
    if automap_size is not None:
        add(160, bytes(automap_size))

    header = bytearray(struct.pack("<H", block_count) + b"\x00" * 4)
    for table in (offsets, flags, sizes, available):
        header.extend(struct.pack(f"<{block_count}I", *table))
    return bytes(header) + bytes(payload)


class UW2MapVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "DATA"
        self.data.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _verify(self, **kwargs) -> dict:
        (self.data / "LEV.ARK").write_bytes(_build_ark(**kwargs))
        return verify_maps(self.data)

    def test_accepts_a_well_formed_archive(self) -> None:
        report = self._verify()

        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["populated_level_slots"], [0])
        self.assertEqual(report["block_count"], ARK_BLOCK_COUNT)
        self.assertEqual(report["available_blocks"], 3)

    def test_reports_the_0x7c06_marker_histogram(self) -> None:
        report = self._verify(marker=0x7577)

        self.assertEqual(report["level_markers"], {"0x7577": 1})

    def test_flags_an_unexpected_block_count(self) -> None:
        report = self._verify(block_count=12)

        self.assertFalse(report["ok"])
        self.assertIn("expected 320 blocks, found 12", report["errors"])

    def test_a_truncated_table_reports_rather_than_raising(self) -> None:
        # Slot 0's texture mapping lives at block 80, past a 12-entry table.
        report = self._verify(block_count=12)

        self.assertEqual(report["populated_level_slots"], [0])
        self.assertTrue(
            any(
                "texture mapping block 80 is unavailable" in error
                for error in report["errors"]
            ),
            report["errors"],
        )

    def test_flags_a_short_map_block(self) -> None:
        report = self._verify(level_size=LEVEL_BLOCK_MIN_SIZE - 8)

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("map size" in error for error in report["errors"]), report["errors"]
        )

    def test_flags_a_short_texture_mapping_block(self) -> None:
        report = self._verify(texture_size=TEXTURE_MAPPING_BLOCK_SIZE - 2)

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("texture size" in error for error in report["errors"]), report["errors"]
        )

    def test_flags_a_short_automap_block(self) -> None:
        report = self._verify(automap_size=AUTOMAP_BLOCK_SIZE // 2)

        self.assertFalse(report["ok"])
        self.assertTrue(
            any("automap size" in error for error in report["errors"]), report["errors"]
        )

    def test_a_missing_automap_block_is_not_an_error(self) -> None:
        report = self._verify(automap_size=None)

        self.assertTrue(report["ok"], report["errors"])

    def test_collects_every_failure_instead_of_stopping_at_the_first(self) -> None:
        report = self._verify(
            block_count=12,
            texture_size=TEXTURE_MAPPING_BLOCK_SIZE - 2,
        )

        self.assertFalse(report["ok"])
        self.assertGreaterEqual(len(report["errors"]), 2)


if __name__ == "__main__":
    unittest.main()
