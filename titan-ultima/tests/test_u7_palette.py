"""Tests for titan.u7.palette: slot enumeration, empty vs invalid records,
raw byte round-tripping, and encoding detection/override.

No real game files required -- fixtures are synthetic archives shaped
like the real Black Gate/Serpent Isle PALETTES.FLX occupancy patterns
found during manual analysis of the actual game data.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from titan.u7.palette import PaletteRecordEmptyError, PaletteRecordInvalidError, U7Palette

from tests._fixtures import (
    make_6bit_palette_bytes,
    make_8bit_palette_bytes,
    make_bg_shaped_archive,
    make_overlapping_archive_bytes,
    make_si_shaped_archive,
    make_truncated_archive_bytes,
)


class _TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class SlotEnumerationTests(_TempDirCase):
    def test_bg_shaped_archive_has_expected_occupancy(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        slots = U7Palette.enumerate_slots(path)
        self.assertEqual(len(slots), 16)
        populated = [s.index for s in slots if not s.is_empty]
        self.assertEqual(populated, [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12])
        self.assertTrue(all(s.is_valid for s in slots))

    def test_si_shaped_archive_has_expected_occupancy(self):
        path = make_si_shaped_archive(os.path.join(self.tmpdir, "si.flx"))
        slots = U7Palette.enumerate_slots(path)
        populated = [s.index for s in slots if not s.is_empty]
        self.assertEqual(populated, list(range(13)))

    def test_slot_numbering_never_compacted(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        slots = U7Palette.enumerate_slots(path)
        for i, slot in enumerate(slots):
            self.assertEqual(slot.index, i)

    def test_loaded_slot_content_matches_its_own_index_not_a_compacted_position(self):
        # Slot 10 is the 10th POPULATED slot's real index -- if slots were
        # ever compacted, loading index 10 would silently return the
        # content that was seeded for the 10th populated *position*
        # (which is actually index 11) instead of index 10's own bytes.
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        pal = U7Palette.from_file(path, palette_index=10)
        self.assertEqual(pal.to_raw_bytes(), make_6bit_palette_bytes(seed=10))


class EmptyVsInvalidTests(_TempDirCase):
    def test_empty_slot_raises_empty_error(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        with self.assertRaises(PaletteRecordEmptyError):
            U7Palette.from_file(path, palette_index=9)  # empty in the BG-shaped fixture

    def test_out_of_range_index_raises_invalid_error(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        with self.assertRaises(PaletteRecordInvalidError):
            U7Palette.from_file(path, palette_index=999)

    def test_truncated_record_is_invalid_not_empty(self):
        data = make_truncated_archive_bytes(make_6bit_palette_bytes())
        path = os.path.join(self.tmpdir, "trunc.flx")
        with open(path, "wb") as f:
            f.write(data)

        slots = U7Palette.enumerate_slots(path)
        self.assertEqual(len(slots), 1)
        self.assertFalse(slots[0].is_empty)
        self.assertFalse(slots[0].is_valid)
        self.assertIn("truncated", slots[0].error)

        with self.assertRaises(PaletteRecordInvalidError):
            U7Palette.from_file(path, palette_index=0)

    def test_overlapping_records_are_detected(self):
        data = make_overlapping_archive_bytes(make_6bit_palette_bytes())
        path = os.path.join(self.tmpdir, "overlap.flx")
        with open(path, "wb") as f:
            f.write(data)

        slots = U7Palette.enumerate_slots(path)
        self.assertEqual(len(slots), 2)
        self.assertTrue(slots[0].is_valid)
        self.assertFalse(slots[1].is_valid)
        self.assertIn("overlaps", slots[1].error)

    def test_table_itself_truncated_raises_immediately(self):
        # File too small to even hold the declared record table.
        header = bytearray(128)
        header[0x50:0x54] = b"\x00\x1a\xff\xff"
        import struct
        struct.pack_into("<I", header, 0x54, 5)  # declares 5 slots
        path = os.path.join(self.tmpdir, "short.flx")
        with open(path, "wb") as f:
            f.write(bytes(header))  # no record table data at all follows

        with self.assertRaises(PaletteRecordInvalidError):
            U7Palette.enumerate_slots(path)


class RoundTripTests(_TempDirCase):
    def test_raw_bytes_round_trip_byte_for_byte(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        pal = U7Palette.from_file(path, palette_index=0)
        self.assertEqual(pal.to_raw_bytes(), make_6bit_palette_bytes(seed=0))

    def test_index_255_bytes_preserved_not_reinterpreted(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        pal = U7Palette.from_file(path, palette_index=0)
        raw = pal.to_raw_bytes()
        self.assertEqual((raw[255 * 3], raw[255 * 3 + 1], raw[255 * 3 + 2]), (250, 64, 1))

    def test_flex_index_and_source_recorded(self):
        path = make_bg_shaped_archive(os.path.join(self.tmpdir, "bg.flx"))
        pal = U7Palette.from_file(path, palette_index=3)
        self.assertEqual(pal.flex_index, 3)
        self.assertEqual(pal.source, path)


class EncodingTests(unittest.TestCase):
    def test_auto_detects_6bit(self):
        pal = U7Palette.from_raw_bytes(make_6bit_palette_bytes())
        self.assertEqual(pal.encoding, "6bit")

    def test_auto_detects_8bit(self):
        pal = U7Palette.from_raw_bytes(make_8bit_palette_bytes())
        self.assertEqual(pal.encoding, "8bit")

    def test_explicit_override_forces_interpretation(self):
        data = make_6bit_palette_bytes()
        pal = U7Palette.from_raw_bytes(data, encoding="8bit")
        self.assertEqual(pal.encoding, "8bit")
        self.assertEqual(pal.colors[1], (data[3], data[4], data[5]))

    def test_unknown_encoding_rejected(self):
        with self.assertRaises(ValueError):
            U7Palette.from_raw_bytes(make_6bit_palette_bytes(), encoding="4bit")


class DoublePaletteTests(unittest.TestCase):
    def test_deinterleave(self):
        raw = bytes(range(256)) * 6  # 1536 bytes, deterministic pattern
        primary, secondary = U7Palette.from_double_bytes(raw, encoding="8bit")
        self.assertEqual(primary.colors[0], (raw[0], raw[2], raw[4]))
        self.assertEqual(secondary.colors[0], (raw[1], raw[3], raw[5]))

    def test_too_small_raises(self):
        with self.assertRaises(PaletteRecordInvalidError):
            U7Palette.from_double_bytes(bytes(100))


if __name__ == "__main__":
    unittest.main()
